"""Fantasy resource economy: what a region produces, driven by its biome,
climate, the current season, and how remote it is from a settlement — plus
the turn loop that makes seasons (and stockpiles) actually advance.

No crafting chains: luxury goods (Spices, Silks, Jewelry) are generated
directly like everything else, not manufactured from raw inputs. Similar
sub-items are aggregated into one resource each (Grain covers wheat/barley/
rice, Wood covers oak/pine/mahogany, Gems covers every gem type, Stone
covers granite/marble/limestone) rather than tracking dozens of near-
identical yields.
"""
import random
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

# Gold-equivalent value per unit, by tier -- the shared "how much is this
# actually worth" reference used both for trade pricing (app/world/trade.py)
# and for settlement prosperity (see resource_value()/goods_wealth_value()
# below). Lives here, not in trade.py, since resources.py is the module
# every other economy module already imports RESOURCES from.
BASE_VALUE_BY_TIER = {1: 2, 2: 4, 3: 3, 4: 12}   # gold/unit before scarcity

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
# Non-food resources are harder to get to market from remote regions; food
# is grown and eaten locally so it's unaffected by distance from a settlement.
_REMOTE_MIN = 0.55
_REMOTE_SPAN = 0.45


def compute_region_yield(region, season):
    """This region's resource production for `season`, using its cached
    (static) biome_counts/dominant_climate/settle_proximity plus villages'
    farm output (folded into Grain) — everything geography contributes,
    modulated by climate and the current season."""
    raw = defaultdict(float)
    for biome, count in getattr(region, "biome_counts", {}).items():
        for resource, weight in BIOME_YIELDS.get(biome, {}).items():
            raw[resource] += weight * count
    raw["Grain"] += getattr(region, "village_grain_base", 0)

    climate = getattr(region, "dominant_climate", "temperate")
    proximity = getattr(region, "settle_proximity", 0.5)
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


# --- prosperity: a meter/bar per settlement, driven by the value of goods
# it handles/produces and gold it brings in, that visibly rises and falls
# with how well its whole faction's economy is doing turn to turn (not a
# static score off numbers that never change once rolled) -------------------
PROSPERITY_MAX = 100.0
PROSPERITY_STARTING = 0.0       # every settlement/village starts with none — it's earned
PROSPERITY_VALUE_CEIL = 140.0   # goods+wealth gold-value at which prosperity hits 100
# Fraction of the gap to target closed each turn -- deliberately slow, so a
# meter is a long-term payoff (~90% of the way to a steady target takes
# roughly 230 turns / ~7 in-game years at TURNS_PER_SEASON=8), not something
# that fills up within the first few turns of a new settlement's life.
PROSPERITY_EASE = 0.01


def resource_value(resource, amount):
    """Gold-equivalent value of `amount` units of `resource` — the tier
    pricing every trade deal already uses (app/world/trade.py), reused here
    so "value of goods" means the same thing everywhere in the economy."""
    tier = RESOURCES.get(resource, {}).get("tier", 3)
    return amount * BASE_VALUE_BY_TIER.get(tier, 3)


def _resource_bundle_value(resource_amounts):
    return sum(resource_value(r, a) for r, a in resource_amounts.items())


def settlement_goods_wealth_value(upkeep, tax_income):
    """A city/castle/town's per-turn "goods & wealth" figure: the gold-
    value of the resources it handles (upkeep) plus the gold it brings in
    (tax_income)."""
    return _resource_bundle_value(upkeep) + tax_income


def village_goods_wealth_value(farm_output):
    """A village's per-turn "goods" figure: the gold-value of the Grain it
    produces — villages carry no upkeep/tax of their own (see Village)."""
    return resource_value("Grain", farm_output)


def _prosperity_target(raw_value, health_factor):
    return max(0.0, min(PROSPERITY_MAX,
                        PROSPERITY_MAX * raw_value * health_factor / PROSPERITY_VALUE_CEIL))


def seed_prosperity():
    """Starting meter fill for a brand-new settlement/village — empty.
    Prosperity is something a settlement builds up over a long stretch of
    turns (see PROSPERITY_EASE), not a number it's born with."""
    return PROSPERITY_STARTING


def _faction_health_factor(production_value, upkeep_value, gold_income):
    """>1 when a faction produced more value (+ gold income) than its
    settlements drained this turn, <1 when it's running a deficit — the
    thing that actually makes every one of its settlements' prosperity
    meters rise or fall over time, on top of each settlement's own goods/
    wealth value."""
    if upkeep_value <= 0:
        return 1.0
    return max(0.5, min(1.5, (production_value + gold_income) / upkeep_value))


