# v0.14.0 — An Illuminated Hand

The whole interface is drawn now.

Everything the game shows you used to be built out of flat grey Tk rectangles
with a warm colour painted over them. This release stops painting over the
toolkit and starts drawing on top of it: every panel, menu and card is now a
page of aged vellum — real procedural parchment with fibres and handling marks
in it — rather than a stack of widgets.

## What changed to look at

- **Parchment everywhere.** Every surface is a drawn sheet, edged with a gold
  double rule and corner flourishes, the way a page in a book is.
- **Illuminated capitals** open every heading, and a fine dotted leader runs
  from each label to its figure, the way a ledger keeps your eye on the line.
- **Warnings arrive under a wax seal.** The alerts panel, in particular, is
  the one you read when something is already going wrong, so it is the one
  that most wanted a seal beside every line.
- **Meters read as ink in a carved channel** — a sunken track with the fill
  cut into it — instead of a plain coloured bar.
- **Buttons are carved plaques**, not grey rectangles, each with a small
  fleuron pressed into either end.

## Where you'll see it

All of it: the title screen and its "What's New" panel, Load Game, Credits,
the pause and defeat screens, the resource bar, the alerts panel, every
selection panel, the treasury, the trade log, the pinned time controls, and
every card in the build menu.

The New Game screen and the battle-over banner keep their interactive
controls — you cannot drag a drawn slider — but lose the slate-blue colours
they were still wearing from before the game had a palette at all, so nothing
looks like a different program any more.

## Under the hood

The surfaces are generated from a seed rather than shipped as image files, so
they cost nothing to carry and can be redrawn at any size for any panel. None
of the numbers, mechanics or balance changed — this is entirely how the game
looks, not how it plays. Your saves load and play exactly as before.
