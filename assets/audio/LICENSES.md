# Audio assets

Everything in this folder is **CC0 / public domain**. No attribution is
legally required, and none of it obliges a credits screen.

That was a deliberate choice over the larger CC-BY libraries. CC-BY is free
too, but it is an obligation you cannot undo once you have shipped: every
future build has to keep carrying the credit. CC0 keeps the licence story to
one line. If a CC-BY track is ever added, it needs a visible credits screen
before it ships, and it should be listed separately from everything here.

## Sound effects — `sfx/`

**80 CC0 RPG SFX** by *rubberduck* — https://opengameart.org/content/80-cc0-rpg-sfx
CC0. 80 OGG files: blades, book/page flips, chains, creature sounds, coins,
gems, stone, wood, locks, metal and spells.

## Music — `music/`

**Town Theme RPG** (`town_theme.mp3`) by *cynicmusic* —
https://opengameart.org/content/town-theme-rpg
CC0. Harps and recorders; used as the map theme.

**Battle Theme A** (`battle_theme.mp3`) by *cynicmusic* —
https://opengameart.org/content/battle-theme-a
CC0. Used as the battle theme.

Both authors ask (but do not require) credit as *cynicmusic.com /
pixelsphere.org*. It costs nothing to honour that and it is the decent thing
to do, so if a credits screen is ever added, they belong on it.

## Adding more

`app/core/audio.py` maps an EVENT NAME to files (`SFX`, `MUSIC`). Call sites
say `audio.play("build_done")` and never name a file, so adding or swapping a
sound is a change to that one table. Record anything new here with its author,
source URL and licence at the time it is added.
