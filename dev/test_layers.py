"""The two-layer data model (app/world/layers.py).

    python dev/test_layers.py [world.pkl]

Phase 0 of SUBTERRANEAN_PLAN.md: the model and the accessors, before anything
is built on them. Nothing here carves a real network or renders one -- what is
asserted is that the seam holds:

  * an old save is a valid surface-only world with no migration over its data;
  * a region without a layer reads as a surface region;
  * the underground is genuinely sparse, and rock is the default;
  * a gate is the ONLY way between layers, which is the property every later
    phase (defensible holds, sieges at the door) rests on.

The last one is the load-bearing assertion of the whole feature. If movement
can cross layers anywhere, none of the design above it means anything.
"""
import os
import pickle
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import layers as L
from app.world.worldgen import World, Region

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "worlds", "dev160.pkl")

print("--- a fresh world has an empty underworld ---")
w = World(40, 30)
assert w.under_cells == set() and w.under_kind == {} and w.gates == []
assert L.owner_at(w, 5, 5, L.UNDER) is None
assert L.kind_at(w, 5, 5, L.UNDER) is None
assert not L.is_open(w, 5, 5, L.UNDER), "solid rock read as open ground"
print("  ok    no cells, no gates, and rock is the default")

print("\n--- an old save comes back as a surface-only world ---")
old = pickle.load(open(PATH, "rb"))
for attr in ("under_cells", "under_kind", "under_owner", "under_region", "gates"):
    if hasattr(old, attr):
        delattr(old, attr)          # a world pickled before any of this existed
L.ensure_layers(old)
assert old.under_cells == set() and old.gates == []
L.ensure_layers(old)                # idempotent
assert old.under_cells == set()
surface_regions = L.regions_on(old, L.SURFACE)
assert len(surface_regions) == len(old.regions), (
    "a region pickled before layers existed did not read as a surface region")
assert not L.regions_on(old, L.UNDER)
print(f"  ok    {len(old.regions)} regions, all surface, migration is a no-op twice over")

print("\n--- a region's layer defaults, and is not stored on old ones ---")
r = Region(0, None, "Nowhere")
assert L.region_layer(r) == L.SURFACE and not L.is_under(r)
assert not hasattr(r, "layer"), (
    "Region grew a layer attribute -- every existing save would need migrating "
    "for a value that defaults correctly anyway")
r.layer = L.UNDER
assert L.is_under(r)
print("  ok    surface by default, underground only when said so")

print("\n--- carving and filling keep the set and the kinds in step ---")
w = World(40, 30)
L.carve(w, 10, 10, L.CAVERN)
L.carve(w, 11, 10)                  # defaults to a gallery
assert w.under_cells == {(10, 10), (11, 10)}
assert L.kind_at(w, 10, 10, L.UNDER) == L.CAVERN
assert L.kind_at(w, 11, 10, L.UNDER) == L.GALLERY
L.set_owner_at(w, 10, 10, L.UNDER, 3)
L.set_region_at(w, 10, 10, L.UNDER, 7)
assert L.owner_at(w, 10, 10, L.UNDER) == 3
assert L.region_at(w, 10, 10, L.UNDER) == 7
L.fill(w, 10, 10)
assert (10, 10) not in w.under_cells
assert L.kind_at(w, 10, 10, L.UNDER) is None
assert L.owner_at(w, 10, 10, L.UNDER) is None, (
    "rock still remembers who owned it -- a filled cell must forget everything")
assert L.region_at(w, 10, 10, L.UNDER) is None
try:
    L.carve(w, 1, 1, "cheese")
except ValueError:
    pass
else:
    raise AssertionError("carved a cell with a kind that does not exist")
print("  ok    carve/fill are the only way in and out, and fill forgets")

print("\n--- chasms and sunless water are open space you cannot walk on ---")
w = World(40, 30)
L.carve(w, 5, 5, L.CHASM)
L.carve(w, 6, 5, L.WATER)
L.carve(w, 7, 5, L.GALLERY)
assert not L.is_open(w, 5, 5, L.UNDER) and not L.is_open(w, 6, 5, L.UNDER)
assert L.is_open(w, 7, 5, L.UNDER)
assert L.CAVERN in L.SETTLEABLE_KINDS and L.GALLERY not in L.SETTLEABLE_KINDS, (
    "a gallery is a corridor, not a place anyone lives")
