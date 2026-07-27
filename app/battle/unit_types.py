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
    "cavalry": {
        "name": "Cavalry", "shape": "triangle", "radius": 6,
        "max_hp": 26, "speed": 72, "range": 12, "damage": 10, "cooldown": 0.5,
        "ranged": False, "equipment": ["sword"],
        "charge": True, "charge_bonus": 2.0, "melee_floor": 0.5, "charge_ramp": 1.2,
    },
    "archer": {
        "name": "Archer", "shape": "square", "radius": 5,
        "max_hp": 20, "speed": 30, "range": 90, "damage": 6, "cooldown": 0.9,
        "ranged": True, "accuracy": 0.8, "equipment": [],
    },
}
