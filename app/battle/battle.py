"""The micro-scale battle simulation (pure logic, no rendering)."""
import math
import random
from collections import Counter

import numpy as np

from app.core.events import bus
from app.battle import movement, order_ai, orders
from app.world import weather
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
        # Every unit in this army that projects an aura, COMMANDER FIRST --
        # Unit._aura takes the first source in range rather than summing, so
        # the order is what makes a Marshal outrank a Standard Bearer. Set by
        # Battle.deploy; membership never changes, since a dead source is
        # skipped by the alive check at the point of use.
        self.aura_sources = []

    @property
    def living(self):
        return [u for u in self.units if u.alive]


# --- Terrain in battle (biome overhaul, phase E) -----------------------------
# Where a battle is fought has never mattered here: the sim had no terrain
# hooks of any kind, so a fight in a marsh resolved exactly like one on open
# plains. Three effects, chosen because each is a real, legible thing terrain
# does to a fight rather than an abstract modifier:
#
#   speed    -- broken, wet or steep ground slows everyone equally. Armies
#               have gone around marshland for as long as there have been
#               armies.
#   defender -- high ground favours whoever already holds it. This applies to
#               the DEFENDING side only, which is the whole point of it.
#   ranged   -- cover shortens sightlines. Bows need to see what they are
#               shooting at, and a jungle is where they stop being able to.
#
# Applied ONCE at deploy time to each unit's own attributes rather than
# per-tick in update(). The battle sim runs to a 16.7ms frame budget (see
# battle_view._EQUIPMENT_DETAIL_MAX_UNITS) and a per-tick terrain lookup for
# every soldier would spend it for no gain -- terrain does not change mid
# battle.
#
# Deliberately modest. Species balance here is delicate and hard-won (see
# HANDOFF S4 on how many richer order-AI rules measured WORSE), so these are
# sized to colour a fight rather than decide it, and are meant to be judged
# in play.
BATTLE_TERRAIN = {
    "swamp":    {"speed": 0.75, "defender": 1.00, "ranged": 0.85},
    "jungle":   {"speed": 0.80, "defender": 1.05, "ranged": 0.70},
    "forest":   {"speed": 0.90, "defender": 1.05, "ranged": 0.75},
    "taiga":    {"speed": 0.90, "defender": 1.05, "ranged": 0.85},
    "mountain": {"speed": 0.75, "defender": 1.20, "ranged": 1.00},
    "highland": {"speed": 0.90, "defender": 1.15, "ranged": 1.00},
    "tundra":   {"speed": 0.95, "defender": 1.00, "ranged": 1.00},
    "desert":   {"speed": 0.95, "defender": 1.00, "ranged": 1.00},
    "coastal":  {"speed": 1.00, "defender": 1.00, "ranged": 1.00},
    "plains":   {"speed": 1.00, "defender": 1.00, "ranged": 1.00},
    "steppe":   {"speed": 1.00, "defender": 1.00, "ranged": 1.00},
    "savannah": {"speed": 1.00, "defender": 1.00, "ranged": 1.00},
}
NEUTRAL_TERRAIN = {"speed": 1.0, "defender": 1.0, "ranged": 1.0}

