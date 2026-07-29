# Shapes of War v0.3.4

Two threads finished this release: real shape variety in world generation,
and a full rework of where settlements and villages come from — and what
that actually means for the economy underneath them.

---

## Continents stop looking like the same shape

Every continent used to come from one fixed, axis-aligned ellipse — same
size, same orientation, every seed, every world. The domain-warp noise from
the last release gave coastlines real texture (fjords, peninsulas), but the
underlying skeleton never changed. Continents now get their own randomized
size and rotation, plus 0–3 clustered "lobe" blobs merged in — real forked
arms, diagonal landmasses, and lopsided coasts instead of the same
silhouette moved to a new latitude every time.

**Fixed:** kingdom names overlapping into an unreadable clump at world-view
zoom on a crowded map. Names are decluttered and offset clear of their own
capital marker now, and your own kingdom is always guaranteed a spot even
when rivals are packed in close.

---

## Settlements finally read the map — everywhere, not just at world-gen

World-gen always scored land intelligently for Cities, Castles and Towns.
Nothing else did. AI factions building a settlement after world-gen picked
a **completely random cell** — no fertility, no rivers, no coastline, no
frontier, nothing. That's fixed: the AI now scores its own land the same
way world-gen always has, so a City actually wants a river and a coast, a
Castle actually wants the frontier and high ground. Placing a settlement
yourself now shows an advisory gold-dot hint for where the land wants one
— you can still click anywhere, it's just a hint.

## No more village cap

Villages were capped 3–50 per region by a flat area formula with zero
regard for what the land could actually support. They're now placed
greedily wherever the land clears a real viability bar — a lush,
well-watered region places many, a marginal one places few — and grow as
an organic cluster around cities, towns, and each other instead of
scattering independently across the map.

## Production is real and local now

This is the one that actually matters underneath: every village used to
draw an even slice of one number computed for its *whole region*,
regardless of where it actually sat. A village's own location was
cosmetic. Each village now produces from its own local land — a mountain
village mines Iron, Coal and Stone; a forest village cuts Softwood and
Logs — and settlements draw on that real, sited supply through the same
local trade network as always. More villages on good land now means more
real production, not a thinner slice of a fixed number.

## Roads bend around terrain now

Village and settlement roads used to be drawn as straight lines, full
stop — even though the shipments travelling on them already used real
terrain-aware pathing underneath, quietly rerouting around a mountain the
drawn road cut straight through. Roads now follow that same routing, so
the map and the simulation finally agree.

Local shipments also now prefer your nearest neighboring village or
settlement over a random one — previously whichever candidate happened to
come first in storage order got picked, however far away that actually
was.
