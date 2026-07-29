"""The micro-scale battle simulation (pure logic, no rendering)."""
import math
import random
from collections import Counter

import numpy as np

from app.core.events import bus
from app.battle import order_ai, orders
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
        # Which side the player is giving orders to. Every OTHER side is driven
        # by the order AI (app/battle/order_ai.py). Left None outside a real
        # player battle -- in a headless sim or the balance tournament both
        # sides should be ordered by the same AI, or the numbers mean nothing.
        self.player_side = None
        self._order_ai_cd = 0.0

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

    # Cell size for the density scan below. Roughly the reach of a charge's
    # splash, so "the densest bin" really does mean "where one impact hits the
    # most people".
    _DENSITY_CELL = 55

    def densest_enemy(self, unit):
        """The enemy standing in the thickest knot of enemies -- what a
        regrouping rider picks for its next run (see Unit._update_cycle_charge).

        Bins enemies on a coarse grid and takes the fullest bin rather than
        clustering properly: a squadron re-picks this every few seconds across
        hundreds of units, and an approximate answer that costs one pass is
        worth far more here than an exact one that costs several."""
        bins = {}
        for army in self.armies:
            if army.side == unit.faction.side:
                continue
            for u in army.units:
                if u.alive:
                    bins.setdefault((int(u.x // self._DENSITY_CELL),
                                     int(u.y // self._DENSITY_CELL)), []).append(u)
        if not bins:
            return None
        # Fullest bin, breaking ties toward the one nearest the rider so it
        # doesn't cross the whole field past a target just as good.
        best = max(bins.values(),
                   key=lambda group: (len(group),
                                      -min(math.hypot(u.x - unit.x, u.y - unit.y)
                                           for u in group)))
        cx = sum(u.x for u in best) / len(best)
        cy = sum(u.y for u in best) / len(best)
        return min(best, key=lambda u: (u.x - cx) ** 2 + (u.y - cy) ** 2)

    # --- vectorised target selection ------------------------------------------
    # choose_target was the single biggest cost in the simulation -- 64% of it
    # at 2,400 units -- because every re-targeting unit looped over every living
    # enemy in Python. That is O(n^2): quadrupling the army raised sim cost
    # ~20x, and it, not the renderer, was what capped battle size (8,600 units
    # rendered at 48fps but simulated at 1.5).
    #
    # The enemy list is now snapshotted into numpy arrays ONCE per tick and each
    # unit scores the whole enemy army in a handful of vector operations. The
    # scoring formula is unchanged, so a unit still picks the same soldier for
    # the same reasons.
    #
    # One deliberate difference: positions are read from the start of the tick
    # rather than live mid-tick, so a unit re-targeting late in a tick no longer
    # sees the sub-pixel movement of units updated before it. `_threat` was
    # already snapshotted this way for exactly the same reason, so targeting is
    # now internally consistent rather than half-live.
    def _rebuild_target_cache(self):
        self._target_cache = {}
        sides = {a.side for a in self.armies}
        for side in sides:
            units = [u for a in self.armies if a.side != side
                     for u in a.units if u.alive]
            n = len(units)
            if not n:
                self._target_cache[side] = None
                continue
            xs = np.empty(n); ys = np.empty(n); hpf = np.empty(n)
            rng = np.zeros(n, dtype=bool); thr = np.zeros(n)
            alive = np.ones(n, dtype=bool)
            threat = self._threat
            for i, u in enumerate(units):
                xs[i] = u.x; ys[i] = u.y
                hpf[i] = u.hp / u.max_hp
                rng[i] = u._ranged
                thr[i] = threat.get(u, 0)
                # Where to find this unit when it dies mid-tick, so the arrays
                # can be kept honest without an O(n) rescan (see mark_dead).
                u._cache_key = side
                u._cache_idx = i
            self._target_cache[side] = (units, xs, ys, hpf, rng, thr, alive)

    def mark_dead(self, unit):
        """Drop a unit from the target snapshot the instant it falls.

        Without this a soldier could keep picking a corpse for up to a full
        re-target interval, because the snapshot was taken while it still
        lived. Called from Unit.take_hit -- O(1), no rescan."""
        cache = self._target_cache.get(getattr(unit, "_cache_key", None))
        if cache is None:
            return
        idx = getattr(unit, "_cache_idx", -1)
        if 0 <= idx < cache[6].size and cache[0][idx] is unit:
            cache[6][idx] = False

    def choose_target(self, unit):
        """Scored target pick — units still overwhelmingly go for whoever's
        closest, but with a few refinements over blind nearest-enemy: finish
        off the wounded, don't all dogpile one soldier, and let cavalry favor
        soft archer targets. Distance dominates the score (kept in the same
        pixel scale as the bonuses), so the overall behavior is still ''run at
        the enemy'' -- just with a bit of judgment. Throttled per-unit via
        Unit._retarget_cd so this isn't paid every frame."""
        cache = self._target_cache.get(unit.faction.side)
        if not cache:
            return self.nearest_enemy(unit)
        units, xs, ys, hpf, rng, thr, alive = cache
        if not alive.any():
            return self.nearest_enemy(unit)

        dist = np.hypot(xs - unit.x, ys - unit.y)

        # An Assassin hunts bowmen and nothing else. Deliberately scoped to the
        # WHOLE battlefield rather than "no archer nearby": they are meant to
        # run past a shield line to get at what is behind it, so a nearby wall
        # of swordsmen must not count as having run out of targets. Only once
        # the last enemy archer anywhere is dead do they turn on the line.
        if unit.type.get("hunts_ranged"):
            prey = rng & alive
            if prey.any():
                cost = np.where(prey, dist + _CROWD_PENALTY * thr, np.inf)
                return units[int(np.argmin(cost))]

        # A unit holding its ground will not walk to a target, so picking the
        # "best" enemy across the field would leave it facing someone it can
        # never reach while an enemy in its face went unanswered. Restrict it
        # to what it can actually hit, and only fall through to the ordinary
        # scoring when nothing is in reach (so it still faces the threat).
        if unit.holds_position:
            reach = alive & (dist <= unit.attack_range)
            if reach.any():
                # Weakest first, nearest to break ties -- as the scalar version
                # did with its (hp_fraction, distance) sort key.
                idx = np.flatnonzero(reach)
                order = np.lexsort((dist[idx], hpf[idx]))
                return units[int(idx[order[0]])]

        score = -dist + _FINISH_WEIGHT * (1.0 - hpf) - _CROWD_PENALTY * thr
        if unit.type.get("charge"):
            score = score + _CAVALRY_ARCHER_BONUS * rng
        score = np.where(alive, score, -np.inf)
        best = int(np.argmax(score))
        if score[best] == -np.inf:
            return self.nearest_enemy(unit)
        return units[best]

    # --- orders ---------------------------------------------------------------
    def issue_stance(self, units, stance):
        """Give `units` a stance, skipping any that can't carry it (an archer
        has no business in a shield wall). Returns how many actually took it,
        so the UI can report "12 swordsmen form a shield wall" honestly rather
        than echoing the click.

        Forming the wall is done here rather than per-unit because a wall is a
        property of the GROUP -- every unit needs a slot in one shared line, and
        no unit can work that out on its own."""
        taking = [u for u in units if u.alive and orders.can_take_stance(u, stance)]
        for u in taking:
            u.stance = stance
            if stance != orders.STANCE_SHIELD_WALL:
                u.wall_slot = None
            if stance != orders.STANCE_CYCLE_CHARGE:
                u._cycle_state = "run"
                u._cycle_rally = None
        if stance == orders.STANCE_SHIELD_WALL and taking:
            self.form_shield_wall(taking)
        return len(taking)

    def issue_fire_discipline(self, units, fire_at_will):
        """Hold fire / fire at will. Only means anything to ranged units, so
        the count returned is of archers, not of whatever was selected."""
        ranged = [u for u in units if u.alive and u._ranged]
        for u in ranged:
            u.fire_at_will = fire_at_will
            if fire_at_will is False:
                u.volley = 0.0    # start the draw from cold
        return len(ranged)

    def form_shield_wall(self, units):
        """Lay out a line of slots facing the enemy and assign one per unit.

        The line runs PERPENDICULAR to the direction of the enemy, centred on
        the group's own position, so ordering a wall dresses the troops roughly
        where they already stand rather than marching them somewhere else --
        a wall that first walks 200px to form up would be broken before it
        existed."""
        alive = [u for u in units if u.alive]
        if not alive:
            return
        cx = sum(u.x for u in alive) / len(alive)
        cy = sum(u.y for u in alive) / len(alive)

        # Facing: toward the enemy centre of mass, falling back to straight
        # across the field if there is no enemy left to face.
        ex, ey, n = 0.0, 0.0, 0
        for army in self.armies:
            if army.side == alive[0].faction.side:
                continue
            for u in army.units:
                if u.alive:
                    ex += u.x; ey += u.y; n += 1
        if n:
            fx, fy = ex / n - cx, ey / n - cy
            mag = math.hypot(fx, fy) or 1e-6
            fx, fy = fx / mag, fy / mag
        else:
            fx, fy = (1.0, 0.0) if alive[0].faction.side == 0 else (-1.0, 0.0)
        px, py = -fy, fx          # along the line

        # Sort along the line axis first so units take the slot nearest where
        # they already are -- otherwise the assignment crosses everyone over
        # each other and the formation tangles itself forming up.
        alive.sort(key=lambda u: (u.x - cx) * px + (u.y - cy) * py)
        per_rank = min(orders.WALL_MAX_RANK, len(alive))
        for i, u in enumerate(alive):
            rank, col = divmod(i, per_rank)
            span = min(per_rank, len(alive) - rank * per_rank)
            offset = (col - (span - 1) / 2.0) * orders.WALL_SPACING
            back = rank * orders.WALL_RANK_GAP
            sx = cx + px * offset - fx * back
            sy = cy + py * offset - fy * back
            r = u.radius
            u.wall_slot = (min(self.width - r, max(r, sx)),
                           min(self.height - r, max(r, sy)))

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
                        # each unordered pair once -- by stable uid, never by
                        # id(), which is an address and varies per run (see
                        # Unit._next_uid)
                        if v.uid <= u.uid:
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
                        # Hard separation (split the overlap). Kept an even
                        # split deliberately: anchoring the engaged rank and
                        # taking the whole overlap out of the moving unit was
                        # tried and measured WORSE -- displacing an advancing
                        # unit by the full overlap just made it rebound and
                        # come again, and front-rank travel after contact rose
                        # from 150px to 336px.
                        # Split by mass, not evenly: the lighter unit gives way.
                        # See Unit.mass for why -- an even split let a ring of
                        # soldiers walk their own Commander into a wall.
                        u_share = v.mass / (u.mass + v.mass)
                        u.x -= nx * overlap * u_share
                        u.y -= ny * overlap * u_share
                        v.x += nx * overlap * (1.0 - u_share)
                        v.y += ny * overlap * (1.0 - u_share)
                        # Springy impulse -- but ONLY if someone is actually
                        # closing. Driven by overlap alone it never stopped: a
                        # packed melee overlaps on every single tick, so the
                        # two lines kept shoving each other around the field
                        # instead of standing and fighting. Gating on
                        # `advancing` keeps the impact of a charge hitting a
                        # line (the mover carries real momentum) while a
                        # locked-in melee gets only the hard separation above,
                        # which un-stacks units without driving them anywhere.
                        if not (u.advancing or v.advancing):
                            continue
                        imp = overlap * _BOUNCE
                        u.vx -= nx * imp * u_share
                        u.vy -= ny * imp * u_share
                        v.vx += nx * imp * (1.0 - u_share)
                        v.vy += ny * imp * (1.0 - u_share)

    def _run_order_ai(self, dt):
        """Let every AI-controlled army re-decide its orders, on a throttle."""
        self._order_ai_cd -= dt
        if self._order_ai_cd > 0.0:
            return
        self._order_ai_cd = order_ai.DECIDE_INTERVAL
        for army in self.armies:
            if army.side == self.player_side:
                continue
            order_ai.decide_for_army(self, army)

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

        self._rebuild_target_cache()
        self._run_order_ai(dt)

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
