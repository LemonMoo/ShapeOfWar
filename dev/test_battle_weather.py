"""Weather phase 4: what the sky does to a battle.

    python dev/test_battle_weather.py

Phase E asked WHERE a battle is fought. This asks WHEN. The two stack on the
same hook -- baked into each unit at deploy, never read per tick -- but they
differ in one way that matters more than any number here:

    terrain is ASYMMETRIC. High ground favours whoever holds it, which is the
        entire point of high ground.
    weather is SYMMETRIC. Rain falls on both armies. A storm that helped the
        defender would be a second high-ground bonus wearing a cloud, and it
        would make defending in bad weather strictly better rather than
        differently hard.

HANDOFF S10 asks for "at least a basic sanity tournament pass ... so nothing
ships silently unplayable". The bottom of this file is that pass, and the
thing it is actually watching for is whether severe fog -- which cuts a bow's
reach nearly in half -- makes an archer army worthless.
"""
import sys
import os
import inspect

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.battle.battle import (Battle, Army, BATTLE_WEATHER, NEUTRAL_WEATHER,
                               BATTLE_TERRAIN, DEFENDER_SIDE, MILD_WEATHER_SCALE,
                               weather_profile, weather_note)
from app.world.weather import WeatherEvent, KINDS, MILD, SEVERE, DROUGHT, FOG

COMP = {"archer": 10, "spearman": 10}


def make(event=None, biome=None):
    b = Battle(1200, 800)
    if biome:
        b.set_terrain(biome)
    b.set_weather(event)
    for side in (0, 1):
        army = Army(f"side{side}", side)
        b.deploy(army, COMP, side)
        if army not in b.armies:
            b.armies.append(army)
    return b


def archer(battle, side):
    return next(u for u in battle.armies[side].units if getattr(u, "_ranged", False))


def melee(battle, side):
    return next(u for u in battle.armies[side].units
                if not getattr(u, "_ranged", False) and not u.is_commander)


print("--- every kind of weather is costed, and only real ones ---")
assert set(BATTLE_WEATHER) == set(KINDS), set(BATTLE_WEATHER) ^ set(KINDS)
for kind, profile in BATTLE_WEATHER.items():
    assert set(profile) == set(NEUTRAL_WEATHER), (kind, profile)
    assert all(0 < v <= 1.0 for v in profile.values()), (kind, profile)
print(f"  ok    all {len(KINDS)} kinds have a complete profile, none helpful")

print("\n--- a clear day changes nothing at all ---")
assert weather_profile(None) == NEUTRAL_WEATHER
assert Battle(900, 600).weather == NEUTRAL_WEATHER, (
    "a battle nobody set weather on must fight exactly as it always did")
clear = make(None)
never_set = Battle(1200, 800)
army = Army("plain", 0)
never_set.deploy(army, COMP, 0)
plain_archer = next(u for u in army.units if getattr(u, "_ranged", False))
assert plain_archer._accuracy == archer(clear, 0)._accuracy
assert plain_archer._range == archer(clear, 0)._range
assert plain_archer.speed == archer(clear, 0).speed
print("  ok    None / never-set both give the neutral profile")

print("\n--- drought does nothing here, ON PURPOSE ---")
# Same reasoning as travel.WEATHER_TRAVEL_RATE: dry hard ground is good to
# fight on. If every kind of weather were bad they would be interchangeable,
# and the point of having four is that they are not.
assert BATTLE_WEATHER[DROUGHT] == NEUTRAL_WEATHER, BATTLE_WEATHER[DROUGHT]
assert weather_note(WeatherEvent(DROUGHT, SEVERE, 10)) == "", (
    "a note that says the drought changes nothing is noise")
print("  ok    drought is neutral and says nothing about it")

print("\n--- severity scales the effect, it is not a second table ---")
for kind in KINDS:
    mild = weather_profile(WeatherEvent(kind, MILD, 10))
    severe = weather_profile(WeatherEvent(kind, SEVERE, 10))
    for key in NEUTRAL_WEATHER:
        assert abs((1 - mild[key]) - (1 - severe[key]) * MILD_WEATHER_SCALE) < 1e-9, (
            kind, key, mild[key], severe[key])
        assert mild[key] >= severe[key]
print(f"  ok    mild is exactly {MILD_WEATHER_SCALE} of severe, every kind, every field")

print("\n--- CRITICAL: weather falls on both armies ---")
# The one place this must differ from terrain. An asymmetric storm would be a
# second high-ground bonus wearing a cloud.
storm = make(WeatherEvent("storm", SEVERE, 10))
for side in (0, DEFENDER_SIDE):
    assert abs(melee(storm, side).max_hp - melee(clear, side).max_hp) < 1e-9, (
        "weather changed one side's toughness -- that is terrain's job")
assert abs(archer(storm, 0)._range - archer(storm, DEFENDER_SIDE)._range) < 1e-9
assert abs(archer(storm, 0)._accuracy - archer(storm, DEFENDER_SIDE)._accuracy) < 1e-9
assert abs(melee(storm, 0).speed - melee(storm, DEFENDER_SIDE).speed) < 1e-9
print("  ok    both sides get identical speed, reach and accuracy from a storm")

