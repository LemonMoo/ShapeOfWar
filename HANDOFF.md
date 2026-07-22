# Shapes of War — Handoff

Python/Tkinter/Pillow desktop 4X strategy game, single dev, ~7,200 LOC. Turn-based,
procedurally generated fantasy world. This file is context for a design/ideas
discussion — not a task list.

## Architecture

- `World` (app/world/worldgen.py) — all game state, plain-data objects only (must
  stay pickle-safe: no closures, no bound methods stored on it — save/load is raw
  `pickle`, app/core/save.py).
- `MapView` (app/ui/map_view.py, ~2000 lines) — Tkinter Frame, renders the world to
  a canvas, owns all click/pan/zoom/panel UI. Free camera (drag-pan, wheel-zoom,
  animated zoom-to-target on drill-down).
- `App` (app/ui/app.py) — tk.Tk subclass, screen switching, glues the interactive
  battle minigame to the turn loop.
- Turn loop: `resources.advance_turn()` lazily imports and calls each domain
  module's per-turn hook in sequence (trade, construction, expansion, commander,
  vision).

## Domain modules (app/world/)

- `worldgen.py` — map gen (elevation/climate/biomes/rivers via priority-flood
  hydrology), factions, regions, settlements, villages, roads.
- `vision.py` — fog of war. Two-state (unexplored/revealed), monotonic, radius
  scales with owned-territory fraction; tracks a running `fog_bbox` of everything
  ever revealed (camera zooms to that, not the whole map).
- `expansion.py` — unclaimed "wildland" regions w/ garrison strength, adjacency-
  gated claiming, multi-turn `ClaimProject`, resolved via an interactive
  battlefield (not an instant formula) when the player is involved.
- `diplomacy.py` / `trade.py` — deterministic first-contact reputation on fog
  discovery/shared border; trade gated on diplomacy standing; land routes are
  physically built over turns, sea routes automatic; caravans carry real transit
  risk (war breaking out mid-route).
- `construction.py` — player-built castles (cost+turns+connecting road) and
  shipyards (steep one-time cost, unlocks free/fast ship launches at that city).
- `commander.py` — a player-controlled scout unit (no combat/death risk). Ships
  are physical map entities (not a boolean flag): disembarking leaves the ship
  beached at the last water cell crossed; board/dismantle/rebuild it later.
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
  roads, trade routes, commander movement, ship movement.
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
  scales settlement/village counts with the claimed region's area.
- No art assets — everything is Tkinter Canvas primitives or Pillow pixel
  buffers, no sprites/icon fonts.

## Recent session arc (chronological, latest first)

1. Village + settlement population (headcount, adults/children split; villages
   80–450, towns 1.2–3.5k, cities 4–12k, castles 500–1.5k pop) — flavor stat,
   static, doesn't feed the economy.
2. Stone roads render a brown "bridge" span where they cross a river.
3. Starting spawn normalized to 1 city/2 towns/3 villages/0 castle for every
   faction (was previously incidental). Fixed a bug where a capital's home
   region could be a degenerate all-lake Voronoi cell, silently zeroing that
   faction's starting villages.
4. World-view camera now zooms out only as far as fog has revealed, not the
   whole (mostly black) map.
5. Ships reworked from a boolean "has_ship" flag to physical `Ship` entities
   left beached on shore; shipyards (steep cost, free/fast launches).
6. Wildland garrison claims now fight an interactive battlefield instead of an
   instant coin-flip; commander right-click-to-move QoL; wildland defenders
   -10% strength.
7. Season length set to 8 turns/season; commander foundation (scout unit,
   ship-building, sailing) added specifically to solve island starts having
   no way to explore.

## Current gaps / things not yet done

- No population *growth* simulation — static flavor stat only.
- No minimap.
- ~0.5% of AI factions can spawn with a foothold too small to fit all starting
  buildings (pure geography edge case, pre-existing).
- Camera/zoom position isn't remembered per-faction/region between visits.
- Settlement "resources" model exists and is live (upkeep/tax/trade all feed
  real faction stockpiles) — this is *not* a placeholder anymore, unlike very
  early project history.
