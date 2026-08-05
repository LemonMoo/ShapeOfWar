"""Season news beats: the one-line world digest at each season change.

The chronicles (app/world/chronicle.py) are the world's real history --
every realm's raises, upgrades, claims and foundings, dated and
turn-stamped. At the first turn of a new season, resources.day_steps asks
this module to read back the entries written during the season that just
ended and compress them into a single line of news: "Winter 1, Year 3 —
Two realms raised new Towns; the Goblin realm claimed new land."

The line rides the world (world.season_news + world.season_news_turn) and
the UI surfaces it once via the bottom banner at turn-settled, so the
world's other realms' progress is actually visible rather than happening
behind the fog.
"""
from app.world.resources import TURNS_PER_SEASON


def _season_entries(world):
    """(realm_name, text) for every chronicle entry dated in the season
    that just ended (entries older than that, or from before entries
    carried a turn stamp, are ignored)."""
    out = []
    floor = world.turn - TURNS_PER_SEASON
    for nation in world.factions:
        for e in nation.meta.get("chronicle", []):
            t = e.get("turn", 0)
            if t and floor < t <= world.turn:
                out.append((nation.name, e.get("text", "")))
    return out


def compose_season_news(world):
    """One line summarizing what the realms did last season, or None when
    nothing worth the banner happened."""
    entries = _season_entries(world)
    parts = []
    towns = [n for n, t in entries if "rises to a " in t and "Town" in t]
    cities = [n for n, t in entries if "rises to a " in t and "City" in t]
    claims = [n for n, t in entries if "is secured" in t]
    firsts = [n for n, t in entries if "first village" in t]
    if towns:
        parts.append(f"{towns[0]} raised a new Town" if len(towns) == 1
                     else f"{len(towns)} realms raised new Towns")
    if cities:
        parts.append(f"{cities[0]} raised a new City" if len(cities) == 1
                     else f"{len(cities)} realms raised new Cities")
    if claims:
        parts.append(f"{claims[0]} claimed new land" if len(claims) == 1
                     else f"{len(claims)} realms claimed new land")
    if firsts:
        parts.append(f"{firsts[0]} founded its first village"
                     if len(firsts) == 1 else f"{len(firsts)} realms founded "
                     "their first villages")
    return "; ".join(parts) if parts else None
