# Shapes of War — Handoff

Python/Tkinter desktop 4X strategy game. Single developer, turn-based, procedurally
generated fantasy world. Repo: `LemonMoo/ShapeOfWar`, branch `master`.

**Last release: v0.3.6_1** ("More Continents, Less Water, Smoother Movement").
Check `gh release list --repo LemonMoo/ShapeOfWar --limit 5` before trusting
this line — this repo ships fast, sometimes several releases in one day.

---

## 0. Read this first

v0.3.0 shipped the globe (§2), the end-turn movement animation (§7), species
signature units (§4.1) and the Balance Lab (§5). v0.3.1 shipped the New Game
overhaul (§8). v0.3.2-v0.3.4 shipped ocean currents + physically-carved
coastlines, the globe's camera pitch/3D pins/fog-of-war-as-cloud, and a full
settlement-placement rework (real site scoring everywhere, uncapped
density-driven villages, per-village local production replacing a
region-pooled economy, terrain-aware roads). v0.3.5/v0.3.6 shipped full game
interaction parity on the globe (select/command everything without dropping
to the flat map) and a batch of fixes (a kingdom-name-corruption bug, globe
markers as real 3D pins, default battle formation, per-species special-troop
select buttons). v0.3.6_1 reworked continent placement (see §9 below) to
reliably produce 6-7 real, separate landmasses instead of "constantly mostly
2", cut river/lake density, and fixed a movement-animation timing bug.
Everything is released and the working tree is clean.

**Next up, not yet started:** a tectonic-plate-driven worldgen model, to
replace the current "placed elliptical blobs + noise" approach with
something that actually explains *why* land is shaped the way it is
(mountain ranges from plate collisions, rifts, etc.) instead of continents
"poofing up out of nowhere" — the user's own words. See **§9** for the full
handoff: current-system grounding, a proposed model, phasing, and the open
questions that still need the user's input before implementation starts.

**The one thing to know before touching anything else:** the signature units are
working and legible but **not balanced**, and the release notes say so out loud.
Read §4.1 before moving any number — `dev/balance_lab.py` is the tool for it, and
the shares are the knob, not the stats.

Release flow, for the next one: bump `APP_VERSION` in `build.bat`, add a
`CHANGELOG_ENTRIES` entry at the top of `app/core/changelog.py` (never renumber
the older `version:` integers — that re-flags dismissed entries as NEW for
existing players), write `release_notes_<x.y.z>.md`, run `build.bat`, then
`gh release create v<x.y.z> dist/ShapesOfWar.exe --repo LemonMoo/ShapeOfWar
--title "..." --notes-file release_notes_<x.y.z>.md`.

---

## 1. Architecture

- `World` (`app/world/worldgen.py`) — all game state. Plain data only; it is saved
  with raw `pickle` (`app/core/save.py`), so no closures or bound methods on it.
  Migrations run on load.
- `MapView` (`app/ui/map_view.py`, ~4,000 lines) — the map plus almost all UI:
  panels, cards, alerts, treasury, fog, three zoom levels (World → Region →
  Village). By far the largest file and the main obstacle to any UI change.
- `App` (`app/ui/app.py`) — screen switching, glues the battle minigame to the turn
  loop, builds army compositions (`_army_for`).
- Turn loop: `resources.advance_turn()` calls each domain module's per-turn hook.
- Battle sim (`app/battle/`) is pure logic, no rendering. Two renderers consume it.

### Rendering

Runtime deps are now **moderngl, pyopengltk, numpy** (plus Pillow).

- `app/ui/gl_battle.py` — GPU battle renderer. Whole battlefield in ONE instanced
  draw call against a sprite-atlas texture array. Falls back to the Tk canvas if a
  GL context can't be had, **including mid-session**. The battle log prints which
  renderer is live — a silent fallback is otherwise invisible.
- `app/ui/gl_globe.py` — the globe (uncommitted). Textures the sphere with the flat
  map's *own* raster (`MapView._base_img`) and fog mask, so there is no second copy
  of the map to keep in sync.

