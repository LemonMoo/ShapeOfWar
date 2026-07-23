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
# noteworthy batch of changes ships -- keep it player-facing (what changed
# for someone playing the game), not a commit log.
CHANGELOG_ENTRIES = [
    {
        "version": 3,
        "title": "Roads, Spawns & Live Stats",
        "items": [
            "Roads now avoid crossing rivers/lakes unless there's genuinely "
            "no reasonable way around, and strongly prefer staying on your "
            "own territory instead of routing through someone else's land.",
            "New settlements always start with real farmland somewhere "
            "nearby, instead of possibly landing in the middle of a "
            "mountain range or desert.",
            "Selecting a settlement, village, or commander now stays "
            "selected across End Turn, with its stats updating live turn "
            "by turn instead of going stale until you re-click it.",
        ],
    },
    {
        "version": 2,
        "title": "Currency, Economy Cleanup & the Calendar",
        "items": [
            "Gold is a real, tangible resource now: mined as Gold Ore and "
            "struck into coin at a Mint, stored and spent at your own "
            "settlements like any other good -- no more automatic per-turn "
            "tax income.",
            "A settlement short on Gold can barter real goods of "
            "equivalent value instead, for both domestic and foreign trade.",
            "Fish, Silks, Spices, and Steel -- the last of the old "
            "placeholder resources -- are fully retired.",
            "Seasons are now 25 turns each (100 turns/year), with a "
            "persistent year counter and a year-end summary of your "
            "faction's biggest gains and losses.",
            "Fixed a mid-zoom performance cliff on the world map.",
        ],
    },
    {
        "version": 1,
        "title": "Welcome to Shapes of War",
        "items": [
            "Progressive territory expansion, fog of war, commanders and "
            "ships, diplomacy-gated trade, settlement/village population "
            "and prosperity, and a full in-game Compendium explaining how "
            "it all works (press F1 any time).",
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
