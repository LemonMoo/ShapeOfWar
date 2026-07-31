"""Weather phase 2: a live per-turn travel rate for every convoy.

    python dev/test_travel.py [world.pkl]

Before this, nothing about travel varied turn-to-turn: caravans, regional
shipments and local wagons all did a flat `turn_progress += 1`, so a route's
length was settled at dispatch and nothing on the way could change it. That
is why HANDOFF S10 puts "build the live rate generically, verify it with
weather OFF, then hang weather on it" in that order.

The load-bearing property is that the terrain half is MEAN-NEUTRAL. Almost
every trade route in a developed world runs on roads (measured route pace
0.65 against open country's 1.0), so a naive terrain rate would have made all
trade ~50% faster overnight and quietly re-tuned the entire economy. Dividing
by the route's own average means fair-weather transit times are exactly what
they always were, and weather is the only thing that actually delays anyone.
"""
import sys
import os
import pickle
import statistics

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import travel
from app.world import resources as R
from app.world import weather as W

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "worlds", "dev560.pkl")
w = pickle.load(open(PATH, "rb"))


def convoys(world):
    return [c for c in (list(getattr(world, "caravans", []))
                        + list(getattr(world, "regional_shipments", []))
                        + list(world.local_shipments))
            if getattr(c, "path", None) and len(c.path) > 1]


def journey(world, path, total, mult=1.0):
    """Turns to cross `path` at the live rate, `mult` standing in for a
    constant weather multiplier over the whole route."""
    pace = sum(travel._cell_cost(world, p) for p in path) / len(path)
    progress, turns = 0.0, 0
    while progress < total and turns < 900:
        idx = int(min(1.0, progress / total) * (len(path) - 1))
        rate = pace / travel._cell_cost(world, path[idx]) * mult
        progress += max(travel.MIN_TRAVEL_RATE, rate)
        turns += 1
    return turns


live = convoys(w)
print(f"world: turn {w.turn}, {len(live)} convoys in flight")
assert live, "this save has nothing in transit -- pick a busier world"

print("\n--- CRITICAL: with weather off, nothing about trade timing changes ---")
# If this drifts, every transit constant in trade.py has been silently
# re-tuned by a change that was supposed to be presentation only.
errors = [journey(w, c.path, c.turns_total) - c.turns_total for c in live]
mean = statistics.mean(errors)
assert abs(mean) < 0.5, f"fair-weather arrival drifted {mean:+.2f} turns on average"
assert all(abs(e) <= 1 for e in errors), (
    f"a route arrived {max(errors, key=abs):+d} turns off its costed time")
print(f"  ok    mean drift {mean:+.2f} turns, every route within 1 turn (n={len(errors)})")

print("\n--- ...which is only true because the route's own pace is the divisor ---")
paces = [travel.route_pace(w, c) for c in live]
print(f"  ok    real routes average pace {statistics.mean(paces):.2f} "
      f"(open country is 1.00) -- they run on roads, so a raw terrain rate "
      f"would have made all trade ~{1/statistics.mean(paces):.1f}x faster")
assert statistics.mean(paces) < 0.95, (
    "routes no longer favour roads; re-check that normalising is still needed")

print("\n--- the rate is genuinely live, not a constant ---")
sample = live[0]
rates = {travel._cell_cost(w, p) for p in sample.path}
assert len(rates) > 1, "picked a route with uniform ground; test is not proving much"
fast = travel.route_pace(w, sample) / min(rates)
slow = travel.route_pace(w, sample) / max(rates)
assert fast > slow
print(f"  ok    one route varies {slow:.2f}x to {fast:.2f}x along its own length")

print("\n--- road beats terrain, same rule the marching column uses ---")
road = next((p for c in live for p in c.path
             if travel._cell_cost(w, p) == travel.ROAD_MOVE_COST), None)
assert road is not None, "no convoy is on a road anywhere"
assert travel.ROAD_MOVE_COST < min(travel.TERRAIN_MOVE_COST.values())
print(f"  ok    a road cell costs {travel.ROAD_MOVE_COST}, better than the best "
      f"open country ({min(travel.TERRAIN_MOVE_COST.values())})")

print("\n--- every weather kind is costed, and drought is free ON PURPOSE ---")
assert set(travel.WEATHER_TRAVEL_RATE) == set(W.KINDS), (
    set(travel.WEATHER_TRAVEL_RATE) ^ set(W.KINDS))
