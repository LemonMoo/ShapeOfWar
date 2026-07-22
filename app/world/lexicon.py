"""Fantasy species and faction-name generation.

SPECIES maps a species name to flavor + gameplay traits:
  hue        : base color hue (degrees) used to tint that species' factions
  mil / eco  : stat modifiers (military / economy)
  trait      : short descriptor shown in the UI

Every namer below is species-aware: factions, regions, settlements and
villages all draw their name components from word banks flavored for their
owning species (Elvish forests, Dwarven holds, Orcish warbands, Goblin
warrens, Human realms), so the name itself hints at who lives there.

Add or edit species freely; the generator picks from whatever is here. If a
species has no entry in one of the *_NAMES dicts below, it falls back to the
Human word bank so nothing crashes.
"""
SPECIES = {
    "Humans":  {"hue": 45,  "mil": +2,  "eco": +6,  "trait": "adaptable realm-builders"},
    "Elves":   {"hue": 160, "mil": -8,  "eco": +14, "trait": "ancient forest sages"},
    "Dwarves": {"hue": 30,  "mil": +10, "eco": +10, "trait": "mountain-forged smiths"},
    "Orcs":    {"hue": 95,  "mil": +16, "eco": -8,  "trait": "warband raiders"},
    "Goblins": {"hue": 75,  "mil": -4,  "eco": -6,  "trait": "cunning scavengers"},
}

# --- faction names: "<Adj> <Noun>" ------------------------------------------
_FACTION_NAMES = {
    "Humans": (
        ["Ashen", "Iron", "Golden", "Crimson", "Verdant", "Frost", "Storm",
         "Obsidian", "Radiant", "Hollow", "Thorned", "Gilded", "Pale",
         "Scarlet", "Ember", "Duskward", "Sunder", "Wintered", "Cobalt", "Umber"],
        ["Covenant", "Dominion", "Hegemony", "Reach", "Concord", "Legion",
         "Accord", "Imperium", "Coalition", "Clanhold", "Ascendancy", "Compact",
         "Marches", "Syndicate", "Enclave", "Protectorate", "Sovereignty",
         "Banner", "Throne", "Confluence"],
    ),
    "Elves": (
        ["Silver", "Moonlit", "Starlit", "Verdant", "Whispering", "Gilded",
         "Twilight", "Sylvan", "Emerald", "Evergreen", "Faelight", "Dawnwood",
         "Mistveil", "Ancient", "Highspire"],
        ["Grove", "Glade", "Spire", "Sanctuary", "Vale", "Bloom", "Canopy",
         "Circle", "Wardens", "Court", "Choir", "Weave", "Realm", "Council",
         "Enclave"],
    ),
    "Dwarves": (
        ["Iron", "Stone", "Deep", "Granite", "Forge", "Bronze", "Ember",
         "Anvil", "Grim", "Blackrock", "Ironclad", "Runed", "Underdeep",
         "Steel", "Hammerfell"],
        ["Hold", "Delve", "Bastion", "Forgehall", "Clanhold", "Vault",
         "Anvilworks", "Mine", "Stronghold", "Deephome", "Foundry", "Rampart",
         "Warren", "Keep", "Bulwark"],
    ),
    "Orcs": (
        ["Bloodfang", "Skull", "Iron", "Black", "Gore", "Savage", "Ashen",
         "Red", "Grim", "Broken", "Rotten", "War", "Fang", "Bone", "Doom"],
        ["Warband", "Horde", "Clan", "Warcamp", "Tribe", "Marauders",
         "Ravagers", "Fist", "Legion", "Warhost", "Stormers", "Raiders",
         "Warcry", "Butchers", "Wolfpack"],
    ),
    "Goblins": (
        ["Snaggle", "Rusty", "Mudd", "Grub", "Rat", "Scrap", "Warty", "Sneak",
         "Cracked", "Filthy", "Crooked", "Boggy", "Gnarled", "Slink", "Grimy"],
        ["Warren", "Scrapheap", "Burrow", "Gang", "Horde", "Tunnels",
         "Rabble", "Swarm", "Pit", "Midden", "Nest", "Mob", "Hovels",
         "Scuttle", "Den"],
    ),
}

