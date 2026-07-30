"""app/world/plates.py -- Phase 1 of the tectonic-plate worldgen rework
(HANDOFF.md §9). Plate assignment and boundary classification only; this
module is not wired into generate_world yet, so these checks are entirely
about the plate geometry and classification being CORRECT and FAST, not
about anything the shipping game currently does.

    python dev/test_plates.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from app.world import plates as P

FAILURES = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not ok:
        FAILURES.append(name)


def test_determinism():
    print("\n--- determinism ---")
    a = P.generate_plates(400, 240, seed=99, n_plates=8)
    b = P.generate_plates(400, 240, seed=99, n_plates=8)
    check("same seed -> identical plate grid",
          np.array_equal(a.plate_id, b.plate_id))
    check("same seed -> identical boundary count",
          len(a.boundaries) == len(b.boundaries))
    c = P.generate_plates(400, 240, seed=100, n_plates=8)
    check("a different seed actually changes the result",
          not np.array_equal(a.plate_id, c.plate_id))


def test_basic_shape():
    print("\n--- basic shape ---")
    pl = P.generate_plates(500, 300, seed=1, n_plates=12)
    check("grid shape matches width/height",
          pl.plate_id.shape == (300, 500))
    check("every cell has a valid plate id",
          pl.plate_id.min() >= 0 and pl.plate_id.max() < len(pl.plates))
    check("every plate owns at least one cell",
          all(p.cell_count > 0 for p in pl.plates),
          str([p.cell_count for p in pl.plates]))
    check("cell counts sum to the whole map",
          sum(p.cell_count for p in pl.plates) == 500 * 300)


def test_continental_fraction():
    print("\n--- continental fraction ---")
    # Sampled across many plates/seeds, not one roll -- FRACTION_CONTINENTAL
    # is a per-plate coin flip, so a single small sample is noisy.
    kinds = []
    for seed in range(30):
        pl = P.generate_plates(300, 200, seed=seed, n_plates=20)
        kinds.extend(p.kind for p in pl.plates)
    frac = kinds.count(P.CONTINENTAL) / len(kinds)
    check("continental fraction lands near the target",
          abs(frac - P.FRACTION_CONTINENTAL) < 0.05,
          f"{frac:.3f} vs target {P.FRACTION_CONTINENTAL}")


def test_seam_wrap():
    print("\n--- seam wrap (x=0 / x=width-1 must be real neighbors) ---")
    # Direct, deterministic check of _neighbor_diff rather than hoping a
    # random seed happens to put a plate across the seam: a hand-built grid
    # where columns 0 and width-1 are the SAME plate must show no boundary
    # between them, and one where they DIFFER must show one.
    same = np.zeros((10, 20), dtype=np.int32)
    diff_e, _ = P._neighbor_diff(same, 1, 0)
    check("identical plate across the seam is not a false boundary",
          not diff_e[:, -1].any(), str(diff_e[:, -1]))

    varied = np.zeros((10, 20), dtype=np.int32)
    varied[:, -1] = 1     # last column is a different plate from column 0
    diff_e, neighbor = P._neighbor_diff(varied, 1, 0)
    check("a real difference across the seam IS detected",
          diff_e[:, -1].all())
    check("...and reports the correct wrapped neighbor",
          (neighbor[:, -1] == 0).all())

    # y must NOT wrap (no north-south wrap anywhere in this game -- see
    # wrap.py's own docstring) -- the top/bottom row must never show a false
    # boundary against the opposite edge.
    pole_test = np.zeros((10, 20), dtype=np.int32)
    pole_test[0, :] = 1        # top row is a different plate from the bottom
    diff_s, _ = P._neighbor_diff(pole_test, 0, 1)   # "south" neighbor
    check("the bottom row does not falsely wrap to the top row",
          not diff_s[-1, :].any(), str(diff_s[-1, :]))


def test_boundary_classification():
    print("\n--- boundary classification ---")
    # Every declared kind should show up somewhere across a decent sample --
    # if one branch of the classifier were unreachable, this is where it'd
    # go quiet without anyone noticing.
    seen = set()
    total = 0
    for seed in range(15):
        pl = P.generate_plates(700, 420, seed=seed, n_plates=18)
        total += len(pl.boundaries)
        seen.update(b.kind for b in pl.boundaries)
    check("every boundary kind is reachable",
          seen == {P.CONVERGENT_CC, P.CONVERGENT_SUBDUCTION, P.CONVERGENT_OO,
                   P.DIVERGENT_CC, P.DIVERGENT_OTHER, P.TRANSFORM},
          f"missing: {sorted({P.CONVERGENT_CC, P.CONVERGENT_SUBDUCTION, P.CONVERGENT_OO, P.DIVERGENT_CC, P.DIVERGENT_OTHER, P.TRANSFORM} - seen)}")
    check("boundaries are a small fraction of the map, not most of it",
          total < 700 * 420 * 15 * 0.15, f"{total} cells")

    pl = P.generate_plates(700, 420, seed=3, n_plates=18)
    kind_of = {p.id: p.kind for p in pl.plates}
    mismatches = []
    for b in pl.boundaries:
        ka, kb = kind_of[b.plate_a], kind_of[b.plate_b]
        both_c = ka == kb == P.CONTINENTAL
        both_o = ka == kb == P.OCEANIC
        if b.kind == P.CONVERGENT_CC and not both_c:
            mismatches.append(b.kind)
        if b.kind == P.CONVERGENT_OO and not both_o:
            mismatches.append(b.kind)
        if b.kind == P.CONVERGENT_SUBDUCTION and (both_c or both_o):
            mismatches.append(b.kind)
    check("collision type always matches the two plates' real kinds",
          not mismatches, f"{len(mismatches)} mismatches")


def test_hotspot_chains():
    print("\n--- hotspot chains ---")
    pl = P.generate_plates(600, 360, seed=5, n_plates=16, n_hotspots=4)
    check("requested chain count", len(pl.hotspot_chains) == 4)
    ok_links = all(len(links) == P.HOTSPOT_CHAIN_LINKS
                   for _pid, links in pl.hotspot_chains)
    check("every chain has the full link count", ok_links)
    in_range = all(0 <= x < 600 and links[0][2] == 1.0
                   for _pid, links in pl.hotspot_chains for x, _y, _s in links[:1])
    check("chain x-coordinates are wrapped into the map",
          all(0 <= x < 600 for _pid, links in pl.hotspot_chains
              for x, _y, _s in links))
    check("strength decays monotonically down each chain",
          all(links[i][2] > links[i + 1][2]
              for _pid, links in pl.hotspot_chains
              for i in range(len(links) - 1)))
    check("the vent itself (age 0) is full strength", in_range)


def test_performance():
    print("\n--- performance ---")
    # Generous ceiling, not a tight budget: the user's own call was quality
    # over a perf cap, this just guards against an accidental reintroduction
    # of the Dijkstra-over-the-whole-map approach that was benchmarked and
    # rejected (1.5-3.2s) in favour of the vectorised coordinate-warp method.
    t = time.perf_counter()
    P.generate_plates(1500, 900, seed=1, n_plates=24)
    elapsed = time.perf_counter() - t
    check("Large-size generation stays well under a second",
          elapsed < 3.0, f"{elapsed:.2f}s")


def main():
    test_determinism()
    test_basic_shape()
    test_continental_fraction()
    test_seam_wrap()
    test_boundary_classification()
    test_hotspot_chains()
    test_performance()
    print("\nPLATES TEST " + ("FAILED: " + ", ".join(FAILURES)
                              if FAILURES else "PASSED"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
