"""GPU battle renderer: the battlefield drawn by the graphics card.

Why this exists
---------------
The Tk canvas renderer (see battle_view.render) recreates every canvas item
every frame -- `delete("all")` then one item per soldier, plus two more for its
sword and shield. That is CPU work in Tk's C layer scaling linearly with army
size, and it is why per-soldier equipment had to be switched off past 160 living
units: at that point the glyphs alone were ~80% of a frame.

Here the whole battlefield is ONE draw call. Every soldier, every weapon, every
arrow and spark is an instance of the same unit quad; the GPU expands them.
Cost on the CPU is building one flat float array per frame, and cost on the GPU
is essentially flat until many tens of thousands of instances. That removes the
detail cutoff entirely: kit is drawn at any army size.

Design
------
* One sampler2DArray holding every sprite as a WHITE mask (see _build_atlas).
  Colour comes from the per-instance tint, so one texture serves every faction
  and there is no atlas UV arithmetic -- the layer index IS the sprite id.
* One instance buffer, rebuilt each frame: position, size, rotation, tint,
  sprite layer, alpha. Ten floats per thing on screen.
* A plain white SQUARE layer (LAYER_SOLID) doubles as the primitive for health
  bars, order cues and selection boxes, so untextured rectangles need no second
  shader.

The renderer never mutates the battle -- it only reads it -- so it is safe to
swap with the canvas path at any time, and battle_view falls back to the canvas
automatically if a GL context cannot be created (see BattleView._make_viewport).
"""
import math

import numpy as np
from PIL import Image, ImageDraw

_HAVE_GL = True
try:
    import moderngl
    from pyopengltk import OpenGLFrame
except Exception:            # no GL libraries installed at all
    _HAVE_GL = False
    OpenGLFrame = object


def gl_available():
    """Whether the GL libraries imported. A context can still fail to create
    later (no driver, remote session); battle_view handles that separately."""
    return _HAVE_GL


# --- sprite atlas -------------------------------------------------------------
_TILE = 64            # px per sprite layer; plenty for soldiers a few px across
LAYER_CIRCLE = 0
LAYER_SQUARE = 1
LAYER_TRIANGLE = 2
LAYER_DIAMOND = 3
LAYER_SOLID = 4       # plain filled square -- bars, cues, boxes
LAYER_RING = 5        # hollow circle -- selection, block sparks
LAYER_SWORD = 6
LAYER_SHIELD = 7
LAYER_DAGGER = 8
# Appended at the END with the species signature units, so every constant above
# keeps the index it already had.
LAYER_HEXAGON = 9
LAYER_CHEVRON = 10
_LAYER_COUNT = 11

# Battle shape names (app/battle/shapes.py) -> atlas layer.
SHAPE_LAYER = {
    "circle": LAYER_CIRCLE,
    "square": LAYER_SQUARE,
    "triangle": LAYER_TRIANGLE,
    "diamond": LAYER_DIAMOND,
    "hexagon": LAYER_HEXAGON,
    "chevron": LAYER_CHEVRON,
}

_FLOATS_PER_INSTANCE = 10     # pos2 size2 rot1 color3 layer1 alpha1


