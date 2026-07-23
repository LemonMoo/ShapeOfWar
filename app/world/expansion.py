"""Progressive territory expansion: claiming UNCLAIMED land instead of
starting the game already owning a fully-formed nation. Every region not
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
                                _place_villages_for_region, _adjacent_region_ids)
from app.world.lexicon import make_settlement_namer
from app.world.construction import (can_afford, _pay_cost, RoadProject, _path_between,
                                    _ai_has_active_construction)

CLAIM_BASE_COST = {"Gold": 80}
CLAIM_COST_PER_CELL = {"Gold": 0.6}
CLAIM_BASE_TURNS = 4
CLAIM_TURNS_PER_CELL = 0.03
CLAIM_FAIL_COOLDOWN_TURNS = 5
CLAIM_FAIL_STRENGTH_BUMP = 1.15   # a region "digs in" after repelling a claim

# Wildland garrisons fight 10% below their nominal strength rating — applied
# consistently wherever a garrison is actually fought: here (the AI's
# instant-formula resolution) and as each spawned unit's combat power in the
# player's interactive battle (see app/ui/app.py's stage_wildland_battle,
# app/battle/unit.py's Unit(strength_mult=...)). wildland_strength itself is
# left alone — it's still the canonical "how tough is this garrison" rating
# used for claim difficulty/visuals; this only discounts it at the moment of
# actual combat.
WILDLAND_COMBAT_STRENGTH_MULT = 0.9


def claim_cost(region):
    cost = dict(CLAIM_BASE_COST)
    for resource, per_cell in CLAIM_COST_PER_CELL.items():
        cost[resource] = cost.get(resource, 0) + round(per_cell * len(region.cells))
    return cost


def claim_turns(region):
    return max(1, round(CLAIM_BASE_TURNS + CLAIM_TURNS_PER_CELL * len(region.cells)))


def claim_odds(nation, region):
    """Player-facing success-probability preview for a wildland claim (and
    what the AI's instant-resolve path in advance_claims actually rolls
    against) — the garrison's effective strength is discounted by
    WILDLAND_COMBAT_STRENGTH_MULT, same as its soldiers are in an
    interactive battle."""
    mil = nation.stats.get("military", 0)
    effective_strength = max(1, region.wildland_strength * WILDLAND_COMBAT_STRENGTH_MULT)
    return mil / (mil + effective_strength)


def claimable_frontier(world, faction_idx):
    """UNCLAIMED regions adjacent (by land, or by sea if there's no land
    connection) to a faction's own territory — the only land it can
    legally claim next; this *is* the no-leapfrogging rule, not just a
    check for one."""
    return (territory.bordering_regions(world, faction_idx, UNCLAIMED)
            + territory.naval_reachable_regions(world, faction_idx, UNCLAIMED))


class ClaimProject:
    """A region being claimed: cost is paid up front, progress accrues over
    `total_turns` — mirrors SettlementProject/RoadProject in
    app/world/construction.py, including the ceil-based countdown (not
    round(), which produces an uneven/jumpy display — see construction.py).
    Once `complete`, an AI-owned project resolves instantly (win/loss
    formula, see advance_claims); a player-owned one instead sits complete
    and waits for the player to fight an interactive battle against the
    garrison — see app/ui/app.py's stage_wildland_battle."""

    def __init__(self, faction_idx, region):
        self.faction_idx = faction_idx
        self.region_id = region.id
        self.total_turns = claim_turns(region)
        self.progress_turns = 0.0

    @property
    def turns_left(self):
        return max(0, math.ceil(self.total_turns - self.progress_turns))

    @property
    def complete(self):
        return self.progress_turns >= self.total_turns


