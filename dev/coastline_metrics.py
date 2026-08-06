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

Seam metrics (added for the meandering wrap channel, see worldgen's meander
block): the % of the two seam columns that is ocean (must stay 100), the
min/mean/max per-row distance from the seam to the nearest land (a straight
band pins it at seam_margin; a meander swings it between margin-amp and
margin+amp), and the seam coastline wiggle (0 = ruler-straight coast parallel
to the seam). Also checks same-seed determinism (heights identical twice).

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


def seam_metrics(world):
    """Seam-shape metrics -- the wrap channel's elegance, as numbers.

    The east-west seam (x=0/width-1) is a meandering deep-ocean channel, not
    a straight cut (see generate_world's meander block), so these quantify
    what the old straight band had by construction:

      seam_ocean_pct  % of the two seam columns that are ocean -- the "land
                      never straddles the seam" guarantee (must stay 100).
      seam_gap_*      per-row distance from the seam to the nearest land,
                      min/mean/max over rows. A straight band pins this at
                      seam_margin everywhere; a meander swings it between
                      margin-amp and margin+amp (the strait narrows and
                      widens along its length).
      trench_wander   per-row position of the deepest cell within the seam
                      band, std across rows -- 0 when the deep line is a
                      ruler-straight column at the seam, >0 when the channel
                      meanders. The single number that proves the meander.
      seam_wiggle     within the seam band, the fraction of coast edges that
                      run east-west (pointing north/south) rather than
                      north-south (pointing east/west). 0 = ruler-straight
                      coastline parallel to the seam; higher = wiggly,
                      natural coastline.
    """
    w, h = world.w, world.h
    sea = world.sea_level
    land = [[world.height[y][x] > sea for x in range(w)] for y in range(h)]
    margin = max(6, round(w * 0.03))
    band = int(1.55 * margin)             # margin + amp, the channel's reach

    seam_cells = ocean = 0
    for edge in (0, w - 1):
        for y in range(h):
            seam_cells += 1
            if not land[y][edge]:
                ocean += 1

    gaps = []
    for y in range(h):
        row = land[y]
        xr = next((x for x in range(w) if row[x]), None)
        if xr is None:
            continue                      # all-ocean row; gap is a full width
        xl = next((x for x in range(w - 1, -1, -1) if row[x]), None)
        gaps.append(min(xr, w - 1 - xl))

    # The channel's deepest line: per row, the flat floor is a contiguous arc
    # around the centreline (the fade's zero-zone), so every cell in it ties
    # for the row minimum. Take the circular midpoint of that arc -- that's
    # the centreline position, which the meander moves around. std across
    # rows = 0 for the old straight band, >0 for a meander; the depth std
    # shows the pools/sills along the channel.
    trench_x = []
    trench_depth = []
    for y in range(h):
        band_xs = list(range(0, band + 1)) + list(range(w - 1 - band, w))
        mn = min(world.height[y][x] for x in band_xs)
        flat = [x for x in band_xs if world.height[y][x] <= mn + 1e-9]
        sx = sum(math.sin(2 * math.pi * x / w) for x in flat) / len(flat)
        sy = sum(math.cos(2 * math.pi * x / w) for x in flat) / len(flat)
        mid = (math.atan2(sx, sy) % (2 * math.pi)) / (2 * math.pi) * w
        # Signed offset from the seam (like the centreline p itself) so the
        # std/min/max are linear -- a wrapped x near 0/w would inflate them.
        trench_x.append(mid if mid <= w / 2 else mid - w)
        trench_depth.append(mn)

    horiz = vert = 0
    for y in range(h):
        row = land[y]
        for x in range(w):
            if not row[x] or (x > band and x < w - 1 - band):
                continue                  # not a coast in the seam band
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = (x + dx) % w, y + dy
                if not (0 <= ny < h) or not land[ny][nx]:
                    if dy:
                        horiz += 1        # coast runs along x -> wiggle
                    else:
                        vert += 1
    wiggle = horiz / max(1, horiz + vert)
    return {
        "seam_ocean_pct": 100.0 * ocean / max(1, seam_cells),
        "seam_gap_min": min(gaps) if gaps else w,
        "seam_gap_mean": (sum(gaps) / len(gaps)) if gaps else w,
        "seam_gap_max": max(gaps) if gaps else w,
        "trench_wander": _std(trench_x),
        "trench_depth_std": _std(trench_depth),
        "seam_wiggle": wiggle,
    }


def _std(xs):
    if not xs:
        return 0.0
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def deterministic(seed):
    """Same seed twice must reproduce the same terrain -- the meander is
    seeded from the same rng chain as everything else (nseed+303/+404), so
    heights and sea level must match exactly."""
    w1 = generate_world(560, 340, seed=seed, n_factions=6)
    w2 = generate_world(560, 340, seed=seed, n_factions=6)
    return w1.height == w2.height and w1.sea_level == w2.sea_level


def main():
    seeds = [int(a) for a in sys.argv[1:]] or [1, 2, 3]
    os.makedirs(SHOTS_DIR, exist_ok=True)
    d0 = time.perf_counter()
    det = deterministic(seeds[0])
    print(f"determinism (seed {seeds[0]}, 560x340, twice): "
          + ("OK -- identical heights" if det else "FAILED -- worlds differ"))
    if not det:
        print("SEAM METRICS FAILED")
        sys.exit(1)
    print(f"  ({time.perf_counter() - d0:.1f}s)")

    print(f"{'seed':>6} {'landmasses':>10} {'land%':>7} {'coast':>7} "
          f"{'irregularity':>12} {'mean_width':>10} {'gen s':>6}")
    for seed in seeds:
        t0 = time.perf_counter()
        world = generate_world(seed=seed, n_factions=8)
        gen_s = time.perf_counter() - t0
        m = metrics(world)
        s = seam_metrics(world)
        print(f"{seed:>6} {m['landmasses']:>10} {m['land_pct']:>6.1f}% "
              f"{m['coast_cells']:>7} {m['irregularity']:>12.3f} "
              f"{m['mean_width']:>10.2f} {gen_s:>6.1f}")
        print(f"       seam ocean {s['seam_ocean_pct']:>5.1f}% | "
              f"land gap min/mean/max "
              f"{s['seam_gap_min']:.1f}/{s['seam_gap_mean']:.1f}/"
              f"{s['seam_gap_max']:.1f} | trench wander "
              f"{s['trench_wander']:.1f} (depth {s['trench_depth_std']:.4f}) | "
              f"wiggle {s['seam_wiggle']:.3f}")
        path = os.path.join(SHOTS_DIR, f"coastline_seed{seed}.png")
        render_world(world, size=(world.w, world.h), hide_rivals=False).save(path)
        print(f"         -> {path}")


if __name__ == "__main__":
    main()
