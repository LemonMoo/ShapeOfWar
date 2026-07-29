"""The world as a planet: the 2D map wrapped onto a rotatable globe.

This is a second VIEW of the same world, not a second world. It textures the
sphere with exactly the raster the flat map already builds (MapView._base_img)
and the same fog mask, so anything that changes on the flat map -- ownership,
overlays, newly explored ground -- appears here the moment the texture is
re-uploaded. There is no parallel copy of the map to keep in sync.

Why a sphere is cheap here
--------------------------
The world already wraps east-west (app/world/wrap.py), so it is topologically a
cylinder: no seam to hide where longitude 0 meets 360. That is the hard part of
putting a game map on a globe, and it was already true.

Geometry and projection
-----------------------
Equirectangular: map U is longitude, map V is latitude, stretched over the full
pole-to-pole range (the map is 1100x660, so it is vertically stretched to fit a
sphere -- a deliberate choice, not an accident of aspect). Latitude distortion
near the poles is hidden under ice caps, which is also what a planet looks like.

Camera
------
Free orbit, accumulated as a rotation MATRIX rather than yaw/pitch angles.
Euler angles gimbal-lock when you tilt over a pole; a matrix accumulated from
each drag has no poles of its own, so the globe can be rolled in any direction
indefinitely -- which is what "full free orbit" has to mean.

Picking
-------
Screen click -> ray -> sphere intersection -> latitude/longitude -> map cell.
Exactly the forward projection run backwards, so what you click is what you saw.
"""
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

_HAVE_GL = True
try:
    import moderngl
    from pyopengltk import OpenGLFrame
except Exception:
    _HAVE_GL = False
    OpenGLFrame = object


def gl_available():
    return _HAVE_GL


# Camera distance in sphere radii. 1.0 is the surface, so MIN is "just above
# the ground" and MAX frames the whole planet.
DIST_MIN = 1.12
DIST_MAX = 4.2
DIST_DEFAULT = 2.8
# Altitudes at which the view means "world" / "region" / "village". Kept as
# thresholds rather than snapped steps so the camera itself stays continuous --
# flying closer is just moving, and the discrete LEVELS ride on top of it.
LEVEL_REGION_DIST = 2.1
LEVEL_VILLAGE_DIST = 1.45


# --- latitude mapping ---------------------------------------------------------
# The map is NOT stretched linearly from pole to pole. Doing that is plate
# carree, and it looks wrong on a sphere: at latitude phi a full turn of
# longitude covers cos(phi) of the distance it covers at the equator, so the
# closer to a pole, the more every feature is smeared sideways -- until at the
# pole itself the entire top row of the map converges on a single point.
#
# Instead the vertical sampling is compressed to match, using the Mercator
# relation (the same one web maps use). That makes the mapping CONFORMAL: a
# feature keeps its shape everywhere, because the texture is squeezed
# vertically by exactly the amount the sphere squeezes it horizontally.
#
# Mercator runs to infinity at the poles, so the map covers latitudes up to
# MAP_MAX_LAT and the caps beyond it are ice -- which is both what a planet
# looks like and the reason there is no singular point left to smear.
ICE_BLEND_DEG = 9.0          # how far below the edge the ice starts feathering
_MERC_MAX_CAP = 2.44         # ~= 80 deg; past this the caps get unreasonably small


def _merc_y(phi):
    """Latitude (radians) -> Mercator y."""
    return math.log(math.tan(math.pi * 0.25 + phi * 0.5))


def merc_max_for_map(map_w, map_h):
    """How far from the equator this map should reach, derived from its own
    proportions rather than fixed.

    The scale factors work out to horizontal (2*pi/w) against vertical
    (2*merc_max/h), so choosing merc_max = pi*h/w makes them EQUAL: one map
    cell is exactly as wide as it is tall everywhere on the globe. A hardcoded
    edge latitude cannot do that -- it leaves a constant residual squash that
    depends on the map's aspect (0.90 for a 1100x660 world).
    """
    return min(_MERC_MAX_CAP, math.pi * max(1, map_h) / max(1, map_w))


def merc_to_lat_deg(merc_max):
    return math.degrees(2.0 * math.atan(math.exp(merc_max)) - math.pi * 0.5)


def lat_to_v(phi, merc_max):
    """Latitude -> texture v (0 at the north edge, 1 at the south)."""
    m = max(-merc_max, min(merc_max, _merc_y(max(-1.55, min(1.55, phi)))))
    return 0.5 - 0.5 * (m / merc_max)


def v_to_lat(v, merc_max):
    """Texture v -> latitude. The inverse of lat_to_v, used for placing
    markers and for turning a map cell back into a point on the sphere."""
    m = (0.5 - v) * 2.0 * merc_max
    return 2.0 * math.atan(math.exp(m)) - math.pi * 0.5


def _perspective(fovy_deg, aspect, near, far):
    f = 1.0 / math.tan(math.radians(fovy_deg) / 2.0)
    m = np.zeros((4, 4), dtype="f4")
    m[0, 0] = f / max(aspect, 1e-6)
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = (2 * far * near) / (near - far)
    m[3, 2] = -1.0
    return m


