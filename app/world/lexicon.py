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
    # The Standard Bearer is the rank-and-file form of the Marshal: Humans'
    # whole identity is that the line is worth more than the soldiers in it,
    # and their commander was already the only one whose value is what he does
    # for everyone else. A handful of banners spreads a weaker version of that
    # across the field instead of concentrating it on one body that can die.
    "Humans":  {"hue": 45,  "mil": +2,  "eco": +6,  "trait": "adaptable realm-builders",
                "trade_gold_bonus": 0.15, "block_chance_mult": 1.25,
                "specials": ({"unit": "bannerman", "of_swordsmen": 0.08,
                              "bonus": 0.04},)},
    # Quick and deadly, but lightly armoured. No cavalry -- elves fight as
    # archers, and their whole Cavalry share becomes more of them.
    # Attack speed cut 0.85 -> 0.90: an all-archer roster that never has to
    # close was measuring as the clear outlier (92% of its matchups), and the
    # fast draw is where that came from, not their evasion -- elves have no
    # dodge at all.
    # The Bladesinger is paid for ENTIRELY out of the bows, with no outright
    # bonus -- the only special on the roster funded that way, because Elves
    # lead the roster and theirs is the one signature unit that has no business
    # making them stronger. At a tenth of the bows it measured as the biggest
    # buff on the table (60% of matchups to 85%): what being closed on costs an
    # all-archer line is worth far more than the bows it gives up. Hence 22%.
    "Elves":   {"hue": 160, "mil": -8,  "eco": +14, "trait": "ancient forest sages",
                "unit_cooldown_mult": 0.90, "unit_speed_mult": 1.15,
                "unit_hp_mult": 0.90, "no_cavalry": True,
                "cavalry_becomes": "archers",
                "specials": ({"unit": "bladesinger", "of_archers": 0.22},)},
    # Stout and hard to kill, but methodical -- they march AND swing slower.
    # (Slow feet alone were no drawback at all; the slower swing is the real one.)
    # Dwarves charge behind the shield instead of dropping it: everyone else
    # trades guard for speed (orders.STANCE_CHARGE's block_mult), but a dwarven
    # line comes on with shields up and arrows glance off it. This is the one
    # species that can cross open ground under fire without paying for it.
    # The Shieldwarden is paid for out of the LINE, not the bows, and that is
    # the whole lesson of the unit it replaced. A heavy crossbow was tried here
    # first and took Dwarves from 25% of their matchups to 8% -- it swapped
    # tanky bodies for fragile ones and gave up 30px of range doing it. The
    # Warden instead doubles down on the one Dwarven mechanic that already
    # measures well: the line taking less punishment while it advances.
    "Dwarves": {"hue": 30,  "mil": +10, "eco": +10, "trait": "mountain-forged smiths",
                "unit_hp_mult": 1.20, "unit_speed_mult": 0.92,
                "unit_cooldown_mult": 1.08, "charge_shields_up": True,
                "specials": ({"unit": "shieldwarden", "of_swordsmen": 0.10,
                              "bonus": 0.03},)},
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
    # The Berserker takes the Orcish trade to its end: no shield at all, and
    # damage that climbs as it bleeds. It is the only unit in the game that is
    # more dangerous hurt than whole, which makes finishing one off a real
    # decision rather than free tidying-up.
    "Orcs":    {"hue": 95,  "mil": +16, "eco": -8,  "trait": "warband raiders",
                "unit_damage_mult": 1.18, "swordsman_size_mult": 1.30,
                "unit_hp_mult": 1.22, "unit_speed_mult": 1.20,
                "block_chance_mult": 0.72, "no_cavalry": True,
                "specials": ({"unit": "berserker", "of_swordsmen": 0.12,
                              "bonus": 0.01},)},
    # Fast and slippery -- a quarter of all blows miss them entirely -- and
    # they swing quicker than anyone, but they are the frailest thing on the
    # field. No cavalry either: goblins raid on foot. Unlike the Orcs, who pour
    # that share entirely into more Swordsmen, goblins split it evenly between
    # Swordsmen and Archers -- skirmishers, not a shield wall. The dodge and
    # attack-speed numbers are compensation for having measured as the weakest
    # species after the cavalry rework.
    # Dodge 0.18 -> 0.15 measured as far too harsh for how frail they are (25%
    # of matchups down to 8%, and to 0% once Elves were slowed), so it sits at
    # 0.17 -- most of the nerf, none of the collapse. The quicker swing and the
    # Assassin are the compensation.
    "Goblins": {"hue": 75,  "mil": -4,  "eco": -6,  "trait": "cunning scavengers",
                "unit_speed_mult": 1.15, "unit_hp_mult": 0.85,
                "unit_cooldown_mult": 0.94,
                "dodge_chance": 0.17, "no_cavalry": True,
                "cavalry_becomes": "split", "special_unit": "assassin",
                # Funded from three places: a little off the bows, a little off
                # the line, and a little for free. Paying for it ENTIRELY out of
                # the Archer share was measured and it was ruinous -- it turned
                # goblin ranged output into frail bodies and took them from 88%
                # of their matchups to 0%. Splitting the cost across both arms
                # and topping it up with a species bonus keeps the Assassin a
                # goblin advantage instead of a goblin tax.
                # Kept small on measurement, not taste: Goblin win rate falls
                # monotonically with the number of Assassins fielded (83% with
                # none, 54% at nine, 21% at thirteen, 8% at seventeen), so the
                # roster takes the fewest that still make them a real presence.
                # The Sapper is the answer to what the Assassin cannot do.
                # The Assassin's problem was never its numbers -- it was that
                # it dies crossing the field, so nothing it is good at ever
                # happens (0 first strikes and 0 of 9 alive in a measured
                # battle). The Sapper does the Goblin job -- break up a packed
                # formation -- from 110px away, where surviving the approach is
                # not the price of entry. Crude, inaccurate, slow to reload,
                # and it does not care how good your shields are.
                "specials": ({"unit": "assassin", "of_archers": 0.02,
                              "of_swordsmen": 0.02, "bonus": 0.01},
                             {"unit": "sapper", "of_archers": 0.08,
                              "bonus": 0.02})},
}

