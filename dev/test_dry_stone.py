"""Dry-stone construction: a region with no timber pays its Logs as Stone.

    python dev/test_dry_stone.py [world.pkl]

The bug this guards is the mountain-realm deadlock: Logs only grow on
forest/taiga/jungle at low elevation, so a mountain or highland homeland
can never produce them -- but every early building (storage tier 1, camps,
mines, towns) is priced in Logs. The fix: in a timberless region, a
building project pays its Logs line as Stone instead (construction.
resolve_timber_cost), the construction sibling of the Firewood->Coal fuel
substitution. What this test pins down:

  1. resolve_timber_cost converts Logs->Stone only in timberless regions,
     never mutates its input, and is a no-op without a region or without
     Logs in the cost.
  2. can_afford/_pay_cost agree with the resolved cost, so a realm with
     Stone and no Logs can build in a timberless region and not elsewhere.
  3. On a real world, every timberless region's town cost resolves log-free
     while every timbered region's stays exactly as listed, and the build
     menu's own options (buildings.build_options) carry the dry-stone flag
     exactly where the substitution applies.
"""
import sys
import os
import pickle
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import construction as C
from app.world import buildings as B
from app.world import resources as R

TOWN = dict(C.SETTLEMENT_BUILD_COST["town"])     # {"Logs": 1000, "Stone": 500, "Gold": 750}
CAMP = {"Logs": 200, "Stone": 120, "Gold": 160}   # tier-1 Mining Camp


def make_world():
    """Two tiny regions, two tiny nodes, one nation -- enough for
    can_afford/_pay_cost, which read world.regions, world.settlements/
    villages and nation.meta."""
    region_tl = SimpleNamespace(id=0, faction_idx=0, cells=[(1, 1)],
                                biome_counts={"mountain": 100, "highland": 50})
    region_fo = SimpleNamespace(id=1, faction_idx=0, cells=[(5, 5)],
                                biome_counts={"forest": 100})
    st = SimpleNamespace(id=0, kind="town", name="Mines", pos=(1, 1),
                         faction_idx=0, region_id=0, resources={})
    nation = SimpleNamespace(name="Realm", meta={"settlements": [0]},
                             stats={"resources": {}})
    world = SimpleNamespace(regions=[region_tl, region_fo],
                            settlements=[st], villages=[], factions=[nation],
                            region_grid={}, under_region={})
    return world, nation, st


print("--- resolve_timber_cost: Logs -> Stone, and only where timberless ---")
w, _n, _s = make_world()
# Timberless mountain region: Logs 200 -> Stone 400, added to the existing 120.
resolved = C.resolve_timber_cost(CAMP, w, 0)
assert resolved == {"Stone": 520, "Gold": 160}, resolved
assert CAMP == {"Logs": 200, "Stone": 120, "Gold": 160}, \
    "input cost dict must not be mutated"
# Timbered forest region: exactly the listed cost, same object back.
same = C.resolve_timber_cost(CAMP, w, 1)
assert same is CAMP, "a forest region must pay the literal Logs cost"
# No region context: no-op (ships, generic checks).
assert C.resolve_timber_cost(CAMP, w, None) is CAMP
# No Logs line: no-op even in a timberless region.
raise_cost = {"Stone": 250, "Food": 500}
assert C.resolve_timber_cost(raise_cost, w, 0) is raise_cost
# Town cost: 1000 Logs -> 2000 Stone on top of the existing 500.
town_resolved = C.resolve_timber_cost(TOWN, w, 0)
assert town_resolved == {"Stone": 2500, "Gold": 750}, town_resolved
assert C.resolve_timber_cost(TOWN, w, 1) is TOWN
print("  ok    ratio, identity no-op on timbered land, no mutation, no "
      "region / no Logs no-ops")

print("\n--- can_afford / _pay_cost agree on the resolved cost ---")
w, nation, st = make_world()
st.resources = {"Stone": 5000, "Gold": 500}      # plenty of stone, ZERO logs
# Without region context the Logs cost is unaffordable...
assert not C.can_afford(nation, CAMP, w), \
    "should not afford Logs the realm does not have"
