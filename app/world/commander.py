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

from app.world.worldgen import OCEAN, _path_dijkstra, _elev_cost, _sea_cost
from app.world.construction import can_afford

COMMANDER_CELLS_PER_TURN = 5
COMMANDER_VISION_RADIUS = 8
SHIP_COST = {"Wood": 150, "Iron": 40, "Gold": 100}
SHIP_BUILD_TURNS = 8
SHIP_DISMANTLE_REFUND_FRACTION = 0.5   # of SHIP_COST["Wood"], salvaged on dismantle
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
    """The same-faction Ship sitting exactly at `pos`, if any — the one
    lookup board_ship/dismantle_ship/the UI panel all share. Only
    meaningful for a beached ship (a Ship currently being sailed keeps
    whatever `.pos` it had when boarded/launched, since nothing needs to
    query it mid-voyage — see advance_commanders)."""
    return next((s for s in world.ships
                if s.faction_idx == faction_idx and s.pos == pos), None)


def shipyard_at(world, faction_idx, pos):
    for st in world.settlements:
        if (st.faction_idx == faction_idx and st.pos == pos
                and getattr(st, "has_shipyard", False)):
            return st
    return None


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
    Aboard a ship, the cellset includes ocean, so a single Dijkstra search
    naturally sails as far as is cheapest before crossing onto land — no
    separate 'prefer water' rule needed, it falls straight out of cost
    minimization over the combined cellset. On foot, only land is
    reachable at all. Returns a message describing what happened."""
    x, y = dest
    if not (0 <= x < world.w and 0 <= y < world.h):
        return "That's outside the map."
    if dest == commander.pos:
        return "Already there."
    if commander.ship_turns_left is not None:
        return "The commander is busy building a ship."

    aboard = commander.aboard_ship_id is not None
    cellset = _bbox_cellset(world, commander.pos, dest, aboard)
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


def board_ship(world, commander):
    if commander.aboard_ship_id is not None:
        return "Already aboard a ship."
    if commander.ship_turns_left is not None:
        return "The commander is busy building a ship."
    ship = find_ship_at(world, commander.faction_idx, commander.pos)
    if ship is None:
        return "There's no ship here to board."
    commander.aboard_ship_id = ship.id
    return "The commander boards the ship."


def dismantle_ship(world, commander):
    """Salvage a beached ship for SHIP_DISMANTLE_REFUND_FRACTION of its
    Wood cost back to the faction's stockpile. Must be standing at it, and
    not currently aboard it (disembark first)."""
    if commander.aboard_ship_id is not None:
        return "Disembark before dismantling this ship."
    ship = find_ship_at(world, commander.faction_idx, commander.pos)
    if ship is None:
        return "There's no ship here to dismantle."
    world.ships.remove(ship)
    nation = world.factions[commander.faction_idx]
    refund = round(SHIP_COST["Wood"] * SHIP_DISMANTLE_REFUND_FRACTION)
    res = nation.stats.setdefault("resources", {})
    res["Wood"] = res.get("Wood", 0) + refund
    return f"The ship is dismantled, salvaging {refund} Wood."


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
                last_water_pos = None
                for i in range(old_index, new_index + 1):
                    px, py = cmd.path[i]
                    if world.owner[py][px] == OCEAN:
                        last_water_pos = (px, py)
                    elif last_water_pos is not None:
                        ship.pos = last_water_pos
                        cmd.aboard_ship_id = None
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
