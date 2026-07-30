"""Player- and AI-built settlements: cost real resources, take real turns, and
need a connecting road that's physically built cell-by-cell over time (using
the same terrain-aware pathfinding as trade routes/village roads) before
construction can run at full speed — modeling "the workers need a way to
get there."

Claiming wildland only ever hands out villages now (see
app/world/expansion.py's settle_newly_claimed_region) — a City or Town has to
be built here, by hand, the same as a Castle always has been. AI factions get
the same requirement, so they need their own decision loop too: see
run_settlement_ai, wired into the turn loop alongside advance_projects.
"""
import math
import random

from app.world.worldgen import (OCEAN, Settlement, SETTLEMENT_TYPES,
                                SETTLEMENT_TAX_INCOME, _roll_population, _path_dijkstra,
                                _elev_cost, _SEA_COAST_REACH, _site_score,
                                _too_close_any, _mark_occupied_both,
                                _nearest_ocean_cell, _sea_cost, road_cells)
from app.world.lexicon import make_settlement_namer
from app.world.resources import (seed_prosperity, _SETTLEMENT_STORAGE_RESOURCES,
                                 settlement_storage_capacity)
from app.world import wrap
from app.world import resources
from app.world.nation import is_eliminated

# Cost/time to build each settlement kind. City is the crown jewel (biggest
# population range, POPULATION_RANGE in worldgen.py) so it's the steepest;
# Town is the cheap, fast starter settlement. Town/City run 5x their
# original resource cost, Castle 4x — all deliberately steep, multi-turn
# investments now that wildland claims never hand one out for free.
# Costs below use "Logs" where they used to say "Wood" -- "Wood" was
# never a real registry resource even before Phase 12, just a stand-in;
# the actual new-registry equivalent (RESOURCE_SPAWN's own note) is
# Logs/Hardwood/Softwood, split apart back in Phase 3. Logs is the plain
# structural-lumber one, so it's the natural fit for bulk construction.
SETTLEMENT_BUILD_COST = {
    "town": {"Logs": 1000, "Stone": 500, "Gold": 750},
    "castle": {"Stone": 1600, "Logs": 800, "Iron": 400, "Gold": 1200},
    "city": {"Logs": 1750, "Stone": 1500, "Iron": 750, "Gold": 2500},
}
SETTLEMENT_BUILD_TURNS = {"town": 20, "castle": 25, "city": 40}   # at full speed
ROAD_SPEED_PENALTY = 0.5         # project progress rate while its road is incomplete
ROAD_CELLS_PER_TURN = 6          # how much of the route gets physically drawn each turn
_BBOX_PAD = 20

SHIPYARD_COST = {"Logs": 600, "Gold": 200}
SHIPYARD_BUILD_TURNS = 30        # deliberately steep -- "large amount of wood, very long cost"

# --- Storage buildings (Phase 4 of the storage rework) -----------------------
# Each typed storage pool has a building that extends it, and each building
# tiers up rather than being a single flat one-shot bonus. See
# resources.STORAGE_TIER_BONUS for the capacity each tier actually grants.
#
# Costs are paid overwhelmingly in Planks/Bricks/Stone/Tools/Logs, and that is
# the point rather than flavour: those durable Mining/Forestry goods are the
# ones measured at 88-90% of everything in storage precisely because nothing
# consumes them. Making them the currency of storage expansion gives the pile
# its missing sink, and closes the loop -- your surplus timber becomes the
# buildings that keep your grain.
#
# Costs climb steeply per tier so a fully-upgraded network is a real
# late-game investment, while tier 1 stays a reachable early one.
STORAGE_BUILD_COSTS = {
    "granary": [
        None,
        {"Logs": 300, "Stone": 100, "Gold": 150},
        {"Planks": 260, "Bricks": 180, "Stone": 220, "Gold": 420},
        {"Planks": 620, "Bricks": 520, "Tools": 180, "Gold": 1100},
    ],
    "warehouse": [
        None,
        {"Logs": 250, "Stone": 200, "Gold": 150},
        {"Planks": 300, "Bricks": 240, "Stone": 260, "Gold": 450},
        {"Planks": 700, "Bricks": 600, "Tools": 220, "Gold": 1200},
    ],
    "vault": [
        None,
        {"Stone": 320, "Iron": 120, "Gold": 300},
        {"Stone": 700, "Iron": 300, "Tools": 160, "Gold": 900},
    ],
    # Preserving House (Phase 5) -- rides the same project/tier machinery as
    # the three pool buildings, but buys conversion throughput instead of
    # capacity (see resources.PRESERVING_CAP_MULT). Cheapest of the four at
    # tier 1 on purpose: a fishing village losing its whole catch to spoilage
    # should be able to fix that early, not after a full industrial base.
    # Tier 1 is timber and coin only -- deliberately no Stone. It is a
    # smokehouse, a wooden shed, and gating the game's only answer to
    # spoilage behind a quarry meant a faction with no stone-bearing region
    # could never fix a rotting food supply at all. Measured: AI factions
    # were eligible to build one 308 times over 30 turns and affording it
    # zero times, most often for want of Stone they had none of.
    "preserving_house": [
        None,
        {"Logs": 120, "Gold": 60},
        {"Planks": 220, "Stone": 160, "Tools": 100, "Gold": 450},
    ],
    # Herd buildings (village-only -- see resources.HERD_BUILDINGS). Priced
    # like farm infrastructure rather than industry: timber, a little stone,
    # modest coin. The Slaughterhouse wants Tools because it is the one that
    # is actually a workshop.
    "pasture":        [None, {"Logs": 90, "Gold": 70}],
    "barn":           [None, {"Logs": 180, "Stone": 60, "Gold": 110}],
    "stable":         [None, {"Logs": 160, "Stone": 80, "Gold": 140}],
    "slaughterhouse": [None, {"Logs": 140, "Tools": 40, "Gold": 130}],
}
STORAGE_BUILD_TURNS = {"granary": [0, 15, 22, 30],
                       "warehouse": [0, 15, 22, 30],
                       "vault": [0, 18, 28],
                       "preserving_house": [0, 12, 20],
                       "pasture": [0, 8], "barn": [0, 14],
                       "stable": [0, 12], "slaughterhouse": [0, 10]}

