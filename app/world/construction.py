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

from app.world.worldgen import (OCEAN, Settlement,
                                SETTLEMENT_TAX_INCOME, _roll_population, _path_dijkstra,
                                _elev_cost, _SEA_COAST_REACH)
from app.world.lexicon import make_settlement_namer
from app.world.resources import (seed_prosperity, _SETTLEMENT_STORAGE_RESOURCES,
                                 settlement_storage_capacity)
from app.world import wrap

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

# Phase 9 storage buildings -- see app/world/resources.py's
# GRANARY_STORAGE_BONUS/WAREHOUSE_STORAGE_BONUS for what they actually add
# once built. Steep but not Shipyard-steep: these are meant to be a real,
# reachable early investment, not a late-game luxury.
GRANARY_COST = {"Logs": 300, "Stone": 100, "Gold": 150}
GRANARY_BUILD_TURNS = 15
WAREHOUSE_COST = {"Logs": 250, "Stone": 200, "Gold": 150}
WAREHOUSE_BUILD_TURNS = 15


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

    def __init__(self, faction_idx, pos, region_id, road, kind):
        self.faction_idx = faction_idx
        self.pos = pos
        self.region_id = region_id
        self.road = road            # RoadProject or None (already connected)
        self.kind = kind            # "city" | "town" | "castle"
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


def can_build_granary(world, settlement):
    if getattr(settlement, "has_granary", False):
        return False
    return not any(p.settlement_id == settlement.id for p in world.granary_projects)


def can_build_warehouse(world, settlement):
    if getattr(settlement, "has_warehouse", False):
        return False
    return not any(p.settlement_id == settlement.id for p in world.warehouse_projects)


def start_granary(world, nation, settlement):
    """Validate and kick off building a granary at `settlement`. Returns a
    message describing what happened (success or why not)."""
    if not can_build_granary(world, settlement):
        return "A granary can't be built there."
    if not can_afford(nation, GRANARY_COST, world):
        return "You don't have enough resources to start construction."

    _pay_cost(nation, GRANARY_COST, world)

    project = GranaryProject(settlement.faction_idx, settlement.id)
    world.granary_projects.append(project)
    return f"Granary construction begins — estimated {project.total_turns} turns."


def start_warehouse(world, nation, settlement):
    """Validate and kick off building a warehouse at `settlement`. Returns
    a message describing what happened (success or why not)."""
    if not can_build_warehouse(world, settlement):
        return "A warehouse can't be built there."
    if not can_afford(nation, WAREHOUSE_COST, world):
        return "You don't have enough resources to start construction."

    _pay_cost(nation, WAREHOUSE_COST, world)

    project = WarehouseProject(settlement.faction_idx, settlement.id)
    world.warehouse_projects.append(project)
    return f"Warehouse construction begins — estimated {project.total_turns} turns."


def advance_granary_projects(world):
    finished = []
    for project in world.granary_projects:
        project.progress_turns += 1.0
        if project.progress_turns >= project.total_turns:
            finished.append(project)
    for project in finished:
        st = next((s for s in world.settlements if s.id == project.settlement_id), None)
        if st is not None:
            st.has_granary = True
        world.granary_projects.remove(project)


def advance_warehouse_projects(world):
    finished = []
    for project in world.warehouse_projects:
        project.progress_turns += 1.0
        if project.progress_turns >= project.total_turns:
            finished.append(project)
    for project in finished:
        st = next((s for s in world.settlements if s.id == project.settlement_id), None)
        if st is not None:
            st.has_warehouse = True
        world.warehouse_projects.remove(project)


def _path_between(world, origin, dest_pos, faction_idx=None):
    """Terrain-aware path between two specific points — the same Dijkstra +
    elevation-cost machinery worldgen already uses for trade routes/roads,
    so this can't cross a mountain or river any more than anything else in
    the game does. Shared by _find_road_path (nearest existing settlement
    to a new one) and expansion.ensure_interregion_roads (village to
    village across a region border).

    `faction_idx`, when given, makes the path strongly (not absolutely)
    prefer this faction's own territory over land owned by someone else —
    see _elev_cost's own faction_idx param for why this only makes sense
    for road pathing specifically, not every caller of this function."""
    if origin == dest_pos:
        return [origin]
    oy, dy = origin[1], dest_pos[1]
    y0, y1 = sorted((oy, dy))
    by0 = max(0, y0 - _BBOX_PAD)
    by1 = min(world.h, y1 + _BBOX_PAD + 1)
    xs = wrap.bbox_span_wrap(origin[0], dest_pos[0], world.w, _BBOX_PAD)
    land_cellset = {(x, y) for y in range(by0, by1) for x in xs
                     if world.owner[y][x] != OCEAN}
    path = _path_dijkstra(land_cellset,
                          lambda c: _elev_cost(world, world.base_cost, c, faction_idx),
                          origin, dest_pos, world.w)
    return path or [origin, dest_pos]   # fallback straight segment if pathfinding fails


