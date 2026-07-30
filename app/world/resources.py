"""Grounded resource economy: what a region produces, driven by its biome,
climate, the current season, and how remote it is from a settlement — plus
the turn loop that makes seasons (and stockpiles) actually advance.

The registry (RESOURCES) defines every resource as a real crafting-chain
tier instead of a small set of aggregated fantasy-flavor goods:
  1. Crops / Livestock       -- raw agricultural/pastoral output
  2. Forestry / Mining       -- raw industrial output
  3. Food Products           -- Crops/Livestock processed once
  4. Manufactured Goods      -- Forestry/Mining (and some Food Products)
                                 processed into finished goods
Built up in phases, each still clearly labeled below: where a resource
spawns (RESOURCE_SPAWN), what building produces it (BUILDINGS), its
recipe (RECIPES), Crops' growth-season cycle (GROWTH_CYCLE), Livestock as
real populations (LIVESTOCK_DYNAMICS), and finally consumption
(advance_production_chains actually spends recipe inputs;
advance_settlement_consumption is what makes a settlement's population
need Food/Firewood/Clothes for real, replacing the old flat
SETTLEMENT_UPKEEP draw entirely — see Phase 8's section for the full
story). The old aggregated-resource system this overhaul replaced (Wood,
Fish, Gems, Spices, Textiles, Mithril, Steel, Grain, Fresh Water...) is
fully gone now -- each name was either retired outright or migrated to a
real entry in the registry above (see the removal note above
compute_region_yield for the full history).
"""
import random
from collections import defaultdict

from app.world.lexicon import SPECIES
from app.world.worldgen import (OCEAN, _path_dijkstra, _elev_cost, road_cells,
                                path_transit_cells, _VILLAGE_CATCHMENT_RADIUS)
from app.world import weather
from app.world import wrap

# --- the resource registry --------------------------------------------------
# category + tier (1 raw agricultural/pastoral .. 4 manufactured), per the
# crafting-chain tiering described above.
RESOURCES = {
    # Crops
    "Wheat":    {"category": "Crops", "tier": 1},
    "Barley":   {"category": "Crops", "tier": 1},
    "Oats":     {"category": "Crops", "tier": 1},
    "Rye":      {"category": "Crops", "tier": 1},
    "Potatoes": {"category": "Crops", "tier": 1},
    "Carrots":  {"category": "Crops", "tier": 1},
    "Onions":   {"category": "Crops", "tier": 1},
    # Hay/fodder. A Crop like any other -- grown, harvested, stored -- but
    # eaten by animals rather than people (edible: False, like Cotton), and
    # the thing that decides whether a herd survives Winter (see
    # FODDER_PER_HEAD_WINTER). Deliberately a Crop rather than a free
    # pasture yield: that way it competes with food crops for the same
    # regional land, so "feed the herd or feed the people" is a real
    # land-use trade-off instead of a resource that appears from nowhere.
    "Fodder":   {"category": "Crops", "tier": 1},
    "Beans":    {"category": "Crops", "tier": 1},
    "Peas":     {"category": "Crops", "tier": 1},
    "Rice":     {"category": "Crops", "tier": 1},
    "Cotton":   {"category": "Crops", "tier": 1},
    "Grapes":   {"category": "Crops", "tier": 1},   # Phase 13 -- Wine's raw input

    # Livestock
    "Cattle":   {"category": "Livestock", "tier": 1},
    "Sheep":    {"category": "Livestock", "tier": 1},
    "Horses":   {"category": "Livestock", "tier": 1},
    "Goats":    {"category": "Livestock", "tier": 1},
    "Chickens": {"category": "Livestock", "tier": 1},
    "Pigs":     {"category": "Livestock", "tier": 1},
    "Bees":     {"category": "Livestock", "tier": 1},

    # Forestry
    "Logs":     {"category": "Forestry", "tier": 2},
    "Hardwood": {"category": "Forestry", "tier": 2},
    "Softwood": {"category": "Forestry", "tier": 2},
    "Firewood": {"category": "Forestry", "tier": 2},
    "Resin":    {"category": "Forestry", "tier": 2},

    # Mining
    "Iron":     {"category": "Mining", "tier": 2},
    "Copper":   {"category": "Mining", "tier": 2},
    "Tin":      {"category": "Mining", "tier": 2},
    "Coal":     {"category": "Mining", "tier": 2},
    "Stone":    {"category": "Mining", "tier": 2},
    "Clay":     {"category": "Mining", "tier": 2},
    "Sand":     {"category": "Mining", "tier": 2},
    "Salt":     {"category": "Mining", "tier": 2},
    "Gems":     {"category": "Mining", "tier": 2},   # Phase 13 -- Jewelry's raw input;
                                                       # promoted from the old stale BIOME_YIELDS
                                                       # name (see the STALE section)
    "Gold Ore": {"category": "Mining", "tier": 2},   # Gold's raw input -- see the Currency
                                                       # section below

    # Fishing -- its own category, deliberately not Forestry/Mining: unlike
    # every other raw resource, it doesn't spawn from a region's biome
    # shares at all (see RESOURCE_SPAWN's note and _node_fish_yield below),
    # so it needs to stay out of any code that assumes "every raw resource
    # has a RESOURCE_SPAWN entry."
    "Fish":     {"category": "Fishing", "tier": 1},

    # Food Products
    "Flour":       {"category": "Food Products", "tier": 3},
    "Bread":       {"category": "Food Products", "tier": 3},
    "Meat":        {"category": "Food Products", "tier": 3},
    "Milk":        {"category": "Food Products", "tier": 3},
    "Cheese":      {"category": "Food Products", "tier": 3},
    "Eggs":        {"category": "Food Products", "tier": 3},
    "Honey":       {"category": "Food Products", "tier": 3},
    "Smoked Fish": {"category": "Food Products", "tier": 3},
    # Cured meat. Unlike every other Food Product this one has no entry in
    # RECIPES: it can ONLY be made in a Preserving House (Phase 5), which
    # is what gives that building -- and the Salt it burns through -- a
    # reason to exist beyond raising a conversion cap.
    "Salted Meat": {"category": "Food Products", "tier": 3},

    # Manufactured Goods
    "Planks":   {"category": "Manufactured Goods", "tier": 4},
    "Bricks":   {"category": "Manufactured Goods", "tier": 4},
    "Glass":    {"category": "Manufactured Goods", "tier": 4},
    # Wool: a sheared (not eaten) Livestock byproduct -- a fiber, not food,
    # so it belongs here rather than Food Products despite being a
    # "processed once from Livestock" good like the rest of that category.
    # Tier 4 to match every other Manufactured Good (this registry has no
    # resource anywhere whose tier doesn't match its category).
    "Wool":     {"category": "Manufactured Goods", "tier": 4},
    "Cloth":    {"category": "Manufactured Goods", "tier": 4},
    "Clothes":  {"category": "Manufactured Goods", "tier": 4},
    "Leather":  {"category": "Manufactured Goods", "tier": 4},
    "Tools":    {"category": "Manufactured Goods", "tier": 4},
    "Weapons":  {"category": "Manufactured Goods", "tier": 4},
    "Shields":  {"category": "Manufactured Goods", "tier": 4},
    # Paper is Books' missing link (Phase 13), not a luxury itself -- a
    # plain processed intermediate exactly like Flour or Cloth, just one
    # more step removed from its raw input (Cotton).
    "Paper":    {"category": "Manufactured Goods", "tier": 4},
    # Gold -- the currency itself, as of the Currency overhaul (see that
    # section below): a real Manufactured Good now, minted from Gold Ore at
    # a Mint, not a flat per-turn tax number. Tier 4 like every other
    # Manufactured Good; its actual gold-equivalent VALUE is handled as a
    # special case in resource_value() (1 unit of Gold is worth 1 Gold, by
    # definition) rather than the tier-9 default every other tier-4 good gets.
    "Gold":     {"category": "Manufactured Goods", "tier": 4},

    # Luxury Goods (Phase 13) -- "only after the core economy works should
    # luxuries exist." First real use of the `luxury` property flag (see
    # its note below: reserved since the registry was redefined, "for
    # whenever luxury goods return"). Tier 5: the crafting chain's actual
    # top, one step past a Manufactured Good, priced accordingly (see
    # BASE_VALUE_BY_TIER).
    "Wine":         {"category": "Luxury Goods", "tier": 5},
    "Beer":         {"category": "Luxury Goods", "tier": 5},
    "Jewelry":      {"category": "Luxury Goods", "tier": 5},
    "Furniture":    {"category": "Luxury Goods", "tier": 5},
    "Fine Clothes": {"category": "Luxury Goods", "tier": 5},
    "Books":        {"category": "Luxury Goods", "tier": 5},
    "Candles":      {"category": "Luxury Goods", "tier": 5},
}

# --- per-resource properties -------------------------------------------------
# Every resource above also carries:
#   spoil_rate  float, 0.0..1.0 fraction lost per turn in storage (0 = never
#               spoils -- same meaning as the old SPOILAGE_RATE dict below,
#               just per-resource instead of a handful of hardcoded names)
#   stackable   bool, can units just be counted together (True for nearly
#               everything -- False for Livestock, which are individual
#               living animals, not an interchangeable bulk quantity)
#   edible      bool, safe/intended for a person to eat directly
#   refined     bool, has it been processed at all -- False for every raw
#               Crop/Livestock/Forestry/Mining tier, True for every Food
#               Product/Manufactured Good
#   luxury      bool, non-essential/status good -- nothing in the current
#               grounded registry qualifies (the old fantasy luxury tier --
#               Spices/Silks/Jewelry/Mithril -- was dropped when this was
#               redefined); the flag exists for whenever luxury goods return
#   renewable   bool, does the source replenish (crops regrow, herds breed,
#               forests regrow) vs. a one-time deposit that depletes
#               (mined/quarried) -- a manufactured good inherits whichever
#               its main raw input is, not its category as a whole
#   living      bool, a living creature rather than inert material -- only
#               true for Livestock
#   tradable    bool, allowed to move through trade routes/caravans -- every
#               resource qualifies today; the flag is a hook for later, not
#               a real restriction yet
#
# Most of these vary by category, not by individual resource, so they're
# filled in as category-wide defaults with only genuine exceptions listed
# per-resource -- spoil_rate is the one property with no sensible category
# default (it varies too much even within a category: grain vs. root
# vegetables, milk vs. cheese), so every resource gets one explicitly.
_CATEGORY_PROPERTY_DEFAULTS = {
    "Crops":              {"edible": True,  "refined": False, "renewable": True,
                           "living": False, "stackable": True,  "luxury": False, "tradable": True},
    "Livestock":          {"edible": False, "refined": False, "renewable": True,
                           "living": True,  "stackable": False, "luxury": False, "tradable": True},
    "Forestry":           {"edible": False, "refined": False, "renewable": True,
                           "living": False, "stackable": True,  "luxury": False, "tradable": True},
    "Mining":              {"edible": False, "refined": False, "renewable": False,
                           "living": False, "stackable": True,  "luxury": False, "tradable": True},
    # Renewable like Forestry (never depletes -- see _node_fish_yield), but
    # not edible raw the same way a Crop is: it has to be Smoked first,
    # same as Livestock needs slaughtering into Meat.
    "Fishing":             {"edible": False, "refined": False, "renewable": True,
                           "living": False, "stackable": True,  "luxury": False, "tradable": True},
    "Food Products":       {"edible": True,  "refined": True,  "renewable": True,
                           "living": False, "stackable": True,  "luxury": False, "tradable": True},
    "Manufactured Goods":  {"edible": False, "refined": True,  "renewable": True,
                           "living": False, "stackable": True,  "luxury": False, "tradable": True},
    # Phase 13 -- the first category to ever actually set luxury: True (see
    # that field's own note above: reserved since this registry was
    # redefined, "for whenever luxury goods return"). Not edible by
    # default (Wine/Beer are the exceptions, overridden below) -- these
    # are status goods, not sustenance, even the drinkable ones.
    "Luxury Goods":        {"edible": False, "refined": True,  "renewable": True,
                           "living": False, "stackable": True,  "luxury": True,  "tradable": True},
}

_PROPERTY_OVERRIDES = {
    "Salt":    {"edible": True},     # the one edible Mining resource
    "Cotton":  {"edible": False},    # a fiber, not a food
    "Fodder":  {"edible": False},    # animal feed, not human food
    "Bricks":  {"renewable": False},  # fired from Clay -- a Mining (non-renewable) input
    "Glass":   {"renewable": False},  # made from Sand -- a Mining (non-renewable) input
    "Tools":   {"renewable": False},  # smithed from Iron/other ore
    "Weapons": {"renewable": False},
    "Shields": {"renewable": False},
    "Wine":    {"edible": True},     # drunk, not eaten, but still consumed by mouth
    "Beer":    {"edible": True},
    "Jewelry": {"renewable": False},  # set with Gems -- a Mining (non-renewable) input
    "Gold":    {"renewable": False},  # struck from Gold Ore -- a Mining (non-renewable) input
}

_SPOIL_RATE = {
    # Crops -- grains store well dried; root veg and onions spoil faster;
    # dried legumes keep almost indefinitely.
    "Wheat": 0.03, "Barley": 0.03, "Oats": 0.03, "Rye": 0.03,
    "Potatoes": 0.06, "Carrots": 0.07, "Onions": 0.05, "Beans": 0.02, "Peas": 0.02,
    "Rice": 0.03, "Cotton": 0.02,   # dried fiber, at least as durable as a dried grain
    # Dried hay, stacked in a barn, has to survive from the Summer cut to the
    # Winter it exists for -- one to two full seasons, i.e. 25-50 turns. At an
    # ordinary crop's rate that's a 64% loss in transit and the herd starves
    # holding a barn that was full at harvest; measured, the world went from
    # 70,330 hay in Autumn to under 5,000 by the time it was needed. Baled hay
    # genuinely does keep for a year, so it gets the lowest nonzero rate in
    # the registry.
    "Fodder": 0.01,
    "Grapes": 0.06,   # perishable fruit -- same ballpark as Potatoes/Carrots
    # Livestock -- a living animal isn't a perishable stockpile good.
    "Cattle": 0.0, "Sheep": 0.0, "Horses": 0.0, "Goats": 0.0, "Chickens": 0.0, "Pigs": 0.0, "Bees": 0.0,
    # Forestry -- wood is durable; only sap-based Resin degrades at all.
    "Logs": 0.0, "Hardwood": 0.0, "Softwood": 0.0, "Firewood": 0.0, "Resin": 0.02,
    # Mining -- nothing here spoils, salt included (it's a preservative).
    "Iron": 0.0, "Copper": 0.0, "Tin": 0.0, "Coal": 0.0,
    "Stone": 0.0, "Clay": 0.0, "Sand": 0.0, "Salt": 0.0, "Gems": 0.0, "Gold Ore": 0.0,
    # Fishing -- a fresh catch spoils fast (worse than Meat, it's not even
    # butchered/salted yet); Smoked Fish is cured, like Cheese.
    "Fish": 0.35, "Smoked Fish": 0.05,
    # Food Products -- the most perishable tier by far. Milk worst, then
    # Bread ("spoils quickly"), then Meat/Eggs; Cheese is cured/durable;
    # Honey essentially never spoils.
    "Flour": 0.05, "Bread": 0.35, "Meat": 0.30, "Milk": 0.40,
    "Cheese": 0.05, "Eggs": 0.15, "Honey": 0.0,
    "Salted Meat": 0.03,   # salt-cured: keeps like Cheese, unlike Meat at 0.30
    # Manufactured Goods -- finished/durable, almost none of them spoil.
    # Wool is a mild exception (raw fiber, only lightly at risk from moths/
    # damp); Paper is the other (damp/mildew risk).
    "Planks": 0.0, "Bricks": 0.0, "Glass": 0.0, "Cloth": 0.0, "Clothes": 0.0,
    "Leather": 0.0, "Tools": 0.0, "Weapons": 0.0, "Shields": 0.0, "Paper": 0.02,
    "Wool": 0.01, "Gold": 0.0,
    # Luxury Goods -- Beer spoils fastest (real shelf life is short); Wine
    # keeps much better but still ages; Candles slowly degrade (melt/go
    # brittle). Jewelry/Furniture/Fine Clothes/Books are all finished,
    # durable goods -- none of them spoil, same as every other finished
    # good in this registry.
    "Wine": 0.02, "Beer": 0.10, "Jewelry": 0.0, "Furniture": 0.0,
    "Fine Clothes": 0.0, "Books": 0.0, "Candles": 0.03,
}

# --- Phase 2 of the storage rework: bulk ------------------------------------
# How much storage space ONE unit of a resource takes, relative to a unit of
# grain (1.0). Until now every unit cost exactly 1 regardless of what it was,
# which the Phase 9 note defended as avoiding "a second axis of made-up
# numbers" -- reasonable at the time, but the measurements since have made the
# case: raw Mining/Forestry goods were 88-90% of everything in storage, and a
# model where a Log and a Gem occupy identical space has no way to express
# why that's a problem. Bulk is what makes a barn full of timber *feel*
# expensive, and it's the first thing that gives the player a reason to
# prefer refining a good over hoarding its raw input.
#
# Values are about volume, not weight -- storage is floor space. So Iron
# (dense, compact) is cheaper to store per unit than Logs (light, enormous),
# even though the iron is heavier. Anything genuinely tiny and valuable
# (Gems, Gold, Jewelry) costs almost nothing, which is what makes a Vault a
# small building rather than a warehouse for coins.
#
# Most of this varies by category, so it's category defaults plus real
# exceptions -- unlike _SPOIL_RATE, which needs every resource named because
# it varies too much within a category to have a sensible default.
_CATEGORY_BULK = {
    "Crops": 1.0, "Livestock": 1.0, "Forestry": 2.5, "Mining": 1.6,
    "Fishing": 1.0, "Food Products": 1.0, "Manufactured Goods": 1.2,
    "Luxury Goods": 0.5,
}
_BULK_OVERRIDES = {
    # Forestry -- raw timber is the bulkiest thing in the game; Resin is sap
    # in a barrel.
    "Logs": 3.0, "Hardwood": 2.6, "Softwood": 2.6, "Firewood": 2.0, "Resin": 0.8,
    # Mining -- quarried stone/clay/sand is bulky, smelted metal is compact,
    # Gems are a pouch.
    "Stone": 2.5, "Clay": 2.0, "Sand": 2.0, "Coal": 1.8,
    "Iron": 1.2, "Copper": 1.2, "Tin": 1.2, "Salt": 0.8, "Gems": 0.1,
    # Manufactured -- sawn/fired building material stays bulky; finished
    # metalwork and paper are compact. Gold is minted currency: a chest.
    "Planks": 2.0, "Bricks": 2.2, "Glass": 1.0, "Wool": 1.6, "Cloth": 1.0,
    "Clothes": 1.2, "Leather": 1.2, "Tools": 0.8, "Weapons": 0.8,
    "Shields": 1.2, "Paper": 0.5, "Gold": 0.02,
    # Food -- roughly grain-like, with cured/concentrated goods packing better
    # than fresh ones.
    "Flour": 0.9, "Bread": 1.0, "Meat": 1.0, "Milk": 1.2, "Cheese": 0.8,
    "Eggs": 1.2, "Honey": 0.6, "Fish": 1.0, "Smoked Fish": 0.8,
    "Salted Meat": 0.9,
    "Cotton": 1.8, "Grapes": 1.2,     # raw fiber and fresh fruit are bulky
    "Fodder": 2.2,   # baled hay is mostly air -- the bulkiest thing a granary holds
    # Luxury -- small and precious, except Furniture, which is neither.
    "Jewelry": 0.1, "Furniture": 3.0, "Fine Clothes": 0.8, "Books": 0.5,
    "Candles": 0.4, "Wine": 1.0, "Beer": 1.2,
}

for _name, _spec in RESOURCES.items():
    _spec.update(_CATEGORY_PROPERTY_DEFAULTS[_spec["category"]])
    _spec.update(_PROPERTY_OVERRIDES.get(_name, {}))
    _spec["spoil_rate"] = _SPOIL_RATE[_name]
    _spec["bulk"] = _BULK_OVERRIDES.get(_name, _CATEGORY_BULK[_spec["category"]])
del _name, _spec


# Same reasoning as _STORAGE_CLASS_CACHE below: pure function of a name over a
# table fixed at import, called alongside storage_class in the same hot sums.
_RESOURCE_BULK_CACHE = {}


def resource_bulk(resource):
    """Storage space one unit of `resource` occupies (see _CATEGORY_BULK).
    Unknown resources cost 1.0, the grain reference."""
    try:
        return _RESOURCE_BULK_CACHE[resource]
    except KeyError:
        value = RESOURCES.get(resource, {}).get("bulk", 1.0)
        _RESOURCE_BULK_CACHE[resource] = value
        return value

# Gold-equivalent value per unit, by tier -- the shared "how much is this
# actually worth" reference used both for trade pricing (app/world/trade.py)
# and for settlement prosperity (see resource_value()/goods_wealth_value()
# below). Lives here, not in trade.py, since resources.py is the module
# every other economy module already imports RESOURCES from. Monotonic by
# design now that tier tracks the crafting chain (raw < processed):
# rough starting point, not yet balance-tuned. Tier 5 (Phase 13 -- Luxury
# Goods) continues the same rough progression the first four tiers already
# have (each roughly 1.6-1.8x the one before).
BASE_VALUE_BY_TIER = {1: 2, 2: 3, 3: 5, 4: 9, 5: 15}   # gold/unit before scarcity

BIOMES = ["mountain", "forest", "plains", "coastal", "desert", "swamp"]
CLIMATES = ["temperate", "arid", "cold", "humid"]
SEASONS = ["Spring", "Summer", "Autumn", "Winter"]
# 25 turns/season (100 turns/year) -- raised from 8 (32 turns/year) so a
# year is a round, legible number and travel time reads as a smaller
# fraction of a year now that the map itself has gotten larger (multi-
# continent worldgen) without movement speed itself changing.
TURNS_PER_SEASON = 25
YEAR_LENGTH_TURNS = TURNS_PER_SEASON * len(SEASONS)

# --- Phase 3: where a resource actually appears -----------------------------
# Only the 28 *raw* resources (Crops/Livestock/Forestry/Mining -- tiers 1-2)
# get a spawn profile: they come directly from the land, so biome/elevation/
# climate/fertility genuinely apply. Food Products and Manufactured Goods
# (tiers 3-4) don't spawn geographically at all -- Bread doesn't grow in a
# biome, it's made by converting Flour at a settlement. That conversion step
# (production chains) is later work; RESOURCE_SPAWN deliberately has no
# entries for those 16 resources rather than faking geography for them.
#
# One requesting example doesn't map onto the current registry and was
# deliberately left out rather than silently invented:
#   - "Deer" -- explicitly marked future by the request itself; not a
#     resource yet.
# (Rice was added to the Crops list and given a swamp/wetland spawn profile
# below, so that gap from the original registry is now closed.)
# "Timber" isn't a single resource either -- it's represented by Logs/
# Hardwood/Softwood (all forest) from step 1's split of the old generic Wood.
#
# Fields per resource:
#   biomes            set of BIOMES it can appear in at all
#   elevation         (min, max) preferred relief band, 0..1 -- the same
#                     normalized "how far above sea level" scale
#                     classify_biome() already uses (relief > 0.55 = mountain)
#   climate           {climate: multiplier}, sparse -- missing climate = 1.0,
#                     same convention as the old CLIMATE_MODIFIERS below
#   fertility_weight  0..1, how much world.fertility should scale this
#                     resource's yield -- 1.0 for a proper farmland crop,
#                     0.0 for something fertility has no business affecting
#                     (ore doesn't care if the soil above it is rich)
#   rarity            "common" / "uncommon" / "rare" -- see RARITY_ABUNDANCE
#                     for the multiplier it maps to
# renewable/finite is deliberately *not* repeated here -- that's already the
# "renewable" property every resource got in step 2; re-declaring it per
# spawn profile would just be a second source of truth to keep in sync.
RESOURCE_SPAWN = {
    # Crops -- plains farmland. All fully fertility-driven; elevation ceiling
    # and climate spread vary by how hardy/delicate the real crop is.
    "Wheat":    {"biomes": {"plains"}, "elevation": (0.0, 0.35),
                "climate": {"temperate": 1.3, "arid": 0.4, "cold": 0.5, "humid": 0.9},
                "fertility_weight": 1.0, "rarity": "common"},
    "Barley":   {"biomes": {"plains"}, "elevation": (0.0, 0.45),
                "climate": {"temperate": 1.1, "arid": 0.6, "cold": 0.9, "humid": 0.8},
                "fertility_weight": 1.0, "rarity": "common"},
    "Oats":     {"biomes": {"plains"}, "elevation": (0.0, 0.45),
                "climate": {"temperate": 1.0, "arid": 0.4, "cold": 1.0, "humid": 1.1},
                "fertility_weight": 1.0, "rarity": "common"},
    "Rye":      {"biomes": {"plains"}, "elevation": (0.0, 0.50),
                "climate": {"temperate": 0.9, "arid": 0.7, "cold": 1.2, "humid": 0.7},
                "fertility_weight": 0.8, "rarity": "uncommon"},   # hardiest grain, tolerates poor/marginal land
    "Potatoes": {"biomes": {"plains"}, "elevation": (0.0, 0.40),
                "climate": {"temperate": 1.1, "arid": 0.5, "cold": 0.9, "humid": 1.0},
                "fertility_weight": 0.9, "rarity": "common"},
    "Carrots":  {"biomes": {"plains"}, "elevation": (0.0, 0.35),
                "climate": {"temperate": 1.2, "arid": 0.6, "cold": 0.7, "humid": 0.9},
                "fertility_weight": 1.0, "rarity": "common"},
    "Onions":   {"biomes": {"plains"}, "elevation": (0.0, 0.35),
                "climate": {"temperate": 1.1, "arid": 0.8, "cold": 0.6, "humid": 0.8},
                "fertility_weight": 1.0, "rarity": "common"},
    # Grass/hay: the least demanding crop in the registry -- it grows on
    # marginal ground a food crop would fail on (low fertility_weight,
    # tolerant of every climate and the highest elevation ceiling), which
    # is what lets a cold or poor region still keep animals.
    # rarity "uncommon" is doing real balance work here, not flavour:
    # _biome_land_shares splits a biome by rarity alone, so a "common" Fodder
    # claimed a full staple-grain share of every plain (10.5%, the same as
    # Wheat) and cut human food production by about a tenth the moment it
    # existed -- nodes with people starving in them went from 140 to 225.
    # "uncommon" halves that to ~5.5%: keeping animals still costs you fields
    # you could have fed people with, which is the intended trade-off, but it
    # doesn't cost you a staple crop's worth of them.
    "Fodder":   {"biomes": {"plains"}, "elevation": (0.0, 0.60),
                "climate": {"temperate": 1.2, "arid": 0.7, "cold": 1.1, "humid": 1.0},
                "fertility_weight": 0.5, "rarity": "uncommon"},
    "Beans":    {"biomes": {"plains"}, "elevation": (0.0, 0.35),
                "climate": {"temperate": 1.2, "arid": 0.5, "cold": 0.5, "humid": 1.0},
                "fertility_weight": 0.9, "rarity": "uncommon"},
    "Peas":     {"biomes": {"plains"}, "elevation": (0.0, 0.35),
                "climate": {"temperate": 1.2, "arid": 0.5, "cold": 0.7, "humid": 0.9},
                "fertility_weight": 0.9, "rarity": "uncommon"},
    "Rice":     {"biomes": {"swamp"}, "elevation": (0.0, 0.15),
                "climate": {"temperate": 0.9, "arid": 0.2, "cold": 0.3, "humid": 1.4},
                "fertility_weight": 1.0, "rarity": "uncommon"},   # flooded paddy land, the one wetland crop
    "Cotton":   {"biomes": {"plains"}, "elevation": (0.0, 0.35),
                "climate": {"temperate": 0.7, "arid": 1.4, "cold": 0.2, "humid": 1.0},
                "fertility_weight": 1.0, "rarity": "uncommon"},   # warm/arid-favoring -- flips the usual temperate-loving crop pattern
    "Grapes":   {"biomes": {"plains"}, "elevation": (0.0, 0.45),
                "climate": {"temperate": 1.3, "arid": 1.1, "cold": 0.2, "humid": 0.6},
                "fertility_weight": 0.9, "rarity": "uncommon"},   # Phase 13 -- warm/dry-favoring like a real vineyard, hates cold

    # Livestock -- mostly plains grazing; Goats break out to mountain
    # foothills and Pigs to forest, so the category isn't just "plains x6".
    # fertility_weight is lower than Crops across the board (pasture quality
    # matters, but far less directly than tilled soil) and near-zero for the
    # three that don't really graze open farmland at all.
    "Cattle":   {"biomes": {"plains"}, "elevation": (0.0, 0.35),
                "climate": {"temperate": 1.2, "arid": 0.5, "cold": 0.7, "humid": 1.0},
                "fertility_weight": 0.6, "rarity": "common"},
    "Sheep":    {"biomes": {"plains"}, "elevation": (0.0, 0.45),
                "climate": {"temperate": 1.1, "arid": 0.7, "cold": 1.0, "humid": 0.8},
                "fertility_weight": 0.5, "rarity": "common"},
    "Horses":   {"biomes": {"plains"}, "elevation": (0.0, 0.35),
                "climate": {"temperate": 1.2, "arid": 0.6, "cold": 0.7, "humid": 0.9},
                "fertility_weight": 0.6, "rarity": "uncommon"},
    "Goats":    {"biomes": {"mountain"}, "elevation": (0.35, 0.70),
                "climate": {"temperate": 1.0, "arid": 1.1, "cold": 0.9, "humid": 0.7},
                "fertility_weight": 0.2, "rarity": "uncommon"},   # rocky/mountain grazers, not farmland
    "Chickens": {"biomes": {"plains"}, "elevation": (0.0, 0.35),
                "climate": {"temperate": 1.1, "arid": 0.8, "cold": 0.7, "humid": 0.9},
                "fertility_weight": 0.2, "rarity": "common"},
    "Pigs":     {"biomes": {"forest"}, "elevation": (0.0, 0.45),
                "climate": {"temperate": 1.1, "arid": 0.4, "cold": 0.6, "humid": 1.1},
                "fertility_weight": 0.2, "rarity": "common"},   # forest pannage, not pasture
    "Bees":     {"biomes": {"plains", "forest"}, "elevation": (0.0, 0.45),
                "climate": {"temperate": 1.2, "arid": 0.5, "cold": 0.4, "humid": 1.1},
                "fertility_weight": 0.4, "rarity": "uncommon"},   # wildflower meadow or forest clearing, not picky about which

    # Forestry -- all forest, all mildly fertility-sensitive (richer ground
    # grows denser/better timber, but nowhere near as directly as a crop).
    "Logs":     {"biomes": {"forest"}, "elevation": (0.0, 0.55),
                "climate": {"temperate": 1.1, "arid": 0.3, "cold": 0.9, "humid": 1.2},
                "fertility_weight": 0.2, "rarity": "common"},
    "Hardwood": {"biomes": {"forest"}, "elevation": (0.0, 0.50),
                "climate": {"temperate": 1.2, "arid": 0.2, "cold": 0.6, "humid": 1.1},
                "fertility_weight": 0.4, "rarity": "uncommon"},
    "Softwood": {"biomes": {"forest"}, "elevation": (0.0, 0.55),
                "climate": {"temperate": 0.9, "arid": 0.3, "cold": 1.2, "humid": 0.9},
                "fertility_weight": 0.2, "rarity": "common"},
    "Firewood": {"biomes": {"forest"}, "elevation": (0.0, 0.55),
                "climate": {"temperate": 1.0, "arid": 0.5, "cold": 1.0, "humid": 1.0},
                "fertility_weight": 0.1, "rarity": "common"},
    "Resin":    {"biomes": {"forest"}, "elevation": (0.0, 0.50),
                "climate": {"temperate": 1.0, "arid": 0.3, "cold": 0.7, "humid": 1.1},
                "fertility_weight": 0.3, "rarity": "rare"},

    # Mining -- geological, not biological: climate is left empty (no
    # multiplier anywhere -- weather doesn't affect what's in the ground)
    # and fertility_weight is 0.0 across the board. Ore/coal/stone favor
    # mountain, banded by elevation so they don't all read identically;
    # Clay/Sand/Salt are lowland instead, matching where those actually
    # form (floodplains, deserts/beaches).
    "Iron":     {"biomes": {"mountain"}, "elevation": (0.60, 0.85),
                "climate": {}, "fertility_weight": 0.0, "rarity": "common"},
    "Copper":   {"biomes": {"mountain"}, "elevation": (0.55, 0.75),
                "climate": {}, "fertility_weight": 0.0, "rarity": "uncommon"},
    "Tin":      {"biomes": {"mountain"}, "elevation": (0.55, 0.75),
                "climate": {}, "fertility_weight": 0.0, "rarity": "rare"},   # Bronze Age scarcity, deliberate
    "Coal":     {"biomes": {"mountain"}, "elevation": (0.55, 0.68),
                "climate": {}, "fertility_weight": 0.0, "rarity": "common"},
    "Stone":    {"biomes": {"mountain"}, "elevation": (0.55, 1.00),
                "climate": {}, "fertility_weight": 0.0, "rarity": "common"},   # quarried anywhere mountainous
    "Clay":     {"biomes": {"swamp"}, "elevation": (0.0, 0.15),
                "climate": {}, "fertility_weight": 0.0, "rarity": "common"},
    "Sand":     {"biomes": {"desert", "coastal"}, "elevation": (0.0, 0.20),
                "climate": {}, "fertility_weight": 0.0, "rarity": "common"},
    "Salt":     {"biomes": {"desert", "coastal"}, "elevation": (0.0, 0.20),
                "climate": {}, "fertility_weight": 0.0, "rarity": "uncommon"},
    "Gems":     {"biomes": {"mountain", "desert"}, "elevation": (0.0, 1.00),
                "climate": {}, "fertility_weight": 0.0, "rarity": "rare"},
                # Phase 13 -- promoted from the old stale BIOME_YIELDS entry,
                # which sourced it from the same two biomes (mountain seams,
                # desert placer deposits) -- kept that geography, just made
                # it real.
    "Gold Ore": {"biomes": {"mountain"}, "elevation": (0.55, 0.80),
                "climate": {}, "fertility_weight": 0.0, "rarity": "rare"},
                # Currency overhaul -- real deposits, mountain seams like
                # Iron/Coal, but scarcer (rare, same as Gems) so a Mint's
                # output stays meaningfully bottlenecked by geography, not
                # something every mountain region can freely mass-produce.
}

