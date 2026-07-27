"""Procedural generator for an Earth-like fantasy world.

Pipeline:
  1. Fractal value-noise height field + radial falloff -> continents & oceans.
  2. Threshold to land; scatter faction capitals on land.
  3. Multi-source BFS grows each capital's territory over adjacent land.
  4. Bordering territories become diplomatic relationships (species-aware).

Returns a ``World`` holding the grids plus a ``WorldMap`` of factions (Nation
objects) so the rest of the game is unchanged. The map view renders straight
from the grids; battles read faction stats/colors.
"""
import colorsys
import math
import random

from collections import deque, defaultdict

from app.world.nation import Nation
from app.world.world_map import WorldMap
from app.world import wrap
from app.world.lexicon import (SPECIES, make_faction_namer, make_region_namer,
                               make_settlement_namer)


# Settlement archetypes — pure placement data (where they go). Upkeep used
# to be rolled here too (SETTLEMENT_UPKEEP, a flat Grain/Fresh Water/Iron
# draw); that's gone, fully replaced by app/world/resources.py's Phase 8
# consumption model (settlement_needs — Food/Firewood/Clothes, scaled off
# actual population instead of a fixed roll). Production itself is
# region-level (biome-driven — see app/world/resources.py).
#   fert_w      : how strongly placement favors fertile land
#   river_w     : ... proximity to rivers/lakes
#   coast_w     : ... proximity to the sea
#   border_w    : ... proximity to a foreign border (castles guard frontiers)
#   elev_w      : ... high ground (castles like it, towns don't care)
SETTLEMENT_TYPES = {
    "city": {
        "name": "City",
        "fert_w": 1.0, "river_w": 0.8, "coast_w": 0.6, "border_w": 0.0,
        "elev_w": 0.0, "per_cells": 600, "max": 4, "min": 1, "spacing": 14,
    },
    "castle": {
        "name": "Castle",
        "fert_w": 0.1, "river_w": 0.2, "coast_w": 0.0, "border_w": 1.2,
        "elev_w": 0.8, "per_cells": 450, "max": 6, "min": 1, "spacing": 11,
    },
    "town": {
        "name": "Town",
        "fert_w": 0.7, "river_w": 0.5, "coast_w": 0.3, "border_w": 0.0,
        "elev_w": 0.0, "per_cells": 250, "max": 10, "min": 2, "spacing": 7,
    },
}

# Every faction's starting foothold gets exactly this — a small, equal seed
# regardless of how large its home region happens to be (the area-scaled
# min/max/per_cells counts above only kick in later, for settlements placed
# in newly *claimed* territory — see _place_settlements_for_faction's
# `fixed_counts` param and its two call sites).
STARTING_SETTLEMENT_COUNTS = {"city": 1, "town": 2, "castle": 0}

# Gold tax revenue per settlement kind per turn — same "rolled once at
# placement" treatment as upkeep, just positive instead of negative.
SETTLEMENT_TAX_INCOME = {
    "city": (8, 14),
    "castle": (3, 6),
    "town": (2, 4),
}

# This settlement's/village's real population CEILING, rolled once at
# placement (see resources.POPULATION_GROWTH_RATE for the slow climb
# toward it, and POPULATION_MIN_FRACTION for the floor a bad enough
# shortage can never push it below) -- not a flavor stat any more. A
# castle's ceiling skews toward garrison over civilians, hence the lower
# range.
POPULATION_RANGE = {
    "city": (4000, 12000),
    "castle": (500, 1500),
    "town": (1200, 3500),
    "village": (80, 450),
}
CHILDREN_FRACTION_RANGE = (0.30, 0.42)   # share of population under working age

# A freshly founded settlement/village starts well below what it could
# eventually support (see resources.POPULATION_GROWTH_RATE) -- "roughly
# 20%" per the request, with a small spread so every settlement of the
# same kind doesn't start at an identical fraction.
STARTING_POPULATION_FRACTION_RANGE = (0.15, 0.25)


def _roll_population(rng, kind):
    """(starting_population, adults, children, max_population) for one
    settlement of `kind`, rolled once at placement -- `max_population` is
    the real ceiling (see POPULATION_RANGE), `starting_population` is
    roughly 20% of it (STARTING_POPULATION_FRACTION_RANGE) since a
    freshly founded settlement hasn't grown into its potential yet. The
    adult/child split (CHILDREN_FRACTION_RANGE) is rolled against the
    STARTING population, not the ceiling -- there's no one alive yet to
    split for population that hasn't been born."""
    max_population = round(rng.uniform(*POPULATION_RANGE[kind]))
    total = round(max_population * rng.uniform(*STARTING_POPULATION_FRACTION_RANGE))
    children = round(total * rng.uniform(*CHILDREN_FRACTION_RANGE))
    return total, total - children, children, max_population


class Settlement:
    """A city, castle or town. Purely a consumer (population's needs, see
    app/world/resources.py's Phase 8 settlement_needs — scaled off
    population, not a flat roll) — production is region-level, but
    storage is this settlement's own (Phase 9 — see `resources` below)."""

    def __init__(self, sid, kind, name, pos, faction_idx, region_id, tax_income,
                population, adults, children, prosperity, max_population=None):
        self.id = sid
        self.kind = kind               # "city" | "castle" | "town"
        self.name = name
        self.pos = pos                 # (x, y) grid cell
        self.faction_idx = faction_idx
        self.region_id = region_id
        self.tax_income = tax_income   # gold generated per turn
        self.population = population   # current headcount -- starts around 20% of
                                       # max_population, climbs slowly (see
                                       # resources.POPULATION_GROWTH_RATE)
        self.adults = adults
        self.children = children
        # The real ceiling this settlement can ever grow to (see
        # POPULATION_RANGE/_roll_population) -- None only for old saves
        # predating this, handled via getattr(node, "max_population", ...)
        # fallbacks wherever it's read.
        self.max_population = max_population
        # 0..100 meter of goods/wealth value vs. the faction's overall
        # economic health — eased toward a new target every turn, not
        # recomputed from scratch (see resources._update_prosperity).
        self.prosperity = prosperity
        # This settlement's own stockpile (Phase 9 — see
        # app/world/resources.py's settlement_storage_capacity/
        # advance_settlement_storage): resource -> amount, genuinely
        # separate from every other settlement's, capped by a shared
        # space budget rather than an independent cap per resource.
        self.resources = {}
        # Coastal cities only — see app/world/construction.py's
        # ShipyardProject: launches free, faster ships once built.
        self.has_shipyard = False
        # Storage-capacity buildings (Phase 9) — see construction.py's
        # GranaryProject/WarehouseProject and resources.py's
        # settlement_storage_capacity for what each actually adds.
        self.has_granary = False
        self.has_warehouse = False
        # City-only organic growth (see resources._grow_city_villages): a
        # full prosperity meter spawns a new village nearby and resets to
        # 0. villages_spawned is a hidden running counter (not shown in the
        # UI); village_growth_maxed permanently latches once no valid site
        # remains within the growth radius, so a "full" city stops
        # re-scanning every turn.
        self.villages_spawned = 0
        self.village_growth_maxed = False
        # Consecutive turns this settlement has gone with an unmet Food
        # need (see resources._consume_node_needs) -- population loss only
        # actually starts once this crosses STARVATION_GRACE_TURNS, reset
        # to 0 the moment Food is fully met again. A single bad turn (or a
        # short rough patch) shouldn't be an irreversible death spiral.
        self.turns_without_food = 0
        # Same idea, for an unmet Firewood need in Winter (see
        # FREEZE_GRACE_TURNS) -- naturally resets to 0 outside Winter too,
        # since Firewood isn't even needed then.
        self.turns_without_firewood = 0


class Village:
    """A small farming settlement within a region — the finest-grained unit on
    the map (World -> Country -> Region -> Village). The actual farm unit:
    Crop/Livestock production (see app/world/resources.py) lands here
    first, not at a settlement — a village has no mill/loom/forge of its
    own to do anything with raw Wheat, which is exactly why it has to be
    physically shipped to a settlement that can (see Phase 10's
    run_local_logistics), and why the resulting Bread has to be shipped
    back for the village's own population to eat. Population still draws
    real Food/Firewood/Clothes needs (see resources.advance_settlement_
    consumption, which covers Villages too as of Phase 10) — no longer
    the "subsistence-level, no drain" exemption from earlier phases."""

    def __init__(self, vid, region_id, faction_idx, name, pos, farm_output,
                population, adults, children, prosperity, max_population=None):
        self.id = vid
        self.region_id = region_id
        self.faction_idx = faction_idx
        self.name = name
        self.pos = pos                 # (x, y) grid cell
        self.farm_output = farm_output
        self.population = population   # current headcount -- starts around 20% of
                                       # max_population, climbs slowly (see
                                       # resources.POPULATION_GROWTH_RATE)
        self.adults = adults
        self.children = children
        # See Settlement.max_population -- same meaning, same old-save
        # getattr fallback story.
        self.max_population = max_population
        self.prosperity = prosperity   # 0..100 meter — see resources._update_prosperity
        # This village's own stockpile (Phase 10) — same shared-space-
        # budget storage a Settlement has (Phase 9), just a smaller base
        # capacity and no Granary/Warehouse of its own to expand it.
        self.resources = {}
        # See Settlement.turns_without_food/turns_without_firewood -- same
        # starvation/freezing-grace counters, same meaning, for a
        # Village's own population.
        self.turns_without_food = 0
        self.turns_without_firewood = 0


