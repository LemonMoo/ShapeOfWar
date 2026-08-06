# v0.18.21 — Rivers That Meander

Rivers no longer run ruler-straight across the map.

The flood-fill that drains every basin raises its floor to one perfectly
uniform micro-gradient — and D8 flow on that plain has exactly one
strictly-downhill neighbour, so every river crossing a plain was forced
into a dead-straight line. Measured before this release: **60–80% of river
cells sat in straight runs of four or more cells, the longest 40–146
cells** — the scattered straight lines you could see on the map.

The flow now treats **level ground beside the best drop as an equal choice**
(a tiny deterministic, seam-safe noise breaks the tie), so rivers wander
across plains and meander on gentle slopes, exactly the way real lowland
rivers do. On real slopes the level ground falls outside the tie band and
is ignored, so rivers still follow their valleys. A cycle-break pass keeps
the flow network sound (level moves can point two cells at each other; any
such cycle is redirected before accumulation).

Measured after: **~12% of river cells in straight runs** (runs of 4+ are
ordinary river character — it's the 100+ cell grid-lines that are gone),
longest runs 10–32 cells, and **every river still reaches the sea or a
lake** — no truncation, no rerouted-to-nowhere water. New worlds get the
meandering rivers; existing saves keep the terrain they were born with.

(Straightness and reach are now tracked by `dev/river_metrics.py`.)
