"""Commanders: a player-controlled unit that can be walked around the map
and, aboard a ship, sail across open ocean — the foundation for direct
player agency independent of territory growth. Solves a real gap: fog of
war only reveals land near what you own and expansion is gated on adjacency
to it, so an island start with no adjacent unclaimed land had no way to
ever see or reach anyone else. A Commander's own vision bubble (see
app/world/vision.py) works regardless of owned territory.

Ships are physical objects, not a permanent ability: a Commander that steps
onto land leaves its ship behind, marked at the last cell of water it
crossed — it can walk back and re-board that same ship, build a new one
elsewhere (abandoning the old one in place), or dismantle a beached ship
for a partial resource refund. A coastal city with a Shipyard
(app/world/construction.py) launches free, faster ships instead of the
normal costed/timed build — see start_ship.

Pure scout for this pass — no combat, no risk of being lost. Movement and
ship-building reuse the exact same Dijkstra/elevation-cost pathfinding every
other land/sea route in the game already uses (app/world/worldgen.py), not
new machinery.
"""
import math

from app.world.worldgen import (OCEAN, _path_dijkstra, _elev_cost, _sea_cost,
                                _nearest_ocean_cell, _SEA_COAST_REACH,
                                _NEIGH8, _DIAG)
from app.world.construction import can_afford, _pay_cost

COMMANDER_CELLS_PER_TURN = 5
COMMANDER_VISION_RADIUS = 8
# "Logs" as of Phase 12, not "Wood" -- see construction.py's SETTLEMENT_BUILD_COST
# comment: "Wood" was never a real registry resource, Logs is its direct
# new-registry equivalent.
SHIP_COST = {"Logs": 150, "Gold": 100}
SHIP_BUILD_TURNS = 8
SHIP_DISMANTLE_REFUND_FRACTION = 0.5   # of SHIP_COST["Logs"], salvaged on dismantle
SHIPYARD_SPEED_MULT = 1.5              # a shipyard-launched ship's per-turn speed bonus
_BBOX_PAD = 20   # matches construction._BBOX_PAD


class Commander:
    def __init__(self, cid, faction_idx, pos):
        self.id = cid
        self.faction_idx = faction_idx
        self.pos = pos                  # (x, y), current cell
        self.path = None                # queued route, or None if idle
        self.path_index = 0             # how far along `path` so far
        self.aboard_ship_id = None      # id of the Ship carrying it, or None (on foot)
        self.ship_turns_left = None     # None unless currently building a (non-free) ship


class Ship:
    """A physical ship, left wherever its commander last disembarked (or
    just-launched, if never boarded) — not an ability attached to the
    commander. `speed_mult` is 1.0 for a normally-built ship,
    SHIPYARD_SPEED_MULT for one launched from a Shipyard."""

    def __init__(self, sid, faction_idx, pos, speed_mult=1.0):
        self.id = sid
        self.faction_idx = faction_idx
        self.pos = pos
        self.speed_mult = speed_mult


def spawn_commander(world, faction_idx, pos):
    cmd = Commander(len(world.commanders), faction_idx, pos)
    world.commanders.append(cmd)
    return cmd


def find_ship_at(world, faction_idx, pos):
    """The same-faction Ship sitting exactly at `pos`, if any. Only
    meaningful for a beached ship (a Ship currently being sailed keeps
    whatever `.pos` it had when boarded/launched, since nothing needs to
    query it mid-voyage — see advance_commanders)."""
    return next((s for s in world.ships
                if s.faction_idx == faction_idx and s.pos == pos), None)


def find_ship_near(world, faction_idx, pos):
    """Same-faction beached Ship at `pos` or an orthogonally adjacent cell —
    the check board_ship/dismantle_ship/the UI panel actually want. A ship
    is always left on the ocean cell it was last sailing on (see
    advance_commanders), and a commander on foot can never step onto an
    ocean cell (set_move_order restricts land-only movement), so an exact
    `find_ship_at(pos)` match would never fire for a disembarked commander
    walking back to its ship — only "next to it" is ever reachable."""
    ship = find_ship_at(world, faction_idx, pos)
    if ship is not None:
        return ship
    x, y = pos
    for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
        ship = find_ship_at(world, faction_idx, (nx, ny))
        if ship is not None:
            return ship
    return None


