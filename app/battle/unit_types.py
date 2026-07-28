"""Unit archetypes — pure data. Add a new type here and it's immediately
usable by any army. ``shape`` references a key in the shape registry.

Speeds/ranges are in canvas pixels; times in seconds.
  ``ranged``      : True fires an animated arrow ('.') at the target on each hit.
  ``accuracy``    : chance (0..1) an in-range, off-cooldown attack actually
                    lands — a miss still spends the cooldown (and, if ranged,
                    still fires the arrow) but deals no damage. Defaults to
                    1.0 (always hits) via Unit.update's .get() when omitted.
  ``equipment``   : list of hand-held markers drawn by the battle view —
                    "sword" ('t', right hand) and "shield" ('o', left hand).
  ``block_chance``: chance (0..1) a sword+shield unit deflects an incoming hit
                    with its shield -- but only if the attacker is within the
                    unit's frontal ``block_arc_deg`` cone (a shield covers the
                    front, not the flanks/rear). See Unit.take_hit.
  ``block_arc_deg``: total width (degrees) of that frontal cone.
  ``charge``      : True marks a mounted unit that builds momentum while
                    galloping toward its target and delivers a couched impact
                    hit -- devastating fresh out of a charge, weak once bogged
                    down in a melee. See Unit.update / Unit.charge.
  ``charge_bonus``: extra damage multiplier at full momentum (added on top of
                    ``melee_floor``).
  ``melee_floor`` : damage multiplier with zero momentum (stuck in a scrum) --
                    below 1.0, so a bogged-down rider hits softer than its raw
                    ``damage`` implies.
  ``charge_ramp`` : seconds of uninterrupted galloping to reach full momentum.
"""
UNIT_TYPES = {
    "infantry": {
        "name": "Swordsmen", "shape": "circle", "radius": 5,
        "max_hp": 30, "speed": 34, "range": 14, "damage": 8, "cooldown": 0.6,
        "ranged": False, "equipment": ["sword", "shield"],
        "block_chance": 0.35, "block_arc_deg": 150,
    },
    # Rebuilt around the charge after archer range doubled: a horseman spends
    # the whole approach being shot at, so the gallop has to be fast enough to
    # cross that envelope and the impact has to be worth having crossed it.
    # Speed 72 -> 110, charge_bonus 2.0 -> 3.0 (a full-momentum couched hit is
    # now 3.5x its base damage, not 2.5x), and charge_ramp 1.2 -> 1.0 so a rider
    # that pulls back and comes again is dangerous sooner. melee_floor stays
    # low: bogged down in a scrum they are still the worst unit on the field.
    #
    # The AOE numbers below are swept, not chosen. A first pass at radius 30 /
    # share 0.60 was simply dominant -- it took the two cavalry species from the
    # bottom of the roster to 94% and 78% and pushed Goblins to 3%. These values
    # measured the most even spread of everything tried while keeping the charge
    # unmistakably the biggest single event on the field.
    "cavalry": {
        "name": "Cavalry", "shape": "triangle", "radius": 6,
        "max_hp": 26, "speed": 110, "range": 12, "damage": 10, "cooldown": 0.5,
        "ranged": False, "equipment": ["sword"],
        "charge": True, "charge_bonus": 3.0, "melee_floor": 0.5, "charge_ramp": 1.0,
        # A couched impact doesn't just hit one soldier -- it ploughs into
        # whatever frontline it reaches. Everyone else within this radius of the
        # struck target takes `charge_aoe_share` of the impact damage. Scales
        # with momentum, so only a real gallop scatters a line.
        "charge_aoe_radius": 22, "charge_aoe_share": 0.35,
    },
    # Range doubled from 90. The armies deploy ~900px apart, so archers still
    # have to advance to shoot rather than opening fire from the spawn line --
    # but they now get roughly twice as long shooting into an approaching enemy
    # before it closes, which is a large buff to any archer-heavy roster.
    # --- The Commander ------------------------------------------------------
    # Not part of an army's composition: exactly one is added per side on top
    # of it (see Battle.deploy), so fielding him never costs you a soldier and
    # small armies don't end up proportionally more commander than army.
    #
    # Sized and statted to be "very hard to take down" without deciding fights
    # by himself: ~9x a Swordsman's HP and ~3x its damage means several
    # soldiers focusing him for a sustained stretch will still bring him down,
    # but no single unit trades with him. He is drawn as an oversized circle
    # with a contrasting inner disc -- see battle_view._draw_commander.
    "commander": {
        "name": "Commander", "shape": "circle", "radius": 15,
        "max_hp": 270, "speed": 30, "range": 18, "damage": 24, "cooldown": 0.7,
        "ranged": False, "equipment": ["sword", "shield"],
        "block_chance": 0.45, "block_arc_deg": 180,
    },
    "archer": {
        "name": "Archer", "shape": "square", "radius": 5,
        "max_hp": 20, "speed": 30, "range": 180, "damage": 6, "cooldown": 0.9,
        "ranged": True, "accuracy": 0.8, "equipment": [],
    },
}

