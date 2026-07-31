"""The order AI: gives an army the same battlefield orders a player can give.

Without this, orders would be a straight power gain for whoever is clicking --
and worse, it would quietly invalidate the species balance the roster was tuned
around (see unit_types.py), since every tournament number was measured with both
sides fighting on the default stance.

Deliberately reactive rather than clever. It reads three things off the field --
is horse coming at my infantry, am I being shot at, am I winning -- and answers
each with the one order that counters it. That is enough for the order set to
play as rock-paper-scissors against a human, and it keeps the AI legible: you
can watch a line brace as your cavalry commits and understand exactly why.

Runs on a throttle, not per-frame: orders are decisions, and re-deciding sixty
times a second would produce a line that twitches between stances instead of
committing to one.
"""
import math

from app.battle import orders

DECIDE_INTERVAL = 1.1      # seconds between decisions for one army
BRACE_RANGE = 210.0        # how close closing cavalry has to be to set a line
BRACE_MOMENTUM = 0.15      # ...and how much gallop it needs to count as a threat
PRESS_ADVANTAGE = 1.45     # outnumbering by this much means stop being careful
VOLLEY_HOLD_RANGE = 250.0  # hold fire until they are inside this


def _living(army):
    return [u for u in army.units if u.alive]


def _enemies(battle, army):
    return [u for other in battle.armies if other.side != army.side
            for u in other.units if u.alive]


def _nearest_dist(unit, group):
    if not group:
        return float("inf")
    return min(math.hypot(u.x - unit.x, u.y - unit.y) for u in group)


def _group_nearest_dist(units, group):
    """The closest any of `units` is to any of `group`.

    Measured over the whole body rather than off units[0], which is what it
    used to be. One man's nearest enemy jumps by ninety pixels the moment that
    enemy dies, and the archers' whole posture turned on that number: the line
    formed and dissolved three times in twenty-five seconds. The minimum over
    the line barely moves, because somebody in it is always the nearest."""
    if not units or not group:
        return float("inf")
    return min(_nearest_dist(u, group) for u in units)


CLOSING_RANGE = 320.0      # an approaching enemy this close is "coming at us"


def _enemy_closing(foes, x, y):
    """Is any enemy actually advancing on this point?

    `Unit.advancing` is already maintained every tick for the collision solver
    (it is what stops a locked-in melee shoving), so this is a free, honest
    read of intent rather than a guess from positions over time."""
    for u in foes:
        if not u.advancing:
            continue
        if math.hypot(u.x - x, u.y - y) <= CLOSING_RANGE:
            return True
    return False


