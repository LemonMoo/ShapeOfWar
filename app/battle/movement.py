"""How a soldier walks, as opposed to who it is fighting.

Until this module existed there was nothing between "choose_target picked that
man" and "add speed*dt toward him". Every soldier ran at its own enemy in a
straight line, through whatever stood in the way, and the collision solver
turned the consequences into the shape armies actually had: a blob.

Three terms, in the order they matter:

  seek         where the unit wants to go (its target, its slot, its move
               order) -- supplied by the caller, since only the caller knows
               which of those applies.
  separation   allies inside its personal space push it away, so a line stops
               compressing into a knot as it advances. This is the whole of
               "less swarmy": a formation is a spacing, and nothing was
               maintaining one.
  avoidance    an ally standing in the short cone directly ahead is stepped
               AROUND, on the side it is not on, rather than walked into and
               shoved through.

Deliberately steering rather than pathfinding. This runs per advancing unit per
tick inside a 16.7ms frame budget across hundreds of soldiers; a real path
search is out of the question and would also be the wrong answer -- a soldier
does not plan a route around his neighbour, he leans past him. What it costs is
a handful of arithmetic ops against a grid the battle already builds.

Two properties worth keeping if this is ever rewritten:

  * The deflection is CAPPED (MAX_DEFLECT_COS). Steering that can turn a unit
    more than about sixty degrees off its objective produces soldiers who
    orbit each other instead of advancing, and an army that never closes is a
    worse failure than an army that swarms.
  * Units already in contact do not steer at all. They are exactly where the
    crowd is densest, so skipping them is most of the cost saved -- and a man
    swinging a sword is not manoeuvring.
"""
import math

from app.battle import roles

# --- separation ---------------------------------------------------------------
# Measured centre to centre, ON TOP of the two bodies' radii, so this is real
# elbow room rather than a bigger collision radius. At 11px between two ordinary
# soldiers (radius 5) a line stands shoulder to shoulder without fighting the
# collision solver, which is holding them at 10.
PERSONAL_SPACE = 9.0
SEPARATION_WEIGHT = 1.15

# --- avoidance ----------------------------------------------------------------
# How far ahead an ally counts as being in the way, and how narrow "ahead" is.
# The cone is deliberately tight: a wide one makes a unit swerve for allies it
# would comfortably pass, which reads as drifting rather than as stepping
# around someone.
AVOID_DIST = 30.0
AVOID_CONE_COS = 0.82        # ~35 degrees off the direction of travel
AVOID_WEIGHT = 1.30

# Steering may not turn a unit more than this far off its objective (cosine of
# the angle). See the module note -- an army that circles is worse than one
# that clumps.
MAX_DEFLECT_COS = 0.5        # 60 degrees

# --- anti-swarm ---------------------------------------------------------------
# How many allies may be in contact with one enemy before the rest stop trying
# to reach it themselves. Roughly how many bodies physically fit around one
# soldier and can still swing: beyond that the extra men are pushing, not
# fighting. Choose_target's _CROWD_PENALTY is the same idea applied to who a
# unit picks; this is the half that governs where it stands.
CONTACT_CAP = 3
# A unit held off a mobbed enemy still closes to this far past its own reach --
# it forms the second rank, right behind the fighting, and steps in the moment
# a place opens. Standing further back would read as hanging back from the
# fight, which is not what is being asked for.
SWARM_STANDOFF = 16.0

# --- infiltration ---------------------------------------------------------------
# An Assassin's whole value is arriving among the bowmen, and what has always
# killed it is crossing the line in front of them (HANDOFF S4 #3: "they die
# crossing the field"). So for this role ENEMY bodies -- every one except the
# one it is going for -- are obstacles to swing wide around too. Wider than the
# ally cone, because going around a formation means committing to the detour
# early rather than brushing along its face.
INFILTRATE_AVOID_DIST = 52.0
INFILTRATE_WEIGHT = 1.9


