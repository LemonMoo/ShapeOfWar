"""The economy ledger is the sim, measured -- and changes nothing.

    python dev/test_econ_ledger.py [world.pkl]

The load-bearing claims of ECONOMY_PLAN.md's Part A, in order:

1. RECONCILIATION -- for every resource a faction holds, the ledger's causes
   sum to that resource's real stock change over the run. This is the whole
   point of measuring at phase boundaries instead of instrumenting by hand:
   the panel's numbers are the world's numbers, and if a phase is ever missed
   the invariant breaks and this test goes red. Measured over the run's own
   econ_ledger window (turn-filtered): a warm dev save carries year-to-date
   econ_year history, so the year window cannot measure a short run.

2. OBSERVATION-ONLY -- a world run with the ledger recording runs to an
   identical fingerprint as the same world with it switched off
   (world._econ_ledger_enabled = False). The pass must change nothing
   simulated; the fingerprint is the same shape dev/test_turn_slice.py uses.

3. YEAR ROLLOVER -- world.econ_year resets at the year boundary, so the
   Ledger's "THIS YEAR" section never mixes two years.

4. PANEL SMOKE -- the Ledger panel renders without error both with data and
   with an empty ledger (the "let a day pass" placeholder). Skips cleanly with
   exit 0 where there is no display, same as dev/test_panels.py.
"""
import hashlib
import os
import pickle
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import commander as C
from app.world import resources as R

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "worlds", "dev560.pkl")
DAYS = 10


def load():
    random.seed(4242)          # the AI makes random choices; pin them
    with open(PATH, "rb") as fh:
        world = pickle.load(fh)
    C.ensure_faction_commanders(world)
    return world


def fingerprint(world):
    """Same shape as dev/test_turn_slice.py -- regions, nodes, factions."""
    h = hashlib.sha256()
    for r in world.regions:
        h.update(f"{r.id}:{r.faction_idx}:{r.wildland_strength}|".encode())
    for node in list(world.settlements) + list(world.villages):
        h.update(f"{getattr(node, 'id', '')}:{getattr(node, 'population', 0)}:".encode())
        h.update(",".join(f"{k}={v}"
                          for k, v in sorted((getattr(node, "resources", {}) or {}).items())
                          ).encode())
        h.update(b"|")
    for f in world.factions:
        h.update(f"{f.name}:{sorted(f.stats.items())}|".encode())
    h.update(f"turn={world.turn}season={world.season}".encode())
    return h.hexdigest()


def faction_snapshots(world):
    return [R.faction_resource_snapshot(world, i)
            for i in range(len(world.factions))]


print(f"--- 1. the ledger reconciles to the real stock change ({DAYS} days) ---")
world = load()
start_turn = world.turn
before = faction_snapshots(world)
for _ in range(DAYS):
    R.advance_turn(world)
after = faction_snapshots(world)
# Reconcile over the RUN's own window: sum the windowed entries (econ_ledger)
# whose turn falls inside the run. The year window (econ_year) cannot measure
# a 10-day run on a dev world -- make_dev_world.py warms the save 560 turns,
# so econ_year already holds pre-run history, and a year boundary inside the
# run would cut the window in half. The run-window sum is the exact claim:
# the ledger's causes sum to that resource's real stock change over the run.
assert DAYS <= R.ECON_LEDGER_HISTORY_TURNS, (
    f"run window {DAYS} exceeds the ledger history window "
    f"{R.ECON_LEDGER_HISTORY_TURNS} -- entries would be evicted mid-run")
for fac_idx in range(len(world.factions)):
    run_net = {}
    for resource, entries in world.econ_ledger.get(fac_idx, {}).items():
        for entry in entries:
            if start_turn < entry.get("turn", 0) <= world.turn:
                run_net[resource] = run_net.get(resource, 0) + entry.get("net", 0)
    for resource, start in before[fac_idx].items():
        ledger_net = run_net.get(resource, 0)
        real_change = after[fac_idx].get(resource, 0) - start
        if real_change or ledger_net:
            print(f"  {world.factions[fac_idx].name:24s} {resource:14s} "
                  f"ledger {ledger_net:+,}  real {real_change:+,}")
            assert ledger_net == real_change, (
                f"{resource} for {world.factions[fac_idx].name}: ledger says "
                f"{ledger_net:+,} but stock really changed {real_change:+,}")
    # Resources that appeared during the run.
    for resource in after[fac_idx]:
        if resource not in before[fac_idx]:
            ledger_net = run_net.get(resource, 0)
            assert ledger_net == after[fac_idx][resource], (
                f"new resource {resource} for {world.factions[fac_idx].name}: "
                f"ledger {ledger_net:+,} vs stock {after[fac_idx][resource]:+,}")
