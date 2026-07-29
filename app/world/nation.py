"""A nation on the macro map."""
from itertools import count

_ids = count()


def is_eliminated(nation):
    """True once a nation has lost its last region (see
    app/world/territory.py's eliminate_faction).

    Eliminated nations are *tombstoned*, not deleted: they stay in
    world.factions at their original position and simply get flagged. That
    is not squeamishness about deleting data -- a faction's identity in this
    game IS its index into world.factions, and that index is stored in the
    world.owner grid (one entry per map cell), on every region, settlement,
    village, commander, ship and caravan, in each trade route's
    a_faction/b_faction, in world.discovered_factions, and in
    world.player_faction_idx. Removing a list element would silently
    renumber every faction after it and reassign territory wholesale.

    Read through this helper rather than touching the attribute directly:
    saves written before elimination existed have Nation objects with no
    such attribute, so the getattr default is what keeps them loadable."""
    return getattr(nation, "eliminated", False)


def active_factions(world):
    """[(idx, nation), ...] for every faction still in the game — the list
    every UI listing and AI pass should iterate instead of enumerating
    world.factions directly."""
    return [(i, f) for i, f in enumerate(world.factions) if not is_eliminated(f)]


class Nation:
    """A nation. ``stats`` and ``meta`` are free-form dicts so extensions can
    bolt on economy, tech, population, etc. without changing this class.

    ``territory`` is a list of rings (a multi-polygon); each ring is a list of
    (x, y) points in normalized 0..1 map space, so the map scales to any window
    size. ``center`` (0..1) is where the label/relationship links anchor; if not
    given it is computed from the territory.
    """

    def __init__(self, name, color, territory=None, center=None,
                 stats=None, meta=None, ruler=None):
        self.id = f"nation_{next(_ids)}"
        self.name = name
        self.color = color
        # Who sits the throne: {"name": str, "title": str}. Distinct from the
        # battlefield Commander (app/world/commander.py), who is the general
        # who marches and can fall -- this one is the realm's identity, and it
        # is why a rival has a name to go to war WITH rather than just a flag.
        # Defaulted rather than required, so a Nation built by older code or an
        # older save is still coherent (see nation.ensure_rulers).
        self.ruler = ruler or {}
        self.territory = territory or []      # list of rings
        self._center = center
        self.stats = {"military": 50, "morale": 50, **(stats or {})}
        self.meta = meta or {}
        # Set when this nation loses its last region — see is_eliminated().
        self.eliminated = False
        self.eliminated_by = None     # index of the faction that took the last region
        self.eliminated_turn = None

    @property
    def center(self):
        if self._center is not None:
            return self._center
        pts = [p for ring in self.territory for p in ring]
        if not pts:
            return (0.5, 0.5)
        return (sum(p[0] for p in pts) / len(pts),
                sum(p[1] for p in pts) / len(pts))


def ensure_rulers(world):
    """Give a monarch to any realm that has none.

    Saves predating rulers have factions with no throne at all, and every UI
    that shows one would otherwise have to check. Seeded from the world's own
    seed rather than fresh randomness, so loading the same save twice does not
    quietly rename a rival's king between sessions."""
    import random

    from app.world.lexicon import make_ruler_namer, ruler_title

    missing = [n for n in getattr(world, "factions", ()) if not getattr(n, "ruler", None)]
    if not missing:
        return 0
    rng = random.Random(getattr(world, "seed", 0))
    namer = make_ruler_namer(rng)
    for nation in missing:
        species = (nation.meta or {}).get("species", "Humans")
        nation.ruler = {"name": namer(species), "title": ruler_title(species, rng)}
    return len(missing)


def ruler_label(nation):
    """'King Aldric the Bold', or just the realm's name if it has no monarch."""
    ruler = getattr(nation, "ruler", None) or {}
    name = ruler.get("name")
    if not name:
        return ""
    title = ruler.get("title")
    return f"{title} {name}" if title else name
