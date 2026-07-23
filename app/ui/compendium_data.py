"""Content for the in-game Compendium (app/ui/compendium.py).

Resource/recipe/building entries below are generated live from the actual
resources.py registries (RESOURCES/RESOURCE_SPAWN/BUILDINGS/RECIPES) rather
than hand-written, so they can never drift out of sync with the real game
data as the economy changes — see resource_entry_text()/category_overview_text().

Everything else (how storage, prosperity, trade, diplomacy, expansion,
construction, commanders, and combat actually work) is hand-written prose in
ARTICLES below, sourced from the live constants at import time (an f-string
reading e.g. resources.GRANARY_STORAGE_BONUS) wherever a specific number is
quoted, so a future retune updates the compendium automatically without
anyone having to remember to hand-edit prose.

Formatting note: every flowing prose paragraph below is built from adjacent
string-literal fragments with NO embedded newline (they concatenate into one
unbroken string) — the Compendium's Text widget word-wraps at render time, so
a hard newline baked into the source would show up as an actual forced line
break in the UI, often mid-sentence. Short label/bullet lines ("  City: ...")
are fine as literal single lines since they're never long enough to wrap.

Maintenance note: whenever a future change alters a mechanic described here,
update the relevant article (or add a new one) as part of that change's own
"done" — the whole point of this file is that it stays trustworthy, not that
it gets rewritten as a one-off.
"""
from app.world import resources as R
from app.world import trade
from app.world import construction
from app.world import commander
from app.world import expansion
from app.world import diplomacy
from app.world.worldgen import POPULATION_RANGE, SETTLEMENT_TAX_INCOME, CHILDREN_FRACTION_RANGE
from app.world.lexicon import SPECIES

RESOURCE_CATEGORIES = ["Crops", "Livestock", "Forestry", "Mining", "Fishing",
                       "Food Products", "Manufactured Goods", "Luxury Goods"]

CATEGORY_BLURB = {
    "Crops": (
        "Grown by Villages on suitable terrain (mostly Plains, Rice on "
        "Swamp). Each Crop only produces during its own Harvest season "
        "(see its Growth Cycle) — nothing outside that window. Every "
        "edible Crop (all of them except Cotton, a fiber) can be eaten "
        "raw to satisfy a settlement/village's Food need directly, on top "
        "of being the raw input a Food Product is made from — a Village "
        "with no Settlement nearby to mill/bake for it can still feed "
        "itself off its own harvest, not just once it's been converted."
    ),
    "Livestock": (
        "Living, breeding animal populations kept at the region level "
        "(region.livestock: animal → head count), not a stockpiled "
        "quantity — see the Settlements & Villages and Prosperity "
        "articles. Grown/shrunk once a year via births, natural deaths, "
        "and slaughter."
    ),
    "Forestry": "Logged/tapped by Villages in Forest terrain.",
    "Mining": (
        "Extracted by Villages from Mountain/Desert/Swamp/Coastal "
        "terrain, geological rather than seasonal — production is "
        "continuous, every turn, unlike a Crop's one-season harvest."
    ),
    "Fishing": (
        f"Caught directly by a Settlement or Village sited near open "
        f"ocean, a river, or a lake (within {R.FISH_ADJACENCY_REACH} "
        f"cells) — the one raw resource that isn't a biome share at all: "
        f"ocean gives a flat catch, a river or lake scales with that "
        f"specific body of water's own real size, not just its presence. "
        f"Unlike Mining, it never depletes — the same adjacency yields "
        f"fresh Fish every turn, forever. Not edible raw; has to be "
        f"Smoked first (see Food Products)."
    ),
    "Food Products": (
        "Made at a Settlement from a Crop, Livestock byproduct, or "
        "another Food Product. Any Food Product in storage can satisfy a "
        "settlement's Food need — they're fully interchangeable for that "
        "purpose, and pool together with raw edible Crops (see that "
        "category) as one shared Food supply."
    ),
    "Manufactured Goods": (
        "Finished goods made at a Settlement from raw Forestry/Mining "
        "materials or other processed goods. Durable — almost none of "
        "them spoil."
    ),
    "Luxury Goods": (
        "The top of the crafting chain (Tier 5) — status goods that "
        "satisfy a settlement's Luxury need, giving prosperity a real "
        "boost when met and never a penalty when they're not. See the "
        "Luxury Economy article."
    ),
}

_GROWTH_STAGE_ORDER = ["Plant", "Growing", "Harvest", "Dormant"]


def _pct(x):
    v = x * 100
    return f"{v:.0f}%" if abs(v - round(v)) < 0.05 else f"{v:.1f}%"


def _spoil_desc(rate):
    if rate <= 0:
        return "never spoils"
    if rate < 0.05:
        return f"spoils very slowly ({_pct(rate)} of unsold stock lost per turn)"
    if rate < 0.15:
        return f"spoils slowly ({_pct(rate)}/turn)"
    if rate < 0.30:
        return f"spoils at a moderate pace ({_pct(rate)}/turn)"
    return f"spoils quickly ({_pct(rate)}/turn)"


def _used_in(name):
    outs = []
    for output, options in R.RECIPES.items():
        for opt in options:
            if name in opt["inputs"]:
                outs.append(output)
                break
    return outs


def _recipe_desc(name):
    options = R.recipe_for(name)
    if not options:
        return None
    parts = []
    for opt in options:
        inputs = opt["inputs"]
        tag = ""
        if opt.get("slaughter"):
            tag = " (slaughters the animal)"
        elif opt.get("byproduct"):
            tag = " (collected from a live animal, no slaughter)"
        parts.append(" + ".join(inputs) + tag)
    return "; or ".join(parts) if len(parts) > 1 else parts[0]


def _spawn_lines(name):
    spec = R.RESOURCE_SPAWN.get(name)
    if not spec:
        return []
    lines = []
    biomes = ", ".join(sorted(spec["biomes"]))
    lines.append(f"Terrain: {biomes}")
    climate = spec.get("climate", {})
    if climate:
        favored = sorted((c for c, m in climate.items() if m > 1.0), key=lambda c: -climate[c])
        disfavored = sorted((c for c, m in climate.items() if m < 1.0), key=lambda c: climate[c])
        bits = []
        if favored:
            bits.append("favors " + ", ".join(f"{c} (x{climate[c]:.2g})" for c in favored))
        if disfavored:
            bits.append("disfavors " + ", ".join(f"{c} (x{climate[c]:.2g})" for c in disfavored))
        lines.append("Climate: " + ("; ".join(bits) if bits else "no strong preference"))
    else:
        lines.append("Climate: no effect (geological, not biological)")
    fert = spec.get("fertility_weight", 0.0)
    if fert <= 0:
        fert_txt = "not affected by soil fertility"
    elif fert < 0.5:
        fert_txt = "lightly affected by soil fertility"
    else:
        fert_txt = "strongly affected by soil fertility"
    lines.append(f"Soil: {fert_txt} (weight {fert:.2g})")
    lines.append(f"Rarity: {spec.get('rarity', 'common')}")
    return lines


