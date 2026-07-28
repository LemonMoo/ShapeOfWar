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
