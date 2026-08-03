# Audio assets

Everything in this folder is currently **CC0 / public domain**, but that is no
longer a constraint: **the game has a credits screen** (see
`app/ui/credits.py`), so attribution-required work can be used.

The original decision was to avoid CC-BY because a credit is an obligation you
cannot undo once you have shipped -- every future build has to keep carrying
it. That reasoning still holds, and the answer to it is simply that there is
now somewhere for the credit to live, and a test that keeps it honest.

## Adding CC-BY work

Three things, and the third is the one that gets forgotten:

1. Drop the files in `sfx/` or `music/`, and name them the way the existing
   ones are named (`family_NN.ogg`).
2. Add them to the section below, with the author, the licence, and the URL
   the file came from.
3. **Add an entry to `CREDITS` in `app/ui/credits.py`**, with
   `"requires_credit": True`. `dev/test_audio.py` asserts the screen and this
   file agree -- a credit that lives only in a markdown file nobody ships is
   not a credit, and a screen that has drifted from this record is worse than
   no screen at all.

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
pixelsphere.org*. That is honoured on the credits screen, exactly as worded --
see `COURTESY_LINES` in `app/ui/credits.py`.

## Adding more

`app/core/audio.py` maps an EVENT NAME to files (`SFX`, `MUSIC`). Call sites
say `audio.play("build_done")` and never name a file, so adding or swapping a
sound is a change to that one table. Record anything new here with its author,
source URL and licence at the time it is added.
