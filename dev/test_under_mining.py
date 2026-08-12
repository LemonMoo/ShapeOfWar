"""The hybrid ore model: the great hall IS the mine; everyone else digs.

    python dev/test_under_mining.py

v0.18.27 hybrid: an under-CAPITAL (the hold's great hall, under_capital=True)
keeps the free mining inheritance -- it stands in the deepest rock and works
it by right of being there. Every OTHER underground node is a mining
settlement like any surface one: no extractive camp, no ore (see
resources._village_terrain_potential's under branch). A Mining Camp must be
buildable underground -- by villages AND by under-towns (a mining town is
the whole reason a settlement exists in a gallery), which is
storage_max_tier's `under` flag and the under-aware land gate in
build_options.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import layers as L
from app.world import construction as C
from app.world import resources as R
from app.world import buildings as B
from app.world.worldgen import generate_world

ORES = ("Iron", "Coal", "Gold Ore", "Stone", "Copper", "Tin", "Gems")

world = generate_world(560, 340, seed=21, n_factions=8)
print("world:", world.under_summary)

home = next(h for h in world.under_homes if h["kind"] == "hold")
idx = home["faction_idx"]
nation = world.factions[idx]
region = world.regions[home["regions"][0]]
occupied = {st.pos for st in world.settlements}
occupied.update(v.pos for v in world.villages)
caverns = [p for p in region.cells
           if L.kind_at(world, p[0], p[1], L.UNDER) == "cavern"
           and p not in occupied]


def ore_potential(node):
    return R._village_terrain_potential(world, node, world.season)[0]


print("\n--- the great hall mines for free; a bare town mines nothing ---")
seat = next(s for s in world.settlements if getattr(s, "under_capital", False))
assert getattr(seat, "under_capital", False)
assert any(ore_potential(seat).get(r, 0) > 0 for r in ORES), (
    "the great hall lost its free inheritance")

def fund():
    for node in list(world.settlements) + list(world.villages):
        if node.faction_idx == idx:
            node.resources = dict(node.resources or {})
            for r in ("Stone", "Food", "Logs", "Iron", "Gold"):
                node.resources[r] = node.resources.get(r, 0) + 20000

fund()
msg = C.start_settlement(world, nation, caverns[-1], "town", layer=L.UNDER)
assert msg.startswith("Construction begins"), msg
from app.world.construction import _finish_settlement
_finish_settlement(world, world.settlement_projects[-1])
town = world.settlements[-1]
assert not any(ore_potential(town).get(r, 0) > 0 for r in ORES), (
    "a town without a camp mines for nothing -- the hybrid gate is off")
print("  ok    seat mines free, bare town mines nothing")

print("\n--- the same camp rules apply to hold steadings (born miners) ---")
steading = next(v for v in world.villages
                if v.faction_idx == idx and L.is_under(world.regions[v.region_id]))
assert R.storage_tier(steading, R.MINING_CAMP) > 0
assert any(ore_potential(steading).get(r, 0) > 0 for r in ORES)
print("  ok    a born-miner steading digs")

print("\n--- an under TOWN can build a Mining Camp through the real path ---")
assert R.storage_max_tier(town, R.MINING_CAMP, under=True) > 0, (
    "an under settlement was denied the extractive camps")
assert R.storage_max_tier(town, R.MINING_CAMP) == 0, (
    "the surface rule leaked: a plain settlement still maxes at zero")
next_t = C.storage_next_tier(world, town, R.MINING_CAMP)
assert next_t == 1, next_t
cost = C.storage_build_cost(town, R.MINING_CAMP, 1, under=True)
assert cost is not None
msg = C.start_storage_building(world, nation, town, R.MINING_CAMP)
assert "Building" in msg or "Upgrading" in msg, msg
R.set_storage_tier(town, R.MINING_CAMP, 1)
assert any(ore_potential(town).get(r, 0) > 0 for r in ORES), (
    "a camp did not unlock the ore")
print("  ok    Mining Camp tier 1 built at the town, ore unlocked")

print("\n--- the build menu offers the camp below, and the land gate agrees ---")
opts = {o.building: o for o in B.build_options(world, town, nation)}
assert R.MINING_CAMP in opts, "no Mining Camp card for an under town"
assert R.GRANGE not in opts, "a Grange (crops) is offered in a gallery"
assert R.has_region_outstation_land(world, town, R.MINING_CAMP), (
    "the under land gate denied a camp under a mountain")
print("  ok    menu + land gate are under-aware")

print("\n--- the depth bonus still multiplies the camps' ore ---")
deep = world.regions[home["regions"][-1]]
tier, bonus = R.under_depth_info(world, deep)
assert tier in ("shallow", "deep", "abyssal") and bonus >= 1.0
print(f"  ok    depth tier {tier} (ore x{bonus:g})")

print("\nUNDER MINING TEST PASSED")
sys.exit(0)
