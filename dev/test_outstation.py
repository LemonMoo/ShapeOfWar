"""Biome overhaul phase D: one terrain building per biome family.

    python dev/test_outstation.py [world.pkl]

Phase D's stated risk was that twelve bespoke buildings cannot be verified
equal in value, and getting it wrong would quietly make some homelands better
-- undoing the "asymmetric in KIND, not quality" principle the whole overhaul
rests on.

The answer was to make them not twelve effects but ONE effect with a biome
argument, reusing the shape the Mining Camp already had: not "+X% ore" but
REACH -- working cells of a given kind that lie in your REGION but outside
your own catchment. So the fairness property is not "these are balanced", it
is "these are literally the same building", and that is what this asserts.
"""
import sys
import os
import pickle
import inspect

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import resources as R
from app.world import buildings as B
from app.world import construction as C

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "worlds", "dev560.pkl")
w = pickle.load(open(PATH, "rb"))

print("--- every biome belongs to exactly one family ---")
real = ({b for row in R._BIOME_MATRIX for b in row}
        | {"mountain", "highland", "coastal", "swamp"})
seen = {}
for building, (biomes, sample, label) in R.OUTSTATIONS.items():
    assert biomes, building
    assert sample in (R.OUTSTATION_CROP, R.OUTSTATION_INDUSTRY), (building, sample)
    assert label, building
    for b in biomes:
        assert b in real, f"{building} claims unknown biome {b!r}"
        assert b not in seen, (
            f"{b} is worked by BOTH {seen[b]} and {building} -- an overlap "
            f"lets one region be worked twice over")
        seen[b] = building
missing = real - set(seen)
assert not missing, f"no outstation works: {sorted(missing)}"
print(f"  ok    {len(real)} biomes across {len(R.OUTSTATIONS)} families, "
      f"no overlap and no orphan")

print("\n--- CRITICAL: the family is one building, not four ---")
# This is the entire fairness guarantee. If any member ever gets its own
# reach, price or build time, phase D has quietly become the thing it was
# designed not to be.
first = None
for building in R.OUTSTATIONS:
    spec = (C.STORAGE_BUILD_COSTS[building], C.STORAGE_BUILD_TURNS[building])
    if first is None:
        first, first_name = spec, building
        continue
    assert spec[0] == first[0], (
        f"{building} costs differently from {first_name} -- one homeland is "
        f"now cheaper to work than another")
    assert spec[1] == first[1], f"{building} builds in different time"
print(f"  ok    all {len(R.OUTSTATIONS)} share one cost table and one build time")

village = next(v for v in w.villages if v.faction_idx >= 0)
tiers = {b: R.storage_max_tier(village, b) for b in R.OUTSTATIONS}
assert len(set(tiers.values())) == 1, tiers
assert R.OUTSTATION_CELLS is R.MINING_CAMP_CELLS, (
    "the family must share ONE reach table")
print(f"  ok    same max tier ({next(iter(tiers.values()))}) and one shared "
      f"reach table {R.OUTSTATION_CELLS}")

print("\n--- village-only, and gated on the REGION not the catchment ---")
settlement = next(s for s in w.settlements if s.faction_idx >= 0)
for b in R.OUTSTATIONS:
    assert R.storage_max_tier(settlement, b) == 0, f"{b} offered at a settlement"
src = inspect.getsource(R.has_region_outstation_land)
assert "region" in src.lower()
print("  ok    settlements cannot build one; the gate reads the region's land")

print("\n--- reach is capped by the region and SHARED between camps ---")
target = None
for v in w.villages:
    if v.faction_idx < 0:
        continue
    for b in R.OUTSTATIONS:
        if R.has_region_outstation_land(w, v, b):
            region = w.regions[v.region_id]
            peers = [w.villages[i] for i in getattr(region, "villages", [])
                     if 0 <= i < len(w.villages)]
            if len(peers) >= 2:
                target, building = v, b
                break
    if target:
        break