def _build_atlas():
    """Every sprite as a white alpha mask, stacked into one array texture.

    Drawn at 4x and downsampled: these are a handful of pixels across on screen
    and hard edges alias badly at that size, so the supersample is what makes a
    soldier read as a round body rather than a lump.
    """
    ss = 4
    n = _TILE * ss
    layers = []

    def blank():
        img = Image.new("RGBA", (n, n), (255, 255, 255, 0))
        return img, ImageDraw.Draw(img)

    W = (255, 255, 255, 255)
    pad = n * 0.06

    img, d = blank(); d.ellipse([pad, pad, n - pad, n - pad], fill=W)
    layers.append(img)                                          # circle
    img, d = blank(); d.rectangle([pad, pad, n - pad, n - pad], fill=W)
    layers.append(img)                                          # square
    img, d = blank()
    d.polygon([(n / 2, pad), (n - pad, n - pad), (pad, n - pad)], fill=W)
    layers.append(img)                                          # triangle
    img, d = blank()
    d.polygon([(n / 2, pad), (n - pad, n / 2), (n / 2, n - pad), (pad, n / 2)],
              fill=W)
    layers.append(img)                                          # diamond
    img, d = blank(); d.rectangle([0, 0, n, n], fill=W)
    layers.append(img)                                          # solid
    img, d = blank()
    d.ellipse([pad, pad, n - pad, n - pad], outline=W, width=int(n * 0.09))
    layers.append(img)                                          # ring
    # Sword: a blade up the tile with a crossguard, pointing -Y (rotation 0 is
    # "up"), so the instance rotation can just be the facing angle.
    img, d = blank()
    d.rectangle([n * 0.44, n * 0.06, n * 0.56, n * 0.78], fill=W)
    d.rectangle([n * 0.28, n * 0.72, n * 0.72, n * 0.84], fill=W)
    layers.append(img)                                          # sword
    img, d = blank()
    d.ellipse([n * 0.12, n * 0.06, n * 0.88, n * 0.94], fill=W)
    layers.append(img)                                          # shield
    img, d = blank()
    d.rectangle([n * 0.42, n * 0.24, n * 0.58, n * 0.74], fill=W)
    d.rectangle([n * 0.30, n * 0.70, n * 0.70, n * 0.80], fill=W)
    layers.append(img)                                          # dagger
    img, d = blank()
    d.regular_polygon((n / 2, n / 2, n / 2 - pad), 6, rotation=30, fill=W)
    layers.append(img)                                          # hexagon
    img, d = blank()
    d.polygon([(n / 2, n - pad), (n - pad, pad), (n / 2, n * 0.42), (pad, pad)],
              fill=W)
    layers.append(img)                                          # chevron

    assert len(layers) == _LAYER_COUNT
    small = [im.resize((_TILE, _TILE), Image.LANCZOS) for im in layers]
    return b"".join(im.tobytes() for im in small)


_VERTEX_SHADER = """
#version 330
uniform vec2 u_viewport;
in vec2 in_vert;
in vec2 in_pos;
in vec2 in_size;
in float in_rot;
in vec3 in_color;
in float in_layer;
in float in_alpha;
out vec2 v_uv;
out vec3 v_color;
out float v_layer;
out float v_alpha;
void main() {
    vec2 p = in_vert * in_size;
    float c = cos(in_rot), s = sin(in_rot);
    p = vec2(p.x * c - p.y * s, p.x * s + p.y * c) + in_pos;
    // Battle space is pixels with +Y down (canvas convention); NDC is +Y up.
    gl_Position = vec4(p.x / u_viewport.x * 2.0 - 1.0,
                       1.0 - p.y / u_viewport.y * 2.0, 0.0, 1.0);
    v_uv = in_vert + vec2(0.5);
    v_color = in_color;
    v_layer = in_layer;
    v_alpha = in_alpha;
}
"""

_FRAGMENT_SHADER = """
#version 330
uniform sampler2DArray u_atlas;
in vec2 v_uv;
in vec3 v_color;
in float v_layer;
in float v_alpha;
out vec4 f_color;
void main() {
    float a = texture(u_atlas, vec3(v_uv, v_layer)).a;
    if (a < 0.004) discard;          // keeps overdraw off the blend unit
    f_color = vec4(v_color, a * v_alpha);
}
"""


class InstanceBatch:
    """Growable flat float buffer of instances, reused across frames.

    A list-of-tuples rebuilt per frame would allocate on every soldier every
    frame; this writes into one numpy array that only ever grows.
    """

    def __init__(self, capacity=4096):
        self.data = np.zeros(capacity * _FLOATS_PER_INSTANCE, dtype="f4")
        self.count = 0

    def clear(self):
        self.count = 0

    def add(self, x, y, w, h, rot, color, layer, alpha=1.0):
        i = self.count * _FLOATS_PER_INSTANCE
        if i + _FLOATS_PER_INSTANCE > self.data.size:
            self.data = np.resize(self.data, self.data.size * 2)
        d = self.data
        d[i] = x; d[i + 1] = y
        d[i + 2] = w; d[i + 3] = h
        d[i + 4] = rot
        d[i + 5], d[i + 6], d[i + 7] = color
        d[i + 8] = layer
        d[i + 9] = alpha
        self.count += 1

    def view(self):
        return self.data[:self.count * _FLOATS_PER_INSTANCE]


_COLOR_CACHE = {}


def hex_rgb(value):
    """'#c33' / '#cc3333' -> (r, g, b) floats. Cached: called per instance."""
    hit = _COLOR_CACHE.get(value)
    if hit is not None:
        return hit
    s = (value or "#ffffff").lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    try:
        rgb = (int(s[0:2], 16) / 255.0, int(s[2:4], 16) / 255.0,
               int(s[4:6], 16) / 255.0)
    except ValueError:
        rgb = (1.0, 1.0, 1.0)
    _COLOR_CACHE[value] = rgb
    return rgb


