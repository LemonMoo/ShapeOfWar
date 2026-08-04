"""Spike profiler: drive the real loop and log EVERY frame's render breakdown.

Same idea as prof_frames.py but focused on spikes: sets the flatgl timing
threshold to zero so _sync_flatgl records every frame (phase by phase) to
flatgl_timing.log, runs the world for a while at the given speed, then prints
the worst frames and per-phase cost distributions from that log.

    python dev/prof_spikes.py [world.pkl] [--speed N] [--seconds S]
"""
import os
import pickle
import sys
import time
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.save import _app_root
from app.ui.map_view import MapView
from app.world import commander as Cmd

PATH = next((a for a in sys.argv[1:] if a.endswith(".pkl")),
            "dev/worlds/dev560.pkl")
SPEED = float(next((a.split("=")[1] for a in sys.argv if a.startswith("--speed=")),
                   1.0))
SECONDS = float(next((a.split("=")[1] for a in sys.argv if a.startswith("--seconds=")),
                     40.0))

LOG = _app_root() / "flatgl_timing.log"


def main():
    with open(PATH, "rb") as fh:
        world = pickle.load(fh)
    Cmd.ensure_faction_commanders(world)
    if world.player_faction_idx is None:
        world.player_faction_idx = 0

    root = tk.Tk()
    root.geometry("1280x800")
    view = MapView(root, world, on_attack=lambda *a, **k: None,
                   on_end_turn=lambda: None)
    view.pack(fill="both", expand=True)
    view.set_world(world)
    root.update()
    time.sleep(0.5)
    root.update()

    # Log every frame, not just the slow ones.
    view._FLATGL_LOG_THRESHOLD_MS = 0.0
    view._set_speed(SPEED)
    view.render()
    root.update()
    print(f"GL active: {view._use_flatgl}  -- logging every frame to {LOG}")

    # Truncate the log so we analyze only this run.
    try:
        LOG.write_text("", encoding="utf-8")
    except OSError:
        pass

    end = time.monotonic() + SECONDS

    def done():
        if time.monotonic() < end:
            root.after(100, done)
        else:
            root.destroy()

    root.after(100, done)
    root.mainloop()

    try:
        lines = LOG.read_text(encoding="utf-8").splitlines()
    except OSError:
        print("could not read the timing log")
        return 1
    print(f"{len(lines)} frames logged")

    rows = []
    for ln in lines:
        # e.g. ... total=12.3ms ensure_base=... rebuilt=1.0 content_build=...
        parts = {}
        for tok in ln.split():
            if "=" not in tok:
                continue
            k, v = tok.split("=", 1)
            if v.endswith("ms"):
                v = v[:-2]
            try:
                parts[k] = float(v)
            except ValueError:
                pass
        rows.append(parts)

    totals = sorted(r["total"] for r in rows)
    n = len(totals)
    if n:
        for p in (0.5, 0.9, 0.99):
            v = totals[min(n - 1, int(n * p))]
            print(f"  frame total p{int(p*100):02d}: {v:.1f}ms")
        print(f"  max: {totals[-1]:.1f}ms")

    print("\nworst 10 frames (phase breakdown):")
    for r in sorted(rows, key=lambda r: -r["total"])[:10]:
        keys = ("total", "ensure_base", "ensure_fog", "set_map", "content_build",
                "lines_set", "markers_set", "labels_set", "render_now")
        print("  " + " ".join(f"{k}={r.get(k, 0):.1f}" for k in keys))

    # Per-phase cost over ALL frames (which phases own the spikes?).
    print("\nper-phase p95 across frames (ms):")
    for phase in ("ensure_base", "ensure_fog", "content_build", "lines_set",
                  "markers_set", "labels_set", "render_now"):
        vals = sorted(r.get(phase, 0.0) for r in rows)
        v = vals[min(n - 1, int(n * 0.95))] if n else 0.0
        print(f"  {phase:14s} p95={v:.2f}  max={vals[-1]:.2f}" if vals else "")
    try:
        root.destroy()
    except tk.TclError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