def shipyard_at(world, faction_idx, pos):
    for st in world.settlements:
        if (st.faction_idx == faction_idx and st.pos == pos
                and getattr(st, "has_shipyard", False)):
            return st
    return None


def _path_dijkstra_nearest(cellset, cost_fn, start, dest):
    """Like worldgen._path_dijkstra, but never fails: if `dest` isn't in
    `cellset` or isn't reachable from `start`, this returns the path to
    whichever visited cell ends up closest (straight-line) to `dest`
    instead. Used for commander movement so an order sent into fog — where
    the player can't yet know what's actually out there — always just
    walks/sails as far toward it as the terrain allows and stops at
    whatever's blocking it, rather than an explicit 'no route' response
    that would itself leak what's blocking it (water, a separate
    landmass, ...)."""
    import heapq
    if start not in cellset:
        return None
    dist = {start: 0.0}
    parent = {}
    pq = [(0.0, start)]
    best, best_d2 = start, (start[0] - dest[0]) ** 2 + (start[1] - dest[1]) ** 2
    while pq:
        d, cur = heapq.heappop(pq)
        if d > dist.get(cur, 1e18):
            continue
        d2 = (cur[0] - dest[0]) ** 2 + (cur[1] - dest[1]) ** 2
        if d2 < best_d2:
            best_d2, best = d2, cur
        if cur == dest:
            break
        cx, cy = cur
        for dx, dy in _NEIGH8:
            nb = (cx + dx, cy + dy)
            if nb not in cellset:
                continue
            step = cost_fn(nb) * (_DIAG if dx and dy else 1.0)
            nd = d + step
            if nd < dist.get(nb, 1e18):
                dist[nb] = nd
                parent[nb] = cur
                heapq.heappush(pq, (nd, nb))
    path = [best]
    while path[-1] != start:
        path.append(parent[path[-1]])
    path.reverse()
    return path


def _bbox_cellset(world, a, b, include_ocean):
    """Every cell in a padded bounding box around two points — the same
    'pad the rectangle between start/dest, not a fixed window' approach
    construction._find_road_path already uses, which is why it scales fine
    to any distance. include_ocean=False restricts to land only."""
    x0, x1 = sorted((a[0], b[0]))
    y0, y1 = sorted((a[1], b[1]))
    bx0 = max(0, x0 - _BBOX_PAD)
    by0 = max(0, y0 - _BBOX_PAD)
    bx1 = min(world.w, x1 + _BBOX_PAD + 1)
    by1 = min(world.h, y1 + _BBOX_PAD + 1)
    if include_ocean:
        return {(x, y) for y in range(by0, by1) for x in range(bx0, bx1)}
    return {(x, y) for y in range(by0, by1) for x in range(bx0, bx1)
            if world.owner[y][x] != OCEAN}


_NEIGH8 = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
_SHIP_LANDING_SEARCH_R = 200   # generous -- covers even a very deep inland dest
_SEA_COAST_REACH_PAD = _SEA_COAST_REACH + 2   # a shipyard can sit a few cells inland


def _ocean_cellset(world, a, b):
    x0, x1 = sorted((a[0], b[0]))
    y0, y1 = sorted((a[1], b[1]))
    bx0 = max(0, x0 - _BBOX_PAD)
    by0 = max(0, y0 - _BBOX_PAD)
    bx1 = min(world.w, x1 + _BBOX_PAD + 1)
    by1 = min(world.h, y1 + _BBOX_PAD + 1)
    return {(x, y) for y in range(by0, by1) for x in range(bx0, bx1)
            if world.owner[y][x] == OCEAN}


def _shore_neighbor(world, ocean_cell, toward):
    """A land cell adjacent to `ocean_cell`, preferring whichever is
    closest to `toward` -- the actual disembark/embark point next to a
    given sea cell."""
    x, y = ocean_cell
    best, best_d2 = None, None
    for dx, dy in _NEIGH8:
        nx, ny = x + dx, y + dy
        if not (0 <= nx < world.w and 0 <= ny < world.h):
            continue
        if world.owner[ny][nx] == OCEAN:
            continue
        d2 = (nx - toward[0]) ** 2 + (ny - toward[1]) ** 2
        if best_d2 is None or d2 < best_d2:
            best_d2, best = d2, (nx, ny)
    return best


