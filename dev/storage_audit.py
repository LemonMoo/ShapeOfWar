"""Storage audit: where goods pile up, what destroys them, and what the
throttle is actually suppressing.

    python dev/storage_audit.py [world.pkl] [turns]
    python dev/storage_audit.py --fresh [seed] [turns]

Instruments the real turn loop (no simulation of its own):

  * per-pool fill distribution across every storage-owning node, and the
    fraction of node-turns spent at/over capacity
  * goods destroyed per turn, split into ORDINARY spoilage (a resource's own
    spoil_rate) vs OVERFLOW decay (the over-capacity penalty on top), by
    resource and by pool
  * production suppressed by storage_throttle -- output that was never
    produced because the pool was already full, which is invisible in any
    stock-level metric
  * what actually occupies each pool, by space
"""
import sys
import os
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import resources as R


def all_nodes(world):
    return [("settlement", s) for s in world.settlements] + \
           [("village", v) for v in world.villages]


class Audit:
    def __init__(self):
        self.spoil = defaultdict(float)      # resource -> units lost to spoil_rate
        self.overflow = defaultdict(float)   # resource -> units lost to overflow
        self.throttled = defaultdict(float)  # pool -> units of output suppressed
        self.produced = defaultdict(float)   # pool -> units actually delivered
        self.fill_samples = defaultdict(list)   # pool -> [fill fraction]
        self.over_cap = defaultdict(int)
        self.samples = defaultdict(int)

    def install(self, world):
        orig_spoil = R._apply_settlement_spoilage_and_overflow
        orig_route = R._route_farm_production

        def wrapped_spoil(node):
            res = getattr(node, "resources", None)
            before = dict(res) if res else {}
            # Split the two effects by running the base spoil arithmetic here.
            orig_spoil(node)
            if not res:
                return
            for r, b in before.items():
                after = res.get(r, 0)
                lost = b - after
                if lost <= 0:
                    continue
                rate = R.RESOURCES.get(r, {}).get("spoil_rate", 0.0)
                base_loss = b - int(b * (1 - rate))
                self.spoil[r] += min(lost, base_loss)
                if lost > base_loss:
                    self.overflow[r] += lost - base_loss

        def _account(resource_amounts, delivered):
            wanted = defaultdict(float)
            for r, amt in (resource_amounts or {}).items():
                wanted[R.storage_class(r)] += amt
            got = defaultdict(float)
            for r, amt in (delivered or {}).items():
                got[R.storage_class(r)] += amt
            for pool, amt in wanted.items():
                self.produced[pool] += got.get(pool, 0.0)
                self.throttled[pool] += max(0.0, amt - got.get(pool, 0.0))

        def wrapped_route(world_, region, resource_amounts, throttle=True):
            delivered = orig_route(world_, region, resource_amounts, throttle)
            _account(resource_amounts, delivered)
            return delivered

        orig_deliver = R._deliver_village_yield

        def wrapped_deliver(village, resource_amounts, throttle=True):
            delivered = orig_deliver(village, resource_amounts, throttle)
            _account(resource_amounts, delivered)
            return delivered

        R._apply_settlement_spoilage_and_overflow = wrapped_spoil
        R._route_farm_production = wrapped_route
        R._deliver_village_yield = wrapped_deliver
        self._orig = (orig_spoil, orig_route, orig_deliver)

    def uninstall(self):
        (R._apply_settlement_spoilage_and_overflow, R._route_farm_production,
         R._deliver_village_yield) = self._orig

    def sample_fill(self, world):
        for _kind, node in all_nodes(world):
            for pool in R.STORAGE_POOLS:
                cap = R.node_pool_capacity(node, pool)
                if not cap:
                    continue
                fill = R.node_pool_stock(node, pool) / cap
                self.fill_samples[pool].append(fill)
                self.samples[pool] += 1
                if fill >= 1.0:
                    self.over_cap[pool] += 1


def pct(n, d):
    return f"{100.0 * n / d:5.1f}%" if d else "    -"


