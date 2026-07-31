"""Claiming wildland is colonisation: settlers and provisions, nothing else.

    python dev/test_claim_cost.py [world.pkl]

The bug this replaces was structural, not a tuning miss. Claims were priced
in Gold + Logs + Stone, and measured on a real save that left 5 of 14 realms
UNABLE TO CLAIM ANYTHING AT ALL -- four short of Stone, one short of Gold.
Quarrying barely exists for most realms (villages sit on farmland, mountain
is ~4.5% of the map) and some worlds mint no gold whatsoever, so the price
was one whole realms could never pay.

Settlers and food cannot lock anyone out: a realm with neither is already
finished. The core property this guards is exactly that.
"""
import sys
import os
import pickle

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import expansion as E
from app.world import resources as R

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "worlds", "dev560.pkl")
w = pickle.load(open(PATH, "rb"))
wild = [r for r in w.regions if r.faction_idx < 0 and r.cells]
assert wild, "this world has no unclaimed land to test against"
region = wild[len(wild) // 2]

print("--- a claim costs people and food, and nothing else ---")
cost = E.claim_cost(region)
assert set(cost) == {"Food"}, cost
for gone in ("Gold", "Logs", "Stone", "Iron"):
    assert gone not in cost, f"{gone} is back in the claim price"
assert not hasattr(E, "CLAIM_BASE_COST"), "the old goods price should be gone"
settlers = E.claim_settlers(region)
assert settlers > 0
assert cost["Food"] == settlers * E.CLAIM_PROVISIONS_PER_SETTLER
print(f"  ok    {len(region.cells)}-cell region: {settlers} settlers, "
      f"{cost['Food']} food, no goods at all")

print("\n--- CRITICAL: no realm is structurally locked out ---")
# The whole point. Gold/Logs/Stone blocked 5 of 14 here; people and food
# are things every living realm has.
blocked = [w.factions[i].name for i in range(len(w.factions))
           if E.can_afford_claim(w, i, region) is not None]
assert not blocked, f"still locked out of expanding entirely: {blocked}"
print(f"  ok    all {len(w.factions)} realms can fund this claim")

print("\n--- an amphibious claim is a far bigger undertaking ---")
land = E.claim_settlers(region, sea_only=False)
sea = E.claim_settlers(region, sea_only=True)
assert sea > land * 2, (land, sea)
print(f"  ok    {land} settlers overland vs {sea} across water")

print("\n--- paying it takes real people, and real working-age people ---")
fac = 0
nodes = E._faction_population_nodes(w, fac)
pop_before = sum(n.population for n in nodes)
adults_before = sum(getattr(n, "adults", 0) for n in nodes)
food_before = E._faction_food_stock(w, fac)
floors = {id(n): (getattr(n, "max_population", None) or n.population)
          * R.POPULATION_MIN_FRACTION for n in nodes}

took, food_taken = E._pay_claim(w, fac, region)
assert took == E.claim_settlers(region), (took, E.claim_settlers(region))
assert food_taken == cost["Food"], (food_taken, cost["Food"])
pop_after = sum(n.population for n in nodes)
adults_after = sum(getattr(n, "adults", 0) for n in nodes)
assert pop_before - pop_after == took, (pop_before, pop_after, took)
assert adults_before - adults_after == took, "settlers must come off the workforce"
assert food_before - E._faction_food_stock(w, fac) == food_taken
print(f"  ok    -{took} population, -{took} adults, -{food_taken} food")

print("\n--- and it can never empty a place below the famine floor ---")
for node in nodes:
    assert node.population >= floors[id(node)] - 0.001, (
        f"{node.name} was drained below the floor starvation itself respects")
    assert node.population >= 0 and getattr(node, "adults", 0) >= 0, node.name
print(f"  ok    all {len(nodes)} nodes still above POPULATION_MIN_FRACTION, "
      f"none negative")

print("\n--- no single place is gutted for one expedition ---")
worst = max(nodes, key=lambda n: E._node_spare_settlers(n))
pop = worst.population
assert E._node_spare_settlers(worst) <= pop * E.CLAIM_SETTLER_DRAW_FRACTION + 1
print(f"  ok    a node offers at most "
      f"{E.CLAIM_SETTLER_DRAW_FRACTION:.0%} of its people")

print("\n--- a poor realm is limited, but never permanently blocked ---")
# It should run out of provisions and have to rebuild them -- a
# self-correcting brake, not the hard lockout the old price was.
small = min(range(len(w.factions)),
            key=lambda i: E.faction_available_settlers(w, i))
claims = 0
for _ in range(20):
    if E.can_afford_claim(w, small, region) is not None:
        break
    E._pay_claim(w, small, region)
    claims += 1
reason = E.can_afford_claim(w, small, region)
assert reason is not None, "the smallest realm claimed 20 regions without limit"
assert "settlers" in reason or "food" in reason, reason
print(f"  ok    {w.factions[small].name} managed {claims} back-to-back claims, "
      f"then: {reason}")

print("\n--- spoils no longer net off a Gold price that doesn't exist ---")
spoils = E.claim_spoils(w, region)
assert E.claim_net_gold(w, region) == spoils.get("Gold", 0)
assert not hasattr(E, "CLAIM_SPOILS_GOLD_MULT"), (
    "the spoils multiple was pinned to a Gold cost that is gone")
print(f"  ok    net gold == spoils gold ({spoils.get('Gold', 0):,})")

print("\n--- a real turn still runs ---")
for _ in range(3):
    R.advance_turn(w)
for n in list(w.settlements) + list(w.villages):
    assert n.population >= 0, (n.name, n.population)
    for res, amt in (n.resources or {}).items():
        assert amt >= 0, (n.name, res, amt)
print("  ok    3 turns, no negative population or stock")

print("\nCLAIM COST TEST PASSED")
