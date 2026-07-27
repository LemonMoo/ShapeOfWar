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
