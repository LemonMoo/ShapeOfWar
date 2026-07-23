# Shapes of War — Handoff

Python/Tkinter/Pillow desktop 4X strategy game, single dev, ~8,500 LOC. Turn-based,
procedurally generated fantasy world. This file is context for a design/ideas
discussion — not a task list.

## Architecture

- `World` (app/world/worldgen.py) — all game state, plain-data objects only (must
  stay pickle-safe: no closures, no bound methods stored on it — save/load is raw
  `pickle`, app/core/save.py).
- `MapView` (app/ui/map_view.py, ~2200 lines) — Tkinter Frame, renders the world to
  a canvas, owns all click/pan/zoom/panel UI. Free camera (drag-pan, wheel-zoom,
  animated zoom-to-target on drill-down). Three zoom levels: World → Region (a
  faction's regions) → Village (every village *that faction* owns, across all its
  regions — not scoped to one region).
- `App` (app/ui/app.py) — tk.Tk subclass, screen switching, glues the interactive
  battle minigame to the turn loop.
- Turn loop: `resources.advance_turn()` lazily imports and calls each domain
  module's per-turn hook in sequence (trade, construction, expansion, commander,
  vision).

## Domain modules (app/world/)

- `worldgen.py` — map gen: 2-3 continents on distinct climate bands (banded by
  distance from the equator, not raw row, so mirrored continents don't get
  identical climates), elevation/rivers via priority-flood hydrology, factions,
  regions, settlements, villages, roads. Region names draw from a single
  ~10,000-combination pool spanning many fantasy traditions (not per-species) —
  generated before any faction/species claims land, so there was nothing to
  flavor a species-specific pick with anyway.
- `vision.py` — fog of war. Two-state (unexplored/revealed), monotonic, radius
  scales with owned-territory fraction; tracks a running `fog_bbox` of everything
  ever revealed (camera zooms to that, not the whole map).
- `expansion.py` — unclaimed "wildland" regions w/ garrison strength, adjacency-
  gated claiming, multi-turn `ClaimProject`, resolved via an interactive
  battlefield (not an instant formula) when the player is involved. Wildland
  claims only ever yield villages (1-3, scaled by area) — no free City, Town, or
  Castle; those require an actual construction project like everyone's first one
  did.
- `diplomacy.py` / `trade.py` — deterministic first-contact reputation on fog
  discovery/shared border. Trade routes (land *and* sea) require an explicit
  proposal (player or AI) that the other faction can actually decline
  (`evaluate_trade_route` — standing, species affinity, real economic
  complementarity; same weighing `form_alliance` uses, lower bar). A decline sets
  a cooldown before that pair can be re-proposed. Land routes are then physically
  built over turns; sea routes open immediately once agreed (nothing to
  construct across open water). Caravans carry real transit risk (war breaking
  out mid-route).
- `construction.py` — player-built castles/cities/towns (cost+turns+connecting
  road) and shipyards (steep one-time cost, unlocks free/fast ship launches at
  that city).