# A village builds smaller and cheaper than a settlement -- but it can build,
# which it never could before. Villages were over capacity 78% of the time in
# the measurements with no lever of any kind available to them.
VILLAGE_STORAGE_COST_MULT = 0.45
VILLAGE_STORAGE_TURNS_MULT = 0.7

# Legacy aliases (old saves / callers predating tiers).
GRANARY_COST = STORAGE_BUILD_COSTS["granary"][1]
GRANARY_BUILD_TURNS = STORAGE_BUILD_TURNS["granary"][1]
WAREHOUSE_COST = STORAGE_BUILD_COSTS["warehouse"][1]
WAREHOUSE_BUILD_TURNS = STORAGE_BUILD_TURNS["warehouse"][1]


class RoadProject:
    """A road under construction: `built_index` is how much of the final
    `path` is actually visible/traversable so far — grows by
    ROAD_CELLS_PER_TURN every turn until it reaches the end. `tier` is
    fixed at creation (not re-derived from what the endpoints happen to be)
    since the caller already knows: "stone" for a settlement-to-settlement
    connector (Castle/City/Town roads), "dirt" for anything touching a
    village (see expansion.ensure_interregion_roads)."""

    def __init__(self, faction_idx, path, tier="stone"):
        self.faction_idx = faction_idx
        self.path = path
        self.built_index = 0
        self.tier = tier

    @property
    def complete(self):
        return self.built_index >= len(self.path) - 1

    @property
    def built_cells(self):
        return self.path[:self.built_index + 1]


class SettlementProject:
    """A City, Town, or Castle under construction — one class for all three
    since they only ever differed in cost/turns (SETTLEMENT_BUILD_COST/
    SETTLEMENT_BUILD_TURNS) and the resulting Settlement's `kind`."""

    def __init__(self, faction_idx, pos, region_id, road, kind, sea_lane=None):
        self.faction_idx = faction_idx
        self.pos = pos
        self.region_id = region_id
        self.road = road            # RoadProject or None (already connected)
        self.kind = kind            # "city" | "town" | "castle"
        # Open-water path to the nearest existing settlement, set instead of
        # `road` when no land connection exists at all (a new coastal city on
        # a different landmass) -- see _find_road_path. No construction phase
        # of its own (nothing physical to build across open water, same
        # reasoning trade.py's sea trade routes use), so it's just folded
        # straight into the road network once the settlement itself finishes
        # -- see _finish_settlement.
        self.sea_lane = sea_lane
        self.total_turns = SETTLEMENT_BUILD_TURNS[kind]
        self.progress_turns = 0.0

    @property
    def turns_left(self):
        # ceil, not round: progress advances by half-turns while the road is
        # unfinished, and round()'s banker's-rounding on those .5 values made
        # the displayed countdown skip a number some turns and hold for two
        # others (e.g. 4 -> 4 -> 6), instead of ticking down steadily.
        return max(0, math.ceil(self.total_turns - self.progress_turns))

    @property
    def half_speed(self):
        return self.road is not None and not self.road.complete


class ShipyardProject:
    """A shipyard under construction at an existing coastal city -- no road
    to build (it's sited in place), just a long flat time+resource sink."""

    def __init__(self, faction_idx, settlement_id):
        self.faction_idx = faction_idx
        self.settlement_id = settlement_id
        self.total_turns = SHIPYARD_BUILD_TURNS
        self.progress_turns = 0.0

    @property
    def turns_left(self):
        return max(0, math.ceil(self.total_turns - self.progress_turns))


def _is_coastal(world, pos):
    """BFS out from `pos` up to _SEA_COAST_REACH steps looking for open
    water -- the same reach trade._coastal_factions applies (there, via a
    single map-wide BFS from every ocean cell; here, just for one point, so
    a small local search is cheaper than that)."""
    x0, y0 = pos
    if world.owner[y0][x0] == OCEAN:
        return False
    seen = {pos}
    frontier = [pos]
    for _ in range(_SEA_COAST_REACH):
        nxt = []
        for x, y in frontier:
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if not (0 <= nx < world.w and 0 <= ny < world.h) or (nx, ny) in seen:
                    continue
                if world.owner[ny][nx] == OCEAN:
                    return True
                seen.add((nx, ny))
                nxt.append((nx, ny))
        frontier = nxt
    return False


def can_build_shipyard(world, settlement):
    if settlement.kind != "city":
        return False
    if getattr(settlement, "has_shipyard", False):
        return False
    if any(p.settlement_id == settlement.id for p in world.shipyard_projects):
        return False
    return _is_coastal(world, settlement.pos)


def start_shipyard(world, nation, settlement):
    """Validate and kick off building a shipyard at an existing coastal
    city. Returns a message describing what happened (success or why not)."""
    if not can_build_shipyard(world, settlement):
        return "A shipyard can't be built there."
    if not can_afford(nation, SHIPYARD_COST, world):
        return "You don't have enough resources to start construction."

    _pay_cost(nation, SHIPYARD_COST, world)

    project = ShipyardProject(settlement.faction_idx, settlement.id)
    world.shipyard_projects.append(project)
    return f"Shipyard construction begins — estimated {project.total_turns} turns."


