"""Render the globe headlessly-ish and save PNGs, one per zoom level.

The globe is the one part of this project that cannot be checked by a test that
returns a number: shaders only compile against a real GL context, and "the
overlays are in the right place" is a thing you have to look at. This opens the
real MapView on a real world, flies the camera to each altitude, and dumps what
the card actually drew.

    python dev/globe_shot.py dev/worlds/dev560.pkl [outdir]

Exits non-zero if the globe failed to come up at all, so it doubles as a smoke
test for the GL path -- a silent fallback to the flat map is otherwise invisible
(the same trap gl_battle.py documents).
"""
import os
import pickle
import sys
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

from app.ui import gl_globe
from app.ui.map_view import MapView
from app.world import commander as C

# (label, camera distance) -- one per zoom level, picked just inside each
# threshold so each shot is unambiguously in that level.
SHOTS = [
    ("world", gl_globe.DIST_DEFAULT),
    ("region", gl_globe.LEVEL_REGION_DIST - 0.05),
    ("village", gl_globe.LEVEL_VILLAGE_DIST - 0.05),
]


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = sys.argv[1]
    outdir = sys.argv[2] if len(sys.argv) > 2 else "dev/shots"
    os.makedirs(outdir, exist_ok=True)

    with open(path, "rb") as fh:
        world = pickle.load(fh)
    C.ensure_faction_commanders(world)
    # The saved worlds were played, not explored -- dev560 has 700 of its
    # 726,000 cells revealed, so with fog left alone every overlay here is
    # correctly, uselessly empty. This is a RENDERING check; lift the fog so
    # there is something to render. (Pass --fog to leave it as saved.)
    if "--fog" not in sys.argv:
        world.fog = bytearray(b"\xff" * (world.w * world.h))
        world.fog_fully_revealed = True
        world.fog_version = getattr(world, "fog_version", 0) + 1
        # Names are gated on CONTACT, not on fog (see MapView._is_known), so
        # lifting fog alone still leaves the map anonymous.
        world.discovered_factions = set(range(len(world.factions)))
    root = tk.Tk()
    root.geometry("1280x800")
    view = MapView(root, world, on_attack=lambda *a, **k: None,
                   on_end_turn=lambda *a, **k: None)
    view.pack(fill="both", expand=True)
    view.set_world(world)
    root.update()

    view._set_globe(True)
    root.update()
    if not view.globe_active:
        print("FAILED: globe would not start (no GL context?)")
        return 1
    g = view.globe
    if g is None or g.failed:
        print("FAILED: globe reported failure after start")
        return 1

    for label, dist in SHOTS:
        g.dist = dist
        # Twice. pyopengltk's _display swaps buffers at the end of every frame,
        # so reading ctx.screen straight afterwards returns the PREVIOUS frame
        # -- which quietly made every shot here one zoom level stale, and sent
        # a good half hour into "why are the villages missing".
        view.render()
        root.update()
        view.render()
        root.update()
        w, h = g._size()
        raw = g.ctx.screen.read(components=3)
        img = Image.frombytes("RGB", (w, h), raw).transpose(Image.FLIP_TOP_BOTTOM)
        out = os.path.join(outdir, f"globe_{label}.png")
        img.save(out)
        print(f"{label:8s} dist={dist:.2f} level={g.zoom_level} "
              f"lines={g._line_count:6d} marks={g._marker_count:5d} "
              f"glyphs={g._glyph_count:6d} -> {out}")

    root.destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