- `commander.py` — a player-controlled scout unit (no combat/death risk). Ships
  are physical map entities (not a boolean flag): disembarking leaves the ship
  beached at the last water cell crossed; a commander *next to* (not just
  exactly on) a beached ship can board or dismantle it. Movement routes
  sea-then-land instead of one mixed Dijkstra, so the coastline is crossed at
  most once — never ocean→land→ocean, which used to strand a shipless commander
  mid-route. Orders into fog never say "can't reach that" (which would itself
  leak what's out there); they just walk/sail as far as possible and stop at the
  edge. Basic ships cost Wood+Gold only (no Iron — an iron-poor start used to be
  a dead end).
- `resources.py` — economy (region yield, storage caps, upkeep), turn/season
  advance (season = 8 turns).

## Battle system (app/battle/)

Real-time particle-collision micro-sim (`Battle`, `Army`, `Unit`) used only for
player-involved fights: manual attacks and wildland-claim battles. AI-vs-AI and
AI-vs-wildland resolve instantly via formula (`expansion.claim_odds`). Wildland
defenders are 10% weaker than regular troops. Winning transfers region ownership
(settlements, cells, faction stats) — the map/battle loop is fully connected.

## Conventions worth knowing

- Pathfinding: one Dijkstra implementation (`_path_dijkstra`/`_elev_cost`/
  `_sea_cost` in worldgen.py) reused for every land/sea route in the game —
  roads, trade routes, commander movement, ship movement. Commander movement
  additionally has a "never fail, just get as close as possible" variant
  (`_path_dijkstra_nearest`) specifically so an order sent into fog can't leak
  information through an explicit rejection.
- Diplomatic "ask, and the other side might say no": `form_alliance` and
  `evaluate_trade_route` both score standing + species affinity + resource
  complementarity against a threshold and return a real decline with a reason,
  rather than a proposal being a formality once some gate is cleared. Declines
  set a cooldown (see expansion.py's claim cooldown for the original pattern)
  instead of being instantly re-askable.
- Multi-turn project countdowns use `math.ceil`, never `round()` (banker's
  rounding made displayed countdowns jump/stall).
- Stats "rolled once at placement" (upkeep, tax income, population) are
  computed by the caller and passed into plain constructors, not randomized
  inside `__init__`.
- Schema changes tolerate old saves via `getattr(obj, "new_field", default)`
  rather than migrations — this is an actively-changing solo project, not
  treated as precious data.
- Fixed vs. scaled counts: the *starting* foothold gets exact fixed counts
  (1 city/2 towns/3 villages, no castle); *ongoing* territory expansion still
  scales village counts with the claimed region's area, capped at 1-3.
- Expensive per-frame/per-turn work is gated behind a version counter bumped
  only when the underlying thing actually changes (e.g. `world.territory_version`
  gates the full political-map color rebuild) rather than recomputed
  unconditionally every turn/click.
- No art assets — everything is Tkinter Canvas primitives or Pillow pixel
  buffers, no sprites/icon fonts.

## Recent session arc (chronological, latest first)

1. Trade routes now require mutual agreement: sea lanes used to open the
   instant two coastal factions were "eligible," with no consent from either
   side. Both land and sea now go through one propose-and-agree flow, with a
   real chance of decline.
2. Ship movement fixed at the root: routing now guarantees the coastline is
   crossed at most once (was a single mixed land/sea Dijkstra that could
   strand a shipless commander), and no move order into fog of war ever
   reports failure — it just goes as far as it can and stops.
3. A commander can board/dismantle a ship standing *next to* it, not only
   exactly on its cell (the ship sits on water, which a walking commander can
   never literally stand on — the old exact-match check basically never
   fired).
4. Village view (zoomed into a region) now shows every village the faction
   owns across all its regions, not just that one. Added a world-view
   population counter (settlements + villages, faction-wide).
5. Region names draw from one large, tradition-spanning pool instead of a
   small per-species list — large maps used to exhaust it and fall back to
   "Name 47"-style numbered duplicates.
6. Wildland claims no longer hand out a free Castle (villages only, 1-3).
   Basic ships no longer cost Iron. Build Ship panel now shows cost/build
   time and exactly which resources are missing.
7. Map generation overhaul: 2-3x larger, multiple real continents on
   distinct climate bands, forest/mountain map symbols + legend, retroactive
   dirt roads connecting newly claimed regions into the road network.
8. Fixed overlapping settlement/village placement in newly claimed wildland,
   a duplicate `_SHIP_STYLE` constant mixing up beached-ship/sea-caravan
   colors, and end-turn/region-click lag from unconditional color-raster
   rebuilds + redundant coastal-distance BFS scans.
9. Settlement population/prosperity, city-driven village growth, and an
   interactive battle planning phase (drag units into position before a
   fight).
10. Ships reworked from a boolean `has_ship` flag to physical `Ship`
    entities left beached on shore; shipyards (steep cost, free/fast
    launches). Wildland garrison claims fight an interactive battlefield
    instead of an instant coin-flip.

## Current gaps / things not yet done

- No population *growth* simulation — the population counter is a live sum,
  but individual settlement/village population is still a static flavor stat.
- No minimap.
- Trade routes are still capital-to-capital only, never a specific settlement.
- ~0.5% of AI factions can spawn with a foothold too small to fit all starting
  buildings (pure geography edge case, pre-existing).
- Camera/zoom position isn't remembered per-faction/region between visits.
- No GitHub remote configured for this repo yet — local git history only.
