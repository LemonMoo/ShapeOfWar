"""Render the drawn HUD to a PNG, so it can be looked at.

    python dev/hud_shot.py [out.png]

This project has been saved five times by rendering something before trusting
it (HANDOFF's START HERE), and a UI surface is the most obvious case of all: a
palette can be read in the source, but "does a page of drawn parchment with a
dotted leader and a wax seal on it actually look like anything" cannot.

Builds a real Page (app/ui/parchment.py) against a real Tk canvas, fills it
with the kind of content the HUD actually shows, and grabs the window.
"""
import os
import sys
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "shots", "hud.png")

try:
    root = tk.Tk()
except tk.TclError as exc:
    print(f"no display available ({exc}) -- skipping")
    sys.exit(0)

from app.ui import parchment, theme

root.configure(bg=theme.BG)
root.geometry("1180x660")

open_state = {"stores": True, "herds": False}

left = parchment.Page(root, 300, seed=3, palette_name="vellum")
left.canvas.pack(side="left", fill="y", padx=12, pady=12)
left.begin(600)
left.title("Khazhold", "a dwarf hold, below the Iron Reach")
left.kv("Population", "1,874")
left.kv("Prosperity", "62", fg=theme.GOOD)
left.kv("Season", "Autumn, Year 3")
left.gap()
if left.card("stores", "Stores", open_state):
    left.bar("Granary", 1840, 2400)
    left.bar("Warehouse", 3100, 2800)
    left.bar("Feed", 240, 900)
    left.kv("Salted Meat", "726")
    left.kv("Cave-aged Cheese", "418")
    left.kv("Mushrooms", "54")
left.gap()
if left.card("herds", "Herds", open_state, subtitle="12 head"):
    left.kv("Goats", "8")
left.divider()
left.alert("Bokhollow was raided from below — 260 of its stores carried off",
           "critical")
left.alert("Filthole has gone without food for 3 days")
left.gap()
left.button("Muster the host", lambda: None, kind="accent")
left.button("Open the gate", lambda: None)
left.finish()

right = parchment.Page(root, 380, seed=11, palette_name="vellum")
right.canvas.pack(side="left", fill="y", padx=(0, 12), pady=12)
right.begin(600)
right.title("The Realm")
right.text("A realm of seven regions under the mountains and the skirts "
           "around them. Its halls are rich and its fields are somebody "
           "else's.", fill=theme.MUTED)
right.divider()
right.kv("Iron", "1,204")
right.kv("Coal", "980")
right.kv("Gold Ore", "412", fg=theme.ACCENT)
right.kv("Gems", "38", fg=theme.ACCENT)
right.gap()
right.bar("Treasury", 4200, 8000)
right.gap()
right.button("Sound the horns", lambda: None, kind="danger")
right.finish()


pale = parchment.Page(root, 300, seed=3, palette_name="parchment")
pale.canvas.pack(side="left", fill="y", padx=(0, 12), pady=12)
pale.begin(600)
pale.title("Khazhold", "a dwarf hold, below the Iron Reach")
pale.kv("Population", "1,874")
pale.kv("Prosperity", "62", fg="#3f6a2c")
pale.kv("Season", "Autumn, Year 3")
pale.gap()
if pale.card("stores", "Stores", {"stores": True}):
    pale.bar("Granary", 1840, 2400)
    pale.bar("Warehouse", 3100, 2800)
    pale.kv("Salted Meat", "726")
    pale.kv("Cave-aged Cheese", "418")
pale.gap()
pale.alert("Bokhollow was raided from below — 260 of its stores carried off",
           "critical")
pale.gap()
pale.button("Muster the host", lambda: None, kind="accent")
pale.finish()

root.update()
try:
    from PIL import ImageGrab
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    x, y = root.winfo_rootx(), root.winfo_rooty()
    grab = ImageGrab.grab((x, y, x + root.winfo_width(), y + root.winfo_height()))
    grab.save(OUT)
    print(f"wrote {OUT} ({grab.width}x{grab.height})")
except Exception as exc:
    print(f"could not grab the window ({exc}) -- showing it instead")
    root.mainloop()
root.destroy()
