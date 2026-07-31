"""Formation cohesion and ally-aware movement (app/battle/movement.py).

    python dev/test_formation.py

Every soldier used to run at its own best-scored enemy in a straight line,
through whatever stood in the way. The army had no shape, which is the whole
of "swarmy": nothing maintained a spacing, and nothing stepped around an ally.

What is asserted here is STRUCTURAL -- spacing, spread, whether a unit walks
into an ally's body when a clear side exists -- never a win rate. A win rate
over a handful of battles is a coin flip (see HANDOFF), and this changes how
soldiers walk, not how hard they hit.

The A/B is done by DISABLING the new thing (movement.SEPARATION_WEIGHT and
friends set to zero) rather than by comparing against a remembered number,
which is this project's standing pattern for "did the new mechanism do it".
"""
import math
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import random

from app.battle import movement
from app.battle.battle import Battle, Army

FIELD = (1200, 800)
COMP = {"infantry": 40, "archer": 20, "cavalry": 10}


def make(seed=7):
    random.seed(seed)
    b = Battle(*FIELD)
    b.deploy(Army("A", "#cc3333", 0, species="Humans"), COMP, 0)
    b.deploy(Army("B", "#3399cc", 1, species="Humans"), COMP, 1)
    return b


def run(b, seconds, dt=1 / 60):
    t = 0.0
    while not b.over and t < seconds:
        b.update(dt)
        t += dt
    return t


def nearest_ally_distances(army):
    live = [u for u in army.units if u.alive]
    out = []
    for u in live:
        best = float("inf")
        for v in live:
            if v is u:
                continue
            d = math.hypot(v.x - u.x, v.y - u.y) - u.radius - v.radius
            best = min(best, d)
        if best < float("inf"):
            out.append(best)
    return out


def spread(army):
    """Standard distance of living soldiers from their own centre of mass --
    a blob has a small one, a formation a larger one."""
    live = [u for u in army.units if u.alive]
    cx = sum(u.x for u in live) / len(live)
    cy = sum(u.y for u in live) / len(live)
    return statistics.mean(math.hypot(u.x - cx, u.y - cy) for u in live)


print("--- steering is a unit vector, always ---")
b = make()
u = b.armies[0].units[0]
for dx, dy in ((1.0, 0.0), (0.0, -1.0), (0.6, 0.8)):
    nx, ny = movement.steer(u, dx, dy, b)
    assert abs(math.hypot(nx, ny) - 1.0) < 1e-9, (dx, dy, nx, ny)
print("  ok    normalised for every input direction")

print("\n--- deflection is capped, so nobody orbits instead of advancing ---")
# Box a unit in with allies on the exact heading it wants to walk, which is the
# case that would otherwise turn it right around.
b = make()
army = b.armies[0]
probe = army.units[0]
probe.x, probe.y = 600.0, 400.0
for i, v in enumerate(army.units[1:9]):
    v.x, v.y = 600.0 + 12 + i * 3, 400.0 + (i - 4) * 2
b._build_move_grid()
nx, ny = movement.steer(probe, 1.0, 0.0, b)
assert nx >= movement.MAX_DEFLECT_COS - 1e-9, (
    f"steered {math.degrees(math.acos(max(-1.0, min(1.0, nx)))):.0f} deg off, "
    f"past the {math.degrees(math.acos(movement.MAX_DEFLECT_COS)):.0f} deg cap")
print(f"  ok    boxed in, still within {math.degrees(math.acos(movement.MAX_DEFLECT_COS)):.0f} deg of its objective")

print("\n--- an ally dead ahead is stepped AROUND, not into ---")
b = make()
army = b.armies[0]
probe, blocker = army.units[0], army.units[1]
probe.x, probe.y = 500.0, 400.0
blocker.x, blocker.y = 500.0 + 14.0, 400.0
for v in army.units[2:]:
    v.x, v.y = -5000.0, -5000.0      # out of the way entirely
b._build_move_grid()
nx, ny = movement.steer(probe, 1.0, 0.0, b)
assert abs(ny) > 0.15, f"walked straight at an ally 14px ahead ({nx:.2f}, {ny:.2f})"
print(f"  ok    deflected {math.degrees(math.atan2(abs(ny), nx)):.0f} deg to pass an ally 14px ahead")

