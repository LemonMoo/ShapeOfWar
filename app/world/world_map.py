"""Nations plus the relationship graph between them."""
from app.core.events import bus


class Stance:
    """Relationship stances. Add new ones here and give them a color in the
    map view; the rest of the code treats stance as opaque data."""
    ALLY = "ally"
    NEUTRAL = "neutral"
    ENEMY = "enemy"


#  Default "standing" (see app/world/diplomacy.py) for a relationship rolled
# with a given stance and no explicit standing of its own.
_STANCE_DEFAULT_STANDING = {Stance.ALLY: 60, Stance.NEUTRAL: 0, Stance.ENEMY: -60}


class WorldMap:
    def __init__(self):
        self.nations = {}        # id -> Nation
        self.relationships = {}  # frozenset({idA, idB}) -> {"stance", "tension",
                                  #                           "standing", "acted_turn"}

    def add_nation(self, nation):
        self.nations[nation.id] = nation
        bus.emit("nation:added", nation)
        return nation

    @staticmethod
    def _key(a_id, b_id):
        return frozenset((a_id, b_id))

    def set_relationship(self, a_id, b_id, stance=Stance.NEUTRAL, tension=0,
                          standing=None, acted_turn=None):
        if a_id == b_id:
            return None
        if standing is None:
            standing = _STANCE_DEFAULT_STANDING.get(stance, 0)
        rel = {"stance": stance, "tension": tension, "standing": standing,
               "acted_turn": acted_turn}
        self.relationships[self._key(a_id, b_id)] = rel
        bus.emit("relationship:changed",
                 {"a_id": a_id, "b_id": b_id, **rel})
        return rel

    def get_relationship(self, a_id, b_id):
        return self.relationships.get(
            self._key(a_id, b_id),
            {"stance": Stance.NEUTRAL, "tension": 0, "standing": 0, "acted_turn": None})

    def relationships_of(self, nation_id):
        """All relationships involving a nation, resolved to the other party."""
        out = []
        for key, rel in self.relationships.items():
            if nation_id in key:
                other_id = next(i for i in key if i != nation_id)
                out.append({"other": self.nations[other_id], **rel})
        return out
