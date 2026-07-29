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
import time

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

# Camera pitch. Zooming straight in along the same overhead ray gives an
# aerial-photo view with no horizon and nothing to place yourself against --
# exactly the "we don't know much" complaint a pure top-down close-up has.
# Past PITCH_START_DIST the camera swings toward a shallow, horizon-revealing
# angle instead of just getting closer, the same trade real map applications
# (and most 3D strategy games) make once you approach the ground.
PITCH_START_DIST = LEVEL_REGION_DIST   # pitch is exactly 0 at/above this altitude
PITCH_MAX_DEG = 58.0                   # oblique angle reached at DIST_MIN


def pitch_for_dist(dist):
    """Camera pitch in radians for this altitude -- 0 down to PITCH_START_DIST,
    smoothstepped up to PITCH_MAX_DEG by DIST_MIN. World-view zoom stays the
    plain top-down orbit it always was; the tilt is specifically the "near
    the planet" behaviour that was missing."""
    span = PITCH_START_DIST - DIST_MIN
    if span <= 1e-9 or dist >= PITCH_START_DIST:
        return 0.0
    t = max(0.0, min(1.0, (PITCH_START_DIST - dist) / span))
    t = t * t * (3 - 2 * t)
    return math.radians(PITCH_MAX_DEG) * t


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


def _camera_basis(eye, target, up):
    """(right, up, forward) orthonormal camera axes -- forward points from
    eye toward target. Factored out of _look_at so pick() can turn a screen
    ray into the SAME world-space direction the view matrix itself used,
    which stopped being "assume the camera looks straight down -Z" the
    moment the camera could pitch (see pitch_for_dist) -- eye is no longer
    always on the Z axis, so a ray built in the old fixed-axis shortcut
    would silently point the wrong way at any tilted altitude."""
    f = target - eye
    f = f / np.linalg.norm(f)
    s = np.cross(f, up)
    n = np.linalg.norm(s)
    if n < 1e-6:                       # looking straight along `up`
        s = np.cross(f, np.array([0.0, 0.0, 1.0]))
        n = np.linalg.norm(s)
    s = s / n
    u = np.cross(s, f)
    return s, u, f


def _look_at(eye, target, up):
    s, u, f = _camera_basis(eye, target, up)
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


def _align_y_to(n):
    """3x3 rotation taking local +Y to unit vector `n` -- how a settlement
    pin, modelled standing upright along +Y, gets planted pointing straight
    out of the ground at its own spot on a sphere instead of everywhere at
    the same fixed orientation. Same Rodrigues construction as _axis_angle,
    specialised to a from-vector/to-vector pair rather than an axis/angle."""
    y = np.array([0.0, 1.0, 0.0])
    n = np.asarray(n, dtype="f8")
    n = n / (np.linalg.norm(n) or 1.0)
    v = np.cross(y, n)
    s = np.linalg.norm(v)
    c = float(np.dot(y, n))
    if s < 1e-9:
        return np.eye(3) if c > 0 else _axis_angle((1.0, 0.0, 0.0), math.pi)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx.dot(vx) * ((1 - c) / (s * s))


def _pin_mesh(sides=6):
    """A small hex-pyramid 'spire' in its OWN local frame: base ring at y=0,
    apex at y=1 -- planted so the base sits on the ground and the point
    reaches away from it. Scaled and reoriented per instance (see set_pins),
    not per vertex, so this is built exactly once and shared by every
    settlement on the planet.

    Real geometry, not a billboard: unlike the flat marker discs (which only
    ever face the camera and so read the same from directly overhead as from
    orbit), a standing shape shows its own footprint and height from any
    angle -- which is the whole reason to have one for something you want to
    look like it is PLANTED somewhere rather than floating over it."""
    ang = np.linspace(0.0, 2.0 * math.pi, sides, endpoint=False)
    base = np.stack([np.cos(ang), np.zeros(sides), np.sin(ang)], axis=-1)
    apex = np.array([[0.0, 1.0, 0.0]])
    verts = np.vstack([base, apex]).astype("f4")     # [0..sides-1]=base, [sides]=apex
    tris = []
    for i in range(sides):
        tris.append((i, (i + 1) % sides, sides))
    idx = np.array(tris, dtype="i4").ravel()
    return verts, idx