def advance_shipyard_projects(world):
    finished = []
    for project in world.shipyard_projects:
        project.progress_turns += 1.0
        if project.progress_turns >= project.total_turns:
            finished.append(project)
    for project in finished:
        st = next((s for s in world.settlements if s.id == project.settlement_id), None)
        if st is not None:
            st.has_shipyard = True
        world.shipyard_projects.remove(project)


class GranaryProject:
    """A granary under construction -- see resources.py's Phase 9 storage
    section for what it actually adds once built. No road, no site
    restriction (any settlement kind can build one), just a flat
    time+resource sink, same shape as ShipyardProject."""

    def __init__(self, faction_idx, settlement_id):
        self.faction_idx = faction_idx
        self.settlement_id = settlement_id
        self.total_turns = GRANARY_BUILD_TURNS
        self.progress_turns = 0.0

    @property
    def turns_left(self):
        return max(0, math.ceil(self.total_turns - self.progress_turns))


class WarehouseProject:
    """A warehouse under construction -- same shape as GranaryProject."""

    def __init__(self, faction_idx, settlement_id):
        self.faction_idx = faction_idx
        self.settlement_id = settlement_id
        self.total_turns = WAREHOUSE_BUILD_TURNS
        self.progress_turns = 0.0

    @property
    def turns_left(self):
        return max(0, math.ceil(self.total_turns - self.progress_turns))


class StorageProject:
    """A storage building being built or upgraded, at a Settlement or a
    Village. One class for all three buildings and every tier -- what it is
    building is `building` ("granary"/"warehouse"/"vault") and `to_tier`.

    Targets a node by (kind, id) rather than a bare settlement_id because
    Villages can build these now too; `node_kind` is "settlement" or
    "village"."""

    def __init__(self, faction_idx, node_kind, node_id, building, to_tier,
                 total_turns):
        self.faction_idx = faction_idx
        self.node_kind = node_kind
        self.node_id = node_id
        self.building = building
        self.to_tier = to_tier
        self.total_turns = total_turns
        self.progress_turns = 0.0

    @property
    def turns_left(self):
        return max(0, math.ceil(self.total_turns - self.progress_turns))

    def node(self, world):
        if self.node_kind == "village":
            return next((v for v in world.villages if v.id == self.node_id), None)
        return next((s for s in world.settlements if s.id == self.node_id), None)


def _node_kind_of(node):
    return "settlement" if hasattr(node, "kind") else "village"


def _storage_projects(world):
    """The live StorageProject list, created on demand so worlds pickled
    before this existed pick it up on load rather than needing a migration."""
    projects = getattr(world, "storage_projects", None)
    if projects is None:
        projects = []
        world.storage_projects = projects
    return projects


def storage_build_cost(node, building, to_tier):
    """Resource cost to take `node`'s `building` up to `to_tier`, or None if
    that tier doesn't exist for this kind of node."""
    costs = STORAGE_BUILD_COSTS.get(building)
    if not costs or to_tier <= 0 or to_tier >= len(costs):
        return None
    if to_tier > resources.storage_max_tier(node, building):
        return None
    cost = costs[to_tier]
    if _node_kind_of(node) == "village":
        return {r: max(1, round(a * VILLAGE_STORAGE_COST_MULT))
                for r, a in cost.items()}
    return dict(cost)


def storage_build_turns(node, building, to_tier):
    turns = STORAGE_BUILD_TURNS.get(building, [0])
    t = turns[min(to_tier, len(turns) - 1)]
    if _node_kind_of(node) == "village":
        t = max(1, round(t * VILLAGE_STORAGE_TURNS_MULT))
    return t


def storage_next_tier(world, node, building):
    """The tier a new project at `node` would build toward, or None if it's
    already maxed for this node kind or has one underway."""
    if any(p.node_kind == _node_kind_of(node) and p.node_id == node.id
           and p.building == building for p in _storage_projects(world)):
        return None
    current = resources.storage_tier(node, building)
    if current >= resources.storage_max_tier(node, building):
        return None
    return current + 1


def can_build_storage(world, node, building):
    return storage_next_tier(world, node, building) is not None


def start_storage_building(world, nation, node, building):
    """Validate and kick off building (or upgrading) `building` at `node`.
    Returns a message describing what happened, success or why not."""
    label = building.replace("_", " ").title()
    to_tier = storage_next_tier(world, node, building)
    if to_tier is None:
        current = resources.storage_tier(node, building)
        if current >= resources.storage_max_tier(node, building):
            return f"{node.name}'s {label} is already at its highest tier."
        return f"Work on {node.name}'s {label} is already underway."
    cost = storage_build_cost(node, building, to_tier)
    if cost is None:
        return f"A {label} can't be built there."
    if not can_afford(nation, cost, world):
        return "You don't have enough resources to start construction."

    _pay_cost(nation, cost, world)
    _storage_projects(world).append(StorageProject(
        node.faction_idx, _node_kind_of(node), node.id, building, to_tier,
        storage_build_turns(node, building, to_tier)))
    verb = "Upgrading" if to_tier > 1 else "Building"
    return f"{verb} {label} (tier {to_tier}) at {node.name}."


