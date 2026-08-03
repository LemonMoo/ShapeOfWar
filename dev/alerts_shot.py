"""The real alerts panel, on a real world, as a PNG.

    python dev/alerts_shot.py [out.png]

dev/hud_shot.py renders the KIT against invented content; this renders the
panel the game actually builds, from real alerts on a real generated world.
Both are needed: the first says whether the drawing is any good, the second
says whether the conversion of a real panel kept its behaviour.
"""
import os
import sys
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "shots", "alerts.png")

try:
    root = tk.Tk()
except tk.TclError as exc:
    print(f"no display available ({exc}) -- skipping")
    sys.exit(0)

from app.ui.map_view import MapView
from app.ui import theme
from app.world import resources as R
from app.world.worldgen import generate_world

root.configure(bg=theme.BG)
root.geometry("1100x700")

world = generate_world(560, 340, seed=21, n_factions=8)
world.player_faction_idx = 0
view = MapView(root, world, lambda *a, **k: None, lambda *a, **k: None)
view.pack(fill="both", expand=True)

# Real trouble, rather than a world that happens to be fine on day one: starve
# a few of the player's own nodes and let the panel report what it finds.
mine = [n for n in list(world.settlements) + list(world.villages)
        if n.faction_idx == 0]
for i, node in enumerate(mine[:9]):
    node.turns_without_food = 9 if i % 3 == 0 else 2
    if i % 4 == 0:
        node.turns_without_firewood = 7
    if i % 5 == 0:
        node.raided_turn = world.turn
        node.raided_amount = 260

view._refresh_alerts()
view._alerts_expanded = {a["kind"] for a in view._current_alerts[:1]}
view._render_alerts()
root.update()

try:
    from PIL import ImageGrab
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    x, y = root.winfo_rootx(), root.winfo_rooty()
    grab = ImageGrab.grab((x, y, x + root.winfo_width(), y + root.winfo_height()))
    grab.save(OUT)
    print(f"wrote {OUT} ({grab.width}x{grab.height}), "
          f"{len(view._current_alerts)} alerts")
except Exception as exc:
    print(f"could not grab the window ({exc})")
root.destroy()
