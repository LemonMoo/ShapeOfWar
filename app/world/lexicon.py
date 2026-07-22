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
_REGION_NAMES = {
    "Humans": (
        _FACTION_NAMES["Humans"][0],
        ["Vale", "Downs", "Moor", "Weald", "Fen", "Hollow", "Ridge", "Marsh",
         "Heath", "Glen", "Wold", "Reach", "Barrow", "Fell", "Combe",
         "Meadows", "Hills", "Bluffs", "Cross", "Hedge"],
    ),
    "Elves": (
        _FACTION_NAMES["Elves"][0],
        ["Glade", "Grove", "Hollow", "Vale", "Wood", "Bower", "Thicket",
         "Glen", "Meadow", "Brook", "Fernwood", "Moonwood", "Willows",
         "Canopy", "Dell"],
    ),
    "Dwarves": (
        _FACTION_NAMES["Dwarves"][0],
        ["Deep", "Shaft", "Vein", "Crag", "Ridge", "Cavern", "Tunnels",
         "Quarry", "Peak", "Hollow", "Mine", "Chasm", "Foothold", "Bluff",
         "Underhall"],
    ),
    "Orcs": (
        _FACTION_NAMES["Orcs"][0],
        ["Wastes", "Scar", "Ashfield", "Ruin", "Flats", "Blight", "Warcamp",
         "Pit", "Gash", "Crag", "Bonefield", "Mire", "Blackland", "Ridge",
         "Hollow"],
    ),
    "Goblins": (
        _FACTION_NAMES["Goblins"][0],
        ["Burrow", "Midden", "Warren", "Tunnels", "Sinkhole", "Bog",
         "Scrapfield", "Ditch", "Hollow", "Thicket", "Muckland", "Pit",
         "Undercroft", "Crevice", "Gulch"],
    ),
}

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
    """Return a function (species) -> unique '<Adj> <Feature>' region name,
    drawn from that species' word bank (falls back to Human if unknown)."""
    used = set()

    def namer(species="Humans"):
        adj, feature = _REGION_NAMES.get(species, _REGION_NAMES["Humans"])
        for _ in range(200):
            name = f"{rng.choice(adj)} {rng.choice(feature)}"
            if name not in used:
                used.add(name)
                return name
        name = f"{rng.choice(adj)} {rng.choice(feature)} {len(used)}"
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
