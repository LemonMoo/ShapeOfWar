"""Inland water: one great lake, not a flooded continent.

    python dev/test_lakes.py [seeds...]

Reported from a screenshot of a large world: not that lakes existed, but that
there were so many ENORMOUS ones that the land stopped reading as whole.
Measured before the change, across three seeds, lakes covered 8.9-14.6% of
all land with three to six separate basins each over 1% of it -- one was 5.4%
of the world's land on its own.

The fix is NOT the depth threshold, and that distinction is the point of this
file. `_LAKE_DEPTH` is a single global number: raise it enough to drown the
inland seas and every pond goes with them, which costs the small lakes that
are pure character. The problem was never lake DEPTH, it was the size of
individual BASINS. So basins are what get capped, with exactly one allowed to
exceed it -- because a single huge lake is a landmark, and that was explicit
in the report.

This generates real worlds, so it is slow. That is the only way to test
worldgen honestly.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import worldgen as WG

SEEDS = [int(a) for a in sys.argv[1:]] or [11, 22, 33]


def survey(world):
    land = sum(1 for y in range(world.h) for x in range(world.w)
               if world.owner[y][x] != WG.OCEAN)
    basins = WG._lake_basins(world.lake_cells)
    return land, basins


print("--- the knobs mean what they say ---")
assert 0 < WG._LAKE_MAX_SHARE < 1
assert WG._GREAT_LAKE_LIMIT >= 1, (
    "no world may have a great lake at all -- that was not the ask; one huge "
    "lake is a landmark")
print(f"  ok    depth {WG._LAKE_DEPTH}, per-basin cap "
      f"{WG._LAKE_MAX_SHARE*100:.1f}% of land, "
      f"{WG._GREAT_LAKE_LIMIT} basin(s) exempt")

print("\n--- basin splitting finds what a human would call one lake ---")
# Two cells touching only at a corner are one lake, not two -- water does not
# care about the difference, and 4-connectivity would report a diagonal
# channel as a chain of separate ponds.
diagonal = {(0, 0), (1, 1), (2, 2)}
assert len(WG._lake_basins(diagonal)) == 1, WG._lake_basins(diagonal)
apart = {(0, 0), (9, 9)}
assert len(WG._lake_basins(apart)) == 2
assert WG._lake_basins(set()) == []
big, small = {(x, 0) for x in range(5)}, {(0, 9)}
assert len(WG._lake_basins(big | small)[0]) == 5, "basins must come back largest first"
print("  ok    8-connected, largest first, empty is empty")

print("\n--- receding a lake leaves ONE lake, not a scatter of puddles ---")
# A long lumpy basin, deep at BOTH ends and shallow in the middle -- the case
# that can come out as two separate pools, which is the fractured look this is
# fixing. The left end is the deeper of the two, so trimming to the deepest
# cells keeps the left pool and drops the rest: one lake, on the deep end.
H = [[0.0] * 12 for _ in range(6)]
filled = [[0.0] * 12 for _ in range(6)]
basin = set()
for x in range(12):
    depth = 0.14 if x in (1, 2, 3, 4) else 0.10 if x in (8, 9) else 0.03
    filled[1][x] = depth
    basin.add((x, 1))
# A bigger basin elsewhere, so the trough is NOT the one GREAT lake (the
# largest, which gets the roomier great-lake cap). land_area is chosen so the
# 20-cell great basin fits its cap (great_cap = 0.028 * area = 20) while the
# 12-cell trough exceeds the medium cap (0.006 * area = 4) and gets trimmed.
great = set()
for x in range(10):
    for y in (4, 5):
        filled[y][x] = 0.20
        great.add((x, y))
land_area = 720                # great_cap = 20 (== great), medium_cap = 4 (< 12)
lake = set(basin) | great
WG._trim_oversized_lakes(lake, filled, H, land_area=land_area)
assert great <= lake, "the great lake fits its cap and should be untouched"
lake -= great
assert lake, "the whole lake was drained"
assert len(WG._lake_basins(lake)) == 1, (
    f"a receding lake broke into {len(WG._lake_basins(lake))} pools: "
    f"{sorted(lake)}")
assert lake < basin, "nothing was trimmed at all"
print(f"  ok    a 12-cell trough receded to one {len(lake)}-cell pool")

# ...and the great lake is CAPPED now, not exempt -- a basin big enough to be
# an inland sea is brought back to the great-lake cap. This is the change that
# stops a smooth continent's one basin flooding to 17% of the land.
sea = {(x, y) for x in range(40) for y in range(3)}   # 120 cells
sfilled = [[0.30] * 40 for _ in range(3)]
sH = [[0.0] * 40 for _ in range(3)]
sea_lake = set(sea)
WG._trim_oversized_lakes(sea_lake, sfilled, sH, land_area=1000)  # great_cap=28
assert 0 < len(sea_lake) <= int(1000 * WG._GREAT_LAKE_MAX_SHARE) + 1, (
    f"the great lake was not capped: {len(sea_lake)} cells")
print(f"  ok    a would-be inland sea capped to {len(sea_lake)} cells")

print("\n--- ...and it recedes to the DEEP end, not an arbitrary one ---")
deep_x = {x for x, _ in lake}
assert all(filled[1][x] >= 0.10 for x in deep_x), (
    f"the lake survived in the shallows: kept {sorted(deep_x)}")
print(f"  ok    what remains sits on the deepest cells")

print("\n--- real worlds: one great lake, and no second inland sea ---")
worst_share = 0.0
for seed in SEEDS:
    world = WG.generate_world(seed=seed, n_factions=8)
    land, basins = survey(world)
    share = len(world.lake_cells) / land
    worst_share = max(worst_share, share)
    cap = land * WG._LAKE_MAX_SHARE
    oversized = [b for b in basins if len(b) > cap * 1.05]
    assert len(oversized) <= WG._GREAT_LAKE_LIMIT, (
        f"seed {seed}: {len(oversized)} basins over the cap "
        f"({[len(b) for b in oversized]}), only {WG._GREAT_LAKE_LIMIT} allowed")
    # ...and the small lakes are still there. Draining the map would satisfy
    # every assertion above and be a much worse world.
    assert len(basins) >= 20, (
        f"seed {seed}: only {len(basins)} lakes left -- the small ones are "
        f"character and should have survived this")
    print(f"  ok    seed {seed}: {share*100:4.1f}% of land in {len(basins)} "
          f"lakes; largest {[len(b) for b in basins[:4]]}")

print("\n--- the continent is not waterlogged ---")
# Before: 8.9-14.6%. The remaining high-water seeds are high because of their
# ONE great lake, which is the case that was explicitly fine.
assert worst_share < 0.11, (
    f"lakes still cover {worst_share*100:.1f}% of the land at worst")
print(f"  ok    worst seed is {worst_share*100:.1f}% of land under fresh water")

print("\n--- and the world still works ---")
world = WG.generate_world(seed=SEEDS[0], n_factions=8)
assert world.river_cells, "no rivers at all"
assert not (world.river_cells & world.lake_cells), (
    "a cell is both river and lake")
for x, y in list(world.lake_cells)[:500]:
    assert world.owner[y][x] != WG.OCEAN, (x, y, "a lake in the sea")
from app.world import resources as R
for _ in range(3):
    R.advance_turn(world)
print(f"  ok    {len(world.river_cells):,} river cells, lakes all inland, "
      f"3 turns run clean")

print("\nLAKES TEST PASSED")
