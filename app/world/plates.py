"""Tectonic plates: geometry and boundary classification.

STATUS: Phase 1 of the plate-driven worldgen rework (see HANDOFF.md §9).
Plate assignment and boundary classification ONLY -- nothing here touches
the height field, and nothing in generate_world calls this yet. The
phasing this project has used for every other worldgen rework is
investigate -> build one verifiable piece -> measure/render -> move on;
this module is that first piece. Validate with dev/plate_shot.py before
Phase 2 (height integration) is attempted.

Model (per HANDOFF.md §9's proposed model, refined during implementation):

  1. Scatter K seed points across the WHOLE map (plates exist under ocean
     too, so this runs with no notion of land/sea yet -- there isn't one).
  2. Grow them into plate territories via a wrap-aware nearest-seed
     assignment over a DOMAIN-WARPED coordinate grid, not a Dijkstra flood
     fill. generate_world's own continent falloff already solves "how do
     you turn a smooth distance field into an organic, non-elliptical
     shape" with exactly this trick (warp the sample coordinates with a
     low-frequency noise field, then evaluate the smooth thing on the
     warped grid) -- reusing it here is both cheaper than a Dijkstra over
     up to 1.35M cells (though that WAS benchmarked: 1.5-3.2s, affordable)
     and stylistically the same move the codebase already made once.
  3. Each plate gets a drift vector (direction + speed) and a kind
     (continental biases toward land later; oceanic biases toward sea).
  4. Every boundary cell (a cell touching a different plate) gets a LOCAL
     normal estimated from which neighbors differ -- not a straight line
     between plate centroids, which would be wrong for anything but two
     circular plates -- and is classified convergent/divergent/transform
     from the two plates' relative drift projected onto that normal, then
     further split by continental/oceanic composition (see the *_KIND
     constants below).
  5. A few plates (oceanic, mostly -- that is the geologically real case
     for a visible chain of islands) get a hotspot: a point fixed in
     absolute space that the plate drifts OVER, leaving a trail of
     progressively older, weaker islands trailing in the direction the
     plate came FROM (opposite its own drift) -- the same mechanism that
     produced the Hawaiian island chain.

Nothing here mutates a World or reads world.height/sea_level -- it takes
raw width/height/seed and returns a self-contained Plates object, so it can
be built, rendered and thrown away without any risk to the pipeline that
currently ships.
"""
import math
import random

import numpy as np

from app.world import noise

CONTINENTAL = "continental"
OCEANIC = "oceanic"

# Boundary kinds. The "_cc"/"_oo"/"_subduction" split matters because a
# collision's effect is NOT symmetric between two oceanic plates, two
# continental ones, or one of each -- see classify below.
CONVERGENT_CC = "convergent_cc"                  # both continental: big range
CONVERGENT_SUBDUCTION = "convergent_subduction"   # one of each: trench + coastal range
CONVERGENT_OO = "convergent_oo"                   # both oceanic: island arc
DIVERGENT_CC = "divergent_cc"                     # both continental: rift valley
DIVERGENT_OTHER = "divergent_other"                # either side oceanic: mid-ocean ridge
TRANSFORM = "transform"                           # sliding past: texture only

# Roughly Earth's real continental fraction. A knob, not a law -- nothing
# downstream depends on this being astronomically accurate, only on there
# being a believable mix of both kinds.
FRACTION_CONTINENTAL = 0.32

# A boundary cell is classified by the RATIO of how much of the relative
# drift is along the normal (opening/closing) vs along the tangent
# (sliding past). Below this ratio it reads as a transform fault instead
# of a real collision or rift -- real transform boundaries (the San
# Andreas) are exactly "mostly sliding, a little of either".
_TRANSFORM_RATIO = 0.55

HOTSPOT_OCEANIC_BIAS = 0.85    # fraction of hotspots seeded on oceanic plates
HOTSPOT_CHAIN_LINKS = 6        # islands per chain, current vent to oldest/weakest
HOTSPOT_STEP_FRAC = 0.028      # spacing between chain links, as a fraction of map width


