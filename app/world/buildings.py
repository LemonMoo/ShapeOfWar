"""What a settlement or village can build, and whether it is worth building.

The build lever already existed before this module -- construction.py has had
tiered Granaries, Warehouses, Vaults, Barns, Preserving Houses, herd buildings
and Shipyards for several phases. What it did not have was any way to find out
which of them a given node actually NEEDS. Measured on the turn-561 benchmark
world: one Granary and one Warehouse existed across 42 settlements and 609
villages. The buildings were reachable in principle and unreachable in
practice, because nothing in the game connected "this village lands 30 Fish a
turn and watches most of it rot" to "so build a Preserving House".

This module is that connection, and it is deliberately game logic rather than
UI code: the recommendation is a claim about the simulation ("this granary is
94% full and the harvest is being turned away"), it has to be testable without
standing up a widget tree, and the AI's own build choice (construction.
run_storage_ai) reasons about exactly the same question. app/ui/build_menu.py
is a view on top of this, nothing more.

Two things it deliberately does NOT do:
  * It never spends anything. start_storage_building/start_shipyard stay the
    only paths that move resources, so a recommendation can never become an
    accidental purchase.
  * It never invents a building. Everything here is discovered from
    construction.py's own tables, so a building added there shows up here
    without a second registry to keep in step.
"""
from app.world import construction
from app.world import resources


# How full a pool has to be before its building counts as urgent rather than
# merely useful. Below STORAGE_THROTTLE_START nothing is being turned away yet,
# so that is the natural line for "this is costing you something right now".
URGENT_FILL = resources.STORAGE_THROTTLE_START
USEFUL_FILL = 0.55

# Perishable inflow per turn at which a Preserving House stops being a nicety.
# Sized off the measured hole it exists for: Fish and Smoked Fish are 35% of
# everything the map destroys, and a node landing this much of it is losing
# real tonnage every single turn.
URGENT_PERISHABLE_FLOW = 12
USEFUL_PERISHABLE_FLOW = 4

PRIORITY_ORDER = {"urgent": 0, "useful": 1, "idle": 2, "blocked": 3}


class BuildOption:
    """One card in the build menu: a building, the tier it would go to, what
    it costs, and whether this particular node has any reason to want it."""

    def __init__(self, building, label, category, current_tier, max_tier,
                 to_tier=None, cost=None, turns=0, affordable=False,
                 blocked=None, in_progress=None, effects=(),
                 priority="idle", reason="", score=0.0):
        self.building = building          # key, e.g. "granary"
        self.label = label                # "Granary"
        self.category = category          # "Storage" | "Food" | "Livestock" | "Naval"
        self.current_tier = current_tier
        self.max_tier = max_tier
        self.to_tier = to_tier            # None when nothing can be started
        self.cost = cost or {}
        self.turns = turns
        self.affordable = affordable
        self.blocked = blocked            # human reason, or None
        self.in_progress = in_progress    # (elapsed, total) while building
        self.effects = list(effects)      # human lines describing what it does
        self.priority = priority          # "urgent" | "useful" | "idle" | "blocked"
        self.reason = reason              # one line: why this node wants it
        self.score = score                # for ordering within a priority

    @property
    def buildable(self):
        return self.to_tier is not None and self.blocked is None and self.affordable

    @property
    def sort_key(self):
        return (PRIORITY_ORDER.get(self.priority, 9), -self.score, self.label)

    def __repr__(self):
        return (f"<BuildOption {self.label} t{self.current_tier}->{self.to_tier} "
                f"{self.priority} {self.reason!r}>")


BUILDING_CATEGORY = {
    "granary": "Storage", "warehouse": "Storage", "vault": "Storage",
    "barn": "Livestock", resources.PRESERVING_HOUSE: "Food",
    "pasture": "Livestock", "stable": "Livestock", "slaughterhouse": "Livestock",
    "shipyard": "Naval",
    resources.GOLD_MINE: "Coin", resources.MINT: "Coin",
}

BUILDING_BLURB = {
    "granary": "Room for the harvest, the catch and the winter firewood.",
    "warehouse": "Room for timber, stone, ore and everything made from them.",
    "vault": "Room for coin and luxuries.",
    "barn": "Hay store and winter shelter: less fodder needed, fewer animals lost.",
    resources.PRESERVING_HOUSE:
        "Cures perishables before they rot. Burns Salt doing it.",
    "pasture": "More head of every animal this village can keep.",
    "stable": "More horses, and a stronger mounted arm.",
    "slaughterhouse": "More meat and leather from every animal taken.",
    "shipyard": "Launches free, faster ships from this coastal city.",
    resources.GOLD_MINE:
        "Works the seam properly. More ore out of the same ground — "
        "and more hands out of the fields to do it.",
    resources.MINT:
        "Strikes Gold Ore into coin. Upper tiers recover more metal "
        "from every unit of ore.",
}

