"""Species balance tournament.

Every species fights every other, both sides of the table, across N seeds.
Reports win rate per species and the SPREAD (best minus worst), which is the
number balance work actually moves.

Usage:
    python dev/tournament.py               # 3 seeds, orders on and off
    python dev/tournament.py 5             # 5 seeds
    python dev/tournament.py 5 on          # only with the order AI enabled
    python dev/tournament.py 5 on --ab     # ...also without species specials
    python dev/tournament.py 5 on --isolate  # one run per species' specials

Composition comes from lexicon.army_composition -- the same function the game
fields armies with. It used to be a hand-copied duplicate here, which is a
tournament that can quietly stop measuring the real game.

Read the numbers with care:
  * Sample is small. At 3 seeds each species plays 24 games, so anything under
    about 10-15 points is noise. Only large moves mean anything.
  * Matchups are near-deterministic per seed, so results tend to flip in whole
    matchups rather than drifting -- which makes small samples LOOK decisive.
  * Battles are reproducible from a seed (Unit.uid ordering), so a repeat run of
    an identical configuration must give an identical answer. If it does not,
    something has reintroduced address-dependent ordering; that bug cost a lot
    of wasted tuning before it was found.
  * The "orders off" column is a historical baseline only. Both sides use the
    order AI in a real game, so "orders on" is the column that matters.
"""
import itertools
import random
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.battle.order_ai as order_ai
from app.battle.battle import Battle, Army
from app.world import lexicon

SPECIES = ["Humans", "Elves", "Dwarves", "Orcs", "Goblins"]
POWER = 120
FIELD = (1100, 620)
TIME_LIMIT = 120.0


def composition(species, power=POWER, specials=True, only=None):
    """The army the game itself fields, straight from lexicon.

    This used to be a hand-copied duplicate of App._army_for with a comment on
    both asking whoever came next to keep them in step. It is now the same
    function, because a tournament measuring a composition the game does not
    field is worse than no tournament at all.

    `specials=False` strips the species' signature units and gives their
    headcount back to the arms that paid for them -- the A/B control for "is
    this unit worth its slot", measured by DISABLING it rather than by
    comparing against a remembered number from an earlier build.

    `only=<species>` keeps specials for that species alone. Turning them all on
    at once measures five changes stacked, and the first run that way was
    genuinely misleading: the roster spread went 45 -> 78 points, which says
    nothing about which unit did it. Isolation is the only way to attribute.
    """
    if specials and (only is None or only == species):
        return lexicon.army_composition(species, power)
    saved = lexicon.SPECIES.get(species, {}).pop("specials", None)
    try:
        return lexicon.army_composition(species, power)
    finally:
        if saved is not None:
            lexicon.SPECIES[species]["specials"] = saved


def fight(a_species, b_species, seed, specials=True, only=None):
    random.seed(seed)
    b = Battle(*FIELD)          # player_side stays None: the AI orders BOTH
    b.deploy(Army(a_species, "#cc3333", 0, species=a_species),
             composition(a_species, specials=specials, only=only), 0)
    b.deploy(Army(b_species, "#3399cc", 1, species=b_species),
             composition(b_species, specials=specials, only=only), 1)
    t = 0.0
    while not b.over and t < TIME_LIMIT:
        b.update(1 / 60)
        t += 1 / 60
    return (b.winner.side if b.winner else None), t


def run(orders_on, seeds, specials=True, only=None):
    real = order_ai.decide_for_army
    if not orders_on:
        order_ai.decide_for_army = lambda *a, **k: None
    wins = {s: 0 for s in SPECIES}
    games = {s: 0 for s in SPECIES}
    stalemates = 0
    try:
        for a, b in itertools.permutations(SPECIES, 2):
            for seed in seeds:
                side, _ = fight(a, b, seed, specials=specials, only=only)
                games[a] += 1
                games[b] += 1
                if side == 0:
                    wins[a] += 1
                elif side == 1:
                    wins[b] += 1
                else:
                    stalemates += 1
    finally:
        order_ai.decide_for_army = real
    rates = {s: 100.0 * wins[s] / max(1, games[s]) for s in SPECIES}
    return rates, stalemates, sum(games.values()) // 2


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    n_seeds = int(args[0]) if args else 3
    which = args[1].lower() if len(args) > 1 else "both"
    seeds = [11 + 12 * i for i in range(n_seeds)]
    modes = [("orders OFF", False), ("orders ON ", True)]
    if which == "on":
        modes = modes[1:]
    elif which == "off":
        modes = modes[:1]
    # --ab runs each mode twice, with the species' signature units and without,
    # so the effect of adding them is measured against a control run in THIS
    # build rather than against a number remembered from an earlier one.
    variants = [("", True)] if "--ab" not in flags else [(" -specials", False),
                                                         (" +specials", True)]
    print(f"{n_seeds} seeds, {len(SPECIES) * (len(SPECIES) - 1) * n_seeds} battles per mode\n")
    for label, on in modes:
        if "--isolate" in flags:
            isolate(label, on, seeds)
            continue
        for suffix, specials in variants:
            rates, stale, total = run(on, seeds, specials=specials)
            spread = max(rates.values()) - min(rates.values())
            print(f"{label}{suffix}: "
                  + "  ".join(f"{s[:3]} {rates[s]:3.0f}%" for s in SPECIES)
                  + f" | spread {spread:3.0f}pts | stalemates {stale}/{total}")


def isolate(label, orders_on, seeds):
    """What each species' signature units are worth ON THEIR OWN.

    A control run with nobody's specials, then one run per species with only
    that species' specials enabled. The delta on that species' own row is the
    unit's effect, attributable; the other rows in each run only show what
    facing it costs everyone else.

    This exists because the first measurement turned all five on at once and
    was uninterpretable -- the spread moved 33 points and there was no way to
    say which of five simultaneous changes did it."""
    base, _, _ = run(orders_on, seeds, specials=False)
    print(f"{label} control : "
          + "  ".join(f"{s[:3]} {base[s]:3.0f}%" for s in SPECIES)
          + f" | spread {max(base.values()) - min(base.values()):3.0f}pts")
    for species in SPECIES:
        rates, _, _ = run(orders_on, seeds, specials=True, only=species)
        delta = rates[species] - base[species]
        print(f"{label} {species[:7]:<8s}: "
              + "  ".join(f"{s[:3]} {rates[s]:3.0f}%" for s in SPECIES)
              + f" | {species} {base[species]:3.0f}% -> {rates[species]:3.0f}% "
                f"({delta:+.0f})")


if __name__ == "__main__":
    main()
