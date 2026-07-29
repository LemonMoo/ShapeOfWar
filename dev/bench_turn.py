"""End-turn benchmark, with an optional correctness check.

    python dev/bench_turn.py                    # time 10 turns
    python dev/bench_turn.py --turns 20
    python dev/bench_turn.py --profile          # where the time actually goes
    python dev/bench_turn.py --fingerprint      # hash the world state

The fingerprint is the important one. Any optimisation that is supposed to be
behaviour-preserving must produce the SAME fingerprint before and after -- that
is how the 2.8x end-turn work was validated, and it is the only way to be sure a
cache has not quietly changed the economy. Run it, make the change, run it
again, compare the hash.

Baselines on dev/worlds/dev560.pkl (turn 561, 300 owned regions, 651 nodes):
    before optimisation   1199 ms/turn
    after                  424 ms/turn
The remaining hotspot is node_pool_stock, which needs a per-turn cache of
MUTABLE state -- deliberately not done, since a missed invalidation would show
up as economy drift fifty turns later.
"""
import argparse
import hashlib
import os
import pickle
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import resources as R, commander as C

WORLD = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "worlds", "dev560.pkl")


def load():
    random.seed(4242)          # the AI makes random choices; pin them
    with open(WORLD, "rb") as fh:
        world = pickle.load(fh)
    C.ensure_faction_commanders(world)
    return world


def fingerprint(world):
    """Everything an economy optimisation could plausibly disturb."""
    h = hashlib.sha256()
    for r in world.regions:
        h.update(f"{r.id}:{r.faction_idx}:{r.wildland_strength}|".encode())
    for node in list(world.settlements) + list(world.villages):
        res = "".join(f"{k}={v:.4f},"
                      for k, v in sorted((getattr(node, "resources", {}) or {}).items()))
        h.update(f"{getattr(node, 'name', '')}:"
                 f"{getattr(node, 'population', 0):.4f}:{res}|".encode())
    for f in world.factions:
        h.update(f"{f.name}:{sorted(f.stats.items())}|".encode())
    return h.hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns", type=int, default=10)
    ap.add_argument("--profile", action="store_true")
    ap.add_argument("--fingerprint", action="store_true")
    args = ap.parse_args()

    world = load()
    owned = sum(1 for r in world.regions if r.faction_idx >= 0)
    print(f"turn {getattr(world, 'turn', '?')}, {owned} owned regions, "
          f"{len(world.settlements) + len(world.villages)} nodes, "
          f"{len(world.factions)} factions")

    if args.profile:
        import cProfile, pstats, io
        for _ in range(2):
            R.advance_turn(world)          # warm caches first
        pr = cProfile.Profile()
        pr.enable()
        for _ in range(3):
            R.advance_turn(world)
        pr.disable()
        s = io.StringIO()
        pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(15)
        print(s.getvalue())
        return

    t0 = time.perf_counter()
    for _ in range(args.turns):
        R.advance_turn(world)
    ms = (time.perf_counter() - t0) / args.turns * 1000
    print(f"{ms:.0f} ms/turn over {args.turns} turns")
    if args.fingerprint:
        print(f"fingerprint: {fingerprint(world)}")


if __name__ == "__main__":
    main()
