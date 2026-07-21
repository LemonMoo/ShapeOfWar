"""Territory transfer: moving a county (and everything in it) from one
faction to another when a battle is won, keeping every ownership/aggregate
data structure on the World consistent.
"""
import random

from app.core.events import bus
from app.world.world_map import Stance
from app.world.worldgen import OCEAN

_NEIGH4 = ((1, 0), (-1, 0), (0, 1), (0, -1))


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

    gen = county.stats.get("res_gen", 0)
    drain = county.stats.get("res_drain", 0)
    crops = county.stats.get("crops", 0)
    old_faction.stats["res_gen"] = old_faction.stats.get("res_gen", 0) - gen
    old_faction.stats["res_drain"] = old_faction.stats.get("res_drain", 0) - drain
    old_faction.stats["crops"] = old_faction.stats.get("crops", 0) - crops
    new_faction.stats["res_gen"] = new_faction.stats.get("res_gen", 0) + gen
    new_faction.stats["res_drain"] = new_faction.stats.get("res_drain", 0) + drain
    new_faction.stats["crops"] = new_faction.stats.get("crops", 0) + crops

    _recompute_faction_totals(world, old_faction, old_faction_idx)
    _recompute_faction_totals(world, new_faction, new_faction_idx)
    _refresh_borders(world, county, rng)

    bus.emit("county:transferred", {"county": county, "old_faction": old_faction,
                                     "new_faction": new_faction})
