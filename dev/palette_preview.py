"""Preview render of the redesigned terrain palette + texture.

    python dev/palette_preview.py [world.pkl]

Loads a generated world and renders the two biome-relevant map modes the
same way MapView does (module-level color/texture functions from
app/ui/map_view.py -- the Tk widget pipeline itself can't run headless), so
the new palette can be eyeballed before launching the game:

  dev/shots/palette_biome.png      -- Biome mode: flat biome colors + texture
  dev/shots/palette_political.png  -- Political mode: faction colors, biome
                                      tint, texture at reduced strength
  dev/shots/palette_legend.png     -- the 12-biome swatch key
"""
import os
import pickle
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw

from app.ui import map_view as M
from app.world.worldgen import OCEAN

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots")


def _water_rgb(w, x, y, h):
    """Ocean depth ramp / lake / river -- mirrors _compute_cell."""
    if (x, y) in w.river_cells:
        return M._rgb(*M._RIVER_RGB)
    if (x, y) in w.lake_cells:
        return M._rgb(*M._LAKE_RGB)
    sea = w.sea_level
    depth = max(0.0, min(1.0, (sea - h) / (sea or 1)))
    return M._rgb(*(M._OCEAN_DEEP[j] + (M._OCEAN_SHALLOW[j] - M._OCEAN_DEEP[j])
                    * (1 - depth) for j in range(3)))


def build_biome(w):
    data = [None] * (w.w * w.h)
    for y in range(w.h):
        row = w.biome_grid[y]
        base = y * w.w
        for x in range(w.w):
            i = base + x
            biome = row[x]
            if biome:
                rgb = M._biome_rgb(biome)
                data[i] = M._texture_cell(rgb, biome, x, y, M._TEXTURE_FULL)
            else:
                data[i] = _water_rgb(w, x, y, w.height[y][x])
    return data


def build_political(w):
    fcolors = [M._hex_to_rgb(f.color) for f in w.factions]
    data = [None] * (w.w * w.h)
    sea = w.sea_level
    for y in range(w.h):
        row = w.owner[y]
        base = y * w.w
        for x in range(w.w):
            i = base + x
            o = row[x]
            h = w.height[y][x]
            if o == OCEAN or (x, y) in w.lake_cells or (x, y) in w.river_cells:
                data[i] = _water_rgb(w, x, y, h)
                continue
            relief = (h - sea) / (1 - sea) if sea < 1 else 0
            if o >= 0:
                base_c = M._rgb(*M._lighten(fcolors[o], 0.10 * relief))
            else:
                base_c = M._rgb(*M._lighten(M._UNCLAIMED_RGB, 0.08 * relief))
            biome = w.biome_grid[y][x]
            tint = M._POL_BIOME_TINT.get(biome)
            if tint:
                base_c = M._rgb(*M._blend(base_c, M._POL_BIOME_COLORS[biome], tint))
            data[i] = M._texture_cell(base_c, biome, x, y, M._TEXTURE_POL)
    return data


def build_legend():
    names = ("mountain", "highland", "forest", "taiga", "jungle", "plains",
             "steppe", "savannah", "coastal", "desert", "tundra", "swamp")
    sw = 46
    img = Image.new("RGB", (sw * 2 + 40, 24 * 6 + 24), (24, 26, 32))
    d = ImageDraw.Draw(img)
    for i, name in enumerate(names):
        col, row = i // 6, i % 6
        x0 = 12 + col * (sw + 40)
        y0 = 12 + row * 24
        d.rectangle([x0, y0, x0 + sw, y0 + 16], fill=M._BIOME_COLORS[name],
                    outline=(60, 62, 70))
        d.text((x0 + sw + 6, y0 - 1), name, fill=(230, 230, 230))
    return img


def save(data, w, name, scale=1):
    img = Image.new("RGB", (w.w * scale, w.h * scale))
    if scale == 1:
        img.putdata(data)
    else:
        small = Image.new("RGB", (w.w, w.h))
        small.putdata(data)
        img = small.resize(img.size, Image.NEAREST)
    path = os.path.join(OUT_DIR, name)
    img.save(path)
    return path


def stats(data, w, label):
    from collections import Counter
    c = Counter(data[i] for i in range(0, w.w * w.h, 7))
    top = c.most_common(8)
    print(f"  {label}: {len(c)} distinct sampled colors; top:")
    for rgb, cnt in top:
        print(f"    #{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}  x{cnt}")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "dev/worlds/dev160.pkl"
    with open(path, "rb") as fh:
        w = pickle.load(fh)
    print(f"world {path}: {w.w}x{w.h}, {len(w.factions)} factions, "
          f"turn {w.turn}")
    biome = build_biome(w)
    polit = build_political(w)
    p1 = save(biome, w, "palette_biome.png", scale=2)
    p2 = save(polit, w, "palette_political.png", scale=2)
    p3 = build_legend()
    p3.save(os.path.join(OUT_DIR, "palette_legend.png"))
    print(f"saved {p1}\nsaved {p2}\nsaved "
          f"{os.path.join(OUT_DIR, 'palette_legend.png')}")
    stats(biome, w, "biome mode")
    stats(polit, w, "political mode")


if __name__ == "__main__":
    main()
