# Shapes of War

A minimal, extensible war-simulation game — a **standalone Windows desktop app**
built with Python + Tkinter. No browser, no art assets: soldiers are drawn from
primitive shapes (circles, squares, triangles, diamonds).

- **Macro scale:** a procedurally generated Earth-like world (fractal-noise
  continents and oceans), carved into fictional **factions** — each belonging to
  a fantasy **species** (Humans, Elves, Dwarves, Orcs, Goblins) — with a relationship graph (ally / neutral / enemy)
  derived from who borders whom. Every launch (and the **Generate New World**
  button) makes a fresh world. The panel's **View** button cycles five map
  modes: **Political**, **Fertility** (a barren→lush ecology heatmap),
  **Elevation** (terrain relief), **Biome** (mountain/forest/plains/coastal/
  desert/swamp — what a county can produce) and **Climate** (temperate/arid/
  cold/humid — a modifier on top of biome). Rivers are
  traced downhill from the peaks to the sea, drawn on every mode, and irrigate
  the land they pass through (raising nearby fertility). Rivers use real drainage
  (depression-filled terrain + flow accumulation), so they emerge in valleys,
  branch and merge, and always reach the sea or pool into a **lake**. Country
  and county borders are river-aware: territory growth pays a surcharge to
  cross water, so frontiers settle along rivers and lakeshores where they
  exist. Click your own country to inspect it, click it **again** to smoothly
  zoom in and reveal its **counties** — each a sub-region whose biome/climate
  determine what it produces (Grain, Iron, Wood, Gems, Spices, ... 15
  resources across 4 tiers). Clicking a **foreign** nation instead shows a
  diplomatic-only view (no drilling into its counties) with an **Attack**
  button if you're at war — it zooms to your shared border and lets you pick
  which frontline county to strike. Counties are the unit of control: winning
  a battle for one flips it to the attacker (with a blinking gold/red border
  and a "seized/failed" banner); losing zooms back out. Every country also
  founds **cities, castles and towns** (counts scale with its size): cities
  settle fertile, riverside or coastal land; castles guard frontiers and high
  ground; towns fill the countryside. Each draws Grain/Fresh Water (and
  castles a little Iron) from the faction's stockpile every turn — the
  **End Turn** button advances the season (Spring→Summer→Autumn→Winter) and
  recomputes every county's yield, each faction's stockpile, and its military
  strength (driven mainly by Iron/Steel reserves) from it. The world view
  marks cities; the county view shows every settlement, clickable for its
  upkeep. Click a county **again** to zoom in one level further to its
  **village view** — 3 villages for a small county in a small country, up to
  ~50 for a large county in a huge one. Villages are linked by simple straight
  dirt roads (a minimum spanning tree, so every village is reachable with no
  redundant roads); each village's farms are not drawn, but their output
  feeds straight into its county's Grain yield, scaled by local fertility.
- **Micro scale:** a 2D battlefield where shape-soldiers seek and fight in real
  time until one side is wiped out.

## Running

**As an app:** double-click `dist\ShapesOfWar.exe` (self-contained; no Python
needed — copy it anywhere). If you're iterating on the source locally, double-
click **`Play.bat`** instead — it rebuilds the exe from current source and then
launches it, so you never have to remember to run `build.bat` first. (A running
`.exe` can't rebuild/replace itself on Windows, which is why this is a separate
file rather than something the exe does on its own.)

**From source:** `python main.py` (requires Python 3.10+ with Tkinter — ships with
the standard Windows Python installer — and Pillow: `python -m pip install pillow`,
used to render the map with smooth, anti-aliased borders).

Click a faction on the map to inspect its species, stats and relationships;
click an enemy nation and then **Attack** to pick a frontline county and stage
a battle for it. **Generate New World** rolls a fresh map. On the battlefield:
**Start / Pause**, **Step** (one frame), **New Skirmish**,
and **Speed** (cycles 1x / 2x / 4x). Infantry & cavalry carry a sword (`t`, right
hand); infantry also carry a shield (`o`, left hand); archers loose arrows (`.`)
that fly to their target. Units collide and bounce rather than stacking.

## Building the exe

Double-click `build.bat` (or run it from a terminal). It runs PyInstaller and
produces `dist\ShapesOfWar.exe`. Re-run it after editing any game files.
Requires PyInstaller and Pillow: `python -m pip install pyinstaller pillow`
(PyInstaller bundles Pillow into the exe automatically).

## Architecture

