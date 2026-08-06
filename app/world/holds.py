"""Who lives under the mountains: dwarf holds and goblin warrens.

Phase 5 of SUBTERRANEAN_PLAN.md. Phases 0-4 built a place, a way to walk it, a
way to see it and an economy that works down there; every one of them was
tested against ground nobody lived on. This is the phase that puts somebody in
it, and it is where the plan's own named risk sits: the AI is the hard part,
not the terrain.

TWO KINDS OF INHABITANT, AND THEY ARE NOT THE SAME MECHANIC
-----------------------------------------------------------
A **hold** is one great settlement in the deepest hall plus mining villages
around it: wealthy, defensible, and structurally food-poor. It is born with
terraces on the mountainside above its own doors (phase 4's gate holding) and a
full larder, which is the Cappadocian picture exactly -- shelter, stores, and a
door. It begins fat and has to solve the food problem before the stores run
out.

A **warren** is many small villages clustered at the gates: poor, numerous, and
fed by scavenging and by what it can carry off. It will not terrace a
mountainside, so it gets no gate holding at all, and its aggression is driven
by its own hunger rather than by a timer -- a warren beside a rich valley is a
permanent nuisance, one beside a poor valley is quiet, because there is nothing
worth taking. That gives a surface player a real lever: feed them, or garrison
the gate.

WHY THIS IS PLACED AT WORLDGEN RATHER THAN GROWN
------------------------------------------------
A hold is not a settlement that happened to end up underground; it is what that
species IS. Dwarves' existing homeland affinity already points at mountain 1.0
and highland 0.9, so the range their capital was placed against is the range
their hold belongs under. Growing holds later through the ordinary expansion
path would mean a world where the underground is empty for the first fifty
years and then fills with whoever got there first, which is a different game
from the one the plan describes.
"""
import random

from app.world import layers as L
from app.world import resources as R
from app.world import wrap
from app.world.lexicon import make_settlement_namer
from app.world.worldgen import Settlement, Village

HOLD = "hold"
WARREN = "warren"

# Which species live below, and how. Everyone else stays a surface people who
# may take galleries by force -- that is the plan's own third decision, and it
# is why this is a small table rather than a general rule.
UNDERGROUND_SPECIES = {"Dwarves": HOLD, "Goblins": WARREN}

# A network smaller than this is a working, not a kingdom: it gets nobody.
MIN_HOLD_CELLS = 60
MIN_WARREN_CELLS = 40

# How far from its capital a faction's own underground home may be. A hold
# under a range on the other side of the world is not that faction's hold, it
# is a colony -- and colonising is what the expansion AI is for.
HOME_NETWORK_MAX_DIST = 140

# How far from the great hall the capital's front gate may exit, in cells.
# The shaft is 'straight up' in spirit, but it gets to land on the realm's
# OWN ground (see _settle_hold's probe), which the hall's exact column often
# is not -- a few cells of give is what makes the garrison town a town of
# the realm instead of a lone house in the wild.
_FRONT_GATE_RING = 6

# What a hold is: one great hall and a few mining villages around it.
HOLD_VILLAGES = (2, 4)
WARREN_VILLAGES = (4, 7)
# Warrens are numerous and poor; a hold's people are few and rich. Both are
# fractions of the ordinary roll for that node kind (see _roll_population).
WARREN_POP_MULT = 0.55
HOLD_POP_MULT = 1.15

# The full larder a hold is born with, in days of its own consumption. Real
# stores, not a number that looks generous: the point is that a hold starts fat
# and has to have solved the problem before this runs out, so it has to be long
# enough to build a gate holding and a fungus gallery in and no longer.
LARDER_DAYS = 120
# What the larder is made of. Cured, keeping goods -- which is what a cave
# larder is for, and all three of them spoil slowly enough that the hold's own
# UNDER_SPOIL_MULT makes them last (see phase 4).
LARDER_GOODS = ("Salted Meat", "Cheese", "Smoked Fish")

# A warren scavenges better than anybody: cave fish, grubs, guano, carrion.
# This is a multiplier on the sunless floor every underground node gets
# (resources.under_floor_yield), not a mechanic of its own -- being better at
# living on nothing is exactly what "cunning scavengers" should mean.
WARREN_SCAVENGE_MULT = 2.2

# --- raiding -----------------------------------------------------------------
# Hunger is the trigger, and that is the whole design: a warren that cannot feed
# itself sends parties over the surface to carry off a neighbour's stores. Not a
# claim on ground -- a raid takes food and goes home.
#
# THIS IS THE PIECE MOST LIKELY TO MEASURE OPPRESSIVE, and the plan says so
# before a line of it was written. The two knobs are named here rather than
# discovered later: RAID_CHANCE_PER_DAY and RAID_HAUL_FRACTION. The failure to
# watch for is a warren raiding constantly because scavenging was tuned just
# below its own subsistence -- so dev/test_holds.py measures the raid rate fed
# against the raid rate starving and records both numbers rather than asserting
# a threshold on either.
RAID_HUNGER_DAYS = 4          # days short of food before a warren will raid
RAID_CHANCE_PER_DAY = 0.06    # per hungry warren node, per day
# A PLAYER raid (map_view's "Raid the Surface" button on a warren village)
# is a deliberate act, not a hunger reflex -- it costs nothing but a
# cooldown, so the same warren cannot farm the same fields every day.
RAID_COOLDOWN_DAYS = 5


