"""Player-built castles: cost real resources, take real turns, and need a
connecting road that's physically built cell-by-cell over time (using the
same terrain-aware pathfinding as trade routes/village roads) before
construction can run at full speed — modeling "the workers need a way to
get there."
"""
import random

from app.world.worldgen import (OCEAN, Settlement, SETTLEMENT_UPKEEP,
                                SETTLEMENT_TAX_INCOME, _path_dijkstra, _elev_cost)
from app.world.lexicon import make_settlement_namer

CASTLE_COST = {"Stone": 400, "Wood": 200, "Iron": 100, "Gold": 300}
CASTLE_BUILD_TURNS = 15          # at full speed
ROAD_SPEED_PENALTY = 0.5         # castle progress rate while its road is incomplete
ROAD_CELLS_PER_TURN = 6          # how much of the route gets physically drawn each turn
_BBOX_PAD = 20


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
        return max(0, round(self.total_turns - self.progress_turns))

    @property
    def half_speed(self):
        return self.road is not None and not self.road.complete


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
    it renders like any other established dirt road from then on."""
    x, y = road.path[-1]
    if not (0 <= x < world.w and 0 <= y < world.h):
        return
    county_id = world.county_grid[y][x]
    if county_id < 0:
        return
    segs = world.roads_by_county.setdefault(county_id, [])
    segs.extend(zip(road.path, road.path[1:]))


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
