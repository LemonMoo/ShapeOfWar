"""Biome overhaul phase C: a people works its own country better.

    python dev/test_aptitude.py [world.pkl]

A Dwarf village in the highlands gets more out of the same ground than an
Orc one would, and less out of a jungle -- with the penalty eroding as the
realm actually lives there.

Two properties matter most here and both are about fairness rather than
flavour:

  * The acclimatisation half is not optional. Without it a realm that
    conquers alien terrain is permanently worse at it than the neighbour it
    took it from, which compounds every turn and turns expansion into unlike
    country into a trap rather than a choice.
  * Conquest must NOT hand you the previous owner's local knowledge. Taking
    a people's fields should not come with their generations of learning it.
"""
import sys
import os
import pickle

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import resources as R
from app.world.lexicon import SPECIES_BIOME_AFFINITY

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "worlds", "dev560.pkl")
w = pickle.load(open(PATH, "rb"))

print("--- aptitude stays inside its stated band ---")
lo = 1.0 - R.TERRAIN_APTITUDE_PENALTY
hi = 1.0 + R.TERRAIN_APTITUDE_BONUS
owned = [v for v in w.villages if v.faction_idx is not None and v.faction_idx >= 0]
assert owned, "this world has no owned villages"
vals = [R.terrain_aptitude(w, v) for v in owned]
assert all(lo - 1e-9 <= a <= hi + 1e-9 for a in vals), (min(vals), max(vals))
print(f"  ok    {len(vals)} villages, aptitude {min(vals):.3f}..{max(vals):.3f} "
      f"inside [{lo:.2f}, {hi:.2f}]")

print("\n--- it reuses phase B's homelands, not a second table ---")
# The land you come from IS the land you are good at. A separate table would
# be free to drift away from where the species actually spawns.
import inspect
src = inspect.getsource(R.terrain_aptitude)
assert "homeland_affinity" in src, (
    "aptitude must score off the same affinity phase B places homelands with")
print("  ok    terrain_aptitude scores off homeland_affinity")

print("\n--- native ground beats alien ground, for the same species ---")
best = max(owned, key=lambda v: R.terrain_aptitude(w, v))
worst = min(owned, key=lambda v: R.terrain_aptitude(w, v))
assert R.terrain_aptitude(w, best) > R.terrain_aptitude(w, worst)
print(f"  ok    best {R.terrain_aptitude(w, best):.3f} ({best.name}) vs "
      f"worst {R.terrain_aptitude(w, worst):.3f} ({worst.name})")

print("\n--- acclimatisation erodes the penalty, and only the penalty ---")
alien = next((v for v in owned if R.terrain_aptitude(w, v) < 0.99), None)
native = next((v for v in owned if R.terrain_aptitude(w, v) > 1.01), None)
assert alien is not None, "no village on alien ground to test with"
species = w.factions[alien.faction_idx].meta["species"]
before_state = (getattr(alien, "acclimatisation", 0.0),
                getattr(alien, "acclim_species", None))
try:
    alien.acclim_species = species
    alien.acclimatisation = 0.0
    raw = R.terrain_aptitude(w, alien)
    alien.acclimatisation = 1.0
    learned = R.terrain_aptitude(w, alien)
    assert learned > raw, (raw, learned)
    assert abs(learned - 1.0) < 1e-9, (
        f"a fully acclimatised alien village should reach 1.0, not {learned} "
        f"-- living somewhere long enough stops it fighting you, it does not "
        f"make you native to it")
    print(f"  ok    alien ground {raw:.3f} -> {learned:.3f} once learned, "
          f"capped at 1.0 (never the native bonus)")
finally:
    alien.acclimatisation, alien.acclim_species = before_state

# WHOLLY native ground -- nothing alien left in the catchment to learn, so
# acclimatisation has nothing to do. Note a merely GOOD village (say 1.09)
# legitimately still improves: a mixed catchment has an alien share in it,
# and learning that share is exactly the mechanic working.
pure = next((v for v in owned if R.terrain_aptitude(w, v) >= hi - 1e-9), None)
if pure is not None:
    keep = (getattr(pure, "acclimatisation", 0.0),
            getattr(pure, "acclim_species", None))
    try:
        pure.acclim_species = w.factions[pure.faction_idx].meta["species"]
        pure.acclimatisation = 0.0
        a0 = R.terrain_aptitude(w, pure)
        pure.acclimatisation = 1.0
        a1 = R.terrain_aptitude(w, pure)
        assert abs(a1 - a0) < 1e-9, (a0, a1)
        print(f"  ok    wholly native ground is {a0:.3f} either way -- "
              f"nothing left to learn")
    finally:
        pure.acclimatisation, pure.acclim_species = keep
