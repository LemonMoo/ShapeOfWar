"""Progressive territory expansion: claiming UNCLAIMED land instead of
starting the game already owning a fully-formed nation. Every county not
part of a faction's starting foothold begins UNCLAIMED, defended by a
neutral "wildland" garrison (see app/world/worldgen.py's
_seed_wildland_strength) — claiming one requires being adjacent to land you
already hold (no leapfrogging), costs real resources, takes real turns, and
only resolves win/loss against the garrison once the work is done.
"""
import math
import random

from app.world import territory
from app.world import resources
from app.world.worldgen import (UNCLAIMED, _place_settlements_for_faction,
                                _place_villages_for_county)
from app.world.lexicon import make_settlement_namer
from app.world.construction import can_afford

CLAIM_BASE_COST = {"Gold": 80}
CLAIM_COST_PER_CELL = {"Gold": 0.6}
CLAIM_BASE_TURNS = 4
CLAIM_TURNS_PER_CELL = 0.03
CLAIM_FAIL_COOLDOWN_TURNS = 5
CLAIM_FAIL_STRENGTH_BUMP = 1.15   # a county "digs in" after repelling a claim

# Wildland garrisons fight 10% below their nominal strength rating — applied
# consistently wherever a garrison is actually fought: here (the AI's
# instant-formula resolution) and as each spawned unit's combat power in the
# player's interactive battle (see app/ui/app.py's stage_wildland_battle,
# app/battle/unit.py's Unit(strength_mult=...)). wildland_strength itself is
# left alone — it's still the canonical "how tough is this garrison" rating
# used for claim difficulty/visuals; this only discounts it at the moment of
# actual combat.
WILDLAND_COMBAT_STRENGTH_MULT = 0.9


def claim_cost(county):
    cost = dict(CLAIM_BASE_COST)
    for resource, per_cell in CLAIM_COST_PER_CELL.items():
        cost[resource] = cost.get(resource, 0) + round(per_cell * len(county.cells))
    return cost


def claim_turns(county):
    return max(1, round(CLAIM_BASE_TURNS + CLAIM_TURNS_PER_CELL * len(county.cells)))


def claim_odds(nation, county):
    """Player-facing success-probability preview for a wildland claim (and
    what the AI's instant-resolve path in advance_claims actually rolls
    against) — the garrison's effective strength is discounted by
    WILDLAND_COMBAT_STRENGTH_MULT, same as its soldiers are in an
    interactive battle."""
    mil = nation.stats.get("military", 0)
    effective_strength = max(1, county.wildland_strength * WILDLAND_COMBAT_STRENGTH_MULT)
    return mil / (mil + effective_strength)


def claimable_frontier(world, faction_idx):
    """UNCLAIMED counties adjacent (by land, or by sea if there's no land
    connection) to a faction's own territory — the only land it can
    legally claim next; this *is* the no-leapfrogging rule, not just a
    check for one."""
    return (territory.bordering_counties(world, faction_idx, UNCLAIMED)
            + territory.naval_reachable_counties(world, faction_idx, UNCLAIMED))


class ClaimProject:
    """A county being claimed: cost is paid up front, progress accrues over
    `total_turns` — mirrors CastleProject/RoadProject in
    app/world/construction.py, including the ceil-based countdown (not
    round(), which produces an uneven/jumpy display — see construction.py).
    Once `complete`, an AI-owned project resolves instantly (win/loss
    formula, see advance_claims); a player-owned one instead sits complete
    and waits for the player to fight an interactive battle against the
    garrison — see app/ui/app.py's stage_wildland_battle."""

    def __init__(self, faction_idx, county):
        self.faction_idx = faction_idx
        self.county_id = county.id
        self.total_turns = claim_turns(county)
        self.progress_turns = 0.0

    @property
    def turns_left(self):
        return max(0, math.ceil(self.total_turns - self.progress_turns))

    @property
    def complete(self):
        return self.progress_turns >= self.total_turns


def start_claim(world, faction_idx, county):
    """Validate and kick off claiming `county` for `faction_idx` (player or,
    in a future phase, AI). Returns a message describing what happened
    (success or why not) — used identically by the player's UI action and
    the AI expansion routine, one code path for both."""
    if county.faction_idx >= 0:
        return "That land is already claimed."
    if county not in claimable_frontier(world, faction_idx):
        return "That land doesn't border your territory."
    if world.turn < county.claim_cooldown_until_turn:
        return ("The locals are still wary after repelling your last "
                "attempt — try again later.")
    if any(p.county_id == county.id for p in world.claim_projects):
        return "A claim is already underway there."

    nation = world.factions[faction_idx]
    cost = claim_cost(county)
    if not can_afford(nation, cost):
        return "You don't have enough resources to fund this expansion."

    res = nation.stats.setdefault("resources", {})
    for resource, amount in cost.items():
        if resource == "Gold":
            nation.stats["gold"] = nation.stats.get("gold", 0) - amount
        else:
            res[resource] = res.get(resource, 0) - amount

    project = ClaimProject(faction_idx, county)
    world.claim_projects.append(project)
    return (f"Expansion begins into {county.name} — estimated "
            f"{project.total_turns} turns.")


def settle_newly_claimed_county(world, county):
    """Place settlements/villages for a freshly claimed county, reusing the
    same worldgen machinery used for a faction's starting foothold (so a new
    city/castle/town lands fresh, scored against live geography, rather than
    being pre-baked at world-gen for land nobody may ever reach), and
    recompute its resource yield so next turn's advance_turn is accurate."""
    if not county.settlements_generated:
        namer = make_settlement_namer(random)
        _place_settlements_for_faction(world, random, county.faction_idx,
                                       list(county.cells), namer)
        _place_villages_for_county(world, random, county)
        county.settlements_generated = True
    county.resources = resources.compute_county_yield(county, world.season)


def resolve_claim_win(world, county, faction_idx):
    """A garrison battle (or, for AI, the instant formula) was won: transfer
    the county and populate it fresh. Shared by advance_claims' AI path and
    app.py's player-battle-outcome handling."""
    territory.transfer_county(world, county, faction_idx)
    settle_newly_claimed_county(world, county)


def resolve_claim_loss(world, county):
    """A garrison battle (or the instant formula) was lost: no refund, the
    garrison digs in (a permanent strength bump) and a cooldown before it
    can be attempted again. Shared the same way as resolve_claim_win."""
    county.wildland_strength = round(county.wildland_strength * CLAIM_FAIL_STRENGTH_BUMP)
    county.claim_cooldown_until_turn = world.turn + CLAIM_FAIL_COOLDOWN_TURNS


def advance_claims(world):
    """Called every turn (alongside construction.advance_projects): grow
    claim progress. An AI-owned claim resolves instantly (win/loss formula)
    the moment it completes, same as before; the player's own claims
    instead sit complete and wait for an interactive battle against the
    garrison rather than auto-resolving — see app/ui/app.py's
    stage_wildland_battle, which calls resolve_claim_win/_loss once that
    battle's outcome is known."""
    player_idx = world.player_faction_idx
    finished_ai = []
    for project in world.claim_projects:
        if not project.complete:
            project.progress_turns += 1.0
        if project.complete and project.faction_idx != player_idx:
            finished_ai.append(project)

    for project in finished_ai:
        world.claim_projects.remove(project)
        county = world.counties[project.county_id]
        nation = world.factions[project.faction_idx]
        if random.random() < claim_odds(nation, county):
            resolve_claim_win(world, county, project.faction_idx)
        else:
            resolve_claim_loss(world, county)