print("  ok    every resource reconciles -- ledger net == real stock change")

print("\n--- 2. the ledger is observation-only (A/B fingerprint) ---")
# Load-and-advance each arm in sequence, exactly as test_turn_slice does:
# load() reseeds random to 4242 AT LOAD TIME, so the second load's reseed
# must land right before its own advancing -- loading both worlds up front
# lets the first arm's 10 days pollute the shared random stream the second
# arm then advances on, and the arms diverge for reasons that have nothing
# to do with the ledger (measured: 38 settlements differ with the ledger
# OFF in both arms under that bug).
on = load()
for _ in range(DAYS):
    R.advance_turn(on)
off = load()
off._econ_ledger_enabled = False
for _ in range(DAYS):
    R.advance_turn(off)
fon, foff = fingerprint(on), fingerprint(off)
print(f"  on  {fon[:16]}")
print(f"  off {foff[:16]}")
assert fon == foff, (
    "recording the economy ledger changed the simulated world -- the pass "
    "must be observation-only")
print("  ok    identical worlds, ledger on or off")

print("\n--- 3. econ_year resets at the year boundary ---")
world = load()
# YEAR_LENGTH_TURNS = 100; the new year starts at turn 101 (_is_new_year),
# so begin ten days before the boundary and run through it -- ten days of
# Year-1 accumulation makes a leak unmistakable.
world.turn = R.YEAR_LENGTH_TURNS - 10     # turn 90
for _ in range(10):
    R.advance_turn(world)
assert world.turn == R.YEAR_LENGTH_TURNS  # turn 100: still Year 1
assert R.current_year(world.turn) == 1
R.advance_turn(world)                      # turn 101: first day of Year 2
assert R.current_year(world.turn) == 2
# The precise leak test: after the boundary the accumulator may hold ONLY
# turn 101's movement -- the windowed ledger entry for each resource carries
# its turn, so the fresh accumulator must equal exactly today's entry net.
# (Comparing Year-1 vs Year-2 totals is not a valid test: one day of Year-2
# production can coincidentally equal one captured day of Year-1 production.)
year_after = getattr(world, "econ_year", {})
for fac_idx in range(len(world.factions)):
    for resource, causes in year_after.get(fac_idx, {}).items():
        recent = R.economy_recent(world, fac_idx, resource)
        today = [e for e in recent if e.get("turn") == world.turn]
        assert today, f"{resource} in econ_year with no turn-{world.turn} entry"
        window_net = sum(e.get("net", 0) for e in today)
        assert sum(causes.values()) == window_net, (
            f"econ_year for {resource} mixes years: accumulator "
            f"{sum(causes.values()):+,} vs turn {world.turn} net {window_net:+,}")
print("  ok    the new year's accumulator started fresh (turn-101 entries only)")

print("\n--- 4. the Ledger panel renders (real Tk) ---")
try:
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
except tk.TclError as exc:
    print(f"  no display available ({exc}) -- skipping panel smoke")
    sys.exit(0)

from app.ui.map_view import MapView
world = load()
if world.player_faction_idx is None:
    world.player_faction_idx = 0
for _ in range(DAYS):
    R.advance_turn(world)


def noop(*a, **k):
    pass


view = MapView(root, world, noop, noop)
view.update_idletasks()
view.open_ledger()
view.update_idletasks()
# Tip text builders must be safe for a resource the faction may not hold.
player = view._player_faction()
assert player is not None
view._resource_tip_text("Logs")
# Empty-ledger placeholder: a fresh world with no days run has nothing yet.
fresh = load()
fresh_view = MapView(root, fresh, noop, noop)
fresh_view.update_idletasks()
fresh_view.open_ledger()
fresh_view.update_idletasks()
view._refresh_ledger()
view.update_idletasks()
root.destroy()
print("  ok    Ledger panel rendered with data and with an empty ledger")

print("\nECONOMY LEDGER TEST PASSED")
