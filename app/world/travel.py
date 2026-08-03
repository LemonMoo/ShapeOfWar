"""How fast a convoy actually moves this turn.

Weather phase 2 (HANDOFF S10). Until now nothing about travel varied
turn-to-turn at all: every caravan, regional shipment and local wagon did a
flat `turn_progress += 1` per turn, so a route's length was decided entirely
at dispatch and nothing that happened along the way could change it. That
left weather with nothing to hook into -- which is exactly why the phasing
put "build a live per-turn progress rate" before "hang weather off it".

Two things move the rate, and they are deliberately different in kind:

  terrain  -- MEAN-NEUTRAL over a route, by construction. A convoy runs
              ahead on the road stretches and falls behind in the hills,
              and in fair weather arrives at exactly the turn it always
              would have. This is presentation and texture, not balance:
              with weather off, nothing about trade timing changes at all,
              which is the sanity check HANDOFF S10 asks for before weather
              is allowed anywhere near it.
  weather  -- the real mechanic, and the only thing that changes how long a
              journey takes. A blizzard in the passes is a delay, and a
              delayed caravan spends more turns exposed to the per-turn
              raid roll, so bad weather costs goods as well as time without
              any separate rule saying so.

This also finally gives Fog a job. It is generated in every climate and has
no crop effect by design, so before this it was a purely cosmetic event; not
being able to see the road is precisely a logistics problem.
"""
from app.world import weather
from app.world.commander import (TERRAIN_MOVE_COST, DEFAULT_MOVE_COST,
                                 ROAD_MOVE_COST)
from app.world.worldgen import road_cells

# What a convoy's day is worth under each kind of weather, (mild, severe).
#
# Drought is 1.0 on purpose and not an oversight: dry ground is GOOD for a
# wagon. A drought is a catastrophe in the fields and nothing at all on the
# road, and pretending otherwise would make every event interchangeable.
#
# Blizzard is the harshest because a closed pass is a closed pass. Storm is
# mud and flooded fords. Fog is slow going rather than dangerous going.
WEATHER_TRAVEL_RATE = {
    weather.DROUGHT:  (1.00, 1.00),
    weather.STORM:    (0.75, 0.55),
    weather.BLIZZARD: (0.65, 0.40),
    weather.FOG:      (0.85, 0.70),
}

# Nothing ever stops dead. A convoy pinned at zero would sit on the map
# forever collecting raid rolls, which is a bug wearing a mechanic's coat --
# this bounds the worst possible journey at four times its fair-weather
# length however badly the terrain and the weather stack up.
MIN_TRAVEL_RATE = 0.25


def _weather_rate(world, pos):
    """The weather multiplier over one cell, or 1.0 where there is none.

    Weather is simulated per REGION and only for regions somebody owns (see
    resources.advance_weather), so open ocean and unclaimed wildland are
    always clear here. That is a real limit rather than a rounding of one:
    a sea storm would need weather over water, which does not exist yet.
    """
    events = getattr(world, "region_weather", None)
    if not events:
        return 1.0
    x, y = int(pos[0]), int(pos[1])
    try:
        region_id = world.region_grid[y][x]
    except (IndexError, TypeError):
        return 1.0
    event = events.get(region_id)
    if event is None:
        return 1.0
    mild, severe = WEATHER_TRAVEL_RATE.get(event.kind, (1.0, 1.0))
    return severe if event.severity == weather.SEVERE else mild


def _cell_cost(world, pos, roads=None):
    """What one cell of this ground costs a wagon, in units of easy-going
    open country. Same table the marching column uses -- a road is a road
    whoever is on it, and a marsh is a marsh.

    `roads` is the world's road-cell set, passed in by callers that are about
    to ask this for a whole route: fetching it per cell was the single
    biggest cost in the real-time frame loop."""
    x, y = int(pos[0]), int(pos[1])
    if roads is None:
        roads = road_cells(world)
    try:
        if (x, y) in roads:
            return ROAD_MOVE_COST
        biome = world.biome_grid[y][x]
    except (IndexError, TypeError):
        return DEFAULT_MOVE_COST
    return TERRAIN_MOVE_COST.get(biome, DEFAULT_MOVE_COST)


def route_pace(world, convoy):
    """The average cell cost along this convoy's whole route.

    This is the denominator that makes terrain mean-neutral: dividing each
    cell's cost by the route's own average means the fast and slow stretches
    cancel over the journey, so `turns_total` -- which was tuned against a
    flat rate and is not being re-tuned here -- stays correct in fair
    weather.

    Cached on the convoy after the first call. Walking a two-hundred-cell
    path once per convoy per turn would be real work for an answer that
    cannot change; `getattr` rather than an attribute means convoys already
    in transit in an old save pick it up on their next turn.
    """
    cached = getattr(convoy, "_route_pace", None)
    if cached is not None:
        return cached
    path = getattr(convoy, "path", None) or []
    if not path:
        pace = 1.0
    else:
        roads = road_cells(world)
        pace = sum(_cell_cost(world, p, roads) for p in path) / len(path)
    pace = max(0.01, pace)
    convoy._route_pace = pace
    return pace


def convoy_rate(world, convoy):
    """How much of a turn's progress `convoy` makes this turn.

    1.0 is "the pace this route was costed at". Above it on a good road in
    clear weather, below it in the hills or under a storm.
    """
    pos = getattr(convoy, "pos", None)
    if pos is None:
        return 1.0
    terrain = route_pace(world, convoy) / _cell_cost(world, pos)
    return max(MIN_TRAVEL_RATE, terrain * _weather_rate(world, pos))


def weather_at(world, pos):
    """The active WeatherEvent over a cell, or None. Shared by the callers
    that want to REPORT the weather a convoy is in rather than act on it."""
    events = getattr(world, "region_weather", None)
    if not events:
        return None
    x, y = int(pos[0]), int(pos[1])
    try:
        return events.get(world.region_grid[y][x])
    except (IndexError, TypeError):
        return None
