"""The micro-scale battle simulation (pure logic, no rendering)."""
import math
import random
from collections import Counter

from app.core.events import bus
from app.battle.unit import Unit

# Collision tuning.
_BOUNCE = 7.0      # impulse per pixel of overlap — higher = springier
_FRICTION = 0.80   # per-frame velocity damping so bounces settle quickly
_CELL = 16         # spatial-hash cell size (px); ~2x a unit diameter
_ARROW_SPEED = 320  # px/sec — how fast an arrow travels to its target

PLANNING_ZONE_MARGIN = 24   # px kept clear of the midline on each side, so a
                            # dragged unit can never land in/past the enemy's half

# --- scored target selection (see choose_target) ---------------------------
_RETARGET_INTERVAL = 0.6    # seconds a unit keeps a target before re-evaluating
_FINISH_WEIGHT = 40.0       # score bonus for a target at 0 HP (prefer finishing
                            # the wounded); scaled by how hurt it is
_CROWD_PENALTY = 18.0       # score penalty per ally already targeting an enemy
                            # (soft anti-dogpile — spread the focus fire out)
_CAVALRY_ARCHER_BONUS = 30.0  # cavalry lean toward archers: soft, undefended,
                              # ideal couch targets


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


class Effect:
    """A brief, purely-cosmetic combat flourish at a fixed spot — a shield
    ``block`` spark or a cavalry ``impact`` burst — that fades over ``dur``
    seconds. The view reads ``t/dur`` for its animation phase. Damage/logic
    already happened; this is only feedback."""
    __slots__ = ("x", "y", "kind", "color", "t", "dur", "size")

    def __init__(self, x, y, kind, color, dur, size=0.0):
        self.x, self.y = x, y
        self.kind = kind          # "block" | "dodge" | "impact" | "shock"
        self.color = color
        self.t = 0.0
        self.dur = dur
        # Only "shock" uses this: the real AOE radius of the charge that spawned
        # it, so the drawn ring matches the ground actually hit rather than
        # being a fixed decorative size.
        self.size = size

    def update(self, dt):
        self.t += dt
        return self.t < self.dur      # False -> faded, drop it