def player_raid(world, warren_node):
    """The goblin PLAYER orders a raid: take the richest reachable surface
    store and carry it home, exactly as the AI's hungry-warren raids do
    (same targets, same carry-off, same victim marking that feeds the
    alerts panel) -- the only difference is WHO decides. Returns the raid
    dict, or None when there is nothing to raid or the warren is still on
    cooldown. Sets warren_node.raid_cooldown_until so the same village
    cannot raid again for RAID_COOLDOWN_DAYS."""
    from app.world import resources as _R
    turn = getattr(world, "turn", 0)
    if getattr(warren_node, "raid_cooldown_until", 0) > turn:
        return None
    targets = _raid_targets(world, warren_node, warren_node.faction_idx)
    if not targets:
        return None
    victim = max(targets, key=_node_food)
    hauled = _carry_off(victim, warren_node)
    if not hauled:
        return None
    victim.raided_turn = turn
    victim.raided_amount = sum(hauled.values())
    warren_node.raid_cooldown_until = turn + RAID_COOLDOWN_DAYS
    return {"raider": warren_node, "victim": victim, "hauled": hauled}


def raid_target_summary(world, warren_node):
    """The richest reachable surface store a player raid would hit, or None.
    Used by the warren panel to name the target before the button is
    pressed -- the choice is informed even though the raid itself is one
    click."""
    targets = _raid_targets(world, warren_node, warren_node.faction_idx)
    if not targets:
        return None
    victim = max(targets, key=_node_food)
    return victim, _node_food(victim)
RAID_RANGE = 22               # cells from the warren's own gates
RAID_HAUL_FRACTION = 0.18     # of the victim's food stock, per raid
RAID_HAUL_CAP = 260


class TunnelProject:
    """A tunnel under construction: carves a corridor of rock between the
    faction's underground home and the nearest unclaimed cavern network,
    then claims that network for the faction (v0.18.14 -- the underground
    expansion analog of a surface claim). `path` is the corridor of rock
    cells, in order; `built_index` grows by TUNNEL_CELLS_PER_TURN like a
    road, and each newly reached cell becomes a CAVERN as the work arrives
    -- so a tunnel is visible growing, exactly as a road is."""

    def __init__(self, faction_idx, path, network, region_ids=None):
        self.faction_idx = faction_idx
        self.path = path
        self.network = network
        self.built_index = 0
        self.total_turns = max(1, round(len(path) / TUNNEL_CELLS_PER_TURN))
        self.progress_turns = 0.0

    @property
    def complete(self):
        return self.built_index >= len(self.path)

    @property
    def built_cells(self):
        return self.path[:self.built_index]


TUNNEL_MAX_RANGE = 260        # cells from the home network's own edge
TUNNEL_CELLS_PER_TURN = 6     # corridor cells carved per day (road pace)
TUNNEL_GOLD_PER_CELL = 6      # gold cost per corridor cell


def _home_cells(world, faction_idx):
    """Every under cell of a faction's underground home (the network it was
    born with), as a set."""
    home = next((h for h in getattr(world, "under_homes", None) or ()
                 if h["faction_idx"] == faction_idx), None)
    if home is None:
        return set()
    cells = set()
    for rid in home["regions"]:
        cells |= set(world.regions[rid].cells)
    return cells


def _nearest_unclaimed_network(world, faction_idx, rng=None):
    """(network, corridor) -- the nearest cavern network not owned by this
    faction and the corridor of ROCK cells from the home network's edge to
    it (in order, first cell adjacent to home), or (None, None). The search
    walks through un-carved rock only: an unclaimed network is reached by
    digging, not by cutting through somebody else's gallery."""
    import heapq
    from app.world import layers as L
    home_cells = _home_cells(world, faction_idx)
    if not home_cells:
        return None, None
    components = _components(world)
    owned_ids = set()
    for i, network in enumerate(components):
        for x, y in network:
            rid = L.region_at(world, x, y, L.UNDER)
            if rid is not None and 0 <= rid < len(world.regions) \
                    and world.regions[rid].faction_idx == faction_idx:
                owned_ids.add(i)
                break
    targets = [i for i, network in enumerate(components) if i not in owned_ids]
    if not targets:
        return None, None
    w, h = world.w, world.h
    start = set()
    for x, y in home_cells:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = (x + dx) % w, y + dy
            if 0 <= ny < h and not L.kind_at(world, nx, ny, L.UNDER):
                start.add((nx, ny))
    if not start:
        return None, None
    # BFS through rock; the first reachable unclaimed network's edge wins.
    # Capped by DISTANCE from the home (BFS layer depth), not by cells
    # explored: a corridor 190 cells long is a real tunnel through ~30k
    # cells of rock, and a raw cell budget would kill the search before it
    # ever reached the door of a merely far network.
    prev = {s: None for s in start}
    dist = {s: 0 for s in start}
    queue = list(start)
    head = 0
    found = None
    found_i = None
    target_members = set()
    for i in targets:
        target_members |= set(components[i])
    while head < len(queue):
        cur = queue[head]
        head += 1
        if dist[cur] >= TUNNEL_MAX_RANGE:
            continue
        cx, cy = cur
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = (cx + dx) % w, cy + dy
            if not (0 <= ny < h):
                continue
            nxt = (nx, ny)
            if nxt in target_members:
                # A rock cell's neighbour is the edge of an unclaimed
                # network: the corridor ends at THIS rock cell -- the
                # target cell itself is already cavern and is not carved.
                found = cur
                found_i = next(i for i in targets if nxt in set(components[i]))
                break
            if nxt in prev or L.kind_at(world, nx, ny, L.UNDER):
                continue
            prev[nxt] = cur
            dist[nxt] = dist[cur] + 1
            queue.append(nxt)
        if found is not None:
            break
    if found is None:
        return None, None
    corridor = []
    step = found
    while step is not None:
        corridor.append(step)
        step = prev[step]
    corridor.reverse()
    return components[found_i], corridor


