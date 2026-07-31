"""Special units behave like what they are, not like another swordsman.

    python dev/test_special_roles.py

Every signature unit had special STATS and default BEHAVIOUR: it walked at its
own nearest enemy exactly like a line soldier. So a Shieldwarden whose entire
value is the line taking less punishment walked out of the line, and a Sapper
built to break up a packed formation bombed whichever single man was closest.

Each assertion below is structural -- where a unit stands, what it picks --
never a win rate. What these roles do to the roster is measured once in the
tournament and recorded, not gated here (HANDOFF: a win rate over a handful of
battles is a coin flip, and it has failed builds twice).
"""
import math
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import random

from app.battle import movement, roles
from app.battle.battle import Battle, Army
from app.battle.unit_types import UNIT_TYPES

FIELD = (1200, 800)


def make(a_comp, b_comp, seed=5, a_species="Dwarves", b_species="Humans"):
    random.seed(seed)
    b = Battle(*FIELD)
    b.deploy(Army("A", "#cc3333", 0, species=a_species), a_comp, 0)
    b.deploy(Army("B", "#3399cc", 1, species=b_species), b_comp, 1)
    return b


def run(b, seconds, dt=1 / 60):
    t = 0.0
    while not b.over and t < seconds:
        b.update(dt)
        t += dt
    return t


def toward_enemy(unit, army):
    """How far in front of its own army's centre this unit stands, measured
    along the direction of the enemy. Negative is behind the line."""
    cx, cy = army.centre
    ex, ey = army.enemy_centre
    dx, dy = ex - cx, ey - cy
    mag = math.hypot(dx, dy) or 1.0
    return ((unit.x - cx) * dx + (unit.y - cy) * dy) / mag


print("--- every special carries a role, and no ordinary soldier does ---")
special = {"shieldwarden": roles.ANCHOR, "bannerman": roles.BANNER,
           "bladesinger": roles.FLANKER, "berserker": roles.FRENZIED,
           "sapper": roles.BOMBARD, "assassin": roles.INFILTRATOR}
for key, role in special.items():
    assert UNIT_TYPES[key].get("role") == role, (key, UNIT_TYPES[key].get("role"))
for key in ("infantry", "archer", "cavalry", "commander"):
    assert "role" not in UNIT_TYPES[key], f"{key} was given a role"
print(f"  ok    {len(special)} specials tagged, the four ordinary types untouched")

print("\n--- a role changes no stat ---")
# Every numeric field of every special must be exactly what the table says --
# a role is where a unit stands and what it picks, and nothing else.
b = make({"shieldwarden": 4, "infantry": 10}, {"infantry": 12})
warden = next(u for u in b.armies[0].units if u.type_key == "shieldwarden")
t = UNIT_TYPES["shieldwarden"]
from app.world.lexicon import species_traits
tr = species_traits("Dwarves")
assert abs(warden.max_hp - t["max_hp"] * tr["unit_hp_mult"]) < 1e-9
assert abs(warden.damage - t["damage"] * tr["unit_damage_mult"]) < 1e-9
assert abs(warden.speed - t["speed"] * tr["unit_speed_mult"]) < 1e-9
print("  ok    the Shieldwarden's numbers are the table's numbers")

print("\n--- station keeping: measured by turning it off ---")
# A/B by DISABLING the role, which is this project's standing pattern for "did
# the new mechanism do it". Two numbers per unit: how far forward of its own
# army's centre it stands (the anchor's job is to be in front of the men it
# protects, the banner's is not to be), and how many allies its aura actually
# covers, which is the whole reason either unit exists.
def station_report(comp, key, species, seconds=9.0, role_on=True):
    real = roles.station
    if not role_on:
        roles.station = lambda unit: None
    try:
        b = make(comp, {"infantry": 30}, a_species=species)
        run(b, seconds)
        army = b.armies[0]
        mine = [u for u in army.units if u.type_key == key and u.alive]
        foot = [u for u in army.units if u.type_key == "infantry" and u.alive]
        if not mine or not foot or army.centre is None:
            return None
        lead = statistics.mean(toward_enemy(u, army) for u in mine)
        foot_lead = statistics.mean(toward_enemy(u, army) for u in foot)
        covered = sum(1 for u in foot
                      if any(math.hypot(s.x - u.x, s.y - u.y) <= s.aura_radius
                             for s in mine))
        stray = statistics.mean(math.hypot(u.x - army.centre[0],
                                           u.y - army.centre[1]) for u in mine)
        return lead - foot_lead, covered / len(foot), stray
    finally:
        roles.station = real