# Ore on hand at a settlement above which a Mint is plainly the bottleneck,
# and ore produced per turn at a village above which a Gold Mine is worth it.
URGENT_MINT_ORE = 60
URGENT_MINE_ORE_FLOW = 3


# Plain language for what a herd building's multiplier actually acts on -- the
# bare number ("0.75") says nothing on its own. Moved here from map_view's own
# _HERD_EFFECT_TEXT when the build UI moved out of the side panel; it is
# description of a game effect, which belongs next to the effect.
HERD_EFFECT_TEXT = {
    ("pasture", "capacity"): "Herd capacity ×{v:g}",
    ("stable", "capacity"): "Horse capacity ×{v:g}",
    ("barn", "feed"): "Winter fodder need ×{v:g}",
    ("barn", "death"): "Livestock deaths ×{v:g}",
    ("slaughterhouse", "yield"): "Meat & Leather per head ×{v:g}",
}


def _label(building):
    return building.replace("_", " ").title()


def node_kind(node):
    return "settlement" if hasattr(node, "kind") else "village"


# --- what this node produces -------------------------------------------------

def production_report(world, node):
    """What this node actually makes, in the terms the player thinks in.

    A Village works land, so its report is the Phase 14 labor breakdown --
    which sectors its hands are on, what the land offered, and which of the
    two ceilings is binding. A Settlement works stock: it has no fields of its
    own, it runs the conversion recipes (see
    advance_settlement_production_chains), so its report is which of those
    recipes can currently run and which are starved of input."""
    if node_kind(node) == "village":
        report = resources.village_labor_report(world, node)
        report["kind"] = "village"
        report["fish_potential"] = getattr(node, "fish_yield", 0) or 0
        report["herds"] = dict(getattr(node, "herds", {}) or {})
        return report

    res = getattr(node, "resources", {}) or {}
    recipes = []
    for output, options in resources.RECIPES.items():
        if output not in resources._SETTLEMENT_STORAGE_RESOURCES:
            continue
        luxury = resources.RESOURCES[output]["luxury"]
        cap = (resources.LUXURY_CONVERSION_RATE_CAP if luxury
               else resources.CONVERSION_RATE_CAP)
        best = None
        for option in options:
            inputs = option["inputs"]
            available = min(res.get(i, 0) for i in inputs)
            running = min(available, cap)
            if best is None or running > best[1]:
                best = (inputs, running)
        if best is None:
            continue
        inputs, running = best
        if luxury and world.turn < resources.LUXURY_CONVERSION_MIN_TURN:
            note = f"not until turn {resources.LUXURY_CONVERSION_MIN_TURN}"
        elif running <= 0:
            note = "no input"
        elif running >= cap:
            note = "at capacity"
        else:
            note = "short of input"
        recipes.append({"output": output, "inputs": list(inputs),
                        "rate": running, "cap": cap, "note": note})
    recipes.sort(key=lambda r: (-r["rate"], r["output"]))
    return {"kind": "settlement", "recipes": recipes,
            "preserving": resources.preserving_cap_multiplier(node)}


# --- does this node want it? -------------------------------------------------

def _pool_pressure(node, pool):
    """(fill fraction, capacity) for one of this node's storage pools."""
    capacity = resources.node_pool_capacity(node, pool)
    if capacity <= 0:
        return 0.0, 0
    return resources.node_pool_stock(node, pool) / capacity, capacity


def _dominant_occupant(node, pool):
    """The single resource taking the most SPACE in `pool` -- what turns
    "my warehouse is full" into "my warehouse is full of Softwood"."""
    res = getattr(node, "resources", {}) or {}
    best, best_space = None, 0
    for r, amount in res.items():
        if amount <= 0 or resources.storage_class(r) != pool:
            continue
        space = amount * resources.resource_bulk(r)
        if space > best_space:
            best, best_space = r, space
    return best


def _storage_verdict(node, pool):
    fill, capacity = _pool_pressure(node, pool)
    if capacity <= 0:
        return "idle", "No storage of this kind here yet.", 0.0
    occupant = _dominant_occupant(node, pool)
    of_what = f" of {occupant}" if occupant else ""
    if fill >= URGENT_FILL:
        return ("urgent",
                f"{int(fill * 100)}% full{of_what} — production is being turned away.",
                fill)
    if fill >= USEFUL_FILL:
        return ("useful", f"{int(fill * 100)}% full{of_what}.", fill)
    return "idle", f"Only {int(fill * 100)}% full — no pressure yet.", fill


