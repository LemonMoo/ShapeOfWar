"""Two layers of world: the surface, and the galleries under the mountains.

Phase 0 of SUBTERRANEAN_PLAN.md -- the data model and the accessors, and
deliberately nothing else. No worldgen carves anything yet, nothing renders,
and no rule reads it. The phase exists so the seam is settled before anything
is built on it.

WHY IT IS SPARSE
----------------
`world.owner[y][x]` and friends are dense [y][x] grids, and there are ten of
them. Mirroring that for the underground would cost 726,000 cells on a Standard
world, of which the overwhelming majority would be solid rock nobody ever
visits, and it would double the pickle. The underground exists only under
mountain and highland cells and a margin around them -- a few per cent of the
map -- so it is stored as a SET of open cells plus dicts keyed by (x, y).
Absent means rock. A save grows by kilobytes.

WHY REGIONS ARE NOT SPECIAL
---------------------------
An underground region is an ordinary `Region` in `world.regions` carrying
`layer = UNDER`. That is what lets territory transfer, claims, prosperity,
trade, construction and battles work on it with no underground-specific twin of
any of them. Read through `region_layer()`, which defaults to the surface, so
every world ever pickled is already a valid surface-only world and there is no
migration to run over region data at all.

WHAT KNOWS ABOUT BOTH LAYERS
----------------------------
This module, and as little else as possible. Call sites move onto the
accessors here only where they genuinely must -- pathing, territory, vision,
settlement placement. Everything else in the game is surface-only by nature and
keeps reading the dense grids directly, which is both faster and honest about
what it means.

A GATE is the only join between the layers: a surface cell paired with an
underground one. `neighbours()` is where that becomes an edge, so anything that
walks the map through this module gets cross-layer movement for free, and
anything that does not, cannot accidentally tunnel.
"""

from app.world.worldgen import OCEAN

SURFACE = 0
UNDER = 1
LAYERS = (SURFACE, UNDER)

# Underground cell kinds. Deliberately few, and each one is a thing a network
# actually has rather than a biome-style climate reading -- there is no weather
# down here to have bands of.
GALLERY = "gallery"   # a worked passage: narrow, walkable, slow
CAVERN = "cavern"     # open ground: where a hold or a warren can be built
CHASM = "chasm"       # a drop. Impassable, and what gives a network its shape
WATER = "water"       # sunless water. Impassable on foot
UNDER_KINDS = (GALLERY, CAVERN, CHASM, WATER)

# Which kinds can be walked through, and which can be settled on. Kept apart on
# purpose: a gallery is a corridor you pass along, not a place anyone lives.
PASSABLE_KINDS = frozenset({GALLERY, CAVERN})
SETTLEABLE_KINDS = frozenset({CAVERN})


def ensure_layers(world):
    """Give `world` the underground fields if it has none.

    Idempotent and cheap, in the same shape as every other migration this
    project runs on load (see app/core/save.py). A world saved before the
    underground existed comes back as a world with an empty one -- no
    underground cells, no gates -- which is exactly what it was.
    """
    if not hasattr(world, "under_cells"):
        world.under_cells = set()        # (x, y) with open space; absent == rock
        world.under_kind = {}            # (x, y) -> one of UNDER_KINDS
        world.under_owner = {}           # (x, y) -> faction index; absent == unclaimed
        world.under_region = {}          # (x, y) -> region id; absent == none
        world.gates = []                 # see add_gate
    return world


# --- regions ------------------------------------------------------------------
def region_layer(region):
    """Which layer a region is on. Defaults to the surface, so a region pickled
    before this module existed reads correctly rather than needing migrating."""
    return getattr(region, "layer", SURFACE)


def is_under(region):
    return region_layer(region) == UNDER


def regions_on(world, layer):
    return [r for r in world.regions if region_layer(r) == layer]


# --- cells --------------------------------------------------------------------
def is_open(world, x, y, layer):
    """Can anything exist at this cell on this layer?

    Surface: anything that is not ocean. Underground: only a carved cell, and
    only one whose kind is passable -- a chasm and a sunless lake are open space
    in the sense that they are not rock, and closed in every sense that
    matters to something trying to stand there."""
    if layer == SURFACE:
        return world.owner[y][x] != OCEAN or _is_land(world, x, y)
    return world.under_kind.get((x, y)) in PASSABLE_KINDS


def _is_land(world, x, y):
    """Land regardless of who owns it -- `owner` carries OCEAN for sea cells and
    an unclaimed-land marker for the rest, so ownership alone cannot answer
    this."""
    return world.height[y][x] > 0.0 and (x, y) not in world.lake_cells


def kind_at(world, x, y, layer):
    """The underground kind of a cell, or None on the surface (which has
    biomes instead -- see world.biome_grid) and None where there is rock."""
    if layer == SURFACE:
        return None
    return world.under_kind.get((x, y))


