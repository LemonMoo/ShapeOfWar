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
                                path_transit_cells)

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
    "Cotton":  {"edible": False},    # the one non-edible Crop -- a fiber, not a food
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

for _name, _spec in RESOURCES.items():
    _spec.update(_CATEGORY_PROPERTY_DEFAULTS[_spec["category"]])
    _spec.update(_PROPERTY_OVERRIDES.get(_name, {}))
    _spec["spoil_rate"] = _SPOIL_RATE[_name]
del _name, _spec

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
    "Meat":    [{"inputs": ["Cattle"], "slaughter": True},
               {"inputs": ["Sheep"], "slaughter": True},
               {"inputs": ["Goats"], "slaughter": True},
               {"inputs": ["Pigs"], "slaughter": True},
               {"inputs": ["Horses"], "slaughter": True}],   # Butcher -- any Livestock, always slaughtered
    "Milk":    [{"inputs": ["Cattle"], "byproduct": True},
               {"inputs": ["Sheep"], "byproduct": True},
               {"inputs": ["Goats"], "byproduct": True}],   # Dairy -- milked from a live animal, never slaughtered
    "Cheese":  [{"inputs": ["Milk"]}],                   # Creamery
    "Eggs":    [{"inputs": ["Chickens"]}],               # Henhouse
    "Honey":   [{"inputs": ["Bees"]}],                   # Apiary
    "Smoked Fish": [{"inputs": ["Fish"]}],               # Smokehouse -- cured for storage, same
                                                          # 1:1 shape as Flour->Bread
    "Wool":    [{"inputs": ["Sheep"], "byproduct": True}],   # Shearing Shed -- sheared from a live sheep
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
    range)."""
    biome_counts = getattr(region, "biome_counts", {})
    climate = getattr(region, "dominant_climate", "temperate")
    fertility_frac = region.stats.get("fertility", 50) / 100.0

    result = {}
    for biome, cell_count in biome_counts.items():
        for crop, share in _CROP_SHARES_BY_BIOME.get(biome, {}).items():
            if not is_harvest_season(crop, season):
                continue
            fert_w = RESOURCE_SPAWN[crop]["fertility_weight"]
            fertility_mult = 1.0 + fert_w * (fertility_frac - 0.5)
            amount = (BASE_CROP_YIELD_PER_CELL * cell_count * share
                     * climate_affinity(crop, climate) * fertility_mult)
            amount = round(amount)
            if amount:
                result[crop] = result.get(crop, 0) + amount
    return result


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

_RAW_YIELD_OVERRIDE = {"Firewood": FIREWOOD_YIELD_PER_CELL}


def _raw_yield_per_cell(resource):
    """Per-cell base output for a raw Forestry/Mining resource: a per-resource
    override (only Firewood, kept high for survival) else the category base."""
    over = _RAW_YIELD_OVERRIDE.get(resource)
    if over is not None:
        return over
    return (BASE_FORESTRY_YIELD_PER_CELL
            if RESOURCES[resource]["category"] == "Forestry"
            else BASE_MINING_YIELD_PER_CELL)


def compute_industry_yield(region, season):
    """This region's Forestry/Mining production -- the industrial-output
    counterpart to compute_crop_yield just above, sharing its exact
    formula shape (see that function's docstring), just without any
    harvest-season gating (see the section note above for why). Per-resource
    base rates (see _raw_yield_per_cell) -- structural wood and mining are cut
    hard as durable, sink-less storage-cloggers; Firewood stays high because
    it's survival-critical."""
    biome_counts = getattr(region, "biome_counts", {})
    climate = getattr(region, "dominant_climate", "temperate")
    fertility_frac = region.stats.get("fertility", 50) / 100.0

    result = {}
    for biome, cell_count in biome_counts.items():
        for resource, share in _INDUSTRY_SHARES_BY_BIOME.get(biome, {}).items():
            fert_w = RESOURCE_SPAWN[resource]["fertility_weight"]
            fertility_mult = 1.0 + fert_w * (fertility_frac - 0.5)
            base = _raw_yield_per_cell(resource)
            amount = (base * cell_count * share
                     * climate_affinity(resource, climate) * fertility_mult)
            amount = round(amount)
            if amount:
                result[resource] = result.get(resource, 0) + amount
    return result


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
    for node in list(world.settlements) + list(world.villages):
        yield_amt = getattr(node, "fish_yield", None)
        if yield_amt is None:
            yield_amt = _node_fish_yield(world, node.pos)
            node.fish_yield = yield_amt
        if yield_amt <= 0:
            continue
        if not hasattr(node, "resources"):
            node.resources = {}
        node.resources["Fish"] = node.resources.get("Fish", 0) + yield_amt


def village_projected_annual_yield(world, village):
    """{resource: amount} this Village can expect to receive over a full
    year (len(SEASONS) * TURNS_PER_SEASON turns) from its region's
    production -- real numbers, not the flavor farm_output stat (see the
    Village class). Crops only count during their own Harvest season (see
    GROWTH_CYCLE/compute_crop_yield); Forestry/Mining are continuous,
    every turn, all year (see compute_industry_yield). Both are actually
    computed at the REGION level and split evenly across every Village the
    region has (see _route_farm_production), so this is specifically this
    village's own share, not the region's raw total -- a region with more
    villages means a smaller individual share of the same regional yield,
    not a bigger one."""
    region = world.regions[village.region_id]
    n_targets = max(1, len(getattr(region, "villages", [])))
    annual = defaultdict(float)
    for season in SEASONS:
        for crop, amount in compute_crop_yield(region, season).items():
            annual[crop] += amount * TURNS_PER_SEASON
    # No season gating for Forestry/Mining -- one season's worth already
    # represents every season, so just scale by the full year's turn count.
    for resource, amount in compute_industry_yield(region, world.season).items():
        annual[resource] += amount * TURNS_PER_SEASON * len(SEASONS)
    result = {r: round(a / n_targets) for r, a in annual.items() if round(a / n_targets) > 0}
    # Fish doesn't go through the region-level split above at all (see
    # _produce_fishing) -- it's this village's own adjacency, not a shared
    # regional pool, so it's added directly rather than divided by n_targets.
    fish = _node_fish_yield(world, village.pos)
    if fish:
        result["Fish"] = result.get("Fish", 0) + fish * YEAR_LENGTH_TURNS
    return result


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
STARTING_LIVESTOCK_HEAD = 20


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


def _ensure_region_livestock(region):
    """Lazily seed a starting herd (STARTING_LIVESTOCK_HEAD, capped at
    capacity) for every Livestock type this region's land can support but
    isn't tracking yet -- the same getattr-and-backfill treatment every
    other schema addition in this codebase gets, so an old save (predating
    `livestock` existing on Region at all) or a region advance_livestock
    hasn't reached before picks up sane defaults instead of a missing
    key."""
    if not hasattr(region, "livestock"):
        region.livestock = {}
    for animal in _LIVESTOCK:
        if animal in region.livestock:
            continue
        capacity = _livestock_capacity(region, animal)
        if capacity > 0:
            region.livestock[animal] = min(STARTING_LIVESTOCK_HEAD, capacity)
    return region.livestock


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


def advance_livestock(world):
    """Called once a year (see _is_new_year) from advance_turn: grow/shrink
    every claimed region's Livestock populations via births, natural
    deaths, and slaughter (LIVESTOCK_DYNAMICS), and route that year's
    Wool/Milk/Meat/Leather/Eggs/Honey straight to the region's own
    settlement(s) (see _route_farm_production, Phase 9) -- every
    one of those products lives in settlement storage now, not the
    national pool. Returns {faction_idx: gold-value produced} (not the raw
    amounts, which already went straight to storage) purely so
    advance_turn can still fold it into production_value for the health/
    prosperity calc -- a no-op {} on every turn but the first of the
    year, since population genuinely persists on the region between calls
    rather than being recomputed from scratch like a Crop's stage is."""
    value_by_fac = defaultdict(float)
    if not _is_new_year(world.turn):
        return value_by_fac

    for region in world.regions:
        if region.faction_idx < 0:
            continue
        livestock = _ensure_region_livestock(region)
        year_products = defaultdict(int)

        for animal in list(livestock.keys()):
            population = livestock[animal]
            spec = LIVESTOCK_DYNAMICS[animal]
            births = round(population * spec["birth_rate"])
            deaths = round(population * spec["death_rate"])
            slaughtered = min(round(population * spec["slaughter_rate"]), population)
            capacity = _livestock_capacity(region, animal)
            new_population = max(0, population + births - deaths - slaughtered)
            livestock[animal] = min(new_population, capacity) if capacity else new_population

            for resource, product in spec["products"].items():
                base = population if product["source"] == "population" else slaughtered
                amount = round(base * product["per_head"])
                if amount:
                    year_products[resource] += amount

        _route_farm_production(world, region, year_products)
        value_by_fac[region.faction_idx] += _resource_bundle_value(year_products)

    return value_by_fac


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

    res = getattr(node, "resources", None)
    if res:
        capacity = _node_storage_capacity(node)
        if capacity and sum(res.values()) > capacity:
            alerts.append({"kind": "storage_overflow", "severity": "warning",
                           "message": f"{node.name}'s storage is full — excess goods are spoiling"})
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

# Rough placeholders, not balance-tuned (same caveat as every quantity in
# this file).
SETTLEMENT_STORAGE_BASE = {"city": 3000, "castle": 2000, "town": 1200}
_DEFAULT_SETTLEMENT_STORAGE_BASE = 1200
GRANARY_STORAGE_BONUS = 2000
WAREHOUSE_STORAGE_BONUS = 1000
VILLAGE_STORAGE_BASE = 1800   # a village's own storage (Phase 10) -- smaller
                              # than a Settlement's, and no Granary/Warehouse
                              # of its own to expand it, but has to be large
                              # enough to actually bank a harvest: a Crop
                              # only produces during its own ~TURNS_PER_SEASON
                              # -turn Harvest window, all at once, then
                              # nothing again for the rest of the year -- at
                              # the old 600 cap, a real harvest routinely
                              # ran 2-2.7x over budget for the entire season,
                              # so most of it was destroyed by overflow
                              # spoilage before Local Logistics ever got a
                              # chance to move it out to the Settlements
                              # depending on it (raised from 600, which was
                              # sized before Crops/Food Products were real,
                              # season-gated production at all)

OVERFLOW_SPOILAGE_MULTIPLIER = 5.0   # extra decay speed applied on top of a
                                     # resource's own spoil_rate while over cap
MAX_OVERFLOW_LOSS_FRACTION = 0.75   # even the worst case (badly overflowing,
                                     # fast-spoiling) keeps a sliver of grace
OVERFLOW_MIN_RATE = 0.10            # even a spoil_rate-0 good leaks away some
                                     # while overflowing -- no shelter, no floor space


def settlement_storage_capacity(settlement):
    """Total shared-space budget this settlement's storage has -- every
    resource in _SETTLEMENT_STORAGE_RESOURCES draws from the same pool,
    not an independent cap per resource. Granary/Warehouse (see
    construction.py) each add a flat bonus on top of the settlement
    kind's base."""
    base = SETTLEMENT_STORAGE_BASE.get(settlement.kind, _DEFAULT_SETTLEMENT_STORAGE_BASE)
    if getattr(settlement, "has_granary", False):
        base += GRANARY_STORAGE_BONUS
    if getattr(settlement, "has_warehouse", False):
        base += WAREHOUSE_STORAGE_BONUS
    return base


def _node_storage_capacity(node):
    """Same idea as settlement_storage_capacity, but for whichever kind of
    storage-owning node this actually is -- a Village (flat
    VILLAGE_STORAGE_BASE, no Granary/Warehouse) or a Settlement
    (settlement_storage_capacity). Dispatches on hasattr("kind") rather
    than isinstance so it works without importing Settlement/Village
    here."""
    if hasattr(node, "kind"):
        return settlement_storage_capacity(node)
    return VILLAGE_STORAGE_BASE


def _route_farm_production(world, region, resource_amounts):
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
    game-only edge case). Doesn't check capacity on the way in --
    overflow is handled afterward by advance_local_storage's grace-period
    decay, not by rejecting delivery."""
    if not resource_amounts:
        return
    vids = list(getattr(region, "villages", []))
    targets = [("village", vid) for vid in vids]
    if not targets:
        sids = list(getattr(region, "meta_settlements", []))
        targets = [("settlement", sid) for sid in sids]
    if not targets:
        nation = world.factions[region.faction_idx]
        fallback = nation.meta.get("settlements", [])
        if not fallback:
            return
        targets = [("settlement", fallback[0])]
    n = len(targets)
    for kind, node_id in targets:
        node = world.villages[node_id] if kind == "village" else world.settlements[node_id]
        if not hasattr(node, "resources"):
            node.resources = {}
        for resource, amount in resource_amounts.items():
            share = round(amount / n)
            if share:
                node.resources[resource] = node.resources.get(resource, 0) + share


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
                break


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

    capacity = _node_storage_capacity(node)
    total = sum(res.values())
    if total <= capacity:
        return
    overage_frac = (total - capacity) / total
    for resource in list(res.keys()):
        if res[resource] <= 0 or resource == "Gold":
            continue   # Gold is minted currency, not a perishable good --
                        # it still occupies vault space (counts toward
                        # `total` above) but never decays just because the
                        # granary is overflowing with grain or timber
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
_LOCAL_SHIPMENT_PRIORITY = (list(_FOOD_SOURCES) + ["Firewood", "Clothes"]
                           + sorted(_SETTLEMENT_STORAGE_RESOURCES - set(_FOOD_SOURCES)
                                   - {"Firewood", "Clothes"}))


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
    and dispatch a LocalShipment for the first match found per node, same
    greedy-first-match style as trade.run_trade_ai. Fully automatic --
    no player or AI decision involved, matching how the rest of this
    economy already works."""
    world._local_path_budget = LOCAL_PATH_BUDGET_PER_TURN
    for region in world.regions:
        if region.faction_idx < 0:
            continue
        nodes = _region_logistics_nodes(world, region)
        if len(nodes) < 2:
            continue
        season = world.season
        needs_by_node = {(kind, node.id): settlement_needs(node, season) for kind, node in nodes}

        for kind, node in nodes:
            if _active_outgoing_shipments(world, kind, node.id) >= MAX_ACTIVE_LOCAL_SHIPMENTS_PER_NODE:
                continue
            own_needs = needs_by_node[(kind, node.id)]
            dispatched = False
            for resource in _LOCAL_SHIPMENT_PRIORITY:
                surplus = _node_surplus(node, resource, own_needs)
                if surplus < LOCAL_SHIPMENT_MIN_QUANTITY:
                    continue
                for other_kind, other in nodes:
                    if other is node:
                        continue
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

    levy = adults * MOBILIZATION_RATE
    armed = min(levy, weapons)
    militia = levy - armed
    strength = armed + militia * MILITIA_WEIGHT
    if armed > 0:
        strength *= 1.0 + SHIELD_BONUS * min(armed, shields) / armed
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
        population, adults, children, max_population = _roll_population(random, "village")
        prosperity = seed_prosperity()

        v = Village(len(world.villages), region_id, st.faction_idx,
                   namer("village", species), (x, y), farm,
                   population, adults, children, prosperity, max_population)
        world.villages.append(v)
        region.villages.append(v.id)
        world.roads_by_region.setdefault(region_id, []).append((st.pos, v.pos, "dirt"))
        _connect_new_village_to_region(world, region, v)

        st.villages_spawned += 1
        st.prosperity = 0.0


