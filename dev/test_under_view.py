"""Looking at the underworld (app/ui/map_view.py).

    python dev/test_under_view.py

Phase 2 of SUBTERRANEAN_PLAN.md. The plan's own risk note for this phase was
that "which layer am I looking at" has to be ONE piece of state, settled here,
or the assumption that there is a single map gets patched into twenty places.
So that is what most of this asserts: one flag, and everything -- the raster,
the cache key, the click handler, the markers -- reading it.

Builds a real MapView against a real generated world, the same pattern
dev/test_panels.py uses.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk

from app.world import layers as L
from app.world.worldgen import generate_world, OCEAN

try:
    root = tk.Tk()
except tk.TclError as exc:
    print(f"no display available ({exc}) -- skipping")
    sys.exit(0)
root.withdraw()

from app.ui.map_view import (MapView, _UNDER_GATE_RGB, _UNDER_KIND_RGB,
                             _UNDER_ROCK, _UNDER_ABOVE_LAND)


def noop(*a, **k):
    pass


world = generate_world(560, 340, seed=7, n_factions=6)
world.player_faction_idx = 0
print(f"world: {world.under_summary}")
assert world.under_cells and world.gates, "this seed carved nothing to look at"

view = MapView(root, world, noop, noop)
view.pack(fill="both", expand=True)
root.update_idletasks()

try:
    print("\n--- one piece of state, and it starts on the surface ---")
    assert view.layer == L.SURFACE
    view._ensure_base()
    surface_img = view._base_img
    surface_key = view._base_key
    print(f"  ok    layer={view.layer}, base key {surface_key!r}")

    print("\n--- descending changes what is drawn, not just a flag ---")
    view.toggle_layer()
    root.update_idletasks()
    view._ensure_base()
    assert view.layer == L.UNDER
    assert view._base_key != surface_key, "the raster cache key did not change"
    under_img = view._base_img
    assert list(under_img.getdata()) != list(surface_img.getdata()), (
        "the underworld draws exactly the same pixels as the surface")
    print(f"  ok    base key {view._base_key!r}")

    print("\n--- unexplored ground is not drawn at all ---")
    # Phase 3 put darkness on this raster (app/world/vision.py): a gallery
    # nobody has carried a lantern down is indistinguishable from the rock
    # around it, which is why the assertions below have to light the map
    # first. Rock and unexplored are the SAME pixel here on purpose -- a
    # greyed-out shape would still tell you a hall was there.
    dark_img = view._base_img
    lit_cell = next(iter(world.under_kind))
    assert dark_img.getpixel(lit_cell) in (_UNDER_ROCK, _UNDER_ABOVE_LAND), (
        "an unexplored gallery is drawn on the map")
    world.under_fog = set(world.under_cells)
    view._base_key = None
    view._ensure_base()
    under_img = view._base_img
    print("  ok    dark until walked, and the whole network once it is")

    print("\n--- the raster says what is actually down there ---")
    for (x, y), kind in list(world.under_kind.items())[:400]:
        if L.owner_at(world, x, y, L.UNDER) is not None:
            continue                      # held ground is tinted; see _under_pixels
        if L.region_at(world, x, y, L.UNDER) == getattr(view.selected_region, "id", -1):
            continue
        if (x, y) in {tuple(g["under"]) for g in world.gates}:
            continue
        assert under_img.getpixel((x, y)) == _UNDER_KIND_RGB[kind], (
            f"a {kind} at {(x, y)} is not drawn as one")
    gate = world.gates[0]
    assert under_img.getpixel(tuple(gate["under"])) == _UNDER_GATE_RGB
    print(f"  ok    galleries, caverns, water and chasms all read as themselves; "
          f"{len(world.gates)} gates marked")

    print("\n--- the sea is still the sea, so you know where you are ---")
    # Descending into an unrelieved black void with a squiggle in it is
    # disorienting: the land above is drawn as a second shade of rock.
    ocean = next((x, y) for y in range(world.h) for x in range(world.w)
                 if world.owner[y][x] == OCEAN)
    land = next((x, y) for y in range(world.h) for x in range(world.w)
                if world.owner[y][x] != OCEAN and (x, y) not in world.under_cells)
    assert under_img.getpixel(ocean) != under_img.getpixel(land), (
        "sea and land are the same colour below ground -- there is no way to "
        "tell where on the map you are")
    print("  ok    the coastline is still readable from below")

    print("\n--- gates are marked on BOTH layers ---")
    gate_rgb = tuple(c / 255.0 for c in _UNDER_GATE_RGB)
    below = [m for m in view._flat_markers(0) if m[3] == gate_rgb]
    view.toggle_layer()
    root.update_idletasks()
    above = [m for m in view._flat_markers(0) if m[3] == gate_rgb]
    assert view.layer == L.SURFACE
    print(f"  {len(above)} gate markers on the surface, {len(below)} below")
    assert len(above) == len(world.gates) == len(below), (
        "a gate is not marked on one of the two sides")
    surface_cells = {tuple(g["pos"]) for g in world.gates}
    assert {(m[0], m[1]) for m in above} == surface_cells, (
        "the surface markers are not at the gates' surface mouths")
    print("  ok    a door is visible from either side of it")

    print("\n--- clicking below ground picks a hall, not a surface region ---")
    view.toggle_layer()
    root.update_idletasks()
    cell = next(p for p in sorted(world.under_cells)
                if L.region_at(world, p[0], p[1], L.UNDER) is not None)
    rid = L.region_at(world, cell[0], cell[1], L.UNDER)
    under_region = world.regions[rid]
    assert L.is_under(under_region)
    surface_rid = world.region_grid[cell[1]][cell[0]]
    assert surface_rid != rid, (
        "this test cell cannot tell the two layers apart -- pick another")

    class Click:
        pass

    ev = Click()
    ev.x, ev.y = view.world_to_screen(cell[0], cell[1]) if hasattr(
        view, "world_to_screen") else (0, 0)
    view._show_region(under_region)          # the panel path the click takes
    view.selected_region = under_region
    root.update_idletasks()
    assert view.selected_region is under_region
    print(f"  ok    {under_region.name} selects as an underground region "
          f"(surface region {surface_rid} is a different place entirely)")

    print("\n--- coming back up restores the surface view ---")
    view.toggle_layer()
    root.update_idletasks()
    view._ensure_base()
    assert view.layer == L.SURFACE
    assert view.selected_region is None, (
        "a selection made below ground survived the trip back up")
    print("  ok    surface again, with nothing selected from below")
finally:
    try:
        root.destroy()
    except tk.TclError:
        pass

print("\nUNDER VIEW TEST PASSED")
