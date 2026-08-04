"""Verify a built ShapesOfWar.exe actually contains the v0.17.0 code.

PyInstaller onefile exes store modules as marshal'd code objects inside a
zlib-compressed PYZ archive, so plain string grep finds nothing. This opens
the CArchive, loads the PYZ, and searches the code objects' co_consts for
marker strings that only exist in the new code.
"""
import os
import sys

from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader

EXE = sys.argv[1] if len(sys.argv) > 1 else "dist/ShapesOfWar.exe"
MARKERS = [
    # (module, string that must appear in its code constants)
    ("app.ui.map_view", "World-static inputs to the texture pass"),
    ("app.ui.map_view", "parked in _pending_tracks"),
    ("app.ui.map_view", "_flat_static_markers"),
    ("app.core.changelog", "A World That Holds Together"),
]

arch = CArchiveReader(EXE)
# PyInstaller 6.x onefile: the PYZ is embedded inside the PKG, not the EXE's
# top-level archive, so go two levels down. The ZlibArchiveReader stays bound
# to the pkg file for its whole lifetime, so it must outlive the extraction.
pkg_path = EXE + ".pkg"
with open(pkg_path, "wb") as fh:
    fh.write(arch.raw_pkg_data())
pkg = CArchiveReader(pkg_path)
z = pkg.open_embedded_archive("PYZ.pyz")

found = {}
for mod in z.toc:
    if mod.startswith("app.") and mod.count(".") <= 2:
        try:
            code = z.extract(mod)
            consts = []

            def walk(c):
                if c is None:
                    return
                if isinstance(c, tuple):
                    for x in c:
                        walk(x)
                elif hasattr(c, "co_consts"):
                    for x in c.co_consts:
                        walk(x)
                elif isinstance(c, str):
                    consts.append(c)

            walk(code)
            found[mod] = set(consts)
        except Exception:
            pass

try:
    os.remove(pkg_path)
except OSError:
    pass

ok = True
for mod, marker in MARKERS:
    present = any(marker in s for s in found.get(mod, ()))
    print(f"  {'ok  ' if present else 'MISS'}  {mod}: {marker!r}")
    ok = ok and present
print("EXE CONTAINS v0.17.0 CODE" if ok else "EXE IS MISSING v0.17.0 CODE")
sys.exit(0 if ok else 1)
