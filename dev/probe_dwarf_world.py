"""Probe: inspect a new dwarf world's player regions/villages for the
extra-surface-territory + under-data-on-surface bugs."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world.worldgen import generate_world
from app.world import layers as L


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 11
    world = generate_world(width=560, height=340, seed=seed,
                           player_species="Dwarves", n_factions=8)
    idx = world.player_faction_idx
    nation = world.factions[idx]
    meta = nation.meta
    print(f"seed={seed} player species={meta['species']}")
    print(f"capital meta={meta['capital']} (gate town pos per settle_underworld)")
    print("settlements:")
    for sid in meta["settlements"]:
        st = world.settlements[sid]
        print(f"  {sid}: {st.kind} '{st.name}' pos={st.pos} region={st.region_id} "
              f"[{L.region_layer(world.regions[st.region_id]) if st.region_id is not None else '?'}] "
              f"is_capital={getattr(st, 'is_capital', False)} "
              f"under_capital={getattr(st, 'under_capital', False)}")
    print(f"regions ({len(meta['regions'])}):")
    for rid in meta["regions"]:
        r = world.regions[rid]
        cells = r.cells
        n_under = sum(1 for x, y in cells if (x, y) in world.under_cells)
        villages = [world.villages[v].pos for v in r.villages]
        print(f"  region {rid} [{L.region_layer(r)}]: {len(cells)} cells "
              f"({n_under} under), settlements={r.meta_settlements}, "
              f"villages={len(villages)} {villages[:6]}")
    # surface owner cells belonging to the player
    surf = sum(1 for y in range(world.h) for x in range(world.w)
               if world.owner[y][x] == idx)
    under = sum(1 for x, y in getattr(world, "under_owner", {}).items() if y == idx)
    print(f"player surface owner cells={surf}, under owner cells={under}")
    owned_set = {(x, y) for y in range(world.h) for x in range(world.w)
                 if world.owner[y][x] == idx}
    region_set = set()
    for cid in meta["regions"]:
        if L.region_layer(world.regions[cid]) == L.UNDER:
            continue
        region_set |= set(world.regions[cid].cells)
    outside = owned_set - region_set
    if outside:
        from collections import Counter
        c = Counter(world.region_grid[y][x] for x, y in outside)
        print(f"  !! {len(outside)} owned surface cells OUTSIDE any surface region "
              f"(sample {sorted(outside)[:5]}) region_ids: {dict(c)}")
        for rid in c:
            r = world.regions[rid]
            print(f"     region {rid}: faction_idx={r.faction_idx} "
                  f"in_meta={rid in meta['regions']} cells={len(r.cells)} "
                  f"center={r.center}")
    # Fog leak check: is any UNDER region cell revealed in the SURFACE fog?
    fog = getattr(world, "fog", None)
    leaked = 0
    far = 0          # leaked but well away from any player SURFACE region
    coincident = 0   # leaked AND under a player surface region cell
    surf_cells = set()
    for cid in meta["regions"]:
        r = world.regions[cid]
        if L.region_layer(r) == L.UNDER:
            continue
        surf_cells |= set(r.cells)
    if fog is not None:
        for cid in meta["regions"]:
            r = world.regions[cid]
            if L.region_layer(r) != L.UNDER:
                continue
            for x, y in r.cells:
                if fog[y * world.w + x]:
                    leaked += 1
                    if (x, y) in surf_cells:
                        coincident += 1
                    elif min(abs(x - sx) + abs(y - sy) for sx, sy in surf_cells) > 20:
                        far += 1
    print(f"under-region cells revealed in SURFACE fog: {leaked} "
          f"(coincident with surface region: {coincident}, "
          f"far from any surface region: {far})")


if __name__ == "__main__":
    main()