class Region:
    """A sub-region of a faction's territory. The unit of control that will be
    fought over once territory can change hands. Stats derive from the fertility
    of the land it covers."""

    def __init__(self, cid, faction_idx, name):
        self.id = cid
        self.faction_idx = faction_idx     # owning faction (index into factions)
        self.name = name
        self.cells = []                    # list of (x, y) grid cells
        self.center = (0.5, 0.5)           # normalized 0..1
        self.bbox = (0, 0, 1, 1)           # grid coords (x0, y0, x1, y1)
        self.stats = {}                    # area, fertility %
        # Economy (see app/world/resources.py): biome_counts/dominant_climate
        # are static geography, cached once here; settle_proximity is filled
        # in after settlements exist. `resources` is this region's most
        # recent turn's yield.
        self.biome_counts = {}
        self.dominant_climate = "temperate"
        self.settle_proximity = 0.5
        self.resources = {}
        # Livestock (see app/world/resources.py's Phase 7): animal name ->
        # live head count, grown/shrunk once a year via births/natural
        # deaths/slaughter -- unlike `resources` above (recomputed fresh
        # every turn), this genuinely persists and accumulates over time.
        self.livestock = {}
        # Progressive expansion (see app/world/expansion.py): garrison rating
        # for UNCLAIMED land (irrelevant once claimed), whether this region's
        # settlements/villages have been generated yet (False for every
        # UNCLAIMED region until claimed), and a claim-retry cooldown after a
        # failed attempt.
        self.wildland_strength = 0
        self.settlements_generated = False
        self.claim_cooldown_until_turn = 0

    def finalize(self, world):
        n = max(1, len(self.cells))
        xs = [p[0] for p in self.cells]
        ys = [p[1] for p in self.cells]
        self.center = (sum(xs) / n / world.w, sum(ys) / n / world.h)
        self.bbox = (min(xs), min(ys), max(xs) + 1, max(ys) + 1)
        fert_sum = sum(world.fertility[y][x] for x, y in self.cells)
        self.stats = {"area": len(self.cells),
                      "fertility": round(100 * fert_sum / n)}

        biome_counts = defaultdict(int)
        climate_counts = defaultdict(int)
        for x, y in self.cells:
            biome = world.biome_grid[y][x]
            if biome:
                biome_counts[biome] += 1
            climate = world.climate_grid[y][x]
            if climate:
                climate_counts[climate] += 1
        self.biome_counts = dict(biome_counts)
        self.dominant_climate = (max(climate_counts, key=climate_counts.get)
                                  if climate_counts else "temperate")


def _generate_all_regions(world, rng, base_cost, land_cells):
    """Bisect the *entire* landmass into regions before any faction owns
    anything — region geometry becomes the fixed unit of territory that
    ownership (starting footholds, later claims/conquests) maps onto,
    instead of being carved out of land a faction already owns. Seeds are
    spaced across all land, then grown with the same river-aware weighted
    flooding used for country borders, so region borders follow rivers too.
    Every region starts UNCLAIMED; callers assign faction_idx afterward."""
    n_regions = max(1, len(land_cells) // 200)
    min_d = max(3.0, (len(land_cells) / n_regions) ** 0.5 * 0.7)
    shuffled = land_cells[:]
    rng.shuffle(shuffled)
    seeds = []
    for p in shuffled:
        if len(seeds) >= n_regions:
            break
        if all((p[0] - s[0]) ** 2 + (p[1] - s[1]) ** 2 >= min_d * min_d
               for s in seeds):
            seeds.append(p)
    if not seeds:
        seeds = [land_cells[0]]

    landset = set(land_cells)
    assign = _grow_weighted(world, landset, seeds, base_cost, _REGION_RIVER_PEN)
    for p in land_cells:                # disconnected bits -> nearest seed
        if p not in assign:
            assign[p] = min(range(len(seeds)),
                            key=lambda i: (p[0] - seeds[i][0]) ** 2
                            + (p[1] - seeds[i][1]) ** 2)

    namer = make_region_namer(rng)
    objs = [Region(i, UNCLAIMED, namer()) for i in range(len(seeds))]
    for (x, y), i in assign.items():
        world.region_grid[y][x] = i
        objs[i].cells.append((x, y))
    for cobj in objs:
        cobj.finalize(world)
        world.regions.append(cobj)


OCEAN = -1
UNCLAIMED = -2   # land not yet claimed by any faction — see _assign_starting_footholds

# Fertility weighting — how much each factor contributes (should sum to 1).
_FERT_MOISTURE = 0.40     # rainfall (noise layer)
_FERT_LOWLAND = 0.30      # low elevation good; mountains barren
_FERT_WATER = 0.30        # closeness to water (irrigation)
_WATER_FALLOFF = 13.0     # cells; how fast the water bonus decays inland


# --- value noise -----------------------------------------------------------
# The world wraps east-west (see app/world/wrap.py) -- x=width-1 is a real
# neighbor of x=0 -- so every noise field sampled across the x axis (height,
# moisture, region/country border cost) needs to be genuinely PERIODIC in x
# with period `width`, or scrolling the camera across the seam would show a
# visible discontinuity (an uncorrelated noise value jump) even in the
# ocean cells that mask the coastline seam (see _pick_continent_centers'
# margin, which keeps LAND off the seam but doesn't touch the underlying
# noise field cells themselves, which still get sampled/colored). y never
# wraps, so y-hashing is untouched.
def _vhash(ix, iy, seed, period_x=None):
    if period_x is not None:
        ix = ix % period_x
    n = (ix * 73856093) ^ (iy * 19349663) ^ (seed * 83492791)
    n &= 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    n ^= (n >> 16)
    return (n & 0xFFFF) / 0xFFFF


def _vnoise(x, y, seed, period_x=None):
    """Value noise at (x, y). `period_x`, if given, is the integer lattice
    period _vhash wraps ix by -- pass it together with an x already rescaled
    via _periodic_freq (below) so that x=width samples the exact same
    lattice cell as x=0, closing the loop with no seam artifact."""
    x0, y0 = math.floor(x), math.floor(y)
    fx, fy = x - x0, y - y0
    sx = fx * fx * (3 - 2 * fx)
    sy = fy * fy * (3 - 2 * fy)
    v00 = _vhash(x0, y0, seed, period_x)
    v10 = _vhash(x0 + 1, y0, seed, period_x)
    v01 = _vhash(x0, y0 + 1, seed, period_x)
    v11 = _vhash(x0 + 1, y0 + 1, seed, period_x)
    a = v00 + (v10 - v00) * sx
    b = v01 + (v11 - v01) * sx
    return a + (b - a) * sy


def _periodic_freq(width, freq):
    """(effective_freq, period_x) for sampling _vnoise's x argument so it
    tiles exactly across a map `width` cells wide at the requested `freq`.
    period_x is the nearest integer lattice period to width*freq (must be
    an integer since _vhash wraps a lattice coordinate, not a real number);
    effective_freq is the tiny rescale of `freq` needed so that x=width
    lands exactly on lattice coordinate `period_x` -- imperceptibly
    different from `freq` for any reasonable width, but what makes x=0 and
    x=width hash identically."""
    period_x = max(1, round(width * freq))
    return period_x / width, period_x


def _hex(r, g, b):
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}"


def _hsv_hex(h_deg, s, v):
    r, g, b = colorsys.hsv_to_rgb((h_deg % 360) / 360.0, s, v)
    return _hex(r * 255, g * 255, b * 255)


_NEIGH8 = [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]

# Border shaping. Region growth pays a per-cell traversal cost = 1 + noise
# (for chaotic wander) with a big surcharge for crossing rivers/lakes, so the
# frontiers where two regions meet settle onto rivers and lakeshores.
#
# Three octaves, weighted toward the *finer* end on purpose: a border's local
# shape is most sensitive to noise right where two regions' accumulated costs
# are nearly tied, so short-wavelength detail is what actually produces jagged,
# non-monotonic frontiers (bites, pockets, thin spurs) — a slow-varying octave
# alone just gives the border a gentle, still-mostly-straight bend.
_WARP_COST = 7.0              # how much the noise perturbs cost (border wiggle)
_COST_FREQ_LO = 0.030         # broad wander (~33-cell wavelength)
_COST_FREQ_MID = 0.085        # medium jaggedness (~12-cell wavelength)
_COST_FREQ_HI = 0.35          # fine jaggedness (~3-cell wavelength)
_COUNTRY_RIVER_PEN = 20.0     # surcharge to cross water when growing countries
_REGION_RIVER_PEN = 12.0      # ... and (weaker) when growing regions


