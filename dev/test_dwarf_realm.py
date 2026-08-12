"""A cave realm owns exactly its mountain and its door -- nothing else.

    python dev/test_dwarf_realm.py

Two bugs shipped together and were reported together from a fresh dwarf
world:

  * The surface fog of war revealed the player's UNDERGROUND network: the
    surface-fog recompute (vision.recompute) revealed every cell of every
    region in the player's meta["regions"], and the under regions claimed by
    holds._claim_network are in that list. So the whole cave network --
    hold, tunnels, warrens -- was readable on the overground map through the
    fog, as if the underground had been walked. The underground has its own
    darkness (vision.recompute_under) and must be walked to be known.

  * The player was handed a SECOND surface territory they never asked for:
    worldgen's starting foothold was assigned to cave peoples like anyone
    else, so a dwarf realm got a surface foothold (with its starting
    villages) on top of the gate town's door region. A cave realm's only
    above-ground land is the gate town's region.

What is asserted here, on freshly generated worlds (Dwarves and Goblins):

  * the player owns exactly ONE surface region, and it is the region the
    gate town sits in, with no starting villages in it;
  * no under-region cell is revealed in the SURFACE fog unless it lies
    under the player's own revealed surface ground (a cave network far
    from the door must read as fog from above);
  * the cave realm's nation stats are sane (cells > 0, a real center and
    bbox) even though no surface foothold was assigned;
  * every cave realm that cannot reach a cave network still gets a proper
    surface start (its own region, its city and its starting villages) --
    the fallback must not end up a city on land it does not own.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import layers as L
from app.world.worldgen import generate_world
from app.world.holds import UNDERGROUND_SPECIES

SMALL = dict(width=560, height=340, n_factions=8)
FAILURES = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not ok:
        FAILURES.append(name)


def player_surface_regions(world):
    idx = world.player_faction_idx
    meta = world.factions[idx].meta
    return [world.regions[cid] for cid in meta["regions"]
            if L.region_layer(world.regions[cid]) != L.UNDER]


def test_realm(world, species):
    print(f"\n--- {species} realm ---")
    idx = world.player_faction_idx
    nation = world.factions[idx]
    meta = nation.meta
    has_under = any(L.region_layer(world.regions[cid]) == L.UNDER
                    for cid in meta.get("regions", []))
    if not has_under:
        # The player's realm could not reach a cave network and fell back to
        # a plain surface start: it must be a REAL surface realm, not a city
        # on land it does not own.
        surf = [world.regions[cid] for cid in meta["regions"]
                if L.region_layer(world.regions[cid]) != L.UNDER]
        owned = {(x, y) for y in range(world.h) for x in range(world.w)
                 if world.owner[y][x] == idx}
        check("surface fallback player owns its region",
              bool(surf) and meta.get("capital") in owned, f"{len(surf)} region(s)")
        if surf:
            check("surface fallback got its starting villages",
                  len(max(surf, key=lambda r: len(r.villages)).villages) >= 3)
        return

    # 1. exactly one surface region, the gate town's, with no villages.
    surf = player_surface_regions(world)
    check("the player owns exactly ONE surface region", len(surf) == 1,
          f"{len(surf)}")
    if surf:
        gate_towns = [world.settlements[s] for s in meta["settlements"]
                      if world.settlements[s].kind == "town"
                      and not L.is_under(world.regions[world.settlements[s].region_id])]
        check("that region is the gate town's", gate_towns
              and all(st.region_id == surf[0].id for st in gate_towns))
        check("no starting villages in the surface region",
              len(surf[0].villages) == 0, f"{len(surf[0].villages)}")

    # 2. no under-region cell is revealed in the SURFACE fog unless it is
    #    under the player's own revealed surface ground.
    surf_cells = {c for r in surf for c in r.cells}
    fog = getattr(world, "fog", None)
    far_leaks = 0
    if fog is not None:
        for cid in meta["regions"]:
            region = world.regions[cid]
            if L.region_layer(region) != L.UNDER:
                continue
            for x, y in region.cells:
                if fog[y * world.w + x]:
                    d = min(abs(x - sx) + abs(y - sy) for sx, sy in surf_cells)
                    if d > 20:
                        far_leaks += 1
    check("no underground shape leaks into the surface fog",
          far_leaks == 0, f"{far_leaks} far revealed cells")

    # 3. sane nation stats despite no surface foothold.
    cells = meta.get("cells", 0)
    bbox = meta.get("bbox")
    cx, cy = nation.center
    check("nation has cells/center/bbox", cells > 0
          and bbox is not None and bbox != (0, 0, 1, 1)
          and (cx, cy) != (0, 0), f"cells={cells} bbox={bbox} center={(cx, cy)}")

    # 4. the realm's settlements are where they should be: a dwarf hold's
    #    capital is the great hall under the mountain, with carven halls
    #    (under towns) and one surface door town; a goblin warren has no
    #    great hall, so its capital IS the door town.
    meta_sts = [world.settlements[s] for s in meta["settlements"]]
    kinds = sorted(s.kind for s in meta_sts)
    caps = [s.kind for s in meta_sts if getattr(s, "is_capital", False)]
    if species == "Dwarves":
        under_towns = [s for s in meta_sts
                       if s.kind == "town"
                       and L.is_under(world.regions[s.region_id])]
        surf_towns = [s for s in meta_sts
                      if s.kind == "town"
                      and not L.is_under(world.regions[s.region_id])]
        check("hold: one great hall under the mountain, at least one carven "
              "hall, and exactly one door town on the surface",
              kinds.count("city") == 1 and len(under_towns) >= 1
              and len(surf_towns) == 1 and caps == ["city"],
              f"{kinds} cap={caps} (under towns: {len(under_towns)}, "
              f"door towns: {len(surf_towns)})")
    else:
        check("warren: the door town is the capital",
              kinds == ["town"] and caps == ["town"], f"{kinds} cap={caps}")


def test_fallbacks(world):
    """Cave realms that could not reach a cave network fell back to a plain
    surface start -- they must own their land and have their starting
    villages, and the claimed region must be in the faction's own meta."""
    print("\n--- cave realms with no reachable network ---")
    seen = 0
    for idx, nation in enumerate(world.factions):
        if nation.meta.get("species") not in UNDERGROUND_SPECIES:
            continue
        has_under = any(L.region_layer(world.regions[cid]) == L.UNDER
                        for cid in nation.meta.get("regions", []))
        if has_under:
            continue   # went underground -- not a fallback
        seen += 1
        meta = nation.meta
        surf = [world.regions[cid] for cid in meta["regions"]
                if L.region_layer(world.regions[cid]) != L.UNDER]
        owned = {(x, y) for y in range(world.h) for x in range(world.w)
                 if world.owner[y][x] == idx}
        capital = meta.get("capital")
        check(f"faction {idx}: surface fallback owns its region",
              bool(surf) and (capital in owned),
              f"{len(surf)} surface region(s), capital owned={capital in owned}")
        if surf:
            home = max(surf, key=lambda r: len(r.villages))
            check(f"faction {idx}: fallback got its starting villages",
                  len(home.villages) >= 3, f"{len(home.villages)}")
    if not seen:
        print("  (no cave realm needed the fallback on this seed)")
    return seen


