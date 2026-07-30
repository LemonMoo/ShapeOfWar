"""Tectonic plates: geometry, boundary classification, and the height-field
contribution built from them.

STATUS: Phase 2 of the plate-driven worldgen rework (see HANDOFF.md §9).
Phase 1 (plate assignment + boundary classification, this module's top half)
is done and was validated standalone with dev/plate_shot.py before any of
what follows was written. Phase 2 (height_contribution, below) is wired into
generate_world in place of _pick_continent_centers + the blob falloff term.

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

# NOT "Earth's real land fraction" (~29%) -- deliberately close to the GAME's
# own ~40% land target instead (see generate_world's sea-level percentile).
# Land% is a fixed percentile cutoff over cell values regardless of this
# number, so it is always exactly 40% either way -- what this controls is
# HOW FRAGMENTED that 40% is. If continental plate AREA already covers close
# to the target land fraction, the sea-level threshold sits almost exactly at
# the continental/oceanic boundary and needs only a little oceanic-bump land
# to fill the remainder; measured too low (0.32) it forced far more of the
# 40% quota to come from scattered oceanic-boundary bumps, which -- being
# necessarily disconnected from any continental body -- showed up as many
# more separate small landmasses than intended (9-19 across 15 seeds against
# the ~6-7 this project already tuned the old blob system to).
FRACTION_CONTINENTAL = 0.40

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

    # A fixed COUNT of continental plates, not a per-plate coin flip. A coin
    # flip at n_plates=16 landed as low as 1 continental plate in testing --
    # a world with almost no land -- and Phase 2 needs the continental
    # fraction to be a stable knob to tune against, not something that can
    # occasionally vanish on an unlucky seed. Which plates are continental is
    # still random; only the COUNT is fixed.
    n_continental = max(1, min(n_plates - 1,
                               round(n_plates * FRACTION_CONTINENTAL)))
    order = list(range(n_plates))
    py_rng.shuffle(order)
    continental_ids = set(order[:n_continental])

    plates = []
    for i, (sx, sy) in enumerate(seeds):
        kind = CONTINENTAL if i in continental_ids else OCEANIC
        angle = py_rng.uniform(0.0, 2 * math.pi)
        speed = py_rng.uniform(0.4, 1.0)
        plates.append(Plate(i, kind, sx, sy, angle, speed))
    counts = np.bincount(plate_id.ravel(), minlength=len(plates))
    for p in plates:
        p.cell_count = int(counts[p.id])

    boundaries = _classify_boundaries(plate_id, plates, py_rng)
    hotspot_chains = _place_hotspots(py_rng, plates, width, n_hotspots)

    return Plates(width, height, plate_id, plates, boundaries, hotspot_chains)


# --- Phase 2: height-field contribution ---------------------------------------
# Falloff radius for how far a boundary's effect reaches, as a FRACTION of map
# width -- scaled like the old blob system's own radii, so the relative shape
# doesn't change between Small/Standard/Large.
BOUNDARY_FALLOFF_FRAC = 0.045

# Per-kind elevation amplitudes. Signed: positive raises, negative lowers.
# Absolute scale doesn't matter -- generate_world min-max normalises the
# whole field before thresholding at the sea-level percentile, exactly as it
# did for the old blob system's own `v` -- only the RELATIVE size of these
# against each other and against BASE_CONTINENTAL/BASE_OCEANIC matters.
# Starting points, not measured yet: see HANDOFF.md §9 for what still needs
# re-measuring (land %, continent count, mountain-range shape) before these
# are treated as settled.
AMP_CONVERGENT_CC = 1.35          # the big range: two continents colliding
AMP_SUBDUCTION_RANGE = 1.05       # coastal range on the continental side
AMP_SUBDUCTION_TRENCH = -0.85     # trench on the oceanic side of the same boundary
# Cut from 0.55/0.25 (first pass): oceanic-oceanic boundaries are common (most
# plates are oceanic), and at the original amplitudes enough arcs/ridges
# poked above sea level as their own SEPARATE small landmasses that measured
# landmass count ran 9-14 against the ~6-7 target this project already tuned
# the old blob system to (see dev/coastline_metrics.py). Some archipelago
# island-chain effect from these is still real and desired -- an oceanic
# arc/ridge occasionally breaking the surface is exactly the point -- just
# not enough of them to read as a dozen extra "continents".
AMP_CONVERGENT_OO = 0.40          # island arc
AMP_DIVERGENT_CC = -0.65          # rift valley
AMP_DIVERGENT_OTHER = 0.15        # mid-ocean ridge

# Base elevation bias by plate kind -- this is what makes continental plates
# LAND-biased and oceanic ones SEA-biased at all, before any boundary or
# fine-detail noise is added on top.
BASE_CONTINENTAL = 0.75
BASE_OCEANIC = -0.75

# Hotspot islands: a small radial bump per chain link, scaled by that link's
# age-based strength (see _place_hotspots) -- a fresh vent (strength 1) is a
# real island; the oldest, weakest links in a chain barely break the surface.
HOTSPOT_BUMP_AMP = 0.9
HOTSPOT_BUMP_RADIUS_FRAC = 0.012


_DILATE_OFFSETS = ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0),
                   (-1, 1), (0, 1), (1, 1))


def _shift_bool(mask, dx, dy):
    """mask shifted so result[y, x] = mask[y + dy, x + dx] -- the neighbor at
    offset (dx, dy)'s own value, brought to this cell. Same convention
    _neighbor_diff already uses. Wraps in x (cylinder topology); the y edge
    that would otherwise wrap to the opposite pole is cleared to False
    instead -- there is nothing beyond the map's top/bottom to grow into."""
    shifted = np.roll(mask, (-dy, -dx), axis=(0, 1))
    if dy == 1:
        shifted[-1, :] = False
    elif dy == -1:
        shifted[0, :] = False
    return shifted