class Plate:
    """One tectonic plate. `cx`/`cy` are the seed point growth started from,
    not a true post-growth centroid -- close enough for drawing a drift arrow
    and picking hotspot origins, and cheap (no second pass over the grid)."""

    __slots__ = ("id", "kind", "cx", "cy", "drift_x", "drift_y", "speed",
                "cell_count")

    def __init__(self, id_, kind, cx, cy, drift_angle, speed):
        self.id = id_
        self.kind = kind
        self.cx = cx
        self.cy = cy
        self.drift_x = math.cos(drift_angle)
        self.drift_y = math.sin(drift_angle)
        self.speed = speed
        self.cell_count = 0     # filled in after growth


class Boundary:
    """One boundary cell: where it is, the two plates that meet there, and
    what kind of collision (if any) is happening. `strength` is
    |relative drift projected onto the boundary's own normal or tangent,
    whichever the classification actually used| -- a bigger number is a
    harder collision/faster rift/faster slip, and Phase 2 will use it to
    scale how much the height field actually moves here."""

    __slots__ = ("x", "y", "plate_a", "plate_b", "kind", "strength")

    def __init__(self, x, y, plate_a, plate_b, kind, strength):
        self.x = x
        self.y = y
        self.plate_a = plate_a
        self.plate_b = plate_b
        self.kind = kind
        self.strength = strength


class Plates:
    """Everything Phase 1 produces. `plate_id` is a (height, width) int
    array; `boundaries` and `hotspot_chains` are plain lists so they're cheap
    to iterate for rendering or (later) height-field integration."""

    def __init__(self, width, height, plate_id, plates, boundaries,
                hotspot_chains):
        self.width = width
        self.height = height
        self.plate_id = plate_id
        self.plates = plates
        self.boundaries = boundaries
        self.hotspot_chains = hotspot_chains    # [(plate_id, [(x,y,age),...]), ...]


def _periodic_octaves_for(width, octaves):
    """Same freq/period pairing worldgen._periodic_octaves computes, kept
    local rather than imported to avoid a plates<->worldgen import cycle
    (worldgen will import plates once Phase 2 wires this in; plates must
    never import worldgen back)."""
    out = []
    for freq, amp in octaves:
        period_cells = max(1, round(width * freq))
        eff_freq = period_cells / width
        out.append((eff_freq, period_cells, freq, amp))
    return out


def _scatter_seeds(rng, width, height, n):
    """n wrap-aware, spread-out seed points across the WHOLE map -- no
    latitude banding (unlike _pick_continent_centers): plates are a purely
    geometric layer with no climate meaning of their own, so there is no
    reason to bias where they land. Same best-of-K scoring idea as continent
    placement, simplified since there's no per-seed radius to weight by."""
    placed = []
    for _ in range(n):
        best_score, best_xy = -1.0, None
        for _try in range(60):
            x = rng.uniform(0, width)
            y = rng.uniform(0, height)
            if not placed:
                best_xy = (x, y)
                break
            score = min(((x - px + width / 2) % width - width / 2) ** 2
                        + (y - py) ** 2 for px, py in placed)
            if score > best_score:
                best_score, best_xy = score, (x, y)
        placed.append(best_xy)
    return placed


def _grow_plate_ids(width, height, seeds, rng, seed_val):
    """Wrap-aware nearest-seed assignment over a domain-warped coordinate
    grid -- see the module docstring for why this replaces a literal Dijkstra
    flood fill. Returns a (height, width) int32 array."""
    warp_octaves = _periodic_octaves_for(width, [(0.010, 1.0), (0.024, 0.4)])
    # Amplitude in CELLS, scaled to a fraction of typical plate spacing
    # (width / sqrt(n_plates)) rather than a fixed constant -- few big plates
    # need a bigger wobble to look organic than many small ones do, the same
    # reasoning generate_world's own warp_amp already applies to continent
    # count.
    spacing = width / max(1.0, math.sqrt(len(seeds)))
    warp_amp = spacing * 0.35
    warp_x = (noise.fbm_grid(width, height, seed_val + 501, warp_octaves)
              - 0.5) * 2.0 * warp_amp
    warp_y = (noise.fbm_grid(width, height, seed_val + 907, warp_octaves)
              - 0.5) * 2.0 * warp_amp

    xs = np.arange(width, dtype=np.float64)
    ys = np.arange(height, dtype=np.float64).reshape(-1, 1)
    plate_id = np.zeros((height, width), dtype=np.int32)
    best_d2 = None
    for i, (sx, sy) in enumerate(seeds):
        ddx = ((xs - sx + warp_x + width / 2) % width) - width / 2
        ddy = ys - sy + warp_y
        d2 = ddx * ddx + ddy * ddy
        if best_d2 is None:
            best_d2 = d2
        else:
            better = d2 < best_d2
            plate_id[better] = i
            best_d2 = np.where(better, d2, best_d2)
    return plate_id


