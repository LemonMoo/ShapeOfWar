"""An economy with no sun (SUBTERRANEAN_PLAN phase 4).

    python dev/test_under_food.py

The plan's own claim is that the underground is a CONVERTER and a LARDER, not
a farm, and that a hold is therefore structurally a trading power with a
standing food dependency rather than a handicap. These are the structural
consequences of that, and none of them is a win rate or a balance number:

  * nothing grows underground -- a hold's own ground offers no crop at all,
    and the mountainside above its doors is the only land it can farm;
  * fungus is BOUNDED BY SUBSTRATE. Beds with nothing to compost produce
    nothing, however big they are. Fungiculture converts waste into food and
    cannot create it, and a fungus farm producing from nothing is the one
    thing in this design that would be plainly wrong;
  * the guano floor is real and is NOT enough on its own, which is what makes
    the loop worth building rather than optional;
  * the larder is real: identical stock spoils measurably slower below ground;
  * and a hold cut off from its terraces runs down over SEASONS rather than
    days, then recovers when they are retaken.

Warrens, scavenging and hunger-driven raiding are the last item in the plan's
build order and are deliberately not here: they need somebody to live in the
warren, which is phase 5.

Builds a real world and plants a real Village in a real underground region --
worldgen does not put anybody down there yet, so this is the honest way to
exercise the machinery a hold will use.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import layers as L
from app.world import resources as R
from app.world import buildings as B
from app.world.worldgen import generate_world, Village

world = generate_world(560, 340, seed=7, n_factions=6)
world.player_faction_idx = 0
print(f"world: {world.under_summary}")

# An underground region with a door of its own -- the shape a hold will have.
mouths = {tuple(g["under"]) for g in world.gates}
region = next(r for r in world.regions
              if L.is_under(r) and set(r.cells) & mouths)
region.faction_idx = 0
cell = next(p for p in region.cells
            if L.kind_at(world, p[0], p[1], L.UNDER) == L.CAVERN)


def plant(name="Deep Hall", home=None, pos=None):
    """A village in the hall, wired in the way worldgen wires one."""
    home = home or region
    village = Village(len(world.villages), home.id, 0, name, pos or cell,
                      farm_output=0, population=180, adults=120, children=60,
                      prosperity=50, max_population=400)
    world.villages.append(village)
    home.villages = list(getattr(home, "villages", [])) + [village.id]
    return village


hold = plant()
season = world.season

print("\n--- nothing grows down here ---")
raw, potentials, _by_sector = R._village_terrain_potential(world, hold, season)
crops = {r: a for r, a in raw.items()
         if R.RESOURCES.get(r, {}).get("category") == "Crops"}
assert not crops, f"a hold grew crops out of solid rock: {crops}"
print("  ok    no crop of any kind from a hold's own ground")

print("\n--- ...but the ore above it is real, once someone digs ---")
# HYBRID (v0.18.27): the capital seat inherits the mine -- it IS the mine,
# see holds._settle_hold's under_capital stamp -- and every OTHER under node
# is a mining settlement like any surface one: no camp, no ore (see
# _village_terrain_potential's under branch).
raw, potentials, _by_sector = R._village_terrain_potential(world, hold, season)
mining = {r: a for r, a in raw.items()
          if R.RESOURCES.get(r, {}).get("category") == "Mining"}
assert not mining, ("a bare gallery offered ore for nothing -- the hybrid "
                    "gate is off (only the capital seat inherits the mine)")
print("  ok    a bare hall mines nothing until a camp is sunk")
# Seed the camps its own overhead rock supports (mountain -> Mining Camp,
# highland -> Workings, forest -> Woodcutters'), the same bootstrap every
# born village gets -- then the ore above the gallery is real.
R.seed_family_camps(world, region, hold)
raw, potentials, _by_sector = R._village_terrain_potential(world, hold, season)
mining = {r: a for r, a in raw.items()
          if R.RESOURCES.get(r, {}).get("category") == "Mining"}
assert mining, "a camp did not unlock the ore above a gallery"
print(f"  ok    a camp unlocks: {', '.join(sorted(mining))}")

print("\n--- the floor: guano and blind fish, and not enough of either ---")
floor = R.under_floor_yield(world, hold, region)
assert floor.get("Guano", 0) > 0, "no guano anywhere in a cavern system"
need = R.FOOD_PER_CAPITA * hold.adults
edible = sum(a for r, a in floor.items() if R.RESOURCES[r]["edible"])
print(f"  floor {floor}, edible {edible:.3f}/day against a need of {need:.3f}")
assert edible < need, (
    "the scavenging floor alone feeds a hold -- that is the failure mode the "
    "plan names: nothing below is worth building if the floor is subsistence")
assert edible > 0 or floor.get("Guano", 0) > 0, "the floor is nothing at all"
print("  ok    a real trickle, and well under what the people need")

print("\n--- fungus is bounded by substrate, not by bed size ---")
R.set_storage_tier(hold, R.FUNGUS_GALLERY, 1)
hold.resources = {}
R.advance_fungus_galleries(world)
assert not hold.resources.get("Mushrooms"), (
    "beds with nothing in them produced food -- fungiculture converts waste, "
    "it cannot create it")
hold.resources = {"Manure": 4}
R.advance_fungus_galleries(world)
small = hold.resources.get("Mushrooms", 0)
assert small > 0 and hold.resources.get("Manure", 0) == 0, hold.resources
hold.resources = {"Manure": 200}
R.advance_fungus_galleries(world)
big = hold.resources.get("Mushrooms", 0)
cap = R.fungus_cap(hold)
assert big > small, "more substrate did not mean more food"
assert big <= cap, f"{big} mushrooms out of a bed rated for {cap} substrate"
print(f"  ok    4 substrate -> {small} food, 200 -> {big} (the bed caps at {cap})")

print("\n--- and the stalls are what fill the beds ---")
hold.herds = {"Goats": 40, "Pigs": 20}
hold.resources = {}
R.set_storage_tier(hold, R.STALLS, 1)
world.turn = 1        # the first turn of a season -- see _is_new_season
world.season = "Summer"
R.advance_herds(world)
muck = hold.resources.get("Manure", 0)
assert muck > 0, "a stalled herd produced no muck at all"
hold.resources = {}
R.set_storage_tier(hold, R.STALLS, 0)
R.advance_herds(world)
assert not hold.resources.get("Manure"), (
    "manure appeared with no stalls to produce it -- the building is the "
    "whole mechanic")
print(f"  ok    60 head in stalls -> {muck} Manure a season, and none without them")
world.season = season

print("\n--- the terraces above the doors are the only farm a hold has ---")
before = R.gate_holding_cells(world, hold)
assert before == 0, "terraces without ever building the holding"
R.set_storage_tier(hold, R.GATE_HOLDING, 1)
terraces = R.gate_holding_cells(world, hold)
assert terraces > 0, "a hold with a door of its own could not farm above it"
hold._labor_cache = None
raw2, _p, _b = R._village_terrain_potential(world, hold, "Summer")
grown = {r: a for r, a in raw2.items()
         if R.RESOURCES.get(r, {}).get("category") == "Crops"}
assert grown, ("the gate holding grew nothing -- the terraces are the whole "
               "bootstrap, and without them a hold starves before trade exists")
print(f"  ok    {terraces} cells of mountainside -> {', '.join(sorted(grown))}")

# ...and taking them away takes the food away with it, which is the strategy
# the mechanic exists to create: to starve a hold you take its terraces.
R.set_storage_tier(hold, R.GATE_HOLDING, 0)
hold._labor_cache = None
raw3, _p, _b = R._village_terrain_potential(world, hold, "Summer")
assert not [r for r in raw3 if R.RESOURCES.get(r, {}).get("category") == "Crops"], (
    "a hold cut off from its terraces still grew food")
R.set_storage_tier(hold, R.GATE_HOLDING, 1)
print("  ok    cut off from them, it grows nothing again")

print("\n--- the larder: identical stock keeps far better below ground ---")
surface_region = next(r for r in world.regions
                      if not L.is_under(r) and r.cells)
above = plant("Upper Village", home=surface_region, pos=surface_region.cells[0])
stock = {"Meat": 1000, "Mushrooms": 1000, "Cheese": 1000}
hold.resources = dict(stock)
above.resources = dict(stock)
for _ in range(10):
    R._apply_settlement_spoilage_and_overflow(hold, R.node_spoil_mult(world, hold))
    R._apply_settlement_spoilage_and_overflow(above, R.node_spoil_mult(world, above))
print(f"  after 10 days: below {hold.resources}, above {above.resources}")
assert R.node_spoil_mult(world, hold) == R.UNDER_SPOIL_MULT
assert R.node_spoil_mult(world, above) == 1.0
for resource in stock:
    assert hold.resources[resource] > above.resources[resource], (
        f"{resource} kept no better in a cave than in a barn")
# Stated as a ratio on the fastest-spoiling good rather than a threshold on
# every one of them: Cheese is cured already (0.05) and ten days cannot
# separate the two by much, while Meat at 0.30 is exactly the case the larder
# is for. Recorded, not asserted tightly -- UNDER_SPOIL_MULT is a first pass.
assert hold.resources["Meat"] > above.resources["Meat"] * 3, hold.resources
print(f"  Meat: {hold.resources['Meat']} below against "
      f"{above.resources['Meat']} above, after ten days")
print("  ok    a hold is the best storehouse in the world")

print("\n--- the beds and the terraces are offered below ground, and only there ---")
options = {o.building for o in B.build_options(world, hold, world.factions[0])}
for building in (R.GATE_HOLDING, R.FUNGUS_GALLERY, R.STALLS):
    assert building in options, f"{building} is not offered to a hold"
above_options = {o.building for o in B.build_options(world, above, world.factions[0])}
for building in (R.GATE_HOLDING, R.FUNGUS_GALLERY, R.STALLS):
    assert building not in above_options, (
        f"{building} was offered to a village on the surface")
# ...and the CROP outstation is not offered below -- the Grange extends crop
# reach, and there are no crops in a gallery (v0.18.27). The extractive
# camps ARE offered below: that is the hybrid ore model -- an under node
# builds the Mining Camp / Workings its overhead rock supports, exactly like
# a surface village (see test_under_mining.py). The Gold Mine stays gone
# below (its seam gate reads the surface grid) and the surface keeps the
# underground three hidden.
for building in R.OUTSTATIONS:
    if building == R.GRANGE:
        assert building not in options, "the crop Grange was offered in a gallery"
assert any(b in options for b in (R.MINING_CAMP, R.WORKINGS, R.WOODCUTTERS_CAMP)), (
    "no extractive camp offered to an under village -- the hybrid ore model "
    "gates mining on camps, so the camps must be buildable below")
print("  ok    the beds, the terraces and the mines below, and no overlap")

print("\n--- a hold with the whole loop running feeds itself ---")
# Not a balance claim: what is asserted is that the CHAIN closes -- terraces
# feed the beasts, the beasts feed the beds, the beds feed the hold -- and
# that the food it makes is food the existing consumption code can eat.
hold.resources = {"Manure": 60, "Guano": 20, "Logs": 40}
hold.herds = {"Goats": 40, "Pigs": 20}
R.set_storage_tier(hold, R.STALLS, 1)
for _ in range(20):
    R.advance_fungus_galleries(world)
food = hold.resources.get("Mushrooms", 0)
assert food > 0
assert "Mushrooms" in R._FOOD_SOURCES and "Cave Fish" in R._FOOD_SOURCES, (
    "the food a hold grows is not food the population knows how to eat")
print(f"  ok    {food} Mushrooms in the larder, and they count as food")

print("\n--- and a world with a hold in it still runs a day ---")
# The 200-day "a new hold does not starve" run the plan asks for needs a hold
# worldgen actually built, with a population, a larder and a herd of its own --
# that is phase 5. What can be checked today is that every per-day phase copes
# with a node whose region is on the other layer, which is the thing phase 5
# will be standing on.
world.turn = 1
hold.resources = {"Mushrooms": 200, "Manure": 40}
before_pop = hold.population
for _ in range(30):
    R.advance_turn(world)
assert hold.population > 0 and hold.faction_idx == 0
assert all(v >= 0 for v in hold.resources.values()), hold.resources
print(f"  ok    30 days with a hold in the world: population {before_pop} -> "
      f"{hold.population}, stock {hold.resources.get('Mushrooms', 0)} Mushrooms")

print("\nUNDER FOOD TEST PASSED")
