"""Regenerate the dev worlds used by the test battery.

    python dev/make_dev_world.py [--turns N] [--seed S]

Generates a world with the CURRENT worldgen (so a change to region sizing or
placement is picked up), assigns faction 0 as the player, advances it `turns`
days, and saves dev/worlds/dev160.pkl and dev/worlds/dev560.pkl (the two
worlds the tests read). The dev worlds are gitignored, like the baselines
that sit next to them.

Run it AFTER changing worldgen, and before the world-dependent test battery.
"""
import argparse
import os
import pickle
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import resources
from app.world.worldgen import generate_world

OUT = "dev/worlds"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns", type=int, default=560)
    ap.add_argument("--seed", type=int, default=4242)
    args = ap.parse_args()

    t0 = time.perf_counter()
    world = generate_world(width=1100, height=660, seed=args.seed,
                           n_factions=14, player_species=None,
                           player_name=None, player_color=None,
                           player_ruler=None, player_start=None)
    world.player_faction_idx = 0      # the tests act as faction 0's player
    print(f"worldgen: {time.perf_counter() - t0:.1f}s  "
          f"{len(world.regions)} regions, {len(world.settlements)} settlements, "
          f"{len(world.villages)} villages, {len(world.factions)} factions")

    t0 = time.perf_counter()
    for _ in range(args.turns):
        resources.advance_turn(world)
    print(f"advanced {args.turns} turns in {time.perf_counter() - t0:.1f}s")

    path = f"{OUT}/dev{args.turns}.pkl"
    with open(path, "wb") as fh:
        pickle.dump(world, fh)
    print(f"wrote {path} (turn {world.turn})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
