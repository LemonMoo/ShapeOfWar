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
from app.world.nation import is_eliminated
from app.world import resources
from app.world import wrap
from app.world.worldgen import (UNCLAIMED, _place_settlements_for_faction,
                                _place_villages_for_region, _adjacent_region_ids)
from app.world.lexicon import make_settlement_namer
from app.world.construction import (can_afford, _pay_cost, RoadProject, _path_between,
                                    _ai_has_active_construction)

# Claiming is an expedition, not a purchase. It used to be paid in Gold alone
# (80 flat + 0.6/cell, so ~170 for a typical region), which made expansion a
# pure treasury check -- and a punishing one: instrumenting the expansion AI
# showed 90% of all its attempts failing on affordability, against 0.2% blocked
# by anything else. Gold is now a small fraction of that, and most of the cost
# is the timber and stone an expedition actually consumes putting up palisades,
# bridges and the first buildings on ground nobody has settled before.
# Stone is kept genuinely minimal. At a first pass it was the single binding
# constraint on 4 of 14 realms in a late-game save (Logs never blocked anyone),
# which is not what "a minimal amount of stone" should mean -- quarrying is far
# rarer across the map than logging, so the same nominal price bites much harder.
CLAIM_BASE_COST = {"Gold": 25, "Logs": 30, "Stone": 12}
CLAIM_COST_PER_CELL = {"Gold": 0.1, "Logs": 0.12, "Stone": 0.04}
CLAIM_BASE_TURNS = 4
CLAIM_TURNS_PER_CELL = 0.03
CLAIM_FAIL_COOLDOWN_TURNS = 5
CLAIM_FAIL_STRENGTH_BUMP = 1.15   # a region "digs in" after repelling a claim

# Amphibious ("sea-only") claims: a shore region reachable only across water,
# with no land border to territory the faction already holds (see
# is_sea_only_claim). These are deliberately far more expensive and better
# defended than a normal land-adjacent claim, so neither the player nor the AI
# can cheaply leapfrog across the sea and over-expand beyond their real reach
# in the early game.
# Rebalanced on the same principle, but deliberately still steep: an amphibious
# claim has to be a real commitment, not a way to leapfrog the map early.
SEA_ONLY_CLAIM_COST = {"Gold": 300, "Logs": 220, "Stone": 90}
SEA_ONLY_STRENGTH_MULT = 1.5      # its garrison is stronger (more soldiers) too

# Wildland garrisons fight 10% below their nominal strength rating — applied
# consistently wherever a garrison is actually fought: here (the AI's
# instant-formula resolution) and as each spawned unit's combat power in the
# player's interactive battle (see app/ui/app.py's stage_wildland_battle,
# app/battle/unit.py's Unit(strength_mult=...)). wildland_strength itself is
# left alone — it's still the canonical "how tough is this garrison" rating
# used for claim difficulty/visuals; this only discounts it at the moment of
# actual combat.
WILDLAND_COMBAT_STRENGTH_MULT = 0.9

# How sharply a strength ADVANTAGE converts into a win. A plain
# mil/(mil+strength) ratio is very forgiving of being outnumbered: it takes a
# ~32x advantage to reach 97% odds, which no realm ever reaches. Raising both
# sides to this power makes concentrated force tell the way it does in
# practice -- being twice as strong is worth much more than twice the odds --
# so a developed realm genuinely rolls over wildland (97%+ once it has the
# population and the Weapons/Shields to arm it, see resources.
# _recompute_military) while an early, unarmed one still faces a real fight
# (~35%) against exactly the same garrison. Tuned against measured
# early/mid/late military ratings from real games, not picked by feel.
CLAIM_ODDS_EXPONENT = 1.75


def is_sea_only_claim(world, faction_idx, region):
    """True when `region` is claimable only across water — naval-reachable
    from the faction's territory but NOT sharing a land border with it. These
    amphibious claims carry the steep SEA_ONLY_CLAIM_COST and a tougher
    garrison (see SEA_ONLY_STRENGTH_MULT); a normal land-adjacent claim is
    False and keeps the cheap per-cell cost."""
    if region in territory.bordering_regions(world, faction_idx, UNCLAIMED):
        return False
    return region in territory.naval_reachable_regions(world, faction_idx, UNCLAIMED)


def claim_cost(region, sea_only=False):
    cost = dict(SEA_ONLY_CLAIM_COST if sea_only else CLAIM_BASE_COST)
    for resource, per_cell in CLAIM_COST_PER_CELL.items():
        cost[resource] = cost.get(resource, 0) + round(per_cell * len(region.cells))
    return cost


def claim_turns(region):
    return max(1, round(CLAIM_BASE_TURNS + CLAIM_TURNS_PER_CELL * len(region.cells)))


