"""Ocean currents: driven by the same latitude/temperature banding the
climate system already uses, and used for two things --

  1. Carving the coastline. Wind-driven currents are deflected by whatever
     coastline already exists, which concentrates flow (and, physically,
     erosive energy) along some stretches of coast and starves others --
     that differential is what turns a merely-irregular coastline (the
     domain-warp fix in worldgen.py) into one with the asymmetric look of a
     real one: a fast channel cutting a strait, a sheltered bay silting up
     into a spit, both on the SAME coastline for a reason the game can point
     to (a current runs through here) rather than by coincidence of noise.
     The shelf pass (apply_erosion_shelf) then lays shallow water along every
     shore, so a coast slopes out to sea instead of stopping straight at the
     waterline; worldgen applies it to whatever layout survives its landmass
     checks, carved or not.
  2. Sea travel speed. A route that runs with a strong current is faster to
     sail than one that fights it (see CURRENT_SPEED_CAP and app/world/trade.py
     / commander.py's sea-cost functions).

Physical model (deliberately the simplified textbook version, not a real
ocean GCM -- this needs to run once per world generation in well under a
second, not converge a real Navier-Stokes solve):

  temperature/latitude  ->  idealized 3-cell-per-hemisphere wind bands
                             (trade winds / westerlies / polar easterlies --
                             the same bands that, in reality, drive the
                             ocean's subtropical and subpolar gyres)
                        ->  wind-stress CURL (Sverdrup's relation: it is the
                             curl of the wind, not the wind itself, that
                             forces large-scale ocean circulation)
                        ->  a streamfunction psi solving a Poisson equation
                             against that forcing, with psi = 0 on land --
                             "the coastline is a streamline" is exactly the
                             boundary condition that makes flow run ALONG a
                             coast and never through it, which is also
                             physically why real western-boundary currents
                             (the Gulf Stream, the Kuroshio) exist at all
                        ->  current velocity = the streamfunction's own
                             rotated gradient (u, v) = (dpsi/dy, -dpsi/dx),
                             which is automatically divergence-free -- no
                             current can appear from nowhere or vanish into
                             a sink, it only ever circulates.

Everything here operates on numpy arrays shaped (height, width), matching
worldgen.py's [y][x] convention, and wraps in x via np.roll the same way
wrap.py's dx_wrap wraps -- there is no wrap in y, matching the rest of the
game (the poles are real edges, the equator is not a seam).
"""
import numpy as np

from app.world import noise
from app.world import wrap

# --- wind bands ----------------------------------------------------------
# Boundaries of the three idealized bands, as normalized distance from the
# equator (0) to the pole (1) -- thirds, the standard idealized-circulation
# split. Blended with a smoothstep rather than a hard switch so the curl
# forcing derived from d(wind)/dy stays a smooth field, not a spike exactly
# at the boundary.
BAND_1_EDGE = 1.0 / 3.0
BAND_2_EDGE = 2.0 / 3.0
BAND_BLEND = 0.06     # half-width of the smoothstep transition, in the same
                      # 0..1 distance-from-equator units as the bands above
MERIDIONAL_SHARE = 0.35  # meridional (toward/away from equator) wind as a
                         # fraction of the zonal (east/west) component --
                         # kept well below 1 so the bands still read as
                         # "mostly east-west belts," matching real trade
                         # winds/westerlies, with just enough poleward/
                         # equatorward drift to seed the gyre circulation


def _smooth_step_band(d, edge, half_width):
    t = np.clip((d - edge) / (2 * half_width) + 0.5, 0.0, 1.0)
    return t * t * (3 - 2 * t)