print("\n--- a unit already in contact does not steer (cost, and it is fighting) ---")
# The packed melee is exactly where the neighbour grid is densest, so skipping
# it is most of what keeps this affordable. Counted rather than argued.
b = make(seed=5)
run(b, 6.0)                     # lines have met by now
real_steer = movement.steer
calls = [0]


def counting_steer(*a, **k):
    calls[0] += 1
    return real_steer(*a, **k)


movement.steer = counting_steer
try:
    import app.battle.unit as unit_mod
    unit_mod.movement.steer = counting_steer
    b.update(1 / 60)
finally:
    movement.steer = real_steer
    unit_mod.movement.steer = real_steer
living = sum(len(a.living) for a in b.armies)
fighting = sum(1 for a in b.armies for u in a.living
               if u.target is not None and u.target.alive
               and math.hypot(u.target.x - u.x, u.target.y - u.y)
               <= u.attack_range + u.radius + u.target.radius)
assert calls[0] <= living - fighting + 1, (
    f"{calls[0]} steer calls for {living} units of which {fighting} are in contact")
print(f"  ok    {calls[0]} steer calls for {living} living units "
      f"({fighting} in contact, and none of them steered)")

print("\n--- mobbed: a fourth man does not join a fight three already have ---")
b = make()
a_army, b_army = b.armies
victim = b_army.units[0]
victim.x, victim.y = 600.0, 400.0
attackers = a_army.units[:5]
for i, atk in enumerate(attackers):
    ang = i * (math.tau / 5)
    atk.x = victim.x + math.cos(ang) * 12
    atk.y = victim.y + math.sin(ang) * 12
    atk.target = victim
b.update(1 / 60)
assert b.contact_count(victim) >= movement.CONTACT_CAP, b.contact_count(victim)
far = a_army.units[9]
far.x, far.y = victim.x - 200.0, victim.y
far.target = victim
assert movement.mobbed(far, b), "a target with five men on it reads as un-mobbed"
print(f"  ok    contact_count={b.contact_count(victim)} against a cap of "
      f"{movement.CONTACT_CAP}; further attackers are held off")

print("\n--- and the army still closes and resolves (no stall) ---")
b = make()
elapsed = run(b, 90.0)
assert b.over, f"battle did not resolve in {elapsed:.0f}s of sim time"
print(f"  ok    resolved in {elapsed:.1f}s, winner side {b.winner.side}")

print("\n--- A/B: does the mechanism actually change the shape of an army? ---")
saved = (movement.SEPARATION_WEIGHT, movement.AVOID_WEIGHT)


def shape_after(seconds, on):
    movement.SEPARATION_WEIGHT, movement.AVOID_WEIGHT = saved if on else (0.0, 0.0)
    b = make()
    run(b, seconds)
    live = [a for a in b.armies if a.living]
    if not live:
        return None
    army = max(live, key=lambda a: len(a.living))
    return (statistics.mean(nearest_ally_distances(army)), spread(army),
            len(army.living))


try:
    off = shape_after(8.0, False)
    on = shape_after(8.0, True)
finally:
    movement.SEPARATION_WEIGHT, movement.AVOID_WEIGHT = saved

print(f"  off   nearest ally {off[0]:6.2f}px   spread {off[1]:6.1f}px   {off[2]} alive")
print(f"  on    nearest ally {on[0]:6.2f}px   spread {on[1]:6.1f}px   {on[2]} alive")
assert on[0] > off[0], (
    "separation made no difference to how tightly packed the army is")
print("  ok    the line stands looser with steering on than with it off")

print("\n--- frame budget: the sim must still fit 16.7ms ---")
b = make(seed=3)
run(b, 3.0)                       # get them into contact first, the worst case
n = sum(len(a.living) for a in b.armies)
t0 = time.perf_counter()
for _ in range(60):
    b.update(1 / 60)
ms = (time.perf_counter() - t0) / 60 * 1000
print(f"  {n} units in contact: {ms:.2f} ms/tick")
assert ms < 16.7, f"{ms:.2f} ms/tick blows the frame budget"
print("  ok    within budget")

print("\nFORMATION TEST PASSED")
