"""What's-new data + "have I shown this yet" persistence.

Entries are hand-written, newest first, each tagged with an integer
CHANGELOG_VERSION that gets bumped whenever a new entry is added. A tiny
local file next to saves/ (see app.core.save._app_root, same reasoning:
survives a PyInstaller --onefile temp-dir launch) remembers the highest
version the player has actually seen, so the popup only appears once per
update rather than on every single launch.
"""
import json

from app.core.save import _app_root

_SEEN_PATH = _app_root() / "changelog_seen.json"

# Each entry: {"version": int, "title": str, "items": [str, ...]}.
# Bump CHANGELOG_VERSION and add a new entry at the top whenever a
# noteworthy batch of changes ships. Patch-notes style: terse, dashed,
# what-changed-and-by-how-much -- not a prose explanation of the mechanic
# (that's what the in-game Compendium, F1, is for).
CHANGELOG_ENTRIES = [
    {
        "version": 40,
        "title": "A World You Can Turn",
        "items": [
            "THE MAP IS A PLANET. Press Globe and your world wraps onto a sphere you can spin freely in any direction, roll over the poles, and fly down to. It is the same map, not a second copy — anything that changes on the flat map is already there",
            "Everything the flat map draws is on it: roads, trade routes, caravans in transit, realm and region and settlement names, alert badges, fog of war. Click a region on the globe and it selects exactly as it would flat",
            "FLYING CLOSER IS ZOOMING IN. Realms and trunk roads from orbit, region names lower down, individual villages and dirt tracks near the ground — there is no view to switch into, you just descend",
            "Terrain keeps its shape all the way to the ice caps. The obvious way to wrap a map on a globe smears everything toward the poles; this one is conformal, so a forest is the same forest at any latitude",
            "A day/night terminator crosses the world as the years pass, kept light enough to read borders and roads straight through",
            "Your camera and which view you prefer are remembered in the save",
            "END TURN NOW MOVES THINGS. Caravans, shipments, ships and commanders travel along their actual route over about three quarters of a second instead of blinking from one cell to the next. A trade network finally looks like one",
            "EVERY SPECIES HAS A UNIT NOBODY ELSE DOES, paid for out of its own soldiers plus a small bonus, so it is an advantage rather than a reshuffle",
            "HUMANS — Standard Bearer: mediocre with a sword, but everyone near one hits harder, swings faster and holds a steadier shield. Two banners are worth no more than one; they spread the effect, they do not stack it",
            "ELVES — Bladesinger: the melee answer an all-archer line never had. Fast, evasive, and frail enough that anything landing a hit nearly kills it. Paid for entirely out of the bows",
            "DWARVES — Shieldwarden: an anchor. The line around one takes visibly less punishment while it advances, which is what finally makes the dwarven walk across open ground pay",
            "ORCS — Berserker: no shield at all, and damage that climbs as it bleeds. The only unit in the game more dangerous hurt than whole",
            "GOBLINS — Sapper: crude bombs at middling range. The blast catches everyone packed around whoever it lands on, so a tight shield wall is the worst thing to face one in. It does from a distance what the Assassin could never survive long enough to do",
            "The battle AI now gives these units orders too — it only ever recognised Swordsmen, Archers and Cavalry by name, so anything new stood there unordered",
            "The Compendium (F1) describes every one of them under Military & Combat",
            "NOTE: SPECIES BALANCE IS IN FLUX. The new units measurably move win rates and are not yet settled — the Shieldwarden is worth about +17 points to Dwarves, while the Elf and Goblin units currently cost their own side. Expect these numbers to move again",
        ],
    },
    {
        "version": 39,
        "title": "Drawn by the Graphics Card",
        "items": [
            "Battles are now rendered on the GPU. The whole battlefield — every soldier, every weapon, every arrow — is drawn in a single instanced call instead of thousands of individual canvas items",
            "EVERY SOLDIER KEEPS ITS KIT. Swords, shields and daggers used to switch off past 160 living units because the glyphs alone cost most of a frame; there is no cutoff any more, at any army size",
            "Measured on a real battle: 15 fps to 141 fps at ~590 living units, with full equipment drawn the whole time",
            "Battle simulation is 4-6x faster. Target selection scanned every enemy for every unit, which is quadratic — quadrupling an army raised its cost about twentyfold. It now scores the whole enemy army in one vectorised pass",
            "Armies of ~5,000 are playable where ~1,000 used to be the practical ceiling",
            "Machines without a working GPU context fall back to the old canvas renderer automatically, including mid-session, so nothing stops working",
            "END TURN IS 2.8x FASTER on a large realm (1,199ms to 424ms at 300 regions). Storage-class and bulk lookups are memoised, region adjacency is computed once instead of every call, and the expansion AI no longer rescans a faction's whole territory once per frontier region",
            "That optimisation is verified identical, not just faster: ownership, stocks, population and faction stats were hashed across ten turns and match exactly",
            "NOTE: battle outcomes shift slightly. Target selection now reads positions from the start of each tick rather than partway through it — the same way the anti-dogpile count already worked — so targeting is internally consistent for the first time",
        ],
    },
    {
        "version": 38,
        "title": "Battlefield Orders",
        "items": [
            "You can now give orders DURING a battle, not just before it. Select troops (drag a box, or 1/2/3/4) and command them; Space pauses the fight so you can look at the field and give several at once",
            "HOLD HERE — stand your ground braced. A braced line takes only 42% of a cavalry charge's impact and its splash, which makes it the clearest counter in the game to being ridden down",
            "CHARGE — +30% speed and +15% damage, but your guard drops: you cannot run at someone and shield properly",
            "SHIELD WALL (Swordsmen) — dresses a real line facing the enemy, shields up. The bonus only counts CONTIGUOUS neighbours, so a wall that gets broken up stops protecting, and since shields only ever block frontally, walking around a wall still beats it",
            "CHARGE & REGROUP (Cavalry) — riders hit, pull out instead of bogging down, then pick the thickest enemy formation on the field and come again",
            "HOLD FIRE / FIRE AT WILL (Archers) — holding draws a volley worth up to +150% on release. It only builds while a target is actually in range, so it costs you shots rather than being a free opening",
            "Enemy armies use the same orders you do — they brace against your cavalry, cycle their own horse, and time their volleys",
            "DWARVES charge with shields raised. Everyone else drops their guard to run; a dwarven line does not, and you can see arrows visibly glance off it as it comes on",
            "GOBLINS get the ASSASSIN: twin daggers, fastest thing on foot, and it hunts ARCHERS specifically — it will run past a shield line and refuses to touch swordsmen until the last enemy archer on the field is dead. Its opening blow on each victim hits for 3.5x",
            "Goblin dodge partly restored (0.15 to 0.17) after the last cut proved far too harsh, and they swing a little faster. Assassins are slipperier still at 0.22",
            "Elves' attack speed reduced — an all-archer roster that never has to close was winning 92% of its matchups",
            "FIXED: commanders were being shoved around the battlefield by the crowd and pinned against walls. Collisions now account for mass (a commander weighs nine soldiers), and he holds behind his own line instead of walking into the enemy, which is what the game always claimed he did",
            "FIXED: battles were not reproducible — the collision solver ordered units by memory address, so the same fight could resolve differently each run",
        ],
    },
    {
        "version": 37,
        "title": "Lines Stand and Fight",
        "items": [
            "Melee no longer degenerates into two lines shoving each other around the field. The collision impulse was driven by overlap alone, and a packed melee overlaps every single tick, so the pushing never stopped",
            "Knockback now applies only while a unit is still closing: a charge hitting a line lands with full force, but once soldiers are locked in and trading blows they hold their ground",
            "Fights resolve about 26% faster as a result (58.5s to 44.2s across eight test battles) — units spend the fight killing each other rather than being pushed apart",
            "Commanders are drawn as an oversized disc with a contrasting centre instead of a spiked star inside a halo ring; the ring sat outside the body and mostly read as clutter once a melee closed around him",
            "FIXED: enemy commanders were visible through fog of war — on a test save 12 of 13 rivals could be seen marching across ground the player had never explored. Their queued-path preview leaked their destination too, and is now hidden the same way",
            "Rival commanders are drawn in their own realm's colour, so a marker tells you whose army it is at a glance. Your own keeps its distinct orchid",
        ],
    },
    {
        "version": 36,
        "title": "Commanders Lead Armies — and Claiming Land Pays For Itself",
        "items": [
            "COMMANDERS: your army is tied to your commander. You cannot attack a rival or claim wildland unless your commander is standing in one of your regions bordering the target — no more armies materialising anywhere on the map",
            "The panel tells you exactly why an attack is refused and where to march to fix it, rather than silently offering no targets",
            "Every faction has one, AI included, and the AI now marches its commander toward what it intends to take",
            "Commanders are real units on the battlefield now, not just vision: a large 8-pointed star, far tougher than a line soldier, and they project an aura that buffs every friendly unit around them",
            "Each species fields its own commander with its own profile — Human Marshal (all-round buff), Elven Warden (ranged, extends your archers' reach), Dwarven Thane (enormous HP, soaks damage for the line), Orcish Warchief (heaviest hitter, cleaves through groups), Goblin Chieftain (fast, evasive)",
            "Losing your commander in battle breaks your army's morale on the spot — damage and speed both drop for the rest of the fight",
            "A fallen commander is really gone: the realm cannot attack or claim at all until a successor takes the field 12 turns later at your capital",
            "Species commanders were tuned across a full battle tournament — win-rate spread between species narrowed from about 45 points to about 17",

            "Claiming wildland is no longer a pure Gold check. A claim is an expedition: it now costs 25 Gold, 30 Logs and 12 Stone plus a small per-cell rate, so most of the bill is the timber and stone the crew actually consumes",
            "Gold for a typical region drops from about 199 to 44 — instrumenting the expansion AI showed 90% of its attempts failing on affordability alone, against 0.2% blocked by anything else",
            "NEW: winning the fight now seizes SPOILS. You take roughly 10 turns of whatever that region produces, delivered straight into its new villages, so rich land is worth more than a bog",
            "Spoils Gold is 1.8x what you paid, plus a bounty per point of garrison strength — so a land claim you win returns MORE Gold than it cost. Measured across all 400 wildland regions on a test map: every one is net-positive, median +54 Gold",
            "This is meant to be how a young realm generates coin and gets its economy moving, instead of every kingdom simply starting with a heap of it. The margin per claim is small and compounds over a campaign",
            "Amphibious claims are deliberately excluded from the profit — spoils are pinned to the land price, so crossing the sea still runs about 222 Gold in the red and stays a real commitment rather than a way to farm coin",
            "The claim panel now previews the spoils and the net Gold before you commit, and the post-battle message reports what was seized",
            "On a late-game test map, factions able to afford a frontier claim went from 2 of 14 to 8 of 14",
            "Every region now scrapes together a trickle of Logs and Stone regardless of biome, so a desert or steppe realm can still slowly fund its way outward instead of being sealed in by geography — 64% of regions were producing no Stone at all, which is why cutting the price hadn't helped them",
            "It's a floor, not a bonus: a region with real forest or a quarry is far above it and gains nothing, so it can't re-inflate the timber hoards that storage throttling exists to contain",
        ],
    },
    {
        "version": 35,
        "title": "In-Game Treasury, and a Bad Fix Undone",
        "items": [
            "The Treasury is now an in-game panel instead of a separate window — it stays inside the game, keeps its place while you pan and zoom, and can be dragged anywhere (but never off the edge)",
            "Leave it open across End Turn and it updates in step with the turn, which is the only way to actually watch minting, trade income and construction spend land",
            "Click the Gold row to toggle it open or closed",
            "IMPORTANT FIX: v0.2.1's legacy-save cleanup was destroying goods, and measured WORSE than doing nothing at all — over 100 turns it cost 5,198 population against 4,737 for leaving the save alone, plus 942 gold the realm would have minted from ore in that pile",
            "The cleanup now only MOVES goods into real spare capacity (settlements first, since only they run conversion recipes) and destroys nothing. Population loss over 100 turns: 1,197, against 4,737 untouched and 5,198 under v0.2.1",
            "Anything that still cannot be rehoused stays where it is and drains through the ordinary overflow rule, so it can be eaten and converted on the way down rather than deleted",
            "Saves that already went through v0.2.1's cleanup are eligible for the corrected pass — what it destroyed is gone, but any overflow still sitting there now gets rehoused instead of ignored",
        ],
    },
    {
        "version": 34,
        "title": "Towns & Cities Get the New Panel",
        "items": [
            "Town and City panels now use the same folding cards as Villages — Summary, Build, Industry, Storage, Held — instead of the old wall of text",
            "New INDUSTRY card shows what a settlement is actually converting right now and at what rate, so 'why is my city sitting on Wheat with no Bread?' has an answer on screen",
            "The Shipyard moved into the Build card alongside everything else you can build there",
            "Storage shows the four typed pools as meters, replacing an aggregate total that stopped meaning anything once space became typed",
            "FIXED: worlds saved before storage was typed carried enormous stockpiles from the old shared pool — one city held 1.47 million space against a 3,300 capacity. Those nodes were throttled to zero production for ~80 turns while it drained",
            "On first load, that legacy overflow is now spilled into whatever spare capacity the realm actually has, and only what nothing can hold is discarded. Measured on a real save: population loss over 60 turns fell from -4,731 to -1,960, starving settlements from 196 to 128, and storage alerts from 405 to 55",
            "Normal overflow is deliberately left alone — a settled realm running a few percent over on timber is the overflow rule working, not damage",
        ],
    },
    {
        "version": 33,
        "title": "Interface Overhaul, Herds & Honest Numbers",
        "items": [
            "INTERFACE: the map is now the base layer and fills the window — both side panels fold away to slim edge tabs, so you can give the map the whole screen whenever you want it",
            "Alerts are grouped by kind with a count instead of eight near-identical paragraphs covering the map — click a group to list the settlements, click a settlement to jump there. 150 alerts now read as 3 lines instead of hiding 142 of them behind '+142 more'",
            "The resources sidebar groups into Food / Industry / Luxury with a NEEDS ATTENTION block that surfaces survival goods running low — 30 flat rows are now 4 lines that expand on click",
            "Settlement and village panels are folding cards (Summary / Build / Production / Storage / Herd) with aligned figures and real meters, replacing ~30 lines of run-on prose. End Turn is pinned so build actions can never fall off the bottom",
            "The Trade Log is a tab you open rather than an empty black box permanently sitting on the map",
            "LIVESTOCK: herds now belong to Villages, not regions, and run on the season — births in Spring, hay cut in Summer, the cull in Autumn, and Winter fed from stored Fodder",
            "Fodder is a new Crop with its own Barn storage. A village that can't feed its herd through Winter loses it, so laying in hay is a real decision",
            "Herd policy per village (Grow / Balanced / Cull) sets how hard you harvest each Autumn, and four new village buildings — Pasture, Barn, Stable, Slaughterhouse — set the ceiling",
            "Horses finally matter: they add a cavalry bonus to military strength, and a realm with enough of them puts its Commanders on horseback (5 → 8 cells a turn)",
            "Livestock can be traded — buy breeding stock from a neighbour to restock a herd a hard Winter took",
            "Meat no longer arrives once a year and rots in six turns; it comes four times a year, and a Preserving House cures it into Salted Meat",
            "STORAGE: space is typed — Granary (food, firewood), Warehouse (timber, ore, goods), Vault (gold, luxuries), Barn (fodder) — each with its own building and upgrade tiers",
            "Goods take up space by bulk now: a Log eats 3x what a sack of grain does, and Gems almost nothing",
            "Production stops when there's nowhere to put it, instead of being silently destroyed on arrival. Storage overflow waste is down about three quarters",
            "GOLD: a new Treasury panel (click the Gold row) shows where your gold is, how much is actually spendable, how much is riding home on a caravan, and where every coin came from",
            "The trade log marks rows where no coin moved, so an internal barter transfer stops reading as income you never received",
            "Fixed: conquering a region banked a phantom copy of its goods in a national pool nothing could spend from — the resources sidebar was overstating what you owned",
            "Conquering a nation's last region now removes it from the world properly, and losing your own last region ends the game",
        ],
    },
    {
        "version": 32,
        "title": "Global Trade Goes Gold-Only",
        "items": [
            "Foreign trades between two different factions now pay in Gold alone -- never barter, never substitute goods for what the agreed price should be in coin",
            "If your paying settlement can't fully cover the deal in Gold, only Gold actually paid is recorded -- the seller's paid event reads the real money that arrived, not the agreed round number",
            "The AI now sizes foreign deals against a buyer's spendable Gold only, so a deal completes on Gold alone or doesn't happen at all (no last-minute barter-surprise)",
            "Regional Markets (your own settlements trading inside your realm) still mix Gold and barter exactly as before -- this is a global-trade rule, not a regional one",
            "Factions whose realm has no Mountain land -- so no Gold Ore, so no Gold source -- now struggle to import via foreign trade. Outside threats are still swords; the economy at least now matches how real money used to work",
        ],
    },
    {
        "version": 31,
        "title": "Trade Log: Numbers Match Reality",
        "items": [
            "The Trade Log's -/+ now shows what your settlement actually moved (Gold and/or barter), not the agreed price",
            "These could differ whenever a buyer's spending was capped by the gold reserve, or a deal settled partly in barter",
            "Buyer rows tag every payment item with its sign, so a buyer paying partly in barter no longer reads as '-100g + 50 Iron': every item really did leave your treasury",
            "Same fix on the seller's + for the matching payment, including the Humans trade bonus on the way home",
        ],
    },
    {
        "version": 30,
        "title": "Species Balance Tightened",
        "items": [
            "Goblins' attack-speed bonus dialled back from ~12% to ~3% -- at 12% they were beating every other species handily; their 18% dodge is unchanged",
            "That single change brings the whole roster to its closest matchup spread yet -- no species is now a clearly wrong pick",
        ],
    },
    {
        "version": 29,
        "title": "Longer Bows, Tougher Orcs, Cleaner Map",
        "items": [
            "Archers now shoot twice as far -- armies pay a real price for crossing open ground, and Cavalry pays the most",
            "Orcs get a big compensating buff: +15% HP and +20% movement speed, so the one army with no Cavalry and the fewest Archers can actually close the distance",
            "Cavalry rebuilt around the charge: much faster (speed 72 to 110), a full-momentum couched hit now lands for 3.5x its base damage, and momentum rebuilds quicker so a rider who pulls back and comes again is dangerous sooner",
            "Charges now hit a WHOLE FRONTLINE, not one soldier -- the impact splashes damage into everyone around whoever they struck, scaled by how hard they were galloping. Slamming a packed line is now the single biggest thing that happens in a battle, with a shockwave to match",
            "Bogged-down riders still fight softer than a swordsman, and shields and dodges still work against the splash -- charge, pull back, charge again",
            "Domestic trade shipments are no longer drawn on the map -- foreign caravans still show",
            "Region names no longer clutter the realm view; the region panel still names them",
            "Goblins are harder to pin down: dodge raised to 18% and they now swing ~12% faster",
            "Orcs get a bit more meat on them: troop HP up from +15% to +22%",
            "Balance: species are much closer than they were -- Humans, Dwarves, Orcs and Elves now land within a few points of each other. Goblins are the current outlier on top",
        ],
    },
    {
        "version": 28,
        "title": "Armies Are Made of People Now",
        "items": [
            "Military strength is now how many people you can arm: 8% of your adult population across every settlement and village, armed one-for-one by your Weapons, with Shields adding up to +25%",
            "It no longer rewards owning empty land -- the old formula was mostly territory and Iron, and its Iron term maxed out almost immediately, so your rating barely moved all game",
            "Unarmed levies still march but count for far less, so a Weaponsmith and Shieldwright are now worth real strength",
            "Armies on the battlefield scale with that rating, so a developed realm fields hundreds of soldiers instead of a few dozen",
            "Taking wildland now goes from a real gamble early to near-certain once you're established -- garrisons never grow, so build up and equip first",
            "Battles with very large armies drop the per-soldier sword/shield glyphs to stay smooth",
            "Elves now field no Cavalry -- their whole mounted share becomes Archers",
            "Goblins now field no Cavalry either -- theirs splits evenly into Swordsmen and Archers",
            "Heads up: with three species now fielding no Cavalry, the matchups are NOT evenly balanced -- archer-heavy rosters (Elves, Goblins) currently win more than the rest. See the Compendium",
        ],
    },
    {
        "version": 27,
        "title": "Trade Log: Global Tab Fixed",
        "items": [
            "The Trade Log's Global tab showed a blank panel even when your foreign trades were being recorded -- switching from the busy Domestic tab left the list scrolled far past the handful of foreign entries",
            "Your foreign trade was being logged correctly the whole time; it was just scrolled out of sight",
            "Same fix applies the other way round, and the 'No trades yet.' placeholder is now actually visible when a tab really is empty",
        ],
    },
    {
        "version": 26,
        "title": "Trade Follows the Roads",
        "items": [
            "Goods now travel on your road network instead of trailing across open wilderness -- roads were decoration for trade until now",
            "Same-region shipments follow a real route over the ground; they used to be drawn as a dead-straight line whatever was in the way",
            "Foreign caravans and cross-region shipments hug the roads too, and cross rivers at the bridges the roads already use",
            "Hauling along a road is 1.6x faster than open country, so a road built for any reason speeds up every shipment that can use it",
        ],
    },
    {
        "version": 25,
        "title": "River Trade",
        "items": [
            "Rivers are now trade routes, not just scenery -- any settlement, town, castle or village within 3 cells of one can ship goods by boat",
            "Two of your own settlements on the same river trade in a single turn instead of three -- river frontage is now worth settling for",
            "Foreign trade routes follow river corridors where the water runs the right way, opening instantly (nothing to build) and reaching inland cities no coast touches",
            "Route preference is now river, then land, then sea",
            "Domestic shipments are drawn on the map for the first time -- previously only foreign caravans were visible, so most of the trade actually happening was invisible",
            "River boats have their own look, distinct from overland wagons and sea ships",
        ],
    },
    {
        "version": 24,
        "title": "Tell Your Caravans Apart",
        "items": [
            "Your own trade caravans now stand out; other nations' caravans crossing your view are drawn small and muted instead of looking identical to yours",
            "Same for the glowing route highlight -- only your own active trade routes light up brightly",
        ],
    },
    {
        "version": 23,
        "title": "Species Now Fight Differently",
        "items": [
            "Every species now has real battlefield traits, each with a matching weakness -- pick one and it genuinely changes how your armies play",
            "Humans: +25% shield block and +15% Gold from foreign sales -- disciplined traders",
            "Dwarves: +20% troop HP, but they march and swing slower",
            "Elves: +15% attack and movement speed, but lighter armour (-10% HP)",
            "Orcs: +18% damage and visibly bigger Swordsmen, but no Cavalry at all and far less use of a shield",
            "Goblins: +15% movement speed and a 15% chance to dodge any hit outright, but frail (-15% HP)",
            "The New Game screen now spells out what each species does before you commit",
        ],
    },
    {
        "version": 22,
        "title": "Foreign Trade & Diplomacy Come Alive",
        "items": [
            "Factions now discover each other once they're near enough neighbors, instead of only when their borders literally touch -- which almost never happened, leaving foreign trade and diplomacy dormant",
            "As a result foreign trade actually happens now: the Trade Log's Global tab fills in, and trade routes, alliances, and rivalries form between neighboring realms",
        ],
    },
    {
        "version": 21,
        "title": "Storage & Economy Rebalance",
        "items": [
            "Raw materials no longer flood storage to the brim from turn one -- structural wood (Logs/Hardwood/Softwood/Resin) cut to about a quarter, mining (Sand/Salt/Gems/Stone/ore) cut further; storage now fills gradually and is a real management decision",
            "Firewood is no longer wildly overproduced -- it was piling up ~128x faster than it's ever burned; cut hard so it doesn't clog storage",
            "Winter is still safe: forest-poor regions now scrounge more of their own firewood, so the lower production doesn't cause new freezing (verified across many game-years)",
        ],
    },
    {
        "version": 20,
        "title": "Much Faster End Turns",
        "items": [
            "Big speedup to End Turn on large, late-game worlds -- the AI's sea-invasion check was re-scanning the whole coastline every turn; it's now computed once and cached (~20x faster turn processing)",
            "Trimmed some unused internal code",
        ],
    },
    {
        "version": 19,
        "title": "Map Cleanup, Smoother Turns & Amphibious Claims",
        "items": [
            "Removed the relationship lines between your realm and others -- they were just visual clutter",
            "Ending turns very fast no longer makes the side panels flicker, flash, or vanish (End Turn is now gently rate-limited)",
            "Claiming a shore region you don't border by land (reachable only by sea) now costs ~1000 Gold and faces a bigger garrison -- curbs runaway early expansion for you and the AI alike",
        ],
    },
    {
        "version": 18,
        "title": "Combat Overhaul: Shields, Charges & Formations",
        "items": [
            "Swordsmen can now block frontal attacks with their shield -- flank and rear hits still land, so surrounding an enemy matters",
            "Cavalry are always the fastest on the field and hit hard with a couched charge, but fight softer once bogged down in a melee -- charge, pull back, charge again",
            "Planning phase: keys 1/2/3 (or buttons) select all Swordsmen/Cavalry/Archers; right-drag a line to form the selection up with rally-flag previews; Space deploys",
            "Troops pick targets with a bit more thought -- finishing the wounded, not all dogpiling one soldier, cavalry favoring archers",
        ],
    },
    {
        "version": 17,
        "title": "Map Panning Jitter Fixed",
        "items": [
            "Fixed map symbols, roads, and labels jittering against the terrain while panning",
        ],
    },
    {
        "version": 16,
        "title": "Gold No Longer Decays",
        "items": [
            "Gold no longer decays in storage -- it's currency, not a perishable good",
        ],
    },
    {
        "version": 15,
        "title": "Smoother Map Dragging",
        "items": [
            "Rapid map dragging no longer piles up redraws -- panning stays smooth and responsive",
        ],
    },
    {
        "version": 13,
        "title": "Trade Log: Tabs and Grouped Purchases",
        "items": [
            "Added Domestic/Global tabs to the Trade Log",
            "Purchases by the same buyer now collapse into one expandable row",
        ],
    },
    {
        "version": 12,
        "title": "Settlements Now Keep a Gold Buffer",
        "items": [
            "Settlements now hold back a 200 Gold buffer before spending on trade",
            "That buffer is trade-only -- it's still fully spendable on their own claims and construction",
        ],
    },
    {
        "version": 11,
        "title": "The World Wraps",
        "items": [
            "The map now wraps east-west -- scroll past one edge and continue onto the other",
            "Movement, pathfinding, and vision all cross the seam when it's the shorter route",
            "North/south edges don't wrap; the seam is always open ocean",
        ],
    },
    {
        "version": 10,
        "title": "Population Has Real Limits Now",
        "items": [
            "Added a population cap per settlement/village, with slow growth toward it",
            "Added a population floor -- starvation/freezing can shrink but never wipe out a settlement",
            "Regions with no Forest now scrounge up to 50% of their Firewood need",
            "Added a 'no local Firewood source' alert",
            "Regional Markets pay in goods first, Gold only for the rest -- and only if the faction owns Mountain land",
        ],
    },
    {
        "version": 9,
        "title": "Real Resource Totals & Economy Rebalance",
        "items": [
            "RESOURCES sidebar now totals every settlement and village",
            "Villages now count toward what you can afford to build",
            "Mining output cut significantly (Food/Firewood untouched)",
            "Luxury Goods no longer convert before turn 100, and only trickle in after",
            "Added keyboard shortcuts: E = End Turn, V = cycle map view",
        ],
    },
    {
        "version": 8,
        "title": "Trade Route Diplomacy & Fixes",
        "items": [
            "Fixed the Trade Log panel rendering at zero height and disappearing",
            "Trade routes and shipments now route around third-party territory",
            "Roads, trade routes, caravans, and ships reveal more fog of war",
        ],
    },
    {
        "version": 7,
        "title": "Villages Can Now Trade Between Regions",
        "items": [
            "Villages can now send and receive cross-region trade shipments",
            "Trade routes stay hidden under undiscovered fog until found",
            "Roads/trade routes reveal fog as built; caravans/ships reveal a radius around themselves",
        ],
    },
    {
        "version": 6,
        "title": "End Turn Hitching Fixed",
        "items": [
            "Fixed End Turn hitching from recoloring the whole map on any ownership change",
            "Now only recolors the regions that actually changed",
        ],
    },
    {
        "version": 5,
        "title": "Alerts: Know When Something's Wrong",
        "items": [
            "Added an Alerts panel (top-left) for shortages, starvation/freezing, and storage overflow",
            "Click an alert to jump to the settlement/village; matching badge on its map marker",
        ],
    },
    {
        "version": 4,
        "title": "Fishing, Smarter AI & Trade Diplomacy",
        "items": [
            "Added Fishing: free Fish near water, smoked into Smoked Fish for storage",
            "Trade route proposals now require Accept/Decline",
            "AI factions now claim wildland, build, and trade (1 project at a time)",
            "Added a grace period before starvation/freezing sets in",
            "Prosperity now takes ~1 year of good conditions to max out",
            "City-grown villages build roads to nearby villages too",
            "Starting Gold raised",
            "Added a resizable Trade Log panel (lower-left)",
            "Roads/trade routes avoid mountains more strongly; a river alone no longer blocks a route",
            "Fixed an occasional End Turn freeze from AI trade activity",
        ],
    },
    {
        "version": 3,
        "title": "Roads, Spawns & Live Stats",
        "items": [
            "Roads now avoid rivers/lakes and foreign territory where possible",
            "New settlements always spawn with farmland nearby",
            "Settlement/village/commander selection persists across End Turn with live stats",
        ],
    },
    {
        "version": 2,
        "title": "Currency, Economy Cleanup & the Calendar",
        "items": [
            "Gold is now mined as Gold Ore and struck into coin -- no more per-turn tax income",
            "Settlements short on Gold can barter goods of equal value instead",
            "Removed placeholder resources: Fish, Silks, Spices, Steel",
            "Seasons are now 25 turns each (100 turns/year)",
            "Added a year counter and year-end summary",
            "Fixed a mid-zoom performance cliff",
        ],
    },
    {
        "version": 1,
        "title": "Welcome to Shapes of War",
        "items": [
            "Initial release: progressive territory expansion, fog of war",
            "Commanders and ships",
            "Diplomacy-gated trade",
            "Settlement/village population and prosperity",
            "In-game Compendium explaining how it all works (press F1 any time)",
        ],
    },
]

CHANGELOG_VERSION = CHANGELOG_ENTRIES[0]["version"]


def _read_last_seen():
    try:
        return json.loads(_SEEN_PATH.read_text()).get("version", 0)
    except (OSError, ValueError):
        return 0


def mark_seen(version=CHANGELOG_VERSION):
    _SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SEEN_PATH.write_text(json.dumps({"version": version}))


def unseen_entries():
    """Entries newer than the last version the player dismissed the popup
    at, newest first -- empty once they're caught up. A brand new install
    (no seen-file yet) sees everything, framed as "here's what's in the
    game" rather than a growing wall of history it'll never fully show
    again once dismissed."""
    last_seen = _read_last_seen()
    return [e for e in CHANGELOG_ENTRIES if e["version"] > last_seen]
