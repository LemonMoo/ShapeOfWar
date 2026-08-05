"""The world clock: how fast time passes, and what stops it.

The game was turn-based, and a turn was three things at once -- the unit of
simulation, the unit of the calendar, and the thing the player pressed a button
to spend. This splits them. The DAY is still the unit of simulation and still
`world.turn` (so every per-day rate in the economy keeps its exact meaning, and
so does every save), but it is now spent by time passing rather than by a
button, and the player controls how fast that happens.

Deliberately pure: no World, no Tk, no import of anything in app.world. It
takes real elapsed seconds and reports how much simulated time is owed. What
actually does the work is app.world.turn_phases.TurnRunner, and the two are
kept apart on purpose -- the clock must be testable without a world, and the
simulation must be runnable (by the tournament, the benchmark, every dev
harness) without a clock.

The demand/supply split is the whole design:

  DEMAND   this module. Real seconds in, days owed out. Knows nothing about
           how long a day costs to simulate.
  SUPPLY   the runner. Chews through a day's phases under a millisecond
           budget, and says when a day is finished.

When supply cannot keep up with demand -- a late-game world at 4x -- the
backlog is CAPPED and the overflow is counted rather than queued. The world
then runs slower than the speed asked for, which is honest and visible, instead
of building an unbounded queue of days that arrive in a burst the moment the
player looks at a smaller province.
"""

PAUSED = 0.0

# What the buttons offer. 1x is the reference; the rest are multiples of it.
SPEEDS = (1.0, 2.0, 4.0)

# Real seconds one game day takes at 1x. A season is 25 days and a year 100
# (see resources.TURNS_PER_SEASON), so at this rate a year of world history
# takes about four minutes of watching -- brisk enough that a caravan arrives
# while you are still interested in it, slow enough to give an order before the
# thing you were reacting to has finished happening. First pass, meant to be
# judged in play.
SECONDS_PER_DAY = 2.4

# Days of simulation the clock will let pile up before it starts dropping them.
# Above 1 so a single slow day (a season boundary, a big AI pass) is absorbed
# rather than dropped; low enough that a machine which genuinely cannot keep up
# runs at a steady slower rate instead of lurching.
MAX_BACKLOG = 2.0

# --- why the clock stopped ----------------------------------------------------
# A real-time world that keeps running while the player's attention is
# elsewhere loses them things they would have acted on. Each of these stops it,
# and the reason is kept so the UI can say WHICH -- "paused" with no cause is
# indistinguishable from a bug.
MANUAL = "manual"
BATTLE = "battle"
ATTACKED = "attacked"
PROJECT_DONE = "project"
FRONTIER = "frontier"

PAUSE_REASON_TEXT = {
    MANUAL: "Paused",
    BATTLE: "Paused — a battle",
    ATTACKED: "Paused — you are under attack",
    PROJECT_DONE: "Paused — work finished",
    FRONTIER: "Paused — a frontier event",
}

# Which of them are on by default. MANUAL is not listed because it is not a
# rule, it is the player pressing pause.
DEFAULT_AUTO_PAUSE = {BATTLE: True, ATTACKED: True, PROJECT_DONE: True,
                      FRONTIER: True}


class Clock:
    """Real seconds in, simulated days owed out.

    `pending` is the debt: how much simulated time has been demanded and not
    yet supplied. The driver works it off by finishing days (see `day_done`)."""

    def __init__(self, speed=1.0, seconds_per_day=SECONDS_PER_DAY):
        self.speed = speed              # 0.0 == paused; see PAUSED/SPEEDS
        self.seconds_per_day = seconds_per_day
        self.pending = 0.0              # days owed
        self.dropped = 0.0              # days demanded and thrown away because
                                        # the simulation could not keep up
        self.pause_reason = None        # None while running; see PAUSE_REASON_TEXT
        self._resume_speed = speed or SPEEDS[0]
        self.auto_pause = dict(DEFAULT_AUTO_PAUSE)

    # --- state ----------------------------------------------------------------
    @property
    def paused(self):
        return self.speed <= 0.0

    def pause(self, reason=MANUAL):
        """Stop the clock. Remembers the speed to come back to, so resuming
        after a battle returns the player to the pace they were watching at
        rather than dropping them to 1x."""
        if not self.paused:
            self._resume_speed = self.speed
        self.speed = PAUSED
        self.pause_reason = reason

    def auto_pause_for(self, reason):
        """Pause because something happened, if that rule is enabled. Returns
        whether it actually stopped the clock -- the caller usually wants to
        say so in the log, and only when it was this event that did it.

        Never overrides an existing pause: if the world is already stopped, the
        first reason stands. The player is looking at the reason they were
        given, and rewriting it under them helps nobody."""
        if self.paused or not self.auto_pause.get(reason):
            return False
        self.pause(reason)
        return True

    def resume(self):
        if self.paused:
            self.speed = self._resume_speed or SPEEDS[0]
        self.pause_reason = None

    def toggle_pause(self):
        if self.paused:
            self.resume()
        else:
            self.pause(MANUAL)

    def set_speed(self, speed):
        """Pick a running speed. Also un-pauses -- pressing 2x while paused
        means "run, at 2x", which is the only reading of it that isn't a
        no-op."""
        self.speed = max(0.0, float(speed))
        if self.speed > 0.0:
            self._resume_speed = self.speed
            self.pause_reason = None

    # --- the demand side ------------------------------------------------------
    def tick(self, dt):
        """`dt` real seconds have passed. Adds what that is worth in simulated
        days, and returns how many WHOLE days are now owed -- the driver starts
        a day whenever that is at least one and the runner is idle.

        Time demanded past MAX_BACKLOG is dropped, not queued. See the module
        note: a world that cannot keep up should run slower, not lurch."""
        if self.paused or dt <= 0:
            return int(self.pending)
        self.pending += dt * self.speed / self.seconds_per_day
        if self.pending > MAX_BACKLOG:
            self.dropped += self.pending - MAX_BACKLOG
            self.pending = MAX_BACKLOG
        return int(self.pending)

    def day_done(self):
        """The runner finished a day: pay one off the debt."""
        self.pending = max(0.0, self.pending - 1.0)

    @property
    def keeping_up(self):
        """False once the simulation has genuinely fallen behind the speed
        asked for. The UI shows this rather than hiding it -- a world silently
        running at half the speed on the button is the kind of thing that reads
        as the game being broken."""
        return self.dropped < 1.0

    def forgive_backlog(self):
        """Forget the debt entirely -- used when the world was legitimately not
        being simulated at all (a battle, a load, a long pause), where the
        elapsed real time says nothing about how much world time should have
        passed."""
        self.pending = 0.0
