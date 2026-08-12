"""Conquering underground ground transfers ownership on the RIGHT layer.

    python dev/test_under_conquest.py

Armies can march through gates (commander._two_layer_path), so a surface
realm can fight a battle in the galleries. territory.transfer_region must
then flip the sparse `under_owner` map -- NOT the dense surface grid, whose
coordinates under a mountain belong to whoever owns the mountainside above
(usually nobody, or a different realm). Before this fix the two maps
diverged: the conqueror got a bogus surface territory and the loser kept
the galleries.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import layers as L
from app.world import territory
from app.world.worldgen import generate_world

world = generate_world(560, 340, seed=21, n_factions=8)
print("world:", world.under_summary)

print("\n--- a hold's galleries change hands on the under layer ---")
home = next(h for h in getattr(world, "under_homes", [])
            if h["kind"] == "hold")
old_idx = home["faction_idx"]
region = world.regions[home["regions"][0]]
conqueror = next(i for i in range(len(world.factions)) if i != old_idx)

# Ownership BEFORE, on both layers, at one of the region's cells.
x, y = region.cells[0]
under_before = L.owner_at(world, x, y, L.UNDER)
surf_before = world.owner[y][x]
assert under_before == old_idx, "the hold does not own its own gallery"
surf_owned = surf_before >= 0

territory.transfer_region(world, region, conqueror)

assert L.owner_at(world, x, y, L.UNDER) == conqueror, (
    "the galleries did not pass to the conqueror")
assert region.faction_idx == conqueror
assert world.owner[y][x] == surf_before, (
    "transfer_region touched the SURFACE grid for an under region -- the "
    "conqueror was handed the mountainside above as well")
assert region.id not in world.factions[old_idx].meta["regions"]
assert region.id in world.factions[conqueror].meta["regions"]
assert old_idx not in {L.owner_at(world, px, py, L.UNDER)
                       for px, py in region.cells}
assert all(L.owner_at(world, px, py, L.UNDER) == conqueror
           for px, py in region.cells)
print(f"  ok    region {region.name}: under_owner all flipped to {conqueror}, "
      f"surface owner untouched (was {'owned' if surf_owned else 'unclaimed'})")

print("\n--- and the same path still works for a surface region ---")
surface_region = next(r for r in world.regions
                      if not L.is_under(r) and r.faction_idx == old_idx)
sx, sy = surface_region.cells[0]
before = world.owner[sy][sx]
territory.transfer_region(world, surface_region, conqueror)
assert world.owner[sy][sx] == conqueror and before == old_idx
print("  ok    surface transfer unchanged")

print("\nUNDER CONQUEST TEST PASSED")
sys.exit(0)
