"""Regional weather: multi-turn events, biased by a region's own static
climate classification.

STATUS: Phase 0 of the weather system (see HANDOFF.md). Weather generation
ONLY -- nothing here reads or writes a World, and nothing anywhere calls
into this module yet. Same posture Phase 1 of the tectonic-plate rework
used: build the core standalone, validate it with a debug render, and only
wire it into gameplay once the geometry/distribution is trusted.

Decided going in (see the design-question rounds that preceded this):
  - Weather is per-REGION, not a single world-wide event -- one part of the
    map can be in drought while another floods.
  - Events last several turns to part of a season (a season is 25 turns),
    not single-turn flicker and not a permanent condition.
  - Occasional and notable, not constant: most turns, most regions have no
    active weather at all.
  - Odds are correlated with the region's own `dominant_climate` (the same
    static "cold"/"arid"/"humid"/"temperate" classify_climate already
    produces) -- arid regions roll drought more, humid/coastal roll storm
    more, cold regions roll blizzard more. Fog has no climate lean.
  - Two severity tiers, Mild and Severe, not a continuous 0..1 intensity or
    a flat present/absent.

Not decided yet, and deliberately not yet wired into anything downstream:
how a drought actually reduces a crop's eventual Harvest (Phase 1), how a
storm slows a caravan/commander mid-journey (Phase 2), or what a blizzard
does to a battle fought in it (Phase 3).
"""
import random

DROUGHT = "drought"
STORM = "storm"
BLIZZARD = "blizzard"
FOG = "fog"
KINDS = (DROUGHT, STORM, BLIZZARD, FOG)

MILD = "mild"
SEVERE = "severe"

# Player-facing labels -- "Severe Drought" reads as an escalation of
# "Drought", not a different thing, which is the whole point of two tiers
# instead of more distinct weather types.
LABELS = {
    DROUGHT: "Drought", STORM: "Storm", BLIZZARD: "Blizzard", FOG: "Fog",
}

# Per-climate weighted odds of each KIND, conditioned on a region having
# already rolled into a new event at all (see EVENT_CHANCE_PER_TURN). Fog
# carries no climate lean -- it can settle in anywhere, which is what makes
# it the one type that reads as a wildcard rather than "the arid/humid/cold
# thing". Rows sum to 1.0 (not enforced at runtime; _weighted_choice
# normalises regardless, so a rounding slip here degrades gracefully rather
# than crashing).
CLIMATE_WEIGHTS = {
    "arid":      {DROUGHT: 0.55, STORM: 0.08, BLIZZARD: 0.00, FOG: 0.37},
    "humid":     {DROUGHT: 0.05, STORM: 0.55, BLIZZARD: 0.00, FOG: 0.40},
    "cold":      {DROUGHT: 0.00, STORM: 0.12, BLIZZARD: 0.53, FOG: 0.35},
    "temperate": {DROUGHT: 0.18, STORM: 0.28, BLIZZARD: 0.06, FOG: 0.48},
}

# Chance a CLEAR region rolls into a brand new event on any given turn.
#
# The number that actually matters for "occasional, notable" is not "how
# likely is at least one event this season" -- it's the STEADY-STATE
# fraction of region-turns spent under one at all, which for this simple
# renewal process is p*D / (1 + p*D) where D is the average duration
# (~11 turns). A first pass at 0.03 measured 24.3% of region-turns under
# weather somewhere -- that reads as a constant background condition, not
# an occasional event, and dev/weather_shot.py is what caught it before
# anything downstream got built against the wrong assumption. 0.007 targets
# ~7%: on a modest kingdom of a couple dozen regions, something is usually
# NOT happening, but a turn rarely goes by with nothing going on anywhere.
# Re-measure once Phase 1 gives this a real gameplay consequence to weigh
# against -- this is a first tuning pass, not a settled number.
EVENT_CHANCE_PER_TURN = 0.007

# How long a rolled event lasts, in turns. A quarter to a bit over half a
# season -- long enough to plan around, short enough that every region
# doesn't end up permanently under one thing or another given the low
# per-turn roll chance above.
EVENT_MIN_DURATION = 6
EVENT_MAX_DURATION = 16

# Severe is the less common tier -- an escalation worth noticing, not the
# default outcome of rolling weather at all.
SEVERE_CHANCE = 0.25


class WeatherEvent:
    """One active event in one region. `turns_left` counts down to 0, at
    which point the region returns to clear (see advance)."""

    __slots__ = ("kind", "severity", "turns_left", "duration")

    def __init__(self, kind, severity, duration):
        self.kind = kind
        self.severity = severity
        self.duration = duration
        self.turns_left = duration

    @property
    def label(self):
        prefix = "Severe " if self.severity == SEVERE else ""
        return prefix + LABELS[self.kind]

    def copy(self):
        """An independent snapshot -- `advance` mutates an active event IN
        PLACE and keeps returning the same object, so anything that wants to
        freeze "what was this region's weather at turn N" for later display
        (a debug render, a save-file summary) needs its own copy, not a bare
        reference that keeps changing underneath it as the simulation
        continues. Caught for real in dev/weather_shot.py, whose first
        version reported every sampled event as having already expired."""
        c = WeatherEvent(self.kind, self.severity, self.duration)
        c.turns_left = self.turns_left
        return c

    def __repr__(self):
        return f"WeatherEvent({self.kind}, {self.severity}, {self.turns_left}/{self.duration})"


def _weighted_choice(rng, weights):
    total = sum(weights.values())
    if total <= 0:
        return rng.choice(list(weights))
    r = rng.uniform(0, total)
    upto = 0.0
    for kind, w in weights.items():
        upto += w
        if r <= upto:
            return kind
    return next(iter(weights))     # float rounding fallback


def roll_new_event(climate, rng):
    """A fresh WeatherEvent for a region of this climate, or None if this
    turn's roll didn't produce one at all. Exposed on its own (not just
    inlined into advance) so dev/weather_shot.py and later tuning can sample
    the distribution directly without simulating turn-by-turn."""
    if rng.random() >= EVENT_CHANCE_PER_TURN:
        return None
    weights = CLIMATE_WEIGHTS.get(climate, CLIMATE_WEIGHTS["temperate"])
    kind = _weighted_choice(rng, weights)
    severity = SEVERE if rng.random() < SEVERE_CHANCE else MILD
    duration = rng.randint(EVENT_MIN_DURATION, EVENT_MAX_DURATION)
    return WeatherEvent(kind, severity, duration)


def advance(event, climate, rng):
    """One turn of one region's weather. `event` is that region's current
    WeatherEvent or None (clear); returns the event that should be active
    AFTER this turn (None if still clear, or if the active one just ran
    out). Takes raw `climate`/`rng` rather than a World or Region, so it is
    fully standalone: testable and renderable before anything wires it in,
    the same reasoning app/world/plates.py's functions took raw
    width/height/seed instead of a World."""
    if event is not None:
        event.turns_left -= 1
        return event if event.turns_left > 0 else None
    return roll_new_event(climate, rng)


def advance_all(climates_by_region, events, rng):
    """Advance every region's weather by one turn. `climates_by_region` is
    {region_id: climate}; `events` is {region_id: WeatherEvent} for regions
    CURRENTLY under one (a clear region simply has no key, rather than an
    explicit None entry, so the common case -- most regions, most turns --
    costs nothing to represent). Mutates and returns `events`."""
    for region_id, climate in climates_by_region.items():
        current = events.get(region_id)
        nxt = advance(current, climate, rng)
        if nxt is None:
            events.pop(region_id, None)
        else:
            events[region_id] = nxt
    return events