_PIN_VERT = """
#version 330
uniform mat4 u_viewproj;
uniform mat3 u_rot;
in vec3 in_vert;          // local pin geometry: base ring y=0, apex y=1
in vec3 in_pos;           // planted point, UNROTATED planet frame
in mat3 in_orient;        // local +Y -> this point's own outward direction
in vec2 in_scale;         // (radius, height)
in vec3 in_color;
out vec3 v_color;
out float v_localy;
void main() {
    vec3 local = vec3(in_vert.x * in_scale.x, in_vert.y * in_scale.y, in_vert.z * in_scale.x);
    vec3 planted = in_pos + in_orient * local;
    gl_Position = u_viewproj * vec4(u_rot * planted, 1.0);
    v_color = in_color;
    v_localy = in_vert.y;
}
"""

_PIN_FRAG = """
#version 330
in vec3 v_color;
in float v_localy;
out vec4 f_color;
void main() {
    // No real lighting model -- a cheap base-to-tip gradient is enough to
    // read as a solid, shaded 3D shape rather than a flat cutout, which is
    // the entire point of using real geometry here instead of a billboard.
    float shade = mix(0.58, 1.22, clamp(v_localy, 0.0, 1.0));
    f_color = vec4(v_color * shade, 1.0);
}
"""

_PIN_STRIDE = 17   # pos(3) orient(9) scale(2) color(3)


# Terrain relief. Land bulges outward by up to this fraction of the sphere's
# radius; ocean stays flat at the base radius rather than sinking into
# trenches, which is the standard "relief map" convention and reads far
# better than actually carving the sea floor would. Exaggerated well past
# any real planet's proportions (Everest is ~0.15% of Earth's radius,
# invisible at this scale) -- a game globe is meant to be read, not measured.
ELEV_SCALE = 0.035


