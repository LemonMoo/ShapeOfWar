"""Phase 5 of the economy pass: waste, not production.

    python dev/test_spoilage.py [world.pkl]

Two behavioural changes, both found by measuring what was actually being
destroyed rather than by reasoning about the model:

  * A landed fish is food. Fish was flagged inedible by analogy to Livestock
    needing slaughtering -- but a village has no smokehouse, so it could
    neither smoke nor eat its own catch, and watched it rot at spoil_rate
    0.35.
  * A settlement's fishing fleet is a side trade. Settlements have no labour
    model (villages got one in Phase 14), so a coastal settlement landed its
    FULL geographic yield every turn forever: 1,210 Fish/turn from
    settlements alone against a world-wide food demand of 181/turn.

Plus the storage throttle's hard 0.0 floor becoming a soft one, so a full
node is throttled rather than switched off.
"""
import sys
import os
import pickle

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import resources as R

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "worlds", "dev560.pkl")
w = pickle.load(open(PATH, "rb"))

print("--- a landed fish is food ---")
assert R.RESOURCES["Fish"]["edible"], "Fish must be edible"
assert "Fish" in R._FOOD_SOURCES, "Fish must be in the food pool"
assert "Smoked Fish" in R._FOOD_SOURCES, "curing must not remove it from the pool"
print(f"  ok    Fish and Smoked Fish are both real food sources "
      f"({len(R._FOOD_SOURCES)} total)")

print("\n--- curing is still worth doing (it keeps, fresh fish does not) ---")
raw = R.RESOURCES["Fish"]["spoil_rate"]
cured = R.RESOURCES["Smoked Fish"]["spoil_rate"]
assert cured < raw, (raw, cured)
print(f"  ok    Fish spoils at {raw}, Smoked Fish at {cured} -- the pressure to "
      f"smoke a surplus catch is unchanged")

print("\n--- CRITICAL: 'edible' is not the same as 'a staple' ---")
# The flag means "consumed by mouth", which is broader: sweeping every
# edible into the food pool would let a village live on salt or wine.
for name in ("Salt", "Wine", "Beer"):
    assert R.RESOURCES[name]["edible"], f"{name} is still edible-by-mouth"
    assert name not in R._FOOD_SOURCES, (
        f"{name} must not count as a food source -- nobody subsists on it")
assert "Wine" in R._LUXURY_GOODS, "Wine is still luxury demand"
print("  ok    Salt/Wine/Beer stay out of the food pool; Wine is still a luxury")

print("\n--- a village can now eat its own catch ---")
village = next(v for v in w.villages if v.faction_idx >= 0)
before_res = dict(village.resources or {})
try:
    village.resources = {"Fish": 500}
    needs = R.settlement_needs(village, w.season)
    food_needed = needs["Food"]
    assert food_needed > 0
    eaten = R._consume_from_pool(village.resources, R._FOOD_SOURCES, food_needed)
    assert eaten == food_needed, (eaten, food_needed)
    assert village.resources["Fish"] == 500 - food_needed
    print(f"  ok    {village.name} ate {eaten} of its own Fish with nothing else "
          f"in store")
finally:
    village.resources = before_res

print("\n--- settlement fishing was NOT capped, deliberately ---")
# Scaling the settlement catch down halved fish spoilage and cost far more
# than it bought: on a developed save it turned a 60-turn population trend
# of -5.6% into -18.5%, and even a mild 0.6 cut still cost -9.9%. The waste
# it "fixed" is cosmetic -- fish rots because it spoils at 0.35, not because
# storage is full, and the pools were measured non-binding. Guarding the
# revert so it does not get reintroduced from the audit numbers alone.
assert not hasattr(R, "SETTLEMENT_FISHING_SHARE"), (
    "capping the settlement catch reduces waste by cutting the food supply "
    "populations actually eat -- see the note above _node_fish_yield")
print("  ok    settlements still land their full catch; the cut was reverted")

print("\n--- a village's catch is still its own labour decision ---")
import inspect
src = inspect.getsource(R._produce_fishing)
assert "village_labor_state" in src, "villages must still go through the labour model"
print("  ok    a village lands whatever share of its workforce went fishing")

print("\n--- the storage throttle taper is soft, not a cliff ---")
assert 0.0 < R.STORAGE_THROTTLE_FLOOR < 1.0, R.STORAGE_THROTTLE_FLOOR
node = next(v for v in w.villages if v.faction_idx >= 0)
before_res = dict(node.resources or {})
try:
    pool_res = "Logs"
    pool = R.storage_class(pool_res)
    cap = R.node_pool_capacity(node, pool)
    bulk = R.resource_bulk(pool_res)
    node.resources = {pool_res: int((cap * 2.0) / bulk)}   # far past capacity
    throttled = R.storage_throttle(node, pool_res)
    assert throttled == R.STORAGE_THROTTLE_FLOOR, throttled
    assert throttled > 0.0, "an over-full node must still trickle, not switch off"
    node.resources = {pool_res: 0}
    assert R.storage_throttle(node, pool_res) == 1.0
    print(f"  ok    empty -> 1.0, over capacity -> {throttled} "
          f"(production continues, throttled)")
finally:
    node.resources = before_res

print("\n--- a real turn still runs, and nothing goes negative ---")
for _ in range(3):
    R.advance_turn(w)
for n in list(w.settlements) + list(w.villages):
    for res, amt in (n.resources or {}).items():
        assert amt >= 0, (n.name, res, amt)
print("  ok    3 turns, no negative stock anywhere")

print("\nSPOILAGE TEST PASSED")