def _to_sea_leg(world, pos, max_r):
    """(land_path, sea_cell) connecting `pos` to open water: if `pos` is
    already ocean, there's no land leg at all (land_path is just [pos]);
    otherwise a short land-only hop from `pos` to the shore beside the
    nearest reachable ocean cell. Returns (None, None) if no ocean cell is
    found within `max_r`."""
    x, y = pos
    if world.owner[y][x] == OCEAN:
        return [pos], pos
    sea_cell = _nearest_ocean_cell(world, pos, max_r=max_r)
    if sea_cell is None:
        return None, None
    shore = _shore_neighbor(world, sea_cell, pos)
    if shore is None:
        return None, None
    if shore == pos:
        return [pos], sea_cell
    land_cellset = _bbox_cellset(world, pos, shore, False)
    if pos not in land_cellset or shore not in land_cellset:
        return None, None
    land_path = _path_dijkstra(land_cellset, lambda c: _elev_cost(world, world.base_cost, c),
                               pos, shore)
    if land_path is None:
        return None, None
    return land_path, sea_cell


def _join_paths(a, b):
    """Concatenate two adjacent path segments, dropping a's last cell if
    it's literally b's first (the two legs share an endpoint) rather than
    duplicating it."""
    return (a[:-1] if a[-1] == b[0] else a) + b


def _ship_path(world, start, dest):
    """Route for a ship-borne commander. If `dest` is itself open water,
    this is a pure ocean-only search -- land is never even in the cellset,
    so the ship can't graze a coastline or peninsula along the way and
    trigger a spurious mid-voyage 'landing'. Otherwise it's a two-phase
    sea-then-land route: a short land hop (if needed) from `start` out to
    open water, sail to the ocean cell nearest `dest`, then walk the rest
    on foot -- so the coastline is crossed at most once, never
    ocean->land->ocean, which would otherwise leave the commander's path
    walking through cells it has no ship to cross (see
    advance_commanders).

    Whenever the ideal route can't be completed -- `dest` is across fogged
    water the ship can't actually reach, or there's no coastline anywhere
    near it -- this sails as far in that direction as the sea allows and
    stops there (_path_dijkstra_nearest), the same 'follow the line, stop
    at the edge' behavior set_move_order uses on foot, instead of an
    explicit failure that would leak what's actually out there through the
    fog."""
    start_land, sea_start = _to_sea_leg(world, start, _SEA_COAST_REACH_PAD)
    if sea_start is None:
        return None

    dx, dy = dest
    sea_cost = lambda c: _sea_cost(world, world.base_cost, c)

    if world.owner[dy][dx] == OCEAN:
        sea_cellset = _ocean_cellset(world, sea_start, dest)
        sea_path = (_path_dijkstra(sea_cellset, sea_cost, sea_start, dest)
                   if dest in sea_cellset else None)
        if sea_path is None:
            sea_path = _path_dijkstra_nearest(sea_cellset, sea_cost, sea_start, dest)
        return _join_paths(start_land, sea_path)

    dest_land, sea_end = _to_sea_leg(world, dest, _SHIP_LANDING_SEARCH_R)
    sea_target = sea_end if sea_end is not None else dest
    sea_cellset = _ocean_cellset(world, sea_start, sea_target)
    sea_path = (_path_dijkstra(sea_cellset, sea_cost, sea_start, sea_target)
               if sea_target in sea_cellset else None)
    reached_landing = sea_path is not None
    if sea_path is None:
        sea_path = _path_dijkstra_nearest(sea_cellset, sea_cost, sea_start, sea_target)

    path = _join_paths(start_land, sea_path)
    if reached_landing and sea_end is not None:
        path = _join_paths(path, list(reversed(dest_land)))
    return path