assert target is not None, "no region with two villages to test sharing"
region = w.regions[target.region_id]
peers = [w.villages[i] for i in region.villages if 0 <= i < len(w.villages)]
saved = {id(p): R.storage_tier(p, building) for p in peers}
try:
    for p in peers:
        R.set_storage_tier(p, building, 0)
    R.set_storage_tier(target, building, 1)
    alone = R.outstation_cells(w, target, building)
    other = next(p for p in peers if p is not target)
    R.set_storage_tier(other, building, 1)
    shared = R.outstation_cells(w, target, building)
    total = R.region_outstation_cells(w, region, building)
    assert shared <= alone, (alone, shared)
    assert shared <= total, (shared, total)
    print(f"  ok    {building}: {alone} cells alone -> {shared} with a second "
          f"camp (region holds {total})")
finally:
    for p in peers:
        R.set_storage_tier(p, building, saved[id(p)])

print("\n--- it competes for hands rather than being free output ---")
src = inspect.getsource(R._village_terrain_potential)
assert "village_outstation_cells" in src
assert src.index("village_outstation_cells") < src.index("by_sector = defaultdict"), (
    "outstation cells must be added to the LAND's offer BEFORE the labour "
    "limit, or a camp is free production instead of a choice")
print("  ok    cells are added before the Phase 14 labour cap")

print("\n--- a family feeds only its own sample ---")
# Ore must never arrive in the harvest, nor grain out of a quarry.
crop_biomes = {b for bs, s, _ in
               ((v[0], v[1], v[2]) for v in R.OUTSTATIONS.values())
               if s == R.OUTSTATION_CROP for b in bs}
ind_biomes = {b for bs, s, _ in
              ((v[0], v[1], v[2]) for v in R.OUTSTATIONS.values())
              if s == R.OUTSTATION_INDUSTRY for b in bs}
assert not (crop_biomes & ind_biomes), crop_biomes & ind_biomes
reach = R.village_outstation_cells(w, village)
assert set(reach) == {R.OUTSTATION_CROP, R.OUTSTATION_INDUSTRY}
print(f"  ok    {len(crop_biomes)} crop-sample biomes, {len(ind_biomes)} "
      f"industry-sample, no biome in both")

print("\n--- the Mining Camp still behaves exactly as it always did ---")
# It is shipped, measured and tested against mountain specifically. The
# family must not have widened it.
assert R.OUTSTATIONS[R.MINING_CAMP][0] == ("mountain",), (
    "the Mining Camp was widened beyond mountain -- its measured numbers were "
    "tuned against mountain alone")
mv = next((v for v in w.villages
           if v.faction_idx >= 0 and R.has_region_mountain(w, v)), None)
if mv is not None:
    keep = R.storage_tier(mv, R.MINING_CAMP)
    try:
        R.set_storage_tier(mv, R.MINING_CAMP, 1)
        assert R.mining_camp_cells(w, mv) == R.outstation_cells(w, mv, R.MINING_CAMP)
        print(f"  ok    mountain-only, and mining_camp_cells still agrees "
              f"({R.mining_camp_cells(w, mv)} cells)")
    finally:
        R.set_storage_tier(mv, R.MINING_CAMP, keep)

print("\n--- each one is offered where its land is, and only there ---")
nation = w.factions[village.faction_idx]
offered = {b: 0 for b in R.OUTSTATIONS}
wrong = []
for v in w.villages[:250]:
    if v.faction_idx < 0:
        continue
    keys = {o.building for o in B.build_options(w, v, nation)}
    for b in R.OUTSTATIONS:
        if b in keys:
            offered[b] += 1
            if not R.has_region_outstation_land(w, v, b):
                wrong.append((v.name, b))
assert not wrong, f"offered with no land to work: {wrong[:3]}"
assert sum(offered.values()) > 0, "no outstation was offered anywhere"
print(f"  ok    {dict(offered)}, never where the region has none")

print("\n--- a real turn still runs, and nothing goes negative ---")
for _ in range(3):
    R.advance_turn(w)
for n in list(w.settlements) + list(w.villages):
    for res, amt in (n.resources or {}).items():
        assert amt >= 0, (n.name, res, amt)
print("  ok    3 turns, no negative stock anywhere")

print("\nOUTSTATION TEST PASSED")