def _connect_new_village_to_region(world, region, new_village):
    """A newly city-grown village also gets connected directly to nearby
    villages already in its own region -- not just back to the City that
    founded it -- so a region ends up genuinely interconnected (better
    trading/logistics reach) instead of a pure hub-and-spoke back to one
    city. Straight-line dirt segments, same instant-connection style the
    city->village link right above already uses, not the gradual
    RoadProject/pathfinding machinery construction.py's other roads go
    through. Picks the VILLAGE_MESH_MAX_LINKS closest existing villages
    within VILLAGE_MESH_LINK_RADIUS, not every village in the region
    regardless of distance, so one spawn event can't blanket a large,
    already-crowded region in new links."""
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
        segs.append((new_village.pos, other.pos, "dirt"))


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


def _crop_yield_at_own_harvest(region):
    """Every Crop's yield computed at ITS OWN harvest season, regardless
    of the world's current season -- summed across all 4 calls to
    compute_crop_yield (each Crop only ever contributes during its own
    single Harvest season out of the four, so nothing double-counts).
    Used only for seeding a fresh game's starting stockpile (see
    seed_initial_stockpiles): world.season is always "Spring" at
    generation time (see generate_world), and no Crop's GROWTH_CYCLE
    actually harvests in Spring -- every single one is Summer or Autumn
    -- so seeding off the live season the normal way (compute_region_yield)
    always seeded exactly zero starting Crops/Food Products, no matter
    what the map looked like. That's a real bug, not a balance choice: a
    fresh settlement/village had nothing to eat at all until the world's
    season clock happened to reach whichever season its local crops
    harvest in -- up to 3 seasons (worst case ~75 turns) away -- which is
    what was actually driving population collapse in the game's opening
    stretch, not a per-capita rate problem."""
    result = {}
    for season in SEASONS:
        for crop, amount in compute_crop_yield(region, season).items():
            result[crop] = result.get(crop, 0) + amount
    return result


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
        nation = world.factions[region.faction_idx]
        # Crops use their OWN harvest season (see _crop_yield_at_own_harvest
        # for why -- world.season at generation time is always "Spring",
        # which no Crop actually harvests in); Forestry/Mining are
        # continuous/season-agnostic, so the live season is fine for them.
        region.resources = dict(_crop_yield_at_own_harvest(region))
        for resource, amount in compute_industry_yield(region, world.season).items():
            region.resources[resource] = region.resources.get(resource, 0) + amount
        settlement_bound = {r: a for r, a in region.resources.items()
                            if r in _SETTLEMENT_STORAGE_RESOURCES}
        faction_bound = {r: a for r, a in region.resources.items()
                         if r not in _SETTLEMENT_STORAGE_RESOURCES}
        _route_farm_production(
            world, region, {r: a * _STARTING_STOCKPILE_TURNS for r, a in settlement_bound.items()})
        res = nation.stats["resources"]
        for resource, amount in faction_bound.items():
            res[resource] = res.get(resource, 0) + amount * _STARTING_STOCKPILE_TURNS
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


