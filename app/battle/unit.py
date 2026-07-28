"""A single soldier.

Behavior is intentionally simple (seek a target, attack when in range) and
isolated in ``update`` so it's easy to extend. Beyond the base seek-and-swing:

  * Facing — a unit always faces its current target; ``self.facing`` is the
    shared source of truth for both the shield's frontal block arc (take_hit)
    and how the battle view draws its sword/shield.
  * Shield block — a sword+shield unit (block_chance in UNIT_TYPES) can deflect
    a hit that comes from within its frontal cone; flank/rear hits always land.
  * Cavalry charge — a mounted unit (charge in UNIT_TYPES) builds momentum while
    galloping in and lands a couched impact hit, then must disengage and
    re-accelerate to charge again; bogged down in a scrum it fights softer than
    its raw damage (melee_floor).
  * Target selection — delegated to Battle.choose_target (scored, not blind
    nearest), re-evaluated on a throttle rather than only when the target dies.
"""
import math
import random

from app.battle.unit_types import (UNIT_TYPES, COMMANDER_AURA_RADIUS,
                                   commander_profile)
from app.world.lexicon import species_traits

_IMPACT_CHARGE_MIN = 0.5   # momentum above which a couched hit spawns an impact
                           # burst + reads as a real "charge" in the log


class Unit:
    def __init__(self, type_key, faction, x, y, strength_mult=1.0, species=None):
        t = UNIT_TYPES.get(type_key, UNIT_TYPES["infantry"])
        self.type_key = type_key
        self.type = t
        self.faction = faction   # the owning Army
        self.x = x
        self.y = y
        # Species traits (see app/world/lexicon.py) are baked into per-INSTANCE
        # stats here rather than read from self.type on the fly, because
        # self.type is the single shared UNIT_TYPES dict every other army reads
        # from too -- mutating it would leak one faction's bonuses into
        # everyone else's soldiers. A species of None (a wildland garrison)
        # gets all-default traits and fights at the plain baseline.
        self.species = species
        traits = species_traits(species)
        # strength_mult scales this unit's combat power relative to the
        # shared UNIT_TYPES baseline (both HP and damage dealt) — e.g. a
        # wildland garrison's soldiers, per app/ui/app.py's
        # stage_wildland_battle, without mutating the shared type data
        # every other army also reads from.
        self.max_hp = t["max_hp"] * strength_mult * traits["unit_hp_mult"]
        self.damage = t["damage"] * strength_mult * traits["unit_damage_mult"]
        self.speed = t["speed"] * traits["unit_speed_mult"]
        self.cooldown = t["cooldown"] * traits["unit_cooldown_mult"]
        self.dodge_chance = traits["dodge_chance"]
        # Physical size: Orcish Swordsmen are visibly bigger bodies. Radius is
        # cosmetic-plus-collision only (attack reach is `range`, measured
        # center to center), so a larger soldier takes up more of the line
        # rather than out-reaching anyone.
        self.radius = t["radius"]
        if type_key == "infantry":
            self.radius *= traits["swordsman_size_mult"]
        # Shield discipline: Orcs swing oversized weapons and hold a far looser
        # line, so they get much less out of a shield than a drilled Dwarven or
        # Human formation does -- the counterweight to their raw damage.
        self.block_chance = t.get("block_chance", 0.0) * traits["block_chance_mult"]
        # A commander is its species' champion, not a generic one: apply that
        # species' profile over the base entry (see COMMANDER_BY_SPECIES).
        # Done AFTER the species multipliers above so a profile's explicit
        # number is the final word -- an Orcish Warchief is meant to be exactly
        # as tough as the table says, not that times another +22%.
        self.is_commander = type_key == "commander"
        self.aura = {}
        self.cleave = None
        self.title = t.get("name", "Commander")
        if self.is_commander:
            prof = commander_profile(species)
            self.title = prof.get("title", "Commander")
            self.aura = prof.get("aura") or {}
            self.cleave = prof.get("cleave")
            stats = prof.get("stats") or {}
            if "max_hp" in stats:
                self.max_hp = stats["max_hp"] * strength_mult
            if "damage" in stats:
                self.damage = stats["damage"] * strength_mult
            if "speed" in stats:
                self.speed = stats["speed"]
            if "block_chance" in stats:
                self.block_chance = stats["block_chance"]
            if "dodge_chance" in stats:
                self.dodge_chance = stats["dodge_chance"]
            # Range/ranged/accuracy live on self.type, which is the SHARED
            # UNIT_TYPES dict -- mutating it would leak one species' Warden
            # into everyone else's commander. Keep per-instance overrides.
            self._range = stats.get("range", t["range"])
            self._ranged = stats.get("ranged", t.get("ranged", False))
            self._accuracy = stats.get("accuracy", t.get("accuracy", 1.0))
        else:
            self._range = t["range"]
            self._ranged = t.get("ranged", False)
            self._accuracy = t.get("accuracy", 1.0)

        self.hp = self.max_hp
        self._cd = 0.0           # attack cooldown timer
        self.target = None
        self.vx = 0.0            # bounce velocity (from collisions), decays
        self.vy = 0.0
        self.facing = (1.0, 0.0)  # unit-vector toward target; default east
        self.charge = 0.0        # cavalry momentum 0..1 (see update); 0 for others
        self.advancing = False   # closing on a target this tick, i.e. not yet
                                 # locked in melee -- gates collision knockback
                                 # so lines stand and fight (see
                                 # Battle._resolve_collisions)
        self._retarget_cd = random.random() * 0.6   # jittered so units don't all
                                                     # re-evaluate on the same tick

    # --- commander auras ------------------------------------------------------
    # Read on demand from the army's living commander rather than written onto
    # each soldier. That means an aura can never double-apply, never needs
    # cleaning up when he dies, and costs one distance check at the moment it
    # actually matters instead of a sweep over every unit every tick.
    def _aura(self, key, default=1.0):
        cmd = getattr(self.faction, "commander", None)
        if cmd is None or cmd is self or not cmd.alive or not cmd.aura:
            return default
        value = cmd.aura.get(key)
        if value is None:
            return default
        dx, dy = cmd.x - self.x, cmd.y - self.y
        if dx * dx + dy * dy > COMMANDER_AURA_RADIUS * COMMANDER_AURA_RADIUS:
            return default
        return value

    @property
    def attack_range(self):
        return self._range * self._aura("range_mult")

    @property
    def effective_cooldown(self):
        return self.cooldown * self._aura("cooldown_mult")

    @property
    def effective_block(self):
        return min(0.95, self.block_chance + self._aura("block_add", 0.0))

    @property
    def effective_dodge(self):
        return min(0.85, self.dodge_chance + self._aura("dodge_add", 0.0))

    @property
    def alive(self):
        return self.hp > 0

    def take_hit(self, attacker, dmg, battle):
        """Receive ``dmg`` from ``attacker``. Two ways it can come to nothing:
        a nimble species (Goblins) may simply dodge it outright, from any
        direction; failing that, a sword+shield unit gets a chance to deflect
        it -- but only a blow arriving within its frontal ``block_arc_deg``
        cone (dot of its facing with the direction to the attacker), so a
        flank or rear hit always lands and surrounding an enemy pays off.
        Returns "dodge", "block" or "hit" for the view's log/effects."""
        # Dodge first: sidestepping a blow doesn't care which way you're facing
        # or whether you carry a shield, so it applies before the shield check.
        dodge = self.effective_dodge
        if dodge and random.random() < dodge:
            battle.spawn_effect(self.x, self.y, "dodge", "#b7f07a")
            return "dodge"

        block_chance = self.effective_block
        if block_chance > 0.0:
            ax, ay = attacker.x - self.x, attacker.y - self.y
            ad = math.hypot(ax, ay) or 1e-6
            facing_dot = (self.facing[0] * ax + self.facing[1] * ay) / ad
            arc = math.radians(self.type.get("block_arc_deg", 150)) * 0.5
            if facing_dot >= math.cos(arc) and random.random() < block_chance:
                battle.spawn_effect(self.x, self.y, "block", "#a9d4ff")
                return "block"
        # A Dwarven Thane's line takes less punishment while he stands.
        self.hp -= dmg * self._aura("damage_taken_mult")
        return "hit"

    def update(self, dt, battle):
        if not self.alive:
            return
        self._cd = max(0.0, self._cd - dt)
        self._retarget_cd -= dt
        # Cleared every tick and re-raised only in the advance branch below, so
        # a unit standing in range -- whether swinging or waiting on its
        # cooldown -- counts as stationary and stops shoving.
        self.advancing = False

        # Scored re-target on a throttle (or immediately if the current target
        # is gone) -- see Battle.choose_target.
        if self.target is None or not self.target.alive or self._retarget_cd <= 0:
            self.target = battle.choose_target(self)
            self._retarget_cd = 0.6
        if self.target is None:
            return

        dx = self.target.x - self.x
        dy = self.target.y - self.y
        dist = math.hypot(dx, dy) or 1e-6
        self.facing = (dx / dist, dy / dist)

        if dist > self.attack_range:
            self.advancing = True
            move = self.speed * dt
            self.x += dx / dist * move
            self.y += dy / dist * move
            # Galloping toward the enemy builds couched-charge momentum. A
            # bogged-down unit is in the attack branch instead, so its charge
            # decays to nothing -- devastating on impact, weak in a grind.
            if self.type.get("charge"):
                self.charge = min(1.0, self.charge + dt / self.type.get("charge_ramp", 1.2))
        elif self._cd <= 0:
            self._cd = self.effective_cooldown
            dmg = self.damage * self._aura("damage_mult")
            charging = self.type.get("charge")
            if charging:
                # melee_floor (<1) at zero momentum up to melee_floor+charge_bonus
                # at a full gallop -- see UNIT_TYPES.
                floor = self.type.get("melee_floor", 0.5)
                dmg = self.damage * (floor + self.type.get("charge_bonus", 2.0) * self.charge)
            # accuracy (see UNIT_TYPES) defaults to 1.0 -- melee always
            # connects when in range; a miss still fires (the arrow flies,
            # the cooldown ticks) but deals no damage.
            outcome = "miss"
            if random.random() < self._accuracy:
                momentum = self.charge
                outcome = self.target.take_hit(self, dmg, battle)
                if charging and outcome == "hit" and momentum >= _IMPACT_CHARGE_MIN:
                    battle.spawn_effect(self.target.x, self.target.y, "impact",
                                        self.faction.color)
                    self._charge_splash(battle, dmg, momentum)
            if charging:
                self.charge = 0.0   # impact spent -- must back off and re-accelerate
            if self.cleave and outcome == "hit":
                self._cleave(battle, dmg)
            if self._ranged:
                battle.spawn_projectile(self.x, self.y,
                                        self.target.x, self.target.y,
                                        self.faction.color)
            if battle.on_attack:
                battle.on_attack(self, self.target, outcome)

    def _cleave(self, battle, dmg):
        """An Orcish Warchief's swing carries through whatever is packed around
        the soldier he struck -- the same shape as a cavalry charge's splash,
        but on every blow rather than only out of a gallop. It is the whole of
        what Orcs get from their commander: no aura, no protection, just this.
        """
        if self.target is None:
            return
        radius = self.cleave["radius"]
        share = self.cleave["share"]
        cx, cy, r2 = self.target.x, self.target.y, radius * radius
        splash = dmg * share
        for army in battle.armies:
            if army is self.faction:
                continue
            for other in army.units:
                if other is self.target or not other.alive:
                    continue
                dx, dy = other.x - cx, other.y - cy
                if dx * dx + dy * dy <= r2:
                    other.take_hit(self, splash, battle)
        battle.spawn_effect(cx, cy, "impact", self.faction.color, size=radius)

    def _charge_splash(self, battle, impact_dmg, momentum):
        """A couched impact ploughs into the whole frontline it reaches, not
        just the one soldier it struck: every OTHER enemy within
        ``charge_aoe_radius`` of that soldier takes ``charge_aoe_share`` of the
        impact damage, scaled by how much momentum the rider actually carried
        in. Riders who trotted into contact barely jostle anyone; a full
        gallop scatters a line.

        Splash goes through take_hit like any other blow, so shields still
        block it from the front and Goblins can still dodge it -- a charge is
        devastating, not unanswerable. Only ever called on a real impact (see
        _IMPACT_CHARGE_MIN), which the attack cooldown already rate-limits, so
        this never runs per-frame per-rider."""
        radius = self.type.get("charge_aoe_radius", 0.0)
        if radius <= 0 or self.target is None:
            return
        splash = impact_dmg * self.type.get("charge_aoe_share", 0.5) * momentum
        if splash <= 0:
            return
        cx, cy, r2 = self.target.x, self.target.y, radius * radius
        for army in battle.armies:
            if army is self.faction:
                continue          # riders don't trample their own line
            for other in army.units:
                if not other.alive or other is self.target:
                    continue
                if (other.x - cx) ** 2 + (other.y - cy) ** 2 <= r2:
                    other.take_hit(self, splash, battle)
        battle.spawn_effect(cx, cy, "shock", self.faction.color,
                            dur=0.36, size=radius)
