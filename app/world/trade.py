"""Autonomous inter-faction trade: every faction independently evaluates and
initiates trades with others each turn (no player involvement required — the
player's own faction is just one more participant, not special-cased).

Trade is gated on diplomacy, not just geography: two factions must have
made contact (app/world/diplomacy.establish_contact — fired by the player's
fog-of-war discovery, or a shared border for anyone — see
app/world/vision.py and app/world/territory.py) and be on decent terms
(standing >= TRADE_STANDING_THRESHOLD) before a route can even be proposed
at all — see eligible_to_trade(). Neither a land nor a sea route ever opens
on its own, though: one side has to propose it (the player via the UI, an
AI faction via run_trade_route_ai) and the other has to actually agree
(diplomacy.evaluate_trade_route — standing, species affinity, and real
economic complementarity, the same "does this make sense for them" check
form_alliance uses, just a lower bar) before anything is established — see
start_trade_route, the single entry point both proposers go through. Once
agreed, a *land* route still has to be physically built before caravans can
use it: TradeRouteProject grows a precomputed capital-to-capital path from
both ends at once, meeting in the middle (see advance_trade_route_projects).
A *sea* route opens the moment it's agreed to — nothing to physically build
across open water — see _capital_sea_path (path lookup only; it no longer
opens a route as a side effect).

A deal is carried out by a TradeCaravan (land) or ship (sea, same class) that
travels the established route from the seller's capital to the buyer's,
delivers the goods and collects payment there, then must make it *back home*
before the seller actually receives the gold — modeling real risk (a caravan
can be lost if war breaks out while it's in transit) instead of an instant
wire transfer.

First-pass simplifications (see the plan this was built from): trade routes
always run capital-to-capital rather than picking a specific settlement;
the AI is a greedy first-match, not a globally optimal matching; caravan risk
is driven only by the existing war/relationship system, no separate
bandit/piracy mechanic.
"""
import random

from app.world.world_map import Stance
from app.world.worldgen import (OCEAN, UNCLAIMED, _path_dijkstra, _nearest_ocean_cell,
                                _elev_cost, _sea_cost, _bfs_distance,
                                _SEA_COAST_REACH)
from app.world.resources import (RESOURCES, BASE_VALUE_BY_TIER, RESOURCE_SPAWN,
                                 _storage_cap, _clamp_to_storage,
                                 settlement_needs, _FOOD_SOURCES, _LUXURY_GOODS,
                                 _SETTLEMENT_STORAGE_RESOURCES,
                                 settlement_storage_capacity, _node_storage_capacity,
                                 _node_surplus, _node_wants,
                                 _LOCAL_SHIPMENT_PRIORITY, resource_value)
from app.world.diplomacy import TRADE_STANDING_THRESHOLD
from app.world import wrap
from app.world import rivers

# --- market ------------------------------------------------------------------
MIN_TRADE_QUANTITY = 20
SAFETY_RESERVE_TURNS = 8          # food: never sell below N turns of upkeep
NON_FOOD_RESERVE_FRACTION = 0.1   # non-food: never sell below 10% of storage cap

MAX_ACTIVE_TRADES_PER_FACTION = 3
CELLS_PER_TURN = 15
# A river barge outruns an overland caravan for the same reason a river
# shipment outruns a wagon (see RIVER_SHIPMENT_CELLS_PER_TURN): a prepared
# waterway with no terrain to fight.
RIVER_CELLS_PER_TURN = 30
MIN_TRANSIT_TURNS, MAX_TRANSIT_TURNS = 5, 20
# A river route's own, lower floor -- same reasoning as
# MIN_RIVER_TRANSIT_TURNS for domestic shipments: without it a short river
# haul just hits the general minimum and the waterway buys you nothing.
MIN_RIVER_CARAVAN_TURNS = 2
LAND_RISK_PER_TURN = 0.08         # per turn, crossing land at war with either party
_TRADE_BBOX_PAD = 30

# --- trade route construction (land only; sea is automatic, see below) -------
TRADE_ROUTE_CELLS_PER_TURN = 6           # per end, per turn -- matches construction.ROAD_CELLS_PER_TURN
MAX_ACTIVE_ROUTE_PROJECTS_PER_FACTION = 1
_REGIONAL_BBOX_PAD = 30   # see Phase 11's regional-market section, near the bottom of this file


def _settlement_needs_total(nation, resource, world):
    """How much of `resource` this nation's settlements actually need per
    turn under Phase 8's consumption model (see resources.settlement_needs)
    — the replacement for the old upkeep-dict-based figure now that
    SETTLEMENT_UPKEEP is gone. For a food source (Food Product or edible
    raw Crop — see resources._FOOD_SOURCES) this is deliberately
    conservative: it assumes the whole nation's food need could fall on
    this one resource alone (food actually comes from whichever of them is
    in stock, not one specific one), erring toward reserving too much
    rather than too little — safer than accidentally trading away food a
    settlement (or, now that raw Crops count too, a Village that's never
    converted a single one of them) needs to survive."""
    total = 0
    for sid in nation.meta.get("settlements", []):
        needs = settlement_needs(world.settlements[sid], world.season)
        if resource in _FOOD_SOURCES:
            total += needs["Food"]
        elif resource == "Firewood":
            total += needs.get("Firewood", 0)
        elif resource == "Clothes":
            total += needs["Clothes"]
        elif resource in _LUXURY_GOODS:
            total += needs["Luxury"]
    return total


def _safety_reserve(nation, resource, world):
    needs_total = _settlement_needs_total(nation, resource, world)
    if needs_total > 0:
        return needs_total * SAFETY_RESERVE_TURNS
    return _storage_cap(nation, resource) * NON_FOOD_RESERVE_FRACTION


def _faction_settlements(nation, world):
    return [world.settlements[sid] for sid in nation.meta.get("settlements", [])]


def _faction_settlement_total(nation, resource, world):
    """Sum of `resource` across every settlement this faction owns — the
    aggregate view trade needs for a Phase 9 settlement-storage resource,
    since there's no longer one national number for it (each settlement
    keeps its own stockpile now)."""
    return sum(getattr(st, "resources", {}).get(resource, 0)
              for st in _faction_settlements(nation, world))


def _faction_capital_settlement(nation, world):
    """Where a caravan carrying a settlement-storage resource actually
    picks up/drops off — trade routes are still capital-to-capital
    (unchanged since routes were built, long before per-settlement
    storage existed), so the faction's first settlement stands in for
    "the capital" here. None if the faction has no settlement yet."""
    sids = nation.meta.get("settlements", [])
    return world.settlements[sids[0]] if sids else None


def _faction_has_gold_source(world, fac_idx):
    """Whether this faction currently owns any Mountain-biome land at all --
    the sole terrain Gold Ore ever spawns on (see RESOURCE_SPAWN), and
    Mining is continuous/non-depleting (see compute_industry_yield), so
    owning any is enough to call the resulting Gold Ore -> Gold conversion
    ("a Mint", see RECIPES/resources.py's Currency section -- there's no
    separate buildable structure, it just runs automatically wherever
    Gold Ore is flowing in) genuinely RELIABLE, not a one-off windfall.
    Used to gate Gold out of Regional Markets entirely for a faction with
    no such access (see _collect_payment's allow_gold) -- without a real,
    ongoing source, a faction's Gold is a fixed starting pile with nothing
    replacing it, and letting internal trade spend it down would just be
    a slow drain to zero, not real currency circulating."""
    return any(r.faction_idx == fac_idx and r.biome_counts.get("mountain", 0) > 0
              for r in world.regions)


# --- Currency overhaul: Gold payment, settlement-grounded, with a barter
# fallback -- Gold is a real, mined-and-minted _SETTLEMENT_STORAGE_RESOURCES
# good now (see resources.py's Currency section), not a bottomless national
# wallet, so a specific paying settlement can genuinely run short. Rather
# than blocking the deal, a settlement short on Gold barters real goods of
# roughly equivalent value instead -- "countries who don't have access to
# gold" (the request's own framing) still get to trade, just not for
# currency. Applies to both foreign trade (TradeCaravan) and domestic
# Regional Markets (RegionalShipment) below.
_BARTER_EXCLUDE = {"Gold", "Gold Ore"}


def _settlement_gold(st):
    return getattr(st, "resources", {}).get("Gold", 0) if st is not None else 0


# A settlement used to happily spend every last coin the instant it had
# some to spend, in both foreign and domestic trade -- fine for a single
# deal, but it meant a nation never actually held onto Gold long enough to
# fund anything else, like claiming wildland (CLAIM_BASE_COST +
# CLAIM_COST_PER_CELL in expansion.py -- a typical mid-size region runs
# ~150-250 Gold) or any other future Gold cost. This is purely a trade-
# spending floor, not a hard cap on the settlement's own Gold: claiming/
# construction still draw on its FULL stockpile, reserve included, when
# the settlement itself decides to spend it -- this only holds back what
# gets offered up in commerce, so the reserve is actually still there
# when a real opportunity (a wildland claim, say) comes along.
GOLD_TRADE_RESERVE = 200


def _spendable_gold(st):
    """Gold a settlement will actually put toward a trade, after holding
    back GOLD_TRADE_RESERVE -- see that constant's docstring."""
    return max(0, _settlement_gold(st) - GOLD_TRADE_RESERVE)


def _find_barter_good(payer_st, world, season, value_needed):
    """The single real (non-currency) resource `payer_st` can best spare --
    real surplus, respecting its own safety reserve, same _node_surplus
    logic every other logistics tier already uses -- picked by whichever
    has the greatest spare gold-equivalent value. None if payer_st has no
    meaningful surplus of anything. Doesn't try to match what the
    recipient specifically wants (a real haggling model is out of scope
    here) -- "equivalent value" is satisfied by resource_value() pricing
    the swap fairly, not by hand-picking the ideal good."""
    if payer_st is None or value_needed <= 0:
        return None
    needs = settlement_needs(payer_st, season)
    best_resource, best_value = None, 0
    for resource in _SETTLEMENT_STORAGE_RESOURCES:
        if resource in _BARTER_EXCLUDE:
            continue
        surplus = _node_surplus(payer_st, resource, needs)
        if surplus <= 0:
            continue
        value = resource_value(resource, surplus)
        if value > best_value:
            best_resource, best_value = resource, value
    if best_resource is None:
        return None
    per_unit = resource_value(best_resource, 1) or 1
    surplus = _node_surplus(payer_st, best_resource, needs)
    qty = min(surplus, max(1, round(value_needed / per_unit)))
    return (best_resource, qty)


