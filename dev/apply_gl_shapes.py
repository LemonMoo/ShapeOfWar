"""One-shot apply of the GL terrain-shape edits to app/ui/gl_flatmap.py.

Same rationale as dev/apply_terrain_redesign.py: the desktop host restores
files from a stale buffer, so apply everything atomically in one write.

Run from the repo root:  python dev/apply_gl_shapes.py
"""
import io
import sys

PATH = "app/ui/gl_flatmap.py"
src = io.open(PATH, encoding="utf-8").read()
orig_len = len(src)

EDITS = [
    ('''SHAPE_CIRCLE = 0.0     # city, village, caravan, placement hint, construction, ring
SHAPE_TRIANGLE = 1.0   # castle, terrain-symbol glyphs
SHAPE_SQUARE = 2.0     # town
SHAPE_DIAMOND = 3.0    # commander
SHAPE_HULL = 4.0       # ship''',
     '''SHAPE_CIRCLE = 0.0     # city, village, caravan, placement hint, construction, ring
SHAPE_TRIANGLE = 1.0   # castle, mountain/highland terrain peaks
SHAPE_SQUARE = 2.0     # town
SHAPE_DIAMOND = 3.0    # commander
SHAPE_HULL = 4.0       # ship
SHAPE_TREE = 5.0       # pine tree (forest/taiga/jungle terrain glyph)
SHAPE_MOUND = 6.0      # low mound (tundra scrub, dunes)
SHAPE_BLADES = 7.0     # grass/reed tuft (swamp/steppe/savannah terrain glyph)
SHAPE_CACTUS = 8.0     # saguaro (desert terrain glyph)'''),

    ('''    if (shape == 0) {
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
}''',
     '''    if (shape == 0) {
        // Soft-edged disc -- city/village/caravan/hint/construction/ring.
        float d = length(p) * 2.0;
        if (d > 1.0) discard;
        alpha = smoothstep(1.0, 0.75, d);
    } else if (shape == 1) {
        // Triangle, apex up -- castle, and the mountain/highland terrain
        // glyphs (differently coloured/sized).
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
    } else if (shape == 4) {
        // Hull -- ship: a narrow trapezoid, wider at the waterline (bottom)
        // than the deck (top), echoing _draw_ships' canvas polygon.
        float halfw = mix(0.32, 0.5, clamp((p.y + 0.5) / 0.9, 0.0, 1.0));
        if (abs(p.x) > halfw || p.y < -0.5 || p.y > 0.4) discard;
    } else if (shape == 5) {
        // Pine tree (forest/taiga/jungle terrain glyph): an apex-up
        // triangle over a short trunk -- the canvas conifer cluster's
        // silhouette in miniature.
        vec2 A = vec2(0.0, -0.55), B = vec2(0.52, 0.42), C = vec2(-0.52, 0.42);
        float d1 = cross2(p - A, B - A);
        float d2 = cross2(p - B, C - B);
        float d3 = cross2(p - C, A - C);
        bool hasNeg = (d1 < 0.0) || (d2 < 0.0) || (d3 < 0.0);
        bool hasPos = (d1 > 0.0) || (d2 > 0.0) || (d3 > 0.0);
        if (hasNeg && hasPos) discard;
        if (p.y > 0.42 && !(p.y < 0.62 && abs(p.x) < 0.1)) discard;
    } else if (shape == 6) {
        // Low mound (tundra scrub / dune): the upper half of a disc.
        if (p.y < -0.05 || length(p) > 0.55) discard;
    } else if (shape == 7) {
        // Grass/reed tuft (swamp/steppe/savannah): three thin vertical
        // diamonds side by side.
        bool hit = false;
        for (int i = -1; i <= 1; i++) {
            vec2 q = vec2(p.x - float(i) * 0.22, p.y + 0.1);
            if (abs(q.x) + abs(q.y) * 1.6 < 0.1 && q.y < 0.6) hit = true;
        }
        if (!hit) discard;
    } else if (shape == 8) {
        // Cactus (desert): a trunk plus one up-reaching arm.
        bool hit = false;
        if (abs(p.x) < 0.16 && p.y > -0.5 && p.y < 0.52) hit = true;
        if (p.x > 0.12 && p.x < 0.4 && p.y > -0.32 && p.y < -0.1) hit = true;
        if (p.x > 0.26 && p.x < 0.4 && p.y > -0.62 && p.y < -0.3) hit = true;
        if (!hit) discard;
    } else {
        discard;   // unknown shape id -- nothing to draw
    }
    f_color = vec4(v_color, alpha);
}'''),
]

for i, (old, new) in enumerate(EDITS, 1):
    n = src.count(old)
    if n != 1:
        print(f"EDIT {i}: expected exactly 1 occurrence, found {n}")
        sys.exit(1)
    src = src.replace(old, new)

with io.open(PATH, "w", encoding="utf-8", newline="") as fh:
    fh.write(src.replace("\n", "\r\n"))
print(f"applied {len(EDITS)} edits: {orig_len} -> {len(src)} bytes -> {PATH}")