**GL gotchas that already cost time:**
- A GL context only exists once Tk has *mapped* the widget. Testing for one at
  construction always fails and silently demotes to the canvas.
- `pyopengltk` only sets `self.width` after a `<Configure>`; `initgl` runs on
  `<Map>` before that. Use `winfo_width()` as a fallback.
- `initgl` is called again on every resize — it must be idempotent.
- Don't name a method `_setup` on a Tk widget subclass; `tkinter.Widget` owns it.
- PyInstaller: `glcontext` needs `--collect-all` (its `wgl.*.pyd` is loaded by name
  at runtime, so `--hidden-import` does **not** bring it). Already in `build.bat`.

---

## 2. The globe — state and what's left

Done and verified:
- Conformal (Mercator) latitude mapping. Shape distortion is **exactly 1.0000 at
  every latitude**. The naive plate-carrée version smeared terrain toward the poles
  (1.20 → 0.31 distortion) — that was the bug the user reported, and it is fixed.
- The edge latitude is **derived from the map's aspect** (`merc_max = π·h/w`), not
  hardcoded: for 1100×660 that is ±72.7°. Ice caps cover everything beyond, so
  there is no singular point left to smear. Caps are not clickable.
- Free orbit as an accumulated rotation *matrix* — no gimbal lock. After 200 steps
  rolled over the poles: det 1.000000, orthogonality error 1e-14.
- Picking: ray → sphere → lat/long → cell → region, exact (6/6 round-trip). Feeds
  the existing selection path, so region/settlement selection needs no duplicate
  logic. A drag never selects.
- Fog as a texture, billboarded markers, day/night terminator (sun advances with
  the game year), atmospheric rim.
- Camera + preferred view persist on the `world` object, so they survive save/load
  without touching the save schema. Verified through a pickle round-trip.
- ~900–1,200 fps in the live view.

Overlays (added after the first pass — everything the flat map draws on top of
terrain now has a globe form):
- **Lines** — roads, trade routes, route construction, active caravan lanes,
  attack frontiers. Instanced quads widened in *screen* space, so a road is
  legible from orbit and from ground level; depth comes from the segment's own
  place on the sphere, so the planet occludes the far side for free.
- **Text** — realm, region, settlement and village names plus alert badges,
  against a PIL-built glyph atlas laid out in screen pixels around a projected
  anchor.
- **Zoom levels now change what is drawn**: realms and trunk roads from orbit,
  region names closer in, villages and dirt tracks near the ground. Flying
  closer *is* drilling down — there is no view state to enter.
- `visible_mask` culls markers and labels to what the camera can actually see,
  horizon included (the visible cap is `p.z > 1/dist`, **not** a hemisphere).
  From village altitude that is 500 markers down to 21.

**Still flat-map only:** terrain symbols, the terrain legend, the prosperity/
storage bars, and the post-battle region flash.

Two bugs fixed that predated the overlays: overlay geometry was baked in the
camera's frame (the planet turned out from under its own markers on the first
drag — every overlay program now takes `u_rot`), and the day/night terminator
was physically dark enough to make most of the visible disc unreadable.

**`dev/globe_shot.py`** renders one PNG per zoom level against a real GL
context. Use it — a shader only compiles against a real context, and "the
overlay is in the right place" is not a thing a return value can tell you.
Two traps it documents: pyopengltk swaps buffers at the end of every frame, so
reading `ctx.screen` afterwards returns the *previous* one; and the dev worlds
are 99.9% fogged, so with fog left alone every overlay is correctly empty.

Open question for the user: whether the ice caps read as too large. Raising the
edge latitude trades shape accuracy for coverage; it is a one-constant change.

---

## 3. Where the performance work landed

| | before | after |
|---|---|---|
| End turn (300 regions) | 1,199 ms | **424 ms** |
| Battle render (~590 units, full kit) | 15 fps | **141 fps** |
| Battle sim, 4,700 units | 6.7 fps | **31 fps** |

