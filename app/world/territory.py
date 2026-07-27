"""Territory transfer: moving a region (and everything in it) from one
faction to another when a battle is won, keeping every ownership/aggregate
data structure on the World consistent.
"""
import math

from app.core.events import bus
from app.world import wrap
from app.world.worldgen import OCEAN, _bfs_distance

_NEIGH4 = ((1, 0), (-1, 0), (0, 1), (0, -1))
_NAVAL_COAST_REACH = 3   # same reach as the trade-route coastal test in worldgen.py


def mark_cells_dirty(world, cells):
    """Flag `cells` as needing their map color redone (see map_view.py's
    _precompute_colors/_update_dirty_colors) -- anywhere a cell's DISPLAYED
    color can change: not just transfer_region's ownership flip, but also
    an UNCLAIMED region's wildland_strength changing (see expansion.py's
    resolve_claim_loss), since that strength feeds the "danger" tint
    unclaimed land gets. Accumulated across possibly several changes
    before the next render, then drained and cleared there."""
    dirty = getattr(world, "_dirty_color_cells", None)
    if dirty is None:
        dirty = set()
        world._dirty_color_cells = dirty
    dirty.update(cells)


def _recompute_settle_proximity(world, region):
    """A conquered region's nearest settlement may now belong to a
    different owner, so its remoteness (and thus next turn's non-food
    resource yields — see app/world/resources.py) needs updating. Uses
    straight-line distance to the nearest settlement rather than a full
    grid BFS — cheap enough for a single region on a rare, player-
    triggered conquest, unlike the full-map BFS done once at generation."""
    if not world.settlements:
        region.settle_proximity = 0.5
        return
    cx = sum(x for x, y in region.cells) / len(region.cells)
    cy = sum(y for x, y in region.cells) / len(region.cells)
    best = min(wrap.dist_wrap((cx, cy), st.pos, world.w)
               for st in world.settlements)
    region.settle_proximity = math.exp(-best / 10.0)


def bordering_regions(world, attacker_idx, defender_idx):
    """Regions owned by `defender_idx` that share at least one cell edge
    with land owned by `attacker_idx` — the frontline, and the only
    territory that can realistically change hands from a single battle."""
    w, h, owner = world.w, world.h, world.owner
    if defender_idx < 0:
        # UNCLAIMED wildland (expansion.claimable_frontier's use of this) is
        # typically the vast majority of a large map, while a faction's own
        # territory (attacker_idx) is comparatively small, especially early
        # game — iterate the smaller, attacker side instead of scanning
        # every unclaimed region on the whole map one at a time. This is
        # the path a single region click re-ran from scratch (no caching),
        # so it was the single biggest source of region-click lag on a
        # large map. Left as the original algorithm for faction-vs-faction
        # calls (comparable sizes either way, not reported as slow).
        found_ids = set()
        for region in world.regions:
            if region.faction_idx != attacker_idx:
                continue
            for x, y in region.cells:
                for dx, dy in _NEIGH4:
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and owner[ny][nx] == defender_idx:
                        found_ids.add(world.region_grid[ny][nx])
        return [world.regions[rid] for rid in found_ids]

    out = []
    for region in world.regions:
        if region.faction_idx != defender_idx:
            continue
        for x, y in region.cells:
            for dx, dy in _NEIGH4:
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and owner[ny][nx] == attacker_idx:
                    out.append(region)
                    break
            else:
                continue
            break
    return out


def naval_reachable_regions(world, attacker_idx, defender_idx):
    """Defender's coastal regions, reachable by sea IF the attacker owns at
    least one coastal settlement (a port) — the fallback used when
    bordering_regions is empty (no land connection at all), so an
    overseas/island enemy can still be invaded.

    Simplification: this only checks that both sides have *some* coastline,
    not that they're on the same connected ocean body — fine for this
    generator (one continents-in-one-ocean landmass; edges always sink
    underwater), but would need a real flood-fill check on a world with
    multiple disconnected seas.

    Reuses the coast-distance field settlement placement already computed
    once at world-gen (worldgen._init_settlement_proximity_fields's
    world._settle_coast_d) instead of a fresh map-wide BFS every call — this
    used to redo that full-grid BFS on *every single click* of an unclaimed
    region (claimable_frontier calls this), which on a large map was the
    single biggest source of region-click lag by far."""
    coastal_ids = _coastal_region_ids(world)
    coast_d = world._settle_coast_d   # populated as a side effect of the call above
    if coast_d is None:
        return []

    def is_coastal(pos):
        x, y = pos
        return coast_d[y][x] <= _NAVAL_COAST_REACH

    has_port = any(is_coastal(st.pos) for st in world.settlements
                   if st.faction_idx == attacker_idx)
    if not has_port:
        return []

    return [region for region in world.regions
            if region.faction_idx == defender_idx and region.id in coastal_ids]