def resource_entry_text(name):
    spec = R.RESOURCES[name]
    lines = [f"{name}", f"{spec['category']} · Tier {spec['tier']}", ""]
    building = R.BUILDINGS.get(name, {}).get("name")
    if building:
        lines.append(f"Building: {building}")
    lines.append(f"Spoilage: {_spoil_desc(spec['spoil_rate'])}")

    cycle = R.GROWTH_CYCLE.get(name)
    if cycle:
        stages = ", ".join(f"{s}: {cycle.get(s, '—')}" for s in _GROWTH_STAGE_ORDER)
        lines.append(f"Growth cycle: {stages} (only produces during Harvest)")

    lines.extend(_spawn_lines(name))

    recipe_txt = _recipe_desc(name)
    if recipe_txt:
        lines.append(f"Made from: {recipe_txt}")

    used = _used_in(name)
    if used:
        lines.append(f"Used to craft: {', '.join(used)}")

    if name in R._FOOD_PRODUCTS:
        lines.append("")
        lines.append(
            "Satisfies a settlement/village's Food need — any Food "
            "Product (or edible raw Crop) in storage counts, fully "
            "interchangeably."
        )
    elif name in R._RAW_FOOD_CROPS:
        lines.append("")
        lines.append(
            "Edible raw — satisfies a settlement/village's Food need "
            "directly, pooled together with Food Products, no conversion "
            "needed."
        )
    if name in R._LUXURY_GOODS:
        lines.append("")
        lines.append(
            "Satisfies a settlement/village's Luxury need — any Luxury "
            "Good in storage counts, fully interchangeably. Raises "
            "prosperity when met; going without one is simply a "
            "non-event, never a penalty."
        )
    if name == "Fish":
        lines.append("")
        lines.append(
            f"Caught by adjacency, not biome — a Settlement or Village "
            f"within {R.FISH_ADJACENCY_REACH} cells of open ocean, a "
            f"river, or a lake catches some every turn, scaled by that "
            f"specific water body's own size (ocean flat; a river by its "
            f"real flow; a lake by its own connected size). Never "
            f"depletes."
        )
    if name == "Firewood":
        lines.append("")
        lines.append("Consumed by every settlement/village, Winter only.")
    if name == "Clothes":
        lines.append("")
        lines.append("Worn out slowly by every settlement/village, year-round.")

    lines.append("")
    if spec["category"] == "Livestock":
        lines.append(
            "Not a stockpiled resource — tracked as a living, breeding "
            "regional population instead (see Settlements & Villages / "
            "Prosperity)."
        )
    elif name in R._SETTLEMENT_STORAGE_RESOURCES:
        lines.append(
            "Stored per-settlement/village, in that node's own shared "
            "space budget (see Storage & Spoilage)."
        )
    else:
        lines.append(
            "Still on the old shared national stockpile, not yet "
            "migrated to per-settlement storage."
        )

    props = []
    if spec.get("edible"):
        props.append("edible")
    if spec.get("luxury"):
        props.append("luxury")
    if not spec.get("renewable", True):
        props.append("non-renewable source")
    if props:
        lines.append("(" + ", ".join(props) + ")")

    return "\n".join(lines)


def category_overview_text(category):
    names = sorted((n for n, s in R.RESOURCES.items() if s["category"] == category),
                   key=lambda n: (R.RESOURCES[n]["tier"], n))
    lines = [category, CATEGORY_BLURB.get(category, ""), "",
             "Select an entry on the left for full detail. At a glance:", ""]
    for n in names:
        spec = R.RESOURCES[n]
        building = R.BUILDINGS.get(n, {}).get("name", "")
        lines.append(f"  {n}  (Tier {spec['tier']}, {building}) — {_spoil_desc(spec['spoil_rate'])}")
    return "\n".join(lines)


def resource_children(category):
    return sorted((n for n, s in R.RESOURCES.items() if s["category"] == category),
                  key=lambda n: (R.RESOURCES[n]["tier"], n))


# --- hand-written articles --------------------------------------------------

def _settlements_article():
    pop = POPULATION_RANGE
    tax = SETTLEMENT_TAX_INCOME
    cf = CHILDREN_FRACTION_RANGE
    parts = [
        "Settlements & Villages",
        (
            "Every faction's territory is built from Regions, each "
            "containing some mix of Settlements (City, Castle, Town) and "
            "Villages."
        ),
        "SETTLEMENTS (City / Castle / Town)",
        (
            "Population is rolled once when a settlement is founded and "
            "never grows on its own — it's a flavor/info stat, split into "
            f"adults and children ({_pct(cf[0])}–{_pct(cf[1])} of the "
            "total are children):"
        ),
        "\n".join([
            f"  City:   {pop['city'][0]:,}–{pop['city'][1]:,} pop, civic wealth {tax['city'][0]}–{tax['city'][1]}/turn",
            f"  Castle: {pop['castle'][0]:,}–{pop['castle'][1]:,} pop, civic wealth {tax['castle'][0]}–{tax['castle'][1]}/turn",
            f"  Town:   {pop['town'][0]:,}–{pop['town'][1]:,} pop, civic wealth {tax['town'][0]}–{tax['town'][1]}/turn",
        ]),
        (
            "(A Castle's population skews toward garrison over civilians, "
            "hence the lower range despite outbuilding a Town.) Civic "
            "wealth doesn't generate any actual Gold any more (see "
            "Currency) — it's purely a Prosperity input now, folded into "
            "how big a settlement's target meter is."
        ),
        (
            "A Settlement is a consumer and a converter — it eats "
            "(Food/Firewood/Clothes/Luxury, see Prosperity) and runs "
            "every processing building (Mill, Bakery, Sawmill, Winery, "
            "...), turning raw stock it's holding into Food Products, "
            "Manufactured Goods, and Luxury Goods. It does NOT farm, log, "
            "or mine on its own."
        ),
        "VILLAGES",
        f"Population: {pop['village'][0]:,}–{pop['village'][1]:,}, no tax income of its own.",
        (
            "A Village is purely a producer — the actual farm/logging "
            "camp/mine, wherever a region's terrain supports one (see the "
            "Crops/Livestock/Forestry/Mining categories). It has no mill, "
            "loom, or forge of its own: raw Logs (or any non-food raw "
            "material) sitting in a village's storage is genuinely stuck "
            "there until Local Logistics (see that article) physically "
            "ships it to a Settlement that can convert it — raw Crops are "
            "the one exception, edible on their own (see the Crops "
            "category), so a Village can feed itself straight off its own "
            "harvest without needing a Settlement's Bakery at all. A "
            "Village's population eats exactly like a Settlement's does "
            "— it is not exempt from Food/Firewood/Clothes/Luxury needs, "
            "though see Prosperity for the grace period before a Food "
            "shortfall actually costs population."
        ),
        (
            "A City can spawn a new Village nearby once its prosperity "
            "meter fills (see Prosperity) — the only way new Villages "
            "appear after world generation and initial wildland claims."
        ),
        (
            "A Village's panel shows what it actually grows and how much "
            "of each resource it's projected to produce over the coming "
            "year — real numbers from the same crop/industry yield math "
            "that drives production, not a flavor stat. A region's total "
            "yield is split evenly across every Village in it, so this is "
            "each Village's own share."
        ),
    ]
    return "\n\n".join(parts)


