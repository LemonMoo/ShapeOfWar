"""The start-site evaluator (app/world/startsites.py, Part B2).

    python dev/test_startsites.py

Pure logic over a real generated world: what a cell offers, and whether it can
feed a realm. The load-bearing behaviour is the sustain verdict -- it must say
YES on the ground the game itself considers a valid capital, and NO in the
open sea and on barren rock -- because that verdict becomes the warning the
player is allowed to override.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world.worldgen import generate_world
from app.world import startsites as S

world = generate_world(560, 340, seed=7, n_factions=6,
                       player_species="Humans", player_name="Test")
print(f"world grown: {len(world.factions)} factions")

print("\n--- it changes nothing ---")
import pickle
before = pickle.dumps((world.height, [list(r) for r in world.biome_grid]))
S.evaluate_site(world, 100, 100, "Humans")
S.candidate_sites(world, 5, "Humans")
after = pickle.dumps((world.height, [list(r) for r in world.biome_grid]))
assert before == after, "evaluating a site mutated the world"
print("  ok    pure -- the world is untouched")

print("\n--- the card is fully populated for a real capital ---")
cap = world.factions[0].meta["capital"]
ev = S.evaluate_site(world, cap[0], cap[1], "Humans")
assert ev["biomes"], "no biomes reported for a real capital"
assert ev["dominant_biome"], "no dominant biome"
assert abs(sum(ev["biomes"].values()) - 1.0) < 1e-6, "biome shares don't sum to 1"
assert 0.0 <= ev["farmland_pct"] <= 1.0
assert ev["affinity"] is not None and ev["affinity"] >= 0.0
assert isinstance(ev["coast"], bool) and isinstance(ev["river"], bool)
print(f"  ok    {ev['dominant_biome']}, farmland {ev['farmland_pct']*100:.0f}%, "
      f"{len(ev['resources'])} goods, coast={ev['coast']} river={ev['river']}, "
      f"room={ev['room']}")

print("\n--- the sustain verdict agrees with the game's own capitals ---")
# Every capital the generator placed passed its farmland bar, so the evaluator
# -- a stricter, real-biome version of the same question -- should call most of
# them sustainable. Not necessarily ALL (the two bars are computed differently),
# but the overwhelming majority.
ok = sum(1 for f in world.factions
         if S.evaluate_site(world, *f.meta["capital"])["sustain"]["ok"])
print(f"  {ok} of {len(world.factions)} placed capitals read as sustainable")
assert ok >= len(world.factions) - 1, (
    "the evaluator disagrees with the game about where a realm can live")
print("  ok    the evaluator and the generator agree on viable ground")

print("\n--- open sea is never sustainable ---")
# A genuine mid-ocean site: an ocean cell whose whole homeland neighbourhood
# is water (biome None == ocean). The seam is a wandering strait now, not a
# deep straight band, so "first ocean cell" is no longer guaranteed to sit in
# open water -- it can land beside the strait's shore and legitimately read
# as sustainable. Pick water that is unambiguously the middle of the ocean.
r = S._HOMELAND_RADIUS
sea = next((x, y) for y in range(r, world.h - r) for x in range(r, world.w - r)
           if all(world.biome_grid[yy][xx] is None
                  for yy in range(y - r, y + r + 1)
                  for xx in range(x - r, x + r + 1)))
ev = S.evaluate_site(world, sea[0], sea[1])
assert not ev["sustain"]["ok"], "the middle of the ocean read as farmable"
assert "water" in ev["sustain"]["reason"].lower()
print(f"  ok    the sea says: {ev['sustain']['reason']!r}")

print("\n--- barren high rock warns, and does not claim farmland ---")
# The deepest mountain cell we can find -- the classic "spawned in a peak" trap.
peak = max(((x, y) for y in range(world.h) for x in range(world.w)
            if world.biome_grid[y][x] == "mountain"),
           key=lambda c: world.height[c[1]][c[0]], default=None)
if peak:
    ev = S.evaluate_site(world, peak[0], peak[1])
    print(f"  a mountain site: farmland {ev['farmland_pct']*100:.0f}%, "
          f"sustain={ev['sustain']['ok']}")
    # It may or may not have a farmable valley in reach; the invariant is only
    # that if it has none, it is flagged, not silently blessed.
    if ev["workable_pct"] < S._SUSTAIN_WORKABLE_FLOOR:
        assert not ev["sustain"]["ok"]
        print(f"  ok    flagged: {ev['sustain']['reason']!r}")
    else:
        print("  --    this peak happens to overlook farmland; not a trap here")
else:
    print("  --    no mountains on this seed")

print("\n--- candidate sites are viable, spaced, and off the rivals ---")
cands = S.candidate_sites(world, 6, "Humans")
assert cands, "no candidate sites offered"
rivals = [f.meta["capital"] for f in world.factions]
for x, y, ev in cands:
    assert ev["sustain"]["ok"], "an unsustainable site was offered as a candidate"
    assert world.owner[y][x] < 0, "a candidate landed on owned (rival) territory"
    near = min(((x - rx) ** 2 + (y - ry) ** 2) ** 0.5 for rx, ry in rivals)
    assert near > 5, f"a candidate is on top of a rival capital ({near:.0f} cells)"
# spaced from each other
for i, (x, y, _) in enumerate(cands):
    for x2, y2, _ in cands[i + 1:]:
        assert (x - x2) ** 2 + (y - y2) ** 2 > 25, "two candidates coincide"
print(f"  ok    {len(cands)} candidates, all sustainable, spaced, clear of rivals")

print("\n--- best-first for the chosen species ---")
affs = [ev["affinity"] for _, _, ev in cands]
assert affs == sorted(affs, reverse=True), "candidates not ordered by homeland fit"
print(f"  ok    ordered by affinity: {[round(a, 2) for a in affs]}")

print("\nSTARTSITES TEST PASSED")
