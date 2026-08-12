"""Progressive territory expansion: claiming UNCLAIMED land instead of
starting the game already owning a fully-formed nation. Every region not
part of a faction's starting foothold begins UNCLAIMED, defended by a
neutral "wildland" garrison (see app/world/worldgen.py's
_seed_wildland_strength) — claiming one requires being adjacent to land you
already hold (no leapfrogging), costs settlers and provisions, takes real
turns, and only resolves win/loss against the garrison once the work is done.
"""
import math
import random

from app.world import territory
from app.world import layers
from app.world.nation import is_eliminated
from app.world import resources
from app.world import wrap
from app.world.worldgen import (UNCLAIMED, _place_settlements_for_faction,
                                _place_villages_for_region, _adjacent_region_ids)
from app.world.lexicon import make_settlement_namer
from app.world.construction import (can_afford, _pay_cost, RoadProject, _path_between,
                                    _ai_has_active_construction)

# Claiming is COLONISATION: you send people, and you feed them until the
# first harvest. Nothing else.
#
# It has been priced three ways now. First Gold alone (a pure treasury
# check: 90% of all AI attempts failed on affordability, against 0.2%
# blocked by anything else). Then Gold + Logs + Stone, on the reasoning
# that an expedition consumes timber and stone raising palisades. That
# second version is the one this replaces, and it failed for a structural
# reason rather than a tuning one: measured on a real save, 5 of 14 realms
# COULD NOT CLAIM ANYTHING AT ALL -- four short of Stone, one short of
# Gold. Quarrying barely exists for most realms (villages are sited on
# farmland, mountain is ~4.5% of the map), and some worlds mint no gold
# whatsoever. Pricing expansion in goods that whole realms structurally
# cannot obtain is a dead end, not a difficulty setting.
#
# Settlers and provisions cannot lock anyone out, because a realm without
# people or food is already finished. It is also what taking new land
# actually cost, historically -- the Roman colonia, the Greek apoikia, the
# Norse landnam, the Ottoman surgun, homesteading: you moved families and
# you victualled them. Timber and stone are what you spend building a fort
# once you are there, which is what the BUILD menu is for.
#
# The real bite is that population IS the workforce (see resources.py's
# Phase 14 labour model), so settlers come straight off the fields at home.
# Expansion now competes with production instead of draining a pile nobody
# was using.
CLAIM_SETTLERS_BASE = 40
CLAIM_SETTLERS_PER_CELL = 0.15
CLAIM_PROVISIONS_PER_SETTLER = 3     # food to see them to the first harvest
# No single node gives up more than this share of its people to any one
# expedition -- a realm should be able to expand without gutting the
# village next door to do it.
CLAIM_SETTLER_DRAW_FRACTION = 0.25
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
# claim has to be a real commitment, not a way to leapfrog the map early. In
# settlers-and-provisions terms that reads more naturally than it did in
# gold and stone -- a sea crossing needs more people and more supplies, and
# is exactly the kind of undertaking a realm has to be big enough to mount.
SEA_ONLY_SETTLERS_BASE = 180
SEA_ONLY_SETTLERS_PER_CELL = 0.35
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


def frontier_id_sets(world, faction_idx):
    """({land-adjacent region ids}, {naval-reachable region ids}) for this
    faction's unclaimed frontier.

    Exists so a caller asking about MANY regions pays for the territory scan
    once instead of once per region. The AI loops did the latter: they called
    is_sea_only_claim for every frontier region, and each call re-scanned the
    faction's whole territory and then did an `in` test against a LIST. On a
    300-region world that was ~24% of the entire end-turn cost.
    """
    land = {r.id for r in territory.bordering_regions(world, faction_idx, UNCLAIMED)}
    # ...and whatever lies through a door you hold (SUBTERRANEAN_PLAN phase 5).
    # Counted as LAND-adjacent rather than as its own third kind of frontier:
    # a gate is a way in that you walk through, so an underground claim is an
    # ordinary claim made at a chokepoint, not an amphibious one. What makes
    # it expensive is the ground itself -- see the marching cost of a gallery.
    land |= {r.id for r in territory.gate_bordering_regions(world, faction_idx,
                                                            UNCLAIMED)}
    naval = {r.id for r in territory.naval_reachable_regions(world, faction_idx,
                                                             UNCLAIMED)}
    return land, naval


