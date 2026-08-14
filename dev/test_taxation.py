"""Taxation and the kingdom treasury: coin that already exists, moved to a pot.

    python dev/test_taxation.py [world.pkl]

The load-bearing claims of TAXATION_PLAN.md, in order:

1. REDISTRIBUTION, NEVER MINTING -- income tax drains gold a settlement
   actually holds into its faction's treasury; the faction's total gold
   (nodes + treasury) is unchanged. A settlement holding no gold pays nothing.
2. TRANSACTION TAX -- a synthetic sale credits (1 - TRADE_TAX_RATE) of the
   gold to the seller settlement and the rest to the seller's treasury, again
   with total gold unchanged.
3. TREASURY FUNDS DEVELOPMENT -- can_afford checks the treasury for a Gold
   cost, and _pay_cost draws it from the treasury, not node stock.
4. RECONCILIATION -- over a run, the treasury ledger's causes sum to the
   treasury's real balance change.
"""
import os
import pickle
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import construction as C
from app.world import resources as R
from app.world import trade as T

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "worlds", "dev560.pkl")


def load():
    random.seed(4242)
    with open(PATH, "rb") as fh:
        world = pickle.load(fh)
    return world


def faction_gold_total(world, fac_idx):
    """Node gold + treasury -- the invariant both taxes must preserve."""
    return R.faction_gold(world, fac_idx) + R.faction_treasury(world, fac_idx)


print("--- 1. income tax redistributes, never mints ---")
w = load()
pidx = w.player_faction_idx if w.player_faction_idx is not None else 0
settlements = [s for s in w.settlements if s.faction_idx == pidx]
assert settlements, "the player faction has no settlements to tax"
# Give the faction a known, comfortable position and a fresh treasury ledger.
w.factions[pidx].stats["treasury"] = 0
w._treasury_turn = {}
for s in settlements:
    s.resources = dict(getattr(s, "resources", None) or {})
    s.resources["Gold"] = 1000          # more than any tax_income roll
before_total = faction_gold_total(w, pidx)
before_node = R.faction_gold(w, pidx)
collected = R.collect_income_tax(w)
after_total = faction_gold_total(w, pidx)
after_node = R.faction_gold(w, pidx)
expected = sum(min(getattr(s, "tax_income", 0) or 0, 1000) for s in settlements)
assert collected.get(pidx, 0) == expected, (collected, expected)
assert after_total == before_total, (
    "income tax changed total gold -- it must only move coin, not mint it")
assert before_node - after_node == collected.get(pidx, 0)
assert R.faction_treasury(w, pidx) == collected.get(pidx, 0)
print(f"  ok    {collected.get(pidx, 0):,} gold drained, total gold unchanged")

print("\n--- 2. a settlement holding no gold pays no tax ---")
w = load()
pidx = w.player_faction_idx if w.player_faction_idx is not None else 0
settlements = [s for s in w.settlements if s.faction_idx == pidx]
w.factions[pidx].stats["treasury"] = 0
w._treasury_turn = {}
for s in settlements:
    s.resources = dict(getattr(s, "resources", None) or {})
    s.resources["Gold"] = 0
collected = R.collect_income_tax(w)
assert collected.get(pidx, 0) == 0, collected
assert R.faction_treasury(w, pidx) == 0
for s in settlements:
    assert (s.resources or {}).get("Gold", 0) == 0
print("  ok    no gold held, no tax paid, nothing went negative")

print("\n--- 3. transaction tax skims the seller's receipt into the treasury ---")
w = load()
pidx = w.player_faction_idx if w.player_faction_idx is not None else 0
settlements = [s for s in w.settlements if s.faction_idx == pidx]
villages = [v for v in w.villages if v.faction_idx == pidx]
buyer = settlements[0]
seller = villages[0] if villages else settlements[0]
for node in list(settlements) + list(villages):
    node.resources = dict(getattr(node, "resources", None) or {})
    node.resources["Gold"] = 0
buyer.resources["Gold"] = 300      # 100 spendable above GOLD_TRADE_RESERVE
w.factions[pidx].stats["treasury"] = 0
w._treasury_turn = {}
before_total = faction_gold_total(w, pidx)
payment = T._collect_payment(buyer, 100, w, w.season, allow_barter=False)
T._deliver_payment(w, seller, payment)
after_total = faction_gold_total(w, pidx)
tax = round(100 * T.TRADE_TAX_RATE)
assert (buyer.resources or {}).get("Gold", 0) == 200, buyer.resources
assert (seller.resources or {}).get("Gold", 0) == 100 - tax, seller.resources
assert R.faction_treasury(w, pidx) == tax, R.faction_treasury(w, pidx)
assert after_total == before_total, "transaction tax must not mint gold"
print(f"  ok    {100 - tax} to the seller, {tax} to the treasury, "
      f"total unchanged")

print("\n--- 4. the treasury funds development, not node stock ---")
w = load()
pidx = w.player_faction_idx if w.player_faction_idx is not None else 0
nation = w.factions[pidx]
# Node gold is plentiful, treasury is exactly 500 -- a 750-gold cost must be
# refused (treasury short) and a 300-gold cost must be paid from the treasury.
for s in w.settlements + w.villages:
    if s.faction_idx == pidx:
        s.resources = dict(getattr(s, "resources", None) or {})
        s.resources["Gold"] = 5000
nation.stats["treasury"] = 500
assert C.can_afford(nation, {"Gold": 750}, w) is False, (
    "750-gold cost should be refused with a 500-gold treasury")
assert C.can_afford(nation, {"Gold": 300}, w) is True
C._pay_cost(nation, {"Gold": 300}, w)
assert R.faction_treasury(w, pidx) == 200, R.faction_treasury(w, pidx)
node_after = R.faction_gold(w, pidx)
assert node_after == 5000 * len(
    [s for s in w.settlements + w.villages if s.faction_idx == pidx]), (
    "_pay_cost must draw Gold from the treasury, not node stock")
print("  ok    affordability and payment both read the treasury")

print("\n--- 5. the treasury ledger reconciles to the real balance change ---")
w = load()
R.migrate_treasury(w)          # old saves start with no treasury -- seed it
pidx = w.player_faction_idx if w.player_faction_idx is not None else 0
start_turn = w.turn
start_treasury = R.faction_treasury(w, pidx)
DAYS = 10
for _ in range(DAYS):
    R.advance_turn(w)
end_treasury = R.faction_treasury(w, pidx)
ledger = R.treasury_ledger(w, pidx)
run_net = 0
for entry in ledger:
    if start_turn < entry.get("turn", 0) <= w.turn:
        run_net += entry.get("net", 0)
assert run_net == end_treasury - start_treasury, (
    f"treasury ledger net {run_net:+,} != real change "
    f"{end_treasury - start_treasury:+,}")
print(f"  ok    ledger {run_net:+,} == real treasury change "
      f"{end_treasury - start_treasury:+,}")

print("\n--- 6. a real turn run stays sane ---")
for node in list(w.settlements) + list(w.villages):
    for res, amt in (getattr(node, "resources", None) or {}).items():
        assert amt >= 0, (node.name, res, amt)
for i in range(len(w.factions)):
    assert R.faction_treasury(w, i) >= 0, i
print("  ok    no negative gold anywhere, every treasury non-negative")

print("\nTAXATION TEST PASSED")
