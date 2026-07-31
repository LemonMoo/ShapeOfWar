"""Biome overhaul phase E: terrain in battle.

    python dev/test_battle_terrain.py

The battle sim had no terrain hooks of any kind -- a fight in a marsh
resolved identically to one on open plains. Now the region's dominant biome
sets three multipliers (speed / defender / ranged) that are baked into each
unit at deploy time.

The two things most worth guarding are structural rather than numeric: that
the defender bonus really only reaches the defending side (an even-handed
"high ground" bonus is not a high-ground bonus at all), and that nothing was
added to the per-tick path -- the sim runs to a 16.7ms frame budget and a
terrain lookup per soldier per frame would spend it for something that cannot
change mid battle.
"""
import sys
import os
import inspect

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.battle.battle import (Battle, Army, BATTLE_TERRAIN, NEUTRAL_TERRAIN,
                               DEFENDER_SIDE, terrain_profile, terrain_note)
from app.world import resources as R

COMP = {"spearman": 12, "archer": 8}


def make(biome, with_commander=True):
    b = Battle(1200, 800)
    b.set_terrain(biome)
    for side in (0, 1):
        army = Army(f"side{side}", side)
        b.deploy(army, COMP, side, with_commander=with_commander)
        b.armies.append(army) if army not in b.armies else None
    return b


print("--- every biome the world can generate can be fought on ---")
real = ({b for row in R._BIOME_MATRIX for b in row}
        | {"mountain", "highland", "coastal", "swamp"})
missing = real - set(BATTLE_TERRAIN)
assert not missing, f"no battle terrain for {missing}"
extra = set(BATTLE_TERRAIN) - real
assert not extra, f"battle terrain for biomes that do not exist: {extra}"
for biome, profile in BATTLE_TERRAIN.items():
    assert set(profile) == set(NEUTRAL_TERRAIN), (biome, profile)
    assert all(v > 0 for v in profile.values()), (biome, profile)
print(f"  ok    all {len(real)} biomes have a complete, positive profile")

print("\n--- unknown ground is neutral, so nothing that skips it changes ---")
assert terrain_profile(None) == NEUTRAL_TERRAIN
assert terrain_profile("no such biome") == NEUTRAL_TERRAIN
assert Battle(900, 600).terrain == NEUTRAL_TERRAIN, (
    "a battle nobody set terrain on must fight exactly as it always did")
print("  ok    None / unknown / never-set all give the neutral profile")

print("\n--- the ground actually reaches the soldiers ---")
plains = make("plains")
swamp = make("swamp")
a_plains = plains.armies[0].units[0]
a_swamp = swamp.armies[0].units[0]
assert a_swamp.speed < a_plains.speed, (a_swamp.speed, a_plains.speed)
ratio = a_swamp.speed / a_plains.speed
assert abs(ratio - BATTLE_TERRAIN["swamp"]["speed"]) < 1e-9, ratio
print(f"  ok    a spearman in swamp moves at {ratio:.2f}x his plains speed")

print("\n--- cover shortens the bow line, and only the bow line ---")
jungle = make("jungle")


def archer(battle, side):
    return next(u for u in battle.armies[side].units if getattr(u, "_ranged", False))


def melee(battle, side):
    return next(u for u in battle.armies[side].units
                if not getattr(u, "_ranged", False) and not u.is_commander)


j_range = archer(jungle, 0)._range
p_range = archer(plains, 0)._range
assert j_range < p_range, (j_range, p_range)
assert abs(j_range / p_range - BATTLE_TERRAIN["jungle"]["ranged"]) < 1e-9
assert melee(jungle, 0)._range == melee(plains, 0)._range, (
    "a spear got longer or shorter because of the trees")
print(f"  ok    archer reach {p_range:.0f} -> {j_range:.0f} in jungle; "
      f"melee reach untouched")

print("\n--- CRITICAL: high ground favours the DEFENDER, not everyone ---")
# An even-handed bonus is not a high-ground bonus. This is the whole mechanic.
mountain = make("mountain")
atk = melee(mountain, 0)
dfn = melee(mountain, DEFENDER_SIDE)
base = melee(plains, 0).max_hp
assert abs(atk.max_hp - base) < 1e-9, (
    f"the attacker got the defender's bonus ({atk.max_hp} vs {base})")
assert dfn.max_hp > atk.max_hp, (dfn.max_hp, atk.max_hp)
assert abs(dfn.max_hp / base - BATTLE_TERRAIN["mountain"]["defender"]) < 1e-9
assert dfn.hp == dfn.max_hp, "the bonus raised the ceiling but not the health"
print(f"  ok    on a mountain the defender fields {dfn.max_hp:.0f} hp against "
      f"the attacker's {atk.max_hp:.0f}")

print("\n--- and the commander stands on the same ground as his men ---")
cmd = mountain.armies[DEFENDER_SIDE].commander
plain_cmd = plains.armies[DEFENDER_SIDE].commander
assert cmd is not None and plain_cmd is not None
assert cmd.max_hp > plain_cmd.max_hp, (cmd.max_hp, plain_cmd.max_hp)
assert cmd.speed < plains.armies[0].commander.speed * 0.99 + 1e-9, (
    "the commander walked over a mountain at his parade-ground pace")
print(f"  ok    commander {plain_cmd.max_hp:.0f} -> {cmd.max_hp:.0f} hp on the height")

print("\n--- no per-tick cost was added to the sim loop ---")
# Terrain cannot change during a battle, so looking it up every frame for
# every soldier would spend the frame budget for nothing.
for fn in (Battle.update, Battle.step) if hasattr(Battle, "step") else (Battle.update,):
    src = "\n".join(line for line in inspect.getsource(fn).splitlines()
                    if not line.lstrip().startswith("#"))
    for token in ("terrain", "BATTLE_TERRAIN", "self.biome"):
        assert token not in src, (
            f"{fn.__name__} touches {token} -- terrain belongs at deploy time")
print("  ok    the tick loop never looks at terrain")

print("\n--- the player is told what the ground is doing ---")
# A modifier nobody can see is a modifier that does not exist.
for biome, profile in BATTLE_TERRAIN.items():
    note = terrain_note(biome)
    if profile == NEUTRAL_TERRAIN:
        assert note == "", (biome, note)
    else:
        assert note, f"{biome} changes the fight but says nothing about it"
assert terrain_note(None) == ""
print(f"  ok    every non-neutral biome has a banner note, e.g. swamp: "
      f"\"{terrain_note('swamp')}\"")

print("\n--- terrain does not decide the fight on its own ---")
# Sized to colour a battle, not to win it. If any single multiplier ever
# drifts past these, it is a balance decision and wants saying out loud.
for biome, profile in BATTLE_TERRAIN.items():
    assert 0.7 <= profile["speed"] <= 1.0, (biome, profile)
    assert 1.0 <= profile["defender"] <= 1.25, (biome, profile)
    assert 0.65 <= profile["ranged"] <= 1.0, (biome, profile)
print("  ok    every multiplier is inside the intended modest band")

print("\n--- a battle on hard ground still actually resolves ---")
for biome in ("swamp", "mountain", "jungle", "plains"):
    b = make(biome)
    for _ in range(6000):
        b.update(1 / 60)
        if b.over:
            break
    assert b.over, f"a battle in {biome} never ended in 100 simulated seconds"
    side = b.armies.index(b.winner) if b.winner in b.armies else b.winner
    print(f"  ok    {biome:<9} resolved, winner side {side}")

print("\nBATTLE TERRAIN TEST PASSED")
