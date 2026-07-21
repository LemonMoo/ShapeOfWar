"""Autonomous inter-faction trade: every faction independently evaluates and
initiates trades with others each turn (no player involvement required — the
player's own faction is just one more participant, not special-cased).

A deal is carried out by a TradeCaravan (land) or ship (sea, same class) that
travels from the seller's capital to the buyer's, delivers the goods and
collects payment there, then must make it *back home* before the seller
actually receives the gold — modeling real risk (a caravan can be lost if war
breaks out while it's in transit) instead of an instant wire transfer.

First-pass simplifications (see the plan this was built from): trade routes
always run capital-to-capital rather than picking a specific settlement;
the AI is a greedy first-match, not a globally optimal matching; caravan risk
is driven only by the existing war/relationship system, no separate
bandit/piracy mechanic.
"""
import random

from app.world.world_map import Stance
from app.world.worldgen import (OCEAN, _path_dijkstra, _nearest_ocean_cell,
                                _elev_cost, _sea_cost, _bfs_distance,
                                _SEA_COAST_REACH)
from app.world.resources import RESOURCES, _LOCAL_FOOD, _storage_cap, _clamp_to_storage

# --- market ------------------------------------------------------------------
BASE_VALUE_BY_TIER = {1: 2, 2: 4, 3: 3, 4: 12}   # gold/unit before scarcity
MIN_TRADE_QUANTITY = 20
SAFETY_RESERVE_TURNS = 8          # food: never sell below N turns of upkeep
NON_FOOD_RESERVE_FRACTION = 0.1   # non-food: never sell below 10% of storage cap

MAX_ACTIVE_TRADES_PER_FACTION = 3
CELLS_PER_TURN = 15
MIN_TRANSIT_TURNS, MAX_TRANSIT_TURNS = 5, 20
LAND_RISK_PER_TURN = 0.08         # per turn, crossing land at war with either party
_TRADE_BBOX_PAD = 30


def _settlement_upkeep_total(nation, resource, world):
    return sum(world.settlements[sid].upkeep.get(resource, 0)
               for sid in nation.meta.get("settlements", []))


def _safety_reserve(nation, resource, world):
    if resource in _LOCAL_FOOD:
        return _settlement_upkeep_total(nation, resource, world) * SAFETY_RESERVE_TURNS
    return _storage_cap(nation, resource) * NON_FOOD_RESERVE_FRACTION


def sellable_surplus(nation, resource, world):
    """How much of `resource` this nation can spare without dipping into its
    own safety margin — food reserves are sized off real upkeep, not a
    guess, so a faction physically cannot sell grain it needs to eat."""
    stock = nation.stats.get("resources", {}).get(resource, 0)
    return max(0, int(stock - _safety_reserve(nation, resource, world)))


def buyer_need(nation, resource, world):
    """0 (stockpile full, no interest) .. 1 (empty, desperate)."""
    stock = nation.stats.get("resources", {}).get(resource, 0)
    cap = _storage_cap(nation, resource)
    return max(0.0, 1.0 - stock / cap) if cap > 0 else 0.0


ALLY_TARIFF_DISCOUNT = 0.85   # allied trade is cheaper — "lower tariffs"


def unit_price(resource, seller, buyer, world):
    """Base tier value, discounted if the seller has ample surplus, marked up
    if the buyer is scarce for it, discounted further for allies (lower
    tariffs). Pure data/formula — easy to retune."""
    tier = RESOURCES.get(resource, {}).get("tier", 3)
    base = BASE_VALUE_BY_TIER.get(tier, 3)

    surplus = sellable_surplus(seller, resource, world)
    reserve = _safety_reserve(seller, resource, world)
    surplus_ratio = min(2.0, surplus / (reserve + 1))
    seller_factor = max(0.6, 1.2 - 0.4 * surplus_ratio)

    need = buyer_need(buyer, resource, world)
    buyer_factor = min(2.5, 0.7 + 1.8 * need)

    price = base * seller_factor * buyer_factor
    rel = world.world_map.get_relationship(seller.id, buyer.id)
    if rel["stance"] == Stance.ALLY:
        price *= ALLY_TARIFF_DISCOUNT
    return round(price, 2)


