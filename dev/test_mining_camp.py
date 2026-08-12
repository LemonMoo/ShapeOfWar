"""The Mining Camp: a workforce for ore nobody lived near.

    python dev/test_mining_camp.py [world.pkl]

Villages are sited on farmland, which is correct, and Iron/Coal/Copper/Tin all
spawn only on mountain, which is 4.5% of the map. Measured on a fresh
10-faction world: 4 of 303 villages had a single mountain cell in catchment and
Iron was produced at 0.35 a turn world-wide. The camp is how that is really
solved -- you send people out to the seam rather than moving the mountain.

The properties worth guarding are the ones that stop it being a free upgrade:
it is gated on owning mountain, it is dug by the village's own hands, and a
region's seam is finite and shared between the camps on it.
"""
import sys
import os
import pickle

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import buildings as B
from app.world import construction
from app.world import resources as R

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "worlds", "dev160.pkl")
w = pickle.load(open(PATH, "rb"))
if w.player_faction_idx is None:
    w.player_faction_idx = 0
season = w.season


def clear(v):
    if hasattr(v, "_labor_cache"):
        del v._labor_cache


def sector_potential(v, sector):
    clear(v)
    return R._village_terrain_potential(w, v, season)[1].get(sector, 0)


eligible = [v for v in w.villages if v.faction_idx >= 0 and R.has_region_mountain(w, v)]
assert eligible, "no village in this world is in a region with any mountain"
owned = [v for v in w.villages if v.faction_idx >= 0]
print(f"villages {len(owned)}; in a region with mountain: {len(eligible)}")

print("\n--- gating ---")
settlement = next(s for s in w.settlements if s.faction_idx >= 0)
assert R.storage_max_tier(settlement, R.MINING_CAMP) == 0, (
    "a camp is people walking out to a seam -- that is a village's work")
assert R.storage_max_tier(eligible[0], R.MINING_CAMP) == 3
flat = [v for v in owned if not R.has_region_mountain(w, v)]
assert flat, "every village in this world has mountain; cannot test the gate"
keys = {o.building for o in B.build_options(w, flat[0], w.factions[flat[0].faction_idx])}
assert R.MINING_CAMP not in keys, (
    f"{flat[0].name}'s region has no mountain but a camp was offered anyway")
offered = {o.building for o in B.build_options(
    w, eligible[0], w.factions[eligible[0].faction_idx])}
assert R.MINING_CAMP in offered, f"{eligible[0].name} sits on a mountain region and got no card"
print(f"  ok    village-only; offered at {eligible[0].name}, hidden at {flat[0].name}")

print("\n--- tier 1 must not be gated on the thing it produces ---")
# Tools are smithed from Iron and this is the building that makes Iron exist.
cost1 = construction.storage_build_cost(eligible[0], R.MINING_CAMP, 1)
assert "Tools" not in cost1 and "Iron" not in cost1, (
    f"tier 1 costs {sorted(cost1)} -- gating the cure on the disease is exactly "
    f"the trap the Preserving House hit with Stone")
cost2 = construction.storage_build_cost(eligible[0], R.MINING_CAMP, 2)
assert "Tools" in cost2, "later tiers should want Tools; by then you have them"
print(f"  ok    tier 1 needs {sorted(cost1)}, tier 2 needs {sorted(cost2)}")

