# v0.18.20 — The Realm's Own Door

Two fixes from live play: the garrison town belongs to the land you actually
own now, and the under view gives away no map vision from below.

- **The garrison town lives in the realm's own territory.** It used to sit
  at whichever cave door happened to be acceptable — measured across ten
  seeds, seven dwarf starts put it in the wild, outside the land you own —
  because the capital's front gate was cut wherever the rock opened and the
  town accepted unclaimed ground. Now the front gate prefers the realm's
  own mountainside, and the garrison town requires owned territory: the
  capital's own door first, then the nearest real door, never a rival's
  foothold. If no door opens on owned ground yet, the unclaimed region the
  door opens onto is claimed for the realm — so the town is always a town
  of your own land, and the caravans and commander anchor inside it.
- **No surface vision from underground — again.** The GPU flat map was
  compositing the *surface* fog mask over the cave raster, so below ground
  you could read the overworld's revealed/unrevealed exploration pattern.
  The canvas renderer had been gated in 0.18.16; the GPU path never got the
  same gate. Both now share one gate, so it cannot drift apart again. Also
  closed below ground: stale surface selection panels (settlement, village,
  commander, faction) that survived a descent and redrew over the cave map,
  alert clicks that opened surface panels underground, and the terrain
  legend that lingered on the under layer.

Under-view leak checks are now 11 assertions in `dev/test_under_no_leak.py`
(all passing), and the garrison-town placement is verified owned-territory
on every tested seed.
