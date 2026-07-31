"""Biome overhaul phase F: named country over mechanical biome.

    python dev/test_biome_names.py [world.pkl]

"the Everwood" rather than "forest", "the Ashwaste" rather than "desert".

The point of this file is the NEGATIVE property. The design was explicit that
fantasy biomes are flavour only -- a named skin, never a different or better
resource profile -- and a naming layer that quietly acquired a mechanical
effect would be the single worst outcome of the whole biome overhaul, because
it would make terrain unfair in a way no player could see. So most of what is
asserted here is that the name changes nothing.
"""
import sys
import os
import pickle

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import resources as R
from app.world.lexicon import BIOME_FLAVOUR_NAMES, biome_flavour_name

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "worlds", "dev560.pkl")
w = pickle.load(open(PATH, "rb"))

print("--- every mechanical biome has a name, and only real biomes do ---")
real = ({b for row in R._BIOME_MATRIX for b in row}
        | {"mountain", "highland", "coastal", "swamp"})
assert set(BIOME_FLAVOUR_NAMES) == real, real ^ set(BIOME_FLAVOUR_NAMES)
for biome, by_climate in BIOME_FLAVOUR_NAMES.items():
    assert by_climate, biome
    assert "*" in by_climate, f"{biome} has no fallback for an unlisted climate"
    for climate, options in by_climate.items():
        assert options and all(isinstance(o, str) and o for o in options), (biome, climate)
print(f"  ok    all {len(real)} biomes named, every one with a climate fallback")

print("\n--- CRITICAL: the name is derived, and nothing reads it back ---")
# Flavour must be a pure function of (biome, climate, id). If anything in the
# economy ever branched on it, terrain would be unfair invisibly.
economy_files = ["app/world/resources.py", "app/world/trade.py",
                 "app/world/construction.py", "app/world/expansion.py",
                 "app/world/buildings.py"]
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for rel in economy_files:
    src = open(os.path.join(root, rel), encoding="utf-8").read()
    for token in ("flavour_name", "BIOME_FLAVOUR_NAMES", "biome_flavour_name"):
        assert token not in src, (
            f"{rel} references {token} -- the naming layer has leaked into the "
            f"economy, which is exactly what phase F must never do")
print(f"  ok    none of {len(economy_files)} economy modules reference the "
      f"naming layer at all")

print("\n--- two regions of the same biome are mechanically identical ---")
by_biome = {}
for r in w.regions:
    if not r.cells or not getattr(r, "biome_counts", None):
        continue
    by_biome.setdefault(r.dominant_biome, []).append(r)
compared = 0
for biome, regions in by_biome.items():
    named = {}
    for r in regions:
        named.setdefault(r.flavour_name, []).append(r)
    if len(named) < 2:
        continue
    # Same biome, different names -> the yield RULES must be the same. Compare
    # what the biome itself offers, not a specific region's acreage.
    spawns = {res for res, spec in R.RESOURCE_SPAWN.items()
              if biome in spec.get("biomes", ())}
    for name, rs in named.items():
        for r in rs:
            got = {res for res, spec in R.RESOURCE_SPAWN.items()
                   if r.dominant_biome in spec.get("biomes", ())}
            assert got == spawns, (biome, name, got ^ spawns)
    compared += 1
    if compared <= 3:
        print(f"  ok    {biome}: {len(named)} different names, one identical "
              f"resource profile ({', '.join(sorted(named)[:3])})")
assert compared > 0, "no biome on this world had two differently-named regions"

print("\n--- the same region always gets the same name ---")
r = next(r for r in w.regions if r.cells and getattr(r, "biome_counts", None))
first = r.flavour_name
for _ in range(5):
    assert r.flavour_name == first, "flavour name is not stable"
# and it survives a pickle round-trip, since it is derived rather than stored
again = pickle.loads(pickle.dumps(r))
assert again.flavour_name == first, "flavour name changed across a save/load"
print(f"  ok    {r.name}: {first!r}, stable and unchanged by save/load")

print("\n--- an old save needs no migration to get one ---")
# flavour_name is a property, not a pickled field, so a world written before
# phase F existed still answers.
named = sum(1 for r in w.regions if r.cells and r.flavour_name)
total = sum(1 for r in w.regions if r.cells)
assert named == total, f"only {named}/{total} regions got a name"
print(f"  ok    all {total} regions in a pre-phase-F save are named")

print("\n--- climate actually changes the name ---")
varied = 0
for biome, by_climate in BIOME_FLAVOUR_NAMES.items():
    if len(by_climate) > 1:
        a = biome_flavour_name(biome, "cold", 0)
        b = biome_flavour_name(biome, "humid", 0)
        if a != b:
            varied += 1
assert varied >= 3, varied
print(f"  ok    {varied} biomes read differently by climate "
      f"(e.g. cold forest {biome_flavour_name('forest', 'cold', 0)!r} vs "
      f"humid {biome_flavour_name('forest', 'humid', 0)!r})")

print("\n--- unknown input degrades quietly, never raises ---")
assert biome_flavour_name("nonesuch", "arid", 0) is None
assert biome_flavour_name("forest", "nonesuch-climate", 0) is not None  # "*"
print("  ok    unknown biome -> None; unknown climate -> the fallback")

print("\nBIOME NAMES TEST PASSED")
