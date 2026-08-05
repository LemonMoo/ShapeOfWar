"""The gate lifeline (v0.18.13): a cave realm's hold and its gate town trade
through the door.

run_local_logistics matches surplus/need only within a single region, so the
hold's food gap and the gate town's cave goods could never meet. The lifeline
is the only cross-region, cross-layer logistics in the game: one shipment per
direction per turn along a real two-layer route through the door.

Also asserts the blockade: a foreign commander standing at the door's surface
mouth holds the gate -- no lifeline that turn (which is what makes a gate
siege mean something).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world.worldgen import generate_world
from app.world import resources as R
from app.world import layers as L
from app.world.commander import Commander

world = generate_world(1100, 660, seed=4242, n_factions=14,
                       player_species="Dwarves", player_name="Stonehome",
                       player_color=None, player_ruler=None, player_start=None)
print(f"world: {world.under_summary}")

link = R._faction_gate_link(world, 0)
assert link, "the player's dwarf realm has no gate link at all"
under_nodes, gate_town, gate = link
under_ids = {(k, n.id) for k, n in under_nodes}
gt_region = world.regions[gate_town.region_id]
gate_ids = {(k, n.id) for k, n in R._region_logistics_nodes(world, gt_region)}
print(f"  gate town {gate_town.name} at door {gate['pos']}, {len(under_nodes)} "
      f"under nodes")

print("\n--- a hold with food surplus exports it to the door ---")
# The hold's cave goods (mushrooms, ore) should stage at the gate town -- its
# export door -- on their own, without the town needing to want them.
up_before = sum(1 for s in world.local_shipments
                if s.faction_idx == 0 and (s.origin_kind, s.origin_id) in under_ids
                and (s.dest_kind, s.dest_id) in gate_ids)
for _ in range(10):
    R.advance_turn(world)
up_after = sum(1 for s in world.local_shipments
               if s.faction_idx == 0 and (s.origin_kind, s.origin_id) in under_ids
               and (s.dest_kind, s.dest_id) in gate_ids)
print(f"  {up_after - up_before} gate shipments carried cave goods UP to the door")
assert up_after > up_before, "the hold never exports through its own door"

print("\n--- surplus food at the door feeds a hungry hold ---")
for _kind, node in R._region_logistics_nodes(world, gt_region):
    node.resources["Barley"] = node.resources.get("Barley", 0) + 300
for _kind, node in under_nodes:
    for f in R._FOOD_SOURCES:
        node.resources[f] = 0


def gate_ships():
    return [s for s in world.local_shipments
            if s.faction_idx == 0
            and (s.origin_kind, s.origin_id) in gate_ids
            and (s.dest_kind, s.dest_id) in under_ids]


R.advance_turn(world)
down = gate_ships()
assert down, "surplus food at the door never flowed DOWN to the hold"
print(f"  ok    {down[0].resource} {down[0].quantity} -> under node "
      f"{down[0].dest_kind} {down[0].dest_id}")

print("\n--- a foreign army at the door holds it (blockade) ---")
world.commanders.append(Commander(9999, 5, tuple(gate["pos"])))
assert R.gate_blocked(world, gate, 0), "an enemy at the door is not a blockade"
count_before = len(gate_ships())
R.advance_turn(world)
assert len(gate_ships()) == count_before, (
    "the lifeline ran while the door was held")
print("  ok    no gate shipments while the door is held")
print("\nGATE LIFELINE TEST PASSED")
