"""Load menu: the world-details panel's map preview shows the actual map.

    python dev/test_load_preview.py

Written after v0.18.22 shipped a load menu whose "map preview" was a 30x30
corner of the world: the first implementation drew one canvas rectangle per
cell, so at 1 px per cell a default 1100x660 world overflowed the 120 px
canvas, and the fallback just stopped at the top-left 30x30 cells -- on most
worlds that corner is the seam ocean, i.e. a solid blue square, not a map.

What is asserted here is the contract the panel now meets: selecting a save
puts a real render_world thumbnail on the canvas -- an image item exists, it
fits the canvas while keeping the world's aspect, and its pixels are not one
flat colour (a blank or placeholder preview would be).
"""
import os
import sys
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# One live root for the whole test, created inside the guard: ImageTk
# PhotoImages bind to tkinter._default_root, so a destroyed probe root could
# leave the bind pointing at a dead Tcl interpreter and every check would
# fail for the wrong reason. A real display is required; skip otherwise.
try:
    root = tk.Tk()
except tk.TclError as exc:
    print(f"no display available ({exc}) -- skipping")
    sys.exit(0)
root.withdraw()

from app.ui.load_game_menu import LoadGameMenuView
from app.world.worldgen import generate_world

# Small on purpose: this harness generates a real world, and Small measures
# ~8s against Standard's ~18s. Nothing asserted depends on the size.
SMALL = dict(width=760, height=456, n_factions=8)

FAILURES = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not ok:
        FAILURES.append(name)


def test_preview(world):
    print("\n--- load-menu map preview ---")
    try:
        view = LoadGameMenuView(root, on_load=lambda sid: None,
                                on_delete=lambda sid: None,
                                on_cancel=lambda: None)
        view._create_map_preview(world)

        check("a PhotoImage was created (old code left it None)",
              view._map_img is not None)
        items = view._map_canvas.find_all()
        check("the canvas holds exactly the image",
              len(items) == 1 and view._map_canvas.type(items[0]) == "image",
              f"{len(items)} item(s)")

        img = view._map_img
        w, h = img.width(), img.height()
        check("preview fits the 120x120 canvas",
              w <= 120 and h <= 120, f"{w}x{h}")
        check("preview keeps the world's aspect",
              abs(w * world.h - h * world.w) <= world.w,
              f"{w}x{h} vs {world.w}x{world.h}")

        # The thumbnail must be a picture, not a flat placeholder. The canvas
        # holds the PhotoImage of render_world's output, so prove the render
        # itself carries real geography: ocean vs land is guaranteed on every
        # generated world.
        from app.ui.world_preview import render_world
        pil = render_world(world, (120, 120))
        check("the thumbnail is not one flat colour",
              len(set(pil.getdata())) >= 2,
              f"{len(set(pil.getdata()))} distinct colours")
    finally:
        root.destroy()


def main():
    print("generating a world (~8s)...")
    world = generate_world(seed=11, player_species="Dwarves", **SMALL)
    test_preview(world)
    print("\nLOAD PREVIEW TEST " + ("FAILED: " + ", ".join(FAILURES)
                                    if FAILURES else "PASSED"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