def _settlement_purchasing_power(st, world, season, include_gold=True):
    """Gold `st` has on hand, plus the gold-equivalent value of what it
    could barter instead (see _find_barter_good) -- what actually caps how
    big a trade this settlement can realistically pay for, now that Gold
    has to be produced/stored/spent for real instead of drawn from a
    bottomless national wallet. Used to size a deal at dispatch time, same
    role nation.stats["gold"] used to play.

    `include_gold=False` (Regional Markets for a faction with no reliable
    Gold source -- see _faction_has_gold_source) sizes the deal off barter
    capacity alone, so a settlement never gets credited for spending power
    it isn't actually allowed to use (see _collect_payment's matching
    allow_gold). Gold itself only ever counts up to _spendable_gold (past
    the GOLD_TRADE_RESERVE floor) -- a settlement flush with cash still
    can't be sized as if the whole pile were up for trade."""
    if st is None:
        return 0
    needs = settlement_needs(st, season)
    barter_value = 0
    for resource in _SETTLEMENT_STORAGE_RESOURCES:
        if resource in _BARTER_EXCLUDE:
            continue
        surplus = _node_surplus(st, resource, needs)
        if surplus > 0:
            barter_value += resource_value(resource, surplus)
    return (_spendable_gold(st) if include_gold else 0) + barter_value


def _collect_payment(payer_st, price, world, season, barter_first=False, allow_gold=True):
    """Deduct up to `price` Gold-equivalent value from payer_st, and return
    what was actually taken, as a list of (resource, quantity). Doesn't
    credit anywhere; see _deliver_payment for the other half. Split in two
    so a caravan/shipment can collect payment when goods are delivered but
    only credit the seller once the return leg actually completes (see
    advance_caravans) -- the same real "the payment can be lost with the
    caravan" risk the traded resource itself already carries.

    `barter_first` (regional/domestic trade -- see run_regional_trade)
    tries a real barter good (_find_barter_good) before touching Gold at
    all: a realm moving goods between its OWN settlements has no reason to
    burn its treasury doing it, any more than a farmer pays cash to move
    grain from one of his own barns to another -- Gold only fills
    whatever's left once there's nothing suitable left to barter with.
    Foreign trade (the default, barter_first=False) keeps Gold-first,
    since a real currency genuinely is the normal way two separate
    nations settle a trade.

    `allow_gold=False` (regional trade for a faction with no reliable Gold
    source -- see _faction_has_gold_source) shuts Gold out of the payment
    entirely, not just deprioritizes it: without a real, ongoing Gold Ore
    -> Gold conversion running somewhere, a faction's starting Gold is a
    one-time, non-renewable pile -- letting internal trade spend it down
    would just be a slow-motion drain to zero with nothing replacing it,
    not real currency circulating. A trade that barter alone can't fully
    cover is undersized at dispatch instead (see run_regional_trade's own
    purchasing-power check), so this should rarely leave real unmet
    shortfall here -- it's a hard backstop, not the normal case.

    Whenever Gold IS on the table (allow_gold=True), it's still capped at
    _spendable_gold -- past GOLD_TRADE_RESERVE, a settlement won't put any
    more toward a trade, foreign or domestic, so it actually keeps enough
    on hand for its own future spending (a wildland claim, say) instead of
    trading away every coin the moment it has one."""
    if payer_st is None or price <= 0:
        return []
    if not hasattr(payer_st, "resources"):
        payer_st.resources = {}
    taken = []
    remaining = price

    def _pay_gold(amount):
        nonlocal remaining
        if not allow_gold:
            return
        gold_have = payer_st.resources.get("Gold", 0)
        gold_paid = min(_spendable_gold(payer_st), amount)
        if gold_paid > 0:
            payer_st.resources["Gold"] = gold_have - gold_paid
            taken.append(("Gold", gold_paid))
            remaining -= gold_paid

    def _pay_barter(amount):
        nonlocal remaining
        barter = _find_barter_good(payer_st, world, season, amount)
        if barter is not None:
            resource, qty = barter
            have = payer_st.resources.get(resource, 0)
            qty = min(qty, have)
            if qty > 0:
                payer_st.resources[resource] = have - qty
                taken.append((resource, qty))
                remaining = max(0, remaining - resource_value(resource, qty))

    if barter_first:
        _pay_barter(remaining)
        if remaining > 0:
            _pay_gold(remaining)
    else:
        _pay_gold(remaining)
        if remaining > 0:
            _pay_barter(remaining)
    return taken


def _deliver_payment(payee_st, paid):
    if payee_st is None or not paid:
        return
    if not hasattr(payee_st, "resources"):
        payee_st.resources = {}
    for resource, qty in paid:
        payee_st.resources[resource] = payee_st.resources.get(resource, 0) + qty


def _species_gold_bonus(world, faction_idx):
    """Extra fraction of Gold this faction's species earns on a completed
    foreign sale -- Humans' shrewd merchants, 0.0 for everyone else. See
    app/world/lexicon.py's SPECIES."""
    from app.world.lexicon import species_traits
    nation = world.factions[faction_idx]
    species = getattr(nation, "meta", {}).get("species")
    return species_traits(species)["trade_gold_bonus"]


def _with_gold_bonus(paid, bonus):
    """(boosted_payment, extra_gold): `paid` with its Gold scaled up by
    `bonus`. Only Gold is boosted -- bartered goods are physical crates that
    don't multiply on the way home. Deliberately applied to FOREIGN sales
    only (see advance_caravans): Regional Markets is a faction trading with
    itself, so a bonus there would just mint Gold out of nothing."""
    if not paid or bonus <= 0:
        return paid, 0
    out, extra = [], 0
    for resource, qty in paid:
        if resource == "Gold":
            bumped = int(round(qty * (1.0 + bonus)))
            extra += bumped - qty
            qty = bumped
        out.append((resource, qty))
    return out, extra


def _nation_resource_stock(nation, resource, world):
    """Wherever `resource` actually lives: summed across the faction's own
    settlements for a settlement-storage resource (as of Phase 12, this
    includes Mining/Forestry and what's crafted from them too -- see
    resources.py's Industry Specialization section), or the shared
    national pool for everything else (old-system-only goods with no
    live-registry equivalent yet: Gems/Mithril/Jewelry/Textiles/Silks/
    Spices/Steel/Fish)."""
    if resource in _SETTLEMENT_STORAGE_RESOURCES:
        return _faction_settlement_total(nation, resource, world)
    return nation.stats.get("resources", {}).get(resource, 0)


def sellable_surplus(nation, resource, world):
    """How much of `resource` this nation can spare without dipping into its
    own safety margin — food reserves are sized off real settlement need
    (Phase 8), not a guess, so a faction physically cannot sell food it
    needs to eat."""
    stock = _nation_resource_stock(nation, resource, world)
    return max(0, int(stock - _safety_reserve(nation, resource, world)))


def buyer_need(nation, resource, world):
    """0 (stockpile full, no interest) .. 1 (empty, desperate)."""
    stock = _nation_resource_stock(nation, resource, world)
    if resource in _SETTLEMENT_STORAGE_RESOURCES:
        cap = sum(settlement_storage_capacity(st) for st in _faction_settlements(nation, world))
    else:
        cap = _storage_cap(nation, resource)
    return max(0.0, 1.0 - stock / cap) if cap > 0 else 0.0


ALLY_TARIFF_DISCOUNT = 0.85   # allied trade is cheaper — "lower tariffs"


def _best_surplus_settlement(nation, resource, world):
    """Which of this faction's settlements actually has the most spare
    `resource` right now — Phase 11's fix for the "always the capital"
    simplification (see the module docstring): a caravan now picks up a
    settlement-storage resource from wherever it genuinely is, not from
    an aggregate national figure that happened to get parked on whichever
    settlement was built first. None if no settlement has any to spare."""
    best, best_amt = None, 0
    for st in _faction_settlements(nation, world):
        needs = settlement_needs(st, world.season)
        amt = _node_surplus(st, resource, needs)
        if amt > best_amt:
            best, best_amt = st, amt
    return best


def _best_need_settlement(nation, resource, world):
    """The settlement with the largest unmet fraction of storage for
    `resource` — where a caravan actually delivers to, instead of always
    the capital. None if the faction has no settlement with real capacity."""
    best, best_deficit = None, -1.0
    for st in _faction_settlements(nation, world):
        cap = settlement_storage_capacity(st)
        if cap <= 0:
            continue
        stock = getattr(st, "resources", {}).get(resource, 0)
        deficit = 1.0 - stock / cap
        if deficit > best_deficit:
            best, best_deficit = st, deficit
    return best


def unit_price(resource, seller, buyer, world, seller_settlement=None, buyer_settlement=None):
    """Base tier value, discounted if the seller has ample surplus, marked up
    if the buyer is scarce for it, discounted further for allies (lower
    tariffs). Pure data/formula — easy to retune.

    `seller_settlement`/`buyer_settlement` (Phase 11): for a settlement-
    storage resource, price forms off that SPECIFIC settlement's own local
    surplus/scarcity instead of the nation-wide aggregate, once
    de-capitalized trade (see _best_surplus_settlement/_best_need_settlement)
    has picked one — the "regional prices" you flagged as a future idea
    falls out of this naturally, without a separate pricing mechanic:
    a nation with one starving border town and one overflowing granary
    now prices a sale to/from each of those very differently, rather than
    blending them into one number. Callers that don't pass a settlement
    (or resources that aren't settlement-storage at all) keep the original
    nation-aggregate behavior unchanged."""
    tier = RESOURCES.get(resource, {}).get("tier", 3)
    base = BASE_VALUE_BY_TIER.get(tier, 3)

    if seller_settlement is not None and resource in _SETTLEMENT_STORAGE_RESOURCES:
        needs = settlement_needs(seller_settlement, world.season)
        surplus = _node_surplus(seller_settlement, resource, needs)
        cap = settlement_storage_capacity(seller_settlement)
        surplus_ratio = min(2.0, surplus / (cap * 0.1 + 1))
    else:
        surplus = sellable_surplus(seller, resource, world)
        reserve = _safety_reserve(seller, resource, world)
        surplus_ratio = min(2.0, surplus / (reserve + 1))
    seller_factor = max(0.6, 1.2 - 0.4 * surplus_ratio)

    if buyer_settlement is not None and resource in _SETTLEMENT_STORAGE_RESOURCES:
        cap = settlement_storage_capacity(buyer_settlement)
        stock = getattr(buyer_settlement, "resources", {}).get(resource, 0)
        need = max(0.0, 1.0 - stock / cap) if cap > 0 else 0.0
    else:
        need = buyer_need(buyer, resource, world)
    buyer_factor = min(2.5, 0.7 + 1.8 * need)

    price = base * seller_factor * buyer_factor
    rel = world.world_map.get_relationship(seller.id, buyer.id)
    if rel["stance"] == Stance.ALLY:
        price *= ALLY_TARIFF_DISCOUNT
    return round(price, 2)


