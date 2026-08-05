# v0.18.0 — The Settlement-First World

A restructuring of how the world grows: bigger regions, less lag, and a
settlement-first progression loop — build your town, upgrade it, fill your
land, then expand.

## World

- **Regions are ~3x larger** — a full-size world now has ~550 regions instead
  of ~1,400. The per-region daily overhead (production, logistics, trade
  chunks) drops with them; measured ~3x faster per turn on the dev world.
  Applies to new games.
- A region is now **one holding to build up**, not a tile to spam settlements
  across.

## Growth

- **Settlements have levels.** A Town supports a few villages, a City many
  more — a region's village capacity is the sum of its settlements'
  allowances plus one frontier homestead.
- **Raise a Town to a City** — a long, expensive upgrade project. A City
  unlocks more village slots, higher tax, a bigger population ceiling, and
  the city-gated buildings. It's the same kind-change the settlement's whole
  economy hangs off, so everything upgrades at once.
- The region panel shows **"n/m villages"**; a full region stops growing
  villages and tells you to upgrade or expand.

## Resources

- **Nothing is guaranteed any more.** The old free Logs/Stone trickle per
  region is gone, and a village's industry output (timber, ore, stone) is
  gated behind its extractive camps — Woodcutters' Camp, Mining Camp,
  Workings. A village without them extracts nothing. The AI builds them too.
- Every founding village starts with the tier-1 camps and Grange its land
  supports; old saves are migrated automatically so nothing deadlocks.

## Expansion

- A realm may only claim new land once **its own regions average half their
  village capacity** — expansion is the reward for filling your land.
- Newly claimed land is empty until you build on it (one frontier homestead
  per claim).

## Balance

- Villages recover from disaster: **children grow into adults**, so a hard
  Winter that takes every adult is a setback, not a permanent death sentence.
- Food/fishing labor is never fully shut off by a full pantry, and firewood
  can't be squeezed out of storage by food.

## Dev

- `dev/make_dev_world.py` regenerates the dev worlds with the current
  worldgen; render baselines re-recorded; full test battery green.