# --- cheap reachability (not the expensive attack-pathing checks) ----------
def _land_connected(world, a, b):
    """Relationships only ever get created between land-bordering factions
    (world-gen adjacency roll, or territory._refresh_borders after a
    conquest) — so "a relationship exists" already means "shares a land
    border," for free."""
    return frozenset((a.id, b.id)) in world.world_map.relationships


def _coastal_factions(world):
    """Faction indices owning at least one coastal settlement — computed
    once per turn, not once per pair (unlike territory.naval_reachable_counties,
    which does a fresh BFS per attack — far too slow to run for every
    faction-pair every turn)."""
    ocean_cells = [(x, y) for y in range(world.h) for x in range(world.w)
                   if world.owner[y][x] == OCEAN]
    if not ocean_cells:
        return set()
    coast_d = _bfs_distance(world, ocean_cells)
    coastal = set()
    for st in world.settlements:
        x, y = st.pos
        if coast_d[y][x] <= _SEA_COAST_REACH:
            coastal.add(st.faction_idx)
    return coastal


# --- routing: capital-to-capital, cached per faction pair for the game -----
def _get_path_cache(world):
    cache = getattr(world, "_trade_path_cache", None)
    if cache is None:
        cache = {}
        world._trade_path_cache = cache
    return cache


def _capital_path(world, a_idx, b_idx):
    """(kind, cells) route between two factions' capitals, land if possible
    else sea, else None. Cached — capitals never move, so the path is
    constant for the whole game; reused by every future trade between the
    same two factions instead of re-pathfinding each time."""
    cache = _get_path_cache(world)
    key = frozenset((a_idx, b_idx))
    if key in cache:
        return cache[key]

    a_pos = world.factions[a_idx].meta["capital"]
    b_pos = world.factions[b_idx].meta["capital"]
    ax, ay = a_pos
    bx, by = b_pos
    x0, x1 = sorted((ax, bx))
    y0, y1 = sorted((ay, by))
    bx0 = max(0, x0 - _TRADE_BBOX_PAD)
    by0 = max(0, y0 - _TRADE_BBOX_PAD)
    bx1 = min(world.w, x1 + _TRADE_BBOX_PAD + 1)
    by1 = min(world.h, y1 + _TRADE_BBOX_PAD + 1)

    land_cellset = {(x, y) for y in range(by0, by1) for x in range(bx0, bx1)
                     if world.owner[y][x] != OCEAN}
    path = None
    if a_pos in land_cellset and b_pos in land_cellset:
        path = _path_dijkstra(land_cellset, lambda c: _elev_cost(world, world.base_cost, c),
                              a_pos, b_pos)

    kind = "land"
    if path is None:
        dock_a = _nearest_ocean_cell(world, a_pos)
        dock_b = _nearest_ocean_cell(world, b_pos)
        if dock_a and dock_b:
            sea_cellset = {(x, y) for y in range(by0, by1) for x in range(bx0, bx1)
                           if world.owner[y][x] == OCEAN}
            sea_path = _path_dijkstra(sea_cellset,
                                      lambda c: _sea_cost(world, world.base_cost, c),
                                      dock_a, dock_b)
            if sea_path is not None:
                path = [a_pos] + sea_path + [b_pos]
                kind = "sea"

    result = (kind, path) if path else None
    cache[key] = result
    return result