# ...but at its own timberless region the same cost is Stone and is affordable.
assert C.can_afford(nation, CAMP, w, region_id=0), \
    "a Stone-rich timberless realm must be able to build its camp"
# A forest region still demands the real Logs it cannot produce.
assert not C.can_afford(nation, CAMP, w, region_id=1)
C._pay_cost(nation, CAMP, w, region_id=0)
assert st.resources == {"Stone": 5000 - 520, "Gold": 500 - 160}, st.resources
assert st.resources.get("Logs", 0) == 0, "no Logs may be spent"
print("  ok    Stone pays for what Logs would have, Logs never spent")

print("\n--- build menu options carry the flag exactly where it applies ---")
PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "worlds", "dev560.pkl")
world = pickle.load(open(PATH, "rb"))
pidx = world.player_faction_idx if world.player_faction_idx is not None else 0
nation = world.factions[pidx]
nodes = ([v for v in world.villages if v.faction_idx == pidx]
         + [s for s in world.settlements if s.faction_idx == pidx])
assert nodes, "player owns no nodes in this world"

def region_kind(rid):
    return (R.region_outstation_cells(world, world.regions[rid],
                                      R.WOODCUTTERS_CAMP) == 0)

timberless_nodes = [n for n in nodes if region_kind(n.region_id)]
timbered_nodes = [n for n in nodes if not region_kind(n.region_id)]
# The player faction may sit entirely in timbered land; any faction with a
# foot in both kinds of country exercises the same code path, so fall back
# to one that does (the first AI realm straddling the two).
for fidx in range(len(world.factions)):
    f_nodes = ([v for v in world.villages if v.faction_idx == fidx]
               + [s for s in world.settlements if s.faction_idx == fidx])
    ftl = [n for n in f_nodes if region_kind(n.region_id)]
    ftr = [n for n in f_nodes if not region_kind(n.region_id)]
    if ftl and ftr:
        nation = world.factions[fidx]
        timberless_nodes, timbered_nodes = ftl, ftr
        break
assert timberless_nodes and timbered_nodes, \
    f"need both kinds of home region (got {len(timberless_nodes)}/{len(timbered_nodes)})"

logs_bearing = 0
for node in timberless_nodes:
    for opt in B.build_options(world, node, nation):
        if not opt.to_tier:
            continue
        # The BASE cost (what a timbered region would pay) tells us whether
        # this building is Logs-priced at all -- the option's own cost has
        # already been resolved dry-stone here.
        if opt.building == "shipyard":
            base = dict(C.SHIPYARD_COST)
        else:
            base = (C.storage_build_cost(node, opt.building, opt.to_tier,
                                         under=B._node_is_under(world, node))
                    or {})
        if "Logs" not in base:
            continue
        logs_bearing += 1
        assert opt.dry_stone, f"{opt.label} at {node.name}: dry_stone not set"
        assert "Logs" not in opt.cost, f"{opt.label} still priced in Logs"
        assert opt.cost.get("Stone", 0) > 0, opt.cost
for node in timbered_nodes:
    for opt in B.build_options(world, node, nation):
        if "Logs" in opt.cost:
            assert not opt.dry_stone, \
                f"{opt.label} at {node.name}: dry_stone on timbered land"
assert logs_bearing > 0, "no Logs-bearing build options found at all"
print(f"  ok    {logs_bearing} Logs-bearing options on timberless land all "
      f"resolved to Stone and flagged; timbered land untouched")

print("\n--- every timberless region's town is log-free on a real world ---")
count = 0
for region in world.regions:
    if not getattr(region, "cells", None):
        continue
    timberless = C.timberless_region(world, region.id)
    assert timberless == (R.region_outstation_cells(
        world, region, R.WOODCUTTERS_CAMP) == 0), region.id
    cost = C.resolve_timber_cost(TOWN, world, region.id)
    if timberless:
        assert "Logs" not in cost and cost["Stone"] == 2500, (region.id, cost)
        count += 1
    else:
        assert cost is TOWN, "timbered region's town cost must not change"
assert count > 0
print(f"  ok    {count} timberless regions build towns in stone; "
      f"{len(world.regions) - count} timbered regions pay logs")

print("\nALL DRY-STONE TESTS PASSED")
