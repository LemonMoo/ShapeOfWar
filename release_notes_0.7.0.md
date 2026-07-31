# v0.7.0 — The Long Road Update

Weather stops being a thing that only happens to crops, roads stop looking
like they were drawn with a ruler, and a commander stops wandering into the
enemy line on his own.

## Weather reaches the roads

Until now nothing about travel varied turn to turn. Every caravan, regional
shipment and local wagon moved a flat step per turn, so a route's length was
settled the moment it was dispatched and nothing that happened along the way
could touch it — which left weather with nothing to hook into.

Now a journey takes as long as the road allows:

- **Storm** — mud and flooded fords. About 1.4× longer, 1.9× when severe.
- **Blizzard** — a closed pass is a closed pass. 1.6×, and 2.5× when severe.
- **Fog** — slow going rather than dangerous going. 1.2×, 1.5× when severe.
- **Drought** — no effect at all, and that is deliberate. Dry ground is good
  for a wagon. A drought is a catastrophe in the fields and nothing on the
  road, and pretending otherwise would make all four kinds of weather
  interchangeable.

This also finally gives fog something to do. It turns up in every climate and
has no effect on crops by design, so until now it was decoration.

A delayed caravan spends more turns exposed to the raid roll, so bad weather
costs goods as well as time without any separate rule saying so. And terrain
now shows in a convoy's pace — it runs ahead on the road stretches and falls
behind in the hills — but averages out over the route, so **fair-weather
trade times are exactly what they always were**. Weather is the only thing
that actually delays anyone.

## Roads that look like roads

Roads are stored as straight segments between points, and were drawn that
way: dead straight, hard elbow, dead straight again. They are drawn as whole
connected routes now, wandering slightly off the grid and curving through
their corners. A stone road runs truer than a dirt track — an engineered road
against a route that grew.

A stone road also properly replaces the dirt track it was paved over, instead
of leaving it showing through underneath.

## A commander holds his ground

Reported as cavalry swooping the enemy commander up and carrying him off.
Measuring it showed something else: he was not being carried anywhere. Of his
movement in a real battle, 1,006 pixels was him walking in under his own
orders against 128 pixels of being shoved. He was choosing to go.

He does not any more. An AI commander never closes on anything — he fights
what reaches him, and the only thing that moves him is staying with his own
army. If a charge does shove him clear of his soldiers, he rides back.

That change made battles start ending as a duel between two commanders, which
turned up a bug that had been there all along: **a commander's reach is
shorter than two commanders' bodies**, so a pair of them stood face to face,
held apart by their own armour, unable to land a blow until the clock ran out.
Fixed, and it cleared a handful of battles that had never been able to finish.

## The build menu keeps up

- A building under construction counts down where you can see it, and
  finishes without you having to close and reopen the window. The menu used
  to be a snapshot taken when you opened it.
- The countdown counts down. "3 of 8 turns" made you do the subtraction
  yourself every turn.
- Bigger window, narrower cards — four columns where there were three.
- The scroll wheel works anywhere in the window, not just over the scrollbar.

## The globe is gone

It never zoomed in a way that made sense, and making it work would have meant
changing too much elsewhere. Rather than leave a second view half-supported,
it has been removed. The flat map is unaffected — it shared some plumbing with
the globe, which has simply moved somewhere sensible.

## Also fixed

- A commander's marching route was invisible on the map. The dashed preview
  had been drawn on the old canvas renderer for as long as commanders have
  existed, but was never added to the one actually in use — so giving a move
  order showed you nothing at all.
- Settlement and road drawing is a good deal cheaper: a developed realm's
  roads went from a few thousand separately drawn pieces to a few hundred.

## Worth your eye

Battles run slightly longer now that commanders hold back — a few seconds at
the median. If a commander feels too passive, or too reluctant to leave his
army, say so: how far he may stray and how fast he rides back are both
adjustable in the balance lab.
