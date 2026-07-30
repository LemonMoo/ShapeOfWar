"""The flat 2D map, GPU-rendered.

Same content the Tk/PIL flat map draws (MapView._base_img, the fog mask,
roads, markers, labels), redrawn through moderngl instead of PIL+Canvas so
its cost stops scaling with window resolution. Measured on a 300-region,
14-faction world: the PIL/Canvas path costs ~8ms/frame at 1280x800 but
~35-40ms/frame at 3840x2160 (see HANDOFF.md) -- Tk's Canvas is a CPU/software
rasterizer, and pushing a freshly-resized terrain image through it every
frame scales with pixel count. A GPU texture sample doesn't.

This reuses gl_globe.py's line/marker/text-glyph shaders directly rather
than reinventing them: they already take a generic (u_viewproj, u_rot)
uniform pair and place world-space points through it, so an orthographic
flat camera is simply u_rot = identity and u_viewproj = a 2D ortho matrix
built from MapView.view -- nothing in those shaders assumes a sphere. Only
the terrain itself gets a new, much simpler shader here: a textured quad,
no Mercator projection, no elevation displacement, no day/night/clouds --
this view is meant to match the existing flat map's look, not the globe's.

World-wrap seam: unlike the sphere (which wraps for free -- longitude is
circular), a flat orthographic quad needs the same trick the PIL renderer's
_wrapped_x_segments hand-rolls on the CPU. Here it's free too, just via a
different mechanism: the terrain texture has repeat_x=True (GL_REPEAT), and
the quad's texture-U coordinate is the UNWRAPPED world x divided by the
map's width -- sampling naturally wraps at the seam with no CPU-side
segment-splitting needed. Vector geometry (markers/lines/labels) has no
such free ride, since those are placed at real positions rather than
texture-sampled -- see _wrap_x.

Simplification kept from the first pass, deliberate and low-risk: no
standing 3D pins for settlements/villages/commanders (see the globe's
set_pins) -- a "planted spire" under a dead-on orthographic top-down camera
foreshortens to a blob, so it buys nothing here. Shape is instead carried
by a small self-contained marker shader (SHAPE_CIRCLE/TRIANGLE/SQUARE/
DIAMOND/HULL below) that reproduces the canvas's city/castle/town/
commander/ship silhouettes as a per-instance fragment-shader test -- not
shared with gl_globe.py's own plain-circle _MARK shader, so the working
globe is untouched by this.
"""
import math

import numpy as np

from app.ui import gl_globe as _glg

_HAVE_GL = _glg._HAVE_GL
OpenGLFrame = _glg.OpenGLFrame
moderngl = None
if _HAVE_GL:
    import moderngl


def gl_available():
    return _HAVE_GL


_TERRAIN_VERT = """
#version 330
uniform mat4 u_viewproj;
in vec2 in_pos;      // world coords, unwrapped (may lie outside [0, world_w))
in vec2 in_uv;       // texture coords; x may be outside [0,1) -- GL_REPEAT wraps it
out vec2 v_uv;
void main() {
    gl_Position = u_viewproj * vec4(in_pos, 0.0, 1.0);
    v_uv = in_uv;
}
"""

_TERRAIN_FRAG = """
#version 330
uniform sampler2D u_map;
uniform sampler2D u_fog;
uniform float u_fog_on;
in vec2 v_uv;
out vec4 f_color;
void main() {
    vec3 base = texture(u_map, v_uv).rgb;
    float hidden = texture(u_fog, v_uv).r * u_fog_on;
    // Same flat darkening the PIL renderer composites for unexplored
    // ground (MapView._FOG_HIDDEN_RGB) -- no cloud-cover flourish here,
    // this view matches the existing flat map rather than the globe.
    vec3 hidden_color = vec3(7.0 / 255.0, 9.0 / 255.0, 14.0 / 255.0);
    f_color = vec4(mix(base, hidden_color, hidden), 1.0);
}
"""

_IDENTITY3 = np.eye(3, dtype="f4")
_CLEAR_RGB = (13.0 / 255.0, 16.0 / 255.0, 23.0 / 255.0)   # theme.CANVAS, #0d1017

