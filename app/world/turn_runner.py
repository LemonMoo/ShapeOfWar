"""Running a day a slice at a time, so the map stays live while it happens.

The supply side of real time (app/core/clock.py is the demand side). A day of
world costs about 425ms on a developed map -- as one blocking call that is four
visible freezes a minute at 1x, and it is why the turn-based build needed a
worker thread and a full-frame busy overlay that ate every click.

So the day is not run as one call. `resources.day_steps` is a generator that
pauses between phases, and this steps it under a millisecond budget: as many
phases as fit in the time a frame can spare, then back to the UI, then more
next frame. The world is coherent at every one of those breaks -- that is the
contract `day_steps` documents and the reason a phase is never split in the
middle.

Deliberately NOT a thread. It was one, for exactly this cost, and threading is
the wrong tool the moment the map has to be readable while the world moves:
rendering from another thread's half-updated dictionaries is a race that
CPython will happily turn into a RuntimeError mid-frame. Stepping on the main
thread between frames has no such window, needs no lock, and makes the speed
control a budget rather than a negotiation.
"""
import time

from app.world import resources


# How long a slice of world may take before handing the frame back. The battle
# renderer's own budget is 16.7ms for everything; the world map is not
# animating sixty times a second, so 8ms leaves most of a frame for drawing and
# still gets a 425ms day done in about half a second of wall time.
DEFAULT_BUDGET_MS = 8.0

# A phase is never split, so a single long one overruns the budget on its own.
# This is the ceiling an ordinary phase is held to: past it, chunk the phase
# (resources.REGION_CHUNK, trade.REGIONAL_TRADE_NODE_CHUNK and
# expansion.advance_claims_steps are the three worked examples). Reported
# rather than enforced -- stopping mid-phase is exactly what must never happen.
SLOW_PHASE_MS = 60.0

# ...except where the work is atomic by nature. A region changing hands
# (expansion.resolve_claim_win) repopulates its settlements and relays its
# roads: measured at ~130ms, and there is no split of it that leaves the world
# coherent in between -- a half-transferred region is exactly the kind of state
# nothing else in the game is written to survive seeing. So it is allowed to
# overrun, and the honest description of the result is a brief hitch on the day
# a province falls, which is both rare and the same cost the turn-based build
# paid on every single turn.
#
# Anything added here needs the same argument made for it. The hard ceiling
# below still applies, because "atomic" is not a licence to be unboundedly
# slow.
#   claims          a region changing hands, as above.
#   domestic trade  one uncached terrain path search (trade._regional_route ->
#                   a Dijkstra over the map). Chunking the phase around it got
#                   the p95 from 60ms to 11ms and could go no further, because
#                   what remains is a SINGLE call: there is no break inside one
#                   path search to take. It is already rate-limited per day
#                   (REGIONAL_PATH_BUDGET_PER_TURN) and cached after the first
#                   one, so it spikes on a new route and not otherwise.
ATOMIC_PHASES = frozenset({"claims", "domestic trade"})
HARD_PHASE_MS = 170.0


class TurnRunner:
    """Steps one day at a time, `step()` per frame.

    Owns no policy: it does not decide WHEN a day should start (the clock
    does), only how much of one gets done per call."""

    def __init__(self, world, budget_ms=DEFAULT_BUDGET_MS):
        self.world = world
        self.budget_ms = budget_ms
        self._steps = None            # live generator while a day is in progress
        self.phase = None             # name of the last phase completed
        self.phases_done = 0
        # True only while a phase is actually executing. World code can reach
        # the UI mid-phase (a region changing hands emits an event the app
        # listens to), and anything that reacts by trying to finish the day
        # would be calling next() on a generator that is already running --
        # ValueError, from the middle of a territory transfer. Callers check
        # this and defer instead; see App._pause_world_for.
        self.stepping = False
        self.slowest_phase = (None, 0.0)   # (name, ms) seen this session

    @property
    def busy(self):
        """True while a day is part-done. Nothing may save, and nothing may
        start another day, until this goes false."""
        return self._steps is not None

    def set_world(self, world):
        """Rebind the runner to a different world (a second game in the same
        session, a load). Without this the runner keeps stepping the world it
        was born with: a day of game two would advance game one, the clock
        would call day_done() against days that never happened, and the new
        world's date would sit on day 1 forever while the old one quietly
        ran on. Any day in progress is discarded -- it belongs to the old
        world, and a half-run day must never finish against a different one
        (the world is coherent at every yield, and this is a yield point:
        set_world is only ever called between phases)."""
        self.world = world
        self._steps = None
        self.phase = None
        self.phases_done = 0

    def begin_day(self):
        """Start a day. Harmless if one is already running -- a day in progress
        is never restarted, since that would replay phases that already
        happened to the world."""
        if self._steps is None:
            self._steps = resources.day_steps(self.world)
            self.phases_done = 0

    def step(self, budget_ms=None):
        """Run phases until the budget is spent or the day ends. Returns True
        if the day FINISHED on this call, which is the driver's cue to pay it
        off the clock's backlog.

        The budget is checked between phases, never inside one, so a slice
        overruns by however long the last phase took. That is the price of the
        world being coherent whenever anyone looks at it."""
        if self._steps is None:
            return False
        budget = self.budget_ms if budget_ms is None else budget_ms
        deadline = time.perf_counter() + budget / 1000.0
        while True:
            started = time.perf_counter()
            self.stepping = True
            try:
                self.phase = next(self._steps)
            except StopIteration:
                self._steps = None
                return True
            finally:
                self.stepping = False
            ms = (time.perf_counter() - started) * 1000.0
            self.phases_done += 1
            if ms > self.slowest_phase[1]:
                self.slowest_phase = (self.phase, ms)
            if time.perf_counter() >= deadline:
                return False

    def finish_day(self):
        """Run whatever is left of the current day with no budget at all.

        For the two cases where a part-done day is unacceptable: saving (a save
        must be a whole day, see REALTIME_PLAN) and a battle about to be
        staged. Both are rare, both already involve a pause, and both are far
        better served by a brief hitch than by a world persisted mid-phase."""
        while self._steps is not None:
            self.step(budget_ms=0.0)

    def run_day(self):
        """One whole day, start to finish -- the turn-based behaviour, kept for
        the 'skip a day' key and for anything headless that wants a day without
        a clock."""
        self.begin_day()
        self.finish_day()
