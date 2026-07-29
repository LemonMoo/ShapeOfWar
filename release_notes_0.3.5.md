# Shapes of War v0.3.5

The globe stops being a pretty view you have to leave to actually do anything.

---

## Play the whole game from the globe

Clicking a city, a village, or your own commander on the globe used to just
select whatever region happened to be underneath it — there was no way to
open a settlement's panel, check a village, or give your commander an order
without switching back to the flat map. That's fixed:

- **Click a settlement or village directly** to open its panel, the same as
  the flat map.
- **Select and move your commander** — click to select, click again (or arm
  Move) to send them somewhere, and a new right-click shortcut sends them
  straight there without arming anything first.
- **Attack targeting and settlement placement both work** — pick an attack
  target, or place a new City/Town/Castle, straight from orbit.
- **The placement hint shows up too** — arming a settlement now marks the
  region's own best-scoring cells with the same gold-dot hint the flat map
  shows, so you get the same guidance either way.

Region and realm selection — the globe's original behavior — is still there
as the fallback whenever a click doesn't land on anything more specific.

## Fixed: fog haze over your own territory

Fog of war on the globe was hazing over land you'd already fully explored,
not just the genuinely unrevealed parts — the fog mask shared its texture
filtering with the terrain map, which is fine for smooth terrain from orbit
but blurred the sharp revealed/hidden boundary outward onto land that was
never actually hidden. Your own territory (and anywhere else you've
discovered) now reads as completely clear; only real fog of war shows cloud
cover.