def is_sea_only_claim(world, faction_idx, region, frontier=None):
    """True when `region` is claimable only across water — naval-reachable
    from the faction's territory but NOT sharing a land border with it. These
    amphibious claims need far more settlers (SEA_ONLY_SETTLERS_BASE) and a
    tougher garrison (see SEA_ONLY_STRENGTH_MULT); a normal land-adjacent
    claim is False and keeps the cheap per-cell rate.

    `frontier` is an optional (land_ids, naval_ids) pair from
    frontier_id_sets, for callers testing many regions at once. Passing it is
    a pure hoist -- the answer is identical, it just is not recomputed per
    region."""
    land, naval = frontier if frontier is not None else frontier_id_sets(
        world, faction_idx)
    if region.id in land:
        return False
    return region.id in naval


def claim_settlers(region, sea_only=False):
    """How many people this claim takes out of the realm."""
    base = SEA_ONLY_SETTLERS_BASE if sea_only else CLAIM_SETTLERS_BASE
    per_cell = SEA_ONLY_SETTLERS_PER_CELL if sea_only else CLAIM_SETTLERS_PER_CELL
    return max(1, round(base + per_cell * len(region.cells)))


def claim_cost(region, sea_only=False):
    """The GOODS half of a claim -- provisions for the settlers, and nothing
    else. Returned as a {resource: amount} dict for the same reason it
    always was: every caller (the UI's cost line, the AI's affordability
    check) already speaks that shape.

    "Food" is not a resource in the registry -- it is a pooled demand met by
    any edible (resources._FOOD_SOURCES), exactly as population consumption
    already works -- so this does NOT go through construction.can_afford /
    _pay_cost, which look resources up by literal name. See
    can_afford_claim / _pay_claim below."""
    settlers = claim_settlers(region, sea_only)
    return {"Food": settlers * CLAIM_PROVISIONS_PER_SETTLER}


def _faction_population_nodes(world, faction_idx):
    """Every settlement and village this faction owns that has people in it,
    nearest-first ordering left to the caller."""
    nodes = [s for s in world.settlements if s.faction_idx == faction_idx]
    nodes += [v for v in world.villages if v.faction_idx == faction_idx]
    return [n for n in nodes if getattr(n, "population", 0) > 0]


def _node_spare_settlers(node):
    """How many people this node will release to an expedition: its share cap
    (CLAIM_SETTLER_DRAW_FRACTION), and never below the same hard floor
    starvation itself respects (resources.POPULATION_MIN_FRACTION of its own
    max_population) -- so expanding can never empty a village the way a
    famine can't."""
    from app.world.resources import POPULATION_MIN_FRACTION
    pop = getattr(node, "population", 0)
    if pop <= 0:
        return 0
    max_pop = getattr(node, "max_population", None) or pop
    floor = max_pop * POPULATION_MIN_FRACTION
    return max(0, int(min(pop * CLAIM_SETTLER_DRAW_FRACTION, pop - floor)))


def faction_available_settlers(world, faction_idx):
    """People the realm could actually put on the road right now."""
    return sum(_node_spare_settlers(n)
               for n in _faction_population_nodes(world, faction_idx))


def _faction_food_stock(world, faction_idx):
    """Total edible goods across the realm -- the pooled figure provisions
    are drawn from (see claim_cost on why this isn't a plain resource)."""
    from app.world.resources import _FOOD_SOURCES
    nation = world.factions[faction_idx]
    total = 0
    for node in _faction_population_nodes(world, faction_idx):
        res = getattr(node, "resources", None) or {}
        total += sum(res.get(f, 0) for f in _FOOD_SOURCES)
    return total