print("\n--- a camp adds ore, and only ore ---")
v = max(eligible, key=lambda x: R.region_mountain_cells(w, w.regions[x.region_id]))
region = w.regions[v.region_id]
# A mountain-region village may already be BORN with a tier-1 camp (the
# worldgen seed_family_camps bootstrap -- this dev world is one such), so
# the before/after measurement is taken around an explicit strip-and-build:
# the point under test is that the CAMP is what unlocks the ore.
R.set_storage_tier(v, R.MINING_CAMP, 0)
before_farm = sector_potential(v, "farming")
before_mine = sector_potential(v, "mining")
try:
    R.set_storage_tier(v, R.MINING_CAMP, 1)
    after_farm = sector_potential(v, "farming")
    after_mine = sector_potential(v, "mining")
    assert after_mine > before_mine, (before_mine, after_mine)
    assert after_farm == before_farm, (
        f"a camp changed what grows in the fields: {before_farm} -> {after_farm}")
    print(f"  ok    {v.name}: mining potential {before_mine:.1f} -> {after_mine:.1f}, "
          f"farming unchanged at {after_farm:.1f}")

    ores = [r for r in R._village_terrain_potential(w, v, season)[2]
            .get("mining", {})]
    assert any(o in ores for o in ("Iron", "Coal", "Copper", "Tin")), ores
    print(f"  ok    it yields real ore: {', '.join(sorted(ores))}")

    print("\n--- dug by the village's own hands, not for free ---")
    rep = R.village_labor_report(w, v)
    mining_row = next((r for r in rep["sectors"] if r["sector"] == "mining"), None)
    assert mining_row is not None, "mining is not in the labour report"
    assert mining_row["workers"] > 0, "a camp that costs no hands is a free upgrade"
    assert mining_row["output"] <= mining_row["potential"]
    print(f"  ok    {mining_row['workers']} of {rep['workforce']} hands on the "
          f"seam, {mining_row['output']} of {mining_row['potential']} "
          f"({mining_row['limited_by']}-limited)")

    # The hard proof it goes through the labour limit: no hands, no ore.
    orig_adults = v.adults
    v.adults = 0
    clear(v)
    starved = R.compute_village_yield(w, v, season)
    v.adults = orig_adults
    clear(v)
    assert sum(a for r, a in starved.items()
               if R.production_sector(r) == "mining") < 1, starved
    print("  ok    with no workforce the camp produces nothing")

    print("\n--- the region's seam is finite and shared ---")
    total = R.region_mountain_cells(w, region)
    alone = R.mining_camp_cells(w, v)
    assert alone <= total, (alone, total)
    others = [w.villages[vid] for vid in getattr(region, "villages", [])
              if 0 <= vid < len(w.villages) and w.villages[vid] is not v]
    if others:
        R.set_storage_tier(others[0], R.MINING_CAMP, 1)
        shared = R.mining_camp_cells(w, v)
        R.set_storage_tier(others[0], R.MINING_CAMP, 0)
        assert shared <= alone, (
            f"a second camp in the same region did not split the seam: "
            f"{alone} -> {shared}")
        print(f"  ok    region has {total} cells; one camp works {alone}, "
              f"two work {shared} each")

    # Whatever the tier, a camp can never work more than the region has.
    for tier in range(1, len(R.MINING_CAMP_CELLS)):
        R.set_storage_tier(v, R.MINING_CAMP, tier)
        assert R.mining_camp_cells(w, v) <= total, (tier, total)
    R.set_storage_tier(v, R.MINING_CAMP, 1)
    print(f"  ok    no tier can work more mountain than the region has ({total})")

    print("\n--- the card says what it is for ---")
    opt = next(o for o in B.build_options(w, v, w.factions[v.faction_idx])
               if o.building == R.MINING_CAMP)
    assert opt.category == "Industry", opt.category
    assert "mountain" in opt.reason.lower(), opt.reason
    print(f"  ok    {opt.priority} — {opt.reason}")
finally:
    R.set_storage_tier(v, R.MINING_CAMP, 0)
    clear(v)

print("\n--- a real turn still runs ---")
built = []
for village in eligible[:20]:
    R.set_storage_tier(village, R.MINING_CAMP, 1)
    built.append(village)
try:
    for _ in range(3):
        R.advance_turn(w)
    for node in list(w.settlements) + list(w.villages):
        for r, amt in (node.resources or {}).items():
            assert amt >= 0, (node.name, r, amt)
    ore_held = sum((n.resources or {}).get("Iron", 0)
                   for n in list(w.settlements) + list(w.villages))
    print(f"  ok    3 turns with {len(built)} camps; no negative stock, "
          f"Iron held {ore_held:,.0f}")
finally:
    for village in built:
        R.set_storage_tier(village, R.MINING_CAMP, 0)

print("\nMINING CAMP TEST PASSED")