# Shape-aware marker billboard: a self-contained replacement for gl_globe's
# plain circular _MARK shader (not touching that one -- it's shared with the
# working, shipped globe, and this needs shapes the globe has no use for).
# One quad, one fragment-shader shape test per instance, selected by
# `in_shape` -- cheaper than separate draw calls per shape and the instance
# count here is always small (dozens to low hundreds).
SHAPE_CIRCLE = 0.0     # city, village, caravan, placement hint, construction, ring
SHAPE_TRIANGLE = 1.0   # castle, terrain-symbol glyphs
SHAPE_SQUARE = 2.0     # town
SHAPE_DIAMOND = 3.0    # commander
SHAPE_HULL = 4.0       # ship

_SHAPE_STRIDE = 8   # center(3) size(1) color(3) shape(1)

_SHAPE_VERT = """
#version 330
uniform mat4 u_viewproj;
uniform vec3 u_right;
uniform vec3 u_up;
in vec2 in_vert;
in vec3 in_center;
in float in_size;
in vec3 in_color;
in float in_shape;
out vec2 v_local;
out vec3 v_color;
out float v_shape;
void main() {
    vec3 p = in_center + (u_right * in_vert.x + u_up * in_vert.y) * in_size;
    gl_Position = u_viewproj * vec4(p, 1.0);
    v_local = in_vert;     // -0.5..0.5, this instance's own local quad space
    v_color = in_color;
    v_shape = in_shape;
}
"""

_SHAPE_FRAG = """
#version 330
in vec2 v_local;
in vec3 v_color;
in float v_shape;
out vec4 f_color;

float cross2(vec2 a, vec2 b) { return a.x * b.y - a.y * b.x; }

void main() {
    vec2 p = v_local;
    int shape = int(v_shape + 0.5);
    float alpha = 1.0;
    if (shape == 0) {
        // Soft-edged disc -- city/village/caravan/hint/construction/ring.
        float d = length(p) * 2.0;
        if (d > 1.0) discard;
        alpha = smoothstep(1.0, 0.75, d);
    } else if (shape == 1) {
        // Triangle, apex up -- castle, and (smaller/recoloured) terrain
        // symbol glyphs.
        vec2 A = vec2(0.0, -0.55), B = vec2(0.55, 0.5), C = vec2(-0.55, 0.5);
        float d1 = cross2(p - A, B - A);
        float d2 = cross2(p - B, C - B);
        float d3 = cross2(p - C, A - C);
        bool hasNeg = (d1 < 0.0) || (d2 < 0.0) || (d3 < 0.0);
        bool hasPos = (d1 > 0.0) || (d2 > 0.0) || (d3 > 0.0);
        if (hasNeg && hasPos) discard;
    } else if (shape == 2) {
        // Square -- town.
        if (max(abs(p.x), abs(p.y)) > 0.5) discard;
    } else if (shape == 3) {
        // Diamond -- commander.
        if (abs(p.x) + abs(p.y) > 0.55) discard;
    } else {
        // Hull -- ship: a narrow trapezoid, wider at the waterline (bottom)
        // than the deck (top), echoing _draw_ships' canvas polygon.
        float halfw = mix(0.32, 0.5, clamp((p.y + 0.5) / 0.9, 0.0, 1.0));
        if (abs(p.x) > halfw || p.y < -0.5 || p.y > 0.4) discard;
    }
    f_color = vec4(v_color, alpha);
}
"""