# "How rare" as a multiplier -- deliberately separate from crafting tier
# (a tier-1 Crop like Wheat is common; so is a tier-2 Mining resource like
# Stone) and from BASE_VALUE_BY_TIER (worth per unit, not how often a region
# actually produces it).
RARITY_ABUNDANCE = {"common": 1.0, "uncommon": 0.5, "rare": 0.2}


def climate_affinity(resource, climate):
    """Yield multiplier for `resource` in `climate`, per RESOURCE_SPAWN --
    missing = 1.0 (neutral)."""
    return RESOURCE_SPAWN.get(resource, {}).get("climate", {}).get(climate, 1.0)


def rarity_abundance(resource):
    rarity = RESOURCE_SPAWN.get(resource, {}).get("rarity", "common")
    return RARITY_ABUNDANCE.get(rarity, 1.0)


# --- Phase 4: buildings -------------------------------------------------
# One building per resource -- decided literally rather than the "one craft,
# several related outputs" reading the Blacksmith/Tailor examples first
# suggested (that reading would have bundled e.g. Tools+Weapons+Shields into
# a single Blacksmith); every one of the 45 resources gets its own building
# whose sole purpose is producing it.
#
# Raw resources (Crops/Livestock/Forestry/Mining) reuse RESOURCE_SPAWN's
# biome list as their placement requirement via building_biomes() below,
# rather than repeating it -- e.g. Wheat Farm only goes on plains, Rice
# Paddy only on swamp, Iron Mine only on mountain, matching the "split raw
# buildings by biome/method" decision (hence Quarry/Clay Pit/Saltern/etc.
# as distinct buildings instead of one generic catch-all Mine). Food
# Products and Manufactured Goods buildings are workshops with no biome
# requirement of their own -- they're presumably built at a settlement, not
# tied to a specific tile.
#
# Where a workshop needs to be sited relative to its input's source (a
# Sawmill presumably wants to be near a Forester, a Mill near grain
# farmland, etc.) is still not modeled -- a building name here is
# informational/flavor, not a placement requirement, for anything past a
# raw resource's own biome. What a processing building actually consumes,
# at what ratio, IS defined now (see RECIPES below) -- that part of the
# original "outputs only for now" deferral has since been done.
#
# One modeling wrinkle worth flagging rather than silently smoothing over:
# Milk/Eggs/Honey each get their own dedicated building (Dairy/Henhouse/
# Apiary) distinct from the animal that would realistically produce them as
# a byproduct (Cattle Ranch/Sheep Pasture, Beehive) -- a direct consequence
# of "one building per resource" being literal. (Honey used to also lack any
# Livestock input at all -- Bees now exists and fills that gap, kept in a
# Beehive, separate from Apiary the same way Chickens/Chicken Coop is
# separate from Eggs/Henhouse -- but the actual Bees -> Honey conversion
# still isn't wired up, same as every other input/output chain here.)
BUILDINGS = {
    # Crops -- dryland farms on plains; Rice is the one exception (a
    # flooded paddy, and the only crop sited on swamp).
    "Wheat":    {"name": "Wheat Farm"},
    "Barley":   {"name": "Barley Farm"},
    "Oats":     {"name": "Oat Farm"},
    "Rye":      {"name": "Rye Farm"},
    "Potatoes": {"name": "Potato Farm"},
    "Carrots":  {"name": "Carrot Farm"},
    "Onions":   {"name": "Onion Farm"},
    "Beans":    {"name": "Bean Farm"},
    "Peas":     {"name": "Pea Farm"},
    "Rice":     {"name": "Rice Paddy"},
    "Cotton":   {"name": "Cotton Farm"},
    "Grapes":   {"name": "Vineyard"},

    # Livestock -- plains grazing/keeping, except Goats (mountain) and
    # Pigs (forest pannage), matching their Phase 3 spawn profiles.
    "Cattle":   {"name": "Cattle Ranch"},
    "Sheep":    {"name": "Sheep Pasture"},
    "Horses":   {"name": "Stud Farm"},
    "Goats":    {"name": "Goat Pen"},
    "Chickens": {"name": "Chicken Coop"},
    "Pigs":     {"name": "Piggery"},
    "Bees":     {"name": "Beehive"},

    # Forestry -- all forest-sited; split by activity (structural logging
    # vs. fuel gathering vs. sap tapping), not just tree type.
    "Logs":     {"name": "Forester"},
    "Hardwood": {"name": "Hardwood Camp"},
    "Softwood": {"name": "Softwood Camp"},
    "Firewood": {"name": "Woodcutter"},
    "Resin":    {"name": "Resin Tapper"},

    # Mining -- split by what's actually being extracted and how, not one
    # catch-all Mine; ore/coal/stone on mountain, Clay in swamp, Sand/Salt
    # on desert or coastal.
    "Iron":     {"name": "Iron Mine"},
    "Copper":   {"name": "Copper Mine"},
    "Tin":      {"name": "Tin Mine"},
    "Coal":     {"name": "Coal Mine"},
    "Stone":    {"name": "Quarry"},
    "Clay":     {"name": "Clay Pit"},
    "Sand":     {"name": "Sand Pit"},
    "Salt":     {"name": "Saltern"},
    "Gems":     {"name": "Gem Mine"},
    "Gold Ore": {"name": "Gold Mine"},

    # Food Products -- workshops, no biome requirement of their own.
    "Flour":    {"name": "Mill"},
    "Bread":    {"name": "Bakery"},
    "Meat":     {"name": "Butcher"},
    "Milk":     {"name": "Dairy"},
    "Cheese":   {"name": "Creamery"},
    "Eggs":     {"name": "Henhouse"},
    "Honey":    {"name": "Apiary"},
    "Wool":     {"name": "Shearing Shed"},

    # Manufactured Goods -- workshops, no biome requirement of their own.
    "Planks":   {"name": "Sawmill"},
    "Bricks":   {"name": "Brickworks"},
    "Glass":    {"name": "Glassworks"},
    "Cloth":    {"name": "Weaver"},
    "Clothes":  {"name": "Tailor"},
    "Leather":  {"name": "Tannery"},
    "Tools":    {"name": "Toolsmith"},
    "Weapons":  {"name": "Weaponsmith"},
    "Shields":  {"name": "Shieldwright"},
    "Paper":    {"name": "Papermill"},
    "Gold":     {"name": "Mint"},

    # Luxury Goods (Phase 13) -- workshops, no biome requirement of their
    # own, same as every other processed-good building.
    "Wine":         {"name": "Winery"},
    "Beer":         {"name": "Brewery"},
    "Jewelry":      {"name": "Jeweler"},
    "Furniture":    {"name": "Furniture Maker"},
    "Fine Clothes": {"name": "Dressmaker"},
    "Books":        {"name": "Bindery"},
    "Candles":      {"name": "Chandler"},
}


def building_for(resource):
    """The one building that produces `resource` -- {"name": ...} -- or
    None if it doesn't have one (shouldn't happen; every current resource
    does)."""
    return BUILDINGS.get(resource)


def building_biomes(resource):
    """Which biomes `resource`'s building can be sited in, reused straight
    from RESOURCE_SPAWN rather than repeated here. None for a resource with
    no spawn profile (Food Products/Manufactured Goods: a workshop built at
    a settlement, not tied to any particular tile)."""
    spec = RESOURCE_SPAWN.get(resource)
    return spec["biomes"] if spec else None


# --- Phase 5: production recipes --------------------------------------------
# What a building actually consumes to make its one output. Exactly mirrors
# RESOURCE_SPAWN's coverage, just inverted: RESOURCE_SPAWN only has entries
# for the 29 raw resources (Crops/Livestock/Forestry/Mining -- nothing to
# convert, they come straight from the land); RECIPES only has entries for
# the 16 processed resources (Food Products/Manufactured Goods -- nothing
# comes from the land, they're all converted from something else). Every
# resource is covered by exactly one of the two, never both.
#
# Two of the requesting examples used "Blacksmith" for both the Tools and
# Shield recipes, but the buildings phase split that into one building per
# output (Toolsmith/Weaponsmith/Shieldwright) -- the recipes below are kept
# attached to those, not a reintroduced shared Blacksmith.
#
# Only resource *names* are connected here, no quantities/ratios (matching
# the request's own examples, which don't give numbers either) -- exact
# conversion amounts are a further-down balancing step. Each entry is a
# *list* of alternative recipes for that output -- most outputs only have
# one way to make them, so a one-item list, but a resource with more than
# one plausible real source (Cloth: Wool or Cotton fiber; Meat/Leather: any
# of five Livestock; Milk: any of the three dairy animals) gets one list
# entry per source.
# Within a single recipe, `inputs` is still an all-of list (Shields
# genuinely needs both Iron and Hardwood together) -- it's only the outer
# list that means "any one of these".
#
# Two extra per-recipe flags capture what actually happens to the input
# animal, distinguishing Milk (kept alive) from Meat/Leather (killed):
#   byproduct  True on Milk's recipe -- collected from a live animal, so
#              it should never reduce a Cattle count the way a real
#              consumption mechanic eventually will for the others
#   slaughter  True on every Meat/Leather recipe -- the animal doesn't
#              survive, whichever Livestock it is. Meat and Leather stay
#              two buildings (Butcher/Tannery), not merged into one
#              Slaughterhouse -- keeps the one-building-per-resource rule
#              intact, since "requires slaughter" is a property of the
#              recipe, not a reason the two outputs need to share a
#              building.
# Neither flag does anything mechanically yet (no consumption is modeled
# at all until quantities exist) -- they're here so the distinction is
# already captured in the data once that's wired up.
RECIPES = {
    "Flour":   [{"inputs": ["Wheat"]}],                  # Mill
    "Bread":   [{"inputs": ["Flour"]}],                  # Bakery
    # NOTE: Meat, Milk, Wool, Eggs and Honey are NOT made here. They come off
    # living herds (LIVESTOCK_DYNAMICS / advance_herds), and their inputs are
    # animals -- which live in village.herds, not in node.resources, where
    # every recipe in this table reads its inputs from. Entries for them used
    # to sit here with "slaughter"/"byproduct" flags and could never once
    # fire; worse, they read as the real production path and led directly to
    # a wrong diagnosis that Meat was unproducible when in fact the herd
    # system had been making it all along. Removed rather than left as a trap.
    "Cheese":  [{"inputs": ["Milk"]}],                   # Creamery
    "Smoked Fish": [{"inputs": ["Fish"]}],               # Smokehouse -- cured for storage, same
                                                          # 1:1 shape as Flour->Bread
    "Planks":  [{"inputs": ["Logs"]}],                   # Sawmill
    "Bricks":  [{"inputs": ["Clay"]}],                   # Brickworks
    "Glass":   [{"inputs": ["Sand"]}],                   # Glassworks
    "Cloth":   [{"inputs": ["Wool"]}, {"inputs": ["Cotton"]}],   # Weaver -- wool or cotton fiber, either works
    "Clothes": [{"inputs": ["Cloth"]}],                  # Tailor
    "Leather": [{"inputs": ["Cattle"], "slaughter": True},
               {"inputs": ["Sheep"], "slaughter": True},
               {"inputs": ["Goats"], "slaughter": True},
               {"inputs": ["Pigs"], "slaughter": True},
               {"inputs": ["Horses"], "slaughter": True}],   # Tannery -- any Livestock, always slaughtered
    "Tools":   [{"inputs": ["Iron"]}],                   # Toolsmith
    "Weapons": [{"inputs": ["Iron", "Softwood"]}],       # Weaponsmith -- blade + haft
    "Shields": [{"inputs": ["Iron", "Hardwood"]}],       # Shieldwright -- metal rim/boss + wooden face
    "Paper":   [{"inputs": ["Cotton"]}],                 # Papermill -- rag paper, not wood pulp
    "Gold":    [{"inputs": ["Gold Ore"]}],                # Mint -- struck into coin from raw ore,
                                                          # same 1:1 conversion shape as every
                                                          # other recipe here (see the Currency
                                                          # section for the full picture)

    # Luxury Goods (Phase 13). Wine/Beer/Furniture/Fine Clothes/Candles all
    # reuse an existing raw/processed resource one step further down the
    # chain; Jewelry is the one built straight from a raw Mining resource
    # (Gems), same shape as Tools from Iron. Books is the one two-input
    # recipe in this batch (paper + binding), mirroring Shields' all-of
    # list.
    "Wine":         [{"inputs": ["Grapes"]}],            # Winery
    "Beer":         [{"inputs": ["Barley"]}],            # Brewery
    "Jewelry":      [{"inputs": ["Gems"]}],              # Jeweler
    "Furniture":    [{"inputs": ["Planks"]}],            # Furniture Maker
    "Fine Clothes": [{"inputs": ["Cloth"]}],             # Dressmaker -- a finer cut than plain Clothes
    "Books":        [{"inputs": ["Paper", "Leather"]}],  # Bindery -- pages + binding
    "Candles":      [{"inputs": ["Honey"]}],             # Chandler -- beeswax, simplified as Honey
                                                          # itself rather than a separate wax byproduct
}


def recipe_for(resource):
    """The list of alternative recipes for `resource` -- each a
    {"inputs": [...]}, optionally with a "byproduct" or "slaughter" flag
    (see RECIPES) -- or None for a raw resource (comes from the land, not a
    recipe; see RESOURCE_SPAWN instead). Cloth, Meat, Milk, and Leather are
    the resources with more than one entry today."""
    return RECIPES.get(resource)


# --- Phase 6: agriculture -- growth seasons ---------------------------------
# "Instead of simply producing food every turn": each Crop now cycles
# through Plant -> Growing -> Harvest -> Dormant over the year, one stage
# per season, and only actually yields anything during its own Harvest
# stage. Different crops get different real calendars rather than one
# generic cycle applied to all 11:
#   - Wheat/Rye are true "winter grains" -- planted in Autumn, essentially
#     dormant over Winter, resume active growth in Spring, harvested in
#     Summer. (Rye shares Wheat's cycle -- both are winter-sown in reality;
#     Rye's extra cold-hardiness, already reflected in its climate
#     affinity from the world-gen phase, is what differentiates it, not a
#     different calendar.)
#   - Barley/Oats are fast-maturing spring cereals -- planted Spring,
#     harvested Autumn, the "generic" cycle from the request's own example.
#   - Potatoes/Carrots/Onions/Beans/Rice/Cotton all follow that same
#     standard Spring-plant/Autumn-harvest calendar too -- genuinely how
#     they're grown, not a cop-out; forcing artificial per-crop
#     differences where none exist agriculturally would be less honest
#     than the repetition.
#   - Peas are the one true outlier: a cool-season crop that can't take
#     summer heat, planted as early as Winter, harvested by Summer --
#     well before the Spring-planted crops even reach Harvest.
# Livestock/Forestry/Mining don't get a cycle -- scoped to Crops only, per
# the request.
GROWTH_CYCLE = {
    "Wheat":    {"Autumn": "Plant", "Winter": "Dormant", "Spring": "Growing", "Summer": "Harvest"},
    "Rye":      {"Autumn": "Plant", "Winter": "Dormant", "Spring": "Growing", "Summer": "Harvest"},
    "Barley":   {"Spring": "Plant", "Summer": "Growing", "Autumn": "Harvest", "Winter": "Dormant"},
    "Oats":     {"Spring": "Plant", "Summer": "Growing", "Autumn": "Harvest", "Winter": "Dormant"},
    "Potatoes": {"Spring": "Plant", "Summer": "Growing", "Autumn": "Harvest", "Winter": "Dormant"},
    "Carrots":  {"Spring": "Plant", "Summer": "Growing", "Autumn": "Harvest", "Winter": "Dormant"},
    "Onions":   {"Spring": "Plant", "Summer": "Growing", "Autumn": "Harvest", "Winter": "Dormant"},
    # Cut in Summer, a season EARLIER than the food harvest, so the hay is
    # already banked when the Autumn cull decision arrives -- you know what
    # you can feed before you choose how many to keep.
    "Fodder":   {"Spring": "Plant", "Summer": "Harvest", "Autumn": "Growing", "Winter": "Dormant"},
    "Beans":    {"Spring": "Plant", "Summer": "Growing", "Autumn": "Harvest", "Winter": "Dormant"},
    "Peas":     {"Winter": "Plant", "Spring": "Growing", "Summer": "Harvest", "Autumn": "Dormant"},
    "Rice":     {"Spring": "Plant", "Summer": "Growing", "Autumn": "Harvest", "Winter": "Dormant"},
    "Cotton":   {"Spring": "Plant", "Summer": "Growing", "Autumn": "Harvest", "Winter": "Dormant"},
    "Grapes":   {"Spring": "Plant", "Summer": "Growing", "Autumn": "Harvest", "Winter": "Dormant"},
}


def crop_stage(crop, season):
    """Plant/Growing/Harvest/Dormant for `crop` during `season`, or None
    for a non-Crop. Purely a function of the fixed annual GROWTH_CYCLE --
    no separate per-field planting-date state to track, since the whole
    world shares one season clock (world.season), so every region growing
    the same crop is always on the same point in its cycle."""
    return GROWTH_CYCLE.get(crop, {}).get(season)


def is_harvest_season(crop, season):
    return crop_stage(crop, season) == "Harvest"


# --- weather Phase 1: crop impact ---------------------------------------------
# Only the Growing/Plant window can hurt a crop -- a decision made explicitly
# over the alternative (a straight Harvest-turn multiplier) because that would
# mean a drought only ever matters if it happens to overlap the ~25-turn
# window a crop is actually being cut in, out of the full 100-turn year. This
# way a bad season shows up as a worse eventual harvest regardless of exactly
# when in the year it struck, which is what "a bad growing season" actually
# means. See app.world.weather for the event model itself -- this module owns
# every bit of what weather DOES to a crop, weather.py owns none of it.
#
# Per-turn nudge while a crop sits in Plant/Growing under an active event, by
# (kind, severity). Fog is deliberately absent -- it has no crop effect at
# all, reserved for a later phase's vision/logistics wiring; showing a "your
# crops are affected" alert for a weather kind that does nothing yet would be
# actively misleading. First-pass numbers, not measured -- see HANDOFF.md for
# what to re-tune once this has a full season's worth of real play behind it.
_CROP_WEATHER_IMPACT = {
    (weather.DROUGHT, weather.MILD): -0.015,
    (weather.DROUGHT, weather.SEVERE): -0.035,
    (weather.STORM, weather.MILD): -0.008,
    (weather.STORM, weather.SEVERE): -0.020,
    (weather.BLIZZARD, weather.MILD): -0.012,
    (weather.BLIZZARD, weather.SEVERE): -0.030,
}
CROP_WEATHER_KINDS = frozenset(k for k, _s in _CROP_WEATHER_IMPACT)
CROP_WEATHER_RECOVERY = 0.01   # per turn, whenever NOT actively being hurt --
                              # including Dormant/Harvest, so the land heals
                              # between growing seasons rather than staying
                              # scarred from one bad year forever
CROP_WEATHER_FLOOR = 0.35     # a crop's multiplier never drops below this --
                              # weather makes a harvest bad, never zero


def _advance_region_crop_weather(region, event, season):
    """One turn's stress/recovery on every crop `region` might be growing,
    stored as region.crop_weather_mult -- {crop: multiplier}, entries only
    ever present while below 1.0 (a crop at full health costs nothing to
    represent, the same reasoning weather.advance_all's clear-region-has-no-
    key convention uses). Applied at harvest time by compute_village_yield.

    Only a crop currently in Plant or Growing (see GROWTH_CYCLE) can be hurt
    THIS turn; a crop that isn't -- Dormant, or between plantings -- simply
    recovers. HARVEST IS FROZEN, deliberately not a third "recovers" case:
    a crop's own Harvest stage runs for a full season (~25 turns), and if it
    kept healing turn by turn while being cut, the SAME harvest would read
    better on turn 20 of it than it did on turn 1 -- one harvest cannot
    have two different outcomes depending on which turn within it you
    happen to check. The multiplier is set once Growing/Plant ends and
    holds steady for the whole window it's actually read in."""
    mult = getattr(region, "crop_weather_mult", None)
    if mult is None:
        mult = region.crop_weather_mult = {}
    impact = (_CROP_WEATHER_IMPACT.get((event.kind, event.severity))
             if event is not None else None)
    for crop in GROWTH_CYCLE:
        stage = crop_stage(crop, season)
        if stage == "Harvest":
            continue     # frozen -- see the docstring above
        current = mult.get(crop, 1.0)
        if impact is not None and stage in ("Plant", "Growing"):
            current = max(CROP_WEATHER_FLOOR, current + impact)
        else:
            current = min(1.0, current + CROP_WEATHER_RECOVERY)
        if current >= 1.0:
            mult.pop(crop, None)     # back to full health -- stop carrying it
        else:
            mult[crop] = current


def advance_weather(world):
    """One turn of regional weather for every OWNED region: rolls/advances
    each region's WeatherEvent (see app.world.weather) and applies this
    turn's crop stress/recovery from it. Called from advance_turn, after
    world.season is set for the turn and before production is computed, so
    this turn's harvest already reflects whatever weather is active right
    now rather than lagging a turn behind.

    Unclaimed wildland never rolls weather at all: nothing there has crops
    or an owner to show an alert to. A later phase's map overlay may want
    every region to have weather for visual richness; Phase 1 only needs
    the ones that can actually grow something."""
    if not hasattr(world, "region_weather"):
        world.region_weather = {}
    if not hasattr(world, "_weather_rng"):
        # An independent stream, not the turn loop's shared `random` module
        # state -- weather rolling for a large kingdom must not perturb
        # whatever anything ELSE this turn draws from random.random()
        # afterward, the same reasoning worldgen's own per-purpose RNGs
        # (region names, moisture, capital placement...) all get their own.
        world._weather_rng = random.Random((world.seed or 0) + 774_001)
    climates = {r.id: r.dominant_climate for r in world.regions
               if r.faction_idx >= 0}
    weather.advance_all(climates, world.region_weather, world._weather_rng)
    for region in world.regions:
        if region.faction_idx < 0:
            continue
        event = world.region_weather.get(region.id)
        _advance_region_crop_weather(region, event, world.season)


_CROPS = [name for name, spec in RESOURCES.items() if spec["category"] == "Crops"]
# Rough placeholder, not balance-tuned (same caveat as every other quantity
# in this file): a crop now only produces during ~1 of its 4 seasons
# instead of continuously, so its per-turn rate during Harvest is boosted
# roughly 4x versus the old always-on "Grain": 2.5/cell baseline, aiming
# for comparable *annual* totals rather than comparable *per-turn* ones.
BASE_CROP_YIELD_PER_CELL = 10.0


def _biome_land_shares(biome, resource_names):
    """What fraction of `biome`'s land each of `resource_names` gets, so
    resources sharing both a biome AND some other reason to all draw on it
    at once (Crops sharing a harvest season; Livestock sharing pasture)
    split the same land instead of each independently claiming the
    region's full cell count -- without this, N resources sharing a biome
    would overproduce/overpopulate Nx from identical acreage. Split by
    rarity, not evenly, so a common resource gets more of the land than an
    uncommon one. Shared by both Phase 6 (Crops) and Phase 7 (Livestock)
    below rather than duplicated."""
    eligible = [r for r in resource_names if biome in RESOURCE_SPAWN[r]["biomes"]]
    weights = {r: rarity_abundance(r) for r in eligible}
    total = sum(weights.values()) or 1.0
    return {r: w / total for r, w in weights.items()}


_CROP_SHARES_BY_BIOME = {biome: _biome_land_shares(biome, _CROPS) for biome in BIOMES}


def _crop_yield_core(biome_counts, climate, fertility_frac, season):
    """The actual Crop-yield formula, parameterized on raw geography
    (biome cell counts, dominant climate, fertility fraction) rather than a
    Region -- shared by compute_crop_yield (the region-wide wrapper, still
    used where a whole-region estimate is genuinely wanted: claim-spoils
    sizing, the Compendium) and compute_village_yield (the real per-village
    production a village's own local land sample feeds into every turn).
    See compute_crop_yield's docstring for what each term means; this is
    exactly that formula, just no longer tied to reading a Region."""
    result = {}
    for biome, cell_count in biome_counts.items():
        for crop, share in _CROP_SHARES_BY_BIOME.get(biome, {}).items():
            if not is_harvest_season(crop, season):
                continue
            fert_w = RESOURCE_SPAWN[crop]["fertility_weight"]
            fertility_mult = 1.0 + fert_w * (fertility_frac - 0.5)
            amount = (BASE_CROP_YIELD_PER_CELL * cell_count * share
                     * climate_affinity(crop, climate) * fertility_mult)
            # Float, like _industry_yield_core -- see _deliver_village_yield for
            # why per-turn rounding here silently deleted every small yield.
            if amount > 0:
                result[crop] = result.get(crop, 0) + amount
    return result


def compute_crop_yield(region, season):
    """This region's Crop production for `season` from the new per-crop
    registry (RESOURCE_SPAWN + GROWTH_CYCLE) -- additive to, and
    independent of, compute_region_yield's existing Grain-based number
    (see its STALE note above; the two coexist as separate resource lines
    for now, nothing has been unified). A crop contributes nothing at all
    outside its own Harvest season -- the actual "instead of simply
    producing food every turn" mechanic. When it is harvest time, output
    scales with the region's biome cell count, this crop's rarity-weighted
    share of that biome's farmland (see _biome_land_shares), its climate
    affinity, and fertility (weighted per-crop via fertility_weight -- a
    weight of 0 means fertility has no effect at all, 1.0 means it fully
    scales output between half and 1.5x across the 0..100% fertility
    range).

    A whole-region estimate now -- real per-turn production is per-village
    (see compute_village_yield); this stays for callers that genuinely want
    "if this whole region were farmed as one" (claim-spoils sizing, the
    Compendium's projected-yield figures)."""
    biome_counts = getattr(region, "biome_counts", {})
    climate = getattr(region, "dominant_climate", "temperate")
    fertility_frac = region.stats.get("fertility", 50) / 100.0
    return {c: round(a) for c, a in
            _crop_yield_core(biome_counts, climate, fertility_frac, season).items()
            if round(a) > 0}


# --- Phase 12: industry specialization ---------------------------------------
# "Now geography naturally creates economies... you never have to force
# specialization, it naturally happens because resources are regional."
#
# This is the Mining/Forestry migration Phase 9's storage section and
# trade.py's module docstring both flagged as still owed ("Mining/Forestry
# were never migrated to live production... the same STALE gap flagged
# since Phase 1"). RESOURCE_SPAWN/BUILDINGS/RECIPES already had every
# Mining and Forestry resource fully defined -- Iron Mine, Coal Mine,
# Sawmill, Toolsmith/Weaponsmith/Shieldwright and all -- but nothing ever
# actually produced them; they only ever existed as flavor-only labels
# (building_for/building_biomes are, and remain, unused anywhere else in
# the codebase). compute_industry_yield is that missing production step,
# built directly off compute_crop_yield just above -- same RESOURCE_SPAWN-
# driven biome/rarity/fertility/climate formula, reusing _biome_land_shares
# for the same reason Crops needed it (several Mining/Forestry resources
# sharing "mountain" or "forest" shouldn't each independently claim the
# region's full cell count).
#
# One real difference from Crops: no GROWTH_CYCLE/harvest-season gating.
# Logging and mining aren't biological -- there's no "dormant" season for a
# quarry -- so output is continuous, every turn, at a flat per-cell rate
# instead of concentrated into one season out of four the way a crop is.
#
# Once this actually produces Iron/Logs/etc., the immediate consequence is
# that a Mountain region really does end up rich in Iron/Coal/Stone while
# a Forest region ends up rich in Logs/Hardwood/Softwood/Resin -- the
# "naturally happens" part -- with zero new placement/construction
# mechanic needed, exactly like Wheat never needed a player to build a
# "Wheat Farm" (see _route_farm_production: this output is routed to the
# region's own Villages first, same as a Crop harvest, then converted
# locally at whichever Settlement it's shipped to via
# advance_settlement_production_chains -- both already fully generic,
# needing no changes here beyond widening _SETTLEMENT_STORAGE_RESOURCES
# below to include these resources and what's crafted from them).
#
# The old BIOME_YIELDS aggregate's "Iron"/"Coal"/"Stone"/"Wood" entries are
# retired below (see the STALE section) now that a real replacement
# exists, same reasoning as the Meat/BIOME_YIELDS cleanup a phase ago --
# otherwise a mountain region would double-produce Iron forever, once for
# free into the old national pool and again for real into village storage.
# Construction costs (settlements/shipyards/granaries/warehouses/ships),
# which used to draw their Wood/Stone/Iron requirement from that same old
# national pool, are migrated alongside it in construction.py/commander.py
# to draw from the faction's own settlement storage instead -- otherwise
# retiring the free version would have made every one of those permanently
# unaffordable once existing stockpiles ran out. "Wood" itself has no
# direct new-registry equivalent (see RESOURCE_SPAWN's own note: it was
# already split into Logs/Hardwood/Softwood back in Phase 3) and is
# renamed to Logs there, the direct structural-lumber equivalent.
_INDUSTRY = [name for name, spec in RESOURCES.items()
            if spec["category"] in ("Forestry", "Mining")]