# --- the caravan/ship itself -------------------------------------------------
class TradeCaravan:
    """A caravan (land) or ship (sea) carrying one resource one way, then
    gold back. `pos` interpolates along `path` from the current leg's
    progress — purely for the "very basic" map marker, not physical
    simulation."""
    _next_id = 0

    def __init__(self, kind, seller_idx, buyer_idx, resource, quantity, price, path,
                 speed_multiplier=1.0):
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
        self.leg = "outbound"           # "outbound" | "return"
        base_turns = max(MIN_TRANSIT_TURNS, min(MAX_TRANSIT_TURNS,
                         round(len(path) / CELLS_PER_TURN)))
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


def _dispatch_caravan(world, seller_idx, buyer_idx, resource, quantity, price, kind, path):
    seller = world.factions[seller_idx]
    buyer = world.factions[buyer_idx]
    res = seller.stats.setdefault("resources", {})
    res[resource] = max(0, res.get(resource, 0) - quantity)   # gone from the seller now, in transit
    rel = world.world_map.get_relationship(seller.id, buyer.id)
    speed = ALLY_TRANSIT_SPEEDUP if rel["stance"] == Stance.ALLY else 1.0
    world.trade_caravans.append(
        TradeCaravan(kind, seller_idx, buyer_idx, resource, quantity, price, path, speed))


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
            if owner_idx != OCEAN and owner_idx not in (c.seller_idx, c.buyer_idx):
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

        if c.leg == "outbound":
            res = buyer.stats.setdefault("resources", {})
            res[c.resource] = res.get(c.resource, 0) + c.quantity
            _clamp_to_storage(buyer)
            buyer.stats["gold"] = max(0, buyer.stats.get("gold", 0) - c.total_price)
            events.append({"type": "delivered", "seller_idx": c.seller_idx, "buyer_idx": c.buyer_idx,
                          "resource": c.resource, "quantity": c.quantity, "price": c.total_price})
            c.leg = "return"
            c.turn_progress = 0
            remaining.append(c)
        else:
            seller.stats["gold"] = seller.stats.get("gold", 0) + c.total_price
            events.append({"type": "paid", "seller_idx": c.seller_idx, "buyer_idx": c.buyer_idx,
                          "resource": c.resource, "quantity": c.quantity, "price": c.total_price})
            # round trip complete — caravan is simply not carried forward

    world.trade_caravans = remaining
    return events


def run_trade_ai(world):
    """Greedy, capped, first-match — not an optimizer. See module docstring
    for why: this is the first autonomous-agent logic in the game. Returns a
    list of "dispatched" event dicts (see advance_caravans) for UI messaging."""
    events = []
    coastal = _coastal_factions(world)
    n = len(world.factions)

    for f_idx in range(n):
        seller = world.factions[f_idx]
        if _active_trade_count(world, f_idx) >= MAX_ACTIVE_TRADES_PER_FACTION:
            continue

        partners = [i for i in range(n) if i != f_idx]
        random.shuffle(partners)

        for p_idx in partners:
            buyer = world.factions[p_idx]
            rel = world.world_map.get_relationship(seller.id, buyer.id)
            if rel["stance"] == Stance.ENEMY:
                continue
            if not (_land_connected(world, seller, buyer)
                    or (f_idx in coastal and p_idx in coastal)):
                continue

            dispatched = False
            for resource in RESOURCES:
                surplus = sellable_surplus(seller, resource, world)
                if surplus < MIN_TRADE_QUANTITY:
                    continue
                if buyer_need(buyer, resource, world) <= 0:
                    continue
                price = unit_price(resource, seller, buyer, world)
                if price <= 0:
                    continue
                qty = int(min(surplus, buyer.stats.get("gold", 0) // price))
                if qty < MIN_TRADE_QUANTITY:
                    continue
                route = _capital_path(world, f_idx, p_idx)
                if route is None:
                    continue
                kind, path = route
                _dispatch_caravan(world, f_idx, p_idx, resource, qty, price, kind, path)
                events.append({"type": "dispatched", "seller_idx": f_idx, "buyer_idx": p_idx,
                              "resource": resource, "quantity": qty, "price": round(qty * price)})
                dispatched = True
                break

            if dispatched:
                break

    return events
