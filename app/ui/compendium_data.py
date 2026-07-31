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
from app.world import rivers
from app.world.worldgen import (POPULATION_RANGE, SETTLEMENT_TAX_INCOME,
                                CHILDREN_FRACTION_RANGE,
                                STARTING_POPULATION_FRACTION_RANGE,
                                ROAD_TRAVEL_SPEEDUP)
from app.world.lexicon import SPECIES, species_trait_summary

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
        "Living, breeding herds kept by each Village (not a stockpiled "
        "quantity, and not a regional pool) — see the Settlements & "
        "Villages article. Herds run on the season: births in Spring, "
        "the cull in Autumn, and Winter fed from stored Fodder. A "
        "Village that cannot feed its herd through Winter loses it. "
        "Pasture, Barn, Stable and Slaughterhouse all extend what a "
        "Village can keep and what it gets from them, and the Cull "
        "policy sets how hard it harvests each Autumn."
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


def _cost_phrase(cost):
    """'25 Gold, 30 Logs and 20 Stone' — reads as prose, and stays correct
    when the claim tables in expansion.py are retuned."""
    parts = [f"{a:g} {r}" for r, a in cost.items() if a]
    if not parts:
        return "nothing"
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


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
        # GROWTH_CYCLE maps SEASON -> stage, so it has to be inverted to list
        # stages in order. Reading it the other way round -- cycle.get("Plant")
        # -- silently returned nothing for every crop in the game, so this line
        # had always rendered as "Plant: —, Growing: —, Harvest: —, Dormant: —".
        season_for = {stage: season for season, stage in cycle.items()}
        stages = ", ".join(f"{s}: {season_for.get(s, '—')}"
                           for s in _GROWTH_STAGE_ORDER)
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
            "A settlement's real population ceiling (\"max population\") "
            f"is rolled once when it's founded, split into "
            f"adults and children ({_pct(cf[0])}–{_pct(cf[1])} of the "
            "total are children) — the ranges below:"
        ),
        "\n".join([
            f"  City:   {pop['city'][0]:,}–{pop['city'][1]:,} max pop, civic wealth {tax['city'][0]}–{tax['city'][1]}/turn",
            f"  Castle: {pop['castle'][0]:,}–{pop['castle'][1]:,} max pop, civic wealth {tax['castle'][0]}–{tax['castle'][1]}/turn",
            f"  Town:   {pop['town'][0]:,}–{pop['town'][1]:,} max pop, civic wealth {tax['town'][0]}–{tax['town'][1]}/turn",
        ]),
        (
            "(A Castle's population ceiling skews toward garrison over "
            "civilians, hence the lower range despite outbuilding a Town.) "
            "Civic wealth doesn't generate any actual Gold any more (see "
            "Currency) — it's purely a Prosperity input now, folded into "
            "how big a settlement's target meter is."
        ),
        "POPULATION: FLOOR, CEILING, GROWTH",
        (
            "A freshly founded settlement or village starts at only "
            f"roughly {_pct(STARTING_POPULATION_FRACTION_RANGE[0])}–"
            f"{_pct(STARTING_POPULATION_FRACTION_RANGE[1])} of its own "
            "max population — it hasn't grown into its full potential "
            "yet. From there it climbs back toward that ceiling on its "
            "own, very slowly, closing a small fraction of the remaining "
            "gap each turn (only while it's not currently in a Food/"
            "Firewood shortage grace period) — this genuinely takes "
            "decades of in-game time to meaningfully close, by design; "
            "expect a settlement to still be well under half its ceiling "
            "after 10-20 years. A bad enough sustained shortage can still "
            f"shrink it (see Prosperity), but never below "
            f"{_pct(R.POPULATION_MIN_FRACTION)} of its own max population "
            "— a hard-scrabble remnant survives rather than the "
            "settlement being wiped out entirely."
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
        "VILLAGES CAN BUILD NOW",
        (
            "A Village is no longer a passive producer. It can put up its "
            "own Granary, Warehouse, Vault, Barn and Preserving House "
            "(smaller and cheaper than a Settlement's), plus the four herd "
            "buildings — Pasture, Barn, Stable and Slaughterhouse — that no "
            "Settlement can build at all. It also sets its own herd cull "
            "policy. See Construction and Livestock & Herds."
        ),
        "LOSING EVERYTHING",
        (
            "A nation that loses its last region is finished: it disappears "
            "from the map, from diplomacy and from trade. Its part-built "
            "works and trade routes pass to whoever took that final region; "
            "its commanders, ships and caravans are gone. If the realm that "
            "falls is yours, the game ends."
        ),

    ]
    return "\n\n".join(parts)


