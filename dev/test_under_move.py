"""Marching underground, and not seeing in the dark (SUBTERRANEAN_PLAN phase 3).

    python dev/test_under_move.py

Three claims, and all three are structural rather than a number anyone has to
like:

  * a column can only reach the galleries THROUGH A GATE, and it pays for the
    door in days -- which is the whole design, and the same property phase 0's
    `neighbours` test guards one layer down;
  * distance underground is expensive because haulage is expensive: the same
    journey costs more in a gallery than on open country above it;
  * darkness is not a small fog radius, it is a walk along open passage. Two
    galleries with rock between them are not in sight of each other however
    close they are, and nothing underground is ever revealed by owning half
    the surface.

Generates a real world (the only honest way to get a real network) and marches
a real Commander through a real gate, rather than a hand-built toy: the whole
point of the phase is that the pieces meet.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import layers as L
from app.world import vision
from app.world import commander as C
from app.world.worldgen import generate_world, OCEAN

world = generate_world(560, 340, seed=7, n_factions=6)
world.player_faction_idx = 0
print(f"world: {world.under_summary}")
assert world.under_cells and world.gates, "this seed carved nothing to walk in"

# A gate whose surface side is real, reachable ground.
gate = next(g for g in world.gates
            if world.owner[g["pos"][1]][g["pos"][0]] != OCEAN)
gx, gy = gate["pos"]

print("\n--- what a step costs, above and below ---")
gallery = L.UNDER_MOVE_COST[L.GALLERY]
cavern = L.UNDER_MOVE_COST[L.CAVERN]
worst_surface = max(C.TERRAIN_MOVE_COST.values())
assert gallery >= worst_surface, (
    "a gallery is easier going than the worst ground on the surface -- haulage "
    "is supposed to be what makes distance underground expensive")
assert cavern < gallery, "a cavern floor should be quicker than a working"
assert L.GATE_TRANSIT_COST >= C.COMMANDER_CELLS_PER_TURN, (
    "a gate costs less than a day -- descending is meant to be an event")
print(f"  gallery {gallery}, cavern {cavern}, worst surface ground "
      f"{worst_surface}, the door {L.GATE_TRANSIT_COST}")

print("\n--- a column can only get down through a gate ---")
cmd = C.spawn_commander(world, 0, (gx, gy))
assert C.commander_layer(cmd) == L.SURFACE
under_target = tuple(gate["under"])
msg = C.set_move_order(world, cmd, under_target, L.UNDER)
print(f"  {msg}")
assert cmd.path_layers is not None, "a march below ground kept no layers"
crossings = [i for i in range(len(cmd.path_layers) - 1)
             if cmd.path_layers[i] != cmd.path_layers[i + 1]]
assert crossings, "reached the underworld without crossing anything"
for i in crossings:
    assert cmd.path[i] == cmd.path[i + 1], (
        "a layer change that is not a gate -- the column tunnelled")
    assert L.gate_at(world, cmd.path[i][0], cmd.path[i][1],
                     cmd.path_layers[i]) is not None
print(f"  {len(crossings)} crossing(s), every one of them a door")

days = 0
while cmd.path is not None and days < 60:
    C.advance_commanders(world)
    days += 1
assert C.commander_layer(cmd) == L.UNDER, "the column never got below"
assert cmd.pos == under_target, f"stopped short at {cmd.pos}"
print(f"  arrived below in {days} days")

print("\n--- and the door itself costs a day ---")
# The same commander, standing IN the gate mouth, ordered one step back up:
# one cell of travel, and it is the gate that is being paid for.
cmd.pos = tuple(gate["under"])
cmd.layer = L.UNDER
cmd.path, cmd.path_layers, cmd.path_index = None, None, 0
C.set_move_order(world, cmd, (gx, gy), L.SURFACE)
assert len(cmd.path) == 2 and cmd.path_layers == [L.UNDER, L.SURFACE], cmd.path
before = C.commander_layer(cmd)
C.advance_commanders(world)
assert before == L.UNDER and C.commander_layer(cmd) == L.SURFACE
print("  one day, one door, back on the hillside")

print("\n--- a gallery is slower than the same distance above it ---")
# Measured rather than asserted from the table: what matters is that the
# march actually spends the cost, not that the constant exists.
def march_cells(layer, start, steps=8):
    """How many cells a day's marching covers from `start` on `layer`."""
    scout = C.spawn_commander(world, 0, start)
    scout.layer = layer
    dest = None
    seen = {start}
    frontier = [start]
    # Walk `steps` cells out along open ground/passage to get a destination
    # that is genuinely reachable on this layer.
    for _ in range(steps):
        nxt = []
        for p in frontier:
            for nx, ny, nl in L.open_neighbours(world, p[0], p[1], layer):
                if (nx, ny) not in seen:
                    seen.add((nx, ny))
                    nxt.append((nx, ny))
        if not nxt:
            break
        frontier = nxt
        dest = frontier[0]
    if dest is None:
        return None
    C.set_move_order(world, scout, dest, layer)
    walked_from = scout.path_index
    C.advance_commanders(world)
    covered = scout.path_index - walked_from
    world.commanders.remove(scout)
    return covered