assert travel.WEATHER_TRAVEL_RATE[W.DROUGHT] == (1.0, 1.0), (
    "dry ground is good for a wagon -- a drought is a catastrophe in the "
    "fields and nothing at all on the road")
for kind in (W.STORM, W.BLIZZARD, W.FOG):
    mild, severe = travel.WEATHER_TRAVEL_RATE[kind]
    assert 0 < severe < mild < 1.0, (kind, mild, severe)
print("  ok    Storm/Blizzard/Fog all slow travel, severe worse than mild; "
      "Drought does not")

print("\n--- Fog finally does something ---")
# It is generated in every climate and has no crop effect by design, so
# before this it was a purely cosmetic event.
assert travel.WEATHER_TRAVEL_RATE[W.FOG][0] < 1.0
assert not any(k[0] == W.FOG for k in R._CROP_WEATHER_IMPACT), (
    "Fog has grown a crop effect; this test's premise needs revisiting")
print("  ok    Fog has no crop effect but does slow a convoy")

print("\n--- weather is what actually delays a journey ---")
longer = [(p, t) for p, t in ((c.path, c.turns_total) for c in live) if t >= 5]
assert longer, "no route long enough to measure a ratio that isn't rounding"
for kind in (W.STORM, W.BLIZZARD, W.FOG):
    for label, mult in zip(("Mild", "Severe"), travel.WEATHER_TRAVEL_RATE[kind]):
        got = statistics.mean(journey(w, p, t, mult) / t for p, t in longer)
        ideal = 1 / mult
        assert got > 1.0, (kind, label, got)
        assert abs(got - ideal) < 0.25, (kind, label, got, ideal)
        print(f"  ok    {kind:9} {label:7} {got:.2f}x longer (target {ideal:.2f}x)")

print("\n--- nothing ever stalls forever ---")
# A convoy pinned at zero would sit on the map collecting raid rolls, which
# is a bug wearing a mechanic's coat.
worst = min(travel.WEATHER_TRAVEL_RATE[k][1] for k in travel.WEATHER_TRAVEL_RATE)
hardest = max(travel.TERRAIN_MOVE_COST.values())
floor_case = worst * (min(paces) / hardest)
assert max(travel.MIN_TRAVEL_RATE, floor_case) >= travel.MIN_TRAVEL_RATE > 0
assert 1 / travel.MIN_TRAVEL_RATE <= 4.0, (
    "the worst possible journey is now more than 4x its fair-weather length")
print(f"  ok    rate floors at {travel.MIN_TRAVEL_RATE}, so the worst journey "
      f"is {1/travel.MIN_TRAVEL_RATE:.0f}x its costed time and no worse")

print("\n--- open water and unclaimed land are clear, by construction ---")
# Weather is simulated per owned REGION, so there is none out at sea. That
# is a real limit, documented in travel.py, not an accident.
assert travel._weather_rate(w, (-5, -5)) == 1.0, "an off-map cell was not clear"
print("  ok    an off-map / regionless cell reads as clear weather")

print("\n--- all three convoy kinds go through the same rate ---")
import inspect
from app.world import trade as T
for fn in (T.advance_caravans, T.advance_regional_shipments,
           R.advance_local_shipments):
    src = inspect.getsource(fn)
    assert "convoy_rate" in src, (
        f"{fn.__name__} still does a flat turn_progress += 1")
print("  ok    caravans, regional shipments and local wagons all use it")

print("\n--- a real simulation still runs, with weather live throughout ---")
before = sum(n.population for n in list(w.settlements) + list(w.villages))
for _ in range(20):
    R.advance_turn(w)
after = sum(n.population for n in list(w.settlements) + list(w.villages))
negative = [(n.name, r, a) for n in list(w.settlements) + list(w.villages)
            for r, a in (n.resources or {}).items() if a < 0]
assert not negative, negative[:3]
stuck = [c for c in convoys(w) if getattr(c, "turn_progress", 0) > c.turns_total * 5]
assert not stuck, f"{len(stuck)} convoys are massively overdue"
print(f"  ok    20 turns, pop {before:,} -> {after:,}, no negative stock, "
      f"nothing stranded")

print("\nTRAVEL TEST PASSED")
