"""Battlefield orders -- what a player (or the order AI) tells troops to do
once the fight is under way.

Two independent axes, deliberately kept separate rather than folded into one
"order" field, because they answer different questions and a unit can hold both
at once. An archer told to stand its ground AND hold fire is a coherent,
useful instruction; a single enum would have forced a choice between them.

  STANCE          how the unit moves and carries itself
  fire discipline whether a ranged unit shoots (ranged units only)

Every modifier here is a multiplier or an addend applied on top of the unit's
existing numbers, so species traits, commander auras and the charge system all
keep working underneath an order rather than being overridden by it.

The set is deliberately rock-paper-scissors rather than four separate buffs:

  HOLD/SHIELD_WALL   brace, and blunt a cavalry charge (BRACE_CHARGE_MULT)
  CHARGE             hits harder and moves faster, but drops its guard
  SHIELD_WALL        strong from the front, and no better than usual from the
                     flank -- shields already only block within a frontal arc
                     (see Unit.take_hit), so walking around a wall beats it
  CYCLE_CHARGE       cavalry that will not sit in a grind: it hits, pulls out,
                     and comes again at whatever formation is fattest

so ordering well means answering what the other side just did.
"""

# --- stances ------------------------------------------------------------------
STANCE_ADVANCE = "advance"          # default: the behaviour that predates orders
STANCE_HOLD = "hold"                # stand your ground, braced
STANCE_CHARGE = "charge"            # press forward hard
STANCE_SHIELD_WALL = "shield_wall"  # infantry only -- dress a line, shields up
STANCE_CYCLE_CHARGE = "cycle_charge"  # cavalry only -- hit, ride through, again
STANCE_FIRING_LINE = "firing_line"  # ranged only -- dress a shooting line and
                                    # shoot from it, rather than each bowman
                                    # walking at whoever he personally picked

# Which stances a given unit type may be given. Everything gets the two basic
# ones; the specialised stances are the reason each arm plays differently.
STANCES_FOR_TYPE = {
    "infantry": (STANCE_ADVANCE, STANCE_HOLD, STANCE_CHARGE, STANCE_SHIELD_WALL),
    "cavalry": (STANCE_ADVANCE, STANCE_HOLD, STANCE_CHARGE, STANCE_CYCLE_CHARGE),
    "archer": (STANCE_ADVANCE, STANCE_HOLD, STANCE_CHARGE, STANCE_FIRING_LINE),
    # No shield to raise and no horse to wheel: an Assassin only ever advances,
    # holds, or runs in.
    "assassin": (STANCE_ADVANCE, STANCE_HOLD, STANCE_CHARGE),
    "commander": (STANCE_ADVANCE, STANCE_HOLD, STANCE_CHARGE),
    # Species signature units. The two that carry a shield can dress a line;
    # the Berserker (no shield), Bladesinger (no shield) and Sapper (a bomb at
    # range) fall through to the basic three via allowed_stances' default, but
    # are listed here anyway so this table reads as the whole roster rather
    # than the half of it somebody remembered to write down.
    "bannerman": (STANCE_ADVANCE, STANCE_HOLD, STANCE_CHARGE, STANCE_SHIELD_WALL),
    "shieldwarden": (STANCE_ADVANCE, STANCE_HOLD, STANCE_CHARGE, STANCE_SHIELD_WALL),
    "berserker": (STANCE_ADVANCE, STANCE_HOLD, STANCE_CHARGE),
    "bladesinger": (STANCE_ADVANCE, STANCE_HOLD, STANCE_CHARGE),
    "sapper": (STANCE_ADVANCE, STANCE_HOLD, STANCE_CHARGE, STANCE_FIRING_LINE),
}

STANCE_LABEL = {
    STANCE_ADVANCE: "Advance",
    STANCE_HOLD: "Hold Here",
    STANCE_CHARGE: "Charge",
    STANCE_SHIELD_WALL: "Shield Wall",
    STANCE_CYCLE_CHARGE: "Charge & Regroup",
    STANCE_FIRING_LINE: "Firing Line",
}

# Stances in which a unit refuses to walk toward a distant enemy. It still
# fights whatever comes within reach -- holding ground is not passivity.
HOLDING_STANCES = (STANCE_HOLD, STANCE_SHIELD_WALL, STANCE_FIRING_LINE)

# Stances that put a unit in an assigned place in a formation (Unit.
# formation_slot). Both are laid out by the GROUP -- no unit can work out its
# own place in a line -- so both are formed by a Battle method at the moment
# the order is issued, and both clear the slot when the order is replaced.
SLOTTED_STANCES = (STANCE_SHIELD_WALL, STANCE_FIRING_LINE)

