"""Cavalry ride through the enemy and wheel for a fresh angle.

    python dev/test_cavalry_cycle.py

The cycle used to REVERSE at contact: the rally point was set straight back
along the rider's own facing, so a squadron bounced off the same face of the
same formation over and over. A charge that stops in the enemy line is a failed
charge -- the drill is to ride through, reform behind, and come again from a
direction the enemy is not already facing.

Asserted structurally: does a rider cross the formation rather than turn round
at it, and do successive impacts arrive on genuinely different bearings. Never
a win rate -- what a change like this does to the roster is measured once, in
the tournament, and recorded rather than gated (see HANDOFF).
"""
import math
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import random

from app.battle import orders
from app.battle.battle import Battle, Army
from app.battle.unit import Unit

FIELD = (1200, 800)


def make(seed=11, horse=14, foot=50):
    random.seed(seed)
    b = Battle(*FIELD)
    b.deploy(Army("Horse", "#cc3333", 0, species="Humans"), {"cavalry": horse}, 0)
    b.deploy(Army("Foot", "#3399cc", 1, species="Humans"), {"infantry": foot}, 1)
    b.issue_stance([u for u in b.armies[0].units if u.type.get("charge")],
                   orders.STANCE_CYCLE_CHARGE)
    return b


print("--- the states exist and a rider starts in none of them ---")
b = make()
rider = next(u for u in b.armies[0].units if u.type.get("charge"))
assert rider._cycle_state == "run", rider._cycle_state
assert rider._cycle_heading is None
print("  ok    a fresh rider is in 'run'")

print("\n--- impact puts a rider into 'through', on the heading it struck on ---")
b = make()
rider = next(u for u in b.armies[0].units if u.type.get("charge"))
rider.facing = (1.0, 0.0)
rider._begin_ride_through(b)
assert rider._cycle_state == "through", rider._cycle_state
assert rider._cycle_heading == (1.0, 0.0), rider._cycle_heading
print("  ok    heading frozen at impact, not tracking the next target")

print("\n--- riding through CROSSES the enemy rather than reversing ---")
# One rider, one clump. Record where it is when it hits, and where it goes.
b = make(horse=1, foot=24)
rider = next(u for u in b.armies[0].units if u.type.get("charge"))
# A lone rider against two dozen spearmen dies in five seconds, which measures
# nothing about geometry. Make this one unkillable: what is under test here is
# where it goes, not whether it survives going there.
rider.max_hp = rider.hp = 1e9
crossings = []
t = 0.0
prev_state = rider._cycle_state
while not b.over and t < 40.0:
    b.update(1 / 60)
    t += 1 / 60
    if not rider.alive:
        break
    if prev_state != rider._cycle_state:
        if rider._cycle_state == "through":
            start = (rider.x, rider.y)
            heading = rider._cycle_heading
        elif prev_state == "through":
            # Did it keep going the way it was pointed, or turn back?
            travel = (rider.x - start[0], rider.y - start[1])
            dot = travel[0] * heading[0] + travel[1] * heading[1]
            crossings.append((dot, math.hypot(*travel)))
        prev_state = rider._cycle_state

assert crossings, "the rider never completed a ride-through in 40s"
backwards = [d for d, _ in crossings if d <= 0]
print(f"  {len(crossings)} ride-throughs, mean travel "
      f"{statistics.mean(d for _, d in crossings):.0f}px, "
      f"{len(backwards)} of them backwards")
assert not backwards, "a rider went BACKWARDS during a ride-through"
print("  ok    every ride-through carried on through, none reversed")

print("\n--- successive charges come in on different bearings ---")
b = make(horse=8, foot=60)
for u in b.armies[0].units:
    u.max_hp = u.hp = 1e9        # again: bearings, not survival
bearings = {}
t = 0.0
states = {}
while not b.over and t < 45.0:
    b.update(1 / 60)
    t += 1 / 60
    for u in b.armies[0].units:
        if not u.alive or not u.type.get("charge"):
            continue
        was = states.get(u.uid)
        if was != "through" and u._cycle_state == "through":
            hx, hy = u._cycle_heading
            bearings.setdefault(u.uid, []).append(math.atan2(hy, hx))
        states[u.uid] = u._cycle_state

repeats = [b_ for b_ in bearings.values() if len(b_) >= 2]
assert repeats, "no rider landed two charges in 45s"
turns = []
for seq in repeats:
    for a, c in zip(seq, seq[1:]):
        turns.append(abs((c - a + math.pi) % math.tau - math.pi))
mean_turn = statistics.mean(turns)
same_face = sum(1 for x in turns if x < math.radians(20))
print(f"  {len(turns)} consecutive charge pairs, mean turn between them "
      f"{math.degrees(mean_turn):.0f} deg; {same_face} landed within 20 deg "
      f"of the previous one")
assert mean_turn > math.radians(35), (
    f"consecutive charges only turn {math.degrees(mean_turn):.0f} deg apart -- "
    "that is still bouncing off the same face")
print("  ok    riders come round to a genuinely new angle")

print("\n--- a rider still lands real impacts (momentum is rebuilt) ---")
b = make(horse=10, foot=60)
hits = []
full = []
t = 0.0

# Momentum is zeroed on impact BEFORE the on_attack hook runs, so the hook
# cannot see it. _charge_splash is the honest signal: it is only ever reached
# from a hit carrying at least _IMPACT_CHARGE_MIN momentum -- i.e. a real
# charge as opposed to a rider grinding away in a scrum.
real_splash = Unit._charge_splash


def counting_splash(self, battle, impact_dmg, momentum):
    full.append(momentum)
    return real_splash(self, battle, impact_dmg, momentum)


Unit._charge_splash = counting_splash


def on_attack(attacker, target, outcome):
    if attacker.type.get("charge") and outcome == "hit":
        hits.append(1)


b.on_attack = on_attack
try:
    while not b.over and t < 45.0:
        b.update(1 / 60)
        t += 1 / 60
finally:
    Unit._charge_splash = real_splash
assert hits, "cavalry landed nothing at all"
print(f"  {len(hits)} cavalry hits, {len(full)} of them real charges "
      f"(mean momentum {statistics.mean(full):.2f})" if full
      else f"  {len(hits)} cavalry hits, none of them a real charge")
assert len(full) / len(hits) > 0.25, (
    "hardly any cavalry hit carries momentum -- they are grinding, not charging")
print("  ok    the cycle rebuilds real momentum between runs")

print("\n--- and a cavalry-vs-foot fight still resolves ---")
b = make(horse=16, foot=48)
t = 0.0
while not b.over and t < 120.0:
    b.update(1 / 60)
    t += 1 / 60
assert b.over, "cavalry battle did not resolve in 120s -- riders circling forever"
print(f"  ok    resolved in {t:.0f}s, winner {b.winner.name if b.winner else 'nobody'}")

print("\nCAVALRY CYCLE TEST PASSED")