def _sphere_mesh(seg_u=320, seg_v=160):
    """Unit sphere with equirectangular UVs. v=0 is the north pole.

    Denser than the pre-elevation version (192x96): a flat-textured sphere
    needed only enough triangles to avoid a visibly faceted silhouette, but
    terrain relief is now carried by vertex DISPLACEMENT, and a mountain
    range can only show up as a bump if there is a vertex near it to move.
    Still cheap -- 320x160 is under 100k triangles, nothing for a GPU that
    was already handling tens of thousands of battle sprite instances."""
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
uniform sampler2D u_elev;
uniform float u_merc_max;
uniform float u_sea_level;
uniform float u_elev_scale;
in vec3 in_pos;
in vec2 in_uv;
out vec2 v_uv;
out vec3 v_world;
out vec3 v_model;
void main() {
    // Same conformal latitude -> texture-row mapping the fragment shader
    // uses (see its own comment) -- needed here too because elevation has
    // to be sampled to DISPLACE the vertex, which can only happen in the
    // vertex stage, not borrowed from the fragment shader's own copy.
    float phi = asin(clamp(in_pos.y, -1.0, 1.0));
    float m = log(tan(0.7853981634 + phi * 0.5));
    float tv = 0.5 - 0.5 * clamp(m / u_merc_max, -1.0, 1.0);
    float h = texture(u_elev, vec2(in_uv.x, tv)).r;
    // Land only: ocean stays at the base radius rather than carving a
    // trench, the same convention _draw_currents' land-only carving and
    // every other relief-map choice here follows.
    float radius = 1.0 + u_elev_scale * max(0.0, h - u_sea_level);
    vec3 displaced = in_pos * radius;
    vec3 p = u_rot * displaced;
    gl_Position = u_viewproj * vec4(p, 1.0);
    v_uv = in_uv;
    v_world = p;
    v_model = displaced;      // unrotated; NOT unit length any more (see the
                              // fragment shader, which normalizes before
                              // reading latitude out of it)
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
uniform float u_cloud_t;    // slow time offset so cloud cover drifts
in vec2 v_uv;
in vec3 v_world;
in vec3 v_model;
out vec4 f_color;

// Cheap 3D value noise for procedural cloud cover -- evaluated directly in
// the sphere's own unrotated direction (not the 2D map UV), so cloud shapes
// never warp or seam at the poles the way sampling a flat 2D noise texture
// through the same conformal projection the terrain uses would.
float _cloud_hash(vec3 p) {
    p = fract(p * 0.3183099 + vec3(0.1, 0.19, 0.13));
    p *= 17.0;
    return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}
float _cloud_noise(vec3 x) {
    vec3 i = floor(x);
    vec3 f = fract(x);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(mix(_cloud_hash(i + vec3(0, 0, 0)), _cloud_hash(i + vec3(1, 0, 0)), f.x),
                   mix(_cloud_hash(i + vec3(0, 1, 0)), _cloud_hash(i + vec3(1, 1, 0)), f.x), f.y),
               mix(mix(_cloud_hash(i + vec3(0, 0, 1)), _cloud_hash(i + vec3(1, 0, 1)), f.x),
                   mix(_cloud_hash(i + vec3(0, 1, 1)), _cloud_hash(i + vec3(1, 1, 1)), f.x), f.y), f.z);
}
float _cloud_fbm(vec3 p) {
    float v = 0.0, a = 0.5;
    for (int i = 0; i < 4; i++) {
        v += a * _cloud_noise(p);
        p = p * 2.05 + vec3(11.3, 7.1, 5.9);
        a *= 0.5;
    }
    return v;
}

