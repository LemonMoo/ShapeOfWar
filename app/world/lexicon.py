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
# Beyond hue/mil/eco/trait, each species carries battlefield + economic traits
# (see _SPECIES_TRAIT_DEFAULTS below for the full key list and what each does).
# Every species is deliberately given a real drawback alongside its strength so
# none is strictly best: Dwarves are tanky but slow, Elves quick but frail,
# Goblins evasive but fragile, Orcs hit hardest but field no cavalry at all,
# and Humans trade the lot for a purely economic edge. `mil`/`eco` above are
# the STRATEGIC layer (faction stats); these are the TACTICAL one (individual
# soldiers in a battle), and they stack.
# The multipliers below started as TUNED NUMBERS, not guesses: they came out of
# a round-robin tournament (every species vs every other, both sides played) run
# against this exact battle sim. The first, intuitive pass -- +30% damage for
# Orcs, +30% HP for Dwarves and so on -- produced a 74% win-rate spread (Orcs
# 88%, Goblins 14%), because HP/damage dominate this sim while movement speed
# barely registers.
#
# THEY ARE NO LONGER BALANCED, and this comment used to claim otherwise (the
# old "42% to 58%" line was already stale before any recent change: the spread
# measured 64% even then). Latest tournament run, harness self-checked -- same
# species on both sides wins 52%, so no positional bias:
#
# the Goblin dodge/cooldown pair below at .18/.97 measured a 25% and a 28%
# spread across two separate seed batches -- the tightest this roster has ever
# come. Two forces pull against each other and roughly cancel: long archer
# range punishes any army crossing open ground, while the reworked cavalry
# charge -- faster, harder, splashing damage across whatever line it hits --
# pays a roster back for keeping horse.
#
# MEASUREMENT CAVEAT, learned the hard way: individual matchups here are
# knife-edge and resolve almost deterministically, so a species' win rate can
# swing 20+ points between seed batches while the overall SPREAD stays stable.
# Measured directly on this very setting: Goblins came out at 62% in one batch
# and 38% in the other. Trust the spread, sample plenty of rounds, and never
# tune against a single run.
#
# The alternative considered was .18/.88 -- a far more VISIBLE buff (+12%
# attack speed rather than +3%), but it measured a 41% spread with Goblins
# alone on 79%. Tightest balance was chosen over the bigger-feeling number.
# Re-run the tournament if you touch any of these.
SPECIES = {
    # Purely economic edge on paper, so it needs *some* melee identity or it
    # loses every fight by default: disciplined drilled ranks get more out of a
    # shield than anyone else.
    "Humans":  {"hue": 45,  "mil": +2,  "eco": +6,  "trait": "adaptable realm-builders",
                "trade_gold_bonus": 0.15, "block_chance_mult": 1.25},
    # Quick and deadly, but lightly armoured. No cavalry -- elves fight as
    # archers, and their whole Cavalry share becomes more of them.
    "Elves":   {"hue": 160, "mil": -8,  "eco": +14, "trait": "ancient forest sages",
                "unit_cooldown_mult": 0.85, "unit_speed_mult": 1.15,
                "unit_hp_mult": 0.90, "no_cavalry": True,
                "cavalry_becomes": "archers"},
    # Stout and hard to kill, but methodical -- they march AND swing slower.
    # (Slow feet alone were no drawback at all; the slower swing is the real one.)
    "Dwarves": {"hue": 30,  "mil": +10, "eco": +10, "trait": "mountain-forged smiths",
                "unit_hp_mult": 1.20, "unit_speed_mult": 0.92,
                "unit_cooldown_mult": 1.08},
    # Biggest, hardest-hitting bodies on the field and no cavalry at all. Note
    # that losing cavalry is not itself a cost here (their share becomes more
    # Swordsmen, who are tankier and carry shields) -- the real counterweight is
    # that oversized weapons and a loose line get far less out of a shield.
    # +15% HP and +20% speed are COMPENSATION, measured not guessed: with no
    # cavalry and the fewest archers of anyone, orcs have to cross the whole
    # field on foot under fire, and doubling archer range made that walk twice
    # as costly. Bigger bodies that close faster is the direct counter, and it
    # fits what they already are. Sweeps: as they stood they won 44% of their
    # matchups (0% vs both archer rosters); +15% HP alone took them to 72% but
    # still lost to Elves 88% of the time; this pair lands them at 84% with an
    # even split against Elves.
    "Orcs":    {"hue": 95,  "mil": +16, "eco": -8,  "trait": "warband raiders",
                "unit_damage_mult": 1.18, "swordsman_size_mult": 1.30,
                "unit_hp_mult": 1.22, "unit_speed_mult": 1.20,
                "block_chance_mult": 0.72, "no_cavalry": True},
    # Fast and slippery -- a quarter of all blows miss them entirely -- and
    # they swing quicker than anyone, but they are the frailest thing on the
    # field. No cavalry either: goblins raid on foot. Unlike the Orcs, who pour
    # that share entirely into more Swordsmen, goblins split it evenly between
    # Swordsmen and Archers -- skirmishers, not a shield wall. The dodge and
    # attack-speed numbers are compensation for having measured as the weakest
    # species after the cavalry rework.
    "Goblins": {"hue": 75,  "mil": -4,  "eco": -6,  "trait": "cunning scavengers",
                "unit_speed_mult": 1.15, "unit_hp_mult": 0.85,
                "unit_cooldown_mult": 0.97,
                "dodge_chance": 0.18, "no_cavalry": True,
                "cavalry_becomes": "split"},
}

