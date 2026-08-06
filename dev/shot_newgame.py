"""The New Game screen, as PNGs -- for the preview rework.

    python dev/shot_newgame.py

Shows the world preview twice with a Dwarf selected: once with the default
start (white ring) and once after clicking a different start (green ring,
and the white default ring must be GONE -- the residual-circle bug). Also
asserts, on pixels, that:

  * the preview shows the violet cave-door diamonds (Dwarf entrances), and
  * after choosing a start, no white ring remains at the default capital.
"""
import os
import sys
import time
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots")

try:
    root = tk.Tk()
except tk.TclError as exc:
    print(f"no display available ({exc}) -- skipping")
    sys.exit(0)

root.geometry("1360x800")
from app.ui import new_game as NG
from app.ui import theme

view = NG.NewGameView(root, on_play=lambda w: None, on_back=lambda: None)
view.pack(fill="both", expand=True)

# A Dwarf world, Small so the shot is quick.
view._pick_size(0)
view._pick_species("Dwarves")
view._request_world()

deadline = time.time() + 90
while view._world is None and time.time() < deadline:
    root.update()
    root.update_idletasks()
    time.sleep(0.05)
assert view._world is not None, "world never finished generating"
root.update()


def grab(name):
    os.makedirs(SHOTS, exist_ok=True)
    from PIL import ImageGrab
    top = view.winfo_toplevel()
    top.attributes("-topmost", True)
    top.lift()
    top.update()
    top.update_idletasks()
    x, y = view.winfo_rootx(), view.winfo_rooty()
    w, h = view.winfo_width(), view.winfo_height()
    img = ImageGrab.grab((x, y, x + w, y + h))
    path = os.path.join(SHOTS, name)
    img.save(path)
    print(f"  -> {path}")
    return img


def count_color(img, rgb, box):
    """Pixels matching rgb within (x0, y0, x1, y1), where the box is in
    PREVIEW-local coordinates and img is the full-window grab."""
    x0, y0 = view._preview.winfo_rootx() - view.winfo_rootx(), \
             view._preview.winfo_rooty() - view.winfo_rooty()
    x0 += box[0]; y0 += box[1]
    n = 0
    for yy in range(y0, y0 + box[3]):
        for xx in range(x0, x0 + box[2]):
            p = img.getpixel((xx, yy))[:3]
            if abs(p[0] - rgb[0]) <= 12 and abs(p[1] - rgb[1]) <= 12 \
                    and abs(p[2] - rgb[2]) <= 12:
                n += 1
    return n


print("\n--- shot 1: default start (white ring), Dwarves ---")
img1 = grab("newgame_dwarves_default.png")

world = view._world
scale = view._preview_scale
cap = world.factions[world.player_faction_idx].meta["capital"]
# A small box around the default capital's ring radius.
ring_r = max(4, int(min(view._preview.winfo_width(),
                        view._preview.winfo_height()) * 0.035))
box = (int(cap[0] * scale) - ring_r - 4, int(cap[1] * scale) - ring_r - 4,
       2 * (ring_r + 4), 2 * (ring_r + 4))
white_default = count_color(img1, (255, 255, 255), box)
door_px = count_color(img1, (0xB0, 0x6A, 0xD4),
                      (0, 0, view._preview.winfo_width(),
                       view._preview.winfo_height()))
print(f"  white pixels at default capital: {white_default} "
      f"(expect > 0: the default ring)")
print(f"  violet door pixels: {door_px} (expect > 0: dwarf entrances)")
assert white_default > 0, "shot 1 should show the default white ring"
assert door_px > 0, "dwarf preview should show the violet door diamonds"

print("\n--- shot 2: a start was CHOSEN (green ring, no white) ---")
import random as _random
# Click a land cell far from the default capital.
wx = (cap[0] + 60) % world.w
wy = cap[1]
class _Ev:  # a minimal click event
    x = int(wx * scale)
    y = int(wy * scale)
view._on_preview_click(_Ev())
assert view._start_cell is not None, "click should have chosen a start"
root.update()
img2 = grab("newgame_dwarves_chosen.png")
white_default2 = count_color(img2, (255, 255, 255), box)
start = view._start_cell
green_box = (int(start[0] * scale) - 8, int(start[1] * scale) - 8, 16, 16)
green_chosen = count_color(img2, (0x5F, 0xD0, 0x6A), green_box)
print(f"  white pixels at default capital after choice: {white_default2} "
      f"(expect 0: residual ring is gone)")
print(f"  green pixels at chosen start: {green_chosen} (expect > 0)")
assert white_default2 == 0, "residual white ring must not remain"
assert green_chosen > 0, "the chosen start must show the green ring"

print("\nNEW GAME SHOT PASSED")
root.destroy()