def advance_storage_projects(world):
    """Tick every storage build/upgrade; completed ones set the node's tier."""
    projects = _storage_projects(world)
    finished = []
    for project in projects:
        project.progress_turns += 1.0
        if project.progress_turns >= project.total_turns:
            finished.append(project)
    for project in finished:
        node = project.node(world)
        if node is not None:
            resources.set_storage_tier(node, project.building, project.to_tier)
        projects.remove(project)


# --- legacy single-tier API, kept so existing callers/saves keep working -----
def can_build_granary(world, settlement):
    return can_build_storage(world, settlement, "granary")


def can_build_warehouse(world, settlement):
    return can_build_storage(world, settlement, "warehouse")


def start_granary(world, nation, settlement):
    return start_storage_building(world, nation, settlement, "granary")


def _start_granary_legacy(world, nation, settlement):
    if not can_build_granary(world, settlement):
        return "A granary can't be built there."
    if not can_afford(nation, GRANARY_COST, world):
        return "You don't have enough resources to start construction."

    _pay_cost(nation, GRANARY_COST, world)

    project = GranaryProject(settlement.faction_idx, settlement.id)
    world.granary_projects.append(project)
    return f"Granary construction begins — estimated {project.total_turns} turns."


def start_warehouse(world, nation, settlement):
    return start_storage_building(world, nation, settlement, "warehouse")


def advance_granary_projects(world):
    """Legacy tick, for saves written before StorageProject existed and still
    carrying GranaryProject entries. Completing one now sets tier 1 rather
    than a bare boolean, so it lands in the same model as everything else."""
    finished = []
    for project in getattr(world, "granary_projects", []):
        project.progress_turns += 1.0
        if project.progress_turns >= project.total_turns:
            finished.append(project)
    for project in finished:
        st = next((s for s in world.settlements if s.id == project.settlement_id), None)
        if st is not None:
            resources.set_storage_tier(st, "granary", 1)
        world.granary_projects.remove(project)


def advance_warehouse_projects(world):
    """Legacy tick -- see advance_granary_projects."""
    finished = []
    for project in getattr(world, "warehouse_projects", []):
        project.progress_turns += 1.0
        if project.progress_turns >= project.total_turns:
            finished.append(project)
    for project in finished:
        st = next((s for s in world.settlements if s.id == project.settlement_id), None)
        if st is not None:
            resources.set_storage_tier(st, "warehouse", 1)
        world.warehouse_projects.remove(project)


def _path_between(world, origin, dest_pos, faction_idx=None, allow_fallback=True):
    """Terrain-aware path between two specific points — the same Dijkstra +
    elevation-cost machinery worldgen already uses for trade routes/roads,
    so this can't cross a mountain or river any more than anything else in
    the game does. Shared by _find_road_path (nearest existing settlement
    to a new one) and expansion.ensure_interregion_roads (village to
    village across a region border).

    `faction_idx`, when given, makes the path strongly (not absolutely)
    prefer this faction's own territory over land owned by someone else —
    see _elev_cost's own faction_idx param for why this only makes sense
    for road pathing specifically, not every caller of this function.

    `allow_fallback` controls what happens when no land route exists at
    all: True (the default, used by every caller for whom the two points
    are guaranteed to share a landmass, e.g. neighboring regions) returns
    the straight two-point segment rather than fail outright, on the
    assumption any miss is a rare local pathfinding quirk. _find_road_path
    passes False, because for it a miss can mean the two points genuinely
    sit on different landmasses -- and drawing a straight "road" across
    open ocean was exactly the reported bug this exists to avoid."""
    if origin == dest_pos:
        return [origin]
    oy, dy = origin[1], dest_pos[1]
    y0, y1 = sorted((oy, dy))
    by0 = max(0, y0 - _BBOX_PAD)
    by1 = min(world.h, y1 + _BBOX_PAD + 1)
    xs = wrap.bbox_span_wrap(origin[0], dest_pos[0], world.w, _BBOX_PAD)
    land_cellset = {(x, y) for y in range(by0, by1) for x in xs
                     if world.owner[y][x] != OCEAN}
    roads = road_cells(world)
    path = _path_dijkstra(land_cellset,
                          lambda c: _elev_cost(world, world.base_cost, c,
                                               faction_idx, roads=roads),
                          origin, dest_pos, world.w)
    if path is not None:
        return path
    return [origin, dest_pos] if allow_fallback else None


_SEA_LANE_BBOX_PAD = 30   # matches trade._TRADE_BBOX_PAD's reach for the same
                          # kind of dock-to-dock open-water search


def _sea_lane_between(world, a_pos, b_pos):
    """Open-water path between the coastal points nearest `a_pos`/`b_pos`,
    or None if either isn't within reach of the sea or no water connection
    exists in the search box -- the same dock-to-dock Dijkstra
    trade._capital_sea_path uses for cross-faction sea trade, reused here
    for _find_road_path's same-faction case. Not cached: unlike the AI's
    per-turn trade lookups, this only ever runs once, at the moment a
    settlement is founded."""
    dock_a = _nearest_ocean_cell(world, a_pos)
    dock_b = _nearest_ocean_cell(world, b_pos)
    if not dock_a or not dock_b:
        return None
    ay, by = a_pos[1], b_pos[1]
    y0, y1 = sorted((ay, by))
    by0 = max(0, y0 - _SEA_LANE_BBOX_PAD)
    by1 = min(world.h, y1 + _SEA_LANE_BBOX_PAD + 1)
    xs = wrap.bbox_span_wrap(a_pos[0], b_pos[0], world.w, _SEA_LANE_BBOX_PAD)
    sea_cellset = {(x, y) for y in range(by0, by1) for x in xs
                   if world.owner[y][x] == OCEAN}
    sea_path = _path_dijkstra(sea_cellset,
                              lambda c: _sea_cost(world, world.base_cost, c),
                              dock_a, dock_b, world.w)
    if sea_path is None:
        return None
    return [a_pos] + sea_path + [b_pos]


