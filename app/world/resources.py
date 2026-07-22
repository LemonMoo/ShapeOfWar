"""Fantasy resource economy: what a county produces, driven by its biome,
climate, the current season, and how remote it is from a settlement — plus
the turn loop that makes seasons (and stockpiles) actually advance.

No crafting chains: luxury goods (Spices, Silks, Jewelry) are generated
directly like everything else, not manufactured from raw inputs. Similar
sub-items are aggregated into one resource each (Grain covers wheat/barley/
rice, Wood covers oak/pine/mahogany, Gems covers every gem type, Stone
covers granite/marble/limestone) rather than tracking dozens of near-
identical yields.
"""
from collections import defaultdict

from app.world.lexicon import SPECIES

# --- the resource registry --------------------------------------------------
# category + tier (1 essential ... 4 luxury), per the tiering system.
RESOURCES = {
    "Fresh Water": {"category": "Food", "tier": 1},
    "Grain":       {"category": "Food", "tier": 1},
    "Iron":        {"category": "Metal", "tier": 1},
    "Steel":       {"category": "Metal", "tier": 1},
    "Meat":        {"category": "Food", "tier": 2},
    "Fish":        {"category": "Food", "tier": 2},
    "Wood":        {"category": "Raw Material", "tier": 2},
    "Gems":        {"category": "Mineral", "tier": 2},
    "Stone":       {"category": "Raw Material", "tier": 3},
    "Coal":        {"category": "Mineral", "tier": 3},
    "Textiles":    {"category": "Agricultural", "tier": 3},
    "Spices":      {"category": "Luxury", "tier": 4},
    "Silks":       {"category": "Luxury", "tier": 4},
    "Jewelry":     {"category": "Luxury", "tier": 4},
    "Mithril":     {"category": "Metal", "tier": 4},
}

BIOMES = ["mountain", "forest", "plains", "coastal", "desert", "swamp"]
CLIMATES = ["temperate", "arid", "cold", "humid"]
SEASONS = ["Spring", "Summer", "Autumn", "Winter"]
TURNS_PER_SEASON = 8

# Food/water resources are grown and eaten locally, so they're exempt from
# the remoteness penalty applied to everything else below.
_LOCAL_FOOD = {"Grain", "Meat", "Fish", "Fresh Water"}

# --- geography -> base yield (per cell, before climate/season/distance) ----
BIOME_YIELDS = {
    "mountain": {"Iron": 3.0, "Steel": 1.2, "Coal": 1.0, "Gems": 0.5,
                 "Mithril": 0.04, "Stone": 1.5, "Grain": 0.05, "Jewelry": 0.05},
    "forest":   {"Wood": 3.0, "Meat": 0.9, "Grain": 0.2, "Textiles": 0.1},
    "plains":   {"Grain": 2.5, "Meat": 1.0, "Textiles": 1.0, "Stone": 0.2},
    "coastal":  {"Fish": 2.5, "Fresh Water": 1.0, "Wood": 0.5, "Grain": 0.4,
                 "Silks": 0.15, "Jewelry": 0.05},
    "desert":   {"Gems": 0.8, "Spices": 1.2, "Stone": 0.3, "Grain": 0.03},
    "swamp":    {"Wood": 0.8, "Fresh Water": 0.8, "Fish": 0.3, "Grain": 0.1},
}

# --- climate/season -> per-resource multiplier (missing = 1.0) -------------
CLIMATE_MODIFIERS = {
    "temperate": {},
    "arid": {"Fresh Water": 0.5, "Grain": 0.6, "Meat": 0.7, "Gems": 1.4,
             "Spices": 1.6, "Textiles": 0.8},
    "cold": {"Coal": 1.4, "Wood": 1.2, "Grain": 0.6, "Meat": 0.7,
             "Fish": 0.85, "Fresh Water": 0.9},
    "humid": {"Fish": 1.3, "Wood": 1.3, "Iron": 0.85, "Steel": 0.85,
              "Grain": 1.1, "Textiles": 1.1},
}

SEASON_MODIFIERS = {
    "Spring": {"Grain": 1.3, "Wood": 1.05, "Textiles": 1.1},
    "Summer": {"Grain": 1.6, "Meat": 1.3, "Fish": 1.15, "Spices": 1.1},
    "Autumn": {"Wood": 1.2, "Spices": 1.3, "Textiles": 1.2},
    "Winter": {"Grain": 0.4, "Meat": 0.6, "Fish": 0.7, "Coal": 1.5, "Wood": 0.9},
}


def get_climate_modifier(resource, climate):
    return CLIMATE_MODIFIERS.get(climate, {}).get(resource, 1.0)