def owner_at(world, x, y, layer):
    """Faction index owning this cell, or None if nobody does.

    The two layers answer this differently on purpose: the surface grid stores
    OCEAN and an unclaimed marker in the same array it stores owners in, while
    the underground simply has no entry for ground nobody holds."""
    if layer == SURFACE:
        idx = world.owner[y][x]
        return None if idx < 0 else idx
    return world.under_owner.get((x, y))


def set_owner_at(world, x, y, layer, faction_idx):
    """Claim (or release, with None) one cell on one layer."""
    if layer == SURFACE:
        world.owner[y][x] = OCEAN if faction_idx is None else faction_idx
        return
    if faction_idx is None:
        world.under_owner.pop((x, y), None)
    else:
        world.under_owner[(x, y)] = faction_idx


def region_at(world, x, y, layer):
    """Region id covering this cell, or None."""
    if layer == SURFACE:
        rid = world.region_grid[y][x]
        return None if rid < 0 else rid
    return world.under_region.get((x, y))


def set_region_at(world, x, y, layer, region_id):
    if layer == SURFACE:
        world.region_grid[y][x] = -1 if region_id is None else region_id
        return
    if region_id is None:
        world.under_region.pop((x, y), None)
    else:
        world.under_region[(x, y)] = region_id


def carve(world, x, y, kind=GALLERY):
    """Open one underground cell. The only way `under_cells` should ever grow,
    so the set and the kind map cannot drift apart."""
    if kind not in UNDER_KINDS:
        raise ValueError(f"unknown underground kind: {kind!r}")
    world.under_cells.add((x, y))
    world.under_kind[(x, y)] = kind


def fill(world, x, y):
    """Close an underground cell back to solid rock, and forget everything
    about it -- a cell that is rock cannot be owned or belong to a region."""
    world.under_cells.discard((x, y))
    world.under_kind.pop((x, y), None)
    world.under_owner.pop((x, y), None)
    world.under_region.pop((x, y), None)


# --- gates --------------------------------------------------------------------
# The only join between the layers. A gate is a pair of cells -- one on each
# side -- and it is deliberately a small, findable, defensible thing: see
# SUBTERRANEAN_PLAN's note on Cappadocia, where a handful of doors IS the
# fortification.
def add_gate(world, surface_pos, under_pos, name=None):
    gate = {"pos": tuple(surface_pos), "under": tuple(under_pos), "name": name}
    world.gates.append(gate)
    world._gate_index = None      # see gate_at
    return gate


def gate_at(world, x, y, layer):
    """The gate whose mouth is this cell on this layer, or None.

    Indexed rather than scanned, because `neighbours` asks this at every step
    and `neighbours` is what a path search walks: a linear scan over every gate
    on the map, per cell, per search, is the kind of quiet quadratic this
    project has already had to dig out of `choose_target` once. The index is
    rebuilt lazily and thrown away whenever a gate is added, which happens at
    worldgen and essentially never again.

    Cached on the world, so it is NOT part of the save -- `_gate_index` is
    rebuilt on first use after a load. Keep it that way: a stale index pickled
    beside the gates it indexes is a bug waiting for someone to edit one."""
    index = getattr(world, "_gate_index", None)
    if index is None:
        index = {}
        for gate in world.gates:
            index[(gate["pos"][0], gate["pos"][1], SURFACE)] = gate
            index[(gate["under"][0], gate["under"][1], UNDER)] = gate
        world._gate_index = index
    return index.get((x, y, layer))


def gate_exit(gate, layer):
    """Where a gate lands you, coming from `layer`: (x, y, layer)."""
    if layer == SURFACE:
        return gate["under"][0], gate["under"][1], UNDER
    return gate["pos"][0], gate["pos"][1], SURFACE


# --- movement -----------------------------------------------------------------
_NEIGH8 = ((-1, -1), (0, -1), (1, -1),
           (-1, 0), (1, 0),
           (-1, 1), (0, 1), (1, 1))


def neighbours(world, x, y, layer):
    """Every cell reachable in one step from here, as (x, y, layer).

    The eight around it on its own layer, plus -- if it stands in a gate's
    mouth -- the cell on the other side. This is the single place cross-layer
    movement exists: anything that walks the world through this function can
    descend, and anything that does not, cannot tunnel by accident."""
    for dx, dy in _NEIGH8:
        nx, ny = x + dx, y + dy
        if 0 <= nx < world.w and 0 <= ny < world.h and is_open(world, nx, ny, layer):
            yield nx, ny, layer
    gate = gate_at(world, x, y, layer)
    if gate is not None:
        yield gate_exit(gate, layer)
