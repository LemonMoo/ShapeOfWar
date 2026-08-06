"""Verify a built ShapesOfWar.exe actually contains the intended code.

PyInstaller onefile exes store modules as marshal'd code objects inside a
zlib-compressed PYZ (embedded in the PKG in PyInstaller 6.x), so plain string
grep finds nothing. This opens the CArchive -> PKG -> PYZ chain and searches
the code objects for release markers.

Markers are matched two ways, because not every change leaves a string
literal:
  const  a substring of any string constant (docstrings, literals)
  name   a name referenced anywhere (co_names) -- for attribute/global
         references like timeBeginPeriod, which never appear as constants.

Usage: python dev/verify_exe_code.py [path-to-ShapesOfWar.exe]
"""
import os
import sys

from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader

EXE = sys.argv[1] if len(sys.argv) > 1 else "dist/ShapesOfWar.exe"
MARKERS = [
    # (module, marker, kind) -- update the version markers with each release.
    ("app.ui.map_view", "parked in _pending_tracks", "const"),
    ("app.ui.gl_flatmap", "wglSwapIntervalEXT", "const"),
    ("app.ui.app", "timeBeginPeriod", "name"),
    ("app.ui.gl_common", "math", "name"),
    ("app.world.trade", "same contract as run_regional_trade_steps", "const"),
    ("app.world.resources", "Yields \"households\" between region chunks", "const"),
    ("app.ui.map_view", "the frame that runs one of the day's unsplittable phases", "const"),
    ("app.core.changelog", "The World Is Thinking", "const"),
    # v0.18.0 -- the settlement-first world.
    ("app.ui.map_view", "Choose its character", "const"),
    ("app.world.expansion", "Your realm is still growing", "const"),
    ("app.core.changelog", "The Settlement-First World", "const"),
    ("app.core.changelog", "burns its coal in Winter", "const"),
    # v0.18.1 -- the ladder.
    ("app.ui.map_view", "Found Village...", "const"),
    ("app.ui.map_view", "Raise to Town", "const"),
    ("app.world.construction", "the settlement-first ladder's first rung", "const"),
    ("app.core.changelog", "The Ladder", "const"),
    # v0.18.2 -- the compendium pass.
    ("app.ui.compendium_data", "Founding & Growth", "const"),
    ("app.ui.compendium_data", "THE DEVELOPMENT GATE", "const"),
    ("app.core.changelog", "The Compendium Pass", "const"),
    # v0.18.3 -- dated ledger.
    ("app.ui.map_view", "Season/day/year for any turn number", "const"),
    ("app.core.changelog", "Dated Ledger", "const"),
    # v0.18.4 -- earned growth (population-gated ladder).
    ("app.world.construction", "VILLAGE_RAISE_POPULATION_FRACTION", "name"),
    ("app.world.construction", "TOWN_UPGRADE_POPULATION_FRACTION", "name"),
    ("app.world.construction", "isn't big enough yet", "const"),
    ("app.world.construction", "populous enough yet", "const"),
    ("app.world.resources", "FRONTIER_POPULATION_GROWTH_RATE", "name"),
    ("app.core.changelog", "Earned Growth", "const"),
    # v0.18.5 -- settlement characters.
    ("app.world.resources", "SETTLEMENT_CHARACTERS", "name"),
    ("app.world.resources", "GARRISON_LEVY_EXTRA", "name"),
    ("app.world.resources", "settlement_character", "name"),
    ("app.world.construction", "_ai_pick_character", "name"),
    ("app.core.changelog", "A Character of Its Own", "const"),
    # v0.18.6 -- the realm chronicle + seed reproducibility.
    ("app.world.chronicle", "turn_date_text", "name"),
    ("app.world.chronicle", "CHRONICLE_CAP", "name"),
    ("app.world.construction", "Your settlers found", "const"),
    ("app.world.expansion", "is secured", "const"),
    ("app.world.worldgen", "The whole game is reproducible", "const"),
    ("app.core.changelog", "The Realm Chronicle", "const"),
    # v0.18.7 -- the frontier.
    ("app.world.frontier", "FRONTIER_WINDOW_TURNS", "name"),
    ("app.world.frontier", "The bandits take", "const"),
    ("app.world.frontier", "The hermit's blessing", "const"),
    ("app.core.clock", "FRONTIER", "name"),
    ("app.ui.frontier_dialog", "FrontierDialog", "name"),
    ("app.core.changelog", "The Frontier", "const"),
    # v0.18.8 -- the seat of the realm.
    ("app.world.worldgen", "is_capital", "name"),
    ("app.world.resources", "FRONTIER_POPULATION_GROWTH_RATE", "name"),
    ("app.ui.map_view", "Seat of the Realm", "const"),
    ("app.core.changelog", "The Seat of the Realm", "const"),
    # v0.18.9 -- season news.
    ("app.world.news", "compose_season_news", "name"),
    ("app.world.news", "raised a new Town", "const"),
    ("app.world.resources", "season_news", "name"),
    ("app.core.changelog", "Season News", "const"),
    # v0.18.10 -- rivers run true (slope-weighted D8).
    ("app.world.worldgen", "_SQRT2", "name"),
    ("app.world.worldgen", "drainage hydrology", "const"),
    ("app.core.changelog", "Rivers Run True", "const"),
    # v0.18.11 -- claims + village roads.
    ("app.world.expansion", "A claim is already underway there.", "const"),
    ("app.world.expansion", "CLAIM_DEVELOPMENT_FRACTION", "name"),
    ("app.world.expansion", "advance_claims_steps", "name"),
    ("app.world.commander", "commander_can_reach", "name"),
    ("app.world.construction", "_connect_new_village_to_region", "name"),
    ("app.ui.map_view", "march them to the frontier first", "const"),
    ("app.core.changelog", "Claims That Work, Villages That Connect", "const"),
    # v0.18.12 -- the underground capital.
    ("app.world.holds", "_place_gate_town", "name"),
    ("app.world.holds", "_fallback_surface_capital", "name"),
    ("app.world.holds", "_cache_network_terraces", "name"),
    ("app.world.holds", "under_capital", "name"),
    ("app.world.holds", "beneath the mountains.", "const"),
    ("app.world.resources", "under_capital", "const"),
    ("app.world.startsites", "_under_key", "name"),
    ("app.world.worldgen", "UNDERGROUND_SPECIES", "name"),
    ("app.core.changelog", "Under the Mountain", "const"),
    # v0.18.13 -- the gate lifeline + blockade.
    ("app.world.resources", "run_gate_logistics", "name"),
    ("app.world.resources", "_faction_gate_link", "name"),
    ("app.world.resources", "gate_blocked", "name"),
    ("app.world.resources", "GATE_CARAVAN_QUANTITY", "name"),
    ("app.world.resources", "The underground realm's supply line", "const"),
    ("app.core.changelog", "The Door", "const"),
    # v0.18.14 -- player raids, tunnels, depth.
    ("app.world.holds", "player_raid", "name"),
    ("app.world.holds", "raid_target_summary", "name"),
    ("app.world.holds", "TunnelProject", "name"),
    ("app.world.holds", "_nearest_unclaimed_network", "name"),
    ("app.world.holds", "advance_tunnel_projects", "name"),
    ("app.world.holds", "A new gallery opens beneath the mountain.", "const"),
    ("app.world.resources", "under_depth_info", "name"),
    ("app.world.resources", "UNDER_DEPTH_TIERS", "name"),
    ("app.core.changelog", "Deeper and Further", "const"),
    # v0.18.15 -- the under view leaks nothing of the overworld.
    ("app.ui.map_view", "fog_version", "const"),
    ("app.ui.map_view", "_under_pixels", "name"),
    ("app.core.changelog", "No Windows on the Ceiling", "const"),
    # v0.18.16 -- the rest of the under-view leaks (weather/attack/roads/
    # alert badges/panel biome/fog overlay).
    ("app.ui.map_view", "Cavern galleries", "const"),
    ("app.core.changelog", "No Windows on the Ceiling (2)", "const"),
    # v0.18.17 -- the capital's own front gate.
    ("app.world.holds", "is_capital_door", "const"),
    ("app.world.holds", "Front Gate", "const"),
    ("app.core.changelog", "The Front Gate", "const"),
    # v0.18.18 -- the wrap seam is a wandering deep channel.
    ("app.core.changelog", "The Map Is a Seamless Sea", "const"),
    # v0.18.19 -- the New Game preview: mountain doors, bigger map, no
    # stray default ring.
    ("app.core.changelog", "The Mountain Doors", "const"),
    # v0.18.20 -- the realm's own door, and no surface vision below.
    ("app.core.changelog", "The Realm's Own Door", "const"),
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
            consts, names = [], []

            def walk(c):
                if c is None:
                    return
                if isinstance(c, tuple):
                    for x in c:
                        walk(x)
                elif hasattr(c, "co_consts"):
                    for x in c.co_consts:
                        walk(x)
                    names.extend(c.co_names)
                    # A nested def's own name lives in co_name, and a closure
                    # reference (LOAD_DEREF) is addressed by its co_freevars
                    # index, not by co_names -- without these two, a marker
                    # like startsites' _under_key (a local def captured by a
                    # lambda) is invisible to the verifier.
                    if c.co_name:
                        names.append(c.co_name)
                    names.extend(c.co_freevars)
                elif isinstance(c, str):
                    consts.append(c)

            walk(code)
            found[mod] = (set(consts), set(names))
        except Exception:
            pass

try:
    os.remove(pkg_path)
except OSError:
    pass

ok = True
for mod, marker, kind in MARKERS:
    consts, names = found.get(mod, (set(), set()))
    present = (any(marker in s for s in consts) if kind == "const"
               else marker in names)
    print(f"  {'ok  ' if present else 'MISS'}  {mod}: {marker!r} ({kind})")
    ok = ok and present
print(f"EXE CONTAINS THE INTENDED CODE ({EXE})" if ok
      else f"EXE IS MISSING THE INTENDED CODE ({EXE})")
sys.exit(0 if ok else 1)
