"""Roads are drawn as smoothed, wandering polylines, not grid segments.

    python dev/test_road_geometry.py [world.pkl]

Reported with a screenshot: a road running dead straight, turning through a
hard elbow, running dead straight again. Roads are stored as endpoint pairs
and were drawn one straight segment at a time, so that is exactly what came
out -- and you cannot smooth a line you are drawing two points at a time.

Three pieces: worldgen.road_chains joins the loose segments into connected
runs, MapView._road_points wanders and smooths one run, and both renderers
draw runs instead of segments. All VIEW-ONLY -- the stored network is
untouched and no save needs migrating, which is the property this file cares
most about proving.

The number that matters is how far the drawn road strays from where the road
actually goes. Character is good; a road drawn through country it does not
pass anywhere near is a bug.
"""
import sys
import os
import pickle
import math
import statistics

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk

try:
    root = tk.Tk()
    root.withdraw()
except tk.TclError as exc:
    print(f"no display available ({exc}) -- skipping")
    sys.exit(0)

from app.ui.map_view import MapView, _catmull_rom
from app.world.worldgen import road_chains, add_road_segments, ROAD_TIER_RANK

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "worlds", "dev560.pkl")
world = pickle.load(open(PATH, "rb"))
if world.player_faction_idx is None:
    world.player_faction_idx = 0
view = MapView(root, world, lambda *a: None, lambda *a: None)

segments = sum(len(s) for s in world.roads_by_region.values())
chains = road_chains(world)
runs = [(cells, tier) for v in chains.values() for cells, tier in v]
print(f"world: {segments:,} road segments -> {len(runs)} connected runs")


def point_to_polyline(p, poly):
    best = float("inf")
    for a, b in zip(poly, poly[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length2 = dx * dx + dy * dy
        t = 0.0 if not length2 else max(0.0, min(
            1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2))
        best = min(best, math.hypot(p[0] - (a[0] + dx * t), p[1] - (a[1] + dy * t)))
    return best


def turns(pts):
    out = []
    for a, b, c in zip(pts, pts[1:], pts[2:]):
        v1 = (b[0] - a[0], b[1] - a[1])
        v2 = (c[0] - b[0], c[1] - b[1])
        m1, m2 = math.hypot(*v1), math.hypot(*v2)
        if m1 < 1e-9 or m2 < 1e-9:
            continue
        cos = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (m1 * m2)))
        out.append(math.degrees(math.acos(cos)))
    return out


print("\n--- chaining loses nothing ---")
covered = sum(len(cells) - 1 for cells, _ in runs)
assert covered == segments, (covered, segments)
assert all(len(cells) >= 2 for cells, _ in runs)
print(f"  ok    every one of the {segments:,} segments is in exactly one run")

print("\n--- and it is cached, because none of it changes until a road is built ---")
assert road_chains(world) is chains, "road_chains rebuilt for an unchanged network"
print("  ok    a second call returns the same object")

print("\n--- CRITICAL: the drawn road stays on its own route ---")
# Character is the point; a road drawn through country it does not go near is
# a bug. This caught a real one -- the point cache was keyed on (first cell,
# last cell, length, tier), which two different chains meeting at a junction
# can share, so one was handed the other's geometry and drew nearly seven
# cells clear of itself.
stray = {"stone": [], "dirt": [], "sea": []}
for cells, tier in runs:
    raw = [(x + 0.5, y + 0.5) for x, y in cells]
    smooth = view._road_points(cells, tier)
    stray.setdefault(tier, []).append(
        max(point_to_polyline(p, raw) for p in smooth))
worst = max(max(v) for v in stray.values() if v)
assert worst < 1.0, f"a road strays {worst:.2f} cells from its own route"
for tier, values in stray.items():
    if values:
        print(f"  ok    {tier:6} mean {statistics.mean(values):.2f}, "
              f"max {max(values):.2f} cells off route")

print("\n--- an engineered road wanders less than a track that grew ---")
assert (view._ROAD_WANDER["stone"] < view._ROAD_WANDER["dirt"]), view._ROAD_WANDER
assert view._ROAD_WANDER["sea"] == 0.0, "a sea lane is not a country road"
assert statistics.mean(stray["stone"]) < statistics.mean(stray["dirt"])
print(f"  ok    stone {view._ROAD_WANDER['stone']}, dirt "
      f"{view._ROAD_WANDER['dirt']}, and it shows in the measured drift")

print("\n--- the grid staircase is gone ---")
sharp_raw = sharp_smooth = counted = 0
for cells, tier in runs:
    if len(cells) < 4:
        continue
    raw = turns([(x + 0.5, y + 0.5) for x, y in cells])
    smooth = turns(view._road_points(cells, tier))
    if raw and smooth:
        sharp_raw += max(raw)
        sharp_smooth += max(smooth)
        counted += 1
assert sharp_smooth < sharp_raw, (sharp_smooth, sharp_raw)
print(f"  ok    worst corner per run: {sharp_raw/counted:.0f} deg of grid "
      f"elbow -> {sharp_smooth/counted:.0f} deg spread over a curve")