class Army:
    """One side in a battle. ``side`` is 0 or 1. ``species`` (may be None for a
    neutral wildland garrison) decides every soldier's species traits -- see
    app/world/lexicon.py's SPECIES and Unit.__init__."""

    def __init__(self, name, color, side=0, species=None):
        self.name = name
        self.color = color
        self.side = side
        self.species = species
        self.units = []
        self.commander = None        # set by Battle.deploy
        self.commander_lost = False  # latched once he falls -- see morale

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
        self.effects = []      # block sparks / charge impacts (cosmetic)
        self.on_attack = None  # optional hook set by the view for log/effects
        self._threat = Counter()  # enemy -> # of living units currently targeting
                                  # it; rebuilt each update() for choose_target

    def spawn_projectile(self, sx, sy, tx, ty, color):
        self.projectiles.append(Projectile(sx, sy, tx, ty, color))

    def spawn_effect(self, x, y, kind, color, dur=0.28, size=0.0):
        self.effects.append(Effect(x, y, kind, color, dur, size))

    def threat_count(self, enemy):
        """How many living units already target ``enemy`` (see choose_target's
        soft anti-dogpile term). Snapshot from the last update() tick."""
        return self._threat.get(enemy, 0)

    def deploy(self, army, composition, side, strength_mult=1.0, with_commander=True):
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
            army.units.append(Unit(type_key, army, x, y, strength_mult,
                                   species=getattr(army, "species", None)))

        if with_commander:
            # Behind his own formation, not in front of it: he reaches the
            # fight after the lines meet, and cutting to the enemy's commander
            # means going through their army first -- which is what makes
            # killing one an achievement rather than an opening move. Added on
            # top of the composition, never taken out of it.
            back = x0 - 40 if side == 0 else x0 + 40
            cmd = Unit("commander", army, back, self.height / 2, strength_mult,
                       species=getattr(army, "species", None))
            cmd.is_commander = True
            army.units.append(cmd)
            army.commander = cmd
        self.armies.append(army)
        return army

    def zone_bounds(self, side):
        """(x_min, x_max) a side's units may occupy during the pre-battle
        planning phase (app/ui/battle_view.py) — confines dragging to that
        side's own half, leaving a gap at the midline so a unit can never
        be dropped in or past the opposing army's territory."""
        mid = self.width / 2
        if side == 0:
            return (0.0, mid - PLANNING_ZONE_MARGIN)
        return (mid + PLANNING_ZONE_MARGIN, self.width)

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

    def choose_target(self, unit):
        """Scored target pick — units still overwhelmingly go for whoever's
        closest, but with a few refinements over blind nearest-enemy: finish
        off the wounded, don't all dogpile one soldier, and let cavalry favor
        soft archer targets. Distance dominates the score (kept in the same
        pixel scale as the bonuses), so the overall behavior is still ''run at
        the enemy'' -- just with a bit of judgment. Throttled per-unit via
        Unit._retarget_cd so this isn't paid every frame."""
        is_cav = unit.type.get("charge")
        best, best_score = None, float("-inf")
        for army in self.armies:
            if army.side == unit.faction.side:
                continue
            for u in army.units:
                if not u.alive:
                    continue
                dist = math.hypot(u.x - unit.x, u.y - unit.y)
                score = -dist
                score += _FINISH_WEIGHT * (1.0 - u.hp / u.max_hp)
                score -= _CROWD_PENALTY * self._threat.get(u, 0)
                if is_cav and u.type.get("ranged"):
                    score += _CAVALRY_ARCHER_BONUS
                if score > best_score:
                    best, best_score = u, score
        return best or self.nearest_enemy(unit)

    # --- morale ---------------------------------------------------------------
    # A commander falling does not end the battle -- his soldiers keep fighting,
    # just far worse. Chosen over an instant rout because a rout makes every
    # engagement a single decapitation race and throws away the army balance the
    # species roster was tuned around; a lasting penalty still makes killing him
    # the most valuable thing on the field without making it the only thing.
    MORALE_DAMAGE_MULT = 0.70   # leaderless soldiers hit softer
    MORALE_SPEED_MULT = 0.85    # ...and press forward less willingly

    def _check_morale(self):
        """Latch the morale penalty onto an army the moment its commander dies.

        Applied once to each surviving soldier rather than re-checked every
        tick: update() runs many times a second across hundreds of units, and
        this only ever needs to happen on the single frame he falls."""
        for army in self.armies:
            cmd = getattr(army, "commander", None)
            if cmd is None or army.commander_lost or cmd.alive:
                continue
            army.commander_lost = True
            for u in army.units:
                if u.alive and u is not cmd:
                    u.damage *= self.MORALE_DAMAGE_MULT
                    u.speed *= self.MORALE_SPEED_MULT
            bus.emit("battle:commander_lost", {"army": army})

    def _resolve_collisions(self):
        """Push overlapping units apart and add a small springy impulse so they
        bounce instead of stacking. Uses a spatial hash to stay ~O(n)."""
        units = [u for army in self.armies for u in army.units if u.alive]

        grid = {}
        for u in units:
            grid.setdefault((int(u.x // _CELL), int(u.y // _CELL)), []).append(u)

        for u in units:
            cx, cy = int(u.x // _CELL), int(u.y // _CELL)
            ur = u.radius
            for gx in (cx - 1, cx, cx + 1):
                for gy in (cy - 1, cy, cy + 1):
                    for v in grid.get((gx, gy), ()):
                        # each unordered pair once
                        if id(v) <= id(u):
                            continue
                        dx = v.x - u.x
                        dy = v.y - u.y
                        min_d = ur + v.radius
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
                r = u.radius
                u.x = min(self.width - r, max(r, u.x))
                u.y = min(self.height - r, max(r, u.y))

    def update(self, dt):
        if self.over:
            return

        # Snapshot who's targeting whom, once, before any unit re-picks this
        # tick -- choose_target reads it for its anti-dogpile term.
        self._threat = Counter(
            u.target for army in self.armies for u in army.units
            if u.alive and u.target is not None and u.target.alive)

        for army in self.armies:
            for u in army.units:
                u.update(dt, self)

        self._check_morale()
        self._resolve_collisions()
        self._integrate(dt)
        self.projectiles = [p for p in self.projectiles if p.update(dt)]
        self.effects = [e for e in self.effects if e.update(dt)]

        standing = [a for a in self.armies if a.living]
        if len(standing) <= 1:
            self.over = True
            self.winner = standing[0] if standing else None
            bus.emit("battle:over", {"winner": self.winner})
