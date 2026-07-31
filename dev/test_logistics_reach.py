"""Can a raw good actually reach a workshop? Three ways it could not.

    python dev/test_logistics_reach.py [world.pkl]

The domestic economy has four tiers that move goods, and a raw material only
has to be blocked by ONE of them to be stranded forever. Measured before these
fixes on a fresh 10-faction world at turn 120, Tools, Weapons, Shields, Bricks
and Cloth all sat at exactly zero world-wide and 16 of ~22 settlement recipes
were blocked on a zero input -- not from any shortage, but from three separate
plumbing faults that were each individually invisible.

This asserts the plumbing, not the numbers: every fault below was found by
asking "can a unit of clay get from the pit to a brickworks", never by looking
at a stock level.
"""
import sys
import os
import pickle

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import resources as R
from app.world import trade as T

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "worlds", "dev160.pkl")
w = pickle.load(open(PATH, "rb"))
if w.player_faction_idx is None:
    w.player_faction_idx = 0
print(f"world: turn {w.turn}, {len(w.settlements)} settlements, "
      f"{len(w.villages)} villages")

print("\n--- 1. route discovery must not be starved by its own budget ---")
# A solved pair is cached forever, so the cost of a bigger budget is transient
# while the benefit is permanent. At 1/turn only 120 of 340 village->city pairs
# had EVER been looked up after 120 turns, and every unsolved one turned out to
# have a perfectly good route.
owned = [v for v in w.villages if v.faction_idx >= 0]
per_search_ms = 2.6      # measured; see the constant's own comment
budget = T.REGIONAL_PATH_BUDGET_PER_TURN
assert budget >= 4, (
    f"REGIONAL_PATH_BUDGET_PER_TURN is {budget}; at that rate a world of "
    f"{len(owned)} villages needs ~{len(owned)//max(1,budget)} turns of "
    f"nothing else competing before its goods can move at all")
turns_to_clear = len(owned) // budget
print(f"  ok    budget {budget}/turn (~{budget*per_search_ms:.0f} ms transient), "
      f"clears {len(owned)} pairs in ~{turns_to_clear} turns")

print("\n--- 2. nodes must not all scan the same order on the same turn ---")
# Rotating on the turn alone puts every node in the world in lockstep, so a
# good only gets a chance on the one turn its rotation brings it forward -- and
# only from nodes under their shipment cap right then.
order = T._SELL_TO_CITY_ORDER
a = R.rotate_for_turn(order, 10 + 0)
b = R.rotate_for_turn(order, 10 + 1)
assert a != b, "two different nodes scan an identical order on the same turn"
assert sorted(a) == sorted(b) == sorted(order), "rotation dropped or added a good"
# Every good must lead for SOME node on any given turn, which is the property
# that actually matters -- it is what stops a low-volume good waiting for its
# one turn in N.
leaders = {R.rotate_for_turn(order, 10 + node_id)[0] for node_id in range(len(order))}
assert leaders == set(order), sorted(set(order) - leaders)
print(f"  ok    on one fixed turn, all {len(order)} goods lead for some node")

# Still deterministic: same turn + same node => same order, always.
assert R.rotate_for_turn(order, 7 + 3) == R.rotate_for_turn(order, 7 + 3)
assert R.local_shipment_priority(5, 2) == R.local_shipment_priority(5, 2)
assert R.local_shipment_priority(5, 2) != R.local_shipment_priority(5, 3)
# Survival goods keep the front unconditionally, whatever the node.
for node_id in (0, 1, 17, 250):
    head = R.local_shipment_priority(3, node_id)[:len(R._LOCAL_SHIPMENT_SURVIVAL)]
    assert head == R._LOCAL_SHIPMENT_SURVIVAL, (node_id, head[:4])
print("  ok    deterministic per (turn, node), and survival goods still lead")

print("\n--- 3. barely-perishable industrial inputs must be shippable ---")
# The old filter was spoil_rate <= 0 exactly, which excluded Cotton (0.02),
# Wool (0.01), Paper (0.02) and Resin (0.02) alongside Milk (0.40). Nothing
# else could move them: they are not consumption goods so no need-based tier
# wants them, and local logistics is region-locked.
for good in ("Cotton", "Wool", "Paper", "Resin"):
    assert good in T._SELL_TO_CITY_ORDER, (
        f"{good} (spoil {R.RESOURCES[good]['spoil_rate']}) cannot be carted to "
        f"a city, and nothing else in the game will move it either")