void main() {
    vec3 N = normalize(v_world);

    // Latitude straight from the unrotated sphere DIRECTION, then the
    // CONFORMAL texture row for it. This is what stops the poles smearing:
    // the texture is compressed vertically by exactly the factor the sphere
    // compresses it horizontally, so terrain keeps its shape all the way to
    // the ice. Normalized first because v_model now carries elevation
    // displacement (see the vertex shader) and is no longer unit length --
    // dividing it out here recovers the pure direction, same as it always was.
    vec3 dir = normalize(v_model);
    float phi = asin(clamp(dir.y, -1.0, 1.0));
    float m = log(tan(0.7853981634 + phi * 0.5));
    float tv = 0.5 - 0.5 * clamp(m / u_merc_max, -1.0, 1.0);
    vec2 uv = vec2(v_uv.x, tv);
    vec3 base = texture(u_map, uv).rgb;

    // Ice caps take over at the map's edge latitude -- there is no terrain
    // beyond it to stretch, which is the point.
    float polar = smoothstep(u_ice_lat, u_lat_max, abs(phi));
    base = mix(base, vec3(0.90, 0.95, 1.0), polar);

    // Fog of war: unexplored ground is genuinely HIDDEN under cloud cover,
    // not a darkened peek at terrain that has not actually been seen --
    // "unexplored" should mean the player sees clouds, not a dim but
    // accurate guess at the truth underneath them.
    //
    // Blended smoothly by `hidden` rather than an on/off switch, so the
    // existing soft fog edge (from the fog texture's own linear filtering)
    // still reads as a ragged cloud bank fraying at its border instead of a
    // hard line -- which is also more honest: real fog of war reveals
    // partially, not as a razor edge.
    float hidden = texture(u_fog, uv).r * u_fog_on;
    if (hidden > 0.002) {
        float n = _cloud_fbm(dir * 5.0 + vec3(0.0, u_cloud_t, u_cloud_t * 0.6));
        float cloud = smoothstep(0.30, 0.72, n);
        vec3 cloud_color = mix(vec3(0.50, 0.53, 0.62), vec3(0.95, 0.97, 1.0), cloud);
        base = mix(base, cloud_color, hidden);
    }

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
        self._elev_img = None
        self._elev_dirty = True
        # Set by _upload_textures whenever a texture was just CREATED (only
        # ever happens once per world: going from the 1x1 startup placeholder
        # to the real map size) -- see redraw()'s use of it. Measured
        # directly: the very first frame drawn against a texture that size-
        # changed this same call came out visibly wrong on this machine (an
        # otherwise flat test texture rendered as a dark, discoloured sphere),
        # while every frame after was correct with IDENTICAL camera/uniform
        # state -- a GPU/driver timing quirk around brand-new texture storage,
        # not a logic bug. Redrawing once more before presenting is the
        # standard, low-risk answer to exactly this class of glitch.
        self._texture_just_created = False
        self._height_grid = None    # world.height, kept for CPU-side
                                    # terrain_radius lookups (markers/lines/
                                    # labels sitting flush with the terrain)
        self._sea_level = 0.0
        self._pins = np.zeros(0, dtype="f4")
        self._pin_count = 0
        # Start looking at the MIDDLE of the map, not its east-west seam.
        # Longitude 0 is where the map wraps, and an unrotated sphere puts that
        # edge square to the camera -- so the first thing a player saw was the
        # join rather than their world.
        self.rot = _axis_angle((0.0, 1.0, 0.0), math.pi)
        self.dist = DIST_DEFAULT
        self.sun = np.array([1.0, 0.25, 0.45])
        # Wall-clock, not game-turn: purely cosmetic drift so cloud cover
        # looks alive across separate glances at the globe, unlike the sun
        # (a real simulation quantity tied to the turn counter instead).
        self._start_time = time.perf_counter()
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
        # Single-channel normalized byte, same convention as tex_fog. 0
        # everywhere -> exactly sea level -> zero displacement, so a world
        # that hasn't called set_elevation yet (or an old save with no
        # height grid) renders as a perfectly smooth sphere rather than a
        # collapsed one.
        self.tex_elev = ctx.texture((1, 1), 1, b"\x00")
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
        # Settlement pins: real 3D geometry (see _pin_mesh), not a billboard.
        # Drawn with depth test AND depth write on (see redraw()) so pins
        # occlude each other and get occluded by the terrain correctly,
        # unlike the flat overlays below which deliberately disable both.
        self.pin_prog = ctx.program(vertex_shader=_PIN_VERT,
                                    fragment_shader=_PIN_FRAG)
        pverts, pidx = _pin_mesh()
        self._pin_index_count = len(pidx)
        self.pin_vbo = ctx.buffer(pverts.tobytes())
        self.pin_ibo = ctx.buffer(pidx.tobytes())
        self.pin_inst = ctx.buffer(reserve=1024 * _PIN_STRIDE * 4, dynamic=True)
        self.pin_vao = ctx.vertex_array(self.pin_prog, [
            (self.pin_vbo, "3f", "in_vert"),
            (self.pin_inst, "3f 9f 2f 3f/i", "in_pos", "in_orient", "in_scale", "in_color"),
        ], self.pin_ibo)
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
        # Elevation is a DISPLACEMENT map, not something meant to be read
        # crisply up close -- blocky steps in a height field look like
        # terraced ground, where the whole point of relief is a smooth
        # rolling surface. Linear both ways, no mipmap asymmetry needed.
        self.tex_elev.repeat_x = True
        self.tex_elev.repeat_y = False
        self.tex_elev.filter = (moderngl.LINEAR, moderngl.LINEAR)

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

    def set_elevation(self, height_grid, sea_level):
        """Hand over world.height and world.sea_level -- the exact grid the
        flat map's own elevation shading reads, encoded as a single-channel
        texture the vertex shader displaces the sphere by (see ELEV_SCALE).

        Kept separate from set_map rather than folded into it: the height
        grid is static for the life of a world (worldgen never touches it
        again), while the map image and fog mask are re-rendered often, and
        this way callers who only need to refresh ownership colours never
        pay to re-encode elevation they already uploaded once.

        Also stored as a plain Python list (not just uploaded to the GPU):
        terrain_radius needs the same values on the CPU side, to place
        markers/lines/labels flush with the actual displayed relief."""
        self._height_grid = height_grid
        self._sea_level = float(sea_level)
        h, w = len(height_grid), (len(height_grid[0]) if height_grid else 1)
        arr = (np.asarray(height_grid, dtype="f8") * 255.0).clip(0, 255).astype("u1")
        self._elev_img = Image.frombytes("L", (w, h), arr.tobytes())
        self._elev_dirty = True

    def terrain_radius(self, cx, cy):
        """Local sphere radius at a map cell, including relief -- mirrors the
        vertex shader's own displacement formula exactly (land bulges by up
        to ELEV_SCALE, ocean stays flat), so anything anchored with this --
        markers, lines, labels -- sits flush with what is actually drawn
        rather than floating above a mountain or sinking into a bulge.

        Deliberately NOT consulted by pick(): ray-vs-true-terrain would need
        a per-triangle test instead of the cheap ray-vs-sphere one, and at
        ELEV_SCALE's few-percent exaggeration the picked cell is the same
        either way for all but a sliver of near-limb clicks right at a
        steep slope. Picking against the plain unit sphere is an accepted
        approximation, not an oversight."""
        grid = self._height_grid
        if not grid:
            return 1.0
        h, w = len(grid), len(grid[0])
        gy = min(max(int(cy), 0), h - 1)
        gx = int(cx) % w
        return 1.0 + ELEV_SCALE * max(0.0, grid[gy][gx] - self._sea_level)

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

    def set_pins(self, pins):
        """Settlements as real 3D geometry (see _pin_mesh) instead of the
        flat billboard discs set_markers draws -- a standing shape reads as
        'planted at this spot' from orbit or up close, where a billboard
        (which only ever faces the camera) reads as a flat sticker floating
        over the ground however you look at it.

        ``pins`` is [(cell_x, cell_y, radius, height, (r,g,b)), ...],
        `radius`/`height` in sphere-radius units -- same units set_markers'
        `size` already uses, so a caller sizing a city bigger than a village
        does not need a second, differently-scaled number for this."""
        n = len(pins)
        need = max(1, n) * _PIN_STRIDE
        if self._pins.size < need:
            self._pins = np.zeros(need, dtype="f4")
        d = self._pins
        for i, (cx, cy, radius, height, color) in enumerate(pins):
            anchor = self.cell_to_point(cx, cy)
            normal = anchor / (np.linalg.norm(anchor) or 1.0)
            orient = _align_y_to(normal)
            o = i * _PIN_STRIDE
            d[o:o + 3] = anchor
            d[o + 3:o + 12] = orient.astype("f4").ravel(order="F")
            d[o + 12] = radius
            d[o + 13] = height
            d[o + 14:o + 17] = color
        self._pin_count = n

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
        ctx = self.ctx
        if self._tex_dirty and self._map_img is not None:
            img = self._map_img
            recreated = self.tex_map.size != img.size
            if recreated:
                self.tex_map.release()
                self.tex_map = ctx.texture(img.size, 3, img.tobytes())
            else:
                self.tex_map.write(img.tobytes())
            fog = self._fog_img
            if fog is not None:
                if self.tex_fog.size != fog.size:
                    recreated = True
                    self.tex_fog.release()
                    self.tex_fog = ctx.texture(fog.size, 1, fog.tobytes())
                else:
                    self.tex_fog.write(fog.tobytes())
            self._configure_textures()
            if recreated:
                self._texture_just_created = True
            self._tex_dirty = False
        # Independent of the map/fog dirty flag -- set_elevation is called far
        # less often (the height grid never changes after worldgen) and has
        # its own flag so a plain ownership-colour refresh never re-encodes it.
        if self._elev_dirty and self._elev_img is not None:
            img = self._elev_img
            if self.tex_elev.size != img.size:
                self.tex_elev.release()
                self.tex_elev = ctx.texture(img.size, 1, img.tobytes())
            else:
                self.tex_elev.write(img.tobytes())
            self._configure_textures()
            self._elev_dirty = False

    # --- camera ---------------------------------------------------------------
    def eye(self):
        """Camera position: always exactly self.dist from the sphere's
        centre (so DIST_MIN/DIST_MAX keep meaning a literal distance), swung
        toward +Y by pitch_for_dist as the camera nears the surface. Always
        looking at the origin (redraw()/pick() both target (0,0,0)), so
        swinging eye off the Z axis is what actually produces an oblique
        view: the ray from an off-axis eye to dead centre no longer meets
        the sphere along that point's own surface normal."""
        theta = pitch_for_dist(self.dist)
        return np.array([0.0, self.dist * math.sin(theta),
                         self.dist * math.cos(theta)], dtype="f8")

    @property
    def zoom_level(self):
        """Which of the three map levels this altitude corresponds to."""
        if self.dist <= LEVEL_VILLAGE_DIST:
            return 2
        if self.dist <= LEVEL_REGION_DIST:
            return 1
        return 0

    def cell_to_point(self, cx, cy):
        """Map cell -> point on the UNROTATED sphere, AT ITS OWN TERRAIN
        RADIUS (see terrain_radius) -- every overlay built from this
        (markers, lines, labels) therefore sits flush with the actual
        displayed relief for free, not floating above a mountain or sinking
        into a bulge, without each of them needing their own elevation logic.

        Deliberately not rotated: every overlay program applies u_rot itself,
        so overlay geometry is uploaded once and stays glued to the terrain
        through a drag. Rotating here instead means a drag moves the planet out
        from under its own markers until the next set_* call."""
        w, h = self._world_size()
        lon = (cx + 0.5) / w * 2.0 * math.pi
        lat = v_to_lat((cy + 0.5) / h, self.merc_max)   # inverse of the shader
        r = self.terrain_radius(cx, cy)
        return r * np.array([math.cos(lat) * math.sin(lon), math.sin(lat),
                             math.cos(lat) * math.cos(lon)])

    def _world_size(self):
        img = self._map_img
        return img.size if img is not None else (1, 1)

    def cells_to_points(self, cells):
        """cell_to_point for a whole list at once, as an (n, 3) array.

        Used by visible_mask for culling, where terrain relief would only
        ever shift a point by a few percent of the sphere's radius -- nowhere
        near enough to change whether something is on-screen or over the
        horizon. Left at the base radius rather than threading the height
        grid through here too: a culling test has no need to be that exact."""
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

        The horizon test is dot(p, eye_dir) > 1/dist, not p.z > 0: the visible
        cap of a sphere seen from a finite distance is smaller than a
        hemisphere, and from low altitude it is *much* smaller. Written
        against the eye's own direction rather than the fixed Z axis because
        the camera can now pitch (see pitch_for_dist) -- eye is not always
        on the Z axis, and the old fixed-axis shortcut would silently start
        calling the wrong cap "visible" the moment it tilted."""
        n = len(cells)
        if n == 0:
            return np.zeros(0, dtype=bool)
        pts = self.cells_to_points(cells) @ self.rot.T
        eye_dir = self.eye()
        eye_dir = eye_dir / (np.linalg.norm(eye_dir) or 1.0)
        seen = pts.dot(eye_dir) > 1.0 / max(self.dist, 1.0 + 1e-6)
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
        ndc_x = (2.0 * sx / w - 1.0) * math.tan(fov / 2.0) * aspect
        ndc_y = (1.0 - 2.0 * sy / h) * math.tan(fov / 2.0)
        origin = self.eye()
        # Camera-space ray (camera looks down its own -Z), turned into WORLD
        # space via the same basis _look_at builds the view matrix from.
        # Assuming camera-space == world-space here (as this used to,
        # implicitly, before the camera could pitch) was only ever correct
        # because eye happened to always sit on the Z axis; it silently
        # pointed clicks the wrong way the moment eye could swing off it.
        right, up, forward = _camera_basis(origin, np.zeros(3),
                                           np.array([0.0, 1.0, 0.0]))
        direction = ndc_x * right + ndc_y * up + forward
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
            if self._texture_just_created:
                # See the flag's own comment (set in _upload_textures): the
                # frame just presented used a texture created this same call
                # and measured visibly wrong on this machine. A second FULL
                # display cycle -- not just a second draw call, an actual
                # repeat of tkMakeCurrent/redraw/tkSwapBuffers -- is what
                # reliably produced the correct frame when this was measured;
                # redrawing twice inside one cycle without re-presenting was
                # tried first and did NOT fix it, so whatever the underlying
                # driver quirk is, it apparently needs the buffer swap itself
                # to actually resolve. One extra full frame, exactly once per
                # world, not a per-frame cost.
                self._texture_just_created = False
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
        self.tex_elev.use(3)
        p = self.prog
        p["u_map"] = 0
        p["u_fog"] = 1
        p["u_elev"] = 3
        p["u_viewproj"].write(viewproj.T.tobytes())
        p["u_rot"].write(self.rot.astype("f4").T.tobytes())
        p["u_eye"].value = tuple(float(v) for v in eye)
        p["u_sun"].value = tuple(float(v) for v in self.sun)
        p["u_fog_on"].value = 1.0 if self._fog_img is not None else 0.0
        p["u_merc_max"].value = float(self.merc_max)
        p["u_lat_max"].value = float(self.lat_max)
        p["u_ice_lat"].value = float(self.lat_max - math.radians(ICE_BLEND_DEG))
        p["u_night"].value = float(self.night_strength)
        p["u_sea_level"].value = float(self._sea_level)
        p["u_elev_scale"].value = float(ELEV_SCALE)
        # Slow enough that a whole session's worth of drift is subtle --
        # this is texture, not weather simulation.
        p["u_cloud_t"].value = float((time.perf_counter() - self._start_time) * 0.015)
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

        # Pins are real geometry with their own depth extent -- depth WRITE
        # goes back on just for these, so two settlements (or a settlement
        # and a mountain) occlude each other correctly instead of z-fighting
        # the way the flat overlays above deliberately do.
        if self._pin_count:
            ctx.depth_mask = True
            pp = self.pin_prog
            pp["u_viewproj"].write(viewproj.T.tobytes())
            pp["u_rot"].write(rot)
            payload = self._pins[:self._pin_count * _PIN_STRIDE].tobytes()
            if len(payload) > self.pin_inst.size:
                self.pin_inst.orphan(len(payload))
            self.pin_inst.write(payload)
            self.pin_vao.render(moderngl.TRIANGLES,
                                vertices=self._pin_index_count,
                                instances=self._pin_count)
            ctx.depth_mask = False

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

    def face_cell(self, cx, cy):
        """Rotate the planet so this cell faces the camera dead-on -- used to
        give a NEW globe (no saved camera yet) a sensible first view: your
        own capital, not whatever the mesh's arbitrary default orientation
        happens to centre. Same "rotate point to +Z" construction _align_y_to
        uses for pin orientation, applied to the whole planet instead of one
        marker."""
        p = self.cell_to_point(cx, cy)
        n = p / (np.linalg.norm(p) or 1.0)
        z = np.array([0.0, 0.0, 1.0])
        v = np.cross(n, z)
        s = np.linalg.norm(v)
        c = float(np.dot(n, z))
        if s < 1e-9:
            self.rot = np.eye(3) if c > 0 else _axis_angle((1.0, 0.0, 0.0), math.pi)
            return
        vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
        self.rot = np.eye(3) + vx + vx.dot(vx) * ((1 - c) / (s * s))
