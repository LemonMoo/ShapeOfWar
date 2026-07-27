"""Rivers as navigable trade arteries.

Rivers were previously decoration for trade purposes: baked into the terrain
raster for display (map_view) and feeding Fishing yields (resources.py), but
no goods ever moved along them. This module supplies the three geography
primitives trade.py needs to change that:

  * which connected river NETWORK a cell belongs to (tributaries that merge
    downstream are one system, so goods can move between any two points on it),
  * whether a settlement/village sits close enough to a river to use it,
  * an actual navigable path between two river-side nodes.

Everything here derives from ``world.rivers`` / ``world.river_cells``, which
worldgen builds once and never mutates afterward -- so the expensive parts
(component labelling) are computed once and cached on the world forever, the
same idiom as ``territory._coastal_region_ids`` and
``resources._river_cell_flow``. The per-node lookup is cached lazily instead of
precomputed, because settlements and villages CAN appear mid-game (city growth,
newly settled claims) long after worldgen finished.

x wraps east-west everywhere here (see app/world/wrap.py); y never does.
"""
from app.world import wrap
from app.world.worldgen import OCEAN, _path_dijkstra

# How far from flowing water a settlement/village can sit and still load boats.
RIVER_ADJACENCY_REACH = 3

# Routing costs for river_path's Dijkstra. Water is the cheap highway; dry land
# is deliberately expensive so a path only ever steps ashore for the short hop
# between a node's door and its riverbank, never to shortcut overland.
_RIVER_STEP_COST = 1.0
_BANK_STEP_COST = 6.0

_NEIGH4 = ((1, 0), (-1, 0), (0, 1), (0, -1))
_NEIGH8 = ((-1, -1), (0, -1), (1, -1), (-1, 0),
           (1, 0), (-1, 1), (0, 1), (1, 1))


def river_systems(world):
    """``{(x, y): system_id}`` for every river cell -- one id per connected
    river network. Tributaries that merge downstream share cells, so they fall
    into the same component naturally, which is exactly the "can a boat get
    from here to there" question trade wants answered. Cached permanently."""
    cached = getattr(world, "_river_systems_cache", None)
    if cached is not None:
        return cached

    cells = getattr(world, "river_cells", None) or set()
    systems = {}
    next_id = 0
    for start in cells:
        if start in systems:
            continue
        systems[start] = next_id
        stack = [start]
        while stack:
            x, y = stack.pop()
            for dx, dy in _NEIGH8:
                ny = y + dy
                if not (0 <= ny < world.h):
                    continue
                nb = (wrap.wrap_x(x + dx, world.w), ny)
                if nb in cells and nb not in systems:
                    systems[nb] = next_id
                    stack.append(nb)
        next_id += 1

    world._river_systems_cache = systems
    return systems


def river_system_cells(world, system_id):
    """Every cell belonging to one river system -- the inverse index of
    river_systems(), built once and cached so river_path doesn't rescan the
    whole map on every lookup."""
    cache = getattr(world, "_river_system_cells_cache", None)
    if cache is None:
        cache = {}
        for cell, sid in river_systems(world).items():
            cache.setdefault(sid, set()).add(cell)
        world._river_system_cells_cache = cache
    return cache.get(system_id, set())


def _node_key(node):
    """Settlement and Village ids are separate, independently-numbered id
    spaces, so the cache key has to say which one this is -- same reasoning as
    trade._regional_node_kind."""
    return ("settlement" if hasattr(node, "kind") else "village", node.id)


def node_river_system(world, node):
    """The river system this node can load boats on, or None if there's no
    flowing water within RIVER_ADJACENCY_REACH. Short local BFS, the same shape
    as resources._node_fish_yield's water search. Cached per node (lazily --
    nodes can be created long after worldgen)."""
    cache = getattr(world, "_node_river_system_cache", None)
    if cache is None:
        cache = {}
        world._node_river_system_cache = cache
    key = _node_key(node)
    if key in cache:
        return cache[key]

    systems = river_systems(world)
    result = None
    x0, y0 = node.pos
    if (x0, y0) in systems:          # standing on the water's edge itself
        result = systems[(x0, y0)]
    else:
        seen = {(x0, y0)}
        frontier = [(x0, y0)]
        for _ in range(RIVER_ADJACENCY_REACH):
            nxt = []
            for x, y in frontier:
                for dx, dy in _NEIGH4:
                    ny = y + dy
                    if not (0 <= ny < world.h):
                        continue
                    nb = (wrap.wrap_x(x + dx, world.w), ny)
                    if nb in seen:
                        continue
                    seen.add(nb)
                    if nb in systems:
                        result = systems[nb]
                        break
                    nxt.append(nb)
                if result is not None:
                    break
            if result is not None:
                break
            frontier = nxt

    cache[key] = result
    return result


def shared_river_system(world, a_node, b_node):
    """The river system both nodes sit on, or None if they don't share one --
    the single gate for "can these two trade by boat"."""
    a = node_river_system(world, a_node)
    if a is None:
        return None
    return a if a == node_river_system(world, b_node) else None


def _bank_halo(world, pos, reach):
    """Dry-land cells within `reach` of `pos` -- the little bit of shore a
    path is allowed to use to get from a node's door to the water. Ocean is
    excluded: this is river navigation, not a sea voyage."""
    x0, y0 = pos
    out = set()
    for dy in range(-reach, reach + 1):
        ny = y0 + dy
        if not (0 <= ny < world.h):
            continue
        for dx in range(-reach, reach + 1):
            nx = wrap.wrap_x(x0 + dx, world.w)
            if world.owner[ny][nx] != OCEAN:
                out.add((nx, ny))
    return out


def river_path(world, a_pos, b_pos, system_id):
    """Navigable cells from `a_pos` to `b_pos` along river `system_id`, or None.

    The search space is the river itself plus a small halo of shore around each
    endpoint, so the result is naturally "short hop to the water, along the
    river, short hop to the far door" -- it can't wander overland, because dry
    cells cost several times a water step and only exist in the cellset near
    the two ends anyway."""
    river = river_system_cells(world, system_id)
    if not river:
        return None
    cellset = set(river)
    cellset |= _bank_halo(world, a_pos, RIVER_ADJACENCY_REACH)
    cellset |= _bank_halo(world, b_pos, RIVER_ADJACENCY_REACH)
    if a_pos not in cellset or b_pos not in cellset:
        return None

    def cost(cell):
        return _RIVER_STEP_COST if cell in river else _BANK_STEP_COST

    return _path_dijkstra(cellset, cost, a_pos, b_pos, world.w)
