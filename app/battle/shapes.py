"""Registry of soldier "sprites" drawn from primitive shapes on a Tk canvas.

Register a shape once and any unit type can reference it by name — no art
assets needed. A draw function takes (canvas, x, y, r, fill, tag) and creates
one canvas item.
"""
import math

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


# Two more, added with the species signature units: a roster where Humans field
# square Archers AND square Standard Bearers, or Goblins diamond Assassins AND
# diamond Sappers, cannot be read at a glance -- and telling your own units
# apart mid-battle is most of what these sprites are for.
def _hexagon(canvas, x, y, r, fill, tag):
    pts = []
    for i in range(6):
        a = math.pi / 6.0 + i * math.pi / 3.0
        pts += [x + r * math.cos(a), y + r * math.sin(a)]
    return canvas.create_polygon(*pts, fill=fill, outline="", tags=tag)


def _chevron(canvas, x, y, r, fill, tag):
    """A downward arrowhead -- an upside-down triangle with a notched base, so
    it never reads as a Cavalry triangle even at three pixels across."""
    return canvas.create_polygon(x, y + r, x + r, y - r, x, y - r * 0.35,
                                 x - r, y - r, fill=fill, outline="", tags=tag)


register_shape("circle", _circle)
register_shape("square", _square)
register_shape("triangle", _triangle)
register_shape("diamond", _diamond)
register_shape("hexagon", _hexagon)
register_shape("chevron", _chevron)
