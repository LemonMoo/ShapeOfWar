# v0.11.0 — The World Does Not Wait

There is no End Turn any more. The world runs, and you decide how fast.

Pause, 1x, 2x or 4x, from exactly where that button used to be, with the date
beside it. Space stops and starts the clock; **E still runs a single day**, for
when you want to step it by hand.

## What a day is

A day is precisely what a turn was. Not a rescaling, not an approximation —
**the same unit of simulation, spent by time passing instead of by a button
press.** Every rate in the economy keeps its exact meaning, every save carries
over untouched, and none of the balance has moved.

What changed is that a day is no longer one blocking lump of work. It is worked
through in slices between frames, so the map stays live while the world moves.
Ten days run in slices and ten days run whole produce byte-identical worlds —
that is asserted by fingerprint, not hoped for.

The visible consequence: **the "Processing turn…" cover is gone**, along with
the freeze it was covering. So is the wait for it.

## Travel that does not stop

Armies, caravans and shipments used to slide over their day's travel in three
quarters of a second and then stand perfectly still until you pressed the
button again. Now a day's march takes exactly as long as the day does, so
things on the map are always moving.

## The clock stops itself

A real-time world will happily take a province off you while you are reading a
panel. So it stops for the things that matter, and the date line says which:

- **a battle** — the world stops dead and is still stopped when you come back,
  because returning from a fight into a running world is how you lose what you
  just won without seeing it happen;
- **losing ground** — someone has taken territory from you;
- **work finishing** — something you ordered built is done.

Real minutes spent fighting are not days the world owes you: the time is
forgiven rather than paid out in a burst on your return.

## Under it

The heavy lifting was making a day interruptible without changing it. Four
things had to be broken into pieces before the map stopped hitching — the
region production sweep, domestic trade (twice: by faction, then by node), claim
resolution, and the AI commander pass. The result is a median slice of **1.0 ms
and a p95 of 12 ms**, against a single 425 ms block before.

Two things are still atomic, and deliberately: a region changing hands cannot be
half-transferred, and a single path search has no break inside it to take. Both
are rare, and both cost exactly what the turn-based build paid on every single
turn.

The worker thread that used to run turns is gone entirely. A day is stepped on
the same thread that draws, which is why the map can be looked at while it
happens.
