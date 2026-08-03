"""Draw the underworld, because a metric will not tell you it looks wrong.

    python dev/under_shot.py [seed] [width height]

Writes dev/shots/under_<seed>.png: the whole map with every network on it, and
then one close-up per district for the biggest few.

This exists because rendering worldgen before trusting it has caught two real
bugs in this project already -- the plate distance transform's diamond
starbursts, and the lakes that had flooded a continent -- and neither showed up
in any number anyone was looking at. A cave network is exactly the sort of
thing that can pass every structural assertion in dev/test_underworld.py and
still be visibly a scribble.

  grey      mountain and highland (the rock the network is in)
  dark      the rest of the land
  gold      caverns -- open ground, where a hold can be built
  amber     galleries -- passages
  blue      sunless water
  black     chasms
  red ring  a gate: the only way in
"""
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw

from app.world import layers as L
from app.world import underworld as U
from app.world.worldgen import generate_world

SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 11
W = int(sys.argv[2]) if len(sys.argv) > 3 else 1100
H = int(sys.argv[3]) if len(sys.argv) > 3 else 660

OCEAN_RGB = (16, 26, 44)
LAND_RGB = (34, 40, 34)
ROCK_RGB = (96, 96, 104)
KIND_RGB = {
    L.CAVERN: (232, 190, 90),
    L.GALLERY: (170, 120, 50),
    L.WATER: (70, 130, 200),
    L.CHASM: (10, 10, 14),
}
GATE_RGB = (230, 70, 60)

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots")
os.makedirs(OUT, exist_ok=True)

print(f"generating {W}x{H}, seed {SEED} ...")
t0 = time.perf_counter()
world = generate_world(W, H, seed=SEED, n_factions=8)
print(f"  {time.perf_counter() - t0:.1f}s")
print(f"  {world.under_summary}")


def base_image():
    img = Image.new("RGB", (world.w, world.h), OCEAN_RGB)
    px = img.load()
    for y in range(world.h):
        for x in range(world.w):
            if world.height[y][x] <= 0.0:
                continue
            biome = world.biome_grid[y][x]
            px[x, y] = ROCK_RGB if biome in U.UNDER_BIOMES else LAND_RGB
    return img


img = base_image()
px = img.load()
for (x, y), kind in world.under_kind.items():
    px[x, y] = KIND_RGB.get(kind, (255, 0, 255))
draw = ImageDraw.Draw(img)
for gate in world.gates:
    gx, gy = gate["pos"]
    draw.ellipse([gx - 3, gy - 3, gx + 3, gy + 3], outline=GATE_RGB, width=1)
path = os.path.join(OUT, f"under_{SEED}.png")
img.save(path)
print(f"wrote {path}")

# --- close-ups ----------------------------------------------------------------
# The whole map at one pixel per cell makes a 200-cell network four pixels
# across. The close-ups are what you actually look at.
regions = sorted(L.regions_on(world, L.UNDER), key=lambda r: -len(r.cells))
for n, region in enumerate(regions[:4]):
    x0, y0, x1, y1 = region.bbox
    pad = 25
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(world.w, x1 + pad), min(world.h, y1 + pad)
    crop = img.crop((x0, y0, x1, y1))
    scale = max(1, min(8, 900 // max(1, x1 - x0)))
    crop = crop.resize(((x1 - x0) * scale, (y1 - y0) * scale), Image.NEAREST)
    out = os.path.join(OUT, f"under_{SEED}_{n}.png")
    crop.save(out)
    gates_here = sum(1 for g in world.gates
                     if x0 <= g["pos"][0] < x1 and y0 <= g["pos"][1] < y1)
    print(f"wrote {out}  ({region.name}: {len(region.cells)} cells, "
          f"{gates_here} gate(s), {scale}x)")

# --- what the eye should be checking ------------------------------------------
kinds = {}
for kind in world.under_kind.values():
    kinds[kind] = kinds.get(kind, 0) + 1
land = sum(1 for y in range(world.h) for x in range(world.w)
           if world.height[y][x] > 0.0)
print(f"\n{len(world.under_cells):,} cells ({len(world.under_cells) / land:.2%} of land), "
      f"{kinds}")
print(f"{len(world.gates)} gates over {world.under_summary['districts']} districts")
print("\nlook for: networks that reach out of the grey onto the dark (the skirt),")
print("gates on the flanks rather than the summit, passages that wander without")
print("doubling back, and no network that is one solid blob of cavern.")
