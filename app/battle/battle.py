"""The micro-scale battle simulation (pure logic, no rendering)."""
import math
import random

from app.core.events import bus
from app.battle.unit import Unit

# Collision tuning.
_BOUNCE = 7.0      # impulse per pixel of overlap — higher = springier
_FRICTION = 0.80   # per-frame velocity damping so bounces settle quickly
_CELL = 16         # spatial-hash cell size (px); ~2x a unit diameter
_ARROW_SPEED = 320  # px/sec — how fast an arrow travels to its target


class Projectile:
    """A cosmetic arrow flying from a shooter to where its target was. Purely
    visual (damage is already applied on the shot); rendered as a '.'."""
    __slots__ = ("sx", "sy", "tx", "ty", "x", "y", "color", "t", "dur")

    def __init__(self, sx, sy, tx, ty, color):
        self.sx, self.sy, self.tx, self.ty = sx, sy, tx, ty
        self.x, self.y = sx, sy
        self.color = color
        self.t = 0.0
        self.dur = max(0.05, math.hypot(tx - sx, ty - sy) / _ARROW_SPEED)

    def update(self, dt):
        self.t += dt
        f = min(1.0, self.t / self.dur)
        self.x = self.sx + (self.tx - self.sx) * f
        self.y = self.sy + (self.ty - self.sy) * f
        return self.t < self.dur      # False -> arrived, drop it


class Army:
    """One side in a battle. ``side`` is 0 or 1."""

    def __init__(self, name, color, side=0):
        self.name = name
        self.color = color
        self.side = side
        self.units = []

    @property
    def living(self):
        return [u for u in self.units if u.alive]


class Battle:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.armies = []
        self.over = False
        self.winner = None
        self.projectiles = []  # in-flight arrows (cosmetic)
        self.on_attack = None  # optional hook set by the view for log/effects

    def spawn_projectile(self, sx, sy, tx, ty, color):
        self.projectiles.append(Projectile(sx, sy, tx, ty, color))

    def deploy(self, army, composition, side, strength_mult=1.0):
        """Place an army in a grid along one side from a composition dict
        ``{unit_type: count}``. ``strength_mult`` scales every spawned
        unit's combat power (see Unit) — used for a wildland garrison's
        weaker soldiers, 1.0 (no change) for a normal nation's army."""
        army.side = side
        x0 = self.width * 0.12 if side == 0 else self.width * 0.88
        entries = []
        for type_key, count in composition.items():
            entries.extend([type_key] * count)

        rows = max(1, math.ceil(math.sqrt(len(entries))))
        for i, type_key in enumerate(entries):
            col = i // rows
            row = i % rows
            jitter = lambda: (random.random() - 0.5) * 8
            x = x0 + (col * 16 if side == 0 else -col * 16) + jitter()
            y = self.height / 2 + (row - rows / 2) * 16 + jitter()
            army.units.append(Unit(type_key, army, x, y, strength_mult))
        self.armies.append(army)
        return army

    def nearest_enemy(self, unit):
        best, best_d = None, float("inf")
        for army in self.armies:
            if army.side == unit.faction.side:
                continue
            for u in army.units:
                if not u.alive:
                    continue
                d = (u.x - unit.x) ** 2 + (u.y - unit.y) ** 2
                if d < best_d:
                    best, best_d = u, d
        return best

    def _resolve_collisions(self):
        """Push overlapping units apart and add a small springy impulse so they
        bounce instead of stacking. Uses a spatial hash to stay ~O(n)."""
        units = [u for army in self.armies for u in army.units if u.alive]

        grid = {}
        for u in units:
            grid.setdefault((int(u.x // _CELL), int(u.y // _CELL)), []).append(u)

        for u in units:
            cx, cy = int(u.x // _CELL), int(u.y // _CELL)
            ur = u.type["radius"]
            for gx in (cx - 1, cx, cx + 1):
                for gy in (cy - 1, cy, cy + 1):
                    for v in grid.get((gx, gy), ()):
                        # each unordered pair once
                        if id(v) <= id(u):
                            continue
                        dx = v.x - u.x
                        dy = v.y - u.y
                        min_d = ur + v.type["radius"]
                        d2 = dx * dx + dy * dy
                        if d2 >= min_d * min_d:
                            continue
                        if d2 > 1e-9:
                            d = math.sqrt(d2)
                            nx, ny = dx / d, dy / d
                            overlap = min_d - d
                        else:  # exactly overlapping — pick a random split
                            ang = random.random() * math.tau
                            nx, ny = math.cos(ang), math.sin(ang)
                            overlap = min_d
                        # hard separation (split the overlap)
                        push = overlap * 0.5
                        u.x -= nx * push
                        u.y -= ny * push
                        v.x += nx * push
                        v.y += ny * push
                        # springy impulse
                        imp = overlap * _BOUNCE
                        u.vx -= nx * imp
                        u.vy -= ny * imp
                        v.vx += nx * imp
                        v.vy += ny * imp

    def _integrate(self, dt):
        """Apply bounce velocity, damp it, and keep units on the field."""
        for army in self.armies:
            for u in army.units:
                if not u.alive:
                    continue
                u.x += u.vx * dt
                u.y += u.vy * dt
                u.vx *= _FRICTION
                u.vy *= _FRICTION
                r = u.type["radius"]
                u.x = min(self.width - r, max(r, u.x))
                u.y = min(self.height - r, max(r, u.y))

    def update(self, dt):
        if self.over:
            return
        for army in self.armies:
            for u in army.units:
                u.update(dt, self)

        self._resolve_collisions()
        self._integrate(dt)
        self.projectiles = [p for p in self.projectiles if p.update(dt)]

        standing = [a for a in self.armies if a.living]
        if len(standing) <= 1:
            self.over = True
            self.winner = standing[0] if standing else None
            bus.emit("battle:over", {"winner": self.winner})
