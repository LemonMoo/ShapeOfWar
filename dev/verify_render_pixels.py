"""Render-equivalence check: the full _ensure_base pipeline, pixel-for-pixel.

The terrain texture pass (_texture_pixels) and the pixel store were rewritten
from pure-Python per-cell loops to numpy. This script pins the OUTPUT of every
_ensure_base path (every view mode, selection state, and layer) to a recorded
baseline, so a rewrite that changes a single rendered pixel is caught.

    python dev/verify_render_pixels.py --baseline [world.pkl]   # record baselines
    python dev/verify_render_pixels.py           [world.pkl]   # compare against them

Baselines are stored next to the world file as <world>.render_pixels.npz.
"""
import os
import pickle
import sys
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from app.ui.map_view import MapView
from app.world import layers

FAILURES = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not ok:
        FAILURES.append(name)


def capture(world_path):
    with open(world_path, "rb") as fh:
        world = pickle.load(fh)
    root = tk.Tk()
    root.withdraw()
    view = MapView(root, world, on_attack=lambda *a, **k: None,
                   on_end_turn=lambda: None)
    view.pack(fill="both", expand=True)
    view.set_world(world)
    root.update()

    states = []

    def add(name):
        view._base_key = None      # force the next _ensure_base to rebuild
        view._ensure_base()
        states.append((name, np.frombuffer(view._base_img.tobytes(), "u1")))

    # Political world view, no selection.
    view.selected = None
    view.zoom_faction = None
    view.selected_region = None
    view.mode = "political"
    view.layer = layers.SURFACE
    add("political")

    # Political with a faction selected -- the np.where(owner==sel) path.
    view.selected = world.factions[0]
    add("political_selected")

    # Region view via zoom_faction -- plain _px_region, textured.
    view.selected = None
    view.zoom_faction = world.factions[1]
    add("region_zoom")

    # Region view with a specific region selected -- the hi/base where path.
    view.zoom_faction = None
    view.selected_region = world.regions[3]
    add("region_selected")

    # The non-textured modes.
    view.selected = None
    view.selected_region = None
    for mode in ("fertility", "elevation", "climate"):
        view.mode = mode
        add(mode)

    # Biome mode -- full-strength texture.
    view.mode = "biome"
    add("biome")

    # The underworld raster (own path) -- only worlds that actually have one.
    if hasattr(world, "under_cells"):
        view.layer = layers.UNDER
        view.selected_region = None
        add("under")

    root.destroy()
    return states


def main():
    baseline = "--baseline" in sys.argv
    world_path = next((a for a in sys.argv[1:] if a.endswith(".pkl")),
                      "dev/worlds/dev560.pkl")
    print(f"{'recording' if baseline else 'checking'} render pixels on {world_path}")

    states = capture(world_path)
    out_path = world_path + ".render_pixels.npz"
    if baseline:
        np.savez(out_path, **{name: data for name, data in states})
        print(f"  wrote {len(states)} baselines to {out_path}")
        return 0

    try:
        ref = np.load(out_path)
    except FileNotFoundError:
        print(f"  no baseline at {out_path} -- run with --baseline first "
              "(baselines live next to the world and are gitignored like it)")
        return 1
    if set(ref.files) != {name for name, _ in states}:
        print("  baseline was recorded from a different state set -- "
              "re-record with --baseline")
        return 1
    for name, data in states:
        if name not in ref:
            check(name, False, "no baseline recorded")
            continue
        ref_data = ref[name]
        same = len(data) == len(ref_data) and bool(np.array_equal(data, ref_data))
        if same:
            check(name, True)
        else:
            diff = int(np.count_nonzero(data != ref_data)) if len(data) == len(ref_data) else -1
            check(name, False, f"{diff} bytes differ")
    print("\nRENDER PIXELS " + ("FAILED: " + ", ".join(FAILURES) if FAILURES else "MATCH"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