def _find_road_path(world, faction_idx, dest_pos):
    """("land"|"sea", path) connecting one of this faction's existing
    settlements to `dest_pos`, or (None, None) if nothing connects at all.

    Tries every candidate settlement, nearest first, for a land route; only
    if NONE of them has one -- a new coastal city on a different landmass
    from every settlement this faction already owns -- does it try again,
    nearest first, for a sea lane instead. Checking every candidate (not
    just the single nearest) matters because "nearest" and "coastal" don't
    have to be the same settlement: a faction's capital is often well
    inland, and it'd be wrong to call a new island city unreachable just
    because the closest existing settlement by raw distance happens to have
    no coast of its own, when a farther one does.

    Never fakes a straight road across open ocean when no land route
    exists -- that was the reported bug: a brand new settlement used to
    get a literal straight "stone" road drawn through the sea to whichever
    existing settlement happened to be nearest as the crow flies. If even
    a sea lane fails for every candidate (no coast anywhere, or every water
    route is out of search range), the settlement still gets built, it
    just starts with no connector at all, same as any other genuinely
    isolated case in this game."""
    candidates = [st.pos for st in world.settlements if st.faction_idx == faction_idx]
    candidates = sorted((p for p in candidates if p != dest_pos),
                        key=lambda p: wrap.dist2_wrap(p, dest_pos, world.w))
    if not candidates:
        return None, None
    for origin in candidates:
        land = _path_between(world, origin, dest_pos, faction_idx=faction_idx,
                             allow_fallback=False)
        if land is not None:
            return "land", land
    for origin in candidates:
        sea = _sea_lane_between(world, origin, dest_pos)
        if sea is not None:
            return "sea", sea
    return None, None


def _faction_nodes(nation, world):
    """Every Settlement AND Village this faction owns -- "our country's
    whole pool of resources" the player actually expects to draw on when
    building something, not just whatever happens to already be sitting
    in a Settlement specifically. A Village can hold real stock too (see
    this session's Regional Markets widening), and there's no reason a
    stockpile of Logs sitting in a border village shouldn't count toward
    a City's construction cost just because it hasn't been physically
    hauled to the City yet -- the same "hauled in from wherever it's
    stockpiled" abstraction _pay_cost below already applies across
    multiple settlements."""
    fac_idx = world.factions.index(nation)
    nodes = [world.settlements[sid] for sid in nation.meta.get("settlements", [])]
    nodes += [v for v in world.villages if v.faction_idx == fac_idx]
    return nodes


def _faction_settlement_stock(nation, resource, world):
    """Sum of `resource` across every settlement AND village this faction
    owns -- same aggregate-economy view trade.py's _faction_settlement_total
    and resources.py's _recompute_military already need for the same reason
    (Phase 12: Logs/Stone/Iron are settlement-storage resources now, no
    longer one national number). Kept this name (not just settlements
    despite it) since it's the established call site everywhere else in
    the codebase already uses."""
    return sum(getattr(node, "resources", {}).get(resource, 0)
              for node in _faction_nodes(nation, world))


def can_afford(nation, cost, world):
    """Anything in _SETTLEMENT_STORAGE_RESOURCES (as of Phase 12, that
    includes Logs/Stone/Iron -- see resources.py's Industry Specialization
    section; as of the Currency overhaul, Gold too -- see resources.py's
    Currency section) from the faction's settlements in aggregate; anything
    else from the old shared national pool (nothing left in these cost
    dicts falls in that last bucket any more, but this stays generic
    rather than assuming that never changes)."""
    for resource, amount in cost.items():
        if resource in _SETTLEMENT_STORAGE_RESOURCES:
            if _faction_settlement_stock(nation, resource, world) < amount:
                return False
        elif nation.stats.get("resources", {}).get(resource, 0) < amount:
            return False
    return True


def _pay_cost(nation, cost, world):
    """Deduct `cost` from `nation`, the spending half of can_afford -- a
    settlement-storage resource (Gold included, as of the Currency
    overhaul) spread across whichever of the faction's Settlements AND
    Villages actually have it (largest stockpile first, the realistic
    "hauled in from wherever it's stockpiled" reading -- the same
    aggregate-economy assumption trade.py's sellable_surplus already
    makes, see _faction_nodes above for why Villages count too), anything
    else from the old shared pool. Caller must have already confirmed
    can_afford."""
    for resource, amount in cost.items():
        if resource in _SETTLEMENT_STORAGE_RESOURCES:
            remaining = amount
            ordered = sorted(_faction_nodes(nation, world),
                             key=lambda node: getattr(node, "resources", {}).get(resource, 0),
                             reverse=True)
            for node in ordered:
                if remaining <= 0:
                    break
                if not hasattr(node, "resources"):
                    node.resources = {}
                have = node.resources.get(resource, 0)
                take = min(have, remaining)
                if take:
                    node.resources[resource] = have - take
                    remaining -= take
        else:
            res = nation.stats.setdefault("resources", {})
            res[resource] = res.get(resource, 0) - amount