def wind_field(width, height):
    """(wind_u, wind_v) over the whole grid, driven ONLY by latitude -- the
    same distance-from-equator quantity worldgen._classify_biomes_and_climate
    computes as latitude_temp (1 - abs(y/h - 0.5) * 2 is that function's own
    temperature; this is 1 minus it, i.e. distance from the equator rather
    than closeness). Real idealized atmospheric circulation is latitude-only
    to first order (it's called the 3-CELL model, not the 3-cell-plus-
    continents model), so this needs nothing about where land actually is."""
    ys = np.arange(height, dtype=np.float64).reshape(-1, 1)
    d = np.abs(ys / height - 0.5) * 2.0                    # 0 equator .. 1 pole
    toward_equator = np.sign(height / 2.0 - ys)             # +1 if y is north
                                                            # of the equator row
    # Zonal (east-west) sign per band: trade winds and polar easterlies both
    # blow east-to-west (negative); westerlies blow west-to-east (positive).
    # Blended across the two band edges rather than switched.
    b1 = _smooth_step_band(d, BAND_1_EDGE, BAND_BLEND)      # 0 in trades, 1 beyond
    b2 = _smooth_step_band(d, BAND_2_EDGE, BAND_BLEND)      # 0 through westerlies, 1 in polar
    zonal = -1.0 * (1 - b1) + 1.0 * (b1 * (1 - b2)) + -1.0 * b2
    # Meridional: convergent on the equator side of each cell boundary,
    # divergent on the poleward side -- toward the equator in the trade-wind
    # belt, poleward through the westerlies, equatorward again in the polar
    # easterlies. Same band blend, signed by hemisphere.
    merid_sign = 1.0 * (1 - b1) + -1.0 * (b1 * (1 - b2)) + 1.0 * b2
    wind_u = np.broadcast_to(zonal, (height, width)).copy()
    wind_v = np.broadcast_to(merid_sign * toward_equator * MERIDIONAL_SHARE,
                             (height, width)).copy()
    return wind_u, wind_v


# --- streamfunction solve --------------------------------------------------
SOLVE_DOWNSAMPLE = 6      # solve at 1/6 resolution -- gyres are a large-scale
                          # feature, and relaxation converges far faster (and
                          # is far cheaper per iteration) on a coarse grid
SOLVE_ITERATIONS = 260
CURRENT_MAG_CLIP = 3.0    # multiples of the 97th-percentile magnitude; see
                          # the note where this is applied


def _downsample_bool_or(mask, factor):
    h, w = mask.shape
    ch, cw = (h + factor - 1) // factor, (w + factor - 1) // factor
    ph, pw = ch * factor - h, cw * factor - w
    padded = np.pad(mask.astype(np.float64), ((0, ph), (0, pw)), mode="edge")
    return padded.reshape(ch, factor, cw, factor).mean(axis=(1, 3))


def _upsample(field, out_h, out_w):
    """Bilinear upsample -- ψ and the currents derived from it are meant to
    be large-scale and smooth, so this introduces no character of its own,
    just spreads the coarse solve back out."""
    h, w = field.shape
    ys = (np.arange(out_h) + 0.5) * h / out_h - 0.5
    xs = (np.arange(out_w) + 0.5) * w / out_w - 0.5
    y0 = np.clip(np.floor(ys), 0, h - 1).astype(int)
    x0 = np.clip(np.floor(xs), 0, w - 1).astype(int)
    y1 = np.clip(y0 + 1, 0, h - 1)
    x1 = np.clip(x0 + 1, 0, w - 1)
    fy = np.clip(ys - y0, 0, 1).reshape(-1, 1)
    fx = np.clip(xs - x0, 0, 1).reshape(1, -1)
    top = field[np.ix_(y0, x0)] * (1 - fx) + field[np.ix_(y0, x1)] * fx
    bot = field[np.ix_(y1, x0)] * (1 - fx) + field[np.ix_(y1, x1)] * fx
    return top * (1 - fy) + bot * fy