# --- Where a people comes from (biome overhaul, phase B) ---------------------
# Which biomes each species calls home. Used to decide WHICH already-placed
# capital each species is given (see worldgen._order_capitals_by_affinity) --
# an Elf realm should open in forest and a Dwarven one in the highlands,
# rather than the pure lottery it was, where nothing about a species touched
# placement at all.
#
# Weights, not a flat set: a Dwarf would rather have real mountains than mere
# highland, but will take the highland. Anything unlisted scores 0 for that
# species -- not a penalty, just no pull.
#
# Humans are deliberately broad and shallow. Their trait is literally
# "adaptable realm-builders", so they get a weak preference for the open,
# mixed, farmable middle of the map rather than a homeland of their own. That
# also means they are the species most willing to be displaced when someone
# else's homeland is scarce, which is exactly right.
#
# NOTE this is a preference over capitals that ALREADY passed worldgen's
# farmland check (_capital_has_nearby_farmland), so it can never place a realm
# somewhere it cannot feed itself. That guarantee is load-bearing and is
# asserted in dev/test_homeland.py: forest, the Elf homeland and the single
# most common biome on the map, grows no crops of its own at all.
SPECIES_BIOME_AFFINITY = {
    "Humans":  {"plains": 1.0, "coastal": 0.7, "forest": 0.5, "savannah": 0.5},
    "Elves":   {"forest": 1.0, "taiga": 0.7, "jungle": 0.4},
    "Dwarves": {"mountain": 1.0, "highland": 0.9, "tundra": 0.3},
    "Orcs":    {"savannah": 1.0, "steppe": 0.9, "plains": 0.6},
    "Goblins": {"swamp": 1.0, "jungle": 0.8, "tundra": 0.6},
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
    "charge_shields_up": False, # True = charging does NOT drop this species'
                                # guard (see Unit.effective_block), so it can
                                # advance under arrows behind its shields
    # Unit types only this species fields, on top of the shared Swordsman /
    # Archer / Cavalry core. A list of dicts, each:
    #   {"unit": key, "of_archers": f, "of_swordsmen": f, "bonus": f}
    # -- the first two are the fraction of that arm's headcount the unit is
    # paid for out of, and `bonus` is a fraction of military power granted
    # outright. See army_composition below for why it is funded from three
    # places rather than one.
    #
    # THESE SHARES ARE THE BALANCE KNOB. A signature unit's effect is almost
    # entirely how many of it you field, not its stats -- the Bladesinger went
    # from +25 points to -25 on a share change alone, with only its dodge
    # touched. Measure with `python dev/tournament.py 5 on --isolate`, which
    # runs a control with nobody's specials and then one run per species, so
    # each unit's effect is attributable. Turning all five on at once was tried
    # first and is uninterpretable.
    "specials": (),
}


