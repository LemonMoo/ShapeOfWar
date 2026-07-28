"""Registry of soldier "sprites" drawn from primitive shapes on a Tk canvas.

Register a shape once and any unit type can reference it by name — no art
assets needed. A draw function takes (canvas, x, y, r, fill, tag) and creates
one canvas item.
"""
_shapes = {}


def register_shape(name, draw_fn):
    _shapes[name] = draw_fn


def draw_shape(canvas, name, x, y, r, fill, tag="unit"):
    fn = _shapes.get(name, _shapes["circle"])
    return fn(canvas, x, y, r, fill, tag)


# --- Built-in shapes -------------------------------------------------------
def _circle(canvas, x, y, r, fill, tag):
    return canvas.create_oval(x - r, y - r, x + r, y + r,
                              fill=fill, outline="", tags=tag)


def _square(canvas, x, y, r, fill, tag):
    return canvas.create_rectangle(x - r, y - r, x + r, y + r,
                                   fill=fill, outline="", tags=tag)


def _triangle(canvas, x, y, r, fill, tag):
    return canvas.create_polygon(x, y - r, x + r, y + r, x - r, y + r,
                                 fill=fill, outline="", tags=tag)


def _diamond(canvas, x, y, r, fill, tag):
    return canvas.create_polygon(x, y - r, x + r, y, x, y + r, x - r, y,
                                 fill=fill, outline="", tags=tag)


register_shape("circle", _circle)
register_shape("square", _square)
register_shape("triangle", _triangle)
register_shape("diamond", _diamond)


def _star(canvas, x, y, r, fill, tag):
    """An eight-pointed star -- the Commander's mark.

    Deliberately unlike any soldier shape on the field: circles, squares,
    triangles and diamonds are all convex blobs that read the same at a
    glance, especially at the sizes armies of hundreds get drawn at. A spiked
    silhouette is identifiable even when small, and the Commander is drawn at
    several times a soldier's radius on top of that (see UNIT_TYPES)."""
    import math
    pts = []
    for i in range(16):
        ang = math.pi * i / 8 - math.pi / 2
        rad = r if i % 2 == 0 else r * 0.45
        pts.extend((x + math.cos(ang) * rad, y + math.sin(ang) * rad))
    return canvas.create_polygon(*pts, fill=fill, outline="", tags=tag)


register_shape("star", _star)
