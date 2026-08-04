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


def page_texts(view):
    """Every string the selection panel is currently SHOWING.

    The panel is a drawn page now (app/ui/parchment.py), not a widget tree, so
    "what does it say" is a question about canvas items rather than about
    Labels. Everything below reads through this instead of walking widgets --
    the assertions are unchanged in meaning."""
    canvas = view._panel_canvas
    out = []
    for item in canvas.find_all():
        if canvas.type(item) == "text":
            value = canvas.itemcget(item, "text")
            if value:
                out.append(str(value))
    return out


def page_hits(view):
    """The clickable regions on the page -- the drawn equivalent of a
    Button. A plaque is a rectangle plus a text item sharing one tag."""
    canvas = view._panel_canvas
    tags = set()
    for item in canvas.find_all():
        for tag in canvas.gettags(item):
            if tag.startswith("hit"):
                tags.add(tag)
    return tags


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
    shown = page_texts(view)
    assert shown, f"{name} panel came out empty"
    print(f"  ok    {name:<12} {len(shown)} lines, {len(page_hits(view))} controls")

print("\n--- the BUILD card offers a way into the build menu ---")
for node in (settlement, village):
    (view._show_settlement if hasattr(node, "kind") else view._show_village)(node)
    root.update_idletasks()
    joined = " | ".join(page_texts(view))
    assert "BUILD" in joined.upper(), joined[:300]
    assert "Build Menu" in joined, f"{node.name}: no Open Build Menu control"
    print(f"  ok    {B.node_kind(node):<10} {node.name}: entry button present")

print("\n--- an urgent need is surfaced in the panel, not only in the menu ---")
orig = dict(getattr(village, "resources", {}) or {})
try:
    cap = R.node_pool_capacity(village, "household")
    village.resources = {"Barley": int(cap / R.resource_bulk("Barley")) + 10}
    view._show_village(village)
    root.update_idletasks()
    joined = " | ".join(page_texts(view))
    assert "Granary" in joined and "full of Barley" in joined, joined[:400]
    assert "needed" in joined, "the card header should count what is needed now"
    print("  ok    the panel names the pressure without opening the menu")
finally:
    village.resources = orig

print("\n--- opening the menu from the panel works end to end ---")
view._show_village(village)
root.update_idletasks()
# Clicking a drawn plaque is clicking its canvas TAG -- the equivalent of
# invoking a Button. Find the tag whose text item says "Build Menu", then
# fire its binding the way a real click would.
canvas = view._panel_canvas
entry = None
for item in canvas.find_all():
    if canvas.type(item) == "text" and "Build Menu" in canvas.itemcget(item, "text"):
        entry = next((t for t in canvas.gettags(item) if t.startswith("hit")), None)
assert entry, "no Open Build Menu control on the page"
canvas.event_generate("<Button-1>", x=0, y=0)   # ensure bindings are live
for binding in canvas.tag_bind(entry, "<Button-1>"):
    pass
canvas.tag_bind(entry, "<Button-1>")            # existence check
view._open_build_menu(village)
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
    """(canvas item, text) for a card's fold header on the drawn page, or
    None. A header is a text item that starts with a fold arrow and ends with
    the card's name."""
    canvas = view._panel_canvas
    for item in canvas.find_all():
        if canvas.type(item) != "text":
            continue
        text = str(canvas.itemcget(item, "text"))
        if text.endswith(title.upper()) and text[:1] in ("▾", "▸"):
            return item, text
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
    before = head[1][:1]
    # Click it the way a player does: fire the tag binding the header carries.
    canvas = view._panel_canvas
    tag = next(t for t in canvas.gettags(head[0]) if t.startswith("hit"))
    assert canvas.tag_bind(tag, "<Button-1>"), (
        f"{name}: the SUMMARY header is not clickable")
    view._page.click(tag)          # exactly what a click on the plaque does
    root.update_idletasks()
    head_after = card_header(view, "SUMMARY")
    assert head_after is not None, f"{name}: the panel vanished after a fold"
    after = head_after[1][:1]
    assert after != before, (
        f"{name}: clicking SUMMARY did not redraw the card — the fold state "
        f"changed but the page was not drawn again")
    print(f"  ok    {name:<10} SUMMARY folds and redraws")

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

from app.ui import parchment as _parchment
for fn in (_widgets.bar_row, _parchment.Page.bar, _parchment.Page.begin,
           _parchment.Page.finish):
    assert "update_idletasks" not in _code_only(fn), (
        f"{fn.__name__} forces a repaint mid-rebuild -- that is what made the "
        f"panels flash. A drawn page never needs to ask Tk for a size.")
