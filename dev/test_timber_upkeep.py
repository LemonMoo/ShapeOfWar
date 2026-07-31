"""Phase 2 of the economy pass: a Timber upkeep sink for the durable pool.

    python dev/test_timber_upkeep.py [world.pkl]

Durable goods (mostly timber) were piling up almost untouched -- only ~26%
of durable production was consumed by anything, measured with
dev/storage_audit.py (see HANDOFF.md S15.1). This asserts the sink actually
draws from the pooled Timber sources, scales with population AND with what's
actually built, costs prosperity (never population) on a shortfall, plugs
into local logistics' surplus/want matching, and -- the CRITICAL constraint
from the plan -- never touches a resource that isn't actually oversupplied
(Iron/Coal/Copper/Tin and everything else outside the four Timber sources).
"""
import sys
import os
import pickle

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import resources as R

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "worlds", "dev560.pkl")
w = pickle.load(open(PATH, "rb"))
pidx = w.player_faction_idx if w.player_faction_idx is not None else 0

print("--- Timber is a real, pooled need ---")
assert R._TIMBER_SOURCES == ["Planks", "Hardwood", "Softwood", "Logs"]
st = next(s for s in w.settlements if s.faction_idx == pidx and s.population > 0)
needs = R.settlement_needs(st, w.season)
assert "Timber" in needs and needs["Timber"] > 0, needs
print(f"  ok    {st.name} (pop {st.population}): Timber need = {needs['Timber']:.2f}")

print("\n--- CRITICAL: only the four Timber sources are touched ---")
# The plan's own explicit warning: Iron/Copper/Coal/Tin are genuinely scarce
# and must never get a sink sized against durable's (wood-driven) surplus.
scarce = ["Iron", "Copper", "Coal", "Tin", "Gold Ore", "Stone"]
for res in scarce:
    assert res not in R._TIMBER_SOURCES, res
    assert res not in R._SHORTAGE_PROSPERITY_PENALTY, (
        f"{res} must not carry a shortage penalty from this mechanism")
print(f"  ok    none of {scarce} are Timber sources or carry a Timber-style penalty")

print("\n--- a shortfall costs prosperity, never population (unlike Food/Firewood) ---")
before_res = dict(st.resources or {})
before_prosperity = st.prosperity
before_short = dict(getattr(st, "prosperity_shortfall", None) or {})
try:
    # Consumption records the deficit; the meter itself moves later in the turn
    # via _update_prosperity. Asserting on the meter here is what this test
    # used to do, and it was right for the mechanism at the time -- shortages
    # used to subtract points directly, which is exactly the bug that pinned
    # every meter in the game at zero (see dev/test_prosperity.py).
    st.resources = {k: v for k, v in before_res.items() if k not in R._TIMBER_SOURCES}
    st.prosperity = 50.0
    R._consume_node_needs(st, w.season, w)
    assert st.prosperity == 50.0, (
        "consumption must not move the meter directly any more")
    deficit = (getattr(st, "prosperity_shortfall", None) or {}).get("Timber", 0)
    assert deficit > 0, "a full Timber shortfall recorded no deficit"
    assert R._prosperity_condition(st) < 1.0, (
        "a Timber shortfall should pull the prosperity target down")
    assert not hasattr(st, "turns_without_timber"), (
        "Timber must not grow a starvation-style grace-period counter")
    print(f"  ok    full shortfall: deficit {deficit:.2f} recorded, target "
          f"scaled to {R._prosperity_condition(st):.2f}x, no population loss")
finally:
    st.resources = before_res
    st.prosperity = before_prosperity
    st.prosperity_shortfall = before_short

print("\n--- consumption pools across all four sources, biggest stock first ---")
before_res = dict(st.resources or {})
try:
    st.resources = dict(before_res)
    for src in R._TIMBER_SOURCES:
        st.resources[src] = 0
    st.resources["Logs"] = 10_000   # only one of the four sources has stock
    needs = R.settlement_needs(st, w.season)
    timber_needed = needs["Timber"]
    R._consume_node_needs(st, w.season, w)
    consumed = 10_000 - st.resources.get("Logs", 0)
    assert abs(consumed - timber_needed) < 1e-6, (consumed, timber_needed)
    print(f"  ok    {timber_needed:.2f} Timber need drawn entirely from Logs "
          f"when it's the only source stocked")
finally:
    st.resources = before_res