def solve_currents(land_mask, width, height):
    """(u, v) surface current at every OCEAN cell; zero on land.

    Solves Poisson's equation against the wind's curl -- Sverdrup's relation,
    the textbook link between idealized wind bands and large-scale ocean
    gyre circulation -- with psi=0 on land (a coastline is a streamline: no
    flow crosses it, which is what makes currents run ALONG a coast instead
    of through it, and is also why real ocean boundary currents exist at
    all). Solved by Jacobi relaxation at reduced resolution (gyres are a
    large-scale feature; a coarse solve converges fast and upsamples with no
    visible loss of character), then the velocity is read off the converged
    streamfunction so it is exactly divergence-free -- no current can appear
    from nowhere or vanish into a sink."""
    wind_u, wind_v = wind_field(width, height)
    # curl(wind) = d(wind_v)/dx - d(wind_u)/dy. The bands are x-independent
    # by construction, so this reduces to -d(wind_u)/dy: exactly Sverdrup's
    # relation, that it is the CHANGE in the wind's push between latitude
    # bands (not the push itself) that spins up a gyre.
    dwu_dy = np.gradient(wind_u, axis=0)
    forcing = -dwu_dy

    factor = SOLVE_DOWNSAMPLE
    land_c = _downsample_bool_or(land_mask, factor) > 0.5
    # Downsample forcing by the same simple block-average as the land mask,
    # so both operate on the same coarse grid.
    ch, cw = land_c.shape
    ph, pw = ch * factor - height, cw * factor - width
    forcing_pad = np.pad(forcing, ((0, ph), (0, pw)), mode="edge")
    forcing_c = forcing_pad.reshape(ch, factor, cw, factor).mean(axis=(1, 3))

    psi = np.zeros((ch, cw), dtype=np.float64)
    ocean_c = ~land_c
    # dx^2 term folded into the forcing scale -- only the RELATIVE magnitude
    # of psi across the field matters (currents come from its gradient), not
    # its absolute units, so there is no real-world grid spacing to get right.
    for _ in range(SOLVE_ITERATIONS):
        up = np.vstack([psi[:1], psi[:-1]])
        down = np.vstack([psi[1:], psi[-1:]])
        left = np.roll(psi, 1, axis=1)
        right = np.roll(psi, -1, axis=1)
        psi_new = 0.25 * (up + down + left + right - forcing_c)
        psi = np.where(ocean_c, psi_new, 0.0)

    psi_full = _upsample(psi, height, width)
    psi_full = np.where(land_mask, 0.0, psi_full)

    # (u, v) = (dpsi/dy, -dpsi/dx) -- the rotated gradient, guaranteeing
    # div(u, v) == 0 to floating-point precision by construction.
    dpsi_dy = np.gradient(psi_full, axis=0)
    dpsi_dx_right = np.roll(psi_full, -1, axis=1) - psi_full
    dpsi_dx_left = psi_full - np.roll(psi_full, 1, axis=1)
    dpsi_dx = 0.5 * (dpsi_dx_right + dpsi_dx_left)
    u = dpsi_dy
    v = -dpsi_dx
    u = np.where(land_mask, 0.0, u)
    v = np.where(land_mask, 0.0, v)
    # Normalize to a sane, seed-independent magnitude range (~0..1) so
    # downstream consumers -- coastal carving's coefficients, trade's speed
    # cap -- can use fixed constants instead of re-deriving a scale per world.
    mag = np.hypot(u, v)
    peak = float(np.percentile(mag[~land_mask], 97)) if (~land_mask).any() else 1.0
    peak = peak or 1.0
    u, v = u / peak, v / peak

    # Clip the outlier tail. psi is hard-zeroed ON land, so the finite-
    # difference gradient AT a coastal cell (one neighbour real, one
    # neighbour clamped to exactly 0) is steeper than the smooth interior
    # flow it is estimating from -- a discretization artifact, not a real
    # current, and it lands exactly on the coastal cells coastal carving
    # reads. Measured on a real world: post-normalization magnitude should
    # sit within a few multiples of 1.0, and instead ran up to 15x at these
    # cells. Clipped rather than re-deriving a boundary-aware gradient
    # scheme, since a real strait squeezing a current to a few times the
    # open-ocean norm is itself a genuine, wanted effect -- only the
    # far tail is the artifact.
    mag2 = np.hypot(u, v)
    over = mag2 > CURRENT_MAG_CLIP
    scale = np.where(over, CURRENT_MAG_CLIP / np.maximum(mag2, 1e-9), 1.0)
    return u * scale, v * scale


# --- coastal carving --------------------------------------------------------
BAND_BLUR_RADIUS = 2       # cells; controls how wide the "coastal band" that
                          # carving is allowed to touch actually is