# --- Species commanders -------------------------------------------------------
# Every commander inherits its species' soldier multipliers (Unit reads them),
# and measurement showed that alone is a balance problem: it AMPLIFIES the
# raw-stat species and does nothing for the utility ones. A tournament with
# commanders added widened the roster spread by ~7 points across two seed
# batches, entirely at the expense of Humans (23-28% -> 16-20%) while Orcs
# stayed at ~80%, because an Orcish commander gets +22% HP and +18% damage on a
# 270 HP body while the Human bonus (block chance) is worth almost nothing on a
# single unit.
#
# So these profiles are corrective, not just flavourful. Each species'
# commander is the concentrated form of that species' identity, and the ones
# whose armies are already strong get commanders that add little raw power,
# while the ones that need help get commanders whose value is what they do for
# everyone around them.
#
# `stats` override the base commander entry in UNIT_TYPES. `aura` is applied to
# living friendly soldiers within `aura_radius` px -- read on demand at the
# point of use rather than written onto units, so it can never double-apply and
# needs no cleanup when the commander dies (see Unit._aura).
COMMANDER_AURA_RADIUS = 130

COMMANDER_BY_SPECIES = {
    # The Marshal: least dangerous commander alive, the best force multiplier
    # in the game. Humans' whole identity is the drilled line, and they measured
    # worst by a wide margin -- this is where that gets answered.
    "Humans": {
        "title": "Marshal",
        "stats": {"max_hp": 250, "damage": 18},
        "aura": {"damage_mult": 1.15, "cooldown_mult": 0.90, "block_add": 0.10},
    },
    # The Warden: fights at range and extends his archers' reach. Frailest
    # commander on the field -- caught in melee he dies like any other elf.
    "Elves": {
        "title": "Warden",
        "stats": {"max_hp": 190, "damage": 11, "range": 150, "ranged": True,
                  "accuracy": 0.9, "speed": 34, "block_chance": 0.0},
        "aura": {"range_mult": 1.05, "cooldown_mult": 0.95},
    },
    # The Thane: the anchor. Enormous and immovable; his line takes less
    # punishment while he stands, but he cannot chase a fight that moves.
    "Dwarves": {
        "title": "Thane",
        "stats": {"max_hp": 470, "damage": 26, "speed": 28, "block_chance": 0.58},
        "aura": {"damage_taken_mult": 0.76},
    },
    # The Warchief: pure offence, no aura at all. Orcs already measure ~80%, so
    # their commander deliberately gains nothing for the army and instead
    # trades his own life -- a heavy cleaving arc, and no protection for anyone.
    "Orcs": {
        "title": "Warchief",
        "stats": {"max_hp": 300, "damage": 30, "block_chance": 0.15},
        "cleave": {"radius": 34, "share": 0.55},
        "aura": {"damage_mult": 1.10},
    },
    # The Chieftain: never meant to be hit. Lowest damage of the five; wins by
    # not dying and by making everyone around him just as hard to pin down.
    "Goblins": {
        "title": "Chieftain",
        "stats": {"max_hp": 200, "damage": 14, "speed": 42, "dodge_chance": 0.34},
        "aura": {"dodge_add": 0.05, "cooldown_mult": 0.98},
    },
}

_NO_AURA = {}


def commander_profile(species):
    """The species' commander profile, or a plain baseline for an unknown
    species (a wildland garrison has none)."""
    return COMMANDER_BY_SPECIES.get(species, {"title": "Commander",
                                              "stats": {}, "aura": _NO_AURA})
