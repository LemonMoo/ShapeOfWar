"""Autonomous inter-faction trade: every faction independently evaluates and
initiates trades with others each turn (no player involvement required — the
player's own faction is just one more participant, not special-cased).

Trade is gated on diplomacy, not just geography: two factions must have
made contact (app/world/diplomacy.establish_contact — fired by the player's
fog-of-war discovery, or a shared border for anyone — see
app/world/vision.py and app/world/territory.py) and be on decent terms
(standing >= TRADE_STANDING_THRESHOLD) before any deal can happen at all —
see eligible_to_trade(). A *land* route additionally has to be physically
built before caravans can use it: TradeRouteProject grows a precomputed
capital-to-capital path from both ends at once, meeting in the middle (see
start_trade_route/advance_trade_route_projects) — the player proposes one
via the UI, AI factions do the same via run_trade_route_ai. Sea lanes stay
automatic once eligible (nothing to physically build across open water) —
see _capital_sea_path.

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
from app.world.worldgen import (OCEAN, _path_dijkstra, _nearest_ocean_cell,
                                _elev_cost, _sea_cost, _bfs_distance,
                                _SEA_COAST_REACH)
from app.world.resources import (RESOURCES, BASE_VALUE_BY_TIER, _LOCAL_FOOD,
                                 _storage_cap, _clamp_to_storage)
from app.world.diplomacy import TRADE_STANDING_THRESHOLD

# --- market ------------------------------------------------------------------
MIN_TRADE_QUANTITY = 20
SAFETY_RESERVE_TURNS = 8          # food: never sell below N turns of upkeep
NON_FOOD_RESERVE_FRACTION = 0.1   # non-food: never sell below 10% of storage cap

MAX_ACTIVE_TRADES_PER_FACTION = 3
CELLS_PER_TURN = 15
MIN_TRANSIT_TURNS, MAX_TRANSIT_TURNS = 5, 20
LAND_RISK_PER_TURN = 0.08         # per turn, crossing land at war with either party
_TRADE_BBOX_PAD = 30

# --- trade route construction (land only; sea is automatic, see below) -------
TRADE_ROUTE_CELLS_PER_TURN = 6           # per end, per turn -- matches construction.ROAD_CELLS_PER_TURN
MAX_ACTIVE_ROUTE_PROJECTS_PER_FACTION = 1


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
    """Faction indices owning at least one coastal settlement — computed
    once per turn, not once per pair (unlike territory.naval_reachable_regions,
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


# --- routing: capital-to-capital ---------------------------------------------
def _get_path_cache(world):
    cache = getattr(world, "_trade_sea_path_cache", None)
    if cache is None:
        cache = {}
        world._trade_sea_path_cache = cache
    return cache


def _land_capital_path(world, a_idx, b_idx):
    """Terrain-aware land path between two factions' capitals, or None if
    no land connection exists — used once, when a land route is proposed
    (start_trade_route); unlike the sea case there's nothing to cache
    against since land routes are only ever computed at proposal time, not
    re-derived every turn."""
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
    if a_pos not in land_cellset or b_pos not in land_cellset:
        return None
    return _path_dijkstra(land_cellset, lambda c: _elev_cost(world, world.base_cost, c),
                          a_pos, b_pos)


def _capital_sea_path(world, a_idx, b_idx):
    """("sea", cells) route between two factions' capitals over open water,
    or None if no sea connection exists. Cached — capitals never move, so
    the path is constant for the whole game. Land routes no longer auto-
    compute here at all: they require actually being built (see
    TradeRouteProject) — sea is the only kind that stays automatic, since
    there's nothing physical to construct across open water. The first time
    a pair's sea path is found, it's also registered into world.trade_routes
    /trade_routes_by_pair so it renders (see app/ui/map_view.py's
    _draw_trade_routes, which just reads that list generically)."""
    cache = _get_path_cache(world)
    key = frozenset((a_idx, b_idx))
    if key in cache:
        return cache[key]

    a_pos = world.factions[a_idx].meta["capital"]
    b_pos = world.factions[b_idx].meta["capital"]
    x0, x1 = sorted((a_pos[0], b_pos[0]))
    y0, y1 = sorted((a_pos[1], b_pos[1]))
    bx0 = max(0, x0 - _TRADE_BBOX_PAD)
    by0 = max(0, y0 - _TRADE_BBOX_PAD)
    bx1 = min(world.w, x1 + _TRADE_BBOX_PAD + 1)
    by1 = min(world.h, y1 + _TRADE_BBOX_PAD + 1)

    path = None
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

    result = ("sea", path) if path else None
    cache[key] = result
    if result is not None:
        route = {"kind": "sea", "cells": path, "a_faction": a_idx, "b_faction": b_idx}
        world.trade_routes.append(route)
        world.trade_routes_by_pair[key] = route
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


def _route_for_pair(world, a_idx, b_idx, coastal):
    """A usable (kind, path) route for this faction pair, or None: an
    already-completed land route (see TradeRouteProject) takes priority;
    otherwise an automatic sea lane if both sides are coastal. Land is never
    auto-computed here — it has to have actually been built."""
    land = world.trade_routes_by_pair.get(frozenset((a_idx, b_idx)))
    if land is not None and land["kind"] == "land":
        return ("land", land["cells"])
    if a_idx in coastal and b_idx in coastal:
        return _capital_sea_path(world, a_idx, b_idx)
    return None


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
            if not eligible_to_trade(world, f_idx, p_idx):
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
                route = _route_for_pair(world, f_idx, p_idx, coastal)
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


def start_trade_route(world, a_idx, b_idx):
    """Validate and kick off building a land trade route between a_idx and
    b_idx's capitals. Returns a message describing what happened (success
    or why not) — used identically by the player's UI action and
    run_trade_route_ai, one code path for both."""
    if a_idx == b_idx:
        return "A nation can't trade with itself."
    if not eligible_to_trade(world, a_idx, b_idx):
        return "Relations aren't warm enough yet to propose a trade route."
    key = frozenset((a_idx, b_idx))
    if key in world.trade_routes_by_pair:
        return "A trade route already connects these two."
    if any(frozenset((p.a_idx, p.b_idx)) == key for p in world.trade_route_projects):
        return "A trade route is already under construction between these two."

    path = _land_capital_path(world, a_idx, b_idx)
    if path is None:
        return "No viable land route exists between these two capitals."

    world.trade_route_projects.append(TradeRouteProject(a_idx, b_idx, path))
    a_name, b_name = world.factions[a_idx].name, world.factions[b_idx].name
    return f"Construction begins on a trade route between {a_name} and {b_name}."


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
        seller = world.factions[f_idx]
        candidates = []
        for p_idx in range(n):
            if p_idx == f_idx:
                continue
            key = frozenset((f_idx, p_idx))
            if key in world.trade_routes_by_pair or key in building_pairs:
                continue
            if eligible_to_trade(world, f_idx, p_idx):
                candidates.append(p_idx)
        if not candidates:
            continue

        best = max(candidates, key=lambda p:
                   diplomacy._resource_complementarity(world, seller, world.factions[p]))
        msg = start_trade_route(world, f_idx, best)
        if msg.startswith("Construction begins"):
            events.append({"type": "route_started", "a_idx": f_idx, "b_idx": best})
            active[f_idx] = active.get(f_idx, 0) + 1
            building_pairs.add(frozenset((f_idx, best)))

    return events