# Erosion is driven by the FLOW, not by noise: where the longshore current is
# fast it attacks the shore, and where its transport capacity RISES along its
# own path (a headland squeezes the streamlines, a channel mouth funnels them)
# it picks up material and carries it away -- cut. Where the capacity FALLS
# (a sheltered bay, the lee of a headland) it drops its load -- fill. The
# noise `detail` only decides WHERE within a favoured stretch the bite lands,
# so a coast reads as carved by the current, not by coincidence of noise.
ERODE_CURRENT = 0.015      # cut where the longshore current runs fast
ERODE_ACCEL = 0.18         # cut where the current accelerates along the coast
DEPOSE_SLACK = 0.18        # build where the current decelerates (spits, bars)
DEPOSE_ONSHORE = 0.04      # build where the current pushes onshore
CARVE_ITERATIONS = 3       # recompute currents against the refined coastline
                          # this many times, so a cut this pass can deepen
                          # (or a bar this pass built can grow) next pass --
                          # the compounding is what gives carved features
                          # their shape instead of a single uniform nudge
# Per-pass cap on how much any single cell's height may move. The gradient
# of current speed (the acceleration term) can spike at sharp coastline
# corners -- a discretization artifact, not a real current -- and uncapped it
# could excavate a whole coast in one pass. The cap bounds the damage while
# still letting a real strait or headland compound over the iterations.
CARVE_DELTA_CAP = 0.15

# The underwater shelf: how far out from the shore the sea floor is pulled up
# into a gentle ramp (the "erosion layer" a coast actually has -- the water
# slopes out over a beach and shelf instead of dropping straight to depth at
# the waterline). Depth grows linearly with distance from shore, influence
# fades to zero at SHELF_REACH cells out.
SHELF_REACH = 5
SHELF_SHALLOW = 0.05       # target depth (fraction of sea level) at the waterline
                           # itself; the first water cell (d=1) lands at
                           # SHALLOW + SLOPE = 0.15
SHELF_SLOPE = 0.10         # target depth added per cell of distance from shore


def _extend_currents_to_coast(u, v, land, width, height):
    """Diffuse the current field one cell INLAND across the coastline, so
    `along`/`cross` are meaningful at coastal LAND cells. solve_currents
    hard-zeros u/v on land (sea travel only ever samples ocean cells), but a
    coastline is a streamline -- the longshore current does not stop at the
    waterline -- and the carving term lives exactly at the coastline. Each
    coastal land cell adopts the mean of its ocean neighbours' currents; the
    band_weight falloff already confines the carving to the coastal band, so
    one cell inland is all the erosion term needs. Carving only; the returned
    cu/cv stored on the world stay zeroed on land."""
    u = u.copy()
    v = v.copy()
    ocean = ~land
    su = np.zeros_like(u)
    sv = np.zeros_like(v)
    cnt = np.zeros_like(land, dtype=np.float64)
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        if dx:
            nu = np.roll(u, -dx, axis=1)        # value at (x+dx, y)
            nv = np.roll(v, -dx, axis=1)
            no = np.roll(ocean, -dx, axis=1)
        else:
            nu = np.roll(u, -dy, axis=0)        # value at (x, y+dy)
            nv = np.roll(v, -dy, axis=0)
            no = np.roll(ocean, -dy, axis=0)
            # no wrap in y: kill the rolled edge row so the map's poles
            # don't see a neighbour from the other side
            if dy == 1:
                nu[-1] = nv[-1] = 0.0
                no[-1] = False
            else:
                nu[0] = nv[0] = 0.0
                no[0] = False
        su += np.where(no, nu, 0.0)
        sv += np.where(no, nv, 0.0)
        cnt += no
    adopt = (cnt > 0) & land
    u = np.where(adopt, su / np.maximum(cnt, 1.0), u)
    v = np.where(adopt, sv / np.maximum(cnt, 1.0), v)
    return u, v


def _distance_from_land(land, width, height, max_d):
    """4-connected distance from land for every cell, wrap-aware in x (the
    seam is ocean, so distance legitimately crosses it), clipped to max_d.
    Iterative numpy dilation -- cheap for the small reach the shelf needs."""
    dist = np.full(land.shape, float(max_d + 1), dtype=np.float64)
    dist[land] = 0.0
    for _ in range(max_d):
        nxt = dist.copy()
        nxt = np.minimum(nxt, np.roll(dist, 1, axis=1) + 1.0)
        nxt = np.minimum(nxt, np.roll(dist, -1, axis=1) + 1.0)
        nxt = np.minimum(nxt, np.vstack([dist[1:], dist[-1:]]) + 1.0)  # y+1,
        nxt = np.minimum(nxt, np.vstack([dist[:1], dist[:-1]]) + 1.0)  # y-1
        dist = nxt
    return dist


