"""Coin: the Gold Mine, the Mint, and the chain that has to work between them.

    python dev/test_gold.py [world.pkl]

Gold was a real produced resource on paper long before this and produced almost
none in practice, because the chain from ore in the ground to coin in the
treasury was severed at four separate links -- each one invisible on its own and
only findable by walking the whole chain end to end. That is what this asserts:
not "does the Mint multiply correctly" but "can a unit of ore actually get from
the seam to the vault".
"""
import sys
import os
import pickle

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import buildings as B
from app.world import construction
from app.world import resources as R
from app.world import trade as T

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "worlds", "dev560.pkl")
w = pickle.load(open(PATH, "rb"))
pidx = w.player_faction_idx if w.player_faction_idx is not None else 0
nation = w.factions[pidx]

print("--- link 1: a seam in the ground actually yields ore ---")
seam = [v for v in w.villages if v.faction_idx >= 0 and R.has_gold_seam(w, v)]
assert seam, "no village anywhere in this world sits on a gold seam"
best = max(seam, key=lambda v: R._village_terrain_potential(w, v, w.season)[0].get("Gold Ore", 0))
potential = R._village_terrain_potential(w, best, w.season)[0].get("Gold Ore", 0)
assert potential > 0, best.name
print(f"  ok    {best.name}: {potential:.2f} ore/turn of terrain potential")

print("\n--- a fractional yield accumulates instead of rounding to nothing ---")
# The bug this exists for: a rare seam yielding 0.195/turn rounded to 0 every
# turn forever, so the whole resource silently did not exist.
tiny = 0.2
v = best
before_stock = (v.resources or {}).get("Gold Ore", 0)
before_carry = dict(getattr(v, "_yield_carry", {}) or {})
try:
    v.resources = dict(v.resources or {})
    v.resources.pop("Gold Ore", None)
    v._yield_carry = {}
    delivered_turns = 0
    for _ in range(20):
        got = R._deliver_village_yield(v, {"Gold Ore": tiny}, throttle=False)
        if got.get("Gold Ore"):
            delivered_turns += 1
    total = (v.resources or {}).get("Gold Ore", 0)
    assert total == 4, f"20 turns at {tiny}/turn should bank 4 units, got {total}"
    assert delivered_turns == 4, delivered_turns
    print(f"  ok    {tiny}/turn for 20 turns banks {total} units over "
          f"{delivered_turns} deliveries — nothing rounded away")
finally:
    v.resources["Gold Ore"] = before_stock
    v._yield_carry = before_carry

print("\n--- link 2: a Gold Mine multiplies what comes out of that seam ---")
before_tier = R.storage_tier(best, R.GOLD_MINE)
try:
    R.set_storage_tier(best, R.GOLD_MINE, 0)
    if hasattr(best, "_labor_cache"):
        del best._labor_cache
    plain = R._village_terrain_potential(w, best, w.season)[0].get("Gold Ore", 0)
    R.set_storage_tier(best, R.GOLD_MINE, 1)
    if hasattr(best, "_labor_cache"):
        del best._labor_cache
    mined = R._village_terrain_potential(w, best, w.season)[0].get("Gold Ore", 0)
    assert mined > plain, (plain, mined)
    ratio = mined / plain
    assert abs(ratio - R.GOLD_MINE_YIELD_MULT[1]) < 0.15, ratio
    print(f"  ok    tier 1 Gold Mine: {plain:.2f} -> {mined:.2f} ore/turn "
          f"(x{ratio:.2f})")
finally:
    R.set_storage_tier(best, R.GOLD_MINE, before_tier)
    if hasattr(best, "_labor_cache"):
        del best._labor_cache

print("\n--- link 3: nothing low in a priority list is starved forever ---")
# Both run_local_logistics and run_sell_to_city ship ONE resource per node per
# turn off a fixed list. Every entry must reach the front within one cycle.
tail = R._LOCAL_SHIPMENT_INDUSTRIAL
seen_first = set()
for turn in range(len(tail)):
    order = R.local_shipment_priority(turn)
    assert order[:len(R._LOCAL_SHIPMENT_SURVIVAL)] == R._LOCAL_SHIPMENT_SURVIVAL, (
        "survival goods must keep the front unconditionally")
    seen_first.add(order[len(R._LOCAL_SHIPMENT_SURVIVAL)])
assert seen_first == set(tail), sorted(set(tail) - seen_first)
assert R.local_shipment_priority(5) == R.local_shipment_priority(5 + len(tail)), (
    "rotation must be a pure function of the turn -- a replayed turn has to "
    "ship the same goods")
print(f"  ok    all {len(tail)} industrial goods lead the queue within one "
      f"cycle, deterministically")

order_a = R.rotate_for_turn(T._SELL_TO_CITY_ORDER, 0)
order_b = R.rotate_for_turn(T._SELL_TO_CITY_ORDER, 1)
assert order_a != order_b and sorted(order_a) == sorted(order_b)
assert "Gold Ore" in order_a
lead = {R.rotate_for_turn(T._SELL_TO_CITY_ORDER, t)[0]
        for t in range(len(T._SELL_TO_CITY_ORDER))}
assert lead == set(T._SELL_TO_CITY_ORDER)
print(f"  ok    sell-to-city rotates too — every one of "
      f"{len(T._SELL_TO_CITY_ORDER)} goods gets the lead")

