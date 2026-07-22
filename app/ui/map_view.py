"""Macro world-map screen.

Renders the procedurally generated world as a raster (a Pillow image cropped to
a viewport and scaled with nearest-neighbor, so borders stay crisp). Three
zoom levels, click-to-drill-down:
  - World: click a country to select it, click it again to zoom into...
  - Country: shows its counties + settlements. Click a county to select it,
    click it again to zoom into...
  - County ("village view"): shows its villages, linked by simple dirt roads,
    plus its settlements. Click a village for its farm-output stats.
Click outside the zoomed region (or the Back button) to zoom back out one
level at a time. Counties are the future unit of control for territory
reassignment.
"""
import math
import time
import tkinter as tk

from PIL import Image, ImageTk

from app.ui import theme
from app.world.world_map import Stance
from app.world.worldgen import OCEAN
from app.world.territory import bordering_counties, naval_reachable_counties
from app.world.resources import RESOURCES
from app.world import diplomacy
from app.world import construction
from app.world import trade
from app.world import expansion
from app.world import commander

_FLASH_COLOR = (255, 236, 120)   # bright gold — county gained
_FLASH_FAIL_COLOR = (232, 74, 62)  # bright red — county attack failed
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

# Per-county lightness offsets so neighboring counties of a faction read apart.
_COUNTY_SHADES = [-0.12, 0.10, 0.22, -0.04, 0.15, 0.02, 0.28, -0.09, 0.06, 0.19]


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
# app/world/resources.py (each biome/climate drives what a county yields).
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
# Local roads (village/settlement network within a county — see
# _place_villages_for_county in app/world/worldgen.py): Dirt for a road
# touching a village, brown; Stone for a road linking two settlements, gray.
_DIRT_ROAD_COLOR = "#8a6f4a"
_STONE_ROAD_COLOR = "#9a9ba3"
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
_SHIP_STYLE = {"fill": "#c8f5ff", "outline": "#154a5c", "r": 6, "glow": "#5fd0ff"}
# Commander (app/world/commander.py) — a bright orchid diamond, deliberately
# unlike any settlement/caravan color so the player's own unit never gets
# confused with anything else on the map.
_COMMANDER_STYLE = {"fill": "#e685ff", "outline": "#4a1a5c", "r": 7}
_SHIP_STYLE = {"fill": "#c9a86a", "outline": "#5c3f1a", "r": 6}
# Above this many villages in a county, skip name labels (village view) so it
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
    faction/county/settlement's resource dict."""
    if not res:
        return "None yet."
    order = sorted(res.keys(), key=lambda r: (RESOURCES.get(r, {}).get("tier", 9), r))
    return " · ".join(f"{r} {_fmt_amount(res[r])}" for r in order if res[r])


