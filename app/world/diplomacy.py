"""Diplomacy actions: nudging a relationship's numeric "standing" (-100..100)
up or down, and the explicit regime changes — declaring war or forming an
alliance — that crossing a threshold only *unlocks*, never triggers on its
own. Mirrors app/world/territory.py's role for conquest: a separate module
for actions that mutate world state, keeping world_map.py itself just the
data/graph structure.
"""
from app.world.world_map import Stance
from app.world.resources import RESOURCES

STANDING_MIN, STANDING_MAX = -100, 100
ALLY_THRESHOLD = 50     # standing at/above this unlocks Form Alliance
WAR_THRESHOLD = -50     # standing at/below this unlocks Declare War

IMPROVE_RELATIONS_DELTA = 12
FABRICATE_CLAIM_DELTA = -15
TERRORIZE_LOCALS_DELTA = -25
TERRORIZE_MORALE_COST = 3   # terrorizing civilians costs the actor's own morale

# How readily two species get along, culturally — a hard-to-overcome veto for
# bitter-rival pairs, a boost for natural-ally ones. Unlisted pairs (and any
# species with itself) default to +2/neutral via the lookup fallback below.
SPECIES_AFFINITY = {
    frozenset(["Humans", "Dwarves"]): 2,    # classic allies
    frozenset(["Humans", "Elves"]): 1,
    frozenset(["Humans", "Goblins"]): -1,   # raided villages, distrust
    frozenset(["Humans", "Orcs"]): -2,      # traditional conflict
    frozenset(["Elves", "Dwarves"]): -1,    # rivalry, not hatred
    frozenset(["Elves", "Orcs"]): -2,
    frozenset(["Elves", "Goblins"]): -1,
    frozenset(["Dwarves", "Orcs"]): -2,
    frozenset(["Dwarves", "Goblins"]): -1,
    frozenset(["Orcs", "Goblins"]): 2,      # allied "raider" cultures
}

ALLIANCE_ACCEPT_THRESHOLD = 50   # matches ALLY_THRESHOLD: a neutral-species,
                                 # zero-complementarity pair is right at the door
_SPECIES_WEIGHT = 15
_COMPLEMENTARITY_WEIGHT = 15


def species_affinity(species_a, species_b):
    if species_a == species_b:
        return 2
    return SPECIES_AFFINITY.get(frozenset([species_a, species_b]), 0)


def _resource_complementarity(world, a, b):
    """0..~2: how much each side has spare that the other is short on —
    reuses trade.py's own surplus/need math (no separate scarcity model to
    keep in sync)."""
    from app.world import trade
    score = 0.0
    for resource in RESOURCES:
        if (trade.sellable_surplus(a, resource, world) >= trade.MIN_TRADE_QUANTITY
                and trade.buyer_need(b, resource, world) > 0.3):
            score += trade.buyer_need(b, resource, world)
        if (trade.sellable_surplus(b, resource, world) >= trade.MIN_TRADE_QUANTITY
                and trade.buyer_need(a, resource, world) > 0.3):
            score += trade.buyer_need(a, resource, world)
    return score / len(RESOURCES)


def _clamp_standing(v):
    return max(STANDING_MIN, min(STANDING_MAX, v))


def can_act_this_turn(world, player, target):
    """One diplomatic nudge (Improve Relations / Fabricate Claim / Terrorize
    Locals) per turn per relationship — shared across all three, so you can't
    stack two hostile moves (or rush straight to a threshold) in one turn."""
    rel = world.world_map.get_relationship(player.id, target.id)
    return rel.get("acted_turn") != world.turn


def _adjust_standing(world, player, target, delta):
    wm = world.world_map
    rel = wm.get_relationship(player.id, target.id)
    new_standing = _clamp_standing(rel.get("standing", 0) + delta)
    wm.set_relationship(player.id, target.id, stance=rel["stance"],
                        tension=rel.get("tension", 0), standing=new_standing,
                        acted_turn=world.turn)
    return new_standing


def improve_relations(world, player, target):
    standing = _adjust_standing(world, player, target, IMPROVE_RELATIONS_DELTA)
    return (f"{player.name} extends an offer of friendship to {target.name}. "
            f"(Standing: {standing})")


def fabricate_claim(world, player, target, county):
    standing = _adjust_standing(world, player, target, FABRICATE_CLAIM_DELTA)
    return (f"{player.name} fabricates a claim on {county.name}, souring "
            f"relations with {target.name}. (Standing: {standing})")


def terrorize_locals(world, player, target, county):
    standing = _adjust_standing(world, player, target, TERRORIZE_LOCALS_DELTA)
    player.stats["morale"] = max(15, player.stats.get("morale", 50) - TERRORIZE_MORALE_COST)
    return (f"{player.name} terrorizes the people of {county.name}. "
            f"{target.name} is outraged. (Standing: {standing}, your morale "
            f"-{TERRORIZE_MORALE_COST})")


def declare_war(world, player, target):
    wm = world.world_map
    rel = wm.get_relationship(player.id, target.id)
    if rel.get("standing", 0) > WAR_THRESHOLD:
        return f"Relations with {target.name} aren't hostile enough to justify war yet."
    wm.set_relationship(player.id, target.id, stance=Stance.ENEMY,
                        tension=max(rel.get("tension", 0), 60),
                        standing=rel.get("standing", 0),
                        acted_turn=rel.get("acted_turn"))
    return f"{player.name} declares war on {target.name}!"


def form_alliance(world, player, target):
    """Proposing an alliance doesn't guarantee one — the target actually
    weighs it: how well the two species get along culturally, and whether
    there's real mutual benefit (each side having surplus the other lacks),
    on top of how warm relations already are."""
    wm = world.world_map
    rel = wm.get_relationship(player.id, target.id)
    standing = rel.get("standing", 0)
    if standing < ALLY_THRESHOLD:
        return f"Relations with {target.name} aren't warm enough for an alliance yet."

    species_score = species_affinity(player.meta.get("species"), target.meta.get("species"))
    complementarity = _resource_complementarity(world, player, target)
    score = standing + species_score * _SPECIES_WEIGHT + complementarity * _COMPLEMENTARITY_WEIGHT

    if score < ALLIANCE_ACCEPT_THRESHOLD:
        if species_score <= -2:
            reason = (f"the {target.meta.get('species')} have never trusted "
                      f"the {player.meta.get('species')}")
        else:
            reason = "they see little to gain from closer ties"
        return f"{target.name} declines the alliance — {reason}."

    wm.set_relationship(player.id, target.id, stance=Stance.ALLY, tension=0,
                        standing=standing, acted_turn=rel.get("acted_turn"))
    return f"{target.name} accepts! {player.name} and {target.name} are now allied."