def _storage_article():
    R_ = R
    pool_rows = []
    for pool in R_.STORAGE_POOLS:
        building = R_.STORAGE_BUILDING_BY_POOL[pool].title()
        base = R_.STORAGE_POOL_BASE
        pool_rows.append(
            f"  {building:<10} ({pool}) — city {base['city'][pool]:,} · "
            f"castle {base['castle'][pool]:,} · town {base['town'][pool]:,} · "
            f"village {base['village'][pool]:,}")
    bulky = sorted(R_.RESOURCES, key=lambda n: -R_.resource_bulk(n))[:5]
    compact = sorted(R_.RESOURCES, key=lambda n: R_.resource_bulk(n))[:5]
    parts = [
        "Storage & Spoilage",
        (
            "Every Settlement and Village owns its own stockpile — not "
            "one shared national pool. A settlement can be starving "
            "while the rest of its faction is fine if nothing has "
            "actually reached its own granary."
        ),
        "FOUR KINDS OF SPACE",
        (
            "Space is typed. A good only ever competes for room with "
            "others of its own kind, so a timber glut can fill your "
            "warehouse without touching the grain in your granary."
        ),
        "\n".join(pool_rows),
        (
            "Each pool has its own building, and each building upgrades "
            "through tiers rather than being a one-off — see Construction "
            "for costs. Villages build smaller and cheaper versions of all "
            "of them."
        ),
        "BULK — NOT EVERY UNIT IS THE SAME SIZE",
        (
            "A unit of grain is the reference, at 1 space. Raw timber and "
            "quarried stone are enormous; smelted metal, coin and gems are "
            "compact. This is why a warehouse full of Logs runs out of room "
            "long before the unit count suggests it should."
        ),
        "\n".join(
            ["  Bulkiest:     " + " · ".join(f"{n} {R_.resource_bulk(n):g}" for n in bulky),
             "  Most compact: " + " · ".join(f"{n} {R_.resource_bulk(n):g}" for n in compact)]),
        "PRODUCTION STOPS WHEN THERE'S NO ROOM",
        (
            "A node approaching full throttles its own primary production, "
            f"tapering from full rate at {_pct(R_.STORAGE_THROTTLE_START)} "
            "of a pool's capacity down to a complete stop once that pool is "
            "full. Nothing is silently destroyed on arrival any more — it is "
            "simply never produced, which is something you can see and act "
            "on. It also means capacity buys real output: a bigger Granary "
            "is more harvest actually taken in, not just a higher pile."
        ),
        "SPOILAGE",
        (
            "Each resource has its own spoil rate (see its entry under "
            "Crops/Food Products/etc.), applied to stock every turn — from "
            "\"never\" (Iron, Tools, Furniture, ...) to \"quickly\" "
            "(Bread, Milk, Fish)."
        ),
        "PRESERVATION",
        (
            "A Preserving House cures perishables into forms that keep: "
            "Fish into Smoked Fish, Milk into Cheese, and Meat into Salted "
            "Meat (which can only be made this way). It burns Salt doing "
            "it — little for smoked fish and cheese, a great deal for salt "
            "meat — which is what finally gives Salt a real demand. Villages "
            "can build one, and for a fishing village it is often the single "
            "most valuable thing they can build: raw Fish is the most "
            "perishable good in the game."
        ),
        "OVERFLOW",
        (
            "Production is never rejected at the door. Once a pool exceeds "
            "its capacity, the overage decays at an accelerated rate on top "
            "of the resource's normal spoilage — "
            f"{R_.OVERFLOW_SPOILAGE_MULTIPLIER:.0f}x the base spoil rate, "
            f"with a floor of {_pct(R_.OVERFLOW_MIN_RATE)}/turn even for a "
            "resource that never normally spoils. The loss is capped at "
            f"{_pct(R_.MAX_OVERFLOW_LOSS_FRACTION)} of that resource's stock "
            "in a single turn. Gold is the one exception — it occupies vault "
            "space but never decays: it is minted currency, not a perishable "
            "good."
        ),
        "LIVESTOCK IS NOT STORED",
        (
            "Animals are the one tradable thing that never occupies storage "
            "at all — they are a living herd held per Village (see "
            "Settlements & Villages). What they need instead is Fodder in "
            "the Barn to survive Winter."
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
            "on mountain and highland terrain, scarce (rare, the same rarity tier as "
            "Gems), and comes in via a Gold Mine exactly like any other "
            "ore. A Mint then converts Gold Ore into Gold, 1:1, the same "
            "automatic conversion every other recipe in the game uses "
            "(see Construction/the resource categories) — no separate "
            "\"build a Mint\" step, it runs the moment a settlement is "
            "holding both the ore and the recipe applies."
        ),
        "WHERE YOUR GOLD COMES FROM",
        (
            "Minting is almost always the answer, and it is easy to miss "
            "because nothing announces it: a settlement holding Gold Ore "
            "quietly strikes coin every single turn. Trade is usually the "
            "smaller share, and internal transfers between your own "
            "settlements mostly pay in barter rather than coin at all — "
            "which is why a busy Trade Log and a barely-moving Gold figure "
            "are not a contradiction."
        ),
        (
            "Click the Gold row in the resources sidebar to open the "
            "Treasury. It shows what you actually hold, how much of it is "
            "genuinely spendable, how much is riding home on a caravan, "
            "which settlements are holding it, and a per-cause breakdown of "
            "every coin gained or spent over recent turns — minting, "
            "foreign trade, domestic trade, construction and expansion."
        ),
        "MONEY IN TRANSIT",
        (
            "A foreign sale collects the buyer's Gold when the goods are "
            "delivered, but that payment only reaches you when the caravan "
            "completes its journey home — and it is lost with the caravan if "
            "that return leg is raided. So the Trade Log can announce a sale "
            "several turns before the coin actually arrives."
        ),
        (
            f"Settlements also hold back {trade.GOLD_TRADE_RESERVE:,} Gold "
            "each as a trading reserve, and Villages never pay for foreign "
            "trade at all, so your spendable total is always somewhat below "
            "your headline total."
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
            "Regional Markets lets a settlement short on Gold pay any "
            "shortfall with a real surplus good instead -- priced at "
            "that good's normal gold-equivalent tier value (see the "
            "resource categories), no penalty for using it, because "
            "it's your realm trading with itself and there's no "
            "currency middleman needed.\n\n"

            "Foreign Trade runs on Gold alone, never barter "
            "substitution, since inter-nation trade is real currency. "
            "A deal is sized against the Gold your paying settlement "
            "can actually release for trade -- settlement Gold above "
            "its own 200-unit Trade Reserve, the per-settlement floor "
            "trade itself respects on both incoming and outgoing "
            "deals. Wildland claims and construction do not -- they "
            "draw from the full stockpile whenever the faction "
            "decides to spend, so they're never blocked by the floor. "
            "If the buyer's paying settlement can't cover a deal in "
            "Gold above the 200 floor, the deal is sized down or "
            "skipped entirely, not patched up with substitute goods. "
            "The seller gets whatever Gold actually arrives home -- "
            "if something else drained the buyer's Gold above the "
            "floor between dispatch and delivery, the seller's haul "
            "is the smaller amount.\n\n"

            "Factions whose realm has no Mountain land: see Regional "
            "Markets (below) for how their internal trade handles the "
            "missing Gold source; for global trade the result is "
            "the same either way -- no Gold source, no real-currency "
            "deal completes. See Foreign Trade for the full mechanics "
            "of Gold-only inter-nation trade."
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
        "A SETTLEMENT KEEPS A BUFFER",
        (
            f"A settlement never puts its very last coin toward a trade — "
            f"it holds back {trade.GOLD_TRADE_RESERVE:,} Gold as a trading "
            "floor, in both Foreign Trade and Regional Markets, so a run "
            "of profitable deals doesn't just get spent right back out the "
            "moment it lands. That buffer is only a trade-spending limit, "
            "not a hard cap on the settlement's own Gold: it still draws "
            "on its full stockpile, buffer included, when the faction "
            "itself decides to spend it — claiming wildland (see "
            "Expansion) or any other real cost — so the whole point of "
            "holding it back is that it's actually there when a real "
            "opportunity comes along, not sitting empty."
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
            "one running short. A Village's target instead comes from the "
            "gold-value of what it has actually been delivering, smoothed "
            "over recent turns so a harvest season and a fallow one do not "
            "swing it (it carries no tax of its own)."
        ),
        "SHORTAGES AND LUXURY",
        (
            "Running short of a survival good lowers the TARGET the meter is "
            "easing toward, by a fraction of it, scaled by how much of the "
            "need went unmet. A place that cannot feed or warm its people "
            "cannot be prosperous, however much it produces:"
        ),
        "\n".join([
            f"  Food shortage:     −{R.PROSPERITY_SHORTAGE_WEIGHT['Food']:.0%} of the target at total famine (and starvation — see below)",
            f"  Firewood shortage: −{R.PROSPERITY_SHORTAGE_WEIGHT['Firewood']:.0%}, Winter only (and freezing)",
            f"  Clothes shortage:  −{R.PROSPERITY_SHORTAGE_WEIGHT['Clothes']:.0%}",
            f"  Timber shortage:   −{R.PROSPERITY_SHORTAGE_WEIGHT['Timber']:.0%} (homes and buildings going unmaintained)",
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
        "WHEN A REGION HAS NO FOREST AT ALL",
        (
            "Firewood only comes from wooded land — Forest, Taiga or "
            "Jungle (see Mining & Forestry). A settlement whose own region "
            "has none of those can never produce any locally, and if that is also its "
            "faction's ONLY region, Regional Markets has nothing to "
            "redistribute either (there's no second region to draw from). "
            "The only real fix is a foreign trade route with a neighbor "
            "that does have Firewood to spare, or expanding/conquering "
            "toward forested land — this is exactly the kind of gap Trade "
            "Routes and territorial expansion exist to solve. A settlement "
            "short on Firewood still scrounges some on its own (dung, scrub, "
            f"deadfall — up to {_pct(R.NO_FOREST_SUBSISTENCE_FRACTION)} of any "
            "shortfall with no forest at all, tapering to nothing by the time "
            "a region is "
            f"{_pct(R.FOREST_SELF_SUFFICIENT_SHARE)} forest and grows plenty "
            "of its own), enough that a forest-poor region isn't a total, "
            "unrecoverable death spiral, but nowhere near enough to match "
            "real Forestry access or a proper trade route. A distinct \"no "
            "local source of Firewood\" alert calls this out specifically, "
            "separate from the ordinary freezing alert, whenever it's the "
            "actual cause."
        ),
        (
            "Luxury Goods (Wine, Beer, Jewelry, Furniture, Fine Clothes, "
            "Books, Candles — see the Luxury Economy article) are the "
            "mirror image: meeting the need raises the target by up to "
            f"+{R.LUXURY_PROSPERITY_BONUS:.0%}, scaled by how much of it is "
            "met. Going without is simply a non-event — "
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
            "A real path over the ground, following the region's roads "
            "wherever they go the right way — not a line drawn straight "
            "across the wilderness. Taking "
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
            "Once a settlement or village's own region genuinely can't "
            "help (Local Logistics, above, already had its shot this "
            "same turn), it can reach any OTHER settlement OR village its "
            "own faction owns anywhere on the map — a real, Gold-priced "
            "market, not free redistribution. Same-region pairs are "
            "always skipped here; that's Local Logistics' job, for free. "
            "A Village can be either end of the deal, not just a "
            "Settlement — a Village sitting on real surplus (the only "
            "forest for miles, say) can export it just as a Settlement "
            "can, and a Village with nothing of its own in a region with "
            "no local source of something at all can still receive it "
            "from wherever in the faction actually has it, not just "
            "whatever a same-region Settlement happens to pass along."
        ),
        "PRICE AND PAYMENT",
        (
            "Priced with the same tier/surplus/need formula foreign "
            "trade uses (see Foreign Trade), but settled differently: "
            "this is the realm trading with itself, so the buying "
            "settlement pays with real goods first — whatever it can "
            "best spare, of roughly equivalent value — and only reaches "
            "into its own Gold for whatever's left once it has nothing "
            "suitable left to barter with. There's no reason for a "
            "nation to spend its own currency moving goods between its "
            "own settlements the way it would with a genuinely separate "
            "trading partner (see Foreign Trade, which is now Gold-only)."
        ),
        (
            "Gold isn't available here at all, in fact, unless the faction "
            "owns at least some Mountain or Highland land somewhere — the only "
            "terrain Gold Ore ever spawns on, and the source a Mint (see "
            "Currency) actually strikes real Gold from, continuously, for "
            "as long as that access holds. A faction with no Mountain or "
            "Highland land has no ongoing Gold income at all — only its original "
            "starting pile — so letting it spend that down on internal "
            "trade would just be a one-way drain to zero, not real "
            "currency circulating. Regional Markets falls back to pure "
            "barter for a faction in that position, and how big a deal a "
            "settlement can strike is capped by its barter capacity alone "
            "— Gold on hand doesn't widen it. Once the faction claims or "
            "conquers some Mountain land, Regional Markets picks Gold back "
            "up automatically, no separate action needed."
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
            "outbound per settlement at once. Overland or by river (see "
            "below) — a faction whose settlements are only reachable by "
            "open SEA from each other can't regional-trade between them yet."
        ),
        (
            "An overland haul follows the road network wherever it runs the "
            "right way, and moves "
            f"{ROAD_TRAVEL_SPEEDUP:g}x faster along it than across "
            "open country — so a road you built for one reason quietly speeds "
            "up every shipment that can use it, and a region left unconnected "
            "trades slowly. Foreign caravans use your roads the same way."
        ),
        "BY RIVER",
        (
            "Any settlement, town, castle or village within "
            f"{rivers.RIVER_ADJACENCY_REACH} cells of a river can load boats. "
            "When BOTH ends of a deal sit on the same connected river system "
            "— tributaries that merge downstream count as one system — the "
            "goods go by water instead of by road, and arrive far sooner: as "
            f"little as {trade.MIN_RIVER_TRANSIT_TURNS} turn, against "
            f"{trade.MIN_REGIONAL_TRANSIT_TURNS} for the same trip overland. "
            "Riverside towns are simply better connected to each other than "
            "their distance suggests, which makes a river frontage worth "
            "settling for."
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
            f"{trade.TRADE_ROUTE_CELLS_PER_TURN} cells/turn per end); river "
            "and sea routes open immediately once agreed, since there's "
            "nothing to construct along a waterway. A decline sets a "
            f"{trade.TRADE_ROUTE_DECLINE_COOLDOWN_TURNS}-turn cooldown "
            "before that pair can be asked again."
        ),
        "ROUTE KINDS: RIVER, THEN LAND, THEN SEA",
        (
            "When a route is agreed, the best available connection is taken. "
            "A RIVER route is preferred: if a course between the two capitals "
            "can be found that runs mostly along navigable water (rivers are "
            "treated as the cheap way to travel rather than an obstacle to "
            "ford), barges work that corridor — no construction, and the "
            "fastest transit of the three, reaching inland cities no coast "
            "touches. Failing that a LAND route is built in the usual way, "
            "and failing that a SEA route between two coastal realms."
        ),
        (
            "Note the river rule for FOREIGN trade is different from the "
            "domestic one above: two nations are never near enough for their "
            "settlements to share one river system, so instead of requiring a "
            "shared river, a foreign route simply follows whatever waterways "
            "happen to run the right way — the historical pattern of barge "
            "traffic working its way up a river valley."
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
        "TRADING LIVESTOCK",
        (
            "Animals trade like any other good, but in head rather than "
            "bulk, and they never touch storage: they leave the seller's "
            "pastures and arrive in whichever of the buyer's villages has "
            "room for them. A realm only sells what is above its breeding "
            f"core (at most {_pct(1 - trade.LIVESTOCK_BREEDING_RESERVE)} of "
            "the herd), and in smaller batches than ordinary goods "
            f"({trade.LIVESTOCK_MIN_TRADE_HEAD} head rather than "
            f"{trade.MIN_TRADE_QUANTITY} units). Demand is judged against "
            "what a buyer's LAND can carry — so the buyer is the realm with "
            "empty pasture, usually one whose herd a hard Winter just took. "
            "See Livestock & Herds."
        ),
        "THE CARAVAN",
        (
            f"Travels {trade.MIN_TRANSIT_TURNS}–{trade.MAX_TRANSIT_TURNS} "
            "turns out with the goods, delivers, then has to make it all "
            "the way back before the seller actually gets paid -- in real "
            "Gold only, never barter substitution, since inter-nation "
            "trade runs on currency (see Currency and BARTER, above). The "
            "deal is sized at dispatch against the Gold your buyer's "
            "paying settlement can actually release for trade; the "
            "seller's payout is whatever Gold the caravan actually "
            "carries home -- if anything else drained that buyer's Gold "
            "reserve in the meantime, the seller gets the smaller amount, "
            "and the Trade Log's + entry reads that exact figure. Either "
            "way, if the caravan is lost on the way back, that payment "
            "is lost with it. Allied "
            f"caravans move {_pct(1 - trade.ALLY_TRANSIT_SPEEDUP)} "
            "faster. A caravan crossing hostile third-party territory "
            "risks being lost entirely "
            f"({_pct(trade.LAND_RISK_PER_TURN)}/turn) — trading with an "
            "active war enemy never holds up at all. Each faction runs "
            f"up to {trade.MAX_ACTIVE_TRADES_PER_FACTION} trades and "
            f"{trade.MAX_ACTIVE_ROUTE_PROJECTS_PER_FACTION} "
            "route-under-construction at once. Your own roads, trade "
            "routes, and caravans/ships all reveal the fog of war they "
            "actually pass through — a route only shows the stretch "
            "you've genuinely discovered, not its whole length just "
            "because one end is on the map."
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
            "Relationships don't exist until contact is made: the player "
            "discovering a faction through fog of war, any two factions "
            "sharing a border, or — most commonly — two realms coming "
            f"within {diplomacy.PROXIMITY_CONTACT_RANGE} cells of each "
            "other (their nearest settlements), i.e. becoming near enough "
            "neighbors to know of each other at all. Initial standing is "
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
            "A claim is colonisation, not a purchase. You send people, and "
            "you feed them until the first harvest — that is the whole "
            "bill. No gold, no timber, no stone: those are what you spend "
            "BUILDING once you are there."
        ),
        (
            f"A normal land-adjacent claim takes "
            f"{expansion.CLAIM_SETTLERS_BASE} settlers plus "
            f"{expansion.CLAIM_SETTLERS_PER_CELL:.2g} per cell of the "
            f"region's area, and "
            f"{expansion.CLAIM_PROVISIONS_PER_SETTLER} food per settler to "
            f"provision them. It takes {expansion.CLAIM_BASE_TURNS} turns "
            f"plus {expansion.CLAIM_TURNS_PER_CELL:.2g} turns per cell "
            "(paid and started immediately; the fight only happens once "
            "that work is done)."
        ),
        (
            "Settlers come from whichever of your settlements and villages "
            "sit nearest the new land, and no one place gives up more than "
            f"{_pct(expansion.CLAIM_SETTLER_DRAW_FRACTION)} of its people "
            "to a single expedition — nor is any place ever emptied below "
            "the same floor a famine could push it to. They are working-age "
            "people, so expansion genuinely costs you hands in the fields "
            "back home. That is the real price of growing."
        ),
        (
            f"An amphibious claim — a shore region reachable only across "
            f"water, with no land border to territory you already hold — "
            f"costs far more: {expansion.SEA_ONLY_SETTLERS_BASE} settlers "
            f"plus {expansion.SEA_ONLY_SETTLERS_PER_CELL:.2g} per cell, and "
            f"its garrison is {_pct(expansion.SEA_ONLY_STRENGTH_MULT)} the "
            "size. A sea crossing needs more people and more supplies, and "
            "only a realm with people to spare can mount one — which is "
            "what stops both you and the AI from leapfrogging the map early."
        ),
        "SPOILS",
        (
            "Winning the fight seizes what the garrison was sitting on, "
            "not just the ground. Expect roughly "
            f"{expansion.CLAIM_SPOILS_YIELD_TURNS} turns' worth of "
            "whatever that region produces, delivered straight into its "
            "new villages, so rich land is worth more than a bog."
        ),
        (
            f"The Gold taken is {expansion.CLAIM_SPOILS_GOLD_BASE} from the "
            f"garrison's own strongbox plus "
            f"{expansion.CLAIM_SPOILS_GOLD_PER_STRENGTH:.2g} per point of "
            "garrison strength — a tough wildland was guarding something. "
            "Since a claim costs no Gold at all, every claim you win is "
            "pure coin gained. That is intentional: expansion is meant to "
            "be how a young realm generates money and gets its economy "
            "moving, rather than every kingdom simply starting with a heap "
            "of it."
        ),
        "ODDS",
        (
            "Your success chance compares your military rating against the "
            "garrison's, but a strength ADVANTAGE tells much harder than a "
            "straight ratio would — being twice as strong is worth far more "
            "than twice the odds. The practical effect is that wildland goes "
            "from a genuine gamble to a formality as you develop: an early, "
            "unarmed realm is around a coin-flip against a typical garrison, "
            "while an established one with the population and the Weapons and "
            "Shields to arm it wins upwards of 95% of the time. Wildland "
            "garrisons never grow — so the way to expand safely is to grow "
            "and equip first, not to throw a militia at it early."
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
            "Win: the region transfers, and gets settled fresh — at least "
            f"{expansion.WILDLAND_VILLAGE_MIN} Village, more wherever the "
            "land can actually support them, but NEVER a free City/Town/"
            "Castle; a real Settlement still has to be built there like "
            "any other (see Construction)."
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
        "STORAGE BUILDINGS (settlements and villages)",
        (
            "Each typed storage pool has its own building, and each one "
            "upgrades through tiers rather than being a single flat "
            "one-off — see Storage & Spoilage for what the pools are."
        ),
        "\n".join(_storage_building_lines()),
        (
            "Villages build all of these too, at roughly "
            f"{_pct(construction.VILLAGE_STORAGE_COST_MULT)} of the cost "
            f"and {_pct(construction.VILLAGE_STORAGE_TURNS_MULT)} of the "
            "time, but reach lower tiers than a settlement can."
        ),
        "HERD BUILDINGS (villages only)",
        (
            "Animals live where the fields are, so these are village-only "
            "— see Livestock & Herds for what they change."
        ),
        "\n".join(_herd_building_lines()),
    ]
    return "\n\n".join(parts)


def _storage_building_lines():
    """Cost/time/effect for every tier of every storage building, read from
    the live tables so this can't drift out of sync with the game."""
    out = []
    for pool in R.STORAGE_POOLS:
        building = R.STORAGE_BUILDING_BY_POOL[pool]
        costs = construction.STORAGE_BUILD_COSTS.get(building, [])
        turns = construction.STORAGE_BUILD_TURNS.get(building, [])
        # The Barn is village-only (it's a herd building too), so its tiers
        # and prices come from the village tables, not the settlement ones.
        village_only = building in R.HERD_BUILDINGS
        bonus = (R.VILLAGE_STORAGE_TIER_BONUS if village_only
                 else R.STORAGE_TIER_BONUS).get(building, [0])
        for tier in range(1, len(costs)):
            if costs[tier] is None or tier >= len(bonus):
                continue
            added = bonus[tier] - bonus[tier - 1]
            mult = construction.VILLAGE_STORAGE_COST_MULT if village_only else 1.0
            cost = ", ".join(f"{max(1, round(v * mult)):,} {k}"
                             for k, v in costs[tier].items())
            n_turns = turns[tier]
            if village_only:
                n_turns = max(1, round(n_turns * construction.VILLAGE_STORAGE_TURNS_MULT))
            out.append(f"  {building.title()} T{tier}: {cost} — {n_turns} turns, "
                       f"+{added:,} {pool} space"
                       + (" (village only)" if village_only else ""))
    building = R.PRESERVING_HOUSE
    costs = construction.STORAGE_BUILD_COSTS.get(building, [])
    turns = construction.STORAGE_BUILD_TURNS.get(building, [])
    for tier in range(1, len(costs)):
        if costs[tier] is None:
            continue
        cost = ", ".join(f"{v:,} {k}" for k, v in costs[tier].items())
        rate = int(R.CONVERSION_RATE_CAP * R.PRESERVING_CAP_MULT[tier])
        out.append(f"  Preserving House T{tier}: {cost} — {turns[tier]} turns, "
                   f"cures up to {rate:,}/turn")
    return out


def _herd_building_lines():
    effect_text = {
        ("pasture", "capacity"): "herd capacity x{v:g}",
        ("stable", "capacity"): "Horse capacity x{v:g}",
        ("barn", "feed"): "Winter fodder need x{v:g}",
        ("barn", "death"): "livestock deaths x{v:g}",
        ("slaughterhouse", "yield"): "Meat & Leather per head x{v:g}",
    }
    out = []
    for building in R.HERD_BUILDINGS:
        costs = construction.STORAGE_BUILD_COSTS.get(building, [])
        turns = construction.STORAGE_BUILD_TURNS.get(building, [])
        for tier in range(1, len(costs)):
            if costs[tier] is None:
                continue
            # Villages are the only builders, so quote the village price.
            cost = ", ".join(
                f"{max(1, round(v * construction.VILLAGE_STORAGE_COST_MULT)):,} {k}"
                for k, v in costs[tier].items())
            effects = "; ".join(
                effect_text[(building, eff)].format(v=table[tier])
                for eff, table in R.HERD_BUILDING_EFFECTS.get(building, {}).items()
                if (building, eff) in effect_text and tier < len(table))
            village_turns = max(1, round(turns[tier] * construction.VILLAGE_STORAGE_TURNS_MULT))
            out.append(f"  {building.title()} T{tier}: {cost} — "
                       f"{village_turns} turns, {effects}")
    return out


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
            "interchangeably). Meeting it raises the prosperity target by "
            f"up to +{R.LUXURY_PROSPERITY_BONUS:.0%} at full "
            "fulfillment; going without is simply a non-event, never a "
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
        "STAYING SCARCE",
        (
            "Deliberately hard to get much of early on: no Luxury Good "
            "converts from its raw input at all before turn "
            f"{R.LUXURY_CONVERSION_MIN_TURN} (a full year), and even after "
            f"that the conversion rate is capped at only "
            f"{R.LUXURY_CONVERSION_RATE_CAP} units/turn per settlement — "
            "deliberately below a typical settlement's own Luxury need, so "
            "a stockpile builds up slowly and stays genuinely scarce for a "
            "long while rather than quietly catching up to \"enough for "
            "everyone\" within the first year. Every other processed good "
            f"converts at up to {R.CONVERSION_RATE_CAP} units/turn by "
            "comparison."
        ),
    ]
    return "\n\n".join(parts)


def _livestock_article():
    R_ = R
    feed_rows = [f"  {a}: {v:g} Fodder per head" for a, v in
                 sorted(R_.FODDER_PER_HEAD_WINTER.items(), key=lambda kv: -kv[1])
                 if v]
    parts = [
        "Livestock & Herds",
        (
            "Animals are not a stockpiled resource. Each Village keeps a "
            "living herd — real head counts that breed, die, get eaten and "
            "can be traded — and no herd occupies any storage space at all. "
            "What a herd needs is Fodder, and somewhere to shelter."
        ),
        "THE HERD YEAR",
        (
            "Herds run on the season rather than being recalculated from "
            "nothing each turn:"
        ),
        "\n".join([
            "  Spring — births",
            "  Summer — the Fodder harvest is cut and stored",
            "  Autumn — the cull: animals slaughtered for Meat and Leather",
            "  Winter — the herd eats stored Fodder to survive",
        ]),
        (
            "Milk, Wool, Eggs and Honey come off the living herd every "
            "season. Meat and Leather come only from animals actually "
            "slaughtered."
        ),
        "FODDER AND THE WINTER",
        (
            "Fodder is a Crop like any other — it grows on plains, it is "
            "harvested, and it competes with food crops for the same land. "
            "It is also the bulkiest thing a village stores, and it lives in "
            "its own pool: the Barn."
        ),
        "\n".join(feed_rows),
        (
            "A village that cannot feed its herd through Winter culls it "
            "down to what the hay covers — you still get Meat and Leather "
            "from most of those animals — and loses the remainder outright. "
            "This is the decision the whole system turns on: lay in enough "
            "hay, or take the herd's value now while it still has any."
        ),
        "CULL POLICY",
        (
            "Every village has a policy setting how hard it harvests each "
            "Autumn, multiplying each animal's own slaughter rate:"
        ),
        "\n".join(f"  {name}: x{mult:g}" + (
            "  (bank animals for future years, bigger winter feed bill)"
            if name == "Grow" else
            "  (maximum meat now, a smaller and cheaper herd through Winter)"
            if name == "Cull" else "  (the default)")
            for name, mult in R_.HERD_POLICY_MULTIPLIER.items()),
        "BUILDINGS",
        (
            "Four village buildings shape what a herd can do — Pasture "
            "(more head), Barn (less winter fodder needed, fewer deaths, and "
            "the hay store itself), Stable (more Horses) and Slaughterhouse "
            "(more Meat and Leather per animal taken). See Construction for "
            "costs."
        ),
        "HORSES",
        (
            "Horses are the one animal with a use beyond food. They add a "
            "cavalry bonus to military strength — worth up to "
            f"+{_pct(R_.CAVALRY_BONUS)} if you can mount every armed "
            "soldier — and a realm holding at least "
            f"{commander.MOUNTED_COMMANDER_HORSES} horses puts its "
            "Commanders in the saddle, raising overland speed from "
            f"{commander.COMMANDER_CELLS_PER_TURN} to "
            f"{round(commander.COMMANDER_CELLS_PER_TURN * commander.MOUNTED_SPEED_MULT)} "
            "cells a turn. Unlike Weapons and Shields, you cannot smith a "
            "horse: it has to be bred, fed through Winter, and not culled."
        ),
        "TRADING ANIMALS",
        (
            "Livestock can be bought and sold like any other good, in head "
            "rather than bulk. A realm only ever sells what is above its "
            f"breeding core ({_pct(1 - trade.LIVESTOCK_BREEDING_RESERVE)} of "
            "the herd at most), and demand is judged against what a buyer's "
            "LAND can carry — so the realm that wants animals is the one "
            "with empty pasture, usually because a hard Winter just took its "
            "herd. Imported animals go straight to whichever of the buyer's "
            "villages has room for them."
        ),
    ]
    return "\n\n".join(parts)


def _military_article():
    sp = ", ".join(f"{name} {spec.get('mil', 0):+d}%" for name, spec in
                   sorted(SPECIES.items(), key=lambda kv: -kv[1].get("mil", 0)))
    parts = [
        "Military & Combat",
        "MILITARY RATING",
        (
            "How many people you can put in the field and arm — not how much "
            "land you own. Recomputed every turn from three things you build "
            "up yourself: population, Weapons, Shields."
        ),
        "\n".join([
            f"  Your levy is {_pct(R.MOBILIZATION_RATE)} of the ADULT "
            "population across every settlement AND village you hold. The "
            "rest are busy farming, mining and hauling.",
            "  Weapons arm that levy one for one. A soldier you have no "
            "weapon for still marches, but as militia — worth only "
            f"{_pct(R.MILITIA_WEIGHT)} of an armed soldier.",
            f"  Shields add up to +{_pct(R.SHIELD_BONUS)}, scaled by how much "
            "of your ARMED strength they cover.",
            f"  Horses add up to +{_pct(R.CAVALRY_BONUS)} the same way — "
            "cavalry, scaled by how many of your armed soldiers you can "
            "actually mount (see Livestock & Herds).",
            f"  Then a per-species modifier: {sp}.",
        ]),
        (
            "Horses are the one military input you cannot smith. Weapons and "
            "Shields come out of a forge with ore you already hold; a horse "
            "has to be bred, fed through Winter and not culled — which makes "
            "a Stable, the Grow herd policy and a full hay Barn all read "
            "straight through into your army's strength."
        ),
        (
            "Two consequences worth planning around. Weapons and Shields "
            "beyond what your levy can carry are wasted — arming 400 soldiers "
            "takes 400 Weapons and no more, so population is the ceiling on "
            "everything. And a realm that never builds a Weaponsmith or "
            "Shieldwright stays weak no matter how large it grows, because a "
            "militia mob is a fraction of an equipped army."
        ),
        "SPECIES TRAITS",
        (
            "Military rating above is the STRATEGIC layer — how big an army a "
            "faction can field. On top of that, every species fights "
            "differently soldier-for-soldier. These stack, and each species "
            "pays for its strength somewhere:"
        ),
        "\n".join(
            f"  {name}: " + ("; ".join(species_trait_summary(name)) or "no modifiers")
            for name in SPECIES
        ),
        (
            "Three species field no Cavalry at all, and each puts that share "
            "somewhere different — same headcount, very different army. Orcs "
            "turn it into extra Swordsmen (a heavier foot line, no charge). "
            "Elves turn all of it into Archers. Goblins split it evenly "
            "between Swordsmen and Archers."
        ),
        (
            "These are about as evenly matched as they have ever been. Two "
            "forces pull against each other and roughly cancel: Archers reach "
            "a long way, so crossing open ground is costly, but a Cavalry "
            "charge that does connect is devastating. No species is a clearly "
            "wrong pick — choose on flavour and on the strategic bonuses."
        ),
        "ARMY COMPOSITION",
        (
            "A battle army is built straight from military rating: "
            "roughly 40% Swordsmen, 25% Archer, 20% Cavalry by headcount "
            "(the remainder isn't separately represented). All three "
            "unit types:"
        ),
        "\n".join([
            "  Swordsmen: melee, high HP, sword+shield. Their shield has "
            "a chance to BLOCK an incoming hit outright (no damage) — but "
            "only a blow coming from their front; a strike from the flank "
            "or rear always lands. Facing a soldier is toward whatever "
            "they're fighting, so surrounding an enemy turns off their "
            "shield.",
            "  Cavalry:  mounted, far and away the fastest thing on the "
            "field, and built entirely around the charge. Galloping toward "
            "a target builds momentum, and the couched impact lands for "
            "several times their base damage — AND ploughs into everyone "
            "around whoever they hit, splashing a share of that damage "
            "across the whole knot of soldiers. A charge into a packed "
            "frontline is the single biggest thing that happens in a "
            "battle. The splash scales with momentum, so a rider who "
            "trotted into contact barely jostles anyone; only a real "
            "gallop scatters a line. Shields and dodges still work against "
            "it. That momentum is spent on impact and can't rebuild while "
            "they're stuck in a melee, so a bogged-down rider fights "
            "softer than a swordsman. Hit hard, pull back, charge again.",
            "  Archer:   ranged (180-cell range vs. ~12-14 melee), fires "
            "arrows, 80% accuracy — a miss still spends the attack, it "
            "just deals no damage. (A shield can still block an arrow that "
            "comes at a swordsman head-on.)",
        ]),
        "SIGNATURE UNITS",
        (
            "On top of those three, every species fields at least one unit "
            "nobody else has, paid for out of its own Swordsmen and Archers "
            "plus a small bonus — so a signature unit is an advantage, not "
            "simply a reshuffle. They are few in number and specialised; "
            "none of them is a better Swordsman."
        ),
        "\n".join([
            "  Standard Bearer (Humans): carries the colours rather than the "
            "fight — mediocre with a sword, but every soldier near one hits "
            "harder, swings faster and holds a steadier shield. Humans' whole "
            "identity is that the line is worth more than the soldiers in it, "
            "and this is that in rank and file rather than concentrated in "
            "one commander who can die. Standing near two banners is worth "
            "exactly as much as standing near one: they spread the effect "
            "across the field, they do not stack it.",
            "  Bladesinger (Elves): the melee answer an all-archer line has "
            "never had. Fast, lightly armed and hard to pin down — the only "
            "elf on the field who can dodge a blow outright — but frail "
            "enough that anything landing a hit is most of the way to "
            "killing one. Paid for entirely out of the bows, so fielding "
            "them is a real trade.",
            "  Shieldwarden (Dwarves): an anchor, not a duellist. Enormous, "
            "slow, heavily shielded, and the line around one takes visibly "
            "less punishment while it advances. Dwarves are the one species "
            "that crosses open ground under fire with its shields still up; "
            "the Warden is what makes that crossing pay.",
            "  Berserker (Orcs): no shield at all, and damage that climbs as "
            "it bleeds — the only unit in the game more dangerous hurt than "
            "whole. Leaving one wounded on the field is a decision, not "
            "tidying-up.",
            "  Assassin (Goblins): a counter-archer with twin daggers, "
            "fastest thing on foot, and it ignores everything but enemy "
            "bowmen while any still live. Its opening strike on each new "
            "victim lands for several times its damage. Fragile to the point "
            "of absurdity — caught in the open by anything that hits back, "
            "it dies at once.",
            "  Sapper (Goblins): crude bombs at middling range. Slow to "
            "reload and unreliable, but the blast catches everyone packed "
            "around whoever it lands on, which makes a tight shield wall the "
            "worst possible formation to face one in.",
        ]),
        "TARGETING",
        (
            "Units still overwhelmingly go for whoever's closest, but with "
            "a little judgment: they lean toward finishing off the wounded, "
            "avoid every soldier piling onto the same target, and cavalry "
            "favor exposed archers (ideal charge targets). They re-check "
            "their target periodically rather than tunnel-visioning on one "
            "enemy to the exclusion of a closer threat."
        ),
        "PLANNING PHASE & FORMATIONS",
        (
            "Before the fight you position your own army (a strict midline "
            "gap keeps you out of the enemy's half):"
        ),
        "\n".join([
            "  - Left-drag a unit to move it; left-drag empty ground to "
            "box-select several.",
            "  - Keys 1 / 2 / 3 (or the panel buttons) select all your "
            "Swordsmen / Cavalry / Archers at once.",
            "  - With a selection, RIGHT-drag a line to form them up along "
            "it — ghost rally-flags preview each soldier's spot, and they "
            "snap into ranks when you release.",
            "  - Space (or \"Deploy Army\") ends planning and starts the "
            "fight.",
        ]),
        "FIGHTING A BATTLE",
        (
            "Combat is real-time and automatic once started — units path "
            "to a chosen enemy and attack in range. A battle ends the "
            "instant only one side has anyone left standing (or a true "
            "stalemate if both sides are wiped at once)."
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
        "THE MAP WRAPS",
        (
            "The world is a cylinder, not a flat rectangle: the map's "
            "east and west edges are the same place. Scroll the camera "
            "far enough in either direction and it keeps going, showing "
            "the opposite side continuing seamlessly — and it's not just "
            "cosmetic. A Commander or ship ordered toward the edge will "
            "actually walk/sail through it and appear on the other side "
            "if that's genuinely the shorter route, the same way a "
            "domestic shipment, a foreign trade route, or plain vision "
            "will. The map's north and south edges are real edges, "
            "though — only east-west wraps, not top-to-bottom. Landmasses "
            "themselves never straddle the wrap seam — it's reliably open "
            "ocean there, the same way any other stretch of open sea "
            "works for sailing between continents."
        ),
    ]
    return "\n\n".join(parts)


ARTICLES = {
    "overview": ("Overview", _overview_article()),
    "settlements": ("Settlements & Villages", _settlements_article()),
    "storage": ("Storage & Spoilage", _storage_article()),
    "livestock_herds": ("Livestock & Herds", _livestock_article()),
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
    ("livestock_herds", "Livestock & Herds", "article"),
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
