# Shapes of War — Handoff Document

This document exists to bring a fresh coding agent (or a fresh human) up to
speed on this project with zero prior context. It captures not just *what*
exists but *why* — the design decisions, the conventions to keep following,
and where things are headed. Read this before touching code.

If you only read one other file, read `README.md` — it's the user-facing
architecture reference and stays accurate as the source of truth for file
layout and extension points. This document is the *narrative* layer on top:
history, intent, and the things a fresh agent would otherwise have to
rediscover the hard way.

## What this project is

A **standalone Windows desktop game**, built with Python's standard-library
Tkinter (no web stack, no external game engine) plus Pillow for smooth map
rendering. It has two scales:

- **Macro**: a procedurally generated fantasy world — continents, rivers,
  lakes, countries ("factions") of invented species, counties, and
  settlements (cities/castles/towns) — all click-to-explore on a 2D map.
- **Micro**: a real-time battlefield where armies of primitive-shape "soldiers"
  (circles, squares, triangles) fight it out with collision, projectiles, and
  simple AI.

There is currently **no connection between the two scales** — battles are
staged manually from the map (click an enemy → "Attack") and don't yet affect
county ownership or country stats. Wiring that loop up is the most likely
next milestone (see "Where this is heading" below).

## Origin story / how we got here

This was built **incrementally, one user request at a time**, each fully
implemented and visually verified before moving to the next. Roughly in
order:

1. Started as an HTML/JS/Canvas browser prototype (macro world map + micro
   shape battles). The user explicitly asked to **throw this away** and
   rebuild as a native desktop app — hence pure Python/Tkinter, no browser,
   no server. (There is no leftover HTML in the repo; it was deleted.)
2. Packaged as a standalone `.exe` via PyInstaller from day one — the user
   wants a double-clickable app, not a dev environment.
3. Map started as **real-world countries** (Natural Earth GeoJSON data), then
   the user pivoted hard: **no real-world geography** — a fully procedurally
   generated Earth-*like* world with invented species/factions instead. The
   GeoJSON data and loader were deleted; `worldgen.py` was born.
4. Added unit collision/bounce physics, sword/shield ASCII-glyph equipment
   markers on units (iterated several times on exact placement/rotation —
   see "Tuning knobs" for where these ended up), battle speed control,
   animated arrow projectiles for archers.
5. Added an ecology layer: fertility sub-map, driven by elevation + moisture
   + water proximity, converted into crop output per faction.
6. Added an elevation sub-map and real river generation (initially naive
   steepest-descent, which produced rivers that dead-ended randomly — the
   user flagged this, so it was rebuilt as proper **hydrology**: priority-flood
   depression filling + flow accumulation, so rivers always reach the sea or
   pool into a lake).
7. User asked for less-blurry, more-chaotic borders → switched map rendering
   from bilinear to nearest-neighbor at higher resolution, and switched
   territory assignment from smooth BFS to noise-warped weighted growth.
8. Added counties (sub-divisions of each country) with click-to-zoom
   (animated) and per-county fertility-derived stats — explicitly described
   by the user as **the future unit of control for territory conquest**.
9. Made country *and* county borders river-aware (weighted growth pays a
   surcharge to cross rivers/lakes, so real borders tend to follow them).
10. Added settlements — cities/castles/towns, counts scaling with country
    size, placement following terrain logic, generating/draining **generic
    "resources"** that the user has explicitly said are **not yet specified**
    (crops will fold into them eventually, but don't invent a resource model
    — ask, or keep it generic, until told otherwise).

**Every feature above was verified by actually running the app** (headless
Python driving the Tkinter app object, plus real screenshots via a background
browser/screenshot tool) before being reported done. See "How this was
tested" — this pattern is worth continuing.

## Directory layout

```
D:\Claude Project\
  main.py                 entry point — from source: `python main.py`
  build.bat                double-click to rebuild dist\ShapesOfWar.exe
  dist\ShapesOfWar.exe     the packaged standalone app (PyInstaller onefile)
  README.md                 user-facing architecture + extension guide
  HANDOFF.md                 this file
  app\
    core\   events.py       tiny pub/sub EventBus (see below)
    world\  nation.py        Nation class (a faction; free-form stats/meta dicts)
            world_map.py     WorldMap: factions dict + relationship graph, Stance enum-ish consts
            lexicon.py       word lists + name generators (species, factions, counties, settlements)
            worldgen.py      THE BIG ONE — the entire procedural world generator (~670 lines)
    battle\ shapes.py        shape registry (register_shape/draw_shape) — no art assets, ever
            unit_types.py    UNIT_TYPES dict — pure data per unit archetype
            unit.py          Unit class — seek-nearest-enemy AI, one update(dt) method
            battle.py        Battle + Army classes — collision resolution, projectiles, victory check
    ui\     theme.py         color/font constants
            map_view.py      THE OTHER BIG ONE — world map rendering (~600 lines)
            battle_view.py   battlefield rendering + the Tk `after()` game loop
            app.py           main window: top nav, screen switching, battle staging glue
```

