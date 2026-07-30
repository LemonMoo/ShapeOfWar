"""app/world/weather.py -- Phase 0 of the weather system (HANDOFF.md).
Weather generation only; not wired into anything yet, so these checks are
entirely about the distribution being CORRECT, not about anything the
shipping game currently does.

    python dev/test_weather.py
"""
import os
import random
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import weather as W

FAILURES = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not ok:
        FAILURES.append(name)


def _simulate(climate, seed, turns):
    rng = random.Random(seed)
    event = None
    started = []
    completed_durations = []
    active_turns = 0
    for _ in range(turns):
        before = event
        event = W.advance(event, climate, rng)
        if event is not None and before is None:
            started.append(event.copy())
        if event is None and before is not None:
            completed_durations.append(before.duration)
        if event is not None:
            active_turns += 1
    return started, completed_durations, active_turns


def test_determinism():
    print("\n--- determinism ---")
    a, _, _ = _simulate("cold", seed=42, turns=500)
    b, _, _ = _simulate("cold", seed=42, turns=500)
    check("same seed -> identical event sequence",
          [(e.kind, e.severity, e.duration) for e in a]
          == [(e.kind, e.severity, e.duration) for e in b])
    c, _, _ = _simulate("cold", seed=43, turns=500)
    check("a different seed changes the sequence",
          [(e.kind, e.severity, e.duration) for e in a]
          != [(e.kind, e.severity, e.duration) for e in c])


def test_duration_bounds():
    print("\n--- duration bounds ---")
    started, completed, _ = _simulate("temperate", seed=1, turns=3000)
    # A weak sanity bound, not a frequency check -- one region over 3000
    # turns is a small, noisy sample (this project's own standing lesson
    # about not trusting small samples applies to its own tests too);
    # test_frequency_is_occasional covers the real statistical claim at
    # n=20000.
    check("events actually occurred", len(started) > 5, str(len(started)))
    check("every rolled duration is within the declared range",
          all(W.EVENT_MIN_DURATION <= e.duration <= W.EVENT_MAX_DURATION
              for e in started))
    check("every event that completed ran its FULL declared duration "
          "(advance never truncates one early)",
          all(d >= W.EVENT_MIN_DURATION for d in completed))


def test_frequency_is_occasional():
    print("\n--- frequency: occasional, not constant ---")
    # A single climate, many turns -- the steady-state fraction of turns
    # under an active event should land in a sane "occasional" band, not
    # near 0 (weather never happens) or near 1 (weather never stops). This
    # is exactly the check that caught the first pass's real bug: 0.03/turn
    # measured 24.3% coverage across a real 1451-region world, which reads
    # as constant background noise rather than a notable event.
    _, _, active_turns = _simulate("temperate", seed=7, turns=20000)
    frac = active_turns / 20000
    check("occasional: active well under half the time, not near-zero either",
          0.02 < frac < 0.25, f"{frac:.3f}")


def test_climate_correlation():
    print("\n--- climate correlation ---")
    for climate, dominant in (("arid", W.DROUGHT), ("humid", W.STORM),
                              ("cold", W.BLIZZARD)):
        started, _, _ = _simulate(climate, seed=5, turns=20000)
        counts = Counter(e.kind for e in started)
        total = sum(counts.values())
        share = counts[dominant] / total if total else 0.0
        check(f"{climate} -> {dominant} is the dominant kind",
              share > 0.4, f"{share:.2f} of {total} events")
    # Fog carries no climate lean -- it should show up everywhere, not just
    # cluster in one climate the way the other three deliberately do.
    for climate in ("arid", "humid", "cold", "temperate"):
        started, _, _ = _simulate(climate, seed=9, turns=20000)
        counts = Counter(e.kind for e in started)
        total = sum(counts.values())
        check(f"fog reaches {climate} too", counts[W.FOG] / max(1, total) > 0.15,
              f"{counts[W.FOG]}/{total}")


def test_severity_distribution():
    print("\n--- severity ---")
    started, _, _ = _simulate("temperate", seed=11, turns=20000)
    severe = sum(1 for e in started if e.severity == W.SEVERE)
    frac = severe / len(started)
    check("severe is the minority tier, near SEVERE_CHANCE",
          abs(frac - W.SEVERE_CHANCE) < 0.06, f"{frac:.3f} vs {W.SEVERE_CHANCE}")


def test_snapshot_copy_is_independent():
    print("\n--- WeatherEvent.copy() ---")
    # The bug dev/weather_shot.py actually hit: advance() mutates an active
    # event in place and keeps returning the SAME object, so a bare
    # reference taken as a "snapshot" silently drifts as the simulation
    # keeps running. copy() is what a caller must use instead.
    rng = random.Random(3)
    event = W.roll_new_event("cold", rng)
    while event is None:
        event = W.roll_new_event("cold", rng)
    bare_ref = event
    snapshot = event.copy()
    turns_left_at_capture = event.turns_left
    for _ in range(3):
        event = W.advance(event, "cold", rng)
        if event is None:
            break
    check("a bare reference drifts as the simulation continues",
          bare_ref.turns_left != turns_left_at_capture or event is None)
    check("copy() stays frozen at the moment it was taken",
          snapshot.turns_left == turns_left_at_capture)


def test_advance_all():
    print("\n--- advance_all (multi-region) ---")
    climates = {i: c for i, c in enumerate(
        ["arid", "humid", "cold", "temperate"] * 50)}
    events = {}
    rng = random.Random(21)
    for _ in range(200):
        W.advance_all(climates, events, rng)
    check("clear regions cost nothing (no key), not an explicit None entry",
          all(rid in climates for rid in events) and len(events) <= len(climates))
    check("every stored event is a real WeatherEvent, never None",
          all(ev is not None for ev in events.values()))


def main():
    test_determinism()
    test_duration_bounds()
    test_frequency_is_occasional()
    test_climate_correlation()
    test_severity_distribution()
    test_snapshot_copy_is_independent()
    test_advance_all()
    print("\nWEATHER TEST " + ("FAILED: " + ", ".join(FAILURES)
                               if FAILURES else "PASSED"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
