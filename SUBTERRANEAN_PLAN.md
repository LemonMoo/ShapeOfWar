# The underworld — a plan

A second layer of world beneath the mountains and their skirts: mines, halls,
gates, and realms that live down there. Dwarf holds and goblin warrens are born
in it; anyone can go down if they can take a gate.

## The four decisions, taken up front

1. **A sparse layer, not a mirrored world.** The underground exists only under
   mountain and highland cells and a margin around them. Everywhere else is
   solid rock and is not stored at all.
2. **Dwarf holds and goblin warrens** are generated inhabitants. Orcs stay a
   surface people who may take galleries by force.
3. **A few gates per massif**, and they are the only way between layers.
4. **One level.** Below the galleries is unexcavated rock.

## Why it is shaped this way

Straight out of how underground settlement actually worked, which points
somewhere much more specific than "a cave map":

- **Mines follow seams, not area.** A working is a branching network whose
  shape is dictated by the ore body. Nothing underground is continent-shaped,
  which is the whole argument against mirroring the surface grid.
- **Ventilation, water and haulage were the binding constraints** — distance
  from the face back to the shaft is what decided whether a mine paid, and
  flooding is what abandoned most Roman and medieval workings. Depth and
  distance underground must cost something that distance on the surface does
  not.
- **Subterranean cities were refuges.** Derinkuyu and the rest of Cappadocia
  were carved where the rock allowed, close to the surface, with very few ways
  in. Defensibility is the point, and a small number of doors is the mechanic
  that expresses it.
- **No sunlight, no crops.** An underground realm eats what it trades for and
  what it can grow in fungus galleries. That makes a hold structurally a
  trading power with a standing food dependency — a genuinely different
  economy from any faction now in the game, using trade and logistics machinery
  that already exists.

## The data model

The seam that makes this affordable. `world.owner[y][x]` is read in 61 places
across 10 modules; the plan is not to convert all of them.

**Sparse, keyed by cell, on `World`:**

```
world.under_cells      set[(x, y)]            open space; absent == solid rock
world.under_kind       {(x, y): "gallery" | "cavern" | "chasm" | "water"}
world.under_owner      {(x, y): faction_idx}
world.under_region     {(x, y): region_id}
world.gates            [{"pos": (x, y), "under": (x, y), "name": str, ...}]
```

Sparse because the underground is a few per cent of the map: on a Standard
world that is tens of thousands of cells, not 726,000, and a save grows by
kilobytes rather than megabytes.

**`Region.layer`** — 0 surface, 1 under, read through `getattr(region,
"layer", 0)` so every world pickled before today is a surface-only world with
no migration step at all. Underground regions live in `world.regions` beside
the others, which is what lets territory, claims, prosperity, trade and battles
work on them **unchanged**.

**`app/world/layers.py` (new)** is the only thing that knows both layers:
`owner_at(world, x, y, layer)`, `set_owner`, `region_at`, `passable`,
`neighbours` (which is where a gate becomes an edge between layers). Call sites
convert to it only where they must — pathing, territory transfer, vision,
settlement placement. Everything else keeps reading the surface grids directly,
because everything else is surface-only by nature.

## Phases

Each built, tested and committed on its own, same discipline as the weather,
biome, battle-AI and real-time reworks.

### Phase 0 — the model, and nothing else

`layers.py`, `Region.layer`, the sparse fields, a save that round-trips, and
`dev/test_layers.py`. No worldgen, no rendering, no gameplay. The phase exists
so the seam is settled before anything is built on it.

### Phase 1 — carving the underworld (worldgen)

After mountains exist:

1. **Find massifs** — connected components of mountain/highland cells above a
   size floor. Small outcrops get nothing; a lone peak has no kingdom under it.
2. **Carve a network per massif.** Chamber sites first (a handful per massif,
   biased to where the existing ore tables are richest), then galleries linking
   them — a spanning network, not a maze, because a mine is a tree from its
   shafts and not a labyrinth. Widen at chambers into caverns.
