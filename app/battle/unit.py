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
import itertools
import math
import random

from app.battle import orders
from app.battle.unit_types import (UNIT_TYPES, COMMANDER_AURA_RADIUS,
                                   COMMANDER_SCREEN_MIN, commander_profile)
from app.world.lexicon import species_traits

_IMPACT_CHARGE_MIN = 0.5   # momentum above which a couched hit spawns an impact
                           # burst + reads as a real "charge" in the log


class Unit:
    # Stable per-unit ordinal. The collision solver needs a consistent way to
    # visit each pair once, and it used id() -- a memory address, which changes
    # from run to run. That made a battle NON-REPRODUCIBLE even from a fixed
    # random seed: the same seed and the same armies resolved collisions in a
    # different order and could end with a different winner. It quietly
    # invalidated balance measurement, where two runs of an identical
    # configuration came out 19 points apart.
    _next_uid = itertools.count()

    def __init__(self, type_key, faction, x, y, strength_mult=1.0, species=None):
        self.uid = next(Unit._next_uid)
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
        # A unit type may declare its own dodge floor (the Assassin does);
        # whichever is higher wins, so a species' own evasion still counts.
        self.dodge_chance = max(traits["dodge_chance"], t.get("dodge_chance", 0.0))
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
        self.charge_shields_up = traits["charge_shields_up"]
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
        # Mass for collision resolution, as area (radius squared). Without it
        # every collision split its overlap evenly per PAIR, which quietly
        # wrecked anything bigger than a soldier: a Commander (radius 15) is in
        # contact with a ring of soldiers (radius 5) at once and took half the
        # overlap from every one of them, so his own bodyguard drove him across
        # the field and pinned him on a wall. Heavier units now barely shift
        # while the lighter one goes around -- a Commander weighs 9 soldiers.
        self.mass = float(self.radius * self.radius)
        self.charge = 0.0        # cavalry momentum 0..1 (see update); 0 for others
        self.advancing = False   # closing on a target this tick, i.e. not yet
                                 # locked in melee -- gates collision knockback
                                 # so lines stand and fight (see
                                 # Battle._resolve_collisions)
        self._retarget_cd = random.random() * 0.6   # jittered so units don't all
                                                     # re-evaluate on the same tick

        # --- orders (app/battle/orders.py) -----------------------------------
        self.stance = orders.STANCE_ADVANCE
        self.fire_at_will = True     # ranged only; False = holding, building a volley
        self.volley = 0.0            # 0..1 draw strength built up while holding fire
        self.wall_slot = None        # (x, y) this unit's place in a shield wall
        # Cavalry cycle-charge state machine: "run" (going in), "withdraw"
        # (pulling out after an impact), see Unit._update_cycle_charge.
        self._cycle_state = "run"
        self._cycle_rally = None     # (x, y) it is pulling back to
        self._cycle_timer = 0.0
        # uids this unit has already opened on -- only allocated for a type that
        # actually has a first strike, so ordinary soldiers carry no extra set.
        self._struck = set() if t.get("first_strike") else None

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

    # --- order-modified stats -------------------------------------------------
    # Stance multipliers sit on TOP of species traits and commander auras rather
    # than replacing them, so an order changes how a unit fights without
    # flattening what it is.
    @property
    def holds_position(self):
        """True while this unit refuses to walk toward a distant enemy. It still
        swings at anything that comes within reach."""
        return self.stance in orders.HOLDING_STANCES

    @property
    def effective_speed(self):
        return self.speed * orders.stance_mod(self.stance, "speed_mult")

    @property
    def wall_cohesion(self):
        """Extra block chance from standing in a CONTIGUOUS shield wall -- see
        orders.WALL_COHESION_*. Counted from live neighbours each time it is
        read, so a wall that gets broken up stops protecting immediately."""
        if self.stance != orders.STANCE_SHIELD_WALL or self.wall_slot is None:
            return 0.0
        link2 = orders.WALL_LINK_DIST * orders.WALL_LINK_DIST
        n = 0
        for other in self.faction.units:
            if (other is self or not other.alive
                    or other.stance != orders.STANCE_SHIELD_WALL
                    or other.wall_slot is None):
                continue
            dx, dy = other.x - self.x, other.y - self.y
            if dx * dx + dy * dy <= link2:
                n += 1
                if n >= 2:      # two neighbours is a formed line; more is just
                    break       # a crowd, and counting them all is wasted work
        return min(orders.WALL_COHESION_MAX, n * orders.WALL_COHESION_PER_NEIGHBOUR)

    @property
    def effective_block(self):
        block = (self.block_chance + self._aura("block_add", 0.0)
                 + orders.stance_mod(self.stance, "block_add", 0.0)
                 + self.wall_cohesion)
        # Charging normally means dropping your guard. A species with
        # `charge_shields_up` (Dwarves) keeps it -- they come on behind the
        # shields, so arrows glance off a charging dwarven line instead of
        # cutting it apart on the way in.
        mult = orders.stance_mod(self.stance, "block_mult")
        if mult < 1.0 and self.charge_shields_up:
            mult = 1.0
        return min(0.95, block * mult)

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
                # A deflected ARROW visibly glances away, rather than just
                # popping a spark. Without it "my charge is being blocked"
                # is invisible -- and for a shields-up dwarven charge, arrows
                # skating off the line IS the mechanic, so it has to be
                # legible on screen. Reuses the ordinary projectile so it
                # animates and expires like any other arrow in flight.
                if attacker._ranged:
                    nx, ny = ax / ad, ay / ad          # defender -> attacker
                    # Glance off at an angle instead of straight back, so it
                    # reads as a ricochet and not a returned shot.
                    skew = random.uniform(-0.9, 0.9)
                    rx, ry = nx - ny * skew, ny + nx * skew
                    rmag = math.hypot(rx, ry) or 1.0
                    reach = self.radius + 26
                    battle.spawn_projectile(self.x, self.y,
                                            self.x + rx / rmag * reach,
                                            self.y + ry / rmag * reach,
                                            "#cfd8e6")
                return "block"
        # Braced infantry blunt a couched charge. Checked off the ATTACKER's
        # live momentum rather than a flag on the blow, because Unit.update
        # only zeroes `charge` after take_hit returns -- so this reads the real
        # momentum of the rider who is hitting right now, and it covers the
        # charge splash (_charge_splash runs before that reset) for free.
        if (self.stance in orders.HOLDING_STANCES
                and attacker.type.get("charge") and attacker.charge > 0.0):
            dmg *= orders.BRACE_CHARGE_MULT
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

        # Cavalry told to charge and regroup pull out of the fight entirely
        # after an impact, so that runs ahead of ordinary target seeking.
        if self.stance == orders.STANCE_CYCLE_CHARGE:
            if self._update_cycle_charge(dt, battle):
                return

        # Scored re-target on a throttle (or immediately if the current target
        # is gone) -- see Battle.choose_target.
        if self.target is None or not self.target.alive or self._retarget_cd <= 0:
            self.target = battle.choose_target(self)
            self._retarget_cd = 0.6
        if self.target is None:
            return

        # Dressing the line: a unit given Shield Wall walks to its assigned slot
        # first and only then stands. Until it is in place it is not yet a wall.
        if self.stance == orders.STANCE_SHIELD_WALL and self.wall_slot is not None:
            sx, sy = self.wall_slot
            sdx, sdy = sx - self.x, sy - self.y
            sdist = math.hypot(sdx, sdy)
            if sdist > orders.WALL_SLOT_TOLERANCE:
                self.advancing = True
                move = min(sdist, self.effective_speed * dt)
                self.x += sdx / sdist * move
                self.y += sdy / sdist * move

        dx = self.target.x - self.x
        dy = self.target.y - self.y
        dist = math.hypot(dx, dy) or 1e-6
        self.facing = (dx / dist, dy / dist)

        # Holding fire: draw and wait, and the release hits far harder for it.
        # Deliberately only builds while there is something IN RANGE, so the
        # volley is paid for with shots actually given up. Building it from out
        # of range cost nothing at all, which made "open every battle holding
        # fire" a strictly free +150% -- a dominant opening rather than a
        # decision about when to loose.
        if self._ranged and not self.fire_at_will and dist <= self.attack_range:
            self.volley = min(1.0, self.volley + dt / orders.VOLLEY_FULL_SECONDS)

        if dist > self.attack_range:
            # Holding ground means exactly that: face them, wait, and swing at
            # whatever closes to within reach (Battle.choose_target already
            # prefers an in-reach enemy for a holding unit).
            if self.holds_position or not self._screened(dist):
                self.charge = 0.0
                return
            self.advancing = True
            move = self.effective_speed * dt
            self.x += dx / dist * move
            self.y += dy / dist * move
            # Galloping toward the enemy builds couched-charge momentum. A
            # bogged-down unit is in the attack branch instead, so its charge
            # decays to nothing -- devastating on impact, weak in a grind.
            if self.type.get("charge"):
                self.charge = min(1.0, self.charge + dt / self.type.get("charge_ramp", 1.2))
        elif self._cd <= 0:
            # Ordered to hold fire: stand with the arrow drawn. The cooldown is
            # deliberately NOT ticked forward here, so releasing later doesn't
            # also owe a reload.
            if self._ranged and not self.fire_at_will:
                return
            self._cd = self.effective_cooldown
            dmg = (self.damage * self._aura("damage_mult")
                   * orders.stance_mod(self.stance, "damage_mult"))
            charging = self.type.get("charge")
            if charging:
                # melee_floor (<1) at zero momentum up to melee_floor+charge_bonus
                # at a full gallop -- see UNIT_TYPES.
                floor = self.type.get("melee_floor", 0.5)
                dmg = self.damage * (floor + self.type.get("charge_bonus", 2.0) * self.charge)
            # accuracy (see UNIT_TYPES) defaults to 1.0 -- melee always
            # connects when in range; a miss still fires (the arrow flies,
            # the cooldown ticks) but deals no damage.
            # A held volley spends itself on this one shot -- the payoff for
            # having stood there not shooting.
            first_strike = (self._struck is not None
                            and self.target.uid not in self._struck)
            if first_strike:
                dmg *= self.type["first_strike"]
                self._struck.add(self.target.uid)
            accuracy = self._accuracy
            if self.volley > 0.0:
                dmg *= 1.0 + orders.VOLLEY_DAMAGE_BONUS * self.volley
                accuracy = min(1.0, accuracy
                               + orders.VOLLEY_ACCURACY_BONUS * self.volley)
                self.volley = 0.0
            outcome = "miss"
            if random.random() < accuracy:
                momentum = self.charge
                outcome = self.target.take_hit(self, dmg, battle)
                if first_strike and outcome == "hit":
                    battle.spawn_effect(self.target.x, self.target.y,
                                        "impact", self.faction.color)
                if charging and outcome == "hit" and momentum >= _IMPACT_CHARGE_MIN:
                    battle.spawn_effect(self.target.x, self.target.y, "impact",
                                        self.faction.color)
                    self._charge_splash(battle, dmg, momentum)
            if charging:
                self.charge = 0.0   # impact spent -- must back off and re-accelerate
                # Ordered to cycle: don't stand and grind, pull out now and
                # line up the next run.
                if self.stance == orders.STANCE_CYCLE_CHARGE:
                    self._begin_cycle_withdraw(battle)
            if self.cleave and outcome == "hit":
                self._cleave(battle, dmg)
            if self._ranged:
                battle.spawn_projectile(self.x, self.y,
                                        self.target.x, self.target.y,
                                        self.faction.color)
            if battle.on_attack:
                battle.on_attack(self, self.target, outcome)

    def _screened(self, dist_to_target):
        """True unless this is a commander who has run out of soldiers between
        himself and his target -- see unit_types.COMMANDER_SCREEN_MIN.

        Only ever costs anything for the one commander per army; every other
        unit short-circuits on the first test."""
        if not getattr(self, "is_commander", False) or self.target is None:
            return True
        tx, ty = self.target.x, self.target.y
        ahead = 0
        for u in self.faction.units:
            if u is self or not u.alive:
                continue
            if math.hypot(u.x - tx, u.y - ty) < dist_to_target:
                ahead += 1
                if ahead >= COMMANDER_SCREEN_MIN:
                    return True
        return False

    # --- cavalry: charge and regroup -----------------------------------------
    # Riders are worst in a grind (melee_floor) and best out of a gallop, but
    # left alone they bury themselves in the first line they touch and stay
    # there fighting at a fraction of their worth. This makes them behave the
    # way cavalry is supposed to: hit, pull clear, pick the fattest formation
    # on the field, and come again.
    #
    # Returns True if it took over movement for this tick (caller returns).
    CYCLE_WITHDRAW_SECONDS = 1.9   # how long they run before turning about
    CYCLE_WITHDRAW_DIST = 150.0    # how far back the rally point is set
    CYCLE_REENGAGE_SLACK = 12.0    # px of the rally point that counts as reached

    def _update_cycle_charge(self, dt, battle):
        if self._cycle_state == "withdraw":
            self._cycle_timer -= dt
            rx, ry = self._cycle_rally or (self.x, self.y)
            dx, dy = rx - self.x, ry - self.y
            dist = math.hypot(dx, dy)
            if self._cycle_timer <= 0.0 or dist <= self.CYCLE_REENGAGE_SLACK:
                # Turn about and pick the fattest enemy formation to hit next,
                # rather than whatever happens to be nearest -- the whole point
                # of pulling out is choosing where the next impact lands.
                self._cycle_state = "run"
                self.target = battle.densest_enemy(self) or battle.nearest_enemy(self)
                self._retarget_cd = 1.2   # commit to it; don't re-shop mid-run
                return False
            if dist > 1e-6:
                self.advancing = True     # pulling out still counts as moving,
                                          # so they shove clear of the scrum
                move = self.effective_speed * dt
                self.x += dx / dist * move
                self.y += dy / dist * move
                self.facing = (dx / dist, dy / dist)
            # Momentum builds on the way out too: by the time they turn about
            # they are already at a gallop, which is what makes the second
            # charge land as hard as the first.
            self.charge = min(1.0, self.charge
                              + dt / self.type.get("charge_ramp", 1.2))
            return True
        return False

    def _begin_cycle_withdraw(self, battle):
        """Called the instant a cycling rider lands an impact: set a rally point
        back the way it came and disengage."""
        self._cycle_state = "withdraw"
        self._cycle_timer = self.CYCLE_WITHDRAW_SECONDS
        # Straight back from whatever it just hit, not to a fixed home corner:
        # that keeps the turnaround short and stops the whole squadron funnelling
        # to one spot on the map.
        fx, fy = self.facing
        rx = self.x - fx * self.CYCLE_WITHDRAW_DIST
        ry = self.y - fy * self.CYCLE_WITHDRAW_DIST
        r = self.radius
        self._cycle_rally = (min(battle.width - r, max(r, rx)),
                             min(battle.height - r, max(r, ry)))

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
