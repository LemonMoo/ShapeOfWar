"""Slide continuity across day boundaries: no frame may jump the movers.

The sim clock (TurnRunner completing a day's work) and the display clock
(_sim_days, what the slide's frac is measured against) advance from the same
dt but complete independently. When a day's sim work finishes EARLY -- before
the display clock has reached the day boundary -- the previous slide is still
mid-flight, and the old code re-anchored _anim_day_base to the current
_sim_days, starting the next slide at frac 0 while the movers were mid-path:
a visible backward jump. The fix parks the new day's tracks in
_pending_tracks and swaps them in exactly at the day boundary, where the old
slide's drawn position is the day-end cell the new slide starts from.

    python dev/test_move_continuity.py dev/worlds/dev560.pkl
"""
import os
import pickle
import sys
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ui.map_view import MapView, _PathWalk
from app.world import commander as Cmd

FAILURES = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not ok:
        FAILURES.append(name)


class Mover:
    def __init__(self, name, pos):
        self.name, self.pos = name, pos


def tracks_for(mover, path):
    """One mover sliding along `path` over a day."""
    return [(mover, _PathWalk(path, 0.0, 1.0, 100))]


def main():
    world_path = sys.argv[1] if len(sys.argv) > 1 else "dev/worlds/dev560.pkl"
    with open(world_path, "rb") as fh:
        world = pickle.load(fh)
    Cmd.ensure_faction_commanders(world)

    root = tk.Tk()
    root.withdraw()
    view = MapView(root, world, on_attack=lambda *a, **k: None,
                   on_end_turn=lambda: None)
    view.pack(fill="both", expand=True)
    view.set_world(world)
    root.update()

    view._set_speed(1.0)                      # clock running
    view._sim_days = 0.0
    view._anim_day_base = 0.0

    m = Mover("M", (0.0, 0.0))
    day1 = tracks_for(m, [(0, 0), (10, 0)])   # moves 0 -> 10 on day 1
    day2 = tracks_for(m, [(10, 0), (20, 0)])  # continues 10 -> 20 on day 2

    print("\n--- early finish: sim finishes day 2 before the display clock ---")
    view._start_move_animation(day1)
    assert view._move_tracks == day1 and view._pending_tracks is None
    prev = None
    worst = 0.0
    parked_at = None
    for step in range(1, 41):                 # 40 frames across the day boundary
        view._sim_days = step * 0.05          # 0.05 .. 2.0 display-days
        if step == 12:                        # sim finishes day 2 at display 0.6
            view._start_move_animation(day2)
            parked_at = view._sim_days
        view._update_anim_positions()
        x, y = view._anim_pos[id(m)]
        # The drawn position must stay on the day1+day2 path (x in 0..20).
        assert -1e-9 <= x <= 20.0 + 1e-9, f"mover left the route: x={x}"
        if prev is not None:
            worst = max(worst, abs(x - prev))
        prev = x
        # At the day boundary the swap must be position-continuous: frac 1 of
        # day 1 and frac 0 of day 2 are both x = 10.
        if abs(view._sim_days - 1.0) < 1e-9:
            check("swap happens exactly at the boundary",
                  view._move_tracks == day2 and view._pending_tracks is None)
    check("day 2 was parked while day 1 still drew", parked_at is not None
          and abs(parked_at - 0.6) < 1e-9)
    check("no frame teleports (max step bounded)",
          worst <= 0.75, f"largest step {worst:.3f} cells")
    check("mover ends on day 2's last cell", prev == 20.0, f"ended at {prev}")

    print("\n--- the old bug: install while mid-flight parks, does not jump ---")
    view._sim_days = 0.0
    view._anim_day_base = 0.0
    view._last_slide_frac = None
    view._start_move_animation(day1)
    view._sim_days = 0.3
    view._update_anim_positions()
    mid = view._anim_pos[id(m)]
    check("mid-flight at frac 0.3", abs(mid[0] - 3.0) < 1e-9, f"at {mid}")
    view._start_move_animation(day2)          # sim finished day 2 early
    check("day 2 parked, day 1 still drawing",
          view._pending_tracks == day2 and view._move_tracks == day1)
    view._sim_days = 0.5
    view._update_anim_positions()
    check("still on day 1 while parked", abs(view._anim_pos[id(m)][0] - 5.0) < 1e-9,
          f"at {view._anim_pos[id(m)]}")
    view._sim_days = 1.0
    view._update_anim_positions()             # boundary: swap, no backward jump
    check("after swap, mover is at the boundary cell, not back at day start",
          abs(view._anim_pos[id(m)][0] - 10.0) < 1e-9,
          f"at {view._anim_pos[id(m)]}")
    view._sim_days = 1.1
    view._update_anim_positions()
    check("continues forward on day 2", abs(view._anim_pos[id(m)][0] - 11.0) < 1e-9,
          f"at {view._anim_pos[id(m)]}")

    print("\n--- late finish: install happens immediately, no jump ---")
    view._sim_days = 0.0
    view._anim_day_base = 0.0
    view._last_slide_frac = None
    view._start_move_animation(day1)
    view._sim_days = 1.5                      # slide long settled at the end
    view._update_anim_positions()
    check("settled at day 1 end", abs(view._anim_pos[id(m)][0] - 10.0) < 1e-9)
    view._start_move_animation(day2)          # day 2's sim work finished late
    check("late finish installs immediately",
          view._pending_tracks is None and view._move_tracks == day2)
    check("drawn position did not move (day2 start == day1 end)",
          abs(view._anim_pos[id(m)][0] - 10.0) < 1e-9)

    print("\n--- stop clears parked tracks ---")
    view._start_move_animation(day1)
    view._sim_days = 0.3
    view._update_anim_positions()
    view._start_move_animation(day2)          # park it
    assert view._pending_tracks == day2
    view._stop_move_animation()
    check("stop drops the parked day too", view._pending_tracks is None
          and not view._move_tracks)

    print("\n--- an empty movement day does not drop the parked day ---")
    view._sim_days = 0.0
    view._anim_day_base = 0.0
    view._last_slide_frac = None
    view._start_move_animation(day1)
    view._sim_days = 0.3
    view._update_anim_positions()
    view._start_move_animation(day2)          # park it
    view._start_move_animation(())            # next day: nothing moved
    check("empty day leaves the parked day alone",
          view._pending_tracks == day2 and view._move_tracks == day1)
    view._sim_days = 1.0
    view._update_anim_positions()             # boundary: parked day still plays
    check("parked day still plays after an empty day",
          view._move_tracks == day2 and abs(view._anim_pos[id(m)][0] - 10.0) < 1e-9)

    root.destroy()
    print("\nMOVE CONTINUITY TEST " + ("FAILED: " + ", ".join(FAILURES)
                                       if FAILURES else "PASSED"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
