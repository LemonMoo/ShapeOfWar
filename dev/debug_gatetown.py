"""Probe seeds: when a dwarf player gets a HOLD, where is their gate town
relative to their owned surface territory?"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world.worldgen import generate_world
from app.world import startsites

for seed in (1, 3, 5, 7, 9, 11, 13, 15, 17, 19):
    probe = generate_world(760, 456, seed=seed, n_factions=6,
                           player_species="Dwarves", player_name="Probe")
    cands = startsites.candidate_sites(probe, 6, "Dwarves",
                                       rng=random.Random(probe.seed))
    start = cands[0][:2]
    world = generate_world(760, 456, seed=seed, n_factions=6,
                           player_species="Dwarves", player_name="Probe",
                           player_start=start)
    pidx = world.player_faction_idx
    homes = [h for h in getattr(world, "under_homes", ()) or ()
             if h["faction_idx"] == pidx]
    owns = {rid for row in world.region_grid for rid in row
            if rid >= 0 and world.regions[rid].faction_idx == pidx}
    owned = {(x, y) for y in range(world.h) for x in range(world.w)
             if world.region_grid[y][x] in owns}
    towns = [s for s in world.settlements
             if s.faction_idx == pidx and s.kind == "town"]
    if homes:
        town_owned = None
        if towns:
            town_owned = towns[0].pos in owned
        print(f"seed {seed:>2}: HOLD start={start} towns={len(towns)} "
              f"town_in_owned={town_owned} owned_cells={len(owned)}")
    else:
        print(f"seed {seed:>2}: NO HOLD (surface fallback) towns={len(towns)}")
