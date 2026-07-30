"""Validate app/world/weather.py -- Phase 0 of the weather system
(HANDOFF.md). Weather generation ONLY: this never touches a real World, and
has zero effect on the shipping game. It exists to answer, before Phase 1
(economy) starts: does the regional distribution actually look and behave
like "occasional, notable, climate-correlated events" rather than either
constant noise or near-silence.

    python dev/weather_shot.py [world.pkl] [seed] [turns]
    python dev/weather_shot.py dev/worlds/dev560.pkl 7 400

Loads a real generated world purely for its regions' real `dominant_climate`
values (climate is static geography -- nothing about this reads or writes
anything else on the world), simulates `turns` turns of
weather.advance_all, and reports:

  - event count and average duration, overall and per climate
  - climate correlation: does drought actually concentrate in arid regions,
    blizzard in cold ones, etc.
  - what fraction of region-turns have ANY active event (the "is this
    noise or news" check)

...then renders one snapshot turn as a political thumbnail (reusing
app.ui.world_preview, the same renderer the New Game screen uses) with
every region currently under an event labelled by kind and severity.
"""
import os
import pickle
import random
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import ImageDraw

from app.ui.world_preview import render_world
from app.world import weather as W

SEVERITY_COLOR = {W.MILD: (255, 255, 255), W.SEVERE: (255, 70, 70)}
KIND_MARK = {W.DROUGHT: "D", W.STORM: "S", W.BLIZZARD: "B", W.FOG: "F"}


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "dev/worlds/dev560.pkl"
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 7
    turns = int(sys.argv[3]) if len(sys.argv) > 3 else 400
    snapshot_at = turns // 2

    with open(path, "rb") as fh:
        world = pickle.load(fh)

    climates = {r.id: r.dominant_climate for r in world.regions}
    climate_counts = Counter(climates.values())
    print(f"{len(climates)} regions: "
         + ", ".join(f"{c}={n}" for c, n in climate_counts.most_common()))

    rng = random.Random(seed)
    events = {}
    total_started = 0
    started_by_climate_kind = defaultdict(Counter)
    durations = []
    active_region_turns = 0
    snapshot = None

    for turn in range(turns):
        for region_id, climate in climates.items():
            before = events.get(region_id)
            after = W.advance(before, climate, rng)
            if after is None:
                events.pop(region_id, None)
            else:
                events[region_id] = after
                if before is None:            # a NEW event just started
                    total_started += 1
                    started_by_climate_kind[climate][after.kind] += 1
                if after.turns_left == 0:      # ran to completion this call
                    durations.append(after.duration)
        active_region_turns += len(events)
        if turn == snapshot_at:
            snapshot = {rid: ev.copy() for rid, ev in events.items()}

    total_region_turns = len(climates) * turns
    print(f"\n{turns} turns simulated, seed {seed}")
    print(f"{total_started} events started total "
         f"({total_started / turns:.2f}/turn across {len(climates)} regions)")
    if durations:
        print(f"average completed duration: {sum(durations) / len(durations):.1f} turns "
             f"(range {W.EVENT_MIN_DURATION}-{W.EVENT_MAX_DURATION})")
    print(f"region-turns with an active event: {active_region_turns}/{total_region_turns} "
         f"({100 * active_region_turns / total_region_turns:.1f}%)")

    print("\nclimate correlation (share of THAT climate's events, by kind):")
    for climate in ("arid", "humid", "cold", "temperate"):
        counts = started_by_climate_kind.get(climate)
        if not counts:
            print(f"  {climate:10s} (no events rolled)")
            continue
        total = sum(counts.values())
        print(f"  {climate:10s} " + "  ".join(
            f"{W.LABELS[k]} {100 * n / total:4.0f}%" for k, n in counts.most_common()))

    if not snapshot:
        print("\n(no active events at the snapshot turn -- try more turns or a different seed)")
        return

    print(f"\n{len(snapshot)} regions under weather at turn {snapshot_at}:")
    for region_id, ev in list(snapshot.items())[:15]:
        r = next(rg for rg in world.regions if rg.id == region_id)
        print(f"  {r.name:20s} ({r.dominant_climate:9s}) {ev.label:16s} "
             f"{ev.turns_left}/{ev.duration} turns left")

    img = render_world(world, (900, 540), mark_player=False, hide_rivals=False)
    scale_x = img.width / world.w
    scale_y = img.height / world.h
    draw = ImageDraw.Draw(img)
    for region_id, ev in snapshot.items():
        r = next(rg for rg in world.regions if rg.id == region_id)
        cx, cy = r.center[0] * world.w * scale_x, r.center[1] * world.h * scale_y
        color = SEVERITY_COLOR[ev.severity]
        rad = 5 if ev.severity == W.SEVERE else 3.5
        draw.ellipse([cx - rad, cy - rad, cx + rad, cy + rad],
                    fill=color, outline=(20, 20, 20))
        draw.text((cx + rad + 2, cy - 6), KIND_MARK[ev.kind], fill=color)

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"weather_s{seed}_t{snapshot_at}.png")
    img.save(out_path)
    print(f"\n-> {out_path}  (white=Mild, red=Severe; D/S/B/F = "
         f"Drought/Storm/Blizzard/Fog)")


if __name__ == "__main__":
    main()
