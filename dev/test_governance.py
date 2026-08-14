"""The governance foundation (app/world/governance.py): government forms,
species affinity, and the observation-only loyalty score.

    python dev/test_governance.py [world.pkl]

Slice 1 is observation-only -- it writes nothing and draws no randomness. The
properties this guards: every species has a valid default form, affinity is
complete and on the -2..+2 scale, loyalty is a deterministic pure function of
species+form (base + affinity*weight, clamped), old saves with no
`meta["government"]` fall back to the species default, and no function mutates
the world. Synthetic-world tests assert each precisely; a real save is
sanity-checked.
"""
import sys
import os
import pickle
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import governance as G
from app.world.lexicon import (GOVERNMENT_FORMS, SPECIES_GOVERNMENT_AFFINITY,
                               DEFAULT_GOVERNMENT, SPECIES)

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "worlds", "dev560.pkl")


_MISSING = object()


def _world(species="Humans", government=_MISSING):
    # A faction whose meta may or may not carry a government field. The
    # sentinel default means "no field at all" (an old save).
    meta = {"species": species}
    if government is not _MISSING:
        meta["government"] = government
    return NS(factions=[NS(meta=meta, stats={"military": 50, "morale": 50})])


def _snapshot(world):
    return [dict(getattr(n, "meta", {}) or {}) for n in world.factions]


print("--- every species has a valid default form ---")
assert set(DEFAULT_GOVERNMENT) == set(SPECIES), \
    "DEFAULT_GOVERNMENT must name exactly the species in SPECIES"
for species, form in DEFAULT_GOVERNMENT.items():
    assert form in GOVERNMENT_FORMS, f"{species} default {form!r} unknown"
    assert species in SPECIES_GOVERNMENT_AFFINITY, f"{species} has no affinity table"
print("  OK: %d species, all defaults valid" % len(DEFAULT_GOVERNMENT))

print("--- affinity is complete and on -2..+2 ---")
for species, aff in SPECIES_GOVERNMENT_AFFINITY.items():
    for form in GOVERNMENT_FORMS:
        v = aff.get(form, 0)
        assert -2 <= v <= 2, f"{species}/{form} affinity {v} out of -2..+2"
    # each species' default is (one of) its highest-affinity form(s)
    best_v = max(aff.get(f, 0) for f in GOVERNMENT_FORMS)
    assert aff.get(DEFAULT_GOVERNMENT[species], 0) == best_v, \
        f"{species} default is not a preferred form"
print("  OK: affinity tables complete and bounded, defaults preferred")

print("--- loyalty = base + affinity*weight, clamped ---")
for species in SPECIES:
    for form in GOVERNMENT_FORMS:
        w = _world(species, form)
        expected = G.LOYALTY_BASE + SPECIES_GOVERNMENT_AFFINITY[species].get(form, 0) * G.LOYALTY_AFFINITY_WEIGHT
        expected = max(G.LOYALTY_FLOOR, min(G.LOYALTY_CEIL, expected))
        got = G.government_loyalty(w, 0)
        assert got == expected, f"{species}/{form}: {got} != {expected}"
        assert G.LOYALTY_FLOOR <= got <= G.LOYALTY_CEIL
print("  OK: loyalty formula matches for all %d species x %d forms"
      % (len(SPECIES), len(GOVERNMENT_FORMS)))

print("--- old saves (no meta['government']) fall back to species default ---")
for species in SPECIES:
    w = _world(species)  # no government field
    assert G.government_form(w, 0) == DEFAULT_GOVERNMENT[species], species
    assert G.government_form(w, 0) in GOVERNMENT_FORMS
# an invalid stored value also falls back rather than crashing
w = _world("Orcs", "not_a_real_form")
assert G.government_form(w, 0) == DEFAULT_GOVERNMENT["Orcs"]
print("  OK: fallback correct for every species + invalid value")

print("--- pure functions: no world mutation, deterministic ---")
w = _world("Elves", "monarchy")  # a reform against the grain
before = _snapshot(w)
a = (G.government_form(w, 0), G.government_loyalty(w, 0))
b = (G.government_form(w, 0), G.government_loyalty(w, 0))
assert a == b, "not deterministic"
assert _snapshot(w) == before, "world mutated by a read-only accessor"
print("  OK: no mutation, deterministic (loyalty for Elves/monarchy = %d)" % a[1])

print("--- real save sanity check ---")
if os.path.exists(PATH):
    with open(PATH, "rb") as fh:
        world = pickle.load(fh)
    n = 0
    for i, faction in enumerate(getattr(world, "factions", ())):
        if not (faction.meta or {}).get("species"):
            continue
        form = G.government_form(world, i)
        loyalty = G.government_loyalty(world, i)
        assert form in GOVERNMENT_FORMS, f"faction {i}: {form!r}"
        assert G.LOYALTY_FLOOR <= loyalty <= G.LOYALTY_CEIL, f"faction {i}: {loyalty}"
        n += 1
    print(f"  OK: {n} factions all map to a valid form and in-range loyalty")
else:
    print("  SKIP: %s not found" % PATH)


