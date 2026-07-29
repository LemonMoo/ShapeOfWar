"""Vectorised value noise -- a numpy version of worldgen._vhash/_vnoise that
samples an ENTIRE grid in one call instead of once per cell.

Kept as its own module rather than folded into worldgen.py because two
different systems need it: the height field itself (worldgen.py) and the
per-cell "where exactly does the current bite" detail noise that makes
current-driven coastal carving look textured rather than uniform
(currents.py). Both want the same primitive; neither should duplicate it.

_vhash_np is bit-for-bit the same hash as worldgen._vhash -- verified in
dev/coastline_metrics.py's self-check -- so switching a call site from the
scalar sampler to this one changes nothing about the noise's CHARACTER, only
how fast it is to evaluate. The 4-octave height field this replaced was
costing ~15s of every ~20s world generation; vectorised, the same octaves
cost well under a second, which is what pays for the extra work currents.py
does afterward without world generation becoming noticeably slower overall.
"""
import numpy as np

_MASK32 = np.int64(0xFFFFFFFF)


def vhash_np(ix, iy, seed, period_x=None):
    """Vectorised worldgen._vhash. `ix`, `iy` are numpy integer arrays
    (any shape, broadcastable together); returned array matches their
    broadcast shape, values in [0, 1).

    int64 throughout is required, not a style choice: ix*73856093 alone
    overflows a 32-bit int for any ix beyond a few hundred, and numpy's
    default integer width on Windows is 32-bit (C `long`), unlike Python's
    arbitrary-precision int that the scalar version relies on implicitly."""
    ix = ix.astype(np.int64)
    iy = iy.astype(np.int64)
    if period_x is not None:
        ix = np.mod(ix, np.int64(period_x))
    n = (ix * np.int64(73856093)) ^ (iy * np.int64(19349663)) ^ np.int64(seed * 83492791)
    n &= _MASK32
    n = ((n ^ (n >> 13)) * np.int64(1274126177)) & _MASK32
    n ^= (n >> 16)
    return (n & np.int64(0xFFFF)) / 0xFFFF


def vnoise_grid(width, height, freq_x, freq_y, seed, period_x,
                 warp_x=None, warp_y=None):
    """Value noise sampled at every (x, y) in a width x height grid, at the
    given per-axis frequency. `period_x` must be the integer lattice period
    from worldgen._periodic_freq(width, freq) -- the caller already needs it
    for the scalar path's seam-safe wrapping, so it is required here rather
    than silently recomputed differently.

    `warp_x`/`warp_y`, if given, are (height, width) arrays added to the
    sample position in CELL units before hashing -- domain warping (see
    worldgen.py's height-field comment for why this is what breaks the
    isotropic "sponge" look of unwarped value noise)."""
    xs = np.arange(width, dtype=np.float64)
    ys = np.arange(height, dtype=np.float64)
    gx, gy = np.meshgrid(xs, ys)          # (height, width), gx[y,x] == x
    if warp_x is not None:
        gx = gx + warp_x
    if warp_y is not None:
        gy = gy + warp_y

    sx_pos = gx * freq_x
    sy_pos = gy * freq_y
    x0 = np.floor(sx_pos)
    y0 = np.floor(sy_pos)
    fx = sx_pos - x0
    fy = sy_pos - y0
    sx = fx * fx * (3 - 2 * fx)
    sy = fy * fy * (3 - 2 * fy)

    ix0 = x0.astype(np.int64)
    iy0 = y0.astype(np.int64)
    v00 = vhash_np(ix0, iy0, seed, period_x)
    v10 = vhash_np(ix0 + 1, iy0, seed, period_x)
    v01 = vhash_np(ix0, iy0 + 1, seed, period_x)
    v11 = vhash_np(ix0 + 1, iy0 + 1, seed, period_x)
    a = v00 + (v10 - v00) * sx
    b = v01 + (v11 - v01) * sx
    return a + (b - a) * sy


def fbm_grid(width, height, seed, periodic_octaves, warp_x=None, warp_y=None):
    """Sum of vnoise_grid over a set of octaves -- the vectorised counterpart
    of the scalar sum(amp * _vnoise(...) for ...) loop. `periodic_octaves` is
    worldgen._periodic_octaves(width, octaves)'s own output, reused rather
    than recomputed so both paths agree on exactly which lattice periods
    are in play."""
    total = np.zeros((height, width), dtype=np.float64)
    for (eff_freq, period_x, freq, amp) in periodic_octaves:
        total += amp * vnoise_grid(width, height, eff_freq, freq, seed,
                                   period_x, warp_x, warp_y)
    return total
