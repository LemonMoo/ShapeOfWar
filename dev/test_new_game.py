"""New Game setup: rulers, colours, identity patching, and the preview promise.

The load-bearing claim of this screen is that **you play the world you looked
at**. It generates in the background, you re-skin it while it sits there, and
Play hands that exact world over. If any link in that chain is wrong the screen
still looks fine and quietly lies to the player, so most of what is asserted
here is that chain rather than the widgets.

    python dev/test_new_game.py            # ~1 world generated, be patient
"""
import os
import sys
import time
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ui.world_preview import land_summary, render_world
from app.world.lexicon import (RULER_TITLES, SPECIES, PALETTE_HUE_SPREAD,
                               make_ruler_namer, species_palette,
                               species_stat_chips, species_units)
from app.world.nation import ensure_rulers, ruler_label
from app.world.worldgen import (_PLAYER_HUE_CLEARANCE, _hue_of,
                                apply_player_identity, generate_world)

FAILURES = []
# Small on purpose: this harness generates real worlds, and Small measures ~8s
# against Standard's ~18s. Nothing asserted here depends on the size.
SMALL = dict(width=760, height=456, n_factions=8)


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not ok:
        FAILURES.append(name)


def hue_gap(a, b):
    return abs((_hue_of(a) - _hue_of(b) + 180.0) % 360.0 - 180.0)


def test_palette():
    print("\n--- species palettes ---")
    for species in SPECIES:
        pal = species_palette(species)
        check(f"{species}: distinct swatches", len(pal) == len(set(pal)),
              f"{len(pal)} offered")
        hue = SPECIES[species]["hue"]
        worst = max(abs((_hue_of(c) - hue + 180) % 360 - 180) for c in pal)
        # A palette that wandered outside its species band would break the
        # thing that makes the political map readable: kin looking like kin.
        if worst > PALETTE_HUE_SPREAD + 2.0:
            check(f"{species}: stays in its species band", False,
                  f"{worst:.0f}deg from hue {hue}")
            return
    check("every palette stays inside its species' hue band", True)


def test_ruler_names():
    print("\n--- rulers ---")
    import random
    namer = make_ruler_namer(random.Random(1))
    names = [namer("Dwarves") for _ in range(40)]
    check("ruler names are unique", len(names) == len(set(names)))
    check("titles exist for every species",
          all(s in RULER_TITLES for s in SPECIES))

    class FakeNation:
        def __init__(self, species):
            self.meta = {"species": species}
            self.ruler = {}

    class FakeWorld:
        seed = 99
        factions = [FakeNation("Orcs"), FakeNation("Elves")]

    w = FakeWorld()
    check("ensure_rulers fills an old save", ensure_rulers(w) == 2)
    check("...with a title and a name",
          all(n.ruler.get("name") and n.ruler.get("title") for n in w.factions))
    check("ruler_label reads well", ruler_label(w.factions[0]).count(" ") >= 1,
          ruler_label(w.factions[0]))
    check("ensure_rulers is idempotent", ensure_rulers(w) == 0)
    # Deterministic from the world seed, so reloading a save twice must not
    # quietly rename a rival's king between sessions.
    w2 = FakeWorld()
    ensure_rulers(w2)
    check("ensure_rulers is deterministic from the seed",
          [n.ruler for n in w.factions] == [n.ruler for n in w2.factions])


def test_generation(world):
    print("\n--- a generated world ---")
    check("every realm has a monarch",
          all(getattr(n, "ruler", None) for n in world.factions))
    check("the player's chosen name stuck", world.factions[0].name == "Testhold")
    check("the player's chosen ruler stuck",
          world.factions[0].ruler["name"] == "Brokk Ironbeard")
    player_color = world.factions[0].color
    check("the player's chosen colour stuck", player_color == PICKED_COLOR,
          player_color)
    too_close = [n.name for n in world.factions[1:]
                 if hue_gap(n.color, player_color) < _PLAYER_HUE_CLEARANCE - 0.01]
    check("no rival crowds the player's hue", not too_close, str(too_close))
    check("every rival kept a base colour to re-derive from",
          all(n.meta.get("base_color") for n in world.factions))


