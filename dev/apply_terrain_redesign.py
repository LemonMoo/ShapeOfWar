"""One-shot apply of the terrain-redesign edits to app/ui/map_view.py.

The desktop host periodically restores map_view.py from a stale buffer, so
incremental edit-by-edit application kept losing work. This applies every
replacement to the pristine file in memory and writes it once, atomically.

Run from the repo root:  python dev/apply_terrain_redesign.py
"""
import io
import sys

PATH = "app/ui/map_view.py"

src = io.open(PATH, encoding="utf-8").read()
orig_len = len(src)

# Each (old, new); old must occur exactly once in the running text.
EDITS = [
    # 1. fantasy palette
    ('''_BIOME_COLORS = {
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
}''',
     '''# Fantasy-stylized, hue-separated: every biome gets its own colour FAMILY
# rather than a member of a shared one, so a world map reads at a glance.
# The old palette clustered three near-identical dark greens (forest/taiga/
# jungle/swamp) and four near-identical yellows (plains/steppe/savannah/
# desert); these push the families apart -- emerald vs. teal vs. tropical vs.
# olive, grass vs. dry-grass vs. gold vs. amber -- while staying mid-dark
# enough that markers, labels and the fog overlay all stay legible on top.
_BIOME_COLORS = {
    "mountain": (126, 108, 168),   # violet stone -- instantly reads as peaks
    "highland": (112, 132, 152),   # cool blue-grey foothills, off the greens
    "forest": (24, 100, 52),       # deep emerald
    "taiga": (44, 104, 90),        # cold pine, hue-pulled toward teal
    "jungle": (14, 136, 62),       # vivid tropical green, brightest of the set
    "plains": (120, 168, 70),      # fresh grass -- the baseline "ordinary green"
    "steppe": (172, 160, 86),      # dry yellow-green, clearly yellower than plains
    "savannah": (206, 174, 72),    # warm gold
    "coastal": (84, 172, 178),     # seafoam cyan, off the land-family greens
    "desert": (224, 192, 114),     # amber sand -- the lightest, warmest land
    "tundra": (188, 198, 214),     # pale ice lavender, cold and near-bare
    "swamp": (86, 98, 46),         # murky olive, the darkest, brownest green
}'''),

    # 2. raised political tints
    ('''# The faction colour still has to win: this is the POLITICAL map, and who owns
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
}''',
     '''# The faction colour still has to win: this is the POLITICAL map, and who owns
# a place is what it is for. So the strengths are graded by how much a biome
# needs saying rather than applied evenly -- the extremes (desert, jungle,
# mountain, tundra) tint hard because they change what a region is worth and
# how an army moves through it, while plains and coastal barely tint at all
# because "ordinary green country" is the baseline everything else reads
# against. Steppe and savannah sit between: dry, but not desert.
# Raised across the board (the old 0.12-0.42 band left ten of twelve biomes
# reading as flat faction colour -- see the comment on _BIOME_COLORS); the
# per-biome texture and terrain symbols below carry the rest of the signal
# without letting any single biome wash out the owner.
_POL_BIOME_TINT = {
    "mountain": 0.52,
    "desert": 0.52,
    "jungle": 0.48,
    "forest": 0.46,
    "tundra": 0.46,
    "swamp": 0.44,
    "taiga": 0.42,
    "highland": 0.38,
    "savannah": 0.36,
    "steppe": 0.30,
    "coastal": 0.24,
    "plains": 0.16,
}'''),

    # 3. water palette
    ('''_OCEAN_DEEP = (18, 30, 58)
_OCEAN_SHALLOW = (44, 74, 120)
_LAKE_RGB = (48, 92, 140)      # inland lake water (shown in every map mode)''',
     '''# Water, fantasy-inked to match the land palette: deeper navy, brighter
# tropical shallows, and fresh water pulled further from the sea blues so a
# river and a coast stop being the same colour at a glance.
_OCEAN_DEEP = (16, 34, 70)
_OCEAN_SHALLOW = (46, 106, 152)
_LAKE_RGB = (48, 116, 154)     # inland lake water (shown in every map mode)'''),

    # 4. river colour
    ("_RIVER_RGB = (64, 112, 152)", "_RIVER_RGB = (62, 134, 170)"),

    # 5. terrain symbol colour tables + glyph dispatch
    ('''# Symbols layered on top of the color tint above (political mode only) —
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
                                   # is needed on top of the spacing floor above''',
     '''# Symbols layered on top of the color tint above (political mode only) —
# color alone doesn't read clearly enough at a glance, especially at this
# map's size. Ten of the twelve biomes carry a glyph (plains and coastal are
# the quiet baseline and deliberately get none); see _draw_terrain_symbols/
# _draw_terrain_legend. Colours per biome, matched to the fantasy palette:
# forests are emerald and cold-pine, mountains pale lavender like the peaks
# they sit on, the desert cactus is green because that is what reads as a
# desert on a fantasy map.
_TERRAIN_SYMBOL_FILL = {
    "forest":   "#173d20",
    "taiga":    "#1d3a3c",
    "jungle":   "#0f5c28",
    "swamp":    "#2e3a18",
    "savannah": "#3f4c1d",
    "steppe":   "#4a4a26",
    "desert":   "#4c7a34",
    "tundra":   "#7d8a96",
    "mountain": "#ddd2ee",
    "highland": "#c6ccd8",
}
_TERRAIN_SYMBOL_OUTLINE = {
    "forest":   "#0a1f10",
    "taiga":    "#0c1c1e",
    "jungle":   "#062a12",
    "swamp":    "#161c0a",
    "savannah": "#1c2410",
    "steppe":   "#262612",
    "desert":   "#23401a",
    "tundra":   "#3d434c",
    "mountain": "#544a78",
    "highland": "#5a6274",
}
# Which biomes get a glyph, and how densely: the terrain-defining biomes
# (forest/jungle/mountain) draw at every sampled point; dry and cold ones
# are dotted more sparsely so a desert reads as dunes with a few cacti,
# not a cactus farm. Plains and coastal are deliberately absent -- the
# baseline country every other biome reads against. Values are the
# fraction of sampled grid points that actually draw.
_TERRAIN_GLYPHS = {
    "forest":   1.0,
    "jungle":   1.0,
    "mountain": 1.0,
    "taiga":    0.7,
    "swamp":    0.7,
    "highland": 0.7,
    "savannah": 0.6,
    "desert":   0.6,
    "tundra":   0.6,
    "steppe":   0.5,
}
_TERRAIN_SYMBOL_SCREEN_SPACING = 26   # target px between sampled points on screen
_TERRAIN_SYMBOL_MIN_WORLD_SPACING = 3   # never sample closer than this many world cells
_TERRAIN_SYMBOL_MAX_COUNT = 400   # hard cap on sampled points regardless of visible
                                   # area -- see _draw_terrain_symbols for why this
                                   # is needed on top of the spacing floor above'''),

    # 6. per-biome texture: module functions + strengths (inserted after _biome_rgb)
    ('''def _biome_rgb(biome):
    return _BIOME_COLORS.get(biome, _NO_DATA_RGB)''',
     '''def _biome_rgb(biome):
    return _BIOME_COLORS.get(biome, _NO_DATA_RGB)


# --- per-biome terrain texture ------------------------------------------------
# Colour alone, however well separated, still reads as flat poster paint at a
# map this size. Each biome also gets a deterministic tone texture baked into
# the terrain raster: forest is blotchy canopy, desert has dune ripples, tundra
# is frost-mottled, swamp is wet patches. Two properties matter:
#
#   * DETERMINISTIC. The raster is rebuilt on ownership changes and mode
#     switches, and only a hash keyed by (x, y) keeps the pattern from
#     visibly shifting between rebuilds (a flickering map reads as broken).
#     See _terrain_noise.
#
#   * COARSE-GRAINED. Per-cell white noise is TV static at this scale; the
#     mottle is driven by lattice noise with `scale`-cell patches (blended
#     with a little per-cell grain), so neighbouring cells of the same biome
#     share the texture instead of sparkling.
#
# Applied in _ensure_base after the mode's flat colours are chosen, at full
# strength in Biome mode and reduced strength in the faction-carrying modes
# (political/region) so ownership still wins. See _texture_pixels.
def _terrain_noise(x, y, salt):
    """Deterministic 0..1 hash of cell (x, y), same value every render --
    the same hash family _terrain_jitter uses, returning 0..1 instead of
    -0.5..0.5."""
    h = (x * 374761393 + y * 668265263 + salt * 2246822519) & 0xffffffff
    h = (h ^ (h >> 13)) * 1274126177 & 0xffffffff
    h = (h ^ (h >> 16)) & 0xffffffff
    return h / 0xffffffff


# Per-biome texture spec: (density, dark, light, scale)
#   density - fraction of cells the texture touches (0..1)
#   dark    - how far the touched tone moves toward black (negative)
#   light   - how far toward white (positive)
#   scale   - lattice spacing in cells of the patch noise (blotch size)
# The extremes are graded the same way the political tints are: mountains,
# forests and deserts need the texture most; plains and coastal are baseline
# country and only faintly textured so they stay the quiet ground everything
# else reads against.
_BIOME_TEXTURE = {
    "forest":   (0.30, -0.18, 0.00, 3.0),   # blotchy dark canopy
    "taiga":    (0.18, -0.25, 0.00, 5.0),   # sparser, stronger cold shadows
    "jungle":   (0.45, -0.12, 0.12, 3.0),   # dense sun-dappled canopy
    "swamp":    (0.25, -0.22, 0.00, 6.0),   # big dark wet patches
    "tundra":   (0.30, 0.00, 0.16, 4.0),    # pale frost mottle
    "mountain": (0.30, -0.10, 0.20, 3.0),   # rocky flecks and creases
    "highland": (0.20, 0.00, 0.10, 5.0),    # gentle rolling shade
    "steppe":   (0.06, 0.00, 0.14, 2.0),    # sparse pale grass tufts
    "savannah": (0.08, 0.00, 0.20, 2.0),    # sparse golden tufts
    "plains":   (0.10, -0.05, 0.05, 4.0),   # faint, so it reads as farmland
    "coastal":  (0.12, -0.04, 0.05, 4.0),   # faint dunes/sand flecks
}

# How hard the texture is applied per view mode: full in Biome mode (there
# the biome IS the subject), reduced in the faction-carrying modes so who
# owns a place still reads as the primary signal. See _ensure_base.
_TEXTURE_FULL = 1.0
_TEXTURE_POL = 0.55


def _texture_cell(rgb, biome, x, y, strength):
    """One cell's colour after `biome`'s texture at `strength` (0..1) is
    applied. Returns `rgb` untouched when the cell falls under the biome's
    density threshold, so plains and sparse biomes stay mostly clean."""
    if biome == "desert":
        # Dune ripples: diagonal light bands ~7 cells apart, waved by noise.
        band = (x + y + _terrain_noise(x, y, 7) * 2.5) % 7.0
        if band < 1.6:
            amt = (1.6 - band) / 1.6 * 0.13 * strength
            return _rgb(*_lighten(rgb, amt))
        return rgb
    spec = _BIOME_TEXTURE.get(biome)
    if spec is None:
        return rgb
    density, dark, light, scale = spec
    # Coarse lattice decides WHERE a patch is (exactly `density` of cells,
    # since patch ~ U(0,1)), and a little per-cell jitter softens the patch
    # edges instead of leaving hard scale-cell squares. The jitter has mean
    # zero, so it blurs the boundary without changing the touched fraction.
    patch = _terrain_noise(int(x // scale), int(y // scale), 3)
    grain = _terrain_noise(x, y, 5)
    mix = patch + (grain - 0.5) * 0.4
    if mix > density:
        return rgb
    t = 1.0 - mix / max(density, 1e-4)
    amt = dark + (light - dark) * t
    if amt >= 0:
        return _rgb(*_lighten(rgb, amt * strength))
    return _rgb(*(int(c * (1.0 + amt * strength)) for c in rgb))'''),

    # 7. texture pass in _ensure_base + _texture_pixels method
    ('''        img = Image.new("RGB", (wd.w, wd.h))
        img.putdata(data)
        self._base_img = img
        self._base_key = key

    def _under_pixels(self, selected_id=-1):''',
     '''        img = Image.new("RGB", (wd.w, wd.h))
        if self.mode == "biome":
            strength = _TEXTURE_FULL
        elif region_mode or self.mode == "political":
            strength = _TEXTURE_POL
        else:
            strength = 0.0
        if strength:
            # Copy: the _px_* arrays are the cache the incremental patcher
            # (_update_dirty_colors) recomputes into, and they must stay
            # texture-free or the next rebuild would texture them twice.
            data = self._texture_pixels(list(data), strength)
        img.putdata(data)
        self._base_img = img
        self._base_key = key

    def _texture_pixels(self, data, strength):
        """Overlay the per-biome terrain texture onto a full-map pixel list,
        in place. Ocean cells carry no biome, and lake/river cells must be
        skipped explicitly -- worldgen assigns river cells a biome, but they
        render as flat _RIVER_RGB water and would end up mottled. The
        texture is deterministic per cell (see _terrain_noise), so a region
        whose ownership changes later gets repainted with exactly the same
        pattern its neighbours already wear -- no seams, no flicker."""
        wd = self.world
        bg = wd.biome_grid
        rivers = wd.river_cells
        w, h = wd.w, wd.h
        for y in range(h):
            row = bg[y]
            base = y * w
            for x in range(w):
                biome = row[x]
                if biome and (x, y) not in rivers:
                    i = base + x
                    data[i] = _texture_cell(data[i], biome, x, y, strength)
        return data

    def _under_pixels(self, selected_id=-1):'''),

    # 8. expanded glyph functions (replace the two old ones)
    ('''    def _draw_forest_glyph(self, c, x, y, r):
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
                         fill=_MOUNTAIN_SYMBOL_FILL, outline=_MOUNTAIN_SYMBOL_OUTLINE)''',
     '''    def _draw_conifer_cluster(self, c, x, y, r, fill, outline):
        """A small cluster of 2-3 tiny conifer triangles — reads as "a patch
        of forest/taiga" at a glance, layered on top of the color tint
        _precompute_colors already blends into political mode."""
        for ox, oy, rr in ((-r * 0.55, r * 0.28, r * 0.85),
                          (r * 0.5, r * 0.35, r * 0.8),
                          (0.0, -r * 0.25, r * 0.65)):
            px, py = x + ox, y + oy
            c.create_polygon(px, py - rr, px + rr * 0.62, py + rr * 0.55,
                             px - rr * 0.62, py + rr * 0.55,
                             fill=fill, outline=outline)

    def _draw_forest_glyph(self, c, x, y, r):
        """Deep-emerald conifer cluster."""
        self._draw_conifer_cluster(c, x, y, r, _TERRAIN_SYMBOL_FILL["forest"],
                                   _TERRAIN_SYMBOL_OUTLINE["forest"])

    def _draw_taiga_glyph(self, c, x, y, r):
        """Cold pine-blue conifer cluster -- forest, but visibly colder."""
        self._draw_conifer_cluster(c, x, y, r, _TERRAIN_SYMBOL_FILL["taiga"],
                                   _TERRAIN_SYMBOL_OUTLINE["taiga"])

    def _draw_jungle_glyph(self, c, x, y, r):
        """A broadleaf tree: trunk plus two overlapping canopy circles --
        round and dense where the conifers are spiky."""
        fill, outline = (_TERRAIN_SYMBOL_FILL["jungle"],
                         _TERRAIN_SYMBOL_OUTLINE["jungle"])
        c.create_line(x, y + r * 0.5, x, y - r * 0.1, fill=outline,
                      width=max(1, int(r * 0.14)))
        c.create_oval(x - r * 0.95, y - r * 0.85, x + r * 0.1, y + r * 0.3,
                      fill=fill, outline=outline)
        c.create_oval(x - r * 0.1, y - r * 0.95, x + r * 0.95, y + r * 0.2,
                      fill=fill, outline=outline)

    def _draw_swamp_glyph(self, c, x, y, r):
        """Three thin reed blades rising out of the murk."""
        fill, outline = (_TERRAIN_SYMBOL_FILL["swamp"],
                         _TERRAIN_SYMBOL_OUTLINE["swamp"])
        for ox in (-r * 0.45, 0.0, r * 0.45):
            c.create_polygon(x + ox - r * 0.09, y + r * 0.5,
                             x + ox + r * 0.09, y + r * 0.5,
                             x + ox, y - r * 0.65,
                             fill=fill, outline=outline)

    def _draw_steppe_glyph(self, c, x, y, r):
        """Two short dry grass blades."""
        fill, outline = (_TERRAIN_SYMBOL_FILL["steppe"],
                         _TERRAIN_SYMBOL_OUTLINE["steppe"])
        for ox in (-r * 0.25, r * 0.25):
            c.create_polygon(x + ox - r * 0.07, y + r * 0.5,
                             x + ox + r * 0.07, y + r * 0.5,
                             x + ox + r * 0.05, y - r * 0.45,
                             fill=fill, outline=outline)

    def _draw_savannah_glyph(self, c, x, y, r):
        """An umbrella acacia: thin trunk, one wide flat canopy."""
        fill, outline = (_TERRAIN_SYMBOL_FILL["savannah"],
                         _TERRAIN_SYMBOL_OUTLINE["savannah"])
        c.create_line(x, y + r * 0.5, x, y - r * 0.05, fill=outline,
                      width=max(1, int(r * 0.1)))
        c.create_oval(x - r * 1.0, y - r * 0.5, x + r * 1.0, y + r * 0.15,
                      fill=fill, outline=outline)

    def _draw_desert_glyph(self, c, x, y, r):
        """A saguaro cactus: trunk plus one up-reaching arm -- sparse, so
        desert stays mostly dune."""
        fill, outline = (_TERRAIN_SYMBOL_FILL["desert"],
                         _TERRAIN_SYMBOL_OUTLINE["desert"])
        c.create_rectangle(x - r * 0.15, y - r * 0.5, x + r * 0.15, y + r * 0.5,
                           fill=fill, outline=outline)
        c.create_rectangle(x + r * 0.1, y - r * 0.3, x + r * 0.4, y - r * 0.1,
                           fill=fill, outline=outline)
        c.create_rectangle(x + r * 0.28, y - r * 0.62, x + r * 0.4, y - r * 0.3,
                           fill=fill, outline=outline)

    def _draw_tundra_glyph(self, c, x, y, r):
        """A low, pale scrub mound hugging the ground."""
        fill, outline = (_TERRAIN_SYMBOL_FILL["tundra"],
                         _TERRAIN_SYMBOL_OUTLINE["tundra"])
        c.create_oval(x - r * 0.7, y - r * 0.25, x + r * 0.7, y + r * 0.5,
                      fill=fill, outline=outline)

    def _draw_highland_glyph(self, c, x, y, r):
        """A gentle rounded hill -- the soft slope before the peaks."""
        fill, outline = (_TERRAIN_SYMBOL_FILL["highland"],
                         _TERRAIN_SYMBOL_OUTLINE["highland"])
        c.create_polygon(x - r * 0.9, y + r * 0.5, x - r * 0.45, y - r * 0.4,
                         x + r * 0.55, y - r * 0.35, x + r * 0.9, y + r * 0.5,
                         fill=fill, outline=outline, smooth=True)

    def _draw_mountain_glyph(self, c, x, y, r):
        """A small double-peak mountain silhouette, pale lavender like the
        violet peaks it sits on."""
        fill, outline = (_TERRAIN_SYMBOL_FILL["mountain"],
                         _TERRAIN_SYMBOL_OUTLINE["mountain"])
        c.create_polygon(x - r * 0.95, y + r * 0.5, x - r * 0.15, y - r * 0.65,
                         x + r * 0.55, y + r * 0.5,
                         fill=fill, outline=outline)
        c.create_polygon(x - r * 0.05, y + r * 0.5, x + r * 0.4, y - r * 0.2,
                         x + r * 0.95, y + r * 0.5,
                         fill=fill, outline=outline)

    def _draw_terrain_glyph(self, c, biome, x, y, r):
        """Route one sampled biome to its canvas glyph."""
        if biome == "forest":
            self._draw_forest_glyph(c, x, y, r)
        elif biome == "taiga":
            self._draw_taiga_glyph(c, x, y, r)
        elif biome == "jungle":
            self._draw_jungle_glyph(c, x, y, r)
        elif biome == "swamp":
            self._draw_swamp_glyph(c, x, y, r)
        elif biome == "savannah":
            self._draw_savannah_glyph(c, x, y, r)
        elif biome == "steppe":
            self._draw_steppe_glyph(c, x, y, r)
        elif biome == "desert":
            self._draw_desert_glyph(c, x, y, r)
        elif biome == "tundra":
            self._draw_tundra_glyph(c, x, y, r)
        elif biome == "mountain":
            self._draw_mountain_glyph(c, x, y, r)
        elif biome == "highland":
            self._draw_highland_glyph(c, x, y, r)'''),

    # 9. symbol sampling over all glyph biomes + shared legend builder
    ('''                biome = wd.biome_grid[gy][gx]
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
                     font=("Segoe UI", 8), anchor="w")''',
     '''                biome = wd.biome_grid[gy][gx]
                fraction = _TERRAIN_GLYPHS.get(biome)
                if fraction is None:
                    continue
                # Sparse biomes draw at only `fraction` of sampled points --
                # deterministic (see _terrain_jitter), so nothing dances.
                if fraction < 1.0 and self._terrain_jitter(gx, gy, 4) >= fraction - 0.5:
                    continue
                jx = self._terrain_jitter(gx, gy, 1) * spacing * 0.7
                jy = self._terrain_jitter(gx, gy, 2) * spacing * 0.7
                sx, sy = screen(gx + 0.5 + jx, gy + 0.5 + jy)
                self._draw_terrain_glyph(c, biome, sx, sy, r)

    # Legend rows, in display order: two columns of five, dense-and-important
    # biomes first so the eye finds them. Plains and coastal carry no glyph
    # and are absent by design -- see _TERRAIN_GLYPHS.
    _TERRAIN_LEGEND_ORDER = ("forest", "taiga", "jungle", "swamp", "steppe",
                             "savannah", "desert", "tundra", "highland",
                             "mountain")
    _TERRAIN_LEGEND_LABEL = {
        "forest": "Forest", "taiga": "Taiga", "jungle": "Jungle",
        "swamp": "Swamp", "steppe": "Steppe", "savannah": "Savannah",
        "desert": "Desert", "tundra": "Tundra", "highland": "Highland",
        "mountain": "Mountain",
    }

    def _build_terrain_legend(self, c, x0, y0):
        """Draw the terrain-symbol key onto canvas `c` at (x0, y0): all ten
        glyphs in two columns of five. Shared by the Tk canvas's corner
        legend (_draw_terrain_legend, redrawn every frame) and the GPU flat
        map's static legend (built once at construction -- see the
        _flat_legend block in __init__), so the two can never disagree."""
        col_w, row_h = 104, 20
        w, h = col_w * 2 + 16, 14 + row_h * 5 + 8
        c.create_rectangle(x0, y0, x0 + w, y0 + h, fill=theme.PANEL,
                           outline=theme.LINE, width=1)
        c.create_text(x0 + w / 2, y0 + 10, text="LEGEND", fill=theme.MUTED,
                      font=("Segoe UI", 7, "bold"))
        for i, biome in enumerate(self._TERRAIN_LEGEND_ORDER):
            cx = x0 + 16 + (i // 5) * col_w
            cy = y0 + 16 + row_h * 0.5 + (i % 5) * row_h
            self._draw_terrain_glyph(c, biome, cx, cy, 7)
            c.create_text(cx + 16, cy, text=self._TERRAIN_LEGEND_LABEL[biome],
                          fill=theme.INK, font=("Segoe UI", 8), anchor="w")

    def _draw_terrain_legend(self, c):
        """An always-visible key explaining the terrain glyphs — fixed to
        the map area's top-left corner (not tied to world coordinates, so
        it never pans/zooms with the map), like a real map legend. Political
        mode only, matching the symbols it explains. Placed just right of
        the left sidebar, which overlays the canvas's own corner."""
        if self.mode != "political":
            return
        self._build_terrain_legend(c, _LEFT_PANEL_W + 8, 12)'''),

    # 10. docstring of _draw_terrain_symbols: mention all biomes
    ('''    def _draw_terrain_symbols(self, c, screen, bx0, by0, bx1, by1):
        """Sparse tree/mountain glyphs over forest/mountain biome cells
        within the visible viewport — color tint alone doesn't read clearly''',
     '''    def _draw_terrain_symbols(self, c, screen, bx0, by0, bx1, by1):
        """Sparse terrain glyphs over the glyph-bearing biome cells (forest,
        taiga, jungle, swamp, savannah, steppe, desert, tundra, mountain,
        highland -- see _TERRAIN_GLYPHS) within the visible viewport: color
        tint alone doesn't read clearly'''),

    # 11. GL static legend uses the shared builder
    ('''        # Terrain legend for the GPU flat map (see _sync_flatgl): the
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
                                      font=("Segoe UI", 8), anchor="w")''',
     '''        # Terrain legend for the GPU flat map (see _sync_flatgl): the
        # canvas draws its own corner legend as vector items every frame
        # (_draw_terrain_legend) -- a GL surface can't have Tk items drawn
        # over it that way, so this is the same box built ONCE as an
        # ordinary small Tk canvas and left alone; only shown/hidden per
        # frame, never redrawn, since its content never changes. Same
        # builder as the canvas legend, so both surfaces agree.
        lw, lh = 104 * 2 + 16, 14 + 20 * 5 + 8
        self._flat_legend = tk.Canvas(self, width=lw, height=lh, bg=theme.PANEL,
                                      highlightthickness=1,
                                      highlightbackground=theme.LINE)
        self._build_terrain_legend(self._flat_legend, 0, 0)'''),

    # 12. GL shape import
    ('''from app.ui.gl_flatmap import (SHAPE_CIRCLE, SHAPE_TRIANGLE, SHAPE_SQUARE,
                               SHAPE_DIAMOND, SHAPE_HULL)''',
     '''from app.ui.gl_flatmap import (SHAPE_CIRCLE, SHAPE_TRIANGLE, SHAPE_SQUARE,
                               SHAPE_DIAMOND, SHAPE_HULL, SHAPE_TREE,
                               SHAPE_MOUND, SHAPE_BLADES, SHAPE_CACTUS)'''),

    # 13. remove the old cached GL emitter from _flat_markers
    ('''        # Forest/mountain terrain-symbol glyphs (see _draw_terrain_symbols):
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
        return marks''',
     '''        # Terrain symbols are NOT emitted here -- they are viewport-dependent
        # (sampled over the visible rect, re-spaced by zoom), so caching them
        # with the other markers would leave them stale the moment the camera
        # pans. _sync_flatgl appends the live set every frame instead (see
        # _flat_terrain_symbols), exactly as the canvas draws them every
        # frame.
        return marks

    # Which GL shape each glyph-bearing biome renders as -- mirror of the
    # canvas glyph set in _draw_terrain_glyph, using gl_flatmap's own shape
    # primitives (tree/mound/blades/cactus for the new shapes, triangle for
    # peaks). Only biomes in _TERRAIN_GLYPHS appear.
    _GL_TERRAIN_SHAPE = {
        "forest": SHAPE_TREE,
        "taiga": SHAPE_TREE,
        "jungle": SHAPE_TREE,
        "swamp": SHAPE_BLADES,
        "steppe": SHAPE_BLADES,
        "savannah": SHAPE_BLADES,
        "desert": SHAPE_CACTUS,
        "tundra": SHAPE_MOUND,
        "mountain": SHAPE_TRIANGLE,
        "highland": SHAPE_TRIANGLE,
    }

    def _flat_terrain_symbols(self, vx0, vy0, vx1, vy1, scale):
        """The GL flat map's terrain glyphs, as set_markers tuples
        (x, y, size_world_units, (r,g,b), shape). The GPU equivalent of
        _draw_terrain_symbols -- same jittered per-cell sampling, same
        screen-spacing formula and cap, same per-biome sparseness.

        Computed from the LIVE viewport every frame in _sync_flatgl rather
        than cached with _flat_markers: the sampling grid depends on where
        the camera is and how far it is zoomed, and a cached symbol set
        would go stale on the first pan (the old emitter inside _flat_markers
        had exactly that flaw -- symbols froze in place while the map slid
        underneath them). The grid walk is capped at _TERRAIN_SYMBOL_MAX_COUNT
        and is the same order of work the canvas already does per frame.

        Emits raw unwrapped x (gx may lie past the world edge near the seam);
        gl_flatmap's set_markers wraps each point to the copy nearest the
        camera at pack time, exactly like the canvas's per-segment drawing."""
        if self.mode != "political":
            return []
        wd = self.world
        spacing = max(_TERRAIN_SYMBOL_MIN_WORLD_SPACING,
                     round(_TERRAIN_SYMBOL_SCREEN_SPACING / max(scale, 0.01)))
        visible_area = max(1, (vx1 - vx0) * (vy1 - vy0))
        area_spacing = math.ceil(math.sqrt(visible_area / _TERRAIN_SYMBOL_MAX_COUNT))
        spacing = max(spacing, area_spacing)
        size = max(2.5, scale * spacing * 0.22) / scale
        by0 = max(0, int(math.floor(vy0)))
        by1 = min(wd.h, int(math.ceil(vy1)))
        if by1 <= by0:
            return []
        gy0 = by0 - by0 % spacing
        gx0 = int(math.floor(vx0)) - int(math.floor(vx0)) % spacing
        marks = []
        for gy in range(gy0, by1, spacing):
            for gx in range(gx0, int(math.ceil(vx1)), spacing):
                wx = gx % wd.w
                if (wd.owner[gy][wx] == OCEAN or (wx, gy) in wd.river_cells
                        or (wx, gy) in wd.lake_cells):
                    continue
                if not self._cell_revealed(wx, gy):
                    continue
                biome = wd.biome_grid[gy][wx]
                fraction = _TERRAIN_GLYPHS.get(biome)
                if fraction is None:
                    continue
                if fraction < 1.0 and self._terrain_jitter(wx, gy, 4) >= fraction - 0.5:
                    continue
                jx = self._terrain_jitter(wx, gy, 1) * spacing * 0.7
                jy = self._terrain_jitter(wx, gy, 2) * spacing * 0.7
                marks.append((gx + 0.5 + jx, gy + 0.5 + jy, size,
                             _GL_RGB[_TERRAIN_SYMBOL_FILL[biome]],
                             self._GL_TERRAIN_SHAPE[biome]))
        return marks'''),

    # 14. per-frame GL symbols in _sync_flatgl
    ('''        rebuilt = structural or flashing or move_animating
        t_content = time.perf_counter()

        g.set_lines(lines)''',
     '''        rebuilt = structural or flashing or move_animating
        t_content = time.perf_counter()

        # Terrain glyphs are viewport-dependent (sampled over the visible
        # rect, re-spaced by zoom), so unlike the cached markers they are
        # recomputed every frame from the live view -- same as the canvas
        # path draws them every frame. See _flat_terrain_symbols.
        # In non-political modes (or an empty viewport) `terrain` is [] and
        # the cached list passes through untouched, so set_markers' own
        # identity+wrap-bucket skip still fires on the common idle path.
        # In political mode the concatenation is a fresh list per frame, so
        # markers re-pack each pan -- bounded work (the symbol grid is
        # capped at _TERRAIN_SYMBOL_MAX_COUNT and the canvas pays the same
        # per-frame cost), not a regression to worry about.
        terrain = self._flat_terrain_symbols(vx0, vy0, vx1, vy1, scale)
        if terrain:
            markers = markers + terrain

        g.set_lines(lines)'''),

    # 15. GL legend placement clears the left sidebar
    ('''        if self.mode == "political":
            self._flat_legend.place(x=12, y=12)''',
     '''        if self.mode == "political":
            # Just right of the left sidebar (which overlays the map's own
            # corner), so the key is visible while the panel is open.
            self._flat_legend.place(x=_LEFT_PANEL_W + 8, y=12)'''),

    # 16. lifted palette for political-mode blending
    ('''_POL_BIOME_TINT = {
    "mountain": 0.52,
    "desert": 0.52,
    "jungle": 0.48,
    "forest": 0.46,
    "tundra": 0.46,
    "swamp": 0.44,
    "taiga": 0.42,
    "highland": 0.38,
    "savannah": 0.36,
    "steppe": 0.30,
    "coastal": 0.24,
    "plains": 0.16,
}''',
     '''_POL_BIOME_TINT = {
    "mountain": 0.52,
    "desert": 0.52,
    "jungle": 0.48,
    "forest": 0.46,
    "tundra": 0.46,
    "swamp": 0.44,
    "taiga": 0.42,
    "highland": 0.38,
    "savannah": 0.36,
    "steppe": 0.30,
    "coastal": 0.24,
    "plains": 0.16,
}

# The palette blended into the POLITICAL map's faction colours. Deliberately
# NOT the same colours Biome mode shows: faction colours are dark, and
# blending a dark base toward the deep fantasy palette (forest (24,100,52),
# swamp (86,98,46)...) leaves every biome a shade of the owner's dark olive.
# A LIFTED copy of the palette (each colour lightened toward white) pulls a
# dark faction base visibly into the biome's hue family instead, which is
# what makes a desert read as warm and a forest as green under any owner.
# Measured on a real 14-faction world: political-mode per-biome colour
# separation ~6.8 (dark palette) -> ~13.6 (lifted), beating the old palette.
_POL_BIOME_COLORS = {b: _rgb(*_lighten(c, 0.35))
                     for b, c in _BIOME_COLORS.items()}'''),

    # 17. _compute_cell blends political mode with the lifted palette
    ('''            biome_here = wd.biome_grid[y][x]
            tint = _POL_BIOME_TINT.get(biome_here)
            if tint:
                base = _rgb(*_blend(base, _BIOME_COLORS[biome_here], tint))''',
     '''            biome_here = wd.biome_grid[y][x]
            tint = _POL_BIOME_TINT.get(biome_here)
            if tint:
                base = _rgb(*_blend(base, _POL_BIOME_COLORS[biome_here], tint))'''),
]

for i, (old, new) in enumerate(EDITS, 1):
    n = src.count(old)
    if n != 1:
        print(f"EDIT {i}: expected exactly 1 occurrence, found {n}")
        if n == 0:
            head = old.splitlines()[0][:70]
            print(f"  missing block starting: {head!r}")
        sys.exit(1)
    src = src.replace(old, new)

if len(src) <= orig_len:
    print("no growth -- nothing applied?")
    sys.exit(1)

with io.open(PATH, "w", encoding="utf-8", newline="") as fh:
    # The file is CRLF; universal-newline reading above gave us \n, so put
    # the \r\n back to keep the diff clean.
    fh.write(src.replace("\n", "\r\n"))
print(f"applied {len(EDITS)} edits: {orig_len} -> {len(src)} bytes -> {PATH}")
