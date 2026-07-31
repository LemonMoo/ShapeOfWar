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

print("\n--- folding cards actually fold, on EVERY kind of panel ---")
# The bug: _toggle_panel_card only redrew Settlements and Villages, so clicking
# SUMMARY or SETTLEMENTS on a Region flipped the card's stored state and then
# rebuilt nothing at all. The arrow even changed on the next unrelated redraw,
# which made it look like the card had refused to move rather than that the
# click had gone nowhere.
def card_header(view, title):
    for wdg in walk(view.actions):
        try:
            text = str(wdg.cget("text"))
        except tk.TclError:
            continue
        if text.endswith(title.upper()) and text[:1] in ("▾", "▸"):
            return wdg
    return None


def select(kind):
    """Put the view into the state a real click leaves it in. The _show_*
    methods only DRAW -- it is _on_click that records what is selected (see
    map_view's click handler), and a fold has to redraw from that same
    recorded state, so a test that only calls _show_* would be testing a
    situation the game never gets into."""
    view.selected = view.selected_region = None
    view.selected_settlement = view.selected_village = None
    view.selected_commander = None
    if kind == "region":
        view.selected, view.selected_region = faction, region
        view._show_region(region)
    elif kind == "faction":
        view.selected = faction
        view._show_faction(faction)
    elif kind == "settlement":
        view.selected_settlement = settlement
        view._show_settlement(settlement)
    else:
        view.selected_village = village
        view._show_village(village)


for name in ("region", "faction", "settlement", "village"):
    select(name)
    root.update_idletasks()
    head = card_header(view, "SUMMARY")
    assert head is not None, f"{name} panel has no SUMMARY card to fold"
    before = str(head.cget("text"))[:1]
    head.event_generate("<Button-1>")
    root.update_idletasks()
    head_after = card_header(view, "SUMMARY")
    assert head_after is not None, f"{name}: the panel vanished after a fold"
    after = str(head_after.cget("text"))[:1]
    assert after != before, (
        f"{name}: clicking SUMMARY did not redraw the card "
        f"(arrow stayed {before!r}) -- the fold state flipped with nothing "
        f"rebuilt to show it")
    # And put it back, so the next case starts from a known state.
    head_after.event_generate("<Button-1>")
    root.update_idletasks()
    print(f"  ok    {name:<11} SUMMARY folds {before} -> {after} and back")

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

print("\n--- panels rebuild without painting the half-built state ---")
# Two separate causes of the side panels visibly flashing once a turn, both
# guarded here because both are easy to reintroduce without noticing.
import inspect
from app.ui import widgets as _widgets

# 1. Forcing a layout pass mid-rebuild. update_idletasks() makes Tk process
#    geometry AND repaint immediately, so calling it while a panel is
#    half-built paints the half-built panel. bar_row did it once per storage
#    meter -- four times a turn on a settlement with four pools.
def _code_only(fn):
    """Source with comment lines stripped -- the notes explaining why these
    no longer call update_idletasks() name it, and would match otherwise."""
    return "\n".join(line for line in inspect.getsource(fn).splitlines()
                     if not line.lstrip().startswith("#"))

for fn in (_widgets.bar_row, view._draw_prosperity_bar, view._draw_storage_bar):
    assert "update_idletasks" not in _code_only(fn), (
        f"{fn.__name__} forces a repaint mid-rebuild -- that is what made the "
        f"panels flash. Read the width from <Configure> instead.")
print("  ok    no meter forces a layout pass to learn its own width")

# 2. Tearing a mapped frame down and building it back up in place. Unmapping
#    it first means the empty middle has nowhere to be drawn.
src = inspect.getsource(view._rebuild_selection_panel)
assert "_quiet_rebuild" in src, (
    "the selection panel rebuilds while mapped -- the empty gap will paint")
src = inspect.getsource(view._update_resource_bar)
assert "hidden" in src, (
    "the resource bar rebuilds its rows while visible")
print("  ok    both rebuilds hide their container first")

# ...and both must put it back, whatever happens inside.
before = view.actions.pack_info()
try:
    with view._quiet_rebuild(view.actions):
        raise RuntimeError("boom")
except RuntimeError:
    pass
assert view.actions.pack_info() == before, (
    "_quiet_rebuild lost the frame's pack options after an exception")
state = view._resource_canvas.itemcget(view._resource_rows_window, "state")
assert state == "normal", state
print("  ok    the container comes back even if the rebuild raises")

print("\n--- a commander's march is drawn on the GPU map, not only the canvas ---")
# The bug: _draw_commanders has drawn the dashed route on the Tk canvas since
# commanders existed, but _map_lines -- what the GPU flat map draws from --
# never included it. On the GPU surface, giving a move order showed nothing.
from app.world import commander as C
import random as _random

C.ensure_faction_commanders(world)
mine = next((c for c in world.commanders if c.faction_idx == pidx), None)
if mine is None:
    print("  skip  the player has no commander on this save")
else:
    view.selected_commander = mine
    before = len(view._map_lines(2, 4.0))
    sig_before = view._flat_content_signature(2, 4.0)
    land = [(x, y) for y in range(0, world.h, 37) for x in range(0, world.w, 37)
            if world.owner[y][x] != C.OCEAN]
    C.set_move_order(world, mine, _random.Random(3).choice(land))
    assert mine.path, "could not give this commander a route to test with"
    assert len(view._map_lines(2, 4.0)) > before, (
        "the march added no line to the GPU line list")
    # ...and the map has to notice. The order is given to an ALREADY selected
    # commander, so nothing else in the signature moves; without a term for
    # the route the cached lines would be reused until the turn ended.
    assert view._flat_content_signature(2, 4.0) != sig_before, (
        "the flat map would reuse its cached lines and not draw the route "
        "until the end of the turn")
    print(f"  ok    a {len(mine.path)}-cell march reaches the GPU map, and the "
          f"content cache notices immediately")

root.destroy()
print("\nPANELS TEST PASSED")
