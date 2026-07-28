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
                 stats=None, meta=None):
        self.id = f"nation_{next(_ids)}"
        self.name = name
        self.color = color
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
