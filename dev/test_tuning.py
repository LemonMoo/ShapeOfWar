"""Balance levers: are they real, complete, and reversible?

A tuning layer that quietly fails is worse than none at all -- you would tune
against numbers that never reached the simulation and trust the tournament that
measured nothing. So the assertions here are deliberately about EFFECT, not
about bookkeeping: a lever is only a lever if changing it changes a battle.

    python dev/test_tuning.py
"""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core import tuning

import tournament as T

FAILURES = []
TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tuning_test.json")


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not ok:
        FAILURES.append(name)


def test_index():
    print("\n--- the index ---")
    levers = tuning.levers()
    check("levers found", len(levers) > 150, f"{len(levers)}")
    paths = [p for p, *_ in levers]
    check("paths are unique", len(paths) == len(set(paths)))
    check("every lever has a default",
          all(p in tuning.DEFAULTS for p in paths))
    # Spot-check that each section actually resolved to something -- a typo in
    # a scalar name would otherwise just silently contribute zero levers.
    for section in tuning.SECTIONS:
        n = sum(1 for p in paths if p.startswith(section.key + "."))
        if not n:
            check(f"section '{section.key}' has levers", False)
            break
    else:
        check("every section has levers", True)
    # The ones a balance pass actually reaches for.
    for path in ("units.infantry.max_hp", "units.archer.range",
                 "species.Dwarves.unit_hp_mult",
                 "species.Goblins.specials.0.of_archers",
                 "commanders.Orcs.cleave.radius",
                 "stances.charge.speed_mult", "composition.infantry",
                 "order_ai.PRESS_ADVANTAGE", "morale.MORALE_DAMAGE_MULT"):
        if path not in tuning.DEFAULTS:
            check(f"expected lever {path}", False)
            break
    else:
        check("the levers a balance pass reaches for are all present", True)


def test_reaches_the_tables():
    print("\n--- edits reach the live tables ---")
    from app.battle import unit as unit_mod
    from app.battle.unit_types import UNIT_TYPES
    from app.world.lexicon import SPECIES

    tuning.set("units.infantry.max_hp", 99)
    check("UNIT_TYPES sees it", UNIT_TYPES["infantry"]["max_hp"] == 99,
          str(UNIT_TYPES["infantry"]["max_hp"]))
    tuning.set("species.Dwarves.unit_hp_mult", 1.5)
    check("SPECIES sees it", SPECIES["Dwarves"]["unit_hp_mult"] == 1.5)
    # Imported by value into unit.py -- this is the one that fails silently if
    # the mirror list is ever forgotten.
    tuning.set("commander_rules.COMMANDER_AURA_RADIUS", 200)
    check("by-value scalars are mirrored into their importers",
          unit_mod.COMMANDER_AURA_RADIUS == 200,
          str(unit_mod.COMMANDER_AURA_RADIUS))
    tuning.reset()
    check("reset restores every table",
          UNIT_TYPES["infantry"]["max_hp"] == tuning.DEFAULTS["units.infantry.max_hp"]
          and unit_mod.COMMANDER_AURA_RADIUS == 130)
    check("reset leaves nothing changed", not tuning.changes())


def test_changes_a_battle():
    print("\n--- a lever changes a battle ---")
    base = T.fight("Elves", "Orcs", 11)
    tuning.set("units.archer.damage", 24)
    loud = T.fight("Elves", "Orcs", 11)
    check("quadrupling archer damage changes the result", loud != base,
          f"{base} -> {loud}")
    tuning.reset()
    check("and resetting restores it exactly", T.fight("Elves", "Orcs", 11) == base)

    # Composition is the other half: a share change has to reach the army the
    # tournament fields, or --isolate is measuring nothing.
    before = T.composition("Dwarves")
    tuning.set("composition.infantry", 0.60)
    after = T.composition("Dwarves")
    check("composition shares reach the fielded army",
          after["infantry"] > before["infantry"],
          f"{before['infantry']} -> {after['infantry']}")
    tuning.reset()


def test_round_trip():
    print("\n--- save / load ---")
    tuning.set("units.cavalry.charge_bonus", 4.25)
    tuning.set("species.Orcs.no_cavalry", False)
    tuning.set("units.archer.range", 200)
    _, n = tuning.save(TMP)
    check("saves only what differs", n == 3, f"{n} written")
    tuning.reset()
    check("reset clears them", not tuning.changes())
    tuning.load(TMP, quiet=True)
    check("floats survive", tuning.get("units.cavalry.charge_bonus") == 4.25)
    check("bools survive", tuning.get("species.Orcs.no_cavalry") is False)
    check("ints stay ints", isinstance(tuning.get("units.archer.range"), int))

    # An override file outlives the lever it names. That must cost a warning,
    # not a game that will not start.
    unknown = tuning.apply({"units.nosuchunit.max_hp": 5, "utter.nonsense": 1})
    check("unknown levers are reported, not raised", len(unknown) == 2, str(unknown))
    tuning.reset()
    os.remove(TMP)


def test_defaults_are_pristine():
    print("\n--- defaults ---")
    # DEFAULTS is captured at import, before any override can be applied. If it
    # were a live reference instead of a copy, every "default" shown in the lab
    # would follow the edits and nothing could ever be reset.
    snapshot = copy.deepcopy(tuning.DEFAULTS)
    tuning.set("units.infantry.damage", 40)
    check("editing does not disturb the defaults", tuning.DEFAULTS == snapshot)
    tuning.reset()


def main():
    test_index()
    test_reaches_the_tables()
    test_changes_a_battle()
    test_round_trip()
    test_defaults_are_pristine()
    tuning.reset()
    print("\nTUNING TEST " + ("FAILED: " + ", ".join(FAILURES)
                              if FAILURES else "PASSED"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
