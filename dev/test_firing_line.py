"""Archers hold a line instead of bunching up.

    python dev/test_firing_line.py

Bowmen each walked at whoever they personally picked and ended up in a knot,
which wastes the frontage that is the whole point of massed shooting -- and a
clump of archers blocks its own shooting. STANCE_FIRING_LINE is the formation
half of that: wide spacing, wide frontage, ranks staggered so the second rank
looks down a gap rather than at a back.

Structural assertions only -- frontage, depth, whether the AI actually issues
it -- and one explicit check that the stance carries NO combat modifier, since
quietly hanging one off it would re-fit the archer tuning HANDOFF S26 is still
an open question about.
"""
import math
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import random

from app.battle import order_ai, orders
from app.battle.battle import Battle, Army

FIELD = (1200, 800)


def make(seed=4, archers=24, foot=24, enemy_foot=30):
    random.seed(seed)
    b = Battle(*FIELD)
    b.deploy(Army("Bows", "#cc3333", 0, species="Elves"),
             {"archer": archers, "infantry": foot}, 0)
    b.deploy(Army("Foot", "#3399cc", 1, species="Humans"), {"infantry": enemy_foot}, 1)
    return b


def run(b, seconds, dt=1 / 60):
    t = 0.0
    while not b.over and t < seconds:
        b.update(dt)
        t += dt
    return t


def line_shape(units, battle):
    """(frontage, depth) of a group, measured along and across the direction of
    the enemy -- which is the axis the line is laid out on.

    Deliberately NOT off one unit's `facing`: every archer faces whoever it is
    personally shooting, so that vector says nothing about the body they stand
    in and made a wide line measure as a deep one."""
    live = [u for u in units if u.alive]
    cx = sum(u.x for u in live) / len(live)
    cy = sum(u.y for u in live) / len(live)
    ex = ey = 0.0
    n = 0
    for army in battle.armies:
        if army.side == live[0].faction.side:
            continue
        for u in army.units:
            if u.alive:
                ex += u.x; ey += u.y; n += 1
    fx, fy = (ex / n - cx, ey / n - cy) if n else (1.0, 0.0)
    mag = math.hypot(fx, fy) or 1.0
    fx, fy = fx / mag, fy / mag
    px, py = -fy, fx
    along = [(u.x - cx) * px + (u.y - cy) * py for u in live]
    across = [(u.x - cx) * fx + (u.y - cy) * fy for u in live]
    return max(along) - min(along), max(across) - min(across)


print("--- the stance exists, is ranged-only, and carries no combat modifier ---")
assert orders.STANCE_FIRING_LINE in orders.allowed_stances("archer")
assert orders.STANCE_FIRING_LINE in orders.allowed_stances("sapper")
assert orders.STANCE_FIRING_LINE not in orders.allowed_stances("infantry"), (
    "a swordsman has no business in a firing line")
assert orders.STANCE_FIRING_LINE not in orders.allowed_stances("cavalry")
assert orders.STANCE_MODS[orders.STANCE_FIRING_LINE] == {}, (
    "the firing line changed how hard archers shoot, not just where they stand")
assert orders.STANCE_FIRING_LINE in orders.HOLDING_STANCES
assert orders.STANCE_FIRING_LINE in orders.SLOTTED_STANCES
print("  ok    ranged-only, holding, slotted, and no stat attached")

print("\n--- the line is WIDE and SHALLOW, unlike a shield wall ---")
b = make()
archers = [u for u in b.armies[0].units if u.type_key == "archer"]
b.issue_stance(archers, orders.STANCE_FIRING_LINE)
slots = [u.formation_slot for u in archers]
assert all(s is not None for s in slots), "an archer was left without a slot"
xs = [s[0] for s in slots]
ys = [s[1] for s in slots]
fire_frontage = max(ys) - min(ys)
fire_depth = max(xs) - min(xs)
b2 = make()
foot = [u for u in b2.armies[0].units if u.type_key == "infantry"]
b2.issue_stance(foot, orders.STANCE_SHIELD_WALL)
wslots = [u.formation_slot for u in foot]
wall_frontage = max(s[1] for s in wslots) - min(s[1] for s in wslots)
print(f"  firing line {len(archers)} bows: {fire_frontage:.0f}px frontage, "
      f"{fire_depth:.0f}px deep")