3. **Run out under the skirts.** Galleries reach a margin beyond the mountain
   proper, which is the "surrounding area" part and also what puts some gates
   in country an army can actually reach.
4. **Chasms and sunless water** as impassable structure, so a network has real
   shape rather than being uniformly walkable.
5. **Place gates** on the flanks — one to three per massif, each a surface cell
   paired with an underground cell.
6. **Partition into regions**, the same unit of ownership as above.

`dev/under_shot.py` renders a massif's network as a PNG. This project has twice
been saved by rendering worldgen before trusting it (the plate distance-
transform artifacts, the lake basins), and a cave network is exactly the kind
of thing that looks fine in a metric and wrong to the eye.

### Phase 2 — seeing it

A view for the underworld: rock, galleries, caverns, water, gates, and the
realms below. Gates are drawn on the **surface** map too, because a gate you
cannot find is a gate that does not exist. The existing map-mode switch is the
model; the underground is not a mode of the surface but a place, so it gets its
own toggle and its own raster cache.

### Phase 3 — moving, and not seeing in the dark

- Travel costs per underground kind: galleries slow, caverns quicker, and
  **haulage is what makes distance underground expensive**, which is the honest
  reading of the historical constraint.
- Passing a gate costs real time — descending is an event, not a step.
- **Darkness is the fog.** A separate vision set for the underground with a far
  shorter radius, so a hold knows its own halls and nothing of the next
  massif's. Exploring down there is a real undertaking.

### Phase 4 — an economy with no sun

- **No crops underground**, ever. `compute_village_yield`'s crop path is
  surface-only.
- **Ore, stone and gems are rich** — the existing tables already gate Iron,
  Coal, Gold Ore and Gems on mountain/highland, so the underground inherits a
  working mining economy rather than needing a new one.
- **Fungus galleries** as the one food a hold can grow: real, low-yield, and
  never enough. The gap is covered by trade, which is the point.
- A hold that loses its gates loses its food. That is the siege, and it falls
  out of the economy rather than being scripted.

### Phase 5 — who lives there

- **Dwarf holds**: one great settlement per major massif plus mining villages —
  wealthy, heavily defended, food-poor. Their existing homeland affinity
  (mountain 1.0, highland 0.9) is already pointing here.
- **Goblin warrens**: many small settlements clustered near gates, poor and
  numerous, raiding the surface for what they cannot grow.
- Both need the expansion AI to understand a gate: claiming underground is
  claiming *through* a chokepoint, and an AI that does not know that will
  either never descend or wander in and starve.

### Phase 6 — fighting underground

A battle terrain profile for `gallery` and `cavern`, into the table that
already exists: no room to manoeuvre, cavalry worth little to nothing, archers
short-sighted, and a defender's advantage at a gate that is worth taking
seriously. This is where the battle-AI work from v0.10.0 pays off — formations
in a corridor are a different problem from formations in a field.

### Phase 7 — ship

Full suite, a v0.11.0 save proving migration, a real-time check that the new
per-day work still fits the slice budget, and a release.

## Risks, named up front

- **The AI is the hard part, not the terrain.** Carving caves is a rendering
  problem with a clear answer. An expansion AI that reasons about a second
  layer reachable only through chokepoints is a genuinely new problem, and it
  is where this will overrun if it overruns.
- **Two layers of everything in the UI.** Selection, panels, alerts and the
  minimap all assume one map. Phase 2 must settle "which layer am I looking
  at" as a single piece of state, or that assumption gets patched in twenty
  places.
- **Per-day cost.** Underground regions are more regions, and the day is now
  sliced to a 12ms p95 (see `turn_runner.py`). New work must be chunked as it
  is added, not after `dev/test_turn_slice.py` starts failing.
- **Balance is untouched by design.** Nothing here changes a unit stat or an
  economy constant. A dwarf hold is strong because of where it sits, not
  because dwarves were buffed — and if holds measure oppressive, the lever is
  gate count and food yield, not the species table.
- **Save size.** Sparse storage keeps this in kilobytes. If it is ever made
  dense "for simplicity", that decision costs megabytes per save and should be
  measured before it is taken.