def start_claim(world, faction_idx, region):
    """Validate and kick off claiming `region` for `faction_idx` (player or,
    in a future phase, AI). Returns a message describing what happened
    (success or why not) — used identically by the player's UI action and
    the AI expansion routine, one code path for both."""
    if region.faction_idx >= 0:
        return "That land is already claimed."
    if region not in claimable_frontier(world, faction_idx):
        return "That land doesn't border your territory."
    if world.turn < region.claim_cooldown_until_turn:
        return ("The locals are still wary after repelling your last "
                "attempt — try again later.")
    if any(p.region_id == region.id for p in world.claim_projects):
        return "A claim is already underway there."

    nation = world.factions[faction_idx]
    cost = claim_cost(region)
    if not can_afford(nation, cost, world):
        return "You don't have enough resources to fund this expansion."

    _pay_cost(nation, cost, world)

    project = ClaimProject(faction_idx, region)
    world.claim_projects.append(project)
    return (f"Expansion begins into {region.name} — estimated "
            f"{project.total_turns} turns.")


_NO_FREE_SETTLEMENT = {"city": 0, "town": 0, "castle": 0}   # see _place_settlements_for_faction

WILDLAND_VILLAGE_MIN = 1
WILDLAND_VILLAGE_MAX = 3
WILDLAND_VILLAGE_CELLS_PER = 100   # area per village, before min/max clamping


def _wildland_village_count(region):
    """1-3 villages for a newly claimed region, scaled by area — wildland
    is meant to stay sparse, not use the much larger (3-50) area-scaled
    range the starting foothold / general village formula allows."""
    return max(WILDLAND_VILLAGE_MIN, min(WILDLAND_VILLAGE_MAX,
              round(len(region.cells) / WILDLAND_VILLAGE_CELLS_PER)))


def settle_newly_claimed_region(world, region):
    """Place settlements/villages for a freshly claimed region, reusing the
    same worldgen machinery used for a faction's starting foothold (so a new
    castle/village lands fresh, scored against live geography, rather than
    being pre-baked at world-gen for land nobody may ever reach), and
    recompute its resource yield so next turn's advance_turn is accurate.

    Wildland only ever gives up villages (1-3, scaled by area) — no free
    City, Town, or Castle. Getting one of those now takes an actual
    construction project (app/world/construction.py's start_settlement/
    run_settlement_ai), the same as everyone's very first City/Town/Castle
    always has."""
    if not region.settlements_generated:
        namer = make_settlement_namer(random)
        _place_settlements_for_faction(world, random, region.faction_idx,
                                       list(region.cells), namer,
                                       fixed_counts=_NO_FREE_SETTLEMENT)
        _place_villages_for_region(world, random, region,
                                   fixed_n=_wildland_village_count(region))
        region.settlements_generated = True
    region.resources = resources.compute_region_yield(region, world.season)


def _region_has_interregion_road(world, region):
    """Whether `region` already has at least one interregion road --
    checked across region.id's OWN bucket of world.roads_by_region *and*
    every adjacent region's bucket. A completed road's segments are filed
    entirely under whichever endpoint was the path's destination (see
    construction._finish_road's use of path[-1]'s region), which could be
    either side depending on which region initiated it -- checking only
    region.id's own bucket used to miss a road a neighbor had already
    built TO this region (filed under the neighbor's bucket instead),
    leaving this region unaware it was already connected and free to
    build its own redundant second road back toward that same neighbor,
    often along a slightly different route since it's an independent
    Dijkstra search. A road connecting `region` to some neighbor can only
    ever be filed under one of those two regions' buckets, never a third
    region's, so checking region.id's own bucket plus every adjacent
    region's bucket is exhaustive."""
    buckets = [region.id, *_adjacent_region_ids(world, region)]
    for rid in buckets:
        for (ax, ay), (bx, by), _tier in world.roads_by_region.get(rid, []):
            ra, rb = world.region_grid[ay][ax], world.region_grid[by][bx]
            if ra != rb and region.id in (ra, rb):
                return True
    return False


def _region_has_pending_interregion_road(world, region):
    for proj in world.road_projects:
        if not proj.path:
            continue
        ax, ay = proj.path[0]
        bx, by = proj.path[-1]
        ra, rb = world.region_grid[ay][ax], world.region_grid[by][bx]
        if ra != rb and region.id in (ra, rb):
            return True
    return False


