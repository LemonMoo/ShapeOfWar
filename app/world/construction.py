"""Player-built castles: cost real resources, take real turns, and need a
connecting road that's physically built cell-by-cell over time (using the
same terrain-aware pathfinding as trade routes/village roads) before
construction can run at full speed — modeling "the workers need a way to
get there."
"""
import math
import random

from app.world.worldgen import (OCEAN, Settlement, SETTLEMENT_UPKEEP,
                                SETTLEMENT_TAX_INCOME, _path_dijkstra, _elev_cost,
                                _SEA_COAST_REACH)
from app.world.lexicon import make_settlement_namer

CASTLE_COST = {"Stone": 400, "Wood": 200, "Iron": 100, "Gold": 300}
CASTLE_BUILD_TURNS = 15          # at full speed
ROAD_SPEED_PENALTY = 0.5         # castle progress rate while its road is incomplete
ROAD_CELLS_PER_TURN = 6          # how much of the route gets physically drawn each turn
_BBOX_PAD = 20

SHIPYARD_COST = {"Wood": 600, "Gold": 200}
SHIPYARD_BUILD_TURNS = 30        # deliberately steep -- "large amount of wood, very long cost"


class RoadProject:
    """A road under construction: `built_index` is how much of the final
    `path` is actually visible/traversable so far — grows by
    ROAD_CELLS_PER_TURN every turn until it reaches the end."""

    def __init__(self, faction_idx, path):
        self.faction_idx = faction_idx
        self.path = path
        self.built_index = 0

    @property
    def complete(self):
        return self.built_index >= len(self.path) - 1

    @property
    def built_cells(self):
        return self.path[:self.built_index + 1]


class CastleProject:
    def __init__(self, faction_idx, pos, county_id, road):
        self.faction_idx = faction_idx
        self.pos = pos
        self.county_id = county_id
        self.road = road            # RoadProject or None (already connected)
        self.total_turns = CASTLE_BUILD_TURNS
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
    if not can_afford(nation, SHIPYARD_COST):
        return "You don't have enough resources to start construction."

    res = nation.stats.setdefault("resources", {})
    for resource, amount in SHIPYARD_COST.items():
        if resource == "Gold":
            nation.stats["gold"] = nation.stats.get("gold", 0) - amount
        else:
            res[resource] = res.get(resource, 0) - amount

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


def _find_road_path(world, faction_idx, dest_pos):
    """Terrain-aware path from the nearest existing settlement of this
    faction to `dest_pos` — the exact same Dijkstra + elevation-cost
    machinery worldgen already uses for trade routes/roads, so this can't
    cross a mountain or river any more than anything else in the game does."""
    candidates = [st.pos for st in world.settlements if st.faction_idx == faction_idx]
    if not candidates:
        return [dest_pos]
    dx, dy = dest_pos
    origin = min(candidates, key=lambda p: (p[0] - dx) ** 2 + (p[1] - dy) ** 2)
    if origin == dest_pos:
        return [dest_pos]

    ox, oy = origin
    x0, x1 = sorted((ox, dx))
    y0, y1 = sorted((oy, dy))
    bx0 = max(0, x0 - _BBOX_PAD)
    by0 = max(0, y0 - _BBOX_PAD)
    bx1 = min(world.w, x1 + _BBOX_PAD + 1)
    by1 = min(world.h, y1 + _BBOX_PAD + 1)
    land_cellset = {(x, y) for y in range(by0, by1) for x in range(bx0, bx1)
                     if world.owner[y][x] != OCEAN}
    path = _path_dijkstra(land_cellset, lambda c: _elev_cost(world, world.base_cost, c),
                          origin, dest_pos)
    return path or [origin, dest_pos]   # fallback straight segment if pathfinding fails


def can_afford(nation, cost):
    res = nation.stats.get("resources", {})
    for resource, amount in cost.items():
        if resource == "Gold":
            if nation.stats.get("gold", 0) < amount:
                return False
        elif res.get(resource, 0) < amount:
            return False
    return True


