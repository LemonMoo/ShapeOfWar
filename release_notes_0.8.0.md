# v0.8.0 — The Sound of It

The game makes noise now. It also stops pretending a desert and a jungle look
the same, and archers stop winning every fight they turn up to.

## Sound

There was no audio of any kind before this — no music, no effects, nothing.
Now there is:

- **Music** on the map and a different theme in battle. It does not restart
  when you move between the menu and the map; only actually going to war
  changes the tune.
- **Effects** on the things you do: a chain rattling as a turn is submitted,
  pages turning when the build menu opens, timber for a project started and
  stone for one refused, steel when a battle begins.

All of it is **CC0 / public domain**, chosen deliberately over the larger
attribution-required libraries. CC0 means no credits screen is owed, now or
in any future build — and that is not an obligation you can undo once you have
shipped. Sound effects by *rubberduck*, music by *cynicmusic*, both from
OpenGameArt, recorded in full in `assets/audio/LICENSES.md`. Neither requires
credit; both deserve it.

If your machine has no sound device, the game runs exactly as it did before
and the settings screen says so plainly instead of showing you dead sliders.

## Settings

A Settings screen, reachable from the main menu or from the pause menu while
you play. Music volume, effects volume, and a mute.

Everything applies the moment you move it — there is no OK button, because the
only way to judge whether 40% is the right volume is to hear 40%. Moving the
effects slider plays a sound at the new level for the same reason. Your
choices are remembered for next time.

## Every biome shows on the map

The political map tinted the terrain for forests and mountains and nothing
else — which predates the twelve-biome world, so ten of the twelve rendered as
flat faction colour. A desert and a jungle were the same picture.

All twelve tint now, graded rather than evenly: deserts, jungles, mountains
and tundra show hardest, because those are the ones that change what a region
is worth and how an army moves through it. Plains and coast barely tint at
all — ordinary green country is the baseline everything else reads against.
Who owns a place still wins on a political map; you can just also see what
kind of place it is.

## Roads branch

A new settlement used to build exactly one road, to whichever of your
settlements happened to be nearest. Repeated across a growing realm, that
builds a chain: every new town hanging off one older town, and a city with
three towns around it connected to one of them.

Roads now go to every neighbour a place is genuinely nearest to, and skip the
ones already reachable without a detour. A realm's network has junctions.

## Archers

An archer-heavy army won **100%** of clear-weather fights against foot. That
is not a strong choice, it is the only choice.

Accuracy is down from 80% to 60% and damage slightly reduced. It now wins most
clear-weather fights rather than all of them, and bad weather genuinely
punishes it.

Worth knowing if you go tuning: both numbers sit on cliffs rather than slopes.
Dropping accuracy to 55% collapses archers entirely, and range is not a lever
at all — even at a third less range they still won every clear-weather fight.

## Fixed

- Two commanders could stand face to face, unable to land a blow on each
  other, until the clock ran out. A commander's reach was shorter than the
  distance two commanders' bodies are held apart, so they could never actually
  touch. It only started showing up once commanders stopped walking into the
  crowd and began surviving to the end of a battle.
