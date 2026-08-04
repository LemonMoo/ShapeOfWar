"""Frame profiling: drive the real world loop and time every frame.

Runs the actual MapView._on_frame loop (the same one the game runs) on a dev
world with the clock going, and records per-frame time with a breakdown --
world stepping vs rendering vs day-finish work. Prints p50/p90/p99 and the
worst frames, so a choppy-frame source (a day boundary, a claims phase, the
canvas fallback, a marker rebuild) shows up as a number instead of a feeling.

    python dev/prof_frames.py [world.pkl] [--speed N] [--canvas] [--seconds S]

  --canvas   force the Tk/PIL canvas renderer (simulates a machine with no GL)
  --seconds  how long of game-loop time to sample (default 20)
"""
import os
import pickle
import sys
import time
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ui.map_view import MapView
from app.world import commander as Cmd

PATH = next((a for a in sys.argv[1:] if a.endswith(".pkl")),
            "dev/worlds/dev560.pkl")
SPEED = float(next((a.split("=")[1] for a in sys.argv if a.startswith("--speed=")),
                   1.0))
CANVAS = "--canvas" in sys.argv
SECONDS = float(next((a.split("=")[1] for a in sys.argv if a.startswith("--seconds=")),
                     20.0))


def main():
    with open(PATH, "rb") as fh:
        world = pickle.load(fh)
    Cmd.ensure_faction_commanders(world)
    if world.player_faction_idx is None:
        world.player_faction_idx = 0

    root = tk.Tk()
    root.geometry("1280x800")          # must be mapped for GL context creation
    view = MapView(root, world, on_attack=lambda *a, **k: None,
                   on_end_turn=lambda: None)
    view.pack(fill="both", expand=True)
    view.set_world(world)
    if CANVAS:
        # Simulate "no GL on this machine": never even try to create the frame.
        view._flatgl_tried = True
    root.update()

    print(f"world {os.path.basename(PATH)} ({world.w}x{world.h}, "
          f"{len(world.regions)} regions)  speed {SPEED}x  "
          f"renderer: {'canvas' if CANVAS else 'GL (if it initialises)'}")

    view._set_speed(SPEED)
    if not CANVAS:
        view.render()                  # force first GL init now (or its failure)
        root.update()
        print(f"  GL frame ok: {view._flatgl is not None and not view._flatgl.failed}"
              f"  (flatgl={view._flatgl is not None})")

    # Instrument the three hot phases per frame.
    t0 = time.monotonic()
    frames = []                        # (total_ms, advance_ms, render_ms)
    adv0, rend0, fin0 = [], [], []
    orig_adv, orig_render = view._advance_world, view.render
    orig_finish = view._finish_day

    def wrap_adv(dt):
        s = time.perf_counter()
        orig_adv(dt)
        adv0.append((time.perf_counter() - s) * 1000)

    def wrap_render():
        s = time.perf_counter()
        orig_render()
        rend0.append((time.perf_counter() - s) * 1000)

    def wrap_finish():
        s = time.perf_counter()
        orig_finish()
        fin0.append((time.perf_counter() - s) * 1000)

    view._advance_world, view.render, view._finish_day = \
        wrap_adv, wrap_render, wrap_finish

    end = time.monotonic() + SECONDS
    stamp = [time.perf_counter()]
    orig_frame = view._on_frame

    def wrap_frame():
        s = time.perf_counter()
        orig_frame()
        stamp.append(time.perf_counter())
        if time.monotonic() < end:
            pass                          # orig_frame rescheduled itself
        else:
            root.after(1, root.destroy)

    view._on_frame = wrap_frame
    root.after(100, wrap_frame)           # kick the loop
    root.mainloop()

    view._advance_world, view.render, view._finish_day = \
        orig_adv, orig_render, orig_finish
    view._on_frame = orig_frame

    totals = [(b - a) * 1000 for a, b in zip(stamp, stamp[1:])]
    totals.sort()
    n = len(totals)
    if n == 0:
        print("no frames measured")
        return 1
    def pct(p):
        return totals[min(n - 1, int(n * p))]
    print(f"\nframes: {n}  ({n / max(1e-9, (time.monotonic() - t0)):.0f}/s sample rate)")
    print(f"frame period  p50={pct(0.5):.1f}ms p90={pct(0.9):.1f}ms "
          f"p99={pct(0.99):.1f}ms max={totals[-1]:.1f}ms  "
          f"-> ~{1000 / pct(0.5):.0f}fps median")
    if rend0:
        rend0.sort()
        print(f"render()      p50={rend0[len(rend0)//2]:.1f}ms "
              f"p90={rend0[int(len(rend0)*0.9)]:.1f}ms "
              f"max={rend0[-1]:.1f}ms (n={len(rend0)})")
    if adv0:
        adv0.sort()
        print(f"_advance_world p50={adv0[len(adv0)//2]:.2f}ms "
              f"p90={adv0[int(len(adv0)*0.9)]:.2f}ms max={adv0[-1]:.2f}ms")
    if fin0:
        fin0.sort()
        print(f"_finish_day   n={len(fin0)} p50={fin0[len(fin0)//2]:.1f}ms "
              f"max={fin0[-1]:.1f}ms")
    try:
        root.destroy()
    except tk.TclError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