def can_afford_claim(world, faction_idx, region, sea_only=False):
    """None if this claim can be funded, else why not. Replaces the plain
    construction.can_afford call this used to make -- settlers are people,
    not stock, and provisions are a pooled food draw."""
    settlers = claim_settlers(region, sea_only)
    if faction_available_settlers(world, faction_idx) < settlers:
        return (f"Not enough people to settle it — this expedition needs "
                f"{settlers:,} settlers.")
    needed = claim_cost(region, sea_only)["Food"]
    if _faction_food_stock(world, faction_idx) < needed:
        return (f"Not enough food to provision {settlers:,} settlers — "
                f"needs {needed:,}.")
    return None


def _pay_claim(world, faction_idx, region, sea_only=False):
    """Take the settlers and the provisions. Settlers come from the nodes
    nearest the region first -- people go to the frontier from the edge of
    the realm, not from the capital on the far side of it -- each giving up
    at most its own spare share. Returns (settlers_taken, food_taken)."""
    from app.world.resources import _FOOD_SOURCES, _consume_from_pool
    from app.world import wrap
    settlers = claim_settlers(region, sea_only)
    cx, cy = region.cells[len(region.cells) // 2]

    nodes = sorted(_faction_population_nodes(world, faction_idx),
                   key=lambda n: wrap.dist2_wrap(n.pos, (cx, cy), world.w))
    taken = 0
    for node in nodes:
        if taken >= settlers:
            break
        give = min(_node_spare_settlers(node), settlers - taken)
        if give <= 0:
            continue
        node.population -= give
        # Keep the adults/children split honest -- settlers are working-age
        # people, which is exactly why this costs the realm real labour.
        adults = getattr(node, "adults", 0)
        node.adults = max(0, adults - give)
        taken += give

    needed = claim_cost(region, sea_only)["Food"]
    food_taken = 0
    for node in nodes:
        if food_taken >= needed:
            break
        res = getattr(node, "resources", None)
        if not res:
            continue
        food_taken += _consume_from_pool(res, _FOOD_SOURCES, needed - food_taken)
    return taken, food_taken


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
    check for one.

    An underground region borders you through a DOOR you hold, not across
    any cell edge — the two layers share none (see app/world/layers.py),
    so territory.bordering_regions above can never see it. territory.
    gate_bordering_regions is that border: whoever holds the near end of a
    gate may claim what lies at the far end of it. That is what makes the
    galleries a claimable part of the world for every species, not
    dwarf/goblin-only decoration — the plan's "anyone can go down if they
    can take a gate" made real in the ordinary claim economy (settlers,
    provisions, a commander at the door)."""
    return (territory.bordering_regions(world, faction_idx, UNCLAIMED)
            + territory.gate_bordering_regions(world, faction_idx, UNCLAIMED)
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

    sea_only = is_sea_only_claim(world, faction_idx, region)
    if not sea_only:
        # Settlement-first expansion (phase 5): a realm reaches for new land
        # when its own is genuinely full of villages, not on a whim. Claims
        # require the faction's owned regions to average >=
        # CLAIM_DEVELOPMENT_FRACTION of their village capacity -- the natural
        # "we need more land" moment, shown filling up in the region panel's
        # "n/m villages" readout. Sea claims (fleets/islands) are a different
        # kind of expansion and are exempt. AI and player share this gate --
        # one code path.
        from app.world.resources import region_village_capacity
        cap_sum = vills_sum = 0
        # NOTE: iterate as `r`, NEVER reuse `region` here -- the target
        # region is live below this gate, and rebinding it (a real bug that
        # shipped) made every claim project start on the faction's LAST
        # owned region instead of the wildland target: claims never began,
        # the duplicate guard never matched, and repeated clicks piled up
        # dead projects on the wrong region.
        for r in world.regions:
            if r.faction_idx != faction_idx:
                continue
            cap_sum += region_village_capacity(world, r)
            vills_sum += len(getattr(r, "villages", []))
        if cap_sum and vills_sum / cap_sum < CLAIM_DEVELOPMENT_FRACTION:
            return ("Your realm is still growing -- fill your village lands "
                    "(raise settlements to Cities for more room) before "
                    "reaching for new territory.")
    blocked = can_afford_claim(world, faction_idx, region, sea_only)
    if blocked:
        return blocked

    _pay_claim(world, faction_idx, region, sea_only)

    project = ClaimProject(faction_idx, region, sea_only)
    world.claim_projects.append(project)
    return (f"Expansion begins into {region.name} — estimated "
            f"{project.total_turns} days.")


_NO_FREE_SETTLEMENT = {"city": 0, "town": 0, "castle": 0}   # see _place_settlements_for_faction

# Settlement-first expansion gate (see start_claim): a realm may only reach
# for new land once its OWN regions average at least this fraction of their
# village capacity -- the "we need more land" moment. 0.5 keeps the early
# game moving (a fresh foothold is already close to half full) while making
# claim-spam without development impossible. Tune here; the AI uses the same
# gate through start_claim.
CLAIM_DEVELOPMENT_FRACTION = 0.5

WILDLAND_VILLAGE_MIN = 0   # a freshly claimed region is BARE -- no villages
                           # are handed out with it (you found your own, or
                           # build a settlement and let its prosperity grow
                           # them). Was 1 (the "frontier homestead") before
                           # the settlement-first ladder made founding the
                           # first rung of growth instead of a claim bonus.


def settle_newly_claimed_region(world, region):
    """Place settlements/villages for a freshly claimed region, reusing the
    same worldgen machinery used for a faction's starting foothold (so a new
    castle/village lands fresh, scored against live geography, rather than
    being pre-baked at world-gen for land nobody may ever reach), and
    recompute its resource yield so next turn's advance_turn is accurate.

    Wildland gives up NOTHING pre-grown — no villages (see
    WILDLAND_VILLAGE_MIN), and no free City, Town, or Castle. Getting any of
    those now takes an actual construction project
    (app/world/construction.py's start_found_village/start_settlement/
    run_settlement_ai) — the settlement-first ladder: found a village, raise
    it to a Town, raise the Town to a City."""
    if not region.settlements_generated:
        if layers.is_under(region):
            # An underground claim is BARE GALLERIES, the same "you found
            # your own" deal a surface wildland claim gets -- but there is
            # also nothing the surface placement machinery could put down
            # here even if it tried: _place_villages_for_region scores
            # surface fertility and water, which describe the mountainside
            # overhead and would scatter bogus farming hamlets through a
            # cavern. The ladder works down here (found a village, raise
            # it, build a town, via app/world/construction.py); the claim
            # just hands over the rock.
            region.settlements_generated = True
        else:
            namer = make_settlement_namer(random)
            _place_settlements_for_faction(world, random, region.faction_idx,
                                           list(region.cells), namer,
                                           fixed_counts=_NO_FREE_SETTLEMENT)
            _place_villages_for_region(world, random, region,
                                       fixed_n=WILDLAND_VILLAGE_MIN)
            region.settlements_generated = True
    # Chronicle: a claim is the biggest deliberate act in the game -- the
    # realm put settlers, food and a season's work into this land.
    from app.world import chronicle
    chronicle.log(world, world.factions[region.faction_idx],
                  f"The claim to {getattr(region, 'name', 'new land')} is secured.")
    # The frontier window: for the next FRONTIER_WINDOW_TURNS this region can
    # throw small events at its new owner (app/world/frontier.py). Below
    # ground the events are surface-flavored (soil, hermit's hut, bandits on
    # the road) and a cavern has none of it -- galleries stay event-free.
    if not layers.is_under(region):
        from app.world.frontier import FRONTIER_WINDOW_TURNS
        region.frontier_turns_left = FRONTIER_WINDOW_TURNS
    # A preview only -- real per-village production (and delivery into each
    # village's own storage) happens next turn via advance_turn's own call
    # to recompute_region_resources; this just keeps the region panel's
    # "this turn's yield" accurate in the meantime rather than showing
    # stale zeros for a freshly claimed region until the turn actually ticks.
    region.resources = {}
    for vid in region.villages:
        village = world.villages[vid]
        for resource, amount in resources.compute_village_yield(
                world, village, world.season).items():
            region.resources[resource] = region.resources.get(resource, 0) + amount


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
# Gold spoils used to be pinned to the Gold the claim cost (a multiple of it),
# which kept expansion reliably profitable in coin. A claim costs no Gold at
# all now -- it is paid in settlers and provisions -- so there is nothing left
# to take a multiple OF, and the bounty rests on the one thing that was
# always the better signal anyway: how tough the garrison was. A wildland
# strong enough to need a real army was guarding something.
#
# This still gives an early realm a way to GENERATE gold by expanding rather
# than every kingdom starting with a pile of it, which was the point.
CLAIM_SPOILS_YIELD_TURNS = 10    # stores roughly this many turns of local output
CLAIM_SPOILS_GOLD_BASE = 45      # a garrison's own strongbox
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
    gold = round(CLAIM_SPOILS_GOLD_BASE
                 + region.wildland_strength * CLAIM_SPOILS_GOLD_PER_STRENGTH)
    if gold > 0:
        spoils["Gold"] = spoils.get("Gold", 0) + gold
    return spoils


def claim_net_gold(world, region):
    """Gold a successful claim brings in. All of the spoils, now: a claim
    costs no Gold at all (settlers and provisions -- see claim_cost), so
    there is nothing to net it off against. Kept as its own function
    because the UI reads it and the distinction may return."""
    return claim_spoils(world, region).get("Gold", 0)


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
    """One day of claim growth and resolution, run whole -- see
    advance_claims_steps, which this drains."""
    for _ in advance_claims_steps(world):
        pass


def advance_claims_steps(world):
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

    # Retire stale player claims: a completed claim whose region is no
    # longer wildland (someone else claimed it, or it changed hands) can
    # never be fought -- without this, such projects sat complete in
    # claim_projects forever (a save shipped with 25 dead claims for one
    # region that a rival had since taken).
    for project in list(world.claim_projects):
        if (project.faction_idx == player_idx and project.complete
                and world.regions[project.region_id].faction_idx >= 0):
            world.claim_projects.remove(project)

    for project in finished_ai:
        world.claim_projects.remove(project)
        region = world.regions[project.region_id]
        nation = world.factions[project.faction_idx]
        if random.random() < claim_odds(nation, region, project.sea_only):
            resolve_claim_win(world, region, project.faction_idx)
        else:
            resolve_claim_loss(world, region)
        # One resolved claim at a time: taking a region rebuilds its
        # settlements and roads, so on the day several land at once this was
        # the spikiest phase of the whole day (124ms measured). Each claim is
        # independent of the next, so the break changes nothing.
        yield "claims"


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
    """One day of AI commander orders, run whole -- see
    run_commander_ai_steps, which this drains."""
    for _ in run_commander_ai_steps(world):
        pass


def run_commander_ai_steps(world):
    """Walk each AI faction's commander toward the frontier.

    Yields between factions: working out where a commander should march
    involves a real frontier scan and a path search, and as one call across
    every faction it measured 99ms on a developed world -- past what a slice
    of a day may cost (see turn_runner.SLOW_PHASE_MS). One faction's orders
    touch only its own commander, so the breaks change nothing."""
    from app.world import commander as commander_mod
    for fac_idx, nation in enumerate(world.factions):
        yield "commander orders"
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
        # One territory scan for this faction, reused by every test below.
        fr = frontier_id_sets(world, fac_idx)
        useful = [r for r in frontier
                  if commander_mod.commander_can_reach(world, fac_idx, r)
                  and can_afford_claim(world, fac_idx, r,
                                       is_sea_only_claim(world, fac_idx, r, fr)) is None]
        if useful:
            continue
        # Head for the staging ground of the closest target: one of our OWN
        # regions bordering it, which is where the gate actually wants us.
        # Head for the cheapest handful -- claim cost scales with region size,
        # and marching to something unaffordable just relocates the problem.
        best = None
        targets = sorted(frontier, key=lambda r: sum(
            claim_cost(r, is_sea_only_claim(world, fac_idx, r, fr)).values()))[:6]
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
        fr = frontier_id_sets(world, fac_idx)     # scanned once, not per region
        affordable = [r for r in reachable
                      if can_afford_claim(world, fac_idx, r,
                                          is_sea_only_claim(world, fac_idx, r, fr)) is None]
        if not affordable:
            continue
        region = random.choice(affordable)
        start_claim(world, fac_idx, region)