# --- slices 2-5: a richer synthetic world -----------------------------------
def _w2(species="Humans", government=_MISSING, loyalty=None, military=50,
        n_regions=1, setts=(), trade=False, capital=0):
    world_setts = [NS(faction_idx=0, kind=k, character=c) for k, c in setts]
    meta = {"species": species,
            "regions": list(range(n_regions)),
            "settlements": list(range(len(world_setts)))}
    if government is not _MISSING:
        meta["government"] = government
    if capital is not None:
        meta["capital"] = capital
    stats = {"military": military, "morale": 50}
    if loyalty is not None:
        stats["loyalty"] = loyalty
    return NS(
        factions=[NS(meta=meta, stats=stats)],
        settlements=world_setts,
        villages=[],
        regions=[NS(faction_idx=0, id=i, cells=[(i, 0)],
                    meta_settlements=[], villages=[]) for i in range(n_regions)],
        trade_routes=[{"a_faction": 0, "b_faction": 1}] if trade else [],
        seed=0, turn=0)


print("--- slice 3/4: effect multiplier and governance bonus ---")
assert abs(G.loyalty_effect_mult(_w2(loyalty=50), 0) - 1.0) < 1e-9
assert abs(G.loyalty_effect_mult(_w2(loyalty=99), 0) - 1.4) < 1e-9
assert abs(G.loyalty_effect_mult(_w2(loyalty=15), 0) - 0.6) < 1e-9
assert G.loyalty_gov_bonus(_w2(loyalty=50), 0) == 0
assert G.loyalty_gov_bonus(_w2(loyalty=70), 0) == 1
assert G.loyalty_gov_bonus(_w2(loyalty=30), 0) == -1
print("  OK: mult 0.6/1.0/1.4, gov bonus 0/+1/-1")

print("--- slice 2: behavior delta has the right sign ---")
# A militaristic, isolated Warband is content (positive delta).
warmonger = G.behavior_delta(_w2(species="Orcs", government="warband",
                                 military=99, trade=False), 0)
assert warmonger > 0, warmonger
# A militaristic, sprawling Elder Council offends its people (negative).
council = G.behavior_delta(_w2(species="Elves", government="elder_council",
                               military=99, n_regions=6, trade=False), 0)
assert council < 0, council
print(f"  OK: warband +{warmonger:+.2f}, overreaching elder council {council:+.2f}")

print("--- slice 2: loyalty drifts toward its target and is stored ---")
w = _w2(species="Orcs", government="warband", loyalty=50, military=99, trade=False)
target = G.loyalty_target(w, 0)
assert target > 50
G.apply_loyalty_drift(w)
after = w.factions[0].stats["loyalty"]
expected = max(G.LOYALTY_FLOOR, min(G.LOYALTY_CEIL,
                                    50 + (target - 50) * G.LOYALTY_EASE))
assert after == expected, (after, expected)
assert "loyalty" in w.factions[0].stats
for _ in range(200):
    G.apply_loyalty_drift(w)
converged = w.factions[0].stats["loyalty"]
assert converged > 50 and abs(converged - target) < 3, (converged, target)
print(f"  OK: 50 -> {after} -> {converged} (target {target:.1f})")

print("--- slice 2: reform switches form at a loyalty cost ---")
w = _w2(species="Orcs", government="warband")   # base loyalty 70
msg = G.reform_government(w, 0, "gang")          # affinity 2 -> 1
assert w.factions[0].meta["government"] == "gang", msg
assert w.factions[0].stats["loyalty"] == 62, w.factions[0].stats["loyalty"]  # 70 - 8
assert "Reformed" in msg
assert "already follows" in G.reform_government(w, 0, "gang")
assert "No such form" in G.reform_government(w, 0, "bogus")
assert G.reform_cost(_w2(species="Orcs", government="warband"), 0, "elder_council") == 32
print("  OK: reform landed, same-form and unknown-form guarded, cost scales")

print("--- slice 5: revolt is inert at/above the floor, skips the capital ---")
assert G.apply_revolts(_w2(loyalty=30, n_regions=1)) == []      # above floor
assert G.apply_revolts(_w2(loyalty=10, n_regions=1, capital=0)) == []  # only the capital
print("  OK: no secession above the floor or with only a capital")

print("--- slice 5: secession on a real world ---")
if os.path.exists(PATH):
    from app.world.worldgen import UNCLAIMED
    with open(PATH, "rb") as fh:
        w2 = pickle.load(fh)
    region = fac_idx = None
    for i, nation in enumerate(w2.factions):
        capital = nation.meta.get("capital")
        owned = [rid for rid in nation.meta.get("regions", []) if rid != capital]
        if owned:
            fac_idx, region = i, w2.regions[owned[-1]]
            break
    assert region is not None, "no faction with a non-capital region to test"
    before = set(w2.factions[fac_idx].meta.get("regions", []))
    G.secede_region(w2, region, fac_idx)
    assert region.faction_idx == UNCLAIMED
    assert region.id not in w2.factions[fac_idx].meta.get("regions", [])
    assert region.id in before
    # The seceded world must survive the very next day (the region is now
    # ordinary unclaimed land, and its nodes are neutralized like any demoted
    # settlement).
    from app.world import resources
    resources.advance_turn(w2)
    assert region.faction_idx == UNCLAIMED
    print(f"  OK: {region.name} seceded to UNCLAIMED, left the roster, and the next day ran")
else:
    print("  SKIP: %s not found" % PATH)

print("ALL GOVERNANCE TESTS PASSED")
