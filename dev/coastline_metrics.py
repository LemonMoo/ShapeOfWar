"""Coastline shape metrics -- turns "looks spongy" into a number.

    python dev/coastline_metrics.py [seed ...]

For each seed, generates a world and reports:

  landmasses     count of connected land components with >=0.5% of total land
                 (matches _has_multiple_landmasses' own "substantial" bar)
  land%          fraction of the map that is land
  coast cells    land cells with at least one ocean/lake neighbour
  irregularity   coastline length / sqrt(land area), 4-connected boundary count
                 over sqrt(cell count). A circle scores ~3.5; a real coastline
                 with bays, peninsulas and fjords scores much higher. This is
                 the single number that "sponge -> natural" should move.
  mean width     land area / coastline length, in cells -- a rough "how thick
                 is this landmass on average". Low + high irregularity together
                 is the fjord/peninsula look; high + low irregularity is the
                 sponge (blobby, but with a smooth thresholded edge).

Also writes dev/shots/coastline_seed<N>.png -- a full-resolution political
thumbnail via app.ui.world_preview.render_world, the same renderer the New Game
screen uses. Read the PNG; a metric is a proxy, the picture is the point.
"""
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world.worldgen import generate_world, OCEAN
from app.ui.world_preview import render_world

SHOTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots")


def _connected_components(land, w, h):
    seen = [[False] * w for _ in range(h)]
    sizes = []
    for y0 in range(h):
        for x0 in range(w):
            if not land[y0][x0] or seen[y0][x0]:
                continue
            stack = [(x0, y0)]
            seen[y0][x0] = True
            n = 0
            while stack:
                x, y = stack.pop()
                n += 1
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = (x + dx) % w, y + dy
                    if 0 <= ny < h and land[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True
                        stack.append((nx, ny))
            sizes.append(n)
    return sizes


def metrics(world):
    w, h = world.w, world.h
    sea = world.sea_level
    land = [[world.height[y][x] > sea for x in range(w)] for y in range(h)]
    total_land = sum(sum(row) for row in land)
    sizes = _connected_components(land, w, h)
    substantial = [s for s in sizes if s >= 0.005 * max(1, total_land)]

    coast_len = 0
    coast_cells = 0
    for y in range(h):
        row = land[y]
        for x in range(w):
            if not row[x]:
                continue
            edges = 0
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = (x + dx) % w, y + dy
                if not (0 <= ny < h) or not land[ny][nx]:
                    edges += 1
            if edges:
                coast_cells += 1
                coast_len += edges
    irregularity = coast_len / math.sqrt(max(1, total_land))
    mean_width = total_land / max(1, coast_len)
    return {
        "landmasses": len(substantial),
        "land_pct": 100.0 * total_land / (w * h),
        "coast_cells": coast_cells,
        "irregularity": irregularity,
        "mean_width": mean_width,
    }


def main():
    seeds = [int(a) for a in sys.argv[1:]] or [1, 2, 3]
    os.makedirs(SHOTS_DIR, exist_ok=True)
    print(f"{'seed':>6} {'landmasses':>10} {'land%':>7} {'coast':>7} "
          f"{'irregularity':>12} {'mean_width':>10} {'gen s':>6}")
    for seed in seeds:
        t0 = time.perf_counter()
        world = generate_world(seed=seed, n_factions=8)
        gen_s = time.perf_counter() - t0
        m = metrics(world)
        print(f"{seed:>6} {m['landmasses']:>10} {m['land_pct']:>6.1f}% "
              f"{m['coast_cells']:>7} {m['irregularity']:>12.3f} "
              f"{m['mean_width']:>10.2f} {gen_s:>6.1f}")
        path = os.path.join(SHOTS_DIR, f"coastline_seed{seed}.png")
        render_world(world, size=(world.w, world.h), hide_rivals=False).save(path)
        print(f"         -> {path}")


if __name__ == "__main__":
    main()