def apply_erosion_shelf(height_field, land, sea_level, width, height):
    """Pull the near-shore sea floor up into a smooth ramp -- the shelf a
    coast actually has, so water shallows out gradually from the beach instead
    of dropping straight to depth at the waterline. Target depth grows
    linearly with distance from shore; influence fades smoothly to zero at
    SHELF_REACH cells out, where the natural (current-carved) floor takes
    over. Only ever raises OCEAN heights and never past sea level, so it can
    neither drown land nor build new land -- it shapes the water, not the
    coastline. Called by worldgen on the final layout (carved or not) after
    the landmass checks, so every world gets the shelf even when a seed's
    carving was rejected."""
    d = _distance_from_land(land, width, height, SHELF_REACH + 1)
    ocean = ~land
    # 1 at the waterline (d=1), 0 at SHELF_REACH; land is masked out anyway.
    w = np.clip((SHELF_REACH + 1.0 - d) / SHELF_REACH, 0.0, 1.0)
    w = np.where(ocean, w, 0.0)
    target_depth = SHELF_SHALLOW + SHELF_SLOPE * d
    target_h = sea_level * (1.0 - np.minimum(1.0, target_depth))
    return height_field + (target_h - height_field) * w


def _box_blur(field, radius):
    out = field.astype(np.float64).copy()
    h, w = field.shape
    for _ in range(radius):
        out = (out + np.roll(out, 1, axis=1) + np.roll(out, -1, axis=1)
              + np.vstack([out[:1], out[:-1]]) + np.vstack([out[1:], out[-1:]])) / 5.0
    return out


def carve_coastline(height_field, land_mask, sea_level, width, height, seed,
                    iterations=CARVE_ITERATIONS):
    """Reshape `height_field` near the coast using wind-driven currents, and
    return (new_height, new_land_mask, current_u, current_v) -- the last two
    from the FINAL iteration's solve, for trade/rendering to reuse rather
    than re-solving.

    Runs the wind -> current -> erosion loop `iterations` times, each pass
    against the PREVIOUS pass's coastline: a current that starts carving a
    strait deepens it next pass (more current squeezes through a narrower
    gap, which was already true of it before this pass touched it), and a
    current that starts depositing a bar keeps building on the same bar --
    the compounding is what makes a carved feature read as a real strait or
    a real spit rather than a single undifferentiated nudge along the whole
    coast."""
    h = height_field.copy()
    land = land_mask.copy()
    cu = cv = None
    for i in range(max(1, iterations)):
        cu, cv = solve_currents(land, width, height)
        # The flow is zeroed on land by solve_currents (travel only samples
        # ocean), but the coastline is a streamline: extend the current a
        # couple of cells inland so `along`/`cross` are nonzero AT the coast,
        # which is where the erosion term has to bite. Without this the
        # erosion channel is dead and carving can only ever silt up.
        eu, ev = _extend_currents_to_coast(cu, cv, land, width, height)

        land_f = land.astype(np.float64)
        land_blur = _box_blur(land_f, BAND_BLUR_RADIUS)
        band_weight = 4.0 * land_blur * (1.0 - land_blur)   # peaks at the coast

        gy = np.vstack([land_blur[1:] - land_blur[:-1],
                        (land_blur[-1:] - land_blur[-2:-1])])
        gx = np.roll(land_blur, -1, axis=1) - np.roll(land_blur, 1, axis=1)
        gmag = np.hypot(gx, gy)
        gmag_safe = np.where(gmag > 1e-9, gmag, 1.0)
        # land_blur is high ON land, low at sea -- its gradient points from
        # sea toward land (inward); the coastal OUTWARD normal is the
        # negation of that, normalized.
        nx, ny = -gx / gmag_safe, -gy / gmag_safe
        tx, ty = -ny, nx                      # tangent: normal rotated 90 deg

        along = eu * tx + ev * ty             # signed longshore current speed
        cross = eu * nx + ev * ny             # + = flowing out to sea (offshore)

        # Transport-capacity divergence: d|along|/ds along the FLOW direction.
        # Where the longshore current accelerates along its own path it has
        # spare capacity to pick material up (erode a headland, deepen a
        # channel mouth); where it decelerates it must drop its load (build a
        # bar, silt a bay). This is what makes the carving follow the flow
        # instead of a noise field.
        al = np.abs(along)
        dal_dx = 0.5 * (np.roll(al, -1, axis=1) - np.roll(al, 1, axis=1))
        dal_dy = np.gradient(al, axis=0)
        speed = np.hypot(eu, ev)
        us = np.where(speed > 1e-9, eu / np.maximum(speed, 1e-9), 0.0)
        vs = np.where(speed > 1e-9, ev / np.maximum(speed, 1e-9), 0.0)
        dq_ds = dal_dx * us + dal_dy * vs

        detail = _coast_detail_noise(width, height, seed + 5000 + i)

        erosion = (ERODE_CURRENT * al
                   + ERODE_ACCEL * np.maximum(0.0, dq_ds)) * detail
        deposition = (DEPOSE_SLACK * np.maximum(0.0, -dq_ds)
                      + DEPOSE_ONSHORE * np.maximum(0.0, -cross)) * (1.0 - detail)
        delta = band_weight * (deposition - erosion)
        delta = np.clip(delta, -CARVE_DELTA_CAP, CARVE_DELTA_CAP)

        h = h + delta
        land = h > sea_level

    # The shelf is NOT applied here: worldgen applies it to whichever layout
    # survives its landmass checks (see apply_erosion_shelf), so a seed whose
    # carving gets rejected still gets the shallow-water coastline.

    # `cu`/`cv` were zeroed against the land mask as it stood BEFORE this
    # final pass's own delta was applied, but a handful of coastal-band
    # cells just flipped land<->sea in that same pass (that's the carving
    # actually happening). Re-zero against the mask this function is about
    # to hand back, so nothing downstream -- trade routing, streamline
    # rendering -- ever sees a current value attached to a cell now called
    # land, or a hole where a cell just became ocean.
    cu = np.where(land, 0.0, cu)
    cv = np.where(land, 0.0, cv)
    return h, land, cu, cv


