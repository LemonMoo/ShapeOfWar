"""Commanders: a player-controlled unit that can be walked around the map
and, once it's built a ship, sail across open ocean — the foundation for
direct player agency independent of territory growth. Solves a real gap:
fog of war only reveals land near what you own and expansion is gated on
adjacency to it, so an island start with no adjacent unclaimed land had no
way to ever see or reach anyone else. A Commander's own vision bubble (see
app/world/vision.py) works regardless of owned territory.

Pure scout for this pass — no combat, no risk of being lost. Movement and
ship-building reuse the exact same Dijkstra/elevation-cost pathfinding every
other land/sea route in the game already uses (app/world/worldgen.py), not
new machinery.
"""
import math

from app.world.worldgen import OCEAN, _path_dijkstra, _elev_cost, _sea_cost
from app.world.construction import can_afford

COMMANDER_CELLS_PER_TURN = 5
COMMANDER_VISION_RADIUS = 8
SHIP_COST = {"Wood": 150, "Iron": 40, "Gold": 100}
SHIP_BUILD_TURNS = 8
_BBOX_PAD = 20   # matches construction._BBOX_PAD


class Commander:
    def __init__(self, cid, faction_idx, pos):
        self.id = cid
        self.faction_idx = faction_idx
        self.pos = pos                  # (x, y), current cell
        self.path = None                # queued route, or None if idle
        self.path_index = 0             # how far along `path` so far
        self.has_ship = False
        self.ship_turns_left = None     # None unless currently building


def spawn_commander(world, faction_idx, pos):
    cmd = Commander(len(world.commanders), faction_idx, pos)
    world.commanders.append(cmd)
    return cmd


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


def _move_cost(world, cell):
    x, y = cell
    if world.owner[y][x] == OCEAN:
        return _sea_cost(world, world.base_cost, cell)
    return _elev_cost(world, world.base_cost, cell)


def set_move_order(world, commander, dest):
    """Plan a route from the commander's current position to `dest` and
    queue it — advance_commanders() walks it a few cells per turn. Calling
    this again while already moving simply replans from the current
    position, overwriting the old order (natural mid-route redirection).
    Returns a message describing what happened."""
    x, y = dest
    if not (0 <= x < world.w and 0 <= y < world.h):
        return "That's outside the map."
    if dest == commander.pos:
        return "Already there."
    if commander.ship_turns_left is not None:
        return "The commander is busy building a ship."

    cellset = _bbox_cellset(world, commander.pos, dest, commander.has_ship)
    if dest not in cellset:
        return "No route the commander can currently travel reaches there."
    path = _path_dijkstra(cellset, lambda c: _move_cost(world, c), commander.pos, dest)
    if path is None:
        return "No viable route exists to that location."

    commander.path = path
    commander.path_index = 0
    turns = max(1, math.ceil((len(path) - 1) / COMMANDER_CELLS_PER_TURN))
    return f"The commander sets out — estimated {turns} turns."


def can_build_ship(world, commander):
    if commander.has_ship or commander.ship_turns_left is not None:
        return False
    x, y = commander.pos
    for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
        if 0 <= nx < world.w and 0 <= ny < world.h and world.owner[ny][nx] == OCEAN:
            return True
    return False


def start_ship(world, commander):
    """Validate and kick off building a ship at the commander's current
    position (must be coastal). Returns a message describing what happened
    (success or why not)."""
    if commander.has_ship:
        return "This commander already has a ship."
    if commander.ship_turns_left is not None:
        return "Already building a ship."
    if not can_build_ship(world, commander):
        return "The commander needs to be at the coast to build a ship."
    nation = world.factions[commander.faction_idx]
    if not can_afford(nation, SHIP_COST):
        return "Not enough resources to build a ship."

    res = nation.stats.setdefault("resources", {})
    for resource, amount in SHIP_COST.items():
        if resource == "Gold":
            nation.stats["gold"] = nation.stats.get("gold", 0) - amount
        else:
            res[resource] = res.get(resource, 0) - amount

    commander.path = None   # building locks the commander in place
    commander.path_index = 0
    commander.ship_turns_left = SHIP_BUILD_TURNS
    return f"Shipwrights set to work — estimated {SHIP_BUILD_TURNS} turns."


def advance_commanders(world):
    """Called every turn: walk each commander with an active order a few
    cells further along its path, and count down any ship under
    construction."""
    for cmd in world.commanders:
        if cmd.path is not None:
            cmd.path_index = min(len(cmd.path) - 1,
                                 cmd.path_index + COMMANDER_CELLS_PER_TURN)
            cmd.pos = cmd.path[cmd.path_index]
            if cmd.path_index >= len(cmd.path) - 1:
                cmd.path = None
                cmd.path_index = 0

        if cmd.ship_turns_left is not None:
            cmd.ship_turns_left -= 1
            if cmd.ship_turns_left <= 0:
                cmd.has_ship = True
                cmd.ship_turns_left = None
