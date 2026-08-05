"""Weather phase 5: seeing the weather on the map.

    python dev/test_weather_overlay.py [world.pkl]

The last of the weather phases, and deliberately last: it is built against
settled mechanics rather than redone every time tuning changes what needs
showing.

Weather is per-REGION and changes every turn, which rules out the obvious
implementation. The terrain raster is cached and only rebuilt when ownership
changes; redrawing it once a turn for a handful of storms would be absurd. So
the overlay is made of the two things both renderers already share -- a
coloured outline around the region (_map_lines) and a badge at its centre
(_map_labels). No new drawing primitive, no per-cell work, and the Tk canvas
and the GPU map cannot disagree about what the weather looks like.
"""
import sys
import os
import pickle

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk

try:
    root = tk.Tk()
    root.withdraw()
except tk.TclError as exc:
    print(f"no display available ({exc}) -- skipping")
    sys.exit(0)

from app.ui.map_view import MapView, _WEATHER_GLYPH, _WEATHER_MAP_COLOR
from app.world import weather as W

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "worlds", "dev560.pkl")
world = pickle.load(open(PATH, "rb"))
if world.player_faction_idx is None:
    world.player_faction_idx = 0
view = MapView(root, world, lambda *a: None, lambda *a: None)
# A goblin-player world opens on the UNDER layer (its capital is below),
# and weather is a SURFACE event -- view the surface for the overlay checks.
view.layer = 0


def badges(level):
    return [lbl for lbl in view._map_labels(level)
            if any(g in str(lbl[2]) for g in _WEATHER_GLYPH.values())]


def set_weather(pairs):
    world.region_weather = {r.id: e for r, e in pairs}
    view._weather_cache = None


visible = [r for r in world.regions
           if view._cell_revealed(int(r.center[0] * world.w),
                                  int(r.center[1] * world.h))]
assert visible, "this save has no revealed region to put weather over"
print(f"world: turn {world.turn}, {len(visible)} revealed regions")

print("\n--- every kind of weather has a colour and a glyph ---")
assert set(_WEATHER_MAP_COLOR) == set(W.KINDS), (
    set(_WEATHER_MAP_COLOR) ^ set(W.KINDS))
assert set(_WEATHER_GLYPH) == set(W.KINDS), set(_WEATHER_GLYPH) ^ set(W.KINDS)
assert len(set(_WEATHER_GLYPH.values())) == len(W.KINDS), (
    "two kinds share a glyph -- they would be indistinguishable on the map")
assert len(set(_WEATHER_MAP_COLOR.values())) == len(W.KINDS)
print(f"  ok    {len(W.KINDS)} kinds, all distinct: "
      + ", ".join(f"{k} {_WEATHER_GLYPH[k]}" for k in W.KINDS))

print("\n--- drought is on the map even though it does not touch a fight ---")
# It is the one that ruins your HARVEST, which is arguably the event a player
# most needs to see coming. Leaving it off because it has no combat effect
# would be reading the mechanics rather than the game.
assert W.DROUGHT in _WEATHER_GLYPH
print("  ok    drought is shown; it is a farming catastrophe, not a nothing")

print("\n--- clear skies draw nothing at all ---")
set_weather([])
assert not badges(1), badges(1)
clear_lines = len(view._map_lines(1, 4.0))
print(f"  ok    no weather, no badges, {clear_lines} lines")

print("\n--- a storm outlines its region and names itself ---")
region = visible[0]
set_weather([(region, W.WeatherEvent(W.STORM, W.SEVERE, 10))])
stormy = view._map_lines(1, 4.0)
assert len(stormy) > clear_lines, (
    "the weathered region got no outline at all")
found = badges(1)
assert len(found) == 1, found
text = str(found[0][2])
assert _WEATHER_GLYPH[W.STORM] in text and "Storm" in text, text
assert "Severe" in text, ("severity should read on the badge, not just in "
                          "the line weight", text)
print(f"  ok    +{len(stormy)-clear_lines} outline segments and a badge "
      f"reading {text!r}")

print("\n--- severity shows in the line, not only in the words ---")
set_weather([(region, W.WeatherEvent(W.STORM, W.MILD, 10))])
mild = view._map_lines(1, 4.0)