# --- trade eligibility: contact made, not at war, decent enough terms ------
def eligible_to_trade(world, a_idx, b_idx):
    """Contact must have been made (a relationship exists — see
    diplomacy.establish_contact, fired by the player's fog-of-war discovery
    or a shared border for anyone), relations mustn't be hostile, and
    standing must clear TRADE_STANDING_THRESHOLD. This is the single gate
    both caravan dispatch (run_trade_ai) and route proposals
    (start_trade_route/run_trade_route_ai) go through."""
    a, b = world.factions[a_idx], world.factions[b_idx]
    if frozenset((a.id, b.id)) not in world.world_map.relationships:
        return False
    rel = world.world_map.get_relationship(a.id, b.id)
    if rel["stance"] == Stance.ENEMY:
        return False
    return rel.get("standing", 0) >= TRADE_STANDING_THRESHOLD


def _coastal_factions(world):
    """Faction indices owning at least one coastal settlement — reuses the
    coast-distance field settlement placement already computed once at
    world-gen (worldgen._init_settlement_proximity_fields's
    world._settle_coast_d) instead of redoing that same map-wide BFS from
    every ocean cell every single turn: ocean geography never changes once
    the world exists, so there's nothing to recompute. On a large map this
    used to be the single biggest per-turn cost by far (a full-grid BFS,
    every turn, forever) for a value that's turn-invariant."""
    coast_d = getattr(world, "_settle_coast_d", None)
    if coast_d is None:
        # Old save predating the cached field (or a non-standard World) —
        # compute once and cache, same as world-gen itself does.
        ocean_cells = [(x, y) for y in range(world.h) for x in range(world.w)
                      if world.owner[y][x] == OCEAN]
        if not ocean_cells:
            return set()
        coast_d = _bfs_distance(world, ocean_cells)
        world._settle_coast_d = coast_d
    coastal = set()
    for st in world.settlements:
        x, y = st.pos
        if coast_d[y][x] <= _SEA_COAST_REACH:
            coastal.add(st.faction_idx)
    return coastal


# --- routing: capital-to-capital ---------------------------------------------
def _get_path_cache(world):
    cache = getattr(world, "_trade_sea_path_cache", None)
    if cache is None:
        cache = {}
        world._trade_sea_path_cache = cache
    return cache


def _land_path_between(world, a_pos, b_pos, pad=_TRADE_BBOX_PAD, friendly_idxs=None):
    """Terrain-aware land path between two arbitrary points, or None if no
    land connection exists. Shared by _land_capital_path (foreign trade
    routes) and the Phase 11 regional-market path lookup below — same
    Dijkstra + elevation-cost machinery worldgen already uses everywhere
    else a path needs to respect terrain.

    `friendly_idxs`, when given, makes the search prefer detouring around
    any THIRD faction's territory (see worldgen._elev_cost) -- a real
    preference, not a wall, so a route only actually crosses foreign land
    when there's genuinely no reasonable way around it, same as every
    other terrain toll here."""
    ay, by = a_pos[1], b_pos[1]
    y0, y1 = sorted((ay, by))
    by0 = max(0, y0 - pad)
    by1 = min(world.h, y1 + pad + 1)
    xs = wrap.bbox_span_wrap(a_pos[0], b_pos[0], world.w, pad)
    land_cellset = {(x, y) for y in range(by0, by1) for x in xs
                     if world.owner[y][x] != OCEAN}
    if a_pos not in land_cellset or b_pos not in land_cellset:
        return None
    return _path_dijkstra(land_cellset,
                          lambda c: _elev_cost(world, world.base_cost, c,
                                               friendly_idxs=friendly_idxs),
                          a_pos, b_pos, world.w)


def _land_capital_path(world, a_idx, b_idx):
    """Terrain-aware land path between two factions' capitals — used once,
    when a land route is proposed (start_trade_route); unlike the sea case
    there's nothing to cache against since land routes are only ever
    computed at proposal time, not re-derived every turn. Prefers to
    avoid a THIRD faction's territory (neither a's nor b's own land, which
    are both fine to cross) -- a route "shouldn't" plow through some
    other, uninvolved nation whenever a reasonable detour exists, the same
    preference roads already apply to their own owning faction's land."""
    a_pos = world.factions[a_idx].meta["capital"]
    b_pos = world.factions[b_idx].meta["capital"]
    return _land_path_between(world, a_pos, b_pos, friendly_idxs=frozenset((a_idx, b_idx)))


def _capital_sea_path(world, a_idx, b_idx):
    """("sea", cells) route between two factions' capitals over open water,
    or None if no sea connection exists. Cached — capitals never move, so
    the path is constant for the whole game. Purely a feasibility/path
    lookup: unlike before, finding a sea path no longer opens a usable
    route by itself — a sea route now has to be proposed and agreed to
    exactly like a land one (see start_trade_route), it just skips the
    multi-turn construction phase since there's nothing physical to build
    across open water."""
    cache = _get_path_cache(world)
    key = frozenset((a_idx, b_idx))
    if key in cache:
        return cache[key]

    a_pos = world.factions[a_idx].meta["capital"]
    b_pos = world.factions[b_idx].meta["capital"]
    y0, y1 = sorted((a_pos[1], b_pos[1]))
    by0 = max(0, y0 - _TRADE_BBOX_PAD)
    by1 = min(world.h, y1 + _TRADE_BBOX_PAD + 1)
    xs = wrap.bbox_span_wrap(a_pos[0], b_pos[0], world.w, _TRADE_BBOX_PAD)

    path = None
    dock_a = _nearest_ocean_cell(world, a_pos)
    dock_b = _nearest_ocean_cell(world, b_pos)
    if dock_a and dock_b:
        sea_cellset = {(x, y) for y in range(by0, by1) for x in xs
                       if world.owner[y][x] == OCEAN}
        sea_path = _path_dijkstra(sea_cellset,
                                  lambda c: _sea_cost(world, world.base_cost, c),
                                  dock_a, dock_b, world.w)
        if sea_path is not None:
            path = [a_pos] + sea_path + [b_pos]

    result = ("sea", path) if path else None
    cache[key] = result
    return result


def route_path_possible(world, a_idx, b_idx):
    """Whether a trade route between these two capitals could ever actually
    form -- land OR sea, same check start_trade_route/accept_trade_route_
    proposal fall through to. eligible_to_trade only checks diplomacy
    (contact/standing), not geography, so without this a route can be
    proposed -- by the AI, or offered as a button in the player's own UI --
    between two capitals with no possible connection at all (different,
    unconnected landmasses where at least one side isn't even coastal), and
    the player only finds out it was never achievable after already
    accepting/clicking. Checked up front instead, so a proposal is only
    ever made when it can actually succeed.

    Cached on `world` -- capitals never move, so like _capital_sea_path
    this is turn-invariant. Without caching, run_trade_route_ai would
    re-run a full uncached land Dijkstra (_land_capital_path deliberately
    isn't cached -- see its own docstring, it used to only ever run once
    per accepted proposal) for every candidate pair, every single turn,
    which is real, avoidable per-turn cost on top of what was already
    there."""
    cache = getattr(world, "_route_path_possible_cache", None)
    if cache is None:
        cache = {}
        world._route_path_possible_cache = cache
    key = frozenset((a_idx, b_idx))
    if key in cache:
        return cache[key]
    result = _capital_river_route(world, a_idx, b_idx) is not None
    if not result:
        result = _land_capital_path(world, a_idx, b_idx) is not None
    if not result:
        coastal = _coastal_factions(world)
        if a_idx in coastal and b_idx in coastal:
            result = _capital_sea_path(world, a_idx, b_idx) is not None
    cache[key] = result
    return result


# A capital-to-capital route counts as a river route once at least this much of
# it actually runs along water. Deliberately well below what a river-preferring
# search really achieves in practice (measured 50-76% on real maps), so the
# classification is decisive rather than marginal.
RIVER_CORRIDOR_MIN_FRACTION = 0.35


def _capital_river_route(world, a_idx, b_idx):
    """``("river", cells)`` when two capitals can be linked by a route that
    mostly follows navigable water, else None. Cached on the same "capitals
    never move" assumption _capital_sea_path already relies on.

    Note this deliberately does NOT require both capitals to sit on one shared
    river system, the way domestic river shipments do (_regional_route). That
    rule cannot ever fire between two factions: river systems here average a
    few dozen cells while realms sit hundreds of cells apart, so no single
    river is ever touched by two different nations -- measured across several
    generated worlds, exactly zero river systems host settlements of more than
    one faction. What foreign trade actually wants is the historical pattern
    instead: barges working *along* a river corridor, hopping between the
    waterways that happen to run the right way, reaching inland cities that no
    coastline touches.

    So the search is an ordinary overland route whose cost function makes river
    cells nearly free rather than penalising them (the opposite of _elev_cost's
    normal river toll, which exists to stop ROADS fording rivers repeatedly).
    The result naturally hugs valleys; if enough of it ends up on water, it's a
    river route -- faster, and needing no construction, since the waterway is
    already there."""
    cache = getattr(world, "_capital_river_route_cache", None)
    if cache is None:
        cache = {}
        world._capital_river_route_cache = cache
    key = frozenset((a_idx, b_idx))
    if key in cache:
        return cache[key]

    a_st = _faction_capital_settlement(world.factions[a_idx], world)
    b_st = _faction_capital_settlement(world.factions[b_idx], world)
    result = None
    if a_st is not None and b_st is not None:
        path = _river_corridor_path(world, a_st.pos, b_st.pos,
                                    friendly_idxs=frozenset((a_idx, b_idx)))
        if path:
            river_cells = getattr(world, "river_cells", None) or set()
            share = sum(1 for c in path if c in river_cells) / len(path)
            if share >= RIVER_CORRIDOR_MIN_FRACTION:
                result = ("river", path)
    cache[key] = result
    return result


