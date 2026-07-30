"""Fog of war: what the player has actually seen. Two-state (unexplored /
revealed — no dimmed "remembered" state), monotonic (once seen, always
shown), with the reveal radius scaling up as the player's own territory
grows, so a freshly-founded, single-region realm can't see the whole
continent — see recompute()'s vision-radius formula.

Also tracks which *factions* the player has made contact with (any faction
with at least one revealed cell) — the prerequisite the diplomacy/trade
system uses to gate interacting with a nation you haven't actually found yet.

Sandbox worlds with no player faction (world.player_faction_idx is None)
never populate fog at all — nothing in the game currently checks it in that
case, so the map renders exactly as it did before fog of war existed.
"""
import math
from collections import deque

from app.world import wrap

VISION_MIN = 6      # reveal radius (world cells) at owned_frac == 0
VISION_MAX = 40     # reveal radius at owned_frac == FULL_VISION_THRESHOLD
FULL_VISION_THRESHOLD = 0.75   # owned_frac at/above which the whole map is revealed

CARAVAN_VISION_RADIUS = 7   # much smaller than a scouting Commander's (see
                            # COMMANDER_VISION_RADIUS below) -- a caravan/ship
                            # isn't scouting, it's just passing through, but
                            # its crew still sees more than the single cell
                            # it's standing on right now

ROUTE_REVEAL_RADIUS = 3    # corridor width (flat square, not a BFS -- a road/
                           # trade route can run hundreds of cells long, so a
                           # cheap flat window per cell instead of a full
                           # terrain-aware BFS per cell) around every cell a
                           # player-owned road or trade route actually runs
                           # over, so it reads as a real, lived-in corridor
                           # instead of a razor-thin one-cell-wide slit

# Byte-translate table: fog stores 0 (hidden) / 1 (revealed) per cell; a
# render-time mask needs 255 (hidden) / 0 (revealed) — index i -> table[i].
_INVERT_TABLE = bytes([255] + [0] * 255)


def _reveal_around(reveal, w, h, cx, cy, radius):
    """Flat square window (Chebyshev distance, not a BFS) of every cell
    within `radius` of (cx,cy) -- the corridor a road/trade route reveals
    around each cell it actually runs over (see ROUTE_REVEAL_RADIUS).
    Deliberately not terrain-aware/BFS like Commander or Caravan vision:
    a route can be hundreds of cells long, so this has to stay cheap per
    cell, and a flat corridor reads just as well for "the road crew knows
    the surrounding ground" as a properly-shaped one would. x wraps (the
    map's seam is a real neighbor relationship -- see app/world/wrap.py);
    y never does, same as every other reveal in this module."""
    for dy in range(-radius, radius + 1):
        ny = cy + dy
        if not (0 <= ny < h):
            continue
        for dx in range(-radius, radius + 1):
            reveal(wrap.wrap_x(cx + dx, w), ny)


def _walk_reveal(reveal, w, h, ax, ay, bx, by, radius=0):
    """Call `reveal` (or _reveal_around, if `radius` > 0) on every integer
    cell along the wrap-aware shortest line from (ax,ay) to (bx,by) -- same
    idea as map_view.py's _river_span, just walking cells instead of
    measuring a fractional span. A road/route segment is stored as just its
    two endpoints (see world.roads_by_region), so revealing only the
    endpoints would leave the middle of a long segment dark even though
    it's a real, built road. Sea trade routes can genuinely cross the seam
    now (see trade._capital_sea_path/_land_path_between's wrap-aware
    pathing), so this walks the actual shorter wrap-aware line rather than
    always the direct one."""
    for x, y in wrap.walk_line_wrap((ax, ay), (bx, by), w):
        if not (0 <= y < h):
            continue
        if radius > 0:
            _reveal_around(reveal, w, h, x, y, radius)
        else:
            reveal(x, y)


def init_fog(world):
    """Called once at world-gen: allocate the fog buffer and reveal the
    player's starting foothold (and whatever's already in its vision
    radius)."""
    world.fog = bytearray(world.w * world.h)
    world.fog_version = 0
    world.fog_fully_revealed = False
    world.discovered_factions = set()
    world.fog_bbox = None    # (x0, y0, x1, y1) of everything ever revealed —
                              # see recompute(); lets the world-view camera
                              # zoom out to "as far as discovered" instead of
                              # the whole (mostly-unrevealed) map.
    if world.player_faction_idx is not None:
        recompute(world)


def fog_mask_bytes(world):
    """255=hidden / 0=revealed, for compositing — see app/ui/map_view.py."""
    return bytes(world.fog).translate(_INVERT_TABLE)