def test_no_underworld():
    """A world whose plate layout carved NO underworld at all: cave realms
    cannot go under, so every cave faction must still get a plain surface
    start -- the step-8 foothold was skipped for them, so the
    settle_underworld early-return path is what rescues them. Without it a
    dwarf on such a map owned nothing at all."""
    print("\n--- a world with no underworld carved ---")
    from app.world import underworld
    real_carve = underworld.carve_underworld
    underworld.carve_underworld = lambda w, rng: None
    try:
        world = generate_world(seed=11, player_species="Dwarves", **SMALL)
    finally:
        underworld.carve_underworld = real_carve
    check("no underworld was carved", not world.under_cells)
    idx = world.player_faction_idx
    meta = world.factions[idx].meta
    kinds = sorted(world.settlements[s].kind
                   for s in meta.get("settlements", []))
    check("the realm is a plain surface city", kinds == ["city"], f"{kinds}")
    owned = {(x, y) for y in range(world.h) for x in range(world.w)
             if world.owner[y][x] == idx}
    check("the fallback realm owns its land", meta.get("capital") in owned)
    surf = [world.regions[cid] for cid in meta.get("regions", [])
            if L.region_layer(world.regions[cid]) != L.UNDER]
    if surf:
        check("the fallback realm has its starting villages",
              len(max(surf, key=lambda r: len(r.villages)).villages) >= 3)
    else:
        check("the fallback realm has its starting villages", False,
              "no surface regions in meta")


def main():
    # Seed 11: both species' realms reach a cave network (the underground
    # case). Seed 7: the dwarf player's realm cannot reach one and falls
    # back to a plain surface start -- both paths must produce a sound realm.
    for species, seeds in (("Dwarves", (11, 7)), ("Goblins", (11,))):
        for seed in seeds:
            print(f"generating a {species} world, seed {seed} (~10s)...")
            world = generate_world(seed=seed, player_species=species, **SMALL)
            test_realm(world, species)
            test_fallbacks(world)
    test_no_underworld()
    print("\nDWARF REALM TEST " + ("FAILED: " + ", ".join(FAILURES)
                                   if FAILURES else "PASSED"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