_INDUSTRY_SHARES_BY_BIOME = {biome: _biome_land_shares(biome, _INDUSTRY) for biome in BIOMES}
# Rough placeholder, not balance-tuned (same caveat as every quantity in
# this file): no harvest-season boost the way Crops get (see above), so
# this is deliberately lower than BASE_CROP_YIELD_PER_CELL to land in a
# similar ballpark of annual totals despite producing every turn instead
# of ~1 season out of 4.
# Raw durable output (Forestry/Mining) is per-resource now, not one flat rate
# per category. These resources are *durable* (spoil_rate 0) and have almost no
# consumption sink -- construction is rare, processing converts only a trickle,
# and trade can't absorb the flood -- so at the old rates they pinned every
# settlement's storage to its cap within the first ~25 turns and stayed there
# (structural wood alone was ~77% of everything a faction had stored). These
# rates are cut hard so storage genuinely fills over time (a real management
# decision) instead of being maxed from the start.
#
# Firewood is the deliberate exception: it's survival-critical (winter heating
# -> freezing) and forest-poor regions cover their winter need by importing it
# from forest-rich ones via Regional Markets, so it's kept several times higher
# than the structural woods to stay abundant enough to redistribute. Its winter
# need is tiny (~0.003/capita, Winter only), so even at this reduced rate the
# empire-wide firewood surplus stays large.
BASE_FORESTRY_YIELD_PER_CELL = 0.6   # structural wood: Logs/Hardwood/Softwood/
                                      # Resin -- cut ~4x (was 2.5); no survival
                                      # role, they were the single biggest
                                      # storage clog in the game
FIREWOOD_YIELD_PER_CELL = 0.3         # survival fuel, cut ~8x from its old
                                      # effective 2.5: at this rate its Winter
                                      # draw-down roughly keeps pace with
                                      # production, so it stops being a storage
                                      # clog (was ~164k stored / 128x its need).
                                      # Forest-poor regions, which under-produce
                                      # it at this rate, are backstopped by the
                                      # scaled firewood scrounge (see
                                      # _firewood_scrounge_fraction) -- measured
                                      # freezing is unchanged from the old high
                                      # rate, the scrounge fully covers the cut.
BASE_MINING_YIELD_PER_CELL = 0.2     # cut a further ~2.5x (was 0.5): still a
                                      # durable, sink-less pile-up (Sand/Salt/
                                      # Gems/Stone/ore), none of it survival-
                                      # critical, so the safe place to keep cutting

# Gold Ore is the one Mining resource the general rate is badly wrong for, and
# for a reason that has nothing to do with storage: BASE_MINING_YIELD_PER_CELL
# was cut hard precisely because Sand/Salt/Stone/ore are a sink-less pile-up,
# but Gold Ore's entire purpose is to be consumed -- it is the only input to the
# only source of coin in the game (see the Gold Mine / Mint section below).
#
# At the general rate the currency simply did not exist. Measured on a fresh
# 10-faction world at turn 120: mountain is 4.5% of the map's land, villages are
# sited on FARMLAND rather than on peaks, so only 4 of 185 villages had a single
# mountain cell in catchment -- and those four had an ore potential of 0.09 to
# 0.32 a turn. The map produced ZERO Gold Ore, every Mint had nothing to strike,
# and the only coin in the game was the starting reserve draining to nothing
# (-7,500 over 120 turns, all of it construction).
#
# Raised so that the handful of villages that DO sit on a seam matter enormously
# rather than trivially, which is the right shape for a scarce, geographically
# determined resource: gold comes from the few places that have it, and
# developing one of those places is a real decision. A 33-cell mountain
# catchment goes from 0.32 ore a turn to ~4.8, and a tier-2 Gold Mine takes that
# to ~19 -- which then needs about 38 of that village's hands, taken off the
# harvest. That trade is the mechanic.
GOLD_ORE_YIELD_PER_CELL = 3.0

_RAW_YIELD_OVERRIDE = {"Firewood": FIREWOOD_YIELD_PER_CELL,
                       "Gold Ore": GOLD_ORE_YIELD_PER_CELL}


def _raw_yield_per_cell(resource):
    """Per-cell base output for a raw Forestry/Mining resource: a per-resource
    override (Firewood, kept high for survival; Gold Ore, because it is the
    only input to the game's only source of coin) else the category base."""
    over = _RAW_YIELD_OVERRIDE.get(resource)
    if over is not None:
        return over
    return (BASE_FORESTRY_YIELD_PER_CELL
            if RESOURCES[resource]["category"] == "Forestry"
            else BASE_MINING_YIELD_PER_CELL)


# The trickle every region manages regardless of biome -- see the note at the
# bottom of compute_industry_yield. Sized so a barren region takes roughly a
# dozen-plus turns to fund its share of a claim: enough to expand eventually,
# never enough to build an economy on.
BASELINE_INDUSTRY_FLOOR = {"Logs": 3, "Stone": 3}


def _industry_yield_core(biome_counts, climate, fertility_frac):
    """The actual Forestry/Mining formula, parameterized the same way
    _crop_yield_core is -- shared by compute_industry_yield (region-wide
    wrapper) and compute_village_yield (real per-village production).
    Deliberately does NOT apply BASELINE_INDUSTRY_FLOOR -- that floor is a
    per-REGION guarantee (see compute_industry_yield's note on it), applied
    once after summing every village's own real output, not per-village
    (a village-by-village floor would multiply it by however many villages
    a region happens to have, which was never the intent)."""
    result = {}
    for biome, cell_count in biome_counts.items():
        for resource, share in _INDUSTRY_SHARES_BY_BIOME.get(biome, {}).items():
            fert_w = RESOURCE_SPAWN[resource]["fertility_weight"]
            fertility_mult = 1.0 + fert_w * (fertility_frac - 0.5)
            base = _raw_yield_per_cell(resource)
            amount = (base * cell_count * share
                     * climate_affinity(resource, climate) * fertility_mult)
            if amount > 0:
                result[resource] = result.get(resource, 0) + amount
    return result


def compute_industry_yield(region, season):
    """This region's Forestry/Mining production -- the industrial-output
    counterpart to compute_crop_yield just above, sharing its exact
    formula shape (see that function's docstring), just without any
    harvest-season gating (see the section note above for why). Per-resource
    base rates (see _raw_yield_per_cell) -- structural wood and mining are cut
    hard as durable, sink-less storage-cloggers; Firewood stays high because
    it's survival-critical.

    A whole-region estimate now -- real per-turn production is per-village
    (see compute_village_yield), with BASELINE_INDUSTRY_FLOOR applied once
    at the region level afterward (see recompute_region_resources), not
    here. This function stays for callers that genuinely want a whole-
    region number (claim-spoils sizing, the Compendium)."""
    biome_counts = getattr(region, "biome_counts", {})
    climate = getattr(region, "dominant_climate", "temperate")
    fertility_frac = region.stats.get("fertility", 50) / 100.0
    result = {r: round(a) for r, a in
              _industry_yield_core(biome_counts, climate, fertility_frac).items()}

    # Every region scrapes together SOME timber and stone, whatever its biome:
    # scrub and deadwood, and rock prised out of the ground. Without this a
    # desert or steppe realm produces literally zero of both, and since claiming
    # wildland is now paid mostly in Logs and Stone (see expansion.CLAIM_BASE_COST)
    # such a realm could never expand at all -- a permanent dead end decided at
    # worldgen. On a late-game test map Stone was the single binding constraint
    # on 4 of 14 realms, and halving its price changed nothing, because their
    # problem was never price: it was that the number was zero.
    #
    # Deliberately a FLOOR rather than a bonus. A region already working real
    # forest or a quarry is far above it and gets nothing, so this cannot
    # re-inflate the Logs hoard that storage throttling exists to contain -- it
    # only lifts regions that would otherwise produce none, and slowly.
    if getattr(region, "biome_counts", None):
        for resource, floor in BASELINE_INDUSTRY_FLOOR.items():
            if result.get(resource, 0) < floor:
                result[resource] = floor
    return result


# --- Phase 14: labor -- production is an allocation, not a terrain readout ---
# Measured before this existed (dev/storage_audit.py, fresh 10-faction world,
# 120 turns): potential production ran ~51,100 household + ~9,700 durable
# units per turn against a TOTAL consumption of 944 Food + 659 Clothes + 700
# Luxury. Roughly fifty times more than anything in the game could use. Stated
# per person, which is the number that actually shows how far off it was: one
# village adult harvested 2.58 units of food a turn and ate 0.005 of them.
#
# No storage number can absorb a fifty-fold surplus, and it was never
# storage's job to. Every phase above is a valve on the same unbounded tap:
# storage_throttle silently deleted 53.6% of all household production at
# source before it existed, and spoilage/overflow destroyed 774,581 units on
# top of that. Neither figure was ever shown to the player, and neither was
# ever a decision -- a village produced exactly what its terrain allowed,
# every turn, forever, and the storage system quietly ate the difference.
# That is what made storage feel both punishing and meaningless at once: it
# was doing all the work and none of it was visible.
#
# Labor closes the tap at the correct end. Terrain no longer says what a
# village produces; it says what it COULD produce. A village's adults are a
# finite workforce split across the sectors its land offers, and each
# sector's real output is whichever ceiling binds first -- the land or the
# hands:
#
#     output = min(terrain potential, workers on that sector * output/worker)
#
# Both ceilings matter, and that is the entire point. Putting every hand on
# mining in a village with no ore still yields nothing, so terrain defines
# the CHOICE SPACE and labor decides what is actually taken out of it. A
# village can max one sector or spread itself thin over three; what it can no
# longer do is all of them at once.
#
# This also gives the seasons real texture for the first time. Crops only
# harvest in their own season (Autumn is 52,911 units of the map's farming,
# Summer 20,653, Spring and Winter zero), so under the default Auto policy
# hands genuinely move to the woods and the mines over Winter and back to the
# fields at harvest -- rather than every village doing everything, all year.
PRODUCTION_SECTORS = ("farming", "forestry", "mining", "fishing")

_SECTOR_BY_CATEGORY = {"Crops": "farming", "Forestry": "forestry",
                       "Mining": "mining", "Fishing": "fishing"}

# Units of output one worker brings in per turn, by sector -- the calibration
# knob for the whole system, and the one number to move if total production
# needs to go up or down. Ratios encode how much work a unit of each is:
# quarrying and ore are the most labor-hungry per unit, a woodcutter's cord of
# timber less so, and a harvest the least (one farmer works a lot of acres for
# a few weeks).
#
# These are deliberately NOT set so that a typical village can cover its whole
# terrain potential -- if they were, labor would never bind and this would be
# a no-op with extra steps. A p90 village (65 adults, 287 units of farming
# potential) throwing every hand at the harvest brings in 78 of those 287.
LABOR_OUTPUT_PER_WORKER = {
    "farming": 1.2,
    "forestry": 0.9,
    "mining": 0.5,
    "fishing": 0.8,
}

# Policies a village's labor can be set to. "Auto" is the default and is what
# an untouched realm runs on -- a player who never opens the panel is never
# punished for it, same contract DEFAULT_HERD_POLICY already sets.
LABOR_POLICIES = ("Auto", "Balanced", "Farming", "Forestry", "Mining", "Fishing")
DEFAULT_LABOR_POLICY = "Auto"
LABOR_POLICY_SECTOR = {"Farming": "farming", "Forestry": "forestry",
                       "Mining": "mining", "Fishing": "fishing"}
# A named focus is an emphasis, not an exclusive assignment: the rest of the
# village keeps working the other sectors. A hard 100% was tried in design and
# is a trap -- a village ordered to mine would stop growing its own food and
# starve on a stockpile of ore.
LABOR_FOCUS_SHARE = 0.70

# Hands every live sector gets before the policy distributes the rest, as a
# fraction of the workforce and capped by what that sector can actually absorb.
#
# Without this, weighting purely by potential meant a small sector got a share
# proportional to its TONNAGE, which erases rare resources completely: a
# village with 300 units of farming potential and a gold seam worth 0.2 units a
# turn gave mining a 0.0007 share -- effectively no one -- so the seam was never
# worked at all. Measured: a fresh world at turn 120 had produced zero Gold Ore
# and every Mint in the game had nothing to strike.
#
# The reserve costs almost nothing, because a sector that cannot absorb its
# reserve hands hands them straight back (see village_labor_factors' spillover):
# fully working that 0.2-unit seam takes 0.1 of a worker. What it buys is the
# right model -- a village always works the small things it has, and only has to
# CHOOSE between the things too big to do both.
LABOR_SECTOR_RESERVE = 0.05

# How hard a full pool pulls hands OFF the sector that fills it, under Auto.
# This is the feedback loop that makes storage *mean* something: a full
# warehouse doesn't silently delete the timber any more, it sends the
# woodcutters to the fields. Floor rather than zero so a sector never goes
# completely dark on a momentarily-full pool.
LABOR_PRESSURE_FLOOR = 0.15


def production_sector(resource):
    """Which workforce sector produces `resource`. Note this is about who
    does the WORK, not where the good ends up: Firewood is cut by foresters
    but stored in the granary (see storage_class), and the two answers are
    allowed to differ."""
    return _SECTOR_BY_CATEGORY.get(RESOURCES.get(resource, {}).get("category"))


def labor_policy(village):
    policy = getattr(village, "labor_policy", None)
    return policy if policy in LABOR_POLICIES else DEFAULT_LABOR_POLICY


def set_labor_policy(village, policy):
    if policy in LABOR_POLICIES:
        village.labor_policy = policy


# Scopes a labor order can be given at. Per-village exists because a village
# sitting on a gold seam is genuinely a different case from its neighbours; the
# wider two exist because a realm can hold hundreds of villages and an order
# that has to be given three hundred times is not a lever, it is a chore.
LABOR_SCOPES = ("village", "region", "realm")


def apply_labor_policy(world, village, policy, scope="village"):
    """Set `policy` on this village, on every village in its region, or on
    every village in its realm. Returns how many villages actually changed.

    Never touches another faction's villages, whatever the scope -- the scope
    widens which of YOUR villages an order reaches, and is not a way to give
    orders to someone else's."""
    if policy not in LABOR_POLICIES or scope not in LABOR_SCOPES:
        return 0
    if scope == "village":
        targets = [village]
    else:
        fac_idx = village.faction_idx
        targets = [v for v in world.villages if v.faction_idx == fac_idx]
        if scope == "region":
            targets = [v for v in targets if v.region_id == village.region_id]
    changed = 0
    for target in targets:
        if labor_policy(target) != policy:
            set_labor_policy(target, policy)
            # The allocation is cached per (turn, season) -- a policy change
            # inside a turn has to invalidate it or the panel keeps showing,
            # and the turn keeps producing, the old split.
            if hasattr(target, "_labor_cache"):
                del target._labor_cache
            changed += 1
    return changed


def labor_policy_available(world, village, policy):
    """Is `policy` a meaningful order at this village? A named sector focus is
    only offered where that sector has something to work -- ordering a
    landlocked village to fish is accepted by the model (it falls through to
    Auto rather than idling) but showing it as a choice would be a lie."""
    if policy not in LABOR_POLICIES:
        return False
    sector = LABOR_POLICY_SECTOR.get(policy)
    if sector is None:
        return True     # Auto and Balanced always apply
    season_any = any(
        _village_terrain_potential(world, village, s)[1].get(sector, 0) > 0
        for s in SEASONS)
    return season_any


def village_workforce(village):
    """Hands available to work this turn. Adults, matching what Food
    consumption already scales off (FOOD_PER_CAPITA) -- so "how many people
    does this village feed" and "how many people does it put in the fields"
    are the same headcount rather than two numbers free to drift apart."""
    return max(0, getattr(village, "adults", 0) or 0)


def _sector_pool_relief(node, potentials_by_sector_resource, sector):
    """0..1 -- how much room this sector's OUTPUT still has to land in,
    averaged over its own resources weighted by how much of each it would
    produce. Averaged rather than taken per-resource because labor is
    assigned to a sector, not to a good: a forester whose Softwood has
    nowhere to go is still worth sending out if the Firewood he also cuts is
    needed. Reuses storage_throttle, so this reads the same typed-pool
    fullness every other part of the storage system does."""
    weights = potentials_by_sector_resource.get(sector)
    if not weights:
        return 1.0
    total = sum(weights.values())
    if total <= 0:
        return 1.0
    relief = sum(storage_throttle(node, r) * amt for r, amt in weights.items()) / total
    return max(LABOR_PRESSURE_FLOOR, relief)


def _labor_shares(village, potentials, by_sector_resource):
    """{sector: fraction of the workforce}, from this village's policy.

    Under every policy a sector with no potential at all gets nothing -- there
    is no work to send anyone to -- which is also what makes Winter and Spring
    move hands out of farming on their own, with no seasonal rule anywhere."""
    live = [s for s in PRODUCTION_SECTORS if potentials.get(s, 0) > 0]
    if not live:
        return {}
    policy = labor_policy(village)

    if policy == "Balanced":
        weights = {s: 1.0 for s in live}
    elif policy in LABOR_POLICY_SECTOR:
        focus = LABOR_POLICY_SECTOR[policy]
        if focus in live:
            rest = [s for s in live if s != focus]
            spare = 1.0 - LABOR_FOCUS_SHARE if rest else 0.0
            weights = {focus: LABOR_FOCUS_SHARE}
            rest_total = sum(potentials[s] for s in rest) or 1.0
            for s in rest:
                weights[s] = spare * potentials[s] / rest_total
        else:
            # Ordered to fish with no water in reach. Fall through to Auto
            # rather than idling the village on an impossible order.
            weights = {s: potentials[s] for s in live}
    else:   # Auto
        # Potential-weighted, then damped by how full each sector's own output
        # pool already is -- the storage feedback loop described above.
        weights = {s: potentials[s] * _sector_pool_relief(village, by_sector_resource, s)
                   for s in live}

    total = sum(weights.values())
    if total <= 0:
        return {s: 1.0 / len(live) for s in live}
    return {s: w / total for s, w in weights.items()}


def village_labor_factors(world, village, potentials, by_sector_resource):
    """{sector: 0..1} -- the fraction of each sector's terrain potential this
    village's workforce can actually bring in.

    Labor left over on a sector that has already hit its terrain ceiling is
    handed to the sectors that haven't. Without that spillover a village with
    a trivial mine would strand real hands on it: they would be "assigned to
    mining", produce the mine's whole tiny output, and the remainder would
    simply evaporate rather than going to the fields.

    The redistribution REPEATS until nothing is left to place or every sector
    is full, and that is not a refinement -- a single pass silently leaks
    labor, because a sector receiving spillover can hit its own ceiling too
    and the excess handed to it has nowhere to go. dev/test_labor.py asserts
    the invariant directly (no idle hands while any sector is still short); it
    is what caught this."""
    workforce = village_workforce(village)
    if workforce <= 0 or not potentials:
        return {}
    shares = _labor_shares(village, potentials, by_sector_resource)
    if not shares:
        return {}

    def ceiling(sector):
        per = LABOR_OUTPUT_PER_WORKER.get(sector, 1.0)
        return potentials[sector] / per if per > 0 else 0.0

    # Every live sector is staffed enough to work what it has, up to a small
    # cap, before the policy splits the rest -- see LABOR_SECTOR_RESERVE.
    reserve = {s: min(ceiling(s), workforce * LABOR_SECTOR_RESERVE) for s in shares}
    spare_after_reserve = max(0.0, workforce - sum(reserve.values()))
    workers = {s: reserve[s] + spare_after_reserve * f for s, f in shares.items()}
    for _pass in range(len(workers) + 1):
        spare = 0.0
        hungry = []
        for sector, assigned in workers.items():
            room = ceiling(sector)
            if assigned > room:
                spare += assigned - room
                workers[sector] = room
            elif assigned < room:
                hungry.append(sector)
        if spare <= 1e-9 or not hungry:
            break
        # Redistributed in proportion to the room each still-unsatisfied
        # sector has left, so a spillover fills the sectors that can actually
        # absorb it instead of piling onto one that is nearly full again.
        room_total = sum(ceiling(s) - workers[s] for s in hungry)
        if room_total <= 1e-9:
            break
        for sector in hungry:
            room_left = ceiling(sector) - workers[sector]
            workers[sector] += spare * (room_left / room_total)

    factors = {}
    for sector, assigned in workers.items():
        potential = potentials[sector]
        if potential <= 0:
            continue
        per = LABOR_OUTPUT_PER_WORKER.get(sector, 1.0)
        factors[sector] = min(1.0, (assigned * per) / potential)
    return factors


def _village_terrain_potential(world, village, season):
    """({resource: amount} raw terrain yield, {sector: total},
    {sector: {resource: amount}}) -- what this village's LAND offers this
    season, before any labor limit. This is exactly what compute_village_yield
    used to return outright."""
    region = world.regions[village.region_id]
    biome_counts, climate, fertility_frac = village_local_sample(world, village, region)
    raw = _crop_yield_core(biome_counts, climate, fertility_frac, season)
    # Weather (see _advance_region_crop_weather) applies to the LAND's offer,
    # not to the workforce: a drought means there is less out there to bring
    # in, however many hands are sent.
    weather_mult = getattr(region, "crop_weather_mult", None)
    if weather_mult:
        for crop, amount in list(raw.items()):
            m = weather_mult.get(crop)
            if m is not None:
                raw[crop] = round(amount * m)
    industry = _industry_yield_core(biome_counts, climate, fertility_frac)
    # The Gold Mine works the seam harder (see GOLD_MINE_YIELD_MULT). Applied
    # to the LAND's offer, before labor, deliberately: a bigger mine is more
    # ore to dig, not free ore -- the extra still has to be worked by hands
    # that would otherwise be in the fields.
    ore = industry.get("Gold Ore", 0)
    if ore:
        industry["Gold Ore"] = round(ore * gold_mine_multiplier(village))
    for resource, amount in industry.items():
        raw[resource] = raw.get(resource, 0) + amount

    by_sector = defaultdict(float)
    by_sector_resource = defaultdict(dict)
    for resource, amount in raw.items():
        sector = production_sector(resource)
        if not sector or amount <= 0:
            continue
        by_sector[sector] += amount
        by_sector_resource[sector][resource] = amount

    # Fishing never went through the biome path (see _produce_fishing) but is
    # worked by the same hands, so it has to compete for them here or a
    # fishing village would get its catch for free on top of a full harvest.
    fish = getattr(village, "fish_yield", None)
    if fish is None:
        fish = _node_fish_yield(world, village.pos)
        village.fish_yield = fish
    if fish > 0:
        by_sector["fishing"] += fish
        by_sector_resource["fishing"]["Fish"] = fish

    return raw, dict(by_sector), dict(by_sector_resource)


def village_labor_state(world, village, season):
    """({sector: 0..1 factor}, {resource: raw potential}) for this village
    this turn, cached on the village per (turn, season).

    Cached because three separate callers need the same answer within one
    turn -- compute_village_yield for the harvest, _produce_fishing for the
    catch, and the UI for what to show the player -- and the potential behind
    it costs a (2r+1)^2 grid scan per village (village_local_sample). Keyed by
    season as well as turn because village_projected_annual_yield legitimately
    asks about seasons that aren't the current one."""
    key = (getattr(world, "turn", 0), season)
    cached = getattr(village, "_labor_cache", None)
    if cached is not None and cached[0] == key:
        return cached[1], cached[2]
    raw, potentials, by_sector_resource = _village_terrain_potential(world, village, season)
    factors = village_labor_factors(world, village, potentials, by_sector_resource)
    village._labor_cache = (key, factors, raw)
    return factors, raw


def village_labor_report(world, village, season=None):
    """What the labor panel shows: per sector, the land's offer, the hands on
    it, what actually comes in, and which of the three ceilings is binding --
    "hands", "land", or "season".

    A sector with nothing to offer THIS season is still listed, with its own
    best season's potential and `limited_by == "season"`. Dropping those rows
    was tried first and reads as a bug: crops only harvest in their own season
    (see GROWTH_CYCLE), so for half the year a farming village showed no
    Fields row at all and looked like it had no farmland.

    Read-only, and deliberately recomputed rather than read off
    village_labor_state's cache -- the panel wants a live answer against
    current storage, while the cache deliberately freezes one allocation
    decision per turn."""
    season = season or getattr(world, "season", SEASONS[0])
    raw, potentials, by_sector_resource = _village_terrain_potential(world, village, season)
    factors = village_labor_factors(world, village, potentials, by_sector_resource)
    workforce = village_workforce(village)
    shares = _labor_shares(village, potentials, by_sector_resource)

    # Only farming is season-gated, and only when it is idle right now, so the
    # extra terrain sampling this costs is paid on a panel open and never in
    # the turn loop.
    dormant = {}
    if potentials.get("farming", 0) <= 0:
        for other in SEASONS:
            if other == season:
                continue
            peak = _village_terrain_potential(world, village, other)[1].get("farming", 0)
            if peak > dormant.get("farming", 0):
                dormant["farming"] = peak

    rows = []
    for sector in PRODUCTION_SECTORS:
        potential = potentials.get(sector, 0)
        if potential <= 0:
            asleep = dormant.get(sector, 0)
            if asleep <= 0:
                continue
            rows.append({
                "sector": sector, "potential": round(asleep), "output": 0,
                "workers": 0, "factor": 0.0, "limited_by": "season",
            })
            continue
        factor = factors.get(sector, 0.0)
        rows.append({
            "sector": sector,
            "potential": round(potential),
            "output": round(potential * factor),
            "workers": potential * factor / LABOR_OUTPUT_PER_WORKER.get(sector, 1.0),
            "factor": factor,
            "limited_by": "hands" if factor < 0.999 else "land",
        })
    # Hands with nothing left to do, because every sector this village can work
    # has already hit its terrain ceiling. Worth stating outright: it is the
    # only case where changing the labour policy genuinely does nothing, and
    # without saying so the buttons look broken rather than unnecessary.
    idle = max(0, round(workforce - sum(r["workers"] for r in rows)))
    for row in rows:
        row["workers"] = round(row["workers"])
    return {"policy": labor_policy(village), "workforce": workforce,
            "sectors": rows, "idle": idle}


# --- Fishing: renewable, water-body-size-scaled -- deliberately its own
# code path, not a RESOURCE_SPAWN entry like every resource above. Every
# other raw resource is a per-region biome share (see compute_crop_yield/
# compute_industry_yield): it has no notion of "next to water" or "this
# lake is bigger than that one." Fish instead comes straight off a
# settlement's/village's own position -- adjacent to open ocean, a river
# (scaled by that specific river's real flow, already computed at
# worldgen -- see world.rivers), or a lake (scaled by that specific lake's
# own connected-cell size, since world.lake_cells has no per-lake grouping
# of its own) -- and never depletes, since it's recomputed fresh from the
# same static geography every turn rather than drawn down from a finite
# pool. Bigger water = more fish, exactly as requested.
FISH_ADJACENCY_REACH = 6          # cells -- double construction._SEA_COAST_REACH's
                                   # reach, since a village/settlement (unlike a
                                   # coastal-city check) can sit a bit further inland
                                   # and still plausibly work an adjacent river/lake
FISH_YIELD_OCEAN = 30
FISH_YIELD_PER_RIVER_FLOW = 0.6
FISH_YIELD_RIVER_CAP = 40
FISH_YIELD_PER_LAKE_CELL = 1.5
FISH_YIELD_LAKE_CAP = 40


def _lake_component_sizes(world):
    """{(x,y): that lake's own total cell count} across every lake in the
    world -- world.lake_cells is a flat set with no per-lake grouping, so a
    one-time flood-fill (cached on `world`, geography never changes after
    worldgen) is needed to know how big THIS specific lake is, not just
    that this cell is lake somewhere."""
    cache = getattr(world, "_lake_component_size_cache", None)
    if cache is not None:
        return cache
    lake_cells = getattr(world, "lake_cells", set())
    sizes = {}
    seen = set()
    for start in lake_cells:
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        component = []
        while stack:
            x, y = stack.pop()
            component.append((x, y))
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                nb = (nx, ny)
                if nb in lake_cells and nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        for cell in component:
            sizes[cell] = len(component)
    world._lake_component_size_cache = sizes
    return sizes


def _river_cell_flow(world):
    """{(x,y): that river's flow} for every river cell -- world.rivers
    already carries each individual river's own flow (a real size proxy,
    computed at worldgen from flow accumulation), just not indexed by
    cell. Cached the same way as _lake_component_sizes."""
    cache = getattr(world, "_river_cell_flow_cache", None)
    if cache is not None:
        return cache
    flow_by_cell = {}
    for river in getattr(world, "rivers", []):
        for cell in river["cells"]:
            flow_by_cell[cell] = max(flow_by_cell.get(cell, 0), river["flow"])
    world._river_cell_flow_cache = flow_by_cell
    return flow_by_cell


def _node_fish_yield(world, pos):
    """How much raw Fish a settlement/village at `pos` produces per turn --
    a short BFS (same 4-directional local-search shape as
    construction._is_coastal) out to FISH_ADJACENCY_REACH looking for the
    single best adjacent water source (ocean flat, river by that river's
    own flow, lake by that lake's own size) -- not summed across multiple
    sources, so a settlement that's both riverside and lakeside doesn't
    get double-counted, just whichever's bigger. 0 if no qualifying water
    is in reach at all."""
    x0, y0 = pos
    river_flow = _river_cell_flow(world)
    lake_sizes = _lake_component_sizes(world)
    best = 0
    seen = {(x0, y0)}
    frontier = [(x0, y0)]
    for _ in range(FISH_ADJACENCY_REACH):
        nxt = []
        for x, y in frontier:
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if not (0 <= nx < world.w and 0 <= ny < world.h) or (nx, ny) in seen:
                    continue
                seen.add((nx, ny))
                if world.owner[ny][nx] == OCEAN:
                    best = max(best, FISH_YIELD_OCEAN)
                elif (nx, ny) in river_flow:
                    amt = min(FISH_YIELD_RIVER_CAP,
                             round(river_flow[(nx, ny)] * FISH_YIELD_PER_RIVER_FLOW))
                    best = max(best, amt)
                elif (nx, ny) in lake_sizes:
                    amt = min(FISH_YIELD_LAKE_CAP,
                             round(lake_sizes[(nx, ny)] * FISH_YIELD_PER_LAKE_CELL))
                    best = max(best, amt)
                else:
                    nxt.append((nx, ny))
        frontier = nxt
        if not frontier:
            break
    return best


def _produce_fishing(world):
    """Add this turn's raw Fish straight to every settlement's/village's
    own storage (node.resources), not through the region-level
    compute_region_yield/_route_farm_production path every other raw
    resource uses -- Fish is inherently a per-node (water-adjacent-or-not)
    thing, not a per-region biome share to split evenly across a region's
    villages regardless of which one actually borders the water. Yield is
    computed once and cached on the node itself (node.fish_yield) since
    the underlying adjacency never changes -- avoids re-running the BFS
    above every single turn for every settlement and village in the
    world."""
    season = getattr(world, "season", SEASONS[0])
    for node in list(world.settlements) + list(world.villages):
        yield_amt = getattr(node, "fish_yield", None)
        if yield_amt is None:
            yield_amt = _node_fish_yield(world, node.pos)
            node.fish_yield = yield_amt
        if yield_amt <= 0:
            continue
        # A village's boats are crewed by the same hands that work its fields
        # and woods (Phase 14): the catch is whatever share of the workforce
        # fishing actually got. Settlements have no labor model -- they are
        # consumers, and their fishing fleet isn't a village's workforce
        # question -- so they land the full yield, unchanged.
        if not hasattr(node, "kind"):
            factors, _raw = village_labor_state(world, node, season)
            yield_amt = yield_amt * factors.get("fishing", 0.0)
            if yield_amt <= 0:
                continue
        if not hasattr(node, "resources"):
            node.resources = {}
        # Same storage feedback as the harvest (see storage_throttle): boats
        # don't land a catch there's no room to keep.
        landed = round(yield_amt * storage_throttle(node, "Fish"))
        if landed <= 0:
            continue
        node.resources["Fish"] = node.resources.get("Fish", 0) + landed


