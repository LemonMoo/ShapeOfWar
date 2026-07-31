# v0.10.0 — Armies That Fight Like Armies

Two things in this one. The sound has never worked in a released build, and it
does now. And every soldier on a battlefield used to be an independent man
running at his own nearest enemy in a straight line, which is why armies fought
like a swarm rather than like armies.

## The sound was never in the exe

v0.8.0 was called "The Sound of It" and shipped completely silent. So did
v0.9.0.

The audio itself was fine — music, effects, the settings screen, all working
from the source tree, which is where it was tested. What was missing was one
line in the build script: **the assets were never packed into the exe.** The
game then did exactly what it was written to do about a missing sound file —
note it once, and never complain again.

It is fixed, and it is fixed for anything else that ever lives in `assets/`.

## Armies

Five changes, all of them to how soldiers *move* and what they *choose*. Not
one stat was touched.

- **Soldiers keep a spacing and step around each other.** There was nothing
  between "that is my target" and "walk at it", so a line compressed into a
  knot and men shoved through their own formation. And a soldier no longer
  joins a fight that three of his fellows already have in hand — he forms up
  behind them and steps in when a place opens.
- **Cavalry ride through.** They used to reverse at the moment of impact and
  come back at the same face of the same formation, over and over. Now a rider
  holds the heading he struck on, rides clear out the far side, wheels, and
  comes again from a direction the enemy is not already facing. Successive
  charges now arrive a mean 115 degrees apart.
- **Archers form a firing line.** Wide, shallow, and staggered so the second
  rank is looking down a gap rather than at the back of the man in front. A
  body of two dozen bowmen under fire went from 128px of frontage to 410px at
  the same depth. There is a **Firing Line** order (L) for your own archers
  too.
- **Signature units fight like what they are.** The Shieldwarden holds the
  front of the line it protects instead of walking out of it. The Standard
  Bearer stays with the body of the army. The Bladesinger works the flanks. The
  Berserker goes to the thickest of it and keeps no formation at all. The
  Sapper bombs the densest knot in reach rather than whichever man is nearest.
  The Assassin goes *around* a line on its way to the bowmen, which is what has
  always killed it.

## What that did to the roster

The species were not rebalanced. Their numbers are untouched. But armies that
hold a formation are worth more than armies that swarm, and the drilled species
were the ones paying for the old behaviour:

| | Humans | Elves | Dwarves | Orcs | Goblins | spread |
|---|---|---|---|---|---|---|
| v0.9.0 | 25% | 79% | 8% | 54% | 83% | **75 pts** |
| v0.10.0 | 50% | 58% | 21% | 54% | 58% | **38 pts** |

The gap between the best and worst army on the roster has halved. Dwarves are
still last and this does not pretend to have finished that job — but it is the
largest single move toward an even roster this game has had, and it came out of
fixing behaviour rather than out of moving numbers.

Judge it in play. Two of sixty tournament battles now run to the clock rather
than to a result, where none did before: formations that hold their ground make
for longer fights.
