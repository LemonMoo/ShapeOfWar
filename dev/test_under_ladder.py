"""The settlement ladder works in the galleries, and presents as halls.

    python dev/test_under_ladder.py

Mechanically an under-settlement IS a city/town/village -- same
found/raise/upgrade projects, same capacity, same tax and storage -- so the
whole ladder must work on the under layer (start_found_village /
start_raise_village / start_settlement_upgrade / start_settlement with
layer=layers.UNDER). It must also PRESENT as halls, not towns: node_kind_name
reads "Great Hall"/"Carven Hall"/"Hall-stead" for a dwarf realm, while the
surface gate town stays a Town. And a born under-village is a mining
village: farm output is zero (no sun), but it starts with the tier-1 Mining
Camp its rock supports.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import layers as L
from app.world import construction as C
from app.world import resources as R
from app.world import holds as H
from app.world.worldgen import generate_world

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
assert caverns, "the hold's home region has no free cavern cells to build on"
cell = caverns[-1]


def fund():
    """Give the realm bottomless coffers -- the test is about WHERE things
    land, not whether the nation can pay."""
    for node in list(world.settlements) + list(world.villages):
        if node.faction_idx == idx:
            node.resources = dict(node.resources or {})
            for r in ("Stone", "Food", "Logs", "Iron", "Gold"):
                node.resources[r] = node.resources.get(r, 0) + 20000


print("\n--- rung 1: found a village in a gallery ---")
msg = C.start_found_village(world, nation, cell, layer=L.UNDER)
assert msg == "", msg
from app.world.construction import _finish_found_village
v = _finish_found_village(world, world.found_village_projects[-1])
assert v.farm_output == 0, "a gallery has no farmland"
assert R.storage_tier(v, R.MINING_CAMP) > 0, "a born miner has no mine"
assert R.storage_tier(v, R.GRANGE) == 0, "no crop Grange below ground"
assert v.id in region.villages
assert H.node_kind_name(world, v) == "Hall-stead", H.node_kind_name(world, v)
print(f"  ok    {v.name} is a Hall-stead: farm 0, born with a mine")

print("\n--- rung 2: raise it to a Carven Hall ---")
fund()
v.population = v.max_population
msg = C.start_raise_village(world, nation, v)
assert msg == "", msg
from app.world.construction import _finish_raise_village
st = _finish_raise_village(world, world.raise_village_projects[-1])
assert st.kind == "town" and L.is_under(world.regions[st.region_id])
assert H.node_kind_name(world, st) == "Carven Hall", H.node_kind_name(world, st)
print(f"  ok    {st.name} rises into a Carven Hall")

print("\n--- rung 3: the Carven Hall rises to a Great Hall ---")
fund()
st.population = st.max_population
msg = C.start_settlement_upgrade(world, nation, st)
assert msg == "", msg
from app.world.construction import _finish_settlement_upgrade
_finish_settlement_upgrade(world, world.settlement_upgrade_projects[-1])
assert st.kind == "city"
assert H.node_kind_name(world, st) == "Great Hall", H.node_kind_name(world, st)
print(f"  ok    {st.name} rises into a Great Hall")

print("\n--- build a Carven Hall outright (no road project below) ---")
fund()
msg = C.start_settlement(world, nation, caverns[0], "town", layer=L.UNDER)
assert msg.startswith("Construction begins"), msg
project = world.settlement_projects[-1]
assert project.road is None, "an under settlement must not need a road"
from app.world.construction import _finish_settlement
_finish_settlement(world, project)
new_st = world.settlements[-1]
assert L.is_under(world.regions[new_st.region_id])
assert H.node_kind_name(world, new_st) == "Carven Hall"
print(f"  ok    {new_st.name} carved out of the rock")

print("\n--- an under city grows villages in ITS OWN galleries ---")
fund()
from app.world.resources import _find_city_village_site
site = _find_city_village_site(world, st)
assert site is not None, "the great hall found no gallery to grow into"
assert L.owner_at(world, site[0], site[1], L.UNDER) == idx, (
    "city growth chose a cell the hall does not own below ground")
print(f"  ok    growth site {site} is owned under-ground")

print("\n--- the surface gate town still presents as a Town ---")
gate_town = world.settlements[nation.meta["settlements"][0]]
assert H.node_kind_name(world, gate_town) == "Town"
print("  ok    the door town keeps its ordinary name")

print("\nUNDER LADDER TEST PASSED")
sys.exit(0)
