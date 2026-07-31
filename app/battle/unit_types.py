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
  ``dodge_chance``: floor on this type's chance to evade a hit outright, taken
                    as a MAX against the owning species' own dodge.
  ``first_strike``: damage multiplier on the opening blow against each DISTINCT
                    target (tracked by uid -- see Unit._struck).
  ``hunts_ranged``: ignores everything but enemy ranged units while any live
                    anywhere on the field. See Battle.choose_target.
  ``ignores_block``: this attacker's blows cannot be shielded. Dodge still
                    applies -- it beats armour, not agility.
  ``frenzy``      : extra damage multiplier at ZERO hp, scaled by how much
                    health is already gone; a unit with it is more dangerous
                    hurt than whole.
  ``splash_radius``/``splash_share``: a landed hit also deals `share` of its
                    damage to every other enemy within `radius` of the target.
                    Same shape as a charge impact, but with no momentum term.
  ``aura``/``aura_radius``: this unit projects a commander-style aura over
                    friendly soldiers within the radius. Auras do NOT stack --
                    see Unit._aura.
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
    # --- The Assassin (Goblins only) ----------------------------------------
    # A counter-archer, not a duellist. Twin daggers means a very fast, very
    # small hit -- damage 4 on a 0.22s cooldown is ~18 dps against an archer's
    # 20 HP, so one gets in among bowmen and takes them apart, while the same
    # 4 damage against a 30 HP shielded swordsman (who blocks and hits back for
    # 8) is a losing trade. That asymmetry is the point: they are lethal at the
    # job they are for and nearly useless at anything else, which is what makes
    # `hunts_ranged` a strength rather than a restriction.
    #
    # Fastest thing on foot (speed 46) with no shield and 14 HP -- caught in the
    # open by anything that can hit back, they die immediately.
    "assassin": {
        "name": "Assassin", "shape": "diamond", "radius": 4,
        "max_hp": 14, "speed": 46, "range": 12, "damage": 4, "cooldown": 0.22,
        "ranged": False, "equipment": ["daggers"],
        # Slipperier than any goblin soldier -- pitched just above the 0.18 the
        # whole species carried before its dodge was cut. Evasion, not armour,
        # is what keeps a 14 HP knife-fighter alive long enough to reach the
        # bowmen. Taken as a MAX against the species trait (see Unit.__init__),
        # so it is a floor for the type rather than a replacement for it.
        "dodge_chance": 0.22,
        # First strike: the opening blow on each victim lands for this much.
        # Awarded once per DISTINCT target (tracked by uid, see Unit._struck),
        # never once per engagement -- otherwise a unit could flick its target
        # away and back on the retarget throttle and farm the bonus forever.
        # 4 damage becomes 14, which is most of an archer's 20 HP: an Assassin
        # that reaches the bowmen opens by gutting one, then has to finish the
        # rest at its ordinary rate. That is the whole fantasy of the unit, and
        # it is why simply giving it more HP and damage did not work -- its
        # value should be in the first moment it arrives, not in a slugging
        # match it was never built to win.
        "first_strike": 3.5,
        # Ignores everything but enemy ranged units until none are left alive
        # anywhere on the field -- see Battle.choose_target.
        "hunts_ranged": True,
    },
    # --- The Sapper (Goblins only) ------------------------------------------
    # Everything the Assassin is not. The Assassin's failure was never its
    # numbers -- bigger ones were tried and changed nothing -- it was that its
    # whole value lives in a moment it rarely survives to reach. So the Sapper
    # does the same job, breaking up a packed line, from outside contact.
    #
    # A crude bomb: slow (2.6s), unreliable (0.65), and only 7 damage where it
    # lands -- but every enemy within 26px takes 70% of that too. Against a
    # loose skirmish line it is a bad archer. Against the shield wall that
    # beats Goblins it hits eight soldiers at once, and the splash goes through
    # take_hit like anything else, so shields still stop the part of it that
    # comes from the front.
    "sapper": {
        "name": "Sapper", "shape": "chevron", "radius": 5,
        "max_hp": 16, "speed": 40, "range": 110, "damage": 7, "cooldown": 2.6,
        "ranged": True, "accuracy": 0.65, "equipment": [],
        "splash_radius": 26, "splash_share": 0.70,
    },
    # --- The Shieldwarden (Dwarves only) ------------------------------------
    # This slot held an Arbalest first -- a heavy crossbow, higher damage than
    # a bow, shorter ranged, `ignores_block`. It measured a DISASTER: Dwarves
    # fell from 25% of their matchups to 8%, the worst single result any change
    # has produced here. Two reasons, both of which generalise:
    #
    #   * Range dominates. 150 against the Archer's 180 means the crossbows
    #     spend the approach being shot and unable to answer, and they are the
    #     slowest thing on the field while doing it.
    #   * It paid for tanky bodies with fragile ones. Dwarves' whole advantage
    #     is 20% more HP behind a shield; 22 HP crossbowmen throw that away.
    #
    # So this is the opposite unit. It plays to the one thing Dwarves already
    # do that nothing else can -- walk into arrow fire behind their shields --
    # and it makes everyone around it better at that instead of adding a second
    # thing they are worse at. Rank-and-file version of the Thane's aura, which
    # is the one Dwarven mechanic already measured to work.
    "shieldwarden": {
        "name": "Shieldwarden", "shape": "hexagon", "radius": 6,
        "max_hp": 40, "speed": 26, "range": 14, "damage": 7, "cooldown": 0.90,
        "ranged": False, "equipment": ["sword", "shield"],
        "block_chance": 0.45, "block_arc_deg": 170,
        "aura": {"damage_taken_mult": 0.88},
        "aura_radius": 80,
    },
    # --- The Berserker (Orcs only) ------------------------------------------
    # The Orcish trade taken to its end: no shield whatsoever, and damage that
    # climbs as it bleeds. `frenzy` is the extra damage multiplier at ZERO hp,
    # scaled linearly by how much health is already gone -- so a Berserker at
    # a quarter health hits for 1.6x, and it is the only unit in the game more
    # dangerous hurt than whole. That inverts the usual "finish the wounded"
    # instinct Battle.choose_target has, which is the whole idea.
    #
    # frenzy 1.2 -> 0.8 and the count cut: at 1.2 this took Orcs from 50% of
    # their matchups to 65%, which is a fine unit and bad balance -- Orcs were
    # already mid-table and the roster's problem is its spread.
    "berserker": {
        "name": "Berserker", "shape": "chevron", "radius": 6,
        "max_hp": 34, "speed": 40, "range": 14, "damage": 12, "cooldown": 0.50,
        "ranged": False, "equipment": ["sword"],
        "frenzy": 0.8,
    },
    # --- The Bladesinger (Elves only) ---------------------------------------
    # The one special on the roster paid for entirely out of its own species'
    # strength, with no bonus at all: Elves win ~70% of their matchups on an
    # all-archer line that never has to close, so their signature unit trades
    # a slice of exactly that for the melee answer they have never had.
    #
    # Fast and evasive rather than tough -- Elves carry no dodge as a species,
    # so this is the only elf on the field that is hard to hit, and at 22 HP
    # anything that does hit it is most of the way to killing it.
    #
    # It was meant as a sidegrade and measured as the single biggest buff on
    # the roster: 60% of matchups to 85%. What being closed on costs an
    # all-archer line turns out to be far more than the bows it gives up, so
    # the price went from a tenth of the bows to nearly a quarter, and the
    # dodge came down. If it still measures positive it should get dearer
    # again -- Elves lead the roster and their signature unit is the one on
    # this table that has no business making them stronger.
    "bladesinger": {
        "name": "Bladesinger", "shape": "diamond", "radius": 5,
        "max_hp": 22, "speed": 46, "range": 13, "damage": 9, "cooldown": 0.45,
        "ranged": False, "equipment": ["sword"],
        "dodge_chance": 0.20,
    },
    # --- The Standard Bearer (Humans only) ----------------------------------
    # The rank-and-file form of the Marshal. Humans' identity is that the line
    # is worth more than the soldiers in it, and until now the only expression
    # of that was one commander -- concentrated on a single body that can die,
    # and worth nothing to the flank he is not standing on.
    #
    # Auras do NOT stack (see Unit._aura): a soldier takes the best single
    # source covering it, commander first. Banners spread the effect across the
    # field, they do not pile it up in one place -- which is also why the
    # radius matters more than the count.
    #
    # First pass (4 banners, 90px, +8% damage / +0.05 block) measured as doing
    # nothing at all: 42% of matchups to 40%. Four sources cannot cover a line
    # of eighty soldiers, so almost nobody was ever inside one. Widened and
    # strengthened rather than multiplied, since stacking is off by design.
    "bannerman": {
        "name": "Standard Bearer", "shape": "hexagon", "radius": 6,
        "max_hp": 34, "speed": 32, "range": 14, "damage": 6, "cooldown": 0.80,
        "ranged": False, "equipment": ["sword", "shield"],
        "block_chance": 0.35, "block_arc_deg": 150,
        "aura": {"damage_mult": 1.14, "block_add": 0.08, "cooldown_mult": 0.94},
        "aura_radius": 125,
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

# A commander holds his ground. He fights whatever reaches him and never
# walks forward to close on anything -- see Unit._screened, which used to
# count how many of his own soldiers stood between him and his target and
# let him advance once enough did. Measured, that was no restraint at all: a
# front line is between him and the enemy essentially always. Splitting a
# real battle's commander movement into "advanced under his own orders"
# against "shoved by collisions" came out 1,006px to 128px.
#
# The one thing that does move him: staying with his own army. Past this
# distance from where his soldiers are actually fighting he stops everything
# else and comes back, which also covers being shoved by a charging line.
COMMANDER_LEASH = 165.0

# ...unless there is no line left to hold. Once his own army is down to this
# many soldiers or fewer, a commander fights like anyone else. Without it two
# commanders whose armies had wiped each other out simply stood and looked at
# one another forever -- caught by dev/test_battle_terrain, where a swamp
# battle stopped resolving at all.
COMMANDER_LAST_STAND = 3
COMMANDER_RETURN_SPEED_MULT = 1.6   # he rides back, rather than trudging after
                                    # an army that gallops

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
        "stats": {"max_hp": 200, "damage": 14, "speed": 42, "dodge_chance": 0.32},
        "aura": {"dodge_add": 0.045, "cooldown_mult": 0.98},
    },
}

_NO_AURA = {}


def commander_profile(species):
    """The species' commander profile, or a plain baseline for an unknown
    species (a wildland garrison has none)."""
    return COMMANDER_BY_SPECIES.get(species, {"title": "Commander",
                                              "stats": {}, "aura": _NO_AURA})
