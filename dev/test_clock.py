"""The world clock (app/core/clock.py).

    python dev/test_clock.py

The clock is the demand side of real time: real seconds in, simulated days
owed out. It knows nothing about how long a day costs to simulate, which is
what makes it testable without a world at all -- and this file is the proof of
that, since it imports no world, no Tk and no simulation.

The property worth guarding hardest is the backlog cap. A world that cannot
keep up must run SLOWER, steadily; it must never build a queue of days that
then arrive in a burst.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import clock as C

print("--- a fresh clock runs at 1x and owes nothing ---")
c = C.Clock()
assert not c.paused and c.speed == 1.0
assert c.pending == 0.0 and c.pause_reason is None
print("  ok    running, no debt, no pause reason")

print("\n--- real seconds become days at the advertised rate ---")
c = C.Clock()
assert c.tick(C.SECONDS_PER_DAY) == 1, "one day's worth of seconds owed no day"
assert abs(c.pending - 1.0) < 1e-9, c.pending
c.day_done()
assert abs(c.pending) < 1e-9
print(f"  ok    {C.SECONDS_PER_DAY}s at 1x == one day, and finishing one pays it off")

print("\n--- speed multiplies it, pause stops it dead ---")
c = C.Clock(speed=2.0)
c.tick(C.SECONDS_PER_DAY / 2)
assert abs(c.pending - 1.0) < 1e-9, c.pending
c.pause()
before = c.pending
c.tick(10.0)
assert c.pending == before, "a paused clock still ran"
print("  ok    2x is twice the days; paused is no days at all")

print("\n--- the backlog is CAPPED, and the overflow is counted not queued ---")
c = C.Clock(speed=4.0)
for _ in range(20):
    c.tick(C.SECONDS_PER_DAY)      # 4 days demanded per call, nothing supplied
assert c.pending <= C.MAX_BACKLOG + 1e-9, c.pending
assert c.dropped > 0, "days vanished without being counted as dropped"
assert not c.keeping_up, "20 unsupplied days and the clock still claims to keep up"
print(f"  ok    80 days demanded, {c.pending:.1f} queued, {c.dropped:.0f} dropped, "
      "and it says so")

print("\n--- ...and one slow day is absorbed rather than dropped ---")
c = C.Clock(speed=1.0)
c.tick(C.SECONDS_PER_DAY * 1.5)     # a day and a half owed after one slow day
assert c.dropped == 0.0, "a single slow day was already dropping time"
assert c.keeping_up
print("  ok    a day and a half of debt is carried, not thrown away")

print("\n--- pausing remembers the speed to come back to ---")
c = C.Clock(speed=4.0)
c.pause(C.BATTLE)
assert c.paused and c.pause_reason == C.BATTLE
c.resume()
assert c.speed == 4.0, f"resumed at {c.speed}x after pausing from 4x"
assert c.pause_reason is None
print("  ok    a battle at 4x resumes at 4x")

print("\n--- auto-pause fires once, for the FIRST reason, and only if enabled ---")
c = C.Clock()
assert c.auto_pause_for(C.BATTLE) is True
assert c.pause_reason == C.BATTLE
# Already stopped: a second event must not rewrite the reason under the player.
assert c.auto_pause_for(C.ATTACKED) is False
assert c.pause_reason == C.BATTLE
c.resume()
c.auto_pause[C.PROJECT_DONE] = False
assert c.auto_pause_for(C.PROJECT_DONE) is False
assert not c.paused, "a disabled auto-pause rule stopped the clock anyway"
print("  ok    first reason wins, disabled rules do nothing")

print("\n--- every reason has player-facing text ---")
for reason in (C.MANUAL, C.BATTLE, C.ATTACKED, C.PROJECT_DONE, C.FRONTIER):
    assert reason in C.PAUSE_REASON_TEXT, reason
assert set(C.DEFAULT_AUTO_PAUSE) == {C.BATTLE, C.ATTACKED, C.PROJECT_DONE, C.FRONTIER}, (
    "an auto-pause rule exists that the player was never asked about")
print("  ok    five reasons, four of them rules, all of them speakable")

print("\n--- pressing a speed while paused runs at that speed ---")
c = C.Clock()
c.pause(C.MANUAL)
c.set_speed(2.0)
assert not c.paused and c.speed == 2.0 and c.pause_reason is None
print("  ok    2x while paused means 'run, at 2x'")

print("\n--- a battle's worth of real time does not owe a week of world time ---")
c = C.Clock(speed=2.0)
c.pause(C.BATTLE)
c.tick(300.0)                # five real minutes fighting
c.forgive_backlog()
c.resume()
assert c.pending == 0.0, "the world owed days for time it was not being simulated"
print("  ok    time spent not simulating is forgiven, not owed")

print("\nCLOCK TEST PASSED")