def _update_prosperity(world, production_value, upkeep_value, gold_income):
    """Ease every settlement's and village's prosperity meter toward this
    turn's target — called once per turn from advance_turn, after
    production/upkeep/gold for every faction is known."""
    villages_by_fac = defaultdict(list)
    for v in world.villages:
        villages_by_fac[v.faction_idx].append(v)

    for fac_idx, nation in enumerate(world.factions):
        health = _faction_health_factor(production_value.get(fac_idx, 0.0),
                                        upkeep_value.get(fac_idx, 0.0),
                                        gold_income.get(fac_idx, 0.0))
        for sid in nation.meta.get("settlements", []):
            st = world.settlements[sid]
            target = _prosperity_target(
                settlement_goods_wealth_value(st.upkeep, st.tax_income), health)
            st.prosperity += (target - st.prosperity) * PROSPERITY_EASE
        for v in villages_by_fac.get(fac_idx, []):
            target = _prosperity_target(village_goods_wealth_value(v.farm_output), health)
            v.prosperity += (target - v.prosperity) * PROSPERITY_EASE


# --- city-driven village growth: a city with a full prosperity meter -------
# spawns a new village nearby and resets to 0. A whole city's worth of
# accumulated goods/wealth going into founding one farming village, not
# something that happens often — matches how slowly PROSPERITY_EASE fills
# the meter in the first place.
CITY_VILLAGE_GROWTH_RADIUS = 20     # cells around the city searched for a site
CITY_VILLAGE_MIN_SPACING = (5.0, 7.0)   # cells -- rolled once per attempt; a site must
                                          # be at least this far from every existing
                                          # settlement, village, and road cell
_PROSPERITY_FULL_EPSILON = 0.1      # "filled all the way up" -- close enough that the
                                     # asymptotic ease curve doesn't have to hit 100.0 exactly


def _nearby_road_cells(world, center, radius):
    """Every cell any road segment passes through within roughly `radius`
    of `center`, rasterized the same way map_view._river_span walks a
    straight segment (no UI dependency here, just the geometry) — so a
    city-grown village keeps clear of roads, not just settlements/villages."""
    cx, cy = center
    reach2 = (radius + 5) ** 2
    cells = set()
    for segs in world.roads_by_region.values():
        for (ax, ay), (bx, by), _tier in segs:
            if ((ax - cx) ** 2 + (ay - cy) ** 2 > reach2
                    and (bx - cx) ** 2 + (by - cy) ** 2 > reach2):
                continue   # segment nowhere near the search radius
            dx, dy = bx - ax, by - ay
            steps = max(abs(dx), abs(dy), 1)
            for i in range(steps + 1):
                cells.add((round(ax + dx * i / steps), round(ay + dy * i / steps)))
    return cells


def _find_city_village_site(world, city):
    """A land cell owned by the city's own faction, within
    CITY_VILLAGE_GROWTH_RADIUS of it, at least CITY_VILLAGE_MIN_SPACING
    cells from every existing settlement/village/road cell — or None if
    the area around this city is already full (see village_growth_maxed)."""
    from app.world.worldgen import _too_close, _occupy

    cx, cy = city.pos
    r = CITY_VILLAGE_GROWTH_RADIUS
    min_dist = random.uniform(*CITY_VILLAGE_MIN_SPACING)

    occupied = {}
    for st in world.settlements:
        _occupy(occupied, *st.pos)
    for v in world.villages:
        _occupy(occupied, *v.pos)
    for x, y in _nearby_road_cells(world, city.pos, r):
        _occupy(occupied, x, y)

    candidates = []
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx * dx + dy * dy > r * r:
                continue
            x, y = cx + dx, cy + dy
            if not (0 <= x < world.w and 0 <= y < world.h):
                continue
            if world.owner[y][x] != city.faction_idx:
                continue
            if (x, y) in world.river_cells or (x, y) in world.lake_cells:
                continue
            if _too_close(occupied, x, y, min_dist):
                continue
            candidates.append((world.fertility[y][x] + random.uniform(0.0, 0.1), x, y))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1], candidates[0][2]