print(f"  shield wall {len(foot)} foot: {wall_frontage:.0f}px frontage")
assert fire_frontage > fire_depth * 2, "the shooting line is a block, not a line"
assert fire_frontage / len(archers) > wall_frontage / len(foot), (
    "archers are packed as tightly as a shield wall")
print("  ok    wider per man than a wall, and far wider than it is deep")

print("\n--- ranks are staggered, so nobody shoots his own front rank's back ---")
b = make(archers=40)
archers = [u for u in b.armies[0].units if u.type_key == "archer"]
b.issue_stance(archers, orders.STANCE_FIRING_LINE)
# Group by RANK the way the layout does (per_rank men to a rank), and measure
# sideways offsets along the line's own axis -- the line is not axis-aligned,
# it faces the enemy, so rounding a slot's x is not a rank.
per_rank = min(orders.FIRE_MAX_RANK, len(archers))
assert len(archers) > per_rank, f"{len(archers)} archers formed a single rank"
fx, fy = archers[0].facing
px, py = -fy, fx
along = [(s[0] * px + s[1] * py) for s in (u.formation_slot for u in archers)]
front = sorted(along[:per_rank])
second = sorted(along[per_rank:])
ranks = [front, second]
offsets = [min(abs(y - fy) for fy in front) for y in second]
print(f"  {len(ranks)} ranks; second rank sits a mean "
      f"{statistics.mean(offsets):.1f}px off the men in front "
      f"(spacing is {orders.FIRE_SPACING:.0f}px)")
assert statistics.mean(offsets) > orders.FIRE_SPACING * 0.25, (
    "the second rank is standing directly behind the first")
print("  ok    staggered")

print("\n--- the order AI puts archers in it once they are in range ---")
b = make()
run(b, 20.0)
archers = [u for u in b.armies[0].units if u.type_key == "archer" and u.alive]
in_line = [u for u in archers if u.stance == orders.STANCE_FIRING_LINE]
print(f"  {len(in_line)} of {len(archers)} living archers are in a firing line")
assert in_line, "the AI never formed a firing line in 20s of fighting"
print("  ok    issued by the AI, not just available to a player")

print("\n--- and it makes the archers measurably less of a knot ---")
saved = order_ai.decide_for_army


def shape_with_line(on):
    real_issue = Battle.issue_stance
    if not on:
        # A/B by DISABLING the new thing: the firing line falls back to the
        # plain hold it replaced, everything else identical.
        def no_line(self, units, stance):
            if stance == orders.STANCE_FIRING_LINE:
                stance = orders.STANCE_HOLD
            return real_issue(self, units, stance)
        Battle.issue_stance = no_line
    try:
        b = make(seed=9)
        run(b, 14.0)
        live = [u for u in b.armies[0].units if u.type_key == "archer" and u.alive]
        if len(live) < 4:
            return None
        return line_shape(live, b), len(live)
    finally:
        Battle.issue_stance = real_issue


off = shape_with_line(False)
on = shape_with_line(True)
print(f"  off   frontage {off[0][0]:6.0f}px  depth {off[0][1]:6.0f}px  "
      f"{off[1]} alive")
print(f"  on    frontage {on[0][0]:6.0f}px  depth {on[0][1]:6.0f}px  "
      f"{on[1]} alive")
assert on[0][0] / max(1.0, on[0][1]) > off[0][0] / max(1.0, off[0][1]), (
    "archers are no more line-shaped with the firing line than without it")
print("  ok    a wider, shallower body of bowmen than the plain hold gives")

print("\n--- a battle with archers in a line still resolves ---")
b = make(seed=12)
t = run(b, 120.0)
assert b.over, "archer battle did not resolve in 120s"
print(f"  ok    resolved in {t:.0f}s, winner {b.winner.name if b.winner else 'nobody'}")

print("\nFIRING LINE TEST PASSED")
