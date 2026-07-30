# Shapes of War — Handoff

Python/Tkinter desktop 4X strategy game. Single developer, turn-based, procedurally
generated fantasy world. Repo: `LemonMoo/ShapeOfWar`, branch `master`.

**Last release: v0.3.7_1** ("Take Direct Command of Your Commander").
Check `gh release list --repo LemonMoo/ShapeOfWar --limit 5` before trusting
this line — this repo ships fast, sometimes several releases in one day.
Shipped after v0.3.7: a fix for settlement-less regions never getting a road
into the rest of the kingdom (`_bridge_region_to_kingdom` in worldgen.py), a
Select All battle button/hotkey, and MOBA-style right-click commander/troop
control in battle (`Unit.move_point`/`manual_target`, bypasses the
commander's screening safety net on an explicit player order).

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

**v0.3.7 shipped tectonic-plate-driven worldgen** (Phase 1 + Phase 2).
`generate_world` builds its height field from `app/world/plates.py` now, not
the old blob system (which is deleted, not just unused) — real mountain
ranges at plate collisions, rifts at divergent boundaries, subduction
trenches, hotspot island chains. Land% lands exactly on the 40% target every
time; landmass count runs higher than the old system's tuned 6-7 (currently
~10 on average, down from ~11.5 before an in-session tuning pass, not fully
converged); mountain ranges visually confirmed as real connected curves, not
scattered blobs; river/lake density measurably shifted from the `v0.3.6_1`
baseline and has not yet been re-tuned. Both known gaps are stated plainly
in the release notes and in-game changelog, same transparency precedent as
the unbalanced signature-units release. **This is a real first-pass release,
not a finished tuning pass** — whoever picks up the remaining tuning should
treat it as its own dedicated session, the same way `v0.3.6_1`'s
continent-count fix was. See
**§9** for the full state, what was measured, and what's still open.

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

## 9. Tectonic-plate-driven worldgen — RELEASED in v0.3.7, NOT fully tuned

Replaced "placed elliptical blobs + noise" (the old continent system) with a
plate model that gives geology an actual reason: mountain ranges at
collisions, rifts at divergent boundaries, island chains from hotspots. The
user's own framing when this was first raised: continents used to "poof up
out of nowhere."

**Status:** `generate_world` builds its height field from
`app/world/plates.py` now. `_pick_continent_centers` (the old blob-placement
function) is **deleted**, not just unused — confirmed by grep there are no
remaining call sites, only historical mentions in comments. Shipped in
**v0.3.7** ("Mountains and Coastlines Have a Reason Now") with the known
tuning gaps below stated plainly in the release notes and in-game
changelog — this was a deliberate "ship the real first pass, be upfront
about what's still rough" call, not an oversight. Still needs a further
tuning pass (see "What's still open" below) before it should be considered
settled.

### Phase 1 (recap — geometry and boundary classification)

Built and validated standalone before any height-field code was written:
plate assignment (wrap-aware nearest-seed over a domain-warped coordinate
grid — the same trick the old blob falloff used, reused rather than a
Dijkstra flood fill, which was benchmarked at 1.5-3.2s and would have worked
but was slower and a second mechanism to maintain), six-way boundary
classification from each pair's relative drift projected onto a locally
estimated normal, and hotspot island chains biased onto oceanic plates.

**One real bug found and fixed before Phase 2 could even start measuring
anything sensibly:** `FRACTION_CONTINENTAL` was a per-plate coin flip, and
rendering a few more `plate_shot.py` seeds (as instructed, before touching
height) turned up a seed with 1 continental plate out of 16 — a world with
almost no land. Fixed to a fixed COUNT of continental plates (which plates
are continental is still random), with `dev/test_plates.py` now asserting
the per-seed count, not just a multi-seed average that a few unlucky rolls
can hide.

### Phase 2 (this session): height-field integration

`plates.height_contribution(pl)` returns a raw, unnormalised elevation
field that drops into `generate_world`'s existing normalise/threshold/retry
pipeline unchanged:

- **Base elevation by plate kind** — continental plates land-biased, oceanic
  sea-biased. `FRACTION_CONTINENTAL` is **0.40, not "Earth's real ~29%"** —
  deliberate, see the tuning note below.
- **Per-boundary-kind falloff bumps**, via a capped multi-source distance
  transform (`_capped_distance`) seeded from that boundary kind's cells:
  `CONVERGENT_CC` (big range, both sides), `CONVERGENT_OO` (island arc),
  `DIVERGENT_CC` (rift), `DIVERGENT_OTHER` (mid-ocean ridge). `TRANSFORM`
  gets no elevation term at all — texture only, as Phase 1 already
  documented.
- **`CONVERGENT_SUBDUCTION` is asymmetric**, and it's the one subtle piece:
  a single distance field from the union of subduction boundary cells
  reaches both sides equally (two adjacent cells across a boundary are one
  step apart either way), and then each CELL's own plate kind decides
  whether it gets the coastal range (+, continental side) or the trench
  (−, oceanic side) — no per-boundary-point attribute lookup needed.
- **Hotspot chains are stamped directly** as circular bumps
  (`_stamp_hotspots`), amplitude scaled by each link's age-based `strength`
  (already computed in Phase 1) — the same wrap-aware
  squared-distance-in-a-local-frame trick the old blob falloff used, just
  circular since an island has no preferred long axis.
- **Fine-detail noise is kept**, same domain-warped octaves as before, but
  at a much smaller relative amplitude (`DETAIL_AMPLITUDE`) — plate
  structure now supplies the primary shape; noise only adds local texture
  (small bays, minor irregularity) on top, which is exactly the role Phase
  2's own plan called for.
