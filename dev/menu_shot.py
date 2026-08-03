"""The title screen and the build menu, as PNGs.

    python dev/menu_shot.py

Same reason dev/hud_shot.py exists: a drawn surface has to be looked at. The
title screen is the first thing anybody sees, and the build menu is the
densest data screen in the game -- if the page kit fails anywhere, it fails on
one of those two.
"""
import os
import pickle
import sys
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots")

try:
    root = tk.Tk()
except tk.TclError as exc:
    print(f"no display available ({exc}) -- skipping")
    sys.exit(0)

from app.ui import build_menu, theme
from app.ui.main_menu import MainMenuView
from app.world import buildings as B


def grab(widget, name):
    from PIL import ImageGrab
    os.makedirs(SHOTS, exist_ok=True)
    # Raise the widget's OWN toplevel: the build menu is a Toplevel over the
    # root, and lifting the root puts it behind the thing being photographed.
    top = widget.winfo_toplevel()
    top.attributes("-topmost", True)
    top.lift()
    top.update()
    top.update_idletasks()
    x, y = widget.winfo_rootx(), widget.winfo_rooty()
    img = ImageGrab.grab((x, y, x + widget.winfo_width(),
                          y + widget.winfo_height()))
    out = os.path.join(SHOTS, name)
    img.save(out)
    print(f"wrote {out} ({img.width}x{img.height})")


root.geometry("980x620")
root.configure(bg=theme.BG)
menu = MainMenuView(root, lambda: None, lambda: None, lambda: None,
                    has_save=lambda: True, on_settings=lambda: None,
                    on_credits=lambda: None)
menu.pack(fill="both", expand=True)
root.update()
grab(root, "menu.png")
menu.destroy()

world = pickle.load(open(os.path.join(os.path.dirname(__file__), "worlds",
                                      "dev560.pkl"), "rb"))
if world.player_faction_idx is None:
    world.player_faction_idx = 0
pidx = world.player_faction_idx
village = next(v for v in world.villages if v.faction_idx == pidx)
win = build_menu.BuildMenuWindow(root, world, village, world.factions[pidx])
win.update_idletasks()
root.update()
grab(win, "build_menu.png")
root.destroy()
