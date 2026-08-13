"""Player goblin raids (v0.18.14): a goblin player's warren village can order
a raid -- the warren's warband comes out through its network's doors and
takes the richest reachable surface store, exactly as the AI's hungry-warren
raids do, but the player decides (and pays a cooldown).

Also pins the two reach fixes: raid reach comes from the whole network's
doors (the per-region model left most warren villages in regions that touch
no door, quietly killing the mechanic), and a "warren" is only a warren
UNDER the ground (node_is_warren is species-only -- surface goblin villages
must not raid).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world.worldgen import generate_world, Village
from app.world import holds, layers as L
from app.world import resources as R

world = generate_world(1100, 660, seed=4242, n_factions=14,
                       player_species="Goblins", player_name="Skraggbite",
                       player_color=None, player_ruler=None, player_start=None)

# A warren is UNDER the ground: surface goblin villages must not count.
surface = next((v for v in world.villages
                if v.faction_idx == 0
                and not L.is_under(world.regions[v.region_id])), None)
if surface is None:
    # The player's warren start can leave it with no surface holding at all;
    # plant one so the "surface goblins are not warrens" precondition is real.
    sreg = next(r for r in world.regions
                if r.faction_idx == 0 and not L.is_under(r))
    surface = Village(len(world.villages), sreg.id, 0, "Surface Steading",
                      sreg.cells[0], farm_output=10, population=100,
                      adults=60, children=40, prosperity=50, max_population=300)
    world.villages.append(surface)
    sreg.villages = list(getattr(sreg, "villages", [])) + [surface.id]
assert holds.node_is_warren(world, surface), "precondition: goblin species"
assert not L.is_under(world.regions[surface.region_id])
print("  ok    a surface goblin village is not treated as a warren")

# Pick a faction with a real warren (network reach may not exist for the
# scattered player start) and its warren's network doors.
home = next(h for h in world.under_homes if h["kind"] == holds.WARREN)
idx = home["faction_idx"]
warren = next(v for v in world.villages
              if v.faction_idx == idx
              and L.is_under(world.regions[v.region_id]))
print(f"  warren of {world.factions[idx].name}: {warren.name}")

# Reach is from the NETWORK's doors (see _raid_targets).
mouths = set()
for rid in home["regions"]:
    mouths |= set(world.regions[rid].cells)
gates = [g for g in world.gates if tuple(g["under"]) in mouths]
assert gates, "a warren with no reachable doors at all"
door = gates[0]["pos"]
sx, sy = (door[0] + 8) % world.w, max(0, min(world.h - 1, door[1] - 4))
rid = world.region_grid[sy][sx]
victim = Village(len(world.villages), rid, (idx + 3) % len(world.factions),
                 "Fatfields", (sx, sy), farm_output=100,
                 population=400, adults=260, children=140,
                 prosperity=50, max_population=800)
victim.resources = {"Barley": 900, "Meat": 400}
world.villages.append(victim)

summary = holds.raid_target_summary(world, warren)
assert summary and summary[0] is victim, (
    "the planted store is not within reach of the warren's doors")
print(f"  ok    the raid names its target first: {victim.name} "
      f"({summary[1]:,} food)")

raid = holds.player_raid(world, warren)
assert raid and raid["victim"] is victim and raid["hauled"], raid
assert sum(raid["hauled"].values()) > 0
print(f"  ok    the warband hauls home: {raid['hauled']}")

assert holds.player_raid(world, warren) is None, (
    "a second raid the same day slipped past the cooldown")
assert getattr(warren, "raid_cooldown_until", 0) > world.turn
print(f"  ok    cooldown holds ({holds.RAID_COOLDOWN_DAYS} days)")

print("\nPLAYER RAID TEST PASSED")