def claim_odds(nation, region, sea_only=False):
    """Player-facing success-probability preview for a wildland claim (and
    what the AI's instant-resolve path in advance_claims actually rolls
    against) — the garrison's effective strength is discounted by
    WILDLAND_COMBAT_STRENGTH_MULT, same as its soldiers are in an
    interactive battle, and bumped by SEA_ONLY_STRENGTH_MULT for an
    amphibious claim (its garrison is bigger)."""
    mil = max(0, nation.stats.get("military", 0))
    strength = region.wildland_strength * (SEA_ONLY_STRENGTH_MULT if sea_only else 1.0)
    effective_strength = max(1, strength * WILDLAND_COMBAT_STRENGTH_MULT)
    if mil <= 0:
        return 0.0
    k = CLAIM_ODDS_EXPONENT
    return mil ** k / (mil ** k + effective_strength ** k)


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

    def __init__(self, faction_idx, region, sea_only=False):
        self.faction_idx = faction_idx
        self.region_id = region.id
        self.total_turns = claim_turns(region)
        self.progress_turns = 0.0
        self.sea_only = sea_only   # amphibious claim -> tougher garrison in the
                                   # resolving battle (see stage_wildland_battle)

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
    # The army marches with the commander -- see commander.commander_can_reach.
    from app.world import commander as commander_mod
    blocked = commander_mod.commander_block_reason(world, faction_idx, region)
    if blocked:
        return blocked

    nation = world.factions[faction_idx]
    sea_only = is_sea_only_claim(world, faction_idx, region)
    cost = claim_cost(region, sea_only)
    if not can_afford(nation, cost, world):
        return "You don't have enough resources to fund this expansion."

    _pay_cost(nation, cost, world)

    project = ClaimProject(faction_idx, region, sea_only)
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
            d2 = wrap.dist2_wrap(mp, np, world.w)
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


# --- Spoils of the claim ------------------------------------------------------
# Taking wildland used to give nothing but the ground itself: you paid, you
# fought, and the region arrived empty. What a garrison had actually been
# sitting on -- its stores, and the worked goods of whoever lived there before
# -- now comes with it.
#
# Scaled off the region's OWN output rather than a flat bundle, so seizing rich
# land is worth more than seizing a bog, and off wildland_strength for the Gold,
# because a garrison tough enough to need a real army was guarding something.
# Gold spoils are pinned to what the claim actually COST rather than floating
# free, so taking wildland is reliably profitable in coin instead of sometimes
# being a net loss (at the first pass it returned 38 Gold against a 45 Gold
# price). That profit is the point: it gives an early realm a way to GENERATE
# gold by expanding, rather than every kingdom simply starting with a pile of
# it. The margin is deliberately modest and per-claim -- it compounds over a
# campaign instead of arriving all at once.
#
# Pinned to the LAND cost specifically, so an amphibious claim (far pricier --
# see SEA_ONLY_CLAIM_COST) stays a real commitment rather than a way to farm
# coin across the sea.
CLAIM_SPOILS_YIELD_TURNS = 10    # stores roughly this many turns of local output
CLAIM_SPOILS_GOLD_MULT = 1.8     # Gold returned, as a multiple of the Gold paid
CLAIM_SPOILS_GOLD_PER_STRENGTH = 0.25   # plus a bounty for a tough garrison


def claim_spoils(world, region):
    """{resource: amount} seized when `region` is taken -- a preview the UI can
    show before committing, and the exact bundle resolve_claim_win grants."""
    from app.world import resources as res_mod
    spoils = {}
    for resource, amount in res_mod.compute_region_yield(region, world.season).items():
        take = round(amount * CLAIM_SPOILS_YIELD_TURNS)
        if take > 0:
            spoils[resource] = take
    paid = claim_cost(region).get("Gold", 0)
    gold = round(paid * CLAIM_SPOILS_GOLD_MULT
                 + region.wildland_strength * CLAIM_SPOILS_GOLD_PER_STRENGTH)
    if gold > 0:
        spoils["Gold"] = spoils.get("Gold", 0) + gold
    return spoils


def claim_net_gold(world, region):
    """Gold left over after paying for the claim -- what the UI should promise,
    since 'spoils 100' means little without 'cost 45' beside it."""
    return claim_spoils(world, region).get("Gold", 0) - claim_cost(region).get("Gold", 0)


def _grant_claim_spoils(world, region):
    """Deliver the spoils into the region's own new villages. Routed through
    the ordinary production path so it lands where everything else does and
    respects storage the same way -- but unthrottled, because these goods
    physically exist and are being carried in, not produced on the spot."""
    from app.world import resources as res_mod
    spoils = claim_spoils(world, region)
    bound = {r: a for r, a in spoils.items()
             if r in res_mod._SETTLEMENT_STORAGE_RESOURCES}
    if bound:
        res_mod._route_farm_production(world, region, bound, throttle=False)
    return spoils


def resolve_claim_win(world, region, faction_idx):
    """A garrison battle (or, for AI, the instant formula) was won: transfer
    the region and populate it fresh. Shared by advance_claims' AI path and
    app.py's player-battle-outcome handling."""
    strength = region.wildland_strength   # consumed by the transfer below
    territory.transfer_region(world, region, faction_idx)
    settle_newly_claimed_region(world, region)
    # Villages have to exist first -- they are what receives the spoils.
    region.wildland_strength = strength
    return _grant_claim_spoils(world, region)