No `data/` files remain (the real-world GeoJSON was deleted in step 3 above).
`app/data/__init__.py` is an empty leftover package — harmless, could be
removed.

**There is no git repository in this directory** (`git status` reports "not
a git repository"). If you want version history/rollback safety going
forward, `git init` and commit the current state first — right now the only
safety net is this handoff doc and your own diligence.

## Core architectural conventions (keep following these)

1. **No art assets, ever.** Everything is drawn with Tkinter Canvas primitives
   (ovals, rectangles, polygons, text glyphs) or computed pixel buffers
   (Pillow `Image.putdata`). This was an explicit constraint from the first
   message. Don't introduce image files, sprite sheets, or icon fonts.

2. **Data-driven extensibility.** New unit types, species, settlement kinds,
   shapes, relationship stances are all just entries in a dict/list constant
   — see "Extending it" in `README.md`. When adding a new *kind* of anything,
   follow this pattern: a `_TYPES` dict of pure data, consumed generically by
   the code that uses it. Don't hardcode a new `if kind == "x"` branch when a
   data table would do.

3. **The shared `EventBus`** (`app/core/events.py`) exists for decoupling
   future systems (economy ticks, diplomacy AI, sound, turn structure) from
   what exists today. Currently only `nation:added`, `relationship:changed`,
   `battle:over` are emitted. It's underused so far — lean on it more as the
   game grows a "tick" or "turn" concept.

4. **World generation is a pure function.** `generate_world(width, height,
   seed, n_factions) -> World` in `worldgen.py` has no UI dependency and can
   be called/tested headlessly. Keep it that way — it's the easiest thing in
   the codebase to unit-test and the thing most worth testing before wiring
   into UI.

5. **The `World` object is a big bag of parallel grids + object lists** (see
   full field list below). This is deliberately simple/flat rather than an
   ECS or class hierarchy — fits a small single-player game. Don't over
   engineer this into a generic entity system unless the game's scope
   actually demands it.

6. **UI is one Tkinter window with screen-swapping frames**, not multiple
   windows. `MapView` and `BattleView` are both `tk.Frame` subclasses stacked
   with `.place()` and raised/lowered via `tkraise()`. Follow this pattern
   for any new screen (e.g. a future "Country economy" screen).

## Key data structures (current shape, as of this handoff)

### `World` (`app/world/worldgen.py`)
The central object. Grids are row-major `list[list[...]]` indexed `[y][x]`.
```python
World.w, World.h                  # grid dimensions (default 440x264)
World.owner[y][x]                 # faction index, or OCEAN (-1)
World.height[y][x]                # elevation 0..1
World.fertility[y][x]             # 0..1, land only (0 on water)
World.sea_level                   # float threshold on height
World.rivers                      # list of {"cells": [(x,y),...], "flow": float}
World.river_cells                 # set of (x,y) — every cell any river passes through
World.lake_cells                  # set of (x,y) — land cells that are lake surface
World.counties                    # list[County], index == county id
World.county_grid[y][x]           # county id, or -1
World.settlements                 # list[Settlement], index == settlement id
World.factions                    # list[Nation], index == owner value
World.world_map                   # WorldMap instance (relationship graph)
```

### `Nation` (`app/world/nation.py`) — represents a country/faction
```python
nation.id, nation.name, nation.color, nation.center  # (x,y) normalized 0..1
nation.stats = {"military", "morale", "economy", "crops",
                "res_gen", "res_drain"}     # free-form dict, extend freely
nation.meta = {"species", "trait", "cells", "capital", "fertility",
               "counties": [county_id...], "bbox": (x0,y0,x1,y1),
               "settlements": [settlement_id...]}
```

### `County` (`app/world/worldgen.py`)
```python
county.id, county.faction_idx, county.name, county.cells, county.center, county.bbox
county.stats = {"area", "fertility", "crops", "res_gen", "res_drain"}
county.meta_settlements   # list[settlement_id] — NOTE: not in .meta dict,
                          # it's a plain attribute added post-hoc in
                          # _generate_settlements(). Slight inconsistency
                          # with Nation.meta — worth normalizing if you touch this.
```

### `Settlement` (`app/world/worldgen.py`)
```python
settlement.id, .kind ("city"|"castle"|"town"), .name, .pos (x,y grid cell)
settlement.faction_idx, .county_id, .gen, .drain, .net (property = gen - drain)
```
`SETTLEMENT_TYPES` dict drives generation: per-kind gen/drain ranges,
placement weights (fertility/river/coast/border/elevation), density
(`per_cells`), min/max count, spacing. **The resource numbers here are
placeholders** — the user explicitly said "general resources" are unspecified
pending further design. Don't invent semantics for them (e.g. don't assume
they map to gold/food/wood) without asking.

