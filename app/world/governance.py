"""Government forms and realm loyalty.

Slice 1 (observation-only) answered two questions as pure functions. Slices
2-5 make loyalty a live, stored value that moves with how well a realm's
behavior matches what its government's people want, and that feeds back into
the economy, the army, how much land a realm can govern, and -- at the bottom
-- whether regions revolt and break away.

  government_form / government_loyalty -- the realm's current form and loyalty
  apply_loyalty_drift(world)          -- ease loyalty toward its target (slice 2)
  reform_government(world, fac, form) -- switch form at a loyalty cost (slice 2)
  loyalty_effect_mult(world, fac)     -- 0.6..1.4 the economy/army read (slice 3)
  loyalty_gov_bonus(world, fac)       -- regions added/removed from capacity (slice 4)
  apply_revolts(world)                -- low loyalty flips frontier regions (slice 5)

The forms and the species-affinity tables live in app/world/lexicon.py
(GOVERNMENT_FORMS / SPECIES_GOVERNMENT_AFFINITY / DEFAULT_GOVERNMENT).

Every signal this module reads is a number the sim already tracks (military,
trade routes, cathedral share, claim overstretch), so a given save always
scores the same way -- the "measure once" rule. The drift itself is the one
mutation, applied once per turn from resources.day_steps.
"""
import random

from app.world.lexicon import (GOVERNMENT_FORMS, DEFAULT_GOVERNMENT,
                               SPECIES_GOVERNMENT_AFFINITY)

# First-pass values, judge-in-play (GOVERNANCE_PLAN.md §7).
LOYALTY_BASE = 50
LOYALTY_AFFINITY_WEIGHT = 10      # affinity -2..+2 -> a 30..70 band
LOYALTY_FLOOR = 15                # matches the game's existing morale floor
LOYALTY_CEIL = 99

LOYALTY_EASE = 0.02               # fraction of the gap to target closed per turn
BEHAVIOR_WEIGHT = 10.0            # max +/- loyalty from behavior match
REFORM_COST_PER_STEP = 8          # loyalty lost per affinity step crossed
REFORM_MIN_COST = 6               # even a same-affinity reform costs this

LOYALTY_EFFECT_RANGE = 0.4        # loyalty effect mult spans 1.0 +/- 0.4 (0.6..1.4)
LOYALTY_GOV_STEP = 20             # one region of governance per 20 loyalty points

REVOLT_LOYALTY_FLOOR = 25         # below this, frontier regions may secede
REVOLT_CHANCE_PER_POINT = 0.004   # per-turn chance, per point below the floor


def government_form(world, fac_idx):
    """The realm's current government form key (a GOVERNMENT_FORMS key).

    Read through the nation's meta (a free-form dict), falling back to the
    species' DEFAULT_GOVERNMENT for saves written before governance existed --
    the same getattr-default pattern as nation.is_eliminated."""
    nation = world.factions[fac_idx]
    meta = nation.meta or {}
    form = meta.get("government")
    if form in GOVERNMENT_FORMS:
        return form
    return DEFAULT_GOVERNMENT.get(meta.get("species", "Humans"), "monarchy")


def government_name(world, fac_idx):
    """Display name of the realm's current government form."""
    return GOVERNMENT_FORMS[government_form(world, fac_idx)]["name"]


def species_government_affinity(species, form):
    """-2..+2: how readily `species` accepts `form` (0 for unknown pairs)."""
    return SPECIES_GOVERNMENT_AFFINITY.get(species, {}).get(form, 0)


def base_loyalty_for(species, form):
    """The loyalty a realm of `species` STARTS at under `form` -- the pure
    affinity term, before behavior drift or reform costs."""
    return max(LOYALTY_FLOOR, min(LOYALTY_CEIL,
               LOYALTY_BASE + species_government_affinity(species, form)
               * LOYALTY_AFFINITY_WEIGHT))


def base_loyalty(world, fac_idx):
    nation = world.factions[fac_idx]
    species = (nation.meta or {}).get("species", "Humans")
    return base_loyalty_for(species, government_form(world, fac_idx))


def government_loyalty(world, fac_idx):
    """0..100: the realm's current loyalty (stored, drifted) toward its form.

    Falls back to the pure base for old saves or a realm that hasn't run a
    day yet -- loyalty only becomes a stored value once drift has touched it."""
    nation = world.factions[fac_idx]
    stored = (nation.stats or {}).get("loyalty")
    return stored if stored is not None else base_loyalty(world, fac_idx)


