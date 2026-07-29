# Shapes of War v0.3.0

Your world is a planet you can turn in your hands. Armies and caravans travel
their roads instead of teleporting down them. And every species finally fields
something no other species can.

---

## The map is a globe

Press **Globe** and the world wraps onto a sphere. Drag to spin it in any
direction — roll it straight over a pole and it keeps going, because there is no
"up" for it to run out of. Scroll to fly down toward the surface.

This is the **same map**, not a second copy of it. The globe is textured with the
flat map's own image and its own fog, so anything that changes — a border moving,
ground newly explored, a road finished — is already there.

Everything the flat map draws on top of terrain is drawn on the globe too:

- Stone roads, dirt tracks, trade routes and routes under construction
- Caravans and ships in transit, with their active lane lit up
- Realm, region, settlement and village names
- Alert badges over your own settlements
- Fog of war, cell for cell

Clicking a region on the globe selects it exactly as clicking it flat does — it
is the same selection, not a parallel one.

### Flying closer *is* zooming in

There is no view to switch into. What you see depends on how far away you are:

| Altitude | What is drawn |
|---|---|
| Orbit | Realm names, the trunk road network, trade routes |
| Closer | Region names, every settlement |
| Near the ground | Villages, their names, the dirt-track network |

### Terrain keeps its shape

The obvious way to put a rectangular map on a sphere smears everything sideways
as it approaches the poles, until the entire top row of the map converges on a
single point. This one is **conformal** — the map is compressed vertically by
exactly the amount the sphere stretches it horizontally, so a forest is the same
shape at the equator and at the ice line. Distortion measures 1.0000 at every
latitude. Ice caps cover the rest, which is also what a planet looks like.

A **day/night terminator** crosses the world as the years pass — deliberately
gentle, so you can still read borders and roads on the night side. This is a map
first.

Your camera position and which view you prefer are saved with the game.

> Machines without a working 3D context simply stay on the flat map and say so.

## End Turn moves things

Caravans, regional shipments, ships and commanders used to jump from one cell to
another the instant a turn resolved. They now **travel** — sliding along the
route they actually took, over about three quarters of a second, easing away and
settling as they arrive.

A trade network in motion finally looks like one. Fog follows them properly too:
a caravan mid-journey is hidden or shown based on the ground it is crossing right
now, not on where it will end the turn.

Nothing about how a turn resolves changed. The turn is worked out exactly as
before and the animation replays the ground it covered.

## Every species has its own unit

Until now every army was the same three troops in different proportions. Each
species now fields at least one unit nobody else has, paid for out of its own
Swordsmen and Archers plus a small bonus — so it is a genuine advantage rather
than a reshuffle. They are few, and specialised. None of them is a better
Swordsman.

| Species | Unit | What it is |
|---|---|---|
| **Humans** | Standard Bearer | Poor with a sword; everyone near one fights better |
| **Elves** | Bladesinger | Fast, evasive melee — the answer an archer line never had |
| **Dwarves** | Shieldwarden | An anchor. The line around one takes less punishment |
| **Orcs** | Berserker | No shield, and damage that climbs as it bleeds |
| **Goblins** | Sapper | Bombs whose blast catches a whole packed formation |

**Standard Bearer.** Humans' whole identity is that the line is worth more than
the soldiers in it, and until now the only expression of that was a single
commander — concentrated on one body that can die, and worth nothing to the flank
he is not standing on. Banners spread it. Standing near two is worth exactly as
much as standing near one: they cover the field, they do not pile up.

**Bladesinger.** The only elf who can dodge a blow outright, and frail enough
that anything landing a hit is most of the way to killing one. Paid for entirely
out of the bows, so fielding them is a real trade.

**Shieldwarden.** Dwarves are the one species that can cross open ground with
their shields still raised. The Warden is what makes that crossing pay.

**Berserker.** The only unit in the game that is more dangerous hurt than whole.
Leaving one wounded is a decision, not tidying up.

**Sapper.** Does from 110 paces what the Assassin could never survive long enough
to do. Slow to reload and unreliable — but against a tight shield wall, one bomb
hits everyone in it.

The battle AI gives these units orders too. It had only ever recognised
Swordsmen, Archers and Cavalry by name, so anything new simply stood there
unordered — including a Shieldwarden walking out of the very line it exists to
protect.

Every one of them is described in the **Compendium (F1)**, under Military &
Combat.

> **Species balance is in flux.** These units measurably move win rates and are
> not settled yet. The Shieldwarden is worth roughly **+17 points** to Dwarves,
> the roster's weakest species — but the Elf and Goblin units currently cost
> their own side more than they give. Expect these numbers to move again.
