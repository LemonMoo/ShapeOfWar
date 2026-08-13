"""Realm progression: a development score and named ages that make a
faction's growth legible.

The design problem this answers (see PROGRESSION_PLAN.md): expansion was
gated by a single flat number -- CLAIM_DEVELOPMENT_FRACTION in expansion.py --
a binary lock that said "no" at 49% village fill and "yes" at 50%, with a
message that named a number instead of a reason. There was also no era
structure, so "late game" was not a destination with milestones, just the
moment a realm happened to have built a city and a weaponsmith.

This module is slice 1: the observation-only foundation. It computes, from
signals the sim already tracks, (a) a continuous development score and (b) a
ladder of named ages, each gated on concrete, legible milestones drawn from
the settlement-first ladder the game already has. It writes nothing and draws
no randomness -- every function is a pure function of world state, so a given
save always scores the same way.

Slice 2 (below) turns the score into governance: how many regions a realm can
hold *well*, and how stretched it is past that -- the soft, self-correcting
limit that replaces the flat gate in expansion.py.
"""

# --- the age ladder ---------------------------------------------------------
# Ordered. A faction's age is the HIGHEST index whose milestones are all met,
# so every later age also requires every earlier one. `next` is the
# human-readable hint the UI prints to say what builds the next rung.
AGES = (
    {"name": "Homestead",
     "milestones": (),
     "next": "Raise a village to a Town"},
    {"name": "Age of Villages",
     "milestones": ("town",),
     "next": "Raise a Town to a City"},
    {"name": "Age of Towns",
     "milestones": ("town", "second_city"),
     "next": "Raise a Castle and arm your levy"},
    {"name": "Age of Cities",
     "milestones": ("town", "second_city", "castle", "armed"),
     "next": "Hold 4 regions and stock craft goods"},
    {"name": "Age of Kingdoms",
     "milestones": ("town", "second_city", "castle", "armed",
                    "four_regions", "craft_goods"),
     "next": "Rule 8 regions and keep a trade route"},
    {"name": "Age of Empire",
     "milestones": ("town", "second_city", "castle", "armed",
                    "four_regions", "craft_goods", "eight_regions", "trade"),
     "next": None},
)

# Milestone thresholds -- first-pass, tuned by feel in play (the project's
# "numbers to judge in play, not in a simulator" rule, HANDOFF.md:1731).
ARMED_SHARE_MILESTONE = 0.5    # Weapons cover at least half the levy
# "Craft goods" means manufactured (tier-4) or luxury (tier-5) goods, NOT
# tier-3 Food Products (Bread/Cheese) which a realm mills almost from the
# start. It is a STOCK proxy -- trade and frontier gifts can put a tier-4
# good in a node that never smithed it; a production-based check is slice 2.
CRAFT_GOODS_TIER = 4
KINGDOM_REGIONS = 4
EMPIRE_REGIONS = 8

# Weights for the continuous development score. First-pass and deliberately
# not normalised to a "real" unit -- the scalar's actual job is governance
# capacity (slice 2), which will do its own normalisation. Here it only needs
# to be monotonic in development, which it is.
DEVELOPMENT_WEIGHTS = {
    "population": 1.0 / 100.0,   # ~12,000 people in a full city -> ~120
    "settlements": 40.0,         # town 1 / castle 2 / city 3 points each
    "storage": 20.0,             # per granary/warehouse/vault tier
    "military": 1.0,             # per military point (floor 10 .. ceiling 1200)
    "regions": 60.0,             # per region ruled
}


def _faction_nodes(world, faction_idx):
    """Every settlement and village the faction owns."""
    return ([s for s in world.settlements if s.faction_idx == faction_idx]
            + [v for v in world.villages if v.faction_idx == faction_idx])


def _kind_counts(world, faction_idx):
    """{kind: count} over the faction's settlements (city/castle/town)."""
    counts = {}
    for st in world.settlements:
        if st.faction_idx == faction_idx:
            counts[st.kind] = counts.get(st.kind, 0) + 1
    return counts


def _owned_region_count(world, faction_idx):
    return sum(1 for r in world.regions if r.faction_idx == faction_idx)


def _armed_share(world, faction_idx):
    """Fraction of the levy covered by Weapons -- 1.0 when fully armed.

    Mirrors resources._recompute_military's own levy math (adults *
    MOBILIZATION_RATE) so the milestone and the military rating agree about
    what "armed" means."""
    from app.world.resources import MOBILIZATION_RATE
    nodes = _faction_nodes(world, faction_idx)
    adults = sum(getattr(n, "adults", 0) for n in nodes)
    weapons = sum((getattr(n, "resources", {}) or {}).get("Weapons", 0)
                  for n in nodes)
    levy = adults * MOBILIZATION_RATE
    if levy <= 0:
        return 0.0
    return min(1.0, weapons / levy)


def _highest_good_tier(world, faction_idx):
    """Highest resource tier present in any owned node's stockpile (0..5 --
    the registry tops out at tier-5 Luxury Goods).

    A proxy for "how far up the crafting chain this realm has climbed" --
    tier-3 (Bread/Cheese), tier-4 (Planks/Weapons/Glass) and tier-5 (Wine/
    Furniture) goods only accumulate once the camps and workshops to make
    them exist (or, for stock, once trade brings them in -- see the
    CRAFT_GOODS_TIER note)."""
    from app.world.resources import RESOURCES
    best = 0
    for n in _faction_nodes(world, faction_idx):
        for name, amount in (getattr(n, "resources", {}) or {}).items():
            if amount and RESOURCES.get(name, {}).get("tier", 0) > best:
                best = RESOURCES[name]["tier"]
    return best


