# Shapes of War v0.3.6_1

A world-gen tuning pass and a real movement-animation bug fix.

---

## Many more continents

World generation was effectively stuck at 2-3 continents no matter the
seed. Simply raising the target count made things *worse*, not better —
the placement math (how far apart continents land, how strong the
coastline-warping noise is relative to their size) was quietly tuned for
exactly that narrow range, and a naive increase just meant more of them
merging into one blob.

Fixed properly rather than patched around:

- Each hemisphere now spreads its own continents from equator to pole
  independently, instead of both hemispheres sharing one sequential walk
  that left most continents clustered near the equator regardless of which
  side they landed on.
- Continent size and coastline-warp intensity both scale down with count,
  so a world with 7 continents doesn't get bridged together by the same
  amount of "chaos" that used to be tuned for 3.
- Placement itself picks the best of many candidate spots by actual
  separation from what's already down, instead of accepting the first spot
  that clears a fixed bar or giving up and placing blind.

Net result: continent count now regularly lands at 6-7, spread across real,
separate landmasses at meaningfully different latitudes — which also means
more climate and biome variety across a single world, since latitude is
what drives that.

## Less water in the land

Rivers and lakes were carrying a bit more water than made sense within the
land itself. Both are cut moderately — rivers now need more upstream
drainage area before they count, lakes need a deeper basin — without
changing how the drainage network actually forms.

## Fixed: movement animations flashing and snapping back

Commander and caravan movement at the start of a turn used to flash
forward to its destination, snap back to where it started, and only then
actually animate the slide — a real timing bug, not a style choice. The
turn's final positions could get painted to the screen one frame before
the animation's own starting frame did. Movement now reads as one clean,
continuous slide from start to finish.
