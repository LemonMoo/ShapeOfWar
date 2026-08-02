# Real-time world map — the plan

Turn-based goes. The world map runs on a clock you can pause, slow and speed
up, the way Mount & Blade's does.

## The decision that makes this survivable

**A day stays the simulation quantum.** All 111 per-turn rate constants across
11 modules keep their exact meaning — a crop that grew per turn now grows per
day, a caravan that made `turn_progress += 1` a turn makes it a day. Nothing in
the economy is re-tuned, no balance baseline is thrown away, and
`advance_turn(world)` keeps working unchanged for every dev harness, the
tournament and the benchmark.

This is also what the reference actually does. Warband is not a continuous
simulation: parties move continuously on the map while the economy, AI and
recruitment resolve on periodic ticks. What is continuous is what you can
*see*. That is the split this follows.

## The constraint

`advance_turn` costs **425 ms** on `dev560.pkl` (300 owned regions, 651 nodes,
14 factions), measured this session. Today that is one atomic blocking chunk
that owns the world exclusively while a full-frame busy overlay eats every
click. At a tick every couple of seconds that overlay would blink constantly,
and the map would freeze four times a minute.

So the day gets **sliced**: `advance_turn` becomes an ordered sequence of named
phases, the big loops chunked by index, run under a per-frame time budget. The
speed control is then just a bigger or smaller budget, and on a world too heavy
for the speed asked for, the clock honestly runs slower rather than stuttering.

## Phases

### Phase 1 — the clock (`app/core/clock.py`, new)

Game time in days (`world.turn` remains exactly that, so saves and every
existing rate are untouched), plus a speed state: PAUSED, 1x, 2x, 4x. Real
seconds per game day at 1x is one constant. Pure logic, no UI and no world
dependency — same shape as `weather.py` and `plates.py`.

Also owns **auto-pause**: a battle starting, your territory being attacked, and
a project or order finishing each stop the clock, with the reason recorded so
the UI can say why.

### Phase 2 — slicing the day (`app/world/turn_phases.py`, new)

`advance_turn` is re-expressed as a list of `(name, callable)` phases in the
order it already runs them, with the heavy sweeps (the per-region production
loop above all) chunked so no single slice is long. Two entry points over one
list:

- `advance_turn(world)` — runs every phase to completion. Unchanged behaviour,
  unchanged signature; the whole dev suite keeps passing untouched, and that
  is the regression test for this phase.
- `TurnRunner(world)` — steps phases under a millisecond budget, reporting when
  the day is complete.

**A fingerprint check is the gate**: `dev/bench_turn.py --fingerprint` already
proves a change to turn processing altered nothing. Sliced and unsliced must
produce identical fingerprints.

### Phase 3 — time controls in the UI

End Turn is replaced by pause / 1x / 2x / 4x and a date readout. The busy
overlay goes entirely — with the day sliced there is no window where the world
is unsafe to look at. Alerts become a running feed rather than an end-of-turn
dump. Orders take effect the moment they are given.

### Phase 4 — continuous movement

`_start_move_animation` already interpolates a turn's movement over 0.75s and
nothing in `app/world` knows it exists. It stops being a replay and becomes the
permanent motion: movers interpolate toward their next day-step continuously,
so armies and caravans are always visibly moving rather than teleporting once a
day.

### Phase 5 — battles and the world clock

A battle stops the world clock dead and resumes it after — the strongest of the
auto-pause rules, and the one that makes real time survivable at all.

### Phase 6 — ship

Full suite, a fingerprint comparison, a save loaded from v0.10.0 to prove
migration, and a release.

## Risks, named up front

- **Reading a world mid-day.** The single deepest risk, and the reason for
  slicing rather than threading: phases run on the main thread between frames,
  so there is never a half-updated world being rendered from another thread.
  The existing background worker is removed rather than kept.
- **A phase boundary is a save boundary.** Saving mid-day must either finish
  the day first or record which phase is next. Finishing it is simpler and is
  what this will do.
- **Heavy worlds at 4x.** The clock will not keep up on a late-game world at
  the highest speed. Degrading to a slower clock is the intended behaviour, but
  it must be *visible* rather than silent.
- **Per-turn UI hooks.** A good deal of `map_view.py` refreshes "once per End
  Turn". Each one becomes either per-day or per-frame, and the ones that are
  expensive must not become per-frame by accident.
