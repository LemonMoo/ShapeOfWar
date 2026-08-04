"""Macro world-map screen.

Renders the procedurally generated world as a raster (a Pillow image cropped to
a viewport and scaled with nearest-neighbor, so borders stay crisp). Three
zoom levels, click-to-drill-down:
  - World: click a country to select it, click it again to zoom into...
  - Country: shows its regions + settlements. Click a region to select it,
    click it again to zoom into...
  - Region ("village view"): shows its villages, linked by simple dirt roads,
    plus its settlements. Click a village for its farm-output stats.
Click outside the zoomed region (or the Back button) to zoom back out one
level at a time. Regions are the future unit of control for territory
reassignment.
"""
import math
import time
import contextlib
import tkinter as tk

import numpy as np
from PIL import Image, ImageTk

from app.core import audio
from app.core import clock
from app.ui import parchment
from app.ui import theme
from app.ui import widgets
from app.world.world_map import Stance
from app.world import weather as weather_mod
from app.world.worldgen import OCEAN, road_chains
from app.world.territory import bordering_regions, naval_reachable_regions
from app.world.resources import RESOURCES
from app.world import resources
from app.world import turn_runner
from app.world import layers
from app.world import diplomacy
from app.world import construction
from app.world import trade
from app.world import expansion
from app.world import commander
from app.world import buildings
# Sector names as the player sees them, shared with the build menu so the two
# surfaces can never drift into calling the same thing different names.
from app.ui.build_menu import SECTOR_LABEL
from app.ui import gl_flatmap
from app.ui.gl_flatmap import (SHAPE_CIRCLE, SHAPE_TRIANGLE, SHAPE_SQUARE,
                               SHAPE_DIAMOND, SHAPE_HULL)
from app.world import wrap
from app.world.nation import is_eliminated, ruler_label
from app.ui.compendium import CompendiumWindow
from app.ui import build_menu

_FLASH_COLOR = (255, 236, 120)   # bright gold — region gained
_FLASH_FAIL_COLOR = (232, 74, 62)  # bright red — region attack failed
_FLASH_DURATION = 2.2            # seconds
_FLASH_FREQ = 1.8                # blink cycles per second

_LABEL_FONT = ("Segoe UI", 8, "bold")

# Free camera (drag-pan / wheel-zoom).
_DRAG_THRESHOLD_PX = 4   # movement past this on a press+move counts as a drag, not a click
_ZOOM_STEP = 0.9         # view-span multiplier per wheel notch
_MIN_ZOOM_CELLS = 6      # closest allowed zoom (world-cells across the short viewport edge)
_VILLAGE_REVEAL_SPAN = 40   # world-cells across the shorter viewport edge -- below
                            # this, villages become visible/clickable within region
                            # view (see MapView._villages_visible). Was previously a
                            # separate click-triggered "village view" mode; region
                            # side (~14 cells average) plus room for a couple of
                            # neighboring regions' worth of villages (~7-10 cells
                            # apart) landed on this as a reasonable starting point --
                            # tune by feel if it reveals villages too early/late.

# The world driver's frame period (see MapView._on_frame). ~60fps: this one
# loop both steps the world AND draws the moving map, so it has to run at the
# rate travel is meant to look smooth at. The world's share of each frame is
# still bounded (see _budget_ms/_MAX_BUDGET_MS) and the standing render cost is
# cached across pans (see _sync_flatgl), so most of these frames are cheap.
_FRAME_MS = 16

# Ceiling on how much of a frame the world may take, however high the speed.
# Past this the map stops feeling like something you are watching and starts
# feeling like something that is thinking. A world that cannot keep up at 4x
# runs slower instead -- and says so (see clock.keeping_up).
_MAX_BUDGET_MS = 22.0

# ...and the least. A day must always creep forward, or a world whose cost
# estimate has collapsed could stall entirely.
_MIN_BUDGET_MS = 1.5

# How often the panels are rebuilt while time runs. A day used to end with a
# full teardown and rebuild of the realm/resource/trade panels, which at a day
# every couple of seconds would be a permanent flicker -- so the heavy rebuild
# is throttled to this, and only the cheap readouts (the date, the treasury
# figure) update every day.
_PANEL_REFRESH_MS = 900

# --- the underworld (see app/world/layers.py) ---------------------------------
# Solid rock is the BACKGROUND down here, not the exception: the layer exists
# only under the mountains, so most of the view is stone and the network is
# what you are looking for in it. Warm light against cold rock, which is also
# how anybody has ever drawn a mine.
_UNDER_ROCK = (30, 28, 32)        # unexcavated
_UNDER_ABOVE_LAND = (44, 42, 46)  # rock that has open country above it
_UNDER_KIND_RGB = {
    "cavern": (206, 168, 84),
    "gallery": (140, 100, 46),
    "water": (52, 96, 150),
    "chasm": (8, 8, 12),
}
_UNDER_GATE_RGB = (226, 92, 70)

_OCEAN_DEEP = (18, 30, 58)
_OCEAN_SHALLOW = (44, 74, 120)
_LAKE_RGB = (48, 92, 140)      # inland lake water (shown in every map mode)

# Fog of war (see app/world/vision.py) — unexplored land/sea, world view only.
_FOG_HIDDEN_RGB = (7, 9, 14)

# Per-region lightness offsets so neighboring regions of a faction read apart.
_REGION_SHADES = [-0.12, 0.10, 0.22, -0.04, 0.15, 0.02, 0.28, -0.09, 0.06, 0.19]


def _catmull_rom(points, subdivisions):
    """A CENTRIPETAL Catmull-Rom spline through `points`. It passes THROUGH
    every one of them rather than being pulled towards them, which is what a
    road wants: the cells are where the road actually goes, the curve is only
    how it gets between them.

    Centripetal (the alpha=0.5 knot spacing below), not the uniform version.
    Uniform Catmull-Rom overshoots wherever the control points turn tightly,
    and a road network is full of tight turns -- one three-point dirt track
    that doubled back on itself swung SIX AND A HALF CELLS clear of its own
    route, drawing a road through country it does not go anywhere near.
    Centripetal parameterisation is provably free of cusps and
    self-intersections, and brought that same case under a fifth of a cell.

    The ends are duplicated so the first and last spans are drawn rather than
    dropped for want of a neighbour."""
    if len(points) < 3 or subdivisions < 2:
        return list(points)
    ext = [points[0]] + list(points) + [points[-1]]
    out = [points[0]]
    for i in range(len(ext) - 3):
        p0, p1, p2, p3 = ext[i:i + 4]

        def knot(t, a, b):
            d = math.hypot(b[0] - a[0], b[1] - a[1])
            return t + (d ** 0.5 or 1e-4)

        t0 = 0.0
        t1 = knot(t0, p0, p1)
        t2 = knot(t1, p1, p2)
        t3 = knot(t2, p2, p3)
        for step in range(1, subdivisions + 1):
            t = t1 + (t2 - t1) * step / subdivisions

            def lerp(a, b, ta, tb):
                if tb == ta:
                    return a
                f = (t - ta) / (tb - ta)
                return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)

            a1 = lerp(p0, p1, t0, t1)
            a2 = lerp(p1, p2, t1, t2)
            a3 = lerp(p2, p3, t2, t3)
            b1 = lerp(a1, a2, t0, t2)
            b2 = lerp(a2, a3, t1, t3)
            out.append(lerp(b1, b2, t1, t2))
    return out


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb(r, g, b):
    clamp = lambda v: max(0, min(255, int(v)))
    return (clamp(r), clamp(g), clamp(b))


# Movement animation. A wall-clock window rather than a fixed number of frames,
# so a heavy world animates in the same time a light one does -- it just draws
# fewer frames doing it.
#
# Under the turn-based build this was a REPLAY: the turn resolved, then movers
# slid over their day's travel in 0.75s and stood still until the next button
# press. In a running world that is worse than teleporting, because the
# stop-start is now on a rhythm you can watch -- three quarters of a second
# moving, a second and a half standing. So the window is the DAY: an army
# animating over exactly as long as the day takes is an army that never stops
# moving, and the interpolation stops being a flourish and becomes how travel
# looks (see MapView._move_anim_seconds).
#
# This one still applies when the world is not running on a clock at all --
# stepping a day by hand with E, where there is no day-length to match.
_MOVE_ANIM_SECONDS = 0.75
# At 4x a day goes by in 0.6s, and past that the sliding reads as jitter rather
# than as travel -- so a fast clock stops shortening the window and lets the
# movers simply cover more ground per day instead.
_MOVE_ANIM_MIN_SECONDS = 0.45


def _path_point(path, frac, world_w):
    """Continuous position `frac` (0..1) of the way along an ordered cell
    path. Wrap-aware on x: a route crossing the seam steps from x=1099 to x=0,
    and interpolating that naively sends the caravan the long way round the
    entire world."""
    n = len(path)
    if n == 1:
        return (float(path[0][0]), float(path[0][1]))
    t = max(0.0, min(1.0, frac)) * (n - 1)
    i = min(n - 2, int(t))
    f = t - i
    (ax, ay), (bx, by) = path[i], path[i + 1]
    x = ax + wrap.dx_wrap(ax, bx, world_w) * f
    return (wrap.wrap_x(x, world_w), ay + (by - ay) * f)


class _PathWalk:
    """Slides a mover along its own route between two fractions of it."""

    def __init__(self, path, f0, f1, world_w):
        self.path, self.f0, self.f1, self.w = path, f0, f1, world_w

    def __call__(self, t):
        return _path_point(self.path, self.f0 + (self.f1 - self.f0) * t, self.w)


class _Lerp:
    """Straight line between two cells -- the fallback for a mover with no
    route to replay (a ship that was moved rather than sailed)."""

    def __init__(self, a, b, world_w):
        self.a, self.w = a, world_w
        self.dx = wrap.dx_wrap(a[0], b[0], world_w)
        self.dy = b[1] - a[1]

    def __call__(self, t):
        return (wrap.wrap_x(self.a[0] + self.dx * t, self.w),
                self.a[1] + self.dy * t)


class _GLColors(dict):
    """'#rrggbb' -> (r, g, b) floats in 0..1, memoised.

    The GPU map rebuilds its overlays every frame from the same handful of
    palette constants the canvas draws with, and GL wants floats. Converting
    on the fly turned out to be the one genuinely hot line in that rebuild --
    thousands of road segments a frame, each parsing the same six hex digits."""

    def __missing__(self, key):
        value = tuple(c / 255.0 for c in _hex_to_rgb(key))
        self[key] = value
        return value


_GL_RGB = _GLColors()
_GL_LABEL_COLOR = (0.96, 0.96, 0.96)
_GL_VILLAGE_LABEL_COLOR = (0.84, 0.86, 0.88)
_GL_PLAYER_COMMANDER = (0.90, 0.52, 1.0)   # the orchid the flat map uses

# Painting order for road tiers: low first, so a stone road always lies over
# the dirt track it was paved from rather than whichever happened to be later
# in the region's segment list. Sea lanes go on top of both -- they are drawn
# dashed and thin, and a lane hidden under a road reads as a broken lane.
_ROAD_DRAW_ORDER = {"dirt": 0, "stone": 1, "sea": 2}

# --- Weather on the map (weather phase 5) -----------------------------------
# Weather is per-REGION and changes every turn, so it cannot live in the
# terrain raster: that image is cached and only rebuilt when ownership
# changes, and redrawing it once a turn for a handful of storms would be
# absurd. It is drawn instead from the two things both renderers already
# share -- a coloured outline around the region (_map_lines) and a label at
# its centre (_map_labels). No new primitive, no per-cell work, and the Tk
# canvas and the GPU map cannot disagree about it.
#
# Drought is included here even though it does nothing to travel or battle,
# because it is the one that ruins your HARVEST -- it is arguably the event a
# player most needs to see coming, and leaving it off the map because it has
# no combat effect would be reading the mechanics rather than the game.
_WEATHER_MAP_COLOR = {
    "drought": "#d1922f",    # dusty gold
    "storm": "#4d7fb5",      # rain blue
    "blizzard": "#b9d4e8",   # pale ice
    "fog": "#9aa3ad",        # flat grey
}
# Kind first, severity second: the glyph says WHAT, the ring says how bad.
_WEATHER_GLYPH = {
    "drought": "\u2600",     # sun
    "storm": "\u26c8",       # cloud with lightning
    "blizzard": "\u2744",    # snowflake
    "fog": "\u2248",         # approximately-equal, which reads as haze
}


def _lighten(rgb, amt):
    r, g, b = rgb
    return (r + (255 - r) * amt, g + (255 - g) * amt, b + (255 - b) * amt)


def _shade(rgb, d):
    """Lighten (d>0) or darken (d<0) an RGB tuple."""
    if d >= 0:
        return _lighten(rgb, d)
    f = 1 + d
    return (rgb[0] * f, rgb[1] * f, rgb[2] * f)


def _blend(a, b, t):
    """Linear-interpolate from RGB `a` toward `b` by fraction `t` (0=a, 1=b)."""
    return tuple(a[j] + (b[j] - a[j]) * t for j in range(3))


def _ramp(t, stops):
    t = max(0.0, min(1.0, t))
    for i in range(len(stops) - 1):
        t0, c0 = stops[i]
        t1, c1 = stops[i + 1]
        if t <= t1:
            f = (t - t0) / (t1 - t0) if t1 > t0 else 0
            return _rgb(*(c0[j] + (c1[j] - c0[j]) * f for j in range(3)))
    return _rgb(*stops[-1][1])


_FERT_STOPS = [(0.0, (120, 92, 52)), (0.5, (182, 165, 74)), (1.0, (47, 150, 74))]
_ELEV_STOPS = [(0.0, (58, 104, 66)), (0.35, (150, 148, 88)),
               (0.7, (120, 92, 66)), (1.0, (238, 238, 240))]


def _fert_rgb(f):
    return _ramp(f, _FERT_STOPS)


def _elev_rgb(e):
    return _ramp(e, _ELEV_STOPS)


# Flat per-biome / per-climate colors for the "Biome"/"Climate" view modes —
# these are the literal "sub-maps" for the resource economy in
# app/world/resources.py (each biome/climate drives what a region yields).
_BIOME_COLORS = {
    "mountain": (150, 148, 150),
    "highland": (122, 126, 104),   # foothills: stone greying into grass
    "forest": (40, 110, 58),
    "taiga": (46, 88, 76),         # colder, bluer conifer
    "jungle": (26, 128, 62),       # hotter, more saturated green
    "plains": (168, 178, 84),
    "steppe": (186, 176, 116),     # dry temperate grass, paler than plains
    "savannah": (198, 166, 78),    # warm grass shading toward the desert
    "coastal": (94, 168, 176),
    "desert": (206, 178, 110),
    "tundra": (176, 184, 186),     # pale, cold and nearly bare
    "swamp": (78, 96, 66),
}
_CLIMATE_COLORS = {
    "temperate": (94, 156, 96),
    "arid": (196, 154, 82),
    "cold": (156, 190, 214),
    "humid": (70, 132, 122),
}
_NO_DATA_RGB = (40, 44, 52)   # ocean / unclassified cells in biome & climate modes

# UNCLAIMED land (see app/world/worldgen.py) in the political view — a muted
# neutral tone, no faction owns it so it can't use a faction color. Tinted
# toward a dull rust the more strongly its wildland garrison is defended, as
# a quick "how dangerous to claim" read at a glance.
_UNCLAIMED_RGB = (64, 60, 46)
_UNCLAIMED_DANGER_RGB = (92, 46, 40)
_WILDLAND_DANGER_REF = 150.0   # wildland_strength that reads as "fully dangerous"


def _biome_rgb(biome):
    return _BIOME_COLORS.get(biome, _NO_DATA_RGB)


# Basic topographical texture on the political map itself, not just the
# separate Biome view mode: forests and mountains blend a bit of their
# biome-mode reference color into the political base tint (see
# _precompute_colors), so terrain reads at a glance without losing the
# faction-color-is-primary political view. Other biomes (plains/coastal/
# desert/swamp) are left alone — subtler and less useful to distinguish here.
# How strongly each biome tints the political map's faction colour.
#
# Only forest and mountain used to tint at all -- that predates the 12-biome
# overhaul, so ten of the twelve rendered as flat faction colour and the whole
# new map was invisible on the view people actually play on. A desert and a
# jungle looked exactly alike.
#
# The faction colour still has to win: this is the POLITICAL map, and who owns
# a place is what it is for. So the strengths are graded by how much a biome
# needs saying rather than applied evenly -- the extremes (desert, jungle,
# mountain, tundra) tint hard because they change what a region is worth and
# how an army moves through it, while plains and coastal barely tint at all
# because "ordinary green country" is the baseline everything else reads
# against. Steppe and savannah sit between: dry, but not desert.
_POL_BIOME_TINT = {
    "mountain": 0.42,
    "desert": 0.42,
    "jungle": 0.40,
    "forest": 0.38,
    "tundra": 0.38,
    "swamp": 0.36,
    "taiga": 0.34,
    "highland": 0.30,
    "savannah": 0.28,
    "steppe": 0.24,
    "coastal": 0.18,
    "plains": 0.12,
}

# Symbols layered on top of the color tint above (political mode only) —
# color alone doesn't read clearly enough at a glance, especially at this
# map's size. See _draw_terrain_symbols/_draw_terrain_legend.
_FOREST_SYMBOL_FILL = "#173d20"
_FOREST_SYMBOL_OUTLINE = "#0a1f10"
_MOUNTAIN_SYMBOL_FILL = "#eef0f2"
_MOUNTAIN_SYMBOL_OUTLINE = "#585860"
_TERRAIN_SYMBOL_SCREEN_SPACING = 26   # target px between sampled points on screen
_TERRAIN_SYMBOL_MIN_WORLD_SPACING = 3   # never sample closer than this many world cells
_TERRAIN_SYMBOL_MAX_COUNT = 400   # hard cap on sampled points regardless of visible
                                   # area -- see _draw_terrain_symbols for why this
                                   # is needed on top of the spacing floor above


def _climate_rgb(climate):
    return _CLIMATE_COLORS.get(climate, _NO_DATA_RGB)


# River cells are baked directly into the terrain raster (_precompute_colors,
# same treatment as lake_cells), not drawn as a separate vector line on top —
# a muted fresh-water blue, distinct from but close in tone to lake/ocean, so
# a river reads as part of the terrain instead of a decal floating over it.
_RIVER_RGB = (64, 112, 152)

# Settlement/village marker styling (drawn as canvas shapes — no art
# assets). "base" is a world-cell-unit size, not a screen-pixel one --
# marker radius scales with the current zoom level (see _marker_radius)
# instead of staying a fixed pixel size, which used to mean these never
# got any easier to see zoomed in, and looked identically tiny at every
# zoom level in Village view (the deepest, most-zoomed-in level) as
# everywhere else.
# Marker sizes, in world-cell units, scaled to screen by _marker_radius.
# Raised across the board: at the old sizes a town or village was a few
# pixels of nothing until you were almost on top of it, and the map reads by
# its settlements. The RELATIVE ordering is what carries the kind
# (city > castle > town > village), so they all move together.
_SETTLE_STYLE = {
    "city":   {"fill": "#f2e9c9", "outline": "#4a4230", "base": 0.58},
    "castle": {"fill": "#c9ccd6", "outline": "#3a3f4c", "base": 0.47},
    "town":   {"fill": "#d9b98a", "outline": "#4a3a24", "base": 0.38},
}
_VILLAGE_STYLE = {"fill": "#c9a06a", "outline": "#4a3418", "base": 0.28}
_MARKER_MIN_R = 4.5    # never smaller than this, however far zoomed out
_MARKER_MAX_R = 26.0   # never larger than this, however far zoomed in --
                        # raised so a settlement actually reaches a full,
                        # readable size close in rather than topping out
                        # while there is still plenty of screen for it
# Local roads (village/settlement network within a region — see
# _place_villages_for_region in app/world/worldgen.py): Dirt for a road
# touching a village, brown; Stone for a road linking two settlements, gray.
_DIRT_ROAD_COLOR = "#8a6f4a"
_STONE_ROAD_COLOR = "#9a9ba3"
_BRIDGE_COLOR = "#6e4326"   # a stone road's river crossing, recolored like timber decking

# A road is cut INTO the ground, not painted on top of it. Each one is drawn
# twice: a darker, wider band first -- the shadow in the cutting, the churned
# verge, the ditch -- and the surface over the middle of it. That reads as
# something dug rather than a coloured line laid across the grass, and it
# costs one extra polyline per road rather than any per-cell work.
_ROAD_CUT_DARKEN = 0.45     # how much darker the cut is than the surface
_ROAD_CUT_WIDTH = 2.1       # how much wider, as a multiple of the surface

# ...and a dirt track is a worn surface, not a line. Drawn broken, so the dark
# cut shows through in patches along its length: ruts, puddles, bare earth. A
# stone road is laid and stays laid, so it runs solid.
_DIRT_SURFACE_DASH = (5, 4)
_DIRT_SURFACE_NARROW = 0.62   # the surface is narrower than the cut it sits in


def _darken(hex_color, amount):
    r, g, b = _hex_to_rgb(hex_color)
    return "#%02x%02x%02x" % (int(r * (1 - amount)), int(g * (1 - amount)),
                              int(b * (1 - amount)))
_TRADE_LAND_COLOR = "#7c5f26"   # long-haul trade road — dark bronze, recedes into the map
_TRADE_SEA_COLOR = "#557c8c"    # dark shipping-lane blue, dotted like a nautical chart
_CURRENT_COLOR = "#5ee0c8"      # cool cyan-teal -- distinct from both trade-lane
                                # blue and the ocean itself, reads as "current
                                # flow," not "another shipping lane"
_CURRENT_ARROW_COLOR = "#9df5e4"  # brighter version for the direction chevrons
# A route currently carrying a caravan is redrawn on top in a bright,
# saturated version of its color — thicker than the dim static line — so an
# active trade route reads at a glance, not just its tiny marker.
_ACTIVE_ROUTE_LAND_COLOR = "#ffcf5c"
_ACTIVE_ROUTE_SEA_COLOR = "#a4ecff"
# A land route still under construction (see app/world/trade.py's
# TradeRouteProject) — pale gold, matching the castle-under-construction
# marker's color, distinct from both the dim static line (not built yet)
# and the bright active-caravan highlight (nothing can use it yet).
_TRADE_ROUTE_CONSTRUCTION_COLOR = "#f2e9c9"
# Moving caravan/ship markers — big, glowing (a dim halo behind a bright
# core), so an active caravan is unmistakable even zoomed far out.
# Caravan markers. The map shows EVERY faction's caravans (subject to fog), so
# your own trade and a neighbor's passing through look identical unless they're
# styled apart -- which made it genuinely impossible to tell whether a caravan
# arriving at a city was your deal or someone else's. Your own are drawn bright
# and full-size; everyone else's are smaller and muted.
_CARAVAN_STYLE = {"fill": "#fff3c4", "outline": "#5a4318", "r": 6, "glow": "#ffcf5c"}
_SEA_CARAVAN_STYLE = {"fill": "#c8f5ff", "outline": "#154a5c", "r": 6, "glow": "#5fd0ff"}
_FOREIGN_CARAVAN_STYLE = {"fill": "#8d8261", "outline": "#3d3a2a", "r": 4, "glow": "#6b6244"}
_FOREIGN_SEA_CARAVAN_STYLE = {"fill": "#6f8f9c", "outline": "#22333a", "r": 4, "glow": "#4d6470"}
# River barges — a distinct green-teal from the sea's blue, so a boat working a
# river inland doesn't read as an ocean ship that has somehow sailed ashore.
_RIVER_CARAVAN_STYLE = {"fill": "#bff5e2", "outline": "#14513f", "r": 6, "glow": "#4fd6a8"}
_FOREIGN_RIVER_CARAVAN_STYLE = {"fill": "#6f9c8a", "outline": "#223a33", "r": 4, "glow": "#4d7064"}

# Domestic shipments (a faction moving goods around inside its own realm).
# Smaller and quieter than foreign caravans on purpose: they're far more
# numerous, so they read as background bustle rather than headline events.
# Commander (app/world/commander.py) — a bright orchid diamond, deliberately
# unlike any settlement/caravan color so the player's own unit never gets
# confused with anything else on the map. THE PLAYER'S ONLY: rival commanders
# are drawn in their own realm's colour instead (see _draw_commanders), so the
# marker identifies whose army it is.
_COMMANDER_STYLE = {"fill": "#e685ff", "outline": "#4a1a5c", "r": 7}
_SHIP_STYLE = {"fill": "#c9a86a", "outline": "#5c3f1a", "r": 6}
# Above this many villages in a region, skip name labels (village view) so it
# doesn't turn into unreadable text soup.
# --- UI layout ---------------------------------------------------------------
# The map canvas fills the window and these are overlaid on it, each foldable
# down to a slim edge tab (see _apply_panel_layout).
_RESOURCE_GROUP = {
    "Crops": "Food", "Food Products": "Food", "Fishing": "Food",
    "Forestry": "Industry", "Mining": "Industry", "Manufactured Goods": "Industry",
    "Luxury Goods": "Luxury", "Livestock": "Livestock",
    # Mushrooms and cave fish are food; the muck they grow on is not, but it
    # belongs beside them rather than in a group of its own -- the whole
    # category exists to feed a hold.
    "Subterranean": "Food",
}
_RESOURCE_GROUP_ORDER = ("Food", "Industry", "Luxury", "Livestock", "Other")
# Goods a realm dies without. Low stock of these is promoted above the groups,
# so a firewood crisis is visible without expanding anything.
_SURVIVAL_RESOURCES = {"Firewood", "Fodder", "Bread", "Salted Meat", "Smoked Fish",
                       "Cheese", "Clothes"}
_LOW_STOCK_THRESHOLD = 200

_ALERTS_PANEL_W = 260
_TREASURY_W = 300
_LEFT_PANEL_W = 200
_RIGHT_PANEL_W = 360
_EDGE_TAB_W = 14

_VILLAGE_LABEL_LIMIT = 24

# Viewport culling (see MapView._visible_point / _visible_bbox / _visible_pts).
# Generous enough that nothing whose *body* is on screen is ever dropped
# because its anchor point sits just outside: a marker can be _MARKER_MAX_R
# across, a caravan draws a glow ring at 2.4x its radius, and settlement /
# village names hang ~15px below the anchor.
_CULL_PAD_POINT = 48   # point features (markers + their labels/badges)
_CULL_PAD_LINE = 32    # segments and polylines (roads, routes)

# Village names are two text items each (shadow + fill), and text is the most
# expensive canvas item there is. Only label villages once the camera is close
# enough that the names are actually readable rather than overlapping soup.
_VILLAGE_LABEL_MIN_SCALE = 2.2   # screen px per world cell

# Below this badge radius (px) the alert "!" glyph is dropped and only the
# coloured warning triangle is drawn -- see _draw_alert_badge.
_ALERT_BADGE_GLYPH_MIN_R = 7.0

# Dirt roads only draw once the camera is at least this close (screen px per
# world cell) -- roughly a 55-cell-wide viewport, i.e. about the point where a
# single region fills the screen and its tracks become worth reading. Tuned by
# measurement rather than feel: on a 105-village realm it is the difference
# between ~1000 and ~750 canvas items at the wide end of village view. Lower it
# to bring dirt roads in earlier, at a proportional cost per frame.
# Zoom scale (screen px per world cell) at which dirt roads start drawing.
# Lowered so the local network appears while the region is still fully in
# view -- at 20 you had to be close enough that you could no longer see where
# a road was going, which is most of what a road tells you.
_DIRT_ROAD_MIN_SCALE = 13.0


def _fmt_amount(n):
    """Compact number formatting for resource amounts (12345 -> '12.3k').

    Small numbers go through round() rather than str() so a float that has
    picked up binary-representation dust somewhere upstream reads as "44"
    rather than "44.20000000000000045". Stocks are meant to be whole units
    and the economy keeps them that way (see resources.settlement_needs on
    why a need must be rounded before it is subtracted), but a display has
    no business rendering seventeen decimals whatever arrives -- this is the
    backstop, not the fix."""
    if n >= 10000:
        return f"{n / 1000:.0f}k"
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(int(n)) if float(n).is_integer() else f"{n:.1f}"


def _format_resources(res):
    """'Grain 64k · Iron 21k · ...', ordered by tier then name, for a
    faction/region/settlement's resource dict."""
    if not res:
        return "None yet."
    order = sorted(res.keys(), key=lambda r: (RESOURCES.get(r, {}).get("tier", 9), r))
    return " · ".join(f"{r} {_fmt_amount(res[r])}" for r in order if res[r])


def _resource_shortfall(nation, cost, world):
    """{resource: amount still missing} for whichever of `cost`'s resources
    the nation can't currently cover in full — empty once it can afford
    all of it. Mirrors construction.can_afford's own two-way split: a
    settlement-storage resource (Phase 12: includes Logs/Stone/Iron; the
    Currency overhaul added Gold to this bucket too, no longer a separate
    treasury) summed across the faction's settlements, anything else from
    the old shared pool."""
    res = nation.stats.get("resources", {})
    missing = {}
    for resource, amount in cost.items():
        if resource in resources._SETTLEMENT_STORAGE_RESOURCES:
            have = construction._faction_settlement_stock(nation, resource, world)
        else:
            have = res.get(resource, 0)
        if have < amount:
            missing[resource] = amount - have
    return missing


