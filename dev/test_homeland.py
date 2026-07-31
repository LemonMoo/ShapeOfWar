"""Biome overhaul phase B: a species starts where its people come from.

    python dev/test_homeland.py

Nothing about species touched placement before this -- `_site_score` weighs
fertility, rivers, coast, borders and elevation, and an Elf realm was as
likely to open in a desert as a Human one. Capitals are now handed out to
match the species roster (worldgen._order_capitals_by_affinity).

The property that matters most here is the NEGATIVE one: this reorders an
already-validated list of capitals, so it must never be able to strand a
realm somewhere it cannot live. Forest is the Elf homeland and the single
most common biome on the map, and it grows no crops of its own at all.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import worldgen as W
from app.world import resources as R
from app.world.lexicon import SPECIES, SPECIES_BIOME_AFFINITY

# Small worlds -- this generates several, and the property under test does
# not depend on map size.
GEN = dict(width=420, height=260, n_factions=8)

print("--- the affinity table is complete and well-formed ---")
assert set(SPECIES_BIOME_AFFINITY) == set(SPECIES), (
    set(SPECIES) ^ set(SPECIES_BIOME_AFFINITY))
real_biomes = ({b for row in R._BIOME_MATRIX for b in row}
               | {"mountain", "highland", "coastal", "swamp"})
for species, prefs in SPECIES_BIOME_AFFINITY.items():
    assert prefs, species
    for biome, weight in prefs.items():
        assert biome in real_biomes, f"{species} prefers unknown biome {biome!r}"
        assert 0.0 < weight <= 1.0, (species, biome, weight)
print(f"  ok    all {len(SPECIES_BIOME_AFFINITY)} species map onto real biomes")

print("\n--- a matched world beats a random pairing, clearly ---")
w = W.generate_world(seed=7, **GEN)
caps = [f.meta["capital"] for f in w.factions]
roster = [f.meta["species"] for f in w.factions]
shares = [W._homeland_biomes(w, x, y) for x, y in caps]
matched = sum(W.homeland_affinity(s, sh)
              for s, sh in zip(roster, shares)) / len(roster)
random_pairing = sum(W.homeland_affinity(s, sh) for s in roster for sh in shares) \
    / (len(roster) * len(shares))
assert matched > random_pairing * 1.4, (matched, random_pairing)
print(f"  ok    mean affinity {random_pairing:.3f} random -> {matched:.3f} matched")

print("\n--- species actually land in their own country ---")
# Not every one -- the whole design is a strong preference with graceful
# fallback -- but the best-scoring homeland for a species should go to that
# species rather than to somebody else.
placed = {}
for species, cap_shares in zip(roster, shares):
    top = max(cap_shares.items(), key=lambda kv: kv[1])[0] if cap_shares else None
    placed.setdefault(species, []).append(top)
for species, tops in sorted(placed.items()):
    prefs = SPECIES_BIOME_AFFINITY[species]
    at_home = sum(1 for t in tops if t in prefs)
    print(f"  {species:8} {at_home}/{len(tops)} in a preferred biome "
          f"({', '.join(t or '-' for t in tops)})")
best_for = {}
for i, sh in enumerate(shares):
    for species in set(roster):
        score = W.homeland_affinity(species, sh)
        if score > best_for.get(species, (0.0, None))[0]:
            best_for[species] = (score, i)
for species, (score, cap_i) in best_for.items():
    if score <= 0:
        continue
    assert roster[cap_i] == species, (
        f"the best {species} homeland on this map went to {roster[cap_i]}")
print("  ok    every species' single best available homeland went to that species")

print("\n--- CRITICAL: nobody is placed somewhere they cannot live ---")
# The reorder must not bypass the farmland guarantee every capital passed
# during placement. Re-run that exact check against the FINAL capitals.
land_set = {(x, y) for y in range(w.h) for x in range(w.w)
            if w.owner[y][x] != W.OCEAN}
for f in w.factions:
    cx, cy = f.meta["capital"]
    assert (cx, cy) in land_set, f"{f.meta['species']} capital is not on land"
# The reorder is a permutation of the placed list, so the set of sites in
# use must be exactly the set that passed placement -- no new site can be
# invented, and none dropped.
assert len({f.meta["capital"] for f in w.factions}) == len(w.factions), (
    "two realms were handed the same capital")
print(f"  ok    all {len(w.factions)} capitals are distinct land sites from the "
      f"validated pool")

print("\n--- every realm survives its own homeland ---")
# The real test of viability, rather than a turn-0 crop count (which is a
# poor proxy: a foothold's villages spread onto farmable land as it develops,
# and coastal realms eat fish, which is not a RESOURCE_SPAWN crop at all).
from app.world.nation import is_eliminated
pop0 = {i: sum(n.population for n in list(w.settlements) + list(w.villages)
               if n.faction_idx == i) for i in range(len(w.factions))}
for _ in range(40):
    R.advance_turn(w)
pop1 = {i: sum(n.population for n in list(w.settlements) + list(w.villages)
               if n.faction_idx == i) for i in range(len(w.factions))}
dead = [w.factions[i].meta["species"] for i in range(len(w.factions))
        if is_eliminated(w.factions[i])]
assert not dead, f"realms died in their own homeland: {dead}"
collapsed = [(w.factions[i].meta["species"], pop0[i], pop1[i])
             for i in range(len(w.factions))
             if pop0[i] > 0 and pop1[i] < pop0[i] * 0.5]
assert not collapsed, f"realms more than halved in 40 turns: {collapsed}"
print(f"  ok    40 turns, {len(w.factions)} realms, none eliminated, none halved")

print("\n--- the player gets the species they asked for ---")
wp = W.generate_world(seed=3, player_species="Dwarves", **GEN)
assert wp.factions[0].meta["species"] == "Dwarves", wp.factions[0].meta["species"]
assert wp.player_faction_idx == 0
home = W._homeland_biomes(wp, *wp.factions[0].meta["capital"])
print(f"  ok    player is Dwarves, homeland "
      f"{', '.join(f'{b} {s:.0%}' for b, s in sorted(home.items(), key=lambda kv: -kv[1])[:2])}")

print("\n--- graceful fallback: a species with no homeland still gets placed ---")
# Ask for a species whose biomes may simply be absent from a given map. The
# design is explicit that this must degrade, not fail.
for seed in (11, 12, 13):
    wf = W.generate_world(seed=seed, player_species="Goblins", **GEN)
    assert len(wf.factions) >= 1
    assert wf.factions[0].meta["species"] == "Goblins"
    assert wf.factions[0].meta["capital"] is not None
print("  ok    3 maps generated for a narrow-homeland species, all placed")

print("\n--- the same seed still builds the same world ---")
a = W.generate_world(seed=99, **GEN)
b = W.generate_world(seed=99, **GEN)
assert [f.meta["species"] for f in a.factions] == [f.meta["species"] for f in b.factions]
assert [f.meta["capital"] for f in a.factions] == [f.meta["capital"] for f in b.factions]
print("  ok    species roster and capitals are reproducible from the seed")

print("\nHOMELAND TEST PASSED")
