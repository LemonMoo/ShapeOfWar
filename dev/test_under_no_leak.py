"""The under layer does not leak the overworld (v0.18.15).

Descending must not hand over magical vision of the surface: the landmass
silhouette, surface roads/trade lanes, terrain glyphs, ships, surface
caravans, realm/region names and construction sites are all overworld
information, and none of it may render on the under layer. The under view
shows the cave world, gates, under settlements/villages, and marches -- each
layer-gated on its own.
"""
import os
import sys
import pickle
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ui import map_view as M
from app.world import layers as L

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "worlds",
                    "dev560.pkl")
world = pickle.load(open(PATH, "rb"))
world.player_faction_idx = 0

root = tk.Tk()
root.withdraw()
view = M.MapView(root, world, lambda: None, lambda: None)
try:
    # --- terrain raster: the silhouette is reveal-gated ---
    under = view._under_pixels()
    rock, above = M._UNDER_ROCK, M._UNDER_ABOVE_LAND
    # A cell that is land and NOT surface-revealed must read as rock.
    import app.world.vision as V
    fog = getattr(world, "fog", None)
    hidden = next((x, y) for y in range(world.h) for x in range(world.w)
                  if world.owner[y][x] >= 0
                  and fog is not None and not fog[y * world.w + x])
    assert under[hidden[1] * world.w + hidden[0]] == rock, (
        f"unexplored land ({hidden}) shows as the overworld silhouette")
    # An owned (always-revealed) land cell keeps the silhouette.
    own = next((x, y) for y in range(world.h) for x in range(world.w)
               if world.owner[y][x] == 0)
    assert under[own[1] * world.w + own[0]] == above, (
        "your own land lost its silhouette")
    print("  ok    the landmass silhouette is gated by surface reveal")

    # --- terrain glyphs: surface only ---
    view.layer = L.UNDER
    g = view._flat_terrain_symbols(0, 0, world.w, world.h, 1.0)
    assert g == [], f"under view emits terrain glyphs: {len(g)}"
    view.layer = L.SURFACE
    g = view._flat_terrain_symbols(0, 0, world.w, world.h, 1.0)
    print("  ok    terrain glyphs: none below, "
          f"{len(g)} above")

    # --- roads and trade lanes: surface only ---
    view.layer = L.UNDER
    lines_under = view._map_lines(2, 4.0)
    view.layer = L.SURFACE
    lines_surface = view._map_lines(2, 4.0)
    # Road/trade colors never appear below; they do above (the dev world
    # has roads and trade routes).
    road_colors = {tuple(M._GL_RGB[c]) for c in
                   (M._DIRT_ROAD_COLOR, M._STONE_ROAD_COLOR, M._TRADE_LAND_COLOR)}
    under_roads = [ln for ln in lines_under if tuple(ln[1]) in road_colors]
    surface_roads = [ln for ln in lines_surface if tuple(ln[1]) in road_colors]
    assert not under_roads, f"{len(under_roads)} road/trade lines below"
    assert surface_roads, "the surface view lost its roads"
    print("  ok    roads and trade lanes: none below, "
          f"{len(surface_roads)} above")

    # --- ships and caravans: surface only ---
    view.layer = L.UNDER
    marks_under = view._flat_mover_markers()
    view.layer = L.SURFACE
    marks_surface = view._flat_mover_markers()
    assert not any(m[3] == M.SHAPE_HULL for m in marks_under), (
        "ships rendered below ground")
    print("  ok    ships: none below (surface traffic is world-dependent, "
          "so only the absence below is asserted)")

    # --- realm/region names: surface only ---
    view.layer = L.UNDER
    labels_under = view._map_labels(0)
    view.layer = L.SURFACE
    labels_surface = view._map_labels(0)
    assert not labels_under, f"{len(labels_under)} realm labels below"
    assert labels_surface, "the surface view lost its realm labels"
    print("  ok    realm names: none below, present above")

    print("\nUNDER NO-LEAK TEST PASSED")
finally:
    root.destroy()
