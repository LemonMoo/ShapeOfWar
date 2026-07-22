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

from app.world.worldgen import (OCEAN, Settlement, SETTLEMENT_UPKEEP,
                                SETTLEMENT_TAX_INCOME, _roll_population, _path_dijkstra,
                                _elev_cost, _SEA_COAST_REACH)
from app.world.lexicon import make_settlement_namer
from app.world.resources import seed_prosperity

# Cost/time to build each settlement kind. City is the crown jewel (biggest
# population range, POPULATION_RANGE in worldgen.py) so it's the steepest;
# Town is the cheap, fast starter settlement. Town/City run 5x their
# original resource cost, Castle 4x — all deliberately steep, multi-turn
# investments now that wildland claims never hand one out for free.
SETTLEMENT_BUILD_COST = {
    "town": {"Wood": 1000, "Stone": 500, "Gold": 750},
    "castle": {"Stone": 1600, "Wood": 800, "Iron": 400, "Gold": 1200},
    "city": {"Wood": 1750, "Stone": 1500, "Iron": 750, "Gold": 2500},
}
SETTLEMENT_BUILD_TURNS = {"town": 20, "castle": 25, "city": 40}   # at full speed
ROAD_SPEED_PENALTY = 0.5         # project progress rate while its road is incomplete
ROAD_CELLS_PER_TURN = 6          # how much of the route gets physically drawn each turn
_BBOX_PAD = 20

SHIPYARD_COST = {"Wood": 600, "Gold": 200}
SHIPYARD_BUILD_TURNS = 30        # deliberately steep -- "large amount of wood, very long cost"


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


def _path_between(world, origin, dest_pos):
    """Terrain-aware path between two specific points — the same Dijkstra +
    elevation-cost machinery worldgen already uses for trade routes/roads,
    so this can't cross a mountain or river any more than anything else in
    the game does. Shared by _find_road_path (nearest existing settlement
    to a new one) and expansion.ensure_interregion_roads (village to
    village across a region border)."""
    if origin == dest_pos:
        return [origin]
    ox, oy = origin
    dx, dy = dest_pos
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


def _find_road_path(world, faction_idx, dest_pos):
    """Terrain-aware path from the nearest existing settlement of this
    faction to `dest_pos`."""
    candidates = [st.pos for st in world.settlements if st.faction_idx == faction_idx]
    if not candidates:
        return [dest_pos]
    dx, dy = dest_pos
    origin = min(candidates, key=lambda p: (p[0] - dx) ** 2 + (p[1] - dy) ** 2)
    return _path_between(world, origin, dest_pos)


def can_afford(nation, cost):
    res = nation.stats.get("resources", {})
    for resource, amount in cost.items():
        if resource == "Gold":
            if nation.stats.get("gold", 0) < amount:
                return False
        elif res.get(resource, 0) < amount:
            return False
    return True


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
    if not can_afford(nation, cost):
        return "You don't have enough resources to start construction."

    res = nation.stats.setdefault("resources", {})
    for resource, amount in cost.items():
        if resource == "Gold":
            nation.stats["gold"] = nation.stats.get("gold", 0) - amount
        else:
            res[resource] = res.get(resource, 0) - amount

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
    upkeep = {res: round(random.uniform(*rng_range))
              for res, rng_range in SETTLEMENT_UPKEEP[kind].items()}
    tax_income = round(random.uniform(*SETTLEMENT_TAX_INCOME[kind]))
    population, adults, children = _roll_population(random, kind)
    prosperity = seed_prosperity()
    st = Settlement(len(world.settlements), kind, namer(kind, species),
                    project.pos, project.faction_idx, project.region_id, upkeep, tax_income,
                    population, adults, children, prosperity)
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
    "Build Town": claiming wildland only ever yields villages now (see
    expansion.settle_newly_claimed_region), so a faction has to actually
    construct its City/Town settlements the same way the player does.
    One new project per faction per turn at most (skip if it's already
    building something), targeting a region it owns that has no
    settlements in it yet — prefers a City if it can afford one, else a
    Town. Deliberately simple: no site scoring, no catching up a faction
    that's fallen behind faster than one project at a time."""
    for fac_idx, nation in enumerate(world.factions):
        if fac_idx == world.player_faction_idx:
            continue
        if any(p.faction_idx == fac_idx for p in world.settlement_projects):
            continue
        empty_regions = [r for r in world.regions
                         if r.faction_idx == fac_idx and not getattr(r, "meta_settlements", [])]
        if not empty_regions:
            continue
        region = random.choice(empty_regions)
        pos = _region_settlement_pos(world, region)
        if pos is None:
            continue
        for kind in ("city", "town"):
            if can_afford(nation, SETTLEMENT_BUILD_COST[kind]):
                start_settlement(world, nation, pos, kind)
                break
