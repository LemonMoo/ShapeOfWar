"""Frontier events: the small decisions and discoveries that visit a
freshly-claimed region during its first weeks under your banner.

A region stays "frontier" for FRONTIER_WINDOW_TURNS after it is claimed
(expansion.settle_newly_claimed_region stamps frontier_turns_left). Each
turn of that window there is a per-region chance an event surfaces --
bandits demanding tribute, scouts finding good soil, ruins holding
salvage, a hermit's blessing, wanderers asking to settle. Events with a
real choice are STAGED for the human player (app.world pending
_frontier_events, resolved by the UI dialog in app/ui/frontier_dialog.py
via resolve_event); AI realms resolve their own instantly. Gifts apply
immediately for either.

All amounts are deliberately modest -- the point is texture and small
decisions, not swings. The rolls use the global random, which
generate_world now seeds, so a given seed's frontier history is part of
the reproducible world.
"""
import random

from app.world.resources import faction_gold

FRONTIER_WINDOW_TURNS = 12    # how long a claim stays "frontier"
EVENT_CHANCE_PER_TURN = 0.18  # per frontier region, per turn
MAX_PENDING_EVENTS = 3        # never pile more than this on the player


def _grant(world, nation, resource, amount):
    """Put `amount` of a resource into the faction's first settlement's
    stockpile (its capital, the natural hub) -- falls back to a village if
    it has none."""
    nodes = [st for st in world.settlements if st.faction_idx ==
             world.factions.index(nation)]
    if not nodes:
        nodes = [v for v in world.villages if v.faction_idx ==
                 world.factions.index(nation)]
    if nodes:
        nodes[0].resources[resource] = nodes[0].resources.get(resource, 0) + amount


def _region_nodes(world, region):
    """The region's settlements and villages (any faction)."""
    nodes = []
    for sid in getattr(region, "meta_settlements", []):
        nodes.append(world.settlements[sid])
    for vid in getattr(region, "villages", []):
        nodes.append(world.villages[vid])
    return nodes


def _bandit_tribute(nation, world):
    return max(60, round(0.15 * faction_gold(world, world.factions.index(nation))))


def _roll_event(region):
    """Pick a frontier event for a region, or None. Returns a plain dict so
    the whole thing pickles cleanly with the world."""
    from app.world import construction
    nation_idx = region.faction_idx
    nation = None
    roll = random.random()
    if roll < 0.30:
        return {"id": "bandits", "region_id": region.id,
                "title": "Bandits",
                "text": ("Bandits have been harrying the new land, demanding "
                         "tribute from your settlers."),
                "choices": [{"id": "pay", "label": "Pay the tribute"},
                            {"id": "refuse", "label": "Refuse — drive them off"}]}
    if roll < 0.50:
        return {"id": "good_soil", "region_id": region.id,
                "title": "Rich Soil",
                "text": ("Scouts report rich, black soil in the wilds of the "
                         "new land."),
                "choices": [{"id": "accept", "label": "Sow it"}]}
    if roll < 0.70:
        return {"id": "ruins", "region_id": region.id,
                "title": "Old Ruins",
                "text": ("Your people find tumbled ruins in the brush — old "
                         "walls and stonework that can be carried off."),
                "choices": [{"id": "salvage", "label": "Salvage them"}]}
    if roll < 0.85:
        return {"id": "hermit", "region_id": region.id,
                "title": "The Hermit",
                "text": ("A hermit has made her home in the wilds and offers "
                         "her blessing to the new settlements."),
                "choices": [{"id": "bless", "label": "Accept her blessing"}]}
    return {"id": "wanderers", "region_id": region.id,
            "title": "Wanderers",
            "text": ("A band of wanderers, ragged and hungry, asks leave to "
                     "settle in the new land."),
            "choices": [{"id": "take_in", "label": "Take them in"},
                        {"id": "send_on", "label": "Send them on with provisions"}]}


def advance_frontier_events(world):
    """One turn of frontier life, called from resources.day_steps. The
    player's events are staged on world.pending_frontier_events for the UI
    (app.py's _check_frontier_events) to turn into a dialog; everyone
    else's are resolved instantly with the AI's default choice."""
    if not hasattr(world, "pending_frontier_events"):
        world.pending_frontier_events = []
    player_idx = getattr(world, "player_faction_idx", -1)
    for region in world.regions:
        left = getattr(region, "frontier_turns_left", 0)
        if left <= 0 or region.faction_idx < 0:
            continue
        region.frontier_turns_left = left - 1
        if len(world.pending_frontier_events) >= MAX_PENDING_EVENTS:
            continue
        if random.random() > EVENT_CHANCE_PER_TURN:
            continue
        event = _roll_event(region)
        if event is None:
            continue
        if region.faction_idx == player_idx:
            world.pending_frontier_events.append(event)
        else:
            _resolve_ai(world, event)