# --- Weather in battle (weather phase 4) -------------------------------------
# Where a battle is fought was phase E; WHEN it is fought is this. The two
# stack, and they are deliberately different in one important way:
#
#   terrain is ASYMMETRIC -- high ground favours whoever holds it, which is
#           the entire point of high ground.
#   weather is SYMMETRIC -- rain falls on both armies. A storm that helped
#           the defender would be a second terrain bonus wearing a cloud, and
#           it would make defending in bad weather strictly better rather
#           than differently hard.
#
# Grounded in what weather actually did to battles rather than in abstract
# modifiers. Wet bowstrings and a headwind are the reason Crecy and Agincourt
# read the way they do; fog is why Barnet was fought half-blind and formations
# shot at their own side.
#
#   speed     mud, snow underfoot, ground that will not hold a boot
#   ranged    how far a bowman can SEE to shoot -- reach, not damage, exactly
#             as with cover in phase E
#   accuracy  whether the shot lands once he has taken it, which is a
#             different question from whether he can see the target at all
#
# Drought is neutral here for the same reason it is neutral for a wagon (see
# travel.WEATHER_TRAVEL_RATE): dry hard ground is GOOD to fight on. Making
# every kind of weather bad would make them interchangeable, and the point of
# having four is that they are not.
#
# The accuracy figures COMPOUND with the unit's own, and were first tuned
# against an archer at 0.80. Dropping that to 0.60 (see unit_types) took a
# severe storm from "archers win 72%" to "archers win 0%" -- the same
# multiplier, a very different fight, because it multiplies. They were raised
# to match. If archer accuracy is ever changed again, these move with it.
BATTLE_WEATHER = {
    weather.DROUGHT:  {"speed": 1.00, "ranged": 1.00, "accuracy": 1.00},
    weather.STORM:    {"speed": 0.88, "ranged": 0.85, "accuracy": 0.82},
    weather.BLIZZARD: {"speed": 0.78, "ranged": 0.75, "accuracy": 0.88},
    weather.FOG:      {"speed": 0.97, "ranged": 0.55, "accuracy": 0.90},
}
NEUTRAL_WEATHER = {"speed": 1.0, "ranged": 1.0, "accuracy": 1.0}

# Mild weather is half the effect of severe, rather than a second table to
# keep in step with the first. One set of numbers to tune, and "severe" always
# means exactly twice as much of whatever that weather does.
MILD_WEATHER_SCALE = 0.5


def weather_profile(event):
    """The multipliers for fighting under `event` (a weather.WeatherEvent, or
    None for a clear day). Severity scales the distance from 1.0, so a mild
    storm is half a severe one and clear weather changes nothing."""
    if event is None:
        return dict(NEUTRAL_WEATHER)
    base = BATTLE_WEATHER.get(event.kind)
    if not base:
        return dict(NEUTRAL_WEATHER)
    scale = 1.0 if event.severity == weather.SEVERE else MILD_WEATHER_SCALE
    return {k: 1.0 - (1.0 - v) * scale for k, v in base.items()}

# Which side is defending. stage_battle deploys the attacker as side 0 and
# the defender as side 1, and a wildland garrison is likewise side 1 -- it is
# being attacked in its own country, which is exactly the case high ground is
# supposed to reward.
DEFENDER_SIDE = 1


# What each terrain effect does, said plainly, for the banner over the battle.
# A modifier the player cannot see is a modifier that does not exist -- and
# the whole point of terrain is that you look at where the fight is happening
# and think differently about it before it starts.
_TERRAIN_NOTES = [
    ("speed", lambda v: "broken ground slows both sides" if v < 0.85
     else "heavy going underfoot" if v < 0.95
     else "the going is a little slow"),
    ("ranged", lambda v: "thick cover blinds the archers" if v < 0.8
     else "cover spoils the shooting"),
    ("defender", lambda v: "the high ground strongly favours the defender"
     if v > 1.1 else "the ground favours the defender"),
]


def terrain_note(biome):
    """One short clause describing how this ground changes the fight, or ""
    for open country that changes nothing."""
    profile = BATTLE_TERRAIN.get(biome)
    if not profile:
        return ""
    parts = [text(profile[key]) for key, text in _TERRAIN_NOTES
             if profile[key] != 1.0]
    return "; ".join(parts)


# One clause per kind, not an enumeration of every field that moved. Deriving
# the note from the numbers produced things like "the shooting is blind work;
# the shooting is unsteady; heavy going" for a mild fog that barely slowed
# anyone -- accurate, unreadable, and overstating a 2% change. What a player
# needs is what this weather DOES to a fight, in one line.
_WEATHER_NOTES = {
    weather.STORM: ("rain and wind spoil the shooting",
                    "driving rain: the bows are near useless and the field is mud"),
    weather.BLIZZARD: ("snow underfoot slows both sides",
                       "a blizzard: nobody moves well and nobody shoots well"),
    weather.FOG: ("mist shortens every sightline",
                  "thick fog: the archers cannot see far enough to matter"),
}