def _capped_distance(seed_mask, max_radius):
    """Multi-source distance transform, wrap-aware in x (matching the map's
    cylinder topology) and NOT wrap-aware in y (no north-south wrap anywhere
    in this game -- see wrap.py's own docstring), capped at max_radius: cells
    farther than that from any True seed cell get exactly max_radius back,
    which callers treat as "no effect" via their own falloff reaching 0
    there.

    Capping is deliberate, not just a speed trick: a boundary's geological
    influence is bounded (a real mountain range's effect doesn't taper for a
    thousand miles either), so this only ever runs max_radius dilation
    passes instead of however many it would take to flood the whole map --
    the same reasoning _grow_plate_ids' domain-warp trick uses to avoid a
    literal flood fill in the first place.

    Dilates over all 8 neighbors, not 4 -- a first version used only N/S/E/W
    and it showed: the falloff came out as visible diamonds (Manhattan
    distance) radiating from anywhere two boundaries' effects overlapped,
    especially near the several boundaries that meet close together at a
    triple junction. Diagonal steps make it read as roughly circular
    instead, the same fix a real distance transform always needs over a grid
    -- see dev/plate_shot.py's rendered output for the before/after."""
    if not seed_mask.any():
        return np.full(seed_mask.shape, max_radius, dtype=np.int32)
    dist = np.where(seed_mask, 0, max_radius).astype(np.int32)
    frontier = seed_mask
    for step in range(1, max_radius + 1):
        grown = frontier
        for dx, dy in _DILATE_OFFSETS:
            grown = grown | _shift_bool(frontier, dx, dy)
        newly = grown & (dist > step)
        if not newly.any():
            break
        dist[newly] = step
        frontier = newly
    return dist