def _neighbours(unit, battle, enemies=False):
    """Living units near enough to matter, from the battle's per-tick grid.

    Allies are same-SIDE rather than same-army: two allied armies on one side
    are one formation as far as walking into each other is concerned. Enemies
    are included only for an infiltrator, and its own target never counts as an
    obstacle -- it is where the unit is trying to get to.

    Yields (other, is_ally) pairs."""
    grid = getattr(battle, "_move_grid", None)
    if not grid:
        return ()
    cell = battle.MOVE_CELL
    cx, cy = int(unit.x // cell), int(unit.y // cell)
    side = unit.faction.side
    target = unit.target
    near = []
    for gx in (cx - 1, cx, cx + 1):
        for gy in (cy - 1, cy, cy + 1):
            for other in grid.get((gx, gy), ()):
                if other is unit or not other.alive:
                    continue
                if other.faction.side == side:
                    near.append((other, True))
                elif enemies and other is not target:
                    near.append((other, False))
    return near


def steer(unit, dx, dy, battle):
    """The direction `unit` should actually walk this tick, given that it wants
    to go (`dx`, `dy`) -- a unit vector. Returns a unit vector.

    A unit type may opt out with `no_cohesion` (the Orcish Berserker, whose
    whole character is that he does not keep a line)."""
    infiltrating = unit.type.get("role") == roles.INFILTRATOR
    if unit.type.get("no_cohesion") and not infiltrating:
        return dx, dy

    sx = sy = 0.0          # separation
    ax = ay = 0.0          # avoidance
    for other, is_ally in _neighbours(unit, battle, enemies=infiltrating):
        ox, oy = other.x - unit.x, other.y - unit.y
        d2 = ox * ox + oy * oy
        if d2 < 1e-9:
            continue
        d = math.sqrt(d2)
        space = unit.radius + other.radius + PERSONAL_SPACE
        if is_ally and d < space:
            # Linear falloff: an ally at arm's length barely registers, one
            # standing on top of you dominates. Enemies are never pushed away
            # from -- backing off an enemy is retreating, not spacing.
            push = (space - d) / space
            sx -= ox / d * push
            sy -= oy / d * push
        reach = AVOID_DIST if is_ally else INFILTRATE_AVOID_DIST
        if d < reach:
            # Only what is genuinely in front, and only close enough to be an
            # obstacle rather than a distant body in the same direction.
            ahead = (ox * dx + oy * dy) / d
            if ahead >= AVOID_CONE_COS:
                # Step to the side the body is NOT on: the sign of the cross
                # product says which side it stands, and the perpendicular
                # away from it is where the gap is.
                cross = dx * oy - dy * ox
                side = -1.0 if cross > 0 else 1.0
                weight = (reach - d) / reach * ahead
                if not is_ally:
                    weight *= INFILTRATE_WEIGHT
                ax += -dy * side * weight
                ay += dx * side * weight

    vx = dx + SEPARATION_WEIGHT * sx + AVOID_WEIGHT * ax
    vy = dy + SEPARATION_WEIGHT * sy + AVOID_WEIGHT * ay
    mag = math.hypot(vx, vy)
    if mag < 1e-6:
        return dx, dy
    vx, vy = vx / mag, vy / mag

    # Cap the deflection. Past the cap, take the nearest heading that is
    # within it -- rotate the desired direction toward the steered one by
    # exactly the maximum, rather than falling back to the raw seek, so a unit
    # that is genuinely boxed in still leans the way the gap is.
    dot = vx * dx + vy * dy
    if dot < MAX_DEFLECT_COS:
        cross = dx * vy - dy * vx
        sign = 1.0 if cross > 0 else -1.0
        ang = math.acos(max(-1.0, min(1.0, MAX_DEFLECT_COS))) * sign
        ca, sa = math.cos(ang), math.sin(ang)
        vx, vy = dx * ca - dy * sa, dx * sa + dy * ca
    return vx, vy


def mobbed(unit, battle):
    """True if this unit's target already has as many of the unit's own side in
    contact with it as can usefully fight it (CONTACT_CAP).

    Read off the battle's per-tick contact snapshot, so it costs a dict lookup
    -- the counting itself is one pass over the field per tick, shared by every
    unit that asks."""
    target = unit.target
    if target is None:
        return False
    return battle.contact_count(target) >= CONTACT_CAP
