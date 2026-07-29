# Shapes of War v0.3.2

Coastlines stop looking like they were dropped in as blobs. Currents give the
ocean somewhere to actually go — and a reason to sail one way over another.
And the globe stops being a photograph you spin and starts being somewhere
you can fly down to.

---

## Coastlines with character

Every continent used to come out as a smooth, round-edged shape no matter the
seed — the noise driving them had no way to produce a fjord or a peninsula,
only a blob. Coastlines are now genuinely irregular: bays, headlands, straits,
island chains, without going full Norway about it.

## Ocean currents

Idealized wind bands, driven off the same latitude the climate system already
uses, spin up gyres the same way real ocean circulation actually works. Those
currents don't just sit there — they **carve the coastline they flow past**: a
fast channel cuts a strait, a sheltered eddy silts into a spit.

- Sail **with** a current and a sea route is up to 30% faster. Fight one and
  it's up to 30% slower — trade convoys and ships both route around this now,
  not just the player.
- Currents render as flowing streamlines on the flat map (toggle: **Currents**),
  fog-gated the same as any other route — you only see what you've explored.

---

## The globe grew up

**The camera tilts now.** Zooming in used to just move straight down the same
overhead ray — an aerial photo with no horizon, however close you got.
Approaching the surface now swings the camera toward a low, oblique angle, so
closing in reads as flying down to somewhere, not staring at a photograph of
it.

**Settlements are real 3D spires**, planted upright out of the ground — not a
flat sticker that only ever faces the camera.

**Terrain has relief.** Mountains bulge up off the sphere; the ocean stays
flat. Same height field the flat map always used — now you can see its shape.

**Fog of war is literal cloud cover.** Unexplored land used to just look
darker. It's now genuinely hidden under drifting cloud — you see weather, not
a dim guess at the truth underneath.

**A new globe opens facing your own capital**, not the map's arbitrary
geometric centre. Your realm's name now reliably shows up over your own
territory at world-view zoom, which previously depended on pure luck in which
direction the planet happened to be facing.

---

## Fixes

Two things silently broke the moment battles started rendering on the GPU,
and neither raised an error:

- The drag-select box and the right-click formation-ghost preview during
  battle planning drew nothing at all.
- More seriously: the "click to continue" prompt after a battle ended never
  appeared — even though clicking anywhere still secretly worked underneath.
  A battle that just ended looked identical to one that was frozen.

Both are fixed. Neither will happen again the same way: the GPU renderer now
carries its own copy of every planning-phase overlay instead of relying on
code the canvas fallback used to own alone.
