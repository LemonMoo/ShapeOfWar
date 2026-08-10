# v0.18.24 — Only the Mountain and Its Door

Two bugs from a fresh dwarf world, both fixed at the root.

- **No second territory.** A cave realm owns exactly its mountain and its
  door. New dwarf/goblin worlds were handing the player TWO surface
  territories: the gate town's door region (the right one) plus a leftover
  starting foothold with three villages in it. Cave peoples now get no
  surface starting foothold at all — their realm is the under network,
  claimed when the hold lands, and the gate town's door region on the
  surface. The stray foothold territory and its villages are gone.
- **No underground map through the surface fog.** The surface fog of war
  was revealing the player's entire underground network — every hold,
  tunnel and warren — as if it had been walked: the surface-fog recompute
  seeded itself from every region in the player's list, including the
  underground regions the hold claims. The underground has its own
  darkness and must be walked to be known; the recompute now uses only
  surface regions, and a cave realm's under territory can no longer push
  the owned-fraction toward a full-map reveal either.
- **Fallbacks still work.** A cave realm whose map has no reachable cave
  network — or no underworld carved at all — still gets a proper plain
  surface start: its own claimed region, its capital city and its starting
  villages, exactly like any surface realm.

Covered by the new `dev/test_dwarf_realm.py` (Dwarves and Goblins:
underground realms, a surface-fallback seed, and a no-underworld map —
the test fails 7 assertions on the previous build and passes on this one).