def start_settlement(world, nation, pos, kind):
    """Validate and kick off building a City, Town, or Castle at `pos` for
    `nation`'s own faction (works for the player or an AI nation alike —
    see run_settlement_ai). Returns a message describing what happened
    (success or why not)."""
    x, y = pos
    if not (0 <= x < world.w and 0 <= y < world.h):
        return "That's outside the map."
    faction_idx = world.factions.index(nation)
    if world.owner[y][x] != faction_idx:
        return "You can only build within your own territory."
    region_id = world.region_grid[y][x]
    if region_id < 0:
        return "That location isn't part of any region."
    if any(st.pos == pos for st in world.settlements):
        return "There's already a settlement there."
    if any(p.pos == pos for p in world.settlement_projects):
        return "Construction is already underway there."
    if any(v.pos == pos for v in world.villages):
        return "There's already a village there."
    cost = SETTLEMENT_BUILD_COST[kind]
    if not can_afford(nation, cost, world):
        return "You don't have enough resources to start construction."

    _pay_cost(nation, cost, world)

    tier, road_path = _find_road_path(world, faction_idx, pos)
    road = RoadProject(faction_idx, road_path) if tier == "land" else None
    sea_lane = road_path if tier == "sea" else None
    project = SettlementProject(faction_idx, pos, region_id, road, kind,
                                sea_lane=sea_lane)
    world.settlement_projects.append(project)
    if road is not None:
        world.road_projects.append(road)
    return (f"Construction begins on a new {kind} — estimated "
            f"{project.total_turns} turns.")


def _finish_settlement(world, project):
    kind = project.kind
    faction = world.factions[project.faction_idx]
    species = faction.meta.get("species", "Humans")
    namer = make_settlement_namer(random)
    tax_income = round(random.uniform(*SETTLEMENT_TAX_INCOME[kind]))
    population, adults, children, max_population = _roll_population(random, kind)
    prosperity = seed_prosperity()
    st = Settlement(len(world.settlements), kind, namer(kind, species),
                    project.pos, project.faction_idx, project.region_id, tax_income,
                    population, adults, children, prosperity, max_population)
    world.settlements.append(st)
    _mark_occupied_both(world, *project.pos)
    faction.meta.setdefault("settlements", []).append(st.id)
    if 0 <= project.region_id < len(world.regions):
        region = world.regions[project.region_id]
        if not hasattr(region, "meta_settlements"):
            region.meta_settlements = []
        region.meta_settlements.append(st.id)
    sea_lane = getattr(project, "sea_lane", None)
    if sea_lane:
        segs = world.roads_by_region.setdefault(project.region_id, [])
        segs.extend((p1, p2, "sea") for p1, p2 in zip(sea_lane, sea_lane[1:]))


def _finish_road(world, road):
    """Fold a completed road into the permanent per-region road network so
    it renders like any other established road from then on, at whichever
    tier the project was created with (see RoadProject)."""
    x, y = road.path[-1]
    if not (0 <= x < world.w and 0 <= y < world.h):
        return
    region_id = world.region_grid[y][x]
    if region_id < 0:
        return
    segs = world.roads_by_region.setdefault(region_id, [])
    segs.extend((a, b, road.tier) for a, b in zip(road.path, road.path[1:]))


def advance_projects(world):
    """Called every turn (alongside the trade hooks): grow roads, advance
    settlement projects (at half speed while their road is unfinished), and
    finalize anything that's crossed the finish line."""
    for road in world.road_projects:
        if not road.complete:
            road.built_index = min(len(road.path) - 1, road.built_index + ROAD_CELLS_PER_TURN)

    finished_projects = []
    for project in world.settlement_projects:
        rate = ROAD_SPEED_PENALTY if project.half_speed else 1.0
        project.progress_turns += rate
        if project.progress_turns >= project.total_turns:
            finished_projects.append(project)
    for project in finished_projects:
        _finish_settlement(world, project)
        world.settlement_projects.remove(project)

    finished_roads = [r for r in world.road_projects if r.complete]
    for road in finished_roads:
        _finish_road(world, road)
        world.road_projects.remove(road)


# --- AI construction/expansion pacing ----------------------------------------
def _ai_has_active_construction(world, fac_idx):
    """Whether this AI faction currently has ANY construction or expansion
    project in flight -- a settlement, a Granary/Warehouse/Shipyard, or a
    wildland claim. Every AI decision loop (run_settlement_ai,
    run_storage_ai, expansion.run_expansion_ai) checks this first and
    skips the faction entirely if it's already busy, capping every AI
    faction at ONE such project at a time regardless of how wealthy it
    is. That's the actual safeguard against a well-funded faction chain-
    building across many regions at once and overrunning the map far
    faster than a player (or a poorer AI) ever could -- growth is paced
    by build TIME (15-40 turns per project) instead of by treasury size,
    the same "deliberately simple" philosophy the rest of this AI already
    uses rather than a more elaborate scoring/budget system."""
    if any(p.faction_idx == fac_idx for p in world.settlement_projects):
        return True
    if any(p.faction_idx == fac_idx for p in world.granary_projects):
        return True
    if any(p.faction_idx == fac_idx for p in world.warehouse_projects):
        return True
    # Only SETTLEMENT-scale storage works occupy the single major-build slot.
    # Village-scale ones (a barn, a pasture, a village granary) are counted
    # separately -- see _ai_village_project_count. This gate exists to stop a
    # rich faction chain-building settlements across the map faster than a
    # player could; a village hay barn is not that, and lumping the two
    # together meant the AI never built a single village building in a
    # 110-turn run because the slot was always taken by something bigger.
    if any(p.faction_idx == fac_idx and p.node_kind == "settlement"
           for p in _storage_projects(world)):
        return True
    if any(p.faction_idx == fac_idx for p in world.shipyard_projects):
        return True
    if any(p.faction_idx == fac_idx for p in world.claim_projects):
        return True
    return False


