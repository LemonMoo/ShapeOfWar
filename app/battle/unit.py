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

from app.battle.unit_types import UNIT_TYPES
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
        self.hp = self.max_hp
        self._cd = 0.0           # attack cooldown timer
        self.target = None
        self.vx = 0.0            # bounce velocity (from collisions), decays
        self.vy = 0.0
        self.facing = (1.0, 0.0)  # unit-vector toward target; default east
        self.charge = 0.0        # cavalry momentum 0..1 (see update); 0 for others
        self._retarget_cd = random.random() * 0.6   # jittered so units don't all
                                                     # re-evaluate on the same tick

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
        if self.dodge_chance and random.random() < self.dodge_chance:
            battle.spawn_effect(self.x, self.y, "dodge", "#b7f07a")
            return "dodge"

        block_chance = self.block_chance
        if block_chance > 0.0:
            ax, ay = attacker.x - self.x, attacker.y - self.y
            ad = math.hypot(ax, ay) or 1e-6
            facing_dot = (self.facing[0] * ax + self.facing[1] * ay) / ad
            arc = math.radians(self.type.get("block_arc_deg", 150)) * 0.5
            if facing_dot >= math.cos(arc) and random.random() < block_chance:
                battle.spawn_effect(self.x, self.y, "block", "#a9d4ff")
                return "block"
        self.hp -= dmg
        return "hit"

    def update(self, dt, battle):
        if not self.alive:
            return
        self._cd = max(0.0, self._cd - dt)
        self._retarget_cd -= dt

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

        if dist > self.type["range"]:
            move = self.speed * dt
            self.x += dx / dist * move
            self.y += dy / dist * move
            # Galloping toward the enemy builds couched-charge momentum. A
            # bogged-down unit is in the attack branch instead, so its charge
            # decays to nothing -- devastating on impact, weak in a grind.
            if self.type.get("charge"):
                self.charge = min(1.0, self.charge + dt / self.type.get("charge_ramp", 1.2))
        elif self._cd <= 0:
            self._cd = self.cooldown
            dmg = self.damage
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
            if random.random() < self.type.get("accuracy", 1.0):
                outcome = self.target.take_hit(self, dmg, battle)
                if charging and outcome == "hit" and self.charge >= _IMPACT_CHARGE_MIN:
                    battle.spawn_effect(self.target.x, self.target.y, "impact",
                                        self.faction.color)
            if charging:
                self.charge = 0.0   # impact spent -- must back off and re-accelerate
            if self.type.get("ranged"):
                battle.spawn_projectile(self.x, self.y,
                                        self.target.x, self.target.y,
                                        self.faction.color)
            if battle.on_attack:
                battle.on_attack(self, self.target, outcome)
