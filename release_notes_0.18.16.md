# v0.18.16 — No Windows on the Ceiling (2)

More overworld leaks below ground, all closed:

- **Weather** — storm/bizzard outlines and badges were still drawing on the
  under view, outlining surface regions from inside a cave. Surface-only now.
- **The attack frontier** — while picking an attack target, the red outlines
  and target names rendered below ground too. Surface-only now.
- **Roads under construction** — the dirt dash of an in-progress road showed
  below. Surface-only now.
- **Alert badges** — the red/amber `!` on a settlement in trouble is drawn at
  the settlement's position, and a *surface* settlement's badge was showing
  while you were underground. Badges now follow the settlement itself
  (layer-honest).
- **The region panel** — an under region's "Biome" line was reporting the
  *surface* biome overhead (its cells read the ground above). It now reads
  "Cavern galleries"; the depth line tells you what the rock actually is.
- **The surface fog overlay** — the canvas never composites the overworld's
  exploration pattern over the under raster anymore; the cave map's darkness
  is its own.

What remains layer-honest by design: gates (a door you can't find doesn't
exist), the cave world itself, under settlements and villages, and marches.
