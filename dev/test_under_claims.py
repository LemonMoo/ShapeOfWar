"""Underground regions are claimable through a door you hold -- by ANY species.

    python dev/test_under_claims.py

The two layers share no cell edge (app/world/layers.py), so the ordinary
land-adjacency frontier can never see underground. territory.
gate_bordering_regions is the border: whoever holds the near end of a gate
may claim what lies at the far end. This test asserts the mechanics that
make the galleries a claimable part of the world rather than dwarf/goblin-
only decoration:

  * a faction holding a door has the unclaimed hall behind it on its
    claimable frontier (and can start a claim there);
  * a faction that holds nothing near a door does NOT border through it;
  * claiming an underground region gives BARE galleries -- no surface
    village/settlement machinery scatters farming hamlets through a cavern.

The door-holding is constructed (the test sets a surface mouth's owner),
because on any one seed the unclaimed halls behind held doors may number
zero -- the property is what's being tested, not a particular world.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import layers as L
from app.world import expansion
from app.world import territory
from app.world.worldgen import generate_world, UNCLAIMED

world = generate_world(560, 340, seed=21, n_factions=8)
print("world:", world.under_summary)

unclaimed_under = [r for r in world.regions
                   if L.is_under(r) and r.faction_idx == UNCLAIMED]
print(f"unclaimed under regions: {len(unclaimed_under)}")

print("\n--- nobody borders a hall through a door they do not hold ---")
for gate in world.gates:
    rid = L.region_at(world, gate["under"][0], gate["under"][1], L.UNDER)
    if rid is None:
        continue
    for stranger in range(len(world.factions)):
        reachable = {r.id for r in territory.gate_bordering_regions(
            world, stranger, UNCLAIMED)}
        assert rid not in reachable, (
            f"faction {stranger} borders region {rid} through a door at "
            f"{gate['pos']} it does not hold")
print("  ok    a gate is a chokepoint: no door, no border")

print("\n--- a door you hold is a frontier into the galleries ---")
candidate_gates = [g for g in world.gates
                   if L.region_at(world, g["under"][0], g["under"][1], L.UNDER)
                   in {r.id for r in unclaimed_under}
                   and world.owner[g["pos"][1]][g["pos"][0]] < 0]
assert candidate_gates, "no unclaimed gallery behind an unowned door on this seed"
checked = 0
for gate in candidate_gates[:3]:
    mx, my = gate["pos"]
    rid = L.region_at(world, gate["under"][0], gate["under"][1], L.UNDER)
    region = world.regions[rid]
    holder = 0
    world.owner[my][mx] = holder          # hand the door to faction 0
    try:
        frontier = expansion.claimable_frontier(world, holder)
        assert region in frontier, (
            f"holding the door at {gate['pos']} did not put the hall behind "
            f"it on the frontier")
        assert not expansion.is_sea_only_claim(world, holder, region), (
            "an underground claim through a door was classified as a sea claim")
        msg = expansion.start_claim(world, holder, region)
        assert "doesn't border" not in msg, msg
        checked += 1
    finally:
        world.owner[my][mx] = UNCLAIMED    # restore the map
print(f"  ok    {checked} held doors put the hall behind them on the frontier")

print("\n--- a claimed under region is bare galleries, not a farm pass ---")
gate = candidate_gates[0]
mx, my = gate["pos"]
rid = L.region_at(world, gate["under"][0], gate["under"][1], L.UNDER)
region = world.regions[rid]
holder = 1
world.owner[my][mx] = holder
region.faction_idx = holder
world.factions[holder].meta.setdefault("regions", []).append(rid)
for x, y in region.cells:
    L.set_owner_at(world, x, y, L.UNDER, holder)
expansion.settle_newly_claimed_region(world, region)
assert len(getattr(region, "villages", [])) == 0, (
    "an underground claim sprouted surface villages")
assert not region.meta_settlements, (
    "an underground claim sprouted free settlements")
assert region.settlements_generated, (
    "the claim did not stamp itself settled")
world.owner[my][mx] = UNCLAIMED
print("  ok    bare rock: no villages, no free settlements")

print("\nUNDER CLAIMS TEST PASSED")
sys.exit(0)
