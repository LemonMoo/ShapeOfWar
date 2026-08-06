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

    # --- weather / attack frontier / road projects: surface only ---
    view.attack_mode = "attack"     # arm the frontier like a real attack
    view._attack_frontier = [world.regions[0]]
    view.layer = L.UNDER
    lines_under = view._map_lines(2, 4.0)
    labels_under = view._map_labels(1)
    view.layer = L.SURFACE
    lines_surface = view._map_lines(2, 4.0)
    labels_surface = view._map_labels(1)
    view.attack_mode = None
    view._attack_frontier = []
    assert len(lines_under) == 0, f"{len(lines_under)} surface lines below"
    assert not labels_under, f"{len(labels_under)} surface labels below"
    print("  ok    weather/attack/road lines and labels: none below")

    # --- the under region panel does not name the surface biome above it ---
    from app.world import layers as L2
    under_reg = next(r for r in world.regions if L2.is_under(r)
                     and r.faction_idx >= 0)
    view.selected_region = under_reg
    view.layer = L.UNDER
    view._rebuild_selection_panel()
    page_texts = []
    for item in view._page.canvas.find_all():
        if view._page.canvas.type(item) == "text":
            page_texts.append(str(view._page.canvas.itemcget(item, "text")))
    joined = " | ".join(page_texts)
    assert "Cavern galleries" in joined, (
        f"the under region panel does not say what the rock is: {joined[:200]}")
    print("  ok    the under region panel reads 'Cavern galleries'")

    # --- the surface fog mask never composites below (the GL map's leak) ---
    view.layer = L.UNDER
    view._ensure_fog_overlay()
    assert not view._fog_overlay_active(), (
        "surface fog composited over the under raster -- the GPU map showed "
        "the surface's revealed/unrevealed patchwork below ground")
    view.layer = L.SURFACE
    assert view._fog_overlay_active(), "surface fog missing above ground"
    print("  ok    surface fog mask: never below (canvas AND GL), only above")

    # --- terrain legend: surface only ---
    view.layer = L.UNDER
    view.mode = "political"
    legend = tk.Canvas(root, width=200, height=200)
    view._draw_terrain_legend(legend)
    assert len(legend.find_all()) == 0, "terrain legend drawn below ground"
    view.layer = L.SURFACE
    view._draw_terrain_legend(legend)
    assert len(legend.find_all()) > 0, "terrain legend missing above ground"
    print("  ok    terrain legend: none below, drawn above")

    # --- alert jumps: ignored below ground ---
    node = next(s for s in world.settlements if s.faction_idx == 0)
    view.layer = L.UNDER
    view.selected_settlement = None
    view._jump_to_alert_node(node)
    assert view.selected_settlement is None, (
        "alert jump opened a surface settlement panel below ground")
    print("  ok    alert jumps: ignored below (surface data stays up top)")

    # --- descending clears the surface selection panels ---
    view.layer = L.SURFACE
    view.selected_settlement = node
    view.selected_village = None
    view.selected_commander = None
    view.selected = world.factions[0]
    view.toggle_layer()
    assert view.layer == L.UNDER
    assert view.selected_settlement is None and view.selected is None, (
        "a surface selection survived the descent and redrew its panel "
        "over the cave map")
    print("  ok    descending clears the surface selection panels")

    print("\nUNDER NO-LEAK TEST PASSED")
finally:
    root.destroy()