### `Unit` / `Army` / `Battle` (`app/battle/`)
Separate from the World entirely — battles are self-contained simulations
staged from two `Nation` objects' `stats["military"]` (see `App._army_for` in
`app/ui/app.py`), not yet connected to counties/settlements at all.

## Notable algorithms (worth understanding before modifying)

- **Territory assignment** (`_assign_territories`, `_grow_weighted` in
  `worldgen.py`): multi-source **Dijkstra**, not simple nearest-capital
  Voronoi. Each cell has a base traversal cost of `1 + noise` (creates
  chaotic/organic border wiggle), plus a surcharge (`_COUNTRY_RIVER_PEN=12`,
  `_COUNTY_RIVER_PEN=7`) to cross a river/lake cell — so expanding regions
  stop at natural water barriers. Same function (`_grow_weighted`) is reused
  for both country-level and county-level partitioning.

- **Rivers** (`_generate_hydrology`): a real hydrology pipeline, not a toy.
  1. Priority-flood (`heapq`-based Barnes algorithm) fills depressions in the
     height field so every land cell has a monotonic downhill path to the
     sea — guarantees no river dead-ends randomly.
  2. Cells that had to be raised significantly to drain (`_LAKE_DEPTH`
     threshold) become **lakes**.
  3. D8 flow direction (steepest descent on the filled DEM) + flow
     accumulation (sum upstream area) — a cell only becomes a river once
     enough water drains through it, so rivers emerge in valleys rather than
     appearing arbitrarily on ridges.
  4. Polylines are traced from river "heads" (sources with no incoming flow)
     downstream to their mouth (sea or lake).

- **Fertility** (`_compute_fertility`): weighted blend of moisture noise
  (`_FERT_MOISTURE=0.40`), lowland-ness (`_FERT_LOWLAND=0.30`, i.e. `1 -
  normalized_elevation`), and water proximity (`_FERT_WATER=0.30`, exponential
  decay via `_WATER_FALLOFF=13` cells) — rivers and lakes count as water
  sources for irrigation, not just the ocean.

- **Settlement placement** (`_generate_settlements`): each candidate cell is
  scored per settlement type using precomputed BFS distance fields (to coast,
  to water, to a foreign border) blended with fertility and elevation via
  per-type weights, then placed greedily with a minimum-spacing constraint.

## UI rendering approach (`map_view.py`)

The map is rendered as a **Pillow `Image` built from a flat RGB pixel list**
(`Image.putdata`), not drawn cell-by-cell on the Tkinter canvas — this is a
critical performance decision (render is ~10ms even at 440×264 with three
color modes cached). Key points if you touch this file:

- **Colors are precomputed once per world** in `_precompute_colors()` into
  several flat pixel arrays (`_px_pol`, `_px_fert`, `_px_elev`, `_px_county`,
  plus `_hi` selection-highlight variants). Rebuilding these is only cheap
  relative to *not* rebuilding them every frame — don't call this in a
  per-frame render path.
- **`_base_img` is cache-invalidated by a key** (`_base_key`) reflecting
  mode/selection/zoom state — `_ensure_base()` only rebuilds the PIL image
  when that key changes. If you add new interactive state that changes the
  map's colors, remember to fold it into the cache key or you'll get stale
  renders.
- **Scaling uses `Image.NEAREST`, not bilinear** — this was a deliberate
  fix for a "blurry borders" complaint. Don't switch this back without a
  strong reason; sharp pixel-art-style borders are the intended look now.
- **County zoom is a smooth animation**, not an instant cut: `view` /
  `view_target` are `[x0,y0,x1,y1]` viewport rects in grid space, eased 25%
  toward the target every 16ms via `_animate()` / `Frame.after()`. The
  viewport-crop-then-resize approach in `render()` means zooming doesn't
  rebuild the full-world image — it crops the cached base image to the
  current viewport.
- **Click handling is a small state machine** in `_on_click`: first click on
  a country selects it; second click on the *same already-selected* country
  triggers zoom; while zoomed, clicking a settlement/county selects it,
  clicking outside the zoomed country's territory exits back out.