# --- AI settlement construction ----------------------------------------------
def _region_settlement_pos(world, region, kind):
    """The best-scoring free cell in `region` for `kind`, using the same
    _site_score formula world-gen placement uses (worldgen.py) instead of
    a blind random.choice -- an AI City now actually seeks fertile/
    riverside/coastal land, a Castle actually seeks the frontier and high
    ground, the same as a freshly generated world's own settlements do.

    Excludes rivers, and anything already a settlement, village, or under
    construction — a region can easily have villages but no settlement yet
    (the normal outcome of a wildland claim), so this is exactly the kind
    of region run_settlement_ai targets and villages must be excluded here
    too, not just other settlements. Falls back to the best-scoring cell
    even if nothing clears the usual minimum spacing (worldgen.py's
    _too_close_any, checked against world-gen's own occupancy hashes plus
    every settlement finished since — see _finish_settlement's
    _mark_occupied_both call) rather than refusing to build at all just
    because the region is a tight fit. None only if the region has no
    free land whatsoever."""
    occupied = {st.pos for st in world.settlements}
    occupied.update(p.pos for p in world.settlement_projects)
    occupied.update(world.villages[vid].pos for vid in region.villages)
    candidates = [c for c in region.cells
                 if c not in world.river_cells and c not in occupied]
    if not candidates:
        return None
    coast_d = world._settle_coast_d
    water_d = world._settle_water_d
    border_d = world._settle_border_d
    weights = SETTLEMENT_TYPES[kind]
    scored = sorted(
        ((_site_score(world, weights, x, y, coast_d, water_d, border_d, random), x, y)
         for x, y in candidates), reverse=True)
    for s, x, y in scored:
        if not _too_close_any(world, x, y, weights["spacing"]):
            return (x, y)
    return scored[0][1], scored[0][2]


def run_settlement_ai(world):
    """Every AI faction's equivalent of the player clicking "Build City"/
    "Build Town"/"Build Castle": claiming wildland only ever yields
    villages now (see expansion.settle_newly_claimed_region), so a
    faction has to actually construct its own settlements the same way
    the player does -- and the player can build any of the three kinds
    anywhere in their own territory, so AI gets the same menu. Skips a
    faction entirely if it already has any construction/expansion project
    in flight (see _ai_has_active_construction) -- the actual anti-
    overbuild safeguard, not just "no second settlement project" -- and
    targets a region it owns that has no settlements in it yet, reaching
    for the priciest/most-capable kind it can currently afford (City,
    then Castle, then Town), scored per-kind against that region's own
    land via _region_settlement_pos rather than one random cell for
    whichever kind happened to be affordable. No catching up a faction
    that's fallen behind faster than one project at a time."""
    for fac_idx, nation in enumerate(world.factions):
        if fac_idx == world.player_faction_idx or is_eliminated(nation):
            continue
        if _ai_has_active_construction(world, fac_idx):
            continue
        empty_regions = [r for r in world.regions
                         if r.faction_idx == fac_idx and not getattr(r, "meta_settlements", [])]
        if not empty_regions:
            continue
        region = random.choice(empty_regions)
        for kind in ("city", "castle", "town"):
            if not can_afford(nation, SETTLEMENT_BUILD_COST[kind], world):
                continue
            pos = _region_settlement_pos(world, region, kind)
            if pos is not None:
                start_settlement(world, nation, pos, kind)
            break


# --- AI storage construction ---------------------------------------------
AI_MAX_VILLAGE_PROJECTS = 3   # concurrent village-scale works per AI faction,
                              # independent of the single major-build slot
HERD_AI_CAPACITY_THRESHOLD = 0.85   # herd/land ratio at which a Pasture pays
HERD_AI_SLAUGHTERHOUSE_HEAD = 40    # head before butchering efficiency matters
HERD_AI_STABLE_HORSES = 12          # horses before a Stable is worth the slot
PRESERVE_AI_THRESHOLD = 12   # perishable arriving per turn (fish_yield, plus a
                             # tenth of standing Fish/Milk/Meat) before the AI
                             # thinks a Preserving House is worth a build slot
STORAGE_AI_PRESSURE_THRESHOLD = 0.8   # trigger a Granary/Warehouse once a
                                      # settlement's own storage is at
                                      # least this full -- a real reason,
                                      # not blind busywork: the same
                                      # "storage is under real pressure"
                                      # signal the player's own storage
                                      # progress bar/overflow-spoilage
                                      # penalty already make visible


def _ai_village_project_count(world, fac_idx):
    return sum(1 for p in _storage_projects(world)
               if p.faction_idx == fac_idx and p.node_kind == "village")


