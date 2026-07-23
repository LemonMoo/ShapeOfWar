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
import tkinter as tk

from PIL import Image, ImageTk

from app.ui import theme
from app.world.world_map import Stance
from app.world.worldgen import OCEAN
from app.world.territory import bordering_regions, naval_reachable_regions
from app.world.resources import RESOURCES
from app.world import resources
from app.world import diplomacy
from app.world import construction
from app.world import trade
from app.world import expansion
from app.world import commander

_FLASH_COLOR = (255, 236, 120)   # bright gold — region gained
_FLASH_FAIL_COLOR = (232, 74, 62)  # bright red — region attack failed
_FLASH_DURATION = 2.2            # seconds
_FLASH_FREQ = 1.8                # blink cycles per second

_LABEL_FONT = ("Segoe UI", 8, "bold")

# Free camera (drag-pan / wheel-zoom).
_DRAG_THRESHOLD_PX = 4   # movement past this on a press+move counts as a drag, not a click
_ZOOM_STEP = 0.9         # view-span multiplier per wheel notch
_MIN_ZOOM_CELLS = 6      # closest allowed zoom (world-cells across the short viewport edge)

_OCEAN_DEEP = (18, 30, 58)
_OCEAN_SHALLOW = (44, 74, 120)
_LAKE_RGB = (48, 92, 140)      # inland lake water (shown in every map mode)

# Fog of war (see app/world/vision.py) — unexplored land/sea, world view only.
_FOG_HIDDEN_RGB = (7, 9, 14)

# Per-region lightness offsets so neighboring regions of a faction read apart.
_REGION_SHADES = [-0.12, 0.10, 0.22, -0.04, 0.15, 0.02, 0.28, -0.09, 0.06, 0.19]


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb(r, g, b):
    clamp = lambda v: max(0, min(255, int(v)))
    return (clamp(r), clamp(g), clamp(b))


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
    "forest": (40, 110, 58),
    "plains": (168, 178, 84),
    "coastal": (94, 168, 176),
    "desert": (206, 178, 110),
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
_POL_FOREST_TINT = 0.4
_POL_MOUNTAIN_TINT = 0.35

# Symbols layered on top of the color tint above (political mode only) —
# color alone doesn't read clearly enough at a glance, especially at this
# map's size. See _draw_terrain_symbols/_draw_terrain_legend.
_FOREST_SYMBOL_FILL = "#173d20"
_FOREST_SYMBOL_OUTLINE = "#0a1f10"
_MOUNTAIN_SYMBOL_FILL = "#eef0f2"
_MOUNTAIN_SYMBOL_OUTLINE = "#585860"
_TERRAIN_SYMBOL_SCREEN_SPACING = 26   # target px between sampled points on screen
_TERRAIN_SYMBOL_MIN_WORLD_SPACING = 3   # never sample closer than this many world cells


def _climate_rgb(climate):
    return _CLIMATE_COLORS.get(climate, _NO_DATA_RGB)


# River cells are baked directly into the terrain raster (_precompute_colors,
# same treatment as lake_cells), not drawn as a separate vector line on top —
# a muted fresh-water blue, distinct from but close in tone to lake/ocean, so
# a river reads as part of the terrain instead of a decal floating over it.
_RIVER_RGB = (64, 112, 152)

# Settlement marker styling (drawn as canvas shapes — no art assets).
_SETTLE_STYLE = {
    "city":   {"fill": "#f2e9c9", "outline": "#4a4230", "r": 5},
    "castle": {"fill": "#c9ccd6", "outline": "#3a3f4c", "r": 4},
    "town":   {"fill": "#d9b98a", "outline": "#4a3a24", "r": 3},
}
_VILLAGE_STYLE = {"fill": "#c9a06a", "outline": "#4a3418", "r": 2}
# Local roads (village/settlement network within a region — see
# _place_villages_for_region in app/world/worldgen.py): Dirt for a road
# touching a village, brown; Stone for a road linking two settlements, gray.
_DIRT_ROAD_COLOR = "#8a6f4a"
_STONE_ROAD_COLOR = "#9a9ba3"
_BRIDGE_COLOR = "#6e4326"   # a stone road's river crossing, recolored like timber decking
_TRADE_LAND_COLOR = "#7c5f26"   # long-haul trade road — dark bronze, recedes into the map
_TRADE_SEA_COLOR = "#557c8c"    # dark shipping-lane blue, dotted like a nautical chart
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
_CARAVAN_STYLE = {"fill": "#fff3c4", "outline": "#5a4318", "r": 6, "glow": "#ffcf5c"}
_SEA_CARAVAN_STYLE = {"fill": "#c8f5ff", "outline": "#154a5c", "r": 6, "glow": "#5fd0ff"}
# Commander (app/world/commander.py) — a bright orchid diamond, deliberately
# unlike any settlement/caravan color so the player's own unit never gets
# confused with anything else on the map.
_COMMANDER_STYLE = {"fill": "#e685ff", "outline": "#4a1a5c", "r": 7}
_SHIP_STYLE = {"fill": "#c9a86a", "outline": "#5c3f1a", "r": 6}
# Above this many villages in a region, skip name labels (village view) so it
# doesn't turn into unreadable text soup.
_VILLAGE_LABEL_LIMIT = 24


