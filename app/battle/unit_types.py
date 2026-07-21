"""Unit archetypes — pure data. Add a new type here and it's immediately
usable by any army. ``shape`` references a key in the shape registry.

Speeds/ranges are in canvas pixels; times in seconds.
  ``ranged``    : True fires an animated arrow ('.') at the target on each hit.
  ``equipment`` : list of hand-held markers drawn by the battle view —
                  "sword" ('t', right hand) and "shield" ('o', left hand).
"""
UNIT_TYPES = {
    "infantry": {
        "name": "Infantry", "shape": "circle", "radius": 5,
        "max_hp": 30, "speed": 34, "range": 14, "damage": 8, "cooldown": 0.6,
        "ranged": False, "equipment": ["sword", "shield"],
    },
    "cavalry": {
        "name": "Cavalry", "shape": "triangle", "radius": 6,
        "max_hp": 26, "speed": 62, "range": 12, "damage": 10, "cooldown": 0.5,
        "ranged": False, "equipment": ["sword"],
    },
    "archer": {
        "name": "Archer", "shape": "square", "radius": 5,
        "max_hp": 20, "speed": 30, "range": 90, "damage": 6, "cooldown": 0.9,
        "ranged": True, "equipment": [],
    },
}