def _cost_field(world, nseed):
    """Per-cell base traversal cost: 1 plus three octaves of noise (broad to
    fine), so grown borders wander chaotically instead of running straight.
    Weighted toward the fine end: that's what actually produces jagged, bitten
    -into frontiers, since the border's local shape is decided right at the
    zone where two regions' accumulated costs are nearly tied."""
    w, h = world.w, world.h
    s1, s2, s3 = nseed ^ 0xABCDEF, nseed ^ 0x054321, nseed ^ 0x7A5D3E1
    fx1, p1 = _periodic_freq(w, _COST_FREQ_LO)
    fx2, p2 = _periodic_freq(w, _COST_FREQ_MID)
    fx3, p3 = _periodic_freq(w, _COST_FREQ_HI)
    cost = [[1.0] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            n = (0.20 * _vnoise(x * fx1, y * _COST_FREQ_LO, s1, p1)
                 + 0.30 * _vnoise(x * fx2, y * _COST_FREQ_MID, s2, p2)
                 + 0.50 * _vnoise(x * fx3, y * _COST_FREQ_HI, s3, p3))
            cost[y][x] = 1.0 + _WARP_COST * n
    return cost


def _grow_weighted(world, cellset, seeds, base_cost, river_pen):
    """Multi-source Dijkstra over `cellset`. Each region floods outward paying
    base_cost per cell plus `river_pen` to enter a river/lake cell, so region
    boundaries come to rest along waterways. Returns {cell: seed index}."""
    import heapq
    river, lake = world.river_cells, world.lake_cells
    dist = {}
    owner = {}
    pq = []
    for i, s in enumerate(seeds):
        dist[s] = 0.0
        owner[s] = i
        heapq.heappush(pq, (0.0, s[0], s[1]))
    while pq:
        d, x, y = heapq.heappop(pq)
        if d > dist.get((x, y), 1e18):
            continue
        oi = owner[(x, y)]
        for dx, dy in _NEIGH8:
            nb = (x + dx, y + dy)
            if nb not in cellset:
                continue
            step = base_cost[nb[1]][nb[0]]
            if nb in river or nb in lake:
                step += river_pen
            nd = d + step
            if nd < dist.get(nb, 1e18):
                dist[nb] = nd
                owner[nb] = oi
                heapq.heappush(pq, (nd, nb[0], nb[1]))
    return owner


# Progressive expansion: how strongly an unclaimed region's neutral garrison
# scales with distance from the nearest capital (weak near everyone's start,
# so early expansion is fast; strong deep in the interior, so it takes a
# built-up military to reach) and with the land's own fertility (better land
# is defended harder) — plus a little jitter so it's not perfectly uniform.
WILDLAND_BASE = 20
WILDLAND_DIST_SCALE = 0.6
WILDLAND_FERT_BONUS = 15
WILDLAND_JITTER = 0.15
MIN_FOOTHOLD_CELLS = 120   # every faction starts owning at least this many cells


def _seed_wildland_strength(world, rng, capitals):
    """Rate every region's neutral-garrison strength before any faction
    claims anything — see the WILDLAND_* constants above."""
    for region in world.regions:
        cx, cy = region.center[0] * world.w, region.center[1] * world.h
        dist = min(math.hypot(cx - px, cy - py) for px, py in capitals)
        fert = region.stats.get("fertility", 50) / 100.0
        base = (WILDLAND_BASE + WILDLAND_DIST_SCALE * dist
                + WILDLAND_FERT_BONUS * fert)
        jitter = 1.0 + rng.uniform(-WILDLAND_JITTER, WILDLAND_JITTER)
        region.wildland_strength = max(5, round(base * jitter))


def _adjacent_region_ids(world, region):
    """Region ids sharing a cell edge with `region` (4-neighbor)."""
    ids = set()
    w, h, cg = world.w, world.h, world.region_grid
    for x, y in region.cells:
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h:
                cid = cg[ny][nx]
                if cid >= 0 and cid != region.id:
                    ids.add(cid)
    return ids


def _nearest_unclaimed_region(world, pos):
    """Fallback for the rare case (tiny test maps, unlucky capital spacing)
    where a capital's home region is already claimed by another faction:
    the closest still-UNCLAIMED region by straight-line center distance."""
    x, y = pos
    best, best_d = None, 1e18
    for region in world.regions:
        if region.faction_idx >= 0:
            continue
        cx, cy = region.center[0] * world.w, region.center[1] * world.h
        d = (cx - x) ** 2 + (cy - y) ** 2
        if d < best_d:
            best_d, best = d, region.id
    return best


def _assign_starting_footholds(world, capitals, min_cells=MIN_FOOTHOLD_CELLS):
    """Hand each faction only its capital's home region (plus enough
    bordering unclaimed regions to reach `min_cells`, largest first) —
    everything else on the map stays UNCLAIMED for players/AI to expand
    into over time, instead of the old "claim the whole map instantly"
    flood-fill."""
    for idx, (cx, cy) in enumerate(capitals):
        home_id = world.region_grid[cy][cx]
        if home_id < 0 or world.regions[home_id].faction_idx >= 0:
            home_id = _nearest_unclaimed_region(world, (cx, cy))
        if home_id is None:
            continue   # ran out of unclaimed land — extremely unlikely
        claimed = {home_id}
        total = len(world.regions[home_id].cells)
        while total < min_cells:
            frontier = set()
            for cid in claimed:
                frontier |= _adjacent_region_ids(world, world.regions[cid])
            frontier = {cid for cid in frontier - claimed
                       if world.regions[cid].faction_idx < 0}
            if not frontier:
                break
            best = max(frontier, key=lambda cid: len(world.regions[cid].cells))
            claimed.add(best)
            total += len(world.regions[best].cells)
        for cid in claimed:
            region = world.regions[cid]
            region.faction_idx = idx
            for x, y in region.cells:
                world.owner[y][x] = idx


_LAKE_DEPTH = 0.012       # filled-minus-original elevation that counts as lake


def _generate_hydrology(world, land, rng):
    """Proper drainage hydrology so rivers make sense:

    1. Priority-flood fills depressions, guaranteeing every land cell drains to
       the sea (no rivers cut short at random pits).
    2. Basins that had to be filled become lakes (small/medium/large).
    3. D8 flow directions + flow accumulation over the filled terrain; a cell
       becomes river only once enough upstream area drains through it — so
       rivers emerge in valleys and grow downstream instead of jutting out of
       nowhere. Tributaries merge into trunks that run to the coast or a lake.
    """
    import heapq
    w, h, H = world.w, world.h, world.height

    # 1. priority-flood fill (Barnes) — filled DEM drains monotonically to sea.
    filled = [row[:] for row in H]
    done = [[not land[y][x] for x in range(w)] for y in range(h)]
    pq = []
    for y in range(h):
        for x in range(w):
            if not land[y][x]:                 # ocean cells are the outlets
                heapq.heappush(pq, (H[y][x], x, y))
    eps = 1e-5
    while pq:
        e, x, y = heapq.heappop(pq)
        for dx, dy in _NEIGH8:
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and not done[ny][nx]:
                done[ny][nx] = True
                ne = H[ny][nx] if H[ny][nx] > e + eps else e + eps
                filled[ny][nx] = ne
                heapq.heappush(pq, (ne, nx, ny))

    # 2. lakes: land that had to be raised noticeably to drain sits underwater.
    lake = set()
    for y in range(h):
        for x in range(w):
            if land[y][x] and filled[y][x] - H[y][x] > _LAKE_DEPTH:
                lake.add((x, y))

    # 3a. D8 flow direction on the filled DEM (steepest descent).
    land_cells = [(x, y) for y in range(h) for x in range(w) if land[y][x]]
    down = {}
    for x, y in land_cells:
        best, be = None, filled[y][x]
        for dx, dy in _NEIGH8:
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h:
                fe = filled[ny][nx] if land[ny][nx] else H[ny][nx]
                if fe < be:
                    be, best = fe, (nx, ny)
        down[(x, y)] = best

    # 3b. flow accumulation: high cells first, push their water downstream.
    acc = {p: 1.0 for p in land_cells}
    for p in sorted(land_cells, key=lambda p: filled[p[1]][p[0]], reverse=True):
        d = down[p]
        if d is not None and land[d[1]][d[0]]:
            acc[d] += acc[p]

    thresh = max(35, len(land_cells) // 550)
    river_cells = {p for p in land_cells if acc[p] >= thresh and p not in lake}

    # 3c. build polylines: start at river heads, follow flow to the mouth.
    drains_in = {down[p] for p in river_cells if down[p] in river_cells}
    sources = [p for p in river_cells if p not in drains_in]
    rivers = []
    for s in sources:
        cells = [s]
        cur = s
        for _ in range(4 * (w + h)):
            d = down[cur]
            if d is None:
                break
            cells.append(d)
            if not land[d[1]][d[0]] or d in lake:   # reached sea or a lake
                break
            cur = d
        if len(cells) >= 2:
            rivers.append({"cells": cells,
                           "flow": max(acc.get(c, 1.0) for c in cells
                                       if land[c[1]][c[0]])})

    world.rivers = rivers
    world.river_cells = river_cells
    world.lake_cells = lake


def _bfs_distance(world, sources):
    """Grid BFS distance (4-neighbor steps) from a set of source cells."""
    w, h = world.w, world.h
    INF = 10 ** 9
    dist = [[INF] * w for _ in range(h)]
    dq = deque()
    for x, y in sources:
        if 0 <= x < w and 0 <= y < h:
            dist[y][x] = 0
            dq.append((x, y))
    while dq:
        x, y = dq.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and dist[ny][nx] > dist[y][x] + 1:
                dist[ny][nx] = dist[y][x] + 1
                dq.append((nx, ny))
    return dist


# Shared spatial-hash "occupancy" grid so settlement/village placement can
# repel points from *other* factions/regions too, not just their own —
# without it, e.g. two factions' frontier castles (which each independently
# seek the border) can land right on top of each other. Bucket size is fixed
# and decoupled from any one call's spacing value; the search radius scales
# per call instead, so one grid works for every spacing (7-14 for
# settlements, variable for villages).
_OCCUPANCY_CELL = 8.0


def _bucket_key(x, y):
    return (int(x // _OCCUPANCY_CELL), int(y // _OCCUPANCY_CELL))


def _too_close(occupied, x, y, min_dist):
    min_d2 = min_dist * min_dist
    r = int(min_dist // _OCCUPANCY_CELL) + 1
    cx, cy = _bucket_key(x, y)
    for bx in range(cx - r, cx + r + 1):
        for by in range(cy - r, cy + r + 1):
            for px, py in occupied.get((bx, by), ()):
                if (px - x) ** 2 + (py - y) ** 2 < min_d2:
                    return True
    return False


def _occupy(occupied, x, y):
    occupied.setdefault(_bucket_key(x, y), []).append((x, y))


def _too_close_any(world, x, y, min_dist):
    """_too_close against *both* the settlement (_settle_occupied) and
    village (_village_occupied) auto-placement occupancy hashes. These are
    two separate dicts (settlements are generated before villages, so each
    needed its own), but a settlement and a village should never be able to
    land on/next to each other regardless of which system placed which
    first or which call placed it — see _mark_occupied_both."""
    settle_occ = getattr(world, "_settle_occupied", None)
    if settle_occ is not None and _too_close(settle_occ, x, y, min_dist):
        return True
    village_occ = getattr(world, "_village_occupied", None)
    if village_occ is not None and _too_close(village_occ, x, y, min_dist):
        return True
    return False


def _mark_occupied_both(world, x, y):
    """Register (x, y) as occupied in whichever of the settlement/village
    occupancy hashes currently exist — so a settlement placed here is
    correctly avoided by every future village placement and vice versa.
    (_village_occupied doesn't exist yet the first time this runs at
    world-gen, since settlements are generated before villages.)"""
    settle_occ = getattr(world, "_settle_occupied", None)
    if settle_occ is not None:
        _occupy(settle_occ, x, y)
    village_occ = getattr(world, "_village_occupied", None)
    if village_occ is not None:
        _occupy(village_occ, x, y)


def _init_settlement_proximity_fields(world, rng):
    """Build the shared proximity fields + occupancy hash settlement
    placement scores against, and cache them on `world` — computed once
    (O(w*h)) rather than per-claim, so a settlement placed in a region
    claimed turn 400 scores against the same live geography as one placed at
    world-gen, without redoing a whole-map BFS every time."""
    w, h = world.w, world.h
    ocean_cells = [(x, y) for y in range(h) for x in range(w)
                   if world.owner[y][x] == OCEAN]
    coast_d = _bfs_distance(world, ocean_cells)
    water_d = _bfs_distance(world, list(world.river_cells | world.lake_cells))
    border_sources = []
    for y in range(h):
        for x in range(w):
            o = world.owner[y][x]
            if o < 0:
                continue
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < w and 0 <= ny < h:
                    o2 = world.owner[ny][nx]
                    if o2 >= 0 and o2 != o:
                        border_sources.append((x, y))
                        break
    border_d = _bfs_distance(world, border_sources)

    # NOTE: deliberately not caching a namer here — make_settlement_namer
    # returns a closure, and closures can't be pickled (app/core/save.py
    # pickles the whole World). Each caller of _place_settlements_for_faction
    # builds its own short-lived namer instead (see _generate_settlements and
    # expansion.settle_newly_claimed_region) — same "fresh per call, no
    # global uniqueness guarantee" tradeoff _place_villages_for_region
    # already makes, and for the same reason.
    world._settle_coast_d = coast_d
    world._settle_water_d = water_d
    world._settle_border_d = border_d
    world._settle_occupied = {}


def _place_settlements_for_faction(world, rng, fac_idx, cells, namer, fixed_counts=None):
    """Score and place cities/castles/towns for one faction's cells, using
    the shared proximity fields/occupancy hash `_init_settlement_proximity_
    fields` cached on `world`. Reusable both for the full initial pass (one
    call per faction's starting foothold) and, mid-game, for a single newly
    claimed region's cells (see app/world/expansion.py).

    `fixed_counts`, when given (a {kind: count} dict), overrides the usual
    area-scaled min/max/per_cells count for whichever kinds it names — any
    kind it *doesn't* name still falls back to the normal area-scaled
    formula. Two callers: the starting foothold passes
    STARTING_SETTLEMENT_COUNTS (names all three kinds, so every faction
    begins with the same small seed regardless of how large its home region
    turned out to be); newly claimed wildland (see
    app/world/expansion.py's settle_newly_claimed_region) passes
    {"city": 0, "town": 0, "castle": 0} — no free City/Town/Castle, since
    claiming land was never how you got one of those for free in the first
    place."""
    from app.world.resources import seed_prosperity
    sea = world.sea_level
    span = (1.0 - sea) or 1.0
    coast_d = world._settle_coast_d
    water_d = world._settle_water_d
    border_d = world._settle_border_d
    prox = lambda d, reach: math.exp(-d / reach)   # 1 at the feature, ->0 away
    species = world.factions[fac_idx].meta["species"]

    for kind, t in SETTLEMENT_TYPES.items():
        if fixed_counts is not None and kind in fixed_counts:
            count = fixed_counts[kind]
        else:
            count = max(t["min"], min(t["max"], len(cells) // t["per_cells"]))
        scored = []
        for x, y in cells:
            if (x, y) in world.river_cells:
                continue                       # don't build in the river
            elev = max(0.0, min(1.0, (world.height[y][x] - sea) / span))
            s = (t["fert_w"] * world.fertility[y][x]
                 + t["river_w"] * prox(water_d[y][x], 4.0)
                 + t["coast_w"] * prox(coast_d[y][x], 4.0)
                 + t["border_w"] * prox(border_d[y][x], 5.0)
                 + t["elev_w"] * elev
                 + 0.1 * rng.random())         # tie-break jitter
            scored.append((s, x, y))
        scored.sort(reverse=True)

        placed = 0
        for s, x, y in scored:
            if placed >= count:
                break
            if _too_close_any(world, x, y, t["spacing"]):
                continue
            tax_income = round(rng.uniform(*SETTLEMENT_TAX_INCOME[kind]))
            population, adults, children, max_population = _roll_population(rng, kind)
            prosperity = seed_prosperity()
            region_id = world.region_grid[y][x]
            st = Settlement(len(world.settlements), kind, namer(kind, species),
                            (x, y), fac_idx, region_id, tax_income,
                            population, adults, children, prosperity, max_population)
            world.settlements.append(st)
            _mark_occupied_both(world, x, y)
            world.factions[fac_idx].meta["settlements"].append(st.id)
            if 0 <= region_id < len(world.regions):
                world.regions[region_id].meta_settlements.append(st.id)
            placed += 1


def _recompute_settle_proximity_all(world):
    """settle_proximity: how close each region is to *any* settlement (0..1,
    1 = right on top of one) — feeds the "remote areas are harder to acquire
    resources from" rule in app/world/resources.py. Full-map BFS; cheap
    enough at world-gen time (called once), not used again afterward — a
    single newly claimed region instead uses the cheaper straight-line
    version, territory._recompute_settle_proximity."""
    settle_d = (_bfs_distance(world, [st.pos for st in world.settlements])
                if world.settlements else None)
    for region in world.regions:
        if settle_d is None:
            region.settle_proximity = 0.5
            continue
        avg_d = sum(settle_d[y][x] for x, y in region.cells) / len(region.cells)
        region.settle_proximity = math.exp(-avg_d / 10.0)


def _generate_settlements(world, rng):
    """Found cities, castles and towns for every faction that currently owns
    land (their starting foothold — UNCLAIMED regions get settlements later,
    when claimed). Counts scale with territory size; placement follows the
    map: cities seek fertile, riverside or coastal land, castles guard
    frontiers and high ground, towns fill the countryside. Each settlement
    rolls its per-turn upkeep (population/garrison draw on the faction's
    resource stockpile); production itself is region-level, computed later
    from biome/climate/season."""
    w, h = world.w, world.h
    for c in world.regions:
        c.meta_settlements = []
    for f in world.factions:
        f.meta["settlements"] = []

    _init_settlement_proximity_fields(world, rng)
    namer = make_settlement_namer(rng)

    cells_by_fac = defaultdict(list)
    for y in range(h):
        for x in range(w):
            o = world.owner[y][x]
            if o >= 0 and (x, y) not in world.lake_cells:
                cells_by_fac[o].append((x, y))

    for fac_idx, cells in cells_by_fac.items():
        _place_settlements_for_faction(world, rng, fac_idx, cells, namer,
                                       fixed_counts=STARTING_SETTLEMENT_COUNTS)
        for cid in world.factions[fac_idx].meta.get("regions", []):
            world.regions[cid].settlements_generated = True

    _recompute_settle_proximity_all(world)


# Village generation. Count scales with region size: from ~3 villages for a
# small region in a small country up to ~50 for a large region in a huge one.
_VILLAGE_CELLS_PER = 22   # ~cells per village before min/max clamping
_VILLAGE_MIN = 3
_VILLAGE_MAX = 50
_VILLAGE_FERT_W = 1.0
_VILLAGE_WATER_W = 0.55
_VILLAGE_WATER_REACH = 5.0
_VILLAGE_FARM_RANGE = (10, 26)   # base farm output before the fertility scalar
_VILLAGE_FERT_PATCH = 2          # radius (cells) averaged for "land occupied"
STARTING_VILLAGE_COUNT = 3       # every faction's starting foothold gets exactly
                                  # this many, regardless of its region's area —
                                  # see _place_villages_for_region's `fixed_n`


def _mst_edges(points):
    """Simple O(n^2) Prim's minimum spanning tree over 2D grid points. Returns
    a list of (i, j) index pairs — enough edges to connect every point with no
    cycles, i.e. the sparsest possible road network."""
    n = len(points)
    if n < 2:
        return []
    in_tree = [False] * n
    in_tree[0] = True
    dist = [(points[0][0] - p[0]) ** 2 + (points[0][1] - p[1]) ** 2 for p in points]
    parent = [0] * n
    edges = []
    for _ in range(n - 1):
        best, best_d = -1, 1e18
        for i in range(n):
            if not in_tree[i] and dist[i] < best_d:
                best_d, best = dist[i], i
        if best == -1:
            break
        in_tree[best] = True
        edges.append((parent[best], best))
        bx, by = points[best]
        for i in range(n):
            if not in_tree[i]:
                d = (bx - points[i][0]) ** 2 + (by - points[i][1]) ** 2
                if d < dist[i]:
                    dist[i] = d
                    parent[i] = best
    return edges


def _init_village_fields(world):
    """Shared water-distance field + occupancy hash for village placement,
    cached on `world` — same "compute once, reuse per-claim later" pattern
    as `_init_settlement_proximity_fields`."""
    world._village_water_d = _bfs_distance(
        world, list(world.river_cells | world.lake_cells))
    world._village_occupied = {}
    for st in world.settlements:
        _occupy(world._village_occupied, *st.pos)


def _place_villages_for_region(world, rng, region, fixed_n=None):
    """Sprinkle farming villages within one region — 3 for a small region,
    up to 50 for a large one — each producing farm output tied to the
    fertility of the land it sits on, linked by an MST of simple dirt roads.
    Reusable both for the full initial pass (one call per starting region)
    and, mid-game, for a single newly claimed region (see
    app/world/expansion.py).

    `fixed_n`, when given, overrides the usual area-scaled village count —
    used for the starting foothold (STARTING_VILLAGE_COUNT) so every
    faction begins with the same small handful regardless of its home
    region's actual size; ongoing expansion (fixed_n=None) keeps scaling
    with the newly claimed region's area as before."""
    from app.world.resources import seed_prosperity
    w, h = world.w, world.h
    water_d = world._village_water_d
    # A fresh namer per region: villages are only ever viewed one region at a
    # time, so names need only be unique within a region (a handful to ~50),
    # not across the whole world's thousands of villages.
    namer = make_settlement_namer(rng)
    species = world.factions[region.faction_idx].meta["species"]
    land_cells = [(x, y) for x, y in region.cells
                  if (x, y) not in world.river_cells
                  and (x, y) not in world.lake_cells]
    if not land_cells:
        region.villages = []
        world.roads_by_region[region.id] = []
        return

    area = len(region.cells)
    if fixed_n is not None:
        n = min(fixed_n, len(land_cells))
    else:
        n = max(_VILLAGE_MIN, min(_VILLAGE_MAX, round(area / _VILLAGE_CELLS_PER)))
        n = min(n, len(land_cells))

    scored = []
    for x, y in land_cells:
        s = (_VILLAGE_FERT_W * world.fertility[y][x]
             + _VILLAGE_WATER_W * math.exp(-water_d[y][x] / _VILLAGE_WATER_REACH)
             + 0.15 * rng.random())          # tie-break jitter
        scored.append((s, x, y))
    scored.sort(reverse=True)

    spacing = max(1.5, math.sqrt(area / max(1, n)) * 0.55)
    placed = []
    for s, x, y in scored:
        if len(placed) >= n:
            break
        if _too_close_any(world, x, y, spacing):
            continue
        placed.append((x, y))
        _mark_occupied_both(world, x, y)

    vids = []
    for x, y in placed:
        # "land occupied": average fertility over a small patch around the
        # village, not just the single cell, so farm output reflects the
        # surrounding fields rather than one pixel of terrain.
        samples = []
        r = _VILLAGE_FERT_PATCH
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                nx, ny = x + dx, y + dy
                if (0 <= nx < w and 0 <= ny < h
                        and world.region_grid[ny][nx] == region.id):
                    samples.append(world.fertility[ny][nx])
        local_fert = sum(samples) / len(samples) if samples else world.fertility[y][x]
        farm = round(rng.uniform(*_VILLAGE_FARM_RANGE) * (0.5 + 1.2 * local_fert))
        population, adults, children, max_population = _roll_population(rng, "village")
        prosperity = seed_prosperity()
        v = Village(len(world.villages), region.id, region.faction_idx,
                   namer("village", species), (x, y), farm,
                   population, adults, children, prosperity, max_population)
        world.villages.append(v)
        vids.append(v.id)

    region.villages = vids

    # Local roads: an MST over the villages plus *every* settlement in the
    # region (city/castle/town alike — previously only the first settlement
    # was added, so a second town or castle was left with no road at all),
    # so the whole network ties every settlement into town. Each edge's
    # tier is decided by what it connects, not by region wealth: a road
    # touching a village is a humble Dirt farm track; a road linking two
    # settlements (city/castle/town) is a proper Stone trunk road — see
    # app/ui/map_view.py's _draw_roads for the rendering side.
    points = [world.villages[i].pos for i in vids]
    points += [world.settlements[sid].pos for sid in region.meta_settlements]
    is_settlement = [False] * len(vids) + [True] * len(region.meta_settlements)
    edges = _mst_edges(points)
    world.roads_by_region[region.id] = [
        (points[a], points[b], "stone" if (is_settlement[a] and is_settlement[b]) else "dirt")
        for a, b in edges]


def _generate_villages(world, rng):
    """Sprinkle small farming villages into every currently-owned region's
    starting foothold (UNCLAIMED regions get villages later, when claimed —
    see app/world/expansion.py). A starting foothold can span more than one
    region (_assign_starting_footholds folds in extra bordering regions
    when the capital's home region alone falls short of MIN_FOOTHOLD_CELLS)
    — STARTING_VILLAGE_COUNT is a total for the whole foothold, not per
    region, so all of it lands in one "home" region and any padding
    regions start with none. That's normally the capital's own region, but
    a region is a Voronoi-style region independent of the capital's exact
    cell, so it can end up entirely lake/river with no land at all to place
    on — in that rare case, fall back to the largest owned region that
    actually has land, rather than silently placing zero villages."""
    _init_village_fields(world)

    def has_land(region):
        return any(cell not in world.river_cells and cell not in world.lake_cells
                  for cell in region.cells)

    for faction in world.factions:
        regions = faction.meta.get("regions", [])
        if not regions:
            continue
        cx, cy = faction.meta["capital"]
        home_id = world.region_grid[cy][cx]
        if home_id not in regions or not has_land(world.regions[home_id]):
            landed = [cid for cid in regions if has_land(world.regions[cid])]
            home_id = (max(landed, key=lambda cid: len(world.regions[cid].cells))
                      if landed else None)
        for cid in regions:
            n = STARTING_VILLAGE_COUNT if cid == home_id else 0
            _place_villages_for_region(world, rng, world.regions[cid], fixed_n=n)


# Long-haul trade route pathfinding: used by app/world/trade.py both for the
# built-from-both-ends land construction (see TradeRouteProject) and the
# automatic sea-lane fallback. Real weighted Dijkstra, not a straight line,
# so a route can never cut straight through a mountain range or across dry
# land — it has to wind around high ground the way a real road would, or
# (for sea lanes) stay on open water the whole way.
_ROAD_ELEV_START = 0.62   # elevation (0..1) above which roads start avoiding ground
_ROAD_ELEV_PEN = 60.0     # steepness of that avoidance — pushes roads around peaks
_ROAD_MOUNTAIN_MULT = 1.5   # Mountain-biome cells cost 50% more outright (real quarrying/
                            # grading expense, not just the elevation curve above) --
                            # on top of, not instead of, the elevation penalty, so a
                            # low-relief mountain-biome cell (e.g. a foothill just past
                            # the classification threshold) still costs a bit extra even
                            # where the elevation curve alone wouldn't yet notice it
_ROAD_RIVER_PEN = 25.0    # crossing a river costs extra (a ford/bridge), not blocked --
                          # steep enough that a route only actually crosses when
                          # there's genuinely no reasonable way around (raised from
                          # 6.0, which let roads shrug off small, easily-avoidable
                          # crossings for only a few cells' worth of detour)
_ROAD_FOREIGN_TERRITORY_PEN = 20.0   # building a road across land you don't own
                                     # costs extra (see _elev_cost's faction_idx
                                     # param) -- not blocked, so a faction boxed
                                     # into an awkward shape by its neighbors can
                                     # still always connect its own settlements
_SEA_COAST_REACH = 3      # cells from open water a settlement still counts as a port
_DIAG = 2 ** 0.5


def _path_dijkstra(cellset, cost_fn, start, goal, width):
    """Single-source/single-target Dijkstra over `cellset` (a set of (x,y)
    cells), 8-directional, diagonal steps costing sqrt(2) as much as
    orthogonal ones so the resulting path is geometrically honest. Returns the
    list of cells from start to goal (inclusive), or None if goal can't be
    reached without leaving `cellset`.

    `width` is required (not optional) because the map wraps east-west (see
    app/world/wrap.py): a neighbor step's x is wrapped via wrap_x before
    checking cellset membership, so a cellset built to straddle the seam
    (see wrap.bbox_span_wrap) can actually be traversed across it -- without
    this, stepping from x=width-1 toward x=width would produce a raw (width,
    y) tuple that never matches the (0, y) cell actually in cellset, so the
    search could never cross the seam even if both cells were present."""
    import heapq
    if start not in cellset or goal not in cellset:
        return None
    dist = {start: 0.0}
    parent = {}
    pq = [(0.0, start)]
    while pq:
        d, cur = heapq.heappop(pq)
        if d > dist.get(cur, 1e18):
            continue
        if cur == goal:
            break
        cx, cy = cur
        for dx, dy in _NEIGH8:
            nb = (wrap.wrap_x(cx + dx, width), cy + dy)
            if nb not in cellset:
                continue
            step = cost_fn(nb) * (_DIAG if dx and dy else 1.0)
            nd = d + step
            if nd < dist.get(nb, 1e18):
                dist[nb] = nd
                parent[nb] = cur
                heapq.heappush(pq, (nd, nb))
    if goal not in dist:
        return None
    path = [goal]
    while path[-1] != start:
        path.append(parent[path[-1]])
    path.reverse()
    return path


def _elev_cost(world, base_cost, cell, faction_idx=None, friendly_idxs=None):
    """Land-routing cost: base terrain noise plus a steep penalty for high
    elevation and a toll for crossing a river/lake — shared by every land
    pathfinder in the game (castle-connecting roads in construction.py,
    trade-route construction/regional shipments in trade.py, commander/
    ship movement) so they all route around mountains/rivers identically,
    one formula.

    `faction_idx`, when given, adds a further toll for any cell owned by a
    DIFFERENT single faction (not UNCLAIMED, not this one) — used by road
    pathing (construction.py/expansion.py) and same-faction regional
    shipments (a Village/Settlement trading with another node of its own
    faction, just in a different region, should still prefer staying on
    its own land). `friendly_idxs`, when given instead, generalizes that
    to a SET of factions none of which count as foreign — used by land
    trade routes between two DIFFERENT factions (trade._land_capital_
    path), where "foreign" correctly means a THIRD party's land, not
    either of the two actually trading. Either way this is a preference,
    not a wall: steep enough that a route only actually crosses foreign
    land when there's genuinely no reasonable way around it, same as the
    existing river/mountain tolls above -- a trade route or a commander's
    own movement can still cross it, unlike being flatly forbidden. Left
    at its all-None default for every caller where "whose land is this"
    shouldn't matter at all (a scout can walk anywhere)."""
    x, y = cell
    cost = base_cost[y][x]
    over = world.height[y][x] - _ROAD_ELEV_START
    if over > 0:
        cost += _ROAD_ELEV_PEN * over * over
    if world.biome_grid[y][x] == "mountain":
        cost *= _ROAD_MOUNTAIN_MULT
    if cell in world.river_cells or cell in world.lake_cells:
        cost += _ROAD_RIVER_PEN
    if friendly_idxs is not None:
        owner = world.owner[y][x]
        if owner >= 0 and owner not in friendly_idxs:
            cost += _ROAD_FOREIGN_TERRITORY_PEN
    elif faction_idx is not None:
        owner = world.owner[y][x]
        if owner >= 0 and owner != faction_idx:
            cost += _ROAD_FOREIGN_TERRITORY_PEN
    return cost


def _sea_cost(world, base_cost, cell):
    """Standalone version of the sea-lane routing cost, see `_elev_cost`."""
    x, y = cell
    return 1.0 + 0.4 * base_cost[y][x] / 8.0


def _nearest_ocean_cell(world, pos, max_r=8):
    """Search outward (ring by ring) from `pos` for the closest OCEAN cell —
    a city's notional dock, used as the sea-lane endpoint just offshore."""
    w, h = world.w, world.h
    x0, y0 = pos
    if world.owner[y0][x0] == OCEAN:
        return pos
    for r in range(1, max_r + 1):
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                if max(abs(dx), abs(dy)) != r:
                    continue
                x, y = x0 + dx, y0 + dy
                if 0 <= x < w and 0 <= y < h and world.owner[y][x] == OCEAN:
                    return (x, y)
    return None


def _water_distance(world):
    """Steps from each cell to the nearest water cell (multi-source BFS over
    the ocean). Land cells get their distance-to-coast; water cells get 0."""
    from collections import deque
    w, h = world.w, world.h
    INF = 10 ** 9
    dist = [[INF] * w for _ in range(h)]
    dq = deque()
    for y in range(h):
        for x in range(w):
            # oceans, rivers and lakes all irrigate the land around them
            if (world.owner[y][x] == OCEAN or (x, y) in world.river_cells
                    or (x, y) in world.lake_cells):
                dist[y][x] = 0
                dq.append((x, y))
    while dq:
        x, y = dq.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and dist[ny][nx] > dist[y][x] + 1:
                dist[ny][nx] = dist[y][x] + 1
                dq.append((nx, ny))
    return dist


_MOISTURE_OCTAVES = [(0.045, 1.0), (0.10, 0.5), (0.20, 0.25)]


def _moisture_seed(nseed):
    return nseed ^ 0x9E3779B9        # independent noise for rainfall


def _periodic_octaves(width, octaves):
    """(eff_freq, period_x, orig_freq, amp) per (freq, amp) octave pair --
    call once outside a per-cell loop (see _periodic_freq's own docstring
    for why the x-sample needs both an effective frequency and its lattice
    period) rather than recomputing the same tiny period every cell."""
    return [(*_periodic_freq(width, f), f, a) for f, a in octaves]


def _quick_moisture(x, y, mseed, moisture_octaves):
    """The same per-cell moisture formula _compute_moisture fills the real
    world.moisture grid with, callable standalone for a handful of cells
    before that grid exists yet — see _capital_has_nearby_farmland, which
    needs it well before step 5's full moisture pass runs.
    `moisture_octaves` is precomputed via _periodic_octaves(width,
    _MOISTURE_OCTAVES) by the caller, once, not per cell."""
    m = sum(amp * _vnoise(x * eff_freq, y * freq, mseed, period_x)
           for eff_freq, period_x, freq, amp in moisture_octaves)
    return max(0.0, min(1.0, m / 1.75))


def _compute_moisture(world, nseed):
    """Fill world.moisture (0..1 rainfall noise), land cells only. Factored
    out of fertility so biome/climate classification can share it too."""
    w, h = world.w, world.h
    mseed = _moisture_seed(nseed)
    moisture_octaves = _periodic_octaves(w, _MOISTURE_OCTAVES)
    for y in range(h):
        for x in range(w):
            if world.owner[y][x] == OCEAN or (x, y) in world.lake_cells:
                continue
            world.moisture[y][x] = _quick_moisture(x, y, mseed, moisture_octaves)


def _compute_fertility(world, nseed):
    """Fill world.fertility (0..1). Land only; water stays 0. Combines the
    moisture layer, a lowland bonus (from elevation) and an irrigation
    bonus (from distance to water)."""
    w, h, sea = world.w, world.h, world.sea_level
    dist = _water_distance(world)
    span = (1.0 - sea) or 1.0
    for y in range(h):
        for x in range(w):
            if world.owner[y][x] == OCEAN or (x, y) in world.lake_cells:
                continue                         # lakes are water, not farmland
            elev = max(0.0, min(1.0, (world.height[y][x] - sea) / span))
            lowland = 1.0 - elev                        # coasts/plains > peaks
            water = math.exp(-dist[y][x] / _WATER_FALLOFF)
            fert = (_FERT_MOISTURE * world.moisture[y][x] + _FERT_LOWLAND * lowland
                    + _FERT_WATER * water)
            world.fertility[y][x] = max(0.0, min(1.0, fert))


def _classify_biomes_and_climate(world):
    """Fill world.biome_grid / world.climate_grid (land cells only) from
    elevation relief, moisture, distance to the coast/rivers-and-lakes, and
    a latitude-style "temperature" gradient (warm at the map's vertical
    middle, cold at the top/bottom edges — a stand-in for a real pole
    system, since this world has no globe to wrap around)."""
    from app.world.resources import classify_biome, classify_climate

    w, h, sea = world.w, world.h, world.sea_level
    span = (1.0 - sea) or 1.0
    ocean_cells = [(x, y) for y in range(h) for x in range(w)
                   if world.owner[y][x] == OCEAN]
    coast_d = _bfs_distance(world, ocean_cells) if ocean_cells else None
    water_d = _bfs_distance(world, list(world.river_cells | world.lake_cells))

    for y in range(h):
        latitude_temp = 1.0 - abs(y / h - 0.5) * 2.0
        for x in range(w):
            if world.owner[y][x] == OCEAN or (x, y) in world.lake_cells:
                continue
            relief = max(0.0, min(1.0, (world.height[y][x] - sea) / span))
            moisture = world.moisture[y][x]
            cd = coast_d[y][x] if coast_d is not None else 10 ** 9
            wd = water_d[y][x]
            world.biome_grid[y][x] = classify_biome(relief, moisture, cd, wd)
            world.climate_grid[y][x] = classify_climate(latitude_temp, moisture)


class World:
    """Container the UI renders from."""
    def __init__(self, w, h):
        self.w = w
        self.h = h
        self.owner = [[OCEAN] * w for _ in range(h)]   # faction index or OCEAN
        self.height = [[0.0] * w for _ in range(h)]     # elevation, 0..1
        self.fertility = [[0.0] * w for _ in range(h)]  # 0..1 (land); 0 = water
        self.moisture = [[0.0] * w for _ in range(h)]   # 0..1 rainfall noise (land)
        self.biome_grid = [[None] * w for _ in range(h)]    # biome name or None (ocean)
        self.climate_grid = [[None] * w for _ in range(h)]  # climate name or None
        self.turn = 1
        self.season = "Spring"
        # Bumped whenever region ownership actually changes (see
        # territory.transfer_region) so map_view can skip rebuilding the
        # whole political-mode color raster (an O(w*h) rebuild) on turns
        # where nothing changed hands — most turns.
        self.territory_version = 0
        self.rivers = []               # list of {"cells": [(x,y)...], "flow": f}
        self.river_cells = set()       # all (x, y) cells a river runs through
        self.lake_cells = set()        # (x, y) land cells that are lake surface
        self.regions = []             # list[Region]; index == region id
        self.region_grid = [[-1] * w for _ in range(h)]  # region id, -1 = none
        self.settlements = []          # list[Settlement]; index == id
        self.villages = []             # list[Village]; index == id
        self.roads_by_region = {}      # region_id -> [((x,y),(x,y),"dirt"/"stone"), ...] segments
        # Trade routes exist only once built/opened (app/world/trade.py) —
        # no faction starts pre-connected to any other. trade_routes is the
        # flat list rendering reads (kind/cells, plus a_faction/b_faction);
        # trade_routes_by_pair mirrors it keyed by frozenset({a_idx,b_idx})
        # for O(1) "is this pair connected yet" lookups.
        self.trade_routes = []         # list of {"kind": "land"/"sea", "cells": [...]}
        self.trade_routes_by_pair = {}  # frozenset({a_idx,b_idx}) -> route dict
        self.trade_route_projects = []  # list[TradeRouteProject] — see app/world/trade.py
        self.trade_route_decline_until = {}  # frozenset({a_idx,b_idx}) -> turn a decline expires
        # AI factions proposing a trade route TO the player wait for an
        # actual player response instead of auto-resolving through
        # diplomacy.evaluate_trade_route the way two AI factions do
        # between themselves -- see trade.run_trade_route_ai/
        # accept_trade_route_proposal/decline_trade_route_proposal.
        # list of {"from_idx": int, "turn_proposed": int}, at most one
        # entry per proposing faction at a time.
        self.incoming_trade_proposals = []
        self.trade_caravans = []       # list[TradeCaravan] — see app/world/trade.py
        self.local_shipments = []      # list[LocalShipment] — see app/world/resources.py's Phase 10
        self.regional_shipments = []   # list[RegionalShipment] — see app/world/trade.py's Phase 11
        self.regional_trade_events = []  # this turn's regional dispatch/delivery/loss events
        self.trade_events = []         # this turn's dispatch/delivery/payment/loss events
        self.settlement_projects = []  # list[SettlementProject] — see app/world/construction.py
        self.road_projects = []        # list[RoadProject] — see app/world/construction.py
        self.shipyard_projects = []    # list[ShipyardProject] — see app/world/construction.py
        self.granary_projects = []     # list[GranaryProject] — see app/world/construction.py
        self.warehouse_projects = []   # list[WarehouseProject] — see app/world/construction.py
        self.claim_projects = []       # list[ClaimProject] — see app/world/expansion.py
        self.commanders = []           # list[Commander] — see app/world/commander.py
        self.ships = []                 # list[Ship] — see app/world/commander.py
        self.total_land_cells = 0      # cached once at gen time (vision%/target-size% denom)
        self.base_cost = None          # per-cell noise traversal cost (see _cost_field);
                                        # persisted so trade.py can pathfind post-generation
                                        # without recomputing the noise field from scratch
        self.sea_level = 0.5
        self.factions = []             # list[Nation], index == owner value
        self.world_map = WorldMap()    # holds factions + relationships
        self.seed = 0
        self.player_faction_idx = None  # index into self.factions, or None


def _pick_continent_centers(rng, width, height):
    """2-3 continent centers, spaced far enough apart that real open ocean
    forms between them instead of one landmass touching every edge.

    Each gets a different band of *distance from the equator* (0 = map's
    vertical middle/warmest, 1 = pole/coldest — matches classify_climate's
    latitude_temp = 1 - dist exactly), picked independently for a random
    north/south side each time. That's deliberate, not just "spread them
    across different rows": latitude_temp is symmetric around the equator,
    so two continents merely in different halves of the map (say y=0.25 and
    y=0.75) sit at the *same* distance from it and would get identical
    climates. Banding by distance instead guarantees each continent lands
    at a meaningfully different temperature.

    Each continent's footprint is an ellipse, not a circle: wide east-west
    (sized off the map's full width, so it stays big enough that the height
    noise can't easily bridge it to its neighbor) but compact north-south
    (shrinking a bit as more continents need to fit), so it comfortably
    clears the equator/pole without needing an impractically tall map."""
    n = rng.randint(2, 3)
    radius_x = width * 0.16
    radius_y = height * 0.30 / n
    margin_x = min(radius_x * 1.15, width * 0.35)
    margin_y = radius_y * 1.1
    min_norm_dist = 2.6   # separation required, in radius_x/radius_y-normalized units

    centers = []
    for band in range(n):
        d_lo = band / n
        d_hi = (band + 1) / n
        # Alternate north/south by band (not randomly) so adjacent bands
        # land on opposite sides of the equator, maximizing their actual
        # separation instead of risking two bands both landing north and
        # crowding each other (min_norm_dist below still catches genuine
        # collisions either way, but this cuts down how often it has to).
        side = 1.0 if band % 2 == 0 else -1.0
        for _ in range(500):
            dist = rng.uniform(d_lo, d_hi)          # 0=equator, 1=pole
            y = (0.5 + side * dist / 2.0) * height
            y = max(margin_y, min(height - margin_y, y))
            x = rng.uniform(margin_x, width - margin_x)
            # Wrap-aware even though margin_x already keeps every center's
            # own falloff off the seam (so two continents can never
            # actually touch through it): this still stops two centers
            # from being placed "close" purely because the seam happens to
            # be the short way around between them, which a flat (x-ox)
            # distance alone wouldn't catch.
            if all((wrap.dx_wrap(ox, x, width) / radius_x) ** 2
                  + ((y - oy) / radius_y) ** 2 >= min_norm_dist ** 2
                  for ox, oy in centers):
                centers.append((x, y))
                break
        else:
            y = (0.5 + ((d_lo + d_hi) / 2.0) / 2.0) * height
            centers.append((rng.uniform(margin_x, width - margin_x),
                           max(margin_y, min(height - margin_y, y))))
    return centers, radius_x, radius_y


def _has_multiple_landmasses(land, width, height, land_cells):
    """True if the land mask splits into at least two *substantial*
    (>=3% of total land) connected components — real separate continents,
    not one dominant blob plus a few stray noise-speck islands. On the rare
    seed where the intended 2-3 continents end up noise-bridged into one,
    generate_world retries with a fresh layout instead of accepting it."""
    total = len(land_cells)
    if total == 0:
        return False
    threshold = max(30, total * 0.03)
    seen = set()
    substantial = 0
    for start in land_cells:
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        size = 0
        while stack:
            x, y = stack.pop()
            size += 1
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if (0 <= nx < width and 0 <= ny < height
                        and (nx, ny) not in seen and land[ny][nx]):
                    seen.add((nx, ny))
                    stack.append((nx, ny))
        if size >= threshold:
            substantial += 1
            if substantial >= 2:
                return True
    return False


# --- capital placement: reject sites with no real farmland nearby ----------
_CAPITAL_FOOD_CHECK_RADIUS = 8      # cells around a candidate site sampled
_CAPITAL_FOOD_CHECK_STEP = 2        # sample every Nth cell in that box (speed)
# Same thresholds resources.classify_biome uses for "mountain"/"desert"/
# "forest" (the moisture band actually left over for "plains" once those
# are excluded) -- not imported directly (capital placement runs long
# before regions/resources are relevant to anything), just the same
# values, since what actually matters here is the same "can a Crop grow
# here" question classify_biome answers for real, later.
_CAPITAL_MAX_RELIEF_FOR_FARMLAND = 0.55
_CAPITAL_MIN_MOISTURE_FOR_FARMLAND = 0.32
_CAPITAL_MAX_MOISTURE_FOR_FARMLAND = 0.50
_CAPITAL_COASTAL_EXCLUDE_REACH = 3   # matches classify_biome's own coastal
                                     # override -- a cell this close to open
                                     # water becomes "coastal" biome for
                                     # real, regardless of relief/moisture,
                                     # so it doesn't count as plains here
_CAPITAL_MIN_FOOD_CELL_FRACTION = 0.15   # of the sampled neighborhood


def _capital_has_nearby_farmland(world, x, y, mseed, land_set, coast_d):
    """Whether real Crop-supporting land (moderate elevation, not
    desert-dry or rainforest-wet, not coastal, not open water) exists near
    (x, y) -- a lightweight standalone stand-in for the real biome
    classification (_classify_biomes_and_climate), which doesn't run until
    much later in world-gen and needs data (a full moisture grid) that
    doesn't exist yet at capital-placement time. `coast_d` (a one-time
    _bfs_distance pass computed before the whole capital-placement loop
    runs) gives an exact, cheap coast-distance lookup instead of re-
    scanning each sample's own neighborhood for ocean on every call.
    Doesn't try to be exact (no swamp exception for Rice) -- just close
    enough to stop a faction spawning in the dead middle of a mountain
    range, desert, or coastline with nothing farmable anywhere close by."""
    sea = world.sea_level
    span = (1.0 - sea) or 1.0
    hits = total = 0
    r = _CAPITAL_FOOD_CHECK_RADIUS
    moisture_octaves = _periodic_octaves(world.w, _MOISTURE_OCTAVES)
    for dy in range(-r, r + 1, _CAPITAL_FOOD_CHECK_STEP):
        for dx in range(-r, r + 1, _CAPITAL_FOOD_CHECK_STEP):
            cx, cy = x + dx, y + dy
            if (cx, cy) not in land_set:
                continue
            if (cx, cy) in world.river_cells or (cx, cy) in world.lake_cells:
                continue
            if coast_d[cy][cx] <= _CAPITAL_COASTAL_EXCLUDE_REACH:
                continue
            total += 1
            relief = max(0.0, min(1.0, (world.height[cy][cx] - sea) / span))
            if relief >= _CAPITAL_MAX_RELIEF_FOR_FARMLAND:
                continue
            moisture = _quick_moisture(cx, cy, mseed, moisture_octaves)
            if not (_CAPITAL_MIN_MOISTURE_FOR_FARMLAND <= moisture
                    <= _CAPITAL_MAX_MOISTURE_FOR_FARMLAND):
                continue
            hits += 1
    return total > 0 and hits / total >= _CAPITAL_MIN_FOOD_CELL_FRACTION


def generate_world(width=1100, height=660, seed=None, n_factions=14,
                    player_species=None, player_name=None, _attempt=0):
    """Generate a world. If `player_species`/`player_name` are given, faction
    0 is forced to that species and given that exact name (instead of a
    random roll) and `world.player_faction_idx` is set to 0, so a "New Game"
    flow can drop the player into a nation of their own choosing.

    `_attempt` is internal — caps the retries below so a run of unlucky
    seeds can never recurse forever."""
    rng = random.Random(seed)
    nseed = rng.randint(0, 2 ** 31 - 1)
    world = World(width, height)
    world.seed = nseed if seed is None else seed

    # 1. height field: several octaves of value noise + falloff from the
    #    *nearest* of 2-3 continent centers (see _pick_continent_centers),
    #    so the map is multiple separate landmasses ringed by ocean rather
    #    than one blob glued to the middle of the map.
    octaves = [(0.028, 1.0), (0.060, 0.5), (0.130, 0.25), (0.260, 0.12)]
    height_octaves = _periodic_octaves(width, octaves)
    centers, radius_x, radius_y = _pick_continent_centers(rng, width, height)
    inv_rx2 = 1.0 / (radius_x * radius_x)
    inv_ry2 = 1.0 / (radius_y * radius_y)
    raw = [[0.0] * width for _ in range(height)]
    lo, hi = 1e9, -1e9
    # _pick_continent_centers' own margin_x is a soft, best-effort spacing
    # preference (its docstring: "so real open ocean forms... instead of
    # one landmass touching every edge") -- NOT a hard guarantee; land
    # regularly reaches x=0/width-1 in practice even in the non-wrap game,
    # it just never mattered there since a flat edge with no wrap has
    # nothing to look discontinuous against. Once x=0 and x=width-1 are
    # real neighbors, two unrelated landmasses landing right at the seam
    # would visibly collide. This explicit, always-applied falloff forces
    # a real ocean band there regardless of how the margin's randomness
    # shakes out for a given seed -- both edges are pushed toward the same
    # floor value as they approach the seam, which also means they
    # converge to identical depth-shading right at the wrap boundary.
    seam_margin = max(6, round(width * 0.03))
    for y in range(height):
        for x in range(width):
            v = sum(amp * _vnoise(x * eff_freq, y * freq, nseed, period_x)
                    for eff_freq, period_x, freq, amp in height_octaves)
            # Wrap-aware even though the margin above is meant to keep
            # every center far enough from x=0/width that land can never
            # reach the seam: ocean cells are depth-shaded straight off
            # this raw height value (see map_view.py's ocean color blend),
            # so a FLAT best_d2 here would still make x=0 and x=width-1
            # compute wildly different "distance to nearest continent"
            # whenever centers aren't symmetric across the map, producing
            # a visible depth-shading seam even where both sides are
            # legitimately deep ocean.
            best_d2 = min(wrap.dx_wrap(ccx, x, width) ** 2 * inv_rx2
                          + (y - ccy) ** 2 * inv_ry2
                          for ccx, ccy in centers)
            v -= 0.85 * best_d2                  # push far-from-any-continent cells underwater
            seam_d = min(x, width - x)           # distance to the nearest edge of the seam
            if seam_d < seam_margin:
                t = seam_d / seam_margin
                fade = t * t * (3 - 2 * t)       # smoothstep: 0 at the seam, 1 by seam_margin cells in
                v = v * fade - 3.0 * (1 - fade)  # firmly underwater at the seam itself
            raw[y][x] = v
            lo = min(lo, v)
            hi = max(hi, v)
    span = (hi - lo) or 1.0
    for y in range(height):
        for x in range(width):
            world.height[y][x] = (raw[y][x] - lo) / span

    # threshold so land is ~40% of the map
    flat = sorted(world.height[y][x] for y in range(height) for x in range(width))
    world.sea_level = flat[int(len(flat) * 0.60)]
    land = [[world.height[y][x] > world.sea_level for x in range(width)]
            for y in range(height)]
    land_cells = [(x, y) for y in range(height) for x in range(width) if land[y][x]]
    if not land_cells and _attempt < 6:      # extremely unlucky seed; retry
        return generate_world(width, height, rng.random(), n_factions,
                              player_species, player_name, _attempt=_attempt + 1)
    if (land_cells and _attempt < 6
            and not _has_multiple_landmasses(land, width, height, land_cells)):
        # the 2-3 intended continents got noise-bridged into one blob (rare
        # — see _pick_continent_centers/_has_multiple_landmasses) -- retry
        # with a fresh layout rather than accepting a single-landmass world.
        return generate_world(width, height, rng.random(), n_factions,
                              player_species, player_name, _attempt=_attempt + 1)
    world.total_land_cells = len(land_cells)

    # 2. hydrology: fill basins, form lakes, and route flow-accumulated rivers
    #    to the sea. Done before fertility so water can irrigate nearby land.
    _generate_hydrology(world, land, rng)

    # 3. scatter capitals with a minimum spacing, each one required to have
    #    real farmland somewhere nearby (see _capital_has_nearby_farmland) --
    #    otherwise a faction could spawn in the dead middle of a mountain
    #    range, desert, or coastline with no Crop-capable land anywhere
    #    close to its starting foothold. world.owner isn't populated with
    #    real OCEAN-vs-land data until step 4 below (it defaults to OCEAN
    #    everywhere in World.__init__), so ocean cells for this one-time
    #    coast-distance pass come from `land`/`land_cells` directly instead.
    min_dist = max(6.0, math.sqrt(len(land_cells) / n_factions) * 0.9)
    land_set = set(land_cells)
    ocean_cells = [(x, y) for y in range(height) for x in range(width)
                  if not land[y][x]]
    coast_d = _bfs_distance(world, ocean_cells)
    mseed = _moisture_seed(nseed)
    capitals = []
    tries = 0
    while len(capitals) < n_factions and tries < 6000:
        tries += 1
        x, y = rng.choice(land_cells)
        if not _capital_has_nearby_farmland(world, x, y, mseed, land_set, coast_d):
            continue
        if all((x - px) ** 2 + (y - py) ** 2 >= min_dist ** 2 for px, py in capitals):
            capitals.append((x, y))
    if not capitals:
        # Fell through 6000 tries without finding enough spaced, farmland-
        # adjacent sites (an unusually barren map) -- relax to "just needs
        # farmland nearby" for the rest, rather than leaving factions
        # unplaced; if even that comes up empty, fall back to any land cell
        # at all so world-gen never simply fails.
        farmable = [c for c in land_cells
                   if _capital_has_nearby_farmland(world, c[0], c[1], mseed, land_set, coast_d)]
        capitals.append(rng.choice(farmable) if farmable else rng.choice(land_cells))

    # 4. mark every land cell UNCLAIMED (distinct from OCEAN) before anyone
    #    owns anything — geography (fertility/biome/region shape) no longer
    #    depends on ownership, only on land-vs-water, so it can all be
    #    computed before territory is handed out at all.
    base_cost = _cost_field(world, nseed)
    world.base_cost = base_cost    # persisted for on-demand pathfinding (trade.py)
    for x, y in land_cells:
        world.owner[y][x] = UNCLAIMED

    # 5. ecology: fertility from moisture + elevation + distance to water/rivers.
    _compute_moisture(world, nseed)
    _compute_fertility(world, nseed)
    _classify_biomes_and_climate(world)

    # 6. bisect the *entire* landmass into regions — the fixed unit of
    #    territory, decoupled from ownership (see UNCLAIMED-land progressive
    #    expansion in app/world/expansion.py) — before any faction exists.
    _generate_all_regions(world, rng, base_cost, land_cells)

    # 7. rate every region's neutral-garrison strength (defends UNCLAIMED land
    #    against being claimed until a faction's military can overcome it).
    _seed_wildland_strength(world, rng, capitals)

    # 8. hand each faction only a small starting foothold around its capital
    #    — everything else on the map stays UNCLAIMED for players/AI to
    #    expand into over time, instead of claiming the whole map at once.
    _assign_starting_footholds(world, capitals)

    # 9. build factions (species, color, stats, centroid) from their foothold
    species_names = list(SPECIES.keys())
    namer = make_faction_namer(rng)
    # per faction: cell count, sum x, sum y, sum fertility (foothold only)
    sums = [[0, 0, 0, 0.0] for _ in capitals]
    for y in range(height):
        for x in range(width):
            o = world.owner[y][x]
            if o >= 0:
                sums[o][0] += 1
                sums[o][1] += x
                sums[o][2] += y
                sums[o][3] += world.fertility[y][x]

    for idx in range(len(capitals)):
        is_player = player_species is not None and idx == 0
        species = player_species if is_player else rng.choice(species_names)
        traits = SPECIES[species]
        cells = max(1, sums[idx][0])
        fert_sum = sums[idx][3]
        color = _hsv_hex(traits["hue"] + rng.uniform(-14, 14),
                         rng.uniform(0.55, 0.8), rng.uniform(0.65, 0.9))
        # military is a placeholder here — resources.seed_initial_stockpiles()
        # recomputes it for real from each faction's starting resource
        # stockpile once regions/settlements/villages all exist.
        military = max(15, min(99, int(rng.uniform(45, 72) + traits["mil"]
                                       + min(20, cells / 40))))
        morale = max(15, min(99, int(rng.uniform(50, 75))))
        center = (sums[idx][1] / cells / width, sums[idx][2] / cells / height)
        name = player_name if (is_player and player_name) else namer(species)
        region_ids = [c.id for c in world.regions if c.faction_idx == idx]
        xs = [x for c in region_ids for x, y in world.regions[c].cells]
        ys = [y for c in region_ids for x, y in world.regions[c].cells]
        bbox = (min(xs), min(ys), max(xs) + 1, max(ys) + 1) if xs else (0, 0, 1, 1)
        nation = Nation(
            name, color, territory=[], center=center,
            stats={"military": military, "morale": morale},
            meta={"species": species, "trait": traits["trait"],
                  "cells": cells, "capital": capitals[idx],
                  "fertility": round(100 * fert_sum / cells),  # avg %, 0..100
                  "regions": region_ids, "bbox": bbox})
        world.factions.append(nation)
        world.world_map.add_nation(nation)

    if player_species is not None:
        world.player_faction_idx = 0

    # adjacency: neighboring owners share a border (rarely true yet, since
    # footholds are small and scattered — most new relationships get rolled
    # lazily later, as claims/conquests bring factions into contact, via
    # territory._refresh_borders)
    borders = set()
    for y in range(height):
        for x in range(width):
            o = world.owner[y][x]
            if o < 0:
                continue
            for nx, ny in ((x + 1, y), (x, y + 1)):
                if 0 <= nx < width and 0 <= ny < height:
                    o2 = world.owner[ny][nx]
                    if o2 >= 0 and o2 != o:
                        borders.add((min(o, o2), max(o, o2)))

    from app.world.diplomacy import establish_contact
    for a, b in borders:
        na, nb = world.factions[a], world.factions[b]
        establish_contact(world, na.id, nb.id)

    # 10. found cities, castles and towns in each faction's starting
    #     foothold (UNCLAIMED land gets settlements later, when claimed)
    _generate_settlements(world, rng)

    # 11. sprinkle villages within each starting region, linked by simple
    #     dirt roads; each village's farm output tracks local fertility
    _generate_villages(world, rng)

    # 12. trade routes start nonexistent — no nation is pre-connected to any
    #     other; land routes must be discovered (diplomacy) and physically
    #     built (app/world/trade.py) before caravans can use them, sea lanes
    #     open automatically once eligible. See World.__init__ for the
    #     trade_routes/trade_routes_by_pair/trade_route_projects fields.

    # 13. seed every faction's starting resource stockpile (and, from it,
    #     their real military strength) — see app/world/resources.py
    from app.world.resources import seed_initial_stockpiles
    seed_initial_stockpiles(world)

    # 14. spawn the player's Commander at their capital — a mobile scout
    #     unit, independent of territory growth (see app/world/commander.py;
    #     this is what lets an island start ever explore beyond its own
    #     shore). Before fog init so the very first reveal already accounts
    #     for it.
    if world.player_faction_idx is not None:
        from app.world.commander import spawn_commander
        player = world.factions[world.player_faction_idx]
        spawn_commander(world, world.player_faction_idx, player.meta["capital"])

    # 15. fog of war: reveal the player's starting foothold (and whatever's
    #     already in range of it) — see app/world/vision.py
    from app.world.vision import init_fog
    init_fog(world)

    return world
