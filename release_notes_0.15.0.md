# v0.15.0 — A World Worth the Name

A tuning pass on world generation. The plate model that builds every map shipped
as a deliberate first pass and was never tuned to convergence; this is that
pass. Fantastical, but still recognisably a world.

## What changed

- **Real continents.** A world now forms four or five substantial landmasses
  instead of ten-plus fragments. Most land comes from continental bodies now,
  not from stray bumps along ocean boundaries.
- **Fewer islands.** The noise-specks that made a map read as scattered are
  sunk before the world is finished — everything below a minimum size goes back
  under the sea. Real islands (an arc off a coast, a large offshore body) stay;
  the confetti does not.
- **Better lakes.** Smaller and more numerous, scattered through continental
  interiors, with one great lake per world. The old failure where a single
  basin flooded a sixth of the land into an inland sea is capped out — the great
  lake is a landmark, not a second ocean.
- **Faster.** Fewer retries to place separate continents, and less land for the
  later steps to chew through, cut generation time by roughly a third.

## For the curious

Tuned against measured seed sweeps, not by eye: continent count, island count,
the islet fraction, land percentage and lake sizes, with a rendered map per
seed at every step. Every number moved in the direction it was aimed, and the
worst-case seed still reads as a world rather than a puddle-field.

Existing saves are untouched — this only changes worlds made from here on.