def _nearest_interregion_village_link(world, region):
    """(my_village_pos, neighbor_village_pos) for the closest pair between
    this region's own villages and an adjacent, same-faction, already-
    settled region's villages — or None if there's no candidate (no
    villages here yet, or no settled neighbor with villages of its own)."""
    if not region.villages:
        return None
    neighbor_villages = []
    for rid in _adjacent_region_ids(world, region):
        other = world.regions[rid]
        if other.faction_idx != region.faction_idx or not other.settlements_generated:
            continue
        neighbor_villages.extend(world.villages[vid].pos for vid in other.villages)
    if not neighbor_villages:
        return None
    my_villages = [world.villages[vid].pos for vid in region.villages]
    best, best_d2 = None, None
    for mp in my_villages:
        for np in neighbor_villages:
            d2 = (mp[0] - np[0]) ** 2 + (mp[1] - np[1]) ** 2
            if best_d2 is None or d2 < best_d2:
                best_d2, best = d2, (mp, np)
    return best


def ensure_interregion_roads(world):
    """Every settled region with at least one village should have a dirt
    road connecting it to a neighboring already-settled region of the same
    faction — otherwise a freshly claimed wildland region's villages sit
    isolated from the rest of the faction's road network, cut off at the
    region border. Runs every turn, so it catches both a region claimed
    this turn *and* any pre-existing gap (a starting foothold spanning
    multiple regions, or a region claimed before this rule existed) —
    retroactive by construction, not a one-time migration. One connector
    project started per region per call, using the same RoadProject/
    ROAD_CELLS_PER_TURN machinery every other road in the game already
    uses, tiered "dirt" since it always touches a village."""
    for region in world.regions:
        if region.faction_idx < 0 or not region.settlements_generated:
            continue
        if not region.villages:
            continue
        if _region_has_interregion_road(world, region):
            continue
        if _region_has_pending_interregion_road(world, region):
            continue
        link = _nearest_interregion_village_link(world, region)
        if link is None:
            continue
        my_pos, neighbor_pos = link
        path = _path_between(world, neighbor_pos, my_pos, faction_idx=region.faction_idx)
        if len(path) > 1:
            world.road_projects.append(RoadProject(region.faction_idx, path, tier="dirt"))


def resolve_claim_win(world, region, faction_idx):
    """A garrison battle (or, for AI, the instant formula) was won: transfer
    the region and populate it fresh. Shared by advance_claims' AI path and
    app.py's player-battle-outcome handling."""
    territory.transfer_region(world, region, faction_idx)
    settle_newly_claimed_region(world, region)


def resolve_claim_loss(world, region):
    """A garrison battle (or the instant formula) was lost: no refund, the
    garrison digs in (a permanent strength bump) and a cooldown before it
    can be attempted again. Shared the same way as resolve_claim_win."""
    region.wildland_strength = round(region.wildland_strength * CLAIM_FAIL_STRENGTH_BUMP)
    region.claim_cooldown_until_turn = world.turn + CLAIM_FAIL_COOLDOWN_TURNS


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
        region = world.regions[project.region_id]
        nation = world.factions[project.faction_idx]
        if random.random() < claim_odds(nation, region):
            resolve_claim_win(world, region, project.faction_idx)
        else:
            resolve_claim_loss(world, region)


def run_expansion_ai(world):
    """Every AI faction's equivalent of the player clicking "Claim
    Territory": each turn, a faction with no construction/expansion
    project currently in flight (see construction._ai_has_active_
    construction -- the same shared anti-overbuild gate run_settlement_ai
    and run_storage_ai use) looks at its own claimable frontier and starts
    a claim on one candidate if it can afford it. Deliberately simple,
    same philosophy as run_settlement_ai: picks a random frontier region
    rather than scoring candidates by garrison strength/fertility/
    adjacency-to-a-weak-point/etc -- a reasonable future refinement, not
    this one."""
    for fac_idx, nation in enumerate(world.factions):
        if fac_idx == world.player_faction_idx:
            continue
        if _ai_has_active_construction(world, fac_idx):
            continue
        frontier = claimable_frontier(world, fac_idx)
        if not frontier:
            continue
        region = random.choice(frontier)
        if can_afford(nation, claim_cost(region), world):
            start_claim(world, fac_idx, region)