def _perishable_flow(world, node):
    """Units of perishable input arriving at this node per turn that a
    Preserving House could cure. The catch is the big one (Fish is landed
    straight here every turn) but a herd's Milk and Meat count too."""
    flow = 0.0
    if node_kind(node) == "village":
        factors, _raw = resources.village_labor_state(world, node, world.season)
        flow += (getattr(node, "fish_yield", 0) or 0) * factors.get("fishing", 0.0)
    else:
        flow += getattr(node, "fish_yield", 0) or 0
    res = getattr(node, "resources", {}) or {}
    # Whatever is already sitting in stock counts for far less than a live
    # inflow: a stockpile is a one-off to work through, a flow is every turn
    # forever. Same reasoning construction.run_storage_ai's own preserve
    # score uses -- scoring stock alone built exactly zero houses, because a
    # good spoiling at 0.35 never survives long enough to look like a pile.
    for source in resources.PRESERVATION_RECIPES.values():
        flow += res.get(source, 0) * 0.1
    return flow


def _preserving_verdict(world, node):
    flow = _perishable_flow(world, node)
    if flow >= URGENT_PERISHABLE_FLOW:
        return ("urgent",
                f"About {flow:.0f} units of perishables land here every turn and "
                f"most of it rots.", flow)
    if flow >= USEFUL_PERISHABLE_FLOW:
        return "useful", f"About {flow:.0f} units of perishables arrive per turn.", flow
    if flow > 0:
        return "idle", "Only a trickle of perishables here.", flow
    return "idle", "Nothing perishable is produced here.", 0.0


def _herd_verdict(world, node, building):
    herds = getattr(node, "herds", None) or {}
    head = sum(herds.values())
    if head <= 0:
        return "idle", "No herd here yet.", 0.0
    if building == "barn":
        need = resources.village_winter_fodder_need(node)
        stock = (getattr(node, "resources", {}) or {}).get("Fodder", 0)
        if need > 0 and stock < need:
            return ("urgent",
                    f"{head:,} head need {need:,.0f} Fodder for Winter and only "
                    f"{stock:,} is stored.", float(need - stock))
        return "useful", f"{head:,} head to shelter through Winter.", float(head)
    if building == "stable":
        horses = herds.get("Horses", 0)
        if horses <= 0:
            return "idle", "No horses here.", 0.0
        return "useful", f"{horses:,} horses to raise and remount from.", float(horses)
    if building == "pasture":
        pressure = 0.0
        for animal, count in herds.items():
            capacity = resources.village_herd_capacity(world, node, animal)
            if capacity > 0:
                pressure = max(pressure, count / capacity)
        if pressure >= 0.9:
            return ("urgent",
                    f"The herd is at {int(pressure * 100)}% of what this land can "
                    f"carry.", pressure)
        return "useful", f"Herd at {int(pressure * 100)}% of capacity.", pressure
    # slaughterhouse
    return "useful", f"{head:,} head to take more from at the Autumn cull.", float(head)


def _mint_verdict(world, node):
    """A Mint is judged on ore actually sitting here, not on how much coin the
    faction has: the constraint it lifts is throughput against a supply of ore,
    and a settlement with no ore gains nothing from a better mint."""
    res = getattr(node, "resources", {}) or {}
    ore = res.get("Gold Ore", 0)
    rate = int(resources.CONVERSION_RATE_CAP * resources.mint_rate_multiplier(node))
    if ore <= 0:
        return ("idle",
                "No Gold Ore reaches this settlement — a mint here would stand "
                "idle.", 0.0)
    if ore >= URGENT_MINT_ORE and ore > rate:
        return ("urgent",
                f"{ore:,} Gold Ore is waiting and this settlement can only "
                f"strike {rate:,} a turn.", float(ore))
    if ore > rate:
        return "useful", f"{ore:,} Gold Ore on hand, {rate:,} struck per turn.", float(ore)
    return "idle", f"{ore:,} Gold Ore on hand — the mint keeps up as it is.", float(ore)