# Every species trait, with the "no modifier" value each defaults to. Anything
# without an entry in SPECIES above (notably the neutral Wildland Garrison,
# which has no species at all) falls through to these and fights at the plain
# UNIT_TYPES baseline.
_SPECIES_TRAIT_DEFAULTS = {
    "unit_hp_mult": 1.0,        # scales each soldier's max HP
    "unit_damage_mult": 1.0,    # scales the damage each hit deals
    "unit_speed_mult": 1.0,     # scales movement speed across the battlefield
    "unit_cooldown_mult": 1.0,  # scales the gap between attacks (<1 = attacks faster)
    "swordsman_size_mult": 1.0, # scales Swordsmen's drawn/collision radius only
    "block_chance_mult": 1.0,   # scales the shield's frontal block chance
    "dodge_chance": 0.0,        # chance (0..1) to evade an incoming hit entirely
    "no_cavalry": False,        # True = this species fields no Cavalry at all
    "cavalry_becomes": "swordsmen",   # where a no_cavalry species' Cavalry share goes:
                                       # "swordsmen" (all of it), "archers" (all of it),
                                       # or "split" (evenly between the two). Either way
                                       # the species brings the same headcount to the field
    "trade_gold_bonus": 0.0,    # extra fraction of Gold received on a foreign sale
}


def species_traits(species):
    """Every trait for `species`, with unmodified defaults filled in -- the one
    accessor combat/trade code should use, so an unknown or absent species
    (e.g. a wildland garrison) is always safe and simply baseline."""
    spec = SPECIES.get(species, {})
    return {key: spec.get(key, default)
            for key, default in _SPECIES_TRAIT_DEFAULTS.items()}


def species_trait_summary(species):
    """Player-facing ["+30% ...", "-10% ..."] bullets describing what a species
    actually does differently, generated from the real numbers above rather
    than hand-written prose that could drift out of sync. Shared by the New
    Game screen and the Compendium so both always agree."""
    t = species_traits(species)
    out = []

    def pct(mult, label, higher_is_better=True):
        delta = round((mult - 1.0) * 100)
        if not delta:
            return
        out.append(f"{'+' if delta > 0 else ''}{delta}% {label}")

    pct(t["unit_hp_mult"], "troop HP")
    pct(t["unit_damage_mult"], "damage per hit")
    pct(t["unit_speed_mult"], "movement speed")
    # Cooldown is inverted: less time between swings = faster attacks.
    cd = round((1.0 - t["unit_cooldown_mult"]) * 100)
    if cd:
        out.append(f"{'+' if cd > 0 else ''}{cd}% attack speed")
    blk = round((t["block_chance_mult"] - 1.0) * 100)
    if blk:
        out.append(f"{'+' if blk > 0 else ''}{blk}% shield block chance")
    if t["dodge_chance"]:
        out.append(f"{round(t['dodge_chance'] * 100)}% chance to dodge any hit")
    pct(t["swordsman_size_mult"], "larger Swordsmen")
    if t["no_cavalry"]:
        becomes = {"split": "that share splits evenly into Swordsmen and Archers",
                   "archers": "that share becomes Archers"}.get(
                       t["cavalry_becomes"], "that share becomes Swordsmen")
        out.append(f"fields no Cavalry ({becomes})")
    if t["trade_gold_bonus"]:
        out.append(f"+{round(t['trade_gold_bonus'] * 100)}% Gold from foreign sales")
    return out

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