class GLBattleFrame(OpenGLFrame):
    """A Tk frame whose interior is drawn by the GPU.

    Deliberately a plain Tk widget from the outside: it sits inside the same
    layout as the old canvas, so the surrounding battle UI (panels, orders,
    the log) is untouched Tk and only the battlefield itself is GL.
    """

    def __init__(self, master, view, **kw):
        super().__init__(master, **kw)
        self.view = view          # BattleView, for battle state + selection
        self.ctx = None
        self.prog = None
        self.vao = None
        self.batch = InstanceBatch()
        self.animate = 0          # we drive redraws ourselves, from the sim loop
        self._failed = False

    # --- GL lifecycle ---------------------------------------------------------
    def initgl(self):
        """Called on map AND on every resize, so it must be idempotent."""
        if self._failed:
            return
        if self.ctx is None:
            try:
                self.ctx = moderngl.create_context()
                self._setup_gl()
            except Exception:
                self._failed = True
                return
        w, h = self._size()
        self.ctx.viewport = (0, 0, w, h)

    def _setup_gl(self):
        # NOT _setup: tkinter.Widget already defines that internally.
        ctx = self.ctx
        self.prog = ctx.program(vertex_shader=_VERTEX_SHADER,
                                fragment_shader=_FRAGMENT_SHADER)
        self.atlas = ctx.texture_array((_TILE, _TILE, _LAYER_COUNT), 4,
                                       _build_atlas())
        self.atlas.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.atlas.use(0)
        self.prog["u_atlas"] = 0
        quad = np.array([-0.5, -0.5, 0.5, -0.5, -0.5, 0.5,
                         0.5, -0.5, 0.5, 0.5, -0.5, 0.5], dtype="f4")
        self.quad_vbo = ctx.buffer(quad.tobytes())
        self.inst_vbo = ctx.buffer(reserve=4096 * _FLOATS_PER_INSTANCE * 4,
                                   dynamic=True)
        self.vao = ctx.vertex_array(self.prog, [
            (self.quad_vbo, "2f", "in_vert"),
            (self.inst_vbo, "2f 2f 1f 3f 1f 1f/i",
             "in_pos", "in_size", "in_rot", "in_color", "in_layer", "in_alpha"),
        ])
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA

    def _size(self):
        """Viewport size in pixels. pyopengltk only sets self.width/height once
        a <Configure> has fired, and initgl runs on <Map> BEFORE that -- so fall
        back to the widget's own geometry rather than crashing on first show."""
        w = getattr(self, "width", None) or self.winfo_width()
        h = getattr(self, "height", None) or self.winfo_height()
        return max(1, int(w)), max(1, int(h))

    @property
    def ok(self):
        return self.ctx is not None and not self._failed

    @property
    def failed(self):
        """True only once GL has actually been tried and gone wrong. NOT simply
        'no context yet' -- before Tk maps the widget there is nothing to make
        current, and treating that as failure demoted every machine to the
        canvas before the battle screen was ever shown."""
        return self._failed

    def render_now(self):
        """Draw one frame immediately (the sim loop calls this instead of
        waiting on Tk's expose). A no-op while unmapped."""
        if self._failed or not self.winfo_ismapped():
            return
        try:
            self._display()
        except Exception:
            self._failed = True

    # --- drawing --------------------------------------------------------------
    def redraw(self):
        if not self.ok:
            return
        ctx = self.ctx
        ctx.clear(0.055, 0.066, 0.086)      # theme.CANVAS
        view = self.view
        battle = getattr(view, "battle", None)
        if battle is None:
            return
        w, h = self._size()
        ctx.viewport = (0, 0, w, h)
        self.prog["u_viewport"].value = (float(w), float(h))

        b = self.batch
        b.clear()
        self._emit_midline(b, w, h)
        self._emit_units(b, battle, view)
        self._emit_planning_overlays(b, view)
        self._emit_projectiles(b, battle)
        self._emit_effects(b, battle)

        if b.count == 0:
            return
        payload = b.view().tobytes()
        if len(payload) > self.inst_vbo.size:
            self.inst_vbo.orphan(len(payload))
        self.inst_vbo.write(payload)
        self.vao.render(moderngl.TRIANGLES, vertices=6, instances=b.count)

    def _emit_midline(self, b, w, h):
        b.add(w * 0.5, h * 0.5, 1.0, h, 0.0, (0.11, 0.13, 0.17), LAYER_SOLID)

    _ACCENT_RGB = hex_rgb("#4da3ff")
    _GHOST_RGB = hex_rgb("#3d4757")
    _LINE_W = 1.6

    def _emit_rect_outline(self, b, x0, y0, x1, y1, color):
        """A thin outline via four filled bars -- the GPU path's answer to
        the canvas's dashed create_rectangle. Not dashed (there is no cheap
        dashed-line primitive in an instanced quad batch), but functionally
        the same marquee box, which is the part that actually matters."""
        lo_x, hi_x = min(x0, x1), max(x0, x1)
        lo_y, hi_y = min(y0, y1), max(y0, y1)
        w = self._LINE_W
        b.add((lo_x + hi_x) / 2, lo_y, hi_x - lo_x, w, 0.0, color, LAYER_SOLID)
        b.add((lo_x + hi_x) / 2, hi_y, hi_x - lo_x, w, 0.0, color, LAYER_SOLID)
        b.add(lo_x, (lo_y + hi_y) / 2, w, hi_y - lo_y, 0.0, color, LAYER_SOLID)
        b.add(hi_x, (lo_y + hi_y) / 2, w, hi_y - lo_y, 0.0, color, LAYER_SOLID)

    def _emit_line(self, b, x0, y0, x1, y1, color, width=None):
        w = width or self._LINE_W
        length = math.hypot(x1 - x0, y1 - y0)
        if length < 1e-6:
            return
        ang = math.atan2(x1 - x0, -(y1 - y0))   # sprites point -Y at rot 0
        b.add((x0 + x1) / 2, (y0 + y1) / 2, w, length, ang, color, LAYER_SOLID)

    def _emit_planning_overlays(self, b, view):
        """Marquee box-select and the right-drag formation tool (ghost units
        + rally flags at each slot the selection will snap into) -- carried
        over from the canvas renderer, which drew these in the tail of
        render() that the GPU path skips entirely. Missing here was a real
        regression: once GPU rendering became the default, both of these
        planning aids silently stopped appearing with no error, because
        nothing in this file had ever drawn them."""
        marquee = getattr(view, "_marquee", None)
        if marquee is not None:
            self._emit_rect_outline(b, *marquee, self._ACCENT_RGB)

        line = getattr(view, "_formation_line", None)
        if line is not None:
            self._emit_line(b, *line, self._ACCENT_RGB)

        for u, sx, sy in getattr(view, "_formation_slots", ()):
            r = u.radius
            layer = SHAPE_LAYER.get(u.type["shape"], LAYER_CIRCLE)
            b.add(sx, sy, r * 2, r * 2, 0.0, self._GHOST_RGB, layer)
            pole_top = sy - r - 11
            self._emit_line(b, sx, sy - r, sx, pole_top, self._ACCENT_RGB)
            # Pennant: a small triangle sprite is drawn point-first (-Y);
            # rotate 90 deg so it flies sideways off the pole like the
            # canvas version's create_polygon pennant did.
            b.add(sx + 3.5, pole_top + 3, 7.0, 6.0, math.pi / 2,
                  self._ACCENT_RGB, LAYER_TRIANGLE)

    def _emit_units(self, b, battle, view):
        """Every soldier, and its kit -- no detail cutoff. This is the whole
        point of the GL path: on the canvas the sword/shield glyphs were two
        extra items per soldier and had to be dropped past 160 units."""
        selected = getattr(view, "selected_units", ())
        from app.battle import orders as _orders
        cue = _ORDER_CUE_RGB
        for army in battle.armies:
            color = hex_rgb(army.color)
            for u in army.units:
                if not u.alive:
                    continue
                x, y, r = u.x, u.y, u.radius
                if getattr(u, "is_commander", False):
                    b.add(x, y, r * 2, r * 2, 0.0, color, LAYER_CIRCLE)
                    b.add(x, y, r, r, 0.0, (1.0, 1.0, 1.0), LAYER_CIRCLE)
                    self._emit_health_bar(b, u)
                    continue
                layer = SHAPE_LAYER.get(u.type["shape"], LAYER_CIRCLE)
                b.add(x, y, r * 2, r * 2, 0.0, color, layer)
                self._emit_equipment(b, u, r)
                if u in selected:
                    b.add(x, y, (r + 3) * 2, (r + 3) * 2, 0.0,
                          (1.0, 1.0, 1.0), LAYER_RING)
                tint = cue.get(u.stance)
                if tint is not None:
                    b.add(x, y - r - 4, 7.0, 2.0, 0.0, tint, LAYER_SOLID)
                if u._ranged and not u.fire_at_will and u.volley > 0:
                    b.add(x - 4 + 4 * u.volley, y - r - 8, 8.0 * u.volley, 2.0,
                          0.0, (0.91, 0.77, 0.42), LAYER_SOLID)

    def _emit_equipment(self, b, u, r):
        eq = u.type.get("equipment")
        if not eq:
            return
        fx, fy = u.facing
        # Sprites are authored pointing -Y ("up"), so this is the angle from
        # up to the facing direction.
        ang = math.atan2(fx, -fy)
        rhx, rhy = -fy, fx
        lhx, lhy = fy, -fx
        if "sword" in eq:
            b.add(u.x + fx * r * 0.7 + rhx * r * 0.5,
                  u.y + fy * r * 0.7 + rhy * r * 0.5,
                  r * 1.1, r * 1.7, ang, (0.94, 0.90, 0.78), LAYER_SWORD)
        if "shield" in eq:
            b.add(u.x + lhx * (r + 3), u.y + lhy * (r + 3),
                  r * 1.2, r * 1.4, ang, (0.66, 0.83, 1.0), LAYER_SHIELD)
        if "daggers" in eq:
            for hx, hy in ((rhx, rhy), (lhx, lhy)):
                b.add(u.x + fx * r * 0.55 + hx * r * 0.8,
                      u.y + fy * r * 0.55 + hy * r * 0.8,
                      r * 0.9, r * 1.2, ang, (0.90, 0.82, 0.66), LAYER_DAGGER)

    def _emit_health_bar(self, b, u):
        frac = max(0.0, min(1.0, u.hp / u.max_hp))
        bw = u.radius * 2.2
        by = u.y - u.radius - 12
        b.add(u.x, by, bw, 4.0, 0.0, (0.07, 0.08, 0.11), LAYER_SOLID)
        if frac > 0:
            col = ((0.35, 0.76, 0.48) if frac > 0.5 else
                   (0.85, 0.64, 0.25) if frac > 0.25 else (0.89, 0.38, 0.29))
            b.add(u.x - bw / 2 + bw * frac / 2, by, bw * frac, 4.0, 0.0,
                  col, LAYER_SOLID)

    def _emit_projectiles(self, b, battle):
        for p in battle.projectiles:
            b.add(p.x, p.y, 3.0, 3.0, 0.0, hex_rgb(p.color), LAYER_CIRCLE)

    def _emit_effects(self, b, battle):
        for e in battle.effects:
            f = min(1.0, e.t / e.dur)
            alpha = 1.0 - f
            col = hex_rgb(e.color)
            if e.kind == "block":
                b.add(e.x, e.y, 14 * (0.5 + f), 14 * (0.5 + f), 0.0,
                      (0.66, 0.83, 1.0), LAYER_RING, alpha)
            elif e.kind == "dodge":
                b.add(e.x, e.y, 10 * (0.5 + f), 10 * (0.5 + f), 0.0,
                      (0.72, 0.94, 0.48), LAYER_RING, alpha)
            elif e.kind == "shock":
                size = max(2.0, e.size) * 2 * (0.4 + 0.9 * f)
                b.add(e.x, e.y, size, size, 0.0, col, LAYER_RING, alpha * 0.8)
            else:                                   # impact
                b.add(e.x, e.y, 22 * (0.4 + f), 22 * (0.4 + f), 0.0,
                      col, LAYER_RING, alpha)


# Kept beside the emitter rather than imported from battle_view, so the GL path
# has no dependency back on the canvas renderer.
_ORDER_CUE_RGB = {}


def _init_cue_colors():
    from app.battle import orders
    _ORDER_CUE_RGB.update({
        orders.STANCE_HOLD: hex_rgb("#7fd6ff"),
        orders.STANCE_CHARGE: hex_rgb("#ff9b57"),
        orders.STANCE_SHIELD_WALL: hex_rgb("#9fe0a8"),
        orders.STANCE_CYCLE_CHARGE: hex_rgb("#ffd166"),
        orders.STANCE_FIRING_LINE: hex_rgb("#d3a6f2"),
    })


_init_cue_colors()