def _has_trade_route(world, faction_idx):
    return any(faction_idx in (r.get("a_faction"), r.get("b_faction"))
               for r in getattr(world, "trade_routes", ()))


def _milestone_met(world, faction_idx, name):
    if name == "town":
        return _kind_counts(world, faction_idx).get("town", 0) >= 1
    if name == "second_city":
        return _kind_counts(world, faction_idx).get("city", 0) >= 2
    if name == "castle":
        return _kind_counts(world, faction_idx).get("castle", 0) >= 1
    if name == "armed":
        return _armed_share(world, faction_idx) >= ARMED_SHARE_MILESTONE
    if name == "four_regions":
        return _owned_region_count(world, faction_idx) >= KINGDOM_REGIONS
    if name == "eight_regions":
        return _owned_region_count(world, faction_idx) >= EMPIRE_REGIONS
    if name == "craft_goods":
        return _highest_good_tier(world, faction_idx) >= CRAFT_GOODS_TIER
    if name == "trade":
        return _has_trade_route(world, faction_idx)
    raise KeyError(f"unknown milestone {name!r}")


def faction_age(world, faction_idx):
    """(index, age_dict) for the highest age this faction satisfies.

    Ages are cumulative -- the ladder is ordered, so the search walks from
    the top down and returns the first age whose every milestone is met."""
    for i in range(len(AGES) - 1, -1, -1):
        age = AGES[i]
        if all(_milestone_met(world, faction_idx, m) for m in age["milestones"]):
            return i, age
    return 0, AGES[0]      # unreachable: Homestead has no milestones


def age_label(world, faction_idx):
    """The one-line UI readout: 'Age of Towns — raise a Castle and arm your
    levy', or 'Age of Empire — the realm is at its height'."""
    _, age = faction_age(world, faction_idx)
    if age["next"]:
        return f"{age['name']} — {age['next']}"
    return f"{age['name']} — the realm is at its height"


def development_components(world, faction_idx):
    """The raw, named signals the development score is built from.

    Exposed (rather than only the weighted scalar) so the UI and tests can
    show WHY the score is what it is -- the project's "measure once"
    philosophy: the score is these numbers, weighted."""
    nodes = _faction_nodes(world, faction_idx)
    kinds = _kind_counts(world, faction_idx)
    from app.world.resources import storage_tier
    storage = sum(storage_tier(n, b)
                  for n in nodes for b in ("granary", "warehouse", "vault"))
    nation = world.factions[faction_idx]
    return {
        "population": sum(getattr(n, "population", 0) for n in nodes),
        "adults": sum(getattr(n, "adults", 0) for n in nodes),
        "settlements": (kinds.get("town", 0) * 1
                        + kinds.get("castle", 0) * 2
                        + kinds.get("city", 0) * 3),
        "storage": storage,
        "military": nation.stats.get("military", 0),
        "regions": _owned_region_count(world, faction_idx),
    }


def development_score(world, faction_idx):
    """A scalar development score: the weighted sum of the named components.

    Monotonic in development by construction; first-pass weights in
    DEVELOPMENT_WEIGHTS. The scalar's real consumer is governance capacity
    (slice 2), which does its own normalisation -- here it exists so callers
    have one number instead of six."""
    c = development_components(world, faction_idx)
    return sum(c[key] * DEVELOPMENT_WEIGHTS[key] for key in DEVELOPMENT_WEIGHTS)


# --- governance ---------------------------------------------------------------
# How many regions a realm can hold WELL. Each settlement is a governing
# institution: a City governs provinces, a Castle holds a frontier, a Town
# administers its district. Raising a Town to a City is exactly how a realm
# learns to hold more land -- the legible "why is expansion slow now" answer,
# where the old flat CLAIM_DEVELOPMENT_FRACTION gate was a wall.
GOVERNANCE_BASE_REGIONS = 1
GOVERNANCE_PER_KIND = {"city": 3, "castle": 2, "town": 1}


def governance_capacity(world, faction_idx):
    """Regions this faction can govern well -- the sum of its settlements'
    governance, plus a base foothold. A fresh realm (capital City, no Towns)
    governs 4 regions; every Town raised, Castle built, or City founded after
    that adds more."""
    kinds = _kind_counts(world, faction_idx)
    return GOVERNANCE_BASE_REGIONS + sum(
        GOVERNANCE_PER_KIND.get(k, 0) * count for k, count in kinds.items())


def claim_overstretch(world, faction_idx):
    """Regions already held beyond what the realm can govern well (>= 0).

    This is the soft expansion brake: past capacity claims stay legal but
    cost more settlers and run slower (see expansion.py's
    GOVERNANCE_OVERSTRETCH_*_STEP)."""
    return max(0, _owned_region_count(world, faction_idx)
               - governance_capacity(world, faction_idx))


# Faction-wide village fill above which the realm reads as "crowded" -- the
# positive reason to expand (see expansion_pressure).
EXPANSION_PRESSURE_FILL = 0.85


def expansion_pressure(world, faction_idx):
    """The reason to expand, or None when the realm has room at home.

    Pressure is crowding: the realm's own regions are nearly full of
    villages. Its absence is itself the answer to "should I expand?" -- a
    realm with room and full larders has no call to reach for new land."""
    from app.world.resources import region_village_capacity
    cap_sum = vills_sum = 0
    for r in world.regions:
        if r.faction_idx != faction_idx:
            continue
        cap_sum += region_village_capacity(world, r)
        vills_sum += len(getattr(r, "villages", []))
    if cap_sum <= 0:
        return None
    if vills_sum / cap_sum >= EXPANSION_PRESSURE_FILL:
        return ("Your people are crowded — your lands are nearly full of "
                "villages. Expand, or raise settlements to Cities for more room.")
    return None