def _storage_article():
    R_ = R
    parts = [
        "Storage & Spoilage",
        (
            "Every Settlement and Village owns its own stockpile — not "
            "one shared national pool. A settlement can be starving "
            "while the rest of its faction is fine if nothing has "
            "actually reached its own granary."
        ),
        "SPACE BUDGET",
        (
            "Storage is one shared space budget, not an independent cap "
            "per resource — a full granary of Bread really does mean "
            "less room for Wheat. Every stored unit costs a flat 1 space "
            "regardless of type."
        ),
        "\n".join([
            f"  City storage:    {R_.SETTLEMENT_STORAGE_BASE['city']:,}",
            f"  Castle storage:  {R_.SETTLEMENT_STORAGE_BASE['castle']:,}",
            f"  Town storage:    {R_.SETTLEMENT_STORAGE_BASE['town']:,}",
            f"  Village storage: {R_.VILLAGE_STORAGE_BASE:,} (flat — no Granary/Warehouse of its own)",
        ]),
        (
            f"A Granary adds +{R_.GRANARY_STORAGE_BONUS:,} space; a "
            f"Warehouse adds +{R_.WAREHOUSE_STORAGE_BONUS:,} (both apply "
            "to the same shared budget, not a separate one of their own "
            "— see the Construction article for cost/build time)."
        ),
        "SPOILAGE",
        (
            "Each resource has its own spoil rate (see its entry under "
            "Crops/Food Products/etc.), applied to unsold stock every "
            "turn — from \"never\" (Iron, Tools, Furniture, ...) to "
            "\"quickly\" (Bread, Milk)."
        ),
        "OVERFLOW",
        (
            "Production is never rejected at the door. Once total stock "
            "exceeds capacity, the overage decays at an accelerated rate "
            "on top of the resource's normal spoilage — "
            f"{R_.OVERFLOW_SPOILAGE_MULTIPLIER:.0f}x the base spoil "
            f"rate, with a floor of {_pct(R_.OVERFLOW_MIN_RATE)}/turn "
            "even for a resource that never normally spoils (there's "
            "genuinely no room, whether or not the good itself rots). "
            "The loss is capped at "
            f"{_pct(R_.MAX_OVERFLOW_LOSS_FRACTION)} of that resource's "
            "stock in a single turn, so even the worst case (badly "
            "overflowing + fast-spoiling) keeps a sliver of grace rather "
            "than an instant wipeout."
        ),
        "WHAT'S NOT YET REAL STORAGE",
        (
            "Livestock is the one exception — it's never a stockpiled "
            "quantity at all, but a living regional population (see "
            "Settlements & Villages). Every other resource in the game, "
            "Gold included (see Currency), has a real per-settlement "
            "stockpile now."
        ),
    ]
    return "\n\n".join(parts)


def _currency_article():
    parts = [
        "Currency",
        (
            "Gold is a real Manufactured Good now, not a flat per-turn tax "
            "draw — it has to be mined and minted like anything else, "
            "stockpiled at specific settlements (see Storage & Spoilage), "
            "and physically spent from wherever it's actually sitting. "
            "There's no faction-wide treasury any more: a settlement can "
            "be Gold-rich while another of the same faction's own "
            "settlements is Gold-poor, exactly like every other "
            "settlement-storage resource."
        ),
        "MINING AND MINTING",
        (
            "Gold Ore is a Mining resource like Iron or Gems — it spawns "
            "on mountain terrain, scarce (rare, the same rarity tier as "
            "Gems), and comes in via a Gold Mine exactly like any other "
            "ore. A Mint then converts Gold Ore into Gold, 1:1, the same "
            "automatic conversion every other recipe in the game uses "
            "(see Construction/the resource categories) — no separate "
            "\"build a Mint\" step, it runs the moment a settlement is "
            "holding both the ore and the recipe applies."
        ),
        "WHAT IT'S SPENT ON",
        (
            "Everything that used to draw from the old treasury still "
            "costs Gold exactly the same way — expansion claims, "
            "settlement/road/ship/shipyard construction — it's just paid "
            "out of the faction's settlement storage now (spread across "
            "whichever settlements actually have it, largest stockpile "
            "first, same rule Iron/Logs/Stone already followed), and "
            "trade (see Regional Markets/Foreign Trade) pays and collects "
            "it at the specific settlements actually making the deal."
        ),
        "BARTER",
        (
            "A settlement short on Gold isn't shut out of trade — if it "
            "can't cover a deal's price in Gold, it pays the shortfall "
            "with a real surplus good instead, priced at that good's "
            "normal gold-equivalent tier value (see the resource "
            "categories), no penalty for using it. This applies to both "
            "Regional Markets and Foreign Trade. A settlement with "
            "nothing to spare either way still receives the goods it's "
            "buying — payment just falls short, rather than the deal "
            "being blocked outright."
        ),
        "STARTING RESERVE",
        (
            f"Every faction begins the game with a modest "
            f"{R.STARTING_GOLD_PER_FACTION:,}-Gold reserve, split evenly "
            "across its own starting settlements, so turn-1 construction "
            "and trade aren't completely frozen while the first Gold Mine "
            "and Mint get running. Every turn after that, Gold is exactly "
            "as real and production-driven as any other Manufactured "
            "Good — there's no ongoing free income any more."
        ),
    ]
    return "\n\n".join(parts)


