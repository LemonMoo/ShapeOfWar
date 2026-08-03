"""Carving the galleries under the mountains.

Phase 1 of SUBTERRANEAN_PLAN.md. `app/world/layers.py` is the model; this is
what puts anything in it.

The shape follows the geology rather than a maze generator, and that is the
whole design:

  MASSIFS      A network belongs to a mountain range, not to the map. Connected
               components of mountain/highland cells, and anything smaller than
               a real range gets nothing -- a lone peak has no kingdom under it.
  CHAMBERS     Sited where the rock is deepest, which is where the ore is (the
               existing resource tables already gate Iron, Coal, Gold Ore and
               Gems on mountain/highland elevation, so this puts halls where
               there is a reason to dig).
  GALLERIES    A spanning network between chambers, not a labyrinth. A mine is
               a TREE from its shafts: every working leads back, because
               haulage is the thing that decides whether it pays. Mazes are a
               dungeon-crawl idea and would be wrong here.
  SKIRTS       Galleries run out past the mountain's foot, which is both what
               "and the surrounding area" meant and what puts gates in country
               an army can actually reach.
  CHASMS AND   Structure, so a network has shape instead of being uniformly
  SUNLESS      walkable. Carved only where they cannot cut a chamber off --
  WATER        checked by walking the network afterwards, not assumed.
  GATES        One to three per massif, on the flanks. The only way in.

Nothing here is rendered or read by any rule yet; `dev/under_shot.py` draws it
and `dev/test_underworld.py` measures it. Rendering worldgen before trusting it
has caught two real bugs in this project already -- the plate distance
transform's diamond artifacts and the flooded-continent lakes -- and a cave
network is exactly the kind of thing that passes a metric and looks wrong.
"""
import math
from collections import deque

from app.world import layers as L
from app.world.lexicon import make_under_region_namer
from app.world.worldgen import OCEAN, UNCLAIMED, Region

# --- what counts as a range ---------------------------------------------------
UNDER_BIOMES = ("mountain", "highland")
# Below this many cells a massif is an outcrop, not a range, and gets nothing.
# On a Standard world this leaves the handful of real ranges with networks and
# skips the scatter, which is both cheaper and the right read of the map.
MIN_MASSIF_CELLS = 45

# --- districts ----------------------------------------------------------------
# A connected range is NOT a hold. Measured on a Standard world, mountain and
# highland glue together into components of 35,000 cells and more -- a
# continental cordillera, and giving that one network with one set of doors
# would be both unplayable and wrong. Real ranges carry many separate mining
# districts along their length (the Alps have dozens), each with its own
# workings and its own way in.
#
# So a massif is cut into districts of roughly this size, each of which gets a
# network of its own. This is the constant that decides how much underworld a
# map has.
CELLS_PER_DISTRICT = 4000
MAX_DISTRICTS_PER_MASSIF = 40
DISTRICT_SPACING = 30.0     # cells between district seeds

# --- chambers -----------------------------------------------------------------
CELLS_PER_CHAMBER = 70      # one hall per this much mountain
MIN_CHAMBERS = 2
MAX_CHAMBERS = 9
CHAMBER_SPACING = 11.0      # cells; halls are not next door to each other
CAVERN_RADIUS = 2           # how far a chamber opens out around its centre

# --- galleries ----------------------------------------------------------------
GALLERY_WANDER = 0.35       # chance per step of a one-cell sideways drift, so a
                            # passage follows the rock rather than ruling a line
SKIRT_MARGIN = 7            # how far past the mountain's foot a gallery may run
ADITS_PER_DISTRICT = 2      # entrance passages driven out to the hillside
ADIT_MAX_LENGTH = 45        # cells; past this the hillside is too far to be
                            # worth driving to, and the workings stay sealed

# --- structure ----------------------------------------------------------------
WATER_CHANCE = 0.30         # per chamber: a sunless lake in one corner of it
CHASM_CHANCE = 0.22         # ...or a drop

# --- gates --------------------------------------------------------------------
MIN_GATES, MAX_GATES = 1, 3
GATE_SPACING = 14.0         # cells apart, so two gates are two problems