def start_tunnel_project(world, faction_idx, gold):
    """Queue a tunnel to the nearest unclaimed network. Returns the project
    (deduped: one tunnel per faction at a time), or None when there is
    nothing to dig to or the faction cannot pay."""
    if any(p.faction_idx == faction_idx
           for p in getattr(world, "tunnel_projects", ())):
        return None
    network, corridor = _nearest_unclaimed_network(world, faction_idx)
    if network is None:
        return None
    cost = TUNNEL_GOLD_PER_CELL * len(corridor)
    if gold < cost:
        return None
    project = TunnelProject(faction_idx, corridor, network)
    if not hasattr(world, "tunnel_projects"):
        world.tunnel_projects = []
    world.tunnel_projects.append(project)
    return project


def advance_tunnel_projects(world):
    """One day of tunnelling: carve the corridor cells as the work reaches
    them; on completion, claim the network they connect to (the caverns
    become the faction's)."""
    from app.world import layers as L
    for project in list(getattr(world, "tunnel_projects", ())):
        if not project.complete:
            project.built_index = min(len(project.path),
                                      project.built_index + TUNNEL_CELLS_PER_TURN)
            for x, y in project.built_cells:
                L.carve(world, x, y, L.CAVERN)
        if project.complete:
            _claim_network(world, project.network, project.faction_idx)
            from app.world import chronicle
            chronicle.log(world, world.factions[project.faction_idx],
                          f"A new gallery opens beneath the mountain.")
            world.tunnel_projects.remove(project)


def _components(world):
    """Connected networks of walkable underground, largest first."""
    seen = set()
    out = []
    for start in sorted(world.under_cells):
        if start in seen or not L.is_open(world, start[0], start[1], L.UNDER):
            continue
        comp = {start}
        seen.add(start)
        stack = [start]
        while stack:
            x, y = stack.pop()
            for nx, ny, _lay in L.open_neighbours(world, x, y, L.UNDER):
                if (nx, ny) not in seen:
                    seen.add((nx, ny))
                    comp.add((nx, ny))
                    stack.append((nx, ny))
        out.append(comp)
    out.sort(key=len, reverse=True)
    return out


def _network_gates(world, network):
    return [g for g in world.gates if tuple(g["under"]) in network]


def _network_centre(network):
    xs = [p[0] for p in network]
    ys = [p[1] for p in network]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _caverns(world, network):
    """Where anybody can actually live: a gallery is a corridor, not a place
    (see layers.SETTLEABLE_KINDS)."""
    return sorted(p for p in network
                  if L.kind_at(world, p[0], p[1], L.UNDER) in L.SETTLEABLE_KINDS)


