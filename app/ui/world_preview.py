"""A small picture of a whole world, for the New Game screen.

This is not the map renderer. MapView draws at full resolution with fog,
overlays, five view modes and per-region shading, and lives in a class the
setup screen has no business constructing. What the New Game screen needs is
much smaller: is that a good-looking landmass, where do I start, and who is
crowded up against me.

So this samples the world grid on a stride and paints the political read only --
water, unclaimed land, each realm's colour, and a ring around your capital. It
deliberately shares MapView's palette constants rather than picking its own, so
the preview and the map you land in are recognisably the same world.
"""
import math

from PIL import Image, ImageDraw

from app.ui.map_view import (_LAKE_RGB, _OCEAN_DEEP, _OCEAN_SHALLOW, _RIVER_RGB,
                             _UNCLAIMED_RGB, _hex_to_rgb)

OCEAN = -1


def render_world(world, size=(360, 216), player_idx=None, mark_player=True):
    """A political thumbnail of `world` at roughly `size`, as a PIL RGB image.

    Aspect is taken from the world, not from `size`: worlds come in different
    proportions (see the size presets on the New Game screen) and stretching one
    to fit a fixed box would misrepresent the shape of the very thing the player
    is being asked to judge."""
    w, h = world.w, world.h
    box_w, box_h = size
    scale = min(box_w / w, box_h / h)
    out_w = max(1, int(w * scale))
    out_h = max(1, int(h * scale))

    # One sample per output pixel. At thumbnail size that is a few tens of
    # thousands of lookups -- cheap enough to redraw on every colour click,
    # which is what makes the preview feel live rather than staged.
    colors = [_hex_to_rgb(n.color) for n in world.factions]
    owner, height_grid, sea = world.owner, world.height, world.sea_level
    lakes, rivers = world.lake_cells, world.river_cells
    px = []
    for oy in range(out_h):
        y = min(h - 1, int(oy / scale))
        row_owner = owner[y]
        row_height = height_grid[y]
        for ox in range(out_w):
            x = min(w - 1, int(ox / scale))
            o = row_owner[x]
            if o == OCEAN:
                depth = max(0.0, min(1.0, (sea - row_height[x]) / (sea or 1)))
                px.append(tuple(int(_OCEAN_DEEP[j]
                                    + (_OCEAN_SHALLOW[j] - _OCEAN_DEEP[j])
                                    * (1 - depth)) for j in range(3)))
            elif (x, y) in lakes:
                px.append(_LAKE_RGB)
            elif (x, y) in rivers:
                px.append(_RIVER_RGB)
            elif o >= 0:
                px.append(colors[o] if o < len(colors) else _UNCLAIMED_RGB)
            else:
                # Unclaimed land, lifted a little by elevation so the shape of
                # the continent is still legible under a single flat tone.
                relief = (row_height[x] - sea) / (1 - sea) if sea < 1 else 0.0
                lift = 1.0 + 0.55 * max(0.0, min(1.0, relief))
                px.append(tuple(min(255, int(c * lift)) for c in _UNCLAIMED_RGB))

    img = Image.new("RGB", (out_w, out_h))
    img.putdata(px)

    if mark_player:
        idx = world.player_faction_idx if player_idx is None else player_idx
        if idx is not None and 0 <= idx < len(world.factions):
            _mark_capital(img, world, idx, scale)
    return img


def _mark_capital(img, world, idx, scale):
    """A bright ring where the player starts.

    A thumbnail of fourteen realms is a lot of colour, and "which one is me" is
    the single question the preview exists to answer -- a ring answers it
    faster than hunting for a hue."""
    capital = (world.factions[idx].meta or {}).get("capital")
    if not capital:
        return
    cx, cy = capital[0] * scale, capital[1] * scale
    draw = ImageDraw.Draw(img)
    r = max(4.0, min(img.size) * 0.035)
    # Dark ring under a light one, so it reads against both a pale realm colour
    # and deep ocean without needing to know which it landed on.
    draw.ellipse([cx - r - 1, cy - r - 1, cx + r + 1, cy + r + 1],
                 outline=(10, 12, 18), width=3)
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255), width=2)


def land_summary(world, idx):
    """One line about the starting position: how much of it is workable, and
    how crowded it is. The map shows shape; this says whether it is any good."""
    nation = world.factions[idx]
    meta = nation.meta or {}
    regions = len(meta.get("regions", ()))
    fertility = meta.get("fertility", 0)
    # Nearest rival, as a fraction of the map's width, from realm centres.
    cx, cy = nation.center
    nearest = None
    for i, other in enumerate(world.factions):
        if i == idx:
            continue
        ox, oy = other.center
        d = math.hypot((ox - cx) * world.w, (oy - cy) * world.h)
        if nearest is None or d < nearest[0]:
            nearest = (d, other)
    if nearest is None:
        return f"{regions} starting region(s) · {fertility}% fertility"
    d, other = nearest
    far = d / max(1, world.w)
    room = "isolated" if far > 0.28 else ("elbow room" if far > 0.16 else "crowded")
    return (f"{regions} starting region(s) · {fertility}% avg fertility · "
            f"{room} — nearest rival is {other.name}")
