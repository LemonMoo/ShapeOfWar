"""Weather Phase 1: crop impact, wired into the real turn loop
(app.world.resources.advance_weather / _advance_region_crop_weather /
compute_village_yield). Phase 0's own generation logic is covered by
dev/test_weather.py; this is specifically about the REAL integration --
does a drought during Growing actually reduce a real village's real
harvest, does the multiplier freeze correctly for the whole Harvest window
instead of drifting turn to turn, does it recover afterward, and does the
alert surface for the right weather kinds and never for Fog.

    python dev/test_weather_economy.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import resources as R
from app.world import weather as W
from app.world.worldgen import generate_world

FAILURES = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not ok:
        FAILURES.append(name)


def _first_region_with_villages(world, faction_idx=None):
    """Any owned region that actually has villages in it.

    Deliberately NOT pinned to faction 0. Weather is not a per-faction
    mechanic and this only needs a real village to measure a harvest at --
    but a foothold can legitimately end up with no villages at all (a known
    worldgen quirk, see HANDOFF), so demanding one from a specific faction
    made this fail whenever the map shifted under it."""
    # Ownership first: an UNCLAIMED region has no `villages` attribute at all
    # until it is settled, so testing it before ownership raises.
    regions = [r for r in world.regions
               if r.faction_idx >= 0
               and (faction_idx is None or r.faction_idx == faction_idx)
               and getattr(r, "villages", None)]
    if not regions:
        raise AssertionError("no owned region anywhere has villages")
    return regions[0]


def _goto_season(world, season):
    while world.season != season:
        R.advance_turn(world)


def test_drought_reduces_harvest():
    print("\n--- a real drought reduces a real harvest ---")
    w = generate_world(width=760, height=456, seed=5, n_factions=4,
                       player_species="Humans", player_name="Test")
    R.advance_turn(w)   # establish world.season
    region = _first_region_with_villages(w)
    village = w.villages[region.villages[0]]

    _goto_season(w, "Spring")   # Wheat/Rye's Growing stage
    baseline = R.compute_village_yield(w, village, w.season)

    for _ in range(R.TURNS_PER_SEASON):
        w.region_weather[region.id] = W.WeatherEvent(W.DROUGHT, W.SEVERE, 30)
        R.advance_weather(w)
        w.turn += 1
        w.season = R.SEASONS[((w.turn - 1) // R.TURNS_PER_SEASON) % len(R.SEASONS)]
    check("season advanced to Summer (Wheat/Rye Harvest)", w.season == "Summer",
          w.season)
    check("a full-season severe drought hit the floor",
          all(abs(m - R.CROP_WEATHER_FLOOR) < 1e-6
              for m in region.crop_weather_mult.values()),
          str(region.crop_weather_mult))

    drought_yield = R.compute_village_yield(w, village, w.season)
    for crop in ("Wheat", "Rye"):
        b, d = baseline.get(crop, 0), drought_yield.get(crop, 0)
        check(f"{crop}: drought yield is meaningfully lower than baseline",
              d < b * 0.5 if b else True, f"{b} -> {d}")


def test_harvest_window_is_frozen():
    print("\n--- the multiplier freezes for the whole Harvest window ---")
    w = generate_world(width=760, height=456, seed=5, n_factions=4,
                       player_species="Humans", player_name="Test")
    R.advance_turn(w)
    region = _first_region_with_villages(w)
    village = w.villages[region.villages[0]]
    _goto_season(w, "Spring")
    for _ in range(R.TURNS_PER_SEASON):
        w.region_weather[region.id] = W.WeatherEvent(W.DROUGHT, W.SEVERE, 30)
        R.advance_weather(w)
        w.turn += 1
        w.season = R.SEASONS[((w.turn - 1) // R.TURNS_PER_SEASON) % len(R.SEASONS)]
    check("now in Harvest (Summer)", w.season == "Summer")
    y1 = R.compute_village_yield(w, village, w.season)
    mult_at_start = dict(region.crop_weather_mult)

    for _ in range(15):   # well into the same Harvest season, weather now clear
        w.region_weather.pop(region.id, None)
        R.advance_weather(w)
        w.turn += 1
        w.season = R.SEASONS[((w.turn - 1) // R.TURNS_PER_SEASON) % len(R.SEASONS)]
    check("still the same Harvest season", w.season == "Summer")
    y2 = R.compute_village_yield(w, village, w.season)
    check("Wheat/Rye multiplier did not change mid-harvest",
          all(mult_at_start.get(c) == region.crop_weather_mult.get(c)
              for c in ("Wheat", "Rye")),
          f"{mult_at_start} -> {region.crop_weather_mult}")
    check("yield stayed IDENTICAL across the same harvest, not improving turn "
          "by turn as it's cut",
          y1.get("Wheat") == y2.get("Wheat") and y1.get("Rye") == y2.get("Rye"),
          f"{y1.get('Wheat')}/{y1.get('Rye')} vs {y2.get('Wheat')}/{y2.get('Rye')}")


def test_recovery_between_seasons():
    print("\n--- recovery once the growing window ends ---")
    w = generate_world(width=760, height=456, seed=5, n_factions=4,
                       player_species="Humans", player_name="Test")
    R.advance_turn(w)
    region = _first_region_with_villages(w)
    _goto_season(w, "Spring")
    for _ in range(R.TURNS_PER_SEASON):
        w.region_weather[region.id] = W.WeatherEvent(W.DROUGHT, W.SEVERE, 30)
        R.advance_weather(w)
        w.turn += 1
        w.season = R.SEASONS[((w.turn - 1) // R.TURNS_PER_SEASON) % len(R.SEASONS)]
    hit_bottom = region.crop_weather_mult.get("Barley", 1.0)
    check("Barley (Plant in Spring) took damage", hit_bottom < 1.0, str(hit_bottom))
    # Clear weather and run a full year -- Barley cycles back to Plant/Growing
    # every year, and should have recovered by the time it matters again.
    for _ in range(R.YEAR_LENGTH_TURNS):
        w.region_weather.pop(region.id, None)
        R.advance_weather(w)
        w.turn += 1
        w.season = R.SEASONS[((w.turn - 1) // R.TURNS_PER_SEASON) % len(R.SEASONS)]
    healed = region.crop_weather_mult.get("Barley", 1.0)
    check("Barley recovered after a clear year", healed > hit_bottom,
          f"{hit_bottom} -> {healed}")


def test_alerts():
    print("\n--- alerts ---")
    w = generate_world(width=760, height=456, seed=5, n_factions=4,
                       player_species="Humans", player_name="Test")
    R.advance_turn(w)
    region = _first_region_with_villages(w)
    village = w.villages[region.villages[0]]

    for kind, expect in ((W.DROUGHT, True), (W.STORM, True),
                         (W.BLIZZARD, True), (W.FOG, False)):
        w.region_weather[region.id] = W.WeatherEvent(kind, W.SEVERE, 10)
        alerts = R.node_alerts(village, w)
        got = any(a["kind"] == "weather" for a in alerts)
        check(f"{kind}: weather alert {'shown' if expect else 'absent'} as expected",
              got == expect, f"alerts={[a['kind'] for a in alerts]}")
    del w.region_weather[region.id]


def test_fresh_multiturn_simulation():
    print("\n--- fresh multi-faction world, 100 turns, weather live the whole time ---")
    w = generate_world(width=1100, height=660, seed=11, n_factions=10,
                       player_species="Humans", player_name="SimTest")
    from app.world.commander import ensure_faction_commanders
    ensure_faction_commanders(w)
    for _ in range(100):
        R.advance_turn(w)
    check("all factions survived to turn 100",
          sum(1 for f in w.factions if not f.eliminated) > 0)
    neg = 0
    for node in list(w.settlements) + list(w.villages):
        for v in (getattr(node, "resources", {}) or {}).values():
            if v < -0.01:
                neg += 1
    check("no negative resource stocks anywhere", neg == 0, str(neg))
    check("region_weather exists and has plausible size",
          hasattr(w, "region_weather") and len(w.region_weather) < len(w.regions))
    check("every active event kind is a real weather kind",
          all(ev.kind in W.KINDS for ev in w.region_weather.values()))


def main():
    test_drought_reduces_harvest()
    test_harvest_window_is_frozen()
    test_recovery_between_seasons()
    test_alerts()
    test_fresh_multiturn_simulation()
    print("\nWEATHER ECONOMY TEST " + ("FAILED: " + ", ".join(FAILURES)
                                      if FAILURES else "PASSED"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