# --- regions ------------------------------------------------------------------
CELLS_PER_UNDER_REGION = 120


def _neigh8(x, y, w, h):
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx or dy:
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h:
                    yield nx, ny


def find_massifs(world, min_cells=MIN_MASSIF_CELLS):
    """Connected components of mountain/highland, largest first.

    8-connected, matching `_NEIGH8`'s convention everywhere else in worldgen --
    4-connectivity splits a diagonal ridge into two ranges, which is not what
    anybody looking at the map would call it."""
    w, h = world.w, world.h
    wanted = set(UNDER_BIOMES)
    seen = set()
    out = []
    for y in range(h):
        row = world.biome_grid[y]
        for x in range(w):
            if row[x] not in wanted or (x, y) in seen:
                continue
            stack = [(x, y)]
            seen.add((x, y))
            comp = []
            while stack:
                cx, cy = stack.pop()
                comp.append((cx, cy))
                for nx, ny in _neigh8(cx, cy, w, h):
                    if (nx, ny) not in seen and world.biome_grid[ny][nx] in wanted:
                        seen.add((nx, ny))
                        stack.append((nx, ny))
            if len(comp) >= min_cells:
                out.append(comp)
    out.sort(key=len, reverse=True)
    return out


def _split_into_districts(world, massif, rng):
    """Cut a range into the districts that will each get their own workings.

    Nearest-seed assignment over spaced-out high points -- the same shape as
    the surface region seeding, and for the same reason: it produces compact
    pieces without needing a real clustering pass over tens of thousands of
    cells."""
    n = max(1, min(MAX_DISTRICTS_PER_MASSIF, len(massif) // CELLS_PER_DISTRICT))
    if n == 1:
        return [massif]
    ranked = sorted(massif, key=lambda p: -world.height[p[1]][p[0]])
    pool = ranked[:max(n * 12, 40)]
    rng.shuffle(pool)
    seeds = []
    for p in pool:
        if len(seeds) >= n:
            break
        if all((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 >= DISTRICT_SPACING ** 2
               for q in seeds):
            seeds.append(p)
    if len(seeds) < 2:
        return [massif]
    buckets = [[] for _ in seeds]
    for p in massif:
        best = min(range(len(seeds)),
                   key=lambda i: (p[0] - seeds[i][0]) ** 2 + (p[1] - seeds[i][1]) ** 2)
        buckets[best].append(p)
    return [b for b in buckets if len(b) >= MIN_MASSIF_CELLS]


def _pick_chambers(world, massif, rng):
    """Where the halls go: deep rock, spaced apart.

    Sorted by elevation rather than sampled at random -- the ore tables key off
    elevation, so the deepest rock is where there is a reason to dig, and a
    hall sited there is a hall with something under it."""
    n = max(MIN_CHAMBERS, min(MAX_CHAMBERS, len(massif) // CELLS_PER_CHAMBER))
    ranked = sorted(massif, key=lambda p: -world.height[p[1]][p[0]])
    # Drawn from the whole HIGH HALF of the district, not from the highest
    # handful. Measured: a pool of the top ~70 cells is one summit, every
    # candidate in it is inside CHAMBER_SPACING of every other, and a district
    # that should have had nine halls got two -- 50 carved cells instead of
    # 350. The bias toward deep rock is kept; the tie-break is spread.
    pool = ranked[:max(len(ranked) // 2, n * 20)]
    rng.shuffle(pool)
    chosen = []
    for p in pool:
        if len(chosen) >= n:
            break
        if all((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 >= CHAMBER_SPACING ** 2
               for q in chosen):
            chosen.append(p)
    if not chosen:
        chosen = [ranked[0]]
    return chosen


def _carve_blob(world, cx, cy, radius, kind):
    """A chamber, opened out around its centre.

    The threshold is `r*r + r` rather than `r*r`: at radius 2 a strict circle
    excludes the (1,2) diagonals and what gets drawn is a four-pointed
    diamond -- rendered, a network of them reads as a row of sparkles rather
    than as halls. Caught by dev/under_shot.py, which is what it is for."""
    limit = radius * radius + radius
    for x in range(cx - radius, cx + radius + 1):
        for y in range(cy - radius, cy + radius + 1):
            if not (0 <= x < world.w and 0 <= y < world.h):
                continue
            if (x - cx) ** 2 + (y - cy) ** 2 <= limit:
                L.carve(world, x, y, kind)


def _carve_gallery(world, a, b, rng, allowed, wander=GALLERY_WANDER):
    """A passage from a to b: a walked line with a little drift.

    Confined to `allowed` -- the massif plus its skirt -- so a gallery cannot
    strike out across open farmland to reach the next range. Underground
    kingdoms being connected to each other is a decision, not an accident of
    two chambers happening to be near."""
    x, y = a
    bx, by = b
    guard = 0
    while (x, y) != (bx, by) and guard < 4000:
        guard += 1
        step_x = (bx > x) - (bx < x)
        step_y = (by > y) - (by < y)
        if rng.random() < wander:
            # Drift one cell off the straight line, but only across it -- a
            # passage that can also step BACKWARDS wanders forever.
            if step_x and rng.random() < 0.5:
                step_y = rng.choice((-1, 0, 1))
            elif step_y:
                step_x = rng.choice((-1, 0, 1))
        nx, ny = x + step_x, y + step_y
        if (nx, ny) not in allowed:
            nx, ny = x + ((bx > x) - (bx < x)), y + ((by > y) - (by < y))
            if (nx, ny) not in allowed:
                break
        x, y = nx, ny
        if L.kind_at(world, x, y, L.UNDER) != L.CAVERN:
            L.carve(world, x, y, L.GALLERY)


def _drive_adits(world, chambers, district, allowed, rng):
    """Drive an entrance passage from the workings out to the hillside.

    An ADIT is a horizontal passage driven in from the side of a hill -- how a
    mine was entered and, just as importantly, how it drained: water runs out
    of an adit by itself, where a shaft has to be pumped. Without this the
    network stays entirely inside the rock, every gate ends up on the mountain
    itself, and the "and the surrounding area" half of the brief never
    happens. Rendered, it was obvious: nine halls and not one passage reaching
    daylight.

    Driven from the LOWEST chambers, because that is where an adit pays."""
    outside = allowed - set(district)
    if not outside:
        return []
    driven = []
    lowest = sorted(chambers, key=lambda p: world.height[p[1]][p[0]])
    for start in lowest[:ADITS_PER_DISTRICT]:
        target = min(outside, key=lambda p: (p[0] - start[0]) ** 2
                     + (p[1] - start[1]) ** 2)
        if (target[0] - start[0]) ** 2 + (target[1] - start[1]) ** 2 > ADIT_MAX_LENGTH ** 2:
            continue
        _carve_gallery(world, start, target, rng, allowed)
        driven.append(target)
    return driven


def _spanning_pairs(chambers):
    """Prim's, on straight-line distance: the cheapest network that reaches
    every hall and no more. A mine is a tree from its shafts."""
    if len(chambers) < 2:
        return []
    inside = {0}
    pairs = []
    while len(inside) < len(chambers):
        best = None
        for i in inside:
            for j in range(len(chambers)):
                if j in inside:
                    continue
                d = ((chambers[i][0] - chambers[j][0]) ** 2
                     + (chambers[i][1] - chambers[j][1]) ** 2)
                if best is None or d < best[0]:
                    best = (d, i, j)
        _, i, j = best
        pairs.append((chambers[i], chambers[j]))
        inside.add(j)
    return pairs


def _skirt(world, massif, margin=SKIRT_MARGIN):
    """The massif plus a margin of the land around its foot -- where galleries
    may run and where gates may open. Never ocean, and never a lake bed."""
    w, h = world.w, world.h
    allowed = set(massif)
    frontier = deque((x, y, 0) for x, y in massif)
    while frontier:
        x, y, d = frontier.popleft()
        if d >= margin:
            continue
        for nx, ny in _neigh8(x, y, w, h):
            if (nx, ny) in allowed:
                continue
            if world.owner[ny][nx] == OCEAN or (nx, ny) in world.lake_cells:
                continue
            if world.height[ny][nx] <= 0.0:
                continue
            allowed.add((nx, ny))
            frontier.append((nx, ny, d + 1))
    return allowed


def _reachable(world, start, cells):
    """Everything in `cells` walkable from `start` -- used to prove a chasm did
    not cut a hall off, rather than assuming it did not."""
    seen = {start}
    stack = [start]
    while stack:
        x, y = stack.pop()
        for nx, ny in _neigh8(x, y, world.w, world.h):
            if (nx, ny) in seen or (nx, ny) not in cells:
                continue
            if L.kind_at(world, nx, ny, L.UNDER) not in L.PASSABLE_KINDS:
                continue
            seen.add((nx, ny))
            stack.append((nx, ny))
    return seen


def _add_structure(world, chambers, network, rng):
    """Sunless water and chasms, and then a check that the network still
    hangs together.

    Carved and REVERTED rather than placed carefully: working out in advance
    which cell is a cut vertex is more code than trying it and walking the
    network, and the walk is the honest test anyway."""
    for cx, cy in chambers:
        for kind, chance in ((L.WATER, WATER_CHANCE), (L.CHASM, CHASM_CHANCE)):
            if rng.random() >= chance:
                continue
            spots = [(x, y) for x, y in sorted(network)
                     if abs(x - cx) <= CAVERN_RADIUS and abs(y - cy) <= CAVERN_RADIUS
                     and (x, y) != (cx, cy)]
            if not spots:
                continue
            x, y = rng.choice(spots)
            before = L.kind_at(world, x, y, L.UNDER)
            L.carve(world, x, y, kind)
            if len(_reachable(world, (cx, cy), network)) < _passable_count(world, network):
                L.carve(world, x, y, before)   # it cut something off; put it back


def _passable_count(world, network):
    return sum(1 for p in network
               if L.kind_at(world, p[0], p[1], L.UNDER) in L.PASSABLE_KINDS)


def _components(world, cells):
    """Connected pieces of walkable ground within `cells`."""
    passable = {p for p in cells
                if L.kind_at(world, p[0], p[1], L.UNDER) in L.PASSABLE_KINDS}
    seen = set()
    out = []
    for start in sorted(passable):
        if start in seen:
            continue
        comp = {start}
        seen.add(start)
        stack = [start]
        while stack:
            x, y = stack.pop()
            for nx, ny in _neigh8(x, y, world.w, world.h):
                if (nx, ny) in passable and (nx, ny) not in seen:
                    seen.add((nx, ny))
                    comp.add((nx, ny))
                    stack.append((nx, ny))
        out.append(comp)
    out.sort(key=len, reverse=True)
    return out


def _repair_network(world, network, allowed, rng):
    """Make a district's workings one connected thing, or stop pretending the
    orphans exist.

    A gallery gives up when the ground ahead is outside the district's skirt,
    which leaves the chamber it was heading for stranded. Measured on two real
    worlds that produced fifteen networks from ten districts, three of them
    with no way in at all -- a kingdom nobody can ever reach, and a failure
    that is completely silent: nothing crashes, the map simply contains a hole.

    Every orphan gets one straight-driven passage to the main workings; if the
    ground will not allow even that, it is filled back in. Better no hall than
    a sealed one."""
    comps = _components(world, network)
    if len(comps) <= 1:
        return set(network)
    main = comps[0]
    for comp in comps[1:]:
        a, b = min(((p, q) for p in comp for q in main),
                   key=lambda pair: (pair[0][0] - pair[1][0]) ** 2
                   + (pair[0][1] - pair[1][1]) ** 2)
        _carve_gallery(world, a, b, rng, allowed, wander=0.0)

    network = {p for p in allowed if p in world.under_cells}
    comps = _components(world, network)
    for comp in comps[1:]:
        for x, y in comp:
            L.fill(world, x, y)
    return {p for p in allowed if p in world.under_cells}


def _place_gates(world, massif, network, rng):
    """One to three doors on the flanks of the range.

    A gate needs open ground on BOTH sides: a passable underground cell, and a
    surface cell that is land, dry, and not the summit -- an army has to be
    able to march to it. Lower ground is preferred for exactly that reason,
    which also puts the doors on the skirts rather than on the peak."""
    massif_set = set(massif)
    candidates = [p for p in sorted(network)
                  if L.kind_at(world, p[0], p[1], L.UNDER) in L.PASSABLE_KINDS
                  and p not in massif_set                     # out on the skirt
                  and world.owner[p[1]][p[0]] != OCEAN
                  and p not in world.lake_cells
                  and world.height[p[1]][p[0]] > 0.0]
    if not candidates:
        # A range with no skirt cells carved (a small one, or one hemmed in by
        # water): fall back to its own lowest carved cell, so a network is
        # never sealed with no way in at all.
        candidates = [p for p in sorted(network)
                      if L.kind_at(world, p[0], p[1], L.UNDER) in L.PASSABLE_KINDS
                      and world.owner[p[1]][p[0]] != OCEAN
                      and p not in world.lake_cells]
    if not candidates:
        return []
    candidates.sort(key=lambda p: world.height[p[1]][p[0]])
    wanted = rng.randint(MIN_GATES, MAX_GATES)
    gates = []
    for p in candidates:
        if len(gates) >= wanted:
            break
        if all((p[0] - g[0]) ** 2 + (p[1] - g[1]) ** 2 >= GATE_SPACING ** 2
               for g in gates):
            gates.append(p)
    return gates


def _partition_regions(world, network, rng, namer):
    """Cut a network into regions -- the same unit of ownership as the surface.

    Seeded and grown, like `_generate_all_regions` above ground, because the
    result has to be the same KIND of object: territory transfer, claims,
    prosperity and trade all work on regions, and an underground region that is
    not really one would need a twin of every one of those."""
    # Cells a neighbouring district already partitioned are left alone.
    # District skirts overlap, so a network legitimately contains cells that
    # are already somebody's -- claiming them again would leave the first
    # region listing cells it no longer owns, which is the kind of quiet
    # inconsistency that surfaces fifty turns later as a region with phantom
    # ground.
    passable = [p for p in sorted(network)
                if L.kind_at(world, p[0], p[1], L.UNDER) in L.PASSABLE_KINDS
                and L.region_at(world, p[0], p[1], L.UNDER) is None]
    if not passable:
        return []
    passable_set = set(passable)
    n = max(1, len(passable) // CELLS_PER_UNDER_REGION)
    pool = passable[:]
    rng.shuffle(pool)
    seeds = pool[:n]

    assign = {}
    frontier = deque()
    for i, p in enumerate(seeds):
        assign[p] = i
        frontier.append(p)
    while frontier:
        x, y = frontier.popleft()
        i = assign[(x, y)]
        for nx, ny in _neigh8(x, y, world.w, world.h):
            if (nx, ny) in assign or (nx, ny) not in passable_set:
                continue
            assign[(nx, ny)] = i
            frontier.append((nx, ny))

    # Anything the flood could not reach goes to its nearest seed -- exactly
    # what _generate_all_regions does above ground for the same reason. Without
    # it a stray pocket cut off from every seed belongs to no region at all,
    # which means nobody can ever own it: measured, four such cells on one
    # seed, and they would have been invisible until someone tried to claim
    # the hall they were in.
    for p in passable:
        if p not in assign:
            assign[p] = min(range(len(seeds)),
                            key=lambda i: (p[0] - seeds[i][0]) ** 2
                            + (p[1] - seeds[i][1]) ** 2)

    out = []
    for i in range(len(seeds)):
        cells = [p for p, j in assign.items() if j == i]
        if not cells:
            continue
        region = Region(len(world.regions), UNCLAIMED, namer())
        region.layer = L.UNDER
        region.cells = cells
        region.finalize(world)
        # finalize() reads the SURFACE fertility, biomes and climate at these
        # coordinates, which describe the mountainside overhead and say nothing
        # about a gallery. Overwrite them: nothing grows down here, there is no
        # biome, and there is no weather to have a climate.
        region.stats["fertility"] = 0
        region.biome_counts = {}
        region.dominant_climate = "subterranean"
        world.regions.append(region)
        for x, y in cells:
            L.set_region_at(world, x, y, L.UNDER, region.id)
        out.append(region)
    return out


def carve_underworld(world, rng):
    """Put an underworld beneath every real mountain range on the map.

    Called from generate_world once biomes exist (they decide what a mountain
    is) and before factions are placed. Returns a small summary for the debug
    tools; the world itself carries the result."""
    L.ensure_layers(world)
    namer = make_under_region_namer(rng)
    summary = {"districts": 0, "cells": 0, "gates": 0, "regions": 0}

    for massif in find_massifs(world):
      for district in _split_into_districts(world, massif, rng):
        allowed = _skirt(world, district)
        chambers = _pick_chambers(world, district, rng)
        for cx, cy in chambers:
            _carve_blob(world, cx, cy, CAVERN_RADIUS, L.CAVERN)
        for a, b in _spanning_pairs(chambers):
            _carve_gallery(world, a, b, rng, allowed)
        _drive_adits(world, chambers, district, allowed, rng)

        # Everything this district carved, which is what the structure pass and
        # the region partition work over. Taken from `allowed` rather than from
        # the whole world, so two districts never share a network -- which is
        # what makes each one a separate hold with its own doors.
        network = {p for p in allowed if p in world.under_cells}
        network = _repair_network(world, network, allowed, rng)
        _add_structure(world, chambers, network, rng)
        # ...and again after the chasms and lakes: _add_structure only reverts
        # a feature that cuts a CHAMBER off, and a gallery corner can be
        # stranded without any chamber noticing.
        network = _repair_network(world, network, allowed, rng)

        gate_cells = _place_gates(world, district, network, rng)
        for x, y in gate_cells:
            L.add_gate(world, (x, y), (x, y))

        summary["districts"] += 1
        summary["gates"] += len(gate_cells)

    _enforce_no_sealed_networks(world, rng, summary)

    # Regions are cut LAST, and per connected network rather than per district.
    #
    # Doing it inside the district loop was wrong twice over. District skirts
    # overlap, so a later district's chambers spill cells into ground an
    # earlier one had already partitioned -- measured, 56 caverns belonging to
    # no region at all, which means nobody could ever own them. And a region
    # ought to be a piece of ONE network anyway: a region spanning two
    # unconnected holds is a region you could hold half of without ever being
    # able to walk to the rest.
    for network in _components(world, world.under_cells):
        summary["regions"] += len(_partition_regions(world, network, rng, namer))
    summary["cells"] = len(world.under_cells)
    world.under_summary = summary
    return summary


# A fragment smaller than this is not worth a door of its own -- it is a
# leftover, and the honest thing to do with it is fill it in.
MIN_ORPHAN_CELLS = 25


def _enforce_no_sealed_networks(world, rng, summary):
    """The invariant, checked over the whole map once every district is cut.

    Districts share skirt space -- one range's margin overlaps the next -- so
    carving a later district can strand a fragment of an earlier one after its
    gates were already placed. Per-district repair cannot see that, because at
    the time it runs the cells that will orphan it do not exist yet.

    So this runs last and globally: anything walkable with no gate on it either
    gets a door, or gets filled. A sealed hold is a silent failure -- nothing
    crashes, the map just contains a kingdom no army can ever reach -- and
    dev/test_underworld.py asserts against it precisely because nothing else
    would ever notice."""
    mouths = {tuple(g["under"]) for g in world.gates}
    for comp in _components(world, world.under_cells):
        if comp & mouths:
            continue
        if len(comp) >= MIN_ORPHAN_CELLS:
            gates = _place_gates(world, [], comp, rng)
            if gates:
                for x, y in gates:
                    L.add_gate(world, (x, y), (x, y))
                summary["gates"] += len(gates)
                continue
        for x, y in comp:
            L.fill(world, x, y)
        summary["cells"] -= len(comp)