def _grow_city_villages(world):
    """Called once per turn (after prosperity is updated): any city whose
    prosperity meter is completely full spawns a new village nearby and
    resets to 0. villages_spawned is a hidden running counter; once no
    valid site remains within the growth radius, the city permanently
    stops trying (village_growth_maxed) instead of re-scanning for nothing
    every turn thereafter."""
    from app.world.worldgen import (Village, _roll_population, _VILLAGE_FARM_RANGE,
                                    _VILLAGE_FERT_PATCH)
    from app.world.lexicon import make_settlement_namer

    for st in world.settlements:
        if not hasattr(st, "villages_spawned"):   # self-heal an old save
            st.villages_spawned = 0
            st.village_growth_maxed = False
        if (st.kind != "city" or st.village_growth_maxed
                or st.prosperity < PROSPERITY_MAX - _PROSPERITY_FULL_EPSILON):
            continue

        site = _find_city_village_site(world, st)
        if site is None:
            st.village_growth_maxed = True
            continue

        x, y = site
        region_id = world.region_grid[y][x]
        region = world.regions[region_id]
        faction = world.factions[st.faction_idx]
        species = faction.meta.get("species", "Humans")
        namer = make_settlement_namer(random)

        rr = _VILLAGE_FERT_PATCH
        samples = [world.fertility[ny][nx]
                  for ny in range(max(0, y - rr), min(world.h, y + rr + 1))
                  for nx in range(max(0, x - rr), min(world.w, x + rr + 1))
                  if world.region_grid[ny][nx] == region_id]
        local_fert = sum(samples) / len(samples) if samples else world.fertility[y][x]
        farm = round(random.uniform(*_VILLAGE_FARM_RANGE) * (0.5 + 1.2 * local_fert))
        population, adults, children = _roll_population(random, "village")
        prosperity = seed_prosperity()

        v = Village(len(world.villages), region_id, st.faction_idx,
                   namer("village", species), (x, y), farm,
                   population, adults, children, prosperity)
        world.villages.append(v)
        region.villages.append(v.id)
        world.roads_by_region.setdefault(region_id, []).append((st.pos, v.pos, "dirt"))

        st.villages_spawned += 1
        st.prosperity = 0.0


# --- turn loop ---------------------------------------------------------------
_STARTING_STOCKPILE_TURNS = 6   # turns' worth of production seeded at gen time


def seed_initial_stockpiles(world):
    """Called once at world-gen (after regions/settlements/villages exist):
    gives every faction a starting reserve instead of an empty treasury, and
    sets each faction's initial military from it."""
    for nation in world.factions:
        nation.stats["resources"] = {}
        nation.stats["gold"] = 0
    for region in world.regions:
        if region.faction_idx < 0:      # UNCLAIMED — no faction to seed
            continue
        nation = world.factions[region.faction_idx]
        region.resources = compute_region_yield(region, world.season)
        res = nation.stats["resources"]
        for resource, amount in region.resources.items():
            res[resource] = res.get(resource, 0) + amount * _STARTING_STOCKPILE_TURNS
    for nation in world.factions:
        tax_per_turn = sum(world.settlements[sid].tax_income
                           for sid in nation.meta.get("settlements", []))
        nation.stats["gold"] = tax_per_turn * _STARTING_STOCKPILE_TURNS
        _clamp_to_storage(nation)     # the seeded reserve mustn't itself exceed the cap
        _recompute_military(nation)


def advance_turn(world):
    """The turn loop: cycle the season, recompute every region's yield for
    it, spoil perishables, add production to each faction's stockpile,
    subtract settlement upkeep, clamp to storage capacity (so nothing piles
    up forever), and recompute military from the new stockpiles."""
    world.turn += 1
    world.season = SEASONS[((world.turn - 1) // TURNS_PER_SEASON) % len(SEASONS)]

    production = defaultdict(lambda: defaultdict(int))
    for region in world.regions:
        region.resources = compute_region_yield(region, world.season)
        fac_res = production[region.faction_idx]
        for resource, amount in region.resources.items():
            fac_res[resource] += amount

    production_value = {}
    upkeep_value = {}
    gold_income_by_fac = {}
    for fac_idx, nation in enumerate(world.factions):
        res = nation.stats.setdefault("resources", {})
        _apply_spoilage(res)
        fac_production = production.get(fac_idx, {})
        for resource, amount in fac_production.items():
            res[resource] = int(res.get(resource, 0) + amount)
        production_value[fac_idx] = _resource_bundle_value(fac_production)
        gold_income = 0
        upkeep_total = defaultdict(int)
        for sid in nation.meta.get("settlements", []):
            settlement = world.settlements[sid]
            for resource, amount in settlement.upkeep.items():
                res[resource] = max(0, int(res.get(resource, 0) - amount))
                upkeep_total[resource] += amount
            gold_income += settlement.tax_income
        upkeep_value[fac_idx] = _resource_bundle_value(upkeep_total)
        gold_income_by_fac[fac_idx] = gold_income
        nation.stats["gold"] = nation.stats.get("gold", 0) + gold_income
        _clamp_to_storage(nation)
        _recompute_military(nation)

    _update_prosperity(world, production_value, upkeep_value, gold_income_by_fac)
    _grow_city_villages(world)

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

    # Player/AI-built settlements + their connecting roads
    # (app/world/construction.py).
    from app.world import construction
    construction.advance_projects(world)
    construction.advance_shipyard_projects(world)
    construction.run_settlement_ai(world)

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