class MapView(tk.Frame):
    def __init__(self, master, world, on_attack, on_regenerate, on_end_turn,
                on_wildland_claim=None):
        super().__init__(master, bg=theme.BG)
        self.on_attack = on_attack
        self.on_regenerate = on_regenerate
        self.on_end_turn = on_end_turn
        self.on_wildland_claim = on_wildland_claim
        self.selected = None            # selected faction (world view)
        self.zoom_faction = None        # faction we've zoomed into (county view)
        self.selected_county = None
        self.zoom_county = None         # county we've zoomed into (village view)
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
        # counties launches the battle for it.
        self.attack_mode = None
        self._attack_enemy = None
        self._attack_frontier = []

        # Castle placement: when not None, holds the (own-territory) county
        # the player is about to click a build site within.
        self.building_mode = None

        # Post-battle border flash (see flash_county()): "success" (gold) for
        # a county gained, "failure" (red) for a failed attack.
        self._flash_county = None
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
        self.selected_county = None
        self.zoom_county = None
        self.selected_settlement = None
        self.selected_village = None
        self.selected_commander = None
        self.commander_move_mode = None
        self.attack_mode = None
        self._attack_enemy = None
        self._attack_frontier = []
        self.building_mode = None
        self._flash_county = None
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
        self._exit_ui()
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
        without resetting the camera/selection the way set_world() does."""
        from app.world import vision
        vision.recompute(self.world)
        self._precompute_colors()
        self._base_img = self._base_key = None
        if self.selected is not None:
            self._show_faction(self.selected)
        if self.selected_county is not None:
            self._show_county(self.selected_county)
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
        self._px_county = [None] * n
        self._px_county_hi = [None] * n
        self._owner_flat = [OCEAN] * n
        self._county_flat = [-1] * n
        sea = wd.sea_level
        fcolors = [_hex_to_rgb(f.color) for f in wd.factions]

        # a shaded color per county (varied within its faction)
        cshade = [None] * len(wd.counties)
        for f in wd.factions:
            fc = _hex_to_rgb(f.color)
            for li, cid in enumerate(f.meta.get("counties", [])):
                cshade[cid] = _shade(fc, _COUNTY_SHADES[li % len(_COUNTY_SHADES)])

        cg = wd.county_grid
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
                    self._px_county[i] = self._px_county_hi[i] = px
                elif (x, y) in wd.lake_cells:
                    # lake surface: water in every mode, but keep owner/county
                    # so clicks still resolve to the faction/county beneath.
                    lk = _rgb(*_LAKE_RGB)
                    self._px_pol[i] = self._px_pol_hi[i] = lk
                    self._px_fert[i] = self._px_elev[i] = lk
                    self._px_biome[i] = self._px_climate[i] = lk
                    self._px_county[i] = self._px_county_hi[i] = lk
                    self._owner_flat[i] = o
                    self._county_flat[i] = cg[y][x]
                elif (x, y) in wd.river_cells:
                    # River surface: baked into the raster exactly like a
                    # lake (flat tone, every mode, owner/county preserved
                    # beneath) rather than drawn as a separate vector line on
                    # top of everything — this is what makes it read as part
                    # of the terrain instead of a decal, and it means fog of
                    # war (which only ever composites over this raster)
                    # covers rivers automatically, same as anything else.
                    rv = _rgb(*_RIVER_RGB)
                    self._px_pol[i] = self._px_pol_hi[i] = rv
                    self._px_fert[i] = self._px_elev[i] = rv
                    self._px_biome[i] = self._px_climate[i] = rv
                    self._px_county[i] = self._px_county_hi[i] = rv
                    self._owner_flat[i] = o
                    self._county_flat[i] = cg[y][x]
                else:
                    relief = (h - sea) / (1 - sea) if sea < 1 else 0
                    if o >= 0:
                        base = _rgb(*_lighten(fcolors[o], 0.10 * relief))
                    else:
                        # UNCLAIMED — no faction color to draw from; a muted
                        # neutral tone, darker/rustier where the wildland
                        # garrison guarding it is stronger.
                        cid_here = cg[y][x]
                        strength = (wd.counties[cid_here].wildland_strength
                                   if 0 <= cid_here < len(wd.counties) else 40)
                        danger = max(0.0, min(1.0, strength / _WILDLAND_DANGER_REF))
                        base = _rgb(*(_UNCLAIMED_RGB[j] + (_UNCLAIMED_DANGER_RGB[j]
                                     - _UNCLAIMED_RGB[j]) * danger for j in range(3)))
                        base = _rgb(*_lighten(base, 0.08 * relief))

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

                    biome_rgb = _rgb(*_biome_rgb(wd.biome_grid[y][x]))
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
                    self._county_flat[i] = cid
                    shade = cshade[cid] if (cid >= 0 and cshade[cid] is not None) else base
                    # county border: any 4-neighbor in a different county, or
                    # a water-adjacent (coastline/riverbank) edge
                    border = water_adjacent
                    for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                        if not (0 <= nx < wd.w and 0 <= ny < wd.h) or cg[ny][nx] != cid:
                            border = True
                            break
                    self._px_county[i] = _rgb(*(_shade(shade, -0.5) if border else shade))
                    self._px_county_hi[i] = _rgb(*_lighten(shade, 0.45))
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

        self.rel_header = tk.Label(p, text="RELATIONSHIPS", bg=theme.PANEL,
                                   fg=theme.MUTED, font=("Segoe UI", 8, "bold"))
        self.rel_header.pack(anchor="w", padx=14, pady=(16, 4))
        self.rel_frame = tk.Frame(p, bg=theme.PANEL)
        self.rel_frame.pack(fill="x", padx=14)

        self.actions = tk.Frame(p, bg=theme.PANEL)
        self.actions.pack(fill="x", padx=14, pady=16)

        tk.Button(p, text="Generate New World", command=self.on_regenerate,
                  bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                  relief="flat", font=theme.FONT).pack(side="bottom", fill="x",
                                                       padx=14, pady=(4, 14))
        self.view_btn = tk.Button(p, text="View: Political", command=self._toggle_mode,
                                  bg="#232a36", fg=theme.INK,
                                  activebackground=theme.ACCENT, relief="flat",
                                  font=theme.FONT)
        self.view_btn.pack(side="bottom", fill="x", padx=14)
        tk.Button(p, text="End Turn", command=self._on_end_turn,
                  bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                  relief="flat", font=theme.FONT).pack(side="bottom", fill="x",
                                                       padx=14, pady=(4, 0))
        self.turn_lbl = tk.Label(p, text="", bg=theme.PANEL, fg=theme.MUTED,
                                 font=theme.FONT_BOLD)
        self.turn_lbl.pack(side="bottom", padx=14, pady=(8, 0))
        self.back_btn = tk.Button(p, text="← Back to World",
                                  command=self._exit_county_view, bg="#232a36",
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
        self.refresh()

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
        into your own county" no longer confines the camera to your own
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
        """True while browsing a foreign nation's counties (diplomacy-only —
        no village drill-down, no ordinary management)."""
        player = self._player_faction()
        return (player is not None and self.zoom_faction is not None
                and self.zoom_faction is not player)

    def _do_diplomacy(self, action_fn, nation, county=None):
        """Run a diplomacy action, show its flavor message on the bottom
        banner, and refresh whatever panel is currently displaying it."""
        player = self._player_faction()
        msg = (action_fn(self.world, player, nation, county) if county is not None
               else action_fn(self.world, player, nation))
        self.show_bottom_message(msg)
        if self.selected is nation:
            self._show_faction(nation)
        if county is not None and self.selected_county is county:
            self._show_county(county)
        self.render()

    def _show_faction(self, nation):
        player = self._player_faction()
        own = self._is_player(nation)
        self.title_lbl.config(text="Your Realm" if own else "Foreign Realm")
        s = nation.stats
        n_counties = len(nation.meta.get("counties", []))
        if own or player is None:
            zoom_hint = "\nClick again to zoom in."
        elif self.world.world_map.get_relationship(player.id, nation.id)["stance"] == Stance.ENEMY:
            zoom_hint = "\nClick again to attack."
        else:
            zoom_hint = "\nClick again to inspect its counties."
        self.info.config(
            fg=theme.INK,
            text=f"{nation.name}\nSpecies: {nation.meta['species']} "
                 f"— {nation.meta['trait']}\n"
                 f"Military {s['military']} · Morale {s['morale']} · "
                 f"Gold {s.get('gold', 0):,}\n"
                 f"Avg fertility {nation.meta['fertility']}%\n"
                 f"{self._settle_counts(nation)}\n"
                 f"{n_counties} counties.{zoom_hint}\n\n"
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
                if bordering_counties(self.world, player_idx, target_idx):
                    tk.Button(self.actions, text=f"Attack {nation.name}",
                              command=lambda n=nation: self._begin_attack_setup(n),
                              bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                              relief="flat", font=theme.FONT).pack(fill="x", pady=2)
                elif naval_reachable_counties(self.world, player_idx, target_idx):
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
        """Land trade route status/action against `nation` (only reached
        while relations aren't hostile — see _show_faction's caller): a
        completed route, in-progress construction, a Propose button once
        eligible, or why proposing isn't available yet. Sea lanes need no
        UI — they open automatically once eligible (see
        trade._capital_sea_path) and just show up on the map."""
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

    def _show_county(self, county):
        if county.faction_idx < 0:
            self._show_wildland_county(county)
            return
        s = county.stats
        country = self.zoom_faction
        wd = self.world
        n_villages = len(getattr(county, "villages", []))
        total_cells = sum(county.biome_counts.values()) or 1
        biome_line = ", ".join(
            f"{biome.capitalize()} ({round(100 * count / total_cells)}%)"
            for biome, count in sorted(county.biome_counts.items(),
                                       key=lambda kv: -kv[1])) or "Unclassified"
        lines = [f"{county.name}", f"County of {country.name}",
                 f"Area {s['area']} · Fertility {s['fertility']}%",
                 f"Biome: {biome_line}",
                 f"Climate: {county.dominant_climate.capitalize()}",
                 f"This turn's yield: {_format_resources(county.resources)}"]
        sts = [wd.settlements[i] for i in getattr(county, "meta_settlements", [])]
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
            for label, fn in (("Fabricate Claim on County", diplomacy.fabricate_claim),
                              ("Terrorize Locals", diplomacy.terrorize_locals)):
                tk.Button(self.actions, text=label,
                          command=lambda f=fn: self._do_diplomacy(f, country, county),
                          bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                          relief="flat", font=theme.FONT,
                          state="normal" if can_act else "disabled").pack(fill="x", pady=2)
            if not can_act:
                tk.Label(self.actions, text="Already acted against them this turn.",
                         bg=theme.PANEL, fg=theme.MUTED,
                         font=("Segoe UI", 8)).pack(anchor="w")
        elif self._player_faction() is not None:
            project = next((p for p in wd.castle_projects if p.county_id == county.id), None)
            if project is not None:
                note = " (half speed — road not yet finished)" if project.half_speed else ""
                elapsed = project.total_turns - project.turns_left
                tk.Label(self.actions, text=f"Castle under construction: "
                         f"{elapsed}/{project.total_turns} turns{note}",
                         bg=theme.PANEL, fg=theme.MUTED, font=theme.FONT,
                         justify="left", wraplength=260).pack(anchor="w", pady=(0, 6))
            player = self._player_faction()
            afford = construction.can_afford(player, construction.CASTLE_COST)
            tk.Label(self.actions, text=f"Cost: {_format_resources(construction.CASTLE_COST)}\n"
                     f"Build time: {construction.CASTLE_BUILD_TURNS} turns",
                     bg=theme.PANEL, fg=theme.INK if afford else theme.BAD, font=theme.FONT,
                     justify="left", wraplength=260).pack(anchor="w", pady=(0, 6))
            tk.Button(self.actions, text="Build Castle...",
                      command=lambda cnty=county: self._begin_castle_placement(cnty),
                      bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                      relief="flat", font=theme.FONT).pack(fill="x", pady=2)

    def _show_wildland_county(self, county):
        """UNCLAIMED land: wildland garrison strength, claim cost/time/odds,
        and a Claim Territory button (or why claiming isn't available yet)."""
        wd = self.world
        player = self._player_faction()
        total_cells = sum(county.biome_counts.values()) or 1
        biome_line = ", ".join(
            f"{biome.capitalize()} ({round(100 * count / total_cells)}%)"
            for biome, count in sorted(county.biome_counts.items(),
                                       key=lambda kv: -kv[1])) or "Unclassified"
        lines = [f"{county.name}", "Unclaimed wildland",
                 f"Area {county.stats['area']} · Fertility {county.stats['fertility']}%",
                 f"Biome: {biome_line}",
                 f"Wildland garrison strength: {county.wildland_strength}"]
        if player is not None:
            odds = expansion.claim_odds(player, county)
            lines.append(f"Estimated success odds: {round(100 * odds)}%")
        self.info.config(fg=theme.INK, text="\n".join(lines))

        for w in self.actions.winfo_children():
            w.destroy()
        if player is None:
            return
        faction_idx = wd.factions.index(player)
        if county not in expansion.claimable_frontier(wd, faction_idx):
            tk.Label(self.actions, text="Not adjacent to your territory yet.",
                     bg=theme.PANEL, fg=theme.MUTED, font=theme.FONT,
                     justify="left", wraplength=260).pack(anchor="w")
            return
        if wd.turn < county.claim_cooldown_until_turn:
            tk.Label(self.actions, text="The locals are still wary after "
                     "repelling your last attempt — try again later.",
                     bg=theme.PANEL, fg=theme.BAD, font=theme.FONT,
                     justify="left", wraplength=260).pack(anchor="w")
            return
        project = next((p for p in wd.claim_projects if p.county_id == county.id), None)
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
        cost = expansion.claim_cost(county)
        afford = construction.can_afford(player, cost)
        tk.Label(self.actions, text=f"Cost: {_format_resources(cost)}\n"
                 f"Build time: {expansion.claim_turns(county)} turns",
                 bg=theme.PANEL, fg=theme.INK if afford else theme.BAD, font=theme.FONT,
                 justify="left", wraplength=260).pack(anchor="w", pady=(0, 6))
        tk.Button(self.actions, text="Claim Territory",
                  command=lambda cnty=county: self._do_claim(cnty),
                  bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                  relief="flat", font=theme.FONT).pack(fill="x", pady=2)

    def _do_claim(self, county):
        player = self._player_faction()
        faction_idx = self.world.factions.index(player)
        msg = expansion.start_claim(self.world, faction_idx, county)
        self.show_bottom_message(msg)
        self._base_key = None
        if self.selected_county is county:
            self._show_county(county)
        self.render()

    def _do_wildland_battle(self, project):
        """Hand off to App.stage_wildland_battle — the interactive
        battlefield, not an instant formula, decides whether the claim
        succeeds (see app/world/expansion.py's advance_claims, which leaves
        a completed player claim sitting untouched for exactly this)."""
        if self.on_wildland_claim is not None:
            self.on_wildland_claim(project)

    def _show_settlement(self, st):
        wd = self.world
        county = (wd.counties[st.county_id].name
                  if 0 <= st.county_id < len(wd.counties) else "?")
        lines = [st.name, f"{st.kind.capitalize()} in {county}, "
                 f"{wd.factions[st.faction_idx].name}",
                 f"Upkeep: {_format_resources(st.upkeep)} per turn"]
        if getattr(st, "has_shipyard", False):
            lines.append("Has a Shipyard — commanders here launch free, fast ships.")
        self.info.config(fg=theme.INK, text="\n".join(lines))

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
            afford = construction.can_afford(player, construction.SHIPYARD_COST)
            tk.Label(self.actions,
                     text=f"Cost: {_format_resources(construction.SHIPYARD_COST)}\n"
                          f"Build time: {construction.SHIPYARD_BUILD_TURNS} turns",
                     bg=theme.PANEL, fg=theme.INK if afford else theme.BAD, font=theme.FONT,
                     justify="left", wraplength=260).pack(anchor="w", pady=(0, 6))
            tk.Button(self.actions, text="Build Shipyard",
                      command=lambda s=st: self._do_build_shipyard(s),
                      bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                      relief="flat", font=theme.FONT).pack(fill="x", pady=2)

    def _do_build_shipyard(self, st):
        player = self._player_faction()
        msg = construction.start_shipyard(self.world, player, st)
        self.show_bottom_message(msg)
        if self.selected_settlement is st:
            self._show_settlement(st)
        self.render()

    def _show_village(self, v):
        wd = self.world
        county = wd.counties[v.county_id]
        self.info.config(
            fg=theme.INK,
            text=f"{v.name}\nVillage in {county.name}, "
                 f"{wd.factions[v.faction_idx].name}\n"
                 f"Farms here contribute {v.farm_output} Grain per turn "
                 f"(before climate/season modifiers), scaled by local land "
                 f"fertility.")

    def _show_commander(self, cmd):
        """Panel for a selected Commander: position, current order, and
        Move/Board/Dismantle/Build Ship actions (which of these apply
        depends on whether the commander is aboard a ship, standing on a
        beached one, or on foot with none nearby). A pure scout for now —
        no combat, so there's nothing here about strength or risk."""
        wd = self.world
        aboard = commander.ship_by_id(wd, cmd.aboard_ship_id) if cmd.aboard_ship_id is not None else None
        beached = None if aboard is not None else commander.find_ship_at(
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
            if beached is not None:
                tk.Button(self.actions, text="Board Ship",
                          command=lambda: self._do_board_ship(cmd),
                          bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                          relief="flat", font=theme.FONT).pack(fill="x", pady=2)
                tk.Button(self.actions, text="Dismantle Ship",
                          command=lambda: self._do_dismantle_ship(cmd),
                          bg="#232a36", fg=theme.BAD, activebackground=theme.ACCENT,
                          relief="flat", font=theme.FONT).pack(fill="x", pady=2)
            if aboard is None and commander.can_build_ship(wd, cmd):
                shipyard = commander.shipyard_at(wd, cmd.faction_idx, cmd.pos)
                label = ("Launch Ship (free)" if shipyard is not None
                         else "Build Ship")
                tk.Button(self.actions, text=label,
                          command=lambda: self._do_build_ship(cmd),
                          bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
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
    # Three levels: World -> Country (shows counties) -> County (shows
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
        camera all the way out to it every time you back out of a county is
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

    def _enter_county_view(self, faction):
        self.zoom_faction = faction
        self.zoom_county = None
        self.selected_county = None
        self.selected_village = None
        self._base_key = None
        self.title_lbl.config(text="Counties")
        self.info.config(fg=theme.MUTED,
                         text=f"{faction.name}\nClick a county to inspect it.")
        self._enter_ui("COUNTY", "← Back to World", self._exit_county_view)
        self._start_zoom(self._padded_rect(faction.meta["bbox"]))

    def _exit_county_view(self):
        self.zoom_faction = None
        self.zoom_county = None
        self.selected_county = None
        self.selected_village = None
        self._base_key = None
        self._exit_ui()
        if self.selected:
            self._show_faction(self.selected)
        self._start_zoom(self._world_view_rect())

    def _enter_village_view(self, county):
        self.zoom_county = county
        self.selected_village = None
        self._base_key = None
        self.title_lbl.config(text="Villages")
        self.info.config(fg=theme.MUTED,
                         text=f"{county.name}\nClick a village to inspect it.")
        self._enter_ui("VILLAGE", "← Back to County", self._exit_village_view)
        self._start_zoom(self._padded_rect(county.bbox, min_pad_frac=0.2, min_size=6))

    def _exit_village_view(self):
        self.zoom_county = None
        self.selected_village = None
        self._base_key = None
        self._enter_ui("COUNTY", "← Back to World", self._exit_county_view)
        if self.selected_county:
            self._show_county(self.selected_county)
        self._start_zoom(self._padded_rect(self.zoom_faction.meta["bbox"]))

    # --- attack targeting ----------------------------------------------------
    def _begin_attack_setup(self, enemy, naval=False):
        """Zoom to the shared border (or coastline, for a naval invasion)
        with `enemy` and let the player pick which frontline/coastal county
        to attack. If `naval` isn't explicitly requested, land is tried
        first and naval is the automatic fallback when there's no land
        connection (e.g. the double-click-to-attack shortcut doesn't know
        which kind applies — it just wants "attack them, however")."""
        player = self._player_faction()
        player_idx = self.world.factions.index(player)
        enemy_idx = self.world.factions.index(enemy)

        if naval:
            frontier = naval_reachable_counties(self.world, player_idx, enemy_idx)
        else:
            frontier = bordering_counties(self.world, player_idx, enemy_idx)
            if not frontier:
                frontier = naval_reachable_counties(self.world, player_idx, enemy_idx)
                naval = bool(frontier)

        if not frontier:
            self.info.config(fg=theme.MUTED,
                             text=f"{enemy.name}\nNo shared border or coastal "
                                  "port to attack across right now.")
            return

        self.attack_mode = enemy
        self._attack_enemy = enemy
        self._attack_frontier = frontier
        self.selected_county = None
        self._base_key = None

        xs = [x for county in frontier for x, y in county.cells]
        ys = [y for county in frontier for x, y in county.cells]
        bbox = (min(xs), min(ys), max(xs) + 1, max(ys) + 1)

        self.title_lbl.config(text="Choose a Target")
        if naval:
            self.info.config(fg=theme.MUTED,
                             text=f"Launching a naval invasion of {enemy.name}.\n"
                                  "Click a highlighted county along the coast "
                                  "to attack it.")
        else:
            self.info.config(fg=theme.MUTED,
                             text=f"Attacking {enemy.name}.\nClick a highlighted "
                                  "county along the border to attack it.")
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

    def _launch_attack(self, county):
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
        # battle, flash_county() can highlight the (possibly newly-won)
        # county right where the player is already looking.
        self.on_attack(player, enemy, county)

    # --- castle placement ----------------------------------------------------
    def _begin_castle_placement(self, county):
        self.building_mode = county
        self.info.config(fg=theme.MUTED,
                         text=f"{county.name}\nClick a spot in this county to "
                              "begin building a castle there.\n\n"
                              f"Cost: {_format_resources(construction.CASTLE_COST)}\n"
                              f"Build time: {construction.CASTLE_BUILD_TURNS} turns")
        for w in self.actions.winfo_children():
            w.destroy()
        tk.Button(self.actions, text="Cancel", command=self._cancel_castle_placement,
                  bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                  relief="flat", font=theme.FONT).pack(fill="x", pady=2)
        self.render()

    def _cancel_castle_placement(self):
        self.building_mode = None
        if self.selected_county is not None:
            self._show_county(self.selected_county)
        self.render()

    # --- post-battle conquest flash ------------------------------------------
    def flash_county(self, county, outcome="success"):
        """Briefly blink a county's border — gold for a county gained,
        red for a failed attack — fading out over a couple of seconds. A
        failed attack also zooms back out to the world view once the blink
        finishes, since there's nothing new to look at up close."""
        if self._flash_id is not None:
            self.after_cancel(self._flash_id)
            self._flash_id = None
        self._flash_county = county
        self._flash_outcome = outcome
        self._flash_start = time.time()
        self._flash_tick()

    def _flash_tick(self):
        if self._flash_county is None:
            return
        if time.time() - self._flash_start >= _FLASH_DURATION:
            failed = self._flash_outcome == "failure"
            self._flash_county = None
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
            cid = wd.county_grid[gy][gx]
            if any(c.id == cid for c in self._attack_frontier):
                self._launch_attack(wd.counties[cid])
            return

        if self.building_mode is not None:
            # --- CASTLE PLACEMENT: pick a spot within the armed county -----
            county = self.building_mode
            if wd.county_grid[gy][gx] == county.id:
                player = self._player_faction()
                msg = construction.start_castle(wd, player, (gx, gy))
                self.building_mode = None
                self._base_key = None
                self.show_bottom_message(msg)
                if self.selected_county is county:
                    self._show_county(county)
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
        # the player's own commanders, checked before normal county/faction
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
                    self._enter_county_view(faction)
                else:
                    rel = self.world.world_map.get_relationship(player.id, faction.id)
                    if rel["stance"] == Stance.ENEMY:
                        self._begin_attack_setup(faction)   # at war -> attack
                    else:
                        self._enter_county_view(faction)    # not at war -> browse
            else:                                 # 1st click -> select country
                self.selected = faction
                self._base_key = None
                self._show_faction(faction)
                self.render()

        elif self.zoom_county is None:
            # --- LEVEL 1: county view (zoomed into a country) -------------
            zf = wd.factions.index(self.zoom_faction)
            # settlement markers take priority over county selection
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
            cid = wd.county_grid[gy][gx]
            if cid < 0:
                self._exit_county_view()          # clicked away -> zoom out
                return
            county = wd.counties[cid]
            if county.faction_idx != zf:
                # UNCLAIMED land adjacent to your own realm -> select it
                # (shows wildland info + a Claim button); anything else
                # (foreign-owned land, or unclaimed land while browsing a
                # foreign realm) just zooms back out as before.
                is_own = self.zoom_faction is self._player_faction()
                if is_own and county.faction_idx < 0:
                    self.selected_county = county
                    self._base_key = None
                    self._show_county(county)
                    self.render()
                else:
                    self._exit_county_view()
                return
            # Foreign browsing stops at the county level (diplomacy actions
            # only) — no drilling into a foreign nation's villages.
            if not self._zoom_is_foreign() and county is self.selected_county:
                self._enter_village_view(county)  # 2nd click -> village view
            else:                                 # 1st click -> select county
                self.selected_county = county
                self._base_key = None
                self._show_county(county)
                self.render()

        else:
            # --- LEVEL 2: village view (zoomed into a county) -------------
            for vid in self.zoom_county.villages:
                v = wd.villages[vid]
                sx = (v.pos[0] + 0.5 - vx0) * scale
                sy = (v.pos[1] + 0.5 - vy0) * scale
                if (sx - event.x) ** 2 + (sy - event.y) ** 2 <= 8 ** 2:
                    self.selected_village = v
                    self._show_village(v)
                    self.render()
                    return
            for sid in self.zoom_county.meta_settlements:
                st = wd.settlements[sid]
                sx = (st.pos[0] + 0.5 - vx0) * scale
                sy = (st.pos[1] + 0.5 - vy0) * scale
                if (sx - event.x) ** 2 + (sy - event.y) ** 2 <= 10 ** 2:
                    self.selected_settlement = st
                    self._show_settlement(st)
                    self.render()
                    return
            cid = wd.county_grid[gy][gx]
            if cid != self.zoom_county.id:
                self._exit_village_view()         # clicked away -> zoom out
            # else: clicked empty land within the same county — no-op

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
            sc = self.selected_county.id if self.selected_county else -1
            key = ("county", sc)
        elif self.mode != "political":
            key = (self.mode,)
        else:
            key = ("political", id(self.selected))
        if key == self._base_key and self._base_img is not None:
            return

        if self.zoom_faction is not None:
            if self.selected_county is not None:
                sc = self.selected_county.id
                base, hi = self._px_county, self._px_county_hi
                data = [hi[i] if cid == sc else base[i]
                        for i, cid in enumerate(self._county_flat)]
            else:
                data = self._px_county
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
        self._draw_construction(c, screen)
        self._draw_settlements(c, screen)
        self._draw_villages(c, screen)
        self._draw_labels(c, screen)
        self._draw_attack_targets(c, screen)
        self._draw_ships(c, screen)
        self._draw_commanders(c, screen)
        self._draw_flash(c, screen)

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
        rather than something tied to one county, plus a thin dashed
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
        view shows only cities (to avoid clutter); the county view shows every
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
        span the whole world rather than one county."""
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
            style = _SHIP_STYLE if caravan.kind == "sea" else _CARAVAN_STYLE
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
        construction-site marker for each castle being built."""
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

        for castle in wd.castle_projects:
            x, y = screen(castle.pos[0] + 0.5, castle.pos[1] + 0.5)
            r = 4
            c.create_rectangle(x - r, y - r, x + r, y + r, outline="#f2e9c9",
                               width=2, dash=(2, 2))
            c.create_text(x + 1, y + r + 8, text=f"{castle.turns_left}t",
                         fill="#000000", font=("Segoe UI", 7))
            c.create_text(x, y + r + 7, text=f"{castle.turns_left}t",
                         fill="#f2e9c9", font=("Segoe UI", 7))

    def _draw_roads(self, c, screen):
        """Straight road segments linking every village and settlement
        across a faction's counties (an MST per county — see
        _place_villages_for_county). Per-segment tier, not per-county: Dirt
        (brown/dashed) for any road touching a village, Stone (gray/solid)
        for a road connecting two settlements. Dirt only shows once zoomed
        into a specific nation's counties (too minor to matter at world
        scale); Stone — the trunk network — is visible even from the world
        map, same idea as trade routes already being shown at every zoom
        level."""
        wd = self.world
        width = max(1.0, self._place[2] * 0.18)

        if self.zoom_faction is None:
            for county in wd.counties:
                if county.faction_idx < 0:
                    continue
                for (ax, ay), (bx, by), tier in wd.roads_by_county.get(county.id, []):
                    if tier != "stone":
                        continue
                    if not (self._cell_revealed(ax, ay) or self._cell_revealed(bx, by)):
                        continue
                    x0, y0 = screen(ax + 0.5, ay + 0.5)
                    x1, y1 = screen(bx + 0.5, by + 0.5)
                    c.create_line(x0, y0, x1, y1, fill=_STONE_ROAD_COLOR,
                                  width=width, capstyle="round")
            return

        for cid in self.zoom_faction.meta.get("counties", []):
            for (ax, ay), (bx, by), tier in wd.roads_by_county.get(cid, []):
                if not (self._cell_revealed(ax, ay) or self._cell_revealed(bx, by)):
                    continue
                is_stone = tier == "stone"
                color = _STONE_ROAD_COLOR if is_stone else _DIRT_ROAD_COLOR
                dash = None if is_stone else (4, 3)
                x0, y0 = screen(ax + 0.5, ay + 0.5)
                x1, y1 = screen(bx + 0.5, by + 0.5)
                c.create_line(x0, y0, x1, y1, fill=color, width=width,
                              capstyle="round", dash=dash)

    def _draw_villages(self, c, screen):
        """Small dots for villages — only shown in village view. Names are
        skipped past a village-count threshold to avoid label soup."""
        if self.zoom_county is None:
            return
        wd = self.world
        style = _VILLAGE_STYLE
        r = style["r"]
        vids = self.zoom_county.villages
        show_names = len(vids) <= _VILLAGE_LABEL_LIMIT
        for vid in vids:
            v = wd.villages[vid]
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
        if self.zoom_county is not None:
            return   # village view: county/faction name labels aren't useful here
        if self.zoom_faction is not None:
            items = []
            for cid in self.zoom_faction.meta.get("counties", []):
                county = wd.counties[cid]
                cx, cy = int(county.center[0] * wd.w), int(county.center[1] * wd.h)
                if self._cell_revealed(cx, cy):
                    items.append((county.name, county.center))
        else:
            items = [(f.name, f.center) for f in wd.factions if self._is_known(f)]
        for name, center in items:
            lx, ly = screen(center[0] * wd.w, center[1] * wd.h)
            c.create_text(lx + 1, ly + 1, text=name, fill="#000000", font=_LABEL_FONT)
            c.create_text(lx, ly, text=name, fill="#ffffff", font=_LABEL_FONT)

    def _county_border_segments(self, county):
        """Screen-space-independent (x,y) edge list tracing a county's
        outline: every cell-edge where the neighboring cell belongs to a
        different county (or is off-map)."""
        wd = self.world
        cg = wd.county_grid
        cid = county.id
        segs = []
        for x, y in county.cells:
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
        county in red so it's obvious which land can be struck."""
        if self.attack_mode is None:
            return
        wd = self.world
        width = max(2.0, self._place[2] * 0.3)
        for county in self._attack_frontier:
            for x0, y0, x1, y1 in self._county_border_segments(county):
                sx0, sy0 = screen(x0, y0)
                sx1, sy1 = screen(x1, y1)
                c.create_line(sx0, sy0, sx1, sy1, fill=theme.BAD, width=width,
                              capstyle="round")
            lx, ly = screen(county.center[0] * wd.w, county.center[1] * wd.h)
            c.create_text(lx + 1, ly + 1, text=county.name, fill="#000000",
                          font=_LABEL_FONT)
            c.create_text(lx, ly, text=county.name, fill="#ffffff", font=_LABEL_FONT)

    def _draw_flash(self, c, screen):
        """Blinking outline around a county after a battle: gold for a
        county gained, red for a failed attack — a few strobes that settle
        down as the overall fade envelope runs out."""
        if self._flash_county is None:
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
        for x0, y0, x1, y1 in self._county_border_segments(self._flash_county):
            sx0, sy0 = screen(x0, y0)
            sx1, sy1 = screen(x1, y1)
            c.create_line(sx0, sy0, sx1, sy1, fill=color, width=width,
                          capstyle="round")