def _look_at(eye, target, up):
    f = target - eye
    f /= np.linalg.norm(f)
    s = np.cross(f, up)
    n = np.linalg.norm(s)
    if n < 1e-6:                       # looking straight along `up`
        s = np.cross(f, np.array([0.0, 0.0, 1.0]))
        n = np.linalg.norm(s)
    s /= n
    u = np.cross(s, f)
    m = np.eye(4, dtype="f4")
    m[0, :3] = s
    m[1, :3] = u
    m[2, :3] = -f
    m[0, 3] = -s.dot(eye)
    m[1, 3] = -u.dot(eye)
    m[2, 3] = f.dot(eye)
    return m


def _axis_angle(axis, angle):
    axis = np.asarray(axis, dtype="f8")
    n = np.linalg.norm(axis)
    if n < 1e-9:
        return np.eye(3)
    x, y, z = axis / n
    c, s = math.cos(angle), math.sin(angle)
    C = 1.0 - c
    return np.array([
        [c + x * x * C, x * y * C - z * s, x * z * C + y * s],
        [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
        [z * x * C - y * s, z * y * C + x * s, c + z * z * C],
    ])


def _sphere_mesh(seg_u=192, seg_v=96):
    """Unit sphere with equirectangular UVs. v=0 is the north pole."""
    us = np.linspace(0.0, 1.0, seg_u + 1)
    vs = np.linspace(0.0, 1.0, seg_v + 1)
    uu, vv = np.meshgrid(us, vs)
    lon = uu * 2.0 * math.pi
    lat = (0.5 - vv) * math.pi
    cl = np.cos(lat)
    # Only U is carried on the vertex; V is derived per fragment from latitude
    # (see the fragment shader) so the Mercator compression is exact rather
    # than linearly interpolated across a band of triangles.
    verts = np.stack([cl * np.sin(lon), np.sin(lat), cl * np.cos(lon), uu, vv],
                     axis=-1).astype("f4").reshape(-1, 5)
    w = seg_u + 1
    j, i = np.meshgrid(np.arange(seg_v), np.arange(seg_u), indexing="ij")
    a = (j * w + i).ravel()
    b, c, d = a + 1, a + w, a + w + 1
    idx = np.stack([a, c, b, b, c, d], axis=-1).ravel().astype("i4")
    return verts, idx


def uv_to_cell(u, v, world_w, world_h):
    """Equirectangular UV -> map cell. Longitude wraps; latitude clamps."""
    x = int(math.floor((u % 1.0) * world_w))
    y = int(math.floor(min(max(v, 0.0), 0.999999) * world_h))
    return min(x, world_w - 1), min(y, world_h - 1)


_VERT = """
#version 330
uniform mat4 u_viewproj;
uniform mat3 u_rot;
in vec3 in_pos;
in vec2 in_uv;
out vec2 v_uv;
out vec3 v_world;
out vec3 v_model;
void main() {
    vec3 p = u_rot * in_pos;
    gl_Position = u_viewproj * vec4(p, 1.0);
    v_uv = in_uv;
    v_world = p;               // unit sphere: world position IS the normal
    v_model = in_pos;          // unrotated: this is where latitude comes from
}
"""

_FRAG = """
#version 330
uniform sampler2D u_map;
uniform sampler2D u_fog;
uniform vec3 u_eye;
uniform vec3 u_sun;
uniform float u_fog_on;
uniform float u_merc_max;   // Mercator y at the map's edge latitude
uniform float u_lat_max;    // that edge latitude, radians
uniform float u_ice_lat;    // latitude at which ice starts feathering in
uniform float u_night;      // 0 = flat unlit, 1 = full day/night terminator
in vec2 v_uv;
in vec3 v_world;
in vec3 v_model;
out vec4 f_color;

void main() {
    vec3 N = normalize(v_world);

    // Latitude straight from the unrotated sphere position, then the CONFORMAL
    // texture row for it. This is what stops the poles smearing: the texture is
    // compressed vertically by exactly the factor the sphere compresses it
    // horizontally, so terrain keeps its shape all the way to the ice.
    float phi = asin(clamp(v_model.y, -1.0, 1.0));
    float m = log(tan(0.7853981634 + phi * 0.5));
    float tv = 0.5 - 0.5 * clamp(m / u_merc_max, -1.0, 1.0);
    vec2 uv = vec2(v_uv.x, tv);
    vec3 base = texture(u_map, uv).rgb;

    // Ice caps take over at the map's edge latitude -- there is no terrain
    // beyond it to stretch, which is the point.
    float polar = smoothstep(u_ice_lat, u_lat_max, abs(phi));
    base = mix(base, vec3(0.90, 0.95, 1.0), polar);

    // Fog of war: unexplored ground is darkened, not hidden, so the planet
    // still reads as a planet.
    float hidden = texture(u_fog, uv).r * u_fog_on;
    base = mix(base, base * 0.16 + vec3(0.01, 0.012, 0.02), hidden);

    // Day/night terminator, softened so the line is a dusk band not a cut.
    //
    // Deliberately shallow. A physically dark night side looked far better and
    // made the globe useless as a MAP: with the sun where turn 561 puts it,
    // most of the visible disc was unreadable, and this view is meant to
    // replace the flat map rather than sit beside it. Night is a cool blue
    // wash you can still read borders and roads through.
    float lam = dot(N, normalize(u_sun));
    float day = smoothstep(-0.18, 0.22, lam);
    vec3 lit = base * (0.80 + 0.20 * max(lam, 0.0));
    vec3 night = base * 0.62 + vec3(0.01, 0.02, 0.06);
    vec3 col = mix(mix(base, night, u_night), mix(base, lit, u_night), day);

    // Atmosphere: fresnel rim, brighter on the daylit limb.
    vec3 V = normalize(u_eye - v_world);
    float rim = pow(1.0 - max(dot(N, V), 0.0), 3.0);
    col += vec3(0.28, 0.48, 0.92) * rim * (0.30 + 0.70 * day);

    f_color = vec4(col, 1.0);
}
"""

# Billboarded markers (settlements, commanders) drawn as camera-facing quads.
#
# Every overlay program below takes u_rot and applies it itself, so instance
# data is stored in the sphere's OWN frame and survives a rotation. Baking the
# camera rotation in at set-time instead looks fine until the first drag: the
# planet turns and the markers stay where they were.
_MARK_VERT = """
#version 330
uniform mat4 u_viewproj;
uniform mat3 u_rot;
uniform vec3 u_right;
uniform vec3 u_up;
in vec2 in_vert;
in vec3 in_center;
in float in_size;
in vec3 in_color;
out vec2 v_uv;
out vec3 v_color;
void main() {
    vec3 p = u_rot * in_center + (u_right * in_vert.x + u_up * in_vert.y) * in_size;
    gl_Position = u_viewproj * vec4(p, 1.0);
    v_uv = in_vert + vec2(0.5);
    v_color = in_color;
}
"""

# --- screen-width lines (roads, trade routes, borders) -------------------------
# One instanced quad per SEGMENT, widened in screen space rather than in world
# space: a road has to stay legible whether the camera is in orbit or nearly on
# the ground, and a world-space tube does the opposite of that. The quad's depth
# still comes from the segment's own position on the sphere, so the planet
# occludes the far half of a route for free.
_LINE_VERT = """
#version 330
uniform mat4 u_viewproj;
uniform mat3 u_rot;
uniform vec2 u_px2ndc;      // pixels -> NDC (2/width, 2/height)
in vec2 in_vert;            // x: 0 = start, 1 = end;  y: -1/+1 = which side
in vec3 in_a;
in vec3 in_b;
in vec3 in_color;
in float in_width;          // pixels
out vec3 v_color;
void main() {
    vec4 ca = u_viewproj * vec4(u_rot * in_a, 1.0);
    vec4 cb = u_viewproj * vec4(u_rot * in_b, 1.0);
    vec2 na = ca.xy / ca.w;
    vec2 nb = cb.xy / cb.w;
    // Direction in PIXELS, not NDC -- otherwise the perpendicular is skewed by
    // the viewport's aspect and a line's thickness changes with its angle.
    vec2 dir = (nb - na) / u_px2ndc;
    float len = length(dir);
    dir = len > 1e-6 ? dir / len : vec2(1.0, 0.0);
    vec2 nrm = vec2(-dir.y, dir.x);
    vec4 clip = mix(ca, cb, in_vert.x);
    vec2 off = nrm * (in_width * 0.5) * in_vert.y * u_px2ndc;
    clip.xy += off * clip.w;
    gl_Position = clip;
    v_color = in_color;
}
"""

_LINE_FRAG = """
#version 330
in vec3 v_color;
out vec4 f_color;
void main() { f_color = vec4(v_color, 0.92); }
"""

# --- text ---------------------------------------------------------------------
# Labels are laid out in screen pixels around an anchor that is projected from
# the sphere, so a name keeps its size and stays upright however the planet is
# rolled -- but it still carries the anchor's depth, so a label on the far side
# is hidden by the planet rather than floating over it.
_TEXT_VERT = """
#version 330
uniform mat4 u_viewproj;
uniform mat3 u_rot;
uniform vec2 u_px2ndc;
in vec2 in_vert;            // unit quad, 0..1
in vec3 in_anchor;          // point on the unit sphere
in vec2 in_offset;          // pixels from the projected anchor to the quad's corner
in vec2 in_size;            // quad size in pixels
in vec4 in_uv;              // atlas rect (u0, v0, u1, v1)
in vec3 in_color;
out vec2 v_uv;
out vec3 v_color;
void main() {
    vec4 clip = u_viewproj * vec4(u_rot * in_anchor, 1.0);
    // Laid out in SCREEN convention -- origin top-left of the glyph, y down --
    // and flipped once on the way into NDC. Both the quad and the atlas rect
    // have to make the same flip: the atlas is a PIL image, whose first row is
    // the top of the glyph, and NDC's first row is the bottom.
    vec2 t = vec2(in_vert.x, 1.0 - in_vert.y);
    vec2 px = in_offset + t * in_size;
    clip.xy += vec2(px.x, -px.y) * u_px2ndc * clip.w;
    gl_Position = clip;
    v_uv = mix(in_uv.xy, in_uv.zw, t);
    v_color = in_color;
}
"""

_TEXT_FRAG = """
#version 330
uniform sampler2D u_atlas;
in vec2 v_uv;
in vec3 v_color;
out vec4 f_color;
void main() {
    float a = texture(u_atlas, v_uv).r;
    if (a <= 0.02) discard;
    f_color = vec4(v_color, a);
}
"""

_MARK_FRAG = """
#version 330
in vec2 v_uv;
in vec3 v_color;
out vec4 f_color;
void main() {
    // Soft disc; anything outside the circle is dropped.
    float d = length(v_uv - vec2(0.5)) * 2.0;
    if (d > 1.0) discard;
    float edge = smoothstep(1.0, 0.75, d);
    f_color = vec4(v_color, edge);
}
"""


# --- font atlas ---------------------------------------------------------------
# One texture holding every glyph the globe can draw, laid out on a fixed grid.
# A grid wastes a little space next to a tight packing, but it makes a glyph's
# UV rect pure arithmetic from its index -- and text on the globe is a few
# hundred characters a frame, so the win from packing tighter would be nothing
# and the code to do it would be real.
_ATLAS_PX = 32          # the size glyphs are RASTERISED at; drawn size is free,
                        # since the quads are scaled per label
_ATLAS_COLS = 16
_ATLAS_CHARS = "".join(chr(i) for i in range(32, 127))   # ' ' .. '~'
_FALLBACK_CHAR = "?"

# Floats per instance in the line / glyph buffers (see _setup_gl's vertex
# arrays). Named so the reserve sizes and the packing loops can never drift.
_LINE_STRIDE = 10       # a(3) b(3) color(3) width(1)
_GLYPH_STRIDE = 14      # anchor(3) offset(2) size(2) uv(4) color(3)

# How far overlays float above the surface, in sphere radii. Enough to clear
# depth-buffer noise against the terrain, small enough that nothing visibly
# hovers. Lines sit UNDER markers so a settlement is never hidden by the road
# that reaches it.
LINE_LIFT = 1.0015
MARKER_LIFT = 1.004
LABEL_SHADOW_PX = 1.4
LABEL_SHADOW_COLOR = (0.03, 0.03, 0.05)


class _FontAtlas:
    """Rasterised glyphs plus the metrics to lay them out. Built once, lazily,
    and shared by every globe -- building it costs a few milliseconds of PIL
    work that has no reason to happen per widget."""

    _shared = None

    @classmethod
    def shared(cls):
        if cls._shared is None:
            cls._shared = cls()
        return cls._shared

    def __init__(self):
        font = self._load_font()
        # Cell big enough for the widest glyph and the full ascender-to-
        # descender band, so every glyph sits on the same baseline and a label
        # never wobbles as its letters change.
        adv = [self._advance(font, ch) for ch in _ATLAS_CHARS]
        boxes = [font.getbbox(ch) or (0, 0, 0, 0) for ch in _ATLAS_CHARS]
        self.cell_w = int(math.ceil(max(max(adv), max(b[2] for b in boxes)))) + 2
        self.cell_h = int(math.ceil(max(b[3] for b in boxes))) + 2
        rows = int(math.ceil(len(_ATLAS_CHARS) / _ATLAS_COLS))
        img = Image.new("L", (self.cell_w * _ATLAS_COLS, self.cell_h * rows), 0)
        draw = ImageDraw.Draw(img)
        for i, ch in enumerate(_ATLAS_CHARS):
            col, row = i % _ATLAS_COLS, i // _ATLAS_COLS
            draw.text((col * self.cell_w + 1, row * self.cell_h), ch,
                      font=font, fill=255)
        self.image = img
        self.size = img.size
        # Per-glyph UV rect and advance, both normalised to the cell so a
        # caller only ever works in "ems" and multiplies by its own pixel size.
        self.uv = {}
        self.advance = {}
        for i, ch in enumerate(_ATLAS_CHARS):
            col, row = i % _ATLAS_COLS, i // _ATLAS_COLS
            u0 = col * self.cell_w / img.width
            v0 = row * self.cell_h / img.height
            self.uv[ch] = (u0, v0,
                           u0 + self.cell_w / img.width,
                           v0 + self.cell_h / img.height)
            self.advance[ch] = (adv[i] + 1) / self.cell_h   # in units of cell_h
        self.aspect = self.cell_w / self.cell_h

    @staticmethod
    def _load_font():
        for name in ("segoeuib.ttf", "seguisb.ttf", "arialbd.ttf",
                     "DejaVuSans-Bold.ttf", "segoeui.ttf", "arial.ttf"):
            try:
                return ImageFont.truetype(name, _ATLAS_PX)
            except Exception:
                continue
        return ImageFont.load_default()

    @staticmethod
    def _advance(font, ch):
        try:
            return float(font.getlength(ch))
        except Exception:
            return float(font.getbbox(ch)[2])

    def width_of(self, text, px):
        """Width of `text` when drawn at `px` pixels tall."""
        return px * sum(self.advance.get(ch, self.advance[_FALLBACK_CHAR])
                        for ch in text)


class GLGlobeFrame(OpenGLFrame):
    """The planet. A Tk widget, so it drops into the same layout the flat map
    canvas occupies and the surrounding panels stay ordinary Tk."""

    def __init__(self, master, on_pick=None, **kw):
        super().__init__(master, **kw)
        self.on_pick = on_pick          # called with (cell_x, cell_y) on a click
        self.ctx = None
        self.animate = 0
        self._failed = False
        self._tex_dirty = True
        self._map_img = None
        self._fog_img = None
        # Start looking at the MIDDLE of the map, not its east-west seam.
        # Longitude 0 is where the map wraps, and an unrotated sphere puts that
        # edge square to the camera -- so the first thing a player saw was the
        # join rather than their world.
        self.rot = _axis_angle((0.0, 1.0, 0.0), math.pi)
        self.dist = DIST_DEFAULT
        self.sun = np.array([1.0, 0.25, 0.45])
        self.night_strength = 1.0
        # Derived from the map's proportions the moment one is supplied.
        self.merc_max = merc_max_for_map(1, 1)
        self.lat_max = math.radians(merc_to_lat_deg(self.merc_max))
        self._drag = None
        self._dragged = 0.0
        self._markers = np.zeros(0, dtype="f4")
        self._marker_count = 0
        self._lines = np.zeros(0, dtype="f4")
        self._line_count = 0
        self._glyphs = np.zeros(0, dtype="f4")
        self._glyph_count = 0

        for seq, fn in (("<ButtonPress-1>", self._press),
                        ("<B1-Motion>", self._motion),
                        ("<ButtonRelease-1>", self._release),
                        ("<MouseWheel>", self._wheel),
                        ("<Button-4>", self._wheel),
                        ("<Button-5>", self._wheel)):
            self.bind(seq, fn)

    # --- lifecycle ------------------------------------------------------------
    @property
    def failed(self):
        return self._failed

    @property
    def ok(self):
        return self.ctx is not None and not self._failed

    def _size(self):
        w = getattr(self, "width", None) or self.winfo_width()
        h = getattr(self, "height", None) or self.winfo_height()
        return max(1, int(w)), max(1, int(h))

    def initgl(self):
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
        ctx = self.ctx
        self.prog = ctx.program(vertex_shader=_VERT, fragment_shader=_FRAG)
        verts, idx = _sphere_mesh()
        self.vbo = ctx.buffer(verts.tobytes())
        self.ibo = ctx.buffer(idx.tobytes())
        self.vao = ctx.vertex_array(
            self.prog, [(self.vbo, "3f 2f", "in_pos", "in_uv")], self.ibo)
        # 1x1 placeholders so the first frame can draw before a world exists.
        self.tex_map = ctx.texture((1, 1), 3, b"\x20\x28\x38")
        self.tex_fog = ctx.texture((1, 1), 1, b"\x00")
        self._configure_textures()
        self.mark_prog = ctx.program(vertex_shader=_MARK_VERT,
                                     fragment_shader=_MARK_FRAG)
        quad = np.array([-0.5, -0.5, 0.5, -0.5, -0.5, 0.5,
                         0.5, -0.5, 0.5, 0.5, -0.5, 0.5], dtype="f4")
        self.mark_quad = ctx.buffer(quad.tobytes())
        self.mark_inst = ctx.buffer(reserve=4096 * 7 * 4, dynamic=True)
        self.mark_vao = ctx.vertex_array(self.mark_prog, [
            (self.mark_quad, "2f", "in_vert"),
            (self.mark_inst, "3f 1f 3f/i", "in_center", "in_size", "in_color"),
        ])
        # Lines: one instanced quad per segment. The base quad's x picks an
        # endpoint and its y picks a side, so the two triangles cover the
        # segment once widened in the vertex shader.
        self.line_prog = ctx.program(vertex_shader=_LINE_VERT,
                                     fragment_shader=_LINE_FRAG)
        seg = np.array([0, -1, 1, -1, 0, 1,
                        1, -1, 1, 1, 0, 1], dtype="f4")
        self.line_quad = ctx.buffer(seg.tobytes())
        self.line_inst = ctx.buffer(reserve=4096 * _LINE_STRIDE * 4, dynamic=True)
        self.line_vao = ctx.vertex_array(self.line_prog, [
            (self.line_quad, "2f", "in_vert"),
            (self.line_inst, "3f 3f 3f 1f/i", "in_a", "in_b", "in_color", "in_width"),
        ])
        # Text: one instanced quad per glyph against the shared atlas.
        self.text_prog = ctx.program(vertex_shader=_TEXT_VERT,
                                     fragment_shader=_TEXT_FRAG)
        unit = np.array([0, 0, 1, 0, 0, 1, 1, 0, 1, 1, 0, 1], dtype="f4")
        self.text_quad = ctx.buffer(unit.tobytes())
        self.text_inst = ctx.buffer(reserve=4096 * _GLYPH_STRIDE * 4, dynamic=True)
        self.text_vao = ctx.vertex_array(self.text_prog, [
            (self.text_quad, "2f", "in_vert"),
            (self.text_inst, "3f 2f 2f 4f 3f/i", "in_anchor", "in_offset",
             "in_size", "in_uv", "in_color"),
        ])
        self.atlas = _FontAtlas.shared()
        self.tex_text = ctx.texture(self.atlas.size, 1, self.atlas.image.tobytes())
        self.tex_text.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.tex_text.repeat_x = False
        self.tex_text.repeat_y = False
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA

    def _configure_textures(self):
        # Longitude repeats (the world wraps east-west); latitude clamps.
        #
        # Filtering is deliberately asymmetric, and matches what the flat map
        # does: NEAREST when magnifying, so a map cell close up is a crisp
        # square rather than a smear, and mipmapped LINEAR when minifying,
        # because from orbit a 1100x660 map is squeezed into a few hundred
        # pixels and point-sampling that crawls with every degree of rotation.
        for tex in (self.tex_map, self.tex_fog):
            tex.repeat_x = True
            tex.repeat_y = False
            try:
                tex.build_mipmaps()
                tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.NEAREST)
            except Exception:
                tex.filter = (moderngl.LINEAR, moderngl.NEAREST)

    # --- content --------------------------------------------------------------
    def set_map(self, map_img, fog_img=None):
        """Hand over the flat map's own raster (PIL RGB) and fog mask ("L").
        Cheap to call -- upload only happens on the next frame."""
        self._map_img = map_img
        self._fog_img = fog_img
        self._tex_dirty = True
        if map_img is not None:
            self.merc_max = merc_max_for_map(*map_img.size)
            self.lat_max = math.radians(merc_to_lat_deg(self.merc_max))

    def set_markers(self, marks):
        """[(cell_x, cell_y, size, (r,g,b)), ...] -- billboarded on the sphere.
        Anything on the far side is hidden by the depth buffer for free."""
        n = len(marks)
        need = max(1, n) * 7
        if self._markers.size < need:
            self._markers = np.zeros(need, dtype="f4")
        d = self._markers
        for i, (cx, cy, size, color) in enumerate(marks):
            p = self.cell_to_point(cx, cy) * MARKER_LIFT
            o = i * 7
            d[o:o + 3] = p
            d[o + 3] = size
            d[o + 4:o + 7] = color
        self._marker_count = n

    def set_lines(self, paths):
        """Roads, trade routes and borders.

        ``paths`` is [(cells, (r,g,b), width_px, dash), ...] where ``cells`` is
        an ordered list of (cell_x, cell_y). ``dash`` of 0 draws the path solid;
        any n > 1 draws one segment in every n, which is how a dashed line is
        done here -- a real dash pattern needs per-fragment arc length, and at
        map-cell resolution the segments are already short enough that dropping
        every other one reads exactly like a dashed road.

        Longitude wrap needs no special case: a path that crosses the seam has
        its two cells land on either side of longitude 0, and the chord between
        them on the sphere is the short way round, which is the correct one."""
        segs = []
        for cells, color, width, dash in paths:
            if len(cells) < 2:
                continue
            step = max(1, int(dash) if dash else 1)
            pts = [self.cell_to_point(cx, cy) * LINE_LIFT for cx, cy in cells]
            for i in range(0, len(pts) - 1, step):
                segs.append((pts[i], pts[i + 1], color, width))
        n = len(segs)
        need = max(1, n) * _LINE_STRIDE
        if self._lines.size < need:
            self._lines = np.zeros(need, dtype="f4")
        d = self._lines
        for i, (a, b, color, width) in enumerate(segs):
            o = i * _LINE_STRIDE
            d[o:o + 3] = a
            d[o + 3:o + 6] = b
            d[o + 6:o + 9] = color
            d[o + 9] = width
        self._line_count = n

    def set_labels(self, labels):
        """Place text on the planet.

        ``labels`` is [(cell_x, cell_y, text, (r,g,b), px, dy), ...]: the string
        is centred horizontally on the cell, ``px`` tall, nudged ``dy`` pixels
        (negative is up, to clear a marker). Each label is emitted twice -- a
        dark copy one pixel down-right and then the real one -- because a name
        over terrain is unreadable without something behind it, and that is the
        same trick the flat map's labels already use."""
        atlas = self.atlas if hasattr(self, "atlas") else _FontAtlas.shared()
        glyphs = []
        for cx, cy, text, color, px, dy in labels:
            if not text:
                continue
            anchor = self.cell_to_point(cx, cy) * MARKER_LIFT
            pen0 = -0.5 * atlas.width_of(text, px)
            gw, gh = px * atlas.aspect, px
            for shade, col in ((LABEL_SHADOW_PX, LABEL_SHADOW_COLOR), (0.0, color)):
                pen = pen0
                for ch in text:
                    if ch not in atlas.uv:
                        ch = _FALLBACK_CHAR
                    if ch != " ":
                        glyphs.append((anchor, (pen + shade, dy + shade),
                                       (gw, gh), atlas.uv[ch], col))
                    pen += px * atlas.advance[ch]
        n = len(glyphs)
        need = max(1, n) * _GLYPH_STRIDE
        if self._glyphs.size < need:
            self._glyphs = np.zeros(need, dtype="f4")
        d = self._glyphs
        for i, (anchor, offset, size, uv, color) in enumerate(glyphs):
            o = i * _GLYPH_STRIDE
            d[o:o + 3] = anchor
            d[o + 3:o + 5] = offset
            d[o + 5:o + 7] = size
            d[o + 7:o + 11] = uv
            d[o + 11:o + 14] = color
        self._glyph_count = n

    def _upload_textures(self):
        if not self._tex_dirty or self._map_img is None:
            return
        ctx = self.ctx
        img = self._map_img
        if self.tex_map.size != img.size:
            self.tex_map.release()
            self.tex_map = ctx.texture(img.size, 3, img.tobytes())
        else:
            self.tex_map.write(img.tobytes())
        fog = self._fog_img
        if fog is not None:
            if self.tex_fog.size != fog.size:
                self.tex_fog.release()
                self.tex_fog = ctx.texture(fog.size, 1, fog.tobytes())
            else:
                self.tex_fog.write(fog.tobytes())
        self._configure_textures()
        self._tex_dirty = False

    # --- camera ---------------------------------------------------------------
    def eye(self):
        return np.array([0.0, 0.0, self.dist], dtype="f8")

    @property
    def zoom_level(self):
        """Which of the three map levels this altitude corresponds to."""
        if self.dist <= LEVEL_VILLAGE_DIST:
            return 2
        if self.dist <= LEVEL_REGION_DIST:
            return 1
        return 0

    def cell_to_point(self, cx, cy):
        """Map cell -> point on the UNROTATED unit sphere.

        Deliberately not rotated: every overlay program applies u_rot itself,
        so overlay geometry is uploaded once and stays glued to the terrain
        through a drag. Rotating here instead means a drag moves the planet out
        from under its own markers until the next set_* call."""
        w, h = self._world_size()
        lon = (cx + 0.5) / w * 2.0 * math.pi
        lat = v_to_lat((cy + 0.5) / h, self.merc_max)   # inverse of the shader
        return np.array([math.cos(lat) * math.sin(lon), math.sin(lat),
                         math.cos(lat) * math.cos(lon)])

    def _world_size(self):
        img = self._map_img
        return img.size if img is not None else (1, 1)

    def cells_to_points(self, cells):
        """cell_to_point for a whole list at once, as an (n, 3) array."""
        w, h = self._world_size()
        arr = np.asarray(cells, dtype="f8").reshape(-1, 2)
        lon = (arr[:, 0] + 0.5) / w * 2.0 * math.pi
        m = (0.5 - (arr[:, 1] + 0.5) / h) * 2.0 * self.merc_max
        lat = 2.0 * np.arctan(np.exp(m)) - math.pi * 0.5
        cl = np.cos(lat)
        return np.stack([cl * np.sin(lon), np.sin(lat), cl * np.cos(lon)], axis=-1)

    def viewproj(self):
        w, h = self._size()
        proj = _perspective(45.0, w / max(1, h), 0.05, 40.0)
        view = _look_at(self.eye(), np.zeros(3), np.array([0.0, 1.0, 0.0]))
        return proj @ view

    def visible_mask(self, cells, pad=1.2):
        """Which of these cells the camera can actually see -- on the near side
        of the planet AND inside the viewport.

        The GPU would clip and depth-test them anyway, but that decision comes
        after the work of building their geometry, and from low altitude over a
        developed realm almost everything is off-screen or behind the horizon.
        It also drives the label rules: "how many villages are in shot" is the
        question that decides whether naming them is information or soup, and
        a hemisphere test answers a different, much less useful question.

        The horizon test is p.z > 1/dist, not p.z > 0: the visible cap of a
        sphere seen from a finite distance is smaller than a hemisphere, and
        from low altitude it is *much* smaller."""
        n = len(cells)
        if n == 0:
            return np.zeros(0, dtype=bool)
        pts = self.cells_to_points(cells) @ self.rot.T
        seen = pts[:, 2] > 1.0 / max(self.dist, 1.0 + 1e-6)
        hom = np.concatenate([pts, np.ones((n, 1))], axis=1) @ self.viewproj().T
        wc = hom[:, 3]
        ok = seen & (wc > 1e-6)
        if not ok.any():
            return ok
        ndc = np.zeros((n, 2))
        ndc[ok] = hom[ok, :2] / wc[ok, None]
        return ok & (np.abs(ndc[:, 0]) <= pad) & (np.abs(ndc[:, 1]) <= pad)

    def pick(self, sx, sy):
        """Screen pixel -> map cell, or None if the click missed the planet."""
        w, h = self._size()
        aspect = w / max(1, h)
        fov = math.radians(45.0)
        # Screen -> camera-space ray (camera looks down -Z from +Z).
        ndc_x = (2.0 * sx / w - 1.0) * math.tan(fov / 2.0) * aspect
        ndc_y = (1.0 - 2.0 * sy / h) * math.tan(fov / 2.0)
        origin = self.eye()
        direction = np.array([ndc_x, ndc_y, -1.0])
        direction /= np.linalg.norm(direction)
        # Ray-sphere (unit sphere at the origin).
        b = 2.0 * origin.dot(direction)
        c = origin.dot(origin) - 1.0
        disc = b * b - 4.0 * c
        if disc < 0.0:
            return None
        t = (-b - math.sqrt(disc)) / 2.0
        if t < 0.0:
            return None
        hit = origin + direction * t
        local = self.rot.T.dot(hit)         # undo the orbit
        lat = math.asin(max(-1.0, min(1.0, local[1])))
        if abs(lat) >= self.lat_max:
            return None                      # clicked the ice cap, not the map
        lon = math.atan2(local[0], local[2]) % (2.0 * math.pi)
        ww, hh = self._world_size()
        return uv_to_cell(lon / (2.0 * math.pi),
                          lat_to_v(lat, self.merc_max), ww, hh)

    # --- interaction ----------------------------------------------------------
    def _press(self, event):
        self._drag = (event.x, event.y)
        self._dragged = 0.0

    def _motion(self, event):
        if self._drag is None:
            return
        lx, ly = self._drag
        dx, dy = event.x - lx, event.y - ly
        self._drag = (event.x, event.y)
        self._dragged += abs(dx) + abs(dy)
        # Rotate about CAMERA axes, then accumulate. Doing it in this order is
        # what lets the globe roll over its own poles without gimbal lock --
        # there is no stored pitch to run out of.
        k = 0.005 * max(0.35, self.dist / DIST_DEFAULT)
        r = _axis_angle((0.0, 1.0, 0.0), dx * k)
        r = _axis_angle((1.0, 0.0, 0.0), dy * k).dot(r)
        self.rot = r.dot(self.rot)
        self.render_now()

    def _release(self, event):
        drag = self._dragged
        self._drag = None
        # A click is a click only if the globe did not really move under it.
        if drag <= 3.0 and self.on_pick is not None:
            cell = self.pick(event.x, event.y)
            if cell is not None:
                self.on_pick(*cell)

    def _wheel(self, event):
        delta = getattr(event, "delta", 0)
        step = -1 if (delta > 0 or getattr(event, "num", 0) == 4) else 1
        self.dist = max(DIST_MIN, min(DIST_MAX, self.dist * (1.0 + 0.12 * step)))
        self.render_now()

    # --- drawing --------------------------------------------------------------
    def render_now(self):
        if self._failed or not self.winfo_ismapped():
            return
        try:
            self._display()
        except Exception:
            self._failed = True

    def redraw(self):
        if not self.ok:
            return
        ctx = self.ctx
        w, h = self._size()
        ctx.viewport = (0, 0, w, h)
        ctx.clear(0.016, 0.020, 0.031)
        self._upload_textures()

        eye = self.eye()
        proj = _perspective(45.0, w / max(1, h), 0.05, 40.0)
        view = _look_at(eye, np.zeros(3), np.array([0.0, 1.0, 0.0]))
        viewproj = (proj @ view).astype("f4")

        self.tex_map.use(0)
        self.tex_fog.use(1)
        p = self.prog
        p["u_map"] = 0
        p["u_fog"] = 1
        p["u_viewproj"].write(viewproj.T.tobytes())
        p["u_rot"].write(self.rot.astype("f4").T.tobytes())
        p["u_eye"].value = tuple(float(v) for v in eye)
        p["u_sun"].value = tuple(float(v) for v in self.sun)
        p["u_fog_on"].value = 1.0 if self._fog_img is not None else 0.0
        p["u_merc_max"].value = float(self.merc_max)
        p["u_lat_max"].value = float(self.lat_max)
        p["u_ice_lat"].value = float(self.lat_max - math.radians(ICE_BLEND_DEG))
        p["u_night"].value = float(self.night_strength)
        self.vao.render(moderngl.TRIANGLES)

        rot = self.rot.astype("f4").T.tobytes()
        px2ndc = (2.0 / max(1, w), 2.0 / max(1, h))

        # Overlays don't write depth: they all sit within a couple of
        # thousandths of the same surface, so letting them z-fight each other
        # buys nothing. They still TEST against the sphere, which is what hides
        # the half of the world facing away.
        ctx.depth_mask = False

        if self._line_count:
            lp = self.line_prog
            lp["u_viewproj"].write(viewproj.T.tobytes())
            lp["u_rot"].write(rot)
            lp["u_px2ndc"].value = px2ndc
            payload = self._lines[:self._line_count * _LINE_STRIDE].tobytes()
            if len(payload) > self.line_inst.size:
                self.line_inst.orphan(len(payload))
            self.line_inst.write(payload)
            self.line_vao.render(moderngl.TRIANGLES, vertices=6,
                                 instances=self._line_count)

        # Markers and text are already culled to what the camera can see (see
        # visible_mask), so the depth buffer has nothing left to decide for
        # them -- and letting it try actively hurts: a name near the limb is a
        # wide quad anchored at a point the planet is about to curve away
        # from, and half of it disappears into the horizon.
        ctx.disable(moderngl.DEPTH_TEST)

        if self._marker_count:
            # Billboard axes straight from the view matrix, so markers always
            # face the camera however the planet is rolled.
            right = view[0, :3].astype("f4")
            up = view[1, :3].astype("f4")
            mp = self.mark_prog
            mp["u_viewproj"].write(viewproj.T.tobytes())
            mp["u_rot"].write(rot)
            mp["u_right"].value = tuple(float(v) for v in right)
            mp["u_up"].value = tuple(float(v) for v in up)
            payload = self._markers[:self._marker_count * 7].tobytes()
            if len(payload) > self.mark_inst.size:
                self.mark_inst.orphan(len(payload))
            self.mark_inst.write(payload)
            self.mark_vao.render(moderngl.TRIANGLES, vertices=6,
                                 instances=self._marker_count)

        if self._glyph_count:
            self.tex_text.use(2)
            tp = self.text_prog
            tp["u_atlas"] = 2
            tp["u_viewproj"].write(viewproj.T.tobytes())
            tp["u_rot"].write(rot)
            tp["u_px2ndc"].value = px2ndc
            payload = self._glyphs[:self._glyph_count * _GLYPH_STRIDE].tobytes()
            if len(payload) > self.text_inst.size:
                self.text_inst.orphan(len(payload))
            self.text_inst.write(payload)
            self.text_vao.render(moderngl.TRIANGLES, vertices=6,
                                 instances=self._glyph_count)

        ctx.enable(moderngl.DEPTH_TEST)
        ctx.depth_mask = True

    # --- persistence ----------------------------------------------------------
    def camera_state(self):
        return {"rot": self.rot.tolist(), "dist": float(self.dist)}

    def restore_camera(self, state):
        if not state:
            return
        try:
            rot = np.array(state["rot"], dtype="f8")
            if rot.shape == (3, 3):
                self.rot = rot
            self.dist = max(DIST_MIN, min(DIST_MAX, float(state["dist"])))
        except Exception:
            pass          # a malformed saved camera is not worth a crash
