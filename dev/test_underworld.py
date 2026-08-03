"""Carving the galleries under the mountains (app/world/underworld.py).

    python dev/test_underworld.py [seed ...]

Phase 1 of SUBTERRANEAN_PLAN.md. Generates real worlds, because the only
honest test of worldgen is worldgen -- the same call the game makes.

The load-bearing assertion is that **no network is sealed**: every connected
piece of walkable underground has a gate on it. A hold nobody can reach is not
a hold, it is a hole in the save file, and the failure is silent -- nothing
crashes, the map just quietly contains a kingdom no army can ever visit. A
chasm dropped in the wrong place is exactly how it would happen.

`dev/under_shot.py` is the other half of this: it draws what these numbers
describe, and it has already caught two things no assertion here would have
(chambers rendering as four-pointed diamonds, and networks that never reached
daylight because nothing drove an adit).
"""
import os
import sys
import time
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import layers as L
from app.world import underworld as U
from app.world.worldgen import generate_world, OCEAN

SEEDS = [int(a) for a in sys.argv[1:]] or [3, 11]
W, H = 700, 420


def components(world):
    """Connected pieces of walkable underground -- one per network, or more if
    something cut one in half."""
    passable = {p for p in world.under_cells
                if L.kind_at(world, p[0], p[1], L.UNDER) in L.PASSABLE_KINDS}
    seen = set()
    out = []
    for start in sorted(passable):
        if start in seen:
            continue
        comp = {start}
        seen.add(start)
        queue = deque([start])
        while queue:
            x, y = queue.popleft()
            for nx, ny in U._neigh8(x, y, world.w, world.h):
                if (nx, ny) in passable and (nx, ny) not in seen:
                    seen.add((nx, ny))
                    comp.add((nx, ny))
                    queue.append((nx, ny))
        out.append(comp)
    return out


worlds = {}
for seed in SEEDS:
    t0 = time.perf_counter()
    worlds[seed] = generate_world(W, H, seed=seed, n_factions=6)
    print(f"seed {seed}: generated {W}x{H} in {time.perf_counter() - t0:.1f}s "
          f"-- {worlds[seed].under_summary}")

print("\n--- there is an underworld, and it is a few tenths of a per cent ---")
for seed, world in worlds.items():
    land = sum(1 for y in range(world.h) for x in range(world.w)
               if world.height[y][x] > 0.0)
    share = len(world.under_cells) / land
    print(f"  seed {seed}: {len(world.under_cells):,} cells "
          f"({share:.2%} of land), {world.under_summary['districts']} districts")
    assert world.under_cells, "no underworld was carved at all"
    assert share < 0.05, (
        f"{share:.1%} of the land is hollow -- that is a honeycomb, not a "
        "mountain range")

print("\n--- NO NETWORK IS SEALED: every piece has a gate on it ---")
for seed, world in worlds.items():
    mouths = {tuple(g["under"]) for g in world.gates}
    comps = components(world)
    sealed = [c for c in comps if not (c & mouths)]
    biggest_sealed = max((len(c) for c in sealed), default=0)
    print(f"  seed {seed}: {len(comps)} networks, {len(world.gates)} gates, "
          f"{len(sealed)} sealed (largest {biggest_sealed} cells)")
    assert not sealed, (
        f"{len(sealed)} networks have no gate -- the largest is "
        f"{biggest_sealed} cells of kingdom nobody can ever reach")

print("\n--- ...and every gate opens onto ground an army can stand on ---")
for seed, world in worlds.items():
    for gate in world.gates:
        gx, gy = gate["pos"]
        ux, uy = gate["under"]
        assert world.owner[gy][gx] != OCEAN, f"a gate opens into the sea at {gate['pos']}"
        assert (gx, gy) not in world.lake_cells, "a gate opens into a lake"
        assert L.is_open(world, gx, gy, L.SURFACE), (
            "a gate opens onto no land at all")
        assert L.kind_at(world, ux, uy, L.UNDER) in L.PASSABLE_KINDS, (
            "a gate's inner mouth is rock, water or a drop")
    print(f"  seed {seed}: all {len(world.gates)} gates open onto dry land")

print("\n--- the underworld only exists under the mountains and their skirts ---")
for seed, world in worlds.items():
    rock = {(x, y) for y in range(world.h) for x in range(world.w)
            if world.biome_grid[y][x] in U.UNDER_BIOMES}
    far = 0
    for x, y in world.under_cells:
        assert world.owner[y][x] != OCEAN, f"a gallery under the ocean at {(x, y)}"
        near = any((x + dx, y + dy) in rock
                   for dx in range(-U.SKIRT_MARGIN, U.SKIRT_MARGIN + 1)
                   for dy in range(-U.SKIRT_MARGIN, U.SKIRT_MARGIN + 1))
        far += not near
    print(f"  seed {seed}: {far} cells further than the skirt margin from any rock")
    assert far == 0, "the underworld has wandered out from under the mountains"

print("\n--- underground regions are real regions, with no sky ---")
for seed, world in worlds.items():
    under = L.regions_on(world, L.UNDER)
    assert under, "no underground regions were made"
    ids = [r.id for r in under]
    assert len(set(ids)) == len(ids), "two underground regions share an id"
    for r in under:
        assert world.regions[r.id] is r, "a region's id is not its index"
        assert r.stats["fertility"] == 0, (
            f"{r.name} has fertility -- it inherited the mountainside above it")
        assert r.dominant_climate == "subterranean", r.dominant_climate
        assert not r.biome_counts, "an underground region has biomes"
    covered = sum(len(r.cells) for r in under)
    passable = sum(1 for p in world.under_cells
                   if L.kind_at(world, p[0], p[1], L.UNDER) in L.PASSABLE_KINDS)
    print(f"  seed {seed}: {len(under)} regions covering {covered} of "
          f"{passable} walkable cells")
    assert covered == passable, (
        f"{passable - covered} walkable cells belong to no region -- nobody "
        "could ever own them")

print("\n--- and the weather stays above ground ---")
from app.world import resources as R
world = worlds[SEEDS[0]]
for r in L.regions_on(world, L.UNDER):
    r.faction_idx = 0                     # pretend somebody holds the halls
R.advance_weather(world)
under_ids = {r.id for r in L.regions_on(world, L.UNDER)}
wet = under_ids & set(getattr(world, "region_weather", {}))
assert not wet, f"{len(wet)} underground regions rolled weather -- there is no sky"
print("  ok    no gallery has a drought")

print("\n--- the same seed carves the same underworld ---")
again = generate_world(W, H, seed=SEEDS[0], n_factions=6)
first = worlds[SEEDS[0]]
assert again.under_cells == first.under_cells, "the carve is not reproducible"
assert [g["pos"] for g in again.gates] == [g["pos"] for g in first.gates]
assert ([r.name for r in L.regions_on(again, L.UNDER)]
        == [r.name for r in L.regions_on(first, L.UNDER)])
print(f"  ok    seed {SEEDS[0]} rebuilt cell for cell, gate for gate")

print("\nUNDERWORLD TEST PASSED")