class GLFlatMapFrame(OpenGLFrame):
    """The flat map. A Tk widget dropping into the same layout slot
    MapView.canvas occupies (see MapView._ensure_flatgl) -- click/drag/wheel
    handlers bind onto it exactly as they do the canvas today, since they
    already work purely in terms of MapView.view/screen_to_world/
    world_to_screen, coordinate math with no idea what drew the pixels."""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.ctx = None
        self.animate = 0
        self._failed = False
        # Built here, not in _setup_gl: the atlas is plain PIL/font work,
        # not a GL resource (only uploading it as a texture needs a
        # context -- see _setup_gl) -- set_labels needs it to lay out
        # glyphs the moment MapView calls it, which can happen before this
        # widget's first real GL frame (a bound <Configure> firing as soon
        # as it's packed, ahead of pyopengltk's own lazy initgl()).
        self.atlas = _glg._FontAtlas.shared()
        self._map_img = None
        self._fog_img = None
        self._tex_dirty = True
        self._view = (0.0, 0.0, 1.0, 1.0)      # vx0, vy0, vx1, vy1 -- see set_view
        self._view_center_x = 0.5
        self._world_w = 1
        self._world_h = 1
        self._lines = np.zeros(0, dtype="f4")
        self._line_count = 0
        self._markers = np.zeros(0, dtype="f4")
        self._marker_count = 0
        self._glyphs = np.zeros(0, dtype="f4")
        self._glyph_count = 0
        # Repack cache for set_lines/set_markers/set_labels -- see their own
        # comments. `_wrap_bucket()` is which "copy" of the world-wrap the
        # current camera is closest to; it only changes when the camera
        # actually crosses the seam, which ordinary panning almost never
        # does, so most frames can skip re-wrapping and re-packing entirely
        # and just keep last frame's buffer as-is.
        self._lines_src = None
        self._lines_wrap_bucket = None
        self._markers_src = None
        self._markers_wrap_bucket = None
        self._labels_src = None
        self._labels_wrap_bucket = None

    # --- lifecycle --------------------------------------------------------
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
        self.prog = ctx.program(vertex_shader=_TERRAIN_VERT,
                                fragment_shader=_TERRAIN_FRAG)
        # 4 verts * (pos.xy + uv.xy) f4 -- rewritten in full every frame
        # (set_view/redraw), so a plain dynamic buffer, no instancing needed
        # for a single quad.
        self.quad_vbo = ctx.buffer(reserve=4 * 4 * 4, dynamic=True)
        self.quad_vao = ctx.vertex_array(
            self.prog, [(self.quad_vbo, "2f 2f", "in_pos", "in_uv")])
        self.tex_map = ctx.texture((1, 1), 3, b"\x20\x28\x38")
        self.tex_fog = ctx.texture((1, 1), 1, b"\x00")
        self._configure_textures()

        # Lines, markers and text: gl_globe's own programs and vertex
        # layouts, reused verbatim -- see this module's docstring.
        self.line_prog = ctx.program(vertex_shader=_glg._LINE_VERT,
                                     fragment_shader=_glg._LINE_FRAG)
        seg = np.array([0, -1, 1, -1, 0, 1,
                        1, -1, 1, 1, 0, 1], dtype="f4")
        self.line_quad = ctx.buffer(seg.tobytes())
        self.line_inst = ctx.buffer(reserve=4096 * _glg._LINE_STRIDE * 4, dynamic=True)
        self.line_vao = ctx.vertex_array(self.line_prog, [
            (self.line_quad, "2f", "in_vert"),
            (self.line_inst, "3f 3f 3f 1f/i", "in_a", "in_b", "in_color", "in_width"),
        ])

        self.mark_prog = ctx.program(vertex_shader=_SHAPE_VERT,
                                     fragment_shader=_SHAPE_FRAG)
        mquad = np.array([-0.5, -0.5, 0.5, -0.5, -0.5, 0.5,
                          0.5, -0.5, 0.5, 0.5, -0.5, 0.5], dtype="f4")
        self.mark_quad = ctx.buffer(mquad.tobytes())
        self.mark_inst = ctx.buffer(reserve=4096 * _SHAPE_STRIDE * 4, dynamic=True)
        self.mark_vao = ctx.vertex_array(self.mark_prog, [
            (self.mark_quad, "2f", "in_vert"),
            (self.mark_inst, "3f 1f 3f 1f/i", "in_center", "in_size",
             "in_color", "in_shape"),
        ])

        self.text_prog = ctx.program(vertex_shader=_glg._TEXT_VERT,
                                     fragment_shader=_glg._TEXT_FRAG)
        unit = np.array([0, 0, 1, 0, 0, 1, 1, 0, 1, 1, 0, 1], dtype="f4")
        self.text_quad = ctx.buffer(unit.tobytes())
        self.text_inst = ctx.buffer(reserve=4096 * _glg._GLYPH_STRIDE * 4, dynamic=True)
        self.text_vao = ctx.vertex_array(self.text_prog, [
            (self.text_quad, "2f", "in_vert"),
            (self.text_inst, "3f 2f 2f 4f 3f/i", "in_anchor", "in_offset",
             "in_size", "in_uv", "in_color"),
        ])
        self.tex_text = ctx.texture(self.atlas.size, 1, self.atlas.image.tobytes())
        self.tex_text.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.tex_text.repeat_x = False
        self.tex_text.repeat_y = False

        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA

    def _configure_textures(self):
        # repeat_x=True is what makes the world-wrap seam free -- see the
        # module docstring.
        self.tex_map.repeat_x = True
        self.tex_map.repeat_y = False
        self.tex_map.filter = (moderngl.LINEAR, moderngl.NEAREST)
        self.tex_fog.repeat_x = True
        self.tex_fog.repeat_y = False
        self.tex_fog.filter = (moderngl.NEAREST, moderngl.NEAREST)

    # --- content ------------------------------------------------------------
    def set_map(self, map_img, fog_img=None):
        """Hand over the flat map's own raster (PIL RGB, exactly
        world.w x world.h) and fog mask ("L"). Cheap -- upload happens lazily
        on the next redraw, and ONLY when the image actually changed:
        MapView._sync_flatgl calls this on every single render() (including
        every frame of a pan/zoom drag), passing MapView._base_img/
        _fog_overlay_img straight through -- those are themselves cached
        (MapView._ensure_base/_ensure_fog_overlay only rebuild on a real
        content change), so most calls hand back the EXACT SAME object as
        last time. Marking dirty unconditionally here re-encoded and
        re-uploaded the whole terrain texture to the GPU every frame
        regardless -- real, avoidable cost (a multi-megabyte tobytes() plus
        a GPU texture write) that this identity check skips entirely on the
        overwhelmingly common case where nothing changed."""
        if map_img is not self._map_img or fog_img is not self._fog_img:
            self._map_img = map_img
            self._fog_img = fog_img
            self._tex_dirty = True
        if map_img is not None:
            self._world_w, self._world_h = map_img.size

    def set_view(self, vx0, vy0, vx1, vy1):
        """The exact rect MapView.render() computes via _fit_aspect -- this
        frame draws exactly what that rect frames, nothing more, nothing
        the flat canvas wouldn't also show at the same camera position."""
        self._view = (vx0, vy0, vx1, vy1)
        self._view_center_x = (vx0 + vx1) / 2.0

    def _wrap_x(self, x):
        """Same rule MapView.world_to_screen uses: shift x by whichever
        multiple of the world's width puts it closest to the current view
        centre, so a marker/line point near the seam lands on the correct
        near side instead of potentially far off the unwrapped view rect."""
        w = self._world_w
        k = round((self._view_center_x - x) / w)
        return x + k * w

    def _wrap_bucket(self):
        """Which world-wrap 'copy' the camera is currently closest to, as a
        plain integer -- changes only when the camera actually crosses the
        seam (world_w away from wherever it started), which ordinary
        panning within an explored area essentially never does. Used by
        set_lines/set_markers/set_labels to skip re-wrapping and re-packing
        entirely on a frame where nothing that could change the result --
        neither the content nor this bucket -- has changed. A coarser
        approximation than re-checking every individual point's own
        _wrap_x result, but a safe one: every point _wrap_x is ever asked
        to place is drawn from the current viewport, which is never wider
        than the world itself, so they all round to the same bucket (or an
        adjacent one right at the seam, corrected the moment the bucket
        itself changes)."""
        return round(self._view_center_x / max(1, self._world_w))

    def set_lines(self, paths):
        """paths: [(cells, (r,g,b), width_px, dash), ...] -- the exact shape
        MapView._map_lines already builds (shared with the globe).

        Skips the rebuild entirely when both `paths` (checked by identity,
        not equality -- MapView._sync_flatgl hands back the exact same
        cached list object when nothing changed, see its own content cache)
        and the wrap bucket are unchanged from the last call: panning alone
        changes neither, so this is the common case during a drag, not an
        edge case."""
        bucket = self._wrap_bucket()
        if paths is self._lines_src and bucket == self._lines_wrap_bucket:
            return
        self._lines_src = paths
        self._lines_wrap_bucket = bucket
        segs = []
        for cells, color, width, dash in paths:
            if len(cells) < 2:
                continue
            step = max(1, int(dash) if dash else 1)
            pts = [(self._wrap_x(cx), cy) for cx, cy in cells]
            for i in range(0, len(pts) - 1, step):
                segs.append((pts[i], pts[i + 1], color, width))
        n = len(segs)
        need = max(1, n) * _glg._LINE_STRIDE
        if self._lines.size < need:
            self._lines = np.zeros(need, dtype="f4")
        d = self._lines
        for i, ((ax, ay), (bx, by), color, width) in enumerate(segs):
            o = i * _glg._LINE_STRIDE
            d[o:o + 3] = (ax, ay, 0.0)
            d[o + 3:o + 6] = (bx, by, 0.0)
            d[o + 6:o + 9] = color
            d[o + 9] = width
        self._line_count = n

    def set_markers(self, marks):
        """marks: [(cell_x, cell_y, size_world_units, (r,g,b), shape), ...]
        -- see MapView._flat_markers for how `size` is derived so a marker
        reads at the same screen size the Tk canvas already draws it at, and
        for the SHAPE_* constants (module-level here) each marker kind maps
        to.

        Same identity+wrap-bucket skip as set_lines -- see its docstring."""
        bucket = self._wrap_bucket()
        if marks is self._markers_src and bucket == self._markers_wrap_bucket:
            return
        self._markers_src = marks
        self._markers_wrap_bucket = bucket
        n = len(marks)
        need = max(1, n) * _SHAPE_STRIDE
        if self._markers.size < need:
            self._markers = np.zeros(need, dtype="f4")
        d = self._markers
        for i, (cx, cy, size, color, shape) in enumerate(marks):
            o = i * _SHAPE_STRIDE
            d[o:o + 3] = (self._wrap_x(cx), cy, 0.0)
            d[o + 3] = size
            d[o + 4:o + 7] = color
            d[o + 7] = shape
        self._marker_count = n

    def set_labels(self, labels):
        """labels: [(cell_x, cell_y, text, (r,g,b), px, dy), ...] -- the
        exact shape MapView._map_labels/_flat_labels_extra build.

        Same identity+wrap-bucket skip as set_lines -- see its docstring."""
        bucket = self._wrap_bucket()
        if labels is self._labels_src and bucket == self._labels_wrap_bucket:
            return
        self._labels_src = labels
        self._labels_wrap_bucket = bucket
        atlas = self.atlas
        glyphs = []
        for cx, cy, text, color, px, dy in labels:
            if not text:
                continue
            anchor = (self._wrap_x(cx), cy, 0.0)
            pen0 = -0.5 * atlas.width_of(text, px)
            gw, gh = px * atlas.aspect, px
            for shade, col in ((_glg.LABEL_SHADOW_PX, _glg.LABEL_SHADOW_COLOR),
                              (0.0, color)):
                pen = pen0
                for ch in text:
                    if ch not in atlas.uv:
                        ch = _glg._FALLBACK_CHAR
                    if ch != " ":
                        glyphs.append((anchor, (pen + shade, dy + shade),
                                      (gw, gh), atlas.uv[ch], col))
                    pen += px * atlas.advance[ch]
        n = len(glyphs)
        need = max(1, n) * _glg._GLYPH_STRIDE
        if self._glyphs.size < need:
            self._glyphs = np.zeros(need, dtype="f4")
        d = self._glyphs
        for i, (anchor, offset, size, uv, color) in enumerate(glyphs):
            o = i * _glg._GLYPH_STRIDE
            d[o:o + 3] = anchor
            d[o + 3:o + 5] = offset
            d[o + 5:o + 7] = size
            d[o + 7:o + 11] = uv
            d[o + 11:o + 14] = color
        self._glyph_count = n

    # --- picking --------------------------------------------------------------
    def screen_to_cell(self, sx, sy):
        """Screen pixel -> world cell, x wrapped into [0, world_w) -- the
        direct orthographic inverse of set_view, matching
        MapView.screen_to_world exactly (same view rect, same wrap rule)."""
        w, h = self._size()
        vx0, vy0, vx1, vy1 = self._view
        gx = vx0 + sx / w * (vx1 - vx0)
        gy = vy0 + sy / h * (vy1 - vy0)
        ww = max(1, self._world_w)
        return (int(math.floor(gx)) % ww, int(math.floor(gy)))

    # --- drawing ----------------------------------------------------------
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

    @staticmethod
    def _ortho(l, r, b, t):
        """Standard 2D orthographic projection, world units -> NDC. Passing
        b=vy1 (bottom of the view rect) and t=vy0 (top) rather than the
        other way round is what makes world +y (which points DOWN, same as
        screen y) come out as NDC -y -- the same flip world_to_screen's own
        (gy - vy0) * scale gives for free by just being screen-space math."""
        m = np.zeros((4, 4), dtype="f4")
        m[0, 0] = 2.0 / (r - l)
        m[1, 1] = 2.0 / (t - b)
        m[2, 2] = -1.0
        m[3, 3] = 1.0
        m[0, 3] = -(r + l) / (r - l)
        m[1, 3] = -(t + b) / (t - b)
        return m

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
        ctx.clear(*_CLEAR_RGB)
        self._upload_textures()

        vx0, vy0, vx1, vy1 = self._view
        viewproj = self._ortho(vx0, vx1, vy1, vy0)

        # Terrain: one quad, clipped to the world's actual y-extent (x is
        # left unclipped -- GL_REPEAT wraps it, see the module docstring).
        # Nothing draws below/above the map's real edges, matching the PIL
        # renderer leaving bare canvas background there instead of smearing
        # edge pixels.
        wy0, wy1 = max(0.0, vy0), min(float(self._world_h), vy1)
        if wy1 > wy0 and self._map_img is not None:
            u0, u1 = vx0 / self._world_w, vx1 / self._world_w
            v0, v1 = wy0 / self._world_h, wy1 / self._world_h
            verts = np.array([
                vx0, wy0, u0, v0,
                vx1, wy0, u1, v0,
                vx0, wy1, u0, v1,
                vx1, wy1, u1, v1,
            ], dtype="f4")
            self.quad_vbo.write(verts.tobytes())
            self.tex_map.use(0)
            self.tex_fog.use(1)
            p = self.prog
            p["u_map"] = 0
            p["u_fog"] = 1
            p["u_viewproj"].write(viewproj.T.tobytes())
            p["u_fog_on"].value = 1.0 if self._fog_img is not None else 0.0
            self.quad_vao.render(moderngl.TRIANGLE_STRIP)

        rot = _IDENTITY3.T.tobytes()
        px2ndc = (2.0 / max(1, w), 2.0 / max(1, h))

        if self._line_count:
            lp = self.line_prog
            lp["u_viewproj"].write(viewproj.T.tobytes())
            lp["u_rot"].write(rot)
            lp["u_px2ndc"].value = px2ndc
            payload = self._lines[:self._line_count * _glg._LINE_STRIDE].tobytes()
            if len(payload) > self.line_inst.size:
                self.line_inst.orphan(len(payload))
            self.line_inst.write(payload)
            self.line_vao.render(moderngl.TRIANGLES, vertices=6,
                                 instances=self._line_count)

        if self._marker_count:
            mp = self.mark_prog
            mp["u_viewproj"].write(viewproj.T.tobytes())
            mp["u_right"].value = (1.0, 0.0, 0.0)
            mp["u_up"].value = (0.0, 1.0, 0.0)
            payload = self._markers[:self._marker_count * _SHAPE_STRIDE].tobytes()
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
            payload = self._glyphs[:self._glyph_count * _glg._GLYPH_STRIDE].tobytes()
            if len(payload) > self.text_inst.size:
                self.text_inst.orphan(len(payload))
            self.text_inst.write(payload)
            self.text_vao.render(moderngl.TRIANGLES, vertices=6,
                                 instances=self._glyph_count)