# --- region names: "<Adj> <Feature>" ----------------------------------------
# Regions are generated map-wide before any faction/species claims them (see
# app/world/worldgen.py), so — unlike factions/settlements/villages below —
# there's no owning species yet to flavor the name with. One large, broad
# pool instead, drawing on many different fantasy traditions (high fantasy,
# Norse/saga, Gothic/dark fantasy, Arthurian/British Isles, desert and
# far-eastern flavor, Greco-Roman myth) rather than a single narrow well —
# with this many combinations, two regions landing on the same name is rare
# even across a very large, many-continent map.
_REGION_ADJ = [
    "Ashen", "Iron", "Golden", "Crimson", "Verdant", "Frost", "Storm",
    "Obsidian", "Radiant", "Hollow", "Thorned", "Gilded", "Pale", "Scarlet",
    "Ember", "Duskward", "Sundered", "Wintered", "Cobalt", "Umber", "Silver",
    "Moonlit", "Starlit", "Whispering", "Twilight", "Sylvan", "Emerald",
    "Evergreen", "Mistveil", "Ancient", "Granite", "Deep", "Bronze",
    "Blackrock", "Runed", "Weeping", "Forsaken", "Forgotten", "Sunken",
    "Drowned", "Withered", "Gloaming", "Nightshade", "Wyrmwood", "Fensworn",
    "Dunefire", "Jadewind", "Lotusfall", "Cloudreach", "Amber", "Ivory",
    "Jet", "Copper", "Rime", "Sable", "Titanfallen", "Fated", "Labyrinthine",
    "Elder", "Nameless", "Undying", "Silent", "Hidden", "Lonely", "Widowed",
    "Cursed", "Blessed", "Sacred", "Forbidden", "Endless", "Restless",
    "Winterbound", "Sunscorched", "Windswept", "Stormwrought", "Cinderlit",
    "Mossgrown", "Ironbound", "Wraithbound", "Bloodfang", "Bramblewood",
    "Ravenwood", "Ghostlit", "Emberlit", "Shadowbound", "Grimwald",
    "Frostbitten", "Sunwrought", "Starforged", "Bonewrought", "Thornveiled",
    "Duskbound", "Wyldborne", "Ironvale", "Moonshadow", "Fireforged",
]
_REGION_FEATURE = [
    "Vale", "Downs", "Moor", "Weald", "Fen", "Hollow", "Ridge", "Marsh",
    "Heath", "Glen", "Wold", "Reach", "Barrow", "Fell", "Combe", "Meadows",
    "Hills", "Bluffs", "Cross", "Hedge", "Glade", "Grove", "Wood", "Bower",
    "Thicket", "Brook", "Fernwood", "Willows", "Canopy", "Dell", "Shaft",
    "Vein", "Crag", "Cavern", "Tunnels", "Quarry", "Peak", "Mine", "Chasm",
    "Foothold", "Underhall", "Wastes", "Scar", "Ashfield", "Ruin", "Flats",
    "Blight", "Pit", "Gash", "Bonefield", "Mire", "Blackland", "Burrow",
    "Midden", "Warren", "Sinkhole", "Bog", "Scrapfield", "Ditch",
    "Muckland", "Undercroft", "Crevice", "Gulch", "Span", "March",
    "Steppe", "Delta", "Isle", "Cape", "Cove", "Bay", "Strand", "Shoal",
    "Cairn", "Tor", "Spire", "Aerie", "Roost", "Eyrie", "Mere", "Weir",
    "Furlong", "Hallow", "Sanctum", "Wyrmspine", "Frostreach", "Sunstead",
    "Starfall", "Wyldwood", "Emberfall", "Ashenmoor", "Ravenspire",
    "Wolfden", "Serpentmarsh", "Dragontooth", "Oraclemere", "Labyrinth",
    "Dunereach", "Mirage", "Jadewood", "Lotusmere", "Bambooglen",
    "Silkmere", "Cloudspire",
]
_REGION_QUALIFIERS = [
    "the Elder", "the Lesser", "the Forsaken", "the Forgotten",
    "the Sundered", "the Old", "the Hidden", "the Silent", "the Last",
    "the Nameless", "the Drowned", "the Undying", "the Restless",
    "the Unclaimed", "the Far",
]

