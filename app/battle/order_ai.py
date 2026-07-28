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

    infantry = [u for u in mine if u.type_key == "infantry"]
    cavalry = [u for u in mine if u.type_key == "cavalry"]
    archers = [u for u in mine if u.type_key == "archer"]

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
    if archers:
        near = _nearest_dist(archers[0], foes)
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
        stance = orders.STANCE_HOLD if near <= reach else orders.STANCE_ADVANCE
        _apply_stance(battle, archers, stance)


def _apply_stance(battle, units, stance):
    """Only re-issue when something actually changes -- re-forming a shield wall
    every decision tick would reset every slot and keep the line permanently
    walking to a new position instead of standing in it."""
    if all(u.stance == stance for u in units):
        return
    battle.issue_stance(units, stance)
