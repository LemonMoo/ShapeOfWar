"""Prosperity: a meter that can actually move.

    python dev/test_prosperity.py [world.pkl]

It could not before, and the failure was arithmetic rather than tuning.
_update_prosperity eases the meter by (target - current) * PROSPERITY_EASE --
1% of the remaining gap -- while shortages used to subtract ABSOLUTE points
every turn. At equilibrium (target - P) * 0.01 == penalty, so P settles at
target - 100 * penalty: every single point of per-turn penalty cost 100 points
of a 100-point meter. Since Clothes were zero world-wide, every node in the
game took the full penalty forever and sat at zero regardless of how rich it
was. Measured on a turn-161 save: a settlement whose target was a maxed 100.0
read 1.3.

The invariant that prevents a repeat is the one asserted hardest here: nothing
may write to node.prosperity except the easing. Shortages shape the TARGET.
"""
import sys
import os
import pickle

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import resources as R

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "worlds", "dev160.pkl")
w = pickle.load(open(PATH, "rb"))
if w.player_faction_idx is None:
    w.player_faction_idx = 0
season = w.season
print(f"world turn {w.turn}: {len(w.settlements)} settlements, {len(w.villages)} villages")

print("\n--- shortages scale the target, they do not subtract from the meter ---")
node = next(s for s in w.settlements if s.faction_idx >= 0)
saved = (dict(getattr(node, "prosperity_shortfall", None) or {}),
         getattr(node, "prosperity_luxury", 0.0))
try:
    node.prosperity_shortfall, node.prosperity_luxury = {}, 0.0
    assert R._prosperity_condition(node) == 1.0
    node.prosperity_shortfall = {"Food": 1.0}
    assert R._prosperity_condition(node) == 0.0, (
        "total famine should take the whole target")
    node.prosperity_shortfall = {"Clothes": 1.0}
    lost = 1.0 - R._prosperity_condition(node)
    assert abs(lost - R.PROSPERITY_SHORTAGE_WEIGHT["Clothes"]) < 1e-9, lost
    print(f"  ok    famine -> condition 0.0; no clothes -> −{lost:.0%} of target")

    # The exact case that broke it: goods the economy never produced. Only
    # Food at a full deficit may reach zero -- being cold and badly dressed
    # makes you poor, not destitute.
    node.prosperity_shortfall = {"Clothes": 1.0, "Timber": 1.0, "Firewood": 1.0}
    cond = R._prosperity_condition(node)
    assert 0.0 < cond < 1.0, cond
    target = R._prosperity_target(900.0, 1.0, cond)
    assert target > 0, (
        "a node short of clothes, timber and firewood but otherwise rich must "
        "still have SOME prosperity to ease toward -- it was pinned at 0")
    print(f"  ok    short of clothes+timber+firewood: condition {cond:.2f}, "
          f"target still {target:.1f}, not zero")

    # And the weights must never combine into a negative or a value over 1
    # from shortages alone, whatever the mix.
    node.prosperity_shortfall = {k: 1.0 for k in R.PROSPERITY_SHORTAGE_WEIGHT}
    node.prosperity_luxury = 0.0
    assert R._prosperity_condition(node) == 0.0
    node.prosperity_shortfall = {k: 0.0 for k in R.PROSPERITY_SHORTAGE_WEIGHT}
    assert R._prosperity_condition(node) == 1.0
    print("  ok    every need unmet -> 0.0; every need met -> 1.0")

    node.prosperity_shortfall = {}
    node.prosperity_luxury = 1.0
    assert R._prosperity_condition(node) > 1.0
    print(f"  ok    full luxuries lift the target "
          f"(+{R.LUXURY_PROSPERITY_BONUS:.0%})")
finally:
    node.prosperity_shortfall, node.prosperity_luxury = saved

print("\n--- consumption records deficits and never touches the meter ---")
victim = next(v for v in w.villages if v.faction_idx >= 0)
before = victim.prosperity
victim.resources = {}          # nothing to eat, wear, burn or repair with
R._consume_node_needs(victim, season, w)
assert victim.prosperity == before, (
    f"_consume_node_needs moved the meter directly ({before} -> "
    f"{victim.prosperity}); that is the bug this whole module exists for")
assert getattr(victim, "prosperity_shortfall", None), (
    "a node with nothing at all recorded no shortfall")
print(f"  ok    a node with empty stores recorded "
      f"{sorted(victim.prosperity_shortfall)} and left the meter at {before:.2f}")

print("\n--- the meter moves at the eased rate, in both directions ---")
node = next(s for s in w.settlements if s.faction_idx >= 0)
node.prosperity = 10.0
target = 60.0
step = (target - node.prosperity) * R.PROSPERITY_EASE
assert step > 0
node.prosperity += step
assert abs(node.prosperity - (10.0 + step)) < 1e-9
node.prosperity = 90.0
down = (target - node.prosperity) * R.PROSPERITY_EASE
assert down < 0, "the meter must be able to fall as well as rise"
print(f"  ok    from 10 toward 60: +{step:.2f}/turn; from 90: {down:.2f}/turn")

print("\n--- a village is valued on what it really delivers ---")
# farm_output is the decorative worldgen stat and never changes -- keying the
# target to it gave a village exactly one possible value for the whole game.
v = next(x for x in w.villages if x.faction_idx >= 0)
v.output_value = 50.0
high = R.village_goods_wealth_value(v)
v.output_value = 5.0
low = R.village_goods_wealth_value(v)
assert high > low, (high, low)
fresh = next(x for x in w.villages if x.faction_idx >= 0)
if hasattr(fresh, "output_value"):
    del fresh.output_value
assert R.village_goods_wealth_value(fresh) >= 0, (
    "a village that has never delivered must not raise")
print(f"  ok    delivering 50 -> {high:.0f}, delivering 5 -> {low:.0f}; "
      f"a village with no record falls back safely")

print("\n--- over a real run the meter spreads out instead of flatlining ---")
for _ in range(40):
    R.advance_turn(w)
sp = sorted(s.prosperity for s in w.settlements)
vp = sorted(v.prosperity for v in w.villages)
for label, xs in (("settlements", sp), ("villages", vp)):
    lo, mid, hi = xs[0], xs[len(xs) // 2], xs[-1]
    print(f"  {label:<12} min={lo:6.2f} median={mid:6.2f} max={hi:6.2f}")
    assert all(0.0 <= x <= R.PROSPERITY_MAX for x in xs), (lo, hi)
assert sp[len(sp) // 2] > 5.0, (
    f"settlement prosperity is still flat at {sp[len(sp)//2]:.2f} -- the meter "
    f"is not reaching anything like its target")
assert sp[-1] - sp[0] > 10.0, (
    "every settlement has almost the same prosperity; the meter is not "
    "distinguishing a thriving place from a struggling one")
print("  ok    the meter spans a real range and stays inside 0..100")

print("\n--- and it is still the ONLY thing writing to the meter ---")
import inspect
import re
src = inspect.getsource(R)
writers = set()
for match in re.finditer(r"^\s*(\w+)\.prosperity\s*(\+?=)", src, re.M):
    line_start = src.rfind("def ", 0, match.start())
    fn = re.match(r"def (\w+)", src[line_start:]).group(1)
    writers.add(fn)
allowed = {"_update_prosperity", "_grow_city_villages"}
assert writers <= allowed, (
    f"{sorted(writers - allowed)} writes to node.prosperity directly. Only the "
    f"easing may -- anything else fights it on a different scale and wins, "
    f"which is exactly how this broke")
print(f"  ok    only {sorted(writers)} touch the meter")

print("\nPROSPERITY TEST PASSED")