def test_identity_patch(world):
    print("\n--- identity patching ---")
    before_terrain = (world.w, world.h, len(world.regions), len(world.settlements))
    rival_names_before = [n.name for n in world.factions[1:]]
    mine_before = [s.name for s in world.settlements if s.faction_idx == 0]

    t = time.perf_counter()
    apply_player_identity(world, species="Goblins", name="Rustfang Warren",
                          color=species_palette("Goblins")[2],
                          ruler={"name": "Snik", "title": "Boss"})
    elapsed = (time.perf_counter() - t) * 1000
    # This runs on every keystroke; if it were not effectively free the screen
    # would have to debounce, and browsing species would stop being instant.
    check("patching is fast enough to run per keystroke", elapsed < 60,
          f"{elapsed:.1f} ms")

    p = world.factions[0]
    check("species changed", p.meta["species"] == "Goblins")
    check("trait text followed the species", p.meta["trait"] == SPECIES["Goblins"]["trait"])
    check("realm renamed", p.name == "Rustfang Warren")
    check("monarch replaced", ruler_label(p) == "Boss Snik")
    mine_after = [s.name for s in world.settlements if s.faction_idx == 0]
    check("the player's settlements were renamed for the new species",
          mine_after != mine_before and len(mine_after) == len(mine_before))
    check("the world itself is untouched",
          (world.w, world.h, len(world.regions), len(world.settlements)) == before_terrain)
    check("rivals keep their names",
          [n.name for n in world.factions[1:]] == rival_names_before)

    # Rival colours are re-derived from their stored base every time, so
    # clicking through swatches must not walk them around the wheel.
    stable = [n.color for n in world.factions[1:]]
    for _ in range(6):
        apply_player_identity(world, color=species_palette("Goblins")[2])
    check("rival colours are stable under repeated applies",
          stable == [n.color for n in world.factions[1:]])
    check("rivals still clear of the new player hue",
          all(hue_gap(n.color, world.factions[0].color)
              >= _PLAYER_HUE_CLEARANCE - 0.01 for n in world.factions[1:]))


def test_preview(world):
    print("\n--- preview ---")
    t = time.perf_counter()
    img = render_world(world, (430, 258))
    elapsed = (time.perf_counter() - t) * 1000
    check("thumbnail renders quickly", elapsed < 600, f"{elapsed:.0f} ms")
    check("fits the box", img.width <= 430 and img.height <= 258, str(img.size))
    # Aspect must come from the WORLD, not the box: the preview exists to let
    # you judge the shape of the map, and a stretched one misrepresents it.
    check("keeps the world's aspect",
          abs(img.width / img.height - world.w / world.h) < 0.02)
    check("land summary says something", len(land_summary(world, 0)) > 20,
          land_summary(world, 0))
    check("chips and units exist for every species",
          all(species_stat_chips(s) or species_units(s) for s in SPECIES))


def test_screen_hands_over_its_world():
    print("\n--- the screen plays the world it showed ---")
    from app.ui.new_game import NewGameView

    handed = {}
    root = tk.Tk()
    root.geometry("1180x720")
    view = NewGameView(root, on_play=lambda w: handed.setdefault("world", w),
                       on_back=lambda: None)
    view.pack(fill="both", expand=True)
    root.update()
    check("a world is requested as soon as the screen opens", view._pending == 1)

    deadline = time.time() + 240
    while view._world is None and time.time() < deadline:
        root.update()
        time.sleep(0.05)
    check("the background world arrives", view._world is not None)

    shown = view._world
    view._pick_species("Orcs")
    view._name_var.set("Previewed Realm")
    root.update()
    check("re-skinning does not swap the world out", view._world is shown)

    view._play()
    root.update()
    check("Play hands over the world that was on screen",
          handed.get("world") is shown)
    played = handed.get("world")
    if played is not None:
        check("...with the identity the screen was showing",
              played.factions[0].name == "Previewed Realm"
              and played.factions[0].meta["species"] == "Orcs",
              f"{played.factions[0].name} / {played.factions[0].meta['species']}")
        check("...and a player faction index set", played.player_faction_idx == 0)
    root.destroy()


PICKED_COLOR = species_palette("Dwarves")[3]


def main():
    test_palette()
    test_ruler_names()
    print("\ngenerating a world (~8s)...")
    world = generate_world(seed=11, player_species="Dwarves",
                           player_name="Testhold", player_color=PICKED_COLOR,
                           player_ruler={"name": "Brokk Ironbeard",
                                         "title": "High King"}, **SMALL)
    test_generation(world)
    test_preview(world)
    test_identity_patch(world)
    test_screen_hands_over_its_world()
    print("\nNEW GAME TEST " + ("FAILED: " + ", ".join(FAILURES)
                                if FAILURES else "PASSED"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