def set_move_order(world, commander, dest):
    """Plan a route from the commander's current position to `dest` and
    queue it — advance_commanders() walks it a few cells per turn. Calling
    this again while already moving simply replans from the current
    position, overwriting the old order (natural mid-route redirection).
    Aboard a ship, routing goes through _ship_path so the coastline is
    crossed at most once (see its docstring) instead of a single mixed
    Dijkstra that could dip on and off land wherever that happened to be
    cheapest. On foot, only land is reachable at all.

    `dest` is very often clicked somewhere still hidden by fog of war, so
    this deliberately never reports "can't reach that" -- doing so would
    itself tell the player something about ground they haven't actually
    seen (that it's water, or a separate landmass, etc). Instead, whenever
    the direct route isn't available, _path_dijkstra_nearest walks/sails as
    far toward `dest` as the terrain allows and simply stops at whatever's
    blocking it -- the same "follow the line, stop at the edge" behavior
    either way. Returns a message describing what happened."""
    x, y = dest
    if not (0 <= x < world.w and 0 <= y < world.h):
        return "That's outside the map."
    if dest == commander.pos:
        return "Already there."
    if commander.ship_turns_left is not None:
        return "The commander is busy building a ship."

    if commander.aboard_ship_id is not None:
        path = _ship_path(world, commander.pos, dest)
    else:
        cellset = _bbox_cellset(world, commander.pos, dest, False)
        path = (_path_dijkstra(cellset, lambda c: _elev_cost(world, world.base_cost, c),
                               commander.pos, dest)
                if dest in cellset else None)
        if path is None:
            path = _path_dijkstra_nearest(cellset, lambda c: _elev_cost(world, world.base_cost, c),
                                          commander.pos, dest)
    if path is None:
        # Only possible if the commander's own current tile has no
        # traversable neighbor at all in this mode -- describes what's
        # already visible right where the commander is standing, not
        # anything behind fog.
        return "The commander has nowhere to go from here."

    commander.path = path
    commander.path_index = 0
    turns = max(1, math.ceil((len(path) - 1) / COMMANDER_CELLS_PER_TURN))
    return f"The commander sets out — estimated {turns} turns."


def can_build_ship(world, commander):
    if commander.aboard_ship_id is not None or commander.ship_turns_left is not None:
        return False
    if shipyard_at(world, commander.faction_idx, commander.pos) is not None:
        return True
    x, y = commander.pos
    for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
        if 0 <= nx < world.w and 0 <= ny < world.h and world.owner[ny][nx] == OCEAN:
            return True
    return False


def start_ship(world, commander):
    """Validate and kick off getting a ship at the commander's current
    position (must be coastal, or a Shipyard — see can_build_ship). At a
    same-faction Shipyard, the ship launches immediately, free, and faster
    (SHIPYARD_SPEED_MULT) — the whole reward for that building's very large
    one-time cost; otherwise this is the normal costed/timed build. Returns
    a message describing what happened (success or why not)."""
    if commander.aboard_ship_id is not None:
        return "This commander is already aboard a ship."
    if commander.ship_turns_left is not None:
        return "Already building a ship."
    if not can_build_ship(world, commander):
        return "The commander needs to be at the coast to build a ship."

    shipyard = shipyard_at(world, commander.faction_idx, commander.pos)
    if shipyard is not None:
        ship = Ship(len(world.ships), commander.faction_idx, commander.pos,
                   speed_mult=SHIPYARD_SPEED_MULT)
        world.ships.append(ship)
        commander.aboard_ship_id = ship.id
        return f"A new ship launches from the shipyard at {shipyard.name}, free of charge."

    nation = world.factions[commander.faction_idx]
    if not can_afford(nation, SHIP_COST, world):
        return "Not enough resources to build a ship."

    _pay_cost(nation, SHIP_COST, world)

    commander.path = None   # building locks the commander in place
    commander.path_index = 0
    commander.ship_turns_left = SHIP_BUILD_TURNS
    return f"Shipwrights set to work — estimated {SHIP_BUILD_TURNS} turns."


def board_ship(world, commander):
    if commander.aboard_ship_id is not None:
        return "Already aboard a ship."
    if commander.ship_turns_left is not None:
        return "The commander is busy building a ship."
    ship = find_ship_near(world, commander.faction_idx, commander.pos)
    if ship is None:
        return "There's no ship here to board."
    commander.pos = ship.pos
    commander.aboard_ship_id = ship.id
    return "The commander boards the ship."