# How cheap a river cell is to travel compared with ordinary ground. Low enough
# that the search will detour a long way to pick a river up and stay on it.
_RIVER_CORRIDOR_COST = 0.15


def _river_corridor_path(world, a_pos, b_pos, friendly_idxs=None):
    """Overland path that treats navigable river cells as the cheap option
    instead of an obstacle -- the boat's-eye view of the same terrain
    _land_path_between walks. Same bbox/cellset machinery as that function."""
    river_cells = getattr(world, "river_cells", None) or set()
    if not river_cells:
        return None
    y0, y1 = sorted((a_pos[1], b_pos[1]))
    by0 = max(0, y0 - _TRADE_BBOX_PAD)
    by1 = min(world.h, y1 + _TRADE_BBOX_PAD + 1)
    xs = wrap.bbox_span_wrap(a_pos[0], b_pos[0], world.w, _TRADE_BBOX_PAD)
    cellset = {(x, y) for y in range(by0, by1) for x in xs
               if world.owner[y][x] != OCEAN}
    if a_pos not in cellset or b_pos not in cellset:
        return None

    def cost(cell):
        if cell in river_cells:
            return _RIVER_CORRIDOR_COST
        return _elev_cost(world, world.base_cost, cell, friendly_idxs=friendly_idxs)

    return _path_dijkstra(cellset, cost, a_pos, b_pos, world.w)


# --- the caravan/ship itself -------------------------------------------------
class TradeCaravan:
    """A caravan (land) or ship (sea) carrying one resource one way, then
    payment back -- Gold if the buyer's paying settlement has enough,
    otherwise a barter good of roughly equivalent value (see trade.py's
    Currency-overhaul helpers just above _nation_resource_stock). `pos`
    interpolates along `path` from the current leg's progress — purely for
    the "very basic" map marker, not physical simulation."""
    _next_id = 0

    def __init__(self, kind, seller_idx, buyer_idx, resource, quantity, price, path,
                 speed_multiplier=1.0, dest_settlement_id=None, origin_settlement_id=None):
        self.id = TradeCaravan._next_id
        TradeCaravan._next_id += 1
        self.kind = kind                # "land" | "sea"
        self.seller_idx = seller_idx
        self.buyer_idx = buyer_idx
        self.resource = resource
        self.quantity = quantity
        self.unit_price = price
        self.total_price = round(quantity * price)
        self.path = path                # cells, seller -> buyer order
        # Phase 11: which of the buyer's settlements this specific caravan
        # delivers to (de-capitalized trade — see unit_price's docstring).
        # None falls back to the capital, same as every caravan before
        # this phase (old-save-safe via getattr at the read site too).
        self.dest_settlement_id = dest_settlement_id
        # Currency overhaul: which of the seller's settlements gets paid --
        # collected from the buyer's paying settlement at outbound delivery,
        # only actually credited here once the return leg completes (see
        # advance_caravans). [(resource, quantity), ...], real Gold and/or
        # a barter good -- empty until delivery actually happens.
        self.origin_settlement_id = origin_settlement_id
        self.payment = []
        self.leg = "outbound"           # "outbound" | "return"
        river = kind == "river"
        cells_per_turn = RIVER_CELLS_PER_TURN if river else CELLS_PER_TURN
        floor = MIN_RIVER_CARAVAN_TURNS if river else MIN_TRANSIT_TURNS
        base_turns = max(floor, min(MAX_TRANSIT_TURNS,
                         round(len(path) / cells_per_turn)))
        # allies move goods faster — "free[r] movement through borders"
        self.turns_total = max(MIN_TRANSIT_TURNS, round(base_turns * speed_multiplier))
        self.turn_progress = 0

    @property
    def pos(self):
        frac = min(1.0, self.turn_progress / self.turns_total)
        idx = int(frac * (len(self.path) - 1))
        ordered = self.path if self.leg == "outbound" else list(reversed(self.path))
        return ordered[idx]


ALLY_TRANSIT_SPEEDUP = 0.8   # allied caravans take 20% less time — eased border crossings


def _dispatch_caravan(world, seller_idx, buyer_idx, resource, quantity, price, kind, path,
                      seller_settlement=None, buyer_settlement=None):
    seller = world.factions[seller_idx]
    buyer = world.factions[buyer_idx]
    if resource in _SETTLEMENT_STORAGE_RESOURCES:
        st = seller_settlement or _faction_capital_settlement(seller, world)
        if st is not None:
            if not hasattr(st, "resources"):
                st.resources = {}
            st.resources[resource] = max(0, st.resources.get(resource, 0) - quantity)
    else:
        res = seller.stats.setdefault("resources", {})
        res[resource] = max(0, res.get(resource, 0) - quantity)   # gone from the seller now, in transit
    rel = world.world_map.get_relationship(seller.id, buyer.id)
    speed = ALLY_TRANSIT_SPEEDUP if rel["stance"] == Stance.ALLY else 1.0
    dest_id = buyer_settlement.id if buyer_settlement is not None else None
    origin_st = seller_settlement or _faction_capital_settlement(seller, world)
    origin_id = origin_st.id if origin_st is not None else None
    world.trade_caravans.append(
        TradeCaravan(kind, seller_idx, buyer_idx, resource, quantity, price, path, speed,
                    dest_id, origin_id))


def _active_trade_count(world, fac_idx):
    return sum(1 for c in world.trade_caravans if c.seller_idx == fac_idx)


# --- turn loop hooks -----------------------------------------------------------
def advance_caravans(world):
    """Move every active caravan one turn; handle delivery/payment on
    arrival, and the war-risk loss check. Called before run_trade_ai each
    turn, so a slot freed by a completed trade can be reused immediately.
    Returns a list of event dicts (for UI messaging — see resources.py/
    map_view.py) describing what happened to each caravan this turn."""
    events = []
    remaining = []
    for c in world.trade_caravans:
        seller = world.factions[c.seller_idx]
        buyer = world.factions[c.buyer_idx]
        rel = world.world_map.get_relationship(seller.id, buyer.id)

        lost = False
        if rel["stance"] == Stance.ENEMY:
            lost = True   # trading with an active war enemy doesn't hold
        else:
            x, y = c.pos
            owner_idx = world.owner[y][x]
            if owner_idx >= 0 and owner_idx not in (c.seller_idx, c.buyer_idx):
                owner = world.factions[owner_idx]
                hostile = (world.world_map.get_relationship(owner.id, seller.id)["stance"] == Stance.ENEMY
                          or world.world_map.get_relationship(owner.id, buyer.id)["stance"] == Stance.ENEMY)
                if hostile and random.random() < LAND_RISK_PER_TURN:
                    lost = True   # raided while crossing hostile territory

        if lost:
            events.append({"type": "lost", "seller_idx": c.seller_idx, "buyer_idx": c.buyer_idx,
                           "resource": c.resource, "quantity": c.quantity, "price": c.total_price,
                           "leg": c.leg})
            continue   # caravan (and its goods/gold) simply vanishes

        c.turn_progress += 1
        if c.turn_progress < c.turns_total:
            remaining.append(c)
            continue

        dest_id = getattr(c, "dest_settlement_id", None)
        buyer_st = (world.settlements[dest_id] if dest_id is not None
                   else _faction_capital_settlement(buyer, world))

        if c.leg == "outbound":
            if c.resource in _SETTLEMENT_STORAGE_RESOURCES:
                if buyer_st is not None:
                    if not hasattr(buyer_st, "resources"):
                        buyer_st.resources = {}
                    # No storage-cap check on delivery -- same "never reject
                    # at the door" grace-period philosophy as production
                    # (Phase 9): an over-full granary just spoils faster
                    # next turn (advance_settlement_storage), it doesn't
                    # refuse the caravan.
                    buyer_st.resources[c.resource] = buyer_st.resources.get(c.resource, 0) + c.quantity
            else:
                res = buyer.stats.setdefault("resources", {})
                res[c.resource] = res.get(c.resource, 0) + c.quantity
                _clamp_to_storage(buyer)
            # Currency overhaul: the buyer's paying settlement covers the
            # price in Gold if it can, barters real goods for any shortfall
            # otherwise (see _collect_payment) -- collected now, but only
            # actually credited to the seller if the return leg completes
            # (see the "else" branch below), same real risk the goods
            # themselves already carried the other direction.
            c.payment = _collect_payment(buyer_st, c.total_price, world, world.season)
            events.append({"type": "delivered", "seller_idx": c.seller_idx, "buyer_idx": c.buyer_idx,
                          "resource": c.resource, "quantity": c.quantity, "price": c.total_price,
                          "payment": c.payment})
            c.leg = "return"
            c.turn_progress = 0
            remaining.append(c)
        else:
            origin_id = getattr(c, "origin_settlement_id", None)
            seller_st = (world.settlements[origin_id] if origin_id is not None
                        else _faction_capital_settlement(seller, world))
            payment, bonus_gold = _with_gold_bonus(
                c.payment, _species_gold_bonus(world, c.seller_idx))
            _deliver_payment(seller_st, payment)
            events.append({"type": "paid", "seller_idx": c.seller_idx, "buyer_idx": c.buyer_idx,
                          "resource": c.resource, "quantity": c.quantity, "price": c.total_price,
                          "payment": payment, "bonus_gold": bonus_gold})
            # round trip complete — caravan is simply not carried forward

    world.trade_caravans = remaining
    return events