def advance_turn(world):
    """The turn loop: cycle the season, recompute every region's yield for
    it (including Crops, see compute_region_yield -- production lands at
    the region's own Villages first, Phase 10), grow/harvest Livestock
    once a year (advance_livestock), spoil perishables, add production to
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

    production = defaultdict(lambda: defaultdict(int))
    production_value = defaultdict(float)
    for region in world.regions:
        region.resources = compute_region_yield(region, world.season)
        settlement_bound = {r: a for r, a in region.resources.items()
                            if r in _SETTLEMENT_STORAGE_RESOURCES}
        faction_bound = {r: a for r, a in region.resources.items()
                         if r not in _SETTLEMENT_STORAGE_RESOURCES}
        _route_farm_production(world, region, settlement_bound)
        production_value[region.faction_idx] += _resource_bundle_value(settlement_bound)
        fac_res = production[region.faction_idx]
        for resource, amount in faction_bound.items():
            fac_res[resource] += amount

    for fac_idx, value in advance_livestock(world).items():
        production_value[fac_idx] += value

    for fac_idx, nation in enumerate(world.factions):
        res = nation.stats.setdefault("resources", {})
        _apply_spoilage(res)
        fac_production = production.get(fac_idx, {})
        for resource, amount in fac_production.items():
            res[resource] = int(res.get(resource, 0) + amount)
        production_value[fac_idx] += _resource_bundle_value(fac_production)
        _clamp_to_storage(nation)
        _recompute_military(nation, world, fac_idx)

    advance_local_shipments(world)          # deliver anything in transit before it's needed
    _produce_fishing(world)                 # Fish lands directly at water-adjacent nodes
    advance_production_chains(world)
    advance_settlement_production_chains(world)
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

    # Player/AI-built settlements + their connecting roads
    # (app/world/construction.py).
    from app.world import construction
    construction.advance_projects(world)
    construction.advance_shipyard_projects(world)
    construction.advance_granary_projects(world)
    construction.advance_warehouse_projects(world)
    construction.run_settlement_ai(world)
    construction.run_storage_ai(world)

    # Progressive expansion: claims-in-progress on UNCLAIMED land
    # (app/world/expansion.py).
    from app.world import expansion
    expansion.advance_claims(world)
    expansion.run_expansion_ai(world)
    expansion.ensure_interregion_roads(world)

    # Commanders: walk any active move order, count down ship construction
    # (app/world/commander.py) — before vision.recompute so this turn's
    # movement is reflected in this turn's fog reveal, not one turn late.
    from app.world import commander
    commander.advance_commanders(world)

    # Fog of war: reveal whatever's now in range as territory changes hands
    # (app/world/vision.py).
    from app.world import vision
    vision.recompute(world)