def weather_note(event):
    """One short clause on what the weather is doing to this fight, or "" for
    weather that changes nothing. Same reasoning as terrain_note: a modifier
    the player cannot see is a modifier that does not exist.

    Drought gets no line because it does nothing here, which is itself worth
    not saying -- a note that reads "the drought changes nothing" is noise.
    """
    if event is None:
        return ""
    pair = _WEATHER_NOTES.get(event.kind)
    if not pair:
        return ""
    return pair[1] if event.severity == weather.SEVERE else pair[0]


def terrain_profile(biome):
    """The three multipliers for a battle fought on `biome`. Unknown or
    missing terrain is neutral, so a headless sim or an old save that names
    no biome fights exactly as it always did."""
    return dict(BATTLE_TERRAIN.get(biome) or NEUTRAL_TERRAIN)


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
        self._contact = Counter()  # enemy -> # of living units in REACH of it;
                                   # rebuilt each update() for movement.mobbed
        self._move_grid = {}       # spatial hash for movement.steer's neighbours
        # Which side the player is giving orders to. Every OTHER side is driven
        # by the order AI (app/battle/order_ai.py). Left None outside a real
        # player battle -- in a headless sim or the balance tournament both
        # sides should be ordered by the same AI, or the numbers mean nothing.
        self.player_side = None
        self._order_ai_cd = 0.0
        # Where this is being fought (phase E). Set by set_terrain before
        # deploy; neutral until then, so nothing that never calls it changes.
        self.biome = None
        self.terrain = dict(NEUTRAL_TERRAIN)
        # And when it is being fought (weather phase 4). Neutral until
        # set_weather, so a headless sim or a clear day changes nothing.
        self.weather_event = None
        self.weather = dict(NEUTRAL_WEATHER)

    def spawn_projectile(self, sx, sy, tx, ty, color):
        self.projectiles.append(Projectile(sx, sy, tx, ty, color))

    def spawn_effect(self, x, y, kind, color, dur=0.28, size=0.0):
        self.effects.append(Effect(x, y, kind, color, dur, size))

    def threat_count(self, enemy):
        """How many living units already target ``enemy`` (see choose_target's
        soft anti-dogpile term). Snapshot from the last update() tick."""
        return self._threat.get(enemy, 0)

    def contact_count(self, enemy):
        """How many enemies of ``enemy`` are actually IN REACH of it right now
        -- which is a different question from how many are targeting it, and
        the one that decides whether another body can usefully join the fight
        (see movement.mobbed). Snapshot per tick, same as _threat."""
        return self._contact.get(enemy, 0)

    # Cell size for the movement neighbour grid. Wider than the collision
    # grid's, because steering looks further than a body's own overlap: it must
    # cover AVOID_DIST in one ring of nine cells.
    MOVE_CELL = 32

    def _build_move_grid(self):
        """One spatial hash of every living unit, built before any unit moves,
        for movement.steer's neighbour lookup.

        Built here rather than reusing _resolve_collisions' grid because that
        one is built AFTER the tick's movement, from a different cell size, for
        a different question. Both are one pass over the field; targeting was
        the sim's real cost (see _rebuild_target_cache), not passes like this.
        """
        grid = {}
        cell = self.MOVE_CELL
        for army in self.armies:
            for u in army.units:
                if u.alive:
                    grid.setdefault((int(u.x // cell), int(u.y // cell)), []).append(u)
        self._move_grid = grid

    # Default formation, front-to-back, before the player drags anything
    # during planning: Archers hang back where their range still reaches
    # the enemy without them taking the first charge, Swordsmen anchor the
    # line that actually meets it, everything else (Cavalry, species
    # specials) starts in the middle. Just the starting line, not a
    # restriction -- planning can drag any unit anywhere in its own half.
    # Higher tier -> higher `col` below -> physically closer to the
    # midline/enemy, i.e. further forward.
    _DEPLOY_TIER = {"archer": 0, "infantry": 2}

    def set_terrain(self, biome):
        """Say what ground this battle is fought on. Must be called BEFORE
        deploy -- the effects are baked into each unit as it is created, so
        setting it afterwards would colour nothing."""
        self.biome = biome
        self.terrain = terrain_profile(biome)

    def set_weather(self, event):
        """Say what the weather is doing. Same rule as set_terrain: before
        deploy, or it colours nothing."""
        self.weather_event = event
        self.weather = weather_profile(event)

    def _apply_terrain(self, unit, side):
        """Bake this battle's ground AND weather into one freshly-created
        unit.

        Reach is scaled rather than ranged damage, for both: cover and fog
        are about not being able to SEE what you are shooting at, and
        shortening the bow line is what actually changes how a wood -- or a
        foggy morning -- is fought, because archers have to come close enough
        to be charged. Weakening their damage instead would read as arrows
        mysteriously bouncing off.

        Accuracy is separate from reach and only weather touches it: whether
        a shot lands once taken is a different question from whether the
        bowman could see the target at all, and it is the one a headwind and
        a wet string actually answer.

        The defender bonus is TERRAIN ONLY. Rain falls on both armies -- a
        storm that helped whoever was defending would just be a second
        high-ground bonus wearing a cloud."""
        t, w = self.terrain, self.weather
        speed = t["speed"] * w["speed"]
        if speed != 1.0:
            unit.speed *= speed
        if getattr(unit, "_ranged", False):
            reach = t["ranged"] * w["ranged"]
            if reach != 1.0:
                unit._range *= reach
            if w["accuracy"] != 1.0:
                unit._accuracy *= w["accuracy"]
        if side == DEFENDER_SIDE and t["defender"] != 1.0:
            unit.max_hp *= t["defender"]
            unit.hp = unit.max_hp

    def deploy(self, army, composition, side, strength_mult=1.0, with_commander=True):
        """Place an army in a grid along one side from a composition dict
        ``{unit_type: count}``. ``strength_mult`` scales every spawned
        unit's combat power (see Unit) — used for a wildland garrison's
        weaker soldiers, 1.0 (no change) for a normal nation's army."""
        army.side = side
        x0 = self.width * 0.12 if side == 0 else self.width * 0.88
        entries = []
        ordered = sorted(composition.items(),
                         key=lambda kv: self._DEPLOY_TIER.get(kv[0], 1))
        for type_key, count in ordered:
            entries.extend([type_key] * count)

        rows = max(1, math.ceil(math.sqrt(len(entries))))
        for i, type_key in enumerate(entries):
            col = i // rows
            row = i % rows
            jitter = lambda: (random.random() - 0.5) * 8
            x = x0 + (col * 16 if side == 0 else -col * 16) + jitter()
            y = self.height / 2 + (row - rows / 2) * 16 + jitter()
            unit = Unit(type_key, army, x, y, strength_mult,
                        species=getattr(army, "species", None))
            self._apply_terrain(unit, side)
            army.units.append(unit)

        if with_commander:
            # Behind his own formation, not in front of it: he reaches the
            # fight after the lines meet, and cutting to the enemy's commander
            # means going through their army first -- which is what makes
            # killing one an achievement rather than an opening move. Added on
            # top of the composition, never taken out of it.
            back = x0 - 40 if side == 0 else x0 + 40
            cmd = Unit("commander", army, back, self.height / 2, strength_mult,
                       species=getattr(army, "species", None))
            self._apply_terrain(cmd, side)
            cmd.is_commander = True
            army.units.append(cmd)
            army.commander = cmd
        army.aura_sources = ([army.commander] if army.commander is not None
                             and army.commander.aura else [])
        army.aura_sources += [u for u in army.units
                              if u.aura and u is not army.commander]
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
            # A fresh stance order is an explicit new command -- it should
            # supersede an older right-click move/attack the same way a new
            # right-click supersedes a previous one, not be silently
            # overridden by whichever order happens to still be pending (see
            # Unit.move_point/manual_target).
            u.move_point = None
            u.manual_target = None
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
        # ...and who is actually within reach of whom, which is the question
        # movement.mobbed asks. One pass, one hypot per living unit.
        self._contact = Counter(
            u.target for army in self.armies for u in army.units
            if u.alive and u.target is not None and u.target.alive
            and math.hypot(u.target.x - u.x, u.target.y - u.y)
            <= u.attack_range + u.radius + u.target.radius)

        self._rebuild_target_cache()
        self._build_move_grid()
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
