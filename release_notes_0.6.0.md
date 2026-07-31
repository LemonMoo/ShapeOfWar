# v0.6.0 — The Lay of the Land Update

The Homelands Update gave the world twelve real biomes and put every people
where it came from. This one makes that map matter once you leave the economy
screen: terrain now shapes how fast an army moves, how a battle goes, and what
a village can reach.

## A march is reckoned in country, not miles

Movement was a flat number of cells a turn regardless of what was underfoot. It
is a budget now, and every cell of the route spends its own terrain's share:

- plains — 5 cells a turn
- forest — 3
- swamp, mountain — 2

**Your road network is worth an army now.** A road is cheaper than the easiest
open country, so a column moving on its own roads covers 8 cells a turn against
5 across open plains and 2 through a marsh. Rome built roads precisely because
moving off one cost so much more — until now the network only carried trade.

A commander ordered across a mountain is slowed, never stranded: a column
always advances at least one cell. Ships are unaffected; there is no terrain
out there.

## Where a battle is fought

The battle sim had no terrain hooks of any kind. A fight in a marsh resolved
exactly like one on open plains, which made the whole map read as decoration
the moment an army arrived. Three things now change with the ground:

- **Broken, wet or steep ground slows both sides.** Swamp and mountain are the
  worst of it.
- **The high ground favours whoever already holds it.** This is the defender's
  bonus only — that is the entire point of high ground. A mountain defender
  fields noticeably tougher soldiers, and claiming a mountain wildland is now
  genuinely harder than claiming a plain.
- **Cover shortens the bow line.** Jungle and forest archers keep their punch
  but have to come close enough to be charged. Cover is about not being able to
  see what you are shooting at, not about arrows bouncing off trees.

The banner over each battle tells you plainly what the ground is doing before
it starts.

These are sized to colour a fight rather than decide one. **The mountain
defender bonus is the number most likely to feel wrong in either direction, and
an archer-heavy species fighting in jungle is the matchup to watch.** Say so if
it does.

## Outstations for every kind of country

The Mining Camp let a village work a seam nobody lived near. Every kind of
country gets that now — the Woodcutters' Camp in forest, taiga and jungle, the
Grange on plains, steppe and savannah, and the Workings in highland, desert,
coastal, tundra and swamp.

They are deliberately not twelve different buildings. They are one mechanic
with a biome argument: reach. Working cells that lie inside your region but
outside a village's own catchment. Same cost, same tiers, same everything —
which makes them fair by construction rather than by balancing, and there is no
homeland that quietly got the better building.

They are a genuine trade, not free output. One camp per region per family
measured Iron and Coal up 13%, Barley up 20% and Salt up 16% — with **timber
down 4%**, because the hands went to the ore and the farmland and had to come
from somewhere.

## The map and the HUD

- Settlements are bigger and easier to pick out, scaling up as you zoom in.
- Roads and villages appear a good deal further out than they did.
- Ending a turn no longer blanks the screen to a "Processing turn…" panel, and
  the side panels no longer flash as they rebuild. Two separate causes: meters
  were forcing a full repaint mid-rebuild to measure their own width, and
  panels were being torn down and rebuilt while still on screen.

## Fixed

- Resource amounts like `44.20000000000000045`. A building-upkeep figure is
  fractional and the timber need it feeds was never rounded, so fractions were
  leaking into every stockpile in the world. Fixed at the source rather than
  papered over in the display.
- An outstation could outrank a granary that was 100% full and turning
  production away, because its recommendation score was a raw cell count where
  every other score is a fraction. The Mining Camp had the same bug and only
  escaped notice because it is offered in far fewer places.