def dismantle_ship(world, commander):
    """Salvage a beached ship for SHIP_DISMANTLE_REFUND_FRACTION of its
    Logs cost, delivered to the nearest same-faction settlement's own
    storage -- Logs is a settlement-storage resource as of Phase 12 (see
    resources.py's Industry Specialization section), so there's no more
    one national stockpile to refund into; "nearest" is the same "hauled
    to wherever's closest" reading construction._pay_cost's spend side
    already uses, just picking one settlement instead of spreading across
    several since a refund is a single small amount. Must be standing at
    or next to it, and not currently aboard it (disembark first)."""
    if commander.aboard_ship_id is not None:
        return "Disembark before dismantling this ship."
    ship = find_ship_near(world, commander.faction_idx, commander.pos)
    if ship is None:
        return "There's no ship here to dismantle."
    world.ships.remove(ship)
    nation = world.factions[commander.faction_idx]
    refund = round(SHIP_COST["Logs"] * SHIP_DISMANTLE_REFUND_FRACTION)
    sids = nation.meta.get("settlements", [])
    if sids:
        cx, cy = commander.pos
        st = min((world.settlements[sid] for sid in sids),
                key=lambda s: (s.pos[0] - cx) ** 2 + (s.pos[1] - cy) ** 2)
        if not hasattr(st, "resources"):
            st.resources = {}
        st.resources["Logs"] = st.resources.get("Logs", 0) + refund
    else:
        res = nation.stats.setdefault("resources", {})
        res["Logs"] = res.get("Logs", 0) + refund
    return f"The ship is dismantled, salvaging {refund} Logs."


def ship_by_id(world, ship_id):
    return next((s for s in world.ships if s.id == ship_id), None)


def advance_commanders(world):
    """Called every turn: walk each commander with an active order a few
    cells further along its path (faster while aboard a shipyard-built
    ship), disembarking automatically if that stretch of path crosses from
    water onto land, and count down any ship under construction."""
    for cmd in world.commanders:
        if cmd.path is not None:
            ship = ship_by_id(world, cmd.aboard_ship_id) if cmd.aboard_ship_id is not None else None
            cells_this_turn = (round(COMMANDER_CELLS_PER_TURN * ship.speed_mult)
                              if ship is not None else COMMANDER_CELLS_PER_TURN)
            old_index = cmd.path_index
            new_index = min(len(cmd.path) - 1, old_index + max(1, cells_this_turn))

            if ship is not None:
                # Scan the whole segment crossed this turn (not just the
                # endpoints) for a water->land transition -- a single
                # turn's jump can skip straight over the exact boundary.
                # set_move_order/_ship_path guarantees at most one such
                # crossing per path, so this only ever fires once.
                last_water_pos = None
                for i in range(old_index, new_index + 1):
                    px, py = cmd.path[i]
                    if world.owner[py][px] == OCEAN:
                        last_water_pos = (px, py)
                    elif last_water_pos is not None:
                        ship.pos = last_water_pos
                        cmd.aboard_ship_id = None
                        break
            else:
                # On foot: never step onto an ocean cell. Freshly planned
                # paths can't contain one (see set_move_order), but this
                # guards a path that already existed before that guarantee
                # -- e.g. an old save -- from stranding the commander
                # mid-ocean instead of just stopping short.
                for i in range(old_index, new_index + 1):
                    px, py = cmd.path[i]
                    if world.owner[py][px] == OCEAN:
                        new_index = max(old_index, i - 1)
                        break

            cmd.path_index = new_index
            cmd.pos = cmd.path[cmd.path_index]
            if cmd.path_index >= len(cmd.path) - 1:
                cmd.path = None
                cmd.path_index = 0

        if cmd.ship_turns_left is not None:
            cmd.ship_turns_left -= 1
            if cmd.ship_turns_left <= 0:
                ship = Ship(len(world.ships), cmd.faction_idx, cmd.pos, speed_mult=1.0)
                world.ships.append(ship)
                cmd.aboard_ship_id = ship.id
                cmd.ship_turns_left = None