def village_projected_annual_yield(world, village):
    """{resource: amount} this Village can expect to produce over a full
    year (len(SEASONS) * TURNS_PER_SEASON turns) from its OWN local land
    (see compute_village_yield) -- real numbers, not the flavor
    farm_output stat (see the Village class). Crops only count during
    their own Harvest season (see GROWTH_CYCLE); Forestry/Mining are
    continuous, every turn, all year. Production is per-village now, not a
    region-wide number divided by however many villages happen to share
    the region -- more villages on good land means more total production,
    not a thinner slice for each one."""
    annual = defaultdict(float)
    # Per season rather than "one season stands in for the year": Forestry and
    # Mining are still season-independent at the land, but the LABOR split
    # across them is not (Phase 14) -- with the fields empty over Winter, Auto
    # sends those hands to the woods, so a year's timber is genuinely not four
    # times any one season's. Summing compute_village_yield season by season
    # is the only way to get that right, and it keeps this projection reading
    # off exactly the function the turn loop produces from.
    for season in SEASONS:
        for resource, amount in compute_village_yield(world, village, season).items():
            annual[resource] += amount * TURNS_PER_SEASON
    result = {r: round(a) for r, a in annual.items() if round(a) > 0}
    # Fish doesn't go through the region-level split above at all (see
    # _produce_fishing) -- it's this village's own adjacency, not a shared
    # regional pool, so it's added directly rather than divided by n_targets.
    # Labor-limited the same way the real catch is, season by season.
    fish = getattr(village, "fish_yield", None)
    if fish is None:
        fish = _node_fish_yield(world, village.pos)
        village.fish_yield = fish
    if fish:
        caught = sum(fish * village_labor_state(world, village, s)[0].get("fishing", 0.0)
                     for s in SEASONS) * TURNS_PER_SEASON
        if round(caught) > 0:
            result["Fish"] = result.get("Fish", 0) + round(caught)
    # This village's own herd (Milk/Wool/Eggs/Honey off the living animals,
    # Meat/Leather off the Autumn cull). Not divided by n_targets: the herd
    # belongs to THIS village, unlike the region-level crop and industry
    # yields above. Without this the panel's "Grows per year" quietly omitted
    # everything the animals produce, which for a pastoral village is most of
    # what it actually makes.
    for resource, amount in village_projected_herd_yield(world, village).items():
        result[resource] = result.get(resource, 0) + amount
    return result


def village_projected_herd_yield(world, village):
    """{resource: amount} this village's herd should yield over a full year,
    at its current head count and policy -- the livestock counterpart of the
    crop projection above. An estimate, like the rest of that panel: it
    assumes the herd holds steady and Winter doesn't force an emergency cull."""
    herds = getattr(village, "herds", None)
    if not herds:
        return {}
    out = defaultdict(int)
    policy = herd_policy_multiplier(village)
    yield_mult = herd_building_multiplier(village, "slaughterhouse", "yield")
    for animal, head in herds.items():
        spec = LIVESTOCK_DYNAMICS.get(animal)
        if spec is None or head <= 0:
            continue
        culled = round(head * spec["slaughter_rate"] * policy)
        for resource, product in spec["products"].items():
            if product["source"] == "population":
                out[resource] += round(head * product["per_head"])
            else:
                out[resource] += round(culled * product["per_head"] * yield_mult)
    return {r: a for r, a in out.items() if a > 0}


# --- Phase 7: livestock -- populations, not crops ---------------------------
# Animals don't behave like Crops: instead of a stateless stage that's just
# a function of the current season, a Livestock population is real,
# persistent state (region.livestock: animal -> head count) that genuinely
# grows and shrinks over time via births, natural deaths, and slaughter --
# and unlike a Crop's within-year harvest cycle, that update happens once a
# *year* (_is_new_year), matching the request's own framing.
#
# Byproducts (Wool, Milk, Eggs, Honey) scale with the living population --
# the animal survives collection, same "byproduct" distinction the
# recipes already carry from a couple phases ago. Slaughter products
# (Meat, Leather) scale with how many were actually slaughtered that year.
# Chickens and Bees never slaughter (slaughter_rate 0) -- there's no
# Chickens-Meat or Bees-anything-else recipe, consistent with the existing
# RECIPES; they only ever produce their byproduct.
LIVESTOCK_DYNAMICS = {
    "Cattle":   {"birth_rate": 0.30, "death_rate": 0.06, "slaughter_rate": 0.15,
                "products": {"Milk":    {"per_head": 8, "source": "population"},
                            "Meat":    {"per_head": 8, "source": "slaughter"},
                            "Leather": {"per_head": 4, "source": "slaughter"}}},
    "Sheep":    {"birth_rate": 0.35, "death_rate": 0.07, "slaughter_rate": 0.18,
                "products": {"Wool":    {"per_head": 3, "source": "population"},
                            "Milk":    {"per_head": 3, "source": "population"},
                            "Meat":    {"per_head": 3, "source": "slaughter"},
                            "Leather": {"per_head": 1, "source": "slaughter"}}},
    "Horses":   {"birth_rate": 0.20, "death_rate": 0.05, "slaughter_rate": 0.08,
                "products": {"Meat":    {"per_head": 6, "source": "slaughter"},
                            "Leather": {"per_head": 3, "source": "slaughter"}}},
    "Goats":    {"birth_rate": 0.40, "death_rate": 0.08, "slaughter_rate": 0.20,
                "products": {"Milk":    {"per_head": 4, "source": "population"},
                            "Meat":    {"per_head": 3, "source": "slaughter"},
                            "Leather": {"per_head": 1, "source": "slaughter"}}},
    "Chickens": {"birth_rate": 0.80, "death_rate": 0.15, "slaughter_rate": 0.0,
                "products": {"Eggs":    {"per_head": 6, "source": "population"}}},
    "Pigs":     {"birth_rate": 0.60, "death_rate": 0.10, "slaughter_rate": 0.30,
                "products": {"Meat":    {"per_head": 5, "source": "slaughter"},
                            "Leather": {"per_head": 2, "source": "slaughter"}}},
    "Bees":     {"birth_rate": 0.50, "death_rate": 0.20, "slaughter_rate": 0.0,
                "products": {"Honey":   {"per_head": 2, "source": "population"}}},
}

_LIVESTOCK = [name for name, spec in RESOURCES.items() if spec["category"] == "Livestock"]
_LIVESTOCK_SHARES_BY_BIOME = {biome: _biome_land_shares(biome, _LIVESTOCK) for biome in BIOMES}

# Rough placeholders, not balance-tuned (same caveat as every other quantity
# in this file). BASE_LIVESTOCK_CAPACITY_PER_CELL is picked so a typical
# ~200-cell plains region works out to roughly the request's own "20 Sheep"
# example once split among plains' other competing animals (Cattle/Horses/
# Chickens/Bees) by rarity share.
BASE_LIVESTOCK_CAPACITY_PER_CELL = 0.5


def _livestock_capacity(region, animal):
    """The most head of `animal` this region's land can sustain -- summed
    across every biome the region has that animal eligible for, each
    biome's contribution scaled by that animal's rarity-weighted share of
    it (see _biome_land_shares) so competing animals on shared pasture
    (e.g. Cattle/Sheep/Horses/Chickens/Bees all on plains) split it instead
    of each being able to fill it alone. Without a cap, a fast-breeding
    animal like Chickens or Bees (high birth_rate, no slaughter to offset
    it) would grow unbounded forever."""
    biome_counts = getattr(region, "biome_counts", {})
    total = 0.0
    for biome, cell_count in biome_counts.items():
        share = _LIVESTOCK_SHARES_BY_BIOME.get(biome, {}).get(animal, 0.0)
        total += BASE_LIVESTOCK_CAPACITY_PER_CELL * cell_count * share
    return round(total)



# --- Phase 6 of the storage rework: herds, feed and the autumn cull ---------
# Livestock used to be region-level state updated once per 100-turn year. That
# had three problems, all measured:
#   * The whole year's Meat arrived in ONE turn -- 8,735 head-worth at once --
#     and at spoil_rate 0.30 about 97% of it rotted within six turns. For
#     ~90% of every year there was no meat in the world at all.
#   * Herds sat at region level while every other economic actor (storage,
#     production, buildings) had moved to the village, so livestock could
#     never be shown, managed, or tied to anything.
#   * Nothing constrained a herd but land: animals ate nothing, so there was
#     no decision anywhere in the system.
#
# Herds now live on the Village, run on the SEASON, and eat:
#   Spring   births
#   Summer   (Fodder is cut -- see GROWTH_CYCLE)
#   Autumn   the cull: slaughter for Meat/Leather
#   Winter   feed from stored Fodder; shortfall culls, then starves
# Byproducts (Milk/Wool/Eggs/Honey) come off the living herd every season.
#
# The result is meat four times a year instead of one indigestible dump, and a
# real annual question -- keep the herd through Winter on stored hay, or take
# it now while it's still worth something.
HERD_SEASONS = ("Spring", "Summer", "Autumn", "Winter")

# --- herd policy: the player's dial on the Autumn cull ----------------------
# Multiplies each animal's own slaughter_rate. "Grow" banks animals for future
# years at the cost of meat now (and a bigger Winter feed bill); "Cull" takes
# the meat now and carries a smaller, cheaper herd through Winter. Set per
# village, defaulting to Balanced so an untouched realm behaves sensibly.
HERD_POLICIES = ("Grow", "Balanced", "Cull")
HERD_POLICY_MULTIPLIER = {"Grow": 0.4, "Balanced": 1.0, "Cull": 1.9}
DEFAULT_HERD_POLICY = "Balanced"


def herd_policy(village):
    policy = getattr(village, "herd_policy", None)
    return policy if policy in HERD_POLICY_MULTIPLIER else DEFAULT_HERD_POLICY


def set_herd_policy(village, policy):
    if policy in HERD_POLICY_MULTIPLIER:
        village.herd_policy = policy


def herd_policy_multiplier(village):
    return HERD_POLICY_MULTIPLIER[herd_policy(village)]


# --- herd buildings ---------------------------------------------------------
# Same tiered project machinery as the storage buildings (Phase 4) -- they set
# the ceiling and the efficiency, while herd policy sets how hard you harvest
# against it.
#   pasture        more head of everything
#   stable         more Horses, and a stronger cavalry/commander bonus
#   barn           less Winter Fodder needed, fewer natural deaths
#   slaughterhouse more Meat and Leather per animal taken
HERD_BUILDINGS = ("pasture", "stable", "barn", "slaughterhouse")
HERD_BUILDING_EFFECTS = {
    "pasture":       {"capacity": [1.0, 1.5, 2.1]},
    "stable":        {"capacity": [1.0, 1.8, 2.6]},
    "barn":          {"feed": [1.0, 0.75, 0.55], "death": [1.0, 0.8, 0.65]},
    "slaughterhouse": {"yield": [1.0, 1.35, 1.7]},
}
# Villages reach tier 1 of each; settlements aren't pastures and build none of
# these -- animals live where the fields are.
VILLAGE_HERD_MAX_TIER = 1


def herd_building_multiplier(village, building, effect):
    """Multiplier `building` applies to `effect` at this village, 1.0 (or the
    effect's own neutral value) if it hasn't been built."""
    table = HERD_BUILDING_EFFECTS.get(building, {}).get(effect)
    if not table:
        return 1.0
    tier = min(storage_tier(village, building), len(table) - 1)
    return table[tier]

# Fodder eaten per head per Winter, by animal. Roughly proportional to size:
# a cow eats an order of magnitude more than a chicken.
FODDER_PER_HEAD_WINTER = {
    "Cattle": 6.0, "Horses": 5.0, "Sheep": 2.0, "Goats": 1.8,
    "Pigs": 2.5, "Chickens": 0.3, "Bees": 0.0,   # bees overwinter on their own honey
}

# Of the animals that can't be fed, this fraction can still be slaughtered for
# Meat/Leather before the rest are simply lost. Not 1.0: a desperate winter
# cull is chaotic, and some of the herd is always lost outright rather than
# neatly butchered.
WINTER_EMERGENCY_CULL_FRACTION = 0.7

STARTING_VILLAGE_HERD_FRACTION = 0.6   # of village capacity, when seeding fresh


def _region_villages(world, region):
    return [world.villages[vid] for vid in getattr(region, "villages", [])
            if 0 <= vid < len(world.villages)]


def village_herd_capacity(world, village, animal):
    """Head of `animal` this village can sustain: its share of the region's
    land-derived carrying capacity (_livestock_capacity, split across the
    region's villages so they don't each claim the whole pasture), times
    whatever Pasture/Stable it has built."""
    region = world.regions[village.region_id]
    villages = getattr(region, "villages", []) or []
    share = _livestock_capacity(region, animal) / max(1, len(villages))
    share *= herd_building_multiplier(village, "pasture", "capacity")
    if animal == "Horses":
        share *= herd_building_multiplier(village, "stable", "capacity")
    return max(0, round(share))


def ensure_village_herd(world, village):
    """This village's {animal: head} dict, created on first access.

    Seeded from the region's old region.livestock pool, split evenly across
    the region's villages -- so a save written before herds moved to villages
    keeps the animals it already had instead of losing them or doubling them.
    The region pool is left in place but is no longer the source of truth."""
    herds = getattr(village, "herds", None)
    if herds is not None:
        return herds
    herds = {}
    region = world.regions[village.region_id]
    legacy = getattr(region, "livestock", None) or {}
    n = max(1, len(getattr(region, "villages", []) or []))
    for animal in _LIVESTOCK:
        capacity = village_herd_capacity(world, village, animal)
        if capacity <= 0:
            continue
        if legacy.get(animal):
            herds[animal] = min(round(legacy[animal] / n), capacity)
        else:
            herds[animal] = round(capacity * STARTING_VILLAGE_HERD_FRACTION)
    village.herds = herds

    # Seed one Winter's hay along with the herd. Fodder is a brand-new crop:
    # its first harvest is the following Summer, so a village adopting this
    # system mid-game would meet Winter with an empty barn and lose the whole
    # herd through no decision of its own. Measured on a real save: herds
    # collapsed 16,041 -> 3,438 head in a single winter, leaving almost
    # nothing but Bees (the one animal that eats no fodder). This is the hay
    # they are assumed to have already had in the barn, not a subsidy -- from
    # the next harvest on, the village feeds itself or culls.
    if not hasattr(village, "resources"):
        village.resources = {}
    need = sum(head * FODDER_PER_HEAD_WINTER.get(animal, 1.0)
               for animal, head in herds.items())
    if need > 0:
        village.resources["Fodder"] = max(village.resources.get("Fodder", 0),
                                          round(need))
    return herds


FODDER_STOCK_BUFFER = 1.25   # hay a village tries to hold, as a multiple of
                             # its own herd's Winter need -- a little margin,
                             # not a hoard


def village_winter_fodder_need(node):
    """Fodder this node's herd will eat next Winter, 0 for a node with no
    animals. Used both by the feeding itself and by local logistics, so hay
    actually moves to the villages that have mouths to feed."""
    herds = getattr(node, "herds", None)
    if not herds:
        return 0
    feed_mult = herd_building_multiplier(node, "barn", "feed")
    return round(sum(head * FODDER_PER_HEAD_WINTER.get(animal, 1.0) * feed_mult
                     for animal, head in herds.items()))


def faction_herd_total(world, fac_idx, animal):
    """Head of `animal` across every village this faction holds."""
    return sum((getattr(v, "herds", None) or {}).get(animal, 0)
               for v in world.villages if v.faction_idx == fac_idx)


def faction_horses(world, fac_idx):
    """Horses a faction can muster -- the cavalry input to _recompute_military
    and what decides whether its Commanders ride (see app/world/commander.py's
    MOUNTED_COMMANDER_HORSES)."""
    return faction_herd_total(world, fac_idx, "Horses")


def _seasonal(rate):
    """An annual rate applied once per season."""
    return rate / len(HERD_SEASONS)


def _is_new_season(turn):
    """True on the first turn of a season. advance_turn runs every turn, but
    a herd's year has four events, not a hundred -- without this the births,
    the cull and the winter feeding each fire TURNS_PER_SEASON times over,
    which in testing compounded 25 rounds of births and 25 separate winter
    feedings into a herd collapse from 16,041 head to 70."""
    return (turn - 1) % TURNS_PER_SEASON == 0


def advance_herds(world):
    """One season of every village's herds, on the season's first turn only.
    Returns {faction_idx: gold value produced}, the same contract
    advance_livestock had, so advance_turn can still fold it into
    prosperity."""
    value_by_fac = defaultdict(float)
    if not _is_new_season(world.turn):
        return value_by_fac
    season = world.season
    for village in world.villages:
        if village.faction_idx < 0:
            continue
        herds = ensure_village_herd(world, village)
        if not herds:
            continue
        products = defaultdict(int)

        # --- natural turnover, every season ---------------------------------
        death_mult = herd_building_multiplier(village, "barn", "death")
        for animal in list(herds):
            spec = LIVESTOCK_DYNAMICS.get(animal)
            if spec is None:
                continue
            head = herds[animal]
            if head <= 0:
                continue
            # Byproducts come off the herd as it stood THROUGH the season --
            # before this season's deaths and before the carrying-capacity
            # clamp, which is what the original annual code did too. Taking
            # them from the post-clamp number instead quietly under-counted
            # every milking and shearing in the game: a herd pushed over its
            # land ceiling by Spring births was clamped back down first, and
            # then only the survivors were milked, as though the rest had
            # never been there. Worth ~5% of the realm's food supply, which
            # on a food economy this tight was ~70 extra villages going
            # hungry.
            for resource, product in spec["products"].items():
                if product["source"] != "population":
                    continue
                amount = round(head * _seasonal(product["per_head"]))
                if amount:
                    products[resource] += amount

            if season == "Spring":
                head += round(head * spec["birth_rate"])
            head -= round(head * _seasonal(spec["death_rate"]) * death_mult)
            capacity = village_herd_capacity(world, village, animal)
            herds[animal] = max(0, min(head, capacity) if capacity else head)

        if season == "Autumn":
            _autumn_cull(world, village, herds, products)
        elif season == "Winter":
            _winter_feed(world, village, herds, products)

        if products:
            _deliver_herd_products(world, village, products)
            value_by_fac[village.faction_idx] += _resource_bundle_value(products)
    return value_by_fac


def _slaughter(village, animal, head, products):
    """Turn `head` of `animal` into Meat/Leather at this village, scaled by
    any Slaughterhouse it has built."""
    spec = LIVESTOCK_DYNAMICS.get(animal)
    if spec is None or head <= 0:
        return
    yield_mult = herd_building_multiplier(village, "slaughterhouse", "yield")
    for resource, product in spec["products"].items():
        if product["source"] != "slaughter":
            continue
        amount = round(head * product["per_head"] * yield_mult)
        if amount:
            products[resource] += amount


def _autumn_cull(world, village, herds, products):
    """The planned harvest: slaughter this year's take before Winter, at each
    animal's own slaughter_rate, adjusted by the village's herd policy."""
    policy = herd_policy_multiplier(village)
    for animal in list(herds):
        spec = LIVESTOCK_DYNAMICS.get(animal)
        if spec is None or not spec["slaughter_rate"]:
            continue
        head = herds[animal]
        culled = min(head, round(head * spec["slaughter_rate"] * policy))
        if culled <= 0:
            continue
        herds[animal] = head - culled
        _slaughter(village, animal, culled, products)


def _winter_feed(world, village, herds, products):
    """Feed the herd from this village's stored Fodder. Whatever it can't
    feed is culled for what Meat/Leather a rushed winter slaughter yields
    (WINTER_EMERGENCY_CULL_FRACTION), and the remainder is simply lost."""
    res = getattr(village, "resources", None)
    if res is None:
        res = village.resources = {}
    feed_mult = herd_building_multiplier(village, "barn", "feed")
    need = {a: FODDER_PER_HEAD_WINTER.get(a, 1.0) * feed_mult for a in herds}
    total_need = sum(herds[a] * need[a] for a in herds)
    if total_need <= 0:
        return
    available = res.get("Fodder", 0)
    if available >= total_need:
        res["Fodder"] = available - round(total_need)
        village.herd_fed = True
        return

    # Short. Feed what we can, then cut the herd down to what the hay covers,
    # taking the cheapest-to-keep animals last so a shortfall costs you the
    # big eaters first -- which is also what a real farmer would do.
    village.herd_fed = False
    res["Fodder"] = 0
    budget = available
    order = sorted(herds, key=lambda a: -need.get(a, 0))
    for animal in order:
        head = herds[animal]
        per = need.get(animal, 0)
        if head <= 0:
            continue
        if per <= 0:
            continue
        keep = min(head, int(budget / per))
        budget -= keep * per
        excess = head - keep
        if excess <= 0:
            continue
        culled = round(excess * WINTER_EMERGENCY_CULL_FRACTION)
        herds[animal] = keep
        _slaughter(village, animal, culled, products)   # the rest are lost


def _deliver_herd_products(world, village, products):
    """Route a village's herd output through its REGION, the same path a crop
    harvest takes, and without the production throttle.

    Both of those are deliberate and both were measured. Delivering straight
    into the owning village's own store threw away 42% of everything the herds
    produced -- Leather 94%, Wool 86%, Meat 65% -- because a season's output
    arrives as one lump at one node, and the throttle is sized for per-turn
    flow. Splitting it across the region (which is what the old annual path
    did) puts it where there is actually room.

    The throttle is skipped because it models a decision not to produce, and
    there is no such decision here: the animals have already been slaughtered
    and the cows have already been milked. If there is no room, the goods
    should arrive and then visibly overflow -- which the player can see and
    answer with a Warehouse -- rather than silently never existing."""
    if not products:
        return
    region = world.regions[village.region_id]
    _route_farm_production(world, region, products, throttle=False)


def current_year(turn):
    """1-indexed in-game year for `turn` -- turn 1..YEAR_LENGTH_TURNS is
    Year 1, etc. The UI's persistent year counter and year-rollover popup
    both derive from this, same YEAR_LENGTH_TURNS boundary _is_new_year
    uses below."""
    return (turn - 1) // YEAR_LENGTH_TURNS + 1


def _is_new_year(turn):
    """True on the first turn of every 4-season cycle -- the "every year"
    boundary births/natural deaths/slaughter fire on, unlike a Crop
    harvest (within-year) or the old Grain system (every turn)."""
    return (turn - 1) % YEAR_LENGTH_TURNS == 0


# The old annual, region-level livestock path (advance_livestock and its
# _ensure_region_livestock seeder) lived here. It was superseded by the
# per-village seasonal herd system above and is gone: leaving a second,
# non-functional production path in the file is exactly what caused the
# RECIPES confusion documented at that table. region.livestock itself is
# deliberately KEPT on Region -- ensure_village_herd still reads it to migrate
# saves written before herds moved to villages.


# --- Phase 8: consumption ---------------------------------------------------
# "Now does production become meaningful": nothing produced by any phase
# above was ever actually spent on anything -- resources just piled up
# (capped by storage, spoiled by rate, but never consumed as an input to
# something else). Two pieces close that loop:
#   1. advance_production_chains -- the RECIPES defined a few phases ago
#      finally get wired up for real: a building only actually produces
#      its output by consuming its recipe's input from the stockpile,
#      capped by what's available, instead of output materializing free.
#   2. advance_settlement_consumption -- a City/Town/Castle's population
#      needs Food, Firewood in Winter, and Clothes ("slowly" -- a much
#      smaller rate than Food). Villages stay exempt, matching their
#      existing "subsistence-level, no drain modeled" design (see the
#      Village class). This coexists with, doesn't replace, the older flat
#      SETTLEMENT_UPKEEP draw (Grain/Fresh Water/Iron) -- same "old and
#      new systems both run, unmerged" situation flagged since Phase 6.
# Water isn't modeled at all -- explicitly marked "(future)" in the
# request. "Workers consume Food" wasn't built as a second, separate draw
# -- there's no distinct "worker" headcount anywhere in the game today
# (only population/adults/children) -- it's read as confirming Food's need
# tracks the *working* (adult) population specifically, which is why Food
# below scales off settlement.adults while Firewood/Clothes (needs of the
# whole population, working or not) scale off settlement.population.
#
# A real, meaningful consequence for a shortfall: partial starvation/
# freezing (population loss, capped well under 100% so one bad turn can't
# wipe out a city) plus an immediate prosperity hit -- on top of whatever
# the smoothed _update_prosperity easing already does elsewhere. This is
# also the first thing in the whole overhaul to actually mutate
# population/adults/children after they're rolled once at placement --
# previously a pure flavor stat that "doesn't feed the economy" (see
# HANDOFF.md); a bad enough shortage now genuinely shrinks a settlement.

CONVERSION_RATE_CAP = 30   # rough placeholder, not balance-tuned: max units
                           # of output a single recipe can produce per turn
                           # (was 50 -- trimmed some, though this was never
                           # the main source of the economy feeling
                           # trivially abundant -- see BASE_MINING_YIELD_
                           # PER_CELL for where most of that actually was)
LUXURY_CONVERSION_RATE_CAP = 2   # Luxury Goods specifically convert far
                                 # slower than staple processed goods --
                                 # explicit request: they "shouldn't be
                                 # widespread until industries have been
                                 # running a while." Deliberately BELOW a
                                 # typical settlement's own Luxury need
                                 # (settlement_needs' Luxury figure often
                                 # runs 6-9+ for a real settlement) -- not
                                 # just slower than the general cap, but
                                 # genuinely unable to keep pace with
                                 # demand at first, so it stays scarce
                                 # rather than quietly catching up to
                                 # "enough for the whole population" within
                                 # the first year regardless. Even with a
                                 # settlement sitting on a big stockpile of
                                 # Gems/Grapes/Honey, only a trickle becomes
                                 # an actual Luxury Good each turn, so a real
                                 # stockpile only builds up gradually over
                                 # many turns instead of within the first
                                 # year.
LUXURY_CONVERSION_MIN_TURN = 100   # a full year (TURNS_PER_SEASON * 4) --
                                   # no Luxury Good converts AT ALL before
                                   # this, on top of the trickle-rate cap
                                   # above, so "industries have been running
                                   # a while" is a real, hard requirement,
                                   # not just a slow ramp from turn 1.


def advance_production_chains(world):
    """Called every turn: for every processed resource with a recipe (see
    RECIPES), convert available input stock into output, a simplifying
    1:1 ratio (real ratios -- e.g. Cheese from Milk realistically losing a
    lot of volume -- are a further balancing step), capped by
    CONVERSION_RATE_CAP and by whichever input is scarcest for a
    multi-input recipe (Shields can't outrun its Hardwood supply just
    because Iron is abundant). Tries each alternative recipe in the order
    it's listed, using the first one with any stock at all -- not a
    smarter "whichever's more abundant" choice, a further refinement if it
    turns out to matter. Recipes sourced from a Livestock population
    (Meat, Milk, Wool, Eggs, Honey -- see advance_livestock) never fire
    here: those animals are never stockpiled in the first place, only
    their products are, produced directly by the population mechanic --
    so "available" for e.g. Cattle is always 0 and nothing double-
    converts. Since Phase 9, this only handles recipes whose output is
    *not* in _SETTLEMENT_STORAGE_RESOURCES (Tools/Weapons/Shields/Planks/
    Bricks/Glass -- Mining/Forestry-sourced goods, whose raw inputs still
    only exist on this shared pool); everything else converts locally at
    the settlement that owns it instead -- see
    advance_settlement_production_chains."""
    for nation in world.factions:
        res = nation.stats.setdefault("resources", {})
        changed = False
        for output, options in RECIPES.items():
            if output in _SETTLEMENT_STORAGE_RESOURCES:
                continue
            if RESOURCES[output]["luxury"]:
                if world.turn < LUXURY_CONVERSION_MIN_TURN:
                    continue
                cap = LUXURY_CONVERSION_RATE_CAP
            else:
                cap = CONVERSION_RATE_CAP
            for option in options:
                inputs = option["inputs"]
                available = min(res.get(i, 0) for i in inputs)
                amount = min(available, cap)
                if amount <= 0:
                    continue
                for i in inputs:
                    res[i] -= amount
                res[output] = res.get(output, 0) + amount
                changed = True
                break
        if changed:
            _clamp_to_storage(nation)
            _recompute_military(nation, world)


# Rough placeholders, not balance-tuned (same caveat as every quantity in
# this file): picked to land roughly in the same ballpark as the existing
# SETTLEMENT_UPKEEP Grain range for a similarly-sized settlement, since
# that's the closest existing reference point.
FOOD_PER_CAPITA = 0.005              # per adult, per turn
FIREWOOD_PER_CAPITA_WINTER = 0.003   # per total population, Winter only
CLOTHES_PER_CAPITA = 0.0003          # per total population -- "slowly"
# Phase 13 -- a "nice to have", not a staple, but priced to actually
# scale across the game's real population range rather than flatlining at
# the population_scaled_need floor of 1 for everything except the very
# largest cities (an early value here, an order of magnitude below
# Clothes, did exactly that in testing -- a village of 150 and a city of
# 10,000 both "needed" the same single unit, which isn't really a
# per-capita rate at all). A bit above Clothes' own rate: everyone enjoys
# a bit of Wine or Jewelry, not just a wealthy few.
LUXURY_PER_CAPITA = 0.0008           # per total population

STARVATION_SEVERITY = 0.05   # max fraction of population lost/turn under total famine
FREEZE_SEVERITY = 0.02       # max fraction lost/turn under total winter fuel shortage
STARVATION_GRACE_TURNS = 10   # consecutive turns a node can go with an unmet
                              # Food need before population loss actually
                              # starts (see Settlement/Village.turns_without_food
                              # and _consume_node_needs) -- a short rough patch
                              # (a slow supply chain, a bad harvest) shouldn't
                              # be an irreversible death spiral on its own.
FREEZE_GRACE_TURNS = 8        # same idea as STARVATION_GRACE_TURNS, for an
                              # unmet Firewood need in Winter -- shorter than
                              # Food's, since freezing is the faster of the
                              # two dangers, but still leaves real room (a
                              # season is TURNS_PER_SEASON turns long) before
                              # a supply hiccup starts costing population.
_SHORTAGE_PROSPERITY_PENALTY = {"Food": 8.0, "Firewood": 5.0, "Clothes": 2.0}

# A region with zero Forest-biome cells can never produce Firewood locally
# (see compute_industry_yield's biome gate) -- and if that region is also
# the only one its faction owns, Regional Markets (trade.py) has nothing to
# redistribute either, leaving foreign trade (which requires the player to
# actually propose/accept a route) as the ONLY path to any real Firewood at
# all. Without this, a faction stranded that way grinds toward its
# population floor every single winter forever, with no in-game signal of
# why. This covers up to half of any deficit via basic scrounging (dung,
# scrub, deadfall, salvage) when the settlement's own region has no Forest
# access whatsoever -- real Forestry or trade still clearly beats it, and a
# region that DOES have forest but is just having a bad supply turn gets no
# help from this at all.
NO_FOREST_SUBSISTENCE_FRACTION = 0.5
# Above this forest share a region produces enough Firewood to fend for itself,
# so it gets no scrounge backstop at all; below it the backstop scales up
# (linearly) to the full NO_FOREST_SUBSISTENCE_FRACTION at zero forest. This is
# what lets Firewood production be cut hard (see FIREWOOD_YIELD_PER_CELL)
# without newly freezing forest-POOR regions -- not just the forest-ZERO ones
# the old binary check covered.
FOREST_SELF_SUFFICIENT_SHARE = 0.20


def _region_has_forest(world, node):
    region = world.regions[node.region_id]
    return region.biome_counts.get("forest", 0) > 0