- End turn: memoised `storage_class`/`resource_bulk`, cached region adjacency
  (static after worldgen), and hoisted the frontier scan out of the expansion AI
  (it was rescanning a faction's whole territory *per frontier region*). Verified
  **identical** by fingerprint — see `dev/bench_turn.py`.
- Battle sim: `choose_target` was quadratic. The enemy list is snapshotted into
  numpy arrays once per tick and scored in one vector pass. `take_hit` calls
  `Battle.mark_dead` so nobody targets a corpse.
- **Battles are now reproducible from a seed.** They previously were not: the
  collision solver ordered pairs by `id()`, a memory address. That silently
  invalidated balance measurement — identical configs came out 19 points apart.
  Fixed with a stable `Unit.uid`. If a repeat run ever disagrees with itself
  again, suspect something has reintroduced address-dependent ordering.

Remaining: `node_pool_stock` (~1.3M generator iterations/turn). Needs a per-turn
cache of *mutable* state invalidated on write — deliberately declined, since a
missed invalidation surfaces as economy drift fifty turns later. Probably another
1.5–2×. The sim is no longer quadratic but is still ~O(n^1.6); true linear needs
spatial partitioning for targeting, which trades exactness for speed. Only worth
it if 10k-unit battles are actually wanted.

---

## 4.1 Species signature units — working, NOT balanced

Every species now fields at least one unit nobody else has, on top of the shared
core. Composition lives in **one** place, `lexicon.army_composition` — the
tournament calls the same function the game does, instead of the hand-copied
duplicate it used to keep.

| species | unit | what it is |
|---|---|---|
| Humans | Standard Bearer | rank-and-file Marshal: an aura, not a fighter |
| Elves | Bladesinger | fast, evasive melee — the answer an archer line lacked |
| Dwarves | Shieldwarden | anchor; the line near one takes less punishment |
| Orcs | Berserker | no shield, damage climbs as it bleeds |
| Goblins | Assassin + Sapper | counter-archer; and bombs that break formations |

New mechanics behind them: `ignores_block`, `frenzy`, `splash_radius`/`_share`,
and unit-level `aura` (auras **do not stack** — first source in range wins, and
`Army.aura_sources` is ordered commander-first).

**The measured state.** `dev/tournament.py 5 on --isolate` runs a control with
nobody's specials, then one run per species. Two runs, either side of the
order-AI fix described below (3 seeds on the second, so treat anything under
~15 points there as noise):

| | control | with its own specials | Δ before AI fix | Δ after |
|---|---|---|---|---|
| Humans | 42% | 33% | −2 | −8 |
| Elves | 62% | 46% | −25 | −17 |
| **Dwarves** | 17% | **33%** | +5 | **+17** |
| Orcs | 54% | 46% | −12 | −8 |
| Goblins | 75% | 46% | −25 | −29 |

The Shieldwarden is the one clear success, and only once the AI actually ordered
it — the roster's worst species gains 17 points. Everything else is still a net
cost to its own species; Goblins remain 29 points adrift.

What the numbers already established, and these do generalise:

- **The share is the knob, not the stats.** The Bladesinger went from **+25 to
  −25** on a share change (10% → 22% of the bows) with only its dodge touched.
  Tune `specials` shares first; reach for stats second.
- **Range dominates.** This slot first held a Dwarven Arbalest — a crossbow,
  higher damage than a bow, 150 range against 180, `ignores_block`. It measured
  **25% → 8%**, the worst single result this project has produced. It gave up
  spacing *and* paid for tanky bodies with fragile ones.
- **The Assassin is confirmed a tax, independently.** The control run — which
  simply removes it — put Goblins at **70%**, against 35% with it. That is open
  thread #3 measured from the other direction. Its share is now cut to ~3 units
  from 9; deleting it outright still measures better.
- **An aura needs coverage, not strength.** Four Standard Bearers at 90px did
  literally nothing to a line of eighty. Widen the radius before adding bodies —
  stacking is off by design.

**The order AI now groups by ROLE, not by type name.** It read
`u.type_key == "infantry"` and friends, which left every new unit permanently
unordered. The rules themselves are unchanged (§4 #4 still applies — do not
"improve" them without measuring); they just reach the units they were written
for. Ranged units are ordered per type, since the rule turns on the group's own
reach and a Sapper folded in with Archers would stand at a range only Archers
can shoot from.

---

## 4. Open threads (roughly by value)

0. **Balance the signature units** (§4.1). Re-run `--isolate` now that the order
   AI actually orders them, then move shares. Elves and Goblins are 25 points
   adrift in opposite directions.
1. **Species retune with orders enabled.** The multipliers in `lexicon.py` were all
   fitted to a game where every unit did one thing: walk at the nearest enemy.
   Orders changed the behaviour, so the traits are now worth different amounts than
   when they were priced. **Dwarves sit around 25%** with orders on and 79% with
   them off — same stats, so the swing is entirely behavioural. One cause was found
   and fixed (charging under fire drops shields, and Dwarves *are* their shields);
   the rest is unexplained. Biggest outstanding balance item.
2. **v0.2.6 changed battle outcomes** (targeting now reads start-of-tick positions).
   Species win rates moved up to ~20 points. Any balance work must re-baseline
   rather than compare against pre-0.2.6 numbers.
3. **The Assassin does not earn its slot.** Goblin win rate falls monotonically with
   the number fielded (83% at none, 54% at nine, 8% at seventeen), and *free*
   assassins still made them worse — so it is the unit, not its cost. It now has
   archer-hunting, 0.22 dodge and a 3.5× first strike, and none of it shows up: in
   a full battle it landed **0 first strikes and 0 of 9 survived**, because they die
   crossing the field. Survivability is the binding constraint; bigger HP/damage
   numbers were tried and did not fix it. Needs a mechanic that gets it *there*.
4. **AI order rules are deliberately conservative.** Every richer version measured
   worse (walling under fire: Orcs 0%/Elves 100%; charging under fire: Dwarves 4%).
   The AI now only braces against an actual charge, cycles cavalry, and holds
   archers in range. Don't "improve" it without measuring.
5. Compendium still has no article for battlefield orders. It *does* now
   describe every signature unit, including the Assassin (Military & Combat →
   Signature Units).

---

## 7. End-turn movement animation

`MapView._start_move_animation` and friends. Movers slide along the route they
actually travelled over a fixed 0.75s wall-clock window, eased in and out.

- **View-only.** Nothing in `app/world` knows it exists — the turn resolves
  first and the animation replays it, so the sim stays deterministic and the
  animation can be shortened or cut without touching game state.
- The window is wall-clock, not a frame count, so a heavy world takes the same
  0.75s and simply draws fewer frames. End Turn stays locked while it runs.
- Both views place movers through `_display_pos`, so the globe gets it free.
- **`dev/test_move_anim.py` asserts it is faithful, not merely smooth**: starts
  on the old cell, ends where the world actually put the mover, walks the cells
  between, and survives the seam. It immediately caught a real bug — 18
  shipments a turn animating from halfway across the map, because a shipment
  that delivers mid-turn is freed and CPython hands its address to the next
  object allocated, so an `id()`-keyed snapshot matched a *different* object.
  The snapshot now holds the movers themselves. **`id()` has now bitten this
  project twice** (the other was battle determinism); treat it as unusable as a
  key wherever objects churn.

---

## 5. Dev tools (`dev/`)

- `dev/bench_turn.py` — end-turn timing, `--profile`, and `--fingerprint`. **Use the
  fingerprint to prove any "pure speed" change really is one.**
- `dev/tournament.py` — species balance. Mirrors `App._army_for`; keep them in step.
  Read its docstring before trusting a number: 12–24 games per species means
  anything under ~10–15 points is noise, and matchups flip in whole blocks.
- `dev/test_succession.py`, `test_battle_death.py`, `test_elim.py`,
  `test_commander_gate.py`, `test_gate2.py` — regression harnesses. All pass. Run as
  `python dev/test_succession.py dev/worlds/dev560.pkl`.
- `dev/test_move_anim.py`, `dev/test_tuning.py` — same, for the end-turn
  animation (§7) and the balance levers (below). Both take no world argument
  beyond the default.
- `dev/globe_shot.py` — renders the globe at each zoom level (§2).
- `dev/worlds/dev560.pkl` — turn 561, 300 owned regions, 14 factions. The benchmark
  world. `dev160.pkl` is an earlier one with active trade. **Gitignored** (49 MB
  each): they exist on disk but not in the repo, so a fresh clone won't have them.

### `dev/balance_lab.py` — the tuning tool

`python dev/balance_lab.py`. Every balance number in the game (217 of them),
grouped as the source groups them, editable, with the source default shown
beside anything you've moved. **Edits apply to the live tables immediately**, and
the tournament runs in the same process — so Run measures exactly what is on
screen, with no save/reload/restart in between. Standard, `--ab` and `--isolate`
modes are all there.

Save writes only what *differs* from source defaults, to `dev/balance.json`
(gitignored — it's a personal scratchpad, not a shared setting).
`app.core.tuning.load()` runs at startup and applies it, so numbers you like in
the lab are numbers the game plays with. Packaged builds never see it: `dev/`
isn't shipped, so a release always runs on source defaults.

`app/core/tuning.py` is the index, and it deliberately does **not** move any
number out of the module it lives in — the comment explaining why a value is
what it is belongs next to the value. Two things it depends on:

- **Tables are mutated in place, never rebound.** `unit.py` does
  `from app.battle.unit_types import UNIT_TYPES`, binding the same dict object;
  mutating it is visible everywhere, rebinding the module attribute would be
  visible nowhere.
- **Scalars imported by value get an explicit mirror list.** There are two
  (`COMMANDER_AURA_RADIUS`, `COMMANDER_SCREEN_MIN`, both into `app.battle.unit`).
  A third that isn't added to that list will silently do nothing —
  `dev/test_tuning.py` asserts specifically against that.

Levers are numbers and flags only. Strings (a unit's `name`, its `shape`) and
list structure are not editable: they're structure rather than balance, and a
text box that can put an unregistered shape name into `UNIT_TYPES` is a crash
waiting to be typed.

---

## 6. Working practices that paid off

This project has been run on measurement, not intuition, and that repeatedly caught
changes which felt right and were wrong. Worth continuing:

- **Measure what a fix removes, not just whether the symptom improves.** A v0.2.1
  migration "fixed" overflow while destroying more goods than doing nothing.
- **A/B by disabling the new thing**, not by comparing against memory.
- **Check the harness before believing the result.** Several conclusions were
  harness bugs: reading `region.villages` (nodes live on `world`), reading
  `node.stock` (it's `node.resources`), and composing armies with `'swordsman'`
  (the real key is `'infantry'`; `UNIT_TYPES.get` silently falls back, so it looks
  like it works).
- **Retract numbers when the method turns out to be broken.** The `id()` determinism
  bug invalidated an afternoon of fine-grained tuning; large effects survived, small
  ones did not.
- When a fix underperforms, revert it and record why. Anchoring the engaged rank in
  melee was a good idea that measured worse (front-rank travel 150px → 336px), and
  the finding lives in a comment where the next person will hit it.

---

## 8. New Game overhaul (v0.3.1)

`app/ui/new_game.py` (rebuilt), `app/ui/world_preview.py` (new), plus new data
in `lexicon.py` (rulers, `species_palette`, `species_stat_chips`/`species_units`)
and `worldgen.py` (`apply_player_identity`, `_nudge_away_from`).

**The one thing that makes it work:** `generate_world` takes 8s (Small) / 18s
(Standard) / 37s (Large). The screen starts generating in the background the
moment it opens, and Play hands over the **exact world object** the preview was
showing — never a fresh roll. Species, name, colour and ruler are *not*
world-shaping (terrain and every rival are identical whoever you play), so
they're patched onto the already-generated world via `apply_player_identity` in
~0.1ms, which is what makes browsing species feel instant. Only size, rival
count, or an explicit reroll starts a new background generation.

- **Rulers** are a new, deliberately separate concept from the battlefield
  Commander (`app/world/commander.py`) — the Commander marches and can fall,
  the ruler is who the realm belongs to. Every faction gets one, seeded
  deterministically from the world seed. `nation.ensure_rulers` migrates old
  saves; `app.core.save.load_game` calls it.
- **Colour** is `species_palette(species)` — 12 swatches fanned around the
  species' own hue, not a free picker. Rivals are steered off whatever the
  player picks (`_nudge_away_from`), verified rather than assumed: 8-bit colour
  rounding meant aiming exactly at the clearance distance landed just inside it
  about half the time, so it checks its own output and pushes further if the
  first attempt wasn't actually clear.
- **The preview** (`app/ui/world_preview.py`) is a small, separate thumbnail
  renderer — not MapView reused. It samples the world grid on a stride and
  paints the political read only (water, unclaimed land, realm colours, a ring
  on the capital), sharing MapView's palette constants.
- A Tk trap worth remembering: a `Label`'s `width`/`height` are **characters**
  when it holds text and **pixels** when it holds an image. Sizing the preview
  label directly gave a squashed map in one state and a 258-line placeholder in
  the other. Fixed with a fixed-size `Frame` holding centred content instead.

`dev/test_new_game.py` asserts the chain the screen's promise rests on:
identity patching is fast enough to run per keystroke, doesn't touch terrain or
rivals' names, rival colours are stable under repeated edits, and — the one
that actually matters — Play hands over the identical world object the preview
was showing, with the identity that was on screen at the moment it was pressed.
It generates a real (Small) world, so it's the slowest harness in `dev/`.

---

## 9. Next up: tectonic-plate-driven worldgen (NOT STARTED — plan only)

The user's own framing: continents currently "poof up out of nowhere" — there
is no causal story for why land is shaped the way it is. They asked, almost
in passing, "is there a way we can do a tectonic plate map where we can more
clearly and deliberately form land masses" — this is a real "yes, and here's
what it would take" answer, not a small tweak. **Nothing has been built. This
section is a handoff, not a design that's been agreed to in detail** — the
open questions at the bottom need the user's actual answers before a line of
this gets written, the same way the settlement-system rework earlier this
project started with several rounds of `AskUserQuestion` before any code
changed.

### Why now, and why not just tune the current system more

This project already went through one full tuning pass on the *current*
blob-based system this session (see the `v0.3.6_1` release and the commit
titled "Reliably get 6-7 continents instead of 'constantly mostly 2', less
water") — continent count went from a flat 2-3 to a reliable 6-7, hemisphere
banding was fixed so continents actually spread from equator to pole instead
of clustering near it, and placement itself became a best-of-60-candidates
search instead of a threshold-and-give-up loop. That work is DONE, released,
and verified (`git log` for the full story; the commit message is detailed).

That tuning pass is very likely the ceiling for what this architecture can
give: no matter how well-tuned, "place N elliptical blobs, warp their edges
with noise, add a few lobes" has no notion of *why* a coastline bends where
it does, or *why* a mountain range exists at all (there currently ISN'T
one — elevation past a threshold just reads as "mountain" biome; nothing
carves an actual RANGE, a long connected ridge, anywhere in the game). A
plate model is what would give geology an actual reason: mountain ranges at
collision zones, rifts and new coastline at divergent boundaries, and
continents that could plausibly have drifted into the shapes they're in.

### The current system, precisely (what this would replace or build on)

- `_pick_continent_centers` (`app/world/worldgen.py:1666`) picks 4-7 blob
  centers via best-of-60-candidate placement (score = distance to every
  already-placed blob, keep the best seen — see the function's own
  docstring), banded by latitude with each hemisphere spreading its own
  bands independently. Each blob gets 0-3 "lobe" sub-blobs for shape variety.
  Returns a flat list of `(cx, cy, radius_x, radius_y, angle)` ellipses.
- `generate_world` (`worldgen.py:1902`) builds the height field as: several
  octaves of domain-warped value noise (`app/world/noise.py`, vectorized,
  bit-exact-verified against a scalar reference) MINUS a falloff term from
  the nearest blob (`best_d2`, computed per-blob with the blob's own
  rotation/radii). Thresholds the result at whatever elevation value puts
  ~40% of cells above it (`world.sea_level`).
- `currents.py`'s `solve_currents`/`carve_coastline` (`currents.py:137`,
  `:239`) then runs a wind-driven ocean-circulation Poisson solve and uses
  the resulting current speed to erode/deposit along the coast — this is
  the ONLY part of the pipeline that already has a real physical model
  behind it, and it's a good template for how a plate model should be
  structured (solve the physics once, feed the result into height as a
  secondary adjustment, not the primary shape).
- `_generate_hydrology` (`worldgen.py:618`) does real priority-flood
  drainage + D8 flow accumulation for rivers/lakes — also unaffected by
  continent SHAPE, just reads whatever height field exists.
- `_classify_biomes_and_climate` (`worldgen.py:1560`) is purely per-cell
  (latitude + moisture + relief + coast/river distance) — completely
  independent of how continents got their shape. **This should need zero
  changes** regardless of what replaces blob placement, as long as the
  output is still a `world.height` grid with a `world.sea_level` cutoff.
- Reusable machinery already in the codebase that a plate model should
  build on rather than duplicate:
  - `_grow_weighted` (`worldgen.py:480`) — multi-source Dijkstra flood-fill
    from seed points, already used for territory growth. This is the
    natural tool for growing K plate territories outward from K random
    seeds (uniform cost = clean Voronoi-ish cells; a noise-perturbed cost
    field = organic, non-polygonal plate boundaries).
  - `_bfs_distance` (`worldgen.py:709`) — cheap distance-from-a-set-of-cells
    field, useful for "distance to nearest plate boundary" (mountain-range
    falloff width) without writing a new distance transform.
  - `wrap.py`'s wrap-aware distance helpers — a plate boundary can cross the
    map's east-west seam exactly the way continents already have to handle
    (see `_pick_continent_centers`' own use of `wrap.dx_wrap`); don't
    reinvent this, route through `wrap.py` like everything else does.
  - `noise.py`'s vectorized value noise/domain warp — should very likely
    SURVIVE this rework as the fine-detail texture layer (local coastline
    roughness, minor relief) applied ON TOP of a plate-driven base
    elevation, rather than being the primary shape mechanism it is today.

### A concrete proposed model (starting point, not settled)

1. **Plate assignment.** Scatter K seed points (K is a knob, see open
   question #2), grow them into plate territories with `_grow_weighted`
   over the WHOLE map (plates exist under ocean too, so this runs before
   any land/sea distinction exists). A noise-perturbed cost field gives
   organic boundaries instead of straight Voronoi edges.
2. **Plate properties.** Each plate gets a random drift vector (direction +
   magnitude) and a type — continental (land-biased base elevation) or
   oceanic (sea-biased). Roughly matching Earth's real ratio (~30%
   continental) is a reasonable starting point, not a hard rule.
3. **Boundary classification.** For cells near a plate boundary, compare
   the two plates' drift vectors against the boundary's own normal
   direction:
   - Convergent (closing) + both continental → uplift (mountain range).
   - Convergent + one oceanic → trench on the oceanic side, coastal
     mountains on the continental side (real subduction-zone shape).
   - Divergent (opening) → rift valley on land, or a mid-ocean ridge bump
     if both oceanic.
   - Transform (sliding past) → minor perturbation only, mostly a texture
     effect (fault-line roughness), not a real elevation change.
4. **Height field composition.** `base_elevation(plate) + boundary_effect
   (distance to nearest boundary, boundary type) + existing fine-detail
   noise/warp (unchanged role, smaller relative amplitude now)`. Threshold
   at the sea-level percentile exactly as today, so the ~40%-land contract
   downstream code already assumes keeps holding.
5. **Everything after height-field generation stays as-is**: hydrology,
   biome/climate classification, currents/erosion, settlement placement —
   all of it reads `world.height`/`world.sea_level` generically and
   shouldn't need to know or care that a plate model produced them.

### Phasing (mirrors how the settlement-system rework was actually run this
### session — investigate, build one verifiable piece, measure, move on)

1. **Plates + boundary classification only, no height integration.**
   Generate plate assignment and boundary types, render a standalone debug
   PNG (plate id as flat colour, boundary type as an overlay line) the way
   `dev/coastline_metrics.py` and this session's various `dev/*_check.py`
   throwaway scripts did for other worldgen work. Validate the plate
   geometry looks like plausible tectonics BEFORE touching the height
   field at all — cheap to iterate, zero risk to anything currently
   working.
2. **Height field integration**, replacing `_pick_continent_centers` +
   blob falloff. Re-measure the same metrics this session already
   established a baseline for: continent count (target stays 6-7, via
   whatever the plate-count/continent-count relationship turns out to be —
   see open question #2), land % (~40%), river/lake density (~1.7-2.2%
   river, ~0.1-2.6% lake as of `v0.3.6_1` — see the "Reliably get 6-7
   continents" commit for the exact measurement methodology to reuse).
3. **Mountain-range shape refinement.** Verify visually that convergent
   boundaries actually read as elongated RANGES following the boundary's
   own curve, not blobs — render the biome overlay and eyeball it, the
   same "measure/render, don't assume" discipline the rest of this
   project's worldgen work has used throughout.
4. **Re-verify downstream systems** that implicitly assumed "continents are
   blob-shaped landmasses with no internal structure": faction/capital
   placement (does a real mountain RANGE ever wall off a faction's entire
   starting region?), road pathfinding around mountains (`_ROAD_ELEV_PEN`
   etc. — should keep working since it's purely elevation-based, but a
   genuine mountain WALL rather than a scattered peak is a bigger
   pathfinding obstacle than existed before), the existing full regression
   suite (`dev/test_*.py`) plus a fresh multi-faction world-gen + 100-turn
   simulation (the exact pattern used to verify every worldgen change this
   session).
5. **Re-tune `currents.py`'s erosion/carving** against the new coastline
   shapes if plate-driven coastlines erode differently than blob-driven
   ones did.

### Open questions — ask the user before writing code, don't assume

1. **Scope.** Mountain ranges + basic continental/oceanic plate typing
   only, or also volcanic/hotspot islands, earthquake-flavour zones for a
   future feature, etc.? Recommend starting minimal and treating the rest
   as follow-up, same reasoning as every other multi-phase rework this
   project has done.
2. **Plate count vs. continent count.** These are not obviously the same
   knob — a real continent can span multiple plates (colliding into one
   landmass), and the current `_target_n` (4-7, `worldgen.py:1902`'s
   `_target_n` param) drives continent count directly today. Does the user
   want to keep tuning "continent count" as the primary knob (with plate
   count as an internal implementation detail that produces roughly that
   many continents), or expose plate count as its own separate, meaningful
   dial?
3. **Does anything from the current blob system survive?** Specifically
   the "lobe" mechanism (`_pick_continent_centers`' 0-3 extra blobs per
   continent, added earlier this session for shape variety) — does that
   stay as an additional texture layer on top of plate-driven bases, or
   does plate-boundary geometry alone provide enough shape variety to
   retire it?
4. **Performance budget.** Current world-gen is ~11-17s (Standard size).
   Plate boundary classification adds real work (per-cell nearest-boundary
   lookups, at minimum); is a slower generation acceptable if quality is
   much better, or is there a ceiling the user cares about? (For
   reference: Large-size world-gen already runs ~37s today per the New
   Game screen's own measured numbers, §8 above — so there's precedent for
   "big and slow is fine if the player is told up front.")
5. **Does this apply to every world size**, or could Small specifically
   keep the simpler blob system if plates don't read well at a small
   scale/short generation budget?

### Where to start (for whoever picks this up)

Read `_pick_continent_centers` and the height-field section of
`generate_world` in full (`worldgen.py:1666`-`~2050`) plus all of
`currents.py` — both are directly relevant precedent, and the continent-
placement code specifically is what this would replace. Do NOT start
writing plate-generation code before running the open questions above past
the user; this project's established pattern (see the settlement-system
rework and the New Game overhaul, §8) is real back-and-forth before a
large worldgen change starts, not a plan executed silently.
