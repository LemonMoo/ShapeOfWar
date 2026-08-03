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

**Ore, stone and gems are rich.** The existing tables already gate Iron, Coal,
Gold Ore and Gems on mountain/highland, so the underground inherits a working
mining economy rather than needing a new one. **No crops underground, ever** —
`compute_village_yield`'s crop path stays surface-only.

Food is its own design, and it is the part that decides whether the underground
is a place or a handicap. See **Food below ground** at the end of this
document.

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

---

# Food below ground

"It trades for food" describes a hold at turn 300 and is useless at turn 1,
when no faction has contact with anyone, let alone a built trade route. A realm
that cannot eat before trade exists starves in its first winter, and the first
impression of a whole new way to play would be watching it die.

So the underground gets a food system of its own, and the shape of it comes
straight out of what people underground actually ate.

## What is actually true about food underground

- **Mushrooms are decomposers, not producers.** The Paris champignonnieres --
  disused limestone quarries under the city, from the early 1800s -- grew on
  beds of horse manure. Fungiculture CONVERTS waste into food. It cannot create
  it, and a fungus farm producing from nothing is the one thing here that would
  be plainly wrong.
- **Caves are nutrient-poor** because nothing in them photosynthesises. Real
  cave ecosystems run on energy carried in from outside: bat guano, flood
  debris, tree roots. Guano was mined industrially as fertiliser. Blind
  cavefish are real, and the biomass is negligible.
- **Derinkuyu had stables and storerooms.** The Cappadocian underground cities
  kept livestock and stores below and farmed above. They were refuges, not
  self-sufficient worlds.
- **Mountain communities ran on transhumance.** Herds to high pasture in
  summer, cheese as the storable protein, grain hauled up from the valley. A
  mining town was fed by the country around it.
- **A cave is the best larder available before refrigeration.** Stable cool
  temperature, steady humidity: Roquefort, cave-aged cheese, cave breweries,
  ice houses.

The honest summary: **the underground is a converter and a larder, not a
farm.**

## The four pillars

### 1. Gate holdings -- the bootstrap

A hold is BORN with terraces and high pasture on the mountainside above its
gates, worked from below. This is not a new mechanic: `OUTSTATIONS` already
lets a village work ground outside its own reach, keyed by biome family, with
one shared reach table (`OUTSTATION_CELLS`) deliberately identical for every
member. A gate holding is a new member of that family -- the first one that
reaches from one layer to the other.

It also fixes the strategy: **to starve a hold you take its terraces**, and
that is a surface fight at a gate rather than an abstract siege timer.

Holds also start with a **full larder** -- a real stock of preserved food at
worldgen. They begin fat and must solve the problem before it runs out, which
is the Cappadocian picture exactly: shelter, stores, and a door.

### 2. Fungus galleries -- the converter

Mushrooms need a bed, and the bed is the constraint:

```
fodder (terraces) --> beasts in the stalls --> manure --+
spent timber, sawdust ----------------------------------+--> fungus --> food
guano (a small, free trickle) --------------------------+
```

Fungus yield therefore scales with **herds and timber**, not with land. That is
the production loop the underground gets instead of fields, and it is why a
hold wants pasture above and a woodcutters' camp in the valley: the terraces
feed the beasts, the beasts feed the mushrooms, and the mushrooms feed the hold
through a winter when nothing else can.

Guano is the seed of the loop -- a small free trickle that stops a hold
deadlocking at zero when it has no herds yet and nothing to compost.

### 3. Stalls -- closing the loop

Livestock already needs fodder and a winter feed
(`village_winter_fodder_need`, `FODDER_STOCK_BUFFER`), and beasts already
produce Milk, Meat, Wool and Eggs. Galleries as stalls reuses all of it and
adds the one output the surface never needed: **manure**, the fungus substrate.

This is also what makes cheese matter. Cheese is the storable form of a herd,
it is what mountain communities actually lived on, and the caves are where you
age it.

### 4. The larder -- the advantage, not the handicap

**Spoilage underground is far lower.** `_apply_spoilage` and the per-node
storage path are the right hooks, and the effect is large and simple: a hold is
the best storehouse in the world. Three consequences, all good:

- it survives a bad season that would break a surface realm;
- it can afford to HOLD stock rather than move it, which is exactly right for a
  realm at the end of a long haul road;
- once trade exists it **exports** what it is best at -- cave-aged cheese and
  cured meat -- so the food dependency that defines its early game becomes the
  export that defines its late one.

That turn is the whole reason to build food this way rather than as a debuff.

## Goblin warrens eat differently

Warrens will not terrace a mountainside. They get the floor and the raid:

- **Scavenging** is the floor: cave fish, grubs, guano, carrion. Poor,
  reliable, and never enough for the numbers a warren runs.
- **Raiding is what hunger does.** A warren that cannot feed itself sends
  parties to carry off a neighbour's stores. Not a claim on ground -- a raid
  takes food and goes home.

The important property is that **aggression is driven by their own hunger**
rather than by a timer. A warren beside a rich valley is a permanent nuisance;
one beside a poor valley is quiet, because there is nothing to take. That gives
a surface player a real lever: feed them, or garrison the gate.

**This is the piece most likely to measure oppressive**, so raid frequency and
haul size get measured once, recorded, and named as the knobs. The failure to
watch for is a warren raiding constantly because scavenging was tuned just
below its own subsistence.

## What gets built, in order

1. **Resources and the loop.** Mushrooms, Manure, Guano and Cave Fish into the
   tables; Mushrooms and Cave Fish join `_FOOD_SOURCES`, so the existing pooled
   consumption covers them with no new consumption code at all.
2. **Gate holdings** as an `OUTSTATIONS` family member that reaches across the
   layer boundary, plus the worldgen that gives a hold its starting terraces
   and larder.
3. **Fungus galleries and stalls** as buildings, with the substrate chain wired
   through the existing recipe machinery.
4. **The larder**: an underground spoilage modifier, and cave-ageing as a
   preservation path.
5. **Warrens**: scavenging yield first, then hunger-driven raiding and the AI
   for it.

## How it gets checked

`dev/test_under_food.py`, structural assertions only, never win rates:

- a newly generated hold **does not starve**: 200 days with no trade partner at
  all, food never reaching zero and population not falling;
- a hold cut off from its terraces **does** run down, over seasons rather than
  days, and recovers when they are retaken;
- fungus is **bounded by substrate**: no herds and no timber means guano only,
  and output scales when herds arrive;
- the larder is real: identical stock spoils measurably slower below ground;
- a warren's raid rate **falls when it is fed**, which is the entire claim of
  hunger-driven aggression.