def _find_road_path(world, faction_idx, dest_pos):
    """Terrain-aware path from the nearest existing settlement of this
    faction to `dest_pos`."""
    candidates = [st.pos for st in world.settlements if st.faction_idx == faction_idx]
    if not candidates:
        return [dest_pos]
    origin = min(candidates, key=lambda p: wrap.dist2_wrap(p, dest_pos, world.w))
    return _path_between(world, origin, dest_pos, faction_idx=faction_idx)


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

    road_path = _find_road_path(world, faction_idx, pos)
    road = RoadProject(faction_idx, road_path) if len(road_path) > 1 else None
    project = SettlementProject(faction_idx, pos, region_id, road, kind)
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
    faction.meta.setdefault("settlements", []).append(st.id)
    if 0 <= project.region_id < len(world.regions):
        region = world.regions[project.region_id]
        if not hasattr(region, "meta_settlements"):
            region.meta_settlements = []
        region.meta_settlements.append(st.id)


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
    if any(p.faction_idx == fac_idx for p in world.shipyard_projects):
        return True
    if any(p.faction_idx == fac_idx for p in world.claim_projects):
        return True
    return False


# --- AI settlement construction ----------------------------------------------
def _region_settlement_pos(world, region):
    """A free cell in `region` to build on: not a river, not already a
    settlement, village, or under construction — a region can easily have
    villages but no settlement yet (the normal outcome of a wildland
    claim), so this is exactly the kind of region run_settlement_ai targets
    and villages must be excluded here too, not just other settlements.
    None if nothing's available."""
    occupied = {st.pos for st in world.settlements}
    occupied.update(p.pos for p in world.settlement_projects)
    occupied.update(world.villages[vid].pos for vid in region.villages)
    candidates = [c for c in region.cells
                 if c not in world.river_cells and c not in occupied]
    return random.choice(candidates) if candidates else None


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
    then Castle, then Town). Deliberately simple: no site scoring, no
    catching up a faction that's fallen behind faster than one project at
    a time."""
    for fac_idx, nation in enumerate(world.factions):
        if fac_idx == world.player_faction_idx:
            continue
        if _ai_has_active_construction(world, fac_idx):
            continue
        empty_regions = [r for r in world.regions
                         if r.faction_idx == fac_idx and not getattr(r, "meta_settlements", [])]
        if not empty_regions:
            continue
        region = random.choice(empty_regions)
        pos = _region_settlement_pos(world, region)
        if pos is None:
            continue
        for kind in ("city", "castle", "town"):
            if can_afford(nation, SETTLEMENT_BUILD_COST[kind], world):
                start_settlement(world, nation, pos, kind)
                break


# --- AI storage construction ---------------------------------------------
STORAGE_AI_PRESSURE_THRESHOLD = 0.8   # trigger a Granary/Warehouse once a
                                      # settlement's own storage is at
                                      # least this full -- a real reason,
                                      # not blind busywork: the same
                                      # "storage is under real pressure"
                                      # signal the player's own storage
                                      # progress bar/overflow-spoilage
                                      # penalty already make visible


def run_storage_ai(world):
    """Every AI faction's equivalent of the player clicking "Build
    Granary"/"Build Warehouse": triggered by real storage pressure, not
    an unconditional habit -- only fires when at least one of the
    faction's settlements has filled STORAGE_AI_PRESSURE_THRESHOLD or
    more of its own storage capacity (see resources.
    settlement_storage_capacity), the same overflow risk the player
    already sees reflected in that settlement's storage bar. Skips a
    faction entirely if it already has any construction/expansion project
    in flight (see _ai_has_active_construction). Targets whichever
    settlement is under the most pressure, prefers a Granary (the bigger
    of the two bonuses), falls back to a Warehouse if it already has one.
    Deliberately simple: one settlement, one building, per faction per
    turn at most, same philosophy as run_settlement_ai."""
    for fac_idx, nation in enumerate(world.factions):
        if fac_idx == world.player_faction_idx:
            continue
        if _ai_has_active_construction(world, fac_idx):
            continue
        sids = nation.meta.get("settlements", [])
        if not sids:
            continue
        pressured = []
        for sid in sids:
            st = world.settlements[sid]
            cap = settlement_storage_capacity(st)
            if cap <= 0:
                continue
            stock = sum(getattr(st, "resources", {}).values())
            if stock / cap >= STORAGE_AI_PRESSURE_THRESHOLD:
                pressured.append((stock / cap, st))
        if not pressured:
            continue
        pressured.sort(key=lambda t: -t[0])
        st = pressured[0][1]
        if can_build_granary(world, st) and can_afford(nation, GRANARY_COST, world):
            start_granary(world, nation, st)
        elif can_build_warehouse(world, st) and can_afford(nation, WAREHOUSE_COST, world):
            start_warehouse(world, nation, st)