print("  ok    a drop and a lake are structure, not floor")

print("\n--- a gate is the ONLY way between the layers ---")
w = World(40, 30)
for x in range(8, 16):
    L.carve(w, x, 10, L.GALLERY)
# Open ground on the surface above them, so the surface layer is walkable too.
for x in range(8, 16):
    w.height[10][x] = 0.6
    w.owner[10][x] = -1
gate = L.add_gate(w, (12, 10), (12, 10), name="The Iron Door")

# Away from the gate: neighbours never leave the layer.
for x, y, layer in L.neighbours(w, 9, 10, L.UNDER):
    assert layer == L.UNDER, f"walked out of the underworld at {(x, y)}"
for x, y, layer in L.neighbours(w, 9, 10, L.SURFACE):
    assert layer == L.SURFACE, f"fell into the underworld at {(x, y)}"

# At the gate: exactly one step crosses, and it lands on the far mouth.
crossings = [(x, y) for x, y, layer in L.neighbours(w, 12, 10, L.SURFACE)
             if layer == L.UNDER]
assert crossings == [(12, 10)], crossings
back = [(x, y) for x, y, layer in L.neighbours(w, 12, 10, L.UNDER)
        if layer == L.SURFACE]
assert back == [(12, 10)], back
assert L.gate_at(w, 12, 10, L.SURFACE) is gate
assert L.gate_at(w, 9, 10, L.SURFACE) is None
print(f"  ok    {gate['name']!r} is the one crossing; every other step stays put")

print("\n--- gates are indexed, not scanned, and the index is not saved ---")
# neighbours() asks gate_at at every step and a path search walks neighbours,
# so a linear scan here is a quiet quadratic -- the same shape this project
# already had to dig out of choose_target once.
w = World(200, 200)
for i in range(120):
    L.carve(w, i, 5, L.GALLERY)
    L.add_gate(w, (i, 5), (i, 5), name=f"gate {i}")
assert L.gate_at(w, 60, 5, L.SURFACE)["name"] == "gate 60"
assert getattr(w, "_gate_index", None), "gate_at did not build an index"
L.add_gate(w, (150, 5), (150, 5))
assert w._gate_index is None, "adding a gate left a stale index in place"
assert L.gate_at(w, 150, 5, L.SURFACE) is not None
back = pickle.loads(pickle.dumps(w))
assert getattr(back, "_gate_index", None) is None, (
    "the derived gate index was pickled -- a second copy of the same truth, "
    "and stale the moment a gate moves")
assert L.gate_at(back, 60, 5, L.SURFACE)["name"] == "gate 60", (
    "the index did not rebuild itself after a load")
print("  ok    indexed on demand, dropped from the save, rebuilt on use")

print("\n--- the store is sparse, and rock costs nothing to store ---")
w = World(1100, 660)
for x in range(400, 500):
    for y in range(300, 340):
        L.carve(w, x, y, L.GALLERY)
carved = len(w.under_cells)
dense = w.w * w.h
print(f"  {carved:,} carved cells against {dense:,} in a dense mirror "
      f"({carved / dense:.1%})")
assert carved == 4000
blob = pickle.dumps({"cells": w.under_cells, "kind": w.under_kind,
                     "owner": w.under_owner, "region": w.under_region,
                     "gates": w.gates})
print(f"  a network that size pickles to {len(blob) / 1024:.0f} KB")
assert len(blob) < 400 * 1024, (
    "the underground is not staying in kilobytes -- see the save-size risk in "
    "SUBTERRANEAN_PLAN.md")
print("  ok    sparse, and small on disk")

print("\n--- and the whole thing survives a pickle round-trip ---")
w2 = pickle.loads(pickle.dumps(w))
assert w2.under_cells == w.under_cells
assert w2.under_kind == w.under_kind
print("  ok    round-trips")

print("\nLAYERS TEST PASSED")
