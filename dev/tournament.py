"""Species balance tournament.

Every species fights every other, both sides of the table, across N seeds.
Reports win rate per species and the SPREAD (best minus worst), which is the
number balance work actually moves.

Usage:
    python dev/tournament.py               # 3 seeds, orders on and off
    python dev/tournament.py 5             # 5 seeds
    python dev/tournament.py 5 on          # only with the order AI enabled

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
from app.world.lexicon import species_traits

SPECIES = ["Humans", "Elves", "Dwarves", "Orcs", "Goblins"]
POWER = 120
FIELD = (1100, 620)
TIME_LIMIT = 120.0


def composition(species, power=POWER):
    """Mirrors App._army_for -- keep the two in step or the tournament stops
    measuring the army the game actually fields."""
    t = species_traits(species)
    foot, archer, cav = 0.4, 0.25, 0.2
    if t["no_cavalry"]:
        mode = t["cavalry_becomes"]
        if mode == "split":
            foot += cav / 2
            archer += cav / 2
        elif mode == "archers":
            archer += cav
        else:
            foot += cav
        cav = 0.0
    comp = {"infantry": round(power * foot), "archer": round(power * archer)}
    if cav:
        comp["cavalry"] = round(power * cav)
    special = t["special_unit"]
    if special:
        from_bows = round(comp["archer"] * t["special_share_of_archers"])
        from_line = round(comp["infantry"] * t["special_share_of_swordsmen"])
        bonus = round(power * t["special_bonus_share"])
        comp["archer"] -= from_bows
        comp["infantry"] -= from_line
        if from_bows + from_line + bonus:
            comp[special] = from_bows + from_line + bonus
    return comp


def fight(a_species, b_species, seed):
    random.seed(seed)
    b = Battle(*FIELD)          # player_side stays None: the AI orders BOTH
    b.deploy(Army(a_species, "#cc3333", 0, species=a_species),
             composition(a_species), 0)
    b.deploy(Army(b_species, "#3399cc", 1, species=b_species),
             composition(b_species), 1)
    t = 0.0
    while not b.over and t < TIME_LIMIT:
        b.update(1 / 60)
        t += 1 / 60
    return (b.winner.side if b.winner else None), t


def run(orders_on, seeds):
    real = order_ai.decide_for_army
    if not orders_on:
        order_ai.decide_for_army = lambda *a, **k: None
    wins = {s: 0 for s in SPECIES}
    games = {s: 0 for s in SPECIES}
    stalemates = 0
    try:
        for a, b in itertools.permutations(SPECIES, 2):
            for seed in seeds:
                side, _ = fight(a, b, seed)
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
    n_seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    which = sys.argv[2].lower() if len(sys.argv) > 2 else "both"
    seeds = [11 + 12 * i for i in range(n_seeds)]
    modes = [("orders OFF", False), ("orders ON ", True)]
    if which == "on":
        modes = modes[1:]
    elif which == "off":
        modes = modes[:1]
    print(f"{n_seeds} seeds, {len(SPECIES) * (len(SPECIES) - 1) * n_seeds} battles per mode\n")
    for label, on in modes:
        rates, stale, total = run(on, seeds)
        spread = max(rates.values()) - min(rates.values())
        print(f"{label}: " + "  ".join(f"{s[:3]} {rates[s]:3.0f}%" for s in SPECIES)
              + f" | spread {spread:3.0f}pts | stalemates {stale}/{total}")


if __name__ == "__main__":
    main()