below = march_cells(L.UNDER, under_target)
above = march_cells(L.SURFACE, (gx, gy))
print(f"  one day's march: {above} cells above ground, {below} in the galleries")
assert below is not None and above is not None
assert below < above, (
    "a day underground covered as much ground as a day above it")

print("\n--- darkness: nothing is known until somebody carries a light ---")
world.commanders = [c for c in world.commanders if c is not None]
world.under_fog = set()
for c in list(world.commanders):
    world.commanders.remove(c)
# "Nothing held": the realm must own no hall below either. A cave player
# (Dwarves/Goblins) starts holding its own galleries, so relinquish those
# before asserting a realm with nothing underground sees nothing.
meta_regions = world.factions[world.player_faction_idx].meta.get("regions", [])
for cid in list(meta_regions):
    if L.is_under(world.regions[cid]):
        world.regions[cid].faction_idx = -2
        meta_regions.remove(cid)
vision.recompute_under(world)
assert not world.under_fog, (
    "the underworld was revealed with nobody down there and nothing held")
print("  ok    an empty realm sees nothing below")

scout = C.spawn_commander(world, 0, under_target)
scout.layer = L.UNDER
vision.recompute_under(world)
lit = set(world.under_fog)
assert under_target in lit, "the column cannot see the hall it is standing in"
print(f"  a single column lights {len(lit)} cells of passage")
assert len(lit) < len(world.under_cells) / 4, (
    "one commander lit most of the underworld -- that is a radius, not a lantern")

# The load-bearing one: light follows passage, never rock. Every lit cell has
# to be walkable from the column WITHOUT leaving open ground.
walk = {under_target}
frontier = [under_target]
for _ in range(vision.UNDER_VISION_RADIUS):
    nxt = []
    for p in frontier:
        for nx, ny, _l in L.open_neighbours(world, p[0], p[1], L.UNDER):
            if (nx, ny) not in walk:
                walk.add((nx, ny))
                nxt.append((nx, ny))
    frontier = nxt
assert lit <= walk, (
    f"{len(lit - walk)} cells lit through solid rock -- darkness is a walk "
    "along open passage, not a radius")
print("  ok    light follows the passage and stops at the rock")

print("\n--- and it is monotonic, sparse, and not lifted by the surface ---")
scout.pos = under_target
vision.recompute_under(world)
assert lit <= world.under_fog, "already-explored ground went dark again"
world.fog_fully_revealed = True     # as if the player owned three quarters of
world.fog = bytearray(b"\x01" * (world.w * world.h))   # the map above
before = len(world.under_fog)
vision.recompute(world)
assert len(world.under_fog) == before, (
    "owning the surface revealed the inside of the mountains")
assert not vision.under_revealed(world, *max(
    p for p in world.under_cells if p not in world.under_fog))
print(f"  ok    {len(world.under_fog)} cells known of {len(world.under_cells)} carved")

print("\n--- a gate is a peephole, from the right side of it ---")
world.under_fog = set()
world.commanders.remove(scout)
watcher = C.spawn_commander(world, 0, (gx, gy))
vision.recompute_under(world)
assert tuple(gate["under"]) in world.under_fog, (
    "standing in the doorway showed nothing of what is behind it")
assert len(world.under_fog) < 40, "a peek through a door lit a whole hold"
print(f"  ok    {len(world.under_fog)} cells seen through the open door")

print("\n--- an old commander is one who has never been down ---")
class OldCommander:
    """A commander pickled before phase 3: no layer, no path layers."""
    def __init__(self):
        self.pos, self.path, self.path_index = (gx, gy), None, 0
        self.faction_idx, self.aboard_ship_id, self.ship_turns_left = 0, None, None
old = OldCommander()
assert C.commander_layer(old) == L.SURFACE
assert C.path_layer_at(old, 3) == L.SURFACE
world.commanders.append(old)
vision.recompute_under(world)        # must not raise on a commander with no layer
C.advance_commanders(world)          # nor must a day
print("  ok    reads as a surface commander, and a day runs over it")

print("\nUNDER MOVEMENT TEST PASSED")