def _coastal_region_ids(world):
    """Set of region ids that touch the sea (any cell within
    _NAVAL_COAST_REACH of open ocean) — cached once on the world. A region's
    cells and the coast-distance field are both fixed at world-gen and never
    change afterward, so coastal-ness is turn-invariant; this replaces
    re-scanning every candidate region's cells on every naval_reachable_
    regions call (per faction, per turn — it was the single biggest End Turn
    cost by far). Also ensures world._settle_coast_d is populated."""
    cached = getattr(world, "_coastal_region_ids", None)
    if cached is not None:
        return cached

    coast_d = getattr(world, "_settle_coast_d", None)
    if coast_d is None:
        ocean_cells = [(x, y) for y in range(world.h) for x in range(world.w)
                      if world.owner[y][x] == OCEAN]
        coast_d = _bfs_distance(world, ocean_cells) if ocean_cells else None
        world._settle_coast_d = coast_d
    if coast_d is None:
        world._coastal_region_ids = set()
        return world._coastal_region_ids

    ids = {region.id for region in world.regions
           if any(coast_d[y][x] <= _NAVAL_COAST_REACH for x, y in region.cells)}
    world._coastal_region_ids = ids
    return ids


def _refresh_borders(world, region):
    """After a region changes hands, establish first contact for any faction
    pair that's newly touching along its border — a shared border is the
    AI-vs-AI equivalent of the player's fog-of-war discovery (see
    app/world/vision.py). Existing relationships (factions that already
    share other territory, or that were already at war/allied) are left
    untouched — see diplomacy.establish_contact, which is itself a no-op
    once a relationship exists."""
    from app.world import diplomacy
    pairs = set()
    for x, y in region.cells:
        o = world.owner[y][x]
        for dx, dy in _NEIGH4:
            nx, ny = x + dx, y + dy
            if not (0 <= nx < world.w and 0 <= ny < world.h):
                continue
            o2 = world.owner[ny][nx]
            if o2 >= 0 and o2 != o:
                pairs.add((min(o, o2), max(o, o2)))

    for a, b in pairs:
        na, nb = world.factions[a], world.factions[b]
        diplomacy.establish_contact(world, na.id, nb.id)


def _recompute_faction_totals(world, faction, faction_idx):
    """Recompute a faction's cell count / avg fertility / bbox from its
    (mutated) region list, rather than trying to incrementally un-average."""
    cids = faction.meta.get("regions", [])
    cells = sum(world.regions[cid].stats["area"] for cid in cids)
    fert_sum = sum(world.regions[cid].stats["area"]
                   * world.regions[cid].stats["fertility"] for cid in cids)
    faction.meta["cells"] = cells
    faction.meta["fertility"] = round(fert_sum / cells) if cells else 0

    xs, ys = [], []
    for cid in cids:
        for x, y in world.regions[cid].cells:
            xs.append(x)
            ys.append(y)
    if xs:
        faction.meta["bbox"] = (min(xs), min(ys), max(xs) + 1, max(ys) + 1)


def transfer_region(world, region, new_faction_idx):
    """Move `region` (and every settlement/village in it) to
    `new_faction_idx`. Updates grid ownership, per-region/settlement/village
    owner fields, both factions' meta lists and resource/crop aggregates,
    bounding boxes, and establishes first contact for any newly-adjacent
    faction pair. Emits 'region:transferred' when done.

    `old_faction_idx` may be UNCLAIMED (a fresh claim of neutral land, see
    app/world/expansion.py) rather than a real faction — every old-faction-
    keyed step below is skipped in that case, since there's nothing to move
    out of."""
    old_faction_idx = region.faction_idx
    if old_faction_idx == new_faction_idx:
        return
    old_faction = world.factions[old_faction_idx] if old_faction_idx >= 0 else None
    new_faction = world.factions[new_faction_idx]

    for x, y in region.cells:
        world.owner[y][x] = new_faction_idx
    region.faction_idx = new_faction_idx
    world.territory_version = getattr(world, "territory_version", 0) + 1
    mark_cells_dirty(world, region.cells)

    settlement_ids = list(getattr(region, "meta_settlements", []))
    for sid in settlement_ids:
        world.settlements[sid].faction_idx = new_faction_idx
    village_ids = list(getattr(region, "villages", []))
    for vid in village_ids:
        world.villages[vid].faction_idx = new_faction_idx

    if old_faction is not None:
        old_regions = old_faction.meta.setdefault("regions", [])
        if region.id in old_regions:
            old_regions.remove(region.id)
    new_regions = new_faction.meta.setdefault("regions", [])
    new_regions.append(region.id)

    old_settlements = old_faction.meta.setdefault("settlements", []) if old_faction is not None else []
    new_settlements = new_faction.meta.setdefault("settlements", [])
    for sid in settlement_ids:
        if sid in old_settlements:
            old_settlements.remove(sid)
        new_settlements.append(sid)

    # Move this region's most recent turn's yield out of the old faction's
    # stockpile and into the new one's (military isn't recomputed here —
    # like the resource move itself, that happens on the next End Turn).
    new_res = new_faction.stats.setdefault("resources", {})
    old_res = old_faction.stats.setdefault("resources", {}) if old_faction is not None else None
    for resource, amount in region.resources.items():
        if old_res is not None:
            old_res[resource] = max(0, old_res.get(resource, 0) - amount)
        new_res[resource] = new_res.get(resource, 0) + amount

    if old_faction is not None:
        _recompute_faction_totals(world, old_faction, old_faction_idx)
    _recompute_faction_totals(world, new_faction, new_faction_idx)
    _recompute_settle_proximity(world, region)
    _refresh_borders(world, region)

    bus.emit("region:transferred", {"region": region, "old_faction": old_faction,
                                     "new_faction": new_faction})