def loyalty_effect_mult(world, fac_idx):
    """0.6..1.4, 1.0 at loyalty 50: the single multiplier the economy and
    army read. A loyal realm out-produces and out-musters a disloyal one."""
    loyalty = government_loyalty(world, fac_idx)
    if loyalty >= LOYALTY_BASE:
        return 1.0 + LOYALTY_EFFECT_RANGE * (loyalty - LOYALTY_BASE) \
               / (LOYALTY_CEIL - LOYALTY_BASE)
    return 1.0 - LOYALTY_EFFECT_RANGE * (LOYALTY_BASE - loyalty) \
           / (LOYALTY_BASE - LOYALTY_FLOOR)


def loyalty_gov_bonus(world, fac_idx):
    """Regions added to (or, when negative, removed from) a realm's
    governance capacity -- a loyal realm holds its land well."""
    return int((government_loyalty(world, fac_idx) - LOYALTY_BASE)
               // LOYALTY_GOV_STEP)


# --- behavior match (slice 2) -----------------------------------------------
def _has_trade_route(world, fac_idx):
    return any(fac_idx in (r.get("a_faction"), r.get("b_faction"))
               for r in getattr(world, "trade_routes", ()))


def _cathedral_fraction(world, fac_idx):
    """0..1 share of the faction's settlements that are Cathedrals."""
    from app.world import resources
    sids = world.factions[fac_idx].meta.get("settlements", [])
    if not sids:
        return 0.0
    n = sum(1 for sid in sids
            if resources.settlement_character(world.settlements[sid]) == "cathedral")
    return n / len(sids)


def _behavior_signals(world, fac_idx):
    """The four policy axes, each normalised to -1..+1, read from the sim's
    own tracked numbers -- nothing new to record, nothing random."""
    from app.world import progression
    nation = world.factions[fac_idx]
    military = nation.stats.get("military", LOYALTY_BASE)
    mil_sig = max(-1.0, min(1.0, (military - LOYALTY_BASE) / 50.0))
    trade_sig = 1.0 if _has_trade_route(world, fac_idx) else -1.0
    faith_sig = 2.0 * _cathedral_fraction(world, fac_idx) - 1.0
    over = progression.claim_overstretch(world, fac_idx)
    exp_sig = max(-1.0, min(1.0, 2.0 * min(1.0, over / 3.0) - 1.0))
    return {"military": mil_sig, "trade": trade_sig,
            "faith": faith_sig, "expansion": exp_sig}


def behavior_delta(world, fac_idx):
    """-BEHAVIOR_WEIGHT..+BEHAVIOR_WEIGHT: how much the realm's actual
    behavior pleases (+ve) or offends (-ve) its current government's people."""
    wants = GOVERNMENT_FORMS[government_form(world, fac_idx)].get("wants", {})
    if not wants:
        return 0.0
    sig = _behavior_signals(world, fac_idx)
    total = sum(wants.get(axis, 0.0) * sig.get(axis, 0.0) for axis in wants)
    mean = total / len(wants)
    return max(-BEHAVIOR_WEIGHT, min(BEHAVIOR_WEIGHT, mean * BEHAVIOR_WEIGHT))


def loyalty_target(world, fac_idx):
    """Where loyalty is easing toward this turn: base affinity + behavior."""
    return max(LOYALTY_FLOOR, min(LOYALTY_CEIL,
               base_loyalty(world, fac_idx) + behavior_delta(world, fac_idx)))


def apply_loyalty_drift(world):
    """One turn of easing every live faction's loyalty toward its target.
    Called once per day from resources.day_steps. Loyalty is stored as a
    float (like a prosperity meter), so a slow ease still accumulates."""
    from app.world.nation import is_eliminated
    for fac_idx, nation in enumerate(world.factions):
        if is_eliminated(nation):
            continue
        current = government_loyalty(world, fac_idx)
        target = loyalty_target(world, fac_idx)
        next_l = current + (target - current) * LOYALTY_EASE
        nation.stats["loyalty"] = max(LOYALTY_FLOOR, min(LOYALTY_CEIL, next_l))


# --- reform (slice 2) -------------------------------------------------------
def reform_cost(world, fac_idx, new_form):
    """Loyalty a reform to `new_form` would cost: scaled by how far the
    species' affinity moves, with a floor so even a swap between two
    equally-liked forms is a real decision."""
    species = (world.factions[fac_idx].meta or {}).get("species", "Humans")
    steps = abs(species_government_affinity(species, new_form)
                - species_government_affinity(species, government_form(world, fac_idx)))
    return max(REFORM_MIN_COST, REFORM_COST_PER_STEP * steps)


def reform_government(world, fac_idx, new_form):
    """Switch a realm's government form at a loyalty cost. Returns the
    player-facing message. Does nothing (and says why) if the form is
    unknown or already current."""
    if new_form not in GOVERNMENT_FORMS:
        return f"No such form of government: {new_form}."
    nation = world.factions[fac_idx]
    nation.meta = nation.meta or {}
    old = government_form(world, fac_idx)
    if new_form == old:
        return f"The realm already follows {GOVERNMENT_FORMS[old]['name']}."
    cost = reform_cost(world, fac_idx, new_form)
    loyalty = government_loyalty(world, fac_idx)
    new_loyalty = max(LOYALTY_FLOOR, loyalty - cost)
    nation.meta["government"] = new_form
    nation.stats["loyalty"] = new_loyalty
    from app.world import chronicle
    chronicle.log(world, nation,
                  f"The realm reforms from {GOVERNMENT_FORMS[old]['name']} to "
                  f"{GOVERNMENT_FORMS[new_form]['name']} "
                  f"(loyalty {round(loyalty)} -> {round(new_loyalty)}).")
    return (f"Reformed to {GOVERNMENT_FORMS[new_form]['name']}. "
            f"Loyalty {round(loyalty)} -> {round(new_loyalty)}.")


# --- revolt / secession (slice 5) ------------------------------------------
def secede_region(world, region, fac_idx):
    """A region breaks away: it returns to UNCLAIMED wildland, and its
    settlements and villages are neutralized (faction_idx < 0, the same
    "demoted" state construction.py already leaves behind). Safe on either
    layer (surface grid vs under_owner)."""
    from app.world import layers as L
    from app.world.territory import mark_cells_dirty, _recompute_faction_totals, _refresh_borders
    from app.world.worldgen import UNCLAIMED
    from app.world import chronicle

    nation = world.factions[fac_idx]
    if L.is_under(region):
        for x, y in region.cells:
            L.set_owner_at(world, x, y, L.UNDER, UNCLAIMED)
    else:
        for x, y in region.cells:
            world.owner[y][x] = UNCLAIMED
    region.faction_idx = UNCLAIMED
    world.territory_version = getattr(world, "territory_version", 0) + 1
    mark_cells_dirty(world, region.cells)

    for sid in list(getattr(region, "meta_settlements", [])):
        world.settlements[sid].faction_idx = -1
        if sid in nation.meta.get("settlements", []):
            nation.meta["settlements"].remove(sid)
    for vid in list(getattr(region, "villages", [])):
        world.villages[vid].faction_idx = -1
    region.meta_settlements = []
    region.villages = []

    regions = nation.meta.setdefault("regions", [])
    if region.id in regions:
        regions.remove(region.id)

    _recompute_faction_totals(world, nation, fac_idx)
    _refresh_borders(world, region)
    chronicle.log(world, nation,
                  f"{region.name} rises in revolt and breaks away from the realm.")


def apply_revolts(world):
    """Low loyalty makes frontier regions secede. At most one region per
    faction per turn; the chance scales with how far loyalty is below
    REVOLT_LOYALTY_FLOOR. Deterministic (seeded from the world's seed)."""
    from app.world.nation import is_eliminated
    rng = getattr(world, "_revolt_rng", None)
    if rng is None:
        rng = world._revolt_rng = random.Random(
            (int(getattr(world, "seed", 0) or 0) ^ 0x7E21) & 0x7FFFFFFF)
    seceded = []
    for fac_idx, nation in enumerate(world.factions):
        if is_eliminated(nation):
            continue
        loyalty = government_loyalty(world, fac_idx)
        if loyalty >= REVOLT_LOYALTY_FLOOR:
            continue
        capital = nation.meta.get("capital")
        owned = [rid for rid in nation.meta.get("regions", [])
                 if rid != capital and world.regions[rid].faction_idx == fac_idx]
        if not owned:
            continue
        p = min(0.5, REVOLT_CHANCE_PER_POINT * (REVOLT_LOYALTY_FLOOR - loyalty))
        if rng.random() >= p:
            continue
        region = world.regions[owned[-1]]   # the frontier-most region held
        secede_region(world, region, fac_idx)
        seceded.append((fac_idx, region))
    world.last_revolts = seceded
    return seceded
