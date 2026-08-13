"""The realm progression model (app/world/progression.py): the development
score and the named age ladder.

    python dev/test_progression.py [world.pkl]

Slice 1 is observation-only -- it writes nothing and draws no randomness. The
properties this guards: determinism, a sane starting age, milestones that gate
the ladder exactly as the plan says, and a score that never falls as a realm
develops. The ladder is tested against a synthetic world (so each rung is
asserted precisely) and sanity-checked against a real save.
"""
import sys
import os
import pickle
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import progression as P

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "worlds", "dev560.pkl")

# --- synthetic world for precise ladder tests -------------------------------
def _sett(kind, fac=0):
    return NS(kind=kind, faction_idx=fac)

def _vill(fac=0, population=0, adults=0, resources=None):
    return NS(faction_idx=fac, population=population, adults=adults,
              resources=resources or {})

def _world(cities=1, towns=0, castles=0, villages=0, regions=1,
           population=0, adults=0, weapons=0, craft=None, trade=False,
           military=50):
    setts = ([_sett("city")] * cities + [_sett("town")] * towns
             + [_sett("castle")] * castles)
    res = {"Weapons": weapons} if weapons else {}
    if craft:
        res[craft] = 1
    vills = [_vill(population=population, adults=adults, resources=res)
             for _ in range(villages or (1 if (population or adults or res) else 0))]
    return NS(
        settlements=setts,
        villages=vills,
        regions=[NS(faction_idx=0) for _ in range(regions)],
        factions=[NS(stats={"military": military}, meta={"species": "Humans"})],
        trade_routes=[{"a_faction": 0, "b_faction": 1}] if trade else [],
    )


print("--- the ladder gates exactly as the plan says ---")
# Each rung: add its milestone(s) and the age must advance one step.
steps = [
    (dict(), 0, "Homestead"),
    (dict(towns=1), 1, "Age of Villages"),
    (dict(towns=1, cities=2), 2, "Age of Towns"),
    (dict(towns=1, cities=2, castles=1, adults=1000, weapons=40), 3, "Age of Cities"),
    (dict(towns=1, cities=2, castles=1, adults=1000, weapons=40,
          regions=4, craft="Planks"), 4, "Age of Kingdoms"),
    (dict(towns=1, cities=2, castles=1, adults=1000, weapons=40,
          regions=8, craft="Planks", trade=True), 5, "Age of Empire"),
]
for kwargs, want_idx, want_name in steps:
    idx, age = P.faction_age(_world(**kwargs), 0)
    assert idx == want_idx, (kwargs, want_idx, want_name, idx, age["name"])
    assert age["name"] == want_name, (kwargs, want_name, age["name"])
    print(f"  ok    {want_name:<15} index {idx}")
assert P.faction_age(_world(), 0)[1]["next"] == "Raise a village to a Town"
print(f"  ok    Homestead's next hint names the first rung")

print("\n--- a higher rung needs every lower rung too (cumulative) ---")
# A castle without towns/cities is not Age of Cities -- the ladder is ordered.
idx, _ = P.faction_age(_world(castles=1), 0)
assert idx == 0, f"castle alone should not skip to a later age, got {idx}"
# Armed without a castle is still only Age of Towns.
idx, _ = P.faction_age(_world(towns=1, cities=2, adults=1000, weapons=40), 0)
assert idx == 2, f"armed without a castle should stay Age of Towns, got {idx}"
print("  ok    milestones are cumulative, not skippable")

print("\n--- the score is monotonic in every axis ---")
base = P.development_score(_world(), 0)
more_pop = P.development_score(_world(population=5000, adults=3000), 0)
more_settle = P.development_score(_world(cities=2, towns=1), 0)
more_regions = P.development_score(_world(regions=5), 0)
assert more_pop > base and more_settle > base and more_regions > base, (
    base, more_pop, more_settle, more_regions)
print(f"  ok    {base:.1f} -> pop {more_pop:.1f} / settle {more_settle:.1f} "
      f"/ regions {more_regions:.1f}")

print("\n--- governance: capacity, overstretch, and the soft brake ---")
from app.world import expansion as E
# Capacity is the settlement ladder: base 1 + 3/city + 2/castle + 1/town.
assert P.governance_capacity(_world(cities=1), 0) == 4
assert P.governance_capacity(_world(cities=1, towns=2, castles=1), 0) == 8
# Overstretch is regions held past capacity, and never negative.
assert P.claim_overstretch(_world(cities=1, regions=6), 0) == 2
assert P.claim_overstretch(_world(cities=1, regions=3), 0) == 0
# A stretched realm pays more settlers and takes longer -- a tax, not a wall.
region = NS(cells=[(0, 0)] * 100)
base_settlers = E.claim_settlers(region)
over_settlers = E.claim_settlers(region, overstretch=3)
assert over_settlers > base_settlers, (base_settlers, over_settlers)
assert E.claim_turns(region, overstretch=3) > E.claim_turns(region)
assert E.claim_cost(region, overstretch=3)["Food"] > E.claim_cost(region)["Food"]
print(f"  ok    capacity 4 (1 city) / 8 (city+2 towns+castle); overstretch 2/0")
print(f"  ok    overstretch 3: {base_settlers} -> {over_settlers} settlers, "
      f"{E.claim_turns(region)} -> {E.claim_turns(region, overstretch=3)} turns")

print("\n--- pressure: crowding is the reason to expand ---")
idle = NS(settlements=[_sett("city")], villages=[],
          regions=[NS(faction_idx=0, villages=[], meta_settlements=())],
          factions=[NS(stats={"military": 50}, meta={"species": "Humans"})],
          trade_routes=[])
crowded = NS(settlements=[_sett("city")], villages=[_vill()],
             regions=[NS(faction_idx=0, villages=[0], meta_settlements=())],
             factions=[NS(stats={"military": 50}, meta={"species": "Humans"})],
             trade_routes=[])
assert P.expansion_pressure(idle, 0) is None, "a realm with room has no call to expand"
assert P.expansion_pressure(crowded, 0), "a crowded realm must say so"
print("  ok    pressure is None when there is room, spoken when crowded")

print("\n--- real save: sane, deterministic, bounded ---")
w = pickle.load(open(PATH, "rb"))
for i in range(len(w.factions)):
    idx, age = P.faction_age(w, i)
    assert 0 <= idx < len(P.AGES), (i, idx)
    score = P.development_score(w, i)
    assert score >= 0 and score == score, (i, score)   # finite, non-negative
    comps = P.development_components(w, i)
    for key in ("population", "adults", "settlements", "storage",
                "military", "regions"):
        assert key in comps, (i, key)
    # pure function: two calls agree
    assert P.faction_age(w, i) == (idx, age), f"age not deterministic for {i}"
    assert P.development_score(w, i) == score, f"score not deterministic for {i}"
    print(f"  ok    {w.factions[i].name:<18} {age['name']:<15} score {score:8.1f}")

print("\n--- age_label is the UI line ---")
label = P.age_label(w, w.player_faction_idx if w.player_faction_idx is not None else 0)
assert label and "—" in label, label
print(f"  ok    {label!r}")

print("\nPROGRESSION TEST PASSED")
