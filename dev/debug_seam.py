"""Debug the meander seam channel: replicate generate_world's exact meander
math (same rng sequence) and compare against the generated world's heights."""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from app.world import noise
from app.world.worldgen import (generate_world, _periodic_octaves,
                                _pick_n_plates, OCEAN)

SEED = 10
W, H = 560, 340

world = generate_world(W, H, seed=SEED, n_factions=6)
w, h = world.w, world.h
sea = world.sea_level
margin = max(6, round(w * 0.03))
amp = 0.55 * margin
print(f"w={w} h={h} margin={margin} amp={amp:.2f} sea_level={sea:.4f}")
print(f"world.seed={world.seed} gen_params={getattr(world, '_gen_params', None)}")

# Replicate the rng sequence the FINAL (possibly retried) attempt used:
# the retry path passes the new seed through a fresh Random and only draws
# nseed (the _target_n/_n_plates were already fixed by the first attempt).
sp = world._gen_params["seed"]
rng = random.Random(sp)
nseed = rng.randint(0, 2 ** 31 - 1)

meander_octaves = _periodic_octaves(2, [(0.0035, 1.0), (0.007, 0.45)])
meander = noise.fbm_grid(2, h, nseed + 303, meander_octaves)[:, 0]
meander = meander - meander.mean()
meander = meander * (amp / max(1e-9, np.abs(meander).max()))
p = meander
print(f"nseed={nseed} p: min={p.min():.2f} max={p.max():.2f} "
      f"at y=0..5: {[round(v, 2) for v in p[:6]]}")

xs = np.arange(w, dtype=np.float64)
for y in (0, 170, 339):
    seam_d = np.minimum((xs - p[y]) % w, w - (xs - p[y]) % w)
    fade = np.clip((seam_d - amp) / max(1e-9, margin - amp), 0.0, 1.0)
    fade = fade * fade * (3 - 2 * fade)
    print(f"\ny={y} p={p[y]:.2f}:")
    for x in range(0, 6):
        hgt = world.height[y][x]
        is_lake = (x, y) in world.lake_cells
        is_river = (x, y) in world.river_cells
        print(f"  x={x} seam_d={seam_d[x]:.1f} fade={fade[x]:.2f} "
              f"h={hgt:.4f} land={hgt > sea} owner={world.owner[y][x]} "
              f"lake={is_lake} river={is_river}")

# Ground truth from the world itself: any land within 3 cells of the seam?
land = [[world.height[y][x] > sea for x in range(w)] for y in range(h)]
close = sum(1 for y in range(h)
            if any(land[y][x] for x in range(3))
            or any(land[y][w - 1 - x] for x in range(3)))
# Trench line: circular midpoint of the row's minimum-height arc in the band.
import statistics
band = int(1.55 * margin)
trench = []
for y in range(h):
    band_xs = list(range(0, band + 1)) + list(range(w - 1 - band, w))
    mn = min(world.height[y][x] for x in band_xs)
    flat = [x for x in band_xs if world.height[y][x] <= mn + 1e-9]
    sx = sum(math.sin(2 * math.pi * x / w) for x in flat) / len(flat)
    sy = sum(math.cos(2 * math.pi * x / w) for x in flat) / len(flat)
    mid = (math.atan2(sx, sy) % (2 * math.pi)) / (2 * math.pi) * w
    trench.append(mid if mid <= w / 2 else mid - w)
print(f"\nrows with land within 3 cells of either seam edge: {close}/{h}")
print(f"trench position: min={min(trench):.1f} max={max(trench):.1f} "
      f"std={statistics.pstdev(trench):.1f}")
print(f"real p         : min={p.min():.1f} max={p.max():.1f} "
      f"std={statistics.pstdev(p.tolist()):.1f}")
