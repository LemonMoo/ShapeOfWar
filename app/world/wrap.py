"""Horizontal (east-west) world wrap: the map's x-axis is a cylinder, not a
flat line -- x=width-1 is a real neighbor of x=0, the same way any other
adjacent pair of columns is. y is NEVER wrapped, only x (no north-south
wrap, no true globe/sphere topology) -- every function below reflects that
asymmetry explicitly rather than taking a generic "wrap both axes" flag.

Wrapping is unconditional: there is no non-wrap mode, no flag, nothing to
branch on. Every other module that reasons about map coordinates -- and
there are roughly twenty such call sites across worldgen.py, commander.py,
construction.py, trade.py, expansion.py, resources.py, territory.py, and
vision.py -- should route through here instead of doing raw (x1-x0) or
0<=nx<width arithmetic directly, so the wrap-around behavior lives in
exactly one place.

All functions take width/height explicitly (never a World object) so this
module stays a dependency-free leaf: importable from anywhere without any
circular-import risk, and trivially testable in isolation.
"""
import math


def wrap_x(x, width):
    """Normalize any raw x (negative, or >= width) back into [0, width)."""
    return x % width


def dx_wrap(x0, x1, width):
    """Signed shortest x-delta from x0 to x1, accounting for wrap -- e.g. on
    a width=100 map, dx_wrap(2, 98, 100) == -4 (going left through the seam
    is shorter than going right). Result is always in (-width/2, width/2]."""
    d = (x1 - x0) % width
    if d > width / 2:
        d -= width
    return d


def delta_xy(p0, p1, width):
    """(dx, dy) between two (x, y) points, wrap-aware on x only -- the one
    function every straight-line distance/direction call site in the
    codebase should route through instead of a raw (p1[0]-p0[0],
    p1[1]-p0[1]) subtraction."""
    return dx_wrap(p0[0], p1[0], width), p1[1] - p0[1]


def dist2_wrap(p0, p1, width):
    """Squared wrap-aware distance -- drop-in replacement for the
    (p[0]-s[0])**2+(p[1]-s[1])**2 pattern used all over worldgen.py/
    territory.py/construction.py for spacing/radius checks where the exact
    distance doesn't matter, only the comparison."""
    dx, dy = delta_xy(p0, p1, width)
    return dx * dx + dy * dy


def dist_wrap(p0, p1, width):
    """Real (non-squared) wrap-aware distance -- for the call sites that feed
    the value into something nonlinear (e.g. an exp() falloff) rather than
    just comparing it, where dist2_wrap's squared form won't do."""
    dx, dy = delta_xy(p0, p1, width)
    return math.hypot(dx, dy)


def bbox_span_wrap(xa, xb, width, pad):
    """The x-values (already wrapped into [0, width)) a Dijkstra-style
    search's cellset should cover to connect xa and xb with `pad` extra
    cells of slack on each side -- replacement for the
    sorted((a.x, b.x)) + clamp-pad pattern duplicated across commander.py's
    _bbox_cellset/_ocean_cellset, construction.py's _path_between, and
    trade.py's _land_path_between/_capital_sea_path.

    Two candidate spans are considered: the direct span between xa and xb,
    and the around-the-seam span (going the other way, through x=0/width) --
    whichever has the smaller total width wins, since that's the side any
    reasonable path would actually take. Returns a list of x-values (not a
    range/slice) because the winning span can wrap through 0, so callers
    must iterate the returned list rather than `for x in range(x0, x1)`."""
    lo, hi = min(xa, xb), max(xa, xb)
    # Both endpoints are inclusive, and the two arcs share them, so their
    # unpadded lengths are (hi-lo+1) and (width-(hi-lo)+1) respectively --
    # NOT a simple complement of each other (getting this wrong silently
    # produces a seam span that's short by one cell and drops an endpoint).
    direct_len = (hi - lo + 1) + 2 * pad
    wrap_len = (width - (hi - lo) + 1) + 2 * pad

    if direct_len <= wrap_len:
        x0 = max(0, lo - pad)
        x1 = min(width, hi + pad + 1)
        return list(range(x0, x1))

    # Around-the-seam: cover [hi-pad, width) then [0, lo+pad], wrapped.
    start = wrap_x(hi - pad, width)
    count = min(wrap_len, width)
    return [wrap_x(start + i, width) for i in range(count)]


def walk_line_wrap(p0, p1, width):
    """Every integer cell touched by a straight parametric walk from p0 to
    p1, taking the wrap-aware (shortest) x direction -- replacement for
    vision.py's _walk_reveal, so a revealed line that's shorter going
    through the seam (e.g. a ship's vision sweep near x=0/width-1) is
    walked that way instead of failing to represent the wrap at all.
    Step count matches the straight-line cell distance, same granularity
    _walk_reveal already used."""
    dx, dy = delta_xy(p0, p1, width)
    steps = max(abs(dx), abs(dy), 1)
    cells = []
    for i in range(steps + 1):
        t = i / steps
        x = wrap_x(round(p0[0] + dx * t), width)
        y = round(p0[1] + dy * t)
        cells.append((x, y))
    return cells