def _neighbor_diff(plate_id, dx, dy):
    """(differs, neighbor_plate_id) shifted by (dx, dy). x wraps via np.roll,
    matching the map's cylinder topology (see wrap.py); y does not -- the
    shifted array's top/bottom edge row is patched back to itself so the
    poles never wrap into a fake boundary against the opposite edge."""
    shifted = np.roll(plate_id, (-dy, -dx), axis=(0, 1))
    if dy == 1:
        shifted[-1, :] = plate_id[-1, :]
    elif dy == -1:
        shifted[0, :] = plate_id[0, :]
    return shifted != plate_id, shifted


def _classify_boundaries(plate_id, plates, rng):
    """Every boundary cell, classified. Vectorised over the whole grid: the
    four axis-aligned neighbor comparisons build a local normal (which way is
    "the other plate" from this cell) and pick one neighboring plate id to
    classify against, then the actual classification happens only at the
    (typically a few percent of the map) cells that are boundaries at all."""
    h, w = plate_id.shape
    normal_x = np.zeros((h, w), dtype=np.float64)
    normal_y = np.zeros((h, w), dtype=np.float64)
    is_boundary = np.zeros((h, w), dtype=bool)
    other_id = np.full((h, w), -1, dtype=np.int32)
    # Fixed priority order (E, W, S, N) so a corner cell touching 3+ plates
    # deterministically picks one neighbor to classify against rather than
    # the last direction checked overwriting silently -- triple junctions
    # are real geology but a full N-way split is more machinery than a first
    # pass needs; one boundary relationship per cell is enough to read as a
    # range on the map.
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        diff, neighbor = _neighbor_diff(plate_id, dx, dy)
        normal_x += dx * diff
        normal_y += dy * diff
        take = diff & (other_id < 0)
        other_id[take] = neighbor[take]
        is_boundary |= diff

    ys, xs = np.nonzero(is_boundary)
    if len(xs) == 0:
        return []

    nx, ny = normal_x[ys, xs], normal_y[ys, xs]
    nlen = np.hypot(nx, ny)
    nlen[nlen == 0] = 1.0
    nx, ny = nx / nlen, ny / nlen
    tx, ty = -ny, nx     # tangent: normal rotated 90 degrees

    self_ids = plate_id[ys, xs]
    other_ids = other_id[ys, xs]
    drift_x = np.array([p.drift_x * p.speed for p in plates])
    drift_y = np.array([p.drift_y * p.speed for p in plates])
    rel_x = drift_x[other_ids] - drift_x[self_ids]
    rel_y = drift_y[other_ids] - drift_y[self_ids]

    score_normal = rel_x * nx + rel_y * ny        # negative = converging
    score_tangent = rel_x * tx + rel_y * ty
    magnitude = np.hypot(score_normal, score_tangent)
    magnitude_safe = np.where(magnitude == 0, 1.0, magnitude)
    normal_frac = np.abs(score_normal) / magnitude_safe

    kinds = [None] * len(xs)
    kind_of = {p.id: p.kind for p in plates}
    for i in range(len(xs)):
        a, b = int(self_ids[i]), int(other_ids[i])
        if a > b:
            # Every physical boundary shows up as two adjacent cells, one
            # owned by each plate. Keeping only the lower-id side gives
            # exactly one Boundary record per boundary POINT instead of two
            # (which would double-count it for Phase 2's height integration)
            # -- it draws the curve consistently offset one cell into
            # whichever plate happens to have the lower id, not a gap.
            continue
        ka, kb = kind_of[a], kind_of[b]
        both_continental = ka == kb == CONTINENTAL
        both_oceanic = ka == kb == OCEANIC
        if normal_frac[i] < _TRANSFORM_RATIO:
            kind = TRANSFORM
        elif score_normal[i] < 0:
            if both_continental:
                kind = CONVERGENT_CC
            elif both_oceanic:
                kind = CONVERGENT_OO
            else:
                kind = CONVERGENT_SUBDUCTION
        else:
            kind = DIVERGENT_CC if both_continental else DIVERGENT_OTHER
        kinds[i] = (kind, float(magnitude[i]))

    boundaries = []
    for i, x, y, a, b in zip(range(len(xs)), xs, ys, self_ids, other_ids):
        if kinds[i] is None:
            continue
        kind, strength = kinds[i]
        boundaries.append(Boundary(int(x), int(y), int(a), int(b), kind,
                                   strength))
    return boundaries