def _firewood_scrounge_fraction(world, node):
    """Fraction of a Firewood deficit a region can cover by scrounging (dung,
    scrub, deadfall) -- full NO_FOREST_SUBSISTENCE_FRACTION with no forest at
    all, tapering to 0 by FOREST_SELF_SUFFICIENT_SHARE forest cover, above
    which the region grows plenty and gets no help."""
    region = world.regions[node.region_id]
    total = sum(region.biome_counts.values())
    if total <= 0:
        return NO_FOREST_SUBSISTENCE_FRACTION
    forest_share = region.biome_counts.get("forest", 0) / total
    if forest_share >= FOREST_SELF_SUFFICIENT_SHARE:
        return 0.0
    return NO_FOREST_SUBSISTENCE_FRACTION * (1.0 - forest_share / FOREST_SELF_SUFFICIENT_SHARE)
# Phase 13's mirror image of the shortage penalties above: met luxury
# demand nudges prosperity UP by this much (scaled by how much of it was
# actually met, same deficit-fraction shape the penalties use) instead of
# merely avoiding a penalty -- unmet luxury demand is simply a non-event,
# never a population/starvation consequence, since these aren't survival
# goods. Originally landed in the same rough scale as the shortage
# penalties (6.0, next to Food's 8.0) -- but unlike the penalties (a
# "bad conditions hurt right away" urgency mechanic, deliberately fast),
# this is meant to be a REWARD, and at that scale it completely bypassed
# PROSPERITY_EASE's whole "slow, long-term payoff" design: full luxury
# fulfillment alone maxed a settlement's meter out in ~17 turns
# (100 / 6.0), regardless of how healthy the rest of its economy actually
# was. Cut down so sustained full fulfillment alone takes roughly a year
# to meaningfully move the needle, consistent with the ~230-turn/90%-
# closure timescale the base eased mechanism already uses.
LUXURY_PROSPERITY_BONUS = 0.3

_FOOD_PRODUCTS = [name for name, spec in RESOURCES.items()
                 if spec["category"] == "Food Products" and spec["edible"]]
# Raw Crops (Wheat, Potatoes, Grapes, ...) are already flagged "edible" in
# the registry, but until now that flag was never actually acted on for
# consumption purposes -- population could only eat a converted Food
# Product (Bread, Meat, ...), never the raw grain sitting right there in
# storage. That's a real gap, not just a flavor simplification: a Village
# has no mill/loom/forge of its own (see the Village class), so it can
# NEVER produce a Food Product itself -- its only path to eating was
# depending on a multi-turn round trip through some Settlement's
# production chain (ship raw Wheat out, convert it over several turns,
# ship Bread back), and a region with only Villages and no Settlement at
# all (every fresh wildland claim starts this way -- see expansion.py) had
# no such path whatsoever, guaranteeing permanent starvation. Pooling raw
# Crops in as a real (if less efficient/valuable) food source closes that
# gap for good, on top of the STARVATION_GRACE_TURNS buffer above.
_RAW_FOOD_CROPS = [name for name, spec in RESOURCES.items()
                  if spec["category"] == "Crops" and spec["edible"]]
# The actual pool consumption/local-logistics/trade-safety-reserve code
# draws "Food" from -- Food Products first in priority (see
# _LOCAL_SHIPMENT_PRIORITY) since that's still the intended normal path,
# raw Crops as a real fallback, not a last-resort hack.
_FOOD_SOURCES = _FOOD_PRODUCTS + _RAW_FOOD_CROPS
# Every Luxury Good is fully interchangeable for satisfying "luxury
# demand" -- a settlement with Wine but no Jewelry is just as well
# provided for as one with the reverse -- same pooled-consumption
# treatment _FOOD_SOURCES already gets via _consume_from_pool.
_LUXURY_GOODS = [name for name, spec in RESOURCES.items()
                if spec["category"] == "Luxury Goods"]


def _population_scaled_need(headcount, per_capita):
    """round(headcount * per_capita), except a nonzero population never
    rounds all the way down to zero demand. FOOD_PER_CAPITA/
    FIREWOOD_PER_CAPITA_WINTER/CLOTHES_PER_CAPITA were tuned against
    settlement-scale populations (thousands); a Village's few hundred
    would otherwise round-trip to a "need" of 0 for everything, which
    silently broke Phase 10's whole premise until this was caught in
    testing -- a village that structurally can never need Bread has
    nothing for local logistics to ever actually deliver."""
    if headcount <= 0:
        return 0
    return max(1, round(headcount * per_capita))


def settlement_needs(settlement, season):
    """{"Food": ..., "Firewood": ..., "Clothes": ..., "Luxury": ...} --
    this settlement's (or village's -- see _population_scaled_need)
    per-turn needs. The single source of truth for the per-capita formulas
    above: reused by advance_settlement_consumption (actual draining),
    settlement_needs_value (prosperity), trade's safety-reserve calc,
    local logistics' surplus/need matching (Phase 10), and the settlement
    info panel (see app/ui/map_view.py). Firewood is omitted entirely
    outside Winter -- it isn't needed then at all. Luxury (Phase 13) is
    the one entry here that's never survival-critical -- see
    _consume_node_needs for how it's actually treated differently."""
    needs = {"Food": _population_scaled_need(settlement.adults, FOOD_PER_CAPITA)}
    if season == "Winter":
        needs["Firewood"] = _population_scaled_need(settlement.population, FIREWOOD_PER_CAPITA_WINTER)
    needs["Clothes"] = _population_scaled_need(settlement.population, CLOTHES_PER_CAPITA)
    needs["Luxury"] = _population_scaled_need(settlement.population, LUXURY_PER_CAPITA)
    return needs


def settlement_needs_value(settlement, season):
    """Gold-equivalent value of settlement_needs() -- the replacement for
    the old upkeep-dict-based "goods handled" figure now that
    SETTLEMENT_UPKEEP is gone (see the module docstring). Food's value
    uses tier 3 directly (every Food Product shares that tier, so which
    one actually gets eaten doesn't change the value) rather than naming
    one specific resource the way the old figure named Grain. Luxury
    (Phase 13) uses tier 5 the same way, for the same reason."""
    needs = settlement_needs(settlement, season)
    value = needs["Food"] * BASE_VALUE_BY_TIER[3]
    if "Firewood" in needs:
        value += resource_value("Firewood", needs["Firewood"])
    value += resource_value("Clothes", needs["Clothes"])
    value += needs["Luxury"] * BASE_VALUE_BY_TIER[5]
    return value


def _consume_from_pool(res, resource_names, needed):
    """Draw `needed` total units from `res`, spread across whichever of
    `resource_names` actually have stock (biggest stockpile first) -- used
    for Food, which can come from any edible Food Product, not one
    specific resource. Returns how much was actually available/consumed
    (may be less than `needed`)."""
    pool = sorted((r for r in resource_names if res.get(r, 0) > 0),
                  key=lambda r: res[r], reverse=True)
    remaining = needed
    for r in pool:
        if remaining <= 0:
            break
        take = min(res[r], remaining)
        res[r] -= take
        remaining -= take
    return needed - remaining


POPULATION_MIN_FRACTION = 0.05   # a settlement/village can never be pushed
                                  # below this fraction of its OWN
                                  # max_population (see worldgen.
                                  # _roll_population) by starvation/
                                  # freezing -- "a minimum possible
                                  # population before it collapses," a
                                  # hard-scrabble remnant that survives
                                  # rather than the settlement genuinely
                                  # being wiped out
POPULATION_GROWTH_RATE = 0.0001  # fraction of the remaining gap to
                                  # max_population closed per turn, while
                                  # NOT currently in a food/firewood
                                  # shortfall grace period -- deliberately
                                  # tiny ("very very slowly" per the
                                  # request): asymptotic, not a flat
                                  # amount, so growth naturally tapers off
                                  # approaching the ceiling instead of
                                  # ever overshooting it. See _grow_
                                  # population's own fractional-
                                  # accumulator note for why this doesn't
                                  # just round down to a permanent zero
                                  # for a small village.


def _apply_population_loss(settlement, loss):
    """Remove `loss` head from a settlement, split proportionally between
    adults/children so population == adults + children stays true (rather
    than only decrementing one and leaving the identity broken). Never
    pushes population below POPULATION_MIN_FRACTION of the settlement's
    own max_population -- old saves predating that field (None/missing)
    fall back to the original no-floor behavior."""
    max_pop = getattr(settlement, "max_population", None)
    floor = round(max_pop * POPULATION_MIN_FRACTION) if max_pop else 0
    loss = max(0, min(loss, settlement.population - floor))
    if loss <= 0:
        return
    adult_frac = settlement.adults / settlement.population if settlement.population else 0.0
    adult_loss = round(loss * adult_frac)
    child_loss = loss - adult_loss
    settlement.population -= loss
    settlement.adults = max(0, settlement.adults - adult_loss)
    settlement.children = max(0, settlement.children - child_loss)


def _grow_population(node):
    """Slow organic growth toward this node's own max_population ceiling
    (see worldgen._roll_population/POPULATION_GROWTH_RATE) -- only while
    it isn't currently in a food/firewood shortfall grace period (see
    _consume_node_needs, which calls this after updating turns_without_
    food/turns_without_firewood for the turn). A small village's fair
    share of the gap (e.g. 0.2 head/turn) would just silently round down
    to zero forever if computed fresh each turn -- node._pop_growth_accum
    is a hidden fractional carry so those tiny amounts genuinely
    accumulate into a real head of population every several turns instead
    of never growing at all. Old saves predating max_population (None/
    missing) simply never grow, matching their prior no-growth behavior."""
    max_pop = getattr(node, "max_population", None)
    if not max_pop or node.population >= max_pop:
        return
    if getattr(node, "turns_without_food", 0) > 0 or getattr(node, "turns_without_firewood", 0) > 0:
        return
    accum = getattr(node, "_pop_growth_accum", 0.0)
    accum += (max_pop - node.population) * POPULATION_GROWTH_RATE
    gain = int(accum)
    node._pop_growth_accum = accum - gain
    if gain <= 0:
        return
    gain = min(gain, max_pop - node.population)
    adult_frac = node.adults / node.population if node.population else 1.0
    adult_gain = round(gain * adult_frac)
    child_gain = gain - adult_gain
    node.population += gain
    node.adults += adult_gain
    node.children += child_gain


def _consume_node_needs(node, season, world):
    """Draw Food/Firewood/Clothes/Luxury for one population-owning node
    (Settlement or Village -- both share the same population/adults/
    resources shape) from its own storage, applying the same starvation/
    freezing/prosperity consequences either way -- except Luxury (Phase
    13), which never has a starvation/freezing-style consequence, only a
    prosperity one, and only in the positive direction (see below).
    Returns the gold-value of what was needed (see settlement_needs_value)."""
    if not hasattr(node, "resources"):
        node.resources = {}
    res = node.resources
    needs = settlement_needs(node, season)
    value = settlement_needs_value(node, season)

    food_needed = needs["Food"]
    food_had = _consume_from_pool(res, _FOOD_SOURCES, food_needed)
    if food_needed > 0 and food_had < food_needed:
        # STARVATION_GRACE_TURNS: a short rough patch doesn't cost anyone
        # their lives -- only once this node has gone hungry for MORE than
        # that many turns IN A ROW does population loss actually start (old
        # saves default to 0 via getattr, same as every other new node
        # attribute added after saves already existed).
        node.turns_without_food = getattr(node, "turns_without_food", 0) + 1
        deficit = (food_needed - food_had) / food_needed
        node.prosperity = max(0.0, node.prosperity
                             - _SHORTAGE_PROSPERITY_PENALTY["Food"] * deficit)
        if node.turns_without_food > STARVATION_GRACE_TURNS:
            _apply_population_loss(node, round(node.population * deficit * STARVATION_SEVERITY))
    else:
        node.turns_without_food = 0

    if "Firewood" in needs:
        wood_needed = needs["Firewood"]
        wood_had = min(res.get("Firewood", 0), wood_needed)
        res["Firewood"] = res.get("Firewood", 0) - wood_had
        if wood_had < wood_needed:
            wood_had += (wood_needed - wood_had) * _firewood_scrounge_fraction(world, node)
        if wood_needed > 0 and wood_had < wood_needed:
            # FREEZE_GRACE_TURNS -- same reasoning as Food's grace period
            # above: a Winter-long cold snap shouldn't be an instant,
            # every-single-turn population drain from the moment Firewood
            # first runs short.
            node.turns_without_firewood = getattr(node, "turns_without_firewood", 0) + 1
            deficit = (wood_needed - wood_had) / wood_needed
            node.prosperity = max(0.0, node.prosperity
                                 - _SHORTAGE_PROSPERITY_PENALTY["Firewood"] * deficit)
            if node.turns_without_firewood > FREEZE_GRACE_TURNS:
                _apply_population_loss(node, round(node.population * deficit * FREEZE_SEVERITY))
        else:
            node.turns_without_firewood = 0
    else:
        node.turns_without_firewood = 0

    clothes_needed = needs["Clothes"]
    clothes_had = min(res.get("Clothes", 0), clothes_needed)
    res["Clothes"] = res.get("Clothes", 0) - clothes_had
    if clothes_needed > 0 and clothes_had < clothes_needed:
        deficit = (clothes_needed - clothes_had) / clothes_needed
        node.prosperity = max(0.0, node.prosperity
                             - _SHORTAGE_PROSPERITY_PENALTY["Clothes"] * deficit)

    # Luxury (Phase 13) -- "these improve prosperity instead of survival."
    # The mirror image of the three shortage penalties above: fulfillment
    # scales a BONUS instead of scaling a penalty, and there's no
    # population-loss branch at all -- going without Wine or Jewelry never
    # starves or freezes anyone, it just means missing out on the boost.
    luxury_needed = needs["Luxury"]
    if luxury_needed > 0:
        luxury_had = _consume_from_pool(res, _LUXURY_GOODS, luxury_needed)
        fulfillment = luxury_had / luxury_needed
        node.prosperity = min(PROSPERITY_MAX, node.prosperity
                             + LUXURY_PROSPERITY_BONUS * fulfillment)

    _grow_population(node)
    return value


# --- Player alerts: surfacing trouble instead of requiring the player to
# babysit every settlement's numbers turn after turn. Deliberately NOT an
# event log (like world.trade_events) -- these describe CURRENT ongoing
# state (derived fresh from turns_without_food/turns_without_firewood/
# storage each time), so a problem that's been going on for 20 turns still
# shows up even if the player only checks now, not just the turn it
# started. Population loss in this game only ever has two causes (see
# _consume_node_needs above -- there's no war-casualty/disease drain), so
# "starving"/"freezing" already cover every population-decline case, not
# just a Food/Firewood-specific subset of a broader mechanic.
def node_alerts(node, world):
    """{"kind", "severity" ("warning"/"critical"), "message"} for every
    problem currently active at this settlement/village -- "warning"
    while still inside the grace period (no population loss yet, but
    heading there), "critical" once population is actually being lost.
    Empty list if the node has nothing wrong right now."""
    alerts = []
    twf = getattr(node, "turns_without_food", 0)
    if twf > STARVATION_GRACE_TURNS:
        alerts.append({"kind": "starving", "severity": "critical",
                       "message": f"{node.name} is starving — population is declining"})
    elif twf > 0:
        alerts.append({"kind": "food_shortage", "severity": "warning",
                       "message": f"{node.name} has gone without food for {twf} turn"
                                  f"{'s' if twf != 1 else ''}"})

    twfw = getattr(node, "turns_without_firewood", 0)
    if twfw > FREEZE_GRACE_TURNS:
        alerts.append({"kind": "freezing", "severity": "critical",
                       "message": f"{node.name} is freezing — population is declining"})
    elif twfw > 0:
        alerts.append({"kind": "firewood_shortage", "severity": "warning",
                       "message": f"{node.name} has gone without firewood for {twfw} turn"
                                  f"{'s' if twfw != 1 else ''}"})
    # Distinct from the two alerts above -- explains WHY, when the reason
    # is structural rather than a passing supply hiccup: this node's own
    # region has no Forest access at all, so nothing it does locally (or
    # via Regional Markets, if this is its faction's only region) can ever
    # close the gap -- only a foreign trade route or claiming/conquering
    # forested land actually fixes it (see NO_FOREST_SUBSISTENCE_FRACTION,
    # which only ever softens this, never solves it).
    if twfw > 0 and not _region_has_forest(world, node):
        alerts.append({"kind": "no_firewood_source", "severity": "warning",
                       "message": f"{node.name} has no local source of Firewood — "
                                  "propose a trade route or expand toward forested "
                                  "land"})

    # Weather (see app.world.weather / advance_weather). Region-level, not
    # node-level, but surfaced the same way "no_firewood_source" above
    # already is -- every node in an affected region shows it, which is
    # correct: a drought doesn't pick and choose which village in a region
    # it touches. "warning" regardless of Mild/Severe -- weather is a
    # stressor, not itself a population-loss event (that's what
    # starving/freezing above are for; a bad enough harvest may cascade
    # into one of those separately, on its own alert). Fog is excluded: it
    # has no crop effect yet (a later phase's vision/logistics wiring), and
    # an alert for a weather kind that currently does nothing would mislead
    # rather than inform.
    event = (getattr(world, "region_weather", None) or {}).get(node.region_id)
    if event is not None and event.kind in CROP_WEATHER_KINDS:
        alerts.append({
            "kind": "weather", "severity": "warning",
            "message": f"{node.name}'s region is under {event.label.lower()} — "
                       f"crop yields are down while it lasts ({event.turns_left} "
                       f"turn{'s' if event.turns_left != 1 else ''} left)"})

    # Herds. Losing animals to a Winter you couldn't feed is one of the most
    # consequential things that can happen to a village -- it costs the meat,
    # the milk, the wool and (via faction_horses) the realm's cavalry -- and
    # it was the only such event in the game with no notification at all.
    #
    # Two alerts, because there are two different moments. The Autumn one is
    # the actionable one: hay is already cut and Winter hasn't arrived, so the
    # player can still ship fodder in, set the herd to Cull and bank the meat
    # deliberately, or build a Barn. By the time the herd has actually been
    # culled, all that's left to do is prevent it happening again.
    herds = getattr(node, "herds", None)
    if herds and any(herds.values()):
        need = village_winter_fodder_need(node)
        have = (getattr(node, "resources", None) or {}).get("Fodder", 0)
        if getattr(node, "herd_fed", None) is False:
            alerts.append({
                "kind": "herd_culled", "severity": "critical",
                "message": f"{node.name} could not feed its herd through Winter — "
                           f"animals were culled or lost. Build a Barn, or lay in "
                           f"more Fodder before next Winter"})
        elif need and have < need and world.season in ("Autumn", "Winter"):
            alerts.append({
                "kind": "herd_underfed", "severity": "warning",
                "message": f"{node.name} has {have:,} Fodder for a herd needing "
                           f"{need:,} this Winter — ship hay in, or cull now and "
                           f"keep the meat"})

    # One alert per typed pool, naming the building that fixes it -- "storage
    # is full" was unactionable when it could mean either the grain or the
    # timber, which need entirely different answers.
    if getattr(node, "resources", None):
        for pool in STORAGE_POOLS:
            capacity = node_pool_capacity(node, pool)
            if not capacity:
                continue
            stock = node_pool_stock(node, pool)
            building = STORAGE_BUILDING_BY_POOL[pool].capitalize()
            if stock > capacity:
                alerts.append({
                    "kind": "storage_overflow", "severity": "warning", "pool": pool,
                    "message": f"{node.name}'s {building.lower()} is full — "
                               f"{pool} production has stopped and goods are "
                               f"spoiling; build or upgrade its {building}"})
            elif stock > capacity * STORAGE_THROTTLE_START:
                # The point of throttling is that the player can see it coming
                # and act while there's still something to save -- which needs
                # saying BEFORE the node is over the line, not only after.
                alerts.append({
                    "kind": "storage_nearly_full", "severity": "warning", "pool": pool,
                    "message": f"{node.name}'s {building.lower()} is "
                               f"{round(100 * stock / capacity)}% full — {pool} "
                               f"production is slowing"})
    return alerts


def faction_alerts(world, faction_idx):
    """node_alerts(), aggregated across every settlement and village
    `faction_idx` owns -- what the Alerts panel/map badges actually
    display. Each entry also carries the node itself, so the UI can jump
    straight to it on click without a second lookup."""
    nation = world.factions[faction_idx]
    out = []
    for sid in nation.meta.get("settlements", []):
        node = world.settlements[sid]
        for alert in node_alerts(node, world):
            alert["node"] = node
            out.append(alert)
    for v in world.villages:
        if v.faction_idx == faction_idx:
            for alert in node_alerts(v, world):
                alert["node"] = v
                out.append(alert)
    return out


def advance_settlement_consumption(world):
    """Called every turn: every City/Town/Castle's *and* Village's
    population eats (Food, drawn from any edible Food Product -- see
    _consume_from_pool), needs Firewood in Winter, and wears out Clothes
    slowly (see settlement_needs) -- all drawn from that node's *own*
    storage (Phase 9/10), not a shared national pool. A node can starve
    even while the rest of its faction is well-stocked if nothing's
    actually reached its own granary. Villages are no longer exempt as of
    Phase 10 (see the Village class) -- real storage means a real need to
    keep it fed. Returns {faction_idx: gold-value of what was needed this
    turn} (see settlement_needs_value) -- the direct replacement for the
    old flat-upkeep-based figure, fed into _update_prosperity the same way
    that used to be."""
    consumption_value = defaultdict(float)
    for fac_idx, nation in enumerate(world.factions):
        for sid in nation.meta.get("settlements", []):
            consumption_value[fac_idx] += _consume_node_needs(world.settlements[sid], world.season, world)
    for village in world.villages:
        if village.faction_idx < 0:
            continue
        consumption_value[village.faction_idx] += _consume_node_needs(village, world.season, world)
    return consumption_value


# --- Phase 9: storage -------------------------------------------------------
# "Each settlement owns storage": a real architectural first, not a
# smaller settlement-scales-a-shared-cap compromise. Genuine per-
# settlement stockpiles (Settlement.resources) exist now, fed directly by
# production instead of a national pool -- a settlement can be starving
# while the rest of its faction is fine if nothing's actually reached its
# own granary.
#
# This originally only covered the "household economy": Crops, Food
# Products (including Wool), and the Cloth/Clothes/Leather chain, plus
# Firewood -- exactly what Phase 6/7 produced live and Phase 8 consumed,
# at the time. Mining/Forestry raw materials and the Manufactured Goods
# made from them (Tools/Weapons/Shields/Planks/Bricks/Glass) stayed on the
# shared nation.stats["resources"] pool through Phase 11, because their
# own raw inputs still only existed there (Mining/Forestry were never
# migrated to live production, the STALE gap flagged since Phase 1) -- so
# moving just their *outputs* to per-settlement storage without their
# inputs would have just relocated the gap, not closed it. Phase 12
# finally closes it (see compute_industry_yield): every Mining/Forestry
# raw resource and everything crafted from them now lives here too, same
# genuine per-settlement storage as everything else in this set. Livestock
# itself (Cattle, Sheep, ...) was never a stockpiled quantity either way --
# those are region-level populations (Phase 7), not something a
# settlement stores.
#
# "Resources occupy space": a genuine shared budget, not an independent
# cap per resource -- a full stockpile of Bread really does mean less
# room for Wheat. Every resource costs a flat 1 unit of space regardless
# of type; your own examples gave spoilage a rich per-resource gradient
# but never suggested some goods are bulkier than others, so a uniform
# cost avoids inventing an unrequested second axis of made-up numbers.
#
# Spoilage is finally wired to the real per-resource registry property
# (RESOURCES[resource]["spoil_rate"], defined all the way back when
# resources were first registered) instead of a flat old-system dict --
# and it already matches every example given here exactly: Bread 0.35
# (fast), Potatoes/Carrots/Onions 0.05-0.07 (moderate), Wheat/Barley/
# Oats/Rye 0.03 (slow), Iron/Logs/Hardwood/Softwood 0.0 (never).
#
# "Overflow spoils faster": a grace period, not an instant cutoff.
# Production is never rejected at the door; once total stock exceeds
# capacity, the *overage* decays at a steep accelerated rate each turn
# (see OVERFLOW_SPOILAGE_MULTIPLIER/OVERFLOW_MIN_RATE) until it's back
# under the limit, tapering off as the overflow shrinks. Even normally
# non-perishable goods (Cloth, Leather, Firewood, Honey -- spoil_rate 0)
# lose a little while overflowing specifically: there's genuinely no
# room, whether or not the good itself rots.
#
# "Reasons to build granaries and warehouses": both are real, buildable
# projects now (construction.py's GranaryProject/WarehouseProject, mirrored
# closely off the existing ShipyardProject template), each adding a flat
# capacity bonus at whichever settlement builds one -- Granary sized
# generously (it's the one that matters most, given the household economy
# above is exactly what's storage-constrained); Warehouse is there for
# symmetry with the request's own naming, applying to the same shared
# space budget rather than a second, separate one for Manufactured Goods
# (which -- see above -- mostly don't even reach settlement storage yet).
_SETTLEMENT_STORAGE_RESOURCES = ({name for name, spec in RESOURCES.items()
                                 if spec["category"] in
                                 ("Crops", "Food Products", "Forestry", "Mining",
                                  "Fishing", "Luxury Goods")}
                                 | {"Wool", "Cloth", "Clothes", "Leather",
                                    "Planks", "Bricks", "Glass",
                                    "Tools", "Weapons", "Shields", "Paper", "Gold"})

# --- Phase 3 of the storage rework: typed pools ------------------------------
# Storage used to be one shared budget per node, which meant the goods with no
# consumption sink crowded out the ones people actually eat: measured on a
# turn-561 world, Mining/Forestry durables were 88-90% of every unit in
# storage and food was 6%. No capacity number can fix that, because the
# competition is structural -- a bigger shared barn just holds more timber.
#
# So space is now typed. Each node keeps three independent pools, and a good
# only ever competes with others of its own kind (see storage_class):
#
#   household  Crops, Food Products, Fishing, Firewood  -- Granary
#   durable    Mining, Forestry, Manufactured           -- Warehouse
#   other      Luxury Goods, Gold                       -- Vault
#
# Firewood sits with the household stores rather than with the timber it is
# cut from, and that placement was forced by measurement, not tidiness: it is
# survival-critical (it's what stops a settlement freezing), and leaving it in
# the same pool as structural Logs/Softwood meant the sink-less bulk goods
# crowded it out exactly the way they used to crowd out food. Firewood held
# across the map fell 77% and population dropped with it, while starvation
# stayed flat -- people were freezing, not going hungry. The rule this encodes
# is that a survival good must never share a pool with a bulk good nothing
# consumes. This also matches how the Phase 9 note above already describes
# the "household economy", which listed Firewood alongside the food.
#
# Everything downstream is per-pool now: the overflow decay, the Phase 1
# production throttle, and the storage alerts. A timber glut fills and
# throttles the warehouse without touching the granary, which is both the
# sane reading and what stops it starving the map.
#
# Villages are deliberately food-weighted -- they are farms, and the harvest
# is what they exist to bank -- while a city is the most balanced. Totals are
# in the same ballpark as the single pool each replaces, so this is a
# reallocation of space rather than a stealth buff.
STORAGE_POOLS = ("household", "durable", "other", "feed")

# Capacities are in SPACE, not item count, as of Phase 2 -- a unit of Logs
# eats 3.0 of these and a unit of Gems 0.1 (see _CATEGORY_BULK).
#
# Sized off the measured average bulk of what each pool actually holds
# (household 1.11, durable 2.14, other 0.10). Household is scaled by roughly
# its full average, since ~1.11 means the old unit-count numbers were already
# nearly space numbers. Durable is scaled by only ~1.7 against an average of
# 2.14 -- deliberately NOT fully compensated, because compensating a bulky
# good's capacity by exactly its bulk cancels out the entire point of having
# bulk. Raw timber and quarried stone are meant to be genuinely expensive to
# keep; that pressure is what makes refining them (or building with them)
# more attractive than hoarding them. The vault is left alone: "other" is
# almost entirely Gold at bulk 0.02, so its space number was never really an
# item count to begin with.
STORAGE_POOL_BASE = {
    "city":    {"household": 2100, "durable": 2000, "other": 400, "feed": 200},
    "castle":  {"household": 1300, "durable": 1350, "other": 300, "feed": 200},
    "town":    {"household":  840, "durable":  750, "other": 150, "feed": 200},
    "village": {"household": 1450, "durable": 1000, "other": 150, "feed": 700},
}
_DEFAULT_POOL_BASE = STORAGE_POOL_BASE["town"]

# Legacy aliases -- old saves and any caller still thinking in one number.
SETTLEMENT_STORAGE_BASE = {kind: sum(pools.values())
                           for kind, pools in STORAGE_POOL_BASE.items()
                           if kind != "village"}
_DEFAULT_SETTLEMENT_STORAGE_BASE = sum(_DEFAULT_POOL_BASE.values())
VILLAGE_STORAGE_BASE = sum(STORAGE_POOL_BASE["village"].values())
# A village's storage has to be big enough to actually bank a harvest: a Crop
# only produces during its own ~TURNS_PER_SEASON-turn Harvest window, all at
# once, then nothing again for the rest of the year. Under the old single
# pool that room was shared with -- and in practice swallowed by -- the
# durable Mining/Forestry pile, so a real harvest still ran over budget for
# the whole season and was destroyed before Local Logistics could move it
# out. The food pool above is dedicated, so it is far more usable harvest
# room than the larger shared number it replaces, and a village can now
# extend it further with a Granary of its own (Phase 4).

# --- Phase 4 of the storage rework: tiered storage buildings ------------------
# Each pool has a building that extends it, and each building has tiers you
# upgrade through rather than a single flat one-shot bonus. Bonuses are
# cumulative totals *at* that tier, not increments.
#
# Villages can build a Granary now too. They were the worst offenders in the
# measurements (over capacity 78% of the time) and had no way whatsoever to do
# anything about it -- a flat cap, no building, forever. Their tiers are
# smaller and cheaper than a settlement's, but they exist.
STORAGE_BUILDING_BY_POOL = {"household": "granary", "durable": "warehouse",
                            "other": "vault", "feed": "barn"}
STORAGE_POOL_BY_BUILDING = {v: k for k, v in STORAGE_BUILDING_BY_POOL.items()}

# Also space, and scaled on the same basis as STORAGE_POOL_BASE above.
STORAGE_TIER_BONUS = {
    "granary":   [0, 1200, 2650, 4800],
    "warehouse": [0, 1200, 2700, 4900],
    "vault":     [0, 400, 1000],
}
VILLAGE_STORAGE_TIER_BONUS = {
    "granary":   [0, 650, 1450],
    "warehouse": [0, 600, 1350],
    "vault":     [0, 200],
    # The Barn is both the hay store and the shelter: it holds the feed pool
    # AND cuts Winter fodder need and natural deaths (HERD_BUILDING_EFFECTS).
    "barn":      [0, 700],
}


def storage_max_tier(node, building):
    """Highest tier of `building` this node kind can reach. Covers the
    Preserving House (Phase 5) as well as the three pool buildings -- it uses
    the same project/tier machinery but grants conversion throughput rather
    than capacity, so its tiers come from a different table."""
    village = not hasattr(node, "kind")
    if building == PRESERVING_HOUSE:
        table = VILLAGE_PRESERVING_CAP_MULT if village else PRESERVING_CAP_MULT
        return len(table) - 1
    if building in HERD_BUILDINGS:
        # Herd buildings are village-only: animals live where the fields are,
        # and a walled city is not a pasture.
        return VILLAGE_HERD_MAX_TIER if village else 0
    if building == GOLD_MINE:
        # Village-only, and the seam gate lives in buildings.py rather than
        # here: this function takes no world, and "is there ore under this
        # village" needs the terrain grid. This is the node-KIND gate only.
        return (len(GOLD_MINE_YIELD_MULT) - 1) if village else 0
    if building == MINT:
        # Settlement-only: a village has no forge, which is the same reason it
        # runs no conversion recipe of any kind (see
        # advance_settlement_production_chains).
        return 0 if village else len(MINT_RATE_MULT) - 1
    if building == CARTOGRAPHER:
        # Settlement-only. A guild of surveyors, instrument-makers and copyists
        # is a town institution; a farming hamlet is not where it lives.
        return 0 if village else len(CARTOGRAPHER_LOCAL_RADIUS) - 1
    table = VILLAGE_STORAGE_TIER_BONUS if village else STORAGE_TIER_BONUS
    return len(table.get(building, [0])) - 1