def get_seasonal_modifier(resource, season):
    return SEASON_MODIFIERS.get(season, {}).get(resource, 1.0)


# --- biome / climate classification -----------------------------------------
_MOUNTAIN_RELIEF = 0.55     # elevation (0..1 above sea level) that reads as mountains
_COASTAL_REACH = 3          # cells from open water that still count as coastal
_DESERT_MOISTURE = 0.32
_SWAMP_MOISTURE = 0.68
_SWAMP_RELIEF_MAX = 0.18
_SWAMP_WATER_REACH = 3
_FOREST_MOISTURE = 0.5

_COLD_TEMP = 0.32           # latitude "temperature" (0..1) below which climate is cold
_ARID_MOISTURE = 0.35
_HUMID_MOISTURE = 0.65


def classify_biome(relief, moisture, coast_dist, water_dist):
    """relief: 0..1 elevation above sea level. moisture: 0..1 rainfall noise.
    coast_dist/water_dist: cells to the nearest ocean / river-or-lake."""
    if relief > _MOUNTAIN_RELIEF:
        return "mountain"
    if coast_dist <= _COASTAL_REACH:
        return "coastal"
    if moisture < _DESERT_MOISTURE:
        return "desert"
    if (moisture > _SWAMP_MOISTURE and relief < _SWAMP_RELIEF_MAX
            and water_dist <= _SWAMP_WATER_REACH):
        return "swamp"
    if moisture > _FOREST_MOISTURE:
        return "forest"
    return "plains"


def classify_climate(latitude_temp, moisture):
    """latitude_temp: 0..1, warm at the map's vertical middle, cold at the
    top/bottom edges (a stand-in for a real latitude/pole system)."""
    if latitude_temp < _COLD_TEMP:
        return "cold"
    if moisture < _ARID_MOISTURE:
        return "arid"
    if moisture > _HUMID_MOISTURE:
        return "humid"
    return "temperate"


# --- per-turn yield ----------------------------------------------------------
# Non-food resources are harder to get to market from remote counties; food
# is grown and eaten locally so it's unaffected by distance from a settlement.
_REMOTE_MIN = 0.55
_REMOTE_SPAN = 0.45


def compute_county_yield(county, season):
    """This county's resource production for `season`, using its cached
    (static) biome_counts/dominant_climate/settle_proximity plus villages'
    farm output (folded into Grain) — everything geography contributes,
    modulated by climate and the current season."""
    raw = defaultdict(float)
    for biome, count in getattr(county, "biome_counts", {}).items():
        for resource, weight in BIOME_YIELDS.get(biome, {}).items():
            raw[resource] += weight * count
    raw["Grain"] += getattr(county, "village_grain_base", 0)

    climate = getattr(county, "dominant_climate", "temperate")
    proximity = getattr(county, "settle_proximity", 0.5)
    remote_factor = _REMOTE_MIN + _REMOTE_SPAN * proximity

    result = {}
    for resource, amount in raw.items():
        amount *= get_climate_modifier(resource, climate)
        amount *= get_seasonal_modifier(resource, season)
        if resource not in _LOCAL_FOOD:
            amount *= remote_factor
        amount = round(amount)
        if amount:
            result[resource] = amount
    return result


# --- storage caps + spoilage: without these, stockpiles pile up forever ----
# Cap scales with empire size (more settlements = more warehouse capacity);
# overflow production is simply lost rather than banked, no event/warning.
STORAGE_CAP_BASE = {1: 6000, 2: 4000, 3: 5000, 4: 1000}   # by RESOURCES[r]["tier"]
STORAGE_CAP_SCALE_PER_SETTLEMENT = 0.1
_DEFAULT_CAP_BASE = 3000

# Perishables rot in storage even under cap; everything else defaults to 0.
SPOILAGE_RATE = {
    "Fresh Water": 0.15,
    "Grain": 0.08,
    "Meat": 0.30,
    "Fish": 0.30,
    "Spices": 0.05,
}


def _storage_cap(nation, resource):
    tier = RESOURCES.get(resource, {}).get("tier", 3)
    base = STORAGE_CAP_BASE.get(tier, _DEFAULT_CAP_BASE)
    n_settlements = len(nation.meta.get("settlements", []))
    return base * (1 + STORAGE_CAP_SCALE_PER_SETTLEMENT * n_settlements)


def _apply_spoilage(res):
    for resource in list(res.keys()):
        rate = SPOILAGE_RATE.get(resource, 0.0)
        if rate:
            res[resource] = int(res[resource] * (1 - rate))


def _clamp_to_storage(nation):
    res = nation.stats.get("resources", {})
    for resource in list(res.keys()):
        cap = _storage_cap(nation, resource)
        if res[resource] > cap:
            res[resource] = int(cap)