# Every army's core, before species specials. Swordsmen carry the line, Archers
# shoot it in, Cavalry break it -- and a species with no_cavalry redistributes
# that last share rather than losing the headcount.
CORE_SHARES = {"infantry": 0.40, "archer": 0.25, "cavalry": 0.20}


def army_composition(species, power):
    """{unit_type: count} for a species at a given military rating.

    THE one place army composition is decided. It used to live in App._army_for
    with the balance tournament keeping a hand-copied duplicate, and a comment
    on both asking whoever came next to keep them in step -- which is a bug
    waiting on a distracted afternoon, since the tournament silently stops
    measuring the army the game actually fields.

    A special unit is funded from three places: a slice of the Archers, a slice
    of the Swordsmen, and a bonus granted outright. The bonus is the point --
    it makes the unit a species ADVANTAGE rather than a reshuffle -- and
    splitting the rest across both arms stops it gutting either one. Paying for
    the Goblin Assassin purely out of Archers was measured, and it took them
    from 88% of their matchups to 0%.
    """
    t = species_traits(species)
    foot, archer, cav = (CORE_SHARES["infantry"], CORE_SHARES["archer"],
                         CORE_SHARES["cavalry"])
    if t["no_cavalry"]:
        # Same headcount either way -- only where it lands differs. Orcs pour
        # it all into Swordsmen (a heavier foot line); Goblins split it, coming
        # out as skirmishers rather than a shield wall.
        mode = t["cavalry_becomes"]
        if mode == "split":
            foot += cav / 2
            archer += cav / 2
        elif mode == "archers":
            archer += cav
        else:
            foot += cav
        cav = 0.0
    comp = {"infantry": round(power * foot), "archer": round(power * archer)}
    if cav:
        comp["cavalry"] = round(power * cav)
    for spec in t["specials"]:
        from_bows = round(comp["archer"] * spec.get("of_archers", 0.0))
        from_line = round(comp["infantry"] * spec.get("of_swordsmen", 0.0))
        bonus = round(power * spec.get("bonus", 0.0))
        comp["archer"] -= from_bows
        comp["infantry"] -= from_line
        total = from_bows + from_line + bonus
        if total:
            comp[spec["unit"]] = comp.get(spec["unit"], 0) + total
    return comp


def species_traits(species):
    """Every trait for `species`, with unmodified defaults filled in -- the one
    accessor combat/trade code should use, so an unknown or absent species
    (e.g. a wildland garrison) is always safe and simply baseline."""
    spec = SPECIES.get(species, {})
    return {key: spec.get(key, default)
            for key, default in _SPECIES_TRAIT_DEFAULTS.items()}


def species_stat_chips(species):
    """Short comparison tokens: ["HP +20%", "SPD -8%", "no cavalry", "Arbalest"].

    species_trait_summary writes prose for a panel with room for it. This is the
    same numbers compressed for a row in a table, so five species can be read
    against each other at a glance rather than one at a time -- which is the
    only way the choice is an informed one. Same live values either way; neither
    can drift from the balance table."""
    t = species_traits(species)
    out = []
    for key, label in (("unit_hp_mult", "HP"), ("unit_damage_mult", "DMG"),
                       ("unit_speed_mult", "SPD")):
        delta = round((t[key] - 1.0) * 100)
        if delta:
            out.append(f"{label} {delta:+d}%")
    # Cooldown is inverted -- less time between swings is faster attacks.
    atk = round((1.0 - t["unit_cooldown_mult"]) * 100)
    if atk:
        out.append(f"ATK SPD {atk:+d}%")
    blk = round((t["block_chance_mult"] - 1.0) * 100)
    if blk:
        out.append(f"BLOCK {blk:+d}%")
    if t["dodge_chance"]:
        out.append(f"DODGE {round(t['dodge_chance'] * 100)}%")
    if t["no_cavalry"]:
        out.append("no cavalry")
    if t["trade_gold_bonus"]:
        out.append(f"TRADE +{round(t['trade_gold_bonus'] * 100)}%")
    if t["charge_shields_up"]:
        out.append("charges shielded")
    return out


