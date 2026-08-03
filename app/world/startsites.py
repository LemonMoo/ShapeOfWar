"""What a would-be starting site is actually worth.

Part B2 of WORLDGEN_START_PLAN.md. Pure logic over an already-grown world:
given a cell, say what the land around it offers -- its country, the goods it
can raise, whether it has water and a coast, how much room it has, and, the
one the plan singled out, whether it can feed a realm at all.

Nothing here changes the world. It reads `biome_grid` (the REAL biomes, which
exist by the time anyone is choosing a start -- unlike capital-placement time,
where worldgen had to approximate them) plus height and the water sets, in a
single neighbourhood pass. The New Game screen turns the result into a card;
the sustain verdict becomes the warning the player may override.
"""
from app.world import wrap
from app.world.worldgen import (OCEAN, _HOMELAND_RADIUS, _HOMELAND_STEP,
                                homeland_affinity)
from app.world.resources import RESOURCE_SPAWN

# The country a realm can actually farm -- crops and the herds that graze on
# open grass. This is the "farmland %" the card reports.
_CROP_BIOMES = frozenset({"plains", "steppe", "savannah", "swamp"})

# Barren country: rock, sand and ice. A realm ringed only by these cannot feed
# itself however it trades. Everything else -- forest, taiga, jungle, highland,
# coastal -- is WORKABLE: it carries a settlement on timber, forage, pigs and
# fish even where it grows little grain, which is why the generator is happy to
# place capitals in it. The sustain verdict turns on workable land, not crops;
# a low farmland % is shown on the card but is not by itself a warning.
_BARREN_BIOMES = frozenset({"mountain", "desert", "tundra"})

# Floors, as a fraction of nearby land. Below WORKABLE, a start cannot support
# a realm at all (the real warning). Below CROP but above it, the realm can
# stand but will lean on forage and trade (a softer note). First-pass numbers,
# judged in play. The player may override either -- the verdict warns, it does
# not veto.
_SUSTAIN_WORKABLE_FLOOR = 0.15
_THIN_FARMLAND_FLOOR = 0.06

# How far out "near this site" reaches for coast and river checks -- the same
# neighbourhood the homeland/farmland questions already use, so every answer on
# the card is about the same patch of ground.
_WATER_REACH = _HOMELAND_RADIUS


def _relief(world, x, y):
    sea = world.sea_level
    span = (1.0 - sea) or 1.0
    return max(0.0, min(1.0, (world.height[y][x] - sea) / span))


def _neighbourhood(world, x, y):
    """One pass over the land around (x, y). Returns biome counts, the
    per-resource count of cells matching a resource's own (biome, elevation)
    rule -- the same test region production uses -- and the totals the shares
    are taken against."""
    biome_counts = {}
    resource_hits = {}
    land = crop = workable = 0
    r = _HOMELAND_RADIUS
    for dy in range(-r, r + 1, _HOMELAND_STEP):
        cy = y + dy
        if not (0 <= cy < world.h):
            continue
        for dx in range(-r, r + 1, _HOMELAND_STEP):
            cx = wrap.wrap_x(x + dx, world.w)
            biome = world.biome_grid[cy][cx]
            if biome is None:                 # ocean
                continue
            land += 1
            biome_counts[biome] = biome_counts.get(biome, 0) + 1
            if biome in _CROP_BIOMES:
                crop += 1
            if biome not in _BARREN_BIOMES:
                workable += 1
            relief = _relief(world, cx, cy)
            for name, spec in RESOURCE_SPAWN.items():
                biomes = spec.get("biomes")
                if not biomes or biome not in biomes:
                    continue
                lo, hi = spec.get("elevation", (0.0, 1.0))
                if lo <= relief <= hi:
                    resource_hits[name] = resource_hits.get(name, 0) + 1
    return biome_counts, resource_hits, land, crop, workable


def _has_water(world, x, y, cells):
    """(coast, river) within reach: an ocean cell, and a river or lake cell."""
    coast = river = False
    r = _WATER_REACH
    for dy in range(-r, r + 1, _HOMELAND_STEP):
        cy = y + dy
        if not (0 <= cy < world.h):
            continue
        for dx in range(-r, r + 1, _HOMELAND_STEP):
            cx = wrap.wrap_x(x + dx, world.w)
            if world.owner[cy][cx] == OCEAN:
                coast = True
            if (cx, cy) in world.river_cells or (cx, cy) in world.lake_cells:
                river = True
            if coast and river:
                return True, True
    return coast, river


