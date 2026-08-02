"""The world actually runs, against a real MapView (app/ui/map_view.py).

    python dev/test_realtime.py [world.pkl]

dev/test_clock.py proves the clock's arithmetic and dev/test_turn_slice.py
proves a sliced day is the same day. This is the third leg: that the two are
wired to a real view, that time passing actually advances the world, and that
the controls do what their labels say.

Driven by calling `_advance_world(dt)` with made-up elapsed seconds rather than
by waiting on real ones -- a test that sleeps for six seconds to watch two days
go by is a test nobody runs.
"""
import os
import pickle
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk

from app.core import clock as C
from app.ui.map_view import MapView
from app.world import commander as Cmd

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "worlds", "dev160.pkl")


def noop(*a, **k):
    pass


try:
    root = tk.Tk()
except tk.TclError as exc:
    print(f"no display available ({exc}) -- skipping")
    sys.exit(0)
root.withdraw()

world = pickle.load(open(PATH, "rb"))
if world.player_faction_idx is None:
    world.player_faction_idx = 0
Cmd.ensure_faction_commanders(world)
view = MapView(root, world, noop, noop)
view.pack(fill="both", expand=True)
root.update_idletasks()
print(f"world: turn {world.turn}, {len(world.settlements)} settlements")

try:
    print("\n--- the world starts PAUSED ---")
    assert view.clock.paused, (
        "the map opened with the world already running -- the player's first "
        "look at it would be spent watching it do things")
    start = world.turn
    view._advance_world(10.0)
    assert world.turn == start, "a paused world advanced"
    print("  ok    ten seconds of a paused world is no days at all")

    print("\n--- running it advances real days ---")
    view._set_speed(1.0)
    assert not view.clock.paused
    for _ in range(400):                      # 400 frames of 1/30s = 13.3s
        view._advance_world(1 / 30)
    days = world.turn - start
    expected = 13.3 / C.SECONDS_PER_DAY
    print(f"  {days} days in 13.3 simulated seconds (about {expected:.0f} expected)")
    assert days >= 1, "the world did not advance a single day while running"
    assert abs(days - expected) <= 2, (
        f"{days} days where {expected:.0f} were due -- the clock and the runner "
        "disagree about what a day costs")
    print("  ok    time passing is days passing")

    print("\n--- speed multiplies it ---")
    at_1x = world.turn
    for _ in range(300):
        view._advance_world(1 / 30)
    ran_1x = world.turn - at_1x
    view._set_speed(4.0)
    at_4x = world.turn
    for _ in range(300):
        view._advance_world(1 / 30)
    ran_4x = world.turn - at_4x
    print(f"  same 10 seconds: {ran_1x} days at 1x, {ran_4x} days at 4x")
    assert ran_4x > ran_1x, "4x was no faster than 1x"
    print("  ok    the speed button is a speed")

    print("\n--- pausing stops it dead, and does not bank the time ---")
    view._toggle_pause()
    assert view.clock.paused
    held = world.turn
    for _ in range(200):
        view._advance_world(1 / 30)
    assert world.turn == held, "a paused world advanced"
    view._toggle_pause()                       # resume
    view._advance_world(1 / 30)
    assert world.turn <= held + 1, (
        "resuming paid out the whole pause at once -- forgive_backlog is not "
        "being called, and a long pause will fast-forward the world")
    print("  ok    paused is stopped, and resuming does not fast-forward")

    print("\n--- a battle's pause names itself, and 4x comes back as 4x ---")
    view._set_speed(4.0)
    view.clock.auto_pause_for(C.BATTLE)
    assert view.clock.paused and view.clock.pause_reason == C.BATTLE
    view._refresh_time_controls()
    label = view.turn_lbl.cget("text")
    assert "battle" in label.lower(), f"the date line does not say why: {label!r}"
    view.clock.resume()
    assert view.clock.speed == 4.0
    print(f"  ok    {label!r}, and it resumes at 4x")

    print("\n--- the date line reads like a date ---")
    view._refresh_time_controls()
    text = view.turn_lbl.cget("text")
    assert str(world.season) in text and "Year" in text, text
    print(f"  ok    {text!r}")

    print("\n--- the panels are not rebuilt on every single day ---")
    rebuilds = []
    real_refresh = MapView.refresh
    MapView.refresh = lambda self: (rebuilds.append(1), real_refresh(self))[1]
    try:
        view._set_speed(4.0)
        view._last_panel_refresh = time.monotonic()
        before = world.turn
        for _ in range(300):
            view._advance_world(1 / 30)
        ran = world.turn - before
    finally:
        MapView.refresh = real_refresh
    print(f"  {ran} days ran, {len(rebuilds)} full panel rebuilds")
    assert ran > 0
    assert len(rebuilds) < ran, (
        "the side panels are torn down and rebuilt every single day -- at a "
        "day every couple of seconds that is a permanent flicker")
    print("  ok    throttled, as _PANEL_REFRESH_MS intends")

    print("\n--- an auto-pause fired from INSIDE a day does not re-enter it ---")
    # Two of the three rules fire from world code running mid-phase: a region
    # changing hands and a settlement finishing. Reacting by finishing the day
    # from in there would call next() on the generator currently executing -- a
    # ValueError thrown from the middle of a territory transfer. This stands in
    # for that, by pausing while `stepping` is set, exactly as the bus listener
    # does.
    view.clock.resume()
    view._set_speed(1.0)
    view._advance_world(C.SECONDS_PER_DAY)
    view.runner.step(budget_ms=0.1)
    assert view.runner.busy, "the probe needs a day actually in progress"
    view.runner.stepping = True
    try:
        view.clock.auto_pause_for(C.PROJECT_DONE)
        assert view.clock.paused, "the clock did not stop"
        assert view.runner.busy, "the day was ended from inside itself"
    finally:
        view.runner.stepping = False
    view.runner.finish_day()
    view._finish_day()
    assert not view.runner.busy
    print("  ok    the clock stops; the day in progress finishes on its own")

    print("\n--- a day is never left half-finished behind a save or a battle ---")
    view._set_speed(1.0)
    view._advance_world(C.SECONDS_PER_DAY)     # start one
    view.runner.step(budget_ms=0.1)            # ...and leave it part-done
    if view.runner.busy:
        view.runner.finish_day()
        view._finish_day()
    assert not view.runner.busy
    print("  ok    finish_day() closes out whatever was in progress")
finally:
    try:
        root.destroy()
    except tk.TclError:
        pass

print("\nREALTIME TEST PASSED")