def _gold_mine_verdict(world, node):
    """A Gold Mine is judged on the seam, not on the stockpile: it changes what
    comes OUT of the ground, so what matters is whether there is ore under this
    village at all and how much of it is already being worked."""
    factors, raw = resources.village_labor_state(world, node, world.season)
    flow = raw.get("Gold Ore", 0) * factors.get("mining", 0.0)
    if flow >= URGENT_MINE_ORE_FLOW:
        return ("useful",
                f"This seam yields about {flow:.0f} ore a turn. A deeper mine "
                f"multiplies that.", flow)
    return ("useful",
            "There is a gold seam under this village, barely scratched.", 1.0)


def _verdict(world, node, building):
    """(priority, reason, score) -- does THIS node want THIS building?"""
    if building == resources.MINT:
        return _mint_verdict(world, node)
    if building == resources.GOLD_MINE:
        return _gold_mine_verdict(world, node)
    pool = resources.STORAGE_POOL_BY_BUILDING.get(building)
    if building == "barn":
        # The Barn is both the feed store and the shelter. Judge it on
        # whichever case is more urgent rather than picking one arbitrarily.
        feed = _storage_verdict(node, "feed")
        herd = _herd_verdict(world, node, "barn")
        return min((feed, herd), key=lambda v: PRIORITY_ORDER[v[0]])
    if pool is not None:
        return _storage_verdict(node, pool)
    if building == resources.PRESERVING_HOUSE:
        return _preserving_verdict(world, node)
    if building in resources.HERD_BUILDINGS:
        return _herd_verdict(world, node, building)
    if building == "shipyard":
        return "useful", "A coastal city can launch its own ships.", 1.0
    return "idle", "", 0.0


# --- effect lines ------------------------------------------------------------

def _storage_effect_lines(node, building, to_tier):
    lines = []
    pool = resources.STORAGE_POOL_BY_BUILDING.get(building)
    if pool is not None:
        table = (resources.VILLAGE_STORAGE_TIER_BONUS if node_kind(node) == "village"
                 else resources.STORAGE_TIER_BONUS).get(building, [0])
        if to_tier is not None and to_tier < len(table):
            added = table[to_tier] - table[to_tier - 1]
            current = resources.node_pool_capacity(node, pool)
            lines.append(f"+{added:,} {pool} space  ({current:,} → {current + added:,})")
    if building == resources.GOLD_MINE and to_tier is not None:
        table = resources.GOLD_MINE_YIELD_MULT
        if to_tier < len(table):
            now = table[min(resources.storage_tier(node, building), len(table) - 1)]
            lines.append(f"Gold Ore dug here ×{table[to_tier]:g}  (now ×{now:g})")
            lines.append("Worked by the same hands as the fields and woods")
    if building == resources.MINT and to_tier is not None:
        rates, yields = resources.MINT_RATE_MULT, resources.MINT_YIELD_PER_ORE
        if to_tier < len(rates):
            now_rate = int(resources.CONVERSION_RATE_CAP
                           * rates[min(resources.storage_tier(node, building),
                                       len(rates) - 1)])
            lines.append(f"Strikes up to {int(resources.CONVERSION_RATE_CAP * rates[to_tier]):,} "
                         f"ore per turn  (now {now_rate:,})")
        if to_tier < len(yields) and yields[to_tier] > 1.0:
            lines.append(f"{yields[to_tier]:g} coin per unit of ore — less metal "
                         f"left in the slag")
    if building == resources.PRESERVING_HOUSE and to_tier is not None:
        table = (resources.VILLAGE_PRESERVING_CAP_MULT if node_kind(node) == "village"
                 else resources.PRESERVING_CAP_MULT)
        if to_tier < len(table):
            rate = int(resources.CONVERSION_RATE_CAP * table[to_tier])
            lines.append(f"Cures up to {rate:,} units per turn")
            lines.append("Fish → Smoked Fish, Milk → Cheese, Meat → Salted Meat")
            lines.append("Salt burned per unit: " + ", ".join(
                f"{out} {resources.SALT_PER_PRESERVED[out]:g}"
                for out in resources.PRESERVATION_RECIPES
                if out in resources.SALT_PER_PRESERVED))
    for effect, table in resources.HERD_BUILDING_EFFECTS.get(building, {}).items():
        if to_tier is None or to_tier >= len(table):
            continue
        text = HERD_EFFECT_TEXT.get((building, effect))
        if not text:
            continue
        now = table[min(resources.storage_tier(node, building), len(table) - 1)]
        lines.append(text.format(v=table[to_tier]) + f"  (now ×{now:g})")
    return lines


# --- the list ----------------------------------------------------------------