def decide_for_army(battle, army):
    """Issue this army's orders for the current moment."""
    mine = _living(army)
    if not mine:
        return
    foes = _enemies(battle, army)
    if not foes:
        return

    # Grouped by ROLE, not by type name. This used to read `u.type_key ==
    # "infantry"` and friends, which silently left every species signature unit
    # unordered -- a Shieldwarden whose entire value is the line taking less
    # punishment would advance out of the line it was protecting the moment
    # that line braced. Nothing about the RULES below changed; they now simply
    # reach the units they were always written for, including any added later.
    infantry = [u for u in mine if _is_foot(u)]
    cavalry = [u for u in mine if u.type.get("charge")]
    # Ranged units are ordered per TYPE rather than as one block, because the
    # rule turns on the group's own reach -- a Sapper (110) folded in with
    # Archers (180) would have the whole lot standing at a range only one of
    # them can shoot from.
    shot_groups = {}
    for u in mine:
        if u._ranged and not u.is_commander:
            shot_groups.setdefault(u.type_key, []).append(u)

    enemy_horse = [u for u in foes if u.type.get("charge")]
    enemy_archers = [u for u in foes if u._ranged]
    winning = len(mine) >= len(foes) * PRESS_ADVANTAGE

    # --- infantry ------------------------------------------------------------
    if infantry:
        centre_x = sum(u.x for u in infantry) / len(infantry)
        centre_y = sum(u.y for u in infantry) / len(infantry)

        charging_at_us = [u for u in enemy_horse
                          if u.charge >= BRACE_MOMENTUM
                          and math.hypot(u.x - centre_x, u.y - centre_y) <= BRACE_RANGE]
        # Defensive stances are issued ONLY against a threat that is actually
        # arriving, never as a default posture. Measured the hard way: an
        # earlier version walled up whenever enemy foot was closing, and since
        # a wall stands still, it cost the melee-mass species every match it
        # played (Orcs 0%, Elves 100%, spread 100pts against a 46pt baseline).
        # Anything that delays contact is a tax on the side whose whole plan is
        # to reach the enemy, so the AI now pays it only to stop a charge --
        # which is short, situational, and what bracing is actually for.
        # Note what is NOT here: charging out of archer fire. Charge trades
        # guard for speed (block_mult), and for the shield-reliant species that
        # is a catastrophe -- issuing it under fire took Dwarves from 71% to 4%.
        # Walking in with shields up beats sprinting in without them.
        if charging_at_us and not winning:
            stance = orders.STANCE_HOLD          # set to receive horse
        elif winning:
            stance = orders.STANCE_CHARGE        # press the advantage
        else:
            stance = orders.STANCE_ADVANCE
        _apply_stance(battle, infantry, stance)

    # --- cavalry -------------------------------------------------------------
    # Riders cycle by default: it is simply how horse is worth using, and an AI
    # that let them bog down in a scrum would be throwing them away.
    if cavalry:
        _apply_stance(battle, cavalry, orders.STANCE_CYCLE_CHARGE)

    # --- archers -------------------------------------------------------------
    for archers in shot_groups.values():
        near = _group_nearest_dist(archers, foes)
        reach = archers[0].attack_range
        # Hold the volley while they are still crossing the open ground, then
        # loose it as they come inside range -- the same play a human gets.
        # Only ever hold when someone is actually approaching, for the same
        # reason infantry only brace when charged: archers who hold fire at a
        # stationary enemy are just archers not shooting.
        approaching = _enemy_closing(foes, archers[0].x, archers[0].y)
        want_fire = near <= VOLLEY_HOLD_RANGE or not approaching
        if any(u.fire_at_will != want_fire for u in archers):
            battle.issue_fire_discipline(archers, want_fire)
        # Stand and shoot only while there is something in range to shoot at;
        # otherwise close the distance. Comparing against the real reach (not a
        # multiple of it) matters -- holding just outside your own range is the
        # one position where an archer is worth nothing at all.
        #
        # Standing to shoot means standing in a LINE. Bowmen each walking at
        # whoever they personally picked ended up in a knot, which wastes the
        # frontage that is the whole point of massed shooting -- so the stance
        # for "we are shooting now" is the firing line, not a plain hold.
        # Hysteresis, not a bare comparison: see orders.FIRE_HOLD_SLACK for
        # what a bare one did. But a formed line may only hold SHORT of its own
        # reach while the enemy is actually coming on -- two lines standing two
        # hundred pixels apart, neither able to shoot and neither willing to
        # move, is a battle that never ends, and that is exactly what happened
        # (dev/test_battle_terrain's swamp fight ran past 200 simulated
        # seconds). If nothing is in reach and nobody is closing, walk.
        formed = archers[0].stance == orders.STANCE_FIRING_LINE
        if near <= reach:
            stance = orders.STANCE_FIRING_LINE
        elif formed and approaching and near <= reach * orders.FIRE_HOLD_SLACK:
            stance = orders.STANCE_FIRING_LINE
        else:
            stance = orders.STANCE_ADVANCE
        _apply_stance(battle, archers, stance)
        # A line that has been shoved about -- by a charge, by its own army
        # backing into it -- is dressed again. Only when it has genuinely
        # drifted: re-forming every decision tick would leave it permanently
        # walking to a new slot instead of standing in one and shooting.
        if stance == orders.STANCE_FIRING_LINE and _line_has_drifted(archers):
            battle.form_firing_line(archers)


def _line_has_drifted(units):
    """Is the formation far enough out of its own slots to be worth dressing
    again? True also when it has no slots at all, which is how a group that was
    already in this stance before anything laid one out gets one."""
    drift = 0.0
    n = 0
    for u in units:
        if u.formation_slot is None:
            return True
        drift += math.hypot(u.formation_slot[0] - u.x, u.formation_slot[1] - u.y)
        n += 1
    return n > 0 and drift / n > orders.FIRE_REFORM_DIST


def _is_foot(unit):
    """A soldier who fights in the line: on foot, in melee, and not off doing
    something else.

    Commanders are excluded because they have their own screening rule
    (Unit._screened), and hunters -- the Goblin Assassin -- because ordering
    one is pointless: it ignores everything but enemy bowmen and its whole
    value is arriving among them, which no stance helps with."""
    return (not unit._ranged and not unit.type.get("charge")
            and not unit.is_commander and not unit.type.get("hunts_ranged"))


def _apply_stance(battle, units, stance):
    """Only re-issue when something actually changes -- re-forming a shield wall
    every decision tick would reset every slot and keep the line permanently
    walking to a new position instead of standing in it."""
    if all(u.stance == stance for u in units):
        return
    battle.issue_stance(units, stance)