print("\n--- ...while terrain still favours the defender ---")
height = make(None, biome="mountain")
assert melee(height, DEFENDER_SIDE).max_hp > melee(height, 0).max_hp, (
    "the terrain bonus was lost when weather was layered on top")
print(f"  ok    on a mountain the defender still fields "
      f"{melee(height, DEFENDER_SIDE).max_hp:.0f} hp against "
      f"{melee(height, 0).max_hp:.0f}")

print("\n--- reach and accuracy are different questions ---")
# Whether a bowman can SEE the target is not whether the shot lands once
# taken. Fog answers the first, a wet string and a headwind the second.
fog = make(WeatherEvent(FOG, SEVERE, 10))
assert archer(fog, 0)._range < archer(clear, 0)._range
assert archer(storm, 0)._accuracy < archer(fog, 0)._accuracy, (
    "a storm should spoil the shooting more than fog does")
assert archer(fog, 0)._range < archer(storm, 0)._range, (
    "fog should shorten sightlines more than a storm does")
print(f"  ok    fog: reach {archer(clear,0)._range:.0f} -> "
      f"{archer(fog,0)._range:.0f}; storm: accuracy "
      f"{archer(clear,0)._accuracy:.2f} -> {archer(storm,0)._accuracy:.2f}")

print("\n--- and none of it touches a man with a spear in his hands ---")
assert melee(fog, 0)._range == melee(clear, 0)._range
assert melee(storm, 0)._accuracy == melee(clear, 0)._accuracy
print("  ok    melee reach and accuracy are unchanged by any weather")

print("\n--- weather and terrain stack rather than overriding ---")
both = make(WeatherEvent("blizzard", SEVERE, 10), biome="forest")
expected = (BATTLE_TERRAIN["forest"]["speed"]
            * BATTLE_WEATHER["blizzard"]["speed"])
assert abs(melee(both, 0).speed / melee(clear, 0).speed - expected) < 1e-6, (
    melee(both, 0).speed / melee(clear, 0).speed, expected)
print(f"  ok    a blizzard in a forest is {expected:.2f}x speed, "
      f"both effects applied")

print("\n--- no per-tick cost, same as terrain ---")
src = "\n".join(line for line in inspect.getsource(Battle.update).splitlines()
                if not line.lstrip().startswith("#"))
for token in ("weather", "BATTLE_WEATHER", "self.weather"):
    assert token not in src, (
        f"Battle.update touches {token} -- weather belongs at deploy time")
print("  ok    the tick loop never looks at the weather")

print("\n--- the player is told what the sky is doing ---")
for kind in KINDS:
    for severity in (MILD, SEVERE):
        event = WeatherEvent(kind, severity, 10)
        note = weather_note(event)
        if weather_profile(event) == NEUTRAL_WEATHER:
            assert note == "", (kind, severity, note)
        else:
            assert note, f"{kind}/{severity} changes the fight but says nothing"
            assert ";" not in note, (
                "one clause per kind -- deriving the note from the numbers "
                "produced unreadable enumerations")
print(f"  ok    e.g. \"{weather_note(WeatherEvent(FOG, SEVERE, 10))}\"")

print("\n--- SANITY TOURNAMENT: nothing is made unplayable ---")
# HANDOFF S10's explicit requirement. The real risk is severe fog, which cuts
# a bow's reach nearly in half: if that makes an archer army hopeless then
# weather is deciding battles rather than colouring them.
BOW = {"archer": 16, "spearman": 6}
FOOT = {"swordsman": 12, "spearman": 10}
N = 10


def duel(event):
    b = Battle(1200, 800)
    b.set_weather(event)
    armies = []
    for side, comp in ((0, BOW), (1, FOOT)):
        army = Army(f"s{side}", side)
        b.deploy(army, comp, side)
        if army not in b.armies:
            b.armies.append(army)
        armies.append(army)
    for _ in range(12000):
        b.update(1 / 60)
        if b.over:
            break
    if not b.over or b.winner not in armies:
        return None
    return armies.index(b.winner)


rates = {}
for label, event in ([("clear", None)]
                     + [(f"{k} {s}", WeatherEvent(k, s, 20))
                        for k in KINDS for s in (MILD, SEVERE)]):
    results = [duel(event) for _ in range(N)]
    played = [r for r in results if r is not None]
    if not played:
        continue
    rates[label] = sum(1 for r in played if r == 0) / len(played)
    print(f"  ok    {label:18} archers win {rates[label]*100:3.0f}% "
          f"({len(played)} resolved)")

assert rates["clear"] > 0.5, (
    "archers are not the stronger side in the clear -- this whole tournament "
    "was calibrated against them being it")
worst = min(rates.values())
assert worst >= 0.25, (
    f"some weather drops the archer army to {worst*100:.0f}% -- weather is "
    f"deciding battles rather than colouring them")
assert min(rates.values()) < rates["clear"], "no weather affects the outcome at all"
print(f"  ok    worst case for archers is {worst*100:.0f}%, so no weather "
      f"makes an army worthless")

print("\nBATTLE WEATHER TEST PASSED")
