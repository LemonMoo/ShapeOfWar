"""Render a standalone debug view of app/world/plates.py -- Phase 1 of the
tectonic-plate worldgen rework (HANDOFF.md §9). Plate geometry and boundary
classification ONLY: this never touches generate_world, never builds a real
World, and has zero effect on the shipping game. It exists to answer one
question before Phase 2 (wiring plates into the height field) starts: does
the geometry look like plausible tectonics at all.

    python dev/plate_shot.py [seed] [n_plates] [width] [height]
    python dev/plate_shot.py 7 16 1100 660

Draws:
  - each plate as a flat, distinct colour (continental = warm, oceanic = cool)
  - drift arrows from each plate's seed point
  - boundary cells coloured by classification (see the legend it prints)
  - hotspot island chains as dots fading with age/distance from the vent
"""
import colorsys
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw

from app.world import plates as P

LEGEND = {
    P.CONVERGENT_CC: ("#ff5540", "convergent, both continental -- range"),
    P.CONVERGENT_SUBDUCTION: ("#ff9a3d", "convergent, subduction -- trench + range"),
    P.CONVERGENT_OO: ("#ffe23d", "convergent, both oceanic -- island arc"),
    P.DIVERGENT_CC: ("#3dd6ff", "divergent, both continental -- rift"),
    P.DIVERGENT_OTHER: ("#3d7bff", "divergent, oceanic side -- ridge"),
    P.TRANSFORM: ("#b6b6c2", "transform -- sliding past"),
}


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _plate_color(plate):
    """Continental plates warm (green-brown band), oceanic cool (blue band)
    -- so kind is legible at a glance without needing the legend, and
    individual plates within a kind are told apart by hue offset alone."""
    if plate.kind == P.CONTINENTAL:
        hue = 0.08 + (plate.id * 0.61803) % 0.22   # golden-ratio spread, warm band
        sat, val = 0.55, 0.75
    else:
        hue = 0.52 + (plate.id * 0.61803) % 0.22   # cool band
        sat, val = 0.55, 0.70
    r, g, b = colorsys.hsv_to_rgb(hue, sat, val)
    return (int(r * 255), int(g * 255), int(b * 255))


def render(pl, out_path, scale=1):
    w, h = pl.width, pl.height
    colors = [_plate_color(p) for p in pl.plates]
    img = Image.new("RGB", (w, h))
    flat = pl.plate_id.reshape(-1)
    img.putdata([colors[i] for i in flat])
    if scale != 1:
        img = img.resize((w * scale, h * scale), Image.NEAREST)
    draw = ImageDraw.Draw(img)

    for b in pl.boundaries:
        color = _hex_to_rgb(LEGEND[b.kind][0])
        x, y = b.x * scale, b.y * scale
        draw.point((x, y), fill=color)
        if scale >= 2:
            draw.point((x + 1, y), fill=color)
            draw.point((x, y + 1), fill=color)

    for p in pl.plates:
        cx, cy = p.cx * scale, p.cy * scale
        ex, ey = cx + p.drift_x * 40 * scale, cy + p.drift_y * 40 * scale
        draw.line([cx, cy, ex, ey], fill=(255, 255, 255), width=2)
        draw.ellipse([ex - 3, ey - 3, ex + 3, ey + 3], fill=(255, 255, 255))
        draw.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], outline=(0, 0, 0), width=2)

    for _plate_id, links in pl.hotspot_chains:
        for lx, ly, strength in links:
            r = 2 + strength * 4
            x, y = lx * scale, ly * scale
            draw.ellipse([x - r, y - r, x + r, y + r],
                         fill=(255, 60, 220), outline=(20, 0, 20))

    img.save(out_path)
    return img


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    n_plates = int(sys.argv[2]) if len(sys.argv) > 2 else 16
    width = int(sys.argv[3]) if len(sys.argv) > 3 else 1100
    height = int(sys.argv[4]) if len(sys.argv) > 4 else 660

    pl = P.generate_plates(width, height, seed=seed, n_plates=n_plates)

    counts = {}
    for k, _ in LEGEND.items():
        counts[k] = 0
    for b in pl.boundaries:
        counts[b.kind] += 1

    n_cont = sum(1 for p in pl.plates if p.kind == P.CONTINENTAL)
    n_ocean = len(pl.plates) - n_cont
    print(f"{n_plates} plates ({n_cont} continental, {n_ocean} oceanic) on a "
         f"{width}x{height} map, seed {seed}")
    print(f"plate cell counts: "
         f"{sorted((p.cell_count for p in pl.plates), reverse=True)}")
    print(f"{len(pl.boundaries)} boundary cells:")
    for kind, (_color, label) in LEGEND.items():
        print(f"  {counts[kind]:6d}  {label}")
    print(f"{len(pl.hotspot_chains)} hotspot chains, "
         f"{P.HOTSPOT_CHAIN_LINKS} links each")

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"plates_{width}x{height}_s{seed}_n{n_plates}.png")
    render(pl, out_path, scale=1)
    print(f"-> {out_path}")


if __name__ == "__main__":
    main()