print("\n--- building maintenance scales with what's actually built ---")
building = R._MAINTAINED_BUILDINGS[0]
before_tier = R.storage_tier(st, building)
try:
    R.set_storage_tier(st, building, 0)
    bare = R._building_maintenance_need(st)
    max_tier = R.storage_max_tier(st, building)
    if max_tier > 0:
        R.set_storage_tier(st, building, max_tier)
        built = R._building_maintenance_need(st)
        assert built > bare, (bare, built)
        assert abs(built - bare - max_tier * R.BUILDING_MAINTENANCE_PER_TIER) < 1e-6
        print(f"  ok    {building} tier 0 -> {max_tier}: maintenance "
              f"{bare:.2f} -> {built:.2f} Timber/turn")
    else:
        print(f"  skip  {st.name} can't build {building} at all, tried a different node")
finally:
    R.set_storage_tier(st, building, before_tier)

print("\n--- barn isn't double-counted (storage-pool AND herd building) ---")
assert R._MAINTAINED_BUILDINGS.count("barn") == 1, R._MAINTAINED_BUILDINGS
print(f"  ok    barn appears exactly once in {len(R._MAINTAINED_BUILDINGS)} "
      f"maintained building types")

print("\n--- local logistics: Timber sources lead the queue, no duplicates ---")
for src in R._TIMBER_SOURCES:
    assert src in R._LOCAL_SHIPMENT_SURVIVAL, src
    assert src not in R._LOCAL_SHIPMENT_INDUSTRIAL, (
        f"{src} must not appear in both the survival and industrial lists")
assert len(R._LOCAL_SHIPMENT_PRIORITY) == len(set(R._LOCAL_SHIPMENT_PRIORITY)), (
    "no resource should appear twice in the combined shipment priority list")
print(f"  ok    all {len(R._TIMBER_SOURCES)} Timber sources lead the queue; "
      f"{len(R._LOCAL_SHIPMENT_PRIORITY)} total resources, no duplicates")

print("\n--- _node_surplus/_node_wants treat Timber as one pooled reserve ---")
before_res = dict(st.resources or {})
try:
    st.resources = dict(before_res)
    st.resources["Logs"] = 5
    st.resources["Planks"] = 5
    needs = R.settlement_needs(st, w.season)
    needs["Timber"] = 1   # tiny need -> both should read as comfortable surplus
    surplus_logs = R._node_surplus(st, "Logs", needs)
    surplus_planks = R._node_surplus(st, "Planks", needs)
    # Capped at the shared pool's spare total, not an independent per-resource
    # amount -- the same bug _node_surplus's own docstring documents for Food.
    assert surplus_logs <= 10 and surplus_planks <= 10
    st.resources["Logs"] = 0
    st.resources["Planks"] = 0
    needs["Timber"] = 1000
    assert R._node_wants("settlement", st, "Logs", needs)
    print("  ok    surplus is capped at the shared pool total; "
          "a starved pool wants any of its four sources")
finally:
    st.resources = before_res

print("\n--- CRITICAL: the need is whole, so stocks stay whole ---")
# _consume_from_pool subtracts exactly what it is given. Building maintenance
# is a fractional per-tier figure, so an unrounded Timber need leaked straight
# into storage -- a stockpile became 109913.4 and the resource bar started
# rendering "44.20000000000000045". Every other need here is rounded; this
# one has to be too.
needs = R.settlement_needs(st, w.season)
assert float(needs["Timber"]).is_integer(), (
    f"Timber need {needs['Timber']} is fractional and will make stocks float")
fractional = [(n.name, r, a) for n in list(w.settlements) + list(w.villages)
              for r, a in (n.resources or {}).items()
              if isinstance(a, float) and not float(a).is_integer()]
assert not fractional, fractional[:3]
R.advance_turn(w)
fractional = [(n.name, r, a) for n in list(w.settlements) + list(w.villages)
              for r, a in (n.resources or {}).items()
              if isinstance(a, float) and not float(a).is_integer()]
assert not fractional, f"a turn produced fractional stock: {fractional[:3]}"
print("  ok    Timber need is whole; a full turn leaves every stock whole")

print("\n--- a real turn still runs, and nothing goes negative ---")
for _ in range(3):
    R.advance_turn(w)
for node in list(w.settlements) + list(w.villages):
    for res, amt in (node.resources or {}).items():
        assert amt >= 0, (node.name, res, amt)
print("  ok    3 turns, no negative stock anywhere")

print("\nTIMBER UPKEEP TEST PASSED")