anchor_off = station_report({"shieldwarden": 5, "infantry": 30}, "shieldwarden",
                            "Dwarves", role_on=False)
anchor_on = station_report({"shieldwarden": 5, "infantry": 30}, "shieldwarden",
                           "Dwarves", role_on=True)
print(f"  shieldwarden  role off: {anchor_off[0]:+6.0f}px vs the line, "
      f"{anchor_off[1]:.0%} of it covered")
print(f"  shieldwarden  role on : {anchor_on[0]:+6.0f}px vs the line, "
      f"{anchor_on[1]:.0%} of it covered")
assert anchor_on[0] > anchor_off[0], (
    "the anchor is no further forward with the role than without it")
assert anchor_on[1] >= anchor_off[1], "the anchor's aura covers fewer men"
print("  ok    the anchor moves up the line and covers more of it")

# Two banners over forty men, not five over thirty: at five the 125px aura
# covers the whole line either way and the measurement says nothing.
BANNER_COMP = {"bannerman": 2, "infantry": 40}
banner_off = station_report(BANNER_COMP, "bannerman", "Humans", role_on=False)
banner_on = station_report(BANNER_COMP, "bannerman", "Humans", role_on=True)
print(f"  bannerman     role off: {banner_off[1]:.0%} of the line covered, "
      f"standing {banner_off[2]:.0f}px from its own army's centre")
print(f"  bannerman     role on : {banner_on[1]:.0%} of the line covered, "
      f"standing {banner_on[2]:.0f}px from its own army's centre")
assert banner_on[2] < banner_off[2], (
    "the banner wanders as far from the body of the army as it did without a "
    "role -- it is still chasing whoever it is fighting")
assert banner_on[1] >= banner_off[1], "the banner's aura covers fewer men"
print("  ok    the banner stays with the body of the army, and covers more of it")

print("\n--- the flanker picks the EDGE of the enemy formation ---")
b = make({"bladesinger": 8, "archer": 12}, {"infantry": 40}, a_species="Elves")
run(b, 7.0)
cache = b._target_cache[0]
ecx, ecy = cache[7], cache[8]
singers = [u for u in b.armies[0].units if u.type_key == "bladesinger" and u.alive
           and u.target is not None and u.target.alive]
bows = [u for u in b.armies[0].units if u.type_key == "archer" and u.alive
        and u.target is not None and u.target.alive]
assert singers and bows, "nobody had a live target to compare"
s_edge = statistics.mean(math.hypot(u.target.x - ecx, u.target.y - ecy)
                         for u in singers)
b_edge = statistics.mean(math.hypot(u.target.x - ecx, u.target.y - ecy)
                         for u in bows)
print(f"  bladesingers' targets sit {s_edge:.0f}px out of the enemy centre, "
      f"archers' targets {b_edge:.0f}px")
assert s_edge > b_edge, "the flanker is fighting the middle of the formation"
print("  ok    it works the flanks")

print("\n--- the frenzied unit goes where the fighting is thickest ---")
# A/B, and it has to be: comparing berserkers against their own army's
# swordsmen measures the wrong thing entirely -- a berserker is faster, so it
# arrives first, at a fight nobody has joined yet, and reads as picking a LESS
# crowded target while doing exactly what it should.
def crowd_report(role_on):
    saved = UNIT_TYPES["berserker"].pop("role", None)
    if role_on and saved is not None:
        UNIT_TYPES["berserker"]["role"] = saved
    try:
        b = make({"berserker": 8, "infantry": 20}, {"infantry": 40},
                 a_species="Orcs")
        # Where it STANDS, not who it targets: "goes where the fighting is
        # thickest" is a position. Averaged over the whole melee rather than
        # sampled once -- a single instant lands wherever the retarget throttle
        # happens to have left everyone, and the first sample was taken before
        # the lines had even met (0.0 enemies nearby, for both arms of the A/B).
        samples = []
        t = 0.0
        while not b.over and t < 26.0:
            b.update(1 / 60)
            t += 1 / 60
            if t < 10.0 or int(t * 60) % 30:
                continue
            zerks = [u for u in b.armies[0].units
                     if u.type_key == "berserker" and u.alive]
            foes = [u for a in b.armies if a.side != 0 for u in a.units if u.alive]
            if zerks and foes:
                samples.append(statistics.mean(
                    sum(1 for f in foes
                        if math.hypot(f.x - z.x, f.y - z.y) <= 70.0)
                    for z in zerks))
        return statistics.mean(samples) if samples else None
    finally:
        UNIT_TYPES["berserker"].pop("role", None)
        if saved is not None:
            UNIT_TYPES["berserker"]["role"] = saved


