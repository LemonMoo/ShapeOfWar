"""Territory transfer: moving a region (and everything in it) from one
faction to another when a battle is won, keeping every ownership/aggregate
data structure on the World consistent.
"""
import math

from app.core.events import bus
from app.world import wrap
from app.world import layers as L
from app.world.nation import is_eliminated
from app.world.worldgen import OCEAN, UNCLAIMED, _bfs_distance
from app.world.resources import _SETTLEMENT_STORAGE_RESOURCES

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
               for st in world.settlements if st.faction_idx >= 0)
    region.settle_proximity = math.exp(-best / 10.0)


def gate_bordering_regions(world, attacker_idx, defender_idx):
    """Regions owned by `defender_idx` that this faction reaches THROUGH A
    DOOR (SUBTERRANEAN_PLAN phase 5).

    The two layers share no cell edge -- that is the whole model (see
    app/world/layers.py) -- so `bordering_regions` above, which walks the
    surface owner grid, can never see across. Without this an underground
    region is unclaimable and unattackable by anybody who is not already down
    there, which reads as the underworld being decorative.

    A gate joins two cells, so the rule is exactly as narrow as the geography:
    you border a region on the other layer when you hold (or, for wildland,
    stand beside) the cell at YOUR end of a door whose other end is in it.
    Claiming underground is claiming through a chokepoint, which is what the
    plan asks the AI to understand."""
    out = {}
    for gate in getattr(world, "gates", ()):
        sx, sy = gate["pos"]
        ux, uy = gate["under"]
        for near, far, near_layer, far_layer in (
                ((sx, sy), (ux, uy), 0, 1), ((ux, uy), (sx, sy), 1, 0)):
            from app.world import layers as L
            if L.owner_at(world, near[0], near[1], near_layer) != attacker_idx:
                continue
            far_owner = L.owner_at(world, far[0], far[1], far_layer)
            # Unowned is UNCLAIMED, not OCEAN: an absent sparse-map entry
            # means nobody holds it, and an underground cell is never ocean.
            # Mapping None to -1 (OCEAN) here is what silently made every
            # unclaimed far side fail the `!= defender_idx` test, so the
            # gate frontier could never contain wildland at all.
            far_owner = UNCLAIMED if far_owner is None else far_owner
            if far_owner != defender_idx:
                continue
            rid = L.region_at(world, far[0], far[1], far_layer)
            if rid is not None and 0 <= rid < len(world.regions):
                out[rid] = world.regions[rid]
    return list(out.values())


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

    # Ownership is per-layer: an underground region's cells live in the
    # sparse `under_owner` map, and the SAME coordinates on the surface
    # belong to whoever owns the mountainside above (usually nobody, or a
    # different realm entirely). Writing the dense surface grid for an
    # under region would hand the conqueror a second, bogus surface
    # territory and leave the galleries owned by the loser -- the
    # half-implemented "take a gate" that shipped before this. See
    # app/world/layers.py's owner_at/set_owner_at.
    if L.is_under(region):
        for x, y in region.cells:
            L.set_owner_at(world, x, y, L.UNDER, new_faction_idx)
    else:
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

    # Move this region's most recent turn's yield between the two national
    # pools -- but ONLY for resources that actually live in a national pool.
    #
    # Everything in _SETTLEMENT_STORAGE_RESOURCES (which today is very nearly
    # the whole registry) is held per-node, and this region's settlements and
    # villages have just changed hands a few lines above with their stock
    # aboard. Re-adding their yield to the conqueror's national pool counted
    # the same goods twice AND banked the copy somewhere nothing can ever
    # spend it from: can_afford/_pay_cost read node storage for these, never
    # the pool. Measured on a real save, that had quietly accumulated 48,509
    # phantom units across the factions -- goods the resource bar displayed
    # and no one could touch. See _purge_phantom_pool for the cleanup of
    # stock already banked this way.
    new_res = new_faction.stats.setdefault("resources", {})
    old_res = old_faction.stats.setdefault("resources", {}) if old_faction is not None else None
    for resource, amount in region.resources.items():
        if resource in _SETTLEMENT_STORAGE_RESOURCES:
            continue      # travelled with the nodes, not through a pool
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

    # Losing the last region is what ends a nation. Checked here, after the
    # transfer is fully committed and its event has fired, so every listener
    # sees consistent territory before anything gets torn down.
    if (old_faction is not None
            and not old_faction.meta.get("regions")
            and not is_eliminated(old_faction)):
        eliminate_faction(world, old_faction_idx, new_faction_idx)