def _herd_building_pressure(world, node):
    """[(pressure, node, building), ...] for the herd buildings this village
    has a real reason to want.

    Without this the AI paid the entire cost of the feed system and used none
    of its mitigations -- it never built a Barn or a Pasture, so herds were
    culled every Winter for want of hay that a Barn would have stored and
    sheltered. Each building is triggered by the specific problem it solves,
    not by generic prosperity."""
    herds = getattr(node, "herds", None)
    if not herds or hasattr(node, "kind"):
        return []          # settlements keep no animals
    out = []
    need = resources.village_winter_fodder_need(node)
    if need <= 0:
        return out

    # Barn: triggered by actually having FAILED to feed the herd last Winter,
    # not by storage capacity. Capacity was the first thing tried and built
    # nothing, because the base feed pool already covers a typical herd -- the
    # villages losing animals were short of hay itself, not of somewhere to
    # put it. A Barn cuts the Winter fodder need by a quarter and deaths by a
    # fifth, which is exactly the right answer to that. Same lesson as the
    # Preserving House: trigger on the outcome, not on a stock level.
    if getattr(node, "herd_fed", None) is False:
        out.append((1.4, node, "barn"))
    elif resources.node_pool_capacity(node, "feed") < need * resources.FODDER_STOCK_BUFFER:
        out.append((1.0, node, "barn"))   # can feed them, nowhere to keep the hay

    # Pasture: herd is pressing its land ceiling, so more animals need more
    # ground before anything else will help.
    head = sum(herds.values())
    capacity = sum(resources.village_herd_capacity(world, node, a) for a in herds)
    if capacity and head / capacity >= HERD_AI_CAPACITY_THRESHOLD:
        out.append((head / capacity, node, "pasture"))

    # Slaughterhouse: only worth it where there's a real cull to process.
    if head >= HERD_AI_SLAUGHTERHOUSE_HEAD:
        out.append((1.0, node, "slaughterhouse"))

    # Stable: horses specifically, which are the animal with a use beyond food.
    if herds.get("Horses", 0) >= HERD_AI_STABLE_HORSES:
        out.append((1.0, node, "stable"))
    return out


def run_storage_ai(world):
    """Every AI faction's equivalent of the player clicking "Build/Upgrade
    Granary": triggered by real storage pressure, not an unconditional
    habit. Skips a faction entirely if it already has any construction or
    expansion project in flight (see _ai_has_active_construction).

    Pressure is judged per typed pool (Phase 3) rather than on a node's
    total, and the building it starts is the one for the pool that's
    actually full -- a settlement drowning in timber gets a Warehouse, not
    whichever building happened to be cheapest. Villages are candidates too
    now (Phase 4): they were the most overflowing nodes on the map and had
    no building of their own until this.

    Deliberately simple: one node, one building, per faction per turn at
    most, same philosophy as run_settlement_ai."""
    for fac_idx, nation in enumerate(world.factions):
        if fac_idx == world.player_faction_idx or is_eliminated(nation):
            continue
        # A faction busy with a major build can still put up village works,
        # up to AI_MAX_VILLAGE_PROJECTS at once -- otherwise the whole
        # village-building layer is unreachable for the AI (see
        # _ai_has_active_construction).
        major_busy = _ai_has_active_construction(world, fac_idx)
        village_slots = AI_MAX_VILLAGE_PROJECTS - _ai_village_project_count(world, fac_idx)
        if major_busy and village_slots <= 0:
            continue

        nodes = []
        if not major_busy:
            nodes += [world.settlements[sid] for sid in nation.meta.get("settlements", [])]
        if village_slots > 0:
            nodes += [v for v in world.villages if v.faction_idx == fac_idx]
        if not nodes:
            continue

        pressured = []
        for node in nodes:
            for pool in resources.STORAGE_POOLS:
                cap = resources.node_pool_capacity(node, pool)
                if cap <= 0:
                    continue
                fill = resources.node_pool_stock(node, pool) / cap
                if fill >= STORAGE_AI_PRESSURE_THRESHOLD:
                    pressured.append((fill, node, resources.STORAGE_BUILDING_BY_POOL[pool]))
            # A Preserving House is driven by spoilage, not fullness -- a
            # fishing village can be losing its whole catch every turn while
            # its granary sits half empty, which no capacity check would ever
            # notice.
            #
            # Crucially this scores FLOW, not stock. Scoring stock was tried
            # first and built exactly zero houses: Fish spoils at 0.35, so it
            # never survives long enough to pile up: the map was losing 646k
            # of it over 60 turns while no node ever held more than a few
            # dozen at once. fish_yield is the honest signal -- it's what
            # arrives every turn, cached on the node, and it's what's being
            # thrown away.
            res = getattr(node, "resources", None) or {}
            stock = sum(res.get(src, 0) for src in
                        resources.PRESERVATION_RECIPES.values())
            score = (getattr(node, "fish_yield", 0) or 0) + stock * 0.1
            if score >= PRESERVE_AI_THRESHOLD:
                # Capped so a strong fishing node outranks a merely-full pool
                # without permanently starving every Granary in the realm of
                # the faction's one build slot.
                pressured.append((min(1.5, score / PRESERVE_AI_THRESHOLD), node,
                                  resources.PRESERVING_HOUSE))
            pressured.extend(_herd_building_pressure(world, node))
        if not pressured:
            continue

        # Worst pressure first, but fall through to the next candidate if that
        # one is maxed out or unaffordable -- otherwise a single permanently
        # full, fully-upgraded node would block the faction from ever
        # expanding storage anywhere else.
        pressured.sort(key=lambda t: -t[0])
        # Don't stack the same building type in every village slot. Without
        # this the AI simply worked down a queue of the single highest-pressure
        # type -- 54 Preserving Houses and not one Barn, because there is
        # always another unbuilt fishing village outranking every herd
        # problem in the realm. Preferring a type it isn't already building
        # spreads the three slots across the problems it actually has.
        in_flight = {p.building for p in _storage_projects(world)
                     if p.faction_idx == fac_idx}
        ordered = ([c for c in pressured if c[2] not in in_flight]
                   + [c for c in pressured if c[2] in in_flight])
        for _fill, node, building in ordered:
            to_tier = storage_next_tier(world, node, building)
            if to_tier is None:
                continue
            cost = storage_build_cost(node, building, to_tier)
            if cost is None or not can_afford(nation, cost, world):
                continue
            start_storage_building(world, nation, node, building)
            break
