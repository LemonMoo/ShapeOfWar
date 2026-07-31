"""Shared OpenGL plumbing for the GPU map.

Extracted from gl_globe.py when the globe view was removed. Everything here
is projection-agnostic -- the moderngl/pyopengltk availability probe, the
line and text shaders, and the font atlas -- and none of it ever knew it was
drawing a sphere. gl_flatmap.py was already importing exactly these pieces
out of the globe module rather than duplicating them, which is what made
deleting the globe a matter of moving them somewhere honest.
"""
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

# A grid wastes a little space next to a tight packing, but it makes a glyph's
# UV rect pure arithmetic from its index -- and map text is a few
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

LABEL_SHADOW_PX = 1.4
LABEL_SHADOW_COLOR = (0.03, 0.03, 0.05)


class _FontAtlas:
    """Rasterised glyphs plus the metrics to lay them out. Built once, lazily,
    and shared by every GL frame -- building it costs a few milliseconds of PIL
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