def storage_tier(node, building):
    """Current tier of `building` at `node`, 0 for none.

    Reads through getattr with a legacy fallback so saves written before
    tiers existed -- which recorded a plain has_granary/has_warehouse
    boolean -- load as tier 1 rather than losing the building."""
    tier = getattr(node, f"{building}_tier", None)
    if tier is not None:
        return tier
    return 1 if getattr(node, f"has_{building}", False) else 0


def set_storage_tier(node, building, tier):
    setattr(node, f"{building}_tier", tier)
    # Keep the legacy flags true so anything still reading them (old UI, old
    # saves round-tripping) stays consistent.
    setattr(node, f"has_{building}", tier > 0)


def node_pool_capacity(node, pool):
    """This node's capacity for one storage pool: its kind's base plus
    whatever tier of that pool's building it has built."""
    kind = getattr(node, "kind", "village")
    base = STORAGE_POOL_BASE.get(kind, _DEFAULT_POOL_BASE).get(pool, 0)
    building = STORAGE_BUILDING_BY_POOL.get(pool)
    if building:
        table = (VILLAGE_STORAGE_TIER_BONUS if kind == "village"
                 else STORAGE_TIER_BONUS).get(building, [0])
        tier = min(storage_tier(node, building), len(table) - 1)
        base += table[tier]
    return base


def node_pool_stock(node, pool):
    """Space currently occupied in one of `node`'s pools -- units weighted by
    bulk (Phase 2), not a raw unit count. This is the number every capacity
    check compares against, so "1,200 / 1,600" is space, not items."""
    res = getattr(node, "resources", None)
    if not res:
        return 0
    return round(sum(v * resource_bulk(r) for r, v in res.items()
                     if storage_class(r) == pool))


def node_space_used(node):
    """Total space occupied across every pool -- the bulk-weighted
    counterpart of sum(node.resources.values()), which counts items."""
    res = getattr(node, "resources", None)
    if not res:
        return 0
    return round(sum(v * resource_bulk(r) for r, v in res.items()))


# Legacy single-number bonuses, kept so old callers/saves still resolve.
GRANARY_STORAGE_BONUS = STORAGE_TIER_BONUS["granary"][1]
WAREHOUSE_STORAGE_BONUS = STORAGE_TIER_BONUS["warehouse"][1]

OVERFLOW_SPOILAGE_MULTIPLIER = 5.0   # extra decay speed applied on top of a
                                     # resource's own spoil_rate while over cap
MAX_OVERFLOW_LOSS_FRACTION = 0.75   # even the worst case (badly overflowing,
                                     # fast-spoiling) keeps a sliver of grace
OVERFLOW_MIN_RATE = 0.10            # even a spoil_rate-0 good leaks away some
                                     # while overflowing -- no shelter, no floor space

# --- Phase 1 of the storage rework: production responds to storage ----------
# Until now, capacity was consulted by trade, by the overflow decay, by the
# storage alert and by the AI's build choice -- but by nothing in production.
# A node harvested at full rate into a store that was already over capacity,
# and the overage decay deleted the difference the same turn.
#
# That made storage a no-op. The old overflow rule loses rate * (total -
# capacity) per turn, which is a proportional controller: it settles at
# capacity + inflow/rate and stays there. At that equilibrium the loss equals
# the inflow *regardless of what the capacity is*, so building a granary moved
# the parking level without ever changing how much was destroyed. Measured on
# a turn-561 world, villages sat at 1.12x capacity and were over the line 78%
# of the time, and overflow destroyed 4x more goods than actual spoilage.
#
# The fix is a feedback loop rather than a bigger number: a node approaching
# full throttles its own primary production, tapering to a full stop at
# capacity. Nothing is silently destroyed any more -- it is simply never
# produced, which is a thing the player can see and act on. Capacity now buys
# real output instead of a higher parking level, which is what finally makes a
# Granary worth building.
#
# Applies to *primary* production only -- the harvest and the catch
# (_route_farm_production, _produce_fishing). Deliberately NOT to the
# conversion recipes (advance_settlement_production_chains): those consume at
# least as many input units as they produce, so they relieve storage pressure
# rather than adding to it, and throttling them would make a full node worse
# by stalling the one process that was draining it.
STORAGE_THROTTLE_START = 0.85   # fraction full at which output starts tapering
STORAGE_THROTTLE_FLOOR = 0.0    # multiplier once at/over capacity

# Throttling on a node's TOTAL fullness was tried first and measurably starved
# the map: durable Mining/Forestry goods are 88-90% of everything in storage
# (they have spoil_rate 0 and almost no consumption sink), so a barn packed
# with Softwood shut down the grain harvest and nodes with people starving in
# them went from 207 to 332 over 60 turns.
#
# The rule that actually matches the intent -- stop production that is going to
# be destroyed anyway -- is per storage CLASS: a node throttles the goods it is
# already drowning in, not everything it does. Wheat keeps coming in while the
# timber pile is what's overflowing, which is both the sane economic behaviour
# and what stops the regression. As of Phase 3 those classes are backed by real
# typed pools (see STORAGE_POOL_BASE), so class occupancy is now measured
# against that pool's own capacity rather than the whole node's.
_STORAGE_CLASS_BY_CATEGORY = {
    "Crops": "household", "Food Products": "household", "Fishing": "household",
    "Mining": "durable", "Forestry": "durable", "Manufactured Goods": "durable",
}
_DURABLE_EXTRA = {"Planks", "Bricks", "Glass", "Tools", "Weapons", "Shields",
                  "Paper", "Cloth", "Clothes", "Leather", "Wool"}
# Explicit overrides that beat the category mapping. Gold is registered under
# Mining with the ore it's dug from, but as minted currency it belongs in the
# vault: leaving it in the warehouse pool would let a timber glut block the
# treasury, and the overflow rule already refuses to decay it.
_STORAGE_CLASS_OVERRIDE = {
    # Hay gets its own pool, held in the Barn. It is bulky (2.2) animal
    # feed, and leaving it in the granary put it in direct competition with
    # human food for the same shelf -- the third time that exact pattern bit
    # (Firewood, then Cotton, then this): nodes with people starving in them
    # went from 140 to 225. Same rule as before, stated once more: a
    # survival good never shares a pool with a bulk good.
    "Fodder": "feed",
    "Gold": "other",
    "Firewood": "household",
    # Cotton is registered as a Crop because it's grown, but it is a
    # non-edible industrial fibre (the registry's own `edible: False`
    # exception among Crops) and the raw input to the Cloth chain -- exactly
    # what Wool is, and Wool was already classed durable. Leaving it in the
    # granary put a bulk-1.8 industrial good in direct competition with food
    # for the same space: it alone occupied ~279k of household space and
    # pushed nodes with people starving in them from 140 up to 166.
    "Cotton": "durable",
}


# Memo for storage_class. It is a pure function of a resource NAME over tables
# that are all finalised at import, so this can never go stale -- and it is one
# of the hottest calls in the game: a single end turn on a 300-region world made
# 930,000 of them, because every node_pool_stock sums over every resource a node
# holds and asks the class of each one.
_STORAGE_CLASS_CACHE = {}


def storage_class(resource):
    """Which storage pool a resource occupies and competes within -- "food"
    (Crops/Food Products/Fishing), "durable" (Mining/Forestry/Manufactured),
    or "other" (Luxury Goods, Gold)."""
    try:
        return _STORAGE_CLASS_CACHE[resource]
    except KeyError:
        pass
    override = _STORAGE_CLASS_OVERRIDE.get(resource)
    if override:
        value = override
    elif resource in _DURABLE_EXTRA:
        value = "durable"
    else:
        category = RESOURCES.get(resource, {}).get("category")
        value = _STORAGE_CLASS_BY_CATEGORY.get(category, "other")
    _STORAGE_CLASS_CACHE[resource] = value
    return value


def storage_throttle(node, resource=None):
    """0..1 multiplier on this node's primary production of `resource`, from
    how full its storage already is *of that resource's class*: full rate up
    to STORAGE_THROTTLE_START, then a linear taper to STORAGE_THROTTLE_FLOOR
    at that pool's capacity. Passing resource=None measures whole-node
    fullness instead (used for reporting). A node with no capacity figure or
    no storage dict yet is unthrottled."""
    res = getattr(node, "resources", None)
    if not res:
        return 1.0
    if resource is None:
        capacity = _node_storage_capacity(node)
        stock = node_space_used(node)
    else:
        pool = storage_class(resource)
        capacity = node_pool_capacity(node, pool)
        stock = node_pool_stock(node, pool)
    if not capacity:
        return 1.0
    fill = stock / capacity
    if fill <= STORAGE_THROTTLE_START:
        return 1.0
    if fill >= 1.0:
        return STORAGE_THROTTLE_FLOOR
    span = 1.0 - STORAGE_THROTTLE_START
    return STORAGE_THROTTLE_FLOOR + (1.0 - STORAGE_THROTTLE_FLOOR) * (1.0 - fill) / span


def settlement_storage_capacity(settlement):
    """This settlement's TOTAL storage across every pool.

    Space is typed as of Phase 3 (see STORAGE_POOL_BASE) -- a good only ever
    competes with others of its own class -- so this total is a reporting and
    coarse-gating figure, not the number anything is actually capped against.
    Use node_pool_capacity for that. Kept because trade sizing and the
    resource bar legitimately want one headline number."""
    return sum(node_pool_capacity(settlement, p) for p in STORAGE_POOLS)


def _node_storage_capacity(node):
    """settlement_storage_capacity for whichever kind of storage-owning node
    this is -- Village or Settlement. Both have typed pools now; the only
    difference is their base sizes and how far their buildings tier."""
    return sum(node_pool_capacity(node, p) for p in STORAGE_POOLS)


def _route_farm_production(world, region, resource_amounts, throttle=True):
    """Send `resource_amounts` (a {resource: amount} dict, already
    filtered to _SETTLEMENT_STORAGE_RESOURCES by the caller) straight to
    the region's own Villages -- the actual farm unit (see the Village
    class) -- instead of a national pool or straight to a settlement.
    Since Phase 10, this deliberately does *not* hand production to
    Settlements directly any more: a village has no mill/loom of its own,
    so its harvest has to be physically moved there by
    run_local_logistics, same as the request's own Village-A/Town-B
    example. Split evenly across every village in the region; a region
    with no village of its own (freshly claimed wildland whose only
    village hasn't been planted yet, or a starting foothold that's all
    settlement) falls back to its own settlement(s), then to the
    faction's first settlement, and production is simply lost only if the
    faction has no settlement or village at all yet (a narrow, early-
    game-only edge case).

    Each target's share is scaled by its own storage_throttle (see that
    function): a village whose granary is already full simply doesn't bring
    the harvest in, rather than delivering it into a store that deletes it
    again the same turn. Throttling is per-target, not per-region, so one
    full village doesn't hold back its neighbours.

    Returns the {resource: amount} actually delivered across all targets,
    which is what the caller should value for prosperity -- valuing the
    computed yield instead would credit a faction for a harvest that was
    never taken in."""
    delivered = {}
    if not resource_amounts:
        return delivered
    vids = list(getattr(region, "villages", []))
    targets = [("village", vid) for vid in vids]
    if not targets:
        sids = list(getattr(region, "meta_settlements", []))
        targets = [("settlement", sid) for sid in sids]
    if not targets:
        nation = world.factions[region.faction_idx]
        fallback = nation.meta.get("settlements", [])
        if not fallback:
            return delivered
        targets = [("settlement", fallback[0])]
    n = len(targets)
    for kind, node_id in targets:
        node = world.villages[node_id] if kind == "village" else world.settlements[node_id]
        if not hasattr(node, "resources"):
            node.resources = {}
        # Per-resource: a village drowning in Softwood still brings its grain
        # in. See storage_throttle for why this is per storage class and not
        # per node total.
        for resource, amount in resource_amounts.items():
            factor = storage_throttle(node, resource) if throttle else 1.0
            share = round(amount / n * factor)
            if share:
                node.resources[resource] = node.resources.get(resource, 0) + share
                delivered[resource] = delivered.get(resource, 0) + share
    return delivered


def village_local_sample(world, village, region, radius=None):
    """(biome_counts, climate, fertility_frac) sampled over a radius-R patch
    of the map around `village`, filtered to this village's own region --
    the real production catchment a village's own local yield is computed
    from (see compute_village_yield). Same sampling shape worldgen.py's
    _place_villages_for_region already used for the old decorative
    farm_output stat (a small patch averaged for "land occupied"), just
    biome-classified instead of fertility-only, and over the radius tied to
    placement spacing (worldgen._VILLAGE_CATCHMENT_RADIUS) so "how much
    land is really mine" and "how close is too close to my neighbor" are
    the same underlying idea rather than two numbers that could drift
    apart."""
    r = radius or _VILLAGE_CATCHMENT_RADIUS
    x, y = village.pos
    biome_counts = defaultdict(int)
    climate_counts = defaultdict(int)
    fert_sum, n = 0.0, 0
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            nx, ny = x + dx, y + dy
            if not (0 <= nx < world.w and 0 <= ny < world.h):
                continue
            if world.region_grid[ny][nx] != region.id:
                continue
            biome = world.biome_grid[ny][nx]
            if biome:
                biome_counts[biome] += 1
            climate = world.climate_grid[ny][nx]
            if climate:
                climate_counts[climate] += 1
            fert_sum += world.fertility[ny][nx]
            n += 1
    climate = (max(climate_counts, key=climate_counts.get) if climate_counts
              else region.dominant_climate)
    fertility_frac = (fert_sum / n) if n else region.stats.get("fertility", 50) / 100.0
    return dict(biome_counts), climate, fertility_frac


def compute_village_yield(world, village, season):
    """This village's own real production for `season` -- food AND
    industry both, computed from its own local land (village_local_sample)
    instead of a region-wide pool split evenly across however many
    villages exist. Where a village actually sits now determines what it
    CAN grow or mine.

    What it actually brings in is that terrain potential limited by its own
    finite workforce (Phase 14 -- see village_labor_state): the land's offer
    and the hands available are two separate ceilings and the smaller one
    wins. Fish is deliberately excluded from the result even though it
    competes for the same hands -- it's landed at the node directly by
    _produce_fishing, which reads the same cached labor factors, and
    returning it here too would double-count the catch.

    Amounts are FLOATS, deliberately. Rounding here threw away every yield
    under half a unit, which is every rare seam on the map -- see
    _deliver_village_yield, which now carries the fraction instead."""
    factors, raw = village_labor_state(world, village, season)
    result = {}
    for resource, amount in raw.items():
        factor = factors.get(production_sector(resource))
        share = amount * factor if factor is not None else amount
        if share > 0:
            result[resource] = share
    return result


def _deliver_village_yield(village, resource_amounts, throttle=True):
    """This village's own locally-computed yield straight into its own
    storage, throttled per-resource exactly like _route_farm_production's
    per-target throttle above -- just one target now, since the yield is
    already local instead of needing to be split. Returns {resource:
    amount} actually delivered, for prosperity valuation (crediting a
    harvest that was never taken in would be wrong, same reasoning as
    _route_farm_production's own docstring).

    Fractions CARRY from turn to turn rather than being rounded away, and that
    is a real fix, not tidiness. Rounding each resource to an int per village
    per turn silently deleted every yield under half a unit -- which is every
    rare resource, everywhere. Gold Ore, Gems and Tin all take a 0.0488 share
    of a mountain's land against Iron/Coal/Stone's 0.2439, so a village whose
    catchment gave Iron a comfortable 0.98 a turn gave Gold Ore 0.195, and
    0.195 rounds to zero forever. Measured: a fresh 10-faction world at turn
    120 had produced ZERO Gold Ore, held zero, and had no village anywhere
    sitting on a workable seam -- so the Mint had nothing to strike and the
    only gold in the game was the starting reserve, draining to nothing.

    With a carry, a seam yielding 0.195 a turn delivers one unit every fifth
    turn or so, which is what a rare seam should look like. The carry lives on
    the village (plain float dict, pickles fine) so it is deterministic and
    survives save/load."""
    delivered = {}
    if not resource_amounts:
        return delivered
    if not hasattr(village, "resources"):
        village.resources = {}
    carry = getattr(village, "_yield_carry", None)
    if carry is None:
        carry = village._yield_carry = {}
    for resource, amount in resource_amounts.items():
        factor = storage_throttle(village, resource) if throttle else 1.0
        exact = amount * factor + carry.get(resource, 0.0)
        share = int(exact)
        carry[resource] = exact - share
        if share:
            village.resources[resource] = village.resources.get(resource, 0) + share
            delivered[resource] = delivered.get(resource, 0) + share
    return delivered


def recompute_region_resources(world, region, season, throttle=True):
    """Produce and deliver every one of `region`'s villages' own local
    yield for `season` (see compute_village_yield), applying
    BASELINE_INDUSTRY_FLOOR once at the region level afterward (a
    per-village floor would multiply it by however many villages a region
    has -- see compute_industry_yield's note on it, unchanged from before).

    Sets region.resources to the summed RAW yield -- matching what
    compute_region_yield used to put there ("this turn's yield" in the
    region panel, territory's transfer-on-conquest), not what was actually
    captured into storage. Returns (raw_total, delivered_total):
    delivered_total is what prosperity should be valued against, since a
    village that idled its harvest for want of storage shouldn't be
    credited with the prosperity of bringing it in (region.resources itself
    already carried this exact raw-vs-delivered distinction before this
    function existed -- see advance_turn's own use of `delivered` alongside
    region.resources).

    Shared by advance_turn, seed_initial_stockpiles, and
    expansion.settle_newly_claimed_region so all three compute and deliver
    per-village production the same way instead of three near-duplicate
    loops."""
    raw_total = {}
    delivered_total = {}
    villages = [world.villages[vid] for vid in getattr(region, "villages", [])]
    for village in villages:
        yield_ = compute_village_yield(world, village, season)
        for resource, amount in yield_.items():
            raw_total[resource] = raw_total.get(resource, 0) + amount
        delivered = _deliver_village_yield(village, yield_, throttle=throttle)
        for resource, amount in delivered.items():
            delivered_total[resource] = delivered_total.get(resource, 0) + amount

    if villages:
        for resource, floor in BASELINE_INDUSTRY_FLOOR.items():
            have = raw_total.get(resource, 0)
            if have < floor:
                topup = floor - have
                raw_total[resource] = floor
                target = min(villages, key=lambda v: getattr(v, "resources", {}).get(resource, 0))
                if not hasattr(target, "resources"):
                    target.resources = {}
                factor = storage_throttle(target, resource) if throttle else 1.0
                share = round(topup * factor)
                if share:
                    target.resources[resource] = target.resources.get(resource, 0) + share
                    delivered_total[resource] = delivered_total.get(resource, 0) + share

    # region.resources is a display/transfer figure ("this turn's yield" in the
    # region panel, territory's transfer-on-conquest), so it rounds here --
    # the fractional precision only matters on the delivery path above, where
    # _deliver_village_yield carries it forward instead of discarding it.
    region.resources = {r: round(a) for r, a in raw_total.items() if round(a) > 0}
    return raw_total, delivered_total


def advance_settlement_production_chains(world):
    """The settlement-storage half of advance_production_chains (Phase 8):
    recipes whose output belongs to _SETTLEMENT_STORAGE_RESOURCES convert
    locally now, using that settlement's own stock -- Wheat becomes Flour
    becomes Bread right there in that settlement's granary, not through
    the shared national pool. Same 1:1 ratio / CONVERSION_RATE_CAP /
    scarcest-input / first-available-alternative rules as the faction-
    level version."""
    for settlement in world.settlements:
        if not hasattr(settlement, "resources"):
            settlement.resources = {}
        res = settlement.resources
        for output, options in RECIPES.items():
            if output not in _SETTLEMENT_STORAGE_RESOURCES:
                continue
            if RESOURCES[output]["luxury"]:
                if world.turn < LUXURY_CONVERSION_MIN_TURN:
                    continue
                cap = LUXURY_CONVERSION_RATE_CAP
            elif output == "Gold":
                cap = int(CONVERSION_RATE_CAP * mint_rate_multiplier(settlement))
            else:
                cap = CONVERSION_RATE_CAP
            for option in options:
                inputs = option["inputs"]
                available = min(res.get(i, 0) for i in inputs)
                amount = min(available, cap)
                if amount <= 0:
                    continue
                for i in inputs:
                    res[i] -= amount
                # Every other recipe is 1:1. The Mint is the one that can beat
                # that, at its upper tiers, by recovering metal a rough mint
                # leaves in the slag (see MINT_YIELD_PER_ORE).
                struck = (round(amount * mint_yield_per_ore(settlement))
                          if output == "Gold" else amount)
                res[output] = res.get(output, 0) + struck
                break


# --- Phase 5 of the storage rework: preservation ----------------------------
# Every earlier phase made storage a better-behaved *constraint*. This one is
# the first that hands the player a way to fight back, rather than a defect
# being fixed: spoilage stops being an unavoidable tax and becomes a problem
# with a build-order answer.
#
# It targets a measured hole. With overflow largely solved, Fish alone is 39%
# of all remaining spoilage -- 639k units over 60 turns -- because it spoils at
# 0.35 and lands directly at whichever node is near water (_produce_fishing),
# which is usually a Village. Villages have no mill, loom or smokehouse and are
# excluded from every conversion chain in the game, so a fishing village
# catches fish and simply watches them rot. Nothing it could build changed that.
#
# The Preserving House does three things:
#   1. Lets a VILLAGE run preservation recipes at all -- the first conversion
#      of any kind a village has ever been able to do.
#   2. Raises the conversion cap for those recipes well above
#      CONVERSION_RATE_CAP, so a node with one can actually keep up with a
#      catch instead of curing 30 units a turn.
#   3. Burns Salt doing it. Salt has been an inert Mining resource with no
#      real demand; this makes it the reagent a food economy runs on, which
#      is both historically right and the first genuine reason to trade for it.
#
# Deliberately additive: the ordinary settlement chain still does Fish ->
# Smoked Fish and Milk -> Cheese at the base cap with no Salt, exactly as
# before, so a settlement without the building loses nothing.
PRESERVATION_RECIPES = {
    "Smoked Fish": "Fish",     # 0.35 -> 0.05
    "Cheese": "Milk",          # 0.40 -> 0.05
    "Salted Meat": "Meat",     # 0.30 -> 0.03; Preserving House only
}
# Salt burned per unit cured, per recipe. Not one flat rate: smoke-curing fish
# and setting cheese use very little, while salt-meat is mostly salt -- it's in
# the name. A flat rate was tried and made Salt the binding constraint on the
# one conversion that matters most (Fish is 39% of all spoilage), which is the
# wrong bottleneck: it capped the big win at ~10% instead of letting Salt be
# what gates the premium, salt-hungry option.
SALT_PER_PRESERVED = {"Smoked Fish": 0.04, "Cheese": 0.05, "Salted Meat": 0.35}
DEFAULT_SALT_PER_PRESERVED = 0.10
# Conversion-cap multiplier by tier, over CONVERSION_RATE_CAP.
PRESERVING_CAP_MULT = [0.0, 3.0, 6.0]
VILLAGE_PRESERVING_CAP_MULT = [0.0, 2.5]
PRESERVING_HOUSE = "preserving_house"


# --- Coin: the Gold Mine and the Mint ---------------------------------------
# Gold has been a real produced resource since the Currency overhaul -- struck
# from Gold Ore, not drawn from a flat tax -- but measurement showed the chain
# was severed at every link and the treasury simply drained. On the turn-561
# world over 60 turns: the map held 20,439 Gold Ore, minted essentially none of
# it, destroyed 15,221 of it to overflow decay in village warehouses, and lost
# 5,625 net Gold.
#
# Three separate reasons, all of them structural:
#
#   1. Only Settlements run conversion recipes (a village has no forge), and
#      ZERO of 43 settlements held a single unit of Gold Ore. Every mint in the
#      world was idle for want of ore while the ore rotted where it was dug.
#   2. Local logistics could have carried it and effectively never did. It
#      dispatches ONE shipment per node per turn down a fixed priority list,
#      and Gold Ore sits at index 38 of 57 -- over 20 turns the map dispatched
#      1,155 shipments, of which exactly ONE was Gold Ore. Anything low in that
#      order was permanently starved, ore included. See
#      _LOCAL_SHIPMENT_PRIORITY, which now rotates.
#   3. Local logistics is region-locked, and 82 of the 85 ore-bearing regions
#      have no settlement in them at all -- so for almost all of the map's ore,
#      no amount of priority would have helped. See trade.run_sell_to_city,
#      which now sources from Villages too.
#
# With the ore actually arriving, the two buildings below are what the player
# does about it, and they are deliberately a PAIR rather than one building:
#
#   Gold Mine   village-only, and only where the village's own land really
#               holds a seam. It multiplies extraction -- more ore out of the
#               same ground, at the cost of more hands (Phase 14 labor still
#               applies, so a bigger mine competes with the harvest).
#   Mint        settlement-only. Raises how much ore can be struck per turn,
#               and at the top tiers gets more coin out of each unit of ore
#               through better refining.
#
# Tier 0 of the Mint is 1.0, not 0.0: a settlement without one keeps minting at
# exactly the base rate it always did, so nothing regresses on an existing
# save. The same "additive, a node without the building loses nothing" contract
# the Preserving House above already sets.
GOLD_MINE = "gold_mine"
MINT = "mint"

# Ore extraction multiplier by Gold Mine tier. Steep, because the whole point
# is to make a village that happens to sit on a seam genuinely worth
# developing -- geography deciding that this village, specifically, is where
# your coin comes from.
GOLD_MINE_YIELD_MULT = [1.0, 2.5, 4.0]
# Multiplier on CONVERSION_RATE_CAP for the Gold recipe specifically.
MINT_RATE_MULT = [1.0, 3.0, 6.0, 10.0]
# Coin struck per unit of ore. Above 1.0 at the upper tiers: a great mint
# recovers metal a rough one leaves in the slag. This is what stops an upgrade
# being purely "the same thing, faster" -- it makes each unit of a genuinely
# scarce resource worth more.
MINT_YIELD_PER_ORE = [1.0, 1.0, 1.15, 1.3]


def gold_mine_multiplier(node):
    """Ore-extraction multiplier from this node's Gold Mine, 1.0 without one."""
    tier = min(storage_tier(node, GOLD_MINE), len(GOLD_MINE_YIELD_MULT) - 1)
    return GOLD_MINE_YIELD_MULT[tier]


def mint_rate_multiplier(node):
    tier = min(storage_tier(node, MINT), len(MINT_RATE_MULT) - 1)
    return MINT_RATE_MULT[tier]


def mint_yield_per_ore(node):
    tier = min(storage_tier(node, MINT), len(MINT_YIELD_PER_ORE) - 1)
    return MINT_YIELD_PER_ORE[tier]


def has_gold_seam(world, village):
    """Does this village's own catchment actually hold a Gold Ore seam? The
    "if you can" gate on the Gold Mine -- a village with no ore under it can
    never build one, however rich its owner. Read off the same terrain sample
    production itself uses, so the menu can never offer a mine that would
    produce nothing."""
    region = world.regions[village.region_id]
    biome_counts, climate, fertility_frac = village_local_sample(world, village, region)
    return _industry_yield_core(biome_counts, climate, fertility_frac).get("Gold Ore", 0) > 0


# --- The Cartographer's Guild: mapping the world without marching on it -----
# Fog of war only lifts three ways today (see app/world/vision.py): owning the
# ground, walking a Commander over it, or running a road or caravan across it.
# Every one of those is either territorial or military, which quietly makes
# exploration a thing only an expanding or war-faring realm gets to do -- a
# realm that would rather trade has no way at all to find out what is out there
# short of marching an army it does not want.
#
# The mechanic follows how this was actually done, because the honest history
# happens to be a much better game rule than the obvious invention.
#
# Pre-modern cartographers overwhelmingly did NOT go anywhere. They sat in
# Lisbon, Seville, Venice and Amsterdam and COMPILED. Spain's Casa de la
# Contratacion legally required every returning pilot to report to the master
# chart; Dutch VOC cartographers worked entirely from ships' logs they never
# sailed on; a portolan coastline is twenty merchants' bearings triangulated
# into one line. The map grew where your people already went.
#
# So the rule here is: a Guild does not GENERATE knowledge, it MULTIPLIES the
# knowledge your realm is already gathering by moving about. Concretely,
# vision.py's existing reveals -- around a caravan, along a road, around a
# commander -- all widen when you have a Guild, and a caravan additionally
# reports the whole corridor it has travelled rather than just where it is
# standing right now. That is the pilot's-log rule, exactly.
#
# The consequence is the point: a Guild is worth a great deal to a realm with
# ships and caravans out, and worth almost nothing to a hermit. It can never be
# "free vision for buying a building", because it reveals nothing on its own
# beyond the small local survey below.
#
# What it DOES do unaided is survey its own neighbourhood -- the ground within
# a few days' ride, which a guild really would have walked and measured itself.
# That is deliberately small and hard-capped: enough that an expensive building
# does something the turn you finish it, nowhere near enough to be a map.
#
# "After enough development" is priced rather than gated on a turn number: the
# cost is Planks, Glass, Tools and coin -- a sawmill, a glassworks and a forge
# all running at once. A realm that has not built an industry cannot buy one.
#
# Paper accelerates the local survey but is never required. Maps are drawn on
# paper and it is the right consumable, but Paper is made from Cotton at a
# settlement, and a hard requirement would make the building unreachable on any
# world where that chain has not connected -- the exact trap the Preserving
# House hit with Stone (eligible 308 times, affordable zero).
CARTOGRAPHER = "cartographer"
# The local survey only: what the guild can measure itself, from home. A
# Commander's own COMMANDER_VISION_RADIUS is in this same ballpark on purpose --
# this is a neighbourhood, not a discovery.
CARTOGRAPHER_LOCAL_RADIUS = [0, 9, 14, 20]
CARTOGRAPHER_SURVEY_PER_TURN = [0.0, 0.3, 0.45, 0.6]
CARTOGRAPHER_PAPER_PER_TURN = 1
CARTOGRAPHER_PAPER_SPEEDUP = 2.0

# How much further your own moving agents report back, by the best Guild in the
# realm. This is the real mechanic (see above): added to vision.py's
# CARAVAN_VISION_RADIUS, ROUTE_REVEAL_RADIUS and COMMANDER_VISION_RADIUS.
CARTOGRAPHER_TRAFFIC_BONUS = [0, 4, 8, 13]
# With a Guild, a caravan reports the whole route it has travelled so far, not
# just the ground it is standing on -- the ship's log handed in at the end of
# the voyage. Off entirely without one.
CARTOGRAPHER_LOGS_TRAFFIC = True


def cartographer_radius(node):
    """How far this settlement has actually surveyed around itself so far."""
    return getattr(node, "survey_radius", 0.0)


def cartographer_local_radius(node):
    tier = min(storage_tier(node, CARTOGRAPHER), len(CARTOGRAPHER_LOCAL_RADIUS) - 1)
    return CARTOGRAPHER_LOCAL_RADIUS[tier]


def faction_cartographer_tier(world, fac_idx):
    """The best Guild in the realm. A national chart office is one institution,
    not one per town -- a second Guild does not double what your pilots know,
    so the traffic bonus takes the maximum rather than summing."""
    best = 0
    for st in world.settlements:
        if st.faction_idx == fac_idx:
            best = max(best, storage_tier(st, CARTOGRAPHER))
    return min(best, len(CARTOGRAPHER_TRAFFIC_BONUS) - 1)


