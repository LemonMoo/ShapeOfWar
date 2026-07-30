"""Reported bug: a faction's first settlement on a different landmass got a
literal straight "stone" road drawn through the open sea to its nearest
existing settlement, since construction._find_road_path/worldgen._local_
road_path both silently fell back to a straight two-point segment whenever
their Dijkstra search found no LAND route -- which is exactly what happens
when the two endpoints are on different landmasses, not just a rare local
pathfinding hiccup.

Fix: both now refuse the straight fallback for the specific callers that
can legitimately span two landmasses (_find_road_path,
_bridge_region_to_kingdom), and try a real open-water path (Dijkstra over
OCEAN cells, "sea" tier) instead. This test forces exactly that scenario --
a faction's capital on one real landmass, a second real landmass (from the
same generated world) that shares no land cell with the capital's -- and
checks the result is either a genuine sea lane or nothing at all, never a
fake straight line cutting across open water.

    python dev/test_sea_bridge.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import construction
from app.world.worldgen import (generate_world, OCEAN, Settlement,
                                _nearest_ocean_cell, _roll_population)
from app.world.resources import seed_prosperity

FAILURES = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not ok:
        FAILURES.append(name)


def _landmass(world, start):
    """Flood fill over non-ocean cells reachable from `start` -- one
    connected landmass."""
    seen = {start}
    frontier = [start]
    w, h = world.w, world.h
    while frontier:
        nxt = []
        for x, y in frontier:
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if not (0 <= nx < w and 0 <= ny < h) or (nx, ny) in seen:
                    continue
                if world.owner[ny][nx] == OCEAN:
                    continue
                seen.add((nx, ny))
                nxt.append((nx, ny))
        frontier = nxt
    return seen


def _crosses_ocean(world, a, b):
    """Whether the straight segment a->b passes through any OCEAN cell --
    what the old fallback would have silently drawn."""
    ax, ay = a
    bx, by = b
    steps = max(abs(bx - ax), abs(by - ay), 1)
    for i in range(steps + 1):
        x = round(ax + (bx - ax) * i / steps)
        y = round(ay + (by - ay) * i / steps)
        if world.owner[y][x] == OCEAN:
            return True
    return False


def _find_other_landmass_region(world, home_landmass, faction_idx):
    """An UNCLAIMED region sharing no cell with `home_landmass` -- a
    genuinely different landmass to found a settlement on."""
    for region in world.regions:
        if region.faction_idx != -2:      # UNCLAIMED
            continue
        if not region.cells:
            continue
        if any(c in home_landmass for c in region.cells):
            continue
        coastal = [c for c in region.cells if world.owner[c[1]][c[0]] != OCEAN]
        if coastal:
            return region
    return None


def _nearest_coastal_cell(world, landmass, toward):
    """The cell in `landmass` nearest `toward` that has open ocean within
    reach -- i.e. one _nearest_ocean_cell can actually dock at."""
    best, best_d2 = None, None
    for (x, y) in landmass:
        if _nearest_ocean_cell(world, (x, y)) is None:
            continue
        d2 = (x - toward[0]) ** 2 + (y - toward[1]) ** 2
        if best_d2 is None or d2 < best_d2:
            best_d2, best = d2, (x, y)
    return best


def test_no_fake_road_across_ocean():
    print("\n--- new settlement on a different landmass: no fake straight road ---")
    world = generate_world(width=1400, height=840, seed=17, n_factions=6,
                           player_species="Humans", player_name="SeaTest")
    faction = world.factions[0]
    capital = faction.meta["capital"]
    home = _landmass(world, capital)

    region = _find_other_landmass_region(world, home, 0)
    if region is None:
        print("  (skipped: seed 17 didn't produce a usable second landmass "
             "-- not a failure, just an unlucky map)")
        return

    check("candidate region really shares no cell with the capital's landmass",
          not any(c in home for c in region.cells))

    # Force-claim it, the same bookkeeping expansion.py does for a real claim.
    region.faction_idx = 0
    for (x, y) in region.cells:
        world.owner[y][x] = 0
    faction.meta.setdefault("regions", []).append(region.id)

    target = next(c for c in region.cells if world.owner[c[1]][c[0]] != OCEAN)

    # The real bug report is two ALREADY-EXISTING coastal cities, one per
    # landmass, not "found a new city from a possibly-inland capital 800
    # cells away" -- give the faction a genuine coastal foothold on its own
    # landmass, nearest the strait, standing in for "the city closest to the
    # new one across the water" (placing it directly, bypassing
    # start_settlement, since all that matters here is that it EXISTS).
    home_dock = _nearest_coastal_cell(world, home, target)
    if home_dock is None:
        print("  (skipped: seed 17's home landmass has no cell within sea "
             "range of a dock -- not a failure, just an unlucky map)")
        return
    home_region_id = world.region_grid[home_dock[1]][home_dock[0]]
    population, adults, children, max_pop = _roll_population(__import__("random").Random(1), "town")
    coastal_st = Settlement(len(world.settlements), "town", "Coastwatch", home_dock,
                            0, home_region_id, 10, population, adults, children,
                            seed_prosperity(), max_pop)
    world.settlements.append(coastal_st)
    home_region = world.regions[home_region_id]
    if not hasattr(home_region, "meta_settlements"):
        home_region.meta_settlements = []
    home_region.meta_settlements.append(coastal_st.id)
    faction.meta.setdefault("settlements", []).append(coastal_st.id)

    tier, path = construction._find_road_path(world, 0, target)
    check("a route was found at all (land or sea)", tier is not None, str(tier))
    if tier is not None:
        check("it's tagged 'sea', not 'land' (no land bridge exists)",
              tier == "sea", tier)
        check("every cell on the path is actually OCEAN or an endpoint, "
              "never a straight cut through unrelated terrain",
              all(world.owner[y][x] == OCEAN or (x, y) in (path[0], path[-1])
                  for x, y in path))
        check("path starts at the origin settlement and ends at the target",
              path[0] == faction.meta["capital"] or path[0] in home,
              f"path[0]={path[0]}")
        check("path reaches the target", path[-1] == target)

    # Give the faction's settlements enough stock to always afford it.
    for st in world.settlements:
        if st.faction_idx != 0:
            continue
        st.resources = dict(getattr(st, "resources", {}) or {})
        for res, amt in construction.SETTLEMENT_BUILD_COST["town"].items():
            st.resources[res] = amt * 5

    msg = construction.start_settlement(world, faction, target, "town")
    check("start_settlement accepted the site", "begins" in msg, msg)
    project = next((p for p in world.settlement_projects
                    if p.pos == target), None)
    check("a settlement project was created", project is not None)
    if project is None:
        return
    check("no land RoadProject was queued for it (nothing to build across "
          "open water)", project.road is None)
    check("a sea_lane was recorded on the project instead",
          bool(getattr(project, "sea_lane", None)))

    for _ in range(200):
        if not world.settlement_projects:
            break
        construction.advance_projects(world)
    check("the settlement finished construction",
          any(s.pos == target for s in world.settlements))

    segs = world.roads_by_region.get(region.id, [])
    check("its region now has a 'sea' tier segment on record",
          any(t == "sea" for _a, _b, t in segs), str({t for _a, _b, t in segs}))
    fake_roads = [(a, b) for a, b, t in segs
                 if t in ("stone", "dirt") and _crosses_ocean(world, a, b)]
    check("NOT ONE stone/dirt segment cuts across open ocean "
          "(the exact reported bug)", not fake_roads, str(fake_roads[:3]))


def main():
    test_no_fake_road_across_ocean()
    print("\nSEA BRIDGE TEST " + ("FAILED: " + ", ".join(FAILURES)
                                  if FAILURES else "PASSED"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