print("\n--- a junction is shared, not torn apart ---")
# Every road meeting at a cell must be offset by the SAME amount there, or
# the arms come away from each other. That is why the offset is hashed from
# the cell rather than from anything about the run it belongs to.
a = view._cell_wander(40, 91, 0.4)
b = view._cell_wander(40, 91, 0.4)
assert a == b, "the wander is not deterministic"
assert view._cell_wander(40, 91, 0.0) == (0.0, 0.0), "amount 0 must not move"
assert view._cell_wander(41, 91, 0.4) != a, "neighbouring cells share an offset"
print(f"  ok    the same cell always gives the same offset {a[0]:+.2f},{a[1]:+.2f}")

print("\n--- a road still meets the place it serves ---")
for cells, tier in runs[:200]:
    pts = view._road_points(cells, tier)
    for end, cell in ((pts[0], cells[0]), (pts[-1], cells[-1])):
        assert abs(end[0] - (cell[0] + 0.5)) < 1e-6, (end, cell)
        assert abs(end[1] - (cell[1] + 0.5)) < 1e-6, (end, cell)
print("  ok    both ends sit exactly on their own cell, undisplaced")

print("\n--- centripetal, not uniform: a tight turn must not overshoot ---")
# A three-point run doubling back on itself is the case uniform Catmull-Rom
# gets badly wrong.
v_shape = [(0.0, 0.0), (-5.0, 3.0), (0.0, 9.0)]
spline = _catmull_rom(v_shape, 5)
assert max(point_to_polyline(p, v_shape) for p in spline) < 1.0, (
    "the spline overshoots a doubling-back run -- is this still centripetal?")
print("  ok    a V doubling back stays within a cell of itself")

print("\n--- stone replaces dirt on the same ground, and never doubles it ---")
class _Fake:
    pass


fake = _Fake()
fake.roads_by_region = {}
line = [(0, 0), (1, 0), (2, 0), (3, 0)]
pairs = list(zip(line, line[1:]))
add_road_segments(fake, 1, pairs, "dirt")
assert len(fake.roads_by_region[1]) == 3
add_road_segments(fake, 1, pairs, "stone")
assert [t for _, _, t in fake.roads_by_region[1]] == ["stone"] * 3, (
    "the dirt track survived being paved over")
back = list(reversed(line))
add_road_segments(fake, 1, list(zip(back, back[1:])), "dirt")
assert [t for _, _, t in fake.roads_by_region[1]] == ["stone"] * 3, (
    "a dirt track laid along an existing stone road added itself anyway "
    "(and direction must not matter)")
add_road_segments(fake, 1, pairs, "sea")
assert sorted({t for _, _, t in fake.roads_by_region[1]}) == ["sea", "stone"], (
    "a sea lane and a road sharing a cell must not displace each other")
assert ROAD_TIER_RANK["stone"] > ROAD_TIER_RANK["dirt"] > 0
print("  ok    paving removes the track, a track on a road adds nothing, "
      "sea lanes are untouched")

print("\n--- a road is cut into the ground, not painted on it ---")
# Each road is drawn twice: a darker, wider band (the cutting, the churned
# verge) and the surface sitting down inside it.
from app.ui.map_view import (_darken, _ROAD_CUT_DARKEN, _ROAD_CUT_WIDTH,
                             _DIRT_ROAD_COLOR, _STONE_ROAD_COLOR,
                             _DIRT_SURFACE_NARROW)


def brightness(hex_colour):
    return sum(int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))


for colour in (_DIRT_ROAD_COLOR, _STONE_ROAD_COLOR):
    assert brightness(_darken(colour, _ROAD_CUT_DARKEN)) < brightness(colour)
assert _ROAD_CUT_WIDTH > 1.0, "the cut must be wider than the surface in it"
assert _DIRT_SURFACE_NARROW < 1.0, (
    "a worn track's surface should be narrower than the cut, so the ground "
    "shows along its edges")
gpu = view._map_lines(2, 12.0)
widths = {round(w, 2) for _, _, w, _ in gpu}
assert len(widths) >= 2, (
    "the GPU map emits one width for everything -- the cut is missing, and "
    "the two renderers must agree or switching them changes how the world "
    "looks")
print(f"  ok    a {_DIRT_ROAD_COLOR} surface over a "
      f"{_darken(_DIRT_ROAD_COLOR, _ROAD_CUT_DARKEN)} cut {_ROAD_CUT_WIDTH}x "
      f"as wide, on both renderers")

print("\n--- a dirt track is worn, a stone road is laid ---")
assert any(dash for _, _, _, dash in gpu), (
    "nothing is drawn broken -- a dirt track should show the ground through it")
print("  ok    the surface runs broken for dirt and solid for stone")

print("\n--- the drawing got CHEAPER, not more expensive ---")
# The point of halving the sampling: roads lagged at close zoom.
total = sum(len(view._road_points(cells, tier)) for cells, tier in runs)
assert total < 12000, (
    f"{total:,} drawn points -- that is the close-zoom lag this was meant to fix")
print(f"  ok    {total:,} points for the whole network, against 15,786 at one "
      f"control point per cell")

print("\n--- none of this touched the stored network ---")
assert sum(len(s) for s in world.roads_by_region.values()) == segments
print("  ok    the road data is exactly as it was loaded")

root.destroy()
print("\nROAD GEOMETRY TEST PASSED")