def cartographer_traffic_bonus(world, fac_idx):
    """Extra cells your own caravans, roads and commanders report back."""
    return CARTOGRAPHER_TRAFFIC_BONUS[faction_cartographer_tier(world, fac_idx)]


def advance_cartographers(world):
    """One turn of the local survey at every Guild, burning Paper where there
    is any to burn.

    Only the progress lives here -- turning a radius into revealed fog is
    vision.recompute's job, same as it already is for Commanders, roads and
    caravans. Runs for every faction, not just the player: fog is a
    player-only concept, but a Guild is a real building an AI can own, and
    having its progress depend on who is looking would be a mess the first time
    a save changed hands."""
    for st in world.settlements:
        tier = min(storage_tier(st, CARTOGRAPHER), len(CARTOGRAPHER_SURVEY_PER_TURN) - 1)
        if tier <= 0:
            continue
        reach = CARTOGRAPHER_LOCAL_RADIUS[tier]
        done = cartographer_radius(st)
        if done >= reach:
            continue
        rate = CARTOGRAPHER_SURVEY_PER_TURN[tier]
        res = st.resources if hasattr(st, "resources") else {}
        if res.get("Paper", 0) >= CARTOGRAPHER_PAPER_PER_TURN:
            res["Paper"] -= CARTOGRAPHER_PAPER_PER_TURN
            rate *= CARTOGRAPHER_PAPER_SPEEDUP
        st.survey_radius = min(reach, done + rate)


def preserving_cap_multiplier(node):
    """Conversion-cap multiplier from this node's Preserving House, 0 if it
    has none."""
    table = (VILLAGE_PRESERVING_CAP_MULT if not hasattr(node, "kind")
             else PRESERVING_CAP_MULT)
    tier = min(storage_tier(node, PRESERVING_HOUSE), len(table) - 1)
    return table[tier]


def _preserve_at_node(node):
    """Run this node's Preserving House for one turn. Cures perishables into
    their durable forms, capped by the building's tier, by how much of the
    perishable is actually on hand, and by Salt -- which is a hard limit, not
    a discount: no salt, no curing."""
    res = getattr(node, "resources", None)
    if not res:
        return
    mult = preserving_cap_multiplier(node)
    if mult <= 0:
        return
    cap = int(CONVERSION_RATE_CAP * mult)
    for output, source in PRESERVATION_RECIPES.items():
        available = res.get(source, 0)
        if available <= 0:
            continue
        amount = min(available, cap)
        per_unit = SALT_PER_PRESERVED.get(output, DEFAULT_SALT_PER_PRESERVED)
        if per_unit > 0:
            salt = res.get("Salt", 0)
            amount = min(amount, int(salt / per_unit))
        if amount <= 0:
            continue
        salt_used = round(amount * per_unit)
        res[source] -= amount
        if salt_used:
            res["Salt"] = max(0, res.get("Salt", 0) - salt_used)
        res[output] = res.get(output, 0) + amount


def advance_preservation(world):
    """Every Preserving House in the world, Settlements and Villages alike.
    Runs before the ordinary conversion chains so cured goods are already
    banked when consumption draws on them."""
    for node in list(world.settlements) + list(world.villages):
        _preserve_at_node(node)


def _apply_settlement_spoilage_and_overflow(node):
    """Spoil this settlement's or village's own storage at each resource's
    real registry spoil_rate, then -- if total stock is over capacity --
    decay the overage further on top of that (see the Phase 9 section
    docstring for the full reasoning), tapering off as the overflow
    shrinks back toward the limit instead of an instant cutoff."""
    res = getattr(node, "resources", None)
    if not res:
        return

    for resource in list(res.keys()):
        rate = RESOURCES.get(resource, {}).get("spoil_rate", 0.0)
        if rate:
            res[resource] = int(res[resource] * (1 - rate))

    # Overflow is judged per typed pool as of Phase 3 (see STORAGE_POOL_BASE):
    # a warehouse packed past its limit rots its own timber, and leaves the
    # grain in the granary next door alone. Under the old shared budget a
    # durable glut decayed the food too, which is both wrong and what made
    # the pile impossible to reason about.
    by_pool = {}
    for resource, amount in res.items():
        if amount > 0:
            by_pool.setdefault(storage_class(resource), []).append(resource)

    for pool, names in by_pool.items():
        capacity = node_pool_capacity(node, pool)
        # Space, not item count (Phase 2) -- a pool packed with Logs runs out
        # of room at a third the unit count that grain would.
        total = sum(res[r] * resource_bulk(r) for r in names)
        if not capacity or total <= capacity:
            continue
        overage_frac = (total - capacity) / total
        for resource in names:
            if res[resource] <= 0 or resource == "Gold":
                continue   # Gold is minted currency, not a perishable good --
                            # it still occupies vault space (counts toward
                            # `total` above) but never decays just because the
                            # vault is overflowing
            base_rate = RESOURCES.get(resource, {}).get("spoil_rate", 0.0)
            overflow_rate = max(OVERFLOW_MIN_RATE, base_rate * OVERFLOW_SPOILAGE_MULTIPLIER)
            # Capped well under 100% -- a genuine grace period needs *some*
            # grace even in the worst case (badly overflowing + a fast-
            # spoiling good), not a loophole back to an instant full wipeout.
            loss_frac = min(MAX_OVERFLOW_LOSS_FRACTION, overflow_rate * overage_frac)
            loss = round(res[resource] * loss_frac)
            res[resource] = max(0, res[resource] - loss)


def advance_settlement_storage(world):
    """Called every turn, after production chains and before consumption
    draws on the result: spoil and (if applicable) overflow-decay every
    settlement's *and* village's own storage -- Villages have real storage
    of their own as of Phase 10 (see the Village class), no longer exempt
    the way they used to be."""
    for settlement in world.settlements:
        _apply_settlement_spoilage_and_overflow(settlement)
    for village in world.villages:
        _apply_settlement_spoilage_and_overflow(village)


# --- Phase 10: local logistics -----------------------------------------------
# "Every settlement owns its own inventory. Not one empire inventory" --
# already true as of Phase 9. What was still missing, and what this phase
# actually adds, is the physical *movement* between them: Phase 9's
# production routing (_route_farm_production) deposited a region's harvest
# straight into storage with no travel time at all -- a real teleport, just
# a smaller-scoped one than the old single-national-pool model it replaced.
#
# Two changes close that gap:
#   1. _route_farm_production itself changed (see its docstring): a Crop/
#      Livestock harvest now lands at the region's own Villages first, not
#      its Settlements. A Village has no mill/loom/forge -- it's "purely a
#      producer" -- so raw Wheat sitting in a village's granary is
#      genuinely stuck there until something moves it.
#   2. run_local_logistics is that something: every turn, within each
#      region, it looks for a node (Village or Settlement) sitting on
#      surplus of a household-economy resource (_SETTLEMENT_STORAGE_
#      RESOURCES) and another node in the *same region* that actually
#      needs it, and dispatches a LocalShipment between them -- a real
#      multi-turn journey along a straight-line path (see the class
#      docstring for why not the exact winding road), not an instant
#      transfer. A Village's surplus Wheat can end up at a Settlement that
#      converts it (advance_settlement_production_chains, Village-
#      excluded, Phase 9) into Flour/Bread; that Settlement's surplus
#      Bread can then ship back out to whichever Village or Settlement
#      needs Food most -- which is *usually*, but never guaranteed to be
#      and never literally tracked as, the same Village that grew the
#      wheat in the first place (no per-shipment provenance -- see the
#      module docstring's "general redistribute-by-need" framing).
#
# Deliberately out of scope for this phase: cross-region logistics. A
# region's Villages/Settlements are already connected by real roads (built
# when the region was settled), so this reuses that existing connectivity
# implicitly (any two nodes in the same region are assumed reachable) --
# but two different regions have no such physical link modeled yet, so a
# Village whose faction owns no Settlement in its own region has nothing
# to ship its surplus to and just accumulates it, same as it would with no
# logistics system at all. A real path (following the actual road, not a
# straight line) and reaching across regions are both natural follow-ups,
# not attempted here.

# Rough placeholders, not balance-tuned (same caveat as every quantity in
# this file).
LOCAL_SURPLUS_RESERVE = 20          # flat floor every node keeps of anything before shipping the rest
# Firewood/Clothes production is genuinely small-scale at a single node
# (a per-capita trickle, not a bulk industrial resource like Iron/Logs) --
# LOCAL_SURPLUS_RESERVE's 20-unit floor, sized for those bulk goods, used
# to swallow a small Village's *entire* Firewood stock before it ever
# counted as "surplus" (an 18-unit stockpile, comfortably above its own
# 1-unit/turn need, still computed to exactly 0 spare) -- silently
# blocking Firewood from ever reaching a Settlement that had none at all,
# every single Winter. A much smaller floor, still enough to keep a node
# from shipping away its literal last few units, actually lets real spare
# stock move.
LOCAL_HOUSEHOLD_SURPLUS_RESERVE = 5
LOCAL_RESERVE_BUFFER_TURNS = 4      # for a resource with a real per-turn need, keep this many turns' worth too
LOCAL_NEED_THRESHOLD = 20           # a settlement "needs" a production input if its own stock is below this
# 2 felt tight in testing: a node with a couple of slots already tied up
# in ordinary production-input traffic could end up unable to dispatch a
# genuinely urgent food shipment at all. 4 leaves real headroom.
MAX_ACTIVE_LOCAL_SHIPMENTS_PER_NODE = 6
LOCAL_SHIPMENT_MIN_QUANTITY = 10
LOCAL_SHIPMENT_MAX_QUANTITY = 60   # raised from 30 -- a Harvest-season
                                   # village needs to actually clear a big
                                   # burst of production out to the
                                   # Settlements that depend on it before
                                   # it piles up into overflow spoilage
                                   # (see VILLAGE_STORAGE_BASE)
LOCAL_SHIPMENT_CELLS_PER_TURN = 8
MIN_LOCAL_TRANSIT_TURNS, MAX_LOCAL_TRANSIT_TURNS = 1, 5
_LOCAL_PATH_BBOX_PAD = 8    # cells of slack around the two endpoints for the local
                             # path search -- enough room to bow out to a nearby road
                             # or around a lake without turning a short intra-region
                             # hop into a map-wide Dijkstra
LOCAL_PATH_BUDGET_PER_TURN = 2   # brand-new (uncached) local path searches per turn,
                                  # same reasoning and same shape as trade's
                                  # REGIONAL_PATH_BUDGET_PER_TURN: node pairs are
                                  # cached forever once solved, but new Villages keep
                                  # appearing all game, so the uncached pool never
                                  # fully closes and an unbounded burst would hitch


def _local_path(world, region, a_node, b_node):
    """Terrain- and road-aware path between two nodes in the same region,
    for a LocalShipment to actually follow. Roads get the usual discount
    (worldgen._elev_cost's `roads`), which within a region means shipments
    ride the very road network the region built to connect these nodes,
    instead of cutting cross-country between them.

    Cached forever per node pair -- settlements and villages never move --
    keyed by (kind, id) on both sides, since settlement ids and village ids
    are independent, overlapping id spaces (same care as trade's
    _get_regional_path_cache).

    Returns None when there's no path, or when this turn's search budget is
    already spent; the caller falls back to a straight line for that
    dispatch and tries again for the pair next time (deliberately NOT
    caching the fallback, which would make one busy turn permanently
    saddle a pair with a bad path)."""
    cache = getattr(world, "_local_path_cache", None)
    if cache is None:
        cache = {}
        world._local_path_cache = cache
    key = frozenset(((a_node[0], a_node[1].id), (b_node[0], b_node[1].id)))
    if key in cache:
        return cache[key]
    budget = getattr(world, "_local_path_budget", LOCAL_PATH_BUDGET_PER_TURN)
    if budget <= 0:
        return None
    world._local_path_budget = budget - 1

    a_pos, b_pos = a_node[1].pos, b_node[1].pos
    pad = _LOCAL_PATH_BBOX_PAD
    x0, x1 = sorted((a_pos[0], b_pos[0]))
    y0, y1 = sorted((a_pos[1], b_pos[1]))
    # No wrap handling: both ends are land nodes in one region, and land never
    # straddles the east-west seam (see wrap.py / worldgen's seamlessness).
    cellset = {(x, y)
               for y in range(max(0, y0 - pad), min(world.h, y1 + pad + 1))
               for x in range(max(0, x0 - pad), min(world.w, x1 + pad + 1))
               if world.owner[y][x] != OCEAN}
    roads = road_cells(world)
    path = _path_dijkstra(cellset,
                          lambda c: _elev_cost(world, world.base_cost, c,
                                               faction_idx=region.faction_idx,
                                               roads=roads),
                          a_pos, b_pos, world.w)
    cache[key] = path
    return path

# Every input any settlement-storage recipe actually consumes (Wheat,
# Flour, Milk, Wool, Cotton, Cloth -- see RECIPES) -- the "a settlement
# needs more of this to keep converting" side of demand. Only Settlements
# ever want these (see _node_wants): Villages can't convert anything, so
# there's no reason for one to want raw material shipped *to* it.
_LOCAL_PRODUCTION_INPUTS = {i for output, options in RECIPES.items()
                           if output in _SETTLEMENT_STORAGE_RESOURCES
                           for opt in options for i in opt["inputs"]
                           if i in _SETTLEMENT_STORAGE_RESOURCES}

# Checked in this order when a node looks for something to ship out --
# survival needs (Food/Firewood/Clothes) go first so a node with several
# surplus resources always tries to cover someone's starvation/freezing
# risk before it bothers with ordinary production-input traffic, not
# whichever happened to be first in a plain, unordered resource set.
_LOCAL_SHIPMENT_SURVIVAL = list(_FOOD_SOURCES) + ["Firewood", "Clothes"]
_LOCAL_SHIPMENT_INDUSTRIAL = sorted(_SETTLEMENT_STORAGE_RESOURCES
                                    - set(_FOOD_SOURCES) - {"Firewood", "Clothes"})
_LOCAL_SHIPMENT_PRIORITY = _LOCAL_SHIPMENT_SURVIVAL + _LOCAL_SHIPMENT_INDUSTRIAL


def rotate_for_turn(items, turn):
    """`items` rotated by `turn`, so whatever sat at the back reaches the front
    regularly instead of never.

    This exists because of a starvation bug that turned up in TWO separate
    places, and would turn up in a third the next time someone wrote a "scan a
    fixed list of resources, dispatch the first match, break" loop. Both
    run_local_logistics and trade.run_sell_to_city move at most one resource
    per node per turn and both walked a fixed order, so anything low in that
    order was permanently starved. Measured on the turn-561 world: local
    logistics dispatched 1,155 shipments over 20 turns of which exactly ONE was
    Gold Ore (index 38 of 57), and sell-to-city shipped 11,102 Coal and ZERO
    Gold Ore over 60 turns purely because "Coal" sorts before "Gold Ore". Every
    Mint on the map stood idle while the ore rotted where it was dug.

    Deliberately a rotation rather than a shuffle or a demand-weighted sort:
    it is a pure function of the turn number, so a replayed turn moves exactly
    the same goods and nothing about determinism changes."""
    items = list(items)
    if not items:
        return items
    offset = turn % len(items)
    return items[offset:] + items[:offset]


def local_shipment_priority(turn):
    """The order a node checks its surplus in this turn. Survival goods keep
    the front unconditionally -- covering someone's starvation always beats
    moving ore -- and the industrial tail rotates (see rotate_for_turn)."""
    return _LOCAL_SHIPMENT_SURVIVAL + rotate_for_turn(_LOCAL_SHIPMENT_INDUSTRIAL, turn)


def _region_logistics_nodes(world, region):
    """Every Village and Settlement in `region` as (kind, object) pairs --
    the pool run_local_logistics matches surplus/need within."""
    nodes = [("village", world.villages[vid]) for vid in getattr(region, "villages", [])]
    nodes += [("settlement", world.settlements[sid]) for sid in getattr(region, "meta_settlements", [])]
    return nodes


def _node_surplus(node, resource, needs):
    """How much of `resource` this node can spare -- above a flat floor,
    and above enough of a buffer to cover its own near-term need first (so
    a Village doesn't ship away food it's about to need itself). Food
    sources (Food Products and edible raw Crops -- see _FOOD_SOURCES) are
    handled as one pooled reserve (any of Bread/Meat/Wheat/Potatoes/etc.
    can cover the "Food" need) rather than reserving each one
    individually, since they're fully interchangeable for that purpose --
    Luxury Goods (Phase 13) get the identical pooled treatment, for the
    same reason.

    A pooled resource's OWN surplus is capped at the pool's total spare
    amount, not that resource's proportional share of it -- deliberately
    NOT `stock * spare_total / total`, which used to silently strand real
    spare food that happened to be split across several Crop types (a
    Village holding 12 Wheat + 13 Rye + 17 Peas, comfortably 22 above its
    own reserve, would compute each one's *individual* surplus as 6/7/9 --
    all under LOCAL_SHIPMENT_MIN_QUANTITY, so NONE of it could ever ship,
    even though the pooled total plainly had plenty to spare). Since
    run_local_logistics only ever dispatches one shipment (one resource)
    per node per turn regardless of how many resources it checks, capping
    each candidate at the shared spare_total can't over-ship the pool --
    whichever single resource actually gets picked this turn, the amount
    shipped is still bounded by the real total surplus."""
    res = getattr(node, "resources", {})
    stock = res.get(resource, 0)
    if stock <= 0:
        return 0
    if resource in _FOOD_SOURCES:
        total_food = sum(res.get(f, 0) for f in _FOOD_SOURCES)
        if total_food <= 0:
            return 0
        reserve = max(LOCAL_SURPLUS_RESERVE, needs.get("Food", 0) * LOCAL_RESERVE_BUFFER_TURNS)
        spare_total = max(0, total_food - reserve)
        return min(stock, spare_total)
    if resource in _LUXURY_GOODS:
        total_luxury = sum(res.get(l, 0) for l in _LUXURY_GOODS)
        if total_luxury <= 0:
            return 0
        reserve = max(LOCAL_SURPLUS_RESERVE, needs.get("Luxury", 0) * LOCAL_RESERVE_BUFFER_TURNS)
        spare_total = max(0, total_luxury - reserve)
        return min(stock, spare_total)
    if resource == "Firewood":
        reserve = max(needs.get("Firewood", 0) * LOCAL_RESERVE_BUFFER_TURNS,
                     LOCAL_HOUSEHOLD_SURPLUS_RESERVE)
    elif resource == "Clothes":
        reserve = max(needs.get("Clothes", 0) * LOCAL_RESERVE_BUFFER_TURNS,
                     LOCAL_HOUSEHOLD_SURPLUS_RESERVE)
    elif resource == "Fodder":
        # A village with a herd holds back what that herd will eat this
        # Winter before calling any of its hay spare -- otherwise it ships
        # away the feed and then culls the animals for want of it.
        reserve = max(round(village_winter_fodder_need(node) * FODDER_STOCK_BUFFER),
                     LOCAL_SURPLUS_RESERVE)
    else:
        reserve = LOCAL_SURPLUS_RESERVE
    return max(0, stock - reserve)


def _node_wants(kind, node, resource, needs):
    """Does this node have real unmet demand for `resource` right now?
    Consumption resources (Food/Firewood/Clothes/Luxury) apply to both
    Villages and Settlements -- everyone eats, and everyone can benefit
    from a bit of Wine or Jewelry (Phase 13). Production inputs
    (_LOCAL_PRODUCTION_INPUTS) only ever apply to Settlements -- a Village
    growing its own Wheat never "needs" more Wheat shipped to it, and
    couldn't do anything with someone else's Milk or Wool either.

    A raw Crop (e.g. Wheat) can be wanted for either reason at once now
    that it's a real food source too (_FOOD_SOURCES) -- a Settlement
    might want it to keep its population fed AND to keep its Bakery
    supplied, two independent reasons that don't shadow each other."""
    res = getattr(node, "resources", {})
    if resource in _FOOD_SOURCES:
        total_food = sum(res.get(f, 0) for f in _FOOD_SOURCES)
        wants_food = (needs.get("Food", 0) > 0
                     and total_food < needs.get("Food", 0) * LOCAL_RESERVE_BUFFER_TURNS)
        wants_input = (kind == "settlement" and resource in _LOCAL_PRODUCTION_INPUTS
                      and res.get(resource, 0) < LOCAL_NEED_THRESHOLD)
        return wants_food or wants_input
    if resource in _LUXURY_GOODS:
        total_luxury = sum(res.get(l, 0) for l in _LUXURY_GOODS)
        return needs.get("Luxury", 0) > 0 and total_luxury < needs.get("Luxury", 0) * LOCAL_RESERVE_BUFFER_TURNS
    if resource == "Firewood":
        return (needs.get("Firewood", 0) > 0
               and res.get("Firewood", 0) < needs.get("Firewood", 0) * LOCAL_RESERVE_BUFFER_TURNS)
    if resource == "Clothes":
        return res.get("Clothes", 0) < needs.get("Clothes", 0) * LOCAL_RESERVE_BUFFER_TURNS
    if resource == "Fodder":
        # Hay is wanted by whoever has animals to feed, which is a demand no
        # other branch here can express: Fodder isn't edible, isn't a luxury,
        # and isn't a settlement production input, so it fell through to
        # "nobody wants this" and logistics never moved a bale of it. Villages
        # in forest/mountain regions kept herds they structurally could not
        # feed while plains villages sat on tens of thousands of surplus hay.
        winter_need = village_winter_fodder_need(node)
        return winter_need > 0 and res.get("Fodder", 0) < winter_need * FODDER_STOCK_BUFFER
    if kind == "settlement" and resource in _LOCAL_PRODUCTION_INPUTS:
        return res.get(resource, 0) < LOCAL_NEED_THRESHOLD
    return False


class LocalShipment:
    """Goods physically moving between two of the same faction's
    Villages/Settlements within a single region -- the actual mechanism
    behind "nothing is teleported" (see the module docstring above). No
    price/payment involved (this is internal redistribution, not a trade
    deal) -- otherwise the same "takes real turns along a real path" shape
    as trade.TradeCaravan.

    `path`, when the caller can supply one (_local_path), is the real
    terrain- and road-aware route, so a wagon is drawn following the
    region's roads rather than trailing across open wilderness. It falls
    back to a straight two-point line when no path exists or the turn's
    pathfinding budget is spent -- geometrically wrong but never wrong
    enough to break anything, since nothing about delivery depends on the
    cells in between."""

    def __init__(self, faction_idx, resource, quantity,
                origin_kind, origin_id, dest_kind, dest_id, origin_pos, dest_pos,
                path=None, transit_cells=None):
        self.faction_idx = faction_idx
        self.resource = resource
        self.quantity = quantity
        self.origin_kind = origin_kind   # "village" | "settlement"
        self.origin_id = origin_id
        self.dest_kind = dest_kind
        self.dest_id = dest_id
        self.path = path if path else [origin_pos, dest_pos]
        if transit_cells is not None:
            dist = transit_cells
        else:
            # Straight-line fallback. Both ends are land nodes in the same
            # region -- land never straddles the east-west seam (see wrap.py /
            # worldgen's seamlessness), so plain distance is already correct.
            dist = ((origin_pos[0] - dest_pos[0]) ** 2
                    + (origin_pos[1] - dest_pos[1]) ** 2) ** 0.5
        self.turns_total = max(MIN_LOCAL_TRANSIT_TURNS,
                              min(MAX_LOCAL_TRANSIT_TURNS, round(dist / LOCAL_SHIPMENT_CELLS_PER_TURN)))
        self.turn_progress = 0

    @property
    def pos(self):
        """Position along the path -- for map rendering, same convention as
        trade.TradeCaravan.pos, except interpolated BETWEEN path cells
        rather than snapped to one. Local hops are short: a real path is
        often only a handful of cells, and the straight-line fallback is
        just two, so snapping to the nearest cell would make a wagon jump
        in visible lurches instead of rolling."""
        frac = min(1.0, self.turn_progress / self.turns_total)
        span = frac * (len(self.path) - 1)
        idx = min(int(span), len(self.path) - 2) if len(self.path) > 1 else 0
        if len(self.path) < 2:
            return self.path[0]
        (x0, y0), (x1, y1) = self.path[idx], self.path[idx + 1]
        t = span - idx
        return (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)


def _active_outgoing_shipments(world, kind, node_id):
    """How many shipments this node is *currently sending* -- deliberately
    outgoing-only. Counting incoming ones too (an earlier version of this
    did) meant a busy hub settlement's slots could fill up purely from
    other villages shipping *to* it, before it ever got a turn as a
    source in the same call -- silently blocking it from ever shipping
    its own surplus Bread back out. Receiving isn't capped at all: a
    settlement can be the destination of as many simultaneous deliveries
    as villages want to send it."""
    return sum(1 for s in world.local_shipments if s.origin_kind == kind and s.origin_id == node_id)


def run_local_logistics(world):
    """Called every turn: within each region, greedily match surplus
    household-economy resources to unmet need among that region's own
    Villages/Settlements (see the module docstring for the full picture),
    and dispatch a LocalShipment for the first match found per node --
    nearest candidate first (see the near_by_node precompute below), not
    just whichever happened to come first in region.villages/
    meta_settlements' storage order. Distance-preferring, not a hard
    lock-out: a node still falls through to a farther one if its nearest
    neighbors don't want the resource, so nothing goes unfed just because
    its closest neighbor happens to be equally short. Fully automatic --
    no player or AI decision involved, matching how the rest of this
    economy already works."""
    world._local_path_budget = LOCAL_PATH_BUDGET_PER_TURN
    priority = local_shipment_priority(getattr(world, "turn", 0))
    for region in world.regions:
        if region.faction_idx < 0:
            continue
        nodes = _region_logistics_nodes(world, region)
        if len(nodes) < 2:
            continue
        season = world.season
        needs_by_node = {(kind, node.id): settlement_needs(node, season) for kind, node in nodes}
        # Nearest-first order per node, precomputed once per region per turn
        # (not per resource below -- distance doesn't depend on which
        # resource is being matched, so resorting inside the priority loop
        # would just repeat the same sort for nothing). Cheap squared
        # straight-line distance (wrap.dist2_wrap) for ordering only; the
        # real terrain-aware path is still only computed after a match is
        # chosen, via _local_path below, unchanged.
        near_by_node = {}
        for kind, node in nodes:
            others = [(k2, n2) for k2, n2 in nodes if n2 is not node]
            others.sort(key=lambda kn: wrap.dist2_wrap(node.pos, kn[1].pos, world.w))
            near_by_node[(kind, node.id)] = others

        for kind, node in nodes:
            if _active_outgoing_shipments(world, kind, node.id) >= MAX_ACTIVE_LOCAL_SHIPMENTS_PER_NODE:
                continue
            own_needs = needs_by_node[(kind, node.id)]
            dispatched = False
            for resource in priority:
                surplus = _node_surplus(node, resource, own_needs)
                if surplus < LOCAL_SHIPMENT_MIN_QUANTITY:
                    continue
                for other_kind, other in near_by_node[(kind, node.id)]:
                    if not _node_wants(other_kind, other, resource, needs_by_node[(other_kind, other.id)]):
                        continue
                    qty = min(surplus, LOCAL_SHIPMENT_MAX_QUANTITY)
                    if not hasattr(node, "resources"):
                        node.resources = {}
                    node.resources[resource] = node.resources.get(resource, 0) - qty
                    path = _local_path(world, region, (kind, node), (other_kind, other))
                    world.local_shipments.append(LocalShipment(
                        region.faction_idx, resource, qty, kind, node.id,
                        other_kind, other.id, node.pos, other.pos, path=path,
                        transit_cells=path_transit_cells(world, path) if path else None))
                    dispatched = True
                    break
                if dispatched:
                    break


def advance_local_shipments(world):
    """Called every turn: move every in-transit LocalShipment, delivering
    on arrival straight into the destination's own storage. No capacity
    check at delivery -- same grace-period philosophy as everywhere else
    in Phase 9/10: an over-full granary just spoils faster next turn
    (advance_settlement_storage), the wagon isn't turned away."""
    remaining = []
    for s in world.local_shipments:
        s.turn_progress += 1
        if s.turn_progress < s.turns_total:
            remaining.append(s)
            continue
        dest = (world.villages[s.dest_id] if s.dest_kind == "village"
               else world.settlements[s.dest_id])
        if not hasattr(dest, "resources"):
            dest.resources = {}
        dest.resources[s.resource] = dest.resources.get(s.resource, 0) + s.quantity
    world.local_shipments = remaining


# --- biome / climate classification -----------------------------------------
# BIOME_YIELDS/CLIMATE_MODIFIERS/SEASON_MODIFIERS (the old geography-driven
# aggregate-resource system that predates the tier-based registry above)
# used to still be live here for whichever old names hadn't been migrated
# yet: Grain/Fresh Water were retired outright (no value in the new system
# at all); Iron/Coal/Stone/Wood/Gems each got a real replacement in the new
# registry (Phase 12/13) and were removed once that replacement existed, to
# avoid double-producing them; Mithril/Textiles had no replacement and were
# just removed outright. Fish/Silks/Spices/Steel were the last four still
# running on this old system -- also removed outright now (no live-registry
# equivalent, same clean removal Mithril/Textiles got), which leaves
# nothing left running on it at all, so the whole old system (BIOME_YIELDS/
# CLIMATE_MODIFIERS/SEASON_MODIFIERS/get_climate_modifier/
# get_seasonal_modifier, and compute_region_yield's old geography-driven
# raw-yield loop) is removed along with them rather than kept around empty.
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
def compute_region_yield(region, season):
    """This region's resource production for `season`: the per-crop,
    season-gated production from compute_crop_yield (real, live output for
    Wheat/Barley/Rice/Cotton/etc) plus the continuous, un-gated Forestry/
    Mining production from compute_industry_yield (Phase 12). Every raw
    resource in the game comes from one of these two now -- the old
    geography-driven BIOME_YIELDS/CLIMATE_MODIFIERS/SEASON_MODIFIERS system
    this function used to also blend in has been fully retired (see the
    STALE-removal note above compute_region_yield's neighboring biome/
    climate classification functions)."""
    result = {}
    for crop, amount in compute_crop_yield(region, season).items():
        result[crop] = result.get(crop, 0) + amount
    for resource, amount in compute_industry_yield(region, season).items():
        result[resource] = result.get(resource, 0) + amount
    return result


# --- storage caps + spoilage: without these, stockpiles pile up forever ----
# Cap scales with empire size (more settlements = more warehouse capacity);
# overflow production is simply lost rather than banked, no event/warning.
STORAGE_CAP_BASE = {1: 6000, 2: 4000, 3: 5000, 4: 1000}   # by RESOURCES[r]["tier"]
STORAGE_CAP_SCALE_PER_SETTLEMENT = 0.1
_DEFAULT_CAP_BASE = 3000

# Perishables rot in storage even under cap; everything else defaults to 0.
# This is the old shared-national-pool spoilage table -- every resource
# that used to key into it (Grain/Fresh Water, Iron/Coal/Stone/Wood/Gems,
# Mithril/Textiles, Fish/Silks/Spices/Steel) has since been either retired
# outright or migrated to the new registry's own per-resource "spoil_rate"
# property (see _apply_settlement_spoilage_and_overflow, the real spoilage
# path every current resource actually uses), leaving this permanently
# empty -- kept only as the generic "old shared pool" fallback can_afford/
# _pay_cost/etc. still nominally support, same as nation.stats["resources"]
# itself (see that dict's own note).
SPOILAGE_RATE = {}


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