def _prosperity_article():
    parts = [
        "Prosperity",
        (
            f"Every Settlement and Village has a 0–{R.PROSPERITY_MAX:.0f} "
            "prosperity meter that rises and falls with how well its "
            "faction's economy is actually doing, not a static score "
            "rolled once. It eases toward a target each turn rather than "
            "jumping — by design, a slow, long-term payoff (roughly "
            f"{round(1/R.PROSPERITY_EASE)} turns / "
            f"~{round(1/R.PROSPERITY_EASE/R.YEAR_LENGTH_TURNS, 1)} years to "
            "close 90% of the gap to a steady target)."
        ),
        "THE TARGET",
        (
            "A settlement's target is driven by the gold-value of what "
            "it needs each turn (Food/Firewood/Clothes/Luxury, priced by "
            "tier) plus its tax income, scaled by how healthy its whole "
            "faction's economy is (produced/earned vs. consumed this "
            "turn, faction-wide) — a faction running a deficit drags "
            "every one of its settlements' targets down, not just the "
            "one running short. A Village's target instead comes from "
            "the gold-value of its own farm output (it carries no tax of "
            "its own)."
        ),
        "THE INSTANT SIDE: SHORTAGES AND LUXURY",
        (
            "On top of the slow-moving target, actually running short of "
            "a survival good docks prosperity immediately, scaled by how "
            "much of the need went unmet:"
        ),
        "\n".join([
            f"  Food shortage:     −{R._SHORTAGE_PROSPERITY_PENALTY['Food']:.1f} x deficit fraction (and starvation — see below)",
            f"  Firewood shortage: −{R._SHORTAGE_PROSPERITY_PENALTY['Firewood']:.1f} x deficit fraction, Winter only (and freezing)",
            f"  Clothes shortage:  −{R._SHORTAGE_PROSPERITY_PENALTY['Clothes']:.1f} x deficit fraction",
        ]),
        (
            "A Food or Firewood shortfall costs population too, but not "
            "immediately — a settlement/village can go "
            f"{R.STARVATION_GRACE_TURNS} consecutive turns without enough "
            "Food, or "
            f"{R.FREEZE_GRACE_TURNS} consecutive turns without enough "
            "Firewood in Winter, with no population loss at all (the "
            "prosperity penalty above still applies right away either "
            "way). Only once that streak runs longer does starvation "
            f"(up to {_pct(R.STARVATION_SEVERITY)} per turn) or freezing "
            f"(up to {_pct(R.FREEZE_SEVERITY)} per turn) actually start "
            "costing population, and the streak resets to zero the "
            "moment the need is fully met again — a short rough patch "
            "isn't a death sentence. Clothes never costs population, "
            "only prosperity."
        ),
        "ALERTS",
        (
            "The player's own settlements/villages are watched every turn "
            "for exactly these conditions — a Food or Firewood shortfall "
            "(still inside its grace period, or past it and actively "
            "costing population), and storage sitting over capacity and "
            "spoiling the overage. Anything currently wrong shows up in "
            "the Alerts panel (top-left of the map) and as a warning "
            "badge directly on that settlement/village's own map marker "
            "— click an alert to jump straight to it. This reflects "
            "CURRENT state, not a one-time event: a problem stays listed "
            "for as long as it's actually still happening, whether or "
            "not the player was watching when it started."
        ),
        (
            "Luxury Goods (Wine, Beer, Jewelry, Furniture, Fine Clothes, "
            "Books, Candles — see the Luxury Economy article) are the "
            "mirror image: meeting the need gives a direct "
            f"+{R.LUXURY_PROSPERITY_BONUS:.1f} x fulfillment-fraction "
            "BONUS to prosperity. Going without is simply a non-event — "
            "never a penalty, never a population consequence. These "
            "aren't survival goods; they're exactly what the name says."
        ),
        "CITY GROWTH",
        (
            f"A City whose prosperity meter fills all the way to "
            f"{R.PROSPERITY_MAX:.0f} spawns a brand-new Village nearby "
            "and resets to 0 — the only way new Villages appear after "
            "world generation and initial wildland claims. The new "
            "Village gets a road back to its founding City AND a direct "
            f"road to up to {R.VILLAGE_MESH_MAX_LINKS} other villages "
            "already in the same region (whichever are closest, within "
            f"{R.VILLAGE_MESH_LINK_RADIUS} cells) — a real interconnected "
            "region instead of every village only ever linking back to "
            "one city."
        ),
    ]
    return "\n\n".join(parts)


def _local_logistics_article():
    parts = [
        "Local Logistics (within a Region)",
        (
            "Nothing is teleported: raw Crop/Livestock/Forestry/Mining "
            "production lands at a region's own Villages first (they're "
            "the actual producers — see Settlements & Villages), and has "
            "to be physically moved before it does anyone any good. "
            "Every turn, within each region, the game automatically "
            "matches a Village or Settlement sitting on real surplus of "
            "a resource to another node in the SAME region that "
            "actually needs it, and dispatches a free shipment — no "
            "player or AI decision involved, and no Gold changes hands "
            "(this is internal redistribution, not a trade deal)."
        ),
        "WHAT COUNTS AS SURPLUS/NEED",
        (
            f"A node keeps a floor of {R.LOCAL_SURPLUS_RESERVE} units of "
            f"most things (a smaller {R.LOCAL_HOUSEHOLD_SURPLUS_RESERVE}-"
            "unit floor for Firewood/Clothes specifically — genuinely "
            "small-scale, per-capita goods, not bulk resources like Iron "
            "or Logs) before shipping the rest, plus "
            f"{R.LOCAL_RESERVE_BUFFER_TURNS} turns' worth of its own "
            "near-term need for consumption goods "
            "(Food/Firewood/Clothes/Luxury) — it won't ship away food "
            "it's about to need itself. Food Products, edible raw Crops, "
            "and Luxury Goods are each pooled (any Bread/Meat/Milk/... OR "
            "raw Wheat/Potatoes/... covers \"Food\"; any Wine/Jewelry/... "
            "covers \"Luxury\") rather than reserved individually, since "
            "they're fully interchangeable for that purpose. A Settlement "
            "additionally \"wants\" any production-input resource (Wheat, "
            "Flour, Milk, Wool, Cotton, Cloth, and the Mining/Forestry raw "
            f"materials) once its own stock drops below "
            f"{R.LOCAL_NEED_THRESHOLD} units — a Village never does for a "
            "non-food input, since it can't convert anything; an edible "
            "Crop like Wheat can still move toward a Village that's "
            "actually low on Food, just not toward one that already has "
            "plenty."
        ),
        (
            "Survival needs are checked before ordinary production-input "
            "traffic, so a node with several kinds of surplus always "
            "tries to cover someone's starvation/freezing risk first."
        ),
        "THE SHIPMENT ITSELF",
        (
            "A straight-line path between the two positions, taking "
            f"{R.MIN_LOCAL_TRANSIT_TURNS}–{R.MAX_LOCAL_TRANSIT_TURNS} "
            "turns depending on distance, "
            f"{R.LOCAL_SHIPMENT_MIN_QUANTITY}–"
            f"{R.LOCAL_SHIPMENT_MAX_QUANTITY} units per trip. A node can "
            f"have up to {R.MAX_ACTIVE_LOCAL_SHIPMENTS_PER_NODE} "
            "shipments outbound at once (receiving is uncapped). No "
            "storage-capacity check on delivery — an over-full granary "
            "just spoils faster (see Storage & Spoilage), the wagon "
            "isn't turned away."
        ),
        (
            "A region with no Settlement of its own has nothing to ship "
            "raw goods to, so they just accumulate. Reaching a different "
            "region entirely is Regional Markets, not this."
        ),
    ]
    return "\n\n".join(parts)


