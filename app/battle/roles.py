"""What a special unit DOES, as opposed to what its numbers are.

The roster in unit_types.py has always described six specialists, and every one
of them then walked at its own nearest enemy exactly like a swordsman. That is
the whole of "special units feel like another swordsman or archer": their stats
were special and their behaviour was not.

Six roles, each a small, legible departure from the default. None of them
changes a stat -- a role decides where a unit stands and what it picks to
fight, and nothing else.

  anchor       (Shieldwarden) holds the front of its own line, between its
               allies and the enemy, so the aura it exists for covers the men
               it exists to protect instead of walking away from them.
  banner       (Standard Bearer) stands with the body of the army, a little
               behind its face, where its aura covers the most men. It never
               chases anything.
  flanker      (Bladesinger) works the edges of the enemy formation rather
               than grinding at the middle of it. Fast, evasive, and worth
               nothing in a press.
  frenzied     (Berserker) the opposite: goes where the fighting is thickest
               and keeps no formation at all.
  bombard      (Sapper) drops its bomb on the thickest knot within reach. Its
               whole design is splash; bombing whichever single soldier was
               nearest wasted it.
  infiltrator  (Assassin) already hunts bowmen -- what killed it was crossing
               the line to reach them. It now goes AROUND a formation instead
               of into it.

Deliberately scoped to movement and target choice, and deliberately NOT
implemented as new stances: the order AI is on record as measuring worse every
time it was made richer (HANDOFF S4 #4), and a role is a property of the unit,
not an order somebody gives it.
"""

ANCHOR = "anchor"
BANNER = "banner"
FLANKER = "flanker"
FRENZIED = "frenzied"
BOMBARD = "bombard"
INFILTRATOR = "infiltrator"

# --- where a station-keeping unit stands --------------------------------------
# Both are measured from the body of its own army, along the direction of the
# enemy: an anchor stands in FRONT of it, a banner a little behind. Neither is a
# fixed spot on the field -- the army moves, and so do they.
ANCHOR_LEAD = 46.0        # px in front of the army's centre of mass
BANNER_BACK = 30.0        # px behind it
STATION_TOLERANCE = 18.0  # close enough; below this they stand still rather
                          # than jittering toward a point that moves every tick

# A man hurrying to his place in the line moves faster than the line does.
# Without this the whole idea fails on arithmetic: a Shieldwarden walks at 26
# where the swordsmen it is meant to stand in front of walk at 34, so an
# advancing line leaves it further behind every second -- measured at 92px
# BEHIND its own army's centre while trying to stand 46px in front of it.
#
# Capping this at the ARMY'S pace was tried first and does not work: matching
# the line's speed only stops the gap growing, it never closes one, and the
# warden stayed 44px adrift. It needs to be able to overtake the line to get in
# front of it.
#
# This is not a speed bonus, and the three conditions are what keep it honest:
# it applies only while walking to a station, only while OUT of contact, and
# it stops entirely within STATION_TOLERANCE of the place. A unit using it is
# moving to a spot among its own soldiers -- never toward an enemy.
STATION_CATCHUP_MAX = 1.6

# ...and once there are this few ordinary soldiers left in the army, there is
# nothing to keep station WITH, so the role stops and the unit fights like
# anyone else. Same shape, and the same reason, as COMMANDER_LAST_STAND.
STATION_LAST_STAND = 3

# --- target-choice weights ----------------------------------------------------
# All in the same pixel scale as Battle.choose_target's distance term, since
# they are added to the same score.
FLANK_WEIGHT = 0.55       # per pixel of the candidate's distance from the
                          # enemy centre of mass -- i.e. prefer the edge of a
                          # formation, which is what a flanker is for
FRENZY_SEEK_RANGE = 260.0    # how far a Berserker will look for a thicker
                             # fight. Wide enough to cross to the next knot in
                             # a line, short enough that he does not run the
                             # length of the field past the men in front of him


def station(unit):
    """Where this unit should be standing, as an offset along the direction of
    the enemy from its own army's centre of mass -- or None if the role does
    not keep station. Positive is toward the enemy."""
    role = unit.type.get("role")
    if role == ANCHOR:
        return ANCHOR_LEAD
    if role == BANNER:
        return -BANNER_BACK
    return None