# --- military, derived from war-relevant stockpiles -------------------------
def _recompute_military(nation):
    species = SPECIES.get(nation.meta.get("species"), {})
    res = nation.stats.get("resources", {})
    cells = nation.meta.get("cells", 0)
    iron_bonus = min(25, res.get("Iron", 0) / 40)
    steel_bonus = min(20, res.get("Steel", 0) / 30)
    grain_shortage = 15 if res.get("Grain", 0) <= 0 else 0
    water_shortage = 10 if res.get("Fresh Water", 0) <= 0 else 0
    military = (30 + min(20, cells / 40) + iron_bonus + steel_bonus
                + species.get("mil", 0) - grain_shortage - water_shortage)
    nation.stats["military"] = max(15, min(99, int(military)))


# --- turn loop ---------------------------------------------------------------
_STARTING_STOCKPILE_TURNS = 6   # turns' worth of production seeded at gen time


def seed_initial_stockpiles(world):
    """Called once at world-gen (after counties/settlements/villages exist):
    gives every faction a starting reserve instead of an empty treasury, and
    sets each faction's initial military from it."""
    for nation in world.factions:
        nation.stats["resources"] = {}
        nation.stats["gold"] = 0
    for county in world.counties:
        if county.faction_idx < 0:      # UNCLAIMED — no faction to seed
            continue
        nation = world.factions[county.faction_idx]
        county.resources = compute_county_yield(county, world.season)
        res = nation.stats["resources"]
        for resource, amount in county.resources.items():
            res[resource] = res.get(resource, 0) + amount * _STARTING_STOCKPILE_TURNS
    for nation in world.factions:
        tax_per_turn = sum(world.settlements[sid].tax_income
                           for sid in nation.meta.get("settlements", []))
        nation.stats["gold"] = tax_per_turn * _STARTING_STOCKPILE_TURNS
        _clamp_to_storage(nation)     # the seeded reserve mustn't itself exceed the cap
        _recompute_military(nation)


def advance_turn(world):
    """The turn loop: cycle the season, recompute every county's yield for
    it, spoil perishables, add production to each faction's stockpile,
    subtract settlement upkeep, clamp to storage capacity (so nothing piles
    up forever), and recompute military from the new stockpiles."""
    world.turn += 1
    world.season = SEASONS[((world.turn - 1) // TURNS_PER_SEASON) % len(SEASONS)]

    production = defaultdict(lambda: defaultdict(int))
    for county in world.counties:
        county.resources = compute_county_yield(county, world.season)
        fac_res = production[county.faction_idx]
        for resource, amount in county.resources.items():
            fac_res[resource] += amount

    for fac_idx, nation in enumerate(world.factions):
        res = nation.stats.setdefault("resources", {})
        _apply_spoilage(res)
        for resource, amount in production.get(fac_idx, {}).items():
            res[resource] = int(res.get(resource, 0) + amount)
        gold_income = 0
        for sid in nation.meta.get("settlements", []):
            settlement = world.settlements[sid]
            for resource, amount in settlement.upkeep.items():
                res[resource] = max(0, int(res.get(resource, 0) - amount))
            gold_income += settlement.tax_income
        nation.stats["gold"] = nation.stats.get("gold", 0) + gold_income
        _clamp_to_storage(nation)
        _recompute_military(nation)

    # Autonomous trade (app/world/trade.py): move existing caravans first —
    # freeing a faction's trade "slot" on delivery — then let factions
    # dispatch new ones, so a freed slot can be reused the same turn.
    # Events are stashed on `world` for the UI to turn into player-facing
    # messages (see map_view.py) without resources.py needing to know
    # anything about panels/banners.
    from app.world import trade
    trade.advance_trade_route_projects(world)   # land routes under construction
    events = trade.advance_caravans(world)
    events += trade.run_trade_ai(world)
    events += trade.run_trade_route_ai(world)   # AI proposes new routes
    world.trade_events = events

    # Player-built castles + their connecting roads (app/world/construction.py).
    from app.world import construction
    construction.advance_projects(world)
    construction.advance_shipyard_projects(world)

    # Progressive expansion: claims-in-progress on UNCLAIMED land
    # (app/world/expansion.py).
    from app.world import expansion
    expansion.advance_claims(world)

    # Commanders: walk any active move order, count down ship construction
    # (app/world/commander.py) — before vision.recompute so this turn's
    # movement is reflected in this turn's fog reveal, not one turn late.
    from app.world import commander
    commander.advance_commanders(world)

    # Fog of war: reveal whatever's now in range as territory changes hands
    # (app/world/vision.py).
    from app.world import vision
    vision.recompute(world)
