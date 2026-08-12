# v0.18.26.3

The underworld becomes a place anyone can live in, and the fantasy HUD finishes
its sweep across every screen.

## The underground is a place, not a dwarf/goblin ghetto

- **Claim through a gate.** Any realm can claim an underground region it can
  reach through a door it holds — the ordinary claim economy (settlers,
  provisions, a commander at the door), with the galleries handed over bare.
  A bug that silently kept the underground off every frontier is fixed along
  the way (unowned ground behind a door was being read as ocean).
- **The full settlement ladder works below ground.** Found a village, raise it
  to a town, upgrade the town to a city, build new settlements outright — all
  of it in the galleries, with no surface roads to carve (the halls ARE the
  roads).
- **Conquest transfers the right layer.** Take a hold's halls in battle and
  the galleries change hands cleanly — the conqueror gets the caves, not the
  mountainside above them.

## Dwarf holds are halls, not towns

- A hold is now a real realm under the mountain: a **Great Hall** (the
  capital), **Carven Halls** (towns cut into the deep galleries), and
  **hall-steadings** (mining villages born with terraces, stalls and a mine).
  Goblin warrens run more burrows. Mechanically it is the same city/town/
  village ladder — it simply *presents* as halls, from the panels to the map,
  where under-settlements are diamond forge-gold markers rather than surface
  city glyphs.
- **Hybrid mining.** The great hall works its own ore for free (it IS the
  mine); every other hall, burrow and stead must sink a Mining Camp or
  Workings like any surface village — and a deep, abyssal town still out-mines
  a shallow one.

## Fantasy HUD kit coverage

- The last slate-blue chrome in the game is gone (the nav bar, two Close
  buttons) — every HUD colour now lives in `theme.py`.
- The frontier-event dialog and the trade log are now drawn parchment pages
  instead of flat widget boxes.

---

**The 0.18.26.x line continues.** Changelog 117.
