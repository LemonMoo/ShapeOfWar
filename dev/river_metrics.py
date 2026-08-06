"""River health: straight runs AND how many rivers reach the sea/lake."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world.worldgen import generate_world, OCEAN

MIN_RUN = 4


def river_health(world):
    runs = max_run = run_cells = 0
    total = 0
    reached = 0
    for rv in world.rivers:
        cells = rv["cells"]
        total += len(cells)
        # does it reach the sea or a lake?
        end = cells[-1]
        x, y = end
        if (world.owner[y][x] == OCEAN or end in world.lake_cells
                or (x, y) not in world.river_cells):
            reached += 1
        run = 1
        prev = None
        for a, b in zip(cells, cells[1:]):
            step = (b[0] - a[0], b[1] - a[1])
            if step == prev:
                run += 1
            else:
                if run >= MIN_RUN:
                    runs += 1
                    run_cells += run
                    max_run = max(max_run, run)
                run = 1
            prev = step
        if run >= MIN_RUN:
            runs += 1
            run_cells += run
            max_run = max(max_run, run)
    return runs, max_run, run_cells, total, reached


for seed in (1, 11, 17):
    world = generate_world(1100, 660, seed=seed, n_factions=8)
    runs, mx, run_cells, total, reached = river_health(world)
    pct = 100.0 * run_cells / max(1, total)
    print(f"seed {seed:>3}: rivers={len(world.rivers)} cells={total} "
          f"runs(>={MIN_RUN})={runs} longest={mx} run%={pct:.1f} "
          f"reach sea/lake: {reached}/{len(world.rivers)}")
