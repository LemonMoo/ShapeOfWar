"""Tunnels (v0.18.14): the underground expansion analog of a surface claim.

A cave realm can dig a corridor of rock from its home network to the nearest
UNCLAIMED cavern network; the corridor is carved (becomes passable CAVERN) a
few cells per day like a road, and when the diggers land the target network
is claimed for the faction. One tunnel at a time, gold per cell of rock.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world.worldgen import generate_world
from app.world import holds, layers as L

world = generate_world(1100, 660, seed=4242, n_factions=14)
print(f"world: {world.under_summary}")

# Some realm must have an unclaimed network within digging range.
candidate = None
for h in world.under_homes:
    network, corridor = holds._nearest_unclaimed_network(world, h["faction_idx"])
    if network is not None:
        candidate = (h, network, corridor)
        break
assert candidate, "no faction in this world can dig a tunnel -- the mechanic is unreachable"
home, network, corridor = candidate
idx = home["faction_idx"]
print(f"  {world.factions[idx].name} digs {len(corridor)} cells of rock "
      f"({len(corridor) * holds.TUNNEL_GOLD_PER_CELL} Gold, ~"
      f"{round(len(corridor) / holds.TUNNEL_CELLS_PER_TURN)} days)")

# The corridor is all ROCK before the work starts.
for x, y in corridor:
    assert not L.kind_at(world, x, y, L.UNDER), (
        "the corridor runs through a cell that is already open")
print("  ok    the corridor is solid rock before the dig")

project = holds.start_tunnel_project(world, idx, 10 ** 9)
assert project is not None, "a payable tunnel did not start"
assert holds.start_tunnel_project(world, idx, 10 ** 9) is None, (
    "two tunnels at once")
print("  ok    one tunnel at a time")

before = len(world.factions[idx].meta.get("regions", []))
guard = 0
while project in getattr(world, "tunnel_projects", ()) and guard < 400:
    holds.advance_tunnel_projects(world)
    guard += 1
assert project not in world.tunnel_projects, "the tunnel never completed"
assert guard >= 2, "the tunnel appeared to finish in a single day"

after = len(world.factions[idx].meta.get("regions", []))
assert after > before, "the tunnel claimed no regions for the faction"
for x, y in corridor:
    assert L.kind_at(world, x, y, L.UNDER) == L.CAVERN, (
        "a corridor cell was not carved")
print(f"  ok    {guard} days to carve {len(corridor)} cells; regions "
      f"{before} -> {after}")
print("\nTUNNEL TEST PASSED")
