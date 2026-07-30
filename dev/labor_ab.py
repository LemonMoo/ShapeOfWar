"""A/B the Phase 14 labor limit by disabling it, not by comparing against a
remembered baseline (HANDOFF.md section 6).

"Off" is the identical code path with LABOR_OUTPUT_PER_WORKER raised so high
that a workforce can always cover its terrain's whole offer -- so labor never
binds and every village produces exactly what it produced before Phase 14.
That isolates the labor limit itself from every other difference between two
runs.

    python dev/labor_ab.py [seed] [turns]
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import resources as R
from app.world.worldgen import generate_world


def snapshot(world):
    nodes = list(world.settlements) + list(world.villages)
    stock = {}
    for n in nodes:
        for r, v in getattr(n, "resources", {}).items():
            if v > 0:
                stock[r] = stock.get(r, 0) + v
    return {
        "pop": sum(n.population for n in nodes),
        "settlements": len(world.settlements),
        "villages": len(world.villages),
        "starving": sum(1 for n in nodes if getattr(n, "turns_without_food", 0) > 0),
        "freezing": sum(1 for n in nodes if getattr(n, "turns_without_firewood", 0) > 0),
        "stock": sum(stock.values()),
        "gold": sum(R.faction_gold(world, i) for i in range(len(world.factions))),
        "prosperity": round(sum(getattr(n, "prosperity", 0) for n in nodes) / max(1, len(nodes)), 1),
    }


def run(seed, turns, labor_on):
    original = dict(R.LABOR_OUTPUT_PER_WORKER)
    if not labor_on:
        # Mutate in place, never rebind -- app/core/tuning.py's own rule, and
        # the reason this works at all (unit.py-style `from ... import X`
        # bindings all point at this same dict).
        R.LABOR_OUTPUT_PER_WORKER.update({k: 1e9 for k in original})
    try:
        world = generate_world(seed=seed, n_factions=10)
        marks = {}
        for t in range(1, turns + 1):
            R.advance_turn(world)
            if t in (25, 50, 100, turns):
                marks[t] = snapshot(world)
        return marks
    finally:
        R.LABOR_OUTPUT_PER_WORKER.update(original)


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 42
    turns = int(sys.argv[2]) if len(sys.argv) > 2 else 120
    print(f"seed={seed} turns={turns}\n")
    print("running labor OFF ...")
    off = run(seed, turns, False)
    print("running labor ON ...")
    on = run(seed, turns, True)

    keys = ["pop", "villages", "settlements", "starving", "freezing",
            "stock", "gold", "prosperity"]
    for t in sorted(on):
        print(f"\n--- turn {t} ---")
        print(f"{'':>13} {'OFF':>12} {'ON':>12} {'delta':>12}")
        for k in keys:
            a, b = off[t][k], on[t][k]
            d = b - a
            print(f"{k:>13} {a:12,.0f} {b:12,.0f} {d:+12,.0f}")


if __name__ == "__main__":
    main()