def _pay_gold(world, nation, amount):
    """Consume Gold from the faction's settlements and villages, largest
    stockpile first -- the same aggregate-economy reading faction_gold uses
    (Gold is NOT in construction._SETTLEMENT_STORAGE_RESOURCES, so _pay_cost
    would wrongly touch nation.stats["resources"])."""
    fac_idx = world.factions.index(nation)
    nodes = [st for st in world.settlements if st.faction_idx == fac_idx] + \
            [v for v in world.villages if v.faction_idx == fac_idx]
    nodes.sort(key=lambda n: (getattr(n, "resources", {}) or {}).get("Gold", 0),
               reverse=True)
    remaining = amount
    for node in nodes:
        if remaining <= 0:
            break
        if not hasattr(node, "resources"):
            node.resources = {}
        have = node.resources.get("Gold", 0)
        take = min(have, remaining)
        if take:
            node.resources["Gold"] = have - take
            remaining -= take
    return amount - remaining


def _resolve_ai(world, event):
    """An AI realm's instant handling: pay tribute when it can afford to,
    take in wanderers when its realm is thin, accept every gift."""
    region = world.regions[event["region_id"]]
    nation = world.factions[region.faction_idx]
    if event["id"] == "bandits":
        choice = ("pay" if faction_gold(world, world.factions.index(nation))
                  >= _bandit_tribute(nation, world) else "refuse")
        resolve_event(world, event, choice)
    elif event["id"] == "wanderers":
        resolve_event(world, event, random.choice(("take_in", "send_on")))
    else:
        resolve_event(world, event, event["choices"][0]["id"])


def resolve_event(world, event, choice_id):
    """Apply a player's choice (or an AI's) and return the message the UI
    shows. Idempotent per event: the UI only calls this once, after which
    the event is gone from the pending list."""
    from app.world import construction
    region = world.regions[event["region_id"]]
    nation = world.factions[region.faction_idx]
    eid = event["id"]

    if eid == "bandits":
        if choice_id == "pay":
            tribute = _bandit_tribute(nation, world)
            _pay_gold(world, nation, tribute)
            return (f"The bandits take {tribute:,} Gold and melt back into "
                    "the wilds.")
        for node in _region_nodes(world, region):
            lost = round(getattr(node, "adults", 0) * 0.08)
            node.adults = max(0, node.adults - lost)
            node.prosperity = max(0.0, getattr(node, "prosperity", 0.0) - 8.0)
        return ("The bandits burn a homestead before they leave — the new "
                "villages lose people and heart.")

    if eid == "good_soil":
        food = max(120, round(0.2 * sum(getattr(n, "adults", 0)
                                        for n in _region_nodes(world, region))))
        _grant(world, nation, "Food", food)
        return f"The soil is sown — the realm gains {food:,} Food."

    if eid == "ruins":
        _grant(world, nation, "Logs", 120)
        _grant(world, nation, "Stone", 80)
        _grant(world, nation, "Gold", 60)
        return ("The ruins yield timber, stone and a little gold — 120 Logs, "
                "80 Stone, 60 Gold.")

    if eid == "hermit":
        for node in _region_nodes(world, region):
            node.prosperity = min(100.0, getattr(node, "prosperity", 0.0) + 10.0)
        return "The hermit's blessing lifts the spirits of the new land."

    if eid == "wanderers":
        if choice_id == "take_in":
            nodes = [v for v in _region_nodes(world, region)
                     if hasattr(v, "farm_output")] or _region_nodes(world, region)
            # A bare claim may have no villages yet -- then the wanderers
            # make for the realm's capital instead.
            if not nodes:
                nodes = [st for st in world.settlements
                         if st.faction_idx == region.faction_idx]
            if not nodes:
                # The claiming faction has no settlements anywhere either
                # (e.g. an AI realm wiped out before its first town rose):
                # there is no host for anyone to settle with, so the event
                # quietly passes rather than crashing on an empty max().
                return "Wanderers pass through the empty frontier and move on."
            host = max(nodes, key=lambda n: getattr(n, "max_population", 0) or 0)
            gain = max(20, round((getattr(host, "max_population", 200) or 200) * 0.04))
            host.population = min(getattr(host, "max_population", host.population)
                                  or host.population, host.population + gain)
            host.adults = getattr(host, "adults", 0) + round(gain * 0.4)
            return f"{gain:,} wanderers settle in {host.name}."
        food = max(120, round(0.2 * sum(getattr(n, "adults", 0)
                                        for n in _region_nodes(world, region))))
        _grant(world, nation, "Food", food)
        return f"You give the wanderers provisions and they move on ({food:,} Food)."

    return "The frontier settles quietly."