def _coast_detail_noise(width, height, seed):
    """Per-cell [0,1] noise deciding exactly where, within a current-favoured
    stretch of coast, the carving actually bites -- without this, a whole
    bay would erode or deposit UNIFORMLY along its length, which reads as
    "coastline breathing in and out," not as the individual inlets, points
    and bars a real current-carved coast has."""
    from app.world.worldgen import _periodic_octaves
    octaves = _periodic_octaves(width, [(0.045, 1.0), (0.10, 0.5)])
    raw = noise.fbm_grid(width, height, seed, octaves)
    lo, hi = raw.min(), raw.max()
    return (raw - lo) / ((hi - lo) or 1.0)


# --- trade / ship speed -----------------------------------------------------
# How much a route's travel cost can change from riding or fighting a
# current -- +/-30%, an explicit design choice: strong enough that routing
# WITH a current is a real, visible decision, not so strong that the current
# field swamps the terrain-based sea cost it's layered on top of.
CURRENT_SPEED_CAP = 0.30


def travel_cost_multiplier(current_u, current_v, x, y, dx, dy):
    """Cost multiplier for moving in direction (dx, dy) through cell (x, y).
    1.0 with no current; as low as 1-CURRENT_SPEED_CAP running with a strong
    current, as high as 1+CURRENT_SPEED_CAP fighting one. `(dx, dy)` need not
    be normalized -- only its direction is used."""
    dmag = math_hypot(dx, dy)
    if dmag < 1e-9:
        return 1.0
    u, v = current_u[y][x], current_v[y][x]
    cmag = math_hypot(u, v)
    if cmag < 1e-9:
        return 1.0
    alignment = (dx * u + dy * v) / (dmag * cmag)   # -1..1
    return 1.0 - CURRENT_SPEED_CAP * alignment * min(1.0, cmag)


def math_hypot(a, b):
    return (a * a + b * b) ** 0.5