def _purge_phantom_pool(nation):
    """Drop any _SETTLEMENT_STORAGE_RESOURCES entry from a faction's national
    pool.

    Those goods live per-node now (Phase 9 onward) and can_afford/_pay_cost
    read node storage for them, never the pool -- so anything of that kind
    sitting here is unspendable by definition. It still got SUMMED into the
    resources sidebar (see map_view._current_resource_snapshot), so the player
    was shown stock they could never use: 48,509 phantom units across the
    factions on a measured save, almost all of it crops and timber banked by
    transfer_region on past conquests (now fixed at that source too).

    Runs every turn rather than as a one-shot migration: it's a scan of a
    handful of dict keys, it's idempotent, and doing it this way means any
    future code path that wrongly banks node goods in the pool self-corrects
    instead of quietly re-accumulating the same lie."""
    res = nation.stats.get("resources")
    if not res:
        return
    for resource in [r for r in res if r in _SETTLEMENT_STORAGE_RESOURCES]:
        del res[resource]


def _clamp_to_storage(nation):
    res = nation.stats.get("resources", {})
    for resource in list(res.keys()):
        cap = _storage_cap(nation, resource)
        if res[resource] > cap:
            res[resource] = int(cap)


# --- military, derived from war-relevant stockpiles -------------------------
MOBILIZATION_RATE = 0.08   # share of a realm's ADULTS it can put in the field without
                            # collapsing the economy that feeds them -- the rest are
                            # busy farming, mining and hauling. 8% of a 5,000-adult
                            # realm is a 400-strong army, which is what makes
                            # population the real backbone of military power
MILITIA_WEIGHT = 0.30      # a levied adult with no weapon to give them still shows up,
                            # but counts for far less than a properly armed soldier.
                            # NOT zero: most realms never build a Weaponsmith at all
                            # (measured: several factions still had 0 Weapons at turn
                            # 600), and a hard equipment gate would freeze them out of
                            # expanding entirely rather than merely making them bad at it
CAVALRY_BONUS = 0.50       # fully mounting your armed soldiers is worth +50% -- twice
                           # a Shield, because a horse is worth more than a shield and
                           # is far harder to come by: you can smith shields from ore
                           # you already have, but a horse has to be bred, fed through
                           # Winter and not culled (see LIVESTOCK_DYNAMICS/HERD_POLICIES)
SHIELD_BONUS = 0.25        # fully shielding your armed soldiers is worth +25% -- a real
                            # bonus, but secondary to arming them in the first place
_MILITARY_FLOOR = 10       # even a broken rump state musters something
_MILITARY_CEILING = 1200   # sanity bound only, not a balance lever: military feeds
                            # battlefield unit counts 1:1 (see app/ui/app.py's
                            # _army_for), and past roughly this the battle canvas
                            # stops holding 30 FPS however cheap each unit is


def _faction_nodes(nation, world, fac_idx=None):
    """Every Settlement AND Village a faction holds. Villages carry real
    population and real storage (they receive shipments, see LocalShipment),
    so anything totalling up a realm's people or goods has to count them --
    same reasoning as trade._faction_regional_nodes."""
    nodes = [world.settlements[sid] for sid in nation.meta.get("settlements", [])]
    if fac_idx is None:
        try:
            fac_idx = world.factions.index(nation)
        except ValueError:
            return nodes
    nodes += [v for v in world.villages if v.faction_idx == fac_idx]
    return nodes


def _recompute_military(nation, world, fac_idx=None):
    """Military strength = how many people you can arm, not how much land
    you happen to own.

    A realm levies MOBILIZATION_RATE of its adult population across every
    settlement and village it holds. Weapons arm that levy one-for-one;
    anyone left over still marches, but as militia (MILITIA_WEIGHT), and
    Shields add a bonus over whatever fraction of the ARMED troops they
    cover. So the three things that move this number are exactly the three
    things a player can actually build up: people, Weapons, Shields.

    This replaces a formula built on territory and Iron stock, which had two
    problems: it rewarded owning empty land rather than developing it, and
    its Iron term saturated almost immediately (measured: factions sitting
    on 40,000+ Iron got the same +25 as one with 1,000), leaving the whole
    rating nearly static from the early game onward.

    Species `mil` applies as a multiplier rather than the flat +/- it used to
    be -- a flat +16 was decisive against the old ~50 baseline and rounding
    error against a levy of several hundred."""
    species = SPECIES.get(nation.meta.get("species"), {})
    nodes = _faction_nodes(nation, world, fac_idx)

    adults = sum(getattr(n, "adults", 0) for n in nodes)
    weapons = sum(getattr(n, "resources", {}).get("Weapons", 0) for n in nodes)
    shields = sum(getattr(n, "resources", {}).get("Shields", 0) for n in nodes)

    horses = faction_horses(world, fac_idx) if fac_idx is not None else 0

    levy = adults * MOBILIZATION_RATE
    armed = min(levy, weapons)
    militia = levy - armed
    strength = armed + militia * MILITIA_WEIGHT
    if armed > 0:
        strength *= 1.0 + SHIELD_BONUS * min(armed, shields) / armed
        # Cavalry: exactly the same shape as the Shield term above -- what
        # fraction of your ARMED troops you can put on a horse. Horses are the
        # one military input that isn't a stockpiled good: they're living herd
        # (village.herds), so mounting your army means keeping and feeding one
        # through Winter rather than smithing more. That makes a Stable, the
        # Grow herd policy and a full hay barn all read straight through into
        # military strength.
        strength *= 1.0 + CAVALRY_BONUS * min(armed, horses) / armed
    strength *= 1.0 + species.get("mil", 0) / 100.0

    nation.stats["military"] = max(_MILITARY_FLOOR,
                                   min(_MILITARY_CEILING, int(strength)))


# --- prosperity: a meter/bar per settlement, driven by the value of goods
# it handles/produces and gold it brings in, that visibly rises and falls
# with how well its whole faction's economy is doing turn to turn (not a
# static score off numbers that never change once rolled) -------------------
PROSPERITY_MAX = 100.0
PROSPERITY_STARTING = 0.0       # every settlement/village starts with none — it's earned
PROSPERITY_VALUE_CEIL = 140.0   # goods+wealth gold-value at which prosperity hits 100
# Fraction of the gap to target closed each turn -- deliberately slow, so a
# meter is a long-term payoff (~90% of the way to a steady target takes
# roughly 230 turns, ~2.3 in-game years at the current TURNS_PER_SEASON),
# not something that fills up within the first few turns of a new
# settlement's life.
PROSPERITY_EASE = 0.01


def resource_value(resource, amount):
    """Gold-equivalent value of `amount` units of `resource` — the tier
    pricing every trade deal already uses (app/world/trade.py), reused here
    so "value of goods" means the same thing everywhere in the economy.
    Gold itself is the one special case: it doesn't get priced off its
    (Manufactured Goods) tier like everything else -- a unit of Gold IS a
    unit of gold-equivalent value, by definition, 1:1."""
    if resource == "Gold":
        return amount
    tier = RESOURCES.get(resource, {}).get("tier", 3)
    return amount * BASE_VALUE_BY_TIER.get(tier, 3)


def _resource_bundle_value(resource_amounts):
    return sum(resource_value(r, a) for r, a in resource_amounts.items())


def settlement_goods_wealth_value(settlement, season, tax_income):
    """A city/castle/town's per-turn "goods & wealth" figure: the gold-
    value of what it needs under Phase 8's consumption model (see
    settlement_needs_value) plus the gold it brings in (tax_income). Used
    to be the gold-value of its flat SETTLEMENT_UPKEEP roll; that's gone
    (see the module docstring), replaced by the real, population-scaled
    figure."""
    return settlement_needs_value(settlement, season) + tax_income


def village_goods_wealth_value(farm_output):
    """A village's per-turn "goods" figure: the gold-value of its farm
    output, priced at tier 1 (every Crop shares that tier) — villages
    carry no upkeep/tax of their own (see Village). Used to price this
    against "Grain" specifically; tier-1-flat is the direct replacement
    now that Grain itself is gone (see the module docstring)."""
    return farm_output * BASE_VALUE_BY_TIER[1]


def _prosperity_target(raw_value, health_factor):
    return max(0.0, min(PROSPERITY_MAX,
                        PROSPERITY_MAX * raw_value * health_factor / PROSPERITY_VALUE_CEIL))


def seed_prosperity():
    """Starting meter fill for a brand-new settlement/village — empty.
    Prosperity is something a settlement builds up over a long stretch of
    turns (see PROSPERITY_EASE), not a number it's born with."""
    return PROSPERITY_STARTING


def _faction_health_factor(production_value, consumption_value):
    """>1 when a faction produced more value than its settlements needed
    this turn, <1 when it's running a deficit — the thing that actually
    makes every one of its settlements' prosperity meters rise or fall over
    time, on top of each settlement's own goods/wealth value.
    `consumption_value` is the gold-value of what settlements needed under
    Phase 8 (see advance_settlement_consumption's return value) — used to
    be the old flat upkeep roll's value. There used to be a separate
    `gold_income` term here on top of `production_value` (the old flat
    per-turn tax draw) -- retired along with that whole mechanic (see the
    Currency overhaul section): Gold is real settlement-storage production
    now, so its value already flows through `production_value` the exact
    same way Iron's or Wheat's does, with nothing left to add separately."""
    if consumption_value <= 0:
        return 1.0
    return max(0.5, min(1.5, production_value / consumption_value))


def _update_prosperity(world, production_value, consumption_value):
    """Ease every settlement's and village's prosperity meter toward this
    turn's target — called once per turn from advance_turn, after
    production/consumption for every faction is known."""
    villages_by_fac = defaultdict(list)
    for v in world.villages:
        villages_by_fac[v.faction_idx].append(v)

    for fac_idx, nation in enumerate(world.factions):
        health = _faction_health_factor(production_value.get(fac_idx, 0.0),
                                        consumption_value.get(fac_idx, 0.0))
        for sid in nation.meta.get("settlements", []):
            st = world.settlements[sid]
            target = _prosperity_target(
                settlement_goods_wealth_value(st, world.season, st.tax_income), health)
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
VILLAGE_MESH_LINK_RADIUS = 25       # cells -- how far a newly grown village
                                     # looks for OTHER existing villages in
                                     # its own region to also connect to
                                     # directly (not just back to the city
                                     # that founded it), for a genuinely
                                     # interconnected region instead of a
                                     # pure hub-and-spoke back to one city
VILLAGE_MESH_MAX_LINKS = 3          # cap on how many such links one new
                                     # village creates, so a region with
                                     # many villages already clustered
                                     # together doesn't end up with a dense
                                     # web from a single spawn event
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
                                    _VILLAGE_FERT_PATCH, _local_road_path)
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
        population, adults, children, max_population = _roll_population(random, "village")
        prosperity = seed_prosperity()

        v = Village(len(world.villages), region_id, st.faction_idx,
                   namer("village", species), (x, y), farm,
                   population, adults, children, prosperity, max_population)
        world.villages.append(v)
        region.villages.append(v.id)
        path = _local_road_path(world, st.pos, v.pos, faction_idx=st.faction_idx)
        segs = world.roads_by_region.setdefault(region_id, [])
        segs.extend((p1, p2, "dirt") for p1, p2 in zip(path, path[1:]))
        _connect_new_village_to_region(world, region, v)

        st.villages_spawned += 1
        st.prosperity = 0.0


def _connect_new_village_to_region(world, region, new_village):
    """A newly city-grown village also gets connected directly to nearby
    villages already in its own region -- not just back to the City that
    founded it -- so a region ends up genuinely interconnected (better
    trading/logistics reach) instead of a pure hub-and-spoke back to one
    city. Terrain-aware paths (_local_road_path), same as every other road
    in the region, not the gradual RoadProject machinery construction.py's
    player/AI-built roads go through -- this is instant, like the
    city->village link right above. Picks the VILLAGE_MESH_MAX_LINKS
    closest existing villages within VILLAGE_MESH_LINK_RADIUS, not every
    village in the region regardless of distance, so one spawn event can't
    blanket a large, already-crowded region in new links."""
    from app.world.worldgen import _local_road_path
    candidates = []
    for vid in region.villages:
        if vid == new_village.id:
            continue
        other = world.villages[vid]
        dx = other.pos[0] - new_village.pos[0]
        dy = other.pos[1] - new_village.pos[1]
        dist2 = dx * dx + dy * dy
        if dist2 <= VILLAGE_MESH_LINK_RADIUS ** 2:
            candidates.append((dist2, other))
    candidates.sort(key=lambda t: t[0])
    segs = world.roads_by_region.setdefault(region.id, [])
    for _, other in candidates[:VILLAGE_MESH_MAX_LINKS]:
        path = _local_road_path(world, new_village.pos, other.pos,
                                faction_idx=region.faction_idx)
        segs.extend((p1, p2, "dirt") for p1, p2 in zip(path, path[1:]))


# --- turn loop ---------------------------------------------------------------
_STARTING_STOCKPILE_TURNS = 6   # turns' worth of production seeded at gen time
STARTING_GOLD_PER_FACTION = 4000   # a faction's total starting Gold reserve
                                   # (Currency overhaul), split evenly across
                                   # its own settlements -- not derived from
                                   # _STARTING_STOCKPILE_TURNS like everything
                                   # else above, since Gold has no organic
                                   # "per-turn production" figure to scale
                                   # from until a Mint is actually running.
                                   # Raised from 900 -- that was barely a
                                   # single Town's worth of Gold cost, not
                                   # enough runway to actually build toward
                                   # a Mint (let alone a settlement/claim)
                                   # before running dry, especially before
                                   # first contact with another faction
                                   # opens up trading for more.


def seed_initial_stockpiles(world):
    """Called once at world-gen (after regions/settlements/villages exist):
    gives every faction a starting reserve instead of an empty treasury
    (and every settlement/village its own starting Food/Firewood/Clothes
    reserve in its own storage, Phase 9/10 — without this a fresh game
    would start every granary empty and risk immediate starvation before
    production has a chance to catch up), and sets each faction's initial
    military from it."""
    for nation in world.factions:
        nation.stats["resources"] = {}
    for settlement in world.settlements:
        settlement.resources = {}
    for village in world.villages:
        village.resources = {}
    for region in world.regions:
        if region.faction_idx < 0:      # UNCLAIMED — no faction to seed
            continue
        raw_total = {}
        for vid in getattr(region, "villages", []):
            village = world.villages[vid]
            biome_counts, climate, fertility_frac = village_local_sample(world, village, region)
            # Crops use their OWN harvest season, regardless of the world's
            # current season -- world.season at generation time is always
            # "Spring" (see generate_world), and no Crop's GROWTH_CYCLE
            # actually harvests in Spring -- every single one is Summer or
            # Autumn -- so seeding off the live season the normal way
            # always seeded exactly zero starting Crops/Food Products, no
            # matter what the map looked like. That's a real bug, not a
            # balance choice: a fresh village had nothing to eat at all
            # until the world's season clock happened to reach whichever
            # season its local crops harvest in -- up to 3 seasons (worst
            # case ~75 turns) away -- which is what was actually driving
            # population collapse in the game's opening stretch, not a
            # per-capita rate problem. Summed across all 4 seasons since
            # each Crop only ever contributes during its own single
            # Harvest season, so nothing double-counts.
            yield_ = {}
            for season in SEASONS:
                for crop, amount in _crop_yield_core(biome_counts, climate,
                                                     fertility_frac, season).items():
                    yield_[crop] = yield_.get(crop, 0) + amount
            # Forestry/Mining are continuous/season-agnostic, so this is
            # already right regardless of which season generation happens
            # to start on.
            for resource, amount in _industry_yield_core(biome_counts, climate,
                                                          fertility_frac).items():
                yield_[resource] = yield_.get(resource, 0) + amount
            for resource, amount in yield_.items():
                raw_total[resource] = raw_total.get(resource, 0) + amount
            _deliver_village_yield(
                village, {r: a * _STARTING_STOCKPILE_TURNS for r, a in yield_.items()})
        region.resources = raw_total
    for nation in world.factions:
        # Currency overhaul: Gold is minted from Gold Ore now, not drawn
        # from a flat per-turn tax -- a brand new faction wouldn't have
        # struck a single coin yet even though _route_farm_production just
        # seeded its Gold Ore stock like any other raw resource (production
        # chains only run turn-to-turn, not during this one-time seed). A
        # modest starting reserve, split evenly across this faction's own
        # settlements, keeps turn-1 construction/claims/trade from being
        # completely frozen while the first Mint gets running.
        sids = nation.meta.get("settlements", [])
        if sids:
            share = STARTING_GOLD_PER_FACTION / len(sids)
            for sid in sids:
                st = world.settlements[sid]
                st.resources["Gold"] = st.resources.get("Gold", 0) + round(share)
        _clamp_to_storage(nation)     # the seeded reserve mustn't itself exceed the cap
        _recompute_military(nation, world)


# --- The gold ledger --------------------------------------------------------
# "The gold on the resources tab doesn't align with the trades in the trade
# log." It genuinely doesn't, and the trade log was never the problem.
# Measured over 60 turns on a real faction: Gold went 11,460 -> 12,412, and
# *100% of that* came from minting Gold Ore in the production chains -- a
# silent, per-turn process that appears in no log anywhere. Over the same 60
# turns the trade log recorded 3,352 events, most of them domestic transfers
# that deliberately pay in barter and move no coin at all. So the number moved
# for a reason the log never mentions, while the log was full of activity that
# never touched the number.
#
# This ledger closes that gap by attributing every gold flow to the phase of
# the turn that caused it. It works by snapshotting each faction's gold around
# each phase rather than by instrumenting individual call sites -- which means
# it cannot silently miss a source the way a hand-maintained list would, and
# the parts always reconcile exactly to the total change. Adding a new gold
# sink anywhere in the game needs no ledger change to stay accounted for.
GOLD_LEDGER_HISTORY_TURNS = 24   # enough to read a trend without bloating saves


def faction_gold(world, fac_idx):
    """Every coin a faction actually holds, across settlements and villages.
    The same figure the resource bar shows."""
    total = 0
    for st in world.settlements:
        if st.faction_idx == fac_idx:
            total += (getattr(st, "resources", None) or {}).get("Gold", 0)
    for v in world.villages:
        if v.faction_idx == fac_idx:
            total += (getattr(v, "resources", None) or {}).get("Gold", 0)
    return total


def _gold_snapshot(world):
    return [faction_gold(world, i) for i in range(len(world.factions))]


def _record_gold(world, cause, before):
    """Attribute each faction's gold change since `before` to `cause`."""
    ledger = world._gold_turn
    for i, prev in enumerate(before):
        delta = faction_gold(world, i) - prev
        if delta:
            ledger[i][cause] = ledger[i].get(cause, 0) + delta


def gold_in_transit(world, fac_idx):
    """Gold already collected from a buyer but not yet credited -- it rides
    home on the caravan's return leg and is lost if that leg is raided (see
    trade.advance_caravans). This is the money the trade log has already
    announced as a sale but which hasn't reached the treasury, and it's a
    large part of why the headline number lags the log."""
    total = 0
    for c in getattr(world, "trade_caravans", []):
        if c.seller_idx != fac_idx or getattr(c, "leg", None) != "return":
            continue
        for resource, qty in (getattr(c, "payment", None) or []):
            if resource == "Gold":
                total += qty
    return total


def gold_ledger(world, fac_idx):
    """[{turn, causes...}, ...] most recent last, for the Treasury panel."""
    return [e for e in getattr(world, "gold_ledger", {}).get(fac_idx, [])]


def _close_gold_ledger(world):
    """Commit this turn's per-faction breakdown to world.gold_ledger, keeping
    only the recent window (GOLD_LEDGER_HISTORY_TURNS) so saves don't grow
    without bound."""
    ledger = getattr(world, "gold_ledger", None)
    if ledger is None:
        ledger = world.gold_ledger = {}
    for fac_idx, causes in getattr(world, "_gold_turn", {}).items():
        if not causes:
            continue
        entry = {"turn": world.turn, **causes}
        entry["net"] = sum(v for k, v in causes.items())
        history = ledger.setdefault(fac_idx, [])
        history.append(entry)
        del history[:-GOLD_LEDGER_HISTORY_TURNS]
    world._gold_turn = defaultdict(dict)


# --- one-time migration: legacy overflow ------------------------------------
# Worlds created before storage was typed (Phase 3) accumulated stock under a
# single unbounded shared pool, and some nodes carry a genuinely enormous
# hoard: measured on a real save, one city held 1,472,676 space of household
# goods against a 3,300 capacity, and 1,278,435 durable against 3,200.
#
# Left alone that DOES drain -- overflow decay clears it in roughly 80 turns --
# but for all of those turns the city's production is throttled to a standstill
# and every storage meter reads solid red, which looks like a broken save
# rather than a transition. Worse, all of it is simply destroyed.
#
# So on first load of such a world the excess is spilled into whatever spare
# capacity the rest of that faction actually has -- settlements first, since
# only they run the conversion recipes. Nothing is destroyed: anything that
# cannot be rehoused stays where it is and drains through the ordinary
# overflow rule, which lets it still be eaten and converted on the way down.
# Runs once per world, guarded by a flag on the world itself.
_OVERFLOW_MIGRATION_VERSION = 2   # 1 = the destructive clamp shipped in
                                  # v0.2.1; 2 = move-only, destroys nothing
LEGACY_OVERFLOW_FACTOR = 1.5   # only a hoard this far past capacity counts as
                               # legacy. A settled realm normally runs a few
                               # percent over on its durable pool -- that is the
                               # overflow rule working as designed, not damage,
                               # and this must not "tidy" it away


def migrate_legacy_overflow(world):
    """Redistribute pre-typed-pool overflow into the realm's real spare
    capacity. Never destroys anything -- see the section note for the
    measurements that ruled that out. Idempotent and self-guarding."""
    # Versioned, not a plain boolean. v0.2.1 shipped a destructive variant of
    # this migration and marked worlds done; those saves must still be eligible
    # for the corrected move-only pass, which can only help them (whatever it
    # destroyed is gone, but any overflow still sitting there gets rehoused).
    if getattr(world, "_overflow_migration_version", 0) >= _OVERFLOW_MIGRATION_VERSION:
        return {}
    world._overflow_migration_version = _OVERFLOW_MIGRATION_VERSION
    world._overflow_migrated = True     # legacy flag, kept for older readers
    moved = {"moved": 0}

    nodes_by_faction = {}
    for node in list(world.settlements) + list(world.villages):
        if node.faction_idx < 0:
            continue
        nodes_by_faction.setdefault(node.faction_idx, []).append(node)

    for nodes in nodes_by_faction.values():
        for pool in STORAGE_POOLS:
            donors, receivers = [], []
            for node in nodes:
                cap = node_pool_capacity(node, pool)
                if not cap:
                    continue
                stock = node_pool_stock(node, pool)
                if stock > cap * LEGACY_OVERFLOW_FACTOR:
                    donors.append(node)
                elif stock < cap:
                    receivers.append([node, cap - stock])
            if not donors:
                continue
            # Fill settlements before villages. Only settlements run the
            # conversion recipes, so goods parked in a village are inert:
            # measured, spilling a legacy ore hoard into villages left the
            # realm minting 10 gold per 100 turns instead of 952, because the
            # Gold Ore had nowhere to be turned into coin.
            receivers.sort(key=lambda entry: 0 if hasattr(entry[0], "kind") else 1)
            for donor in donors:
                res = getattr(donor, "resources", None) or {}
                excess = node_pool_stock(donor, pool) - node_pool_capacity(donor, pool)
                # Shed the CHEAPEST goods per unit of space they free, not
                # simply the bulkiest. Sorting on bulk alone looks right --
                # bulky goods free the most room per unit -- but it threw away
                # Gold Ore (bulk 1.6) ahead of Tools (0.8) purely because ore
                # is bulkier, and measured on a real save that cut a realm's
                # ore from 12,662 to 2,430 and its minting from 610 gold per
                # 20 turns to 10. Value per unit of space is the honest
                # ordering: dump the cheap bulk (Logs, Stone) and keep what is
                # actually worth something.
                names = sorted((r for r, a in res.items()
                                if a > 0 and storage_class(r) == pool),
                               key=lambda r: resource_value(r, 1) / (resource_bulk(r) or 1.0))
                for name in names:
                    if excess <= 0:
                        break
                    bulk = resource_bulk(name) or 1.0
                    # Move only what somewhere can actually hold. NOTHING is
                    # destroyed here: an earlier version clamped each hoard
                    # down to capacity and discarded the remainder, which
                    # measured WORSE than leaving it alone entirely -- over
                    # 100 turns population went -5,198 against -4,737 for
                    # doing nothing, because the discarded stock was exactly
                    # the reserve the population had been eating, and it also
                    # cost the realm the 952 gold it would have minted from
                    # the ore in that pile. Whatever cannot be rehoused stays
                    # put and drains through the ordinary overflow rule, which
                    # at least lets it be consumed and converted on the way
                    # down.
                    for entry in receivers:
                        if excess <= 0 or res.get(name, 0) <= 0:
                            break
                        node, room = entry
                        take = min(res[name], int(room / bulk), int(excess / bulk) + 1)
                        if take <= 0:
                            continue
                        res[name] -= take
                        if not hasattr(node, "resources"):
                            node.resources = {}
                        node.resources[name] = node.resources.get(name, 0) + take
                        entry[1] = room - take * bulk
                        excess -= take * bulk
                        moved["moved"] += take
    return moved


def advance_turn(world):
    """The turn loop: cycle the season, recompute every region's yield for
    it (including Crops, see compute_region_yield -- production lands at
    the region's own Villages first, Phase 10), run every Village's herd
    for the season (advance_herds), spoil perishables, add production to
    each faction's stockpile, clamp to storage capacity (so nothing piles
    up forever), and recompute military from the new stockpiles -- then
    deliver/convert/redistribute/consume the household economy (see
    advance_local_shipments/advance_production_chains/
    advance_settlement_production_chains/run_local_logistics/
    advance_settlement_consumption) so nothing just teleports into place
    or accumulates forever. There's no separate flat settlement-upkeep
    draw any more (see the module docstring) --
    advance_settlement_consumption is the entire settlement-drain story
    now, and its returned consumption value feeds prosperity below the
    same way the old upkeep value used to."""
    world.turn += 1
    world.season = SEASONS[((world.turn - 1) // TURNS_PER_SEASON) % len(SEASONS)]
    # Weather: rolled/advanced before production, so this turn's harvest
    # already reflects whatever's active right now (see advance_weather).
    advance_weather(world)
    # Gold ledger for this turn -- see the section above. Every phase below
    # that can move coin is bracketed by a snapshot, so the breakdown always
    # adds up to the real change with nothing unaccounted for.
    world._gold_turn = defaultdict(dict)
    _gold_mark = _gold_snapshot(world)

    production_value = defaultdict(float)
    for region in world.regions:
        # Real per-village production now (see recompute_region_resources) --
        # each village produces from its own local land instead of one
        # region-wide number split evenly across however many happen to
        # exist. Value what was actually taken in (delivered), not the raw
        # yield -- a village that idled its harvest for want of storage
        # shouldn't still be credited with the prosperity of bringing it in.
        _raw, delivered = recompute_region_resources(world, region, world.season)
        production_value[region.faction_idx] += _resource_bundle_value(delivered)

    # Herds run seasonally at the village now (see advance_herds) -- the old
    # once-a-year region-level path is gone, along with the meat spike it made.
    for fac_idx, value in advance_herds(world).items():
        production_value[fac_idx] += value

    for fac_idx, nation in enumerate(world.factions):
        res = nation.stats.setdefault("resources", {})
        _purge_phantom_pool(nation)   # see that function: unspendable stock
        _apply_spoilage(res)
        _clamp_to_storage(nation)
        _recompute_military(nation, world, fac_idx)

    advance_local_shipments(world)          # deliver anything in transit before it's needed
    _produce_fishing(world)                 # Fish lands directly at water-adjacent nodes
    advance_preservation(world)             # cure perishables before they spoil
    advance_production_chains(world)
    advance_settlement_production_chains(world)
    _record_gold(world, "minted", _gold_mark)   # Gold struck from Gold Ore
    _gold_mark = _gold_snapshot(world)
    run_local_logistics(world)              # dispatch new shipments from this turn's fresh stock
    advance_settlement_storage(world)
    consumption_value = advance_settlement_consumption(world)

    _update_prosperity(world, production_value, consumption_value)
    _grow_city_villages(world)

    # Autonomous trade (app/world/trade.py): move existing caravans first —
    # freeing a faction's trade "slot" on delivery — then let factions
    # dispatch new ones, so a freed slot can be reused the same turn.
    # Events are stashed on `world` for the UI to turn into player-facing
    # messages (see map_view.py) without resources.py needing to know
    # anything about panels/banners.
    # Realms discover each other by proximity (not just a shared border), so
    # diplomacy + foreign trade actually have partners to work with -- run
    # before the trade passes so a freshly-discovered neighbor can be a trade
    # candidate the same turn.
    from app.world import diplomacy
    diplomacy.run_proximity_contact(world)

    from app.world import trade
    trade.advance_trade_route_projects(world)   # land routes under construction
    events = trade.advance_caravans(world)
    events += trade.run_trade_ai(world)
    events += trade.run_trade_route_ai(world)   # AI proposes new routes
    world.trade_events = events
    _record_gold(world, "foreign trade", _gold_mark)
    _gold_mark = _gold_snapshot(world)

    # Phase 11: domestic cross-region settlement trade -- run after
    # run_local_logistics (above) has already had first crack at covering
    # need for free within a single region; this only ever moves in on
    # what's left over, and only between different regions (see the
    # module docstring in trade.py). Kept in its own event list rather
    # than merged into trade_events: these events describe one faction
    # trading with itself (a single faction_idx), not the seller_idx/
    # buyer_idx shape every foreign-trade event has, and map_view's
    # _report_trade_events reads that shape unconditionally.
    world.regional_trade_events = (trade.advance_regional_shipments(world)
                                   + trade.run_regional_trade(world)
                                   + trade.run_sell_to_city(world))
    _record_gold(world, "domestic trade", _gold_mark)
    _gold_mark = _gold_snapshot(world)

    # Player/AI-built settlements + their connecting roads
    # (app/world/construction.py).
    from app.world import construction
    construction.advance_projects(world)
    construction.advance_shipyard_projects(world)
    construction.advance_granary_projects(world)     # legacy, pre-tier saves
    construction.advance_warehouse_projects(world)   # legacy, pre-tier saves
    construction.advance_storage_projects(world)
    construction.run_settlement_ai(world)
    construction.run_storage_ai(world)
    _record_gold(world, "construction", _gold_mark)
    _gold_mark = _gold_snapshot(world)

    # Progressive expansion: claims-in-progress on UNCLAIMED land
    # (app/world/expansion.py).
    from app.world import expansion
    expansion.advance_claims(world)
    expansion.run_commander_ai(world)   # walk AI commanders to the frontier
    expansion.run_expansion_ai(world)
    expansion.ensure_interregion_roads(world)
    _record_gold(world, "expansion", _gold_mark)
    _gold_mark = _gold_snapshot(world)

    # Commanders: walk any active move order, count down ship construction
    # (app/world/commander.py) — before vision.recompute so this turn's
    # movement is reflected in this turn's fog reveal, not one turn late.
    from app.world import commander
    commander.advance_commanders(world)
    # Successors take the field (see kill_commander); stashed for the UI.
    world.commander_successions = commander.advance_commander_succession(world)

    # Cartographers survey a little further before the fog is recomputed, so
    # this turn's work shows up this turn rather than one turn late.
    advance_cartographers(world)

    # Fog of war: reveal whatever's now in range as territory changes hands
    # (app/world/vision.py).
    from app.world import vision
    vision.recompute(world)

    # Close the ledger. Anything that moved coin outside the bracketed phases
    # lands in "other" rather than silently vanishing, so the breakdown always
    # reconciles to the real total change -- if "other" ever grows large,
    # that's a genuine signal there's a gold flow worth naming.
    _record_gold(world, "other", _gold_mark)
    _close_gold_ledger(world)
