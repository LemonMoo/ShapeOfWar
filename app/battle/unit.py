"""A single soldier.

Behavior is intentionally simple (seek nearest enemy, attack when in range)
and isolated in ``update`` so it's easy to swap for smarter AI, formations, or
morale-driven routing later.
"""
import math

from app.battle.unit_types import UNIT_TYPES


class Unit:
    def __init__(self, type_key, faction, x, y, strength_mult=1.0):
        t = UNIT_TYPES.get(type_key, UNIT_TYPES["infantry"])
        self.type_key = type_key
        self.type = t
        self.faction = faction   # the owning Army
        self.x = x
        self.y = y
        # strength_mult scales this unit's combat power relative to the
        # shared UNIT_TYPES baseline (both HP and damage dealt) — e.g. a
        # wildland garrison's soldiers, per app/ui/app.py's
        # stage_wildland_battle, without mutating the shared type data
        # every other army also reads from.
        self.max_hp = t["max_hp"] * strength_mult
        self.damage = t["damage"] * strength_mult
        self.hp = self.max_hp
        self._cd = 0.0           # attack cooldown timer
        self.target = None
        self.vx = 0.0            # bounce velocity (from collisions), decays
        self.vy = 0.0

    @property
    def alive(self):
        return self.hp > 0

    def update(self, dt, battle):
        if not self.alive:
            return
        self._cd = max(0.0, self._cd - dt)

        if self.target is None or not self.target.alive:
            self.target = battle.nearest_enemy(self)
        if self.target is None:
            return

        dx = self.target.x - self.x
        dy = self.target.y - self.y
        dist = math.hypot(dx, dy) or 1e-6

        if dist > self.type["range"]:
            move = self.type["speed"] * dt
            self.x += dx / dist * move
            self.y += dy / dist * move
        elif self._cd <= 0:
            self.target.hp -= self.damage
            self._cd = self.type["cooldown"]
            if self.type.get("ranged"):
                battle.spawn_projectile(self.x, self.y,
                                        self.target.x, self.target.y,
                                        self.faction.color)
            if battle.on_attack:
                battle.on_attack(self, self.target)
