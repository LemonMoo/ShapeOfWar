"""Territory transfer: moving a county (and everything in it) from one
faction to another when a battle is won, keeping every ownership/aggregate
data structure on the World consistent.
"""
import math
import random

from app.core.events import bus
from app.world.world_map import Stance
from app.world.worldgen import OCEAN, _bfs_distance

_NEIGH4 = ((1, 0), (-1, 0), (0, 1), (0, -1))
_NAVAL_COAST_REACH = 3   # same reach as the trade-route coastal test in worldgen.py


def _recompute_settle_proximity(world, county):
    """A conquered county's nearest settlement may now belong to a
    different owner, so its remoteness (and thus next turn's non-food
    resource yields — see app/world/resources.py) needs updating. Uses
    straight-line distance to the nearest settlement rather than a full
    grid BFS — cheap enough for a single county on a rare, player-
    triggered conquest, unlike the full-map BFS done once at generation."""
    if not world.settlements:
        county.settle_proximity = 0.5
        return
    cx = sum(x for x, y in county.cells) / len(county.cells)
    cy = sum(y for x, y in county.cells) / len(county.cells)
    best = min(math.hypot(cx - sx, cy - sy) for sx, sy in
               (st.pos for st in world.settlements))
    county.settle_proximity = math.exp(-best / 10.0)


def bordering_counties(world, attacker_idx, defender_idx):
    """Counties owned by `defender_idx` that share at least one cell edge
    with land owned by `attacker_idx` — the frontline, and the only
    territory that can realistically change hands from a single battle."""
    out = []
    for county in world.counties:
        if county.faction_idx != defender_idx:
            continue
        for x, y in county.cells:
            for dx, dy in _NEIGH4:
                nx, ny = x + dx, y + dy
                if (0 <= nx < world.w and 0 <= ny < world.h
                        and world.owner[ny][nx] == attacker_idx):
                    out.append(county)
                    break
            else:
                continue
            break
    return out


def naval_reachable_counties(world, attacker_idx, defender_idx):
    """Defender's coastal counties, reachable by sea IF the attacker owns at
    least one coastal settlement (a port) — the fallback used when
    bordering_counties is empty (no land connection at all), so an
    overseas/island enemy can still be invaded.

    Simplification: this only checks that both sides have *some* coastline,
    not that they're on the same connected ocean body — fine for this
    generator (one continents-in-one-ocean landmass; edges always sink
    underwater), but would need a real flood-fill check on a world with
    multiple disconnected seas."""
    ocean_cells = [(x, y) for y in range(world.h) for x in range(world.w)
                   if world.owner[y][x] == OCEAN]
    if not ocean_cells:
        return []
    coast_d = _bfs_distance(world, ocean_cells)

    def is_coastal(pos):
        x, y = pos
        return coast_d[y][x] <= _NAVAL_COAST_REACH

    has_port = any(is_coastal(st.pos) for st in world.settlements
                   if st.faction_idx == attacker_idx)
    if not has_port:
        return []

    return [county for county in world.counties
            if county.faction_idx == defender_idx
            and any(is_coastal((x, y)) for x, y in county.cells)]


def _refresh_borders(world, county, rng):
    """After a county changes hands, roll a fresh relationship for any
    faction pair that's newly touching along its border. Existing
    relationships (between factions that still share other territory, or
    that were already at war/allied) are left untouched."""
    pairs = set()
    for x, y in county.cells:
        o = world.owner[y][x]
        for dx, dy in _NEIGH4:
            nx, ny = x + dx, y + dy
            if not (0 <= nx < world.w and 0 <= ny < world.h):
                continue
            o2 = world.owner[ny][nx]
            if o2 != OCEAN and o2 != o:
                pairs.add((min(o, o2), max(o, o2)))

    for a, b in pairs:
        na, nb = world.factions[a], world.factions[b]
        key = frozenset((na.id, nb.id))
        if key in world.world_map.relationships:
            continue
        same = na.meta.get("species") == nb.meta.get("species")
        r = rng.random()
        if same:
            stance = Stance.ALLY if r < 0.7 else Stance.NEUTRAL
        else:
            stance = (Stance.ENEMY if r < 0.55 else
                      Stance.NEUTRAL if r < 0.85 else Stance.ALLY)
        tension = {Stance.ENEMY: rng.randint(40, 85),
                   Stance.NEUTRAL: rng.randint(10, 40),
                   Stance.ALLY: 0}[stance]
        world.world_map.set_relationship(na.id, nb.id, stance, tension)


def _recompute_faction_totals(world, faction, faction_idx):
    """Recompute a faction's cell count / avg fertility / bbox from its
    (mutated) county list, rather than trying to incrementally un-average."""
    cids = faction.meta.get("counties", [])
    cells = sum(world.counties[cid].stats["area"] for cid in cids)
    fert_sum = sum(world.counties[cid].stats["area"]
                   * world.counties[cid].stats["fertility"] for cid in cids)
    faction.meta["cells"] = cells
    faction.meta["fertility"] = round(fert_sum / cells) if cells else 0

    xs, ys = [], []
    for cid in cids:
        for x, y in world.counties[cid].cells:
            xs.append(x)
            ys.append(y)
    if xs:
        faction.meta["bbox"] = (min(xs), min(ys), max(xs) + 1, max(ys) + 1)


def transfer_county(world, county, new_faction_idx, rng=None):
    """Move `county` (and every settlement/village in it) to
    `new_faction_idx`. Updates grid ownership, per-county/settlement/village
    owner fields, both factions' meta lists and resource/crop aggregates,
    bounding boxes, and rolls fresh relationships for any newly-adjacent
    faction pair. Emits 'county:transferred' when done."""
    rng = rng or random
    old_faction_idx = county.faction_idx
    if old_faction_idx == new_faction_idx:
        return
    old_faction = world.factions[old_faction_idx]
    new_faction = world.factions[new_faction_idx]

    for x, y in county.cells:
        world.owner[y][x] = new_faction_idx
    county.faction_idx = new_faction_idx

    settlement_ids = list(getattr(county, "meta_settlements", []))
    for sid in settlement_ids:
        world.settlements[sid].faction_idx = new_faction_idx
    village_ids = list(getattr(county, "villages", []))
    for vid in village_ids:
        world.villages[vid].faction_idx = new_faction_idx

    old_counties = old_faction.meta.setdefault("counties", [])
    new_counties = new_faction.meta.setdefault("counties", [])
    if county.id in old_counties:
        old_counties.remove(county.id)
    new_counties.append(county.id)

    old_settlements = old_faction.meta.setdefault("settlements", [])
    new_settlements = new_faction.meta.setdefault("settlements", [])
    for sid in settlement_ids:
        if sid in old_settlements:
            old_settlements.remove(sid)
        new_settlements.append(sid)

    # Move this county's most recent turn's yield out of the old faction's
    # stockpile and into the new one's (military isn't recomputed here —
    # like the resource move itself, that happens on the next End Turn).
    old_res = old_faction.stats.setdefault("resources", {})
    new_res = new_faction.stats.setdefault("resources", {})
    for resource, amount in county.resources.items():
        old_res[resource] = max(0, old_res.get(resource, 0) - amount)
        new_res[resource] = new_res.get(resource, 0) + amount

    _recompute_faction_totals(world, old_faction, old_faction_idx)
    _recompute_faction_totals(world, new_faction, new_faction_idx)
    _recompute_settle_proximity(world, county)
    _refresh_borders(world, county, rng)

    bus.emit("county:transferred", {"county": county, "old_faction": old_faction,
                                     "new_faction": new_faction})