else:
    print("  skip  no wholly-native village on this world")

print("\n--- and it never lifts anyone above the native ceiling ---")
worst_case = 0.0
for v in owned[:200]:
    keep = (getattr(v, "acclimatisation", 0.0), getattr(v, "acclim_species", None))
    try:
        v.acclim_species = w.factions[v.faction_idx].meta["species"]
        v.acclimatisation = 0.0
        a0 = R.terrain_aptitude(w, v)
        v.acclimatisation = 1.0
        a1 = R.terrain_aptitude(w, v)
        assert a1 >= a0 - 1e-9, "acclimatisation made a village WORSE at its ground"
        assert a1 <= hi + 1e-9, (v.name, a1)
        worst_case = max(worst_case, a1)
    finally:
        v.acclimatisation, v.acclim_species = keep
print(f"  ok    200 villages: learning never hurts, and never passes "
      f"{hi:.2f} (highest seen {worst_case:.3f})")

print("\n--- CRITICAL: conquest does not inherit local knowledge ---")
v = owned[0]
keep = (v.faction_idx, getattr(v, "acclimatisation", 0.0),
        getattr(v, "acclim_species", None))
try:
    sp = w.factions[v.faction_idx].meta["species"]
    v.acclim_species = sp
    v.acclimatisation = 1.0
    other = next((i for i, f in enumerate(w.factions)
                  if f.meta.get("species") and f.meta["species"] != sp), None)
    assert other is not None, "this world is single-species"
    v.faction_idx = other
    R.advance_acclimatisation(w)
    assert v.acclimatisation == 0.0, (
        f"a conquering species inherited {v.acclimatisation} of the previous "
        f"owner's local knowledge")
    print(f"  ok    taken by {w.factions[other].meta['species']}: reset to 0.00")

    # ...but an unbroken tenure keeps climbing.
    v.acclimatisation = 0.5
    R.advance_acclimatisation(w)
    assert v.acclimatisation > 0.5, v.acclimatisation
    print(f"  ok    same species, next turn: 0.50 -> {v.acclimatisation:.4f}")
finally:
    v.faction_idx, v.acclimatisation, v.acclim_species = keep

print("\n--- it rides the labour system, not bolted on after it ---")
# Applied to what the LAND offers, so a better-worked catchment still has to
# be worked -- it competes for hands like the Mining Camp's extra cells do.
src = inspect.getsource(R._village_terrain_potential)
assert "terrain_aptitude" in src, "aptitude is not applied to terrain potential"
assert src.index("terrain_aptitude") < src.index("by_sector = defaultdict"), (
    "aptitude must scale the land's offer BEFORE it is bucketed into sectors "
    "and capped by labour")
print("  ok    applied to terrain potential, before the labour cap")

print("\n--- fishing is left alone ---")
# The catch comes off the water, not out of the ground.
fish_at = src.index('by_sector["fishing"]')
apt_at = src.index("terrain_aptitude")
assert apt_at < fish_at, "aptitude must be applied before fishing is added in"
print("  ok    the catch is added after the multiplier, so it is unscaled")

print("\n--- an old save needs no migration ---")
# acclimatisation/acclim_species are read through getattr, so a world written
# before phase C answers 0.0 and simply starts learning.
old = pickle.loads(pickle.dumps(owned[0]))
for attr in ("acclimatisation", "acclim_species"):
    if hasattr(old, attr):
        delattr(old, attr)
assert R.acclimatisation(old) == 0.0
print("  ok    a village with no counter at all reads 0.0 rather than raising")

print("\n--- a real turn still runs, and nothing goes negative ---")
for _ in range(3):
    R.advance_turn(w)
for n in list(w.settlements) + list(w.villages):
    for res, amt in (n.resources or {}).items():
        assert amt >= 0, (n.name, res, amt)
moved = sum(1 for v in w.villages if getattr(v, "acclimatisation", 0.0) > 0)
print(f"  ok    3 turns, no negative stock; {moved} villages have begun to settle in")

print("\nAPTITUDE TEST PASSED")