def sea_edge_cost_fn(world):
    """An edge_cost_fn for _path_dijkstra (see worldgen.py) that prices a sea
    step by how well it rides `world`'s current field -- the thing that
    actually makes "trading networks can use currents to ship goods quicker"
    a real, routeable effect rather than a number nobody's path ever sees.

    None on a world with no current field (old saves, or a sandbox world
    generated before currents existed) returns the identity function rather
    than a per-call None check -- one branch here instead of one in every
    step of every sea pathfind."""
    # getattr, not a direct attribute access: a world SAVED before this
    # feature existed has no current_u/current_v attribute at all -- pickle
    # restores an object's __dict__ directly and never re-runs __init__, so
    # World.__init__'s own `self.current_u = None` default is never applied
    # to an old save on load. A direct `world.current_u` here would raise
    # AttributeError the first time any old save tried to route a sea trade
    # or move a ship -- caught by dev/currents round-trip testing, not by
    # inspection, which is exactly the class of bug that inspection misses.
    cu = getattr(world, "current_u", None)
    cv = getattr(world, "current_v", None)
    if cu is None or cv is None:
        return lambda cur, nb: 1.0
    width = world.w

    def edge_cost(cur, nb):
        dx = wrap.dx_wrap(cur[0], nb[0], width)
        dy = nb[1] - cur[1]
        return travel_cost_multiplier(cu, cv, nb[0], nb[1], dx, dy)

    return edge_cost


# --- streamline precomputation for rendering --------------------------------
# Traced ONCE at world generation and stored on the world (see
# app/world/worldgen.py's call into build_streamlines), not recomputed per
# frame by either renderer -- integrating a vector field is cheap once, and
# every renderer wants the exact same lines.
STREAMLINE_SPACING = 42       # cells between seed points on the tracing grid
STREAMLINE_STEP = 6.0         # cells advanced per integration step
STREAMLINE_MAX_STEPS = 90
STREAMLINE_MIN_SPEED = 0.12   # stop tracing once the current this faint


def build_streamlines(current_u, current_v, land_mask, width, height):
    """[[(x, y), ...], ...] -- one polyline per seed point, each following
    the current downstream (simple RK2 integration, wrap-aware in x) until
    it runs out of open water, fades below STREAMLINE_MIN_SPEED, or leaves
    the map in y. Seeded on a coarse regular grid over ocean cells only;
    land is never fully surrounded by seeds so no line is drawn wandering
    over a continent with nothing under it."""
    cu = np.asarray(current_u)
    cv = np.asarray(current_v)

    def sample(x, y):
        xi = int(x) % width
        yi = min(max(int(y), 0), height - 1)
        return float(cu[yi][xi]), float(cv[yi][xi])

    lines = []
    for sy in range(STREAMLINE_SPACING // 2, height, STREAMLINE_SPACING):
        for sx in range(STREAMLINE_SPACING // 2, width, STREAMLINE_SPACING):
            if land_mask[sy][sx]:
                continue
            u0, v0 = sample(sx, sy)
            if math_hypot(u0, v0) < STREAMLINE_MIN_SPEED:
                continue
            pts = [(float(sx), float(sy))]
            x, y = float(sx), float(sy)
            for _ in range(STREAMLINE_MAX_STEPS):
                u, v = sample(x, y)
                speed = math_hypot(u, v)
                if speed < STREAMLINE_MIN_SPEED:
                    break
                # midpoint (RK2) step -- noticeably smoother curvature than
                # forward Euler at the same step count, which matters here
                # since a gyre's whole visual point is that it curves.
                mx = x + (u / speed) * STREAMLINE_STEP * 0.5
                my = y + (v / speed) * STREAMLINE_STEP * 0.5
                if not (0 <= my < height):
                    break
                mu, mv = sample(mx, my)
                mspeed = math_hypot(mu, mv)
                if mspeed < 1e-6:
                    break
                nx = x + (mu / mspeed) * STREAMLINE_STEP
                ny = y + (mv / mspeed) * STREAMLINE_STEP
                if not (0 <= ny < height) or land_mask[min(max(int(ny), 0),
                                                           height - 1)][int(nx) % width]:
                    break
                if nx < 0 or nx >= width:
                    # Crossed the map's own seam. A polyline connecting a
                    # point right before it to one right after would be a
                    # long straight line spanning nearly the whole map width
                    # -- not what a renderer drawing consecutive points as
                    # segments should ever see. End this piece and start a
                    # fresh one from the wrapped position instead of
                    # continuing across the jump.
                    if len(pts) >= 3:
                        lines.append(pts)
                    x, y = nx % width, ny
                    pts = [(x, y)]
                    continue
                x, y = nx, ny
                pts.append((x, y))
            if len(pts) >= 3:
                lines.append(pts)
    return lines
