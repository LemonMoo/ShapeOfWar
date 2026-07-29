"""One-off: dump economy trend stats across N turns, for before/after
comparison around the per-village production rewrite. Not part of the
regression suite -- throwaway verification script.

    python dev/econ_trend.py [seed] [turns]
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world.worldgen import generate_world
from app.world import resources


def total_population(world):
    return (sum(s.population for s in world.settlements)
            + sum(v.population for v in world.villages))


def total_stock_value(world):
    total = 0
    for node in list(world.settlements) + list(world.villages):
        res = getattr(node, "resources", {})
        total += sum(res.values())
    for nation in world.factions:
        total += sum(nation.stats.get("resources", {}).values())
    return total


def starving_count(world):
    return sum(1 for node in list(world.settlements) + list(world.villages)
              if getattr(node, "turns_without_food", 0) > 0)


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 42
    turns = int(sys.argv[2]) if len(sys.argv) > 2 else 150
    w = generate_world(seed=seed, n_factions=10)
    checkpoints = sorted(set([0, 10, 25, 50, 75, 100, 125, turns]))
    print(f"seed={seed} turns={turns}")
    print(f"{'turn':>5} {'population':>11} {'stock':>10} {'starving':>9} "
          f"{'settlements':>11} {'villages':>9}")
    idx = 0
    for t in range(turns + 1):
        if t in checkpoints:
            print(f"{t:>5} {total_population(w):>11} {total_stock_value(w):>10} "
                  f"{starving_count(w):>9} {len(w.settlements):>11} {len(w.villages):>9}")
        if t < turns:
            resources.advance_turn(w)


if __name__ == "__main__":
    main()