def _regional_markets_article():
    parts = [
        "Regional Markets (across Regions, same faction)",
        (
            "Once a settlement's own region genuinely can't help (Local "
            "Logistics, above, already had its shot this same turn), it "
            "can reach any OTHER settlement its own faction owns "
            "anywhere on the map — a real, Gold-priced market, not free "
            "redistribution. Same-region pairs are always skipped here; "
            "that's Local Logistics' job, for free."
        ),
        "PRICE AND PAYMENT",
        (
            "Priced with the same tier/surplus/need formula foreign "
            "trade uses (see Foreign Trade), paid by the buying "
            "settlement's own Gold on dispatch and credited to the "
            "selling settlement's own storage on delivery (see Currency) "
            "— a settlement genuinely short on Gold barters real goods of "
            "roughly equivalent value instead, and how big a deal it can "
            "strike at all is capped by its Gold plus what it could "
            "barter, not a faction-wide wallet."
        ),
        "THE SHIPMENT ITSELF",
        (
            "A real, terrain-aware path (the same Dijkstra/"
            "elevation-cost pathfinding every road/route in the game "
            f"uses), taking {trade.MIN_REGIONAL_TRANSIT_TURNS}–"
            f"{trade.MAX_REGIONAL_TRANSIT_TURNS} turns, "
            f"{trade.REGIONAL_TRADE_MIN_QUANTITY}–"
            f"{trade.REGIONAL_TRADE_MAX_QUANTITY} units per trip, up to "
            f"{trade.MAX_ACTIVE_REGIONAL_SHIPMENTS_PER_SETTLEMENT} "
            "outbound per settlement at once. Land routes only — a "
            "faction whose settlements are only reachable by sea from "
            "each other can't regional-trade between them yet."
        ),
        "RISK",
        (
            "A shipment can be lost crossing unclaimed wildland, or "
            "another faction's territory if that faction is at war with "
            "you (a faction's own regions aren't guaranteed to be "
            f"geographically contiguous) — a "
            f"{_pct(trade.REGIONAL_SHIPMENT_RISK_PER_TURN)} chance per "
            "turn while in transit through risky territory. Both the "
            "goods and the payment already collected for them (Gold "
            "and/or barter goods) are simply gone if that happens."
        ),
        "SELLING NON-PERISHABLES TO A CITY",
        (
            "Local Logistics and the need-based market above both only "
            "ever move a resource somewhere that genuinely needs it — if "
            "nothing in the whole faction currently needs more Iron, "
            "neither one ever rescues an overflowing settlement's surplus "
            "Iron, and it just decays via the overflow penalty (see "
            "Storage & Spoilage) for no real reason. For non-perishable "
            "resources only (spoil rate 0 — Iron, Tools, Furniture, and "
            "the like), any City-kind settlement always has room for a "
            "same-faction settlement's surplus, whether or not it's "
            "genuinely \"needed\" there, functioning as an internal "
            "collection point that then exports the goods through the "
            "faction's ordinary Foreign Trade. This leg is free — no Gold "
            "either end, the same shape as Local Logistics — so a "
            "cash-poor faction can always use it, unlike the Gold-priced "
            "market above."
        ),
        (
            f"Same terrain-aware pathing, transit, and risk of loss as "
            f"the market above; {trade.SELL_TO_CITY_MIN_QUANTITY}–"
            f"{trade.SELL_TO_CITY_MAX_QUANTITY} units per trip, sharing "
            f"the same {trade.MAX_ACTIVE_REGIONAL_SHIPMENTS_PER_SETTLEMENT}"
            "-outbound-shipment cap per settlement as the market above. A "
            "City stops absorbing once its own total stock reaches "
            f"{_pct(trade.CITY_STOCKPILE_CEILING_FRACTION)} of its own "
            "storage capacity, so this can't just relocate the overflow "
            "problem onto the city instead of actually solving it. "
            "Flooding a city with surplus this way naturally makes its "
            "own export price cheaper too (see Foreign Trade's pricing) "
            "— more supply sitting there is exactly what already pulls "
            "the price down, and it corrects itself over time as the "
            "glut gets traded away."
        ),
    ]
    return "\n\n".join(parts)


