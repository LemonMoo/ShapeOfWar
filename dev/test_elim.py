"""Conquer a whole faction region-by-region and verify elimination bookkeeping."""
import sys, pickle
sys.path.insert(0, r"D:\Claude Project")
from app.core.events import bus
from app.world.territory import transfer_region
from app.world.nation import is_eliminated, active_factions
from app.world.resources import advance_turn
from app.world import trade

with open(sys.argv[1], "rb") as f:
    w = pickle.load(f)

events = []
bus.on("faction:eliminated", lambda p: events.append(p))

# Pick the faction with the FEWEST regions (quickest to wipe out) that isn't
# the player, and give everything to its biggest neighbour.
sizes = {i: len(f.meta.get("regions", [])) for i, f in enumerate(w.factions)}
victim = min((i for i in sizes if sizes[i] > 0 and i != w.player_faction_idx),
             key=lambda i: sizes[i])
conq = max(sizes, key=lambda i: sizes[i])
print(f"victim idx={victim} '{w.factions[victim].name}' regions={sizes[victim]}")
print(f"conqueror idx={conq} '{w.factions[conq].name}' regions={sizes[conq]}")

# Give the victim some assets so the transfer/removal paths are exercised.
from app.world.commander import Commander, Ship
w.commanders.append(Commander(9001, victim, (5, 5)))
w.ships.append(Ship(9002, victim, (6, 6)))
from app.world.construction import RoadProject
w.road_projects.append(RoadProject(victim, [(1, 1), (2, 2)]))
w.trade_routes.append({"kind": "land", "cells": [(1, 1), (2, 2)],
                       "a_faction": victim, "b_faction": conq})
w.trade_routes.append({"kind": "land", "cells": [(3, 3), (4, 4)],
                       "a_faction": victim, "b_faction": w.player_faction_idx})
w.trade_routes_by_pair = {frozenset((r["a_faction"], r["b_faction"])): r
                          for r in w.trade_routes}
before_routes = len(w.trade_routes)
print(f"seeded: 1 commander, 1 ship, 1 road project, 2 trade routes "
      f"(total routes now {before_routes})")

victim_regions = list(w.factions[victim].meta.get("regions", []))
for n, cid in enumerate(victim_regions, 1):
    transfer_region(w, w.regions[cid], conq)
    if is_eliminated(w.factions[victim]):
        print(f"  -> eliminated after taking region {n}/{len(victim_regions)}")
        break

print("\n--- assertions ---")
v = w.factions[victim]
assert is_eliminated(v), "victim not flagged eliminated"
print("eliminated flag        :", v.eliminated, "by", v.eliminated_by, "turn", v.eliminated_turn)
assert v.eliminated_by == conq
assert len(events) == 1, f"expected 1 event, got {len(events)}"
print("bus event fired        : yes")
assert not any(c.faction_idx == victim for c in w.commanders), "commander survived"
print("commanders removed     : ok")
assert not any(s.faction_idx == victim for s in w.ships), "ship survived"
print("ships removed          : ok")
assert not any(victim in (c.seller_idx, c.buyer_idx) for c in w.trade_caravans)
print("caravans removed       : ok")
assert all(p.faction_idx != victim for p in w.road_projects), "road project not transferred"
print("road projects moved    : ok ->", w.road_projects[-1].faction_idx)
assert all(victim not in (r["a_faction"], r["b_faction"]) for r in w.trade_routes)
print("routes repointed       : ok")
self_loops = [r for r in w.trade_routes if r["a_faction"] == r["b_faction"]]
assert not self_loops, f"self-looping routes left: {len(self_loops)}"
print("self-loop routes dropped: ok (routes", before_routes, "->", len(w.trade_routes), ")")
for k, r in w.trade_routes_by_pair.items():
    assert k == frozenset((r["a_faction"], r["b_faction"])), "stale pair key"
print("routes_by_pair rebuilt : ok")
assert not any(i == victim for i, _ in active_factions(w))
print("excluded from active   : ok", f"({len(active_factions(w))}/{len(w.factions)} alive)")
assert not trade.eligible_to_trade(w, victim, conq)
print("trade gate closed      : ok")
assert v.meta.get("regions") == [], f"still owns regions: {v.meta.get('regions')}"
print("owns no regions        : ok")
assert not any(r.faction_idx == victim for r in w.regions)
assert not any(vi.faction_idx == victim for vi in w.villages)
assert not any(s.faction_idx == victim for s in w.settlements)
print("no entities reference it: ok")

print("\n--- 5 turns post-elimination (crash check) ---")
for i in range(5):
    advance_turn(w)
print("advance_turn survived; still eliminated:", is_eliminated(w.factions[victim]))
assert is_eliminated(w.factions[victim]), "resurrected!"
assert not any(victim in (c.seller_idx, c.buyer_idx) for c in w.trade_caravans), \
    "dead faction got a new caravan"
print("no new caravans for the dead: ok")
print("\nALL CHECKS PASSED")
