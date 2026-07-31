"""MapView's side panels, against a real Tk widget tree.

    python dev/test_panels.py [world.pkl]

HANDOFF.md section 13.1: "No dedicated Tk-widget-construction test exists for
'does the panel widget tree still build without exceptions' the way there is
for globe rendering or battle logic" -- every UI change so far was checked with
throwaway scripts that were never committed. This is that harness, built to the
pattern that section itself recommends: construct a real MapView against a real
world and call every _show_* method for a real node of each kind.

Skips cleanly with exit 0 where there is no display -- that is an environment
fact, not a defect.
"""
import sys
import os
import pickle

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk

try:
    root = tk.Tk()
    root.withdraw()
except tk.TclError as exc:
    print(f"no display available ({exc}) -- skipping")
    sys.exit(0)

from app.ui.map_view import MapView
from app.world import buildings as B
from app.world import commander as C
from app.world import resources as R

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "worlds", "dev560.pkl")
world = pickle.load(open(PATH, "rb"))
if world.player_faction_idx is None:
    world.player_faction_idx = 0
pidx = world.player_faction_idx
print(f"world: turn {world.turn}, player {world.factions[pidx].name}")


def noop(*a, **k):
    pass


def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)


def texts(widget):
    out = []
    for wdg in walk(widget):
        try:
            value = wdg.cget("text")
        except tk.TclError:
            continue
        if value:
            out.append(str(value))
    return out


def buttons(widget):
    return [wdg for wdg in walk(widget) if isinstance(wdg, tk.Button)]


view = MapView(root, world, noop, noop)
view.pack(fill="both", expand=True)
root.update_idletasks()
print("  ok    MapView constructed")

village = next(v for v in world.villages if v.faction_idx == pidx)
settlement = next(s for s in world.settlements if s.faction_idx == pidx)
region = world.regions[settlement.region_id]
faction = world.factions[pidx]

print("\n--- every panel builds ---")
cases = [
    ("faction", lambda: view._show_faction(faction)),
    ("region", lambda: view._show_region(region)),
    ("settlement", lambda: view._show_settlement(settlement)),
    ("village", lambda: view._show_village(village)),
]
cmds = C.faction_commanders(world, pidx)
if cmds:
    cases.append(("commander", lambda: view._show_commander(cmds[0])))
for name, call in cases:
    call()
    root.update_idletasks()
    assert texts(view.actions) or texts(view), f"{name} panel came out empty"
    print(f"  ok    {name:<12} {len(list(walk(view.actions)))} widgets")

print("\n--- the BUILD card offers a way into the build menu ---")
for node in (settlement, village):
    (view._show_settlement if hasattr(node, "kind") else view._show_village)(node)
    root.update_idletasks()
    joined = " | ".join(texts(view.actions))
    assert "BUILD" in joined, joined[:300]
    entry = [b for b in buttons(view.actions) if "Build Menu" in str(b.cget("text"))]
    assert entry, f"{node.name}: no Open Build Menu button"
    print(f"  ok    {B.node_kind(node):<10} {node.name}: entry button present")

print("\n--- an urgent need is surfaced in the panel, not only in the menu ---")
orig = dict(getattr(village, "resources", {}) or {})
try:
    cap = R.node_pool_capacity(village, "household")
    village.resources = {"Barley": int(cap / R.resource_bulk("Barley")) + 10}
    view._show_village(village)
    root.update_idletasks()
    joined = " | ".join(texts(view.actions))
    assert "Granary" in joined and "full of Barley" in joined, joined[:400]
    assert "needed" in joined, "the card header should count what is needed now"
    print("  ok    the panel names the pressure without opening the menu")
finally:
    village.resources = orig

print("\n--- opening the menu from the panel works end to end ---")
view._show_village(village)
root.update_idletasks()
entry = next(b for b in buttons(view.actions) if "Build Menu" in str(b.cget("text")))
entry.invoke()
root.update_idletasks()
menus = getattr(root, "_build_menus", {})
assert menus, "no build menu window was registered"
window = next(iter(menus.values()))
assert window.winfo_exists()
assert village.name in " | ".join(texts(window))
print(f"  ok    the button opened a menu for {village.name}")
window.destroy()
root.update_idletasks()

print("\n--- panels survive a real turn ---")
R.advance_turn(world)
for name, call in cases:
    call()
    root.update_idletasks()
print("  ok    every panel rebuilds after advance_turn")

print("\n--- every floating panel survives the canvas/GL swap ---")
# The bug this guards, twice over: the flat map is a GL surface that
# REPLACES self.canvas (_activate_flatgl does self.canvas.pack_forget()).
# Anything parented to the canvas goes invisible with it, and Tk gives no
# error -- the trade log shipped that way and simply never appeared when
# its tab was clicked, because the tab itself was parented to the MapView
# and stayed perfectly clickable. Overlays belong on the MapView.
floating = [("trade log", view.trade_log_frame),
            ("trade log tab", view._trade_log_btn),
            ("alerts", view.alerts_frame),
            ("treasury", view.treasury_frame),
            ("resource bar", view._resource_bar)]
for name, widget in floating:
    assert widget.master is view, (
        f"the {name} is parented to {widget.master!r}, not the MapView -- it "
        f"will vanish whenever the canvas is swapped for the GL flat map")
print(f"  ok    all {len(floating)} floating panels hang off the MapView itself")

view.canvas.pack_forget()          # what _activate_flatgl does
root.update_idletasks()
if not view._trade_log_open:
    view._toggle_trade_log()
root.update_idletasks()
# winfo_manager(), not winfo_ismapped(): whether a widget is really on
# screen depends on the toplevel being realized at a real size, which a
# headless harness cannot promise. "Did _place_trade_log place it, or
# place_forget it" is the thing this is actually guarding, and that is
# exactly what the geometry manager reports.
assert view.trade_log_frame.winfo_manager() == "place", (
    "the trade log was not placed with the canvas swapped out")
print("  ok    the trade log still opens with the canvas swapped out")

root.destroy()
print("\nPANELS TEST PASSED")
