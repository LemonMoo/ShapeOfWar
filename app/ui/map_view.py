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
import tkinter as tk

from PIL import Image, ImageTk

from app.ui import theme
from app.world.world_map import Stance
from app.world.worldgen import OCEAN

_LABEL_FONT = ("Segoe UI", 8, "bold")

_OCEAN_DEEP = (18, 30, 58)
_OCEAN_SHALLOW = (44, 74, 120)
_LAKE_RGB = (48, 92, 140)      # inland lake water (shown in every map mode)

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


RIVER_COLOR = "#5fa8dc"
_RIVER_RGB = _hex_to_rgb(RIVER_COLOR)

# Settlement marker styling (drawn as canvas shapes — no art assets).
_SETTLE_STYLE = {
    "city":   {"fill": "#f2e9c9", "outline": "#4a4230", "r": 5},
    "castle": {"fill": "#c9ccd6", "outline": "#3a3f4c", "r": 4},
    "town":   {"fill": "#d9b98a", "outline": "#4a3a24", "r": 3},
}
_VILLAGE_STYLE = {"fill": "#c9a06a", "outline": "#4a3418", "r": 2}
_ROAD_COLOR = "#8a6f4a"
# Above this many villages in a county, skip name labels (village view) so it
# doesn't turn into unreadable text soup.
_VILLAGE_LABEL_LIMIT = 24


def _lerp_hex(c0, c1, t):
    t = max(0.0, min(1.0, t))
    r, g, b = _rgb(*(c0[j] + (c1[j] - c0[j]) * t for j in range(3)))
    return f"#{r:02x}{g:02x}{b:02x}"