def _spread(sites, count, spacing):
    """`count` sites from `sites`, no two closer than `spacing` -- the same
    greedy spacing rule village placement uses above ground."""
    chosen = []
    for p in sites:
        if len(chosen) >= count:
            break
        if all((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 >= spacing ** 2
               for q in chosen):
            chosen.append(p)
    return chosen


def _claim_network(world, network, faction_idx):
    """Hand every region of this network, and every cell of it, to a faction.

    Underground regions are ordinary Regions (phase 0's whole argument), so
    this is the same three facts territory transfer keeps in step above
    ground: the region's owner, the faction's region list, and the per-cell
    owner map -- which for the underground is the sparse `under_owner` dict
    rather than the dense grid."""
    nation = world.factions[faction_idx]
    owned = nation.meta.setdefault("regions", [])
    claimed = []
    for region in world.regions:
        if not L.is_under(region):
            continue
        if not set(region.cells) & network:
            continue
        region.faction_idx = faction_idx
        if region.id not in owned:
            owned.append(region.id)
        for x, y in region.cells:
            L.set_owner_at(world, x, y, L.UNDER, faction_idx)
        claimed.append(region)
    return claimed


def _stock_larder(node, days):
    """Fill a hold's stores. Split evenly across the keeping goods rather than
    piled into one: a larder is a larder, not a mountain of cheese."""
    need = R.FOOD_PER_CAPITA * max(1, getattr(node, "adults", 0)) * days
    each = max(1, round(need / len(LARDER_GOODS)))
    if not hasattr(node, "resources"):
        node.resources = {}
    for good in LARDER_GOODS:
        node.resources[good] = node.resources.get(good, 0) + each


def _cache_network_terraces(world, network, regions):
    """Give every region of a claimed network the SAME terrace pool: the
    mountainside within GATE_HOLDING_RADIUS of ANY of the network's doors.

    The per-region model (a region's own cells that touch a door) stranded
    the food chain: a hold plants its villages DEEP, as far from the doors
    as possible (defensibility), so the regions that actually touch a door
    held all the terrace cells and the deep regions held none -- and a
    holding village that cannot reach a door works no terraces at all. The
    result was a hold whose villages sat in doorless regions slowly eating
    its larder dry. Terraces are a NETWORK asset; the per-node share in
    gate_holding_cells still splits the pool between the holdings that work
    it, so a big pool with many holdings farms the same 16 cells a holding
    with one door farms (GATE_HOLDING_CELLS caps the per-node take)."""
    mouths = {tuple(g["under"]) for g in getattr(world, "gates", ())}
    door_cells = set()
    for region in regions:
        door_cells |= set(region.cells) & mouths
    total = set()
    r = R.GATE_HOLDING_RADIUS
    for gx, gy in door_cells:
        for dy in range(-r, r + 1):
            ny = gy + dy
            if not (0 <= ny < world.h):
                continue
            for dx in range(-r, r + 1):
                nx = wrap.wrap_x(gx + dx, world.w)
                if world.owner[ny][nx] == L.OCEAN or (nx, ny) in world.lake_cells:
                    continue
                total.add((nx, ny))
    pool = len(total)
    for region in regions:
        region._gate_terrace_cells = pool
    return pool


def _settle_hold(world, rng, network, faction_idx, namer):
    """One great hall, a few mining villages, terraces above the doors, and a
    full larder to solve the problem in."""
    from app.world.resources import seed_prosperity
    from app.world.worldgen import _roll_population
    species = world.factions[faction_idx].meta["species"]
    caverns = _caverns(world, network)
    if not caverns:
        return None
    regions = _claim_network(world, network, faction_idx)
    if not regions:
        return None
    # The terraces are the NETWORK's, not one region's (see
    # _cache_network_terraces): the villages are planted deep, as far from
    # the doors as possible, and the per-region model left every holding in
    # a doorless region unable to reach a single terrace cell -- the hold
    # ate its larder dry. Share the door-regions' mountainside across the
    # whole claimed network.
    _cache_network_terraces(world, network, regions)

    # The great hall goes in the deepest rock -- furthest from any door, which
    # is what a hold being defensible actually means.
    gates = [tuple(g["under"]) for g in _network_gates(world, network)]
    if gates:
        caverns.sort(key=lambda p: -min((p[0] - g[0]) ** 2 + (p[1] - g[1]) ** 2
                                        for g in gates))
    seat = caverns[0]
    population, adults, children, max_population = _roll_population(rng, "city")
    scale = HOLD_POP_MULT
    st = Settlement(len(world.settlements), "city", namer("city", species),
                    seat, faction_idx,
                    L.region_at(world, seat[0], seat[1], L.UNDER),
                    tax_income=0,
                    population=round(population * scale),
                    adults=round(adults * scale), children=round(children * scale),
                    prosperity=seed_prosperity(),
                    max_population=round((max_population or population) * scale))
    # A hold is a Settlement like any other, so it gets a character (see
    # resources.SETTLEMENT_CHARACTERS) -- a fortress-realm's holds lean
    # garrison, weighted for variety like the surface world.
    from app.world.resources import SETTLEMENT_CHARACTERS
    st.character = rng.choices(tuple(SETTLEMENT_CHARACTERS), weights=(25, 50, 25))[0]
    # The first hold is a realm's capital too (see worldgen._place_settle_
    # ments_for_faction's is_capital stamp).
    if not world.factions[faction_idx].meta.get("settlements"):
        st.is_capital = True
    world.settlements.append(st)
    world.factions[faction_idx].meta.setdefault("settlements", []).append(st.id)
    if st.region_id is not None and 0 <= st.region_id < len(world.regions):
        world.regions[st.region_id].meta_settlements.append(st.id)
    # The hall runs the beds at a scale no mining village can, and it is where
    # the stores are.
    R.set_storage_tier(st, R.FUNGUS_GALLERY, 1)

    # The capital's OWN door (v0.18.17): the great hall sits in the deepest
    # rock -- furthest from any door, defensible -- but a realm whose only
    # openings are a day's march through the dark never sees the sun. Cut a
    # private shaft straight up from the hall to the surface and mark it as
    # the capital's door: the gate town above it is the realm's FRONT gate,
    # the hall has a way out of its own city, and the mountainside over the
    # shaft becomes the hold's own front terraces (the terrace pool is
    # re-cached below to include them).
    capital_door = None
    sx, sy = st.pos
    # Prefer the realm's OWN ground for the door: the gate town above it is
    # the realm's front gate (see _place_gate_town), and a front gate that
    # exits into unclaimed wild -- or a rival's foothold -- strands the
    # garrison town outside the territory the realm actually owns. Search a
    # small ring around the hall for an owned open cell first, then fall
    # back to the first open cell, exactly as before.
    probes = [(sx, sy)]
    for ring in range(1, _FRONT_GATE_RING + 1):
        probes += [(wrap.wrap_x(sx + dx, world.w),
                    max(0, min(world.h - 1, sy + dy)))
                   for dx in range(-ring, ring + 1)
                   for dy in range(-ring, ring + 1)
                   if max(abs(dx), abs(dy)) == ring]

    def _open(cell):
        px, py = cell
        return (world.owner[py][px] != L.OCEAN
                and (px, py) not in world.lake_cells)

    for probe_x, probe_y in probes:
        if (world.owner[probe_y][probe_x] == faction_idx
                and _open((probe_x, probe_y))):
            capital_door = L.add_gate(world, (probe_x, probe_y), st.pos,
                                      name="Front Gate")
            capital_door["is_capital_door"] = True
            break
    if capital_door is None:
        for probe_x, probe_y in probes:
            if _open((probe_x, probe_y)):
                capital_door = L.add_gate(world, (probe_x, probe_y), st.pos,
                                          name="Front Gate")
                capital_door["is_capital_door"] = True
                break
    # The new door's mountainside belongs to the hold's own front terraces.
    if capital_door is not None:
        _cache_network_terraces(world, network, regions)

    villages = []
    wanted = rng.randint(*HOLD_VILLAGES)
    for pos in _spread([p for p in caverns if p != seat], wanted, 6):
        village = _plant_village(world, rng, pos, faction_idx, namer, species,
                                 pop_mult=HOLD_POP_MULT)
        if village is None:
            continue
        # Born with its terraces, which is the bootstrap the whole food design
        # rests on -- a hold that has to BUILD its first farm starves before it
        # can. Stalls too: the beasts are what the beds run on.
        R.set_storage_tier(village, R.GATE_HOLDING, 1)
        R.set_storage_tier(village, R.STALLS, 1)
        R.set_storage_tier(village, R.FUNGUS_GALLERY, 1)
        villages.append(village)
    return {"kind": HOLD, "faction_idx": faction_idx, "seat": st,
            "villages": villages, "regions": [r.id for r in regions]}


def _settle_warren(world, rng, network, faction_idx, namer):
    """Many small villages at the doors. No hall, no terraces, no larder --
    a warren lives on what it can scrape and what it can take."""
    species = world.factions[faction_idx].meta["species"]
    caverns = _caverns(world, network)
    if not caverns:
        return None
    regions = _claim_network(world, network, faction_idx)
    if not regions:
        return None
    gates = [tuple(g["under"]) for g in _network_gates(world, network)]
    if gates:
        # Clustered NEAR the doors, which is what makes a warren a permanent
        # problem for whoever lives in the valley below.
        caverns.sort(key=lambda p: min((p[0] - g[0]) ** 2 + (p[1] - g[1]) ** 2
                                       for g in gates))
    villages = []
    for pos in _spread(caverns, rng.randint(*WARREN_VILLAGES), 4):
        village = _plant_village(world, rng, pos, faction_idx, namer, species,
                                 pop_mult=WARREN_POP_MULT)
        if village is not None:
            villages.append(village)
    return {"kind": WARREN, "faction_idx": faction_idx, "seat": None,
            "villages": villages, "regions": [r.id for r in regions]}


def _plant_village(world, rng, pos, faction_idx, namer, species, pop_mult=1.0):
    from app.world.resources import seed_prosperity
    from app.world.worldgen import _roll_population
    region_id = L.region_at(world, pos[0], pos[1], L.UNDER)
    if region_id is None:
        return None
    population, adults, children, max_population = _roll_population(rng, "village")
    village = Village(len(world.villages), region_id, faction_idx,
                      namer("village", species), pos,
                      farm_output=0,           # nothing grows down here
                      population=round(population * pop_mult),
                      adults=round(adults * pop_mult),
                      children=round(children * pop_mult),
                      prosperity=seed_prosperity(),
                      max_population=round((max_population or population) * pop_mult))
    world.villages.append(village)
    region = world.regions[region_id]
    region.villages = list(getattr(region, "villages", [])) + [village.id]
    return village


def _place_gate_town(world, rng, network, faction_idx, namer):
    """The surface door of an underground realm: a small Town at one of the
    network's gates. It is the realm's only above-ground settlement -- trade
    caravans, the commander and every surface-anchored system hang off it
    (settle_underworld inserts it first into meta['settlements']), while the
    realm's people and its true capital live under the mountain. None if no
    gate opens onto land (a sea-gated network) -- the realm then anchors on
    its underground seat alone.

    The town sits on the realm's OWN territory, always: a garrison town in
    the wild (or worse, on a rival's foothold) anchors the caravans and the
    commander outside the land the player actually owns. Prefers the
    capital's own door; if no door opens on owned ground yet, the unclaimed
    region the door opens onto is claimed for the realm (never a rival's),
    so the front gate is always inside the realm's own land."""
    from app.world.resources import seed_prosperity, SETTLEMENT_CHARACTERS
    from app.world.worldgen import (_roll_population, _mark_occupied_both,
                                    SETTLEMENT_TAX_INCOME)
    species = world.factions[faction_idx].meta["species"]
    gates = _network_gates(world, network)
    if not gates:
        return None
    # The realm's FRONT gate is the capital's own door (see _settle_hold):
    # the gate town is the door town, and a door town that isn't at the
    # capital's door is not the front gate. Prefer it; among the other doors
    # take the one nearest the network's centre, so a fallback is the closest
    # real door, never a random adit.
    centre = _network_centre(network)
    candidates = ([g for g in gates if g.get("is_capital_door")]
                  + sorted((g for g in gates if not g.get("is_capital_door")),
                           key=lambda g: ((g["pos"][0] - centre[0]) ** 2
                                          + (g["pos"][1] - centre[1]) ** 2)))
    spot = None
    gate_chosen = None
    for g in candidates:
        sx, sy = g["pos"]
        if not (0 <= sx < world.w and 0 <= sy < world.h):
            continue
        if world.owner[sy][sx] == faction_idx:
            spot = (sx, sy)
            gate_chosen = g
            break
    if spot is None:
        # No door opens on the realm's own ground yet -- but the realm's own
        # front door should be inside its own territory, not a lone house in
        # the wild. Claim the unclaimed region the door opens onto (never a
        # rival's), making the garrison town a town of the realm's own land.
        for g in candidates:
            sx, sy = g["pos"]
            if not (0 <= sx < world.w and 0 <= sy < world.h):
                continue
            o = world.owner[sy][sx]
            if o >= 0 or o == L.OCEAN or (sx, sy) in world.lake_cells:
                continue
            rid = L.region_at(world, sx, sy, L.SURFACE)
            if rid is None or world.regions[rid].faction_idx >= 0:
                continue
            region = world.regions[rid]
            region.faction_idx = faction_idx
            for x, y in region.cells:
                world.owner[y][x] = faction_idx
            world.factions[faction_idx].meta.setdefault("regions", []).append(rid)
            spot = (sx, sy)
            gate_chosen = g
            break
    if spot is None:
        return None
    region_id = L.region_at(world, spot[0], spot[1], L.SURFACE)
    if region_id is None:
        return None
    kind = "town"
    tax_income = round(rng.uniform(*SETTLEMENT_TAX_INCOME[kind]))
    population, adults, children, max_population = _roll_population(rng, kind)
    st = Settlement(len(world.settlements), kind, namer(kind, species),
                    spot, faction_idx, region_id, tax_income,
                    population, adults, children, seed_prosperity(),
                    max_population)
    # A door town rolls a character like any other settlement (it is one).
    st.character = rng.choices(tuple(SETTLEMENT_CHARACTERS),
                               weights=(40, 30, 30))[0]
    world.settlements.append(st)
    _mark_occupied_both(world, spot[0], spot[1])
    world.regions[region_id].meta_settlements.append(st.id)
    return st


def _fallback_surface_capital(world, rng, faction_idx, namer):
    """A cave realm whose mountains have no reachable cave network still
    gets a home: a plain surface capital, the pre-underground behavior.
    Called by settle_underworld when a dwarf/goblin faction cannot reach
    any cavern network -- the start-site preview steers the PLAYER toward
    cavern-over sites, but AI realms scatter blindly and must not end up
    homeless (before the underground capital, every faction had a surface
    capital; the surface-skip in worldgen is only safe when the hold
    actually lands)."""
    from app.world.resources import seed_prosperity, SETTLEMENT_CHARACTERS
    from app.world.worldgen import (_roll_population, _mark_occupied_both,
                                    SETTLEMENT_TAX_INCOME)
    nation = world.factions[faction_idx]
    species = nation.meta["species"]
    capital = nation.meta.get("capital")
    if capital is None:
        return None
    x, y = capital
    if not (0 <= x < world.w and 0 <= y < world.h):
        return None
    kind = "city"
    tax_income = round(rng.uniform(*SETTLEMENT_TAX_INCOME[kind]))
    population, adults, children, max_population = _roll_population(rng, kind)
    region_id = world.region_grid[y][x]
    st = Settlement(len(world.settlements), kind, namer(kind, species),
                    (x, y), faction_idx, region_id, tax_income,
                    population, adults, children, seed_prosperity(),
                    max_population)
    st.character = rng.choices(tuple(SETTLEMENT_CHARACTERS),
                               weights=(40, 30, 30))[0]
    world.settlements.append(st)
    _mark_occupied_both(world, x, y)
    nation.meta["settlements"].append(st.id)
    nation.meta["capital"] = st.pos
    st.is_capital = True
    from app.world import chronicle
    chronicle.log(world, nation,
                  f"The realm of {nation.name} is founded at {st.name}.")
    if 0 <= region_id < len(world.regions):
        world.regions[region_id].meta_settlements.append(st.id)
    return st


def settle_underworld(world, rng=None):
    """Put dwarf holds and goblin warrens under the mountains.

    Called from generate_world after the surface settlements and villages
    exist, so a hold's people are placed against a world that already has
    somebody to trade with and somebody to raid.

    Returns a small summary, the same shape carve_underworld returns, for the
    debug tools and for the tests."""
    rng = rng or random.Random(int(getattr(world, "seed", 0) or 0) ^ 0x40D5)
    L.ensure_layers(world)
    summary = {"holds": 0, "warrens": 0, "settlements": 0, "villages": 0}
    if not world.under_cells or not world.gates:
        world.under_settlement_summary = summary
        return summary

    namer = make_settlement_namer(rng)
    networks = [n for n in _components(world) if _network_gates(world, n)]
    taken = set()
    homes = []
    for idx, nation in enumerate(world.factions):
        kind = UNDERGROUND_SPECIES.get(nation.meta.get("species"))
        if kind is None:
            continue
        capital = nation.meta.get("capital")
        floor = MIN_HOLD_CELLS if kind == HOLD else MIN_WARREN_CELLS
        best, best_d = None, None
        for i, network in enumerate(networks):
            if i in taken or len(network) < floor:
                continue
            cx, cy = _network_centre(network)
            d = (wrap.dist_wrap(capital, (cx, cy), world.w)
                 if capital else 0.0)
            if d > HOME_NETWORK_MAX_DIST:
                continue
            if best_d is None or d < best_d:
                best, best_d = i, d
        if best is None:
            # No range near enough. That is a real outcome, not a failure: a
            # dwarf realm placed on an island of hills simply lives above
            # ground (its capital is a plain surface city, the pre-
            # underground shape), and the galleries elsewhere stay open for
            # anybody who can take a gate.
            if not nation.meta.get("settlements"):
                _fallback_surface_capital(world, rng, idx, namer)
                summary["surface_fallbacks"] = summary.get(
                    "surface_fallbacks", 0) + 1
            continue
        taken.add(best)
        home = (_settle_hold if kind == HOLD else _settle_warren)(
            world, rng, networks[best], idx, namer)
        if home is None:
            if not nation.meta.get("settlements"):
                _fallback_surface_capital(world, rng, idx, namer)
                summary["surface_fallbacks"] = summary.get(
                    "surface_fallbacks", 0) + 1
            continue
        homes.append(home)
        summary["holds" if kind == HOLD else "warrens"] += 1
        summary["settlements"] += 1 if home["seat"] is not None else 0
        summary["villages"] += len(home["villages"])
        # The underground capital (phase A of the underworld rework): the
        # hold/warren is the realm's HOME -- the seat carries the Seat of
        # the Realm stamp, and the founding chronicle fires here, not on
        # the surface (cave peoples skipped their surface capital in
        # worldgen). Their only above-ground anchor is a GATE TOWN at the
        # doors, which is inserted FIRST into meta["settlements"] so the
        # surface-anchored systems (trade caravans, commander spawn,
        # region panels) all point at a place a surface unit can reach.
        seat = home["seat"]
        meta = nation.meta
        gate_town = _place_gate_town(world, rng, networks[best], idx, namer)
        if gate_town is not None:
            # The realm that lives under a mountain is anchored at its door:
            # the gate town is settlements[0], which the surface-anchored
            # systems (trade caravans, commander spawn, region panels) all
            # hang off, and meta["capital"] points there too.
            meta["settlements"].insert(0, gate_town.id)
            meta["capital"] = gate_town.pos
            summary["gate_towns"] = summary.get("gate_towns", 0) + 1
        if seat is not None:
            # The underground capital: the hold is the Seat of the Realm and
            # the founding chronicle fires here, not on the surface (cave
            # peoples skipped their surface capital in worldgen). An
            # under-city is NOT stamped for the frontier population draw
            # (under_capital): people flocking to a visible capital is a
            # surface phenomenon, and a cave city's food is hard-capped by
            # terraces and fungus -- growing it by magic starvation pressure
            # instead of by breaking out to farmland is the wrong loop.
            seat.is_capital = True
            seat.under_capital = True
            from app.world import chronicle
            chronicle.log(world, nation,
                          f"The realm of {nation.name} is founded at "
                          f"{seat.name}, beneath the mountains.")
        elif gate_town is not None:
            # A warren has no great hall (that is the goblin way): the realm's
            # seat is its door town; the warren villages below are its people.
            gate_town.is_capital = True
            from app.world import chronicle
            chronicle.log(world, nation,
                          f"The realm of {nation.name} is founded at "
                          f"{gate_town.name}, at the mountain's door.")

    world.under_homes = [{"kind": h["kind"], "faction_idx": h["faction_idx"],
                          "regions": h["regions"]} for h in homes]
    world.under_settlement_summary = summary
    return summary


def stock_larders(world):
    """Fill every hold's stores.

    Separate from settle_underworld, and called AFTER
    resources.seed_initial_stockpiles, because that function empties every
    node's storage before seeding it -- a larder handed out before it ran was
    silently thrown away, which is exactly the sort of ordering bug that shows
    up months later as "holds seem to starve early". The larder is the whole
    Cappadocian premise: shelter, stores, and a door."""
    for home in getattr(world, "under_homes", ()) or ():
        if home["kind"] != HOLD:
            continue
        for node in list(world.settlements) + list(world.villages):
            rid = getattr(node, "region_id", None)
            if rid in home["regions"]:
                _stock_larder(node, LARDER_DAYS)


# --- living down there --------------------------------------------------------
def node_is_warren(world, node):
    """Whether this node is a warren's -- which is what decides both the
    scavenging bonus and whether it will raid."""
    idx = getattr(node, "faction_idx", -1)
    if idx is None or not (0 <= idx < len(world.factions)):
        return False
    species = world.factions[idx].meta.get("species")
    return UNDERGROUND_SPECIES.get(species) == WARREN


def scavenge_mult(world, node):
    """Multiplier on the sunless floor for this node (see
    resources.under_floor_yield). A warren lives on what a hold would not
    bother to pick up."""
    return WARREN_SCAVENGE_MULT if node_is_warren(world, node) else 1.0


def _node_food(node):
    res = getattr(node, "resources", None) or {}
    return sum(res.get(f, 0) for f in R._FOOD_SOURCES)


def _is_hungry(node):
    """A node that has actually gone without, not one that is merely poor.

    Reads the same counter starvation itself reads (see
    resources._consume_node_needs), so "hungry" here means exactly what it
    means everywhere else in the game rather than being a second opinion."""
    return getattr(node, "turns_without_food", 0) >= RAID_HUNGER_DAYS


def _raid_targets(world, warren_node, faction_idx):
    """Somebody else's stores, within reach of this warren's own doors.

    Reach is measured from the GATES, not from the warren village itself: a
    raiding party comes out of a door and goes over the ground, so what is
    raidable is what lies around the doors -- which is precisely why
    garrisoning the gate is the answer to them."""
    region = world.regions[warren_node.region_id]
    # Reach is from the warren's DOORS, and a warren's doors are its whole
    # network's: the villages cluster near the doors but the per-region model
    # left most of them in regions that touch none -- a warren whose only
    # door region held no village could never raid at all, which quietly
    # killed the mechanic for most goblin realms. Any door of the network
    # can send a party out, so the mouths are every gate under-cell inside
    # the faction's under-home.
    home = next((h for h in getattr(world, "under_homes", None) or ()
                 if h["faction_idx"] == faction_idx), None)
    if home is None:
        return []
    own_cells = set()
    for rid in home["regions"]:
        own_cells |= set(world.regions[rid].cells)
    mouths = own_cells & {tuple(g["under"]) for g in world.gates}
    doors = [tuple(g["pos"]) for g in world.gates
             if tuple(g["under"]) in mouths]
    if not doors:
        return []
    out = []
    for node in list(world.settlements) + list(world.villages):
        idx = getattr(node, "faction_idx", -1)
        if idx == faction_idx or idx is None or idx < 0:
            continue
        rid = getattr(node, "region_id", None)
        if rid is None or not (0 <= rid < len(world.regions)):
            continue
        if L.is_under(world.regions[rid]):
            continue          # a raid goes UP; galleries are war, not robbery
        if _node_food(node) <= 0:
            continue
        if any(wrap.dist_wrap(node.pos, door, world.w) <= RAID_RANGE
               for door in doors):
            out.append(node)
    return out


def _carry_off(victim, raider):
    """Take a share of the victim's food and carry it home. Food only: a raid
    takes what can be eaten and carried, not a region and not a treasury."""
    res = getattr(victim, "resources", None) or {}
    if not hasattr(raider, "resources"):
        raider.resources = {}
    hauled = {}
    total = _node_food(victim)
    if total <= 0:
        return hauled
    budget = min(RAID_HAUL_CAP, round(total * RAID_HAUL_FRACTION))
    for food in R._FOOD_SOURCES:
        if budget <= 0:
            break
        have = res.get(food, 0)
        if have <= 0:
            continue
        take = int(min(have, budget))
        if take <= 0:
            continue
        res[food] = have - take
        raider.resources[food] = raider.resources.get(food, 0) + take
        hauled[food] = take
        budget -= take
    return hauled


def advance_raids(world):
    """One day of hungry warrens. Returns the raids that happened, for the
    alert pipe and for the tests.

    Driven by the warren's own hunger and by nothing else -- no timer, no
    aggression stat, no scripted event. A fed warren is a quiet warren, which
    is the entire claim this mechanic makes and the one dev/test_holds.py
    measures."""
    raids = []
    rng = getattr(world, "_raid_rng", None)
    if rng is None:
        rng = world._raid_rng = random.Random(
            (int(getattr(world, "seed", 0) or 0) ^ 0x8A17) & 0x7FFFFFFF)
    for village in world.villages:
        if not node_is_warren(world, village) or not _is_hungry(village):
            continue
        rid = getattr(village, "region_id", None)
        if rid is None or not L.is_under(world.regions[rid]):
            continue
        if rng.random() >= RAID_CHANCE_PER_DAY:
            continue
        targets = _raid_targets(world, village, village.faction_idx)
        if not targets:
            continue
        victim = max(targets, key=_node_food)
        hauled = _carry_off(victim, village)
        if not hauled:
            continue
        # Marked on the victim rather than pushed anywhere: the alerts panel
        # reads it (resources.node_alerts) the same way it reads a food
        # shortage or a storm, so a raid needs no new UI at all.
        victim.raided_turn = getattr(world, "turn", 0)
        victim.raided_amount = sum(hauled.values())
        raids.append({"raider": village, "victim": victim, "hauled": hauled})
    world.last_raids = raids
    return raids