z_off = crowd_report(False)
z_crowd = crowd_report(True)
print(f"  role off: a berserker stands among {z_off:.1f} enemies")
print(f"  role on : a berserker stands among {z_crowd:.1f} enemies")
assert z_crowd > z_off, "the berserker fights no thicker a press than before"
assert UNIT_TYPES["berserker"].get("no_cohesion") is True
print("  ok    seeks the scrum, and keeps no formation")

print("\n--- the bombardier bombs a knot, not the nearest man ---")
b = make({"sapper": 6, "infantry": 20}, {"infantry": 40}, a_species="Goblins")
run(b, 10.0)
sappers = [u for u in b.armies[0].units if u.type_key == "sapper" and u.alive
           and u.target is not None and u.target.alive]
assert sappers, "no sapper survived to pick a target"
radius = UNIT_TYPES["sapper"]["splash_radius"]
foes = [u for a in b.armies if a.side != 0 for u in a.units if u.alive]
caught = []
nearest_caught = []
for s in sappers:
    caught.append(sum(1 for f in foes
                      if math.hypot(f.x - s.target.x, f.y - s.target.y) <= radius))
    near = min(foes, key=lambda f: math.hypot(f.x - s.x, f.y - s.y))
    nearest_caught.append(sum(1 for f in foes
                              if math.hypot(f.x - near.x, f.y - near.y) <= radius))
print(f"  a sapper's bomb catches {statistics.mean(caught):.1f} men where it "
      f"aims, against {statistics.mean(nearest_caught):.1f} on the nearest man")
assert statistics.mean(caught) >= statistics.mean(nearest_caught), (
    "aiming at the nearest man would catch more than the chosen target")
print("  ok    it aims at the crowd")

print("\n--- the infiltrator goes AROUND a formation rather than through it ---")
# One assassin, one wall of foot with bowmen behind it. Measure how close it
# passes to the enemy line on its way in, with enemy avoidance on and off.
def closest_approach_to_line(avoid):
    saved = movement.INFILTRATE_WEIGHT
    movement.INFILTRATE_WEIGHT = saved if avoid else 0.0
    try:
        b = make({"assassin": 1, "infantry": 12}, {"infantry": 24, "archer": 8},
                 seed=3, a_species="Goblins")
        killer = next(u for u in b.armies[0].units if u.type_key == "assassin")
        killer.max_hp = killer.hp = 1e9      # geometry, not survival
        worst = []
        t = 0.0
        while not b.over and t < 18.0:
            b.update(1 / 60)
            t += 1 / 60
            foot = [u for u in b.armies[1].units
                    if u.type_key == "infantry" and u.alive]
            if foot and killer.target is not None and killer.target._ranged:
                worst.append(min(math.hypot(f.x - killer.x, f.y - killer.y)
                                 for f in foot))
        return statistics.mean(worst) if worst else None
    finally:
        movement.INFILTRATE_WEIGHT = saved


off = closest_approach_to_line(False)
on = closest_approach_to_line(True)
print(f"  mean distance from the enemy line while running at the bowmen: "
      f"{off:.0f}px straight in, {on:.0f}px going round")
assert on > off, "the assassin runs just as close to the line as before"
print("  ok    it keeps its distance from the men that kill it")

print("\n--- and a full five-species field still resolves ---")
for species, comp in (("Dwarves", {"shieldwarden": 6, "infantry": 24}),
                      ("Humans", {"bannerman": 6, "infantry": 24}),
                      ("Elves", {"bladesinger": 6, "archer": 24}),
                      ("Orcs", {"berserker": 6, "infantry": 24}),
                      ("Goblins", {"sapper": 6, "assassin": 6, "infantry": 18})):
    b = make(comp, {"infantry": 20, "archer": 10}, seed=21, a_species=species)
    t = run(b, 150.0)
    assert b.over, f"{species} fight did not resolve in 150s"
    print(f"  ok    {species:8} resolved in {t:5.1f}s")

print("\nSPECIAL ROLES TEST PASSED")
