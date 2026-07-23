"""A nation on the macro map."""
from itertools import count

_ids = count()


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

    @property
    def center(self):
        if self._center is not None:
            return self._center
        pts = [p for ring in self.territory for p in ring]
        if not pts:
            return (0.5, 0.5)
        return (sum(p[0] for p in pts) / len(pts),
                sum(p[1] for p in pts) / len(pts))