## How this was tested (recommended to continue)

There's no formal test suite. The verification pattern used throughout was:

1. **Headless smoke tests** via `python -c "..."` — construct `App()`,
   force `app.update()`/`app.update_idletasks()` to force Tkinter layout,
   then directly call internal methods (`.render()`, `._toggle_mode()`,
   `.stage_battle()`, etc.) and print/assert on internal state. This catches
   crashes and logic errors fast without needing a visible window.
2. **Real visual verification** for anything UI/rendering related: launch the
   real app as a background process, take an actual OS-level screenshot
   (`System.Drawing` via PowerShell in this environment), and read the image
   back to confirm it *looks* right — not just that it didn't crash. This
   caught real problems headless tests couldn't (blurry borders, wrong sword
   angle, rivers not visually connecting to lakes, etc.).
3. **Scratch driver scripts** (in a temp scratchpad dir, not in the repo)
   that import the app and auto-trigger a scenario (e.g. auto-select a
   faction, auto-zoom into county view, auto-start a battle) so a screenshot
   catches the *interesting* state rather than the default idle screen.
4. Before declaring any feature done: **rebuild `dist\ShapesOfWar.exe`** via
   the same PyInstaller command in `build.bat` and re-verify it launches
   standalone (not just `python main.py` from source) — PyInstaller bundling
   has bitten this project before (e.g. confirming Pillow/ImageTk actually
   gets bundled correctly).

If you set up a real test framework going forward, `worldgen.generate_world()`
being a pure function with a `seed` parameter is the natural thing to build
deterministic tests around.

## Build / run reference

```powershell
# Run from source (needs Python 3.10+, tkinter stdlib, and Pillow):
python -m pip install pillow
python main.py

# Rebuild the standalone exe (needs PyInstaller too):
python -m pip install pyinstaller pillow
python -m PyInstaller --noconfirm --onefile --windowed --name "ShapesOfWar" main.py
# or just double-click build.bat
```
Output: `dist\ShapesOfWar.exe` (~14 MB, self-contained, no console window).

## Known rough edges / inconsistencies worth knowing about

- `County.meta_settlements` is a bare attribute, not inside `County.stats` or
  a `.meta` dict like `Nation` uses — minor API inconsistency from
  incremental development. Fine to leave, but don't copy the pattern forward.
- `app/data/__init__.py` is an empty vestigial package from the deleted
  real-world-map era. Harmless dead weight.
- No git repository exists yet in this directory — strongly recommend
  initializing one before making further changes, so there's a rollback
  path.
- Settlement "resources" (`gen`/`drain`) are placeholder numbers with no
  actual gameplay effect yet — they're computed and displayed but nothing
  consumes them. Same for county/country crop output — it's *displayed* but
  doesn't feed into anything (no economy tick, no army upkeep).
- Battles and the world map are **entirely disconnected** — winning a battle
  currently only updates a status-bar message (`bus.on("battle:over", ...)`
  in `app.py`). No county changes hands, no faction stats change.

## Where this is heading (explicit user intent, not yet built)

The user has been building toward — and has explicitly named as a future
step — a **conquest loop**: winning a battle staked on a border county should
transfer that county (and its settlements) to the victor, updating both
factions' aggregate stats. Counties were *specifically* described by the user
as "what can be fought for and control can be lost from losing a war in that
county" — this is the intended payoff for the whole county/settlement system
built so far. If the user asks to continue the natural roadmap, this is
almost certainly what they mean:

1. Pick (or let the user pick) a contested border county as the stake of a
   battle staged from the map.
2. On `battle:over`, if the attacker won, reassign that county's cells in
   `world.county_grid` / `world.owner` to the attacking faction, move its
   `Settlement` objects' `.faction_idx`, and recompute both factions'
   aggregate stats (`cells`, `crops`, `res_gen`/`res_drain`, `fertility`).
   This will also change `world.factions[i].meta["bbox"]` and might touch
   adjacency/relationships (`WorldMap.relationships_of`).
3. Likely needs a re-render of the cached map pixel buffers
   (`_precompute_colors()`) since faction ownership changed — this is the
   expensive one-time recompute, so consider whether it can be made
   incremental for just the affected county rather than the whole world.

Other things the user has floated in passing but not requested yet:
specifying what "resources" actually mean and having them affect army
upkeep/economy; turn-based structure; diplomacy AI that shifts relationships
over time. Don't build these speculatively — wait for the ask, per the
project's established "one explicit request at a time, fully verified"
rhythm.