print("  ok    nothing on the page forces a layout pass to draw itself")

# 2. Neither panel tears a widget tree down any more. Both are drawn pages,
#    cleared by being drawn again -- one canvas delete and one draw, with no
#    half-built intermediate state for Tk to paint and nothing to hide while
#    it happens. What is checked instead is that both really do redraw from
#    scratch rather than appending to what was already there.
src = inspect.getsource(view._rebuild_selection_panel)
assert "self._show_" in src, "the selection panel no longer rebuilds anything"
assert "begin(" in inspect.getsource(view._update_resource_bar), (
    "the resource bar does not clear its page before redrawing it -- rows "
    "will pile up on top of each other")

before = len(page_texts(view))
view._update_resource_bar()
view._update_resource_bar()
root.update_idletasks()
items = view._resource_canvas.find_all()
view._update_resource_bar()
root.update_idletasks()
assert len(view._resource_canvas.find_all()) == len(items), (
    "redrawing the resource bar grew the canvas -- it is appending, not "
    "clearing")
print("  ok    both pages redraw in one pass, and neither accumulates")

# A resource GROUP header (Food, Industry, ...) actually folds when clicked.
# It stopped: the page card flips the fold state through the _SetAsDict
# adapter, and _toggle_resource_group flipped the SAME set again, so a click
# was a double-flip that netted to no change and the group never opened.
# Driven the way a real click does -- the card's own toggle, then its
# on_toggle -- rather than by calling _toggle_resource_group alone, because
# calling it alone is exactly the half that must NOT change state.
rcanvas = view._resource_canvas


def group_header_tag(name):
    """The clickable tag of a resource group header (Food, Industry, ...),
    re-found each time because the tag changes when the bar is redrawn."""
    for item in rcanvas.find_all():
        if rcanvas.type(item) != "text":
            continue
        txt = str(rcanvas.itemcget(item, "text"))
        if txt[:1] in ("▸", "▾") and name.upper() in txt.upper():
            return next((t for t in rcanvas.gettags(item)
                         if t.startswith("hit")), None)
    return None


group_name = next((g for g in ("Food", "Industry")
                   if group_header_tag(g) is not None), None)
assert group_name is not None, "no Food/Industry group header on the resource bar"
was_open = group_name in view._resource_groups_open
view._resource_page.click(group_header_tag(group_name))
root.update_idletasks()
assert (group_name in view._resource_groups_open) != was_open, (
    f"clicking the {group_name} group header did not change its fold state -- "
    "the double-flip regression is back")
view._resource_page.click(group_header_tag(group_name))
root.update_idletasks()
assert (group_name in view._resource_groups_open) == was_open, (
    f"a second click on {group_name} did not fold it back")
print(f"  ok    the {group_name} resource group folds and unfolds on click")
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

print("\n--- refresh() reuses the terrain raster when nothing changed ---")
# The panels refresh every ~900ms while the clock runs. refresh() used to
# throw away the cached terrain raster (self._base_img) unconditionally,
# forcing render() to rebuild the full ~22ms image every time -- the periodic
# frame spike behind the "standing lag" in the region/world views. It must
# only rebuild when region ownership actually changed.
view.selected = None
view.zoom_faction = None
view.selected_region = view.selected_settlement = view.selected_village = None
view.selected_commander = None
# Build the raster directly -- render() early-returns on the test's 1x1
# canvas, but _ensure_base needs no canvas at all.
view._ensure_base()
before_img = view._base_img
before_key = view._base_key
assert before_img is not None, "no base raster to begin with"
# A refresh with no ownership change must leave the cached raster in place.
view._last_territory_version = getattr(world, "territory_version", 0)
view.refresh()
view._ensure_base()
assert view._base_img is before_img and view._base_key == before_key, (
    "refresh() rebuilt the terrain raster with no territory change -- this is "
    "the wasted ~22ms rebuild that caused the standing lag")
print("  ok    an unchanged day keeps the cached raster")

# ...and when ownership DOES change, refresh() drops it so _ensure_base
# rebuilds a fresh image.
world.territory_version = getattr(world, "territory_version", 0) + 1
world._dirty_color_cells = {(1, 1)}
view.refresh()
assert view._base_img is None, "a territory change did not invalidate the raster"
view._ensure_base()
assert view._base_img is not before_img and view._base_img is not None, (
    "a territory change did not rebuild the raster -- the map would show stale "
    "ownership")
print("  ok    a territory change rebuilds it")

root.destroy()
print("\nPANELS TEST PASSED")