def _all_buildings(node):
    """Every building this KIND of node could ever have, in menu order.
    Discovered from construction.py's own tables rather than listed again
    here, so a new building appears in the menu the turn it is added.

    Kind gating only (storage_max_tier takes no world). The Gold Mine's second
    gate -- is there actually a seam under this village -- is applied in
    build_options, which does have one."""
    order = [resources.STORAGE_BUILDING_BY_POOL[p] for p in resources.STORAGE_POOLS]
    order.append(resources.PRESERVING_HOUSE)
    for herd_building in resources.HERD_BUILDINGS:
        if herd_building not in order:
            order.append(herd_building)
    order += [resources.GOLD_MINE, resources.MINT]
    if node_kind(node) == "settlement":
        order.append("shipyard")
    return [b for b in order if resources.storage_max_tier(node, b) > 0
            or b == "shipyard"]


def _in_progress(world, node, building):
    kind = node_kind(node)
    for project in getattr(world, "storage_projects", []) or []:
        if (project.node_kind == kind and project.node_id == node.id
                and project.building == building):
            return (project.total_turns - project.turns_left, project.total_turns)
    if building == "shipyard" and kind == "settlement":
        for project in getattr(world, "shipyard_projects", []) or []:
            if project.settlement_id == node.id:
                return (project.total_turns - project.turns_left, project.total_turns)
    return None


def _shipyard_option(world, node, nation):
    current = 1 if getattr(node, "has_shipyard", False) else 0
    progress = _in_progress(world, node, "shipyard")
    blocked = None
    to_tier = None
    if progress is None and not current:
        if node.kind != "city":
            blocked = "Only a city can build a shipyard."
        elif not construction._is_coastal(world, node.pos):
            blocked = "This city is not on the coast."
        else:
            to_tier = 1
    cost = dict(construction.SHIPYARD_COST) if to_tier else {}
    priority, reason, score = ("idle", "", 0.0)
    if to_tier:
        priority, reason, score = _verdict(world, node, "shipyard")
    return BuildOption(
        "shipyard", "Shipyard", "Naval", current, 1, to_tier=to_tier, cost=cost,
        turns=construction.SHIPYARD_BUILD_TURNS if to_tier else 0,
        affordable=bool(to_tier) and construction.can_afford(nation, cost, world),
        blocked=blocked, in_progress=progress,
        effects=["Ships launch free and sail faster from here"],
        priority="blocked" if blocked else priority, reason=reason, score=score)


def build_options(world, node, nation):
    """Every building this node could have, as BuildOption cards, ordered
    most-worth-building first. Nothing here spends anything -- see the module
    docstring."""
    options = []
    for building in _all_buildings(node):
        if building == "shipyard":
            options.append(_shipyard_option(world, node, nation))
            continue
        # A Gold Mine needs a seam under it. Dropped from the list entirely
        # rather than shown blocked: "you cannot build this because there is no
        # gold here" is true of nearly every village on the map, and a card
        # saying so at all of them is noise, not information.
        if (building == resources.GOLD_MINE
                and not resources.storage_tier(node, building)
                and not resources.has_gold_seam(world, node)):
            continue
        current = resources.storage_tier(node, building)
        max_tier = resources.storage_max_tier(node, building)
        progress = _in_progress(world, node, building)
        to_tier = construction.storage_next_tier(world, node, building)
        cost = (construction.storage_build_cost(node, building, to_tier)
                if to_tier is not None else None) or {}
        blocked = None
        if progress is not None:
            pass          # already building; not blocked, just busy
        elif to_tier is None:
            blocked = ("Already at its highest tier here."
                       if current >= max_tier > 0
                       else f"A {_label(building)} can't be built here.")
        priority, reason, score = _verdict(world, node, building)
        if blocked:
            priority = "blocked"
        options.append(BuildOption(
            building, _label(building), BUILDING_CATEGORY.get(building, "Storage"),
            current, max_tier, to_tier=to_tier, cost=cost,
            turns=(construction.storage_build_turns(node, building, to_tier)
                   if to_tier is not None else 0),
            affordable=bool(cost) and construction.can_afford(nation, cost, world),
            blocked=blocked, in_progress=progress,
            effects=_storage_effect_lines(node, building, to_tier),
            priority=priority, reason=reason, score=score))
    options.sort(key=lambda o: o.sort_key)
    return options


def recommended(world, node, nation, limit=3):
    """The few this node most wants, for a one-line summary elsewhere in the
    UI. Only ever things it could actually start right now."""
    return [o for o in build_options(world, node, nation)
            if o.buildable and o.priority in ("urgent", "useful")][:limit]