def resolve_claim_loss(world, region):
    """A garrison battle (or the instant formula) was lost: no refund, the
    garrison digs in (a permanent strength bump) and a cooldown before it
    can be attempted again. Shared the same way as resolve_claim_win."""
    region.wildland_strength = round(region.wildland_strength * CLAIM_FAIL_STRENGTH_BUMP)
    region.claim_cooldown_until_turn = world.turn + CLAIM_FAIL_COOLDOWN_TURNS
    # The strength bump changes UNCLAIMED land's "danger" tint on the map
    # (see map_view.py's _compute_cell) even though ownership itself never
    # changed here -- territory_version alone wouldn't catch that, so it's
    # bumped explicitly too, on top of marking the cells dirty.
    world.territory_version = getattr(world, "territory_version", 0) + 1
    territory.mark_cells_dirty(world, region.cells)


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
        if random.random() < claim_odds(nation, region, project.sea_only):
            resolve_claim_win(world, region, project.faction_idx)
        else:
            resolve_claim_loss(world, region)


# --- AI commander movement ---------------------------------------------------
# Commander presence gates claiming as well as war (see commander_can_reach),
# and an AI commander that never leaves its capital would freeze that faction's
# expansion permanently -- claiming wildland is the only way AI realms grow.
# So the AI walks its commander to wherever it next wants to take ground.
#
# Deliberately minimal, matching the rest of this AI: no scoring, no planning
# horizon. If the commander is idle and cannot authorise anything, send it
# toward the nearest frontier region it could claim from. That is enough to
# keep expansion moving without pretending to be a general.
def run_commander_ai(world):
    from app.world import commander as commander_mod
    for fac_idx, nation in enumerate(world.factions):
        if fac_idx == world.player_faction_idx or is_eliminated(nation):
            continue
        cmds = commander_mod.faction_commanders(world, fac_idx)
        if not cmds:
            continue
        cmd = cmds[0]
        if cmd.path is not None:            # already marching somewhere
            continue
        frontier = claimable_frontier(world, fac_idx)
        if not frontier:
            continue
        # Stay put only while there is something here worth doing -- ground
        # this faction can both REACH and AFFORD. Testing reachability alone
        # pinned commanders in place forever: measured, on 99.7% of turns they
        # could reach some frontier region so they never moved, while 90% of
        # expansion attempts failed on cost. A commander parked beside land its
        # realm cannot pay for should go and find land it can.
        useful = [r for r in frontier
                  if commander_mod.commander_can_reach(world, fac_idx, r)
                  and can_afford(nation,
                                 claim_cost(r, is_sea_only_claim(world, fac_idx, r)),
                                 world)]
        if useful:
            continue
        # Head for the staging ground of the closest target: one of our OWN
        # regions bordering it, which is where the gate actually wants us.
        # Head for the cheapest handful -- claim cost scales with region size,
        # and marching to something unaffordable just relocates the problem.
        best = None
        targets = sorted(frontier, key=lambda r: sum(
            claim_cost(r, is_sea_only_claim(world, fac_idx, r)).values()))[:6]
        for region in targets:
            for cid in _adjacent_region_ids(world, region):
                staging = world.regions[cid]
                if staging.faction_idx != fac_idx or not staging.cells:
                    continue
                target = min(staging.cells,
                             key=lambda c: wrap.dist_wrap(cmd.pos, c, world.w))
                dist = wrap.dist_wrap(cmd.pos, target, world.w)
                if best is None or dist < best[0]:
                    best = (dist, target)
        if best is not None and best[1] != cmd.pos:
            commander_mod.set_move_order(world, cmd, best[1])


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
        if fac_idx == world.player_faction_idx or is_eliminated(nation):
            continue
        if _ai_has_active_construction(world, fac_idx):
            continue
        frontier = claimable_frontier(world, fac_idx)
        if not frontier:
            continue
        # Only consider ground the commander can actually authorise. The pick
        # used to be uniformly random across the whole frontier, which once
        # claims became commander-gated meant the AI almost always chose a
        # region its commander was nowhere near: measured, 19 of 20 attempts
        # were refused and AI expansion collapsed from +20 regions per 200
        # turns to +3. Choosing from what the army can actually reach costs
        # nothing in simplicity and restores it.
        from app.world import commander as commander_mod
        reachable = [r for r in frontier
                     if commander_mod.commander_can_reach(world, fac_idx, r)]
        if not reachable:
            continue        # run_commander_ai will march someone toward it
        # Choose among what it can actually pay for, not blindly at random.
        # Claim cost scales with region size, and the old uniform pick spent
        # most turns proposing a region the faction could not afford --
        # measured, 90% of all expansion-AI turns ended in "cannot afford"
        # while only 0.2% were blocked by the commander. Narrowing the pool to
        # commander-reachable ground made that worse by removing the cheap
        # outliers a random draw used to stumble into, so affordability is now
        # part of the choice rather than a post-hoc test.
        affordable = [r for r in reachable
                      if can_afford(nation,
                                    claim_cost(r, is_sea_only_claim(world, fac_idx, r)),
                                    world)]
        if not affordable:
            continue
        region = random.choice(affordable)
        start_claim(world, fac_idx, region)
