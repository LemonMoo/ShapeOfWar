"""The biome matrix: latitude means something, and no land is strictly best.

    python dev/test_biomes.py [seed]

Biomes used to come from a threshold cascade that never saw temperature, so
the same moisture gave the same biome at the equator and at the pole. They now
come from a temperature x moisture matrix with relief and water as overrides.

Two properties are worth guarding above all the rest:

  * The six ORIGINAL biome names still exist. biome_grid and
    region.biome_counts are pickled, so every dev world and player save
    already holds those strings; renaming one silently orphans a region's
    whole biome profile.
  * NO biome is strong in everything. That is the fairness mechanism for
    species homelands -- terrain is meant to be asymmetric in kind, not in
    quality, so that every realm needs something its neighbours have.
"""
import sys
import os
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import resources as R
from app.ui.map_view import _BIOME_COLORS

SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 42

print("--- old saves keep working ---")
ORIGINAL = ("mountain", "forest", "plains", "coastal", "desert", "swamp")
for name in ORIGINAL:
    assert name in R.BIOMES, (
        f"'{name}' was removed from BIOMES. Every pickled world stores that "
        f"string in biome_grid and region.biome_counts -- dropping it orphans "
        f"their whole biome profile")
print(f"  ok    all {len(ORIGINAL)} original names survive; "
      f"{len(R.BIOMES)} biomes total")

print("\n--- every biome is drawable and produces something ---")
for name in R.BIOMES:
    assert name in _BIOME_COLORS, f"{name} has no map colour and renders as no-data"
producers = defaultdict(list)
for res, spec in R.RESOURCE_SPAWN.items():
    for biome in spec["biomes"]:
        producers[biome].append(res)
    unknown = set(spec["biomes"]) - set(R.BIOMES)
    assert not unknown, f"{res} spawns in unknown biome(s) {unknown}"
barren = [b for b in R.BIOMES if not producers.get(b)]
assert not barren, f"these biomes produce nothing at all: {barren}"
print(f"  ok    all {len(R.BIOMES)} have a colour and at least one resource")

print("\n--- temperature actually changes the answer ---")
# The whole point of the rebuild: same ground, different latitude, different
# land. Held away from the relief/coast/water overrides so the matrix is what
# is being tested.
FAR, MID = 999, 999
cold = R.classify_biome(0.2, 0.55, FAR, MID, temperature=0.05)
warm = R.classify_biome(0.2, 0.55, FAR, MID, temperature=0.95)
assert cold != warm, (cold, warm)
print(f"  ok    moisture 0.55 gives '{cold}' at the pole and '{warm}' at the equator")

seen = {R.classify_biome(0.2, m / 20.0, FAR, MID, temperature=t / 20.0)
        for m in range(21) for t in range(21)}
assert len(seen) >= 6, sorted(seen)
print(f"  ok    sweeping both axes reaches {len(seen)} distinct biomes: "
      f"{', '.join(sorted(seen))}")

print("\n--- landform still beats weather ---")
assert R.classify_biome(0.9, 0.5, FAR, MID, 0.5) == "mountain"
assert R.classify_biome(0.45, 0.5, FAR, MID, 0.5) == "highland"
assert R.classify_biome(0.2, 0.5, 1, MID, 0.5) == "coastal"
assert R.classify_biome(0.1, 0.9, FAR, 1, 0.7) == "swamp"
# ...but frozen ground does not rot, however wet it is.
assert R.classify_biome(0.1, 0.9, FAR, 1, 0.05) != "swamp"
print("  ok    mountain/highland/coastal/swamp override the matrix; "
      "frozen wetland is not swamp")

print("\n--- no biome is strong in everything ---")
FOOD = {n for n, s in R.RESOURCES.items()
        if s["category"] == "Crops" and s["edible"]}
HERD = {n for n, s in R.RESOURCES.items() if s["category"] == "Livestock"}
WOOD = {n for n, s in R.RESOURCES.items() if s["category"] == "Forestry"}
ORE = {n for n, s in R.RESOURCES.items() if s["category"] == "Mining"}
print(f"  {'biome':<10} {'food':>5} {'herd':>5} {'wood':>5} {'ore':>5}")
allrounders = []
for biome in R.BIOMES:
    rs = set(producers.get(biome, []))
    profile = [len(rs & FOOD), len(rs & HERD), len(rs & WOOD), len(rs & ORE)]
    print(f"  {biome:<10} " + " ".join(f"{n:>5}" for n in profile))
    if all(n >= 2 for n in profile):
        allrounders.append(biome)
assert not allrounders, (
    f"{allrounders} produce plenty of food AND herds AND timber AND ore. A "
    f"species placed there would simply be better off, which is exactly the "
    f"unfairness the asymmetric-terrain design exists to prevent")
print("  ok    none is good at all four")

print("\n--- on a real generated world ---")
from app.world.worldgen import generate_world
w = generate_world(seed=SEED, n_factions=10)
counts = Counter(b for row in w.biome_grid for b in row if b)
land = sum(counts.values())
for biome in R.BIOMES:
    share = 100.0 * counts.get(biome, 0) / land
    print(f"  {biome:<10} {share:5.1f}%")
never = [b for b in R.BIOMES if not counts.get(b)]
assert not never, f"biomes that never appear on a real map: {never}"
assert max(counts.values()) / land < 0.45, (
    f"one biome covers {100*max(counts.values())/land:.0f}% of the map")
print(f"  ok    all {len(R.BIOMES)} appear, none dominates the map")

# Latitude must be legible: the poles and the equator must differ.
h = w.h
polar = Counter()
equator = Counter()
for y in range(h // 8):
    polar.update(b for b in w.biome_grid[y] if b)
for y in range(int(h * 0.44), int(h * 0.56)):
    equator.update(b for b in w.biome_grid[y] if b)
assert polar.most_common(1)[0][0] != equator.most_common(1)[0][0], (
    polar.most_common(2), equator.most_common(2))
print(f"  ok    the poles read '{polar.most_common(1)[0][0]}' and the equator "
      f"'{equator.most_common(1)[0][0]}'")

print("\n--- a world still runs ---")
for _ in range(3):
    R.advance_turn(w)
for node in list(w.settlements) + list(w.villages):
    for res, amt in (node.resources or {}).items():
        assert amt >= 0, (node.name, res, amt)
produced = sum(sum((n.resources or {}).values())
               for n in list(w.settlements) + list(w.villages))
assert produced > 0, "nothing anywhere is producing on the new biome map"
print(f"  ok    3 turns, no negative stock, {produced:,.0f} units held")

print("\nBIOMES TEST PASSED")
