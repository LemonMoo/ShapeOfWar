"""The Realm Chronicle: a dated, curated history of a realm's milestones --
first village founded, every village raised to a Town, every Town raised to
a City, every claim secured, the realm's own founding. The slow-burn game
needs history: entries are written world-side at the moment a milestone
actually happens (construction._finish_raise_village etc.), so they carry
the real in-game date, and the UI (app/ui/chronicle.py) just renders
nation.meta["chronicle"] newest-first.

Recorded for every faction (AI realms chronicle too -- cheap, and the
season-news feature reads the same entries), capped so a centuries-long
realm can't grow an unbounded list.
"""
from app.world.resources import turn_date_text

CHRONICLE_CAP = 200   # a 200-entry chronicle is already a long reign


def log(world, nation, text):
    """Append a dated milestone to a nation's chronicle. `world` supplies
    the turn the date is derived from (the sim's single clock)."""
    entries = nation.meta.setdefault("chronicle", [])
    entries.append({"date": turn_date_text(world.turn), "text": text})
    if len(entries) > CHRONICLE_CAP:
        del entries[:len(entries) - CHRONICLE_CAP]


def entries(nation):
    """A nation's chronicle, defaulting safely for old saves."""
    return nation.meta.get("chronicle", [])
