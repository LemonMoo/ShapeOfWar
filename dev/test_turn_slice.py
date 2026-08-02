"""A day run in slices is the same day (app/world/turn_runner.py).

    python dev/test_turn_slice.py [world.pkl]

This is the load-bearing test of the real-time overhaul. The day was one
atomic 425ms call; it is now a generator that pauses between phases so the map
can be drawn while the world moves. Everything downstream of that -- the clock,
the speed control, the whole UI -- is only safe if slicing changed NOTHING
about the result.

So the gate is a fingerprint, the same instrument dev/bench_turn.py uses to
prove a "pure speed" change really was one: two copies of one world, ten days
each, one run whole and one run a slice at a time, and every region, node,
faction stockpile and gold ledger identical at the end.

The second thing asserted is the reason slicing exists at all: that the longest
uninterruptible slice is short enough not to be a visible hitch.
"""
import hashlib
import os
import pickle
import random
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import commander as C, resources as R
from app.world.turn_runner import (TurnRunner, SLOW_PHASE_MS, ATOMIC_PHASES,
                                   HARD_PHASE_MS)

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "worlds", "dev560.pkl")
DAYS = 10


def load():
    random.seed(4242)          # the AI makes random choices; pin them
    with open(PATH, "rb") as fh:
        world = pickle.load(fh)
    C.ensure_faction_commanders(world)
    return world


def fingerprint(world):
    """Everything a change to turn processing could plausibly disturb -- the
    same shape dev/bench_turn.py uses."""
    h = hashlib.sha256()
    for r in world.regions:
        h.update(f"{r.id}:{r.faction_idx}:{r.wildland_strength}|".encode())
    for node in list(world.settlements) + list(world.villages):
        h.update(f"{getattr(node, 'id', '')}:{getattr(node, 'population', 0)}:".encode())
        h.update(",".join(f"{k}={v}"
                          for k, v in sorted((getattr(node, "resources", {}) or {}).items())
                          ).encode())
        h.update(b"|")
    for f in world.factions:
        h.update(f"{f.name}:{sorted(f.stats.items())}|".encode())
    h.update(f"turn={world.turn}season={world.season}".encode())
    return h.hexdigest()


print(f"--- {DAYS} days, run whole against run in slices ---")
whole = load()
print(f"  world: turn {whole.turn}, {sum(1 for r in whole.regions if r.faction_idx is not None)}"
      f" owned regions, {len(whole.settlements) + len(whole.villages)} nodes")
t0 = time.perf_counter()
for _ in range(DAYS):
    R.advance_turn(whole)
whole_ms = (time.perf_counter() - t0) / DAYS * 1000

sliced = load()
runner = TurnRunner(sliced, budget_ms=4.0)
slices = []
t0 = time.perf_counter()
for _ in range(DAYS):
    runner.begin_day()
    n = 0
    while not runner.step():
        n += 1
        assert n < 100000, "a day never finished"
    slices.append(n + 1)
sliced_ms = (time.perf_counter() - t0) / DAYS * 1000

fw, fs = fingerprint(whole), fingerprint(sliced)
print(f"  whole  {whole_ms:6.0f} ms/day   {fw[:16]}")
print(f"  sliced {sliced_ms:6.0f} ms/day   {fs[:16]}  "
      f"({statistics.mean(slices):.0f} slices per day)")
assert fw == fs, (
    "a day run in slices produced a DIFFERENT world from the same day run "
    "whole -- the real-time driver cannot be trusted until this matches")
print("  ok    identical worlds, to the fingerprint")

print("\n--- the slices are short enough not to be seen ---")
# Measured over every phase of every day, not just the worst one: a single
# spike on the day a province changes hands is a different thing from a day
# made of slow phases, and only the second makes the map feel bad.
timings = []
probe = load()
for _ in range(DAYS):
    steps = R.day_steps(probe)
    while True:
        t0 = time.perf_counter()
        try:
            phase = next(steps)
        except StopIteration:
            break
        timings.append(((time.perf_counter() - t0) * 1000.0, phase))
timings.sort()
p95 = timings[int(len(timings) * 0.95)][0]
worst_ms, worst_name = timings[-1]
print(f"  {len(timings)} phases over {DAYS} days: median {timings[len(timings)//2][0]:.1f} ms, "
      f"p95 {p95:.0f} ms, worst {worst_name!r} at {worst_ms:.0f} ms")
assert p95 < SLOW_PHASE_MS, (
    f"one slice in twenty takes over {SLOW_PHASE_MS:.0f} ms (p95 is {p95:.0f}) "
    "-- the map will feel like it is stuttering, not hitching")
slow = [(ms, name) for ms, name in timings
        if ms >= SLOW_PHASE_MS and name not in ATOMIC_PHASES]
assert not slow, (
    f"phase {slow[-1][1]!r} takes {slow[-1][0]:.0f} ms and is not declared "
    "atomic -- either chunk it, or make the case for it in "
    "turn_runner.ATOMIC_PHASES")
assert worst_ms < HARD_PHASE_MS, (
    f"{worst_name!r} at {worst_ms:.0f} ms is past the hard ceiling even for an "
    "atomic phase")
print(f"  ok    p95 under {SLOW_PHASE_MS:.0f} ms; the only overruns are the "
      f"declared atomic ones ({', '.join(sorted(ATOMIC_PHASES))})")

print("\n--- slicing costs almost nothing in total time ---")
overhead = (sliced_ms - whole_ms) / whole_ms * 100
print(f"  {overhead:+.1f}% against running the day whole")
assert overhead < 25.0, (
    f"stepping the day costs {overhead:.0f}% more than running it -- the "
    "generator machinery should be noise next to the work itself")
print("  ok    the overhead is noise")

print("\n--- a part-done day can be forced to completion ---")
w = load()
r = TurnRunner(w, budget_ms=1.0)
r.begin_day()
r.step()
assert r.busy, "a 1ms budget finished a whole day"
turn_mid = w.turn
r.finish_day()
assert not r.busy and w.turn == turn_mid, (
    "finishing a part-done day started another one")
print("  ok    finish_day() completes the day in progress and starts no other")

print("\n--- begin_day never restarts a day already under way ---")
w = load()
r = TurnRunner(w, budget_ms=1.0)
r.begin_day()
r.step()
before = w.turn
r.begin_day()          # must be a no-op
r.finish_day()
assert w.turn == before, "begin_day replayed phases of a day already in progress"
print("  ok    a day in progress is never restarted")

print("\nTURN SLICE TEST PASSED")
