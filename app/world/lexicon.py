"""Invented species and faction-name generation — nothing from the real world.

SPECIES maps a species name to flavor + gameplay traits:
  hue        : base color hue (degrees) used to tint that species' factions
  mil / eco  : stat modifiers (military / economy)
  trait      : short descriptor shown in the UI

Add or edit species freely; the generator picks from whatever is here.
"""
SPECIES = {
    "Sylvani":  {"hue": 110, "mil": -6,  "eco": +12, "trait": "forest-born weavers"},
    "Drakkan":  {"hue": 8,   "mil": +16, "eco": -4,  "trait": "ember-blooded raiders"},
    "Aquari":   {"hue": 195, "mil": +2,  "eco": +8,  "trait": "tide-singing seafolk"},
    "Umbrals":  {"hue": 275, "mil": +8,  "eco": +2,  "trait": "shadow-cloaked wanderers"},
    "Cindren":  {"hue": 32,  "mil": +10, "eco": -2,  "trait": "ash-forged smiths"},
    "Ferrox":   {"hue": 210, "mil": +12, "eco": +4,  "trait": "iron-carapaced legions"},
    "Lumenai":  {"hue": 52,  "mil": -2,  "eco": +14, "trait": "light-tending scholars"},
    "Gravenkin":{"hue": 150, "mil": +6,  "eco": +0,  "trait": "stone-bound highlanders"},
    "Vosk":     {"hue": 300, "mil": +14, "eco": -6,  "trait": "void-touched swarm"},
}

_ADJ = ["Ashen", "Iron", "Golden", "Crimson", "Verdant", "Frost", "Storm",
        "Obsidian", "Radiant", "Hollow", "Thorned", "Gilded", "Pale",
        "Scarlet", "Ember", "Duskward", "Sunder", "Wintered", "Cobalt", "Umber"]
_NOUN = ["Covenant", "Dominion", "Hegemony", "Reach", "Concord", "Legion",
         "Accord", "Imperium", "Coalition", "Clanhold", "Ascendancy", "Compact",
         "Marches", "Syndicate", "Enclave", "Protectorate", "Sovereignty",
         "Banner", "Throne", "Confluence"]


_FEATURE = ["Vale", "Downs", "Moor", "Weald", "Fen", "Hollow", "Ridge", "Marsh",
            "Heath", "Glen", "Wold", "Reach", "Barrow", "Fell", "Combe",
            "Meadows", "Hills", "Bluffs", "Cross", "Hedge"]


def make_county_namer(rng):
    """Return a function yielding unique '<Adj> <Feature>' county names."""
    used = set()

    def namer():
        for _ in range(200):
            name = f"{rng.choice(_ADJ)} {rng.choice(_FEATURE)}"
            if name not in used:
                used.add(name)
                return name
        name = f"{rng.choice(_ADJ)} {rng.choice(_FEATURE)} {len(used)}"
        used.add(name)
        return name

    return namer


_SETTLE_ROOT = ["Karn", "Vel", "Thal", "Bren", "Ost", "Myr", "Dun", "Fal",
                "Grim", "Hale", "Ithil", "Corv", "Ashen", "Bright", "Stone",
                "Wolf", "Raven", "Ember", "Frost", "Gild"]
_SETTLE_SUFFIX = {
    "city": ["haven", "spire", "gate", "reach", "hold", "crown", "port", "vast"],
    "castle": ["keep", "watch", "guard", "bastion", "fort", "wall", "aerie"],
    "town": ["stead", "ford", "mill", "brook", "field", "market", "crossing",
             "hollow", "wick", "dale"],
}


def make_settlement_namer(rng):
    """Return a function (kind) -> unique name like 'Karnhaven' / 'Grimkeep'."""
    used = set()

    def namer(kind):
        suffixes = _SETTLE_SUFFIX.get(kind, _SETTLE_SUFFIX["town"])
        for _ in range(200):
            name = f"{rng.choice(_SETTLE_ROOT)}{rng.choice(suffixes)}"
            if name not in used:
                used.add(name)
                return name
        name = f"{rng.choice(_SETTLE_ROOT)}{rng.choice(suffixes)} {len(used)}"
        used.add(name)
        return name

    return namer


def make_faction_namer(rng):
    """Return a function that yields unique '<Adj> <Noun>' faction names."""
    used = set()

    def namer():
        for _ in range(200):
            name = f"{rng.choice(_ADJ)} {rng.choice(_NOUN)}"
            if name not in used:
                used.add(name)
                return name
        # fallback if we somehow exhaust combinations
        name = f"{rng.choice(_ADJ)} {rng.choice(_NOUN)} {len(used)}"
        used.add(name)
        return name

    return namer
