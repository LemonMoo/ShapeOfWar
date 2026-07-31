# v0.9.0 — Weather You Can See

Weather has been in the game for a while: ruining harvests, slowing caravans,
shortening an archer's reach. You just could not see it. Now you can. The map
also stops drowning half a continent in inland seas.

## Weather on the map

A region under weather is outlined in its own colour with a badge at its
centre: **a gold sun for drought, a blue thundercloud for storm, pale ice for
a blizzard, grey haze for fog**. Severe weather draws solid and thick, mild
weather dashed and thin — you can tell a bad storm from a light one at the
zoom where you decide whether to march.

Two decisions worth stating:

- **Drought is shown**, even though it does nothing to travel or battle. It is
  the one that ruins your harvest, and leaving it off would be reading the
  mechanics rather than the game.
- **Weather is fogged like anything else**, gated on the region's centre
  exactly the way its name is. Weather over unexplored rival territory would
  quietly turn the overlay into a scouting tool.

It costs nothing per frame: the overlay is built from the region outlines and
labels both renderers already draw, so there is no new per-cell work and the
two map renderers cannot disagree with each other.

## Fewer inland seas

Reported from a screenshot — not that lakes existed, but that there were so
many enormous ones that the land stopped reading as whole. Measured across
three worlds, lakes covered **8.9–14.6% of all land**, with three to six
separate basins each larger than 1% of it.

The obvious knob could not fix it. Lake depth is a single global threshold:
raise it enough to drown an inland sea and every pond goes with it, and the
small lakes are pure character. The problem was never depth, it was the size
of individual **basins**.

So each basin is now capped at half a percent of the land — except the
largest, which keeps whatever size the terrain gave it. **One great lake is a
landmark; six of them is a flooded continent.** An oversized basin recedes to
its deepest cells, which is what a drying lake actually does, and the drained
ground simply becomes low plain. Rivers still route across it exactly as
before.

After: **5.6%, 9.2% and 6.9%** of land across the same three worlds, one large
basin each. Basin count fell only about 10% — a pond is deep for its size, so
the small ones survived.