class MapView(tk.Frame):
    def __init__(self, master, world, on_attack, on_end_turn,
                on_wildland_claim=None, on_turn_settled=None):
        super().__init__(master, bg=theme.BG)
        self.on_attack = on_attack
        self.on_end_turn = on_end_turn
        self.on_wildland_claim = on_wildland_claim
        # Called (main thread, no args) once a background turn has finished
        # settling -- after refresh() and the move animation have started, so
        # App can flush anything it deferred while the turn was in flight (see
        # App._on_faction_eliminated). Optional: dev harnesses that build a
        # MapView standalone have nothing that needs the hook.
        self.on_turn_settled = on_turn_settled
        # The world clock and the thing that works off what it owes. Time
        # starts PAUSED: a world that begins running the moment the map opens
        # would spend the player's first look at it doing things.
        self.clock = clock.Clock(speed=clock.PAUSED)
        self.clock.pause_reason = None
        self.runner = turn_runner.TurnRunner(world)
        self._turn_pending = None    # (before_snapshot, prev_year, movement_snapshot)
        self._last_frame = time.monotonic()
        # A continuous count of days demanded, advanced every frame at the
        # clock's own demand rate (see _advance_world). This -- not wall time --
        # paces the movement slide, so a mover's travel is locked to the world
        # clock and the seam between one day's slide and the next vanishes.
        # Never capped or dropped: it is a display clock, not the sim's.
        self._sim_days = 0.0
        self._frame_id = None
        self._last_panel_refresh = 0.0
        # What a day of this world costs, learned rather than assumed -- see
        # _budget_ms. Seeded at the runner's own slice budget so the very first
        # day is paced sensibly before anything has been measured.
        # WHICH LAYER IS BEING LOOKED AT. One piece of state, deliberately:
        # selection, the raster, the click handler and the panels all read
        # this, and the moment there are two answers to "where am I" it gets
        # patched into twenty places.
        self.layer = layers.SURFACE
        self._px_under = None           # underworld raster, built on demand
        self._day_ms_estimate = 0.0
        self._day_started = 0.0
        self.selected = None            # selected faction (world view)
        self.zoom_faction = None        # faction we've zoomed into (region view --
                                         # villages become visible/clickable once
                                         # zoomed in close, see _villages_visible)
        self.selected_region = None
        self.selected_settlement = None
        self.selected_village = None
        self.selected_commander = None
        self.commander_move_mode = None   # armed Commander awaiting a destination click
        self.mode = "political"
        self.show_currents = False   # opt-in overlay -- see _draw_currents
        self._img = None
        self._place = (0, 0, 1)         # vx0, vy0, scale
        # Per-frame camera constants, refreshed once at the top of render()
        # and read by world_to_screen()/the _visible_* culling helpers.
        # Hoisted out of world_to_screen specifically because that runs
        # hundreds-to-thousands of times a frame and used to call
        # canvas.winfo_width() on every single one -- a full Tk round-trip
        # per coordinate conversion, for a value that cannot change within
        # a frame.
        self._canvas_wh = (1, 1)
        self._view_center_x = 0.0
        self._base_img = None           # cached full-grid PIL image
        self._fog_overlay_img = None    # cached fog mask ("L" image) — see _ensure_fog_overlay
        self._fog_key = None
        self._base_key = None           # signature of what _base_img depicts
        self._anim_id = None
        self._px_pol = None             # None until the first _precompute_colors -- see
                                         # _update_dirty_colors' fallback

        # Free camera (drag-pan / wheel-zoom): independent of the click-
        # driven drill-down zoom (_start_zoom/_animate below), but writes
        # the same self.view/self.view_target so both can coexist.
        self._press_xy = None
        self._dragged = False
        self._animating = False
        self._drag_render_pending = False   # coalesces <B1-Motion> bursts into one
                                             # render() per idle tick -- see _on_drag

        # Attack-target picking: when not None, we've zoomed to the shared
        # border with `_attack_enemy` and clicking one of `_attack_frontier`
        # regions launches the battle for it.
        self.attack_mode = None
        self._attack_enemy = None
        self._attack_frontier = []

        # Castle placement: when not None, holds the (own-territory) region
        # the player is about to click a build site within.
        self.building_mode = None
        self._placement_hint_cells = None   # see _score_placement_hint

        # Post-battle border flash (see flash_region()): "success" (gold) for
        # a region gained, "failure" (red) for a failed attack.
        self._flash_region = None
        self._flash_outcome = "success"
        self._flash_start = 0.0
        self._flash_id = None
        self._bottom_msg_after_id = None
        self._compendium_window = None

        # Resources gained/lost on the turn just ended, keyed by resource
        # name (including "Gold"); shown alongside current totals in the
        # resource bar until the next End Turn overwrites them.
        self._resource_deltas = {}
        self._panel_cards_open = {}
        self._treasury_cards_open = {}

        # Year-rollover banner (see _show_year_banner): the player faction's
        # resource snapshot as of the start of the current in-game year,
        # diffed against the current snapshot the moment a new year begins
        # to build that banner's summary text. Reset every rollover.
        self._year_start_snapshot = {}
        self._year_start_population = 0
        self._year_banner_after_id = None

        # Alerts (settlement/village trouble the player should know about --
        # see resources.faction_alerts): recomputed once per turn (refresh())
        # and once per load (set_world()), NOT per render() -- render() can
        # fire many times a second during camera pan/zoom animation, and
        # faction_alerts walks every settlement/village, so recomputing it
        # there would reintroduce exactly the kind of per-frame cost the
        # earlier mid-zoom performance fix was about. _alert_node_ids is the
        # cached O(1) lookup _draw_settlements/_draw_villages actually use
        # for badges; _current_alerts is what the Alerts panel lists.
        self._current_alerts = []
        self._alert_node_ids = {}

        self._build_resource_bar()

        # The map is the base layer and fills the whole window; every panel is
        # an overlay placed on top of it. That's what lets a panel be folded
        # away and actually give the map back its area, instead of the old
        # fixed three-column split where the map only ever got the leftover
        # ~55% no matter what.
        self.canvas = tk.Canvas(self, bg=theme.CANVAS, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self._bind_map_events(self.canvas)
        # GPU flat map (see gl_flatmap.py): a second view of the same content
        # the canvas draws, swapped in for it automatically rather than by a
        # player toggle, the moment GL is confirmed available
        # (_ensure_flatgl/_activate_flatgl, called from render()). Falls back
        # to the canvas dynamically, every render(), if it ever reports failed
        # rather than only once at startup.
        self._flatgl = None
        self._flatgl_tried = False
        self._use_flatgl = False
        # Cached _map_lines/_flat_markers/(_map_labels+_flat_labels_extra)
        # output -- see _sync_flatgl's own comment on why rebuilding these
        # from scratch on every single pan/zoom frame (the previous
        # behaviour) is pure waste: none of that content depends on the
        # camera's PAN position at all (only _wrap_x, applied inside
        # gl_flatmap's own set_lines/set_markers/set_labels, cares about
        # that), and _flat_content_signature captures everything that
        # actually does change it.
        self._flat_content_sig = None
        self._flat_lines_cache = []
        self._flat_markers_cache = []
        self._flat_labels_cache = []
        # Movement animation state (see _start_move_animation /
        # _update_anim_positions). There is no separate animation timer any
        # more: the one world driver (_on_frame) advances these every frame.
        self._move_tracks = ()       # [(mover, t -> (x, y)), ...] for the day being shown
        self._anim_pos = {}          # id(mover) -> its drawn position this frame
        self._move_active = False    # did a mover's drawn position change this frame?
                                     # (the marker-rebuild signal; see _sync_flatgl)
        self._anim_day_base = 0.0    # _sim_days value the current slide started at
        self._last_slide_frac = None  # last frac drawn, so a settled slide stops redrawing
        self._move_seconds = _MOVE_ANIM_SECONDS   # hand-step (paused) window only
        self._move_t0 = 0.0                        # ...its wall-clock origin

        self.bottom_msg = tk.Label(self, text="", bg=theme.CANVAS, fg=theme.INK,
                                   font=("Segoe UI", 13, "bold"), padx=18, pady=10)

        # Year-rollover banner (see _show_year_banner) — a big top-of-screen
        # announcement, MMO-zone-reveal style, for the once-a-year moment a
        # new year actually begins; distinct from bottom_msg's small
        # one-line event banners above.
        self.year_banner = tk.Frame(self, bg=theme.CANVAS,
                                    highlightbackground=theme.ACCENT,
                                    highlightthickness=2)
        self.year_title_lbl = tk.Label(self.year_banner, text="",
                                       bg=theme.CANVAS, fg=theme.INK,
                                       font=("Segoe UI", 30, "bold"))
        self.year_title_lbl.pack(padx=32, pady=(16, 2))
        self.year_summary_lbl = tk.Label(self.year_banner, text="",
                                         bg=theme.CANVAS, fg=theme.MUTED,
                                         font=("Segoe UI", 11), justify="center",
                                         wraplength=560)
        self.year_summary_lbl.pack(padx=32, pady=(0, 18))

        # Background end-turn busy cover (see _run_end_turn): a full-frame
        # opaque overlay raised the instant End Turn is pressed. It covers
        # the canvas AND both side panels, which is what actually matters --
        # sitting on top absorbs every click meant for anything underneath,
        # so nothing can act on `world` while the worker thread owns it,
        # without having to gate each individual button/handler by hand.

        # Terrain legend for the GPU flat map (see _sync_flatgl): the
        # canvas draws its own corner legend as vector items every frame
        # (_draw_terrain_legend) -- a GL surface can't have Tk items drawn
        # over it that way, so this is the same box built ONCE as an
        # ordinary small Tk canvas and left alone; only shown/hidden per
        # frame, never redrawn, since its content never changes.
        lw, lh = 116, 56
        self._flat_legend = tk.Canvas(self, width=lw, height=lh, bg=theme.PANEL,
                                      highlightthickness=1,
                                      highlightbackground=theme.LINE)
        self._flat_legend.create_text(lw / 2, 10, text="LEGEND", fill=theme.MUTED,
                                      font=("Segoe UI", 7, "bold"))
        self._draw_forest_glyph(self._flat_legend, 16, 26, 7)
        self._flat_legend.create_text(32, 26, text="Forest", fill=theme.INK,
                                      font=("Segoe UI", 8), anchor="w")
        self._draw_mountain_glyph(self._flat_legend, 16, 46, 7)
        self._flat_legend.create_text(32, 46, text="Mountain", fill=theme.INK,
                                      font=("Segoe UI", 8), anchor="w")

        self._build_trade_log()
        self._build_alerts_panel()
        self._build_panel()
        self._build_treasury_panel()
        self._build_edge_tabs()
        self._left_collapsed = False
        self._right_collapsed = False
        self._apply_panel_layout()
        self.set_world(world)
        self._refresh_time_controls()
        # The world driver. Runs for the life of the view, paused or not: it is
        # what keeps the date, the speed buttons and the movement animation
        # honest even while nothing is advancing.
        self._frame_id = self.after(_FRAME_MS, self._on_frame)

    # --- world binding -----------------------------------------------------
    def set_world(self, world):
        self.world = world
        self._flat_content_sig = None   # force a rebuild -- see _sync_flatgl
        self.selected = None
        self.zoom_faction = None
        self.selected_region = None
        self.selected_settlement = None
        self.selected_village = None
        self.selected_commander = None
        self.commander_move_mode = None
        self.attack_mode = None
        self._attack_enemy = None
        self._attack_frontier = []
        self.building_mode = None
        self._placement_hint_cells = None
        self._flash_region = None
        if self._flash_id is not None:
            self.after_cancel(self._flash_id)
            self._flash_id = None
        self._hide_bottom_message()
        self._hide_year_banner()
        self.view = self._world_view_rect()
        self.view_target = list(self.view)
        self._base_img = self._base_key = None
        self._px_pol = None   # new world: force a full _precompute_colors rebuild, not a patch
        self._fog_overlay_img = None
        self._stop_move_animation()   # a slide from the previous world means
                                      # nothing in this one
        self._fog_key = object()   # never matches any real fog_version -> forces a rebuild
        self._precompute_colors()
        self._last_territory_version = getattr(self.world, "territory_version", 0)
        # Restore the view this world was last played in, and where the camera
        # was left. Both ride along on the world object, so they persist through
        # a save/load without touching the save schema.
        self._exit_ui()
        self._hide_prosperity_bar()
        self._hide_storage_bar()
        self._page_begin(None)
        self._panel_text("Click a faction to inspect it.", fg=theme.MUTED)
        self._page_end()
        self._resource_deltas = {}
        self._year_start_snapshot = self._current_resource_snapshot()
        self._year_start_population = self._current_population_total()
        self._update_resource_bar()
        self._update_turn_label()
        self._refresh_alerts()
        self.render()

    def refresh(self):
        """Recompute cached tile colors and panel text after the World's
        ownership data was mutated in place (e.g. a territory transfer),
        without resetting the camera/selection the way set_world() does.

        Recoloring only happens when region ownership actually changed
        (world.territory_version, bumped by territory.transfer_region)
        since the last time — most End Turn calls transfer no territory at
        all, so this used to be pure wasted work every single turn. And
        when it DOES need to recolor, _update_dirty_colors patches only the
        specific cells that changed (world._dirty_color_cells, also
        maintained by transfer_region) instead of _precompute_colors'
        full O(w*h) rebuild — once AI factions started claiming wildland
        as often as the player, a full-map recolor on every single one of
        those transfers became a real, noticeable per-turn cost spike."""
        from app.world import vision
        vision.recompute(self.world)
        territory_version = getattr(self.world, "territory_version", 0)
        if territory_version != getattr(self, "_last_territory_version", None):
            dirty = getattr(self.world, "_dirty_color_cells", None)
            self._update_dirty_colors(dirty or set())
            if dirty:
                dirty.clear()
            self._last_territory_version = territory_version
            # The precomputed pixel arrays just changed under it, so the
            # cached raster is stale and has to be thrown away -- but ONLY
            # then. This used to fire unconditionally, forcing render() to
            # rebuild the full ~22ms terrain image on EVERY panel refresh
            # (every 900ms while the clock runs), even on the overwhelming
            # majority of days that transfer no territory at all. That
            # needless rebuild was the periodic ~100ms frame spike behind the
            # "standing lag" in the region/world views. Selection- and
            # mode-change invalidation is not needed here: _ensure_base's own
            # cache key already captures both, so a changed selection rebuilds
            # the raster on its own without this.
            self._base_img = self._base_key = None
        self._rebuild_selection_panel()
        # Same reasoning as the treasury below: a build menu can be left open
        # across End Turn, and until this call it was a snapshot -- you could
        # start a Granary, end six turns watching nothing change, and only see
        # it built by closing and reopening the window.
        build_menu.refresh_open(self.winfo_toplevel())
        # Treasury is an in-game panel that can be left open across End Turn,
        # so it has to be rebuilt here to show the turn's new figures.
        self._refresh_treasury()
        if self.selected_commander is not None:
            self._show_commander(self.selected_commander)
        self._update_resource_bar()
        self._update_turn_label()
        self._refresh_alerts()
        self.render()

    def _color_context(self):
        """The per-faction/per-region color inputs _compute_cell needs --
        cheap (O(factions)+O(regions), not O(w*h)) so it's fine to
        recompute fresh on every call, full rebuild or incremental alike.

        Each region's shade VARIATION is keyed by the region's own stable
        id, not its position within f.meta["regions"] -- a region gained/
        lost elsewhere can shift every other region's list position, which
        used to shift their shade variation too even though their own
        ownership never changed. That's harmless for a full rebuild (it
        just repaints the whole map either way), but it broke
        _update_dirty_colors' whole premise: a region far from the actual
        transfer could need repainting even though it wasn't in the dirty
        set. Keying by id instead makes a region's shade depend only on
        its own id and its own current owner's color -- exactly the
        "only the transferred region's own cells ever need repainting"
        invariant the incremental path relies on."""
        wd = self.world
        fcolors = [_hex_to_rgb(f.color) for f in wd.factions]
        cshade = [None] * len(wd.regions)
        for f in wd.factions:
            fc = _hex_to_rgb(f.color)
            for cid in f.meta.get("regions", []):
                cshade[cid] = _shade(fc, _REGION_SHADES[cid % len(_REGION_SHADES)])
        return fcolors, cshade

    def _precompute_colors(self):
        """Flat row-major RGB pixel lists for every view (for Image.putdata)
        -- a full rebuild of every cell, O(w*h). Used once at load (see
        set_world) and as _update_dirty_colors' fallback when there's no
        existing array to patch yet. Ownership changes after that go
        through _update_dirty_colors instead (see its docstring for why a
        full rebuild on every single territory change got expensive)."""
        wd = self.world
        n = wd.w * wd.h
        self._px_pol = [None] * n
        self._px_pol_hi = [None] * n
        self._px_fert = [None] * n
        self._px_elev = [None] * n
        self._px_biome = [None] * n
        self._px_climate = [None] * n
        self._px_region = [None] * n
        self._px_region_hi = [None] * n
        self._owner_flat = [OCEAN] * n
        self._region_flat = [-1] * n
        fcolors, cshade = self._color_context()
        cg = wd.region_grid
        for y in range(wd.h):
            for x in range(wd.w):
                self._compute_cell(x, y, y * wd.w + x, wd, cg, fcolors, cshade)

    def _update_dirty_colors(self, cells):
        """Incremental counterpart to _precompute_colors: only redo the
        specific cells whose faction ownership actually changed (see
        territory.transfer_region's world._dirty_color_cells bookkeeping)
        instead of recoloring the entire map every time. A cell's color
        only ever depends on its OWN region's current owner/cshade entry
        -- fertility/elevation/biome/climate/region-id/water-adjacency are
        all static geography, and the region-border shading a neighboring
        cell gets depends on region ID (never changes) not which faction
        owns it -- so scoping strictly to the transferred region's own
        cells is fully correct, no neighbor halo needed. Falls back to a
        full rebuild if there's no existing array to patch (e.g. right
        after set_world, before the first _precompute_colors has run)."""
        if self._px_pol is None or not cells:
            self._precompute_colors()
            return
        wd = self.world
        fcolors, cshade = self._color_context()
        cg = wd.region_grid
        for x, y in cells:
            if 0 <= x < wd.w and 0 <= y < wd.h:
                self._compute_cell(x, y, y * wd.w + x, wd, cg, fcolors, cshade)

    def _compute_cell(self, x, y, i, wd, cg, fcolors, cshade):
        """Write this one cell's color into every self._px_*[i]/
        _owner_flat[i]/_region_flat[i] array -- the actual per-pixel work
        shared by both the full rebuild (_precompute_colors) and the
        incremental update (_update_dirty_colors), so the two can never
        drift out of sync with each other."""
        sea = wd.sea_level
        o = wd.owner[y][x]
        h = wd.height[y][x]
        if o == OCEAN:
            depth = max(0.0, min(1.0, (sea - h) / (sea or 1)))
            px = _rgb(*(_OCEAN_DEEP[j] + (_OCEAN_SHALLOW[j] - _OCEAN_DEEP[j])
                        * (1 - depth) for j in range(3)))
            self._px_pol[i] = self._px_pol_hi[i] = px
            self._px_fert[i] = self._px_elev[i] = px
            self._px_biome[i] = self._px_climate[i] = _rgb(*_NO_DATA_RGB)
            self._px_region[i] = self._px_region_hi[i] = px
        elif (x, y) in wd.lake_cells:
            # lake surface: water in every mode, but keep owner/region
            # so clicks still resolve to the faction/region beneath.
            lk = _rgb(*_LAKE_RGB)
            self._px_pol[i] = self._px_pol_hi[i] = lk
            self._px_fert[i] = self._px_elev[i] = lk
            self._px_biome[i] = self._px_climate[i] = lk
            self._px_region[i] = self._px_region_hi[i] = lk
            self._owner_flat[i] = o
            self._region_flat[i] = cg[y][x]
        elif (x, y) in wd.river_cells:
            # River surface: baked into the raster exactly like a
            # lake (flat tone, every mode, owner/region preserved
            # beneath) rather than drawn as a separate vector line on
            # top of everything — this is what makes it read as part
            # of the terrain instead of a decal, and it means fog of
            # war (which only ever composites over this raster)
            # covers rivers automatically, same as anything else.
            rv = _rgb(*_RIVER_RGB)
            self._px_pol[i] = self._px_pol_hi[i] = rv
            self._px_fert[i] = self._px_elev[i] = rv
            self._px_biome[i] = self._px_climate[i] = rv
            self._px_region[i] = self._px_region_hi[i] = rv
            self._owner_flat[i] = o
            self._region_flat[i] = cg[y][x]
        else:
            relief = (h - sea) / (1 - sea) if sea < 1 else 0
            if o >= 0:
                base = _rgb(*_lighten(fcolors[o], 0.10 * relief))
            else:
                # UNCLAIMED — no faction color to draw from; a muted
                # neutral tone, darker/rustier where the wildland
                # garrison guarding it is stronger.
                cid_here = cg[y][x]
                strength = (wd.regions[cid_here].wildland_strength
                           if 0 <= cid_here < len(wd.regions) else 40)
                danger = max(0.0, min(1.0, strength / _WILDLAND_DANGER_REF))
                base = _rgb(*(_UNCLAIMED_RGB[j] + (_UNCLAIMED_DANGER_RGB[j]
                             - _UNCLAIMED_RGB[j]) * danger for j in range(3)))
                base = _rgb(*_lighten(base, 0.08 * relief))

            biome_here = wd.biome_grid[y][x]
            tint = _POL_BIOME_TINT.get(biome_here)
            if tint:
                base = _rgb(*_blend(base, _BIOME_COLORS[biome_here], tint))

            # water-adjacent: any 4-neighbor is ocean, a lake, or a
            # river — every such shoreline/riverbank cell gets the
            # same darkened "carved edge" treatment, in any mode, so
            # a river reads as cutting a real channel through the
            # landscape rather than floating over flat, unshaded
            # ground on either side.
            water_adjacent = False
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < wd.w and 0 <= ny < wd.h:
                    no = wd.owner[ny][nx]
                    if (no == OCEAN or (nx, ny) in wd.lake_cells
                            or (nx, ny) in wd.river_cells):
                        water_adjacent = True
                        break

            fert_rgb = _fert_rgb(wd.fertility[y][x])
            elev_rgb = _elev_rgb(relief)
            if water_adjacent:
                base = _rgb(*_shade(base, -0.8))
                fert_rgb = _rgb(*_shade(fert_rgb, -0.8))
                elev_rgb = _rgb(*_shade(elev_rgb, -0.8))

            biome_rgb = _rgb(*_biome_rgb(biome_here))
            climate_rgb = _rgb(*_climate_rgb(wd.climate_grid[y][x]))
            if water_adjacent:
                biome_rgb = _rgb(*_shade(biome_rgb, -0.5))
                climate_rgb = _rgb(*_shade(climate_rgb, -0.5))

            self._px_pol[i] = base
            self._px_pol_hi[i] = _rgb(*_lighten(base, 0.4))
            self._px_fert[i] = fert_rgb
            self._px_elev[i] = elev_rgb
            self._px_biome[i] = biome_rgb
            self._px_climate[i] = climate_rgb
            self._owner_flat[i] = o

            cid = cg[y][x]
            self._region_flat[i] = cid
            shade = cshade[cid] if (cid >= 0 and cshade[cid] is not None) else base
            # region border: any 4-neighbor in a different region, or
            # a water-adjacent (coastline/riverbank) edge
            border = water_adjacent
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if not (0 <= nx < wd.w and 0 <= ny < wd.h) or cg[ny][nx] != cid:
                    border = True
                    break
            self._px_region[i] = _rgb(*(_shade(shade, -0.5) if border else shade))
            self._px_region_hi[i] = _rgb(*_lighten(shade, 0.45))

    # --- trade log -------------------------------------------------------------
    _TRADE_LOG_MAX_ENTRIES = 200   # trim oldest once exceeded, so it can't grow forever

    _TRADE_LOG_MIN_WIDTH = 260
    _TRADE_LOG_MAX_WIDTH = 900
    _TRADE_LOG_HEIGHT = 210   # header/tabs + scrollable row list

    _TRADE_LOG_TABS = (("domestic", "Domestic"), ("foreign", "Global"))

    def _build_trade_log(self):
        """A persistent, scrolling ledger of the player's own trade income/
        cost, docked to the bottom-left corner of the map canvas (floated
        via place(), same technique bottom_msg/year_banner already use, so
        it doesn't eat into the fixed side panels' width). Distinct from
        show_bottom_message's one-line banner: that shows only the FIRST
        relevant event each turn and auto-dismisses; this accumulates
        every financial trade event, turn after turn, so the player can
        actually review what happened instead of catching a single
        flashed line.

        A tabbed, row-based widget (Canvas+Frame, same scrollable-list
        pattern the RESOURCES sidebar and "What's New" panel already use)
        rather than a plain Text log: Domestic and Global trade are
        different enough in shape (settlement-to-settlement vs.
        faction-to-faction) that mixing them in one undifferentiated feed
        made it hard to follow either. Same-turn purchases made by the
        same buyer are grouped into one expandable row (see
        _refresh_trade_log_rows) instead of a wall of near-identical
        lines.

        Horizontally resizable (drag the handle on the right edge), since
        a fixed width was cutting off longer lines (long faction names,
        big Gold amounts) with no way to see the rest."""
        self._trade_log_width = 340
        self._trade_log_tab = "domestic"
        self._trade_log_entries = []   # structured events, newest last -- see _log_trade_events
        self._trade_log_expanded = set()   # {(turn, tab, group_label), ...} currently expanded
        self._trade_log_scroll_pending = False   # see _scroll_trade_log_to_end

        # Parented to the MapView, NOT to self.canvas -- same as every other
        # floating panel here (alerts, treasury, the resource bar, and this
        # log's own reopen tab). It used to hang off the canvas, which worked
        # only for as long as the canvas was always the thing on screen: the
        # GPU flat map swaps it out with self.canvas.pack_forget()
        # (_activate_flatgl), and an unmapped parent takes its children with
        # it. The tab stayed visible and clickable because it was already
        # parented to self, so the log simply never appeared when clicked.
        # Same family as the z-order bug in v0.3.8_7 -- anything that must
        # survive the canvas/GL swap belongs on the MapView itself.
        self.trade_log_frame = tk.Frame(self, bg=theme.CANVAS,
                                        highlightbackground=theme.LINE,
                                        highlightthickness=1, height=self._TRADE_LOG_HEIGHT)
        body = tk.Frame(self.trade_log_frame, bg=theme.CANVAS)
        body.pack(side="left", fill="both", expand=True)
        header = tk.Frame(body, bg=theme.PANEL)
        header.pack(fill="x")
        close = tk.Label(header, text="✕", bg=theme.PANEL, fg=theme.MUTED,
                         font=theme.FONT_SMALL, cursor="hand2")
        close.pack(side="left", padx=(8, 4), pady=4)
        close.bind("<Button-1>", lambda e: self._toggle_trade_log())
        tk.Label(header, text="TRADE LOG", bg=theme.PANEL, fg=theme.ACCENT,
                 font=theme.FONT_HEADER).pack(side="left", padx=(0, 8), pady=4)
        # The tab that reopens it once closed -- a drawn plaque rather than a
        # grey Label (app/ui/parchment.py). Its canvas IS _trade_log_btn, so
        # every place()/place_forget()/lift() call around it is unchanged; what
        # used to be .config(text=...) is a redraw, since a drawn control has
        # no label to change in place.
        # Wrapped in a Frame, and the wrapper is what gets placed and raised.
        # On a Canvas, BOTH lift() and tkraise() are aliases for tag_raise --
        # they raise a canvas ITEM -- so placing a bare canvas as a floating
        # panel means every raise is a TclError. A one-line frame around it
        # keeps the placement code ordinary.
        self._trade_log_btn = tk.Frame(self, bg=theme.PANEL)
        self._trade_log_btn_page = parchment.Page(self._trade_log_btn, 154, seed=17)
        self._trade_log_btn_page.canvas.pack()
        self._render_trade_log_btn()
        tabs = tk.Frame(header, bg=theme.PANEL)
        tabs.pack(side="right", padx=6)
        self._trade_log_tab_btns = {}
        for tab_id, label in self._TRADE_LOG_TABS:
            btn = tk.Button(tabs, text=label, font=theme.FONT_SMALL,
                            relief="flat", bd=0, cursor="hand2",
                            command=lambda t=tab_id: self._set_trade_log_tab(t))
            btn.pack(side="left", padx=2, pady=2)
            self._trade_log_tab_btns[tab_id] = btn

        rows_area = tk.Frame(body, bg=theme.CANVAS)
        rows_area.pack(fill="both", expand=True, padx=(6, 0), pady=(4, 6))
        canvas = tk.Canvas(rows_area, bg=theme.CANVAS, highlightthickness=0)
        vbar = tk.Scrollbar(rows_area, orient="vertical", command=canvas.yview)
        canvas.pack(side="left", fill="both", expand=True)
        vbar.pack(side="right", fill="y")
        canvas.configure(yscrollcommand=vbar.set)
        self._trade_log_canvas = canvas
        self._trade_log_rows_frame = tk.Frame(canvas, bg=theme.CANVAS)
        window = canvas.create_window((0, 0), window=self._trade_log_rows_frame, anchor="nw")
        self._trade_log_rows_frame.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(window, width=e.width))
        canvas.bind("<Enter>", lambda e: canvas.bind_all(
            "<MouseWheel>", lambda ev: canvas.yview_scroll(int(-ev.delta / 120), "units")))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        # Drag handle: a thin strip on the right edge that resizes the
        # whole panel's width -- clamped so it can't be dragged smaller
        # than the header text or wider than the map canvas itself.
        handle = tk.Frame(self.trade_log_frame, bg=theme.LINE, width=4,
                          cursor="sb_h_double_arrow")
        handle.pack(side="right", fill="y")
        handle.bind("<B1-Motion>", self._on_trade_log_drag)
        self._trade_log_frame_widget = self.trade_log_frame

        self._resize_trade_log(self._trade_log_width)
        self._trade_log_open = False
        self._place_trade_log()

    def _place_trade_log(self):
        """Dock the log at the bottom-left, clear of whatever the left panel
        is currently doing. Closed by default and hidden entirely when empty:
        it used to sit there as a large black rectangle over the map with
        nothing in it, permanently costing map area to show nothing."""
        x = (_LEFT_PANEL_W if not getattr(self, "_left_collapsed", False)
             else _EDGE_TAB_W)
        if getattr(self, "_trade_log_open", False):
            self.trade_log_frame.place(relx=0.0, rely=1.0, anchor="sw", x=x, y=0)
            self.trade_log_frame.lift()
            self._trade_log_btn.place_forget()
        else:
            self.trade_log_frame.place_forget()
            self._render_trade_log_btn()
            self._trade_log_btn.place(relx=0.0, rely=1.0, anchor="sw", x=x + 8, y=-8)
            self._trade_log_btn.lift()

    def _render_trade_log_btn(self):
        """Draw the reopen plaque, carrying however many entries are waiting."""
        page = getattr(self, "_trade_log_btn_page", None)
        if page is None:
            return
        entries = len(getattr(self, "_trade_log_entries", []) or [])
        page.begin(44)
        page.button(f"Trade Log ({entries})" if entries else "Trade Log",
                    self._toggle_trade_log,
                    kind="accent" if entries else "default")
        page.finish()

    def _toggle_trade_log(self):
        self._trade_log_open = not getattr(self, "_trade_log_open", False)
        self._place_trade_log()
        self._refresh_trade_log_tab_styles()

    def _resize_trade_log(self, width):
        width = max(self._TRADE_LOG_MIN_WIDTH, min(self._TRADE_LOG_MAX_WIDTH, width))
        self._trade_log_width = width
        # pack_propagate(False) locks BOTH axes to whatever's configured,
        # not just the width it's meant to pin here (Tkinter has no
        # single-axis version) -- so height has to be re-asserted on every
        # resize too, or it silently collapses toward 0 the moment this
        # first runs (exactly what happened before this was caught: the
        # panel was still technically "there", just squeezed to ~1px tall
        # and invisible).
        self.trade_log_frame.config(width=width, height=self._TRADE_LOG_HEIGHT)
        self.trade_log_frame.pack_propagate(False)

    def _on_trade_log_drag(self, event):
        # event.x is relative to the handle itself; the handle sits at the
        # panel's right edge, so the panel's own left-anchored x plus the
        # drag position IS the new total width.
        self._resize_trade_log(self._trade_log_width + event.x)

    def _set_trade_log_tab(self, tab_id):
        if tab_id == self._trade_log_tab:
            return
        self._trade_log_tab = tab_id
        self._refresh_trade_log_tab_styles()
        self._refresh_trade_log_rows()

    def _refresh_trade_log_tab_styles(self):
        for tab_id, btn in self._trade_log_tab_btns.items():
            active = tab_id == self._trade_log_tab
            btn.config(bg=theme.ACCENT if active else theme.CANVAS,
                      fg=theme.ACCENT_INK if active else theme.MUTED,
                      activebackground=theme.ACCENT if active else theme.PANEL)

    def _payment_desc(self, payment, value, sign=0):
        """Render a trade payment (a [(resource, qty), ...] list, real
        Gold and/or a barter good -- see trade._collect_payment's
        barter_first path) as trade-log text, e.g. "40 Wheat" or "40
        Wheat + 12g" for an unsigned partial barter (sign=0); "-1,000g
        + -50 Iron" for a buyer mix (sign=-1, EVERY item is a cost --
        not just the first one visually tagged) so an Iron in a buyer
        row doesn't read as a gain; "+115g" or "+1,000g + 50 Iron" for a
        seller mix (sign=1, every item is incoming).

        The sign lives on EVERY entry rather than just on the
        outer " - " prefix because for a multi-item buyer payment
        (a real, post-Currency-overhaul case -- reserved Gold at the
        trade-spending floor short of the full price is now partially
        made up with barter goods), prefixing only the joined string
        reads as "-1,000g + 50 Iron" where the Iron item visually looks
        like it's added to the row instead of it also leaving the
        buyer -- same shape flatters the trade log into
        mis-representing the settlement's actual delta. Falls back to a
        plain signed gold-equivalent figure if `payment` is missing
        (old saves/events from before this field existed) or empty."""
        if not payment:
            if sign < 0:
                return f"-{value:,}g"
            if sign > 0:
                return f"+{value:,}g"
            return f"{value:,}g"
        prefix = "-" if sign < 0 else ("+" if sign > 0 else "")
        return " + ".join(f"{prefix}{qty:,}g" if resource == "Gold"
                          else f"{prefix}{qty:,} {resource}"
                          for resource, qty in payment)

    @staticmethod
    def _payment_has_coin(ev):
        """Did any actual Gold change hands in this event?

        Domestic transfers deliberately settle in barter (see trade.
        _collect_payment's barter_first path) -- a realm has no reason to burn
        its treasury moving its own grain between its own barns. That's sound,
        but it means most rows in this log move no coin at all, which is a
        large part of why the trade log and the Gold figure never appeared to
        agree. Rows that moved no coin are marked, rather than silently
        reading as income you never received."""
        payment = ev.get("payment")
        if not payment:
            return bool(ev.get("price"))   # legacy events: assume coin
        return any(resource == "Gold" and qty for resource, qty in payment)

    def _actual_payment_value(self, ev):
        """Gold-equivalent value of an event's REAL payment list -- the
        actual (resource, qty) tuple list trade._collect_payment returned
        (filled in at event creation by advance_caravans /
        run_regional_trade / advance_regional_shipments), which may be
        Gold only, a mix of Gold and barter goods, or empty -- possibly
        reflecting a settlement that ran short on Gold this turn and
        had _find_barter_good substitute real goods for part of the
        payment.

        Falls back to ev['price'] for any legacy event predating the
        payment field (eg. saves written before Currency overhaul, or
        artificially-recorded informational events with no payment).

        This is what the trade log should sum/display, not ev['price']:
        agreed price is what the two sides SETTLED on, not what actually
        left one settlement's resources this turn, and these two numbers
        diverge whenever the buyer's paying settlement was capped by the
        _spendable_gold floor, paid partly in barter, or had to
        undersize the deal for purchasing-power reasons -- the case where
        the trade log was previously showing numbers that didn't match
        the resources tab (see also the screened trade-log/inventory
        discrepancy)."""
        payment = ev.get("payment")
        if payment:
            return sum((resources.resource_value(r, q) for r, q in payment), 0)
        return ev.get("price", 0)

    def _log_trade_events(self):
        """Called once per End Turn: append every financial trade event
        involving the player this turn to the trade log's structured
        entry list (unlike _report_trade_events/_report_regional_trade_
        events, which only surface the FIRST one on the transient bottom
        banner) -- foreign trade income/cost and domestic regional
        transfers both. Purely informational events with no Gold changing
        hands (a caravan departing, a free sell-to-city shipment) are
        left out — this is specifically an income/cost ledger, not a
        general activity log. Each entry records a `group` label (the
        buying party) so same-turn purchases from the same buyer can be
        collapsed into one row -- see _refresh_trade_log_rows."""
        player_idx = self.world.player_faction_idx
        if player_idx is None:
            return
        turn = self.world.turn
        new_entries = []

        for ev in self.world.trade_events:
            etype = ev["type"]
            if "seller_idx" not in ev or "buyer_idx" not in ev:
                continue   # route_proposed/route_started -- no seller/buyer, not a ledger event
            is_seller = ev["seller_idx"] == player_idx
            is_buyer = ev["buyer_idx"] == player_idx
            if not (is_seller or is_buyer):
                continue
            other_idx = ev["buyer_idx"] if is_seller else ev["seller_idx"]
            other_name = self.world.factions[other_idx].name
            if etype == "delivered" and is_buyer:
                # Use the real (resource, qty) list _collect_payment returned
                # -- what actually left buyer_st.resources this turn, not the
                # agreed price, which can differ when the buyer was capped by
                # _spendable_gold or paid partly in barter (see
                # trade._collect_payment's allow_gold/barter_first paths).
                # sign=-1: both Gold AND any barter items in the payment
                # leave the buyer (see _payment_desc docstring on why this
                # matters for multi-item rows).
                new_entries.append({"turn": turn, "tab": "foreign", "coin": self._payment_has_coin(ev),
                                    "kind": "cost",
                                    "group": "You",
                                    "value": self._actual_payment_value(ev),
                                    "text": f"Bought {ev['quantity']} {ev['resource']} "
                                            f"from {other_name} — "
                                            f"{self._payment_desc(ev.get('payment'), ev['price'], sign=-1)}"})
            elif etype == "paid" and is_seller:
                # bonus_gold: a species trade bonus (Humans) on top of the
                # agreed price -- called out so the perk is visible, not just
                # silently better numbers. The displayed amount is the
                # ACTUAL boosted payment delivered to seller_st, which is
                # what ev['payment'] already contains (post-_with_gold_bonus)
                # -- not "price + bonus_gold", which only matches cleanly
                # for a pure-Gold payment and silently mis-reports the
                # seller-side delta for any barter mix the buyer paid in.
                # sign=1: every item in the boosted payment is incoming
                # (the seller really did get all of them).
                bonus = ev.get("bonus_gold", 0)
                suffix = f" (incl. +{bonus:,}g trade bonus)" if bonus else ""
                new_entries.append({"turn": turn, "tab": "foreign", "coin": self._payment_has_coin(ev),
                                    "kind": "income",
                                    "group": None,
                                    "value": self._actual_payment_value(ev),
                                    "text": f"Sold {ev['quantity']} {ev['resource']} "
                                            f"to {other_name} — "
                                            f"{self._payment_desc(ev.get('payment'), ev['price'], sign=1)}{suffix}"})
            elif etype == "lost":
                # A "lost" event can fire on either leg: outbound (no payment
                # yet — only the goods were in transit) or return (payment was
                # already collected at destination and was riding home with
                # the caravan). The event dict doesn't carry that distinction
                # today, so the log entry just says both are gone — accurate
                # in the worst case and never wrong about the goods, which are
                # always gone.
                new_entries.append({"turn": turn, "tab": "foreign", "kind": "muted",
                                    "group": None,
                                    "text": f"Caravan lost ({ev['quantity']} "
                                            f"{ev['resource']}, {other_name}) — both the "
                                            f"goods and any payment are gone"})

        for ev in self.world.regional_trade_events:
            if ev.get("faction_idx") != player_idx:
                continue
            etype = ev["type"]
            # regional_dispatched/regional_delivered are also the generic
            # delivery-completion events for a FREE sell-to-city shipment
            # (see trade.run_sell_to_city -- price is always 0.0 there by
            # design, indistinguishable at this point from a real
            # regional-market sale) -- only log ones with a real price,
            # so a free internal restock doesn't show up as "paid +0g".
            if etype == "regional_dispatched" and ev["price"] > 0:
                # sign=-1: same mix-payment sign rule as the foreign
                # delivered buyer row above (see _payment_desc).
                new_entries.append({"turn": turn, "tab": "domestic", "coin": self._payment_has_coin(ev),
                                    "kind": "cost",
                                    "group": ev["dest_name"],
                                    "value": self._actual_payment_value(ev),
                                    "text": f"buys {ev['quantity']} {ev['resource']} "
                                            f"from {ev['origin_name']} — "
                                            f"{self._payment_desc(ev.get('payment'), ev['price'], sign=-1)}"})
            elif etype == "regional_delivered" and ev["price"] > 0:
                # Mirror of the foreign-trade "Sold X to Y" wording just
                # above: the seller (origin) RECEIVES payment, so the entry
                # reports a +gain, not a +pay. An earlier draft phrased this
                # as "{origin} paid +Ng", which flipped the direction of
                # the money flow and read opposite of what actually happened.
                # sign=1: every item in the payment is incoming to seller_st.
                new_entries.append({"turn": turn, "tab": "domestic", "coin": self._payment_has_coin(ev),
                                    "kind": "income",
                                    "group": None,
                                    "value": self._actual_payment_value(ev),
                                    "text": f"{ev['origin_name']} sold "
                                            f"{ev['quantity']} {ev['resource']} to {ev['dest_name']} "
                                    f"— {self._payment_desc(ev.get('payment'), ev['price'], sign=1)}"})
            elif etype == "regional_lost":
                new_entries.append({"turn": turn, "tab": "domestic", "kind": "muted",
                                    "group": None,
                                    "text": f"Shipment lost ({ev['quantity']} "
                                            f"{ev['resource']}, {ev['origin_name']} → "
                                            f"{ev['dest_name']})"})

        if not new_entries:
            return
        self._trade_log_entries.extend(new_entries)
        overflow = len(self._trade_log_entries) - self._TRADE_LOG_MAX_ENTRIES
        if overflow > 0:
            del self._trade_log_entries[:overflow]
        self._refresh_trade_log_rows()

    def _refresh_trade_log_rows(self):
        """Rebuild the visible row widgets for the current tab from
        self._trade_log_entries -- same full-rebuild-on-refresh approach
        the RESOURCES sidebar and changelog panel already use, cheap
        enough at this data volume (a few hundred entries, trimmed).
        Consecutive same-turn "cost" entries sharing a `group` label (the
        buying settlement/faction) collapse into one summary row that
        expands to show each individual purchase — see
        _trade_log_expanded. A group of exactly one entry is shown plain,
        no point collapsing a single line."""
        frame = self._trade_log_rows_frame
        for w in frame.winfo_children():
            w.destroy()

        entries = [e for e in self._trade_log_entries if e["tab"] == self._trade_log_tab]
        if not entries:
            tk.Label(frame, text="No trades yet.", bg=theme.CANVAS, fg=theme.MUTED,
                     font=theme.FONT_SMALL, anchor="w").pack(fill="x", padx=4, pady=4)
            self._scroll_trade_log_to_end()
            return

        # Group consecutive cost entries by (turn, group label); everything
        # else (income, muted, ungrouped cost) passes through as its own
        # single-item "group" so the render loop below is uniform.
        groups = []
        key_to_group = {}
        for e in entries:
            gkey = (e["turn"], e["group"]) if (e["kind"] == "cost" and e["group"]) else None
            if gkey is not None and gkey in key_to_group:
                key_to_group[gkey]["items"].append(e)
                continue
            g = {"key": gkey, "turn": e["turn"], "kind": e["kind"], "items": [e]}
            groups.append(g)
            if gkey is not None:
                key_to_group[gkey] = g

        last_turn = None
        for g in groups:
            if g["turn"] != last_turn:
                last_turn = g["turn"]
                tk.Label(frame, text=f"Turn {g['turn']}", bg=theme.CANVAS, fg=theme.ACCENT,
                         font=theme.FONT_SMALL_BOLD, anchor="w"
                         ).pack(fill="x", padx=4, pady=(6, 1))
            color = {"income": theme.GOOD, "cost": theme.BAD,
                    "muted": theme.MUTED}[g["kind"]]
            # A row that moved no coin is drawn muted and tagged, so a barter
            # transfer stops looking like gold you gained or spent -- the
            # single biggest reason this log and the Gold figure read as
            # contradicting each other. See _payment_has_coin.
            no_coin = all(not it.get("coin", True) for it in g["items"])
            if no_coin and g["kind"] != "muted":
                color = theme.MUTED
            if len(g["items"]) == 1:
                tag = "  (barter — no coin)" if no_coin and g["kind"] != "muted" else ""
                tk.Label(frame, text="  " + g["items"][0]["text"] + tag, bg=theme.CANVAS,
                         fg=color, font=theme.FONT_SMALL, anchor="w", justify="left"
                         ).pack(fill="x", padx=4)
                continue

            expanded = g["key"] in self._trade_log_expanded
            # Gold-equivalent total, from each entry's own stored `value`
            # (the real price, same figure _payment_desc rendered into its
            # text) -- not re-derived from the text itself, which would
            # silently undercount a partially- or fully-bartered purchase
            # (e.g. "-40 Wheat" has no "-Ng" token to parse back out).
            total_value = sum(it.get("value", 0) for it in g["items"])
            total_desc = (f"{g['items'][0]['group']} made {len(g['items'])} purchases "
                         f"this turn ({'-' if g['kind'] == 'cost' else '+'}"
                         f"{total_value:,}g total)")
            arrow = "▾" if expanded else "▸"
            row = tk.Label(frame, text=f"  {arrow} {total_desc}", bg=theme.CANVAS, fg=color,
                           font=theme.FONT_SMALL, anchor="w", justify="left", cursor="hand2")
            row.pack(fill="x", padx=4)
            row.bind("<Button-1>", lambda e, k=g["key"]: self._toggle_trade_log_group(k))
            if expanded:
                for it in g["items"]:
                    tk.Label(frame, text="      " + it["text"], bg=theme.CANVAS, fg=color,
                             font=theme.FONT_SMALL, anchor="w", justify="left"
                             ).pack(fill="x", padx=4)

        self._scroll_trade_log_to_end()

    def _scroll_trade_log_to_end(self):
        """Scroll the row list to the newest entry -- deferred to idle, which
        is the whole point.

        The rows frame recomputes the canvas's scrollregion from its
        <Configure> event, and that fires on idle, AFTER this refresh
        returns. Scrolling inline therefore moved to the bottom of the
        PREVIOUS tab's scrollregion: switching from a busy Domestic tab
        (hundreds of rows) to a quiet Global one (a handful) left the canvas
        parked hundreds of pixels below the new, much shorter content, and
        the panel read as completely empty -- not even the "No trades yet."
        placeholder was on screen. Waiting for idle means the scrollregion
        matches the rows that actually exist before we move."""
        canvas = self._trade_log_canvas
        if self._trade_log_scroll_pending:
            return
        self._trade_log_scroll_pending = True

        def do_scroll():
            self._trade_log_scroll_pending = False
            if not canvas.winfo_exists():
                return
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.yview_moveto(1.0)

        self.after_idle(do_scroll)

    def _toggle_trade_log_group(self, key):
        if key in self._trade_log_expanded:
            self._trade_log_expanded.discard(key)
        else:
            self._trade_log_expanded.add(key)
        self._refresh_trade_log_rows()

    # --- alerts ------------------------------------------------------------
    _ALERTS_MAX_VISIBLE = 8
    _ALERT_WARN_COLOR = theme.WARN

    def _build_alerts_panel(self):
        """A persistent top-left panel listing every current problem at one
        of the player's own settlements/villages (see resources.
        faction_alerts) -- food/firewood shortage, starving/freezing,
        overflowing storage -- so trouble is visible without having to
        click through every node's numbers to notice it. Unlike the Trade
        Log (an accumulating ledger), this is a snapshot of CURRENT state:
        rebuilt from scratch each refresh, not appended to, so a problem
        still shows here for as long as it's actually ongoing.  Hidden
        entirely (via place_forget) when there's nothing wrong."""
        self._alerts_open = True
        self._alerts_expanded = set()
        # A DRAWN page rather than a stack of Labels (app/ui/parchment.py).
        # This panel is the one the player reads under pressure -- something is
        # already going wrong when it is on screen -- so it is the one that
        # most wants a wax seal beside each line instead of a coloured word.
        self.alerts_frame = tk.Frame(self, bg=theme.PANEL, width=_ALERTS_PANEL_W)
        self._alerts_page = parchment.Page(self.alerts_frame, _ALERTS_PANEL_W,
                                           seed=5)
        self._alerts_page.canvas.pack(fill="both", expand=True)

        # Badge that takes the panel's place once it's dismissed, so alerts can
        # always be brought back and their count stays visible meanwhile.
        self._alerts_btn = tk.Label(self, text="⚠", bg=theme.ALERT_BG, fg=theme.BAD,
                                    font=theme.FONT_BOLD, cursor="hand2",
                                    padx=8, pady=4,
                                    highlightbackground=theme.BAD, highlightthickness=1)
        self._alerts_btn.bind("<Button-1>", lambda e: self._toggle_alerts())

    def _refresh_alerts(self):
        """Recompute the current alert set (see the __init__ note on why
        this only runs from set_world()/refresh(), never render()) and
        rebuild the panel from it. Also rebuilds _alert_node_ids, the
        cached {id(node): worst severity} lookup _draw_settlements/
        _draw_villages use for map badges."""
        player_idx = self.world.player_faction_idx
        alerts = resources.faction_alerts(self.world, player_idx) if player_idx is not None else []
        # Critical (population actively being lost) always sorts above a
        # mere warning, so the most urgent problems are never scrolled
        # past the visible-rows cap by a pile of lesser ones.
        alerts.sort(key=lambda a: 0 if a["severity"] == "critical" else 1)
        self._current_alerts = alerts

        node_ids = {}
        for a in alerts:
            nid = id(a["node"])
            if nid not in node_ids or a["severity"] == "critical":
                node_ids[nid] = a["severity"]
        self._alert_node_ids = node_ids

        self._render_alerts()

    _ALERT_GROUP_LABEL = {
        "herd_culled": "herds culled — no winter fodder",
        "herd_underfed": "herds short of winter fodder",
        "storage_overflow": "storage full — production stopped",
        "storage_nearly_full": "storage nearly full",
        "starving": "starving",
        "freezing": "freezing",
        "food_shortage": "food shortage",
        "firewood_shortage": "firewood shortage",
        "no_firewood_source": "no local firewood source",
    }

    def _render_alerts(self):
        """One row per alert KIND with a count, expandable to the affected
        settlements.

        The old panel printed the first eight alerts as full sentences and
        added "+142 more". Because alerts of a kind differ only by settlement
        name, that was the same three-line paragraph repeated eight times,
        permanently covering the top-left quarter of the map, while 142
        problems stayed invisible. Measured on a real save: 150 alerts for the
        player across 4 distinct kinds, and 1,088 map-wide. Grouping turns
        that into four lines that name every problem, and the detail is one
        click away."""
        page = self._alerts_page
        alerts = self._current_alerts
        if not alerts or not getattr(self, "_alerts_open", True):
            self.alerts_frame.place_forget()
            self._update_alerts_button()
            return

        groups = {}
        for a in alerts:
            groups.setdefault(a["kind"], []).append(a)
        ordered = sorted(groups.items(),
                         key=lambda kv: (0 if any(x["severity"] == "critical"
                                                  for x in kv[1]) else 1,
                                         -len(kv[1])))
        page.begin(400)
        page.title("Alerts", f"{len(alerts)} standing against your realm")
        for kind, items in ordered:
            critical = any(x["severity"] == "critical" for x in items)
            expanded = kind in self._alerts_expanded
            label = self._ALERT_GROUP_LABEL.get(kind, kind.replace("_", " "))
            page.alert_group(f"{len(items)}   {label}", expanded,
                             "critical" if critical else "warning",
                             lambda k=kind: self._toggle_alert_group(k))
            if not expanded:
                continue
            for a in items[:self._ALERTS_MAX_VISIBLE]:
                page.entry(a["node"].name,
                           lambda n=a["node"]: self._jump_to_alert_node(n))
            extra = len(items) - self._ALERTS_MAX_VISIBLE
            if extra > 0:
                page.kv("", f"+ {extra} more", indent=18)
        page.gap(2)
        page.button("Dismiss", self._toggle_alerts)
        page.finish()
        self.alerts_frame.place(relx=0.0, rely=0.0, anchor="nw",
                                x=_LEFT_PANEL_W if not getattr(self, "_left_collapsed", False)
                                else _EDGE_TAB_W, y=0)
        self.alerts_frame.lift()
        self._update_alerts_button()

    def _toggle_alert_group(self, kind):
        self._alerts_expanded ^= {kind}
        self._render_alerts()

    def _toggle_alerts(self):
        self._alerts_open = not getattr(self, "_alerts_open", True)
        self._render_alerts()

    def _update_alerts_button(self):
        """The always-visible badge that reopens a dismissed alerts panel."""
        btn = getattr(self, "_alerts_btn", None)
        if btn is None:
            return
        count = len(self._current_alerts)
        if not count:
            btn.place_forget()
            return
        critical = any(a["severity"] == "critical" for a in self._current_alerts)
        btn.config(text=f"⚠ {count}",
                   fg=theme.BAD if critical else self._ALERT_WARN_COLOR)
        if getattr(self, "_alerts_open", True):
            btn.place_forget()
        else:
            btn.place(relx=0.0, rely=0.0, anchor="nw",
                      x=(_LEFT_PANEL_W if not getattr(self, "_left_collapsed", False)
                         else _EDGE_TAB_W) + 8, y=8)
            btn.lift()

    def _jump_to_alert_node(self, node):
        """Navigate straight to an alerted settlement/village and select it.
        A settlement is visible at the region-view zoom _enter_region_view
        already lands on; a village needs the camera pulled in tighter than
        that -- close enough to cross the _villages_visible threshold --
        since villages only appear/are clickable once actually zoomed in."""
        wd = self.world
        faction = wd.factions[node.faction_idx]
        self._enter_region_view(faction)
        if hasattr(node, "kind"):   # Settlement
            self.selected_settlement = node
            self._show_settlement(node)
        else:                       # Village
            vx, vy = node.pos
            span = _VILLAGE_REVEAL_SPAN * 0.7
            self._start_zoom([vx - span / 2, vy - span / 2,
                              vx + span / 2, vy + span / 2])
            self.selected_village = node
            self._show_village(node)
        self.render()

    # --- resource bar --------------------------------------------------------
    def _build_resource_bar(self):
        """The RESOURCES sidebar now shows the faction's real, whole
        stockpile (see _current_resource_snapshot) rather than the old
        national-pool number that was empty in practice -- which means
        it's commonly a couple dozen rows long instead of one or two, so
        this needs to actually scroll (a plain Frame doesn't) rather than
        just clip silently past the bottom of the panel."""
        rb = tk.Frame(self, bg=theme.PANEL, width=_LEFT_PANEL_W)
        # Placed, not packed: the map canvas fills the whole window and every
        # panel is an overlay on top of it, so the map can be given back its
        # full area whenever a panel is folded away (see _toggle_left_panel).
        rb.place(x=0, y=0, relheight=1.0, width=_LEFT_PANEL_W)
        rb.pack_propagate(False)
        self._resource_bar = rb
        self._resource_groups_open = set()

        head = tk.Frame(rb, bg=theme.PANEL)
        head.pack(fill="x", padx=12, pady=(14, 6))
        tk.Label(head, text="RESOURCES", bg=theme.PANEL, fg=theme.ACCENT,
                 font=theme.FONT_HEADER).pack(side="left")
        tk.Label(head, text="◀", bg=theme.PANEL, fg=theme.MUTED, cursor="hand2",
                 font=theme.FONT_SMALL).pack(side="right")
        for wdg in (head,) + tuple(head.winfo_children()):
            wdg.bind("<Button-1>", lambda e: self._toggle_left_panel())

        scroll_area = tk.Frame(rb, bg=theme.PANEL)
        scroll_area.pack(fill="both", expand=True, padx=(10, 0))
        canvas = tk.Canvas(scroll_area, bg=theme.PANEL, highlightthickness=0)
        canvas.pack(side="left", fill="both", expand=True)
        vbar = tk.Scrollbar(scroll_area, orient="vertical", command=canvas.yview)
        vbar.pack(side="right", fill="y")
        canvas.configure(yscrollcommand=vbar.set)
        self._resource_canvas = canvas
        # A drawn page on the bar's own scrolling canvas, same as the
        # selection panel (app/ui/parchment.py). The rows were thirty-odd
        # Frames and Labels destroyed and rebuilt every turn, which is why
        # they had to be hidden mid-rebuild; a page is cleared by drawing it.
        self._resource_page = parchment.Page(None, _LEFT_PANEL_W - 22, seed=6,
                                             canvas=canvas)
        canvas.bind("<Enter>", lambda e: canvas.bind_all(
            "<MouseWheel>", lambda ev: canvas.yview_scroll(int(-ev.delta / 120), "units")))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

    def _update_resource_bar(self):
        """Redraw the whole bar.

        No hide-while-rebuilding any more: the rows are drawn onto a page, so
        the rebuild is one canvas clear and one draw with no half-built
        intermediate state for Tk to paint. That is what the hidden window
        existed to prevent."""
        page = getattr(self, "_resource_page", None)
        if page is None:
            return
        page.begin(max(320, self._resource_canvas.winfo_height() or 320))
        self._rebuild_resource_rows()
        page.finish()

    def _rebuild_resource_rows(self):
        current = self._current_resource_snapshot()
        if self._player_faction() is None:
            self._resource_page.text("No realm selected.", fill=theme.MUTED)
            return

        # Thirty-odd rows at equal weight is not a list, it's a wall: Gold sat
        # next to Shields with identical emphasis and the tail scrolled off
        # the bottom of the screen. Grouped and collapsed instead, with Gold
        # pinned and anything actually in trouble promoted out of its group so
        # problems find you rather than the other way round.
        present = [r for r in current if r != "Gold"
                   and (current.get(r, 0) > 0 or self._resource_deltas.get(r, 0) != 0)]
        self._draw_resource_row("Gold", current.get("Gold", 0),
                                self._resource_deltas.get("Gold", 0), gold=True)

        attention = self._resources_needing_attention(current, present)
        if attention:
            self._draw_resource_header("NEEDS ATTENTION")
            for resource in attention:
                self._draw_resource_row(resource, current.get(resource, 0),
                                        self._resource_deltas.get(resource, 0),
                                        warn=True)

        groups = {}
        for resource in present:
            groups.setdefault(_RESOURCE_GROUP.get(
                RESOURCES.get(resource, {}).get("category"), "Other"), []).append(resource)
        for group in _RESOURCE_GROUP_ORDER:
            members = groups.get(group)
            if not members:
                continue
            members.sort(key=lambda r: (RESOURCES.get(r, {}).get("tier", 9), r))
            total = sum(current.get(r, 0) for r in members)
            expanded = group in self._resource_groups_open
            self._draw_resource_group_header(group, total, expanded, len(members))
            if expanded:
                for resource in members:
                    self._draw_resource_row(resource, current.get(resource, 0),
                                            self._resource_deltas.get(resource, 0),
                                            indent=True)

    def _resources_needing_attention(self, current, present):
        """Resources worth promoting above the fold: survival goods that have
        run low, and anything falling fast. Deliberately short -- a list that
        flags everything flags nothing."""
        out = []
        for resource in present:
            amount = current.get(resource, 0)
            delta = self._resource_deltas.get(resource, 0)
            critical = resource in _SURVIVAL_RESOURCES
            if critical and amount < _LOW_STOCK_THRESHOLD:
                out.append(resource)
            elif delta < 0 and amount and abs(delta) > amount * 0.25:
                out.append(resource)
        return out[:5]

    def _current_resource_snapshot(self):
        """This turn's REAL totals for the player faction: every resource
        summed across every Settlement AND Village it owns (see
        construction._faction_nodes) -- "our country's whole pool of
        resources," matching what construction.can_afford/_pay_cost
        actually draw on, not the old national-pool number (nation.stats
        ["resources"]) that's empty in practice now that almost
        everything lives in per-node storage (still included too, for
        whatever narrow legacy case might still land there). This used
        to only ever surface Gold this way and otherwise show the stale,
        near-always-empty national pool -- which is why the sidebar used
        to look basically blank."""
        player = self._player_faction()
        if player is None:
            return {}
        snap = dict(player.stats.get("resources", {}))
        for node in construction._faction_nodes(player, self.world):
            for resource, amount in getattr(node, "resources", {}).items():
                snap[resource] = snap.get(resource, 0) + amount
        return snap

    def _current_population_total(self):
        """The player faction's total living population right now -- every
        Settlement and Village added together (same construction.
        _faction_nodes pool _current_resource_snapshot uses), for the
        year-end banner's population line (see _on_end_turn/
        _show_year_banner). Separate from the resource snapshot since
        population isn't a resource entry on any node."""
        player = self._player_faction()
        if player is None:
            return 0
        return sum(getattr(node, "population", 0)
                  for node in construction._faction_nodes(player, self.world))

    def _draw_resource_header(self, text):
        page = self._resource_page
        page.gap(4)
        page.canvas.create_text(parchment.PAD_X, page.y, anchor="w", text=text,
                                fill=theme.WARN, font=theme.FONT_SMALL_BOLD)
        page.y += 16

    def _draw_resource_group_header(self, group, total, expanded, count):
        self._resource_page.card(
            group, group, self._resource_groups_open_state(), _fmt_amount(total),
            on_toggle=lambda g=group: self._toggle_resource_group(g),
            default_open=False)

    def _resource_groups_open_state(self):
        """The group-fold state as the dict a page card expects. The bar has
        always kept it as a SET of open groups; this is the one adapter rather
        than changing how the bar stores it."""
        class _SetAsDict(dict):
            def __init__(self, owner):
                super().__init__({g: True for g in owner._resource_groups_open})
                self._owner = owner

            def get(self, key, default=None):
                return key in self._owner._resource_groups_open

            def __setitem__(self, key, value):
                if value:
                    self._owner._resource_groups_open.add(key)
                else:
                    self._owner._resource_groups_open.discard(key)

        return _SetAsDict(self)

    def _toggle_resource_group(self, group):
        # Only redraw -- do NOT flip the state here. The page card already
        # flipped it through the _SetAsDict adapter before calling this
        # on_toggle (see parchment.Page.card's own _toggle). Flipping it again
        # was a double-flip that netted to no change, so Food/Industry and the
        # rest never actually opened. The selection panel's _toggle_panel_card
        # gets this right for the same reason: the card owns the flip, the
        # callback owns the redraw.
        self._update_resource_bar()

    def _draw_resource_row(self, resource, amount, delta, gold=False,
                           warn=False, indent=False):
        page = self._resource_page
        fg = theme.INK if (gold or not indent) else theme.MUTED
        if warn:
            fg = theme.WARN
        value = _fmt_amount(amount)
        if delta:
            sign = "+" if delta > 0 else "-"
            value = f"{value}   {sign}{_fmt_amount(abs(delta))}"
        page.kv(("  " if indent else "") + resource, value, fg=fg,
                indent=6 if indent else 0)
        if gold:
            # Gold is the one row whose headline number regularly fails to
            # explain itself: most of it is minted silently from Gold Ore, some
            # is out on a caravan's return leg, and some is held back by the
            # trade reserve. Click through for the real accounting.
            page.hit_last_row(self.toggle_treasury)

    # --- treasury ------------------------------------------------------------
    def _build_treasury_panel(self):
        """The Treasury as an in-game panel rather than an OS window.

        It used to be a tk.Toplevel, which meant it floated free of the game,
        could be dragged off the edge of it, and dropped behind the main window
        the moment you touched the map -- so you could not keep it open and
        watch it update as you ended a turn, which is exactly when the numbers
        are interesting. As an overlay it stays inside the game's bounds, keeps
        its place while you pan and zoom, and refreshes in step with the turn
        (see _refresh_treasury / refresh)."""
        self._treasury_open = False
        f = tk.Frame(self, bg=theme.PANEL, width=_TREASURY_W)
        self.treasury_frame = f

        # The header stays a widget: it is the DRAG HANDLE, and a drag needs a
        # cursor and press/motion bindings on a real window rather than on a
        # canvas item. Everything below it is a drawn page.
        head = tk.Frame(f, bg=theme.PANEL_ALT, cursor="fleur")
        head.pack(fill="x")
        tk.Label(head, text="TREASURY", bg=theme.PANEL_ALT, fg=theme.ACCENT,
                 font=theme.FONT_HEADER).pack(side="left", padx=8, pady=4)
        close = tk.Label(head, text="✕", bg=theme.PANEL_ALT, fg=theme.MUTED,
                         font=theme.FONT_SMALL, cursor="hand2")
        close.pack(side="right", padx=8)
        close.bind("<Button-1>", lambda e: self.close_treasury())
        # Drag by the header, clamped so it can never leave the game window.
        for wdg in (head,) + tuple(head.winfo_children()):
            if wdg is close:
                continue
            wdg.bind("<ButtonPress-1>", self._treasury_drag_start)
            wdg.bind("<B1-Motion>", self._treasury_drag)
        self._treasury_page = parchment.Page(f, _TREASURY_W - 2, seed=13)
        self._treasury_page.canvas.pack(fill="both", expand=True)
        self._treasury_pos = None      # (x, y); None means "dock me by default"

    def _treasury_drag_start(self, event):
        self._treasury_grab = (event.x_root, event.y_root,
                               self.treasury_frame.winfo_x(),
                               self.treasury_frame.winfo_y())

    def _treasury_drag(self, event):
        grab = getattr(self, "_treasury_grab", None)
        if grab is None:
            return
        gx, gy, ox, oy = grab
        x = ox + (event.x_root - gx)
        y = oy + (event.y_root - gy)
        self._treasury_pos = self._clamp_to_view(
            x, y, self.treasury_frame.winfo_width(),
            self.treasury_frame.winfo_height())
        self.treasury_frame.place(x=self._treasury_pos[0], y=self._treasury_pos[1])

    def _clamp_to_view(self, x, y, w, h):
        """Keep a floating panel fully inside the game window -- the whole
        point of it being an in-game window rather than an OS one."""
        max_x = max(0, self.winfo_width() - w)
        max_y = max(0, self.winfo_height() - h)
        return (min(max(0, x), max_x), min(max(0, y), max_y))

    def open_treasury(self):
        self._treasury_open = True
        self._refresh_treasury()

    def close_treasury(self):
        self._treasury_open = False
        self.treasury_frame.place_forget()

    def toggle_treasury(self):
        if getattr(self, "_treasury_open", False):
            self.close_treasury()
        else:
            self.open_treasury()

    _TREASURY_CAUSE_HELP = {
        "minted": "struck from Gold Ore at your settlements",
        "foreign trade": "sales to and purchases from other realms",
        "domestic trade": "transfers between your own settlements (mostly barter)",
        "construction": "buildings, shipyards and storage works",
        "expansion": "wildland claims",
        "other": "anything not covered above",
    }

    def _refresh_treasury(self):
        """Rebuild the Treasury contents in place. Called when it is opened and
        again from refresh() after every End Turn, so it can be left open and
        watched -- which is the only way to see minting, trade income and
        construction spend land as they happen."""
        if not getattr(self, "_treasury_open", False):
            return
        player = self._player_faction()
        if player is None:
            self.close_treasury()
            return
        wd = self.world
        fac_idx = wd.factions.index(player)
        page = self._treasury_page
        page.begin(360)
        # No page title: the drag-handle header above it already says
        # TREASURY, and an illuminated capital repeating the word directly
        # underneath reads as a mistake rather than as ornament.
        page.gap(2)

        def section(title, key, default_open=True):
            """A folding section, and the page itself when it is open -- the
            same truthy-or-None contract _card uses on the selection panel."""
            return page if page.card(key, title, self._treasury_cards_open,
                                     on_toggle=self._refresh_treasury,
                                     default_open=default_open) else None

        def line(parent, text, fg=None, bold=False):
            page.text(text, fill=fg or (theme.ACCENT if bold else theme.INK),
                      font=theme.FONT_SMALL_BOLD if bold else None)

        total = resources.faction_gold(wd, fac_idx)
        transit = resources.gold_in_transit(wd, fac_idx)
        settlements = [s for s in wd.settlements if s.faction_idx == fac_idx]
        spendable = sum(trade._spendable_gold(s) for s in settlements)

        sec = section("TOTAL", "total")
        if sec is not None:
            line(sec, f"{total:,} gold", bold=True)
            line(sec, f"{spendable:,} available for trade", theme.MUTED)
            line(sec, f"{total - spendable:,} held back "
                 f"({trade.GOLD_TRADE_RESERVE:,}/settlement reserve, plus village coin)",
                 theme.MUTED)
            if transit:
                line(sec, f"{transit:,} in transit \u2014 sold, still on the road home",
                     theme.WARN)

        sec = section("WHERE IT IS", "where", default_open=False)
        if sec is not None:
            holders = sorted(((getattr(s, "resources", None) or {}).get("Gold", 0), s.name)
                             for s in settlements)
            for amount, name in reversed(holders[-6:]):
                line(sec, f"  {name}: {amount:,}", theme.MUTED)
            village_gold = total - sum(a for a, _ in holders)
            if village_gold:
                line(sec, f"  villages: {village_gold:,} (cannot pay for trade)", theme.MUTED)

        ledger = resources.gold_ledger(wd, fac_idx)
        sec = section("WHERE IT CAME FROM", "sources")
        if sec is not None:
            if not ledger:
                line(sec, "  Nothing recorded yet \u2014 end a turn.", theme.MUTED)
            else:
                agg = {}
                for entry in ledger:
                    for cause, value in entry.items():
                        if cause not in ("turn", "net"):
                            agg[cause] = agg.get(cause, 0) + value
                line(sec, f"  over the last {len(ledger)} turns:", theme.MUTED)
                for cause, value in sorted(agg.items(), key=lambda kv: -abs(kv[1])):
                    line(sec, f"    {value:+,}  {cause}",
                         theme.GOOD if value > 0 else theme.BAD)
                    line(sec, f"        {self._TREASURY_CAUSE_HELP.get(cause, '')}", theme.MUTED)
                line(sec, f"    {sum(agg.values()):+,}  net", None, bold=True)

        if ledger:
            sec = section("RECENT TURNS", "recent", default_open=False)
            if sec is not None:
                for entry in ledger[-6:]:
                    causes = "  ".join(f"{k} {v:+,}" for k, v in entry.items()
                                       if k not in ("turn", "net"))
                    line(sec, f"  turn {entry['turn']}: {entry['net']:+,}   {causes}",
                         theme.MUTED)

        page.finish()

        # Default dock: just left of the side panel, near the top -- out of the
        # way of both the alerts overlay and the trade log.
        self.treasury_frame.update_idletasks()
        w = _TREASURY_W
        h = min(self.treasury_frame.winfo_reqheight(),
                max(200, self.winfo_height() - 90))
        self.treasury_frame.configure(height=h)
        self.treasury_frame.pack_propagate(False)
        if self._treasury_pos is None:
            right = (_RIGHT_PANEL_W if not getattr(self, "_right_collapsed", False)
                     else _EDGE_TAB_W)
            self._treasury_pos = self._clamp_to_view(
                self.winfo_width() - right - w - 12, 40, w, h)
        else:
            self._treasury_pos = self._clamp_to_view(*self._treasury_pos, w, h)
        self.treasury_frame.place(x=self._treasury_pos[0], y=self._treasury_pos[1],
                                  width=w, height=h)
        self.treasury_frame.lift()

    # --- panel -------------------------------------------------------------
    def _build_panel(self):
        p = tk.Frame(self, bg=theme.PANEL, width=_RIGHT_PANEL_W)
        # Overlay, like the resource bar -- see _build_resource_bar.
        p.place(relx=1.0, y=0, anchor="ne", relheight=1.0, width=_RIGHT_PANEL_W)
        p.pack_propagate(False)
        self._panel = p

        head = tk.Frame(p, bg=theme.PANEL)
        head.pack(fill="x", padx=14, pady=(14, 0))
        self.title_lbl = tk.Label(head, text="Faction", bg=theme.PANEL, fg=theme.INK,
                                  font=theme.FONT_TITLE)
        self.title_lbl.pack(side="left")
        collapse = tk.Label(head, text="▶", bg=theme.PANEL, fg=theme.MUTED,
                            cursor="hand2", font=("Segoe UI", 8))
        collapse.pack(side="right")
        collapse.bind("<Button-1>", lambda e: self._toggle_right_panel())

        # Everything between the title and the pinned bottom controls scrolls,
        # and it is a DRAWN PAGE rather than a widget tree (app/ui/parchment.py).
        # The page borrows this canvas instead of owning one, which is what
        # gives it scrolling for free: there is no inner Frame any more, and so
        # nothing opaque sitting on top of the parchment.
        #
        # The old panel packed straight into the frame, so on an information-
        # dense selection (a village with storage, a herd and seven buildable
        # things) the Build buttons fell off the bottom of the window with no
        # way to reach them at all. That is still what the scrolling is for.
        body = tk.Frame(p, bg=theme.PANEL)
        body.pack(fill="both", expand=True, pady=(6, 0))
        pcanvas = tk.Canvas(body, bg=theme.PANEL, highlightthickness=0)
        pcanvas.pack(side="left", fill="both", expand=True)
        pbar = tk.Scrollbar(body, orient="vertical", command=pcanvas.yview)
        pbar.pack(side="right", fill="y")
        pcanvas.configure(yscrollcommand=pbar.set)
        self._panel_canvas = pcanvas
        self._page = parchment.Page(None, _RIGHT_PANEL_W - 20, seed=2,
                                    canvas=pcanvas)
        pcanvas.bind("<Enter>", lambda e: pcanvas.bind_all(
            "<MouseWheel>", lambda ev: pcanvas.yview_scroll(int(-ev.delta / 120), "units")))
        pcanvas.bind("<Leave>", lambda e: pcanvas.unbind_all("<MouseWheel>"))

        # --- pinned controls: these live on the OUTER panel, below the
        # scrolling body, so the time controls and the view toggles are always
        # on screen no matter how much detail the selection has.
        #
        # A page of its own rather than part of the one above: this is pinned
        # and that one scrolls, so they cannot share a canvas. It is redrawn
        # from state by _render_foot -- every control here has a label that
        # changes (paused/running, which speed, which view, which layer), and
        # a drawn control has no .config() to change one in place.
        foot = tk.Frame(self._panel, bg=theme.PANEL)
        foot.pack(side="bottom", fill="x")
        self._foot_page = parchment.Page(foot, _RIGHT_PANEL_W - 8, seed=9)
        self._foot_page.canvas.pack(fill="x")
        self._panel_foot = foot
        self._back_label = None
        self._back_command = None
        self._render_foot()

    def _render_foot(self):
        """Draw the pinned controls from the current state of the world clock,
        the view mode and the zoom level."""
        page = getattr(self, "_foot_page", None)
        if page is None:
            return
        paused = self.clock.paused if getattr(self, "clock", None) else True
        page.begin(240)
        page.heading(self._foot_date_text(), fill=theme.MUTED)
        page.gap(2)
        # The throttle. Pause reads as the accent because in a real-time game
        # the control that matters is the one that stops it.
        row = [("Resume" if paused else "Pause", self._toggle_pause, "accent")]
        for mult in clock.SPEEDS:
            active = (not paused and getattr(self.clock, "speed", 1.0) == mult)
            row.append((f"{mult:g}x", lambda m=mult: self._set_speed(m),
                        "active" if active else "default"))
        page.button_row(row)
        if self._back_label:
            page.button(self._back_label, self._back_command)
        page.button(f"View: {self.mode.capitalize()}", self._toggle_mode)
        page.button(f"Currents: {'On' if self.show_currents else 'Off'}",
                    self._toggle_currents)
        page.button("View: Surface" if self.layer == layers.UNDER
                    else "View: Underworld", self.toggle_layer)
        page.button("Compendium (F1)", self.open_compendium)
        page.finish()

    def _foot_date_text(self):
        """The date line, and why the world is not moving if it is not."""
        if not getattr(self, "world", None) or not getattr(self, "clock", None):
            return ""
        if self.clock.paused:
            reason = clock.PAUSE_REASON_TEXT.get(self.clock.pause_reason,
                                                 "Paused")
            return f"{self._date_text()} — {reason}"
        if not self.clock.keeping_up:
            return f"{self._date_text()} — running slowly"
        return self._date_text()

    def _toggle_currents(self):
        self.show_currents = not self.show_currents
        self._render_foot()
        self.render()

    def _bind_map_events(self, widget):
        """Wire up the free camera + click/drag/wheel handlers on whichever
        widget is currently the flat map's drawing surface (self.canvas or
        self._flatgl -- see _activate_flatgl). These handlers all work
        purely in terms of self.view/self._place/screen_to_world/
        world_to_screen, not canvas item IDs, so the same functions apply
        unchanged regardless of which one drew the pixels underneath.

        add="+" on <Configure> specifically: pyopengltk's own BaseOpenGLFrame
        already binds <Configure> to its tkResize (glViewport + a redundant
        initgl() call) in its own __init__. A plain .bind() call REPLACES
        that rather than adding to it, which would silently drop tkResize
        for self._flatgl the moment this runs -- harmless in practice
        (gl_flatmap.redraw() sets the viewport itself every frame regardless
        of tkResize ever firing), but there's no reason to depend on that
        and quietly fight a third-party widget's own lifecycle. self.canvas
        (a plain tk.Canvas) has no such existing binding, so add="+" there
        is a no-op, not a behavior change."""
        widget.bind("<Configure>", lambda e: self._on_canvas_configure(), add="+")
        widget.bind("<ButtonPress-1>", self._on_press)
        widget.bind("<B1-Motion>", self._on_drag)
        widget.bind("<ButtonRelease-1>", self._on_release)
        widget.bind("<MouseWheel>", self._on_wheel)
        widget.bind("<Button-3>", self._on_right_click)

    def _on_canvas_configure(self):
        """Redraw, and re-clamp any floating in-game panel so a window resize
        can't strand it outside the visible area."""
        self.render()
        if getattr(self, "_treasury_open", False) and self._treasury_pos:
            f = self.treasury_frame
            self._treasury_pos = self._clamp_to_view(
                *self._treasury_pos, f.winfo_width(), f.winfo_height())
            f.place(x=self._treasury_pos[0], y=self._treasury_pos[1])

    # --- panel collapsing ----------------------------------------------------
    def _toggle_left_panel(self):
        self._left_collapsed = not getattr(self, "_left_collapsed", False)
        self._apply_panel_layout()

    def _toggle_right_panel(self):
        self._right_collapsed = not getattr(self, "_right_collapsed", False)
        self._apply_panel_layout()

    def _apply_panel_layout(self):
        """Place or hide each side panel, leaving a slim always-visible tab in
        its place so a collapsed panel can be brought back."""
        left_hidden = getattr(self, "_left_collapsed", False)
        right_hidden = getattr(self, "_right_collapsed", False)
        if left_hidden:
            self._resource_bar.place_forget()
            self._left_tab.place(x=0, rely=0.5, anchor="w", width=_EDGE_TAB_W, height=90)
            self._left_tab.lift()
        else:
            self._left_tab.place_forget()
            self._resource_bar.place(x=0, y=0, relheight=1.0, width=_LEFT_PANEL_W)
            self._resource_bar.lift()
        if right_hidden:
            self._panel.place_forget()
            self._right_tab.place(relx=1.0, rely=0.5, anchor="e",
                                  width=_EDGE_TAB_W, height=90)
            self._right_tab.lift()
        else:
            self._right_tab.place_forget()
            self._panel.place(relx=1.0, y=0, anchor="ne", relheight=1.0,
                              width=_RIGHT_PANEL_W)
            self._panel.lift()
        self._render_alerts()
        self._place_trade_log()
        # Called once during __init__ before set_world, so there may be no
        # world to draw yet.
        if getattr(self, "world", None) is not None:
            self.render()

    def _build_edge_tabs(self):
        """The slim strips that remain when a side panel is folded away."""
        self._left_tab = tk.Frame(self, bg=theme.PANEL_ALT, cursor="hand2")
        tk.Label(self._left_tab, text="▶", bg=theme.PANEL_ALT, fg=theme.ACCENT,
                 font=theme.FONT_SMALL).place(relx=0.5, rely=0.5, anchor="center")
        self._right_tab = tk.Frame(self, bg=theme.PANEL_ALT, cursor="hand2")
        tk.Label(self._right_tab, text="◀", bg=theme.PANEL_ALT, fg=theme.ACCENT,
                 font=theme.FONT_SMALL).place(relx=0.5, rely=0.5, anchor="center")
        for frame, cb in ((self._left_tab, self._toggle_left_panel),
                          (self._right_tab, self._toggle_right_panel)):
            for wdg in (frame,) + tuple(frame.winfo_children()):
                wdg.bind("<Button-1>", lambda e, c=cb: c())

    def _flat_widget(self):
        """Whichever widget is currently drawing the flat map -- the GPU
        frame once _activate_flatgl has swapped it in, the plain canvas
        otherwise."""
        return self._flatgl if self._use_flatgl else self.canvas



    # --- GPU flat map -----------------------------------------------------
    def _ensure_flatgl(self):
        """Create the GPU flat-map frame on first use. Returns False if this
        machine cannot have one (no GL) or it has already failed, in which
        case the Tk/PIL canvas stays in charge -- tried exactly once
        (_flatgl_tried), not retried every render() the way that would
        otherwise happen given render() calls this on every frame."""
        if self._flatgl is not None:
            return not self._flatgl.failed
        if self._flatgl_tried or not gl_flatmap.gl_available():
            return False
        self._flatgl_tried = True
        try:
            self._flatgl = gl_flatmap.GLFlatMapFrame(self)
        except Exception:
            return False
        self._bind_map_events(self._flatgl)
        return True

    def _activate_flatgl(self):
        self.canvas.pack_forget()
        self._flatgl.pack(fill="both", expand=True)
        # self._flatgl is created lazily on the first render() -- well after
        # the side panels were already built and raised in __init__'s own
        # _apply_panel_layout() call. A newly created/mapped Tk widget goes
        # to the TOP of its parent's stacking order by default, and this one
        # fills the entire MapView area (fill="both", expand=True), so
        # without this it silently sat on top of and completely hid every
        # panel (resource bar, faction panel, alerts, treasury, trade log)
        # the instant the GPU flat map activated -- lower() puts it back at
        # the bottom, exactly where self.canvas always was.
        self._flatgl.lower()
        self._flatgl.update_idletasks()   # winfo_width/height valid immediately
        self._use_flatgl = True

    def _deactivate_flatgl(self):
        """Back to the Tk/PIL canvas -- either GL genuinely isn't available
        on this machine, or self._flatgl started failing after having
        worked (see render()'s own check, which runs every frame rather than
        only once at startup)."""
        self._flatgl.pack_forget()
        self.canvas.pack(fill="both", expand=True)
        self._use_flatgl = False
        self._flat_legend.place_forget()   # canvas draws its own legend

    def _flat_level(self):
        """0/1/2 for world/region/village view -- the flat map's own
        three-tier zoom state, expressed as the int _map_lines/_map_labels
        take. Level 2 is a zoom-scale threshold (see _villages_visible)
        rather than a separate clicked-into mode."""
        if self.zoom_faction is None:
            return 0
        return 2 if self._villages_visible() else 1

    # Temporary diagnostic (see _log_flatgl_timing): kept through this round
    # of investigation to confirm the caching fix below actually removes
    # the rebuild cost rather than just hiding it. Logs a per-step
    # breakdown for any frame slow enough to explain a felt hitch.
    _FLATGL_LOG_THRESHOLD_MS = 20.0

    def _flat_content_signature(self, level, scale):
        """Everything that can actually change what _map_lines/_flat_markers/
        _map_labels produce -- deliberately NOT including self.view (pan
        position): none of those three read the camera's position at all,
        only gl_flatmap's own _wrap_x does (applied at GPU-buffer-pack
        time, inside set_lines/set_markers/set_labels themselves), so
        panning alone can reuse the exact same content forever. `scale` IS
        included because _flat_markers sizes markers off it to hold a
        constant screen size -- zooming genuinely does change that output,
        panning doesn't change scale at all.

        Cheap to compute (attribute reads, no iteration over world data),
        so comparing it every frame to decide whether a rebuild is needed
        costs nothing next to the rebuild itself."""
        wd = self.world
        hint = self._placement_hint_cells
        return (
            wd.turn, getattr(wd, "territory_version", 0), level, round(scale, 3),
            self.mode, self.selected_settlement, self.selected_village,
            self.selected_commander, self.attack_mode, id(self._attack_frontier),
            self.building_mode, tuple(hint) if hint else None,
            # Marching orders. A move order is given to an ALREADY-selected
            # commander, so selected_commander above does not change and the
            # route would not appear until something else forced a rebuild --
            # which, since wd.turn is in here, meant "at the end of the turn".
            # A dozen-odd commanders, three attribute reads each: still cheap
            # enough to compute every frame.
            tuple((c.path_index, len(c.path) if c.path else 0)
                  for c in wd.commanders),
        )

    def _sync_flatgl(self):
        """Push the terrain raster, fog mask, and line/marker/label
        terrain raster, fog mask, and line/marker/label content the Tk
        canvas would draw, in the GPU frame's own terms (see gl_flatmap.py).
        Also refreshes self._place/_canvas_wh/_view_center_x exactly as the
        canvas path does, since screen_to_world/world_to_screen/the click
        handlers all read those regardless of which surface is on screen."""
        g = self._flatgl
        cw, ch = g.winfo_width(), g.winfo_height()
        if cw <= 1 or ch <= 1:
            return
        t_start = time.perf_counter()
        self._ensure_base()
        t_base = time.perf_counter()
        self._ensure_fog_overlay()
        t_fog = time.perf_counter()
        fog_active = self._fog_is_active() and self._fog_overlay_img is not None
        vx0, vy0, vx1, vy1 = self._fit_aspect(self.view, cw / ch)
        scale = cw / (vx1 - vx0)
        self._place = (vx0, vy0, scale)
        self._canvas_wh = (cw, ch)
        self._view_center_x = (vx0 + vx1) / 2
        g.set_map(self._base_img, self._fog_overlay_img if fog_active else None)
        t_set_map = time.perf_counter()
        g.set_view(vx0, vy0, vx1, vy1)
        level = self._flat_level()

        # A pure pan (or a re-render with nothing at all changed) reuses
        # last frame's content wholesale -- see _flat_content_signature and
        # this method's docstring on why that's exactly correct, not an
        # approximation. Flash/move-animation are time-varying and can't be
        # captured by a static signature, so they always force a rebuild
        # while active (both are already short-lived, bounded animations,
        # not something a player spends a sustained drag inside).
        sig = self._flat_content_signature(level, scale)
        structural = sig != self._flat_content_sig
        # A flash (post-battle region highlight) can move a line, so it forces
        # a full rebuild -- but it is a one-shot, not a standing cost.
        flashing = self._flash_region is not None
        # The move animation is the STANDING cost: while the clock runs it
        # re-renders at 30fps for the whole day to slide the movers. But only
        # the movers move -- roads, trade routes and labels are all static
        # between day boundaries (which bump wd.turn, so `structural` catches
        # them). So an animation-only frame rebuilds JUST the markers and
        # reuses last frame's lines and labels, instead of rebuilding all
        # three every frame. This is what took the continuous full-content
        # rebuild (measured ~4-5ms of lines alone in region view, every frame)
        # off the standing render cost that read as lag in the wide views.
        move_animating = self._move_active
        if structural or flashing:
            self._flat_content_sig = sig
            lines = self._map_lines(level, scale=scale)
            markers = self._flat_markers(level)
            labels = self._map_labels(level, region_names=False) + self._flat_labels_extra()
            self._flat_lines_cache = lines
            self._flat_markers_cache = markers
            self._flat_labels_cache = labels
        elif move_animating:
            lines = self._flat_lines_cache
            markers = self._flat_markers(level)   # only the movers slid
            labels = self._flat_labels_cache
            self._flat_markers_cache = markers
        else:
            lines = self._flat_lines_cache
            markers = self._flat_markers_cache
            labels = self._flat_labels_cache
        rebuilt = structural or flashing or move_animating
        t_content = time.perf_counter()

        g.set_lines(lines)
        t_lines_set = time.perf_counter()
        g.set_markers(markers)
        t_markers_set = time.perf_counter()
        g.set_labels(labels)
        t_labels_set = time.perf_counter()
        g.render_now()
        t_render = time.perf_counter()
        total_ms = (t_render - t_start) * 1000
        if total_ms > self._FLATGL_LOG_THRESHOLD_MS:
            self._log_flatgl_timing(
                total_ms,
                ensure_base=(t_base - t_start) * 1000,
                ensure_fog=(t_fog - t_base) * 1000,
                set_map=(t_set_map - t_fog) * 1000,
                rebuilt=1.0 if rebuilt else 0.0,
                content_build=(t_content - t_set_map) * 1000,
                lines_set=(t_lines_set - t_content) * 1000,
                markers_set=(t_markers_set - t_lines_set) * 1000,
                labels_set=(t_labels_set - t_markers_set) * 1000,
                render_now=(t_render - t_labels_set) * 1000,
                n_lines=len(lines), n_markers=len(markers), n_labels=len(labels))
        if self.mode == "political":
            self._flat_legend.place(x=12, y=12)
            # tk.Canvas overrides tkraise/lift to mean tag_raise (a canvas
            # ITEM operation) -- Misc.tkraise (raise this WIDGET in the
            # stacking order, what's actually wanted here) has to be called
            # explicitly to bypass that override.
            tk.Misc.tkraise(self._flat_legend)
        else:
            self._flat_legend.place_forget()

    def _log_flatgl_timing(self, total_ms, **steps):
        """Append one line to flatgl_timing.log next to the exe (see
        app.core.save._app_root -- same reasoning: __file__ isn't writable/
        persistent from inside a PyInstaller --onefile temp dir). Best-
        effort only -- a diagnostic tool must never itself crash the frame
        it's trying to explain."""
        try:
            from app.core.save import _app_root
            import datetime
            path = _app_root() / "flatgl_timing.log"
            parts = " ".join(f"{k}={v:.1f}" for k, v in steps.items())
            line = (f"{datetime.datetime.now().isoformat(timespec='milliseconds')} "
                   f"total={total_ms:.1f}ms {parts}\n")
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line)
        except Exception:
            pass


    def _map_lines(self, level, scale=None):
        """Every path the flat map draws, as (cells, rgb, width_px, dash) for
        the GPU flat map's set_lines (gl_flatmap.py). Pure
        world-state-to-line-list -- it says WHAT to draw, the renderer decides
        where each cell lands on screen. Fog-clipped through the same
        _fog_clip_runs the canvas versions use, so the GPU map never reveals a
        route the canvas would have hidden.

        `scale` is the current world-to-screen zoom (self._place[2]), so
        roads and routes grow thicker zoomed in exactly as the Tk canvas
        already does (_draw_roads etc.): `lw` below carries each line's canvas
        width FACTOR, applied as max(minimum, scale*factor). Passing None
        keeps the fixed pixel widths instead."""
        wd = self.world
        out = []

        def lw(fixed, factor, minimum=1.0):
            return fixed if scale is None else max(minimum, scale * factor)

        def add(cells, color, width, dash=0):
            for run in self._fog_clip_runs(cells):
                if len(run) >= 2:
                    out.append((run, color, width, dash))

        # Stone roads and sea lanes are the trunk network and show at every
        # altitude; dirt tracks are region-scale detail and would be a grey
        # haze from orbit. One factor (0.18) for every tier, matching
        # _draw_roads' own uniform width regardless of tier.
        chains = road_chains(wd)
        runs = [(cells, tier) for region in wd.regions if region.faction_idx >= 0
                for cells, tier in chains.get(region.id, ())]
        # Dirt first so the trunk network lies over it -- same reason as
        # _draw_roads, and it has to match or the two surfaces disagree.
        runs.sort(key=lambda run: _ROAD_DRAW_ORDER.get(run[1], 0))
        for cells, tier in runs:
            if tier not in ("stone", "sea") and level < 2:
                continue
            if tier == "sea":
                color, width = _TRADE_SEA_COLOR, lw(1.8, 0.18)
            elif tier == "stone":
                color, width = _STONE_ROAD_COLOR, lw(2.2, 0.18)
            else:
                color, width = _DIRT_ROAD_COLOR, lw(1.6, 0.18)
            # Fog-clipped on the CELLS, then smoothed per surviving run: the
            # fog mask is a grid, and smoothing first would hand it points
            # between cells it has no answer for.
            for run in self._fog_clip_runs(cells):
                if len(run) < 2:
                    continue
                points = self._road_points(run, tier)
                if tier == "sea":
                    out.append((points, _GL_RGB[color], width, 2))
                    continue
                # Cut then surface, exactly as the canvas draws it -- the two
                # surfaces have to agree or switching renderers changes how
                # the world looks.
                out.append((points, _GL_RGB[_darken(color, _ROAD_CUT_DARKEN)],
                            width * _ROAD_CUT_WIDTH, 0))
                out.append((points, _GL_RGB[color],
                            width if tier == "stone"
                            else width * _DIRT_SURFACE_NARROW,
                            0 if tier == "stone" else 3))

        for r in wd.trade_routes:
            sea = r["kind"] == "sea"
            add(r["cells"],
                _GL_RGB[_TRADE_SEA_COLOR if sea else _TRADE_LAND_COLOR],
                lw(1.8, 0.154) if sea else lw(2.4, 0.22), dash=2)

        for proj in wd.trade_route_projects:
            for seg in proj.built_segments:
                add(seg, _GL_RGB[_TRADE_ROUTE_CONSTRUCTION_COLOR],
                    lw(1.8, 0.18), dash=3)

        # A route with a caravan on it is redrawn brighter on top, exactly as
        # on the flat map -- an active trade lane should be obvious from orbit.
        player_idx = wd.player_faction_idx
        for caravan in wd.trade_caravans:
            mine = player_idx is not None and player_idx in (caravan.seller_idx,
                                                             caravan.buyer_idx)
            if caravan.kind == "sea":
                color, width = _ACTIVE_ROUTE_SEA_COLOR, lw(2.2, 0.187)
            elif caravan.kind == "river":
                color, width = _RIVER_CARAVAN_STYLE["glow"], lw(2.2, 0.22)
            else:
                color, width = _ACTIVE_ROUTE_LAND_COLOR, lw(3.0, 0.286)
            if not mine:
                color = {"sea": _FOREIGN_SEA_CARAVAN_STYLE,
                         "river": _FOREIGN_RIVER_CARAVAN_STYLE}.get(
                             caravan.kind, _FOREIGN_CARAVAN_STYLE)["glow"]
                width = max(1.0, width * 0.5)
            add(caravan.path, _GL_RGB[color], width, dash=2)

        # A commander's queued march. The canvas has drawn this dashed preview
        # since commanders existed (_draw_commanders), but it was never added
        # here -- so on the GPU flat map, giving a move order showed you
        # nothing at all. Same colours and the same fog rules as
        # the canvas: your own in orchid, a rival in his realm's colour, and a
        # foreign march traced only across ground you have actually explored
        # (add() fog-clips, which is exactly the leak that matters -- an
        # unclipped line would give away where he is going through country you
        # cannot see).
        for cmd in wd.commanders:
            if not getattr(cmd, "path", None):
                continue
            remaining = self._visible_route(cmd)
            if len(remaining) < 2:
                continue
            mine = player_idx is not None and cmd.faction_idx == player_idx
            if mine:
                colour = _GL_RGB[_COMMANDER_STYLE["fill"]]
                width = lw(2.0, 0.19)
            else:
                if not self._on_layer(cmd) or not self._revealed_here(*self._display_cell(cmd)):
                    continue
                colour = _GL_RGB[wd.factions[cmd.faction_idx].color]
                width = lw(1.5, 0.14)
            add(remaining, colour, width, dash=2)

        # Weather: the affected region outlined in its own colour. Drawn
        # before the attack frontier so a region you are about to attack
        # still reads as a target first -- war beats weather on a war map.
        for region, event in self._weathered_regions():
            colour = _WEATHER_MAP_COLOR.get(event.kind)
            if not colour:
                continue
            severe = event.severity == weather_mod.SEVERE
            # Separate MINIMUMS, not just separate factors. A shared floor
            # swallowed the difference at world scale -- both severities
            # clamped to the same width, so from orbit a mild fog and a
            # severe blizzard drew identically. Severity has to read at the
            # zoom where you are deciding whether to march.
            for x0, y0, x1, y1 in self._region_border_segments(region):
                out.append(([(x0, y0), (x1, y1)], _GL_RGB[colour],
                            lw(2.4, 0.26, minimum=2.2) if severe
                            else lw(1.6, 0.17, minimum=1.2),
                            0 if severe else 3))

        if self.attack_mode is not None:
            for region in self._attack_frontier:
                for x0, y0, x1, y1 in self._region_border_segments(region):
                    out.append(([(x0, y0), (x1, y1)], _GL_RGB[theme.BAD],
                                lw(2.6, 0.3, minimum=2.0), 0))

        # In-progress road construction (see _draw_construction): only the
        # portion actually built so far, same as the canvas draws it.
        for road in wd.road_projects:
            if len(road.built_cells) >= 2:
                add(road.built_cells, _GL_RGB[_DIRT_ROAD_COLOR], lw(1.6, 0.18), dash=2)

        # Battle-outcome border flash (see _draw_flash): gold for a region
        # gained, red for a failed attack, fading/pulsing over its lifetime.
        if self._flash_region is not None:
            elapsed = time.time() - self._flash_start
            envelope = max(0.0, 1.0 - elapsed / _FLASH_DURATION)
            pulse = abs(math.sin(elapsed * _FLASH_FREQ * math.pi))
            fade = envelope * (0.35 + 0.65 * pulse)
            target_255 = (_FLASH_FAIL_COLOR if self._flash_outcome == "failure"
                         else _FLASH_COLOR)
            base_255 = _hex_to_rgb(theme.CANVAS)
            color = tuple((base_255[i] + (target_255[i] - base_255[i]) * fade) / 255.0
                         for i in range(3))
            width = lw(2.0 + 4.0 * fade, 0.18 + 0.35 * fade, minimum=2.0)
            for x0, y0, x1, y1 in self._region_border_segments(self._flash_region):
                out.append(([(x0, y0), (x1, y1)], color, width, 0))
        return out



    def _map_labels(self, level, cull=None, region_names=True):
        """Names and alert badges, by zoom level: realms at world view,
        regions at region view, settlements and villages at village view.
        Same reasoning as _map_lines -- this is world-state-to-label-list,
        and the renderer decides where each label lands.

        `cull`, when given, is a point-list -> bool-array culling test; the
        GPU map passes None, since an orthographic viewport clips off-screen
        geometry on its own for free.

        `region_names` gates the level-1 branch below. An orthographic camera
        can put an ENTIRE developed kingdom on screen at once with nothing
        bounding the label count -- exactly the "realm view used to label
        every single
        region... dozens of names stacked over the terrain" problem
        _draw_labels' own docstring describes fixing on the canvas years ago
        (it now shows region names nowhere at all, only nation names at
        world view). The flat map passes region_names=False to match that
        already-settled call, rather than reintroducing the clutter (and the
        real per-frame cost of rebuilding hundreds of text-glyph instances
        while panning a large realm) that the canvas deliberately dropped."""
        wd = self.world
        out = []

        def add(items, px, color, dy):
            if not items:
                return
            mask = cull([pos for _, pos in items]) if cull is not None else None
            for i, (text, pos) in enumerate(items):
                if mask is None or mask[i]:
                    out.append((pos[0], pos[1], text, color, px, dy))

        if level == 0:
            factions = [f for f in wd.factions
                       if self._is_known(f) and not is_eliminated(f)]
            player_idx = wd.player_faction_idx
            if player_idx is not None:
                factions.sort(key=lambda f: f is not wd.factions[player_idx])
            # Same declutter the flat map's world view needs (see
            # MapView._draw_labels): on a crowded map, realms whose capitals
            # sit close together project to overlapping, unreadable names
            # from orbit. There's no live canvas here to bbox-check against,
            # so this uses a coarser world-space minimum separation instead
            # -- orbit view only needs "don't stack two names on each
            # other," not pixel-exact spacing -- and the player's own
            # kingdom is placed first so it's never the one dropped.
            min_sep = wd.w * 0.035
            placed_pts = []
            kept = []
            for f in factions:
                cx, cy = f.center[0] * wd.w, f.center[1] * wd.h
                if any(wrap.dist_wrap((cx, cy), (px, py), wd.w) < min_sep
                      for px, py in placed_pts):
                    continue
                placed_pts.append((cx, cy))
                kept.append(f)
            add([(f.name, (f.center[0] * wd.w, f.center[1] * wd.h))
                 for f in kept],
                15.0, _GL_LABEL_COLOR, -14.0)
        elif level == 1:
            # region_names=False (the flat map -- see this method's own
            # docstring) means genuinely nothing at this level, NOT a
            # fall-through to the settlement/village branch below -- level 1
            # is its own exclusive case regardless of what it draws.
            if region_names:
                add([(r.name, (r.center[0] * wd.w, r.center[1] * wd.h))
                     for r in wd.regions
                     if r.faction_idx >= 0 and self._is_known(wd.factions[r.faction_idx])
                     and self._cell_revealed(int(r.center[0] * wd.w),
                                             int(r.center[1] * wd.h))],
                    12.0, _GL_LABEL_COLOR, -10.0)
        else:
            add([(st.name, st.pos) for st in wd.settlements
                 if self._node_visible(st)],
                12.0, _GL_LABEL_COLOR, 14.0)
            # Village names only once there are few enough to read. The whole
            # facing hemisphere of a developed realm is hundreds of them, which
            # is label soup rather than information -- the same reason the flat
            # map gates them on _VILLAGE_LABEL_LIMIT.
            villages = [(v.name, v.pos) for v in wd.villages
                        if self._node_visible(v)]
            if villages:
                count = (int(cull([pos for _, pos in villages]).sum())
                         if cull is not None else len(villages))
                if count <= _VILLAGE_LABEL_LIMIT:
                    add(villages, 9.0, _GL_VILLAGE_LABEL_COLOR, 10.0)

        # Alerts ride on the same text path rather than getting their own
        # geometry: a "!" over the marker is the badge, and it is legible at
        # any altitude the settlement itself is drawn at.
        if level >= 1 and self._alert_node_ids:
            alerts = self._alert_node_ids
            for critical in (True, False):
                colour = _GL_RGB[theme.BAD if critical
                                    else self._ALERT_WARN_COLOR]
                add([("!", n.pos)
                     for nodes in (wd.settlements, wd.villages) for n in nodes
                     if (alerts.get(id(n)) == "critical") == critical
                     and id(n) in alerts and self._cell_revealed(*n.pos)],
                    14.0, colour, -12.0)

        # Weather badges. Only from region view in: at world scale a dozen
        # of these over a continent is confetti, and the outline in
        # _map_lines already says "something is happening here" from orbit.
        if level >= 1:
            for region, event in self._weathered_regions():
                glyph = _WEATHER_GLYPH.get(event.kind)
                if not glyph:
                    continue
                severe = event.severity == weather_mod.SEVERE
                add([(f"{glyph} {event.label}",
                      (region.center[0] * wd.w, region.center[1] * wd.h))],
                    13.0 if severe else 11.0,
                    _GL_RGB[_WEATHER_MAP_COLOR[event.kind]], 22.0)

        # Attack-target region names (see _draw_attack_targets) -- the
        # border highlight itself is in _map_lines, this is just the label.
        if self.attack_mode is not None and self._attack_frontier:
            add([(r.name, (r.center[0] * wd.w, r.center[1] * wd.h))
                 for r in self._attack_frontier],
                12.0, _GL_LABEL_COLOR, 0.0)
        return out

    _SETTLE_SHAPE = {"city": SHAPE_CIRCLE, "castle": SHAPE_TRIANGLE, "town": SHAPE_SQUARE}

    def _flat_markers(self, level):
        """Everything the flat map draws as a point marker, as
        (cell_x, cell_y, radius_world_units, (r,g,b), shape) for
        gl_flatmap's set_markers -- the GPU equivalent of what the canvas
        draws. Shape is carried by gl_flatmap's own marker shader
        (SHAPE_CIRCLE/TRIANGLE/SQUARE/DIAMOND/HULL), which reproduces the
        canvas's city/castle/town/commander/ship silhouettes directly, and
        size comes from _marker_radius's screen-pixel-clamped rule, so a
        marker is exactly as legible at any zoom as it is on the canvas.

        No camera-culling here: an orthographic viewport clips off-screen
        instances on the GPU for free, and at flat-map scale (hundreds, not
        tens of thousands, of markers) there is no reason to spend CPU time
        pre-filtering them."""
        wd = self.world
        scale = self._place[2]
        marks = []

        # Gates, on BOTH layers. A door you cannot find is a door that does
        # not exist -- and on the surface it is the only sign that there is
        # anything under that mountain at all.
        for gate in getattr(wd, "gates", ()):
            gx, gy = gate["pos" if self.layer == layers.SURFACE else "under"]
            marks.append((gx, gy, max(2.0, 6.0 / scale),
                          tuple(c / 255.0 for c in _UNDER_GATE_RGB),
                          SHAPE_DIAMOND))

        def px(screen_r):
            """Screen-pixel radius -> world-unit size for set_markers: the
            same orthographic projection that places the marker also
            multiplies this by `scale`, so passing screen_r/scale here
            reproduces exactly screen_r pixels on screen regardless of
            zoom -- the constant-screen-size behaviour _marker_radius and
            the ships/commanders/caravans' fixed "r" already give the
            canvas."""
            return screen_r / scale

        def ring(cx, cy, screen_r):
            marks.append((cx, cy, px(screen_r + 3), (1.0, 1.0, 1.0), SHAPE_CIRCLE))

        # Settlements: city = circle, castle = triangle, town = square,
        # matching _draw_settlements' own shape-per-kind exactly.
        if self.zoom_faction is not None:
            sids = [sid for sid in self.zoom_faction.meta.get("settlements", [])
                    if self._node_visible(wd.settlements[sid])]
        else:
            sids = [s.id for s in wd.settlements if s.kind == "city"
                    and self._node_visible(s)]
        for sid in sids:
            st = wd.settlements[sid]
            style = _SETTLE_STYLE[st.kind]
            r = self._marker_radius(style["base"])
            if st is self.selected_settlement:
                ring(st.pos[0] + 0.5, st.pos[1] + 0.5, r)
            marks.append((st.pos[0] + 0.5, st.pos[1] + 0.5, px(r),
                         _GL_RGB[style["fill"]], self._SETTLE_SHAPE[st.kind]))

        if level >= 2:
            zf = wd.factions.index(self.zoom_faction)
            r = self._marker_radius(_VILLAGE_STYLE["base"])
            for v in wd.villages:
                if v.faction_idx != zf or not self._node_visible(v):
                    continue
                if v is self.selected_village:
                    ring(v.pos[0] + 0.5, v.pos[1] + 0.5, r)
                marks.append((v.pos[0] + 0.5, v.pos[1] + 0.5, px(r),
                             _GL_RGB[_VILLAGE_STYLE["fill"]], SHAPE_CIRCLE))

        # Commanders: diamond, player's own kept orchid.
        cr = _COMMANDER_STYLE["r"]
        for cmd in wd.commanders:
            if not self._on_layer(cmd):
                continue        # gone below, or still up there
            mine = cmd.faction_idx == wd.player_faction_idx
            if mine:
                color = _GL_RGB[_COMMANDER_STYLE["fill"]]
            else:
                if not self._revealed_here(*self._display_cell(cmd)):
                    continue
                color = _GL_RGB[wd.factions[cmd.faction_idx].color]
            cx, cy = self._display_pos(cmd)
            if cmd is self.selected_commander:
                ring(cx + 0.5, cy + 0.5, cr)
            marks.append((cx + 0.5, cy + 0.5, px(cr), color, SHAPE_DIAMOND))

        # Ships not currently carrying a commander (one being sailed is
        # already represented by its Commander marker) -- hull shape.
        aboard_ids = {cmd.aboard_ship_id for cmd in wd.commanders
                     if cmd.aboard_ship_id is not None}
        sr = _SHIP_STYLE["r"]
        for ship in wd.ships:
            if ship.id in aboard_ids:
                continue
            sx, sy = self._display_pos(ship)
            marks.append((sx + 0.5, sy + 0.5, px(sr), _GL_RGB[_SHIP_STYLE["fill"]],
                         SHAPE_HULL))

        # Trade caravans, yours or foreign, land/sea/river.
        for caravan in wd.trade_caravans:
            if not self._cell_revealed(*self._display_cell(caravan)):
                continue
            style = self._caravan_style(caravan)
            cx, cy = self._display_pos(caravan)
            marks.append((cx + 0.5, cy + 0.5, px(style["r"]), _GL_RGB[style["fill"]],
                         SHAPE_CIRCLE))

        # Settlement placement hint (see _score_placement_hint) -- advisory
        # gold dots over a region's best-scoring cells while a City/Town/
        # Castle is armed to place.
        if self.building_mode is not None and self._placement_hint_cells:
            for x, y in self._placement_hint_cells:
                marks.append((x + 0.5, y + 0.5, px(4.0), _GL_RGB["#ffec78"], SHAPE_CIRCLE))

        # In-progress settlement construction sites (see _draw_construction).
        for project in wd.settlement_projects:
            marks.append((project.pos[0] + 0.5, project.pos[1] + 0.5, px(4.0),
                         _GL_RGB["#f2e9c9"], SHAPE_CIRCLE))

        # Forest/mountain terrain-symbol glyphs (see _draw_terrain_symbols):
        # same jittered per-cell sampling, screen-spacing formula and
        # _TERRAIN_SYMBOL_MAX_COUNT cap, just emitted as small triangle
        # markers instead of vector polygons -- a GPU instance is cheap
        # regardless of count, so none of _draw_terrain_symbols' own
        # cost-driven tuning is a concern here, only its visual density.
        if self.mode == "political":
            cw, ch = self._canvas_wh
            vx0, vy0, _ = self._place
            vx1, vy1 = vx0 + cw / scale, vy0 + ch / scale
            bx0, bx1 = int(math.floor(vx0)), int(math.ceil(vx1))
            by0 = max(0, int(math.floor(vy0)))
            by1 = min(wd.h, int(math.ceil(vy1)))
            spacing = max(_TERRAIN_SYMBOL_MIN_WORLD_SPACING,
                         round(_TERRAIN_SYMBOL_SCREEN_SPACING / max(scale, 0.01)))
            visible_area = max(1, (bx1 - bx0) * (by1 - by0))
            area_spacing = math.ceil(math.sqrt(visible_area / _TERRAIN_SYMBOL_MAX_COUNT))
            spacing = max(spacing, area_spacing)
            sym_r = max(2.5, scale * spacing * 0.22)
            gy0 = by0 - by0 % spacing
            gx0 = bx0 - bx0 % spacing
            forest_rgb = _GL_RGB[_FOREST_SYMBOL_FILL]
            mountain_rgb = _GL_RGB[_MOUNTAIN_SYMBOL_FILL]
            for gy in range(gy0, by1, spacing):
                for gx in range(gx0, bx1, spacing):
                    wx = gx % wd.w
                    if (wd.owner[gy][wx] == OCEAN or (wx, gy) in wd.river_cells
                            or (wx, gy) in wd.lake_cells):
                        continue
                    if not self._cell_revealed(wx, gy):
                        continue
                    biome = wd.biome_grid[gy][wx]
                    if biome not in ("forest", "mountain"):
                        continue
                    jx = self._terrain_jitter(wx, gy, 1) * spacing * 0.7
                    jy = self._terrain_jitter(wx, gy, 2) * spacing * 0.7
                    color = forest_rgb if biome == "forest" else mountain_rgb
                    marks.append((gx + 0.5 + jx, gy + 0.5 + jy, px(sym_r), color,
                                 SHAPE_TRIANGLE))
        return marks

    def _flat_labels_extra(self):
        """Construction-site kind/turns-left captions -- the one bit of
        _draw_construction's text that _map_labels has no natural home for
        (it isn't a name, alert, or region caption). Concatenate with
        _map_labels(level)'s own output when feeding gl_flatmap.set_labels."""
        wd = self.world
        return [(project.pos[0] + 0.5, project.pos[1] + 0.5,
                f"{project.kind[0].upper()}·{project.turns_left}t",
                (0.95, 0.91, 0.79), 7.0, 10.0)
                for project in wd.settlement_projects]

    def _caravan_style(self, caravan):
        """The marker style for a caravan -- yours or somebody else's, by
        kind."""
        mine = (self.world.player_faction_idx is not None
                and self.world.player_faction_idx in (caravan.seller_idx,
                                                      caravan.buyer_idx))
        if caravan.kind == "sea":
            return _SEA_CARAVAN_STYLE if mine else _FOREIGN_SEA_CARAVAN_STYLE
        if caravan.kind == "river":
            return _RIVER_CARAVAN_STYLE if mine else _FOREIGN_RIVER_CARAVAN_STYLE
        return _CARAVAN_STYLE if mine else _FOREIGN_CARAVAN_STYLE




    _MODES = ["political", "fertility", "elevation", "biome", "climate"]

    def _toggle_mode(self):
        self.mode = self._MODES[(self._MODES.index(self.mode) + 1) % len(self._MODES)]
        self._render_foot()
        self._base_key = None
        self.render()

    def _update_turn_label(self):
        """One label, one writer. It used to say "Year 6 - Turn 568 - Autumn",
        which was the truth in a game whose unit of time was a button press;
        now it is the date AND what the clock is doing, and that lives in
        _refresh_time_controls."""
        self._refresh_time_controls()

    def open_compendium(self):
        """Create-or-raise: repeated presses (button or the F1 shortcut in
        app.py) focus the existing window instead of spawning duplicates."""
        if self._compendium_window is not None and self._compendium_window.winfo_exists():
            self._compendium_window.deiconify()
            self._compendium_window.lift()
            self._compendium_window.focus_set()
            return
        self._compendium_window = CompendiumWindow(self)

    # --- driving the clock from the panel ------------------------------------
    def _toggle_pause(self):
        self.clock.toggle_pause()
        if not self.clock.paused:
            # Real time spent paused is not world time owed. Without this,
            # coming back from a long pause pays out every second of it at
            # once (the clock caps the backlog, so it is a burst rather than
            # a flood -- but a burst is still not what pausing meant).
            self.clock.forgive_backlog()
            self._last_frame = time.monotonic()
        audio.play("click")
        self._refresh_time_controls()

    def _set_speed(self, mult):
        was_paused = self.clock.paused
        self.clock.set_speed(mult)
        if was_paused:
            self.clock.forgive_backlog()
            self._last_frame = time.monotonic()
        audio.play("click")
        self._refresh_time_controls()

    def _refresh_time_controls(self):
        """Say what the clock is doing, including when it is not keeping up.

        A world quietly running at half the speed on the button reads as the
        game being broken, so `keeping_up` is surfaced rather than hidden.

        One call now: the pinned controls are a drawn page, so "update the
        pause button, the four speed buttons and the date line" is "draw the
        foot again" -- there is nothing to config() in place."""
        self._render_foot()

    def _date_text(self):
        year = resources.current_year(self.world.turn)
        day = (self.world.turn - 1) % resources.TURNS_PER_SEASON + 1
        return f"{self.world.season} {day}, Year {year}"

    # --- end-turn movement animation -----------------------------------------
    # Caravans, shipments, commanders and ships used to TELEPORT: End Turn
    # advanced them several cells and the next render simply drew them
    # somewhere else. Everything that moves along a path now slides along that
    # path instead, over a fixed wall-clock window, so a turn reads as things
    # travelling rather than as the map being redealt.
    #
    # This is a VIEW-only effect. Nothing in app/world knows it exists: the
    # turn resolves exactly as before and the animation replays the ground it
    # covered. That matters -- the sim stays deterministic and the animation
    # can be shortened, lengthened or skipped without touching game state.

    @staticmethod
    def _mover_track(obj):
        """(path_in_travel_order, fraction_along_it) for anything that moves
        along a stored route, or (None, None) for a mover whose route the view
        cannot see (a beached ship, say, which just changes cell).

        Deliberately duck-typed rather than isinstance'd on the three mover
        classes: caravans and regional shipments already express position as
        turn_progress/turns_total along `path`, commanders as an index into
        one, and anything added later that follows either shape animates
        without this needing to be told about it."""
        path = getattr(obj, "path", None)
        if not path or len(path) < 2:
            return None, None
        total = getattr(obj, "turns_total", None)
        if total:
            frac = min(1.0, getattr(obj, "turn_progress", 0) / max(1, total))
            if getattr(obj, "leg", "outbound") == "return":
                return list(reversed(path)), frac
            return path, frac
        index = getattr(obj, "path_index", None)
        if index is None:
            return None, None
        return path, index / (len(path) - 1)

    def _movers(self):
        wd = self.world
        return (list(wd.trade_caravans) + list(getattr(wd, "regional_shipments", ()))
                + list(wd.commanders) + list(wd.ships))

    def _movement_snapshot(self):
        """Where everything stands BEFORE the turn resolves: the route it is
        on, how far along it is, its leg, and its plain cell as a fallback.

        The mover itself is kept in the snapshot, and that is load-bearing, not
        bookkeeping. Keying on id() alone is a trap here: a shipment that
        delivers during the turn is freed, and CPython hands its address
        straight to the next object allocated -- measured on dev560, 18 brand
        new shipments a turn inherited the id of one that had just arrived and
        were animated from the dead one's position, halfway across the map.
        Holding the reference keeps the old id un-reusable for as long as the
        snapshot needs it to be unique."""
        snap = {}
        for obj in self._movers():
            path, frac = self._mover_track(obj)
            snap[id(obj)] = (obj, path, frac, getattr(obj, "leg", None),
                             tuple(obj.pos))
        return snap

    def _movement_tracks(self, snap):
        """[(mover, t -> (x, y)), ...] for the turn that just resolved.

        A mover still on the same route slides along it; one that arrived and
        dropped its route (a commander does) runs to the end of the route it
        had; anything else -- newly dispatched, or with no route at all --
        eases straight from where it was to where it is."""
        w = self.world.w
        tracks = []
        for obj in self._movers():
            path, frac = self._mover_track(obj)
            before = snap.get(id(obj))
            if before is not None and before[0] is not obj:
                before = None            # an id that outlived its object
            _, path0, frac0, leg0, pos0 = before or (None, None, 0.0, None, None)
            if path is None and path0 is not None:
                path, frac = path0, 1.0     # arrived; its route is gone now
            if path is not None:
                # A caravan that turned for home this turn did not travel: it
                # is standing at the buyer, which is fraction 1 of the outbound
                # path and fraction 0 of the reversed one. Carrying frac0
                # across would send it back to the seller to start again.
                same_route = (before is not None and path0 is not None
                              and len(path0) == len(path)
                              and getattr(obj, "leg", None) == leg0)
                start = frac0 if same_route else 0.0
                if abs(frac - start) < 1e-6:
                    continue
                tracks.append((obj, _PathWalk(path, start, frac, w)))
            elif pos0 is not None and tuple(obj.pos) != pos0:
                tracks.append((obj, _Lerp(pos0, tuple(obj.pos), w)))
        return tracks

    def _move_anim_seconds(self):
        """How long this day's movement should take to draw: exactly as long
        as the day itself, so movers are still travelling when the next day's
        travel is handed to them and the motion never stops.

        Falls back to the fixed window whenever there is no running clock to
        match -- paused, or a day stepped by hand."""
        if self.clock.paused or self.clock.speed <= 0:
            return _MOVE_ANIM_SECONDS
        return max(_MOVE_ANIM_MIN_SECONDS,
                   self.clock.seconds_per_day / self.clock.speed)

    def _start_move_animation(self, tracks):
        """Hand the driver a new day's worth of slides. It does NOT run a timer
        -- the one world loop (_on_frame) walks these every frame. All this does
        is install the tracks and anchor the slide's clock so it plays from the
        start; the driver draws the t=0 frame on this same tick, before anything
        can paint the movers at their final cells."""
        self._move_tracks = tracks or ()
        self._last_slide_frac = None      # force the first frame to draw
        if not tracks:
            self._anim_pos = {}
            self._move_active = False
            return
        if self.clock.paused or self.clock.speed <= 0:
            # Stepped by hand (E) or a slide finishing under a pause: there is
            # no running day-length to lock to, so fall back to the fixed
            # wall-clock window, eased so a caravan pulls away and settles.
            self._move_seconds = self._move_anim_seconds()
            self._move_t0 = time.monotonic()
        else:
            # Running: anchor to the continuous display clock. frac then grows
            # 0 -> 1 as exactly one day is demanded, and wraps cleanly to the
            # next day's slide because that slide starts where this one ends.
            self._anim_day_base = self._sim_days
        self._update_anim_positions()

    def _slide_frac(self):
        """How far through the current day's travel to draw, 0..1.

        Running: the continuous display clock (locked to world speed). Paused /
        hand-stepped: a fixed wall-clock window, since there is no day pace to
        match."""
        if self.clock.paused or self.clock.speed <= 0:
            window = self._move_seconds or _MOVE_ANIM_SECONDS
            t = min(1.0, (time.monotonic() - self._move_t0) / window)
            # Smoothstep only here: easing every running day would put a stop
            # and a start back into travel that is meant to be continuous.
            return t * t * (3.0 - 2.0 * t)
        return max(0.0, min(1.0, self._sim_days - self._anim_day_base))

    def _update_anim_positions(self):
        """Recompute each mover's drawn position for this frame. The single
        writer of _anim_pos; called once per frame by the driver (and once more
        the instant a new day's tracks arrive, to land the t=0 frame).

        Sets _move_active when a position actually changed, which is both the
        driver's "redraw this frame" cue and the marker-rebuild signal the flat
        map reads (see _sync_flatgl) -- so a settled slide stops costing frames."""
        tracks = self._move_tracks
        if not tracks:
            self._move_active = bool(self._anim_pos)   # one frame to clear stale movers
            self._anim_pos = {}
            return
        frac = self._slide_frac()
        if frac == self._last_slide_frac:
            self._move_active = False                  # settled: nothing moved
            return
        self._last_slide_frac = frac
        self._anim_pos = {id(obj): walk(frac) for obj, walk in tracks}
        self._move_active = True

    def _stop_move_animation(self):
        """Drop the slide in flight and put every mover back on its real cell.
        Called on leaving the view (and by reset_frame_clock), so a half-
        finished slide can never be left showing a position the world has
        already moved on from."""
        self._move_active = bool(self._anim_pos)   # need one draw to clear them
        self._move_tracks = ()
        self._anim_pos = {}
        self._last_slide_frac = None

    def _display_pos(self, obj):
        """Where to DRAW a mover: its animated position while an end-turn
        animation is running, otherwise the cell it actually occupies."""
        return self._anim_pos.get(id(obj)) or obj.pos

    def _display_cell(self, obj):
        """_display_pos snapped to a whole cell -- what the fog tests want, so
        a caravan mid-slide is gated on the ground it is crossing rather than
        on the cell it will end the turn in."""
        x, y = self._display_pos(obj)
        return wrap.wrap_x(int(x), self.world.w), max(0, min(self.world.h - 1, int(y)))

    # --- the world clock ------------------------------------------------------
    # The turn-based build ran a whole day in one 425ms call on a worker
    # thread, behind a full-frame overlay that ate every click, because
    # nothing could safely look at the world while it moved. Real time deletes
    # all of that: the day is stepped a slice at a time on THIS thread between
    # frames (app/world/turn_runner.py), so there is never a moment when the
    # world is half-updated and something else is reading it.
    #
    # One driver, running for the life of the view: tick the clock, spend what
    # it owes on the day in progress, and draw. Speed is a budget, not a
    # negotiation -- see app/core/clock.py's demand/supply note.
    def _on_frame(self):
        try:
            now = time.monotonic()
            dt = min(0.25, now - self._last_frame)   # a stall (a battle, a
            self._last_frame = now                   # drag, a load) must not
            self._advance_world(dt)                  # cash in as world time
            # One loop, one draw. The movement slide is not its own timer any
            # more (that second loop stopped rescheduling itself the instant a
            # slide finished, which is where the freeze-then-jump lived); the
            # driver recomputes where the movers are and redraws every frame it
            # needs to.
            self._update_anim_positions()
            if self._should_render_frame():
                self.render()
        finally:
            self._frame_id = self.after(_FRAME_MS, self._on_frame)

    def _should_render_frame(self):
        """Whether this frame changed anything worth redrawing. Movement in
        progress always is; a paused, idle map is not (its own flash/zoom loops
        drive their own redraws)."""
        if self.world is None:
            return False
        return bool(self._move_active)

    def _advance_world(self, dt):
        if self.world is None:
            return
        self.clock.tick(dt)
        # The display clock tracks the SAME demand the sim clock does, so the
        # movement slide advances at exactly the world's pace. Uncapped on
        # purpose: it is what the drawn position is measured against, not a
        # debt anything has to pay off.
        if not self.clock.paused:
            self._sim_days += dt * self.clock.speed / self.clock.seconds_per_day
        if not self.runner.busy and self.clock.pending < 1.0:
            return
        if not self.runner.busy:
            self._begin_day()
            self._day_started = time.monotonic()
        if self.runner.step(self._budget_ms(dt)):
            # Rolling estimate of what a day costs on this world, which is what
            # paces the slices. Weighted toward the recent past so it follows a
            # world that is growing rather than averaging over its whole life.
            cost = (time.monotonic() - self._day_started) * 1000.0
            self._day_ms_estimate = (self._day_ms_estimate * 0.7 + cost * 0.3
                                     if self._day_ms_estimate else cost)
            self.clock.day_done()
            self._finish_day()

    def _budget_ms(self, dt):
        """How much of this frame the world may have.

        PACED to the day's own deadline rather than spent as fast as it will
        go. Taking a fixed slice every frame until the day is finished and
        then idling is bursty by construction: at 1x a day is due every 2.4s
        and costs about 400ms, so the world would work flat out for half a
        second and then do nothing for two -- and the half second is where
        every dropped frame lives.

        Instead each frame gets the fraction of the day that this frame is
        worth. The estimate is a rolling average of what days have actually
        cost on THIS world, so a small map is cheap and a late-game one is
        not, without anybody guessing.

        Floored, so a day always creeps forward and cannot stall; capped, so
        the map is still drawn on a world that cannot keep up (the clock
        reports that separately -- see clock.keeping_up)."""
        day_seconds = self.clock.seconds_per_day / max(0.001, self.clock.speed)
        share = min(1.0, dt / day_seconds) if day_seconds > 0 else 1.0
        want = self._day_ms_estimate * share
        return max(_MIN_BUDGET_MS, min(_MAX_BUDGET_MS, want))

    def _begin_day(self):
        """Everything that has to be captured BEFORE the day happens."""
        self._turn_pending = (self._current_resource_snapshot(),
                              resources.current_year(self.world.turn),
                              self._movement_snapshot())
        self.runner.begin_day()

    def reset_frame_clock(self):
        """Forget how long it has been since the last frame.

        Anything that stops the driver for a stretch -- a battle, a load, a
        pause menu -- must call this on the way back, or the first frame
        afterwards reports the whole gap as elapsed time and the world lurches
        forward. The 0.25s clamp in _on_frame bounds the damage; this removes
        it."""
        self._last_frame = time.monotonic()
        # The display clock resets in step with the frame clock: a battle (or a
        # load, or the pause menu) is a stretch the world was NOT simulated, so
        # the days it would have "demanded" during it are not owed. A stale
        # _sim_days would make the first day back start its slide already
        # part-run -- the specific seam that made movement go choppy again right
        # after a battle.
        self._sim_days = 0.0
        self._anim_day_base = 0.0
        self._stop_move_animation()

    def skip_a_day(self):
        """Run the rest of today and one more, whatever the clock is doing --
        the turn-based cadence, kept for testing and for anyone who wants to
        step the world by hand while it is paused."""
        if self.runner.busy:
            self.runner.finish_day()
            self._finish_day()
        self._begin_day()
        self.runner.finish_day()
        self._finish_day()

    def _finish_day(self):
        """A day has just finished: report it, refresh the panels, and set the
        movers going toward where the day put them.

        This is what used to run when the background turn came back, minus
        everything that existed only to manage the worker and its overlay."""
        try:
            before, prev_year, movement = self._turn_pending
            after = self._current_resource_snapshot()
            self._resource_deltas = {r: after.get(r, 0) - before.get(r, 0)
                                      for r in set(before) | set(after)}
            self._report_trade_events()
            self._report_regional_trade_events()
            self._log_trade_events()

            new_year = resources.current_year(self.world.turn)
            if new_year != prev_year:
                year_deltas = {r: after.get(r, 0) - self._year_start_snapshot.get(r, 0)
                              for r in set(after) | set(self._year_start_snapshot)}
                pop_now = self._current_population_total()
                pop_delta = pop_now - self._year_start_population
                self._show_year_banner(new_year, year_deltas, pop_delta)
                self._year_start_snapshot = after
                self._year_start_population = pop_now

            # The full panel rebuild is THROTTLED now. It tears down and
            # rebuilds the realm/resource/trade panels, which was fine once a
            # turn on a button press and is a permanent flicker at a day every
            # couple of seconds. The cheap readouts still update every day.
            now = time.monotonic()
            if (now - self._last_panel_refresh) * 1000.0 >= _PANEL_REFRESH_MS:
                self._last_panel_refresh = now
                self.refresh()
            else:
                self._refresh_time_controls()
                self.render()
            # After the redraw: the first animated frame has to be the one that
            # lands on screen or movers flash at their destination before
            # setting off back to where they came from.
            self._start_move_animation(self._movement_tracks(movement))
            if self.on_turn_settled is not None:
                self.on_turn_settled()
        finally:
            self._turn_pending = None

    def _report_regional_trade_events(self):
        """Same idea as _report_trade_events, for Phase 11's domestic
        cross-region settlement trade — a separate event list (see
        resources.advance_turn) since these describe one faction trading
        with itself (a single faction_idx, an origin/dest settlement pair)
        rather than the seller/buyer-faction shape foreign trade uses."""
        player_idx = self.world.player_faction_idx
        if player_idx is None:
            return
        for ev in self.world.regional_trade_events:
            if ev["faction_idx"] != player_idx:
                continue
            etype = ev["type"]
            if etype == "regional_dispatched" and ev["price"] > 0:
                msg = (f"{ev['origin_name']} ships {ev['quantity']} {ev['resource']} to "
                       f"{ev['dest_name']} for "
                       f"{self._payment_desc(ev.get('payment'), ev['price'])}.")
            elif etype == "regional_dispatched":
                msg = (f"{ev['origin_name']} ships {ev['quantity']} {ev['resource']} to "
                       f"{ev['dest_name']}.")
            elif etype == "regional_delivered":
                msg = (f"{ev['dest_name']} receives {ev['quantity']} {ev['resource']} "
                       f"from {ev['origin_name']}.")
            elif etype == "regional_lost":
                msg = (f"A shipment of {ev['quantity']} {ev['resource']} from "
                       f"{ev['origin_name']} to {ev['dest_name']} was lost in transit!")
            elif etype == "sold_to_city":
                msg = (f"{ev['origin_name']} sends {ev['quantity']} surplus "
                       f"{ev['resource']} to {ev['dest_name']} for export.")
            else:
                continue
            self.show_bottom_message(msg)
            return   # first relevant event only, to avoid message spam

    def _report_trade_events(self):
        """Surface this turn's autonomous trade activity to the player only
        when it actually involves their own faction — shows the first such
        event on the existing bottom banner (battle outcomes use the same
        one), rather than spamming a message per event."""
        player_idx = self.world.player_faction_idx
        if player_idx is None:
            return
        for ev in self.world.trade_events:
            etype = ev["type"]
            if etype == "route_proposed":
                if ev["from_idx"] == player_idx:
                    continue   # can't happen (AI never proposes to itself), but guard anyway
                proposer = self.world.factions[ev["from_idx"]]
                self.show_bottom_message(
                    f"{proposer.name} proposes a trade route with you — "
                    f"see their faction panel to respond.")
                return
            if etype == "route_started":
                continue   # AI-to-AI route (never involves the player -- see run_trade_route_ai)
            if "seller_idx" not in ev or "buyer_idx" not in ev:
                continue   # unrecognized event shape -- don't risk a KeyError below
            seller = self.world.factions[ev["seller_idx"]]
            buyer = self.world.factions[ev["buyer_idx"]]
            is_seller = ev["seller_idx"] == player_idx
            is_buyer = ev["buyer_idx"] == player_idx
            if not (is_seller or is_buyer):
                continue

            if etype == "dispatched" and is_seller:
                msg = (f"Your caravan departs for {buyer.name} with "
                       f"{ev['quantity']} {ev['resource']}.")
            elif etype == "delivered" and is_seller:
                msg = (f"Your caravan delivers {ev['quantity']} {ev['resource']} to "
                       f"{buyer.name}. Payment is en route home.")
            elif etype == "delivered" and is_buyer:
                msg = (f"{seller.name}'s caravan delivers {ev['quantity']} "
                       f"{ev['resource']} to your ports for {ev['price']} Gold.")
            elif etype == "paid" and is_seller:
                msg = f"Your caravan returns from {buyer.name} with {ev['price']} Gold."
            elif etype == "lost":
                msg = (f"A trade caravan ({ev['quantity']} {ev['resource']}) between "
                       f"{seller.name} and {buyer.name} was lost!")
            else:
                continue
            self.show_bottom_message(msg)
            return   # first relevant event only, to avoid message spam

    def _player_faction(self):
        idx = self.world.player_faction_idx
        return self.world.factions[idx] if idx is not None else None

    def _is_player(self, nation):
        player = self._player_faction()
        return player is not None and nation is player

    def _fog_is_active(self):
        """Whether fog currently gates what's shown. Applies at *every* zoom
        level, not just the world view: with free camera pan/zoom, "zoomed
        into your own region" no longer confines the camera to your own
        territory — you can drag/scroll anywhere on the map while
        zoom_faction stays set, so gating fog off at that level used to let
        you pan out and see the whole map uncovered. Fog only ever hides
        cells you haven't actually revealed regardless (your own territory
        is always revealed by definition), so applying it unconditionally
        costs nothing when looking at your own realm and correctly still
        hides everything else. Computed fresh (not cached) so it's correct
        even when called before render() has run for the current state,
        e.g. mid-click."""
        wd = self.world
        return wd.player_faction_idx is not None and hasattr(wd, "fog")

    def _on_layer(self, obj):
        """Whether this thing is on the layer currently being looked at.

        Two ways to answer it, and both are needed. A mover carries its own
        layer, because a commander walks between them (phase 3). A settlement
        or village never moves, so its layer is its region's -- and as of
        phase 5 there are real holds and warrens down there, so this is no
        longer a question only movers ask."""
        own = getattr(obj, "layer", None)
        if own is not None:
            return own == self.layer
        rid = getattr(obj, "region_id", None)
        if rid is not None and 0 <= rid < len(self.world.regions):
            return layers.region_layer(self.world.regions[rid]) == self.layer
        return self.layer == layers.SURFACE

    def _node_visible(self, node):
        """On this layer, and somewhere the player has actually seen. One call,
        because every marker path needs both and the fog question is different
        on each layer (see _revealed_here)."""
        return self._on_layer(node) and self._revealed_here(*node.pos)

    def _revealed_here(self, x, y):
        """Fog on whichever layer is being looked at. Above ground that is the
        ordinary fog of war; below it, darkness (vision.under_revealed) --
        two different mechanics, and the surface's answer is meaningless for a
        cell under a mountain."""
        if self.layer == layers.UNDER:
            from app.world.vision import under_revealed
            return under_revealed(self.world, x, y)
        return self._cell_revealed(x, y)

    def _visible_route(self, cmd):
        """The stretch of a commander's remaining march that is on the layer
        being looked at -- the first contiguous run of it, so a march that
        goes down through a gate is drawn up to the door on the surface and
        onward from the door below, rather than as one line that teleports."""
        from app.world.commander import path_layer_at
        path = cmd.path or ()
        out = []
        for i in range(cmd.path_index, len(path)):
            if path_layer_at(cmd, i) != self.layer:
                if out:
                    break
                continue
            out.append(path[i])
        return out

    def _cell_revealed(self, x, y):
        """True if fog isn't currently gating the view, or this specific
        cell has been revealed — used for point features (settlements)
        where precise per-cell gating is more accurate than a per-nation
        check (see _is_known, used instead for identity info like labels).

        Deliberately inlines _fog_is_active()'s check rather than calling it:
        this is one of the hottest functions in the renderer (every road
        endpoint, every marker, every route cell) and the extra Python call
        plus hasattr() per invocation showed up in profiles. Still computed
        fresh per call, so the correctness note on _fog_is_active holds."""
        wd = self.world
        if wd.player_faction_idx is None:
            return True
        fog = getattr(wd, "fog", None)
        if fog is None:
            return True
        return bool(fog[y * wd.w + x])

    def _is_known(self, nation):
        """True if `nation` is the player or the player has made contact
        with it (fog of war has revealed at least one of its cells) — see
        app/world/vision.py. True unconditionally in sandbox worlds with no
        player faction, so fog gating is a no-op there."""
        wd = self.world
        if wd.player_faction_idx is None:
            return True
        if self._is_player(nation):
            return True
        idx = wd.factions.index(nation)
        return idx in getattr(wd, "discovered_factions", ())

    def _zoom_is_foreign(self):
        """True while browsing a foreign nation's regions (diplomacy-only —
        no village drill-down, no ordinary management)."""
        player = self._player_faction()
        return (player is not None and self.zoom_faction is not None
                and self.zoom_faction is not player)

    def _villages_visible(self):
        """True once zoomed in close enough, within a faction's own
        territory, that villages should appear and be clickable.

        Replaces the old separate "village view" mode (entered by clicking
        an already-selected region a second time — confusing since the
        camera didn't actually move, and a settlement/village marker under
        that second click could silently intercept it instead). Now it's
        purely a function of how far zoomed in the free camera already is,
        so panning/wheel-zooming across the threshold reveals villages on
        its own, with no separate click step to get wrong. Foreign browsing
        never reaches this regardless of zoom -- diplomacy actions only, no
        drilling into a rival's villages."""
        if self.zoom_faction is None or self._zoom_is_foreign():
            return False
        vx0, vy0, vx1, vy1 = self.view
        return min(vx1 - vx0, vy1 - vy0) <= _VILLAGE_REVEAL_SPAN

    def _do_diplomacy(self, action_fn, nation, region=None):
        """Run a diplomacy action, show its flavor message on the bottom
        banner, and refresh whatever panel is currently displaying it."""
        player = self._player_faction()
        msg = (action_fn(self.world, player, nation, region) if region is not None
               else action_fn(self.world, player, nation))
        self.show_bottom_message(msg)
        if self.selected is nation:
            self._show_faction(nation)
        if region is not None and self.selected_region is region:
            self._show_region(region)
        self.render()

    def _show_faction(self, nation):
        self._hide_prosperity_bar()
        self._hide_storage_bar()
        player = self._player_faction()
        own = self._is_player(nation)
        self.title_lbl.config(text="Your Realm" if own else "Foreign Realm")
        s = nation.stats
        n_regions = len(nation.meta.get("regions", []))
        # Gold is a real settlement-storage resource now (Currency
        # overhaul) -- summed across every settlement this faction owns,
        # same aggregate view Iron/Logs/Stone already get, not a separate
        # treasury number any more.
        gold = construction._faction_settlement_stock(nation, "Gold", self.world)
        if own or player is None:
            zoom_hint = "Click again to zoom in."
        elif self.world.world_map.get_relationship(player.id, nation.id)["stance"] == Stance.ENEMY:
            zoom_hint = "Click again to attack."
        else:
            zoom_hint = "Click again to inspect its regions."
        # The monarch leads the panel: a realm is a name and whoever sits its
        # throne -- the header stays short (name/ruler/species), everything
        # else moves into the SUMMARY card below so this doesn't read as one
        # long paragraph of stats.
        crown = ruler_label(nation)
        self._page_begin(nation.name, crown or None)
        self._panel_text(f"{nation.meta['species']} — {nation.meta['trait']}",
                         fg=theme.MUTED)
        self._panel_gap(4)

        rels = [r for r in self.world.world_map.relationships_of(nation.id)
                if self._is_known(r["other"])]
        if self._card("Relationships", key="rels") is not None:
            if not rels:
                self._panel_text("Isolated — no bordering factions.",
                                 fg=theme.MUTED)
            for rel in rels:
                tag = rel["stance"] + (f" ({rel['tension']})" if rel["tension"] else "")
                self._kv(None, rel["other"].name, tag,
                         fg=theme.STANCE_COLOR.get(rel["stance"], theme.MUTED))

        body = self._card("SUMMARY")
        if body is not None:
            self._kv(body, "Military", f"{s['military']}")
            self._kv(body, "Morale", f"{s['morale']}")
            self._kv(body, "Gold", f"{gold:,}")
            self._kv(body, "Avg fertility", f"{nation.meta['fertility']}%")
            self._kv(body, "Population", f"{self._total_population(nation):,}")
            self._kv(body, "Settlements", self._settle_counts(nation))
            self._kv(body, "Regions", f"{n_regions}")

        # Commander status decides whether this realm can attack or claim at
        # all -- always visible, never folded, since it's actionable/blocking
        # rather than background stats.
        if own:
            fac_idx = self.world.factions.index(nation)
            waiting = commander.commander_respawn_turns(self.world, fac_idx)
            if waiting:
                self._panel_text("No commander — a successor takes "
                         f"the field in {waiting} turn{'s' if waiting != 1 else ''}. "
                         "Your realm cannot attack or claim until then.", fg=theme.WARN)
            elif not commander.faction_commanders(self.world, fac_idx):
                self._panel_text("No commander. Your realm cannot "
                         "attack or claim.", fg=theme.WARN)

        self._panel_text(zoom_hint, fg=theme.MUTED, font=theme.FONT_SMALL)

        if player is None:
            # No player nation on this world (sandbox/legacy save) — keep the
            # old behavior of managing any faction directly.
            enemies = [r for r in rels if r["stance"] == Stance.ENEMY]
            if not enemies:
                self._panel_text("No enemies to fight.", fg=theme.MUTED)
            for r in enemies:
                other = r["other"]
                self._panel_button(f"Attack {other.name}",
                                lambda o=other, n=nation: self.on_attack(n, o))
        elif own:
            self._panel_text("This is your realm. Select a rival "
                     "nation on the map to consider attacking it.", fg=theme.MUTED)
        else:
            rel = self.world.world_map.get_relationship(player.id, nation.id)
            if rel["stance"] == Stance.ENEMY:
                player_idx = self.world.factions.index(player)
                target_idx = self.world.factions.index(nation)
                if bordering_regions(self.world, player_idx, target_idx):
                    self._panel_button(f"Attack {nation.name}",
                                    lambda n=nation: self._begin_attack_setup(n))
                elif naval_reachable_regions(self.world, player_idx, target_idx):
                    self._panel_button(f"Naval Attack on {nation.name}",
                                    lambda n=nation: self._begin_attack_setup(n, naval=True))
                else:
                    self._panel_text(f"No route to {nation.name} — you'd "
                             "need a shared border or a coastal port.", fg=theme.MUTED)
            else:
                standing = rel.get("standing", 0)
                self._panel_text(f"You are {rel['stance']} with "
                         f"{nation.name}. Standing: {standing}", fg=theme.MUTED)

                can_act = diplomacy.can_act_this_turn(self.world, player, nation)
                self._panel_button("Improve Relations",
                                lambda n=nation: self._do_diplomacy(
                                    diplomacy.improve_relations, n))
                if not can_act:
                    self._panel_text("Already acted with them this turn.", fg=theme.MUTED, font=theme.FONT_SMALL)

                if standing <= diplomacy.WAR_THRESHOLD:
                    self._panel_button(f"Declare War on {nation.name}",
                                    lambda n=nation: self._do_diplomacy(
                                        diplomacy.declare_war, n),
                                    kind="danger")
                if standing >= diplomacy.ALLY_THRESHOLD and rel["stance"] != Stance.ALLY:
                    self._panel_button(f"Form Alliance with {nation.name}",
                                    lambda n=nation: self._do_diplomacy(
                                        diplomacy.form_alliance, n),
                                    kind="success")

                self._show_trade_route_status(player, nation)

    def _show_trade_route_status(self, player, nation):
        """Trade route status/action against `nation` (only reached while
        relations aren't hostile — see _show_faction's caller): a
        completed route, in-progress construction, a Propose button once
        eligible, or why proposing isn't available yet. One button covers
        both kinds — start_trade_route picks land or sea (whichever
        exists) and the other side has to actually agree before anything
        opens; neither kind is ever established without going through it."""
        wd = self.world
        player_idx = wd.factions.index(player)
        target_idx = wd.factions.index(nation)
        key = frozenset((player_idx, target_idx))

        if key in wd.trade_routes_by_pair:
            self._panel_text("Trade route established.", fg=theme.GOOD)
            return

        project = next((p for p in wd.trade_route_projects
                        if frozenset((p.a_idx, p.b_idx)) == key), None)
        if project is not None:
            self._panel_text(f"Trade route under construction: "
                     f"{project.built_cells}/{project.total_cells} cells", fg=theme.MUTED)
            return

        pending = next((p for p in getattr(wd, "incoming_trade_proposals", [])
                        if p["from_idx"] == target_idx), None)
        if pending is not None:
            self._show_incoming_trade_proposal(player_idx, target_idx, nation)
            return

        if not trade.eligible_to_trade(wd, player_idx, target_idx):
            self._panel_text(f"Standing needs to reach "
                     f"{diplomacy.TRADE_STANDING_THRESHOLD} before you can "
                     "propose a trade route.", fg=theme.MUTED)
            return

        decline_until = getattr(wd, "trade_route_decline_until", {}).get(key, -1)
        if wd.turn < decline_until:
            self._panel_text(f"{nation.name} recently declined a trade "
                     "proposal — try again later.", fg=theme.BAD)
            return

        if not trade.route_path_possible(wd, player_idx, target_idx):
            self._panel_text(f"No land or sea connection exists "
                     f"to {nation.name}'s capital — a route isn't possible.", fg=theme.MUTED)
            return

        self._show_trade_complementarity(player_idx, target_idx, nation)

        self._panel_button(f"Propose Trade Route with {nation.name}",
                        lambda: self._do_propose_trade_route(player_idx, target_idx))

    def _show_trade_complementarity(self, viewer_idx, other_idx, nation):
        """What `nation` brings to the table that the player doesn't already
        have — currently stocked goods ("have") vs raw resources it could
        geographically produce that the player's own territory has no
        access to at all ("access"), per the player's explicit request that
        a trade decision (incoming or outgoing) show this before they commit."""
        summary = trade.trade_complementarity_summary(self.world, viewer_idx, other_idx)
        lines = []
        if summary["have"]:
            lines.append("Currently has: " + ", ".join(summary["have"]))
        if summary["access"]:
            lines.append("Could produce: " + ", ".join(summary["access"]))
        text = "\n".join(lines) if lines else "Nothing you don't already have access to."
        self._panel_text(text, fg=theme.MUTED, font=theme.FONT_SMALL)

    def _show_incoming_trade_proposal(self, player_idx, target_idx, nation):
        self._panel_text(f"{nation.name} proposes a trade route with you.", fg=theme.INK)
        self._show_trade_complementarity(player_idx, target_idx, nation)
        self._panel_button("Accept", lambda: self._do_respond_trade_proposal(
                               target_idx, player_idx, accept=True),
                           kind="success")
        self._panel_button("Decline", lambda: self._do_respond_trade_proposal(
                               target_idx, player_idx, accept=False),
                           kind="danger")

    def _do_respond_trade_proposal(self, from_idx, player_idx, accept):
        if accept:
            msg = trade.accept_trade_route_proposal(self.world, from_idx)
        else:
            msg = trade.decline_trade_route_proposal(self.world, from_idx)
        self.show_bottom_message(msg)
        if self.selected is self.world.factions[from_idx]:
            self._show_faction(self.selected)
        self.render()

    def _do_propose_trade_route(self, a_idx, b_idx):
        msg = trade.start_trade_route(self.world, a_idx, b_idx)
        self.show_bottom_message(msg)
        if self.selected is self.world.factions[b_idx]:
            self._show_faction(self.selected)
        self.render()

    def _settle_counts(self, nation):
        """'2 cities · 3 castles · 5 towns' summary for a faction."""
        wd = self.world
        counts = {"city": 0, "castle": 0, "town": 0}
        for sid in nation.meta.get("settlements", []):
            counts[wd.settlements[sid].kind] += 1
        return (f"{counts['city']} cities · {counts['castle']} castles · "
                f"{counts['town']} towns")

    def _total_population(self, nation):
        """Every city/castle/town's population plus every village's,
        summed across all of the faction's regions — not just one."""
        wd = self.world
        fac_idx = wd.factions.index(nation)
        total = sum(getattr(wd.settlements[sid], "population", 0)
                   for sid in nation.meta.get("settlements", []))
        total += sum(v.population for v in wd.villages if v.faction_idx == fac_idx)
        return total

    def _show_region(self, region):
        self._hide_prosperity_bar()
        self._hide_storage_bar()
        if region.faction_idx < 0:
            self._show_wildland_region(region)
            return
        s = region.stats
        # region.faction_idx, not self.zoom_faction: they always agree for a
        # region the flat map could show you (you can only select a region
        # while drilled into its own owner), but zoom_faction is FLAT-MAP
        # state with real side effects elsewhere in this file (which raster
        # _ensure_base builds, back-button visibility, camera-animation
        # targets...). Deriving the owner straight from the region itself
        # means a caller showing a region panel never has to first put the
        # flat map's own drill-down state into some particular shape just to
        # get the right name printed here.
        country = self.world.factions[region.faction_idx]
        wd = self.world
        n_villages = len(getattr(region, "villages", []))
        total_cells = sum(region.biome_counts.values()) or 1
        biome_line = ", ".join(
            f"{biome.capitalize()} ({round(100 * count / total_cells)}%)"
            for biome, count in sorted(region.biome_counts.items(),
                                       key=lambda kv: -kv[1])) or "Unclassified"

        is_foreign = self._zoom_is_foreign()
        # The region's fantasy name for the country it is -- "the Everwood"
        # rather than "forest" (biome overhaul, phase F). Purely a name; the
        # mechanical biome is still spelled out in the SUMMARY card below, so
        # nothing is hidden behind the flavour.
        flavour = region.flavour_name
        self._page_begin(None)
        self._panel_text(f"{region.name}\nRegion of {country.name}"
                               + (f"\n{flavour}" if flavour else "")
                               + ("\nForeign territory" if is_foreign else ""), fg=theme.INK)


        body = self._card("SUMMARY")
        if body is not None:
            self._kv(body, "Area", f"{s['area']}")
            self._kv(body, "Fertility", f"{s['fertility']}%")
            self._kv(body, "Biome", biome_line)
            self._kv(body, "Climate", region.dominant_climate.capitalize())
            self._kv(body, "This turn's yield", _format_resources(region.resources))

        sts = [wd.settlements[i] for i in getattr(region, "meta_settlements", [])]
        body = self._card("SETTLEMENTS", f"{len(sts)}", key="settlements")
        if body is not None:
            if sts:
                for st in sts:
                    self._kv(body, st.name, st.kind.capitalize())
            else:
                self._panel_text("No settlements.", fg=theme.MUTED)

        if is_foreign:
            self._panel_text("Foreign territory — consider hostile "
                     "action below.", fg=theme.MUTED, font=theme.FONT_SMALL)
        else:
            self._panel_text(f"{n_villages} villages — click again "
                     "to zoom in.", fg=theme.MUTED, font=theme.FONT_SMALL)

        if is_foreign:
            player = self._player_faction()
            can_act = diplomacy.can_act_this_turn(self.world, player, country)
            for label, fn in (("Fabricate Claim on Region", diplomacy.fabricate_claim),
                              ("Terrorize Locals", diplomacy.terrorize_locals)):
                self._panel_button(label,
                                lambda f=fn: self._do_diplomacy(f, country, region))
            if not can_act:
                self._panel_text("Already acted against them this turn.", fg=theme.MUTED, font=theme.FONT_SMALL)
        elif self._player_faction() is not None:
            # Claiming wildland only ever hands out villages (and, still
            # area-scaled, a Castle) now — a City or Town has to be built
            # here by hand, same as a Castle always did. See
            # app/world/expansion.py's settle_newly_claimed_region.
            player = self._player_faction()
            projects_here = [p for p in wd.settlement_projects if p.region_id == region.id]
            for project in projects_here:
                note = " (half speed — road not yet finished)" if project.half_speed else ""
                elapsed = project.total_turns - project.turns_left
                self._panel_text(f"{project.kind.capitalize()} under "
                         f"construction: {elapsed}/{project.total_turns} turns{note}", fg=theme.MUTED)
            building_kinds = {p.kind for p in projects_here}
            for kind in ("city", "town", "castle"):
                if kind in building_kinds:
                    continue
                cost = construction.SETTLEMENT_BUILD_COST[kind]
                turns = construction.SETTLEMENT_BUILD_TURNS[kind]
                afford = construction.can_afford(player, cost, self.world)
                self._panel_text(f"{kind.capitalize()} — Cost: {_format_resources(cost)}\n"
                              f"Build time: {turns} turns", fg=theme.INK)
                self._panel_button(f"Build {kind.capitalize()}...",
                                lambda r=region, k=kind: self._begin_settlement_placement(r, k))

    def _show_wildland_region(self, region):
        """UNCLAIMED land: wildland garrison strength, claim cost/time/odds,
        and a Claim Territory button (or why claiming isn't available yet)."""
        wd = self.world
        player = self._player_faction()
        total_cells = sum(region.biome_counts.values()) or 1
        biome_line = ", ".join(
            f"{biome.capitalize()} ({round(100 * count / total_cells)}%)"
            for biome, count in sorted(region.biome_counts.items(),
                                       key=lambda kv: -kv[1])) or "Unclassified"
        lines = [f"{region.name}", "Unclaimed wildland"]
        flavour = region.flavour_name        # phase F, see Region.flavour_name
        if flavour:
            lines.append(flavour)
        lines += [f"Area {region.stats['area']} · Fertility {region.stats['fertility']}%",
                  f"Biome: {biome_line}",
                  f"Wildland garrison strength: {region.wildland_strength}"]
        sea_only = False
        if player is not None:
            faction_idx = wd.factions.index(player)
            sea_only = expansion.is_sea_only_claim(wd, faction_idx, region)
            odds = expansion.claim_odds(player, region, sea_only)
            lines.append(f"Estimated success odds: {round(100 * odds)}%")
            if sea_only:
                lines.append("Across open water — no land border. An amphibious "
                             "claim is far costlier and better defended.")
        self._page_begin(None)
        self._panel_text("\n".join(lines), fg=theme.INK)

        if player is None:
            return
        faction_idx = wd.factions.index(player)
        if region not in expansion.claimable_frontier(wd, faction_idx):
            self._panel_text("Not adjacent to your territory yet.", fg=theme.MUTED)
            return
        if wd.turn < region.claim_cooldown_until_turn:
            self._panel_text("The locals are still wary after "
                     "repelling your last attempt — try again later.", fg=theme.BAD)
            return
        project = next((p for p in wd.claim_projects if p.region_id == region.id), None)
        if project is not None:
            if project.complete:
                self._panel_text("The expansion crew has arrived "
                         "— fight the wildland garrison to claim this land.", fg=theme.INK)
                self._panel_button("Fight for the Territory",
                                lambda p=project: self._do_wildland_battle(p),
                                kind="danger")
            else:
                elapsed = project.total_turns - project.turns_left
                self._panel_text(f"Expansion under way: "
                         f"{elapsed}/{project.total_turns} turns", fg=theme.MUTED)
            return
        # A claim is colonisation: settlers and the food to see them through
        # (see expansion.claim_cost). Both figures are shown against what the
        # realm actually has, since "80 settlers" means nothing on its own.
        settlers = expansion.claim_settlers(region, sea_only)
        provisions = expansion.claim_cost(region, sea_only)["Food"]
        have_settlers = expansion.faction_available_settlers(self.world, faction_idx)
        have_food = expansion._faction_food_stock(self.world, faction_idx)
        blocked = expansion.can_afford_claim(self.world, faction_idx, region, sea_only)
        self._panel_text(f"Settlers: {settlers:,} (you can spare {have_settlers:,})\n"
                      f"Provisions: {provisions:,} food (you hold {have_food:,})\n"
                      f"Journey: {expansion.claim_turns(region)} turns", fg=theme.INK)
        # Settlers are working-age people, and population is the workforce
        # (Phase 14) -- saying so stops this reading as a free number.
        self._panel_text("Settlers are drawn from your nearest places and come "
                      "off their workforce.", fg=theme.MUTED, font=theme.FONT_SMALL)
        # Winning pays real coin -- show that up front, or the cost reads as
        # pure expenditure and nobody expands early.
        spoils = expansion.claim_spoils(self.world, region)
        if spoils:
            goods = sum(v for k, v in spoils.items() if k != "Gold")
            line = f"Spoils if won: {spoils.get('Gold', 0):,} Gold"
            if goods:
                line += f" + {goods:,} units of stores"
            self._panel_text(line, fg=theme.GOOD)
        self._panel_button("Claim Territory",
                        lambda cnty=region: self._do_claim(cnty))

    def _do_claim(self, region):
        player = self._player_faction()
        faction_idx = self.world.factions.index(player)
        msg = expansion.start_claim(self.world, faction_idx, region)
        self.show_bottom_message(msg)
        self._base_key = None
        if self.selected_region is region:
            self._show_region(region)
        self.render()

    def _do_wildland_battle(self, project):
        """Hand off to App.stage_wildland_battle — the interactive
        battlefield, not an instant formula, decides whether the claim
        succeeds (see app/world/expansion.py's advance_claims, which leaves
        a completed player claim sitting untouched for exactly this)."""
        if self.on_wildland_claim is not None:
            self.on_wildland_claim(project)

    def _hide_prosperity_bar(self):
        """A no-op on a drawn page.

        The meters used to be two permanently-built Canvases packed and
        unpacked as the selection changed, which is why hiding one was a
        method at all. A page has no such state: a meter exists on it because
        this selection drew one. Kept as a name so the five _show_* methods
        still read the way they did.
        """

    def _show_prosperity_bar(self, value):
        """The prosperity meter, drawn where the caller is (see
        resources._update_prosperity for how `value` moves over time)."""
        self._page.bar("Prosperity", round(value), 100)

    def _hide_storage_bar(self):
        """See _hide_prosperity_bar."""

    def _show_storage_bar(self, stored, capacity):
        """The storage meter. `stored` can exceed `capacity` -- overflowing
        storage spoils faster (see Storage & Spoilage) -- and page.bar colours
        an over-full channel red rather than silently clipping it."""
        self._page.bar("Storage", int(stored), int(capacity))

    def _card(self, title, subtitle=None, key=None, default_open=True):
        """A titled, foldable section on the drawn page. Returns the PAGE when
        the card is open and None when it is folded -- the same
        truthy-or-None contract the widget version had, so every `body =
        self._card(...)` / `if body is not None:` call site is unchanged by
        the move off widgets."""
        key = key or title
        if self._page.card(key, title, self._panel_cards_open, subtitle,
                           on_toggle=lambda k=key: self._toggle_panel_card(k),
                           default_open=default_open):
            return self._page
        return None

    def _panel_text(self, text, fg=None, font=None):
        """A run of prose on the page -- what a tk.Label packed into the old
        actions frame used to be."""
        self._page.text(text, fill=fg, font=font)

    def _panel_button(self, text, command, kind="default"):
        self._page.button(text, command, kind=kind)

    def _panel_gap(self, amount=8):
        self._page.gap(amount)

    def _panel_divider(self):
        self._page.divider()

    def _page_begin(self, title, subtitle=None):
        """Start the selection panel's page. Every _show_* opens with this and
        closes with _page_end, which replaces the old destroy-the-widget-tree/
        rebuild-it dance entirely -- a page is cleared by drawing it again."""
        self._page.begin(max(320, self._panel_canvas.winfo_height() or 320))
        if title:
            self._page.title(title, subtitle)

    def _page_end(self):
        self._page.finish()
        self._panel_canvas.yview_moveto(0.0)

    @contextlib.contextmanager
    def _quiet_rebuild(self, frame):
        """Rebuild `frame`'s contents without the empty middle being drawn.

        Every _show_* destroys the panel's whole widget tree and builds a new
        one. Done while the frame is mapped, Tk is free to paint the gap, and
        on a busy panel that reads as the whole side of the screen blinking
        once a turn. Unmapping it first means the intermediate states have
        nowhere to appear: Tk paints once, when it comes back.

        Restores the exact pack options it was managed with rather than
        assuming any -- re-packing with defaults would silently move the
        frame to the end of its parent and reflow the panel."""
        try:
            info = frame.pack_info()
        except tk.TclError:
            info = None                 # not packed (yet); nothing to hide
        if info:
            frame.pack_forget()
        try:
            yield
        finally:
            if info:
                frame.pack(**info)

    def _rebuild_selection_panel(self):
        """Redraw whichever selection panel is currently up.

        Every kind of selection has to be here, which is exactly what the
        folding cards got wrong: this used to cover only Settlements and
        Villages, so clicking SUMMARY or SETTLEMENTS on a REGION flipped the
        card's open/shut state and then redrew nothing at all. The arrow even
        changed on the next unrelated redraw, which made it look like the click
        had registered and the card had simply refused to move."""
        # No unmap-and-restore dance any more (see _quiet_rebuild): the panel
        # is a drawn page, so a rebuild is one delete-and-draw on a canvas
        # rather than thirty widgets being destroyed and recreated while
        # mapped. There is no half-built intermediate state for Tk to paint.
        if True:
            if self.selected is not None:
                self._show_faction(self.selected)
            if self.selected_region is not None:
                self._show_region(self.selected_region)
            if self.selected_settlement is not None:
                self._show_settlement(self.selected_settlement)
            if self.selected_village is not None:
                self._show_village(self.selected_village)

    def _toggle_panel_card(self, key):
        # Commanders too -- refresh() handles that one separately because it
        # also drives the treasury, but a fold has to redraw it like any other.
        if self.selected_commander is not None:
            self._show_commander(self.selected_commander)
            return
        self._rebuild_selection_panel()

    def _kv(self, parent, label, value, fg=None):
        """One aligned label/value row. `parent` is ignored and kept only so
        the thirty-odd existing call sites did not all have to change when
        the panel stopped being a widget tree -- it was always the card body
        they were already inside, which the page tracks itself."""
        self._page.kv(label, value, fg)

    def _bar_row(self, parent, label, used, cap, warn_at=0.85):
        """A labelled meter -- used/cap plus a fill in a carved channel, so
        four storage pools read as four bars instead of four sentences."""
        self._page.bar(label, used, cap, warn_at)

    def _storage_pool_lines(self, node):
        """One line per typed storage pool (see resources.STORAGE_POOLS) --
        which building holds what, how much SPACE it's using, what's taking
        up the most of it, and whether it's throttling production.

        Two things this has to be explicit about. A single "1,847 / 1,850"
        total was actively misleading once space became typed: it read as
        "nearly full" while the granary was empty and only the warehouse was
        jammed. And the numbers are space, not items (Phase 2) -- a unit of
        Logs eats 3.0 and a unit of Gems 0.1 -- so it names the biggest
        occupant, which is what turns "my warehouse is full" into "my
        warehouse is full *of timber*"."""
        lines = []
        res = getattr(node, "resources", {}) or {}
        for pool in resources.STORAGE_POOLS:
            cap = resources.node_pool_capacity(node, pool)
            if not cap:
                continue
            stock = resources.node_pool_stock(node, pool)
            building = resources.STORAGE_BUILDING_BY_POOL[pool]
            tier = resources.storage_tier(node, building)
            tier_text = f" [T{tier}]" if tier else ""
            state = ""
            if stock > cap:
                state = "  ⚠ FULL — production stopped"
            elif stock > cap * resources.STORAGE_THROTTLE_START:
                state = "  ⚠ slowing"
            lines.append(f"  {self._POOL_LABEL[pool]}{tier_text}: "
                         f"{stock:,} / {cap:,} space{state}")
            occupants = [(round(q * resources.resource_bulk(r)), r)
                         for r, q in res.items()
                         if q > 0 and resources.storage_class(r) == pool]
            if occupants:
                space, name = max(occupants)
                # Only when one good genuinely dominates -- calling a 19%
                # share "mostly" is just noise on a well-mixed store.
                if space and space >= stock * 0.35:
                    lines.append(f"      mostly {name} "
                                 f"({res[name]:,} × {resources.resource_bulk(name):g} "
                                 f"= {space:,} space)")
        return lines

    def _herd_lines(self, village):
        """Herd, capacity, Winter feed position and this village's policy.
        Livestock had no representation in the UI at all before this -- the
        player could not see a single animal they owned, let alone that a herd
        was about to be culled for want of hay."""
        herds = getattr(village, "herds", None)
        if not herds:
            return []
        lines = ["Herd:"]
        for animal in sorted(herds, key=lambda a: -herds[a]):
            head = herds[animal]
            if head <= 0:
                continue
            cap = resources.village_herd_capacity(self.world, village, animal)
            at_cap = "  (at capacity)" if cap and head >= cap else ""
            lines.append(f"  {animal}: {head:,} of {cap:,}{at_cap}")
        need = resources.village_winter_fodder_need(village)
        if need:
            have = (getattr(village, "resources", {}) or {}).get("Fodder", 0)
            state = "enough" if have >= need else "SHORT — herd will be culled"
            lines.append(f"  Winter fodder: {have:,} of {need:,} needed — {state}")
        lines.append(f"  Cull policy: {resources.herd_policy(village)}")
        return lines

    def _build_herd_policy_actions(self, village, parent=None):
        """Grow / Balanced / Cull buttons -- the player's direct dial on the
        Autumn cull (see resources.HERD_POLICY_MULTIPLIER)."""
        if not getattr(village, "herds", None):
            return
        current = resources.herd_policy(village)
        self._panel_text("Herd policy — how hard to cull in Autumn:",
                         fg=theme.MUTED)
        for policy in resources.HERD_POLICIES:
            self._panel_button(
                policy,
                lambda p=policy, v=village: self._do_set_herd_policy(v, p),
                kind="accent" if policy == current else "default")

    def _do_set_herd_policy(self, village, policy):
        resources.set_herd_policy(village, policy)
        self.show_bottom_message(f"{village.name}'s herd policy set to {policy}.")
        self._show_village(village)

    def _build_stockpile_card(self, node, own):
        """STOCKPILE -- how much of each good this node holds back before
        logistics/trade may carry any more of it away (Phase 3, see
        resources.apply_stockpile_target).

        Only lists goods this node actually holds AND that a target can
        legally apply to (resources.stockpile_eligible): the survival and
        upkeep goods run on their own reserve formulas, and offering a
        lever there that silently does nothing would be worse than not
        offering one at all. Default-closed and skipped entirely when
        there's nothing eligible, so an early village with three crops in
        the barn doesn't get an empty card."""
        if not own:
            return
        stock = {r: a for r, a in (getattr(node, "resources", {}) or {}).items()
                 if a and resources.stockpile_eligible(r)}
        if not stock:
            return
        set_count = sum(1 for r in stock if resources.stockpile_target(node, r) is not None)
        body = self._card("STOCKPILE",
                          f"{set_count} set" if set_count else "default",
                          key="stockpile", default_open=False)
        if body is None:
            return
        self._panel_text("How much to hold back before trading the rest away. " "Applies to this place only.", fg=theme.MUTED)
        for res_name in sorted(stock, key=lambda r: -stock[r]):
            current = resources.stockpile_target(node, res_name)
            label = next((name for name, frac in resources.STOCKPILE_PRESETS
                          if frac == current), "Default")
            self._kv(None, f"{res_name}  {stock[res_name]:,}", label,
                     fg=theme.ACCENT if current is not None else None)
            self._page.hit_last_row(
                lambda n=node, r=res_name: self._cycle_stockpile_target(n, r))

    def _cycle_stockpile_target(self, node, resource):
        """Step this resource to the next preset -- a cycle rather than a
        dropdown because the choices are few and coarse (see
        resources.STOCKPILE_PRESETS)."""
        presets = resources.STOCKPILE_PRESETS
        current = resources.stockpile_target(node, resource)
        idx = next((i for i, (_, frac) in enumerate(presets) if frac == current), 0)
        name, frac = presets[(idx + 1) % len(presets)]
        resources.set_stockpile_target(node, resource, frac)
        self.show_bottom_message(f"{node.name}: {resource} stockpile set to {name}.")
        if hasattr(node, "kind"):
            self._show_settlement(node)
        else:
            self._show_village(node)

    def _buildable_at(self, node):
        """Every building this node could ever put up -- pool buildings, the
        Preserving House, and the herd buildings, deduped (the Barn is both a
        pool building and a herd building)."""
        out = [resources.STORAGE_BUILDING_BY_POOL[p] for p in resources.STORAGE_POOLS]
        out.append(resources.PRESERVING_HOUSE)
        out += [b for b in resources.HERD_BUILDINGS if b not in out]
        return out

    def _show_settlement(self, st):
        """Settlement panel, in the same folding-card idiom as the village one
        (see _card / _show_village).

        Settlements differ from villages in three ways worth showing rather
        than hiding: they run the conversion recipes (a village has no mill,
        loom or forge), they can build a Shipyard, and they keep no herd.
        Everything else -- summary, storage meters, what is actually held,
        build actions -- reads identically, so moving between a city and one
        of its villages never means relearning the panel."""
        wd = self.world
        self.selected_village = None   # a settlement and a village are never both selected
        self.title_lbl.config(text=st.name)
        region = (wd.regions[st.region_id].name
                  if 0 <= st.region_id < len(wd.regions) else "?")
        self._page_begin(None)
        self._panel_text(f"{st.kind.capitalize()} in {region}\n"
                 f"{wd.factions[st.faction_idx].name}", fg=theme.MUTED)

        prosperity = getattr(st, "prosperity", None)
        if prosperity is not None:
            self._show_prosperity_bar(prosperity)
        else:
            self._hide_prosperity_bar()
        # Same reasoning as the village panel: space is typed, so one aggregate
        # total is a number that means nothing. STORAGE shows the real pools.
        self._hide_storage_bar()

        player = self._player_faction()
        own = player is not None and st.faction_idx == wd.factions.index(player)

        body = self._card("SUMMARY")
        if body is not None:
            population = getattr(st, "population", None)
            if population is not None:
                max_pop = getattr(st, "max_population", None)
                self._kv(body, "Population",
                         f"{population:,}" + (f" / {max_pop:,}" if max_pop else ""))
                self._kv(body, "Adults \u00b7 children",
                         f"{st.adults:,} \u00b7 {st.children:,}")
            self._kv(body, "Needs per turn",
                     _format_resources(resources.settlement_needs(st, wd.season)))
            built = [b.replace("_", " ").title() for b in self._buildable_at(st)
                     if resources.storage_tier(st, b)]
            if getattr(st, "has_shipyard", False):
                built.append("Shipyard")
            if built:
                self._kv(body, "Built", " \u00b7 ".join(built))

        if own:
            self._build_entry_card(st, player)
            self._build_survey_card(st)

        making = self._settlement_conversions(st)
        body = self._card("INDUSTRY", f"{len(making)} running", key="production",
                          default_open=False)
        if body is not None:
            if making:
                for output, source, rate in making:
                    self._kv(body, f"{source} \u2192 {output}", f"{rate:,}/turn")
            else:
                self._panel_text("Nothing converting \u2014 this settlement is " "waiting on inputs.", fg=theme.MUTED)

        stock = {r: a for r, a in (getattr(st, "resources", {}) or {}).items() if a}
        body = self._card("STORAGE", f"{len(stock)} kinds held", key="storage")
        if body is not None:
            for pool in resources.STORAGE_POOLS:
                cap = resources.node_pool_capacity(st, pool)
                if not cap:
                    continue
                building = resources.STORAGE_BUILDING_BY_POOL[pool]
                tier = resources.storage_tier(st, building)
                label = f"{building.title()}{f' T{tier}' if tier else ''}"
                self._bar_row(body, label, resources.node_pool_stock(st, pool), cap)

        body = self._card("HELD", f"{len(stock)} kinds", key="held",
                          default_open=False)
        if body is not None:
            for res_name, amount in sorted(stock.items(), key=lambda kv: -kv[1]):
                self._kv(body, res_name, f"{amount:,}")

        self._build_stockpile_card(st, own)

    def _settlement_conversions(self, st):
        """[(output, input, units/turn), ...] this settlement can actually run
        right now -- the recipes it has the inputs for, at the rate they would
        convert. Villages cannot convert at all, so this is the one card that
        is genuinely settlement-only, and it answers a question the old panel
        could not: why a city sitting on Wheat still has no Bread."""
        res = getattr(st, "resources", None) or {}
        out = []
        for output, options in resources.RECIPES.items():
            if output not in resources._SETTLEMENT_STORAGE_RESOURCES:
                continue
            cap = (resources.LUXURY_CONVERSION_RATE_CAP
                   if resources.RESOURCES[output]["luxury"]
                   else resources.CONVERSION_RATE_CAP)
            for option in options:
                inputs = option["inputs"]
                rate = min(min(res.get(i, 0) for i in inputs), cap)
                if rate > 0:
                    out.append((output, " + ".join(inputs), rate))
                    break
        # A Preserving House runs its own, separate curing step on top.
        if resources.storage_tier(st, resources.PRESERVING_HOUSE):
            cure_cap = int(resources.CONVERSION_RATE_CAP
                           * resources.preserving_cap_multiplier(st))
            for output, source in resources.PRESERVATION_RECIPES.items():
                have = res.get(source, 0)
                if have > 0:
                    out.append((output, source, min(have, cure_cap)))
        return out

    def _build_entry_card(self, node, player):
        """The BUILD card, for a Settlement or a Village alike: what this place
        most needs, and the way in to the build menu itself.

        This used to be the whole build UI -- a vertical stack of a label and a
        button per building, in a 360px column. That is the wrong shape for a
        build menu, which is a thing you scan and compare across, and it also
        gave no answer to the question that actually matters ("which of these
        does this place need?"). Both moved to app/ui/build_menu.py, which has
        room for real cards, and app/world/buildings.py, which does the
        judging. What is left here is a summary and a door."""
        wd = self.world
        options = buildings.build_options(wd, node, player)
        startable = [o for o in options if o.buildable]
        urgent = [o for o in options if o.priority == "urgent"]
        in_progress = [o for o in options if o.in_progress]

        subtitle = f"{len(startable)} available"
        if urgent:
            subtitle = f"{len(urgent)} needed · {subtitle}"
        body = self._card("BUILD", subtitle, key="build", default_open=True)
        if body is None:
            return

        for option in in_progress:
            elapsed, total = option.in_progress
            self._kv(body, f"{option.label} building", f"{elapsed}/{total} turns",
                     fg=theme.WARN)
        for option in (urgent or options)[:3]:
            if option.priority in ("urgent", "useful") and option.reason:
                self._panel_text(f"• {option.label}: {option.reason}", fg=theme.BAD if option.priority == "urgent" else theme.WARN)
        self._panel_button("Open Build Menu…",
                           lambda n=node: self._open_build_menu(n),
                           kind="accent" if urgent else "default")

    def _open_build_menu(self, node):
        player = self._player_faction()
        if player is None:
            return
        audio.play("menu_open")
        build_menu.open_for(self.winfo_toplevel(), self.world, node, player,
                            on_change=self._after_build_menu_change)

    def _build_survey_card(self, st):
        """SURVEY -- commission a party to go and map what's out there
        (resources.start_survey). Only appears where there's a Guild to
        commission it from; a settlement without one has nothing to say
        here and gets no empty card."""
        wd = self.world
        if resources.storage_tier(st, resources.CARTOGRAPHER) <= 0:
            return
        in_field = [e for e in getattr(wd, "survey_expeditions", None) or []
                    if e.origin_id == st.id and e.faction_idx == st.faction_idx
                    and not e.finished]
        body = self._card("SURVEY", "in the field" if in_field else "available",
                          key="survey", default_open=False)
        if body is None:
            return
        if in_field:
            exp = in_field[0]
            done, total = len(exp.charted), len(exp.path)
            self._kv(body, "Party out", f"{done}/{total} cells charted")
            return

        speed, reach = resources.survey_speed_and_range(wd, st)
        self._kv(body, "Cost", _format_resources(resources.SURVEY_COST))
        self._kv(body, "Range", f"{reach} cells at {speed:g}/turn")
        blocked = resources.can_commission_survey(wd, st)
        if blocked:
            self._panel_text(blocked, fg=theme.MUTED)
        if not blocked:
            self._panel_button("Commission a Survey…",
                               lambda n=st: self._do_start_survey(n))

    def _do_start_survey(self, st):
        self.show_bottom_message(resources.start_survey(self.world, st))
        self._show_settlement(st)
        self._update_resource_bar()
        self.render()

    def _after_build_menu_change(self):
        """Something was started from the build menu: bring the map's own
        panels back in step. The menu never touches them itself -- it is a
        view, and this is the one hook back."""
        if self.selected_settlement is not None:
            self._show_settlement(self.selected_settlement)
        elif self.selected_village is not None:
            self._show_village(self.selected_village)
        self._update_resource_bar()
        self.render()

    def _show_village(self, v):
        """Village panel, rebuilt as folding cards (see _card).

        Previously one Label holding ~30 lines of prose -- a six-line run-on
        of everything the village grows, another for everything it stores,
        then storage and herd as inline "Header:" text. Now: a short summary
        that's always visible, and Production / Storage / Herd / Build as
        sections you open only when you care."""
        wd = self.world
        self.selected_settlement = None   # a village and a settlement are never both selected
        self.title_lbl.config(text=v.name)
        region = wd.regions[v.region_id]
        self._page_begin(None)
        self._panel_text(f"Village in {region.name}\n{wd.factions[v.faction_idx].name}", fg=theme.MUTED)

        prosperity = getattr(v, "prosperity", None)
        if prosperity is not None:
            self._show_prosperity_bar(prosperity)
        else:
            self._hide_prosperity_bar()
        # No aggregate storage bar any more: space is typed (Phase 3), so a
        # single "1,474 / 3,300" total is a number with no meaning -- the
        # Storage card below shows the four real pools instead.
        self._hide_storage_bar()

        player = self._player_faction()
        own = player is not None and v.faction_idx == wd.factions.index(player)

        body = self._card("SUMMARY")
        if body is not None:
            population = getattr(v, "population", None)
            if population is not None:
                max_pop = getattr(v, "max_population", None)
                self._kv(body, "Population",
                         f"{population:,}" + (f" / {max_pop:,}" if max_pop else ""))
                self._kv(body, "Adults · children", f"{v.adults:,} · {v.children:,}")
            needs = resources.settlement_needs(v, wd.season)
            self._kv(body, "Needs per turn", _format_resources(needs))

        if own:
            self._build_entry_card(v, player)

        yield_ = resources.village_projected_annual_yield(wd, v)
        report = resources.village_labor_report(wd, v)
        body = self._card("PRODUCTION", f"labour: {report['policy']}",
                          key="production", default_open=False)
        if body is not None:
            # The labour split first, then the annual figures it produces.
            # Which ceiling binds is the thing a player needs to understand
            # before any of the per-good numbers below mean anything: a
            # village short of hands and a village working all the land there
            # is want completely different responses.
            self._kv(body, "Workforce", f"{report['workforce']:,} adults")
            for row in report["sectors"]:
                self._kv(body,
                         SECTOR_LABEL.get(row["sector"], row["sector"].title()),
                         f"{row['output']:,} of {row['potential']:,}",
                         fg={"hands": theme.WARN,
                             "season": theme.MUTED}.get(row["limited_by"], theme.GOOD))
            if own:
                self._panel_button("Set labour…",
                                   lambda n=v: self._open_build_menu(n))
            self._panel_divider()
            for res_name, amount in sorted(yield_.items(), key=lambda kv: -kv[1]):
                self._kv(body, res_name, f"{amount:,}/yr")

        stock = {r: a for r, a in (getattr(v, "resources", {}) or {}).items() if a}
        body = self._card("STORAGE", f"{len(stock)} kinds held", key="storage")
        if body is not None:
            for pool in resources.STORAGE_POOLS:
                cap = resources.node_pool_capacity(v, pool)
                if not cap:
                    continue
                building = resources.STORAGE_BUILDING_BY_POOL[pool]
                tier = resources.storage_tier(v, building)
                label = f"{building.title()}{f' T{tier}' if tier else ''}"
                self._bar_row(body, label, resources.node_pool_stock(v, pool), cap)


        body = self._card("HELD", f"{len(stock)} kinds", key="held",
                          default_open=False)
        if body is not None:
            for res_name, amount in sorted(stock.items(), key=lambda kv: -kv[1]):
                self._kv(body, res_name, f"{amount:,}")

        self._build_stockpile_card(v, own)

        herds = getattr(v, "herds", None)
        if herds and any(herds.values()):
            body = self._card("HERD", f"{sum(herds.values()):,} head", key="herd")
            if body is not None:
                for animal in sorted(herds, key=lambda a: -herds[a]):
                    if herds[animal] <= 0:
                        continue
                    cap = resources.village_herd_capacity(wd, v, animal)
                    self._kv(body, animal, f"{herds[animal]:,} / {cap:,}")
                need = resources.village_winter_fodder_need(v)
                if need:
                    have = (getattr(v, "resources", None) or {}).get("Fodder", 0)
                    short = have < need
                    self._kv(body, "Winter fodder", f"{have:,} / {need:,}",
                             fg=theme.BAD if short else theme.GOOD)
                    if short:
                        self._panel_text("herd will be culled", fg=theme.BAD)
                if own:
                    self._build_herd_policy_actions(v, body)


    def _show_commander(self, cmd):
        """Panel for a selected Commander: position, current order, and
        Move/Board/Dismantle/Build Ship actions (which of these apply
        depends on whether the commander is aboard a ship, standing on a
        beached one, or on foot with none nearby). A pure scout for now —
        no combat, so there's nothing here about strength or risk."""
        self._hide_prosperity_bar()
        self._hide_storage_bar()
        wd = self.world
        aboard = commander.ship_by_id(wd, cmd.aboard_ship_id) if cmd.aboard_ship_id is not None else None
        beached = None if aboard is not None else commander.find_ship_near(
            wd, cmd.faction_idx, cmd.pos)

        lines = ["Commander", f"Position: ({cmd.pos[0]}, {cmd.pos[1]})"]
        if aboard is not None:
            ship_desc = "fast ship" if aboard.speed_mult > 1.0 else "ship"
            lines.append(f"Aboard a {ship_desc}")
        elif beached is not None:
            lines.append("Standing beside a beached ship")
        else:
            lines.append("On foot")
        if cmd.ship_turns_left is not None:
            lines.append(f"Building ship: {cmd.ship_turns_left} days left")
        elif cmd.path is not None:
            remaining = len(cmd.path) - 1 - cmd.path_index
            lines.append(f"Moving — {remaining} cells left")
        else:
            lines.append("Idle")
        self._page_begin(None)
        self._panel_text("\n".join(lines), fg=theme.INK)

        if cmd.ship_turns_left is None:
            self._panel_button("Move", lambda: self._begin_commander_move(cmd))
            if aboard is None and commander.can_build_ship(wd, cmd):
                shipyard = commander.shipyard_at(wd, cmd.faction_idx, cmd.pos)
                if shipyard is not None:
                    label = "Launch Ship (free)"
                else:
                    label = "Build Ship"
                    nation = wd.factions[cmd.faction_idx]
                    afford = construction.can_afford(nation, commander.SHIP_COST, wd)
                    cost_text = (f"Cost: {_format_resources(commander.SHIP_COST)}\n"
                                f"Build time: {commander.SHIP_BUILD_TURNS} turns")
                    if not afford:
                        missing = _resource_shortfall(nation, commander.SHIP_COST, wd)
                        cost_text += f"\nShort: {_format_resources(missing)}"
                    self._panel_text(cost_text, fg=theme.INK)
                self._panel_button(label, lambda: self._do_build_ship(cmd))
            if beached is not None:
                self._panel_button("Board Ship", lambda: self._do_board_ship(cmd))
                self._panel_button("Dismantle Ship", lambda: self._do_dismantle_ship(cmd), kind="danger")

    def _begin_commander_move(self, cmd):
        self.commander_move_mode = cmd
        self._page_begin(None)
        self._panel_text("Click a spot on the map to send the "
                              "commander there.", fg=theme.MUTED)
        self._panel_button("Cancel", lambda: self._cancel_commander_move(cmd))

    def _cancel_commander_move(self, cmd):
        self.commander_move_mode = None
        self._show_commander(cmd)

    def _do_build_ship(self, cmd):
        msg = commander.start_ship(self.world, cmd)
        self.show_bottom_message(msg)
        self._show_commander(cmd)
        self.render()

    def _do_board_ship(self, cmd):
        msg = commander.board_ship(self.world, cmd)
        self.show_bottom_message(msg)
        self._show_commander(cmd)
        self.render()

    def _do_dismantle_ship(self, cmd):
        msg = commander.dismantle_ship(self.world, cmd)
        self.show_bottom_message(msg)
        self._show_commander(cmd)
        self.render()

    # --- zoom-level enter/exit ----------------------------------------------
    # Three levels: World -> Country (shows regions) -> Region (shows
    # villages). Each level's "enter" sets state + zooms in; "exit" clears
    # that level's state and zooms back out to the level above.
    @staticmethod
    def _padded_rect(bbox, min_pad_frac=0.12, min_size=0):
        x0, y0, x1, y1 = bbox
        pad = min_pad_frac * max(x1 - x0, y1 - y0, min_size)
        return [x0 - pad, y0 - pad, x1 + pad, y1 + pad]

    def _world_view_rect(self):
        """Where "back to world view" should zoom out to: a padded box
        around everything fog of war has actually revealed so far, not the
        full map. Early on, most of the map is still black — snapping the
        camera all the way out to it every time you back out of a region is
        jarring whiplash; zooming only as far as you've actually explored
        keeps the transition proportional, and it naturally widens on its
        own as more gets revealed. Falls back to the full map for sandbox
        worlds (no player/no fog) or once fog_bbox already covers it."""
        wd = self.world
        bbox = getattr(wd, "fog_bbox", None)
        if self._fog_is_active() and bbox is not None:
            return self._padded_rect(bbox, min_pad_frac=0.15, min_size=30)
        return [0.0, 0.0, wd.w, wd.h]

    def _enter_ui(self, section_label, back_label, back_command):
        """Switch the panel into a zoomed mode: clear relationships/attack,
        show a Back button configured for the current level."""
        self._panel_section = section_label
        self._back_label, self._back_command = back_label, back_command
        self._render_foot()

    def _exit_ui(self):
        self._back_label = self._back_command = None
        self._render_foot()

    def _enter_region_view(self, faction):
        """Zooms into one faction's territory. Villages aren't a separate
        mode any more -- they simply become visible/clickable once the free
        camera is zoomed in close enough (see _villages_visible), so this
        is the only "entered" state between here and the world view."""
        self.zoom_faction = faction
        self.selected_region = None
        self.selected_village = None
        self.selected_settlement = None
        self._base_key = None
        self.title_lbl.config(text="Regions")
        self._page_begin(None)
        self._panel_text(f"{faction.name}\nClick a region to inspect it. "
                              "Zoom in close to see its villages.", fg=theme.MUTED)
        self._enter_ui("REGION", "← Back to World", self._exit_region_view)
        self._start_zoom(self._padded_rect(faction.meta["bbox"]))

    def _exit_region_view(self):
        self.zoom_faction = None
        self.selected_region = None
        self.selected_village = None
        self.selected_settlement = None
        self._base_key = None
        self._exit_ui()
        if self.selected:
            self._show_faction(self.selected)
        self._start_zoom(self._world_view_rect())

    # --- attack targeting ----------------------------------------------------
    def _begin_attack_setup(self, enemy, naval=False):
        """Zoom to the shared border (or coastline, for a naval invasion)
        with `enemy` and let the player pick which frontline/coastal region
        to attack. If `naval` isn't explicitly requested, land is tried
        first and naval is the automatic fallback when there's no land
        connection (e.g. the double-click-to-attack shortcut doesn't know
        which kind applies — it just wants "attack them, however")."""
        player = self._player_faction()
        player_idx = self.world.factions.index(player)
        enemy_idx = self.world.factions.index(enemy)

        if naval:
            frontier = naval_reachable_regions(self.world, player_idx, enemy_idx)
        else:
            frontier = bordering_regions(self.world, player_idx, enemy_idx)
            if not frontier:
                frontier = naval_reachable_regions(self.world, player_idx, enemy_idx)
                naval = bool(frontier)

        if not frontier:
            self._page_begin(None)
            self._panel_text(f"{enemy.name}\nNo shared border or coastal "
                                  "port to attack across right now.", fg=theme.MUTED)
            return

        # Only offer ground the army can actually reach. Showing targets
        # that would then be refused makes the rule feel arbitrary; showing
        # only reachable ones makes "move the commander first" self-evident.
        reachable = [r for r in frontier
                     if commander.commander_can_reach(self.world, player_idx, r)]
        if not reachable:
            where = "a coastal landing" if naval else "the frontier"
            self._page_begin(None)
            self._panel_text(f"{enemy.name}\nYour army cannot reach them. March your "
                     f"commander to one of your own regions on {where} with "
                     f"{enemy.name}, then attack.", fg=theme.WARN)
            return
        frontier = reachable

        self.attack_mode = enemy
        self._attack_enemy = enemy
        self._attack_frontier = frontier
        self.selected_region = None
        self._base_key = None

        xs = [x for region in frontier for x, y in region.cells]
        ys = [y for region in frontier for x, y in region.cells]
        bbox = (min(xs), min(ys), max(xs) + 1, max(ys) + 1)

        self.title_lbl.config(text="Choose a Target")
        if naval:
            self._page_begin(None)
            self._panel_text(f"Launching a naval invasion of {enemy.name}.\n"
                                  "Click a highlighted region along the coast "
                                  "to attack it.", fg=theme.MUTED)
        else:
            self._page_begin(None)
            self._panel_text(f"Attacking {enemy.name}.\nClick a highlighted "
                                  "region along the border to attack it.", fg=theme.MUTED)
        self._enter_ui("ATTACK", "← Cancel", self._cancel_attack_setup)
        self._start_zoom(self._padded_rect(bbox, min_pad_frac=0.3, min_size=10))
        self.render()

    def _cancel_attack_setup(self):
        self.attack_mode = None
        self._attack_enemy = None
        self._attack_frontier = []
        self._exit_ui()
        self._base_key = None
        if self.selected:
            self._show_faction(self.selected)
        self._start_zoom(self._world_view_rect())

    def _launch_attack(self, region):
        enemy = self._attack_enemy
        player = self._player_faction()
        # The army marches with the commander: no commander on the frontier,
        # no attack (see commander.commander_can_reach). Checked here rather
        # than only when the target list is built, so a commander that walked
        # away mid-selection can't slip an attack through.
        blocked = commander.commander_block_reason(
            self.world, self.world.factions.index(player), region)
        if blocked:
            self.show_bottom_message(blocked, ms=6000)
            return
        self.attack_mode = None
        self._attack_enemy = None
        self._attack_frontier = []
        self._exit_ui()
        self._base_key = None
        if self.selected:
            self._show_faction(self.selected)
        # THE ARMY MARCHES. It used to fight the instant this was clicked,
        # wherever the commander happened to be standing -- which is how an
        # order reads when a turn is the only thing that makes "later" mean
        # anything. With a running clock, ordering an attack starts a march:
        # the column crosses the ground, the days pass, and the battle is
        # fought on arrival (commander.order_attack -> the
        # "commander:attack_arrived" event -> App._on_attack_arrived). Which
        # also means an attack can now be seen coming, and met.
        #
        # The camera is deliberately left where it is, so the player watches
        # the column leave rather than being thrown at a battle they have not
        # arrived at yet.
        cmds = commander.faction_commanders(self.world,
                                            self.world.factions.index(player))
        if not cmds:
            self.show_bottom_message("You have no commander to lead an attack.",
                                     ms=5000)
            return
        message = commander.order_attack(self.world, cmds[0], region)
        self.show_bottom_message(f"Marching on {region.name}. {message}", ms=6000)

    # --- settlement placement -------------------------------------------------
    def _begin_settlement_placement(self, region, kind):
        self.building_mode = (region, kind)
        self._placement_hint_cells = self._score_placement_hint(region, kind)
        cost = construction.SETTLEMENT_BUILD_COST[kind]
        turns = construction.SETTLEMENT_BUILD_TURNS[kind]
        self._page_begin(None)
        self._panel_text(f"{region.name}\nClick a spot in this region to "
                              f"begin building a {kind} there.\n\n"
                              f"Cost: {_format_resources(cost)}\n"
                              f"Build time: {turns} turns", fg=theme.MUTED)
        self._panel_button("Cancel", self._cancel_settlement_placement)
        self.render()

    def _score_placement_hint(self, region, kind):
        """The region's own best-scoring cells for `kind`, by the same
        _site_score formula world-gen and the AI use (worldgen.py) --
        purely advisory (see _draw_placement_hint): the player can still
        click anywhere in the region, this just marks where a City/Castle/
        Town would naturally want to sit. Computed once when placement is
        armed, not per frame -- a region can be a few hundred to several
        thousand cells, and the score doesn't change while the mode is up.
        Capped to the top decile so the hint reads as 'the good spots',
        not a full-region heatmap."""
        from app.world.worldgen import SETTLEMENT_TYPES, _site_score
        import random as _random
        wd = self.world
        occupied = {st.pos for st in wd.settlements}
        occupied.update(p.pos for p in wd.settlement_projects)
        occupied.update(wd.villages[vid].pos for vid in region.villages)
        coast_d = getattr(wd, "_settle_coast_d", None)
        water_d = getattr(wd, "_settle_water_d", None)
        border_d = getattr(wd, "_settle_border_d", None)
        if coast_d is None or water_d is None or border_d is None:
            return []   # pre-Phase-2 save with no cached proximity fields yet
        weights = SETTLEMENT_TYPES[kind]
        rng = _random.Random(0)   # fixed seed -- a stable hint, not a new
                                   # roll of the tie-break jitter every frame
        scored = sorted(
            ((_site_score(wd, weights, x, y, coast_d, water_d, border_d, rng), x, y)
             for x, y in region.cells
             if (x, y) not in wd.river_cells and (x, y) not in occupied),
            reverse=True)
        top_n = max(1, len(scored) // 10)
        return [(x, y) for _, x, y in scored[:top_n]]

    def _cancel_settlement_placement(self):
        self.building_mode = None
        self._placement_hint_cells = None
        if self.selected_region is not None:
            self._show_region(self.selected_region)
        self.render()

    # --- post-battle conquest flash ------------------------------------------
    def flash_region(self, region, outcome="success"):
        """Briefly blink a region's border — gold for a region gained,
        red for a failed attack — fading out over a couple of seconds. A
        failed attack also zooms back out to the world view once the blink
        finishes, since there's nothing new to look at up close."""
        if self._flash_id is not None:
            self.after_cancel(self._flash_id)
            self._flash_id = None
        self._flash_region = region
        self._flash_outcome = outcome
        self._flash_start = time.time()
        self._flash_tick()

    def _flash_tick(self):
        if self._flash_region is None:
            return
        if time.time() - self._flash_start >= _FLASH_DURATION:
            failed = self._flash_outcome == "failure"
            self._flash_region = None
            self._flash_id = None
            if failed:
                self._start_zoom(self._world_view_rect())
            self.render()
            return
        self.render()
        self._flash_id = self.after(40, self._flash_tick)

    # --- bottom banner (acquisition outcome message) -------------------------
    def show_bottom_message(self, text, ms=4200):
        self.bottom_msg.config(text=text)
        self.bottom_msg.place(relx=0.5, rely=0.97, anchor="s")
        if self._bottom_msg_after_id is not None:
            self.after_cancel(self._bottom_msg_after_id)
        self._bottom_msg_after_id = self.after(ms, self._hide_bottom_message)

    def _hide_bottom_message(self):
        if self._bottom_msg_after_id is not None:
            self.after_cancel(self._bottom_msg_after_id)
            self._bottom_msg_after_id = None
        self.bottom_msg.place_forget()

    # --- year-rollover banner --------------------------------------------------
    def _year_delta_summary(self, deltas, pop_delta=0):
        """'Population +842 · Wheat +1.2k · Gold -340 · ...' for the player
        faction's biggest gains/losses since the year began, ordered by
        tier then name like every other resource listing in this file --
        only nonzero entries, capped so the banner doesn't turn into a
        wall of text. Population leads the line when it changed at all
        (growth/starvation/freezing/combat losses across every settlement
        and village, net for the year) since it's the single figure a
        player cares most about at a glance, ahead of any one resource."""
        parts = []
        if pop_delta:
            sign = "+" if pop_delta > 0 else "-"
            parts.append(f"Population {sign}{_fmt_amount(abs(pop_delta))}")
        order = sorted((r for r in deltas if deltas.get(r)),
                       key=lambda r: (RESOURCES.get(r, {}).get("tier", 9), r))
        for r in order[:10]:
            d = deltas[r]
            sign = "+" if d > 0 else "-"
            parts.append(f"{r} {sign}{_fmt_amount(abs(d))}")
        if not parts:
            return "No significant change this year."
        return " · ".join(parts)

    def _show_year_banner(self, year, deltas, pop_delta=0):
        self.year_title_lbl.config(text=f"YEAR {year}")
        self.year_summary_lbl.config(text=self._year_delta_summary(deltas, pop_delta))
        self.year_banner.place(relx=0.5, rely=0.08, anchor="n")
        if self._year_banner_after_id is not None:
            self.after_cancel(self._year_banner_after_id)
        self._year_banner_after_id = self.after(6000, self._hide_year_banner)

    def _hide_year_banner(self):
        if self._year_banner_after_id is not None:
            self.after_cancel(self._year_banner_after_id)
            self._year_banner_after_id = None
        self.year_banner.place_forget()

    # --- free camera: drag-pan / wheel-zoom ---------------------------------
    def _cancel_animation(self):
        """Manual camera control always wins over an in-flight click-drill
        ease — called before any drag/wheel mutates the view directly."""
        if self._anim_id is not None:
            self.after_cancel(self._anim_id)
            self._anim_id = None
        self._animating = False

    def _on_press(self, event):
        self._cancel_animation()
        self._press_xy = (event.x, event.y)
        self._dragged = False

    def _on_drag(self, event):
        if self._press_xy is None:
            return
        px, py = self._press_xy
        dx, dy = event.x - px, event.y - py
        if not self._dragged and dx * dx + dy * dy < _DRAG_THRESHOLD_PX ** 2:
            return
        self._dragged = True
        _, _, scale = self._place
        wx, wy = dx / scale, dy / scale
        self.view[0] -= wx
        self.view[2] -= wx
        self.view[1] -= wy
        self.view[3] -= wy
        self.view_target = list(self.view)
        self._press_xy = (event.x, event.y)

        # A real motion-driven mouse fires <B1-Motion> far faster than we
        # can usefully redraw -- calling render() (which recreates every
        # road/symbol/label item from scratch) on each and every one of
        # those events queues up a backlog, so the visible map falls
        # behind where the mouse actually is, which reads as everything
        # on the map "lagging behind" the drag. (A cheaper canvas.move()
        # per event was tried here instead of a full render(), but proved
        # to have no visible effect on screen at all in practice -- items'
        # internal coordinates shifted but Tk never repainted them until
        # the next real render() -- so markers stayed frozen in place
        # between renders instead of just being briefly stale.) Coalescing
        # into a single pending render() per idle tick fixes the backlog
        # directly: however many motion events land before Tk is free to
        # repaint, only one render() runs, using wherever self.view ended
        # up by then.
        if not self._drag_render_pending:
            self._drag_render_pending = True
            self.after_idle(self._drag_render_tick)

    def _drag_render_tick(self):
        self._drag_render_pending = False
        if self._dragged:
            self.render()

    def _on_release(self, event):
        was_drag = self._dragged
        self._press_xy = None
        self._dragged = False
        if was_drag:
            self.render()   # final, fully correct frame once the drag actually stops
        else:
            self._on_click(event)

    def _on_wheel(self, event):
        self._cancel_animation()
        vx0, vy0, scale = self._place
        wx, wy = vx0 + event.x / scale, vy0 + event.y / scale
        factor = _ZOOM_STEP if event.delta > 0 else 1.0 / _ZOOM_STEP

        x0, y0, x1, y1 = self.view
        w = (x1 - x0) * factor
        h = (y1 - y0) * factor
        if self._villages_visible():
            # Close enough to see villages is meant to be the deepest zoom
            # level -- cap zoom-out to (roughly) the faction's own
            # territory so the free camera can't wheel its way straight
            # back out to seeing the whole world from here. "Back to
            # World" is the correct way to go wider than that.
            bx0, by0, bx1, by1 = self.zoom_faction.meta["bbox"]
            max_span = max(bx1 - bx0, by1 - by0) * 1.3
        else:
            max_span = max(self.world.w, self.world.h) * 1.2
        w = max(_MIN_ZOOM_CELLS, min(max_span, w))
        h = max(_MIN_ZOOM_CELLS, min(max_span, h))
        fx = (wx - x0) / (x1 - x0) if x1 != x0 else 0.5
        fy = (wy - y0) / (y1 - y0) if y1 != y0 else 0.5
        nx0, ny0 = wx - fx * w, wy - fy * h

        self.view = [nx0, ny0, nx0 + w, ny0 + h]
        self.view_target = list(self.view)
        self.render()

    # --- zoom animation ----------------------------------------------------
    def _start_zoom(self, target):
        self.view_target = list(target)
        if self._anim_id is None:
            self._animating = True
            self._animate()

    def _animate(self):
        done = True
        for k in range(4):
            d = self.view_target[k] - self.view[k]
            if abs(d) > 0.4:
                done = False
            self.view[k] += d * 0.25
        if done:
            self.view = list(self.view_target)
            self._animating = False
            self._anim_id = None
            self.render()
            return
        self.render()
        self._anim_id = self.after(16, self._animate)

    # --- interaction -------------------------------------------------------
    def _on_click(self, event):
        # No guard against the world being mid-day any more: the day is
        # stepped between frames on this very thread (see _on_frame), so a
        # click can only ever land between two whole phases. That is the
        # entire reason for slicing it -- the turn-based build needed a
        # full-frame overlay here to keep hands off `world` while a worker
        # owned it.
        if self._animating:
            return
        vx0, vy0, scale = self._place
        gx, gy = self.screen_to_world(event.x, event.y)
        wd = self.world
        if not (0 <= gy < wd.h):
            return

        if self.layer == layers.UNDER:
            # Below ground the only thing to pick is a hall. Attacking,
            # settling and every other surface mode are simply not offered
            # here yet -- there is nothing down here to attack or build on
            # until the phases that put people in the galleries.
            rid = layers.region_at(wd, gx, gy, layers.UNDER)
            gate = layers.gate_at(wd, gx, gy, layers.UNDER)
            if rid is not None:
                self._show_region(wd.regions[rid])
                self.selected_region = wd.regions[rid]
                self._base_key = None
                self.render()
            elif gate is not None:
                self.show_bottom_message(
                    f"A gate to the surface at {gate['pos']}.", ms=4000)
            else:
                self.show_bottom_message("Solid rock.", ms=2500)
            return

        if self.attack_mode is not None:
            # --- ATTACK-TARGET PICKING: zoomed to a shared border ---------
            cid = wd.region_grid[gy][gx]
            if any(c.id == cid for c in self._attack_frontier):
                self._launch_attack(wd.regions[cid])
            return

        if self.building_mode is not None:
            # --- SETTLEMENT PLACEMENT: pick a spot within the armed region ---
            region, kind = self.building_mode
            if wd.region_grid[gy][gx] == region.id:
                player = self._player_faction()
                msg = construction.start_settlement(wd, player, (gx, gy), kind)
                self.building_mode = None
                self._placement_hint_cells = None
                self._base_key = None
                self.show_bottom_message(msg)
                if self.selected_region is region:
                    self._show_region(region)
                self.render()
            return

        if self.commander_move_mode is not None:
            # --- COMMANDER MOVE: next click of any kind is the destination -
            cmd = self.commander_move_mode
            self.commander_move_mode = None
            msg = commander.set_move_order(wd, cmd, (gx, gy), self.layer)
            self.show_bottom_message(msg)
            if self.selected_commander is cmd:
                self._show_commander(cmd)
            self.render()
            return

        # --- COMMANDER SELECTION: click-radius test against every one of
        # the player's own commanders, checked before normal region/faction
        # selection so a commander is selectable identically at any zoom
        # level rather than duplicating this in all three click branches.
        # Cleared here unconditionally first (only re-set below on an
        # actual hit) — otherwise a commander selected earlier stays
        # "selected" internally forever once the user clicks something
        # else instead, since nothing else in this function used to clear
        # it; that used to be harmless (nothing re-displayed a stale
        # selection on its own), but refresh() now re-shows whatever's
        # currently selected after every End Turn (see that method), so a
        # stale commander selection would silently keep overriding
        # whatever the player actually meant to have selected.
        self.selected_commander = None
        player = self._player_faction()
        if player is not None:
            player_idx = wd.factions.index(player)
            for cmd in wd.commanders:
                if cmd.faction_idx != player_idx or not self._on_layer(cmd):
                    continue
                csx, csy = self.world_to_screen(cmd.pos[0] + 0.5, cmd.pos[1] + 0.5)
                if (csx - event.x) ** 2 + (csy - event.y) ** 2 <= 10 ** 2:
                    self.selected_commander = cmd
                    self._show_commander(cmd)
                    self.render()
                    return

        if self.zoom_faction is None:
            # --- LEVEL 0: world view -------------------------------------
            o = wd.owner[gy][gx]
            if o < 0:            # OCEAN or UNCLAIMED — no faction to select here
                return
            if not self._cell_revealed(gx, gy):
                return           # fogged — nothing has been "found" here yet
            faction = wd.factions[o]
            if faction is self.selected:          # 2nd click -> zoom in / act
                player = self._player_faction()
                if player is None or faction is player:
                    self._enter_region_view(faction)
                else:
                    rel = self.world.world_map.get_relationship(player.id, faction.id)
                    if rel["stance"] == Stance.ENEMY:
                        self._begin_attack_setup(faction)   # at war -> attack
                    else:
                        self._enter_region_view(faction)    # not at war -> browse
            else:                                 # 1st click -> select country
                self.selected = faction
                self._base_key = None
                self._show_faction(faction)
                self.render()

        else:
            # --- FACTION VIEW: zoomed into a country's regions, with ------
            # villages joining in as clickable markers once zoomed in close
            # enough (see _villages_visible) -- no separate mode any more.
            zf = wd.factions.index(self.zoom_faction)
            if self._villages_visible():
                for v in wd.villages:
                    if v.faction_idx != zf or not self._on_layer(v):
                        continue        # a hall is not clickable from above
                    sx, sy = self.world_to_screen(v.pos[0] + 0.5, v.pos[1] + 0.5)
                    hit_r = self._marker_radius(_VILLAGE_STYLE["base"]) + 4
                    if (sx - event.x) ** 2 + (sy - event.y) ** 2 <= hit_r ** 2:
                        self.selected_village = v
                        self._show_village(v)
                        self.render()
                        return
            # settlement markers take priority over region selection
            for sid in self.zoom_faction.meta.get("settlements", []):
                st = wd.settlements[sid]
                if not self._on_layer(st):
                    continue
                sx, sy = self.world_to_screen(st.pos[0] + 0.5, st.pos[1] + 0.5)
                hit_r = self._marker_radius(_SETTLE_STYLE[st.kind]["base"]) + 4
                if (sx - event.x) ** 2 + (sy - event.y) ** 2 <= hit_r ** 2:
                    self.selected_settlement = st
                    self._show_settlement(st)
                    self.render()
                    return
            self.selected_settlement = None
            cid = wd.region_grid[gy][gx]
            if cid < 0:
                self._exit_region_view()          # clicked away -> zoom out
                return
            region = wd.regions[cid]
            if region.faction_idx != zf:
                # UNCLAIMED land adjacent to your own realm -> select it
                # (shows wildland info + a Claim button); anything else
                # (foreign-owned land, or unclaimed land while browsing a
                # foreign realm) just zooms back out as before.
                is_own = self.zoom_faction is self._player_faction()
                if is_own and region.faction_idx < 0:
                    self.selected_region = region
                    self._base_key = None
                    self._show_region(region)
                    self.render()
                else:
                    self._exit_region_view()
                return
            self.selected_region = region
            self._base_key = None
            self._show_region(region)
            self.render()

    def _on_right_click(self, event):
        """QoL: right-click sends the currently-selected Commander toward
        that spot directly, at any zoom level — a faster alternative to the
        Move button + left-click flow, not a replacement for it."""
        if self._animating or self.selected_commander is None:
            return
        gx, gy = self.screen_to_world(event.x, event.y)
        wd = self.world
        if not (0 <= gy < wd.h):
            return
        cmd = self.selected_commander
        self.commander_move_mode = None   # in case Move was separately armed
        # The layer you are LOOKING at is the layer you are pointing at: a
        # right-click on the underworld view is an order into the galleries,
        # and set_move_order will route it through a gate (or refuse, if there
        # is no way in from where he stands).
        msg = commander.set_move_order(wd, cmd, (gx, gy), self.layer)
        self.show_bottom_message(msg)
        self._show_commander(cmd)
        self.render()

    # --- rendering ---------------------------------------------------------
    def _ensure_base(self):
        """Rebuild the full-grid PIL image only when what it depicts changes."""
        wd = self.world
        # Region-mode (per-region shading, with the selected one picked out)
        # applies whenever EITHER the flat map has drilled into a faction
        # (zoom_faction) OR something has a specific region selected without
        # that drill-down state. Either alone is enough: a caller can ask for
        # a region highlight without also pulling in zoom_faction's other
        # side effects (back-button visibility, _zoom_is_foreign, ...).
        # The underworld is a PLACE, not a mode of the surface: it has its own
        # raster and its own cache key, and none of the surface's view modes
        # (fertility, climate, biome) mean anything in a gallery.
        if self.layer == layers.UNDER:
            sc = self.selected_region.id if self.selected_region else -1
            key = ("under", len(wd.under_cells), wd.turn // 8, sc,
                   len(getattr(wd, "under_fog", ()) or ()))
            if key == self._base_key and self._base_img is not None:
                return
            img = Image.new("RGB", (wd.w, wd.h))
            img.putdata(self._under_pixels(sc))
            self._base_img = img
            self._base_key = key
            return

        region_mode = self.zoom_faction is not None or self.selected_region is not None
        if region_mode:
            sc = self.selected_region.id if self.selected_region else -1
            key = ("region", sc)
        elif self.mode != "political":
            key = (self.mode,)
        else:
            key = ("political", id(self.selected))
        if key == self._base_key and self._base_img is not None:
            return

        if region_mode:
            if self.selected_region is not None:
                sc = self.selected_region.id
                base, hi = self._px_region, self._px_region_hi
                data = [hi[i] if cid == sc else base[i]
                        for i, cid in enumerate(self._region_flat)]
            else:
                data = self._px_region
        elif self.mode == "fertility":
            data = self._px_fert
        elif self.mode == "elevation":
            data = self._px_elev
        elif self.mode == "biome":
            data = self._px_biome
        elif self.mode == "climate":
            data = self._px_climate
        elif self.selected is not None:
            sel = wd.factions.index(self.selected)
            base, hi = self._px_pol, self._px_pol_hi
            data = [hi[i] if o == sel else base[i]
                    for i, o in enumerate(self._owner_flat)]
        else:
            data = self._px_pol

        img = Image.new("RGB", (wd.w, wd.h))
        img.putdata(data)
        self._base_img = img
        self._base_key = key

    def _under_pixels(self, selected_id=-1):
        """The underworld as a flat pixel list.

        Rebuilt rather than cached per cell: the network is a fraction of a
        per cent of the map, so this is a fill plus a few thousand pokes, and
        it changes rarely enough (ownership, a selection) that the base-image
        cache key above absorbs it. `_precompute_colors`' incremental patching
        exists because the SURFACE is 726,000 cells; this is not that problem.
        """
        wd = self.world
        n = wd.w * wd.h
        # Two shades of rock, so the coastline and the shape of the land above
        # are still readable while you are below it -- otherwise descending
        # drops you into a black void with a squiggle in it and no way to tell
        # where on the map you are.
        rock, above = _UNDER_ROCK, _UNDER_ABOVE_LAND
        data = [rock] * n
        for y in range(wd.h):
            row = wd.owner[y]
            base = y * wd.w
            for x in range(wd.w):
                # Ownership, not elevation: `height` is raw and the seabed is
                # above zero, so testing it paints the entire ocean as land.
                if row[x] != OCEAN:
                    data[base + x] = above
        fcolors, _ = self._color_context()
        # Darkness (app/world/vision.py). Not the surface's grey fog overlay:
        # down here unexplored ground is simply not drawn at all, so rock and
        # a gallery nobody has carried a lantern down look exactly alike --
        # which is the honest picture, and the reason the surface's fog mask
        # is not applied to this raster (it would grey out the mountain
        # overhead, which has nothing to do with what is under it).
        dark = wd.player_faction_idx is not None and hasattr(wd, "under_fog")
        under_fog = getattr(wd, "under_fog", None) or set()
        for (x, y), kind in wd.under_kind.items():
            if dark and (x, y) not in under_fog:
                continue
            colour = _UNDER_KIND_RGB.get(kind, (255, 0, 255))
            owner = layers.owner_at(wd, x, y, layers.UNDER)
            if owner is not None and 0 <= owner < len(wd.factions):
                # Held ground takes its holder's colour, mixed with the rock so
                # a gallery still reads as a gallery.
                fc = fcolors[owner]
                colour = tuple((c * 2 + f) // 3 for c, f in zip(colour, fc))
            if selected_id >= 0 and layers.region_at(wd, x, y, layers.UNDER) == selected_id:
                colour = tuple(min(255, int(c * 1.45)) for c in colour)
            data[y * wd.w + x] = colour
        for gate in wd.gates:
            gx, gy = gate["under"]
            data[gy * wd.w + gx] = _UNDER_GATE_RGB
        return data

    def toggle_layer(self):
        """Go below, or come back up.

        One switch, and everything that draws or picks reads `self.layer`
        rather than being told separately."""
        self.layer = (layers.UNDER if self.layer == layers.SURFACE
                      else layers.SURFACE)
        self.selected_region = None
        self._base_key = None
        audio.play("panel")
        # The sound of the place changes with the place. This is most of what
        # makes descending feel like going somewhere rather than switching a
        # view -- and it is on the music channel, so it replaces the map theme
        # rather than playing over it.
        if self.layer == layers.UNDER:
            audio.play_ambience("underworld")
        else:
            audio.play_music("map")
        self._render_foot()
        self.show_bottom_message(
            "Below the mountains. Gates are the only way in or out."
            if self.layer == layers.UNDER else "Back on the surface.", ms=4000)
        self.refresh()

    def _ensure_fog_overlay(self):
        """Rebuild the cached fog mask ("L" image, 255=hidden/0=revealed)
        only when world.fog_version changed since last time — mirrors
        _ensure_base's cache-key pattern. None when there's no player
        faction (fog isn't tracked at all in that case) or nothing's
        hidden yet."""
        wd = self.world
        key = getattr(wd, "fog_version", None)
        if key == self._fog_key:
            return
        if wd.player_faction_idx is None or not hasattr(wd, "fog"):
            self._fog_overlay_img = None
        else:
            from app.world.vision import fog_mask_bytes
            self._fog_overlay_img = Image.frombytes(
                "L", (wd.w, wd.h), fog_mask_bytes(wd))
        self._fog_key = key

    @staticmethod
    def _fit_aspect(rect, aspect):
        x0, y0, x1, y1 = rect
        rw, rh = x1 - x0, y1 - y0
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if rw / rh < aspect:
            rw = rh * aspect
        else:
            rh = rw / aspect
        return (cx - rw / 2, cy - rh / 2, cx + rw / 2, cy + rh / 2)

    def world_to_screen(self, gx, gy):
        """World cell coords -> canvas pixel coords, wrap-aware on x: the
        camera (self.view/self._place) is free-scrolling and never itself
        clamped or wrapped (it's just an ever-increasing/decreasing real
        line -- see _on_drag/_on_wheel), so a world x that's always stored
        canonically in [0, world.w) (every entity position in the game is)
        needs to be shifted by the right multiple of world.w to land at
        its correct on-screen position relative to wherever the camera
        currently is. Picks whichever wrapped representative of gx is
        CLOSEST to the camera's current center, so an entity near the seam
        draws at the correct near-edge screen position instead of
        potentially far off-screen. The single shared conversion every
        _draw_* method and every click handler should use -- replaces the
        old local `screen()` closure and the half-dozen places that used
        to hand-roll this same math inline.

        The viewport centre it wraps against comes from self._view_center_x,
        recomputed once per frame in render(), rather than being rederived
        here from canvas.winfo_width() on every call -- see __init__."""
        vx0, vy0, scale = self._place
        width = self.world.w
        k = round((self._view_center_x - gx) / width)
        wrapped_gx = gx + k * width
        return ((wrapped_gx - vx0) * scale, (gy - vy0) * scale)

    # --- viewport culling ---------------------------------------------------
    # Every _draw_* method below rebuilds its canvas items from scratch each
    # frame, and canvas cost is essentially linear in the number of items
    # created. Without culling, village view drew the zoomed faction's ENTIRE
    # road network, village list and settlement list on every frame no matter
    # how far in the camera was -- so zooming in never got cheaper, and the
    # per-frame cost grew with the size of the player's realm rather than with
    # what's actually on screen. These three predicates are the guard: convert
    # to screen space first (which is cheap, and already wrap-correct via
    # world_to_screen), then skip anything the canvas would clip away anyway.

    def _visible_point(self, sx, sy, pad=_CULL_PAD_POINT):
        """Is this screen-space point within `pad` px of the canvas?"""
        cw, ch = self._canvas_wh
        return -pad <= sx <= cw + pad and -pad <= sy <= ch + pad

    def _visible_bbox(self, x0, y0, x1, y1, pad=_CULL_PAD_LINE):
        """Does this screen-space bounding box overlap the padded canvas?"""
        cw, ch = self._canvas_wh
        if x0 > x1:
            x0, x1 = x1, x0
        if y0 > y1:
            y0, y1 = y1, y0
        return not (x1 < -pad or x0 > cw + pad or y1 < -pad or y0 > ch + pad)

    def _visible_pts(self, pts, pad=_CULL_PAD_LINE):
        """Same test for a flat [x0, y0, x1, y1, ...] polyline point list --
        the form the create_line callers already build."""
        xs = pts[0::2]
        ys = pts[1::2]
        return self._visible_bbox(min(xs), min(ys), max(xs), max(ys), pad)

    def screen_to_world(self, sx, sy):
        """Inverse of world_to_screen: canvas pixel coords -> world cell
        coords, wrapping the resulting x back into [0, world.w) so a click
        near the seam resolves to the correct wrapped world cell instead
        of a raw negative or >=width value nothing else in the game would
        recognize."""
        vx0, vy0, scale = self._place
        gx = vx0 + sx / scale
        gy = vy0 + sy / scale
        return (wrap.wrap_x(int(math.floor(gx)), self.world.w), int(math.floor(gy)))

    @staticmethod
    def _wrapped_x_segments(vx0, vx1, width):
        """[(world_x0, world_x1, screen_offset), ...] covering the
        continuous viewport range [vx0, vx1), each piece wrapped into
        [0, width) -- almost always a single segment, exactly 2 when the
        viewport straddles the seam, and more only in the (rare, allowed)
        case of zooming out wider than the world itself.

        screen_offset is how far (unscaled world-units) the left edge of
        this segment's first *integer* world cell (world_x0) sits from vx0
        -- multiply by the render scale to get the screen pixel x to paste
        the base-image crop at. Crucially it anchors on floor(x), NOT the
        fractional continuous start x: the base image is cropped on integer
        cell boundaries (render()'s crop((bx0, ...)) with bx0 = floor), so
        its screen anchor has to be the screen position of that same
        integer cell -- exactly what world_to_screen() gives every overlay.
        Anchoring on the fractional x instead silently snapped the terrain
        to the cell grid while overlays kept their sub-cell offset, so the
        two slid against each other by up to a full cell mid-pan (the
        "symbols/roads lag/jitter behind the terrain" drag bug)."""
        segments = []
        x = vx0
        guard = 0
        while x < vx1 - 1e-9 and guard < 100:
            guard += 1
            local_x0 = wrap.wrap_x(int(math.floor(x)), width)
            seg_len = min(width - local_x0, vx1 - x)
            segments.append((local_x0, local_x0 + seg_len, math.floor(x) - vx0))
            x += seg_len
        return segments

    def render(self):
        # No mid-turn guard: the world is only ever advanced between frames,
        # from _on_frame, and a phase is never split (see
        # app/world/turn_runner.py). Whenever anything gets to draw, the world
        # it is drawing is coherent.
        # GPU flat map: not a player-facing toggle -- swapped in for the
        # canvas automatically whenever GL is available, and dynamically
        # fallen back from rather than only checked once at startup.
        if self._ensure_flatgl():
            if not self._use_flatgl:
                self._activate_flatgl()
            self._sync_flatgl()
            return
        if self._use_flatgl:
            self._deactivate_flatgl()
        c = self.canvas
        c.delete("all")
        cw, ch = c.winfo_width(), c.winfo_height()
        wd = self.world
        if cw <= 1 or ch <= 1:
            return

        self._ensure_base()
        self._ensure_fog_overlay()
        fog_active = self._fog_is_active() and self._fog_overlay_img is not None
        vx0, vy0, vx1, vy1 = self._fit_aspect(self.view, cw / ch)
        scale = cw / (vx1 - vx0)
        self._place = (vx0, vy0, scale)
        # Frame-constant camera values world_to_screen() and the _visible_*
        # culling helpers read instead of re-querying Tk per call.
        self._canvas_wh = (cw, ch)
        self._view_center_x = (vx0 + vx1) / 2

        # Crop the visible grid region and scale it to the canvas (nearest).
        # The camera is free-scrolling and never itself wrapped (self.view
        # can range arbitrarily far past [0, world.w) -- see _on_drag/
        # _on_wheel), so the viewport's x-range is split into however many
        # wrap-wrapped segments it actually spans (almost always 1, or 2
        # right at the seam; more only if zoomed out wider than the world
        # itself) and each is blitted at its own screen offset -- this is
        # the "draw a second copy near the opposite edge" this map needed
        # to actually scroll seamlessly through the seam.
        by0 = max(0, int(math.floor(vy0)))
        by1 = min(wd.h, int(math.ceil(vy1)))
        self._img_refs = []   # keep every PhotoImage alive for this frame (Tkinter drops unreferenced ones)
        if by1 > by0:
            for wx0, wx1, screen_dx in self._wrapped_x_segments(vx0, vx1, wd.w):
                bx0 = max(0, int(math.floor(wx0)))
                bx1 = min(wd.w, int(math.ceil(wx1)))
                if bx1 <= bx0:
                    continue
                crop = self._base_img.crop((bx0, by0, bx1, by1))
                if fog_active:
                    fog_crop = self._fog_overlay_img.crop((bx0, by0, bx1, by1))
                    if fog_crop.getbbox() is not None:   # skip if fully revealed here
                        dark = Image.new("RGB", crop.size, _FOG_HIDDEN_RGB)
                        crop = Image.composite(dark, crop, fog_crop)
                tw = max(1, round((bx1 - bx0) * scale))
                th = max(1, round((by1 - by0) * scale))
                img = ImageTk.PhotoImage(crop.resize((tw, th), Image.NEAREST))
                self._img_refs.append(img)
                screen_x = (screen_dx + (bx0 - wx0)) * scale
                c.create_image(screen_x, (by0 - vy0) * scale, anchor="nw", image=img)

        screen = self.world_to_screen

        # Rivers are baked into the terrain raster itself (_precompute_colors,
        # same as lake_cells) rather than drawn here as a separate vector
        # overlay — see that method for why. No per-frame river drawing
        # needed at all.

        self._draw_currents(c, screen)
        self._draw_trade_routes(c, screen)
        self._draw_trade_route_construction(c, screen)
        self._draw_trade_caravans(c, screen)
        self._draw_roads(c, screen)
        # One call per wrapped x-segment (see the base-image blit above) --
        # a naive single bx0..bx1 range spanning a seam-straddling viewport
        # would walk straight through out-of-bounds x values in the gap
        # between segments.
        for wx0, wx1, _ in self._wrapped_x_segments(vx0, vx1, wd.w):
            sbx0 = max(0, int(math.floor(wx0)))
            sbx1 = min(wd.w, int(math.ceil(wx1)))
            if sbx1 > sbx0:
                self._draw_terrain_symbols(c, screen, sbx0, by0, sbx1, by1)
        self._draw_construction(c, screen)
        self._draw_placement_hint(c, screen)
        self._draw_settlements(c, screen)
        self._draw_villages(c, screen)
        self._draw_labels(c, screen)
        self._draw_attack_targets(c, screen)
        self._draw_ships(c, screen)
        self._draw_commanders(c, screen)
        self._draw_flash(c, screen)
        self._draw_terrain_legend(c)

    def _draw_forest_glyph(self, c, x, y, r):
        """A small cluster of 2-3 tiny conifer triangles — reads as "a patch
        of forest" at a glance, layered on top of the color tint
        _precompute_colors already blends into political mode."""
        for ox, oy, rr in ((-r * 0.55, r * 0.28, r * 0.85),
                          (r * 0.5, r * 0.35, r * 0.8),
                          (0.0, -r * 0.25, r * 0.65)):
            px, py = x + ox, y + oy
            c.create_polygon(px, py - rr, px + rr * 0.62, py + rr * 0.55,
                             px - rr * 0.62, py + rr * 0.55,
                             fill=_FOREST_SYMBOL_FILL, outline=_FOREST_SYMBOL_OUTLINE)

    def _draw_mountain_glyph(self, c, x, y, r):
        """A small double-peak mountain silhouette."""
        c.create_polygon(x - r * 0.95, y + r * 0.5, x - r * 0.15, y - r * 0.65,
                         x + r * 0.55, y + r * 0.5,
                         fill=_MOUNTAIN_SYMBOL_FILL, outline=_MOUNTAIN_SYMBOL_OUTLINE)
        c.create_polygon(x - r * 0.05, y + r * 0.5, x + r * 0.4, y - r * 0.2,
                         x + r * 0.95, y + r * 0.5,
                         fill=_MOUNTAIN_SYMBOL_FILL, outline=_MOUNTAIN_SYMBOL_OUTLINE)

    @staticmethod
    def _terrain_jitter(gx, gy, salt):
        """Deterministic pseudo-random value in -0.5..0.5 for cell (gx,gy)
        — same every render (no flicker/dancing symbols during pan/zoom),
        unlike calling random() fresh each frame. `salt` gives x/y jitter
        for the same cell independent values instead of moving diagonally."""
        h = (gx * 374761393 + gy * 668265263 + salt * 2246822519) & 0xffffffff
        h = (h ^ (h >> 13)) * 1274126177 & 0xffffffff
        h = (h ^ (h >> 16)) & 0xffffffff
        return (h / 0xffffffff) - 0.5

    def _draw_terrain_symbols(self, c, screen, bx0, by0, bx1, by1):
        """Sparse tree/mountain glyphs over forest/mountain biome cells
        within the visible viewport — color tint alone doesn't read clearly
        enough at a glance, especially at this map's size. Political mode
        only (Biome mode already shows this via flat color; the other modes
        aren't about biome at all). Sample spacing is derived from the
        current zoom, not a fixed world-cell count, so on-screen symbol
        density — and render cost — stays roughly constant regardless of
        how much world is visible (world view vs. zoomed into one region).

        That screen-spacing formula alone used to leave a mid-zoom
        performance cliff: for any zoom level where it computes LESS than
        _TERRAIN_SYMBOL_MIN_WORLD_SPACING, the floor overrides it and
        spacing stays pinned at the floor while the visible world AREA
        keeps growing as you zoom out further -- sample count grows with
        that area (quadratically with view span) until the screen-spacing
        formula finally exceeds the floor on its own and takes back over.
        Very close zoom never notices (visible area too small to matter)
        and very far zoom never notices either (screen-spacing formula is
        already the binding constraint by then) -- it's specifically the
        middle band in between, right where a player actually spends most
        of their time, that used to pay for thousands of extra canvas draw
        calls a frame. _TERRAIN_SYMBOL_MAX_COUNT closes that gap directly
        with a hard cap on total sampled points, rather than retuning the
        floor (which would just move the same cliff to a different zoom
        range instead of removing it)."""
        if self.mode != "political":
            return
        wd = self.world
        scale = self._place[2]
        spacing = max(_TERRAIN_SYMBOL_MIN_WORLD_SPACING,
                     round(_TERRAIN_SYMBOL_SCREEN_SPACING / max(scale, 0.01)))
        visible_area = max(1, (bx1 - bx0) * (by1 - by0))
        area_spacing = math.ceil(math.sqrt(visible_area / _TERRAIN_SYMBOL_MAX_COUNT))
        spacing = max(spacing, area_spacing)
        r = max(2.5, scale * spacing * 0.22)
        gy0 = by0 - by0 % spacing
        gx0 = bx0 - bx0 % spacing
        for gy in range(gy0, by1, spacing):
            for gx in range(gx0, bx1, spacing):
                if wd.owner[gy][gx] == OCEAN or (gx, gy) in wd.river_cells or (gx, gy) in wd.lake_cells:
                    continue
                if not self._cell_revealed(gx, gy):
                    continue
                biome = wd.biome_grid[gy][gx]
                if biome not in ("forest", "mountain"):
                    continue
                jx = self._terrain_jitter(gx, gy, 1) * spacing * 0.7
                jy = self._terrain_jitter(gx, gy, 2) * spacing * 0.7
                sx, sy = screen(gx + 0.5 + jx, gy + 0.5 + jy)
                if biome == "forest":
                    self._draw_forest_glyph(c, sx, sy, r)
                else:
                    self._draw_mountain_glyph(c, sx, sy, r)

    def _draw_terrain_legend(self, c):
        """A small always-visible key explaining the forest/mountain glyphs
        — fixed to the canvas corner (not tied to world coordinates, so it
        never pans/zooms with the map), like a real map legend. Political
        mode only, matching the symbols it explains."""
        if self.mode != "political":
            return
        x0, y0 = 12, 12
        row_h = 20
        w, h = 116, row_h * 2 + 16
        c.create_rectangle(x0, y0, x0 + w, y0 + h, fill=theme.PANEL,
                           outline=theme.LINE, width=1)
        c.create_text(x0 + w / 2, y0 + 10, text="LEGEND", fill=theme.MUTED,
                     font=("Segoe UI", 7, "bold"))
        ry = y0 + 16 + row_h * 0.5
        self._draw_forest_glyph(c, x0 + 16, ry, 7)
        c.create_text(x0 + 32, ry, text="Forest", fill=theme.INK,
                     font=("Segoe UI", 8), anchor="w")
        ry += row_h
        self._draw_mountain_glyph(c, x0 + 16, ry, 7)
        c.create_text(x0 + 32, ry, text="Mountain", fill=theme.INK,
                     font=("Segoe UI", 8), anchor="w")

    def _draw_ships(self, c, screen):
        """Beached Ships (app/world/commander.py) — a hull-shaped marker
        distinct from the Commander's diamond, drawn only for ships no
        commander is currently aboard (one being sailed is already
        represented by its Commander marker, so it doesn't need its own)."""
        wd = self.world
        aboard_ids = {cmd.aboard_ship_id for cmd in wd.commanders
                     if cmd.aboard_ship_id is not None}
        style = _SHIP_STYLE
        r = style["r"]
        for ship in wd.ships:
            if ship.id in aboard_ids:
                continue
            sx, sy = self._display_pos(ship)
            x, y = screen(sx + 0.5, sy + 0.5)
            if not self._visible_point(x, y):
                continue
            c.create_polygon(x - r, y + r * 0.4, x + r, y + r * 0.4,
                             x + r * 0.6, y - r * 0.5, x - r * 0.6, y - r * 0.5,
                             fill=style["fill"], outline=style["outline"], width=1.5)

    def _draw_commanders(self, c, screen):
        """Commander(s) (app/world/commander.py) — a distinct diamond
        marker, shown at every zoom level since it's a single mobile unit
        rather than something tied to one region, plus a thin dashed
        preview of its queued path (if any) so a move order is visible at a
        glance.

        Each commander wears its own realm's colour, so a marker on the map
        says WHOSE army that is at a glance rather than every faction's
        commander sharing one hue. The player's own keeps the distinct orchid
        it has always had — it's the one you give orders to, and it should
        never be mistaken for a rival's.

        Foreign commanders are fog-gated per cell, exactly like settlement
        markers: a rival marching through territory you cannot see must not
        be visible, and neither must the dashed preview of where he is headed
        (which would otherwise leak his destination through unexplored ground).
        """
        wd = self.world
        r = _COMMANDER_STYLE["r"]
        for cmd in wd.commanders:
            if not self._on_layer(cmd):
                continue        # gone below, or still up there
            mine = cmd.faction_idx == wd.player_faction_idx
            # Own commander: fixed orchid. Rival: his realm's colour, on a dark
            # outline so pale faction colours still read against the terrain.
            if mine:
                fill, outline = _COMMANDER_STYLE["fill"], _COMMANDER_STYLE["outline"]
            else:
                if not self._revealed_here(*self._display_cell(cmd)):
                    continue
                fill = wd.factions[cmd.faction_idx].color
                outline = "#11151b"

            if cmd.path is not None:
                remaining_path = self._visible_route(cmd)
                if len(remaining_path) >= 2:
                    pts = []
                    for gx, gy in remaining_path:
                        # A foreign march is only traced across ground you have
                        # actually explored.
                        if not mine and not self._revealed_here(gx, gy):
                            break
                        pts.extend(screen(gx + 0.5, gy + 0.5))
                    if len(pts) >= 4 and self._visible_pts(pts):
                        c.create_line(*pts, fill=fill, width=1.5,
                                      dash=(3, 3), capstyle="round", smooth=True)

            cx, cy = self._display_pos(cmd)
            x, y = screen(cx + 0.5, cy + 0.5)
            if not self._visible_point(x, y):
                continue
            if cmd is self.selected_commander:
                c.create_oval(x - r - 3, y - r - 3, x + r + 3, y + r + 3,
                              outline="#ffffff", width=2)
            c.create_polygon(x, y - r, x + r, y, x, y + r, x - r, y,
                             fill=fill, outline=outline, width=1.5)

    def _marker_radius(self, base_world_size):
        """Screen-pixel radius for a settlement/village marker: `base_world_size`
        (world-cell units) times the current zoom scale, floored/capped so a
        marker is never illegibly tiny zoomed out nor a giant blob zoomed
        all the way in. Shared by the draw calls and the click hit-tests
        (_on_click) so a marker's clickable area always matches what's
        actually drawn."""
        return max(_MARKER_MIN_R, min(_MARKER_MAX_R, base_world_size * self._place[2]))

    def _draw_settlements(self, c, screen):
        """Markers: city = circle, castle = triangle, town = square. The world
        view shows only cities (to avoid clutter); the region view shows every
        settlement of the zoomed faction, with names."""
        wd = self.world
        if self.zoom_faction is not None:
            sids = [sid for sid in self.zoom_faction.meta.get("settlements", [])
                    if self._node_visible(wd.settlements[sid])]
            show_names = True
        else:
            sids = [s.id for s in wd.settlements if s.kind == "city"
                    and self._node_visible(s)]
            show_names = False

        for sid in sids:
            st = wd.settlements[sid]
            style = _SETTLE_STYLE[st.kind]
            x, y = screen(st.pos[0] + 0.5, st.pos[1] + 0.5)
            if not self._visible_point(x, y):
                continue
            r = self._marker_radius(style["base"])
            if st is self.selected_settlement:      # selection ring
                c.create_oval(x - r - 3, y - r - 3, x + r + 3, y + r + 3,
                              outline="#ffffff", width=2)
            if st.kind == "city":
                c.create_oval(x - r, y - r, x + r, y + r, fill=style["fill"],
                              outline=style["outline"], width=1.5)
            elif st.kind == "castle":
                c.create_polygon(x, y - r - 1, x + r, y + r, x - r, y + r,
                                 fill=style["fill"], outline=style["outline"],
                                 width=1.5)
            else:
                c.create_rectangle(x - r, y - r, x + r, y + r,
                                   fill=style["fill"], outline=style["outline"],
                                   width=1.5)
            if show_names:
                c.create_text(x + 1, y + r + 8, text=st.name, fill="#000000",
                              font=("Segoe UI", 7))
                c.create_text(x, y + r + 7, text=st.name, fill="#e8e8e8",
                              font=("Segoe UI", 7))
            self._draw_alert_badge(c, x, y, r, st)

    def _draw_alert_badge(self, c, x, y, r, node):
        """A small warning triangle at a marker's upper-right, for any of
        the player's own settlements/villages with an active alert (see
        _refresh_alerts/_alert_node_ids) -- red for a critical problem
        (population actively being lost), amber for a mere warning. Not
        shown for anyone else's territory -- another faction's internal
        struggles aren't the player's to track."""
        severity = self._alert_node_ids.get(id(node))
        if severity is None:
            return
        color = theme.BAD if severity == "critical" else self._ALERT_WARN_COLOR
        bx, by = x + r * 0.75, y - r * 0.75
        br = max(4, r * 0.55)
        c.create_polygon(bx, by - br, bx + br, by + br, bx - br, by + br,
                         fill=color, outline=theme.ALERT_BG, width=1)
        # The "!" is a text item -- the most expensive kind the canvas has --
        # and below a handful of pixels it renders as an unreadable smudge on
        # top of an already-unmistakable coloured triangle. Zoomed out over a
        # developed realm this was hundreds of text items a frame for no
        # legible benefit, so it's drawn only once the badge is big enough to
        # actually read. The triangle itself still shows at every zoom, so an
        # alert is never silently hidden.
        if br >= _ALERT_BADGE_GLYPH_MIN_R:
            c.create_text(bx, by + br * 0.35, text="!", fill=theme.ALERT_BG,
                          font=("Segoe UI", max(6, int(br)), "bold"))

    def _fog_clip_runs(self, cells):
        """Split an ordered path into maximal contiguous runs where at
        least one endpoint of each step is revealed -- same "OR" rule
        _draw_roads already applies per segment, generalized to a whole
        polyline so a long trade route (or anything else drawn as a path)
        only actually renders the portion the player has found, not the
        whole thing just because one end happens to be visible. Yields
        the original `cells` unchanged, as one run, when fog isn't active
        at all (no player faction / sandbox world)."""
        if not self._fog_is_active():
            yield cells
            return
        run = []
        for i in range(len(cells) - 1):
            a, b = cells[i], cells[i + 1]
            if self._cell_revealed(*a) or self._cell_revealed(*b):
                if not run:
                    run.append(a)
                run.append(b)
            else:
                if len(run) >= 2:
                    yield run
                run = []
        if len(run) >= 2:
            yield run

    def _draw_currents(self, c, screen):
        """Ocean current streamlines (see app/world/currents.py), traced once
        at world generation and stored on the world -- this only draws the
        lines, never recomputes them. Opt-in (self.show_currents, off by
        default) rather than always-on: the world map is already carrying
        trade routes, roads and caravans, and currents are read-only
        flavour/planning information, not something that needs to compete
        with what you're actually managing every turn.

        Fog-gated per point the same way trade routes are per cell (loosely
        -- either end of a step revealed is enough): a current is a physical
        feature of ocean you haven't sailed, and showing the whole thing the
        moment one corner of the map is explored would hand over shape
        information about unexplored water for free."""
        lines = getattr(self.world, "current_streamlines", None)
        if not self.show_currents or not lines:
            return
        width = max(1.0, self._place[2] * 0.14)
        arrow_r = max(2.5, self._place[2] * 0.9)
        wd = self.world
        for line in lines:
            run = []
            for i in range(len(line)):
                x, y = line[i]
                cx, cy = int(x) % wd.w, min(max(int(y), 0), wd.h - 1)
                revealed = self._cell_revealed(cx, cy)
                if revealed:
                    run.append(line[i])
                    continue
                if len(run) >= 2:
                    self._draw_current_run(c, screen, run, width, arrow_r)
                run = []
            if len(run) >= 2:
                self._draw_current_run(c, screen, run, width, arrow_r)

    def _draw_current_run(self, c, screen, run, width, arrow_r):
        pts = []
        for gx, gy in run:
            pts.extend(screen(gx + 0.5, gy + 0.5))
        if not self._visible_pts(pts):
            return
        c.create_line(*pts, fill=_CURRENT_COLOR, width=width, capstyle="round",
                      joinstyle="round", smooth=True)
        # One direction chevron at the run's midpoint -- a plain line says
        # "water moves here," not which way, and "which way" is the whole
        # point for a trade route deciding whether to ride this or avoid it.
        mid = len(run) // 2
        if 0 < mid < len(run) - 1:
            (ax, ay), (bx, by) = run[mid - 1], run[mid + 1]
            dx, dy = bx - ax, by - ay
            mag = math.hypot(dx, dy) or 1.0
            ux, uy = dx / mag, dy / mag
            px, py = -uy, ux
            cx, cy = screen(run[mid][0] + 0.5, run[mid][1] + 0.5)
            tip = (cx + ux * arrow_r, cy + uy * arrow_r)
            left = (cx - ux * arrow_r * 0.6 + px * arrow_r * 0.55,
                   cy - uy * arrow_r * 0.6 + py * arrow_r * 0.55)
            right = (cx - ux * arrow_r * 0.6 - px * arrow_r * 0.55,
                    cy - uy * arrow_r * 0.6 - py * arrow_r * 0.55)
            c.create_polygon(*tip, *left, *right, fill=_CURRENT_ARROW_COLOR,
                             outline="")

    def _draw_trade_routes(self, c, screen):
        """Long-haul trade routes: land roads (solid gold, terrain-following)
        and sea lanes (dotted pale-blue), shown at every zoom level since they
        span the whole world rather than one region -- but only the stretch
        of a route the player has actually discovered (see _fog_clip_runs);
        a route between two OTHER factions shouldn't be legible in full just
        because you happened to reveal one end of it once."""
        width = max(1.0, self._place[2] * 0.22)
        for r in self.world.trade_routes:
            cells = r["cells"]
            if len(cells) < 2:
                continue
            if r["kind"] == "sea":
                color, w, dash = _TRADE_SEA_COLOR, max(1.0, width * 0.7), (1, 4)
            else:
                color, w, dash = _TRADE_LAND_COLOR, width, (7, 4)
            for run in self._fog_clip_runs(cells):
                pts = []
                for gx, gy in run:
                    pts.extend(screen(gx + 0.5, gy + 0.5))
                if not self._visible_pts(pts):
                    continue
                c.create_line(*pts, fill=color, width=w, capstyle="round",
                              joinstyle="round", dash=dash, smooth=True)

    def _draw_trade_caravans(self, c, screen):
        """Moving markers for active trade caravans (land) and ships (sea) —
        a glowing marker at the caravan's current interpolated position,
        with the *entire route it's currently on* redrawn in a bright color
        on top of the dim static line, so an active trade route is obvious
        at a glance and not just its small marker. No animation between
        turns; position only changes when render() runs again after End Turn.

        Both the route highlight and the marker itself respect fog of war
        the same as the static route line does (_draw_trade_routes) --
        only the discovered stretch of the highlight draws, and the
        marker itself is skipped entirely while the caravan's own current
        cell hasn't been revealed, so a caravan belonging to (or crossing)
        territory you haven't found isn't a giveaway."""
        width = max(1.0, self._place[2] * 0.22)

        # Highlight every route a caravan is currently traveling, before
        # drawing any markers on top of them.
        player_idx = self.world.player_faction_idx
        for caravan in self.world.trade_caravans:
            # Only YOUR active routes light up brightly; a neighbor's caravan
            # crossing your view gets a dim, thin highlight so it doesn't read
            # as your own trade (see the caravan style definitions).
            mine = player_idx is not None and player_idx in (caravan.seller_idx,
                                                             caravan.buyer_idx)
            if caravan.kind == "sea":
                color, w, dash = _ACTIVE_ROUTE_SEA_COLOR, max(1.0, width * 0.85), (2, 3)
            elif caravan.kind == "river":
                color, w, dash = _RIVER_CARAVAN_STYLE["glow"], width, (5, 3)
            else:
                color, w, dash = _ACTIVE_ROUTE_LAND_COLOR, width * 1.3, (9, 3)
            if not mine:
                color = {"sea": _FOREIGN_SEA_CARAVAN_STYLE,
                         "river": _FOREIGN_RIVER_CARAVAN_STYLE}.get(
                             caravan.kind, _FOREIGN_CARAVAN_STYLE)["glow"]
                w = max(1.0, w * 0.5)
            for run in self._fog_clip_runs(caravan.path):
                pts = []
                for gx, gy in run:
                    pts.extend(screen(gx + 0.5, gy + 0.5))
                if len(pts) < 4 or not self._visible_pts(pts):
                    continue
                c.create_line(*pts, fill=color, width=w, capstyle="round",
                              joinstyle="round", dash=dash, smooth=True)

        player_idx = self.world.player_faction_idx
        for caravan in self.world.trade_caravans:
            # Mid-slide this is where the caravan currently IS, not the cell it
            # will end the turn in -- so it is fog-gated on the ground it is
            # actually crossing (see _display_pos/_display_cell).
            if not self._cell_revealed(*self._display_cell(caravan)):
                continue
            x, y = screen(*[v + 0.5 for v in self._display_pos(caravan)])
            if not self._visible_point(x, y):
                continue
            # Your own trade vs. somebody else's passing through -- see the
            # style definitions. Roughly half the caravans crossing your view
            # at any time belong to other factions.
            mine = player_idx is not None and player_idx in (caravan.seller_idx,
                                                             caravan.buyer_idx)
            if caravan.kind == "sea":
                style = _SEA_CARAVAN_STYLE if mine else _FOREIGN_SEA_CARAVAN_STYLE
            elif caravan.kind == "river":
                style = _RIVER_CARAVAN_STYLE if mine else _FOREIGN_RIVER_CARAVAN_STYLE
            else:
                style = _CARAVAN_STYLE if mine else _FOREIGN_CARAVAN_STYLE
            r = style["r"]
            # glow: a couple of soft, oversized rings behind the solid
            # marker (canvas shapes are opaque, so the "glow" is faked with
            # progressively larger/dimmer-colored circles, not real alpha).
            c.create_oval(x - r * 2.4, y - r * 2.4, x + r * 2.4, y + r * 2.4,
                          fill="", outline=style["glow"], width=2)
            c.create_oval(x - r * 1.6, y - r * 1.6, x + r * 1.6, y + r * 1.6,
                          fill=style["glow"], outline="")
            if caravan.kind == "sea":
                c.create_polygon(x, y - r, x + r, y + r, x - r, y + r,
                                 fill=style["fill"], outline=style["outline"], width=2)
            else:
                c.create_rectangle(x - r, y - r, x + r, y + r,
                                   fill=style["fill"], outline=style["outline"], width=2)

    def _draw_trade_route_construction(self, c, screen):
        """Two growing dashed segments — one from each capital — for every
        land trade route currently under construction, meeting in the
        middle as both sides finish (see app/world/trade.py's
        TradeRouteProject.built_segments) -- fog-clipped the same as the
        finished route it becomes (_draw_trade_routes)."""
        wd = self.world
        width = max(1.0, self._place[2] * 0.18)
        for proj in wd.trade_route_projects:
            for seg in proj.built_segments:
                if len(seg) < 2:
                    continue
                for run in self._fog_clip_runs(seg):
                    pts = []
                    for gx, gy in run:
                        pts.extend(screen(gx + 0.5, gy + 0.5))
                    if not self._visible_pts(pts):
                        continue
                    c.create_line(*pts, fill=_TRADE_ROUTE_CONSTRUCTION_COLOR, width=width,
                                  capstyle="round", joinstyle="round", dash=(3, 5), smooth=True)

    def _draw_construction(self, c, screen):
        """A growing dashed road (only the portion actually built so far —
        it physically extends turn by turn) and a hollow, dashed
        construction-site marker for each City/Town/Castle being built."""
        wd = self.world
        width = max(1.0, self._place[2] * 0.18)
        for road in wd.road_projects:
            cells = road.built_cells
            if len(cells) < 2:
                continue
            pts = []
            for gx, gy in cells:
                pts.extend(screen(gx + 0.5, gy + 0.5))
            if not self._visible_pts(pts):
                continue
            c.create_line(*pts, fill=_DIRT_ROAD_COLOR, width=width, capstyle="round",
                          dash=(4, 3), smooth=True)

        for project in wd.settlement_projects:
            x, y = screen(project.pos[0] + 0.5, project.pos[1] + 0.5)
            if not self._visible_point(x, y):
                continue
            r = 4
            c.create_rectangle(x - r, y - r, x + r, y + r, outline="#f2e9c9",
                               width=2, dash=(2, 2))
            label = f"{project.kind[0].upper()}·{project.turns_left}t"
            c.create_text(x + 1, y + r + 8, text=label,
                         fill="#000000", font=("Segoe UI", 7))
            c.create_text(x, y + r + 7, text=label,
                         fill="#f2e9c9", font=("Segoe UI", 7))

    def _draw_placement_hint(self, c, screen):
        """While a settlement placement is armed (self.building_mode), mark
        the region's own best-scoring cells (see _score_placement_hint) with
        a small gold dot -- purely advisory, same land-scoring formula
        world-gen and the AI use, so the player can see at a glance where a
        City/Castle/Town would naturally want to sit without being made to
        build there. Clicking anywhere else in the region still works."""
        if self.building_mode is None or not self._placement_hint_cells:
            return
        for gx, gy in self._placement_hint_cells:
            x, y = screen(gx + 0.5, gy + 0.5)
            if not self._visible_point(x, y):
                continue
            r = 2.5
            c.create_oval(x - r, y - r, x + r, y + r,
                         fill="#ffec78", outline="")

    def _river_span(self, ax, ay, bx, by):
        """(t0, t1) fractional span along the straight segment (ax,ay)->
        (bx,by) that passes over river cells, or None if it never does.
        Endpoints are always village/settlement positions, which by
        placement rules never sit on a river themselves, so any crossing is
        strictly in the interior — used to redraw just that stretch as a
        bridge instead of recoloring the whole road."""
        wd = self.world
        dx, dy = bx - ax, by - ay
        steps = max(abs(dx), abs(dy))
        if steps == 0:
            return None
        hits = [i for i in range(steps + 1)
               if (round(ax + dx * i / steps), round(ay + dy * i / steps)) in wd.river_cells]
        if not hits:
            return None
        return (max(0.0, (min(hits) - 0.5) / steps), min(1.0, (max(hits) + 0.5) / steps))

    # --- road geometry ---------------------------------------------------
    # A road on a map is never a ruler-drawn line meeting another at a hard
    # elbow, and that is exactly what these were: stored as endpoint pairs and
    # drawn one straight segment at a time. Three things fix it, all of them
    # VIEW-ONLY -- nothing in app/world knows any of this exists, the stored
    # network is unchanged, and no save needs migrating.
    #
    #   1. chain   worldgen.road_chains turns loose segments into connected
    #              runs, because you cannot smooth a line two points at a time.
    #   2. wander  each cell gets a small fixed offset, so the road drifts off
    #              the grid instead of tracking it. Derived by hashing the cell,
    #              which matters more than it sounds: a junction cell must get
    #              the SAME offset from every road that meets there, or the
    #              arms come apart.
    #   3. smooth  Catmull-Rom through the wandered points, so the corners are
    #              curves. This is also what stops a 40-cell straight link from
    #              reading as a drawn line -- it now bows gently along its
    #              length the way a real road follows the ground.
    #
    # A stone road wanders less than a dirt track, which is the whole
    # difference between an engineered road and a cart route that grew.
    _ROAD_WANDER = {"stone": 0.22, "dirt": 0.45, "sea": 0.0}
    _ROAD_SUBDIV = 2        # Catmull-Rom points per source span
    # A control point every couple of cells, evenly. This started at one per
    # cell to stop the spline overshooting where a short span met a long one,
    # back when the spline was uniform Catmull-Rom; centripetal handles uneven
    # spacing properly, so the dense sampling was buying nothing. Halving it
    # took a developed realm from 15,786 drawn points to 7,938 -- which is
    # what the roads lagging at close zoom actually was -- with the measured
    # stray off route unchanged at 0.33 cells mean, 0.76 worst.
    _ROAD_DENSIFY = 2.0
    # The offset is drawn on a COARSER grid than the road's own points, so
    # neighbouring points share it and the road meanders instead of shaking.
    # Per-point white noise was the first attempt and it read as a wobbly line
    # rather than a road following the ground -- a road bends over a hundred
    # yards, not over every yard.
    _ROAD_WANDER_GRID = 4

    @staticmethod
    def _cell_wander(x, y, amount):
        """A small, fixed, cell-derived offset. Deterministic and position-only
        -- never random and never per-frame, or the roads would crawl."""
        if not amount:
            return 0.0, 0.0
        h = (x * 73856093) ^ (y * 19349663)
        h = (h ^ (h >> 13)) * 1274126177 & 0xFFFFFFFF
        return (((h >> 5) & 1023) / 1023.0 - 0.5) * 2 * amount,                (((h >> 17) & 1023) / 1023.0 - 0.5) * 2 * amount

    def _road_points(self, cells, tier):
        """A chain of road cells as a smoothed, wandering polyline in world
        coordinates. Cached per (chain, tier) against the road network's own
        segment count, because none of it changes until a road is built."""
        signature = sum(len(v) for v in self.world.roads_by_region.values())
        cache = getattr(self, "_road_points_cache", None)
        if cache is None or cache[0] != signature:
            cache = (signature, {})
            self._road_points_cache = cache
        # The WHOLE run, not its endpoints and length. Two different chains
        # can easily share a first cell, a last cell and a length -- roads
        # meet at junctions -- and a key that cannot tell them apart hands one
        # of them the other's geometry. That is how a three-cell dirt track
        # ended up drawn nearly seven cells clear of its own route.
        key = (tuple(cells), tier)
        hit = cache[1].get(key)
        if hit is not None:
            return hit

        amount = self._ROAD_WANDER.get(tier, 0.0)
        # Densify first: a link stored as one 40-cell jump has nothing between
        # its ends to bend, so it would stay a straight line however much the
        # rest wandered.
        dense = []
        for (ax, ay), (bx, by) in zip(cells, cells[1:]):
            steps = max(1, int(max(abs(bx - ax), abs(by - ay)) / self._ROAD_DENSIFY))
            for i in range(steps):
                t = i / steps
                dense.append((ax + (bx - ax) * t, ay + (by - ay) * t))
        dense.append(cells[-1])

        pts = []
        for i, (x, y) in enumerate(dense):
            # The two ends stay put: they are a settlement's or a village's own
            # cell, and a road that does not quite touch the place it serves
            # looks like a bug rather than like character.
            edge = i == 0 or i == len(dense) - 1
            g = self._ROAD_WANDER_GRID
            dx, dy = (0.0, 0.0) if edge else self._cell_wander(
                int(x) // g, int(y) // g, amount)
            # Eased off towards each end, so a road still meets the place it
            # serves square-on rather than sidling up to it.
            taper = min(1.0, min(i, len(dense) - 1 - i) / 3.0)
            pts.append((x + 0.5 + dx * taper, y + 0.5 + dy * taper))
        if len(pts) < 3:
            result = pts
        else:
            result = _catmull_rom(pts, self._ROAD_SUBDIV)
        cache[1][key] = result
        return result

    def _draw_road_chain(self, c, screen, cells, tier, width):
        """One connected run of road as a single smoothed polyline, plus a
        brown bridge span wherever a stone road crosses a river.

        One canvas item per RUN rather than per segment, which on a developed
        realm is a few hundred lines where it used to be a few thousand -- the
        smoothing pays for itself and then some."""
        if not (self._cell_revealed(*cells[0]) or self._cell_revealed(*cells[-1])):
            return
        is_sea = tier == "sea"
        is_stone = tier == "stone"
        pts = []
        for wx, wy in self._road_points(cells, tier):
            pts.extend(screen(wx, wy))
        if len(pts) < 4 or not self._visible_pts(pts):
            return
        if is_sea:
            # A lane is on the water, not in it -- nothing to cut into.
            c.create_line(*pts, fill=_TRADE_SEA_COLOR, width=width,
                          capstyle="round", joinstyle="round", dash=(2, 3))
            return
        color = _STONE_ROAD_COLOR if is_stone else _DIRT_ROAD_COLOR
        # The cut first: darker and wider, so the surface sits down inside it.
        c.create_line(*pts, fill=_darken(color, _ROAD_CUT_DARKEN),
                      width=width * _ROAD_CUT_WIDTH, capstyle="round",
                      joinstyle="round")
        # Then the surface. A stone road is laid and runs solid; a dirt track
        # is worn, so it runs broken and the cut shows through in patches.
        c.create_line(*pts, fill=color,
                      width=width if is_stone else width * _DIRT_SURFACE_NARROW,
                      capstyle="round", joinstyle="round",
                      dash=None if is_stone else _DIRT_SURFACE_DASH)
        if is_stone:
            # Bridges stay per-crossing: it is the one part of a road that is
            # genuinely a different object, and it sits on top of the line
            # rather than replacing a piece of it.
            for (ax, ay), (bx, by) in zip(cells, cells[1:]):
                span = self._river_span(ax, ay, bx, by)
                if span is None:
                    continue
                x0, y0 = screen(ax + 0.5, ay + 0.5)
                x1, y1 = screen(bx + 0.5, by + 0.5)
                t0, t1 = span
                c.create_line(x0 + (x1 - x0) * t0, y0 + (y1 - y0) * t0,
                              x0 + (x1 - x0) * t1, y0 + (y1 - y0) * t1,
                              fill=_BRIDGE_COLOR, width=width * 1.2,
                              capstyle="round")

    def _draw_road_segment(self, c, screen, ax, ay, bx, by, color, width, dash=None, bridge=False):
        """One road segment. Stone roads (bridge=True) that cross a river
        get the crossing stretch recolored brown (_BRIDGE_COLOR) — see
        _river_span — so it visually reads as a bridge instead of the road
        just barging through the water.

        Off-screen segments bail out here rather than in _draw_roads so the
        cull also skips _river_span below -- that walks every cell along the
        segment against world.river_cells, which is far more expensive than
        the create_line it feeds."""
        x0, y0 = screen(ax + 0.5, ay + 0.5)
        x1, y1 = screen(bx + 0.5, by + 0.5)
        if not self._visible_bbox(x0, y0, x1, y1):
            return
        span = self._river_span(ax, ay, bx, by) if bridge else None
        if span is None:
            c.create_line(x0, y0, x1, y1, fill=color, width=width,
                          capstyle="round", dash=dash)
            return
        t0, t1 = span
        mx0, my0 = x0 + (x1 - x0) * t0, y0 + (y1 - y0) * t0
        mx1, my1 = x0 + (x1 - x0) * t1, y0 + (y1 - y0) * t1
        if t0 > 0:
            c.create_line(x0, y0, mx0, my0, fill=color, width=width,
                          capstyle="round", dash=dash)
        c.create_line(mx0, my0, mx1, my1, fill=_BRIDGE_COLOR, width=width,
                      capstyle="round")
        if t1 < 1:
            c.create_line(mx1, my1, x1, y1, fill=color, width=width,
                          capstyle="round", dash=dash)

    def _draw_roads(self, c, screen):
        """Straight road segments linking every village and settlement
        across a faction's regions (an MST per region — see
        _place_villages_for_region). Per-segment tier, not per-region: Dirt
        (brown/dashed) for any road touching a village, Stone (gray/solid)
        for a road connecting two settlements. Dirt only shows once zoomed
        into a specific nation's regions (too minor to matter at world
        scale); Stone — the trunk network — is visible even from the world
        map, same idea as trade routes already being shown at every zoom
        level. A stone road crossing a river gets a brown bridge span (see
        _draw_road_segment) — dirt tracks don't bother with one.

        Dirt is gated a second time on the zoom level within region/village
        view (_DIRT_ROAD_MIN_SCALE) — see the comment below."""
        wd = self.world
        width = max(1.0, self._place[2] * 0.18)

        chains = road_chains(wd)
        if self.zoom_faction is None:
            for region in wd.regions:
                if region.faction_idx < 0:
                    continue
                for cells, tier in chains.get(region.id, ()):
                    if tier not in ("stone", "sea"):
                        continue
                    self._draw_road_chain(c, screen, cells, tier, width)
            return

        # Dirt tracks are the densest thing on the map -- a developed realm has
        # thousands of them, and at the wide end of village view (the camera
        # you land on entering it) they alone were about half of every canvas
        # item drawn, for a tangle of 1px lines too fine to read anything from.
        # They come in once the camera is close enough for them to mean
        # something; stone roads (and sea lanes, the other trunk-scale
        # connector) still show at every zoom exactly as before.
        show_dirt = self._place[2] >= _DIRT_ROAD_MIN_SCALE
        # Dirt first, trunk roads over the top. Where a stone road and a dirt
        # track meet -- a junction, or a track that was paved along part of
        # its length -- the stone road is the one that should read, and list
        # order alone used to decide that at random.
        runs = [(cells, tier)
                for cid in self.zoom_faction.meta.get("regions", [])
                for cells, tier in chains.get(cid, ())]
        runs.sort(key=lambda run: _ROAD_DRAW_ORDER.get(run[1], 0))
        for cells, tier in runs:
            if tier not in ("stone", "sea") and not show_dirt:
                continue
            self._draw_road_chain(c, screen, cells, tier, width)

    def _draw_villages(self, c, screen):
        """Small dots for villages — only shown once zoomed in close enough
        within a faction's own territory (see _villages_visible), covering
        every village the zoomed faction owns, not just one region. Names
        are skipped past a village-count threshold to avoid label soup.

        Both the markers and the name threshold are viewport-relative: a
        developed realm can own hundreds of villages, and drawing (and
        counting) all of them regardless of where the camera is was the
        single largest per-frame cost in village view. Culling to what's
        on screen means zooming in genuinely gets cheaper, and it also makes
        the label rule behave the way a player expects -- names appear once
        you're close enough to read them, instead of being switched off
        forever by a realm-wide village count."""
        if not self._villages_visible():
            return
        wd = self.world
        style = _VILLAGE_STYLE
        r = self._marker_radius(style["base"])
        zf = wd.factions.index(self.zoom_faction)
        visible = []
        for v in wd.villages:
            if v.faction_idx != zf or not self._node_visible(v):
                continue
            x, y = screen(v.pos[0] + 0.5, v.pos[1] + 0.5)
            if not self._visible_point(x, y):
                continue
            visible.append((v, x, y))
        show_names = (len(visible) <= _VILLAGE_LABEL_LIMIT
                      and self._place[2] >= _VILLAGE_LABEL_MIN_SCALE)
        for v, x, y in visible:
            if v is self.selected_village:          # selection ring
                c.create_oval(x - r - 3, y - r - 3, x + r + 3, y + r + 3,
                              outline="#ffffff", width=2)
            c.create_oval(x - r, y - r, x + r, y + r, fill=style["fill"],
                          outline=style["outline"], width=1)
            if show_names:
                c.create_text(x + 1, y + r + 7, text=v.name, fill="#000000",
                              font=("Segoe UI", 6))
                c.create_text(x, y + r + 6, text=v.name, fill="#e8e8e8",
                              font=("Segoe UI", 6))
            self._draw_alert_badge(c, x, y, r, v)

    def _draw_labels(self, c, screen):
        wd = self.world
        if self._villages_visible():
            return   # zoomed to village level: region/faction name labels aren't useful here
        if self.zoom_faction is not None:
            # Realm view used to label every single region. With a developed
            # realm that's dozens of names stacked over the terrain, and it
            # buried the settlements and roads underneath -- the region's name
            # is still one click away in its own panel. Only nation names are
            # sparse enough to be worth drawing over the map.
            return
        items = [f for f in wd.factions if self._is_known(f) and not is_eliminated(f)]
        player_idx = wd.player_faction_idx
        # The player's own kingdom always gets a label; everyone else follows
        # in the existing order and is skipped once their name would land on
        # top of one already placed. Without this, a map with several rivals
        # near each other draws every name directly over its neighbors --
        # unreadable overlapping text instead of legible kingdom names -- and
        # there was no guarantee your OWN kingdom's name survived that
        # pileup rather than a rival's.
        if player_idx is not None:
            items.sort(key=lambda f: f is not wd.factions[player_idx])
        placed_boxes = []
        pad = 3
        for f in items:
            lx, cy = screen(f.center[0] * wd.w, f.center[1] * wd.h)
            # Offset above the anchor point rather than centered on it -- a
            # nation's capital (and its commander's diamond, which starts
            # there) sits right at that point too, and a label drawn exactly
            # on top of its own capital marker read as unreadable overlap
            # even once OTHER nations' names stopped colliding with it.
            ly = cy - 14.0
            shadow = c.create_text(lx + 1, ly + 1, text=f.name, fill="#000000",
                                   font=_LABEL_FONT)
            box = c.bbox(shadow)
            if box and any(not (box[2] + pad < ox0 or box[0] - pad > ox1
                                or box[3] + pad < oy0 or box[1] - pad > oy1)
                          for ox0, oy0, ox1, oy1 in placed_boxes):
                c.delete(shadow)
                continue
            c.create_text(lx, ly, text=f.name, fill="#ffffff", font=_LABEL_FONT)
            placed_boxes.append(box)

    def _weathered_regions(self):
        """(region, event) for every region under weather the player may see.

        Fog-gated on the region's own centre, exactly like its name: weather
        over a rival's territory you have never explored is not something you
        would know about, and leaking it would quietly turn the overlay into
        a scouting tool.

        Cached per turn. Both _map_lines and _map_labels call this, the flat
        map calls both every rebuild, and walking every region in the world
        twice a frame to answer a question that changes once a turn is the
        kind of thing that shows up as a stutter later."""
        wd = self.world
        events = getattr(wd, "region_weather", None)
        if not events:
            return ()
        key = (wd.turn, len(events))
        cached = getattr(self, "_weather_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        out = []
        for region_id, event in events.items():
            if not (0 <= region_id < len(wd.regions)) or event is None:
                continue
            region = wd.regions[region_id]
            cx = int(region.center[0] * wd.w)
            cy = int(region.center[1] * wd.h)
            if not self._cell_revealed(cx, cy):
                continue
            out.append((region, event))
        self._weather_cache = (key, out)
        return out

    def _region_border_segments(self, region):
        """Screen-space-independent (x,y) edge list tracing a region's
        outline: every cell-edge where the neighboring cell belongs to a
        different region (or is off-map)."""
        wd = self.world
        cg = wd.region_grid
        cid = region.id
        segs = []
        for x, y in region.cells:
            for dx, dy, corners in (
                    (1, 0, ((1, 0), (1, 1))), (-1, 0, ((0, 0), (0, 1))),
                    (0, 1, ((0, 1), (1, 1))), (0, -1, ((0, 0), (1, 0)))):
                nx, ny = x + dx, y + dy
                n_cid = cg[ny][nx] if 0 <= nx < wd.w and 0 <= ny < wd.h else -999
                if n_cid != cid:
                    (ox0, oy0), (ox1, oy1) = corners
                    segs.append((x + ox0, y + oy0, x + ox1, y + oy1))
        return segs

    def _draw_attack_targets(self, c, screen):
        """While picking an attack target, outline every attackable frontier
        region in red so it's obvious which land can be struck."""
        if self.attack_mode is None:
            return
        wd = self.world
        width = max(2.0, self._place[2] * 0.3)
        for region in self._attack_frontier:
            for x0, y0, x1, y1 in self._region_border_segments(region):
                sx0, sy0 = screen(x0, y0)
                sx1, sy1 = screen(x1, y1)
                if not self._visible_bbox(sx0, sy0, sx1, sy1):
                    continue
                c.create_line(sx0, sy0, sx1, sy1, fill=theme.BAD, width=width,
                              capstyle="round")
            lx, ly = screen(region.center[0] * wd.w, region.center[1] * wd.h)
            c.create_text(lx + 1, ly + 1, text=region.name, fill="#000000",
                          font=_LABEL_FONT)
            c.create_text(lx, ly, text=region.name, fill="#ffffff", font=_LABEL_FONT)

    def _draw_flash(self, c, screen):
        """Blinking outline around a region after a battle: gold for a
        region gained, red for a failed attack — a few strobes that settle
        down as the overall fade envelope runs out."""
        if self._flash_region is None:
            return
        elapsed = time.time() - self._flash_start
        envelope = max(0.0, 1.0 - elapsed / _FLASH_DURATION)
        pulse = abs(math.sin(elapsed * _FLASH_FREQ * math.pi))
        fade = envelope * (0.35 + 0.65 * pulse)
        target = _FLASH_FAIL_COLOR if self._flash_outcome == "failure" else _FLASH_COLOR
        base = _hex_to_rgb(theme.CANVAS)
        color = "#%02x%02x%02x" % tuple(
            int(base[j] + (target[j] - base[j]) * fade) for j in range(3))
        width = max(2.0, self._place[2] * (0.18 + 0.35 * fade))
        for x0, y0, x1, y1 in self._region_border_segments(self._flash_region):
            sx0, sy0 = screen(x0, y0)
            sx1, sy1 = screen(x1, y1)
            if not self._visible_bbox(sx0, sy0, sx1, sy1):
                continue
            c.create_line(sx0, sy0, sx1, sy1, fill=color, width=width,
                          capstyle="round")