def _fmt_amount(n):
    """Compact number formatting for resource amounts (12345 -> '12.3k')."""
    if n >= 10000:
        return f"{n / 1000:.0f}k"
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


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
    all of it. Mirrors construction.can_afford's own three-way split:
    Gold from the treasury, a settlement-storage resource (Phase 12:
    includes Logs/Stone/Iron now) summed across the faction's settlements,
    anything else from the old shared pool."""
    res = nation.stats.get("resources", {})
    gold = nation.stats.get("gold", 0)
    missing = {}
    for resource, amount in cost.items():
        if resource == "Gold":
            have = gold
        elif resource in resources._SETTLEMENT_STORAGE_RESOURCES:
            have = construction._faction_settlement_stock(nation, resource, world)
        else:
            have = res.get(resource, 0)
        if have < amount:
            missing[resource] = amount - have
    return missing


class MapView(tk.Frame):
    def __init__(self, master, world, on_attack, on_end_turn,
                on_wildland_claim=None):
        super().__init__(master, bg=theme.BG)
        self.on_attack = on_attack
        self.on_end_turn = on_end_turn
        self.on_wildland_claim = on_wildland_claim
        self.selected = None            # selected faction (world view)
        self.zoom_faction = None        # faction we've zoomed into (region view)
        self.selected_region = None
        self.zoom_region = None         # region we've zoomed into (village view)
        self.selected_settlement = None
        self.selected_village = None
        self.selected_commander = None
        self.commander_move_mode = None   # armed Commander awaiting a destination click
        self.mode = "political"
        self._img = None
        self._place = (0, 0, 1)         # vx0, vy0, scale
        self._base_img = None           # cached full-grid PIL image
        self._fog_overlay_img = None    # cached fog mask ("L" image) — see _ensure_fog_overlay
        self._fog_key = None
        self._base_key = None           # signature of what _base_img depicts
        self._anim_id = None

        # Free camera (drag-pan / wheel-zoom): independent of the click-
        # driven drill-down zoom (_start_zoom/_animate below), but writes
        # the same self.view/self.view_target so both can coexist.
        self._press_xy = None
        self._dragged = False
        self._animating = False

        # Attack-target picking: when not None, we've zoomed to the shared
        # border with `_attack_enemy` and clicking one of `_attack_frontier`
        # regions launches the battle for it.
        self.attack_mode = None
        self._attack_enemy = None
        self._attack_frontier = []

        # Castle placement: when not None, holds the (own-territory) region
        # the player is about to click a build site within.
        self.building_mode = None

        # Post-battle border flash (see flash_region()): "success" (gold) for
        # a region gained, "failure" (red) for a failed attack.
        self._flash_region = None
        self._flash_outcome = "success"
        self._flash_start = 0.0
        self._flash_id = None
        self._bottom_msg_after_id = None

        # Resources gained/lost on the turn just ended, keyed by resource
        # name (including "Gold"); shown alongside current totals in the
        # resource bar until the next End Turn overwrites them.
        self._resource_deltas = {}

        self._build_resource_bar()

        self.canvas = tk.Canvas(self, bg=theme.CANVAS, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.render())
        # Free camera: press/drag/release (drag pans, a plain click still
        # drills down/selects exactly as before) plus wheel-zoom.
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        # QoL: right-click sends the currently-selected Commander straight
        # to that spot — no need to click Move first (which still works too).
        self.canvas.bind("<Button-3>", self._on_right_click)

        self.bottom_msg = tk.Label(self, text="", bg="#0d1017", fg=theme.INK,
                                   font=("Segoe UI", 13, "bold"), padx=18, pady=10)

        self._build_panel()
        self.set_world(world)

    # --- world binding -----------------------------------------------------
    def set_world(self, world):
        self.world = world
        self.selected = None
        self.zoom_faction = None
        self.selected_region = None
        self.zoom_region = None
        self.selected_settlement = None
        self.selected_village = None
        self.selected_commander = None
        self.commander_move_mode = None
        self.attack_mode = None
        self._attack_enemy = None
        self._attack_frontier = []
        self.building_mode = None
        self._flash_region = None
        if self._flash_id is not None:
            self.after_cancel(self._flash_id)
            self._flash_id = None
        self._hide_bottom_message()
        self.view = self._world_view_rect()
        self.view_target = list(self.view)
        self._base_img = self._base_key = None
        self._fog_overlay_img = None
        self._fog_key = object()   # never matches any real fog_version -> forces a rebuild
        self._precompute_colors()
        self._last_territory_version = getattr(self.world, "territory_version", 0)
        self._exit_ui()
        self._hide_prosperity_bar()
        self.info.config(fg=theme.MUTED, text="Click a faction to inspect it.")
        for frame in (self.rel_frame, self.actions):
            for w in frame.winfo_children():
                w.destroy()
        self._resource_deltas = {}
        self._update_resource_bar()
        self._update_turn_label()
        self.render()

    def refresh(self):
        """Recompute cached tile colors and panel text after the World's
        ownership data was mutated in place (e.g. a territory transfer),
        without resetting the camera/selection the way set_world() does.

        _precompute_colors() rebuilds every cell's color from scratch —
        O(w*h), the single most expensive thing this view does on a large
        map — so it's only actually re-run when region ownership changed
        (world.territory_version, bumped by territory.transfer_region) since
        the last time. Most End Turn calls don't transfer any territory, so
        this used to be pure wasted work every single turn."""
        from app.world import vision
        vision.recompute(self.world)
        territory_version = getattr(self.world, "territory_version", 0)
        if territory_version != getattr(self, "_last_territory_version", None):
            self._precompute_colors()
            self._last_territory_version = territory_version
        self._base_img = self._base_key = None
        if self.selected is not None:
            self._show_faction(self.selected)
        if self.selected_region is not None:
            self._show_region(self.selected_region)
        self._update_resource_bar()
        self._update_turn_label()
        self.render()

    def _precompute_colors(self):
        """Flat row-major RGB pixel lists for every view (for Image.putdata)."""
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
        sea = wd.sea_level
        fcolors = [_hex_to_rgb(f.color) for f in wd.factions]

        # a shaded color per region (varied within its faction)
        cshade = [None] * len(wd.regions)
        for f in wd.factions:
            fc = _hex_to_rgb(f.color)
            for li, cid in enumerate(f.meta.get("regions", [])):
                cshade[cid] = _shade(fc, _REGION_SHADES[li % len(_REGION_SHADES)])

        cg = wd.region_grid
        i = 0
        for y in range(wd.h):
            for x in range(wd.w):
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
                    if biome_here == "forest":
                        base = _rgb(*_blend(base, _BIOME_COLORS["forest"], _POL_FOREST_TINT))
                    elif biome_here == "mountain":
                        base = _rgb(*_blend(base, _BIOME_COLORS["mountain"], _POL_MOUNTAIN_TINT))

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
                i += 1

    # --- resource bar --------------------------------------------------------
    def _build_resource_bar(self):
        rb = tk.Frame(self, bg=theme.PANEL, width=190)
        rb.pack(side="left", fill="y")
        rb.pack_propagate(False)
        self._resource_bar = rb

        tk.Label(rb, text="RESOURCES", bg=theme.PANEL, fg=theme.MUTED,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=12, pady=(14, 6))
        self._resource_rows = tk.Frame(rb, bg=theme.PANEL)
        self._resource_rows.pack(fill="both", expand=True, padx=12)

    def _current_resource_snapshot(self):
        """This turn's totals for the player faction: stockpiled resources
        plus Gold, as one flat dict."""
        player = self._player_faction()
        if player is None:
            return {}
        snap = dict(player.stats.get("resources", {}))
        snap["Gold"] = player.stats.get("gold", 0)
        return snap

    def _update_resource_bar(self):
        for w in self._resource_rows.winfo_children():
            w.destroy()
        current = self._current_resource_snapshot()
        if self._player_faction() is None:
            tk.Label(self._resource_rows, text="No realm selected.",
                     bg=theme.PANEL, fg=theme.MUTED, font=theme.FONT,
                     wraplength=160, justify="left").pack(anchor="w", pady=4)
            return

        order = ["Gold"] + sorted(
            (r for r in current if r != "Gold"),
            key=lambda r: (RESOURCES.get(r, {}).get("tier", 9), r))
        for resource in order:
            amount = current.get(resource, 0)
            delta = self._resource_deltas.get(resource, 0)
            row = tk.Frame(self._resource_rows, bg=theme.PANEL)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=resource, bg=theme.PANEL, fg=theme.INK,
                     font=("Segoe UI", 9), anchor="w").pack(side="left")
            if delta:
                color = theme.GOOD if delta > 0 else theme.BAD
                sign = "+" if delta > 0 else "-"
                tk.Label(row, text=f"{sign}{_fmt_amount(abs(delta))}", bg=theme.PANEL,
                         fg=color, font=("Segoe UI", 9, "bold")).pack(side="right")
            tk.Label(row, text=_fmt_amount(amount), bg=theme.PANEL, fg=theme.MUTED,
                     font=("Segoe UI", 9)).pack(side="right", padx=(0, 6))

    # --- panel -------------------------------------------------------------
    def _build_panel(self):
        p = tk.Frame(self, bg=theme.PANEL, width=300)
        p.pack(side="right", fill="y")
        p.pack_propagate(False)
        self._panel = p

        self.title_lbl = tk.Label(p, text="Faction", bg=theme.PANEL, fg=theme.INK,
                                  font=theme.FONT_TITLE)
        self.title_lbl.pack(anchor="w", padx=14, pady=(14, 6))
        self.info = tk.Label(p, text="Click a faction to inspect it.",
                             bg=theme.PANEL, fg=theme.MUTED, font=theme.FONT,
                             justify="left", wraplength=270, anchor="w")
        self.info.pack(anchor="w", padx=14)

        # Prosperity meter — a settlement/village-only bar (see
        # _show_prosperity_bar/_hide_prosperity_bar), left unpacked here so
        # it's hidden by default for every other panel type.
        self.prosperity_frame = tk.Frame(p, bg=theme.PANEL)
        tk.Label(self.prosperity_frame, text="Prosperity", bg=theme.PANEL,
                 fg=theme.MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w")
        self._prosperity_canvas = tk.Canvas(self.prosperity_frame, height=14,
                                            bg=theme.PANEL, highlightthickness=0)
        self._prosperity_canvas.pack(fill="x", pady=(2, 2))
        self._prosperity_pct_lbl = tk.Label(self.prosperity_frame, text="",
                                            bg=theme.PANEL, fg=theme.MUTED,
                                            font=("Segoe UI", 8))
        self._prosperity_pct_lbl.pack(anchor="w")

        self.rel_header = tk.Label(p, text="RELATIONSHIPS", bg=theme.PANEL,
                                   fg=theme.MUTED, font=("Segoe UI", 8, "bold"))
        self.rel_header.pack(anchor="w", padx=14, pady=(16, 4))
        self.rel_frame = tk.Frame(p, bg=theme.PANEL)
        self.rel_frame.pack(fill="x", padx=14)

        self.actions = tk.Frame(p, bg=theme.PANEL)
        self.actions.pack(fill="x", padx=14, pady=16)

        self.view_btn = tk.Button(p, text="View: Political", command=self._toggle_mode,
                                  bg="#232a36", fg=theme.INK,
                                  activebackground=theme.ACCENT, relief="flat",
                                  font=theme.FONT)
        self.view_btn.pack(side="bottom", fill="x", padx=14, pady=(0, 14))
        tk.Button(p, text="End Turn", command=self._on_end_turn,
                  bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                  relief="flat", font=theme.FONT).pack(side="bottom", fill="x",
                                                       padx=14, pady=(4, 0))
        self.turn_lbl = tk.Label(p, text="", bg=theme.PANEL, fg=theme.MUTED,
                                 font=theme.FONT_BOLD)
        self.turn_lbl.pack(side="bottom", padx=14, pady=(8, 0))
        self.back_btn = tk.Button(p, text="← Back to World",
                                  command=self._exit_region_view, bg="#232a36",
                                  fg=theme.INK, activebackground=theme.ACCENT,
                                  relief="flat", font=theme.FONT)
        # back_btn is packed only while zoomed in.

    _MODES = ["political", "fertility", "elevation", "biome", "climate"]

    def _toggle_mode(self):
        self.mode = self._MODES[(self._MODES.index(self.mode) + 1) % len(self._MODES)]
        self.view_btn.config(text=f"View: {self.mode.capitalize()}")
        self._base_key = None
        self.render()

    def _update_turn_label(self):
        self.turn_lbl.config(text=f"Turn {self.world.turn} — {self.world.season}")

    def _on_end_turn(self):
        before = self._current_resource_snapshot()
        self.on_end_turn()
        after = self._current_resource_snapshot()
        self._resource_deltas = {r: after.get(r, 0) - before.get(r, 0)
                                  for r in set(before) | set(after)}
        self._report_trade_events()
        self._report_regional_trade_events()
        self.refresh()

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
            if etype == "regional_dispatched":
                msg = (f"{ev['origin_name']} ships {ev['quantity']} {ev['resource']} to "
                       f"{ev['dest_name']} for {ev['price']} Gold.")
            elif etype == "regional_delivered":
                msg = (f"{ev['dest_name']} receives {ev['quantity']} {ev['resource']} "
                       f"from {ev['origin_name']}.")
            elif etype == "regional_lost":
                msg = (f"A shipment of {ev['quantity']} {ev['resource']} from "
                       f"{ev['origin_name']} to {ev['dest_name']} was lost in transit!")
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
            seller = self.world.factions[ev["seller_idx"]]
            buyer = self.world.factions[ev["buyer_idx"]]
            is_seller = ev["seller_idx"] == player_idx
            is_buyer = ev["buyer_idx"] == player_idx
            if not (is_seller or is_buyer):
                continue

            etype = ev["type"]
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

    def _cell_revealed(self, x, y):
        """True if fog isn't currently gating the view, or this specific
        cell has been revealed — used for point features (settlements)
        where precise per-cell gating is more accurate than a per-nation
        check (see _is_known, used instead for identity info like labels)."""
        if not self._fog_is_active():
            return True
        wd = self.world
        return bool(wd.fog[y * wd.w + x])

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
        player = self._player_faction()
        own = self._is_player(nation)
        self.title_lbl.config(text="Your Realm" if own else "Foreign Realm")
        s = nation.stats
        n_regions = len(nation.meta.get("regions", []))
        if own or player is None:
            zoom_hint = "\nClick again to zoom in."
        elif self.world.world_map.get_relationship(player.id, nation.id)["stance"] == Stance.ENEMY:
            zoom_hint = "\nClick again to attack."
        else:
            zoom_hint = "\nClick again to inspect its regions."
        self.info.config(
            fg=theme.INK,
            text=f"{nation.name}\nSpecies: {nation.meta['species']} "
                 f"— {nation.meta['trait']}\n"
                 f"Military {s['military']} · Morale {s['morale']} · "
                 f"Gold {s.get('gold', 0):,}\n"
                 f"Avg fertility {nation.meta['fertility']}%\n"
                 f"Population {self._total_population(nation):,}\n"
                 f"{self._settle_counts(nation)}\n"
                 f"{n_regions} regions.{zoom_hint}\n\n"
                 f"RESOURCES\n{_format_resources(s.get('resources', {}))}")

        self.rel_header.config(text="RELATIONSHIPS")
        for w in self.rel_frame.winfo_children():
            w.destroy()
        rels = [r for r in self.world.world_map.relationships_of(nation.id)
                if self._is_known(r["other"])]
        if not rels:
            tk.Label(self.rel_frame, text="Isolated — no bordering factions.",
                     bg=theme.PANEL, fg=theme.MUTED, font=theme.FONT).pack(anchor="w")
        for rel in rels:
            row = tk.Frame(self.rel_frame, bg=theme.PANEL)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=rel["other"].name, bg=theme.PANEL, fg=theme.INK,
                     font=theme.FONT).pack(side="left")
            tag = rel["stance"] + (f" ({rel['tension']})" if rel["tension"] else "")
            tk.Label(row, text=tag, bg=theme.PANEL,
                     fg=theme.STANCE_COLOR.get(rel["stance"], theme.MUTED),
                     font=theme.FONT).pack(side="right")

        for w in self.actions.winfo_children():
            w.destroy()

        if player is None:
            # No player nation on this world (sandbox/legacy save) — keep the
            # old behavior of managing any faction directly.
            enemies = [r for r in rels if r["stance"] == Stance.ENEMY]
            if not enemies:
                tk.Label(self.actions, text="No enemies to fight.", bg=theme.PANEL,
                         fg=theme.MUTED, font=theme.FONT).pack(anchor="w")
            for r in enemies:
                other = r["other"]
                tk.Button(self.actions, text=f"Attack {other.name}",
                          command=lambda o=other, n=nation: self.on_attack(n, o),
                          bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                          relief="flat", font=theme.FONT).pack(fill="x", pady=2)
        elif own:
            tk.Label(self.actions, text="This is your realm. Select a rival "
                     "nation on the map to consider attacking it.",
                     bg=theme.PANEL, fg=theme.MUTED, font=theme.FONT,
                     justify="left", wraplength=260).pack(anchor="w")
        else:
            rel = self.world.world_map.get_relationship(player.id, nation.id)
            if rel["stance"] == Stance.ENEMY:
                player_idx = self.world.factions.index(player)
                target_idx = self.world.factions.index(nation)
                if bordering_regions(self.world, player_idx, target_idx):
                    tk.Button(self.actions, text=f"Attack {nation.name}",
                              command=lambda n=nation: self._begin_attack_setup(n),
                              bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                              relief="flat", font=theme.FONT).pack(fill="x", pady=2)
                elif naval_reachable_regions(self.world, player_idx, target_idx):
                    tk.Button(self.actions, text=f"Naval Attack on {nation.name}",
                              command=lambda n=nation: self._begin_attack_setup(n, naval=True),
                              bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                              relief="flat", font=theme.FONT).pack(fill="x", pady=2)
                else:
                    tk.Label(self.actions, text=f"No route to {nation.name} — you'd "
                             "need a shared border or a coastal port.",
                             bg=theme.PANEL, fg=theme.MUTED, font=theme.FONT,
                             justify="left", wraplength=260).pack(anchor="w")
            else:
                standing = rel.get("standing", 0)
                tk.Label(self.actions, text=f"You are {rel['stance']} with "
                         f"{nation.name}. Standing: {standing}",
                         bg=theme.PANEL, fg=theme.MUTED, font=theme.FONT,
                         justify="left", wraplength=260).pack(anchor="w", pady=(0, 6))

                can_act = diplomacy.can_act_this_turn(self.world, player, nation)
                tk.Button(self.actions, text="Improve Relations",
                          command=lambda n=nation: self._do_diplomacy(
                              diplomacy.improve_relations, n),
                          bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                          relief="flat", font=theme.FONT,
                          state="normal" if can_act else "disabled").pack(fill="x", pady=2)
                if not can_act:
                    tk.Label(self.actions, text="Already acted with them this turn.",
                             bg=theme.PANEL, fg=theme.MUTED,
                             font=("Segoe UI", 8)).pack(anchor="w")

                if standing <= diplomacy.WAR_THRESHOLD:
                    tk.Button(self.actions, text=f"Declare War on {nation.name}",
                              command=lambda n=nation: self._do_diplomacy(
                                  diplomacy.declare_war, n),
                              bg="#3a1f1f", fg=theme.BAD, activebackground=theme.ACCENT,
                              relief="flat", font=theme.FONT).pack(fill="x", pady=(8, 2))
                if standing >= diplomacy.ALLY_THRESHOLD and rel["stance"] != Stance.ALLY:
                    tk.Button(self.actions, text=f"Form Alliance with {nation.name}",
                              command=lambda n=nation: self._do_diplomacy(
                                  diplomacy.form_alliance, n),
                              bg="#1f3a24", fg=theme.GOOD, activebackground=theme.ACCENT,
                              relief="flat", font=theme.FONT).pack(fill="x", pady=(8, 2))

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
            tk.Label(self.actions, text="Trade route established.",
                     bg=theme.PANEL, fg=theme.GOOD, font=theme.FONT,
                     justify="left", wraplength=260).pack(anchor="w", pady=(8, 2))
            return

        project = next((p for p in wd.trade_route_projects
                        if frozenset((p.a_idx, p.b_idx)) == key), None)
        if project is not None:
            tk.Label(self.actions, text=f"Trade route under construction: "
                     f"{project.built_cells}/{project.total_cells} cells",
                     bg=theme.PANEL, fg=theme.MUTED, font=theme.FONT,
                     justify="left", wraplength=260).pack(anchor="w", pady=(8, 2))
            return

        if not trade.eligible_to_trade(wd, player_idx, target_idx):
            tk.Label(self.actions, text=f"Standing needs to reach "
                     f"{diplomacy.TRADE_STANDING_THRESHOLD} before you can "
                     "propose a trade route.",
                     bg=theme.PANEL, fg=theme.MUTED, font=theme.FONT,
                     justify="left", wraplength=260).pack(anchor="w", pady=(8, 2))
            return

        decline_until = getattr(wd, "trade_route_decline_until", {}).get(key, -1)
        if wd.turn < decline_until:
            tk.Label(self.actions, text=f"{nation.name} recently declined a trade "
                     "proposal — try again later.",
                     bg=theme.PANEL, fg=theme.BAD, font=theme.FONT,
                     justify="left", wraplength=260).pack(anchor="w", pady=(8, 2))
            return

        tk.Button(self.actions, text=f"Propose Trade Route with {nation.name}",
                  command=lambda: self._do_propose_trade_route(player_idx, target_idx),
                  bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                  relief="flat", font=theme.FONT).pack(fill="x", pady=(8, 2))

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
        if region.faction_idx < 0:
            self._show_wildland_region(region)
            return
        s = region.stats
        country = self.zoom_faction
        wd = self.world
        n_villages = len(getattr(region, "villages", []))
        total_cells = sum(region.biome_counts.values()) or 1
        biome_line = ", ".join(
            f"{biome.capitalize()} ({round(100 * count / total_cells)}%)"
            for biome, count in sorted(region.biome_counts.items(),
                                       key=lambda kv: -kv[1])) or "Unclassified"
        lines = [f"{region.name}", f"Region of {country.name}",
                 f"Area {s['area']} · Fertility {s['fertility']}%",
                 f"Biome: {biome_line}",
                 f"Climate: {region.dominant_climate.capitalize()}",
                 f"This turn's yield: {_format_resources(region.resources)}"]
        sts = [wd.settlements[i] for i in getattr(region, "meta_settlements", [])]
        if sts:
            lines.append("Settlements: " + ", ".join(
                f"{st.name} ({st.kind})" for st in sts))
        else:
            lines.append("No settlements.")

        is_foreign = self._zoom_is_foreign()
        if is_foreign:
            lines.append("Foreign territory — consider hostile action below.")
        else:
            lines.append(f"{n_villages} villages — click again to zoom in.")
        self.info.config(fg=theme.INK, text="\n".join(lines))

        for w in self.actions.winfo_children():
            w.destroy()
        if is_foreign:
            player = self._player_faction()
            can_act = diplomacy.can_act_this_turn(self.world, player, country)
            for label, fn in (("Fabricate Claim on Region", diplomacy.fabricate_claim),
                              ("Terrorize Locals", diplomacy.terrorize_locals)):
                tk.Button(self.actions, text=label,
                          command=lambda f=fn: self._do_diplomacy(f, country, region),
                          bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                          relief="flat", font=theme.FONT,
                          state="normal" if can_act else "disabled").pack(fill="x", pady=2)
            if not can_act:
                tk.Label(self.actions, text="Already acted against them this turn.",
                         bg=theme.PANEL, fg=theme.MUTED,
                         font=("Segoe UI", 8)).pack(anchor="w")
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
                tk.Label(self.actions, text=f"{project.kind.capitalize()} under "
                         f"construction: {elapsed}/{project.total_turns} turns{note}",
                         bg=theme.PANEL, fg=theme.MUTED, font=theme.FONT,
                         justify="left", wraplength=260).pack(anchor="w", pady=(0, 6))
            building_kinds = {p.kind for p in projects_here}
            for kind in ("city", "town", "castle"):
                if kind in building_kinds:
                    continue
                cost = construction.SETTLEMENT_BUILD_COST[kind]
                turns = construction.SETTLEMENT_BUILD_TURNS[kind]
                afford = construction.can_afford(player, cost, self.world)
                tk.Label(self.actions,
                         text=f"{kind.capitalize()} — Cost: {_format_resources(cost)}\n"
                              f"Build time: {turns} turns",
                         bg=theme.PANEL, fg=theme.INK if afford else theme.BAD, font=theme.FONT,
                         justify="left", wraplength=260).pack(anchor="w", pady=(4, 2))
                tk.Button(self.actions, text=f"Build {kind.capitalize()}...",
                          command=lambda r=region, k=kind: self._begin_settlement_placement(r, k),
                          bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                          relief="flat", font=theme.FONT).pack(fill="x", pady=(0, 8))

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
        lines = [f"{region.name}", "Unclaimed wildland",
                 f"Area {region.stats['area']} · Fertility {region.stats['fertility']}%",
                 f"Biome: {biome_line}",
                 f"Wildland garrison strength: {region.wildland_strength}"]
        if player is not None:
            odds = expansion.claim_odds(player, region)
            lines.append(f"Estimated success odds: {round(100 * odds)}%")
        self.info.config(fg=theme.INK, text="\n".join(lines))

        for w in self.actions.winfo_children():
            w.destroy()
        if player is None:
            return
        faction_idx = wd.factions.index(player)
        if region not in expansion.claimable_frontier(wd, faction_idx):
            tk.Label(self.actions, text="Not adjacent to your territory yet.",
                     bg=theme.PANEL, fg=theme.MUTED, font=theme.FONT,
                     justify="left", wraplength=260).pack(anchor="w")
            return
        if wd.turn < region.claim_cooldown_until_turn:
            tk.Label(self.actions, text="The locals are still wary after "
                     "repelling your last attempt — try again later.",
                     bg=theme.PANEL, fg=theme.BAD, font=theme.FONT,
                     justify="left", wraplength=260).pack(anchor="w")
            return
        project = next((p for p in wd.claim_projects if p.region_id == region.id), None)
        if project is not None:
            if project.complete:
                tk.Label(self.actions, text="The expansion crew has arrived "
                         "— fight the wildland garrison to claim this land.",
                         bg=theme.PANEL, fg=theme.INK, font=theme.FONT,
                         justify="left", wraplength=260).pack(anchor="w", pady=(0, 6))
                tk.Button(self.actions, text="Fight for the Territory",
                          command=lambda p=project: self._do_wildland_battle(p),
                          bg="#3a1f1f", fg=theme.BAD, activebackground=theme.ACCENT,
                          relief="flat", font=theme.FONT).pack(fill="x", pady=2)
            else:
                elapsed = project.total_turns - project.turns_left
                tk.Label(self.actions, text=f"Expansion under way: "
                         f"{elapsed}/{project.total_turns} turns",
                         bg=theme.PANEL, fg=theme.MUTED, font=theme.FONT,
                         justify="left", wraplength=260).pack(anchor="w", pady=(0, 6))
            return
        cost = expansion.claim_cost(region)
        afford = construction.can_afford(player, cost, self.world)
        tk.Label(self.actions, text=f"Cost: {_format_resources(cost)}\n"
                 f"Build time: {expansion.claim_turns(region)} turns",
                 bg=theme.PANEL, fg=theme.INK if afford else theme.BAD, font=theme.FONT,
                 justify="left", wraplength=260).pack(anchor="w", pady=(0, 6))
        tk.Button(self.actions, text="Claim Territory",
                  command=lambda cnty=region: self._do_claim(cnty),
                  bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                  relief="flat", font=theme.FONT).pack(fill="x", pady=2)

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
        self.prosperity_frame.pack_forget()

    def _show_prosperity_bar(self, value):
        """Pack the meter in right under `info` (before rel_header, so it
        lands there regardless of pack/forget history) and draw its current
        fill — see resources._update_prosperity for how `value` (0..100)
        actually moves over time."""
        self.prosperity_frame.pack(anchor="w", padx=14, pady=(8, 0), fill="x",
                                   before=self.rel_header)
        self._draw_prosperity_bar(value)

    def _draw_prosperity_bar(self, value):
        c = self._prosperity_canvas
        c.update_idletasks()
        w = c.winfo_width()
        if w <= 1:
            w = 270   # not yet laid out on the very first draw
        h = 14
        frac = max(0.0, min(1.0, value / 100.0))
        if frac < 0.34:
            color = theme.BAD
        elif frac < 0.67:
            color = theme.WARN
        else:
            color = theme.GOOD
        c.delete("all")
        c.create_rectangle(0, 0, w, h, fill="#11151b", outline="")
        if frac > 0:
            c.create_rectangle(0, 0, w * frac, h, fill=color, outline="")
        self._prosperity_pct_lbl.config(text=f"{value:.0f} / 100")

    def _show_settlement(self, st):
        wd = self.world
        self.selected_village = None   # a settlement and a village are never both selected
        if self.zoom_region is not None:
            self.title_lbl.config(text=st.kind.capitalize())
        region = (wd.regions[st.region_id].name
                  if 0 <= st.region_id < len(wd.regions) else "?")
        needs = resources.settlement_needs(st, wd.season)
        lines = [st.name, f"{st.kind.capitalize()} in {region}, "
                 f"{wd.factions[st.faction_idx].name}",
                 f"Needs: {_format_resources(needs)} per turn"]
        population = getattr(st, "population", None)
        if population is not None:
            lines.append(f"Population: {population:,} "
                         f"({st.adults:,} adults, {st.children:,} children)")
        stored = sum(getattr(st, "resources", {}).values())
        capacity = resources.settlement_storage_capacity(st)
        lines.append(f"Storage: {stored:,} / {capacity:,}"
                     + (" — overflowing, spoiling faster" if stored > capacity else ""))
        if getattr(st, "has_shipyard", False):
            lines.append("Has a Shipyard — commanders here launch free, fast ships.")
        if getattr(st, "has_granary", False):
            lines.append("Has a Granary — more storage space.")
        if getattr(st, "has_warehouse", False):
            lines.append("Has a Warehouse — more storage space.")
        self.info.config(fg=theme.INK, text="\n".join(lines))

        prosperity = getattr(st, "prosperity", None)
        if prosperity is not None:
            self._show_prosperity_bar(prosperity)
        else:
            self._hide_prosperity_bar()

        for w in self.actions.winfo_children():
            w.destroy()
        player = self._player_faction()
        if player is None or st.faction_idx != wd.factions.index(player):
            return
        project = next((p for p in wd.shipyard_projects if p.settlement_id == st.id), None)
        if project is not None:
            elapsed = project.total_turns - project.turns_left
            tk.Label(self.actions, text=f"Shipyard under construction: "
                     f"{elapsed}/{project.total_turns} turns",
                     bg=theme.PANEL, fg=theme.MUTED, font=theme.FONT,
                     justify="left", wraplength=260).pack(anchor="w", pady=(0, 6))
        elif construction.can_build_shipyard(wd, st):
            afford = construction.can_afford(player, construction.SHIPYARD_COST, wd)
            tk.Label(self.actions,
                     text=f"Cost: {_format_resources(construction.SHIPYARD_COST)}\n"
                          f"Build time: {construction.SHIPYARD_BUILD_TURNS} turns",
                     bg=theme.PANEL, fg=theme.INK if afford else theme.BAD, font=theme.FONT,
                     justify="left", wraplength=260).pack(anchor="w", pady=(0, 6))
            tk.Button(self.actions, text="Build Shipyard",
                      command=lambda s=st: self._do_build_shipyard(s),
                      bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                      relief="flat", font=theme.FONT).pack(fill="x", pady=2)

        granary_project = next((p for p in wd.granary_projects if p.settlement_id == st.id), None)
        if granary_project is not None:
            elapsed = granary_project.total_turns - granary_project.turns_left
            tk.Label(self.actions, text=f"Granary under construction: "
                     f"{elapsed}/{granary_project.total_turns} turns",
                     bg=theme.PANEL, fg=theme.MUTED, font=theme.FONT,
                     justify="left", wraplength=260).pack(anchor="w", pady=(0, 6))
        elif construction.can_build_granary(wd, st):
            afford = construction.can_afford(player, construction.GRANARY_COST, wd)
            tk.Label(self.actions,
                     text=f"Cost: {_format_resources(construction.GRANARY_COST)}\n"
                          f"Build time: {construction.GRANARY_BUILD_TURNS} turns\n"
                          f"+{resources.GRANARY_STORAGE_BONUS:,} storage space",
                     bg=theme.PANEL, fg=theme.INK if afford else theme.BAD, font=theme.FONT,
                     justify="left", wraplength=260).pack(anchor="w", pady=(0, 6))
            tk.Button(self.actions, text="Build Granary",
                      command=lambda s=st: self._do_build_granary(s),
                      bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                      relief="flat", font=theme.FONT).pack(fill="x", pady=2)

        warehouse_project = next((p for p in wd.warehouse_projects if p.settlement_id == st.id), None)
        if warehouse_project is not None:
            elapsed = warehouse_project.total_turns - warehouse_project.turns_left
            tk.Label(self.actions, text=f"Warehouse under construction: "
                     f"{elapsed}/{warehouse_project.total_turns} turns",
                     bg=theme.PANEL, fg=theme.MUTED, font=theme.FONT,
                     justify="left", wraplength=260).pack(anchor="w", pady=(0, 6))
        elif construction.can_build_warehouse(wd, st):
            afford = construction.can_afford(player, construction.WAREHOUSE_COST, wd)
            tk.Label(self.actions,
                     text=f"Cost: {_format_resources(construction.WAREHOUSE_COST)}\n"
                          f"Build time: {construction.WAREHOUSE_BUILD_TURNS} turns\n"
                          f"+{resources.WAREHOUSE_STORAGE_BONUS:,} storage space",
                     bg=theme.PANEL, fg=theme.INK if afford else theme.BAD, font=theme.FONT,
                     justify="left", wraplength=260).pack(anchor="w", pady=(0, 6))
            tk.Button(self.actions, text="Build Warehouse",
                      command=lambda s=st: self._do_build_warehouse(s),
                      bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                      relief="flat", font=theme.FONT).pack(fill="x", pady=2)

    def _do_build_shipyard(self, st):
        player = self._player_faction()
        msg = construction.start_shipyard(self.world, player, st)
        self.show_bottom_message(msg)
        if self.selected_settlement is st:
            self._show_settlement(st)
        self.render()

    def _do_build_granary(self, st):
        player = self._player_faction()
        msg = construction.start_granary(self.world, player, st)
        self.show_bottom_message(msg)
        if self.selected_settlement is st:
            self._show_settlement(st)
        self.render()

    def _do_build_warehouse(self, st):
        player = self._player_faction()
        msg = construction.start_warehouse(self.world, player, st)
        self.show_bottom_message(msg)
        if self.selected_settlement is st:
            self._show_settlement(st)
        self.render()

    def _show_village(self, v):
        wd = self.world
        self.selected_settlement = None   # a village and a settlement are never both selected
        self.title_lbl.config(text="Village")
        region = wd.regions[v.region_id]
        lines = [v.name, f"Village in {region.name}, "
                 f"{wd.factions[v.faction_idx].name}",
                 f"Farm output: {v.farm_output} — a prosperity input for this "
                 f"village, scaled by local land fertility."]
        population = getattr(v, "population", None)
        if population is not None:
            lines.append(f"Population: {population:,} "
                         f"({v.adults:,} adults, {v.children:,} children)")
        needs = resources.settlement_needs(v, wd.season)
        lines.append(f"Needs: {_format_resources(needs)} per turn")
        stored = sum(getattr(v, "resources", {}).values())
        capacity = resources._node_storage_capacity(v)
        lines.append(f"Storage: {stored:,} / {capacity:,}"
                     + (" — overflowing, spoiling faster" if stored > capacity else ""))
        self.info.config(fg=theme.INK, text="\n".join(lines))

        prosperity = getattr(v, "prosperity", None)
        if prosperity is not None:
            self._show_prosperity_bar(prosperity)
        else:
            self._hide_prosperity_bar()

    def _show_commander(self, cmd):
        """Panel for a selected Commander: position, current order, and
        Move/Board/Dismantle/Build Ship actions (which of these apply
        depends on whether the commander is aboard a ship, standing on a
        beached one, or on foot with none nearby). A pure scout for now —
        no combat, so there's nothing here about strength or risk."""
        self._hide_prosperity_bar()
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
            lines.append(f"Building ship: {cmd.ship_turns_left} turns left")
        elif cmd.path is not None:
            remaining = len(cmd.path) - 1 - cmd.path_index
            lines.append(f"Moving — {remaining} cells left")
        else:
            lines.append("Idle")
        self.info.config(fg=theme.INK, text="\n".join(lines))

        for w in self.actions.winfo_children():
            w.destroy()
        if cmd.ship_turns_left is None:
            tk.Button(self.actions, text="Move",
                      command=lambda: self._begin_commander_move(cmd),
                      bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                      relief="flat", font=theme.FONT).pack(fill="x", pady=2)
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
                    tk.Label(self.actions, text=cost_text,
                             bg=theme.PANEL, fg=theme.INK if afford else theme.BAD,
                             font=theme.FONT, justify="left",
                             wraplength=260).pack(anchor="w", pady=(0, 4))
                tk.Button(self.actions, text=label,
                          command=lambda: self._do_build_ship(cmd),
                          bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                          relief="flat", font=theme.FONT).pack(fill="x", pady=2)
            if beached is not None:
                tk.Button(self.actions, text="Board Ship",
                          command=lambda: self._do_board_ship(cmd),
                          bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                          relief="flat", font=theme.FONT).pack(fill="x", pady=2)
                tk.Button(self.actions, text="Dismantle Ship",
                          command=lambda: self._do_dismantle_ship(cmd),
                          bg="#232a36", fg=theme.BAD, activebackground=theme.ACCENT,
                          relief="flat", font=theme.FONT).pack(fill="x", pady=2)

    def _begin_commander_move(self, cmd):
        self.commander_move_mode = cmd
        self.info.config(fg=theme.MUTED,
                         text="Click a spot on the map to send the "
                              "commander there.")
        for w in self.actions.winfo_children():
            w.destroy()
        tk.Button(self.actions, text="Cancel",
                  command=lambda: self._cancel_commander_move(cmd),
                  bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                  relief="flat", font=theme.FONT).pack(fill="x", pady=2)

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
        self.rel_header.config(text=section_label)
        for w in self.rel_frame.winfo_children():
            w.destroy()
        for w in self.actions.winfo_children():
            w.destroy()
        self.back_btn.config(text=back_label, command=back_command)
        self.back_btn.pack(side="bottom", fill="x", padx=14, pady=(0, 2))

    def _exit_ui(self):
        self.back_btn.pack_forget()

    def _enter_region_view(self, faction):
        self.zoom_faction = faction
        self.zoom_region = None
        self.selected_region = None
        self.selected_village = None
        self._base_key = None
        self.title_lbl.config(text="Regions")
        self.info.config(fg=theme.MUTED,
                         text=f"{faction.name}\nClick a region to inspect it.")
        self._enter_ui("REGION", "← Back to World", self._exit_region_view)
        self._start_zoom(self._padded_rect(faction.meta["bbox"]))

    def _exit_region_view(self):
        self.zoom_faction = None
        self.zoom_region = None
        self.selected_region = None
        self.selected_village = None
        self._base_key = None
        self._exit_ui()
        if self.selected:
            self._show_faction(self.selected)
        self._start_zoom(self._world_view_rect())

    def _enter_village_view(self, region):
        """Zooms to the whole faction's territory (not just `region`'s bbox)
        since village view shows every village the faction owns, across all
        its regions — `region` is kept only so "Back to Region" returns to
        the region you actually clicked through."""
        self.zoom_region = region
        self.selected_village = None
        self._base_key = None
        self.title_lbl.config(text="Villages")
        self.info.config(fg=theme.MUTED,
                         text=f"{self.zoom_faction.name}\nClick a village to inspect it.")
        self._enter_ui("VILLAGE", "← Back to Region", self._exit_village_view)
        self._start_zoom(self._padded_rect(self.zoom_faction.meta["bbox"]))

    def _exit_village_view(self):
        self.zoom_region = None
        self.selected_village = None
        self._base_key = None
        self.title_lbl.config(text="Regions")
        self._enter_ui("REGION", "← Back to World", self._exit_region_view)
        if self.selected_region:
            self._show_region(self.selected_region)
        self._start_zoom(self._padded_rect(self.zoom_faction.meta["bbox"]))

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
            self.info.config(fg=theme.MUTED,
                             text=f"{enemy.name}\nNo shared border or coastal "
                                  "port to attack across right now.")
            return

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
            self.info.config(fg=theme.MUTED,
                             text=f"Launching a naval invasion of {enemy.name}.\n"
                                  "Click a highlighted region along the coast "
                                  "to attack it.")
        else:
            self.info.config(fg=theme.MUTED,
                             text=f"Attacking {enemy.name}.\nClick a highlighted "
                                  "region along the border to attack it.")
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
        self.attack_mode = None
        self._attack_enemy = None
        self._attack_frontier = []
        self._exit_ui()
        self._base_key = None
        if self.selected:
            self._show_faction(self.selected)
        # Camera is deliberately left zoomed on the border so, on return from
        # battle, flash_region() can highlight the (possibly newly-won)
        # region right where the player is already looking.
        self.on_attack(player, enemy, region)

    # --- settlement placement -------------------------------------------------
    def _begin_settlement_placement(self, region, kind):
        self.building_mode = (region, kind)
        cost = construction.SETTLEMENT_BUILD_COST[kind]
        turns = construction.SETTLEMENT_BUILD_TURNS[kind]
        self.info.config(fg=theme.MUTED,
                         text=f"{region.name}\nClick a spot in this region to "
                              f"begin building a {kind} there.\n\n"
                              f"Cost: {_format_resources(cost)}\n"
                              f"Build time: {turns} turns")
        for w in self.actions.winfo_children():
            w.destroy()
        tk.Button(self.actions, text="Cancel", command=self._cancel_settlement_placement,
                  bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                  relief="flat", font=theme.FONT).pack(fill="x", pady=2)
        self.render()

    def _cancel_settlement_placement(self):
        self.building_mode = None
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
        self.render()

    def _on_release(self, event):
        was_drag = self._dragged
        self._press_xy = None
        self._dragged = False
        if not was_drag:
            self._on_click(event)

    def _on_wheel(self, event):
        self._cancel_animation()
        vx0, vy0, scale = self._place
        wx, wy = vx0 + event.x / scale, vy0 + event.y / scale
        factor = _ZOOM_STEP if event.delta > 0 else 1.0 / _ZOOM_STEP

        x0, y0, x1, y1 = self.view
        w = (x1 - x0) * factor
        h = (y1 - y0) * factor
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
        if self._animating:
            return
        vx0, vy0, scale = self._place
        gx = int(vx0 + event.x / scale)
        gy = int(vy0 + event.y / scale)
        wd = self.world
        if not (0 <= gx < wd.w and 0 <= gy < wd.h):
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
            msg = commander.set_move_order(wd, cmd, (gx, gy))
            self.show_bottom_message(msg)
            if self.selected_commander is cmd:
                self._show_commander(cmd)
            self.render()
            return

        # --- COMMANDER SELECTION: click-radius test against every one of
        # the player's own commanders, checked before normal region/faction
        # selection so a commander is selectable identically at any zoom
        # level rather than duplicating this in all three click branches.
        player = self._player_faction()
        if player is not None:
            player_idx = wd.factions.index(player)
            for cmd in wd.commanders:
                if cmd.faction_idx != player_idx:
                    continue
                csx = (cmd.pos[0] + 0.5 - vx0) * scale
                csy = (cmd.pos[1] + 0.5 - vy0) * scale
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

        elif self.zoom_region is None:
            # --- LEVEL 1: region view (zoomed into a country) -------------
            zf = wd.factions.index(self.zoom_faction)
            # settlement markers take priority over region selection
            for sid in self.zoom_faction.meta.get("settlements", []):
                st = wd.settlements[sid]
                sx = (st.pos[0] + 0.5 - vx0) * scale
                sy = (st.pos[1] + 0.5 - vy0) * scale
                if (sx - event.x) ** 2 + (sy - event.y) ** 2 <= 10 ** 2:
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
            # Foreign browsing stops at the region level (diplomacy actions
            # only) — no drilling into a foreign nation's villages.
            if not self._zoom_is_foreign() and region is self.selected_region:
                self._enter_village_view(region)  # 2nd click -> village view
            else:                                 # 1st click -> select region
                self.selected_region = region
                self._base_key = None
                self._show_region(region)
                self.render()

        else:
            # --- LEVEL 2: village view (zoomed to the whole faction) ------
            zf = wd.factions.index(self.zoom_faction)
            for v in wd.villages:
                if v.faction_idx != zf:
                    continue
                sx = (v.pos[0] + 0.5 - vx0) * scale
                sy = (v.pos[1] + 0.5 - vy0) * scale
                if (sx - event.x) ** 2 + (sy - event.y) ** 2 <= 8 ** 2:
                    self.selected_village = v
                    self._show_village(v)
                    self.render()
                    return
            for sid in self.zoom_faction.meta.get("settlements", []):
                st = wd.settlements[sid]
                sx = (st.pos[0] + 0.5 - vx0) * scale
                sy = (st.pos[1] + 0.5 - vy0) * scale
                if (sx - event.x) ** 2 + (sy - event.y) ** 2 <= 10 ** 2:
                    self.selected_settlement = st
                    self._show_settlement(st)
                    self.render()
                    return
            cid = wd.region_grid[gy][gx]
            if cid < 0 or wd.regions[cid].faction_idx != zf:
                self._exit_village_view()         # clicked away -> zoom out
            # else: clicked empty land still within the faction's own
            # territory (any region) — no-op, stay in village view

    def _on_right_click(self, event):
        """QoL: right-click sends the currently-selected Commander toward
        that spot directly, at any zoom level — a faster alternative to the
        Move button + left-click flow, not a replacement for it."""
        if self._animating or self.selected_commander is None:
            return
        vx0, vy0, scale = self._place
        gx = int(vx0 + event.x / scale)
        gy = int(vy0 + event.y / scale)
        wd = self.world
        if not (0 <= gx < wd.w and 0 <= gy < wd.h):
            return
        cmd = self.selected_commander
        self.commander_move_mode = None   # in case Move was separately armed
        msg = commander.set_move_order(wd, cmd, (gx, gy))
        self.show_bottom_message(msg)
        self._show_commander(cmd)
        self.render()

    # --- rendering ---------------------------------------------------------
    def _ensure_base(self):
        """Rebuild the full-grid PIL image only when what it depicts changes."""
        wd = self.world
        if self.zoom_faction is not None:
            sc = self.selected_region.id if self.selected_region else -1
            key = ("region", sc)
        elif self.mode != "political":
            key = (self.mode,)
        else:
            key = ("political", id(self.selected))
        if key == self._base_key and self._base_img is not None:
            return

        if self.zoom_faction is not None:
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

    def render(self):
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

        # crop the visible grid region and scale it to the canvas (nearest)
        bx0, by0 = max(0, int(math.floor(vx0))), max(0, int(math.floor(vy0)))
        bx1, by1 = min(wd.w, int(math.ceil(vx1))), min(wd.h, int(math.ceil(vy1)))
        if bx1 > bx0 and by1 > by0:
            crop = self._base_img.crop((bx0, by0, bx1, by1))
            if fog_active:
                fog_crop = self._fog_overlay_img.crop((bx0, by0, bx1, by1))
                if fog_crop.getbbox() is not None:   # skip if fully revealed here
                    dark = Image.new("RGB", crop.size, _FOG_HIDDEN_RGB)
                    crop = Image.composite(dark, crop, fog_crop)
            tw = max(1, round((bx1 - bx0) * scale))
            th = max(1, round((by1 - by0) * scale))
            self._img = ImageTk.PhotoImage(crop.resize((tw, th), Image.NEAREST))
            c.create_image((bx0 - vx0) * scale, (by0 - vy0) * scale,
                           anchor="nw", image=self._img)

        def screen(gx, gy):
            return ((gx - vx0) * scale, (gy - vy0) * scale)

        # Rivers are baked into the terrain raster itself (_precompute_colors,
        # same as lake_cells) rather than drawn here as a separate vector
        # overlay — see that method for why. No per-frame river drawing
        # needed at all.

        # Relationship links (world view, selected faction only).
        if self.zoom_faction is None and self.selected:
            ax, ay = screen(self.selected.center[0] * wd.w,
                            self.selected.center[1] * wd.h)
            for rel in wd.world_map.relationships_of(self.selected.id):
                if not self._is_known(rel["other"]):
                    continue
                bx, by = screen(rel["other"].center[0] * wd.w,
                                rel["other"].center[1] * wd.h)
                width = 1 if rel["stance"] == Stance.NEUTRAL else 2
                c.create_line(ax, ay, bx, by,
                              fill=theme.STANCE_COLOR.get(rel["stance"], theme.MUTED),
                              width=width)

        self._draw_trade_routes(c, screen)
        self._draw_trade_route_construction(c, screen)
        self._draw_trade_caravans(c, screen)
        self._draw_roads(c, screen)
        self._draw_terrain_symbols(c, screen, bx0, by0, bx1, by1)
        self._draw_construction(c, screen)
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
        how much world is visible (world view vs. zoomed into one region)."""
        if self.mode != "political":
            return
        wd = self.world
        scale = self._place[2]
        spacing = max(_TERRAIN_SYMBOL_MIN_WORLD_SPACING,
                     round(_TERRAIN_SYMBOL_SCREEN_SPACING / max(scale, 0.01)))
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
            x, y = screen(ship.pos[0] + 0.5, ship.pos[1] + 0.5)
            c.create_polygon(x - r, y + r * 0.4, x + r, y + r * 0.4,
                             x + r * 0.6, y - r * 0.5, x - r * 0.6, y - r * 0.5,
                             fill=style["fill"], outline=style["outline"], width=1.5)

    def _draw_commanders(self, c, screen):
        """Commander(s) (app/world/commander.py) — a distinct diamond
        marker, shown at every zoom level since it's a single mobile unit
        rather than something tied to one region, plus a thin dashed
        preview of its queued path (if any) so a move order is visible at a
        glance."""
        wd = self.world
        style = _COMMANDER_STYLE
        r = style["r"]
        for cmd in wd.commanders:
            if cmd.path is not None:
                remaining_path = cmd.path[cmd.path_index:]
                if len(remaining_path) >= 2:
                    pts = []
                    for gx, gy in remaining_path:
                        pts.extend(screen(gx + 0.5, gy + 0.5))
                    c.create_line(*pts, fill=style["fill"], width=1.5,
                                  dash=(3, 3), capstyle="round", smooth=True)

            x, y = screen(cmd.pos[0] + 0.5, cmd.pos[1] + 0.5)
            if cmd is self.selected_commander:
                c.create_oval(x - r - 3, y - r - 3, x + r + 3, y + r + 3,
                              outline="#ffffff", width=2)
            c.create_polygon(x, y - r, x + r, y, x, y + r, x - r, y,
                             fill=style["fill"], outline=style["outline"], width=1.5)

    def _draw_settlements(self, c, screen):
        """Markers: city = circle, castle = triangle, town = square. The world
        view shows only cities (to avoid clutter); the region view shows every
        settlement of the zoomed faction, with names."""
        wd = self.world
        if self.zoom_faction is not None:
            sids = [sid for sid in self.zoom_faction.meta.get("settlements", [])
                    if self._cell_revealed(*wd.settlements[sid].pos)]
            show_names = True
        else:
            sids = [s.id for s in wd.settlements if s.kind == "city"
                    and self._cell_revealed(*s.pos)]
            show_names = False

        for sid in sids:
            st = wd.settlements[sid]
            style = _SETTLE_STYLE[st.kind]
            x, y = screen(st.pos[0] + 0.5, st.pos[1] + 0.5)
            r = style["r"]
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

    def _draw_trade_routes(self, c, screen):
        """Long-haul trade routes: land roads (solid gold, terrain-following)
        and sea lanes (dotted pale-blue), shown at every zoom level since they
        span the whole world rather than one region."""
        width = max(1.0, self._place[2] * 0.22)
        for r in self.world.trade_routes:
            cells = r["cells"]
            if len(cells) < 2:
                continue
            pts = []
            for gx, gy in cells:
                pts.extend(screen(gx + 0.5, gy + 0.5))
            if r["kind"] == "sea":
                c.create_line(*pts, fill=_TRADE_SEA_COLOR, width=max(1.0, width * 0.7),
                              capstyle="round", joinstyle="round", dash=(1, 4),
                              smooth=True)
            else:
                c.create_line(*pts, fill=_TRADE_LAND_COLOR, width=width,
                              capstyle="round", joinstyle="round", dash=(7, 4),
                              smooth=True)

    def _draw_trade_caravans(self, c, screen):
        """Moving markers for active trade caravans (land) and ships (sea) —
        a glowing marker at the caravan's current interpolated position,
        with the *entire route it's currently on* redrawn in a bright color
        on top of the dim static line, so an active trade route is obvious
        at a glance and not just its small marker. No animation between
        turns; position only changes when render() runs again after End Turn."""
        width = max(1.0, self._place[2] * 0.22)

        # Highlight every route a caravan is currently traveling, before
        # drawing any markers on top of them.
        for caravan in self.world.trade_caravans:
            pts = []
            for gx, gy in caravan.path:
                pts.extend(screen(gx + 0.5, gy + 0.5))
            if len(pts) < 4:
                continue
            if caravan.kind == "sea":
                c.create_line(*pts, fill=_ACTIVE_ROUTE_SEA_COLOR,
                              width=max(1.0, width * 0.85), capstyle="round",
                              joinstyle="round", dash=(2, 3), smooth=True)
            else:
                c.create_line(*pts, fill=_ACTIVE_ROUTE_LAND_COLOR,
                              width=width * 1.3, capstyle="round",
                              joinstyle="round", dash=(9, 3), smooth=True)

        for caravan in self.world.trade_caravans:
            x, y = screen(*[v + 0.5 for v in caravan.pos])
            style = _SEA_CARAVAN_STYLE if caravan.kind == "sea" else _CARAVAN_STYLE
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
        TradeRouteProject.built_segments)."""
        wd = self.world
        width = max(1.0, self._place[2] * 0.18)
        for proj in wd.trade_route_projects:
            for seg in proj.built_segments:
                if len(seg) < 2:
                    continue
                pts = []
                for gx, gy in seg:
                    pts.extend(screen(gx + 0.5, gy + 0.5))
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
            c.create_line(*pts, fill=_DIRT_ROAD_COLOR, width=width, capstyle="round",
                          dash=(4, 3), smooth=True)

        for project in wd.settlement_projects:
            x, y = screen(project.pos[0] + 0.5, project.pos[1] + 0.5)
            r = 4
            c.create_rectangle(x - r, y - r, x + r, y + r, outline="#f2e9c9",
                               width=2, dash=(2, 2))
            label = f"{project.kind[0].upper()}·{project.turns_left}t"
            c.create_text(x + 1, y + r + 8, text=label,
                         fill="#000000", font=("Segoe UI", 7))
            c.create_text(x, y + r + 7, text=label,
                         fill="#f2e9c9", font=("Segoe UI", 7))

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

    def _draw_road_segment(self, c, screen, ax, ay, bx, by, color, width, dash=None, bridge=False):
        """One road segment. Stone roads (bridge=True) that cross a river
        get the crossing stretch recolored brown (_BRIDGE_COLOR) — see
        _river_span — so it visually reads as a bridge instead of the road
        just barging through the water."""
        x0, y0 = screen(ax + 0.5, ay + 0.5)
        x1, y1 = screen(bx + 0.5, by + 0.5)
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
        _draw_road_segment) — dirt tracks don't bother with one."""
        wd = self.world
        width = max(1.0, self._place[2] * 0.18)

        if self.zoom_faction is None:
            for region in wd.regions:
                if region.faction_idx < 0:
                    continue
                for (ax, ay), (bx, by), tier in wd.roads_by_region.get(region.id, []):
                    if tier != "stone":
                        continue
                    if not (self._cell_revealed(ax, ay) or self._cell_revealed(bx, by)):
                        continue
                    self._draw_road_segment(c, screen, ax, ay, bx, by,
                                            _STONE_ROAD_COLOR, width, bridge=True)
            return

        for cid in self.zoom_faction.meta.get("regions", []):
            for (ax, ay), (bx, by), tier in wd.roads_by_region.get(cid, []):
                if not (self._cell_revealed(ax, ay) or self._cell_revealed(bx, by)):
                    continue
                is_stone = tier == "stone"
                color = _STONE_ROAD_COLOR if is_stone else _DIRT_ROAD_COLOR
                dash = None if is_stone else (4, 3)
                self._draw_road_segment(c, screen, ax, ay, bx, by, color, width,
                                        dash=dash, bridge=is_stone)

    def _draw_villages(self, c, screen):
        """Small dots for villages — only shown in village view, which now
        covers every village the zoomed faction owns (not just the region
        last clicked through — see _enter_village_view). Names are skipped
        past a village-count threshold to avoid label soup."""
        if self.zoom_region is None:
            return
        wd = self.world
        style = _VILLAGE_STYLE
        r = style["r"]
        zf = wd.factions.index(self.zoom_faction)
        villages = [v for v in wd.villages if v.faction_idx == zf]
        show_names = len(villages) <= _VILLAGE_LABEL_LIMIT
        for v in villages:
            x, y = screen(v.pos[0] + 0.5, v.pos[1] + 0.5)
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

    def _draw_labels(self, c, screen):
        wd = self.world
        if self.zoom_region is not None:
            return   # village view: region/faction name labels aren't useful here
        if self.zoom_faction is not None:
            items = []
            for cid in self.zoom_faction.meta.get("regions", []):
                region = wd.regions[cid]
                cx, cy = int(region.center[0] * wd.w), int(region.center[1] * wd.h)
                if self._cell_revealed(cx, cy):
                    items.append((region.name, region.center))
        else:
            items = [(f.name, f.center) for f in wd.factions if self._is_known(f)]
        for name, center in items:
            lx, ly = screen(center[0] * wd.w, center[1] * wd.h)
            c.create_text(lx + 1, ly + 1, text=name, fill="#000000", font=_LABEL_FONT)
            c.create_text(lx, ly, text=name, fill="#ffffff", font=_LABEL_FONT)

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
            c.create_line(sx0, sy0, sx1, sy1, fill=color, width=width,
                          capstyle="round")