# --- settlement names: "<Root><suffix>", suffix picked by settlement kind ---
_SETTLE_NAMES = {
    "Humans": (
        ["Karn", "Vel", "Thal", "Bren", "Ost", "Myr", "Dun", "Fal",
         "Grim", "Hale", "Ithil", "Corv", "Ashen", "Bright", "Stone",
         "Wolf", "Raven", "Ember", "Frost", "Gild"],
        {"city": ["haven", "spire", "gate", "reach", "hold", "crown", "port", "vast"],
         "castle": ["keep", "watch", "guard", "bastion", "fort", "wall", "aerie"],
         "town": ["stead", "ford", "mill", "brook", "field", "market",
                   "crossing", "hollow", "wick", "dale"],
         "village": ["ton", "by", "worth", "leigh", "combe", "end", "holt",
                     "thorpe", "wick", "bury"]},
    ),
    "Elves": (
        ["Sil", "Ela", "Thal", "Ain", "Lir", "Fae", "Mira", "Ithi", "Ely",
         "Sol", "Ala", "Ner", "Ysa", "Quel", "Aer"],
        {"city": ["dorei", "thil", "wynn", "lanor", "vale", "mere", "reth", "spire"],
         "castle": ["watch", "spire", "guard", "hollow", "aerie", "ward", "reach"],
         "town": ["glen", "brook", "wood", "vale", "hollow", "mere", "dell",
                   "shade", "leaf"],
         "village": ["leaf", "brook", "glen", "dell", "hollow", "wick",
                     "shade", "vale", "wood"]},
    ),
    "Dwarves": (
        ["Khaz", "Dur", "Bal", "Grum", "Thok", "Bron", "Fen", "Ur", "Dor",
         "Grim", "Bok", "Nar", "Thra", "Kor", "Mor"],
        {"city": ["akad", "bad", "hold", "grad", "forge", "delve", "haven"],
         "castle": ["keep", "watch", "guard", "bastion", "wall", "hold"],
         "town": ["ford", "mill", "hollow", "field", "stead", "hall", "vault"],
         "village": ["hollow", "dell", "hall", "burrow", "shaft", "worth"]},
    ),
    "Orcs": (
        ["Gor", "Skar", "Mog", "Uzk", "Nak", "Grish", "Bogrot", "Ugluk",
         "Zog", "Ghash", "Krug", "Snaga", "Thrak", "Vurg", "Mash"],
        {"city": ["gul", "grod", "zak", "durg", "krath", "moor"],
         "castle": ["fort", "gash", "spike", "hold", "camp", "wall"],
         "town": ["camp", "pit", "hovel", "field", "sty", "mudflat"],
         "village": ["camp", "sty", "pit", "hovel", "shanty", "warcamp"]},
    ),
    "Goblins": (
        ["Snag", "Grub", "Rat", "Mud", "Scrap", "Wart", "Boggle", "Nizz",
         "Skab", "Grimble", "Filth", "Sniv", "Crak", "Gnash", "Slop"],
        {"city": ["burg", "gutter", "town", "hive", "hovel"],
         "castle": ["den", "fort", "sty", "hole", "watch"],
         "town": ["ditch", "hollow", "midden", "burrow", "wallow"],
         "village": ["ditch", "hovel", "burrow", "wallow", "hole", "pit"]},
    ),
}


def make_region_namer(rng):
    """Return a function () -> unique '<Adj> <Feature>' region name. No
    species argument — regions are named map-wide before any faction has
    claimed them (see app/world/worldgen.py), so there's nothing to flavor
    the pick with yet; _REGION_ADJ/_REGION_FEATURE are one broad,
    tradition-spanning pool instead. If that combinatorial space (in the
    thousands) is ever actually exhausted, later names get a themed
    qualifier tacked on rather than a bare number."""
    used = set()

    def namer():
        for _ in range(300):
            name = f"{rng.choice(_REGION_ADJ)} {rng.choice(_REGION_FEATURE)}"
            if name not in used:
                used.add(name)
                return name
        for _ in range(300):
            name = (f"{rng.choice(_REGION_ADJ)} {rng.choice(_REGION_FEATURE)}, "
                    f"{rng.choice(_REGION_QUALIFIERS)}")
            if name not in used:
                used.add(name)
                return name
        # Practically unreachable outside a map with tens of thousands of
        # regions -- still no digits, just two qualifiers stacked together.
        name = (f"{rng.choice(_REGION_ADJ)} {rng.choice(_REGION_FEATURE)}, "
                f"{rng.choice(_REGION_QUALIFIERS)} and {rng.choice(_REGION_QUALIFIERS)}")
        used.add(name)
        return name

    return namer


def make_settlement_namer(rng):
    """Return a function (kind, species) -> unique name like 'Karnhaven' /
    'Duraforge' / 'Gorzak', drawn from that species' word bank (falls back
    to Human if unknown)."""
    used = set()

    def namer(kind, species="Humans"):
        roots, suffix_map = _SETTLE_NAMES.get(species, _SETTLE_NAMES["Humans"])
        suffixes = suffix_map.get(kind, suffix_map["town"])
        for _ in range(200):
            name = f"{rng.choice(roots)}{rng.choice(suffixes)}"
            if name not in used:
                used.add(name)
                return name
        name = f"{rng.choice(roots)}{rng.choice(suffixes)} {len(used)}"
        used.add(name)
        return name

    return namer


def make_faction_namer(rng):
    """Return a function (species) -> unique '<Adj> <Noun>' faction name,
    drawn from that species' word bank (falls back to Human if unknown)."""
    used = set()

    def namer(species="Humans"):
        adj, noun = _FACTION_NAMES.get(species, _FACTION_NAMES["Humans"])
        for _ in range(200):
            name = f"{rng.choice(adj)} {rng.choice(noun)}"
            if name not in used:
                used.add(name)
                return name
        # fallback if we somehow exhaust combinations
        name = f"{rng.choice(adj)} {rng.choice(noun)} {len(used)}"
        used.add(name)
        return name

    return namer
