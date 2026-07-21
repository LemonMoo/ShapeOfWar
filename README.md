# Shapes of War

A minimal, extensible war-simulation game — a **standalone Windows desktop app**
built with Python + Tkinter. No browser, no art assets: soldiers are drawn from
primitive shapes (circles, squares, triangles, diamonds).

- **Macro scale:** a procedurally generated Earth-like world (fractal-noise
  continents and oceans), carved into fictional **factions** — each belonging to
  an invented **species** — with a relationship graph (ally / neutral / enemy)
  derived from who borders whom. Every launch (and the **Generate New World**
  button) makes a fresh world. The panel's **View** button cycles three map
  modes: **Political**, **Fertility** (a barren→lush ecology heatmap that sets
  each faction's **crop output**) and **Elevation** (terrain relief). Rivers are
  traced downhill from the peaks to the sea, drawn on every mode, and irrigate
  the land they pass through (raising nearby fertility). Rivers use real drainage
  (depression-filled terrain + flow accumulation), so they emerge in valleys,
  branch and merge, and always reach the sea or pool into a **lake**. Country
  and county borders are river-aware: territory growth pays a surcharge to
  cross water, so frontiers settle along rivers and lakeshores where they
  exist. Click a country to
  inspect it; click it **again** to smoothly zoom in and reveal its **counties**
  — each a sub-region with its own fertility-derived stats (area, fertility,
  crop output). Counties are selectable and are the intended unit of control for
  future territory reassignment (winning/losing a war in a county flips it).
  Every country also founds **cities, castles and towns** (counts scale with its
  size): cities settle fertile, riverside or coastal land; castles guard
  frontiers and high ground; towns fill the countryside. Each generates and
  drains **general resources** (deliberately unspecified for now — crops fold
  into them) that aggregate up to its county and country. The world view marks
  cities; the county view shows every settlement, clickable for its numbers.
- **Micro scale:** a 2D battlefield where shape-soldiers seek and fight in real
  time until one side is wiped out.

## Running

**As an app:** double-click `dist\ShapesOfWar.exe` (self-contained; no Python
needed — copy it anywhere).

**From source:** `python main.py` (requires Python 3.10+ with Tkinter — ships with
the standard Windows Python installer — and Pillow: `python -m pip install pillow`,
used to render the map with smooth, anti-aliased borders).

Click a faction on the map to inspect its species, stats and relationships, then
click **Attack <enemy>** to stage a battle. **Generate New World** rolls a fresh
map. On the battlefield: **Start / Pause**, **Step** (one frame), **New Skirmish**,
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
         lexicon.py     invented species + faction/county name generators
         worldgen.py    procedural world: elevation, water, fertility, rivers,
                        river-aware territories/counties, and settlements
                        (County, Settlement, SETTLEMENT_TYPES)
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
- **Tune settlements / resources:** `SETTLEMENT_TYPES` in `worldgen.py` is pure
  data — per-type gen/drain ranges, placement weights (fertility, river, coast,
  border, elevation), density (`per_cells`), and spacing. Add a new settlement
  kind there (plus a marker style in `map_view.py`) and it generates instantly.
  When the real resource system is specified, replace the generic `gen`/`drain`
  numbers without touching placement.
- **Tune fertility / crops:** the `_FERT_*` weights and `_CROP_PER_FERTILITY` at
  the top of `worldgen.py` control how elevation, water and moisture combine into
  fertility and how that converts to crop output. Per-cell values live in
  `world.fertility`; per-faction totals in `stats["crops"]` / `meta["fertility"]`.
- **New game system** (economy, diplomacy AI, sound, turn structure): subscribe
  to events via `bus.on(...)`, and/or add a screen as a `tk.Frame` in
  `app.py`.

## Events emitted on the shared `bus`

| Event                   | Payload                          |
|-------------------------|----------------------------------|
| `nation:added`          | the Nation                       |
| `relationship:changed`  | `{a_id, b_id, stance, tension}`  |
| `battle:over`           | `{winner}`                       |