def report(world, a, turns):
    print(f"\n=== storage audit: {turns} turns, {len(world.settlements)} settlements, "
          f"{len(world.villages)} villages ===\n")

    print("POOL FILL (fraction of capacity, sampled every turn at end of turn)")
    print(f"{'pool':>10} {'mean':>7} {'median':>7} {'p90':>7} {'>=cap':>8} {'samples':>9}")
    for pool in R.STORAGE_POOLS:
        s = sorted(a.fill_samples[pool])
        if not s:
            continue
        mean = sum(s) / len(s)
        med = s[len(s) // 2]
        p90 = s[int(len(s) * 0.9)]
        print(f"{pool:>10} {mean:7.2f} {med:7.2f} {p90:7.2f} "
              f"{pct(a.over_cap[pool], a.samples[pool]):>8} {a.samples[pool]:>9}")

    print("\nDESTROYED (units, whole run)")
    spoil_by_pool = defaultdict(float)
    over_by_pool = defaultdict(float)
    for r, v in a.spoil.items():
        spoil_by_pool[R.storage_class(r)] += v
    for r, v in a.overflow.items():
        over_by_pool[R.storage_class(r)] += v
    print(f"{'pool':>10} {'spoilage':>12} {'overflow':>12} {'total':>12}")
    for pool in R.STORAGE_POOLS:
        sp, ov = spoil_by_pool[pool], over_by_pool[pool]
        print(f"{pool:>10} {sp:12,.0f} {ov:12,.0f} {sp + ov:12,.0f}")
    print(f"{'ALL':>10} {sum(a.spoil.values()):12,.0f} {sum(a.overflow.values()):12,.0f} "
          f"{sum(a.spoil.values()) + sum(a.overflow.values()):12,.0f}")

    print("\nTOP DESTROYED RESOURCES")
    tot = defaultdict(float)
    for r, v in a.spoil.items():
        tot[r] += v
    for r, v in a.overflow.items():
        tot[r] += v
    for r, v in sorted(tot.items(), key=lambda kv: -kv[1])[:15]:
        print(f"  {r:<16} {v:10,.0f}   (spoil {a.spoil[r]:9,.0f}  overflow {a.overflow[r]:9,.0f})")

    print("\nPRIMARY PRODUCTION SUPPRESSED BY THROTTLE (units, whole run)")
    print(f"{'pool':>10} {'delivered':>12} {'suppressed':>12} {'lost %':>8}")
    for pool in R.STORAGE_POOLS:
        d, t = a.produced[pool], a.throttled[pool]
        if d or t:
            print(f"{pool:>10} {d:12,.0f} {t:12,.0f} {pct(t, d + t):>8}")

    print("\nWHAT OCCUPIES EACH POOL NOW (space, all nodes)")
    space = defaultdict(lambda: defaultdict(float))
    for _k, node in all_nodes(world):
        for r, v in getattr(node, "resources", {}).items():
            if v > 0:
                space[R.storage_class(r)][r] += v * R.resource_bulk(r)
    for pool in R.STORAGE_POOLS:
        items = sorted(space[pool].items(), key=lambda kv: -kv[1])
        total = sum(space[pool].values())
        cap = sum(R.node_pool_capacity(n, pool) for _k, n in all_nodes(world))
        print(f"  {pool}: {total:,.0f} space used / {cap:,.0f} capacity "
              f"({pct(total, cap)} full)")
        for r, v in items[:8]:
            print(f"      {r:<16} {v:10,.0f}  {pct(v, total)}")


def main():
    args = sys.argv[1:]
    if args and args[0] == "--fresh":
        from app.world.worldgen import generate_world
        seed = int(args[1]) if len(args) > 1 else 42
        turns = int(args[2]) if len(args) > 2 else 80
        print(f"generating fresh world seed={seed} ...")
        world = generate_world(seed=seed, n_factions=10)
    else:
        path = args[0] if args else os.path.join(os.path.dirname(__file__), "worlds", "dev560.pkl")
        turns = int(args[1]) if len(args) > 1 else 60
        import pickle
        print(f"loading {path} ...")
        world = pickle.load(open(path, "rb"))

    a = Audit()
    a.install(world)
    try:
        for t in range(turns):
            R.advance_turn(world)
            a.sample_fill(world)
            if (t + 1) % 20 == 0:
                print(f"  ... turn {t + 1}/{turns}")
    finally:
        a.uninstall()
    report(world, a, turns)


if __name__ == "__main__":
    main()