def _place_hotspots(rng, plates, width, n_hotspots):
    """Island chains: a hotspot is fixed in absolute space, so as its plate
    drifts over it, the chain of past eruption sites trails in the direction
    the plate CAME from -- i.e. opposite its own drift vector. Strength
    decays down the chain (older = weaker/more eroded); Phase 2 will read
    that into how tall/likely each link's island actually is."""
    oceanic = [p for p in plates if p.kind == OCEANIC]
    continental = [p for p in plates if p.kind == CONTINENTAL]
    step = width * HOTSPOT_STEP_FRAC
    chains = []
    for _ in range(n_hotspots):
        pool = oceanic if (oceanic and rng.random() < HOTSPOT_OCEANIC_BIAS) \
            else (continental or oceanic)
        if not pool:
            break
        plate = rng.choice(pool)
        hx = plate.cx + rng.uniform(-0.3, 0.3) * width
        hy = plate.cy + rng.uniform(-0.15, 0.15) * width
        back_x, back_y = -plate.drift_x, -plate.drift_y
        links = []
        for age in range(HOTSPOT_CHAIN_LINKS):
            lx = (hx + back_x * step * age) % width
            ly = hy + back_y * step * age
            strength = 1.0 - age / HOTSPOT_CHAIN_LINKS
            links.append((lx, ly, strength))
        chains.append((plate.id, links))
    return chains


def generate_plates(width, height, seed=None, n_plates=16, n_hotspots=None):
    """Build a Plates object. `n_plates` is the whole knob -- per the
    decision in HANDOFF.md §9, plate count is exposed on its own rather than
    being derived from a target continent count; how many continents that
    actually produces once Phase 2 wires height in is a separate, measured
    question. `n_hotspots` defaults to roughly one per four plates."""
    py_rng = random.Random(seed)
    seed_val = py_rng.randint(0, 2 ** 31 - 1)
    if n_hotspots is None:
        n_hotspots = max(1, round(n_plates / 4))

    seeds = _scatter_seeds(py_rng, width, height, n_plates)
    plate_id = _grow_plate_ids(width, height, seeds, py_rng, seed_val)

    plates = []
    for i, (sx, sy) in enumerate(seeds):
        kind = CONTINENTAL if py_rng.random() < FRACTION_CONTINENTAL else OCEANIC
        angle = py_rng.uniform(0.0, 2 * math.pi)
        speed = py_rng.uniform(0.4, 1.0)
        plates.append(Plate(i, kind, sx, sy, angle, speed))
    counts = np.bincount(plate_id.ravel(), minlength=len(plates))
    for p in plates:
        p.cell_count = int(counts[p.id])

    boundaries = _classify_boundaries(plate_id, plates, py_rng)
    hotspot_chains = _place_hotspots(py_rng, plates, width, n_hotspots)

    return Plates(width, height, plate_id, plates, boundaries, hotspot_chains)