```
main.py                 entry point
app/
  core/  events.py      pub/sub hub — new systems hook in without edits
  world/ nation.py      a faction (free-form stats/meta dicts, incl. species)
         world_map.py   factions + relationship graph, Stance constants
         lexicon.py     fantasy species + faction/county/settlement/village
                        name generators
         worldgen.py    procedural world: elevation, water, fertility,
                        moisture/biome/climate, rivers, river-aware
                        territories/counties, settlements + upkeep, and
                        villages + roads (County, Settlement, Village,
                        SETTLEMENT_TYPES, SETTLEMENT_UPKEEP)
         resources.py   the resource economy: RESOURCES/BIOME_YIELDS/
                        CLIMATE_MODIFIERS/SEASON_MODIFIERS, biome/climate
                        classification, per-county yield, and the turn loop
                        (seed_initial_stockpiles, advance_turn)
         territory.py   county conquest: ownership/resource/relationship
                        bookkeeping when a battle changes who owns a county
  battle/shapes.py      shape registry (register_shape) — the "art"
         unit_types.py  unit archetypes (pure data)
         unit.py        one soldier; simple seek-and-attack AI in update()
         battle.py      battle sim + Army
  ui/    theme.py       colors/fonts
         map_view.py    macro map screen (raster render + click-select)
         battle_view.py battlefield screen (renders + runs the sim loop)
         app.py         main window, screen switching, battle staging
```

## Extending it

Everything below is additive — no existing files need changing.

- **New soldier shape:** `register_shape("star", fn)` in/alongside `shapes.py`,
  where `fn(canvas, x, y, r, fill, tag)` creates one canvas item. Reference it
  via `"shape": "star"` in a unit type.
- **New unit type:** add an entry to `UNIT_TYPES` in `unit_types.py`
  (max_hp, speed, range, damage, cooldown, shape, plus `ranged` and an
  `equipment` list of `"sword"`/`"shield"` markers). Instantly usable.
- **New relationship stance:** add to `Stance` in `world_map.py` and give it a
  color in `theme.STANCE_COLOR`.
- **New species:** add an entry to `SPECIES` in `lexicon.py` (hue + stat traits);
  the generator picks it up automatically. Faction names come from the `_ADJ` /
  `_NOUN` word lists there.
- **Tune world generation:** `generate_world()` in `worldgen.py` exposes
  `width`, `height`, `seed`, `n_factions`; the land fraction, continent shape
  (radial falloff / octaves) and diplomacy rules are all localized there.
- **Tune settlements:** `SETTLEMENT_TYPES` in `worldgen.py` is pure placement
  data — weights (fertility, river, coast, border, elevation), density
  (`per_cells`), and spacing. `SETTLEMENT_UPKEEP` controls what each kind
  draws from its faction's stockpile every turn. Add a new settlement kind
  in both (plus a marker style in `map_view.py`) and it generates instantly.
- **Tune villages / roads:** the `_VILLAGE_*` constants in `worldgen.py`
  control count-per-county (`_VILLAGE_CELLS_PER`, clamped `_VILLAGE_MIN`/`_MAX`),
  placement (fertility/water weights), spacing, and farm output range
  (`_VILLAGE_FARM_RANGE`, which feeds a county's Grain yield). Roads are a
  minimum spanning tree over each county's villages plus its first settlement
  (`_mst_edges`), stored in `world.roads_by_county[county_id]` as straight
  `((x,y),(x,y))` segments — swap in a pathfinder there if roads should ever
  bend around terrain.
- **Tune fertility / biome / climate:** the `_FERT_*` weights at the top of
  `worldgen.py` control how elevation, water and moisture combine into
  fertility (`world.fertility`). Biome/climate classification thresholds
  (mountain/forest/plains/coastal/desert/swamp; temperate/arid/cold/humid)
  live in `classify_biome`/`classify_climate` in `resources.py`.
- **Tune the resource economy:** `RESOURCES`, `BIOME_YIELDS`,
  `CLIMATE_MODIFIERS` and `SEASON_MODIFIERS` in `resources.py` are all pure
  data — add a resource, change what a biome produces, or how a climate/
  season scales it, without touching the turn loop itself
  (`seed_initial_stockpiles`/`advance_turn`). Military strength is derived
  from stockpiles in `_recompute_military` there too.
- **New game system** (diplomacy AI, sound, more turn-based mechanics):
  subscribe to events via `bus.on(...)`, and/or add a screen as a `tk.Frame` in
  `app.py`.

## Events emitted on the shared `bus`

| Event                   | Payload                          |
|-------------------------|----------------------------------|
| `nation:added`          | the Nation                       |
| `relationship:changed`  | `{a_id, b_id, stance, tension}`  |
| `battle:over`           | `{winner}`                       |