def start_castle(world, player, pos):
    """Validate and kick off building a castle at `pos` for the player's own
    faction. Returns a message describing what happened (success or why
    not)."""
    x, y = pos
    if not (0 <= x < world.w and 0 <= y < world.h):
        return "That's outside the map."
    if world.owner[y][x] != world.player_faction_idx:
        return "You can only build within your own territory."
    county_id = world.county_grid[y][x]
    if county_id < 0:
        return "That location isn't part of any county."
    if any(st.pos == pos for st in world.settlements):
        return "There's already a settlement there."
    if any(c.pos == pos for c in world.castle_projects):
        return "Construction is already underway there."
    if not can_afford(player, CASTLE_COST):
        return "You don't have enough resources to start construction."

    res = player.stats.setdefault("resources", {})
    for resource, amount in CASTLE_COST.items():
        if resource == "Gold":
            player.stats["gold"] = player.stats.get("gold", 0) - amount
        else:
            res[resource] = res.get(resource, 0) - amount

    road_path = _find_road_path(world, world.player_faction_idx, pos)
    road = RoadProject(world.player_faction_idx, road_path) if len(road_path) > 1 else None
    castle = CastleProject(world.player_faction_idx, pos, county_id, road)
    world.castle_projects.append(castle)
    if road is not None:
        world.road_projects.append(road)
    return f"Construction begins on a new castle — estimated {castle.total_turns} turns."


def _finish_castle(world, castle):
    faction = world.factions[castle.faction_idx]
    species = faction.meta.get("species", "Humans")
    namer = make_settlement_namer(random)
    upkeep = {res: round(random.uniform(*rng_range))
              for res, rng_range in SETTLEMENT_UPKEEP["castle"].items()}
    tax_income = round(random.uniform(*SETTLEMENT_TAX_INCOME["castle"]))
    st = Settlement(len(world.settlements), "castle", namer("castle", species),
                    castle.pos, castle.faction_idx, castle.county_id, upkeep, tax_income)
    world.settlements.append(st)
    faction.meta.setdefault("settlements", []).append(st.id)
    if 0 <= castle.county_id < len(world.counties):
        county = world.counties[castle.county_id]
        if not hasattr(county, "meta_settlements"):
            county.meta_settlements = []
        county.meta_settlements.append(st.id)


def _finish_road(world, road):
    """Fold a completed road into the permanent per-county road network so
    it renders like any other established road from then on. Always a
    settlement-to-settlement connection (the nearest existing settlement to
    a brand-new castle), so it's Stone — see app/world/worldgen.py's
    _place_villages_for_county for the same tier rule applied at
    world-gen time."""
    x, y = road.path[-1]
    if not (0 <= x < world.w and 0 <= y < world.h):
        return
    county_id = world.county_grid[y][x]
    if county_id < 0:
        return
    segs = world.roads_by_county.setdefault(county_id, [])
    segs.extend((a, b, "stone") for a, b in zip(road.path, road.path[1:]))


def advance_projects(world):
    """Called every turn (alongside the trade hooks): grow roads, advance
    castles (at half speed while their road is unfinished), and finalize
    anything that's crossed the finish line."""
    for road in world.road_projects:
        if not road.complete:
            road.built_index = min(len(road.path) - 1, road.built_index + ROAD_CELLS_PER_TURN)

    finished_castles = []
    for castle in world.castle_projects:
        rate = ROAD_SPEED_PENALTY if castle.half_speed else 1.0
        castle.progress_turns += rate
        if castle.progress_turns >= castle.total_turns:
            finished_castles.append(castle)
    for castle in finished_castles:
        _finish_castle(world, castle)
        world.castle_projects.remove(castle)

    finished_roads = [r for r in world.road_projects if r.complete]
    for road in finished_roads:
        _finish_road(world, road)
        world.road_projects.remove(road)