def species_units(species):
    """Display names of the signature units this species fields."""
    from app.battle.unit_types import UNIT_TYPES
    return [UNIT_TYPES.get(s["unit"], {}).get("name", s["unit"])
            for s in species_traits(species)["specials"]]


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
    if t["specials"]:
        # Imported here rather than at module scope: unit_types imports nothing
        # from this module today, but a species table that cannot be read
        # without the battle package is a circular import waiting to happen.
        from app.battle.unit_types import UNIT_TYPES
        names = [UNIT_TYPES.get(s["unit"], {}).get("name", s["unit"])
                 for s in t["specials"]]
        out.append("fields " + " and ".join(names)
                   + (" -- units no other species has" if len(names) > 1
                      else ", a unit no other species has"))
    return out

# --- faction names: "<Adj> <Noun>" ------------------------------------------
_FACTION_NAMES = {
    # Humans draw on the naming CONVENTIONS of Sanderson's Stormlight
    # Archive rather than anything from it: storm-shaped descriptive
    # compounds, oath and highland vocabulary, and a fondness for symmetry.
    # Every name here is original -- no proper noun of his is reused, which
    # is the whole point of taking a convention rather than a name.
    "Humans": (
        ["Stormward", "Oathbound", "Highstone", "Windswept", "Riven",
         "Tempered", "Sunlit", "Leeward", "Stormcalled", "Unbroken",
         "Stonebound", "Skyward", "Weathered", "Ninefold", "Sworn",
         "Cragbound", "Shorn", "Everward", "Bright", "Sundered"],
        ["Princedom", "Highmarch", "Oathhold", "Conclave", "Dominion",
         "Warcamp", "Covenant", "Accord", "Bulwark", "Reach",
         "Stormseat", "Protectorate", "Sovereignty", "Throne", "Highcourt",
         "Compact", "Bastionry", "Marches", "Concord", "Waymarch"],
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
    # See the note on the Human faction bank above. Roots lean on the
    # th/kh/sh/l/n phonetics and the symmetry the convention prizes
    # (Nomon, Tevet, Kanak, Halah and Sasas all read the same both ways);
    # suffixes trade the Anglo-Saxon -ton/-thorpe/-by village endings for
    # storm-and-stone ones, because on a coast the weather carves the map
    # and people name places for how exposed they are to it.
    "Humans": (
        ["Khal", "Thal", "Vesh", "Nalath", "Torath", "Shael", "Kavel",
         "Denar", "Elith", "Marath", "Sevath", "Halan", "Nomon", "Tevet",
         "Kanak", "Halah", "Sasas", "Storm", "Lee", "Stone"],
        {"city": ["nar", "kar", "eth", "seat", "spire", "reach", "cradle", "vast"],
         "castle": ["watch", "bulwark", "hold", "ward", "bastion", "wall", "stand"],
         "town": ["vah", "eth", "market", "crossing", "rill", "gate",
                   "hollow", "run", "quarter", "dale"],
         "village": ["in", "al", "lee", "shelter", "hollow", "rest",
                     "walk", "row", "fold", "burrow"]},
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


# Underground regions get their own vocabulary. The surface pool is full of
# vales, downs, moors and shores, every one of which needs a sky -- a gallery
# called "Sunlit Meadow" would be the single most obvious tell that the
# underworld was bolted onto a map generator. These are what people actually
# called the parts of a working: a delve is what you dig, a drift follows the
# seam, a stope is the space left where ore was taken out, a sump is where the
# water collects.
_UNDER_ADJ = ("Deep", "Lower", "Under", "Black", "Silent", "Old", "Broken",
              "Iron", "Cold", "Hollow", "Long", "Nether", "Sunken", "Grim",
              "Quiet", "Far", "Drowned", "Ember", "Stone", "Rich")
_UNDER_FEATURE = ("Delve", "Drift", "Gallery", "Hall", "Deep", "Vault",
                  "Stope", "Sump", "Warren", "Undercroft", "Cavern", "Reach",
                  "Shaft", "Hollow", "Descent", "Workings", "Chamber", "Cut")


def make_under_region_namer(rng):
    """Region names for the underworld -- same contract as
    make_region_namer, drawn from a vocabulary that does not assume a sky."""
    used = set()

    def namer():
        for _ in range(300):
            name = f"{rng.choice(_UNDER_ADJ)} {rng.choice(_UNDER_FEATURE)}"
            if name not in used:
                used.add(name)
                return name
        for _ in range(300):
            name = (f"{rng.choice(_UNDER_ADJ)} {rng.choice(_UNDER_FEATURE)}, "
                    f"{rng.choice(_REGION_QUALIFIERS)}")
            if name not in used:
                used.add(name)
                return name
        name = (f"{rng.choice(_UNDER_ADJ)} {rng.choice(_UNDER_FEATURE)}, "
                f"{rng.choice(_REGION_QUALIFIERS)} and {rng.choice(_REGION_QUALIFIERS)}")
        used.add(name)
        return name

    return namer


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

    def _join(root, suffix):
        """Glue a root to a suffix, collapsing a letter doubled across the
        seam -- "Sasas" + "shelter" should read Sasashelter, not
        Sasasshelter, and "Stone" + "eth" Stoneth rather than Stoneeth. Only
        at the join, so a doubling that belongs to either part on its own
        (Ostt-, -rrow) is left alone."""
        if root and suffix and root[-1].lower() == suffix[0].lower():
            return f"{root}{suffix[1:]}"
        return f"{root}{suffix}"

    def namer(kind, species="Humans"):
        roots, suffix_map = _SETTLE_NAMES.get(species, _SETTLE_NAMES["Humans"])
        suffixes = suffix_map.get(kind, suffix_map["town"])
        for _ in range(200):
            name = _join(rng.choice(roots), rng.choice(suffixes))
            if name not in used:
                used.add(name)
                return name
        name = f"{_join(rng.choice(roots), rng.choice(suffixes))} {len(used)}"
        used.add(name)
        return name

    return namer


# --- rulers -------------------------------------------------------------------
# The monarch is a separate figure from the battlefield Commander: the Commander
# is the general who marches and can fall (see app/world/commander.py, which has
# its own species titles -- Marshal, Warden, Thane, Warchief, Chieftain), while
# this is who sits the throne and whose realm it is. They deliberately do not
# share a title table, because a player who names both should never wonder which
# one they just named.
RULER_TITLES = {
    "Humans": ("King", "Queen"),
    "Elves": ("Archon", "Archon"),
    "Dwarves": ("High King", "High Queen"),
    "Orcs": ("Warlord", "Warlord"),
    "Goblins": ("Boss", "Boss"),
}

# Given name + optional epithet, per species. Kept in the same shape as the
# faction banks above so a species missing an entry falls back to Human rather
# than crashing -- the rule every namer in this module follows.
_RULER_NAMES = {
    # See the note on the Human faction bank above. Given names carry the
    # same th/l/n sound and symmetry; epithets swear by storms and oaths
    # rather than by chivalric virtue.
    "Humans": (
        ["Nalath", "Tevalen", "Shaleth", "Kavaran", "Elthar", "Torenal",
         "Vashen", "Halavar", "Renath", "Sevaren", "Dalneth", "Malaren",
         "Ithara", "Naveth", "Shalira", "Elenath", "Ravana", "Talavi",
         "Nomon", "Kanak", "Tevet", "Sasas"],
        ["the Stormward", "Oathkeeper", "the Unbroken", "Stormcalled",
         "the Tempered", "who Held the Wall", "the Twicesworn",
         "the Windward", "the Steadfast"],
    ),
    "Elves": (
        ["Aerandir", "Caelith", "Elrohir", "Faelar", "Ithilwen", "Lorindel",
         "Maerwen", "Nithral", "Silvaria", "Thalindra", "Vaelith", "Ysolde",
         "Aelorin", "Cirdanel", "Elowen", "Fenwyth", "Lythien", "Miravel"],
        ["of the Dawnwood", "Starcaller", "the Everwatchful", "Moonwoven",
         "of the Silver Bough", "the Longmemoried", "Duskwalker"],
    ),
    "Dwarves": (
        ["Brokk", "Durgan", "Thrain", "Balgrim", "Norrik", "Ovar", "Hjalmar",
         "Grimni", "Torvald", "Dvalin", "Kargan", "Rurik", "Hilda", "Brynja",
         "Sigrun", "Astrid", "Thora", "Gudrun"],
        ["Ironbeard", "Stoneborn", "the Anvilhanded", "Deepdelver",
         "Emberforge", "the Unyielding", "Runegraven", "Oathkeeper"],
    ),
    "Orcs": (
        ["Grosh", "Mazrek", "Ugthar", "Karogg", "Drusk", "Vragga", "Skarn",
         "Ghorak", "Mulgor", "Ruzka", "Thokk", "Zarog", "Ogrim", "Brakka"],
        ["Skullsplitter", "the Red", "Bonebreaker", "Ironjaw", "the Devourer",
         "Blackfang", "the Unbroken", "Warbringer"],
    ),
    "Goblins": (
        ["Snik", "Grizzle", "Vex", "Mudge", "Krik", "Sprock", "Nabber",
         "Wixxle", "Gribbit", "Tozz", "Skree", "Rattle", "Pockets", "Fizzik"],
        ["the Cunning", "Three-Fingers", "the Unseen", "Quickknife",
         "the Lucky", "Backstabber", "the Loud", "Nine-Lives"],
    ),
}

# Not every ruler gets an epithet. A field of fourteen realms all led by someone
# "the Bold" or "Ironbeard" reads as generated; a mix reads as a world.
_EPITHET_CHANCE = 0.55


def make_ruler_namer(rng):
    """(species) -> a unique ruler name. Same contract as make_faction_namer."""
    used = set()

    def namer(species="Humans"):
        given, epithets = _RULER_NAMES.get(species, _RULER_NAMES["Humans"])
        for _ in range(200):
            name = rng.choice(given)
            if rng.random() < _EPITHET_CHANCE:
                name += " " + rng.choice(epithets)
            if name not in used:
                used.add(name)
                return name
        name = f"{rng.choice(given)} {len(used) + 1}"
        used.add(name)
        return name

    return namer


def ruler_title(species, rng=None):
    """The royal title for a species. Two are offered where the species has a
    gendered pair; picked at random for an AI realm, and offered as a choice to
    the player (see the New Game screen)."""
    pair = RULER_TITLES.get(species, RULER_TITLES["Humans"])
    if rng is None:
        return pair[0]
    return rng.choice(pair)


# --- colours ------------------------------------------------------------------
# Every faction's colour is drawn from its SPECIES hue (see worldgen), which is
# what makes the political map readable: kin look like kin, and two realms of
# different species never sit on top of each other in hue. A player choosing a
# colour has to stay inside that logic or it stops being true, so the palette
# offered is a spread AROUND the species hue rather than the whole wheel.
PALETTE_HUE_SPREAD = 26.0     # degrees either side of the species hue
PALETTE_SIZE = 12


def species_palette(species, n=PALETTE_SIZE):
    """`n` distinct hex swatches for a species, light-to-dark across a band
    centred on its hue. The first entry is the species' "true" colour."""
    import colorsys

    hue = SPECIES.get(species, {}).get("hue", 45)
    out = []
    for i in range(n):
        # Fan out from the centre rather than sweeping left to right, so the
        # swatches nearest the species' own hue come first and a player who
        # just takes the leading option gets the canonical colour.
        step = (i + 1) // 2 * (1 if i % 2 else -1)
        h = hue + step * (PALETTE_HUE_SPREAD / max(1, n // 2))
        sat = 0.62 + 0.16 * ((i % 3) - 1)
        val = 0.86 - 0.07 * (i % 4)
        r, g, b = colorsys.hsv_to_rgb((h % 360) / 360.0, sat, val)
        out.append("#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255)))
    # Dedupe while keeping order -- a rounding collision would otherwise show
    # the player two swatches that look and behave identically.
    seen, unique = set(), []
    for c in out:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


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


# --- The fantasy naming layer (biome overhaul, phase F) ----------------------
# A named skin over each mechanical biome: the Everwood rather than "forest",
# the Ashwaste rather than "desert".
#
# FLAVOUR ONLY, and that is a hard constraint rather than a stylistic note.
# A named variant NEVER has a different or better resource profile than the
# mechanical biome underneath it -- two regions both classified `forest` are
# mechanically identical whether one is called an Everwood and the other a
# Thornwild. This lives in lexicon.py, next to the other namers and a long way
# from resources.py, precisely so that nothing in the economy can reach it:
# the name is derived FROM the biome and is never read back by anything that
# computes a yield. dev/test_biome_names.py asserts that directly.
#
# Why it is worth having anyway: "the Mistfen" is a place and "swamp" is a
# terrain type, and a world made of places is the one the player remembers.
#
# Keyed by mechanical biome, then by the region's dominant climate, so the
# same forest reads differently in the frozen north than on a warm coast.
# "*" is the fallback for any climate without its own entry.
BIOME_FLAVOUR_NAMES = {
    "forest": {
        "cold":      ("the Hollowpine", "the Frostwood", "the Rimewood"),
        "humid":     ("the Everwood", "the Greenmarch", "the Dampholt"),
        "*":         ("the Everwood", "the Thornwild", "the Silvermoot"),
    },
    "taiga": {
        "*":         ("the Pinereach", "the Longwood", "the Coldmoot"),
    },
    "jungle": {
        "*":         ("the Verdance", "the Tanglewild", "the Rainmaw"),
    },
    "plains": {
        "arid":      ("the Dryacres", "the Dustdowns", "the Thinfields"),
        "cold":      ("the Palefields", "the Shortgrass", "the Wintermeads"),
        "*":         ("the Wide Acres", "the Goldfields", "the Greendowns"),
    },
    "savannah": {
        "*":         ("the Sunveldt", "the Lionreach", "the Brightveldt"),
    },
    "steppe": {
        "*":         ("the Windsea", "the Longgrass", "the Riderwaste"),
    },
    "desert": {
        "*":         ("the Ashwaste", "the Sunscour", "the Dunereach"),
    },
    "tundra": {
        "*":         ("the Palefrost", "the Rimewaste", "the White Silence"),
    },
    "swamp": {
        "cold":      ("the Frozenfen", "the Greymire", "the Chillmarsh"),
        "*":         ("the Mistfen", "the Blackmire", "the Sorrowmarsh"),
    },
    "coastal": {
        "cold":      ("the Grey Shore", "the Icereach", "the Sleetstrand"),
        "*":         ("the Saltmarch", "the Tidewatch", "the Foamreach"),
    },
    "highland": {
        "cold":      ("the Hoarfell", "the Bleakmoor", "the Windbite"),
        "*":         ("the Stonemoor", "the Highfell", "the Craghold"),
    },
    "mountain": {
        "*":         ("the Skyteeth", "the Ironspine", "the Cloudwall"),
    },
}


def biome_flavour_name(biome, climate, key):
    """The named variant of `biome` in `climate` for a region.

    `key` is any stable integer the caller owns (a region id) -- the choice
    has to survive a save/load and be identical on every machine, so it is a
    plain index rather than an rng draw. Returns None for a biome with no
    flavour entry, which callers should render as the plain mechanical name
    rather than inventing one.
    """
    by_climate = BIOME_FLAVOUR_NAMES.get(biome)
    if not by_climate:
        return None
    options = by_climate.get(climate) or by_climate.get("*")
    if not options:
        return None
    return options[key % len(options)]