def storm_lines(lines):
    """Only the weather outline. Filtering by colour matters: roads are drawn
    with a wider 'cut' underneath them, so a max() over every line on the map
    just measures a road and reports the two severities as identical."""
    from app.ui.map_view import _GL_RGB
    want = _GL_RGB[_WEATHER_MAP_COLOR[W.STORM]]
    return [(w, dash) for _, colour, w, dash in lines if colour == want]


severe_lines = storm_lines(stormy)
mild_lines = storm_lines(mild)
assert severe_lines and mild_lines, (len(severe_lines), len(mild_lines))
assert max(w for w, _ in severe_lines) > max(w for w, _ in mild_lines), (
    max(w for w, _ in severe_lines), max(w for w, _ in mild_lines))
assert all(dash for _, dash in mild_lines), (
    "a mild event should read as a broken outline")
assert not any(dash for _, dash in severe_lines), (
    "a severe event should read as a solid outline")
print("  ok    severe draws solid and thicker, mild draws dashed and thinner")

print("\n--- CRITICAL: it never leaks weather you could not know about ---")
# Fog-gated on the region's own centre, exactly like its name. Weather over a
# rival's unexplored territory would quietly turn this into a scouting tool.
hidden = [r for r in world.regions
          if not view._cell_revealed(int(r.center[0] * world.w),
                                     int(r.center[1] * world.h))]
if hidden:
    set_weather([(hidden[0], W.WeatherEvent(W.BLIZZARD, W.SEVERE, 10))])
    assert not badges(1), "weather was drawn over unexplored ground"
    assert len(view._map_lines(1, 4.0)) == clear_lines, (
        "an unexplored region's outline gave its weather away")
    print(f"  ok    a blizzard over unexplored {hidden[0].name} is invisible")
else:
    print("  skip  every region on this save is already revealed")

print("\n--- badges start at region view, outlines show from orbit ---")
# A dozen badges over a continent is confetti; the outline already says
# something is happening there.
set_weather([(region, W.WeatherEvent(W.FOG, W.SEVERE, 10))])
assert not badges(0), "weather badges cluttering the world view"
assert badges(1), "no badge at region view"
fog_colour = _WEATHER_MAP_COLOR[W.FOG]
from app.ui.map_view import _GL_RGB

outlined_from_orbit = [ln for ln in view._map_lines(0, 1.0)
                       if ln[1] == _GL_RGB[fog_colour]]
assert outlined_from_orbit, (
    "the outline vanished at world scale too -- then nothing at all tells you "
    "weather is happening from orbit")
print(f"  ok    level 0 draws {len(outlined_from_orbit)} outline segments and "
      f"no badge; level 1 adds the badge")

print("\n--- the answer is cached per turn, not recomputed per frame ---")
# _map_lines and _map_labels both ask, and the GPU map calls both on every
# rebuild. Walking every region in the world twice a frame for something that
# changes once a turn is how a stutter gets built.
first = view._weathered_regions()
assert view._weathered_regions() is first, "recomputed within the same turn"
world.turn += 1
assert view._weathered_regions() is not first, "the cache never expires"
world.turn -= 1
print("  ok    same object within a turn, rebuilt when the turn changes")

print("\n--- both renderers are fed from the same two calls ---")
import inspect
for name in ("_map_lines", "_map_labels"):
    src = inspect.getsource(getattr(MapView, name))
    assert "_weathered_regions" in src, (
        f"{name} does not draw weather -- the canvas and the GPU map would "
        f"disagree about what the world looks like")
print("  ok    _map_lines and _map_labels both draw it, so both surfaces match")

print("\n--- a real turn still runs with the overlay live ---")
from app.world import resources as R
for _ in range(5):
    R.advance_turn(world)
    view._weathered_regions()
    view._map_lines(1, 4.0)
    view._map_labels(1)
print(f"  ok    5 turns rendered; {len(getattr(world, 'region_weather', {}))} "
      f"regions currently under weather")

root.destroy()
print("\nWEATHER OVERLAY TEST PASSED")
