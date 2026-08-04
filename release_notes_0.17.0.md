# v0.17.0

A performance pass on the real-time world. The map now holds together at
speed — the hitches are gone, and the units stop lying about where they are.

- **The terrain raster rebuilds ~40x faster.** Every time a province changed
  hands, a view mode or a selection changed, the map paid a ~300ms pure-Python
  repaint of all 726,000 cells — a third-of-a-second freeze on a developed
  world. That pass is now numpy-vectorized: a few milliseconds, same picture
  byte for byte.
- **The GPU map stops re-uploading unchanged geometry every frame.** Roads,
  borders and labels are only re-uploaded when they actually change, and a
  day's movement slide redraws just the units that are moving — not every
  settlement and village on the map, thirty times a second.
- **FIXED: units no longer jump backward.** When a day's simulation finished
  before the display clock caught up, the next slide used to start from the
  day's beginning — an army visibly snapped back mid-march. Movement slides
  are now anchored to the world clock, so a column glides through its route
  without teleporting, whether the sim is early or late.
- **Leaner under the hood.** The map's colour data now lives as packed pixels
  instead of hundreds of millions of tiny Python objects — the same rendering
  with a fraction of the memory.

The turn-based behaviour, save format and balance are untouched: a day is
still a day, and every existing save loads as before.