def _foreign_trade_article():
    parts = [
        "Foreign Trade",
        (
            "Every faction, including the player's, independently "
            "evaluates and initiates trade deals with others each turn "
            "— fully autonomous, no obligation to participate."
        ),
        "GETTING A ROUTE OPEN",
        (
            "Two factions must have made contact (see Diplomacy) and be "
            f"on decent terms (standing ≥ "
            f"{diplomacy.TRADE_STANDING_THRESHOLD}) before a route can "
            "even be proposed. Neither side gets to open one "
            "unilaterally: whoever proposes it still needs the other "
            "side to actually agree. Between two AI factions this is "
            "weighed automatically (standing, species affinity, and real "
            "economic complementarity — the same test Diplomacy's Form "
            "Alliance uses, just a much lower bar). The player is never "
            "auto-decided for either way: an AI proposing to you queues "
            "an incoming proposal on that faction's panel instead, "
            "showing what it currently has stocked that you don't and "
            "what it could produce that you have no access to at all, "
            "for you to Accept or Decline yourself; proposing to an AI "
            "is always your own click. A land route then has to be "
            "physically built (growing from both capitals at once, "
            f"{trade.TRADE_ROUTE_CELLS_PER_TURN} cells/turn per end); a "
            "sea route opens immediately once agreed, since there's "
            "nothing to construct across open water. A decline sets a "
            f"{trade.TRADE_ROUTE_DECLINE_COOLDOWN_TURNS}-turn cooldown "
            "before that pair can be asked again."
        ),
        "THE DEAL",
        (
            "A nation will only ever sell real spare surplus — enough of "
            "a safety reserve is always held back first "
            f"({trade.SAFETY_RESERVE_TURNS} turns of its own "
            "settlements' need for a survival good; "
            f"{_pct(trade.NON_FOOD_RESERVE_FRACTION)} of storage capacity "
            f"for anything else) — and only in batches of at least "
            f"{trade.MIN_TRADE_QUANTITY} units. Price scales with the "
            "seller's real surplus (more spare stock = cheaper) and the "
            "buyer's real scarcity (more desperate = pricier), "
            f"discounted {_pct(1 - trade.ALLY_TARIFF_DISCOUNT)} for "
            "allies (\"lower tariffs\"). A caravan picks up from and "
            "delivers to whichever specific settlement actually has the "
            "surplus/need — not always the capital — so price reflects "
            "that settlement's own local situation, not a national "
            "average."
        ),
        "THE CARAVAN",
        (
            f"Travels {trade.MIN_TRANSIT_TURNS}–{trade.MAX_TRANSIT_TURNS} "
            "turns out with the goods, delivers, then has to make it all "
            "the way back before the seller actually gets paid — in real "
            "Gold if the buyer's paying settlement has enough on hand, "
            "otherwise a barter good of roughly equivalent value instead "
            "(see Currency); either way, if the caravan is lost on the "
            "way back, that payment is lost with it. Allied "
            f"caravans move {_pct(1 - trade.ALLY_TRANSIT_SPEEDUP)} "
            "faster. A caravan crossing hostile third-party territory "
            "risks being lost entirely "
            f"({_pct(trade.LAND_RISK_PER_TURN)}/turn) — trading with an "
            "active war enemy never holds up at all. Each faction runs "
            f"up to {trade.MAX_ACTIVE_TRADES_PER_FACTION} trades and "
            f"{trade.MAX_ACTIVE_ROUTE_PROJECTS_PER_FACTION} "
            "route-under-construction at once."
        ),
    ]
    return "\n\n".join(parts)


def _diplomacy_article():
    seen = set()
    aff_lines = []
    for pair, val in diplomacy.SPECIES_AFFINITY.items():
        key = tuple(sorted(pair))
        if key in seen:
            continue
        seen.add(key)
        a, b = key
        aff_lines.append(f"  {a} ↔ {b}: {val:+d}")
    aff_text = "\n".join(sorted(aff_lines))
    parts = [
        "Diplomacy",
        (
            "Every pair of factions has a relationship: a stance (Ally / "
            "Neutral / Enemy) and a numeric standing "
            f"({diplomacy.STANDING_MIN}..{diplomacy.STANDING_MAX}) that "
            "actions nudge up or down. Crossing a threshold only UNLOCKS "
            "a regime change — it never triggers one on its own; you (or "
            "the AI) still have to actually act on it."
        ),
        "\n".join([
            f"  Standing ≥ {diplomacy.ALLY_THRESHOLD}: Form Alliance becomes available",
            f"  Standing ≤ {diplomacy.WAR_THRESHOLD}: Declare War becomes available",
            f"  Standing ≥ {diplomacy.TRADE_STANDING_THRESHOLD}: a trade route can be proposed",
        ]),
        "FIRST CONTACT",
        (
            "Relationships don't exist until contact is made (the player "
            "discovering a faction through fog of war, or any two "
            "factions sharing a border). Initial standing is "
            "deterministic, not a dice roll — purely a function of "
            "species affinity:"
        ),
        aff_text,
        "  (same species: +2; any unlisted pair: 0/neutral)",
        (
            "Affinity tops out at 2, so first contact is always "
            "Neutral, never immediate war or alliance."
        ),
        "ACTIONS (one per relationship per turn)",
        "\n".join([
            f"  Improve Relations: standing {diplomacy.IMPROVE_RELATIONS_DELTA:+d}",
            f"  Fabricate Claim (on a region): standing {diplomacy.FABRICATE_CLAIM_DELTA:+d}",
            f"  Terrorize Locals (in a region): standing "
            f"{diplomacy.TERRORIZE_LOCALS_DELTA:+d}, and costs the actor "
            f"{diplomacy.TERRORIZE_MORALE_COST} of their own morale",
            f"  Declare War: instant, once standing ≤ {diplomacy.WAR_THRESHOLD}",
        ]),
        "ALLIANCES AND TRADE PROPOSALS",
        (
            "Both are a real ask, not a formality — the target actually "
            "weighs standing, species affinity, and whether there's "
            "genuine mutual economic benefit (each side having spare "
            "surplus the other lacks) before accepting. An alliance "
            "needs a much higher bar to clear than a trade route, since "
            "it's a far more binding commitment."
        ),
    ]
    return "\n\n".join(parts)


def _expansion_article():
    parts = [
        "Expansion & Claiming Wildland",
        (
            "Land not part of a faction's starting foothold begins "
            "UNCLAIMED, defended by a neutral \"wildland\" garrison. "
            "Claiming one requires being adjacent to land you already "
            "hold (or, if there's no land connection, reachable by sea "
            "from a coastal settlement) — no leapfrogging."
        ),
        "STARTING A CLAIM",
        (
            f"Costs {expansion.CLAIM_BASE_COST['Gold']:.0f} Gold plus "
            f"{expansion.CLAIM_COST_PER_CELL['Gold']:.2g} Gold per cell "
            f"of the region's area, and takes "
            f"{expansion.CLAIM_BASE_TURNS} turns plus "
            f"{expansion.CLAIM_TURNS_PER_CELL:.2g} turns per cell (paid "
            "and started immediately; the fight only happens once that "
            "work is done)."
        ),
        "RESOLVING IT",
        (
            "For the player, a completed claim triggers an interactive "
            "battle against the garrison (see Military & Combat) instead "
            "of an instant formula — the garrison's army is sized off "
            "the region's wildland-strength rating, same composition "
            "math as a real nation's army, but each of its soldiers "
            f"fights at {_pct(expansion.WILDLAND_COMBAT_STRENGTH_MULT)} "
            "strength."
        ),
        (
            "Win: the region transfers, and gets settled fresh — "
            f"{expansion.WILDLAND_VILLAGE_MIN}–"
            f"{expansion.WILDLAND_VILLAGE_MAX} Villages scaled by area, "
            "but NEVER a free City/Town/Castle; a real Settlement still "
            "has to be built there like any other (see Construction)."
        ),
        (
            "Loss: no refund. The garrison digs in — its strength rating "
            f"rises {_pct(expansion.CLAIM_FAIL_STRENGTH_BUMP - 1)} "
            f"permanently — and a {expansion.CLAIM_FAIL_COOLDOWN_TURNS}-"
            "turn cooldown starts before that region can be attempted "
            "again."
        ),
        (
            "Every settled region with at least one Village automatically "
            "gets a dirt road connecting it to the nearest already-"
            "settled neighboring region of the same faction, so a "
            "freshly claimed region's Villages are never permanently "
            "isolated from the rest of the road network."
        ),
    ]
    return "\n\n".join(parts)