class MapView(tk.Frame):
    def __init__(self, master, world, on_attack, on_regenerate):
        super().__init__(master, bg=theme.BG)
        self.on_attack = on_attack
        self.on_regenerate = on_regenerate
        self.selected = None            # selected faction (world view)
        self.zoom_faction = None        # faction we've zoomed into (county view)
        self.selected_county = None
        self.zoom_county = None         # county we've zoomed into (village view)
        self.selected_settlement = None
        self.selected_village = None
        self.mode = "political"
        self._img = None
        self._place = (0, 0, 1)         # vx0, vy0, scale
        self._base_img = None           # cached full-grid PIL image
        self._base_key = None           # signature of what _base_img depicts
        self._anim_id = None
        self._animating = False

        self.canvas = tk.Canvas(self, bg=theme.CANVAS, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.render())
        self.canvas.bind("<Button-1>", self._on_click)

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
        self.view = [0.0, 0.0, world.w, world.h]
        self.view_target = list(self.view)
        self._base_img = self._base_key = None
        self._precompute_colors()
        self._exit_ui()
        self.info.config(fg=theme.MUTED, text="Click a faction to inspect it.")
        for frame in (self.rel_frame, self.actions):
            for w in frame.winfo_children():
                w.destroy()
        self.render()

    def _precompute_colors(self):
        """Flat row-major RGB pixel lists for every view (for Image.putdata)."""
        wd = self.world
        n = wd.w * wd.h
        self._px_pol = [None] * n
        self._px_pol_hi = [None] * n
        self._px_fert = [None] * n
        self._px_elev = [None] * n
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
                    self._px_county[i] = self._px_county_hi[i] = px
                elif (x, y) in wd.lake_cells:
                    # lake surface: water in every mode, but keep owner/county
                    # so clicks still resolve to the faction/county beneath.
                    lk = _rgb(*_LAKE_RGB)
                    self._px_pol[i] = self._px_pol_hi[i] = lk
                    self._px_fert[i] = self._px_elev[i] = lk
                    self._px_county[i] = self._px_county_hi[i] = lk
                    self._owner_flat[i] = o
                    self._county_flat[i] = cg[y][x]
                else:
                    relief = (h - sea) / (1 - sea) if sea < 1 else 0
                    base = _rgb(*_lighten(fcolors[o], 0.10 * relief))
                    self._px_pol[i] = base
                    self._px_pol_hi[i] = _rgb(*_lighten(base, 0.4))
                    self._px_fert[i] = _fert_rgb(wd.fertility[y][x])
                    self._px_elev[i] = _elev_rgb(relief)
                    self._owner_flat[i] = o

                    cid = cg[y][x]
                    self._county_flat[i] = cid
                    shade = cshade[cid] if cid >= 0 else base
                    # county border: any 4-neighbor in a different county
                    border = False
                    for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                        if not (0 <= nx < wd.w and 0 <= ny < wd.h) or cg[ny][nx] != cid:
                            border = True
                            break
                    self._px_county[i] = _rgb(*(_shade(shade, -0.5) if border else shade))
                    self._px_county_hi[i] = _rgb(*_lighten(shade, 0.45))
                i += 1

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
        self.back_btn = tk.Button(p, text="← Back to World",
                                  command=self._exit_county_view, bg="#232a36",
                                  fg=theme.INK, activebackground=theme.ACCENT,
                                  relief="flat", font=theme.FONT)
        # back_btn is packed only while zoomed in.

    _MODES = ["political", "fertility", "elevation"]

    def _toggle_mode(self):
        self.mode = self._MODES[(self._MODES.index(self.mode) + 1) % len(self._MODES)]
        self.view_btn.config(text=f"View: {self.mode.capitalize()}")
        self._base_key = None
        self.render()

    def _show_faction(self, nation):
        self.title_lbl.config(text="Faction")
        s = nation.stats
        n_counties = len(nation.meta.get("counties", []))
        self.info.config(
            fg=theme.INK,
            text=f"{nation.name}\nSpecies: {nation.meta['species']} "
                 f"— {nation.meta['trait']}\n"
                 f"Military {s['military']} · Morale {s['morale']} · "
                 f"Economy {s['economy']}\n"
                 f"Crop output {s['crops']} · Avg fertility "
                 f"{nation.meta['fertility']}%\n"
                 f"Resources +{s.get('res_gen', 0)} / "
                 f"-{s.get('res_drain', 0)} "
                 f"(net {s.get('res_gen', 0) - s.get('res_drain', 0)})\n"
                 f"{self._settle_counts(nation)}\n"
                 f"{n_counties} counties — click again to zoom in.")

        self.rel_header.config(text="RELATIONSHIPS")
        for w in self.rel_frame.winfo_children():
            w.destroy()
        rels = self.world.world_map.relationships_of(nation.id)
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

    def _settle_counts(self, nation):
        """'2 cities · 3 castles · 5 towns' summary for a faction."""
        wd = self.world
        counts = {"city": 0, "castle": 0, "town": 0}
        for sid in nation.meta.get("settlements", []):
            counts[wd.settlements[sid].kind] += 1
        return (f"{counts['city']} cities · {counts['castle']} castles · "
                f"{counts['town']} towns")

    def _show_county(self, county):
        s = county.stats
        country = self.zoom_faction
        wd = self.world
        n_villages = len(getattr(county, "villages", []))
        lines = [f"{county.name}", f"County of {country.name}",
                 f"Area {s['area']} · Fertility {s['fertility']}%",
                 f"Provides {s['crops']} crops to {country.name}.",
                 f"Resources +{s.get('res_gen', 0)} / -{s.get('res_drain', 0)} "
                 f"(net {s.get('res_gen', 0) - s.get('res_drain', 0)}, "
                 f"incl. {s.get('farm_output', 0)} from farms)"]
        sts = [wd.settlements[i] for i in getattr(county, "meta_settlements", [])]
        if sts:
            lines.append("Settlements: " + ", ".join(
                f"{st.name} ({st.kind})" for st in sts))
        else:
            lines.append("No settlements.")
        lines.append(f"{n_villages} villages — click again to zoom in.")
        self.info.config(fg=theme.INK, text="\n".join(lines))

    def _show_settlement(self, st):
        wd = self.world
        county = (wd.counties[st.county_id].name
                  if 0 <= st.county_id < len(wd.counties) else "?")
        self.info.config(
            fg=theme.INK,
            text=f"{st.name}\n{st.kind.capitalize()} in {county}, "
                 f"{wd.factions[st.faction_idx].name}\n"
                 f"Generates {st.gen} resources · Drains {st.drain}\n"
                 f"Net {'+' if st.net >= 0 else ''}{st.net} resources.")

    def _show_village(self, v):
        wd = self.world
        county = wd.counties[v.county_id]
        self.info.config(
            fg=theme.INK,
            text=f"{v.name}\nVillage in {county.name}, "
                 f"{wd.factions[v.faction_idx].name}\n"
                 f"Farms here produce {v.farm_output} resources, "
                 f"scaled by local land fertility.")

    # --- zoom-level enter/exit ----------------------------------------------
    # Three levels: World -> Country (shows counties) -> County (shows
    # villages). Each level's "enter" sets state + zooms in; "exit" clears
    # that level's state and zooms back out to the level above.
    @staticmethod
    def _padded_rect(bbox, min_pad_frac=0.12, min_size=0):
        x0, y0, x1, y1 = bbox
        pad = min_pad_frac * max(x1 - x0, y1 - y0, min_size)
        return [x0 - pad, y0 - pad, x1 + pad, y1 + pad]

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
        self._start_zoom([0.0, 0.0, self.world.w, self.world.h])

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

        if self.zoom_faction is None:
            # --- LEVEL 0: world view -------------------------------------
            o = wd.owner[gy][gx]
            if o == OCEAN:
                return
            faction = wd.factions[o]
            if faction is self.selected:          # 2nd click -> zoom in
                self._enter_county_view(faction)
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
            if cid < 0 or wd.counties[cid].faction_idx != zf:
                self._exit_county_view()          # clicked away -> zoom out
                return
            county = wd.counties[cid]
            if county is self.selected_county:    # 2nd click -> zoom in
                self._enter_village_view(county)
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
        vx0, vy0, vx1, vy1 = self._fit_aspect(self.view, cw / ch)
        scale = cw / (vx1 - vx0)
        self._place = (vx0, vy0, scale)

        # crop the visible grid region and scale it to the canvas (nearest)
        bx0, by0 = max(0, int(math.floor(vx0))), max(0, int(math.floor(vy0)))
        bx1, by1 = min(wd.w, int(math.ceil(vx1))), min(wd.h, int(math.ceil(vy1)))
        if bx1 > bx0 and by1 > by0:
            crop = self._base_img.crop((bx0, by0, bx1, by1))
            tw = max(1, round((bx1 - bx0) * scale))
            th = max(1, round((by1 - by0) * scale))
            self._img = ImageTk.PhotoImage(crop.resize((tw, th), Image.NEAREST))
            c.create_image((bx0 - vx0) * scale, (by0 - vy0) * scale,
                           anchor="nw", image=self._img)

        def screen(gx, gy):
            return ((gx - vx0) * scale, (gy - vy0) * scale)

        # Rivers: width grows with flow; the last few segments fade into the
        # water they empty into (ocean or lake) for a seamless mouth.
        for r in wd.rivers:
            cells = r["cells"]
            if len(cells) < 2:
                continue
            w = max(1.0, scale * (0.35 + 0.18 * min(3.0, math.log10(r["flow"] + 1))))
            pts = []
            for gx, gy in cells:
                pts.extend(screen(gx + 0.5, gy + 0.5))
            c.create_line(*pts, fill=RIVER_COLOR, width=w, joinstyle="round",
                          capstyle="round", smooth=True)
            # overdraw the mouth segments, blending toward the water color
            n = len(cells)
            for i in range(max(0, n - 4), n - 1):
                d = (n - 1) - (i + 1)
                blend = max(0.0, 1.0 - d / 3.0) * 0.9
                gx0, gy0 = cells[i]
                gx1, gy1 = cells[i + 1]
                x0, y0 = screen(gx0 + 0.5, gy0 + 0.5)
                x1, y1 = screen(gx1 + 0.5, gy1 + 0.5)
                c.create_line(x0, y0, x1, y1,
                              fill=_lerp_hex(_RIVER_RGB, _OCEAN_SHALLOW, blend),
                              width=w, capstyle="round", joinstyle="round")

        # Relationship links (world view, selected faction only).
        if self.zoom_faction is None and self.selected:
            ax, ay = screen(self.selected.center[0] * wd.w,
                            self.selected.center[1] * wd.h)
            for rel in wd.world_map.relationships_of(self.selected.id):
                bx, by = screen(rel["other"].center[0] * wd.w,
                                rel["other"].center[1] * wd.h)
                width = 1 if rel["stance"] == Stance.NEUTRAL else 2
                c.create_line(ax, ay, bx, by,
                              fill=theme.STANCE_COLOR.get(rel["stance"], theme.MUTED),
                              width=width)

        self._draw_roads(c, screen)
        self._draw_settlements(c, screen)
        self._draw_villages(c, screen)
        self._draw_labels(c, screen)

    def _draw_settlements(self, c, screen):
        """Markers: city = circle, castle = triangle, town = square. The world
        view shows only cities (to avoid clutter); the county view shows every
        settlement of the zoomed faction, with names."""
        wd = self.world
        if self.zoom_faction is not None:
            sids = self.zoom_faction.meta.get("settlements", [])
            show_names = True
        else:
            sids = [s.id for s in wd.settlements if s.kind == "city"]
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

    def _draw_roads(self, c, screen):
        """Simple straight dirt-road segments linking villages (and the
        county's main settlement, as a hub) — only shown in village view."""
        if self.zoom_county is None:
            return
        segs = self.world.roads_by_county.get(self.zoom_county.id, [])
        width = max(1.0, self._place[2] * 0.18)
        for (ax, ay), (bx, by) in segs:
            x0, y0 = screen(ax + 0.5, ay + 0.5)
            x1, y1 = screen(bx + 0.5, by + 0.5)
            c.create_line(x0, y0, x1, y1, fill=_ROAD_COLOR, width=width,
                          capstyle="round", dash=(4, 3))

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
            items = [(wd.counties[cid].name, wd.counties[cid].center)
                     for cid in self.zoom_faction.meta.get("counties", [])]
        else:
            items = [(f.name, f.center) for f in wd.factions]
        for name, center in items:
            lx, ly = screen(center[0] * wd.w, center[1] * wd.h)
            c.create_text(lx + 1, ly + 1, text=name, fill="#000000", font=_LABEL_FONT)
            c.create_text(lx, ly, text=name, fill="#ffffff", font=_LABEL_FONT)