def _owned_frac(world):
    player = world.factions[world.player_faction_idx]
    return player.meta.get("cells", 0) / max(1, world.total_land_cells)


def _vision_radius(world):
    frac = min(1.0, _owned_frac(world))
    return VISION_MIN + (VISION_MAX - VISION_MIN) * math.sqrt(frac)


def recompute(world):
    """Reveal every cell the player currently owns, plus everything within
    the current vision radius of that territory's boundary; track any newly
    -revealed faction as discovered. Cheap: bounded by owned-cell count plus
    a depth-capped BFS (~O(perimeter * radius)), not O(w*h) — except the
    one-time full-map reveal once owned_frac clears FULL_VISION_THRESHOLD,
    which happens at most once since fog is monotonic (guarded by
    fog_fully_revealed so it doesn't re-scan every turn after that)."""
    if world.player_faction_idx is None or world.fog_fully_revealed:
        return
    w, h = world.w, world.h
    fog = world.fog
    owner = world.owner
    newly_revealed = []
    bounds = [None, None, None, None]   # minx, miny, maxx, maxy this call

    def reveal(x, y):
        i = y * w + x
        if not fog[i]:
            fog[i] = 1
            newly_revealed.append((x, y))
            if bounds[0] is None:
                bounds[0] = bounds[2] = x
                bounds[1] = bounds[3] = y
            else:
                if x < bounds[0]: bounds[0] = x
                if x > bounds[2]: bounds[2] = x
                if y < bounds[1]: bounds[1] = y
                if y > bounds[3]: bounds[3] = y

    if _owned_frac(world) >= FULL_VISION_THRESHOLD:
        for y in range(h):
            for x in range(w):
                reveal(x, y)
        world.fog_fully_revealed = True
    else:
        player_idx = world.player_faction_idx
        max_steps = int(math.ceil(_vision_radius(world)))
        dist = {}
        frontier = deque()
        for cid in world.factions[player_idx].meta.get("regions", []):
            for (x, y) in world.regions[cid].cells:
                if (x, y) not in dist:
                    dist[(x, y)] = 0
                    frontier.append((x, y))
                reveal(x, y)
        while frontier:
            x, y = frontier.popleft()
            d = dist[(x, y)]
            if d >= max_steps:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = wrap.wrap_x(x + dx, w), y + dy
                if 0 <= ny < h and (nx, ny) not in dist:
                    dist[(nx, ny)] = d + 1
                    frontier.append((nx, ny))
                    reveal(nx, ny)

        # Commander vision: an independent depth-capped BFS seeded from each
        # of the player's commanders' current positions (app/world/
        # commander.py) — real exploration value regardless of owned
        # territory, which is the whole point: an island start with no
        # adjacent unclaimed land can still see somewhere by walking/
        # sailing a commander there.
        # A Cartographer's Guild does not reveal ground of its own (beyond its
        # small local survey below) -- it widens what everything your realm
        # already has out in the world reports back. See resources.py's Guild
        # section: this is the whole mechanic, and it is why the building is
        # worth a great deal to a realm running caravans and almost nothing to
        # a hermit.
        from app.world.resources import (cartographer_radius,
                                         cartographer_traffic_bonus,
                                         CARTOGRAPHER_LOGS_TRAFFIC)
        guild = cartographer_traffic_bonus(world, player_idx)

        from app.world.commander import COMMANDER_VISION_RADIUS
        commander_reach = COMMANDER_VISION_RADIUS + guild
        for cmd in world.commanders:
            if cmd.faction_idx != player_idx:
                continue
            cx, cy = cmd.pos
            cdist = {(cx, cy): 0}
            cfrontier = deque([(cx, cy)])
            reveal(cx, cy)
            while cfrontier:
                x, y = cfrontier.popleft()
                d = cdist[(x, y)]
                if d >= commander_reach:
                    continue
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = wrap.wrap_x(x + dx, w), y + dy
                    if 0 <= ny < h and (nx, ny) not in cdist:
                        cdist[(nx, ny)] = d + 1
                        cfrontier.append((nx, ny))
                        reveal(nx, ny)

        # The Guild's own local survey: the ground within a few days' ride,
        # which a guild really would have walked and measured itself
        # (resources.advance_cartographers grows the radius; this only turns it
        # into revealed ground). Deliberately small and hard-capped -- enough
        # that an expensive building does something the turn it finishes,
        # nowhere near enough to be a map.
        for st in world.settlements:
            if st.faction_idx != player_idx:
                continue
            reach = int(cartographer_radius(st))
            if reach <= 0:
                continue
            sx, sy = st.pos
            sdist = {(sx, sy): 0}
            sfrontier = deque([(sx, sy)])
            reveal(sx, sy)
            while sfrontier:
                x, y = sfrontier.popleft()
                d = sdist[(x, y)]
                if d >= reach:
                    continue
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = wrap.wrap_x(x + dx, w), y + dy
                    if 0 <= ny < h and (nx, ny) not in sdist:
                        sdist[(nx, ny)] = d + 1
                        sfrontier.append((nx, ny))
                        reveal(nx, ny)

        # Roads and trade routes the player owns reveal the ground they
        # actually run over — a caravan/road crew knows the way, even
        # through wildland or foreign territory well outside normal
        # vision range. Cheap to just re-walk every turn (see this
        # function's own docstring on why re-scanning owned territory
        # every call is fine): reveal() is a no-op for anything already
        # revealed, and fog is monotonic besides, so this only actually
        # does anything the first time a given stretch is built/traveled.
        route_reach = ROUTE_REVEAL_RADIUS + guild
        for cid in world.factions[player_idx].meta.get("regions", []):
            for (ax, ay), (bx, by), _tier in world.roads_by_region.get(cid, []):
                _walk_reveal(reveal, w, h, ax, ay, bx, by, radius=route_reach)
        for proj in world.road_projects:
            if proj.faction_idx != player_idx:
                continue
            for x, y in proj.built_cells:
                _reveal_around(reveal, w, h, x, y, route_reach)
        for route in world.trade_routes:
            if route["a_faction"] != player_idx and route["b_faction"] != player_idx:
                continue
            for x, y in route["cells"]:
                _reveal_around(reveal, w, h, x, y, route_reach)
        for proj in world.trade_route_projects:
            if proj.a_idx != player_idx and proj.b_idx != player_idx:
                continue
            for seg in proj.built_segments:
                for x, y in seg:
                    _reveal_around(reveal, w, h, x, y, route_reach)

        # Trade caravans/ships currently in transit: a real radius around
        # wherever the player's own caravan actually is right now (see
        # CARAVAN_VISION_RADIUS above) — more than the bare route-path
        # reveal above gives on its own, same shape as the Commander BFS
        # just above, just a smaller radius since a caravan isn't scouting.
        caravan_reach = CARAVAN_VISION_RADIUS + guild
        for caravan in world.trade_caravans:
            if caravan.seller_idx != player_idx and caravan.buyer_idx != player_idx:
                continue
            # The pilot's log. Without a Guild a caravan tells you only where
            # it is right now; with one, the whole stretch it has already
            # covered comes back as a written record -- which is literally what
            # the Casa de la Contratacion and the VOC compiled their charts
            # from. This is what makes a Guild worth having to a trading realm
            # specifically: it turns every voyage into a survey after the fact.
            if guild and CARTOGRAPHER_LOGS_TRAFFIC:
                path = getattr(caravan, "path", None) or ()
                if path:
                    # Same outbound/return ordering TradeCaravan.pos uses, so
                    # "already covered" means the same thing to both.
                    ordered = (path if getattr(caravan, "leg", "outbound") == "outbound"
                               else list(reversed(path)))
                    frac = min(1.0, getattr(caravan, "turn_progress", 0)
                               / max(1, getattr(caravan, "turns_total", 1) or 1))
                    for x, y in ordered[:max(1, int(len(ordered) * frac))]:
                        if 0 <= y < h:
                            _reveal_around(reveal, w, h, wrap.wrap_x(x, w), y, guild)
            cx, cy = caravan.pos
            cdist = {(cx, cy): 0}
            cfrontier = deque([(cx, cy)])
            reveal(cx, cy)
            while cfrontier:
                x, y = cfrontier.popleft()
                d = cdist[(x, y)]
                if d >= caravan_reach:
                    continue
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = wrap.wrap_x(x + dx, w), y + dy
                    if 0 <= ny < h and (nx, ny) not in cdist:
                        cdist[(nx, ny)] = d + 1
                        cfrontier.append((nx, ny))
                        reveal(nx, ny)

    if newly_revealed:
        world.fog_version += 1
        bx0, by0, bx1, by1 = bounds[0], bounds[1], bounds[2] + 1, bounds[3] + 1
        existing = getattr(world, "fog_bbox", None)
        world.fog_bbox = ((bx0, by0, bx1, by1) if existing is None else
                          (min(existing[0], bx0), min(existing[1], by0),
                           max(existing[2], bx1), max(existing[3], by1)))
        player_idx = world.player_faction_idx
        player = world.factions[player_idx]
        from app.world.diplomacy import establish_contact
        for x, y in newly_revealed:
            o = owner[y][x]
            if o >= 0 and o != player_idx and o not in world.discovered_factions:
                world.discovered_factions.add(o)
                establish_contact(world, player.id, world.factions[o].id)
