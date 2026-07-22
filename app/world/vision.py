"""Fog of war: what the player has actually seen. Two-state (unexplored /
revealed — no dimmed "remembered" state), monotonic (once seen, always
shown), with the reveal radius scaling up as the player's own territory
grows, so a freshly-founded, single-county realm can't see the whole
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

VISION_MIN = 6      # reveal radius (world cells) at owned_frac == 0
VISION_MAX = 40     # reveal radius at owned_frac == FULL_VISION_THRESHOLD
FULL_VISION_THRESHOLD = 0.75   # owned_frac at/above which the whole map is revealed

# Byte-translate table: fog stores 0 (hidden) / 1 (revealed) per cell; a
# render-time mask needs 255 (hidden) / 0 (revealed) — index i -> table[i].
_INVERT_TABLE = bytes([255] + [0] * 255)


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
        for cid in world.factions[player_idx].meta.get("counties", []):
            for (x, y) in world.counties[cid].cells:
                if (x, y) not in dist:
                    dist[(x, y)] = 0
                    frontier.append((x, y))
                reveal(x, y)
        while frontier:
            x, y = frontier.popleft()
            d = dist[(x, y)]
            if d >= max_steps:
                continue
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in dist:
                    dist[(nx, ny)] = d + 1
                    frontier.append((nx, ny))
                    reveal(nx, ny)

        # Commander vision: an independent depth-capped BFS seeded from each
        # of the player's commanders' current positions (app/world/
        # commander.py) — real exploration value regardless of owned
        # territory, which is the whole point: an island start with no
        # adjacent unclaimed land can still see somewhere by walking/
        # sailing a commander there.
        from app.world.commander import COMMANDER_VISION_RADIUS
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
                if d >= COMMANDER_VISION_RADIUS:
                    continue
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in cdist:
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