print(f"  ok    Cotton/Wool/Paper/Resin are shippable "
      f"(spoil <= {T.SELL_TO_CITY_MAX_SPOIL})")

for good in ("Milk", "Bread", "Fish", "Meat"):
    assert good not in T._SELL_TO_CITY_ORDER, (
        f"{good} spoils too fast to be worth carting; the need-based tiers "
        f"exist for it")
# Foods are excluded by category, not by rate -- a Bean at 0.02 would sneak
# through a pure rate test, and regional trade already moves grain on need.
for good in ("Beans", "Peas"):
    assert R.RESOURCES[good]["spoil_rate"] <= T.SELL_TO_CITY_MAX_SPOIL
    assert good not in T._SELL_TO_CITY_ORDER, (
        f"{good} is a food and has its own need-driven tier")
print("  ok    fast-spoiling goods and foods are still excluded")

print("\n--- the chain end to end: raws reach settlements, workshops run ---")
WATCH = ["Clay", "Sand", "Stone", "Cotton"]
arrived = {r: 0.0 for r in WATCH}
orig_local, orig_reg = R.advance_local_shipments, T.advance_regional_shipments


def totals():
    return {r: sum((s.resources or {}).get(r, 0) for s in w.settlements)
            for r in WATCH}


def spy_local(world):
    before = totals()
    orig_local(world)
    for r in WATCH:
        arrived[r] += max(0, totals()[r] - before[r])


def spy_reg(world):
    before = totals()
    ev = orig_reg(world)
    for r in WATCH:
        arrived[r] += max(0, totals()[r] - before[r])
    return ev


R.advance_local_shipments, T.advance_regional_shipments = spy_local, spy_reg
TURNS = 25
try:
    for _ in range(TURNS):
        R.advance_turn(w)
finally:
    R.advance_local_shipments, T.advance_regional_shipments = orig_local, orig_reg

for r in WATCH:
    held = sum((v.resources or {}).get(r, 0) for v in w.villages)
    print(f"  {r:<8} {arrived[r]/TURNS:7.2f}/turn arrived at settlements "
          f"(villages hold {held:,.0f})")

moved = [r for r in WATCH if arrived[r] > 0]
assert moved, (
    "not one raw material reached a settlement in 25 turns -- the domestic "
    "chain is severed again")
print(f"  ok    {len(moved)} of {len(WATCH)} watched raws are moving: "
      f"{', '.join(moved)}")

print("\n--- the workshops that were dead are running ---")
# The real subject. Before these fixes every one of these sat at exactly zero
# world-wide, because their inputs could not reach a settlement. Asserted as a
# group rather than per-good on purpose: which particular goods a given save
# can make depends on its geography, and pinning one (Clay/Bricks, say, on a
# swamp-poor map) would make this fail for a reason that is not a defect.
CHAIN = ["Tools", "Weapons", "Shields", "Bricks", "Cloth", "Clothes", "Paper",
         "Planks", "Glass"]
made = {r: sum((n.resources or {}).get(r, 0)
               for n in list(w.settlements) + list(w.villages))
        for r in CHAIN}
alive = [r for r, v in made.items() if v > 0]
for r in CHAIN:
    print(f"  {r:<10} {made[r]:>10,.0f}")
assert len(alive) >= 5, (
    f"only {len(alive)} of {len(CHAIN)} manufactured goods exist anywhere "
    f"({alive}) -- the raw inputs are not reaching workshops again")
assert made["Tools"] > 0, (
    "no Tools exist anywhere. Tools come from Iron, which is mined in "
    "villages and smithed in settlements -- if this is zero the ore is "
    "stranded again")
print(f"  ok    {len(alive)} of {len(CHAIN)} manufactured goods are being made")

print("\n--- nothing went backwards ---")
for node in list(w.settlements) + list(w.villages):
    for r, amt in (node.resources or {}).items():
        assert amt >= 0, (node.name, r, amt)
print("  ok    no negative stock anywhere after 25 turns")

print("\nLOGISTICS REACH TEST PASSED")