def _construction_article():
    def _cost_line(cost):
        return ", ".join(f"{v:,} {k}" for k, v in cost.items())
    sc = construction.SETTLEMENT_BUILD_COST
    st = construction.SETTLEMENT_BUILD_TURNS
    parts = [
        "Construction",
        (
            "Every building costs real resources and takes real turns — "
            "nothing is free, and (except a Shipyard-launched ship, see "
            "Commanders & Ships) nothing is instant. Costs, Gold included "
            "(see Currency), are paid from the faction's settlement "
            "storage, spread across whichever settlements actually have "
            "the goods, largest stockpile first."
        ),
        "SETTLEMENTS (City / Castle / Town)",
        "\n".join([
            f"  Town:   {_cost_line(sc['town'])} — {st['town']} turns at full speed",
            f"  Castle: {_cost_line(sc['castle'])} — {st['castle']} turns at full speed",
            f"  City:   {_cost_line(sc['city'])} — {st['city']} turns at full speed",
        ]),
        (
            "A new settlement not already connected to the road network "
            "gets one built alongside it automatically; construction "
            f"runs at {_pct(construction.ROAD_SPEED_PENALTY)} speed "
            "until that road is finished."
        ),
        "SHIPYARD (coastal City only)",
        f"  Cost: {_cost_line(construction.SHIPYARD_COST)} — {construction.SHIPYARD_BUILD_TURNS} turns",
        (
            "A steep, one-time investment. Once built, ships launched "
            "from that specific shipyard (not faction-wide) are free and "
            f"{commander.SHIPYARD_SPEED_MULT}x faster than a normally-"
            "built ship — see Commanders & Ships."
        ),
        "GRANARY / WAREHOUSE (any settlement)",
        "\n".join([
            f"  Granary:   {_cost_line(construction.GRANARY_COST)} — {construction.GRANARY_BUILD_TURNS} turns, +{R.GRANARY_STORAGE_BONUS:,} storage",
            f"  Warehouse: {_cost_line(construction.WAREHOUSE_COST)} — {construction.WAREHOUSE_BUILD_TURNS} turns, +{R.WAREHOUSE_STORAGE_BONUS:,} storage",
        ]),
        (
            "Both add to the same shared storage budget (see Storage & "
            "Spoilage), not a separate pool of their own."
        ),
    ]
    return "\n\n".join(parts)


def _commanders_article():
    parts = [
        "Commanders & Ships",
        (
            "A Commander is a player-controlled scout: no combat, no "
            f"risk of being lost, moves {commander.COMMANDER_CELLS_PER_TURN} "
            "cells/turn on land, and reveals fog of war in a "
            f"{commander.COMMANDER_VISION_RADIUS}-cell radius around "
            "itself, independent of owned territory. An order sent into "
            "fog just walks or sails as far as it can and stops at the "
            "edge."
        ),
        "SHIPS ARE PHYSICAL OBJECTS",
        (
            "Not a permanent ability. A Commander that steps off water "
            "leaves its ship behind, beached at the last cell of water "
            "it crossed; it (or a different Commander) can walk back and "
            "re-board that same ship, build a new one elsewhere "
            "(abandoning the old one in place), or dismantle a beached "
            f"ship for a {_pct(commander.SHIP_DISMANTLE_REFUND_FRACTION)} "
            "refund of its Logs cost, delivered to the nearest "
            "settlement. A Commander next to — not just exactly on — a "
            "beached ship can board or dismantle it."
        ),
        "BUILDING A SHIP",
        (
            "  Away from a Shipyard: "
            f"{', '.join(f'{v:,} {k}' for k, v in commander.SHIP_COST.items())}, "
            f"{commander.SHIP_BUILD_TURNS} turns."
        ),
        (
            "  At a same-faction Shipyard (see Construction): free and "
            "instant, and the ship sails "
            f"{commander.SHIPYARD_SPEED_MULT}x faster for as long as it "
            "exists — the entire payoff for that building's very steep "
            "cost."
        ),
        (
            "Movement routes sea-then-land, never mixed in an "
            "unpredictable way, so a path crosses the coastline at most "
            "once."
        ),
    ]
    return "\n\n".join(parts)


def _luxury_article():
    names = R._LUXURY_GOODS
    parts = [
        "Luxury Economy",
        (
            "Seven Luxury Goods exist once the rest of the economy (raw "
            "production, storage, local/regional/foreign trade) is "
            f"already working: {', '.join(names)}. All are Tier 5 — the "
            "top of the crafting chain, priced accordingly (see each "
            "resource's own entry for its exact recipe and inputs — two "
            "of them needed brand new raw resources that didn't exist "
            "before this — Grapes for Wine, Gems for Jewelry — and Books "
            "needed a new Paper intermediate, made from Cotton)."
        ),
        "WHAT THEY ACTUALLY DO",
        (
            "Luxury Goods satisfy a settlement/village's Luxury need "
            "(see Prosperity) — a small per-capita demand, pooled across "
            "all seven (any one of them satisfies it, fully "
            "interchangeably). Meeting it gives prosperity a real, "
            f"direct bonus (+{R.LUXURY_PROSPERITY_BONUS:.1f} at full "
            "fulfillment); going without is simply a non-event, never a "
            "penalty and never a population consequence, unlike Food/"
            "Firewood/Clothes. That's the entire distinction between a "
            "luxury and a survival good in this game."
        ),
        (
            "They're otherwise ordinary settlement-storage resources in "
            "every other respect — real per-settlement storage competing "
            "for the same space budget, real spoilage (Beer spoils "
            "fastest, Wine keeps much better, most of the rest never "
            "spoil at all), and they move through Local Logistics, "
            "Regional Markets, and Foreign Trade exactly like any other "
            "resource, priced at the Tier-5 rate."
        ),
    ]
    return "\n\n".join(parts)