- **A distance-transform bug found and fixed by rendering, not assumed
  away:** the first version of `_capped_distance` dilated over 4 neighbors
  only (N/S/E/W), which produces Manhattan distance — visible as diamond/
  starburst artifacts wherever two boundaries' falloffs overlapped. Switched
  to 8-neighbor dilation (matching `_NEIGH8`'s existing convention
  elsewhere in this file); the artifacts are gone in the rendered output.

### What was measured (dev/coastline_metrics.py + a fresh biome render)

| | result |
|---|---|
| Land % | **exactly 40.0%** on every seed tested — the percentile threshold contract holds perfectly |
| Landmass count | averaged **~10.3** across 12 seeds after tuning (down from ~11.5 before it, real per-seed variance 1-19 observed) — **above** the old blob system's tuned 6-7 target, not yet converged |
| Coastline irregularity | 12.6-47.3 (a circle scores ~3.5) — clearly organic, not sponge-like, comparable to or better than the old tuned system |
| Mountain-range shape | **visually confirmed**: a real connected curved range along a continent's edge in the biome-grid render (`dev/shots/phase2_biome_s9.png`), not a scattered threshold-triggered blob |
| River/lake density | **shifted from the `v0.3.6_1` baseline** (1.7-2.2% river / 0.1-2.6% lake): now measuring 0.6-0.8% river, 0.7-4.5% lake across 3 seeds. **Not yet re-tuned** — flagged, not fixed |
| Generation time | Small ~8.3s, Standard ~15.7s, Large ~27-70s (one seed hit the raised retry cap) — comparable to the pre-plates baseline; the New Game screen already generates in the background, so this doesn't block anything |
| Full regression suite | **all passing** — `dev/test_plates.py`, `dev/test_tuning.py`, `dev/test_new_game.py` (which calls `generate_world` for real), plus every saved-world harness (`test_succession`, `test_elim`, `test_battle_death`, `test_commander_gate`, `test_move_anim`) |
| Fresh downstream check | 14-faction world + 100-turn simulation: no crash, no negative resource entries, all 14 factions still alive, population grew normally. Capital placement's existing farmland-radius requirement (`_capital_has_nearby_farmland`) already structurally excludes tiny archipelago islands from hosting a capital, since a small island has no non-coastal interior cells — confirmed by reading, not just by the sim not crashing |

**Two tuning changes made during this pass, in response to the landmass-count
measurement** (both in `app/world/plates.py`): `FRACTION_CONTINENTAL` raised
0.32 → 0.40 (continental plate AREA now roughly matches the game's own 40%
land target rather than real Earth's ~29%, so the sea-level threshold sits
close to the kind boundary and needs less scattered oceanic-bump land to
fill the remaining quota), and `BASE_CONTINENTAL`/`BASE_OCEANIC` widened
0.55 → 0.75 (a bigger gap between the two kinds' base elevation makes
boundary bumps less likely to accidentally cross it). `AMP_CONVERGENT_OO`/
`AMP_DIVERGENT_OTHER` were also cut (0.55→0.40, 0.25→0.15) as a secondary
measure. The retry cap for "not enough separate landmasses" was raised from
6 to 12 attempts after a seed exhausted the old cap and shipped a
near-single-landmass world — cheap insurance given "quality over a perf
ceiling" was already the explicit decision for this rework (§ history above).

### What's still open

1. **Landmass count is not converged.** ~10.3 average against a 6-7 target,
   with real per-seed variance (one seed produced just 1-2 substantial
   landmasses even after the retry-cap raise). This is exactly the "open
   empirical question" the original Phase 2 plan flagged — plate count,
   `FRACTION_CONTINENTAL`, and the boundary amplitudes all interact, and
   this session's tuning moved the number in the right direction without
   fully closing it. Whoever picks this up next should treat it as its own
   dedicated tuning pass, the same way `v0.3.6_1`'s continent-count fix was
   — not something to guess at inside a larger change.
2. **River/lake density needs re-tuning** against plate-driven terrain's
   different elevation-gradient character. Not investigated further this
   session beyond measuring the shift.
3. **`currents.py`'s erosion/carving** was not specifically re-verified
   against plate-driven coastlines (nothing crashed, but "does it still look
   right" wasn't checked the way the mountain-range shape was).
4. **`_pick_n_plates`'s formula** (`11 * sqrt(area_ratio)`, ±15% jitter) is a
   starting point chosen alongside the other tuning in this pass, not
   independently measured across all three world sizes — only Standard was
   used for the landmass-count measurement above.
5. Faction/capital placement's farmland check was **read**, not stress-tested
   against an adversarial world — worth a wider seed sweep if capitals ever
   start clustering unexpectedly on a future map.

### Where to start (for whoever picks this up)

`dev/coastline_metrics.py` is the tool — it already reports landmass count,
land%, coastline irregularity and mean width, and renders a real preview PNG
per seed via the actual New Game preview renderer, all against the live
`generate_world` path with zero changes needed. Run it across a wider seed
sample (15-20+) before changing anything, since per-seed variance here is
large enough that 5 seeds is not enough to trust a mean. The knobs, in
`app/world/plates.py`: `FRACTION_CONTINENTAL`, `BASE_CONTINENTAL`/
`BASE_OCEANIC`, the six `AMP_*` boundary amplitudes, `BOUNDARY_FALLOFF_FRAC`;
in `worldgen.py`: `_pick_n_plates`'s formula and `DETAIL_AMPLITUDE`. Re-render
`dev/plate_shot.py` alongside `coastline_metrics.py` when tuning plate count
or the continental fraction specifically, since those affect the plate
geometry itself, not just the height composition on top of it.
