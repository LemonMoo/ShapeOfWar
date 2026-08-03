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

# ...and the selection panel beside it, which is the rest of the conversion.
# A settlement selection zooms the camera; the panel is what is being looked
# at here, so the view is put back afterwards.
target = next((s for s in world.settlements if s.faction_idx == 0), None)
if target is not None:
    view.selected_settlement = target
    view._show_settlement(target)
view.view = [0.0, 0.0, world.w, world.h]
view._apply_panel_layout()
# On top, or the grab catches whatever window happens to be over it -- which
# is exactly what happened the first time this ran.
root.attributes("-topmost", True)
root.lift()
root.update()
root.after(120, lambda: None)
root.update()

try:
    from PIL import ImageGrab
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    # Grab the PANELS, not the window. The map canvas asks for a size of its
    # own, so on a small test window the right-hand panel is placed past the
    # window's own right edge and a whole-window grab simply misses it.
    panel = view._panel
    x0 = min(view.alerts_frame.winfo_rootx(), panel.winfo_rootx())
    y0 = min(view.alerts_frame.winfo_rooty(), panel.winfo_rooty())
    x1 = max(view.alerts_frame.winfo_rootx() + view.alerts_frame.winfo_width(),
             panel.winfo_rootx() + panel.winfo_width())
    y1 = max(view.alerts_frame.winfo_rooty() + view.alerts_frame.winfo_height(),
             panel.winfo_rooty() + panel.winfo_height())
    grab = ImageGrab.grab((x0, y0, x1, y1))
    grab.save(OUT)
    print(f"wrote {OUT} ({grab.width}x{grab.height}), "
          f"{len(view._current_alerts)} alerts")
except Exception as exc:
    print(f"could not grab the window ({exc})")
root.destroy()
