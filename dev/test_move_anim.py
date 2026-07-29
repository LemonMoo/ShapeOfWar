"""End-turn movement animation: does everything that moved actually slide, and
does it slide along the route it really took?

The animation is view-only, so the thing worth asserting is that it is FAITHFUL
-- it must start where the mover stood before the turn, end exactly where the
world put it, and pass through the cells in between rather than cutting across.
A pretty tween that lands somewhere the world disagrees with is worse than a
teleport, because the map would then be lying about where an army is.

    python dev/test_move_anim.py dev/worlds/dev560.pkl
"""
import math
import os
import pickle
import sys
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ui.map_view import MapView, _path_point
from app.world import commander as C
from app.world import resources, wrap

FAILURES = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not ok:
        FAILURES.append(name)


def test_path_point():
    print("\n--- _path_point ---")
    path = [(0, 0), (1, 0), (2, 0), (3, 0)]
    check("frac 0 is the start", _path_point(path, 0.0, 100) == (0.0, 0.0))
    check("frac 1 is the end", _path_point(path, 1.0, 100) == (3.0, 0.0))
    mid = _path_point(path, 0.5, 100)
    check("frac 0.5 is halfway", abs(mid[0] - 1.5) < 1e-9, f"got {mid}")
    check("clamps past the end", _path_point(path, 2.0, 100) == (3.0, 0.0))

    # The seam. A route stepping 98 -> 99 -> 0 -> 1 on a width-100 world must
    # creep across the join, not sweep back through the whole map.
    seam = [(98, 0), (99, 0), (0, 0), (1, 0)]
    xs = [_path_point(seam, i / 30.0, 100)[0] for i in range(31)]
    steps = [abs(wrap.dx_wrap(xs[i], xs[i + 1], 100)) for i in range(len(xs) - 1)]
    check("crossing the seam never jumps", max(steps) < 1.0, f"max step {max(steps):.3f}")
    check("stays in range", all(0.0 <= x < 100.0 for x in xs))


def test_live_turn(path):
    print(f"\n--- a real end turn on {os.path.basename(path)} ---")
    with open(path, "rb") as fh:
        world = pickle.load(fh)
    C.ensure_faction_commanders(world)

    root = tk.Tk()
    root.geometry("1000x700")
    view = MapView(root, world, on_attack=lambda *a, **k: None,
                   on_end_turn=lambda: resources.advance_turn(world))
    view.pack(fill="both", expand=True)
    view.set_world(world)
    root.update()

    before = {id(m): tuple(m.pos) for m in view._movers()}
    snap = view._movement_snapshot()
    resources.advance_turn(world)
    tracks = view._movement_tracks(snap)
    check("something moved", len(tracks) > 0, f"{len(tracks)} movers animating")

    moved = sum(1 for m in view._movers()
                if id(m) in before and tuple(m.pos) != before[id(m)])
    animated = sum(1 for m, _ in tracks if id(m) in before)
    check("every mover that moved is animated", animated >= moved,
          f"{moved} moved, {animated} of them animating")

    # Tolerance is one cell diagonal, and that is not slack: a mover's `pos`
    # is the FLOOR of its continuous progress (see TradeCaravan.pos), so the
    # animation is legitimately more precise than the number it is checked
    # against. Anything beyond a cell means it is on the wrong part of the
    # route, which is what this is actually looking for.
    tol = math.sqrt(2) + 1e-6
    w = world.w
    for mover, walk in tracks:
        start = walk(0.0)
        old = before.get(id(mover))
        if old is not None:
            d = math.hypot(wrap.dx_wrap(old[0], start[0], w), old[1] - start[1])
            if d > tol:
                check(f"{type(mover).__name__} starts where it was", False,
                      f"{old} -> {start}, {d:.1f} cells out")
                break
    else:
        check("every slide starts from the mover's old cell", True)

    for mover, walk in tracks:
        end = walk(1.0)
        d = math.hypot(wrap.dx_wrap(end[0], mover.pos[0], w), end[1] - mover.pos[1])
        if d > tol:
            check(f"{type(mover).__name__} ends where the world put it", False,
                  f"{end} vs {mover.pos}, {d:.1f} cells out")
            break
    else:
        check("every slide ends on the mover's real cell", True)

    # Continuity: no frame may teleport. A route is walked cell by cell, so the
    # biggest step between animation frames is bounded by how far a mover can
    # travel in a turn -- what this really catches is a seam or reversed-leg
    # bug sending something across the map and back.
    worst = 0.0
    for mover, walk in tracks:
        pts = [walk(i / 24.0) for i in range(25)]
        for a, b in zip(pts, pts[1:]):
            worst = max(worst, math.hypot(wrap.dx_wrap(a[0], b[0], w), b[1] - a[1]))
    check("no frame jumps across the map", worst < world.w / 4.0,
          f"largest single-frame step {worst:.1f} cells")

    # And the animation must clean up after itself: once it ends, every mover
    # is back on its own real cell, or the map keeps drawing a stale position.
    view._start_move_animation(tracks)
    check("animation is running", view._move_anim is not None)
    view._stop_move_animation()
    check("stopping clears animated positions", not view._anim_pos)
    check("display falls back to the real cell",
          all(view._display_pos(m) == m.pos for m in view._movers()))

    root.destroy()


def main():
    world_path = sys.argv[1] if len(sys.argv) > 1 else "dev/worlds/dev560.pkl"
    test_path_point()
    test_live_turn(world_path)
    print("\nMOVE ANIMATION TEST " + ("FAILED: " + ", ".join(FAILURES)
                                      if FAILURES else "PASSED"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
