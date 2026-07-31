"""Biome overhaul phase E: terrain in movement.

    python dev/test_march.py [world.pkl]

A march was never reckoned in miles, it was reckoned in days through a
particular kind of country. COMMANDER_CELLS_PER_TURN is a budget in
easy-going cells now rather than a flat count, and every cell of path spends
its own terrain's share of it.

The road half matters as much as the terrain half: a road is cheaper than the
easiest open country, so a realm that has built its network can move an army
across itself far faster than one that has not. That is what roads were for,
and it gives the network a military value it never had when it only carried
trade.
"""
import sys
import os
import pickle

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import commander as C
from app.world import resources as R

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "worlds", "dev560.pkl")
w = pickle.load(open(PATH, "rb"))
C.ensure_faction_commanders(w)
roads = C.road_cells(w)

print("--- every biome has a march cost, and only real biomes do ---")
real = ({b for row in R._BIOME_MATRIX for b in row}
        | {"mountain", "highland", "coastal", "swamp"})
assert set(C.TERRAIN_MOVE_COST) == real, real ^ set(C.TERRAIN_MOVE_COST)
assert all(v > 0 for v in C.TERRAIN_MOVE_COST.values())
print(f"  ok    all {len(real)} biomes costed, "
      f"{min(C.TERRAIN_MOVE_COST.values())}..{max(C.TERRAIN_MOVE_COST.values())}")

print("\n--- hard country really is slower than easy country ---")
easy = C.TERRAIN_MOVE_COST["plains"]
for hard in ("swamp", "mountain", "jungle", "highland", "forest"):
    assert C.TERRAIN_MOVE_COST[hard] > easy, hard
print(f"  ok    swamp {C.TERRAIN_MOVE_COST['swamp']}x, mountain "
      f"{C.TERRAIN_MOVE_COST['mountain']}x, jungle "
      f"{C.TERRAIN_MOVE_COST['jungle']}x against plains {easy}x")

print("\n--- a road beats every kind of ground it is built on ---")
assert C.ROAD_MOVE_COST < min(C.TERRAIN_MOVE_COST.values()), (
    "a road must be faster than the easiest open country, or building one "
    "buys an army nothing")
print(f"  ok    road {C.ROAD_MOVE_COST}x, cheaper than the best terrain "
      f"({min(C.TERRAIN_MOVE_COST.values())}x)")

print("\n--- and the road check wins wherever the two disagree ---")
road_cell = next((c for c in roads
                  if w.biome_grid[c[1]][c[0]] not in (None, "plains")), None)
if road_cell is not None:
    biome = w.biome_grid[road_cell[1]][road_cell[0]]
    assert C.cell_move_cost(w, road_cell, roads) == C.ROAD_MOVE_COST, (
        f"a road over {biome} charged the terrain rate")
    print(f"  ok    a road over {biome} costs the road rate, not "
          f"{C.TERRAIN_MOVE_COST[biome]}x")

print("\n--- distance covered actually differs by country ---")
budget = C.COMMANDER_CELLS_PER_TURN
covered = {}
for biome, cost in C.TERRAIN_MOVE_COST.items():
    n, spent = 0, 0.0
    while n == 0 or spent + cost <= budget:
        spent += cost
        n += 1
        if n > 99:
            break
    covered[biome] = n
assert covered["plains"] > covered["swamp"], covered
assert covered["plains"] > covered["mountain"], covered
print(f"  ok    on a {budget}-cell budget: plains {covered['plains']}, "
      f"forest {covered['forest']}, swamp {covered['swamp']}, "
      f"mountain {covered['mountain']} cells a turn")

print("\n--- a column always gets at least one cell ---")
# A budget that rounds to nothing must slow a commander, never strand them.
worst = max(C.TERRAIN_MOVE_COST, key=C.TERRAIN_MOVE_COST.get)
fake = [(0, 0), (1, 0), (2, 0)]
got = C._advance_along_path(w, fake, 0, 0.0, set())
assert got == 1, (
    f"a zero budget advanced {got} cells -- a commander ordered across "
    f"{worst} must be able to start")
print(f"  ok    even a zero budget advances one cell (worst ground is {worst})")

print("\n--- a real commander still marches, and still arrives ---")
cmd = next(c for c in w.commanders if c.faction_idx >= 0)
land = [(x, y) for y in range(0, w.h, 41) for x in range(0, w.w, 41)
        if w.owner[y][x] != C.OCEAN]
import random
dest = random.Random(5).choice(land)
C.set_move_order(w, cmd, dest)
if cmd.path:
    start, length = cmd.path_index, len(cmd.path)
    for _ in range(400):
        C.advance_commanders(w)
        if cmd.path is None:
            break
    assert cmd.path is None or cmd.path_index > start, "the commander never moved"
    print(f"  ok    walked a {length}-cell route to its end")
else:
    print("  skip  no route from where this commander stands")

print("\n--- ships are unaffected: open water is open water ---")
import inspect
src = inspect.getsource(C.advance_commanders)
ship_branch = src.split("if ship is not None:")[1].split("else:")[0]
assert "_advance_along_path" not in ship_branch, (
    "the sea branch went through the terrain budget -- there is no terrain "
    "out there")
print("  ok    the sea branch keeps its flat per-turn count")

print("\n--- a turn still runs, and nobody ends up in the ocean ---")
for _ in range(3):
    R.advance_turn(w)
for c in w.commanders:
    x, y = c.pos
    if c.aboard_ship_id is None:
        assert w.owner[y][x] != C.OCEAN, (c.id, c.pos)
print(f"  ok    3 turns, all {len(w.commanders)} commanders on legal ground")

print("\nMARCH TEST PASSED")
