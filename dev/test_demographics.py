"""Demographics: population grows AND declines off relative wealth, and the
village/town/city pyramid is kept from flattening into "everything is a city".

    python dev/test_demographics.py [world.pkl]

Population used to be a one-way climb toward each node's rolled ceiling (only
starvation/freezing could lower it), so every fed settlement eventually crossed
the ladder's population thresholds and -- with the AI climbing relentlessly --
the map drifted toward cities everywhere. This test pins the replacement:

  * _grow_population's net rate = natural increase + a signed migration term
    proportional to how far a node's wealth stands above/below its region and
    kingdom averages. A thriving node grows toward its ceiling; a marginal one
    declines toward the population floor, so it can never cross a ladder
    threshold it hasn't earned.
  * demote_settlements falls a City back to a Town, or a Town back to a
    Village, once population declines below the recorded floor -- the ladder's
    decline half, mirroring the raise path in reverse.
"""
import os
import pickle
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import resources as R
from app.world import construction as C


class _Node:
    """The minimal shape _grow_population reads: population/adults/children,
    a ceiling, no food/firewood shortfall, and a wealth target."""

    def __init__(self, kind, pop, max_pop, wealth, farm=False):
        self.kind = kind
        self.population = pop
        self.adults = int(pop * 0.6)
        self.children = pop - self.adults
        self.max_population = max_pop
        self.turns_without_food = 0
        self.turns_without_firewood = 0
        self._wealth_target = wealth
        self.region_id = 0
        self.faction_idx = 0
        self._pop_growth_accum = 0.0
        self._adult_growth_accum = 0.0
        if farm:
            self.farm_output = 1     # the codebase's village-detection idiom


def test_growth_and_decline():
    # Thriving (wealth clearly above context): grows toward the ceiling.
    n = _Node("village", 100, 450, 60, farm=True)
    for _ in range(100):
        R._grow_population(n, {0: 20.0}, {0: 20.0})
    assert n.population > 100, n.population
    # Marginal (wealth clearly below context): declines toward the floor.
    m = _Node("village", 200, 450, 5, farm=True)
    for _ in range(300):
        R._grow_population(m, {0: 40.0}, {0: 40.0})
    floor = round(450 * R.POPULATION_MIN_FRACTION)
    assert m.population < 200, m.population
    assert m.population >= floor, (m.population, floor)
    # Average (wealth == context): no migration, natural increase only.
    z = _Node("village", 100, 450, 40, farm=True)
    for _ in range(200):
        R._grow_population(z, {0: 40.0}, {0: 40.0})
    assert z.population > 100, z.population       # natural increase still applies
    assert z.population < 450
    print("  ok  thriving grows, marginal declines to floor, average grows slowly")


def test_demotion(world):
    city = next(s for s in world.settlements if s.faction_idx >= 0 and s.kind == "city")
    town = next(s for s in world.settlements if s.faction_idx >= 0 and s.kind == "town")

    # City -> Town.
    city.demote_threshold = city.population + 1
    city.promoted_at_turn = 0
    city.has_shipyard = True
    C.demote_settlements(world)
    assert city.kind == "town", city.kind
    assert not city.has_shipyard, "a Town can't keep a city-only shipyard"
    assert city.id in world.regions[city.region_id].meta_settlements, (
        "a demoted City stays a settlement (kind changes in place)")

    # Town -> Village: the settlement is neutralized (index preserved), the
    # original village it was raised from is reactivated with the town's
    # people, and the region's settlement list drops it.
    region = world.regions[town.region_id]
    nation = world.factions[town.faction_idx]
    cap_before = R.region_village_capacity(world, region)
    town_pop = town.population
    town.demote_threshold = town.population + 1
    town.promoted_at_turn = 0
    C.demote_settlements(world)
    assert town.kind is None and town.faction_idx < 0, (town.kind, town.faction_idx)
    assert town.id not in nation.meta.get("settlements", []), "removed from nation"
    assert town.id not in region.meta_settlements, "removed from region settlements"
    vid = town.demoted_into
    v = world.villages[vid]
    assert v.faction_idx >= 0, "reactivated village is live"
    assert v.population == town_pop, (v.population, town_pop)
    assert vid in region.villages, "reactivated village rejoins the region"
    # Capacity falls back: the demoted Town's village allowance is gone.
    assert R.region_village_capacity(world, region) < cap_before, (
        "demoting a Town frees its village-slot allowance")
    print("  ok  City->Town in place; Town->Village neutralizes + reactivates + shrinks capacity")


def test_demote_repoints_trade(world):
    """A demoted Town is no longer a settlement, so in-flight trade that names
    its id must follow it: caravans fall back to the capital, and regional/
    local shipments re-target the new village."""
    from types import SimpleNamespace
    town = next(s for s in world.settlements if s.faction_idx >= 0 and s.kind == "town")

    caravan = SimpleNamespace(dest_settlement_id=town.id, origin_settlement_id=town.id)
    world.trade_caravans.append(caravan)
    reg = SimpleNamespace(origin_kind="settlement", origin_id=town.id,
                          dest_kind="settlement", dest_id=town.id)
    world.regional_shipments.append(reg)
    loc = SimpleNamespace(origin_kind="village", origin_id=12345,
                          dest_kind="settlement", dest_id=town.id)
    world.local_shipments.append(loc)

    town.demote_threshold = town.population + 1
    town.promoted_at_turn = 0
    C.demote_settlements(world)

    vid = town.demoted_into
    assert caravan.dest_settlement_id is None and caravan.origin_settlement_id is None, (
        "a caravan must fall back to the capital, not a dead settlement")
    assert (reg.origin_kind, reg.origin_id, reg.dest_kind, reg.dest_id) == \
        ("village", vid, "village", vid), "a regional shipment didn't re-target the village"
    assert (loc.origin_kind, loc.origin_id) == ("village", 12345), (
        "an unrelated origin must be left alone")
    assert (loc.dest_kind, loc.dest_id) == ("village", vid), (
        "a local shipment's settlement dest didn't re-target the village")
    print("  ok  in-flight trade follows a demoted Town into its new Village")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(__file__), "worlds", "dev160.pkl")
    world = pickle.load(open(path, "rb"))
    if getattr(world, "player_faction_idx", None) is None:
        world.player_faction_idx = 0

    test_growth_and_decline()
    test_demotion(world)
    test_demote_repoints_trade(world)
    print("demographics: all checks passed")


if __name__ == "__main__":
    main()