def _falloff(dist, max_radius):
    """1 at distance 0, 0 at max_radius, smoothstepped -- a boundary's effect
    fades out rather than cutting off sharply at its falloff radius."""
    t = np.clip(1.0 - dist / max_radius, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _boundary_mask(boundaries, kinds, height, width):
    ys = [b.y for b in boundaries if b.kind in kinds]
    xs = [b.x for b in boundaries if b.kind in kinds]
    mask = np.zeros((height, width), dtype=bool)
    if ys:
        mask[ys, xs] = True
    return mask


def _stamp_hotspots(field, pl, width, height):
    """Add each hotspot chain link's island bump directly to the field --
    the same wrap-aware squared-distance-in-a-local-frame technique
    generate_world's own (retiring) blob falloff already used, just circular
    rather than elliptical since an island has no preferred long axis the
    way a whole continent's placement does."""
    if not pl.hotspot_chains:
        return field
    xs = np.arange(width, dtype=np.float64)
    ys = np.arange(height, dtype=np.float64).reshape(-1, 1)
    radius = max(2.0, width * HOTSPOT_BUMP_RADIUS_FRAC)
    for _plate_id, links in pl.hotspot_chains:
        for lx, ly, strength in links:
            ddx = ((xs - lx + width / 2) % width) - width / 2
            ddy = ys - ly
            d2 = (ddx * ddx + ddy * ddy) / (radius * radius)
            field = field + HOTSPOT_BUMP_AMP * strength * np.clip(1.0 - d2, 0.0, None)
    return field


def height_contribution(pl):
    """The plate-driven base of the height field, as a raw (height, width)
    float array -- NOT normalised or thresholded, exactly like the blob
    system's own `v` before generate_world's final min-max/sea-level step,
    so it drops into that same pipeline unchanged.

    Composition: each plate's own kind sets a base land/sea bias; every
    boundary type (except TRANSFORM, which is texture only -- see the class
    docstring) stamps a falloff bump or dip of its own sign and reach.
    Subduction is the one asymmetric case: which side of it a cell is on is
    decided by that CELL's own plate kind, not by which side the specific
    boundary record happened to be kept from (see Boundary's own docstring
    for why only one side is stored per point) -- a single distance field
    from the union of subduction boundary cells already reaches both sides
    equally, since two adjacent cells across a boundary are one step apart
    either way."""
    width, height = pl.width, pl.height
    max_radius = max(3, round(width * BOUNDARY_FALLOFF_FRAC))

    kind_lookup = np.array([1 if p.kind == CONTINENTAL else 0 for p in pl.plates])
    own_continental = kind_lookup[pl.plate_id] == 1

    field = np.where(own_continental, BASE_CONTINENTAL, BASE_OCEANIC)

    cc_mask = _boundary_mask(pl.boundaries, {CONVERGENT_CC}, height, width)
    if cc_mask.any():
        field = field + AMP_CONVERGENT_CC * _falloff(
            _capped_distance(cc_mask, max_radius), max_radius)

    oo_mask = _boundary_mask(pl.boundaries, {CONVERGENT_OO}, height, width)
    if oo_mask.any():
        field = field + AMP_CONVERGENT_OO * _falloff(
            _capped_distance(oo_mask, max_radius), max_radius)

    rift_mask = _boundary_mask(pl.boundaries, {DIVERGENT_CC}, height, width)
    if rift_mask.any():
        field = field + AMP_DIVERGENT_CC * _falloff(
            _capped_distance(rift_mask, max_radius), max_radius)

    ridge_mask = _boundary_mask(pl.boundaries, {DIVERGENT_OTHER}, height, width)
    if ridge_mask.any():
        field = field + AMP_DIVERGENT_OTHER * _falloff(
            _capped_distance(ridge_mask, max_radius), max_radius)

    sub_mask = _boundary_mask(pl.boundaries, {CONVERGENT_SUBDUCTION}, height, width)
    if sub_mask.any():
        sub_falloff = _falloff(_capped_distance(sub_mask, max_radius), max_radius)
        field = field + np.where(own_continental,
                                 AMP_SUBDUCTION_RANGE * sub_falloff,
                                 AMP_SUBDUCTION_TRENCH * sub_falloff)

    field = _stamp_hotspots(field, pl, width, height)
    return field