def _nearest_rival(world, x, y):
    """Distance in cells to the nearest faction capital, or None if the world
    has no factions yet. Read from placed capitals so it reflects where the
    rivals actually are, not where they might go."""
    best = None
    for f in world.factions:
        cap = (f.meta or {}).get("capital")
        if not cap:
            continue
        d = ((cap[0] - x) ** 2 + (cap[1] - y) ** 2) ** 0.5
        if best is None or d < best:
            best = d
    return best


def evaluate_site(world, x, y, species=None, top_resources=8):
    """Everything the card shows for a start at (x, y). Pure; changes nothing.

    `species` (optional) adds the homeland-fit score for that people. The
    `sustain` entry is {"ok": bool, "reason": str} -- the plan's warn-don't-
    block verdict."""
    biome_counts, resource_hits, land, crop, workable = _neighbourhood(world, x, y)
    shares = {b: n / land for b, n in biome_counts.items()} if land else {}
    farmland_pct = (crop / land) if land else 0.0
    workable_pct = (workable / land) if land else 0.0
    coast, river = _has_water(world, x, y, land)

    # Likely goods: resources whose (biome, elevation) rule the surrounding
    # land actually meets, most-abundant first. This is what the ground can
    # raise, not a guess from the headline biome.
    resources = sorted(resource_hits, key=lambda n: -resource_hits[n])[:top_resources]

    ok = land > 0 and workable_pct >= _SUSTAIN_WORKABLE_FLOOR
    if land == 0:
        reason = "This is open water -- there is no land to settle."
    elif not ok:
        reason = ("Barren country -- rock, sand or ice. A realm founded here "
                  "cannot support itself.")
    elif farmland_pct < _THIN_FARMLAND_FLOOR:
        reason = ("Little farmland; this realm will live on its forests and "
                  "the coast, and lean on trade for grain.")
    else:
        reason = "Good country; a realm can feed itself here."

    nearest = _nearest_rival(world, x, y)
    if nearest is None:
        room = None
    else:
        far = nearest / max(1, world.w)
        room = "isolated" if far > 0.28 else "elbow room" if far > 0.16 else "crowded"

    return {
        "cell": (x, y),
        "biomes": shares,
        "dominant_biome": max(shares, key=shares.get) if shares else None,
        "resources": resources,
        "farmland_pct": farmland_pct,
        "workable_pct": workable_pct,
        "coast": coast,
        "river": river,
        "affinity": homeland_affinity(species, shares) if species else None,
        "nearest_rival": nearest,
        "room": room,
        "sustain": {"ok": ok, "reason": reason},
    }


def candidate_sites(world, count, species=None, rng=None, min_spacing=None):
    """A handful of good, spread-out places to offer as starts: sustainable,
    away from each other and from the rivals already placed. Ordered best-first
    for the chosen species when one is given.

    Deterministic when handed an `rng`; falls back to the module `random`
    otherwise. This is the source of the markers the picker drops on the
    preview, not a constraint on where the player may click -- free placement
    anywhere is still allowed (see evaluate_site's warning)."""
    import random as _random
    rng = rng or _random
    w, h = world.w, world.h
    spacing = min_spacing if min_spacing is not None else max(
        8.0, (w * h / max(1, count * 20)) ** 0.5)

    land_cells = [(x, y) for y in range(h) for x in range(w)
                  if world.owner[y][x] != OCEAN
                  and (x, y) not in world.lake_cells
                  and world.owner[y][x] < 0]      # UNCLAIMED only -- not on a rival
    rng.shuffle(land_cells)

    rivals = [(f.meta or {}).get("capital") for f in world.factions]
    rivals = [c for c in rivals if c]

    picked = []
    for x, y in land_cells:
        if len(picked) >= count:
            break
        if any((x - rx) ** 2 + (y - ry) ** 2 < (spacing * 2) ** 2 for rx, ry in rivals):
            continue
        if any((x - px) ** 2 + (y - py) ** 2 < spacing ** 2 for px, py, _ in picked):
            continue
        ev = evaluate_site(world, x, y, species)
        if not ev["sustain"]["ok"]:
            continue
        picked.append((x, y, ev))

    if species:
        picked.sort(key=lambda p: -(p[2]["affinity"] or 0.0))
    return [(x, y, ev) for x, y, ev in picked]
