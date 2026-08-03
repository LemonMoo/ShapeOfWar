"""Choosing where the player starts (WORLDGEN_START_PLAN.md, Part B1).

    python dev/test_start_choice.py

generate_world grew a `player_start` parameter. The guarantee the whole
start-picker rests on: for a fixed seed the TERRAIN is identical whether or not
a start is chosen -- so a world previewed with the player auto-placed shows the
exact ground the player will get when they pick a cell and it regenerates. Only
WHO owns WHICH capital changes; the map does not.

Terrain is generated before capitals and does not depend on them, so this is a
property the code should already have -- this pins it down before B2/B3 build
on it.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world.worldgen import generate_world
from app.world import layers as L

SEED = 7
W, H = 560, 340


def terrain_signature(world):
    """Everything about the ground, and nothing about who lives on it."""
    return (
        tuple(tuple(row) for row in world.height),
        tuple(tuple(row) for row in world.biome_grid),
        tuple(sorted(world.lake_cells)),
        tuple(sorted(world.river_cells)),
        tuple(sorted(world.under_cells)),
        world.sea_level,
    )


print("--- a fixed seed grows the same ground, chosen start or not ---")
auto = generate_world(W, H, seed=SEED, n_factions=6, player_species="Humans",
                      player_name="Test")
player_cap = auto.factions[auto.player_faction_idx].meta["capital"]
print(f"  auto-placed player capital: {player_cap}")

# Now pick a specific, deliberately-different cell and regenerate.
land = [(x, y) for y in range(auto.h) for x in range(auto.w)
        if L.owner_at(auto, x, y, L.SURFACE) is not None
        and (x, y) not in auto.lake_cells]
far = max(land, key=lambda c: (c[0] - player_cap[0]) ** 2 + (c[1] - player_cap[1]) ** 2)
chosen = generate_world(W, H, seed=SEED, n_factions=6, player_species="Humans",
                        player_name="Test", player_start=far)
print(f"  chosen start: {far}")

assert terrain_signature(auto) == terrain_signature(chosen), (
    "the terrain changed when a start was chosen -- the preview would lie")
print("  ok    height, biomes, lakes, rivers and the underworld are identical")

print("\n--- ...and the player is actually placed where they chose ---")
chosen_cap = chosen.factions[chosen.player_faction_idx].meta["capital"]
print(f"  player capital is now {chosen_cap}")
assert chosen_cap == tuple(far), (
    f"asked for {far}, got {chosen_cap}")
assert chosen.player_faction_idx == 0
print("  ok    the player's capital is the cell they picked")

print("\n--- a start off the coast snaps to the nearest land, not the sea ---")
off = generate_world(W, H, seed=SEED, n_factions=6, player_species="Humans",
                     player_name="Test", player_start=(0, 0))
cap = off.factions[0].meta["capital"]
assert L.owner_at(off, cap[0], cap[1], L.SURFACE) is not None, (
    "the player was founded on ocean")
assert (cap[0], cap[1]) not in off.lake_cells
print(f"  ok    (0,0) snapped to land at {cap}")

print("\n--- rivals keep their distance from the chosen start ---")
caps = [f.meta["capital"] for f in chosen.factions]
pcap = caps[0]
nearest = min(((r[0] - pcap[0]) ** 2 + (r[1] - pcap[1]) ** 2) ** 0.5
              for r in caps[1:])
print(f"  nearest rival capital is {nearest:.0f} cells from the player")
assert nearest > 5, "a rival spawned on top of the player's chosen start"
print("  ok    rivals spaced away from the player's pick")

print("\n--- the un-chosen path is untouched (affinity still places slot 0) ---")
a2 = generate_world(W, H, seed=SEED, n_factions=6, player_species="Humans",
                    player_name="Test")
assert a2.factions[0].meta["capital"] == player_cap, (
    "generate_world without player_start changed behaviour")
print("  ok    same seed, no start given -> same auto-placement as before")

print("\n--- _gen_params reproduces terrain even for a retried world ---")
# world.seed alone is not enough for a world that retried internally (the retry
# replaces the seed; _target_n/_n_plates came from the original). The stashed
# params are, and startsites.regenerate_with_start uses them.
from app.world import startsites
base = generate_world(W, H, seed=SEED, n_factions=6, player_species="Humans",
                      player_name="Test")
assert hasattr(base, "_gen_params"), "generation params were not stashed"
cell = base.factions[0].meta["capital"]
repro = startsites.regenerate_with_start(base, cell, species="Humans", name="Test")
assert terrain_signature(base) == terrain_signature(repro), (
    "regenerate_with_start did not reproduce the terrain")
assert tuple(repro.factions[0].meta["capital"]) == tuple(cell)
print("  ok    same terrain cell-for-cell, player at the chosen cell")

print("\nSTART CHOICE TEST PASSED")
