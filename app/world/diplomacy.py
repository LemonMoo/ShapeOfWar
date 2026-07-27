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
TRADE_STANDING_THRESHOLD = 10   # standing at/above this unlocks proposing a trade route

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

TRADE_ROUTE_ACCEPT_THRESHOLD = 0   # a much lower bar than an alliance — trade
                                   # is a far less binding ask
_TRADE_SPECIES_WEIGHT = 10
_TRADE_COMPLEMENTARITY_WEIGHT = 25


def species_affinity(species_a, species_b):
    if species_a == species_b:
        return 2
    return SPECIES_AFFINITY.get(frozenset([species_a, species_b]), 0)


# First contact (see establish_contact): reputation starts as a deterministic
# function of species affinity alone (extensible later), not a dice roll.
FIRST_CONTACT_SPECIES_WEIGHT = 15   # matches _SPECIES_WEIGHT's alliance-scoring weight


def first_contact_standing(species_a, species_b):
    return _clamp_standing(species_affinity(species_a, species_b) * FIRST_CONTACT_SPECIES_WEIGHT)


def establish_contact(world, a_id, b_id):
    """Create the relationship between two nations the first time they make
    contact (fog-of-war discovery for the player, a shared border for
    anyone) — idempotent, a no-op if one already exists, so it never
    overwrites standing built up by subsequent diplomacy. Stance is derived
    from the computed standing via the existing ALLY_THRESHOLD/WAR_THRESHOLD
    rather than hardcoded — species affinity tops out at 2 * 15 = 30, under
    both thresholds (50), so stance is always Neutral at first contact
    today; deriving it keeps this correct if affinity values or the weight
    ever change."""
    wm = world.world_map
    if a_id == b_id or frozenset((a_id, b_id)) in wm.relationships:
        return
    a, b = wm.nations[a_id], wm.nations[b_id]
    standing = first_contact_standing(a.meta.get("species"), b.meta.get("species"))
    stance = (Stance.ALLY if standing >= ALLY_THRESHOLD else
              Stance.ENEMY if standing <= WAR_THRESHOLD else Stance.NEUTRAL)
    tension = max(0, -standing)
    wm.set_relationship(a_id, b_id, stance=stance, tension=tension, standing=standing)


PROXIMITY_CONTACT_RANGE = 120  # cells -- two realms "discover" each other (via
                               # scouts, travelers, rumor) once their nearest
                               # settlements come this close, without needing
                               # their territories to literally touch. Contact
                               # only firing on an adjacent border tile left the
                               # whole diplomacy/foreign-trade layer near-dormant
                               # on a spacious map (factions sit dozens of cells
                               # apart with wildland between them and almost
                               # never share a border), so the Global trade tag
                               # had nothing to show. See run_proximity_contact.


def run_proximity_contact(world):
    """Establish first contact between any two not-yet-acquainted factions
    whose nearest settlements are within PROXIMITY_CONTACT_RANGE (wrap-aware,
    so the east-west seam counts). Cheap: contacted pairs are skipped on a
    dict lookup and never re-scanned, and the settlement scan early-exits on
    the first in-range pair, so cost falls as the map fills in."""
    from app.world import wrap
    wm = world.world_map
    by_fac = {}
    for s in world.settlements:
        by_fac.setdefault(s.faction_idx, []).append(s.pos)
    facs = sorted(by_fac)
    r2 = PROXIMITY_CONTACT_RANGE ** 2
    w = world.w
    for i in range(len(facs)):
        a = facs[i]
        aid = world.factions[a].id
        for j in range(i + 1, len(facs)):
            b = facs[j]
            bid = world.factions[b].id
            if frozenset((aid, bid)) in wm.relationships:
                continue
            if any(wrap.dist2_wrap(pa, pb, w) <= r2
                   for pa in by_fac[a] for pb in by_fac[b]):
                establish_contact(world, aid, bid)


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


def fabricate_claim(world, player, target, region):
    standing = _adjust_standing(world, player, target, FABRICATE_CLAIM_DELTA)
    return (f"{player.name} fabricates a claim on {region.name}, souring "
            f"relations with {target.name}. (Standing: {standing})")


def terrorize_locals(world, player, target, region):
    standing = _adjust_standing(world, player, target, TERRORIZE_LOCALS_DELTA)
    player.stats["morale"] = max(15, player.stats.get("morale", 50) - TERRORIZE_MORALE_COST)
    return (f"{player.name} terrorizes the people of {region.name}. "
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
        # ALLY_THRESHOLD == ALLIANCE_ACCEPT_THRESHOLD (both 50), so once
        # standing clears the gate above to even reach this weighing step,
        # it alone already meets the accept threshold -- species_score and
        # complementarity can only add from there, and complementarity
        # (see _resource_complementarity) is always >= 0. That leaves
        # species_score < 0 as the ONLY way this branch is ever actually
        # reached (species_score is always an integer in -2..2, so that's
        # either -2 or -1) -- there's no reachable "economics were too
        # weak" case to attribute here, unlike it might first appear.
        if species_score <= -2:
            reason = (f"the {target.meta.get('species')} have never trusted "
                      f"the {player.meta.get('species')}")
        else:
            reason = (f"relations between the {player.meta.get('species')} "
                      f"and the {target.meta.get('species')} have never "
                      f"been especially warm")
        return f"{target.name} declines the alliance — {reason}."

    wm.set_relationship(player.id, target.id, stance=Stance.ALLY, tension=0,
                        standing=standing, acted_turn=rel.get("acted_turn"))
    return f"{target.name} accepts! {player.name} and {target.name} are now allied."


def evaluate_trade_route(world, proposer, target):
    """Whether `target` agrees to a trade route `proposer` wants to open —
    the same "does this actually make sense for them" weighing as
    form_alliance (standing, species affinity, real economic
    complementarity), just a much lower bar since a trade route is far
    less binding than an alliance. Called by trade.start_trade_route for
    both a land route (before construction begins) and a sea route
    (before it opens) — trade routes are proposed and either accepted or
    declined the same way regardless of kind. Returns (accepted, reason):
    reason is None when accepted, else a short phrase for the decline
    message."""
    rel = world.world_map.get_relationship(proposer.id, target.id)
    standing = rel.get("standing", 0)
    species_score = species_affinity(proposer.meta.get("species"), target.meta.get("species"))
    complementarity = _resource_complementarity(world, proposer, target)
    score = (standing + species_score * _TRADE_SPECIES_WEIGHT
            + complementarity * _TRADE_COMPLEMENTARITY_WEIGHT)
    if score >= TRADE_ROUTE_ACCEPT_THRESHOLD:
        return True, None
    # Unlike form_alliance, species distrust is the ONLY thing that can
    # ever actually cause a trade-route decline here, not just the
    # dominant one: eligible_to_trade already guarantees standing >= 10
    # by the time this runs, complementarity is always >= 0 (can only
    # help, never hurt), and this function's own weight/threshold
    # (_TRADE_SPECIES_WEIGHT=10, TRADE_ROUTE_ACCEPT_THRESHOLD=0) make
    # species_score == -1 break exactly even in the worst case (10 - 10 +
    # 0 = 0, which still clears the >= 0 bar) -- only species_score <= -2
    # can ever push the total under it. So there's no "genuinely low
    # complementarity" case to attribute here the way there is for
    # form_alliance (a much higher bar, see that function) -- if this
    # ever declines, it's species.
    return False, (f"the {target.meta.get('species')} have never trusted "
                   f"{proposer.meta.get('species')} traders")
