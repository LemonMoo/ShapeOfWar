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
    float lam = dot(N, normalize(u_sun));
    float day = smoothstep(-0.18, 0.22, lam);
    vec3 lit = base * (0.55 + 0.45 * max(lam, 0.0));
    vec3 night = base * 0.20 + vec3(0.015, 0.02, 0.05);
    vec3 col = mix(mix(base, night, u_night), mix(base, lit, u_night), day);

    // Atmosphere: fresnel rim, brighter on the daylit limb.
    vec3 V = normalize(u_eye - v_world);
    float rim = pow(1.0 - max(dot(N, V), 0.0), 3.0);
    col += vec3(0.28, 0.48, 0.92) * rim * (0.30 + 0.70 * day);

    f_color = vec4(col, 1.0);
}
"""

# Billboarded markers (settlements, commanders) drawn as camera-facing quads.
_MARK_VERT = """
#version 330
uniform mat4 u_viewproj;
uniform vec3 u_right;
uniform vec3 u_up;
in vec2 in_vert;
in vec3 in_center;
in float in_size;
in vec3 in_color;
out vec2 v_uv;
out vec3 v_color;
void main() {
    vec3 p = in_center + (u_right * in_vert.x + u_up * in_vert.y) * in_size;
    gl_Position = u_viewproj * vec4(p, 1.0);
    v_uv = in_vert + vec2(0.5);
    v_color = in_color;
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
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA

    def _configure_textures(self):
        # Longitude repeats (the world wraps east-west); latitude clamps.
        self.tex_map.repeat_x = True
        self.tex_map.repeat_y = False
        self.tex_map.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.tex_fog.repeat_x = True
        self.tex_fog.repeat_y = False
        self.tex_fog.filter = (moderngl.LINEAR, moderngl.LINEAR)

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
            p = self.cell_to_point(cx, cy) * 1.004      # lift off the surface
            o = i * 7
            d[o:o + 3] = p
            d[o + 3] = size
            d[o + 4:o + 7] = color
        self._marker_count = n

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
        """Map cell -> point on the rotated sphere (world space)."""
        w, h = self._world_size()
        lon = (cx + 0.5) / w * 2.0 * math.pi
        lat = v_to_lat((cy + 0.5) / h, self.merc_max)   # inverse of the shader
        p = np.array([math.cos(lat) * math.sin(lon), math.sin(lat),
                      math.cos(lat) * math.cos(lon)])
        return self.rot.dot(p)

    def _world_size(self):
        img = self._map_img
        return img.size if img is not None else (1, 1)

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

        if self._marker_count:
            # Billboard axes straight from the view matrix, so markers always
            # face the camera however the planet is rolled.
            right = view[0, :3].astype("f4")
            up = view[1, :3].astype("f4")
            mp = self.mark_prog
            mp["u_viewproj"].write(viewproj.T.tobytes())
            mp["u_right"].value = tuple(float(v) for v in right)
            mp["u_up"].value = tuple(float(v) for v in up)
            payload = self._markers[:self._marker_count * 7].tobytes()
            if len(payload) > self.mark_inst.size:
                self.mark_inst.orphan(len(payload))
            self.mark_inst.write(payload)
            self.mark_vao.render(moderngl.TRIANGLES, vertices=6,
                                 instances=self._marker_count)

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