print("\n--- link 4: a Village can sell to a City, not only a Settlement ---")
# 82 of 85 ore-bearing regions have no settlement in them at all, so this tier
# is the ONLY one that could ever move their ore.
import inspect
src = inspect.getsource(T.run_sell_to_city)
assert "_faction_regional_nodes" in src, (
    "run_sell_to_city must source from villages too, not just settlements")
villages_with_surplus = 0
for v in w.villages:
    if v.faction_idx != pidx:
        continue
    needs = R.settlement_needs(v, w.season)
    for res in T._NONPERISHABLE_RESOURCES:
        if T._node_surplus(v, res, needs) >= T.SELL_TO_CITY_MIN_QUANTITY:
            villages_with_surplus += 1
            break
print(f"  ok    villages are eligible sources; {villages_with_surplus} of the "
      f"player's have shippable non-perishable surplus right now")

print("\n--- link 5: a Mint strikes ore into coin, faster and better by tier ---")
city = next((s for s in w.settlements if s.faction_idx == pidx and s.kind == "city"),
            next(s for s in w.settlements if s.faction_idx == pidx))
before_res = dict(city.resources or {})
before_tier = R.storage_tier(city, R.MINT)
try:
    results = {}
    for tier in range(len(R.MINT_RATE_MULT)):
        R.set_storage_tier(city, R.MINT, tier)
        city.resources = dict(before_res)
        city.resources["Gold Ore"] = 5000
        city.resources["Gold"] = 0
        R.advance_settlement_production_chains(w)
        results[tier] = city.resources.get("Gold", 0)
        assert city.resources["Gold Ore"] < 5000, "the mint consumed no ore"
    for tier in range(1, len(R.MINT_RATE_MULT)):
        assert results[tier] > results[tier - 1], (tier, results)
    print("  ok    coin struck per turn by tier: "
          + ", ".join(f"t{t} {g:,}" for t, g in results.items()))

    # The upper tiers beat 1:1 -- an upgrade is not just "the same thing,
    # faster" (see MINT_YIELD_PER_ORE).
    R.set_storage_tier(city, R.MINT, len(R.MINT_RATE_MULT) - 1)
    city.resources = dict(before_res)
    city.resources["Gold Ore"] = 50
    city.resources["Gold"] = 0
    R.advance_settlement_production_chains(w)
    struck, left = city.resources.get("Gold", 0), city.resources.get("Gold Ore", 0)
    assert struck > (50 - left), (
        f"the top-tier mint should recover more than 1 coin per ore: "
        f"{struck} coin from {50 - left} ore")
    print(f"  ok    top tier: {struck} coin from {50 - left} ore "
          f"(x{R.MINT_YIELD_PER_ORE[-1]:g} refining)")
finally:
    R.set_storage_tier(city, R.MINT, before_tier)
    city.resources = before_res

print("\n--- the two buildings are gated to the right kind of place ---")
village = next(v for v in w.villages if v.faction_idx == pidx)
assert R.storage_max_tier(city, R.GOLD_MINE) == 0, "a settlement is not a mine"
assert R.storage_max_tier(village, R.MINT) == 0, "a village has no forge"
assert R.storage_max_tier(city, R.MINT) > 0 and R.storage_max_tier(village, R.GOLD_MINE) > 0
print("  ok    Gold Mine is village-only; Mint is settlement-only")

no_seam = [v for v in w.villages if v.faction_idx == pidx and not R.has_gold_seam(w, v)]
if no_seam:
    keys = {o.building for o in B.build_options(w, no_seam[0], nation)}
    assert R.GOLD_MINE not in keys, (
        "a Gold Mine was offered at a village with no seam under it")
    print(f"  ok    {no_seam[0].name} has no seam and is offered no Gold Mine")
own_seam = [v for v in seam if v.faction_idx == pidx]
if own_seam:
    opt = next((o for o in B.build_options(w, own_seam[0], nation)
                if o.building == R.GOLD_MINE), None)
    assert opt is not None, f"{own_seam[0].name} sits on a seam but got no card"
    assert opt.priority in ("urgent", "useful"), opt
    print(f"  ok    {own_seam[0].name} sits on a seam: {opt.priority} — {opt.reason}")

print("\n--- the Mint card reads the ore, not the treasury ---")
before_res = dict(city.resources or {})
try:
    city.resources = dict(before_res)
    city.resources.pop("Gold Ore", None)
    idle = next(o for o in B.build_options(w, city, nation) if o.building == R.MINT)
    assert idle.priority == "idle" and "No Gold Ore" in idle.reason, idle
    city.resources["Gold Ore"] = 5000
    busy = next(o for o in B.build_options(w, city, nation) if o.building == R.MINT)
    assert busy.priority == "urgent", busy
    assert busy.score > idle.score
    print(f"  ok    no ore: {idle.priority} — {idle.reason}")
    print(f"  ok    5,000 ore: {busy.priority} — {busy.reason}")
finally:
    city.resources = before_res

print("\n--- a real turn still runs, and nothing goes negative ---")
for _ in range(3):
    R.advance_turn(w)
for node in list(w.settlements) + list(w.villages):
    for res, amt in (node.resources or {}).items():
        assert amt >= 0, (node.name, res, amt)
    for res, carry in (getattr(node, "_yield_carry", {}) or {}).items():
        assert 0 <= carry < 1, (node.name, res, carry)
print("  ok    3 turns; every carry stays a proper fraction, no negative stock")

print("\nGOLD TEST PASSED")