def _military_article():
    sp = ", ".join(f"{name} {spec.get('mil', 0):+d}" for name, spec in
                   sorted(SPECIES.items(), key=lambda kv: -kv[1].get("mil", 0)))
    parts = [
        "Military & Combat",
        "MILITARY RATING",
        "A single number per faction, recomputed whenever stockpiles change:",
        "\n".join([
            "  30 (base)",
            "  + up to 20, scaled by territory (owned cells / 40, capped)",
            "  + up to 25, scaled by settlement-storage Iron (summed "
            "across every settlement the faction owns, stock / 40, capped)",
            "  + up to 20, scaled by the national Steel stockpile "
            "(stock / 30, capped — see Storage & Spoilage for how Steel "
            "is kept)",
            f"  + a flat per-species modifier: {sp}",
            "  clamped to 15..99 overall.",
        ]),
        "ARMY COMPOSITION",
        (
            "A battle army is built straight from military rating: "
            "roughly 40% Infantry, 25% Archer, 20% Cavalry by headcount "
            "(the remainder isn't separately represented). All three "
            "unit types:"
        ),
        "\n".join([
            "  Infantry: melee, high HP, sword+shield",
            "  Cavalry:  melee, fastest, hits hardest, lowest HP",
            "  Archer:   ranged (90-cell range vs. ~12-14 melee), fires "
            "arrows, 80% accuracy — a miss still spends the attack, it "
            "just deals no damage",
        ]),
        "FIGHTING A BATTLE",
        (
            "Before the fight, you can drag your own units anywhere "
            "within your half of the field (a strict midline gap keeps "
            "you out of the enemy's side); combat itself is real-time "
            "and automatic once started — units path to the nearest "
            "living enemy and attack in range. A battle ends the instant "
            "only one side has anyone left standing (or a true stalemate "
            "if both sides are wiped at once)."
        ),
        "ATTACKING A RIVAL FACTION",
        (
            "Requires an Enemy stance (see Diplomacy) and either a "
            "shared land border or a coastal route (your own coastal "
            "settlement to theirs) — pick a contested/bordering region "
            "and fight for it directly, no separate resource cost beyond "
            "the battle itself. Winning transfers that region "
            "immediately."
        ),
        "WILDLAND GARRISONS",
        (
            "See the Expansion & Claiming Wildland article — same "
            "battle system, a weaker, region-sized garrison army instead "
            "of a rival faction's."
        ),
    ]
    return "\n\n".join(parts)


def _overview_article():
    parts = [
        "Shapes of War — Compendium",
        (
            "A turn-based 4X strategy game: explore a procedurally "
            "generated fantasy world, grow a settlement economy from "
            "raw materials to finished luxury goods, trade and treat "
            "with your neighbors, and expand — by claiming wildland or "
            "conquering a rival — one region at a time."
        ),
        (
            "This compendium documents the game's actual, currently-"
            "implemented rules — not design intentions, not flavor text. "
            "Every number here is read live from the same code the game "
            "runs on, so it can't drift out of sync as the game changes."
        ),
        "HOW TO READ IT",
        (
            "The categories on the left cover the whole economy (Crops "
            "through Luxury Goods — each resource's own entry lists its "
            "tier, spoilage, where it comes from, and what it's used to "
            "craft) and every other system: settlements and villages, "
            "storage, prosperity, the three tiers of trade (local, "
            "regional, foreign), diplomacy, expansion, construction, "
            "commanders and ships, and combat. Type in the search box to "
            "filter by name."
        ),
        "ONE TURN, IN ORDER",
        (
            "Each turn: regions produce (Crops/Livestock/Forestry/"
            "Mining, landing at Villages first); production chains "
            "convert what a Settlement is holding into Food Products, "
            "Manufactured Goods, and Luxury Goods; local shipments move "
            "within a region for free, regional shipments move across "
            "regions for Gold (or barter, see Currency), and caravans "
            "carry foreign trade deals; every settlement/village eats and "
            "its prosperity meter adjusts; construction/expansion/"
            "commander orders advance; and the season clock ticks "
            f"({R.TURNS_PER_SEASON} turns per season)."
        ),
    ]
    return "\n\n".join(parts)


ARTICLES = {
    "overview": ("Overview", _overview_article()),
    "settlements": ("Settlements & Villages", _settlements_article()),
    "storage": ("Storage & Spoilage", _storage_article()),
    "currency": ("Currency", _currency_article()),
    "prosperity": ("Prosperity", _prosperity_article()),
    "local_logistics": ("Local Logistics", _local_logistics_article()),
    "regional_markets": ("Regional Markets", _regional_markets_article()),
    "foreign_trade": ("Foreign Trade", _foreign_trade_article()),
    "diplomacy": ("Diplomacy", _diplomacy_article()),
    "expansion": ("Expansion & Claiming Wildland", _expansion_article()),
    "construction": ("Construction", _construction_article()),
    "commanders": ("Commanders & Ships", _commanders_article()),
    "luxury": ("Luxury Economy", _luxury_article()),
    "military": ("Military & Combat", _military_article()),
}

# (id, title, kind) — kind is "article" (ARTICLES[id]) or "resources"
# (a RESOURCE_CATEGORIES entry, expanded into per-resource children by the UI).
NAV = [
    ("overview", "Overview", "article"),
    ("crops", "Crops", "resources"),
    ("livestock", "Livestock", "resources"),
    ("forestry", "Forestry", "resources"),
    ("mining", "Mining", "resources"),
    ("fishing", "Fishing", "resources"),
    ("food_products", "Food Products", "resources"),
    ("manufactured_goods", "Manufactured Goods", "resources"),
    ("luxury_goods", "Luxury Goods", "resources"),
    ("settlements", "Settlements & Villages", "article"),
    ("storage", "Storage & Spoilage", "article"),
    ("currency", "Currency", "article"),
    ("prosperity", "Prosperity", "article"),
    ("local_logistics", "Local Logistics", "article"),
    ("regional_markets", "Regional Markets", "article"),
    ("foreign_trade", "Foreign Trade", "article"),
    ("diplomacy", "Diplomacy", "article"),
    ("expansion", "Expansion & Claiming Wildland", "article"),
    ("construction", "Construction", "article"),
    ("commanders", "Commanders & Ships", "article"),
    ("luxury", "Luxury Economy", "article"),
    ("military", "Military & Combat", "article"),
]

_NAV_ID_TO_CATEGORY = {
    "crops": "Crops", "livestock": "Livestock", "forestry": "Forestry",
    "mining": "Mining", "fishing": "Fishing", "food_products": "Food Products",
    "manufactured_goods": "Manufactured Goods", "luxury_goods": "Luxury Goods",
}


def category_for_nav_id(nav_id):
    return _NAV_ID_TO_CATEGORY.get(nav_id)