# --- stance modifiers ---------------------------------------------------------
# Multipliers on the unit's own numbers. `block_add` is an addend on block
# chance (a probability, so it is capped in Unit.effective_block, not scaled).
STANCE_MODS = {
    STANCE_ADVANCE: {},
    STANCE_HOLD: {
        "block_add": 0.10,      # set, shield up, watching them come
    },
    STANCE_CHARGE: {
        "speed_mult": 1.30,
        "damage_mult": 1.15,
        "block_mult": 0.55,     # you cannot run at someone and guard properly
    },
    STANCE_SHIELD_WALL: {
        "block_add": 0.22,
        "damage_mult": 0.85,    # a wall is for holding, not for killing
    },
    STANCE_CYCLE_CHARGE: {
        "speed_mult": 1.15,
    },
    # Deliberately EMPTY. A firing line changes where bowmen stand, not how
    # hard they shoot: this whole pass is movement, and quietly hanging a
    # damage or accuracy bonus off it would re-fit the archer tuning that
    # HANDOFF S26 is still an open question about.
    STANCE_FIRING_LINE: {},
}

# A braced unit takes this fraction of a cavalry charge's impact damage (and of
# its splash). Set low on purpose: bracing infantry against horse is the single
# clearest counter in the order set, and if it only shaved a little off, nobody
# would ever spend an order on it.
BRACE_CHARGE_MULT = 0.42

# --- shield wall --------------------------------------------------------------
WALL_SPACING = 13.0       # px between neighbours in the line -- just over two
                          # infantry radii, so a formed wall is shoulder to
                          # shoulder without units fighting the collision solver
WALL_MAX_RANK = 18        # units per rank before a second rank forms behind
WALL_RANK_GAP = 15.0      # px between ranks
WALL_SLOT_TOLERANCE = 4.0  # how close counts as "in position"

# Cohesion: a wall is only worth anything while it is CONTIGUOUS. Each formed
# neighbour within reach adds to the block bonus, so a wall that has been broken
# up, or one made of a handful of stragglers, protects far less than a solid
# line. This is what makes flanking and breaking a wall meaningful rather than
# the stance being a flat buff.
WALL_LINK_DIST = 20.0
WALL_COHESION_PER_NEIGHBOUR = 0.06
WALL_COHESION_MAX = 0.12

# --- firing line ---------------------------------------------------------------
# Wider spacing and a much wider frontage than a shield wall, because the two
# formations are for opposite things: a wall is a solid face that stops
# something, a shooting line is frontage -- every bow that can see the enemy is
# a bow that counts, and men packed shoulder to shoulder mostly block each
# other. Ranks are staggered by half a spacing so a second-rank bowman is
# looking down a gap rather than at the back of the man in front.
FIRE_SPACING = 21.0
FIRE_MAX_RANK = 26        # bows per rank before another forms behind
FIRE_RANK_GAP = 19.0
FIRE_SLOT_TOLERANCE = 5.0
# How far the line may drift from its slots before the order AI dresses it
# again -- a line that has been shoved about by a charge should re-form, but
# re-forming every decision tick would have it permanently walking.
FIRE_REFORM_DIST = 45.0
# Hysteresis on entering/leaving the line. Without it archers flapped between
# "in range, form up" and "out of range, advance" every decision tick as the
# enemy milled about at the edge of their reach -- measured, a line formed and
# dissolved three times in twenty-five seconds and spent the whole fight
# walking. A formed line stays formed until the enemy is this much past its
# reach, which is also how a real line behaves: it does not dissolve because
# the enemy stepped back a pace.
FIRE_HOLD_SLACK = 1.18

# --- volley (fire discipline) -------------------------------------------------
# Holding fire is not just "stop shooting" -- archers who hold draw and wait,
# and the release hits far harder. Without this, "Hold Fire" would be a button
# with no upside: arrows are unlimited and damage lands on release, so telling
# archers to stop is otherwise pure loss.
VOLLEY_FULL_SECONDS = 4.0   # holding this long builds a full-strength volley
VOLLEY_DAMAGE_BONUS = 1.50  # up to +150% on the first shot after releasing
VOLLEY_ACCURACY_BONUS = 0.15  # ...and a steadier aim for it


def stance_mod(stance, key, default=1.0):
    return STANCE_MODS.get(stance, {}).get(key, default)


def allowed_stances(type_key):
    """Stances `type_key` may be given -- the UI greys out the rest, and the
    order AI never issues one a unit could not carry out."""
    return STANCES_FOR_TYPE.get(type_key, (STANCE_ADVANCE, STANCE_HOLD, STANCE_CHARGE))


def can_take_stance(unit, stance):
    return stance in allowed_stances(getattr(unit, "type_key", ""))