def eliminate_faction(world, dead_idx, conqueror_idx):
    """Retire the faction at `dead_idx`, whose last region has just been
    taken by `conqueror_idx`.

    The faction is tombstoned rather than removed from world.factions --
    see app/world/nation.py's is_eliminated for why that is not optional.
    Its standing assets are then settled:

      * Fixed works in progress (roads, settlements, shipyards, granaries,
        warehouses, wildland claims) pass to the conqueror, who now holds
        the ground they are being built on.
      * Trade routes and part-built trade routes are re-pointed at the
        conqueror, since the goods still have somewhere to go -- except
        where that would leave a route with the conqueror at BOTH ends,
        which is not a trade route at all and is dropped.
      * Commanders, ships and in-transit caravans are removed. They belong
        to a nation that no longer exists, and unlike a half-built road
        there is no ground for them to pass to.

    Emits 'faction:eliminated' with both factions so the UI can announce it.
    """
    dead = world.factions[dead_idx]
    dead.eliminated = True
    dead.eliminated_by = conqueror_idx
    dead.eliminated_turn = getattr(world, "turn", None)

    # --- mobile assets: removed outright -------------------------------
    dead_ship_ids = {s.id for s in world.ships if s.faction_idx == dead_idx}
    world.ships = [s for s in world.ships if s.faction_idx != dead_idx]
    world.commanders = [c for c in world.commanders if c.faction_idx != dead_idx]
    for cmd in world.commanders:
        # A surviving commander can't still be aboard a ship that just went
        # down with its nation.
        if getattr(cmd, "aboard_ship_id", None) in dead_ship_ids:
            cmd.aboard_ship_id = None
    world.trade_caravans = [c for c in world.trade_caravans
                            if dead_idx not in (c.seller_idx, c.buyer_idx)]

    # --- fixed works in progress: inherited by the conqueror -----------
    for attr in ("road_projects", "settlement_projects", "shipyard_projects",
                 "granary_projects", "warehouse_projects", "claim_projects"):
        for proj in getattr(world, attr, []):
            if proj.faction_idx == dead_idx:
                proj.faction_idx = conqueror_idx

    # --- trade routes: re-pointed, or dropped if they'd self-loop ------
    kept_routes = []
    for route in world.trade_routes:
        a = conqueror_idx if route["a_faction"] == dead_idx else route["a_faction"]
        b = conqueror_idx if route["b_faction"] == dead_idx else route["b_faction"]
        if a == b:
            continue
        route["a_faction"], route["b_faction"] = a, b
        kept_routes.append(route)
    world.trade_routes = kept_routes
    # trade_routes_by_pair is keyed by frozenset({a_idx, b_idx}); the keys we
    # just rewrote are stale, so rebuild it from the surviving routes rather
    # than trying to patch individual entries.
    world.trade_routes_by_pair = {
        frozenset((r["a_faction"], r["b_faction"])): r for r in kept_routes}

    kept_projects = []
    for proj in world.trade_route_projects:
        a = conqueror_idx if proj.a_idx == dead_idx else proj.a_idx
        b = conqueror_idx if proj.b_idx == dead_idx else proj.b_idx
        if a == b:
            continue
        proj.a_idx, proj.b_idx = a, b
        kept_projects.append(proj)
    world.trade_route_projects = kept_projects

    bus.emit("faction:eliminated", {
        "faction": dead, "faction_idx": dead_idx,
        "conqueror": world.factions[conqueror_idx], "conqueror_idx": conqueror_idx})