def _route_for_pair(world, a_idx, b_idx):
    """A usable (kind, path) route for this faction pair, or None. Neither
    kind is ever auto-created here anymore — both a land route (finished
    construction) and a sea route require an explicit proposal and the
    other side's agreement first (see start_trade_route); this only looks
    up what's already been established."""
    route = world.trade_routes_by_pair.get(frozenset((a_idx, b_idx)))
    if route is None:
        return None
    return (route["kind"], route["cells"])


def run_trade_ai(world):
    """Greedy, capped, first-match — not an optimizer. See module docstring
    for why: this is the first autonomous-agent logic in the game. Returns a
    list of "dispatched" event dicts (see advance_caravans) for UI messaging."""
    events = []
    n = len(world.factions)

    for f_idx in range(n):
        seller = world.factions[f_idx]
        if _active_trade_count(world, f_idx) >= MAX_ACTIVE_TRADES_PER_FACTION:
            continue

        partners = [i for i in range(n) if i != f_idx]
        random.shuffle(partners)

        for p_idx in partners:
            buyer = world.factions[p_idx]
            if not eligible_to_trade(world, f_idx, p_idx):
                continue

            dispatched = False
            for resource in RESOURCES:
                surplus = sellable_surplus(seller, resource, world)
                if surplus < MIN_TRADE_QUANTITY:
                    continue
                if buyer_need(buyer, resource, world) <= 0:
                    continue

                # Phase 11: pick the actual settlement pair a settlement-
                # storage resource moves between, instead of always
                # assuming the capital (see unit_price's docstring) —
                # clamp the nation-aggregate surplus down to what that
                # ONE settlement genuinely has spare, since that's all a
                # single caravan can actually carry off.
                seller_st = buyer_st = None
                if resource in _SETTLEMENT_STORAGE_RESOURCES:
                    seller_st = _best_surplus_settlement(seller, resource, world)
                    if seller_st is None:
                        continue
                    buyer_st = _best_need_settlement(buyer, resource, world)
                    if buyer_st is None:
                        continue
                    st_needs = settlement_needs(seller_st, world.season)
                    surplus = min(surplus, _node_surplus(seller_st, resource, st_needs))
                    if surplus < MIN_TRADE_QUANTITY:
                        continue

                price = unit_price(resource, seller, buyer, world, seller_st, buyer_st)
                if price <= 0:
                    continue
                # Currency overhaul: the buyer's paying settlement caps how
                # big a deal it can afford -- Gold on hand plus what it
                # could barter instead (see _settlement_purchasing_power),
                # not a bottomless national wallet. Falls back to the
                # capital when this resource isn't settlement-storage
                # (buyer_st is None) -- see the loop above.
                power = (_settlement_purchasing_power(buyer_st, world, world.season)
                        if buyer_st is not None
                        else _settlement_purchasing_power(_faction_capital_settlement(buyer, world),
                                                          world, world.season))
                qty = int(min(surplus, power // price))
                if qty < MIN_TRADE_QUANTITY:
                    continue
                route = _route_for_pair(world, f_idx, p_idx)
                if route is None:
                    continue
                kind, path = route
                _dispatch_caravan(world, f_idx, p_idx, resource, qty, price, kind, path,
                                  seller_st, buyer_st)
                events.append({"type": "dispatched", "seller_idx": f_idx, "buyer_idx": p_idx,
                              "resource": resource, "quantity": qty, "price": round(qty * price)})
                dispatched = True
                break

            if dispatched:
                break

    return events


# --- trade route construction (land only; sea is automatic, see above) -------
class TradeRouteProject:
    """A land trade route under construction: grows from *both* ends of a
    precomputed capital-to-capital path simultaneously, meeting in the
    middle — built_from_a/built_from_b are cell counts built from each end.
    No fractional-turn accumulation (unlike SettlementProject/ClaimProject in
    construction.py/expansion.py), so there's no round()-vs-math.ceil()
    jumpy-countdown risk here by construction: progress is an exact cell
    count, shown directly rather than an estimated turn countdown."""

    def __init__(self, a_idx, b_idx, path):
        self.a_idx = a_idx
        self.b_idx = b_idx
        self.path = path
        self.built_from_a = 0
        self.built_from_b = 0

    @property
    def total_cells(self):
        return len(self.path) - 1

    @property
    def built_cells(self):
        return self.built_from_a + self.built_from_b

    @property
    def complete(self):
        return self.built_cells >= self.total_cells

    @property
    def built_segments(self):
        """The two growing prefixes (from each end) for rendering the
        in-progress route — see app/ui/map_view.py's
        _draw_trade_route_construction."""
        n = len(self.path)
        a_end = min(n, self.built_from_a + 1)
        b_start = max(a_end, n - self.built_from_b)
        return self.path[:a_end], self.path[b_start:]


TRADE_ROUTE_DECLINE_COOLDOWN_TURNS = 10   # matches expansion.CLAIM_FAIL_COOLDOWN_TURNS in spirit


# --- what a trade partner actually brings to the table ----------------------
def _faction_biome_set(world, faction_idx):
    """Every biome present anywhere in this faction's own territory --
    used to judge geographic resource ACCESS (could they ever produce
    this, given their land), not just what they're currently harvesting."""
    biomes = set()
    for region in world.regions:
        if region.faction_idx != faction_idx:
            continue
        biomes.update(getattr(region, "biome_counts", {}).keys())
    return biomes


def _accessible_raw_resources(world, faction_idx):
    """Every raw resource (RESOURCE_SPAWN) this faction could plausibly
    produce somewhere in its own territory, based on biome alone --
    regardless of whether it's actually being harvested yet."""
    biomes = _faction_biome_set(world, faction_idx)
    return {name for name, spec in RESOURCE_SPAWN.items() if spec["biomes"] & biomes}


def _faction_stocked_resources(world, faction_idx, min_amount=1):
    """Resources this faction currently holds a real stockpile of,
    aggregated across its own settlements."""
    nation = world.factions[faction_idx]
    totals = {}
    for sid in nation.meta.get("settlements", []):
        for r, amt in getattr(world.settlements[sid], "resources", {}).items():
            totals[r] = totals.get(r, 0) + amt
    return {r for r, amt in totals.items() if amt >= min_amount}


def trade_complementarity_summary(world, viewer_idx, other_idx):
    """What `other_idx` brings to a trade route, from `viewer_idx`'s own
    point of view: resources they currently HAVE real stock of that the
    viewer doesn't, and raw resources they could ACCESS somewhere in
    their own territory (by biome) that the viewer's territory has no
    access to at all -- whether or not it's actually being harvested yet.
    Used by the trade-route proposal UI (both directions: the player's
    own outgoing proposal and an AI's incoming one) so accepting/
    proposing is actually informed by what's on the table, not a blind
    guess. Returns {"have": [...], "access": [...]}, both sorted."""
    their_stock = _faction_stocked_resources(world, other_idx)
    our_stock = _faction_stocked_resources(world, viewer_idx)
    have_advantage = their_stock - our_stock

    their_access = _accessible_raw_resources(world, other_idx)
    our_access = _accessible_raw_resources(world, viewer_idx)
    # Excludes anything already listed under "have" so a resource they're
    # both stocking AND geographically favored for isn't listed twice
    # under two different framings.
    access_advantage = their_access - our_access - have_advantage

    return {"have": sorted(have_advantage), "access": sorted(access_advantage)}


def _has_pending_proposal(world, from_idx):
    return any(p["from_idx"] == from_idx for p in world.incoming_trade_proposals)


def accept_trade_route_proposal(world, from_idx):
    """The player accepts an AI's pending trade-route proposal (see
    run_trade_route_ai) -- the same route-formation logic
    start_trade_route uses once a proposal is agreed to (land path takes
    priority, physically built over time; a sea route opens immediately),
    just skipping diplomacy.evaluate_trade_route entirely, since the
    player's own acceptance already IS the decision it would otherwise
    make on their behalf."""
    world.incoming_trade_proposals = [p for p in world.incoming_trade_proposals
                                      if p["from_idx"] != from_idx]
    player_idx = world.player_faction_idx
    key = frozenset((from_idx, player_idx))
    if key in world.trade_routes_by_pair:
        return "A trade route already connects you."
    a = world.factions[from_idx]
    land_path = _land_capital_path(world, from_idx, player_idx)
    coastal = _coastal_factions(world)
    sea_result = (_capital_sea_path(world, from_idx, player_idx)
                 if from_idx in coastal and player_idx in coastal else None)
    if land_path is not None:
        world.trade_route_projects.append(TradeRouteProject(from_idx, player_idx, land_path))
        return f"You agree — construction begins on a trade route with {a.name}."
    if sea_result is not None:
        kind, sea_path = sea_result
        route = {"kind": kind, "cells": sea_path, "a_faction": from_idx, "b_faction": player_idx}
        world.trade_routes.append(route)
        world.trade_routes_by_pair[key] = route
        return f"You agree — a sea trade route opens with {a.name}."
    return "No viable route exists between your capitals after all."


def decline_trade_route_proposal(world, from_idx):
    """The player declines an AI's pending proposal -- sets the same
    decline cooldown a formula-driven AI-to-AI decline would (see
    start_trade_route), so the same faction doesn't just re-propose again
    next turn."""
    world.incoming_trade_proposals = [p for p in world.incoming_trade_proposals
                                      if p["from_idx"] != from_idx]
    key = frozenset((from_idx, world.player_faction_idx))
    world.trade_route_decline_until[key] = world.turn + TRADE_ROUTE_DECLINE_COOLDOWN_TURNS
    return f"You decline {world.factions[from_idx].name}'s trade proposal."


def start_trade_route(world, a_idx, b_idx):
    """Propose a trade route (land or sea, whichever exists — land takes
    priority when both do, since it's the more substantial connection)
    between a_idx and b_idx's capitals. Neither kind opens automatically
    anymore: the other side has to actually agree (see
    diplomacy.evaluate_trade_route), the same "propose, then either
    accepted or declined" flow form_alliance already uses — a land route
    still takes real turns to build once agreed to, a sea route opens
    immediately since there's nothing physical to construct across open
    water. Returns a message describing what happened (success, decline,
    or why proposing isn't possible at all) — used identically by the
    player's UI action and run_trade_route_ai, one code path for both."""
    if a_idx == b_idx:
        return "A nation can't trade with itself."
    if not eligible_to_trade(world, a_idx, b_idx):
        return "Relations aren't warm enough yet to propose a trade route."
    key = frozenset((a_idx, b_idx))
    if key in world.trade_routes_by_pair:
        return "A trade route already connects these two."
    if any(frozenset((p.a_idx, p.b_idx)) == key for p in world.trade_route_projects):
        return "A trade route is already under construction between these two."
    decline_until = getattr(world, "trade_route_decline_until", {}).get(key, -1)
    if world.turn < decline_until:
        return "They're not ready to reconsider a trade proposal yet."

    a, b = world.factions[a_idx], world.factions[b_idx]
    # Priority: RIVER > LAND > SEA. A shared river is the best connection going
    # -- fastest, and already navigable, so nothing has to be built.
    river_result = _capital_river_route(world, a_idx, b_idx)
    land_path = _land_capital_path(world, a_idx, b_idx)
    coastal = _coastal_factions(world)
    sea_result = (_capital_sea_path(world, a_idx, b_idx)
                 if a_idx in coastal and b_idx in coastal else None)
    if river_result is None and land_path is None and sea_result is None:
        return "No viable route exists between these two capitals."

    from app.world import diplomacy
    accepted, reason = diplomacy.evaluate_trade_route(world, a, b)
    if not accepted:
        if not hasattr(world, "trade_route_decline_until"):
            world.trade_route_decline_until = {}
        world.trade_route_decline_until[key] = world.turn + TRADE_ROUTE_DECLINE_COOLDOWN_TURNS
        return f"{b.name} declines the trade proposal — {reason}."

    if river_result is not None:
        kind, river_path_cells = river_result
        route = {"kind": kind, "cells": river_path_cells,
                 "a_faction": a_idx, "b_faction": b_idx}
        world.trade_routes.append(route)
        world.trade_routes_by_pair[key] = route
        return (f"{b.name} agrees — a river trade route opens between "
                f"{a.name} and {b.name}.")

    if land_path is not None:
        world.trade_route_projects.append(TradeRouteProject(a_idx, b_idx, land_path))
        return f"{b.name} agrees — construction begins on a trade route between {a.name} and {b.name}."

    kind, sea_path = sea_result
    route = {"kind": kind, "cells": sea_path, "a_faction": a_idx, "b_faction": b_idx}
    world.trade_routes.append(route)
    world.trade_routes_by_pair[key] = route
    return f"{b.name} agrees — a sea trade route opens between {a.name} and {b.name}."


def advance_trade_route_projects(world):
    """Called every turn: grow each project's built_from_a, then whatever's
    left of this turn's budget into built_from_b, so the two ends meet
    roughly in the middle; finalize anything that's crossed the finish
    line into a usable route."""
    finished = []
    for proj in world.trade_route_projects:
        remaining = proj.total_cells - proj.built_cells
        if remaining <= 0:
            finished.append(proj)
            continue
        step_a = min(TRADE_ROUTE_CELLS_PER_TURN, remaining)
        proj.built_from_a += step_a
        remaining -= step_a
        if remaining > 0:
            proj.built_from_b += min(TRADE_ROUTE_CELLS_PER_TURN, remaining)
        if proj.complete:
            finished.append(proj)

    for proj in finished:
        world.trade_route_projects.remove(proj)
        route = {"kind": "land", "cells": proj.path,
                "a_faction": proj.a_idx, "b_faction": proj.b_idx}
        world.trade_routes.append(route)
        world.trade_routes_by_pair[frozenset((proj.a_idx, proj.b_idx))] = route


def run_trade_route_ai(world):
    """Greedy, capped, first-match — same style as run_trade_ai (see that
    function's docstring for why). Each faction with spare capacity
    proposes a route to its best eligible, not-yet-connected partner, by
    resource complementarity (reusing diplomacy's own scarcity model —
    already used by form_alliance — rather than inventing a second one)."""
    from app.world import diplomacy
    events = []
    n = len(world.factions)
    active = {}
    building_pairs = set()
    for proj in world.trade_route_projects:
        active[proj.a_idx] = active.get(proj.a_idx, 0) + 1
        active[proj.b_idx] = active.get(proj.b_idx, 0) + 1
        building_pairs.add(frozenset((proj.a_idx, proj.b_idx)))

    order = list(range(n))
    random.shuffle(order)
    for f_idx in order:
        if active.get(f_idx, 0) >= MAX_ACTIVE_ROUTE_PROJECTS_PER_FACTION:
            continue
        if f_idx == world.player_faction_idx:
            continue   # the player proposes for themself, via their own UI
        if _has_pending_proposal(world, f_idx):
            continue   # already waiting on a player response, don't pile on
        seller = world.factions[f_idx]
        decline_until = getattr(world, "trade_route_decline_until", {})
        candidates = []
        for p_idx in range(n):
            if p_idx == f_idx:
                continue
            key = frozenset((f_idx, p_idx))
            if key in world.trade_routes_by_pair or key in building_pairs:
                continue
            if world.turn < decline_until.get(key, -1):
                continue   # declined recently -- don't re-pester them every turn
            if eligible_to_trade(world, f_idx, p_idx) and route_path_possible(world, f_idx, p_idx):
                candidates.append(p_idx)
        if not candidates:
            continue

        best = max(candidates, key=lambda p:
                   diplomacy._resource_complementarity(world, seller, world.factions[p]))
        key = frozenset((f_idx, best))

        if best == world.player_faction_idx:
            # The player gets an actual choice instead of this auto-
            # resolving through diplomacy.evaluate_trade_route the way an
            # AI-to-AI proposal does -- see accept_trade_route_proposal/
            # decline_trade_route_proposal (map_view.py surfaces this on
            # the proposing faction's info panel).
            world.incoming_trade_proposals.append(
                {"from_idx": f_idx, "turn_proposed": world.turn})
            events.append({"type": "route_proposed", "from_idx": f_idx})
            active[f_idx] = active.get(f_idx, 0) + 1
            building_pairs.add(key)
            continue

        start_trade_route(world, f_idx, best)
        established = key in world.trade_routes_by_pair
        building = key in {frozenset((p.a_idx, p.b_idx)) for p in world.trade_route_projects}
        if established or building:
            events.append({"type": "route_started", "a_idx": f_idx, "b_idx": best})
            active[f_idx] = active.get(f_idx, 0) + 1
            building_pairs.add(key)

    return events


# --- Phase 11: regional markets (domestic, cross-region settlement trade) ----
# "Once transportation exists, settlements can begin trading. If they cannot
# produce something, they will buy it."
#
# resources.run_local_logistics (Phase 10) already redistributes freely
# within a single region, and that section's own docstring flags exactly
# what it deliberately leaves alone: "cross-region logistics... a real
# follow-up, not attempted here." This is that follow-up, for Settlements
# only (see the module's own reasoning: a Village has no way to reach
# beyond its region on its own — it routes through its region's own
# Settlement first via Phase 10, and that Settlement is the one that
# reaches out further here).
#
# Unlike Phase 10's free redistribution, this genuinely costs Gold — the
# same national treasury settlement tax_income already feeds (see
# resources.advance_turn) — priced with the same tier/surplus/need formula
# as foreign trade (_regional_unit_price mirrors unit_price). Buyer and
# seller share one treasury here (same faction), so payment doesn't need a
# caravan to physically carry gold home the way a foreign TradeCaravan's
# return leg does — it's deducted on dispatch and credited back on
# delivery, the same pool either way, which still ties up real working
# capital for the length of the trip and makes it a genuine constraint
# (a treasury too empty to front the cost can't dispatch), just without
# inventing a meaningless net wealth transfer to itself.
#
# Same-region pairs are skipped entirely — Phase 10 already covers those
# for free, and there's no reason to spend Gold moving something a wagon
# would've carried for nothing this same turn.
#
# Risk: a shipment can be lost crossing UNCLAIMED wildland or another
# faction's territory if that faction is at war with you — same shape as
# a foreign TradeCaravan's LAND_RISK_PER_TURN, since a faction's own
# regions aren't guaranteed to be geographically contiguous (a neutral
# or hostile pocket can sit between two of your own regions).
#
# Deliberately out of scope, same as foreign trade: no sea legs (land path
# only, via _land_path_between) — a faction whose settlements are only
# reachable by sea from each other simply can't regional-trade between them
# yet, a natural follow-up alongside foreign sea trade routes, not
# attempted here.

REGIONAL_TRADE_MIN_QUANTITY = 15
REGIONAL_TRADE_MAX_QUANTITY = 50
MAX_ACTIVE_REGIONAL_SHIPMENTS_PER_SETTLEMENT = 2
REGIONAL_SHIPMENT_CELLS_PER_TURN = 10
# Boats beat wagons handily: a river is a prepared, downhill-assisted highway
# with no terrain to fight, so a river-borne shipment covers far more ground
# per turn than the same goods hauled overland. This is what makes "both ends
# sit on the same river" a genuinely valuable position to hold.
RIVER_SHIPMENT_CELLS_PER_TURN = 30
# ...but the cells-per-turn rate alone delivers nothing here, because two nodes
# on the same river system are nearly always CLOSE (river systems are small --
# a few dozen cells) and both routes then bottom out at the same minimum
# transit. The lower floor is what actually makes river trade quick: goods move
# between neighbouring river towns in a turn instead of three.
MIN_RIVER_TRANSIT_TURNS = 1
MIN_REGIONAL_TRANSIT_TURNS, MAX_REGIONAL_TRANSIT_TURNS = 3, 25
REGIONAL_SHIPMENT_RISK_PER_TURN = 0.08


def _get_regional_path_cache(world):
    """Settlement/village positions never change once placed, so a path
    between two of them is cacheable forever — same reasoning as
    _get_path_cache for capital-to-capital sea paths, just keyed by node
    id pair instead of faction id pair (and covering land only — see the
    module note above)."""
    # NOTE the attribute name is versioned (_v2): the pre-river cache stored a
    # bare path per key, this one stores a (transport, path) tuple. A save
    # pickled before river trade carries the old dict, so reusing the old name
    # would feed bare paths straight into tuple-unpacking call sites.
    cache = getattr(world, "_regional_route_cache_v2", None)
    if cache is None:
        cache = {}
        world._regional_route_cache_v2 = cache
    return cache


def _regional_node_kind(node):
    return "settlement" if hasattr(node, "kind") else "village"


REGIONAL_PATH_BUDGET_PER_TURN = 1   # cap on brand-new (uncached) Dijkstra path
                                     # lookups per turn, shared by
                                     # run_regional_trade/run_sell_to_city --
                                     # widening Regional Markets to include
                                     # every Village (not just Settlements,
                                     # see _faction_regional_nodes) means a
                                     # much bigger pool of possible node
                                     # pairs. Not just a one-time startup
                                     # cost either: new Villages keep
                                     # appearing all game (city growth),
                                     # each one creating a fresh batch of
                                     # never-yet-pathed pairs -- measured,
                                     # real hitching without this cap, even
                                     # well into the midgame. Kept
                                     # deliberately tight (real per-turn
                                     # cost measured down to ~1ms/turn
                                     # amortized at 1) rather than a bigger
                                     # number that only helps once at
                                     # startup; already-cached pairs are
                                     # completely unaffected and stay
                                     # instant forever once resolved.


def _regional_route(world, a_node, b_node):
    """``(transport, path)`` between two of a faction's own nodes for Regional
    Markets purposes -- ``("river", cells)`` when both ends sit on the same
    connected river system and a navigable path exists, otherwise
    ``("land", cells)``, or ``(None, None)`` when neither works.

    Works for a Settlement or a Village on either side (see
    run_regional_trade's node-widening). Settlement ids and Village ids are
    separate, independently-numbered id spaces (world.settlements[5] and
    world.villages[5] are unrelated objects) -- the cache key tags each side
    with its own kind so a settlement and a village that happen to share a
    numeric id can never collide.

    River is tried first because it's both faster and, being water, free of
    the terrain tolls a land haul pays. Falling back to land keeps the same
    single-faction preference as before: both ends always belong to the SAME
    faction here, so the land search prefers staying on that faction's own
    territory and only crosses anyone else's when there's no reasonable way
    around it (see worldgen._elev_cost's faction_idx param)."""
    cache = _get_regional_path_cache(world)
    key = frozenset(((_regional_node_kind(a_node), a_node.id),
                     (_regional_node_kind(b_node), b_node.id)))
    if key in cache:
        return cache[key]
    budget = getattr(world, "_regional_path_budget", REGIONAL_PATH_BUDGET_PER_TURN)
    if budget <= 0:
        # Not cached yet -- try again once the budget resets next turn.
        return (None, None)
    world._regional_path_budget = budget - 1

    result = (None, None)
    system_id = rivers.shared_river_system(world, a_node, b_node)
    if system_id is not None:
        river_cells = rivers.river_path(world, a_node.pos, b_node.pos, system_id)
        if river_cells:
            result = ("river", river_cells)
    if result[1] is None:
        land = _land_path_between(world, a_node.pos, b_node.pos, pad=_REGIONAL_BBOX_PAD,
                                  friendly_idxs=frozenset((a_node.faction_idx,)))
        if land:
            result = ("land", land)
    cache[key] = result
    return result


def _regional_unit_price(resource, seller_st, buyer_st, world):
    """Same tier/surplus/need formula as unit_price, evaluated at the
    specific node pair (there's no nation-aggregate fallback here —
    regional trade is node-to-node by construction; either side can be a
    Settlement or a Village -- see run_regional_trade's node-widening).
    No ally tariff discount: that's a foreign-diplomacy concept,
    meaningless within one's own faction."""
    tier = RESOURCES.get(resource, {}).get("tier", 3)
    base = BASE_VALUE_BY_TIER.get(tier, 3)

    seller_needs = settlement_needs(seller_st, world.season)
    surplus = _node_surplus(seller_st, resource, seller_needs)
    seller_cap = _node_storage_capacity(seller_st)
    surplus_ratio = min(2.0, surplus / (seller_cap * 0.1 + 1))
    seller_factor = max(0.6, 1.2 - 0.4 * surplus_ratio)

    buyer_cap = _node_storage_capacity(buyer_st)
    stock = getattr(buyer_st, "resources", {}).get(resource, 0)
    need = max(0.0, 1.0 - stock / buyer_cap) if buyer_cap > 0 else 0.0
    buyer_factor = min(2.5, 0.7 + 1.8 * need)

    return round(base * seller_factor * buyer_factor, 2)


class RegionalShipment:
    """Goods (and Gold) physically moving between two of the same faction's
    nodes in DIFFERENT regions — either a Settlement or a Village on
    either end (see run_regional_trade's node-widening: a Village with
    real surplus can export it just as a Settlement can, and a Village
    lacking something can receive it directly too, not just whatever a
    Settlement in its region happens to redistribute onward via local
    logistics) — the cross-region follow-up to resources.LocalShipment
    (same-region, free — see that class and the module note above for why
    this one's separate). Real terrain-aware path (via _regional_route),
    real multi-turn transit, real risk of loss while in transit — the
    foreign-trade shape, not the free-logistics shape, since this is
    priced.

    origin_kind/dest_kind ("settlement" or "village") say which of
    world.settlements/world.villages origin_id/dest_id actually indexes
    into — the two id spaces are independent and can overlap, so the id
    alone is never enough to resolve a node (see advance_regional_
    shipments)."""
    _next_id = 0

    def __init__(self, faction_idx, resource, quantity, price, path,
                origin_id, dest_id, origin_kind="settlement", dest_kind="settlement",
                transport="land"):
        self.id = RegionalShipment._next_id
        RegionalShipment._next_id += 1
        self.faction_idx = faction_idx
        self.resource = resource
        self.quantity = quantity
        self.unit_price = price
        self.total_price = round(quantity * price)
        self.path = path
        self.origin_id = origin_id
        self.dest_id = dest_id
        self.origin_kind = origin_kind
        self.dest_kind = dest_kind
        # "land" (wagons) or "river" (boats) -- note this is the TRANSPORT
        # mode, distinct from origin_kind/dest_kind which say whether each end
        # is a settlement or a village. Defaults to "land" so a shipment
        # unpickled from a pre-river save is still coherent.
        self.transport = transport
        river = transport == "river"
        cells_per_turn = (RIVER_SHIPMENT_CELLS_PER_TURN if river
                          else REGIONAL_SHIPMENT_CELLS_PER_TURN)
        floor = MIN_RIVER_TRANSIT_TURNS if river else MIN_REGIONAL_TRANSIT_TURNS
        self.turns_total = max(floor,
                              min(MAX_REGIONAL_TRANSIT_TURNS,
                                  round(len(path) / cells_per_turn)))
        self.turn_progress = 0
        # Currency overhaul: what the destination settlement actually paid
        # at dispatch (Gold and/or a barter good, see _collect_payment) --
        # set by the caller right after construction (price is 0.0/no
        # payment for a free sell-to-city shipment, so this stays empty
        # for those); credited to the origin settlement on delivery.
        self.payment = []

    @property
    def pos(self):
        frac = min(1.0, self.turn_progress / self.turns_total)
        idx = int(frac * (len(self.path) - 1))
        return self.path[idx]


def _active_regional_shipments(world, node_id, kind="settlement"):
    """`kind` disambiguates settlement ids from village ids (independent,
    overlapping id spaces -- see RegionalShipment's own docstring)."""
    return sum(1 for s in world.regional_shipments
              if s.origin_id == node_id and s.origin_kind == kind)


def _faction_regional_nodes(world, fac_idx, nation):
    """Every Settlement AND Village this faction owns, as (kind, node)
    pairs -- what run_regional_trade actually matches surplus/need across.
    Villages used to be invisible to this tier entirely: a Village could
    only ever receive goods a same-region Settlement chose to pass along
    (run_local_logistics), and could only ever export surplus to that same
    Settlement -- stranding a Village sitting on real surplus (e.g. next
    to the only forest for miles) whenever its own region's Settlement(s)
    didn't happen to need what it had, and leaving a Village with no
    Settlement in its region (or a region with no local source of some
    good at all -- e.g. no forest anywhere in it) with no path to ever
    receiving it, regardless of how much surplus the rest of the faction
    was sitting on elsewhere."""
    nodes = [("settlement", world.settlements[sid]) for sid in nation.meta.get("settlements", [])]
    nodes += [("village", v) for v in world.villages if v.faction_idx == fac_idx]
    return nodes


def run_regional_trade(world):
    """Called every turn, after run_local_logistics has already had its
    shot at satisfying need within each region: for each faction, greedily
    match a Settlement or Village sitting on cross-region-worthy surplus
    of a household-economy resource to another of that faction's
    Settlements or Villages (in a DIFFERENT region) that genuinely needs
    it, and dispatch a paid RegionalShipment — same greedy-first-match
    style as run_trade_ai/run_local_logistics, not an optimizer. Returns
    "regional_dispatched" event dicts (see advance_regional_shipments for
    the delivered/lost counterparts)."""
    world._regional_path_budget = REGIONAL_PATH_BUDGET_PER_TURN
    events = []
    season = world.season
    for fac_idx, nation in enumerate(world.factions):
        nodes = _faction_regional_nodes(world, fac_idx, nation)
        if len(nodes) < 2:
            continue
        has_gold = _faction_has_gold_source(world, fac_idx)
        needs_by_node = {(kind, node.id): settlement_needs(node, season) for kind, node in nodes}

        # Who wants what, computed ONCE per faction per turn rather than
        # re-scanning every other node for every surplus resource a
        # source might have (an O(nodes^2 * resources) scan otherwise) --
        # widening this tier to include every Village, not just
        # Settlements (see _faction_regional_nodes), made that quadratic
        # cost real: a faction with a few dozen villages was re-checking
        # "does this village want Wheat" dozens of times over for every
        # single surplus-holding node's Wheat, every turn, forever. This
        # collapses that scan to O(nodes * resources) up front, then the
        # matching loop below only ever looks at nodes actually wanting
        # the specific resource in hand.
        wants_by_resource = {}
        for wkind, wnode in nodes:
            wneeds = needs_by_node[(wkind, wnode.id)]
            for resource in _LOCAL_SHIPMENT_PRIORITY:
                if _node_wants(wkind, wnode, resource, wneeds):
                    wants_by_resource.setdefault(resource, []).append((wkind, wnode))

        for kind, node in nodes:
            if _active_regional_shipments(world, node.id, kind) >= MAX_ACTIVE_REGIONAL_SHIPMENTS_PER_SETTLEMENT:
                continue
            own_needs = needs_by_node[(kind, node.id)]
            dispatched = False
            for resource in _LOCAL_SHIPMENT_PRIORITY:
                surplus = _node_surplus(node, resource, own_needs)
                if surplus < REGIONAL_TRADE_MIN_QUANTITY:
                    continue
                for other_kind, other in wants_by_resource.get(resource, ()):
                    if other is node or other.region_id == node.region_id:
                        continue   # same region -- Phase 10 already covers this for free
                    # Path lookup first (and budget-limited -- see
                    # REGIONAL_PATH_BUDGET_PER_TURN) since it's the
                    # single most expensive check here: no point pricing
                    # a deal (below) or checking purchasing power for a
                    # candidate that can't be reached this turn anyway,
                    # once the much bigger node pool _faction_regional_
                    # nodes' village-widening created made that waste
                    # actually add up.
                    transport, path = _regional_route(world, node, other)
                    if path is None:
                        continue
                    price = _regional_unit_price(resource, node, other, world)
                    if price <= 0:
                        continue
                    # Currency overhaul: `other` (the buyer) caps the deal
                    # by its own Gold + barter purchasing power now, not
                    # the faction's old bottomless wallet -- unless this
                    # faction has no reliable Gold source at all (see
                    # _faction_has_gold_source), in which case Gold isn't
                    # spendable here either, so it's excluded from the cap
                    # too (matching _collect_payment's allow_gold below) --
                    # otherwise a deal could get sized off spending power
                    # the settlement is never actually allowed to use.
                    power = _settlement_purchasing_power(other, world, season,
                                                         include_gold=has_gold)
                    qty = int(min(surplus, REGIONAL_TRADE_MAX_QUANTITY, power // price))
                    if qty < REGIONAL_TRADE_MIN_QUANTITY:
                        continue

                    if not hasattr(node, "resources"):
                        node.resources = {}
                    node.resources[resource] = max(0, node.resources.get(resource, 0) - qty)
                    total_price = round(qty * price)
                    shipment = RegionalShipment(fac_idx, resource, qty, price, path,
                                                node.id, other.id, kind, other_kind,
                                                transport=transport)
                    shipment.payment = _collect_payment(other, total_price, world, season,
                                                        barter_first=True, allow_gold=has_gold)
                    world.regional_shipments.append(shipment)
                    events.append({"type": "regional_dispatched", "faction_idx": fac_idx,
                                  "resource": resource, "quantity": qty, "price": total_price,
                                  "payment": shipment.payment,
                                  "origin_name": node.name, "dest_name": other.name})
                    dispatched = True
                    break
                if dispatched:
                    break

    return events


def advance_regional_shipments(world):
    """Called every turn: move every in-transit RegionalShipment, apply the
    wildland/hostile-territory loss check (see the module note above), and
    deliver + settle payment on arrival. Returns event dicts, same
    convention as advance_caravans."""
    events = []
    remaining = []
    for s in world.regional_shipments:
        nation = world.factions[s.faction_idx]
        x, y = s.pos
        owner_idx = world.owner[y][x]
        risky = owner_idx == UNCLAIMED or (
            owner_idx >= 0 and owner_idx != s.faction_idx
            and world.world_map.get_relationship(
                nation.id, world.factions[owner_idx].id)["stance"] == Stance.ENEMY)
        origin = (world.settlements[s.origin_id] if s.origin_kind == "settlement"
                 else world.villages[s.origin_id])
        dest = (world.settlements[s.dest_id] if s.dest_kind == "settlement"
               else world.villages[s.dest_id])
        if risky and random.random() < REGIONAL_SHIPMENT_RISK_PER_TURN:
            events.append({"type": "regional_lost", "faction_idx": s.faction_idx,
                          "resource": s.resource, "quantity": s.quantity, "price": s.total_price,
                          "origin_name": origin.name, "dest_name": dest.name})
            continue

        s.turn_progress += 1
        if s.turn_progress < s.turns_total:
            remaining.append(s)
            continue

        if not hasattr(dest, "resources"):
            dest.resources = {}
        dest.resources[s.resource] = dest.resources.get(s.resource, 0) + s.quantity
        # Currency overhaul: payment was collected from `dest` (the buyer)
        # at dispatch time (see run_regional_trade) -- credited to `origin`
        # (the seller) here, real Gold and/or a barter good, same shape as
        # foreign trade's return leg.
        _deliver_payment(origin, s.payment)
        events.append({"type": "regional_delivered", "faction_idx": s.faction_idx,
                      "resource": s.resource, "quantity": s.quantity, "price": s.total_price,
                      "payment": s.payment,
                      "origin_name": origin.name, "dest_name": dest.name})

    world.regional_shipments = remaining
    return events


# --- Sell to City: non-perishable overflow relief -----------------------------
# Local Logistics (Phase 10) and Regional Markets (above) both only ever
# move a resource to somewhere that genuinely NEEDS it (_node_wants) -- if
# nothing anywhere in the faction currently needs more Iron, neither one
# ever moves an overflowing settlement's surplus Iron anywhere, even to a
# settlement with plenty of free storage, and it just decays via the
# overflow penalty (see resources.py's Storage & Spoilage) for no real
# reason. This closes that gap specifically for non-perishables
# (spoil_rate == 0 -- there's no urgency for anything that already spoils
# on its own timeline; that's what the need-based tiers above are for): a
# City-kind settlement always has room for a same-faction settlement's
# non-perishable surplus, whether or not it "needs" it in the
# settlement_needs sense, acting as an internal trade hub that then
# exports it through the faction's existing foreign trade (see
# run_trade_ai/_best_surplus_settlement above). Since more supply sitting
# at the city already lowers unit_price's surplus-based factor
# automatically, the "sell off excess -> price drops -> corrects itself
# over time" dynamic just falls out of pricing that already exists --
# nothing new needed for that part.
#
# Reuses RegionalShipment/_regional_route/_active_regional_shipments
# wholesale (same terrain-aware pathing, same risk of loss crossing
# unclaimed/hostile territory) -- the only real difference is price is
# always 0: unlike Regional Markets' genuine domestic sale, this leg is
# free, the same "just relocate the goods" shape Local Logistics uses.
# Charging Gold for it (even internally, same treasury either end) would
# leave a cash-poor faction unable to ever relieve overflow decay exactly
# when it matters most; the real Gold in this whole picture is what the
# city eventually earns exporting it, unchanged from how foreign trade
# already works.
SELL_TO_CITY_MIN_QUANTITY = 15
SELL_TO_CITY_MAX_QUANTITY = 50
# A City stops absorbing once its own total stock reaches this fraction of
# its own storage capacity, so this doesn't just relocate the overflow
# problem from the settlement onto the city instead of actually helping.
CITY_STOCKPILE_CEILING_FRACTION = 0.8

_NONPERISHABLE_RESOURCES = {name for name in _SETTLEMENT_STORAGE_RESOURCES
                            if RESOURCES.get(name, {}).get("spoil_rate", 0) <= 0}


def _faction_cities(nation, world):
    return [st for st in _faction_settlements(nation, world) if st.kind == "city"]


def _nearest_city(st, cities, world):
    if not cities:
        return None
    return min(cities, key=lambda c: wrap.dist2_wrap(c.pos, st.pos, world.w))


def run_sell_to_city(world):
    """Called every turn: for each faction with at least one City, match a
    settlement sitting on non-perishable surplus (the same _node_surplus
    reserve logic every other logistics tier already uses) to its nearest
    same-faction City, and dispatch a free RegionalShipment there --
    greedy first-match, same style as run_regional_trade, and sharing that
    same MAX_ACTIVE_REGIONAL_SHIPMENTS_PER_SETTLEMENT cap (both tiers pull
    from the same world.regional_shipments pool, so a settlement's limited
    outbound slots are shared between genuine domestic trade and this).
    Returns "sold_to_city" event dicts -- delivery/loss are handled
    generically by advance_regional_shipments, same as any other
    RegionalShipment."""
    events = []
    season = world.season
    for fac_idx, nation in enumerate(world.factions):
        cities = _faction_cities(nation, world)
        if not cities:
            continue
        sids = nation.meta.get("settlements", [])
        settlements = [world.settlements[sid] for sid in sids]
        needs_by_st = {st.id: settlement_needs(st, season) for st in settlements}

        for st in settlements:
            if st.kind == "city":
                continue   # a City doesn't sell to itself
            if _active_regional_shipments(world, st.id) >= MAX_ACTIVE_REGIONAL_SHIPMENTS_PER_SETTLEMENT:
                continue
            own_needs = needs_by_st[st.id]
            for resource in sorted(_NONPERISHABLE_RESOURCES):
                surplus = _node_surplus(st, resource, own_needs)
                if surplus < SELL_TO_CITY_MIN_QUANTITY:
                    continue
                city = _nearest_city(st, [c for c in cities if c is not st], world)
                if city is None:
                    continue
                cap = settlement_storage_capacity(city)
                stock = sum(getattr(city, "resources", {}).values())
                if cap <= 0 or stock >= cap * CITY_STOCKPILE_CEILING_FRACTION:
                    continue
                qty = min(surplus, SELL_TO_CITY_MAX_QUANTITY)
                transport, path = _regional_route(world, st, city)
                if path is None:
                    continue

                if not hasattr(st, "resources"):
                    st.resources = {}
                st.resources[resource] = max(0, st.resources.get(resource, 0) - qty)
                world.regional_shipments.append(RegionalShipment(
                    fac_idx, resource, qty, 0.0, path, st.id, city.id,
                    transport=transport))
                events.append({"type": "sold_to_city", "faction_idx": fac_idx,
                              "resource": resource, "quantity": qty,
                              "origin_name": st.name, "dest_name": city.name})
                break

    return events
