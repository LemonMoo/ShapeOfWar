# Shapes of War — Handoff

Python/Tkinter desktop 4X strategy game. Single developer, turn-based, procedurally
generated fantasy world. Repo: `LemonMoo/ShapeOfWar`, branch `master`.

**Last release: v0.9.0, "Weather You Can See"** — the weather map overlay
(§29) and the lake basin rework (§30). Check
`gh release list --repo LemonMoo/ShapeOfWar --limit 5` before trusting this
line — this repo ships fast, sometimes several releases in one day.

**Nothing is sitting unreleased.** Working tree is clean; the **39-script
suite passes**. One caveat found while running it: `dev/test_mining_camp.py`
fails on `dev560.pkl` specifically (`workers > 0` assertion) and passes on
`dev160.pkl` and with no world — a world-specific quirk of that late-game
save, not a regression.

**Two long threads finished since the last handoff.** The **biome overhaul**
is complete — all six phases, §§19-24. The **weather system** is complete —
all five phases, §10 plus §§27-29. Neither is a live thread any more; §31 is
where to look for what actually is.

## HOW THIS PROJECT WANTS TO BE WORKED ON

Read this before anything else; it is the thing most likely to make you
useful rather than busy.

- **The user playtests in the game.** Do NOT grind on balance tuning.
  Get the mechanic correct, measure ONCE for direction, pick a sensible
  value, and then **say plainly what may need balancing and name the exact
  constant**. That hand-off is the deliverable. This was reinforced sharply
  during the archer pass (§26): a long sweep across accuracy values got the
  explicit instruction "don't spend more than a couple minutes running the
  tournament, I'd like to move on, balance can be ironed out later."
- **Correctness still deserves real verification.** "Does the chain work,
  does anything go negative, does a village starve, does the panel build"
  is not balancing — test it properly. The 39-script suite in `dev/` is the
  standing gate.
- **Do not put a noisy measurement behind an assert.** This sim has real
  run-to-run variance. A win-rate threshold over a handful of battles is not
  a gate, it is a coin flip that fails the build — it happened twice in one
  session (§26). Measure, RECORD the number in the output, assert on the
  structural fact instead.
- **Act only on effects large enough to be obvious.** §16.4 is a live example
  of a small measured delta misleading and being caught.
- **Ground new mechanics in how the real thing worked** before inventing
  one. It has produced better rules than the obvious invention every time it
  has been tried — see the Guild (§14.5), surveys (§16.3), the claim rework
  (§16.4), weather on the roads (§27) and the relative-neighbourhood road
  rule (§25.3).

## WHAT IS OPEN, ROUGHLY BY VALUE

See **§31** for the detail on the first three; the rest are older and carry
their own section references.

1. **Supply-driven pricing** — a city's price falling as its stock rises.
   `unit_price`'s surplus factor already half does it. See §16.2. This is now
   the largest unbuilt economic idea.
2. **The balance lab has no economy section** — all 217 levers in
   `app/core/tuning.py` are battle-side, so every economy number is
   source-only. Given how much of the economy is tunable constants, adding a
   `resources` section would pay for itself. See §15.5.
3. **Archers are unresolved, and the reason is interesting.** See §26. Every
   output-side lever collapses their bad-weather record long before it dents
   their clear-weather dominance, and RANGE does nothing at all — at a third
   less range they still won every clear-weather fight. That says the cause
   is not a stat.
4. **Cartographer D — Charts as a tradeable good.** The last of the four
   approved Guild mechanics; A, B and C all shipped. See §15.4.
5. **`Settlement.tax_income` is a dead stat** — wire it up or delete it.
6. **The faction health factor is pinned at its 0.5 floor 55% of the time**,
   halving every prosperity target, because production value runs under half
   of consumption value for most factions most turns. Found while fixing
   prosperity and deliberately not chased — it is a separate question about
   how those two quantities are measured. `_faction_health_factor`. See §18.1.
7. **A foothold can still end up with zero villages** (1 in 32 worlds at last
   count). Latent worldgen edge case, never chased.

**Loose ends left deliberately:**
- `flatgl_timing.log` instrumentation (`MapView._log_flatgl_timing`) is
  still active. The user was asked once whether to strip it or keep it as a
  tripwire and the conversation moved on. **Ask before removing.** See §12.
- Both audio composers (cynicmusic, rubberduck) ask for credit without
  requiring it. There is no credits screen. If one is ever added they belong
  on it — see `assets/audio/LICENSES.md`.

**Reading order for the sections below:** **§31 first** — it is the only
forward-looking section. Then §25 (roads, which changed a lot and has a
reusable idea in it), §26 (why archers are still unresolved), §28 (audio, the
newest subsystem). §12's two methodology lessons matter before touching
anything GL-related. §§19-24 and §§10/27-29 are now closed records rather than
plans. Everything else is stable background.

**The suite is 39 scripts and all of them pass.** Run it after every change:

```bash
for f in dev/test_*.py; do out=$(python "$f" 2>&1); [ $? -ne 0 ] && echo "FAIL $f" && echo "$out" | tail -6; done; echo done
```

Five of them (`test_battle_death`, `test_commander_gate`, `test_elim`,
`test_gate2`, `test_succession`) require a world path and fail with
`IndexError: list index out of range` without one — pass
`dev/worlds/dev560.pkl`. `dev160.pkl` is the fast one; `dev560.pkl` is the big
late-game world. `dev/test_lakes.py` generates real worlds and is slow by
nature; that is the only honest way to test worldgen.

**Environment:** run the suite with `PYTHONIOENCODING=utf-8` or Unicode in the
output crashes on cp1252. `build.bat` must be run from PowerShell as
`cmd /c ".\build.bat < NUL"` — it ends in `pause`. **It cannot overwrite the
exe while the game is running**, and the user often has it open; check for a
`ShapesOfWar` process and ask rather than killing it.

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

**v0.3.8 shipped background end-turn processing and a GPU-rendered flat
map**, then needed six point releases to actually be smooth and correctly
layered, then one more (v0.3.8_7) to fix a HUD-hiding bug that shipped
undetected through the whole thing. **v0.3.9 (this session) shipped a full
fantasy/medieval HUD visual redesign** across every panel in the game, a
fix for roads drawing redundantly next to each other instead of merging,
and replaced click-triggered "village view" with a zoom-scale threshold.
See **§12** and **§13**.

**The one thing to know before touching anything else:** the signature units are
working and legible but **not balanced**, and the release notes say so out loud.
Read §4.1 before moving any number — `dev/balance_lab.py` is the tool for it, and
the shares are the knob, not the stats.

Release flow, for the next one — semantic `v0.x.y` tags, decoupled from the
internal `CHANGELOG_VERSION` integer (see §12/§13's release notes for what
that looked like in practice): bump `APP_VERSION` in `build.bat` (a small
fix-batch that doesn't warrant a full `z` bump gets a `v<x.y.z>_<n>`
sub-bump instead — `n` increments, based off the actual latest published
release via `gh release list`, not a remembered one), add a
`CHANGELOG_ENTRIES` entry at the top of `app/core/changelog.py` (never
renumber the older `version:` integers — that re-flags dismissed entries as
NEW for existing players), write `release_notes_<x.y.z>.md`, run
`.\build.bat` from PowerShell directly (a Bash/`cmd /c` invocation of the
`.bat` has silently no-op'd before — the batch file also ends in `pause`,
which hangs a non-interactive shell unless stdin is closed), verify the
stamped version with `(Get-Item dist\ShapesOfWar.exe).VersionInfo` and
actually launch the exe once before publishing, then
`git push origin master` and
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
- **Economy and biome harnesses**, all added during §14-§19:
  `test_labor`, `test_buildings`, `test_gold`, `test_cartographer`,
  `test_timber_upkeep`, `test_stockpile`, `test_spoilage`, `test_claim_cost`,
  `test_mining_camp`, `test_logistics_reach`, `test_prosperity`, `test_biomes`.
  Most take a world as `argv[1]`.
- **Tk widget-tree harnesses**: `test_panels`, `test_build_menu`, `test_keys`.
  They build a real MapView/Toplevel and assert on the widget tree, and exit 0
  with a message where there is no display. This is the gap §13.1 flagged.
- `dev/storage_audit.py` — pool fill, what is destroyed, and what the throttle
  suppressed. Takes a world or `--fresh <seed> <turns>`. **Every economy number
  quoted in §14-§18 came out of this**; measure with it before and after.
- `dev/labor_ab.py` — A/B template: disables the thing under test by making it
  never bind rather than adding a flag.
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

---

## 10. Regional weather — COMPLETE (phases 0-1 here, 2-4 in SS27-29)

Several design-question rounds preceded any code, same as the plate rework.
Decided: per-region (not world-wide), multi-turn events (not per-turn
flicker), correlated with each region's existing static `dominant_climate`,
occasional rather than constant, two severity tiers (Mild/Severe), four
kinds (Drought/Storm/Blizzard/Fog). Also decided, for the LATER phases:
weather affects crop yield during the Growing/Plant stage (not a direct
Harvest-turn multiplier), logistics gets a genuine LIVE per-turn slowdown
(not just a dispatch-time roll), battle gets real combat effects (its own
project — battle has zero terrain hooks today) with NO tournament-rigor
requirement for v1 (the user's own call, explicitly not the recommended
option), and presentation is both an alert/badge AND a map/globe visual
overlay.

### Phasing

1. **Weather core** (done) — event generation only, no wiring.
2. **Economy** (done) — Growing/Plant-stage weather modifies the eventual
   Harvest; surfaces through the existing alert pipe.
3. **Logistics** (DONE — see S27) — a genuinely new live per-turn slowdown
   mechanism (today `turn_progress` is a flat `+= 1` and commander/ship
   movement is a flat cells-per-turn; neither varies turn-to-turn at all),
   built generically, then hung with weather.
4. **Battle** (DONE — see S28) — its own project per the user's explicit
   answer; do at least a basic sanity tournament pass even though full
   rigor wasn't required, so nothing ships silently unplayable.
5. **Visual** (DONE — see S29) — map overlay, deliberately last so it's
   built against settled mechanics rather than redone when tuning changes
   what needs showing.

### Phase 0: what's built and measured

`app/world/weather.py` — self-contained, takes raw `climate`/`rng` (no
World dependency, same reasoning `plates.py` took raw width/height/seed).
`WeatherEvent(kind, severity, duration)`; `advance(event, climate, rng)` is
the one-region-one-turn step; `advance_all` does every region at once from
a `{region_id: climate}` map, representing a clear region by simply having
no key rather than an explicit `None` entry.

**A real tuning miss, caught by rendering before anything downstream could
be built against it:** the first pass at `EVENT_CHANCE_PER_TURN = 0.03`
measured **24.3%** of region-turns under some weather across a real
1451-region world — a constant background condition, not an occasional
event. The number that actually matters isn't "how likely is at least one
event this season", it's the steady-state fraction of time spent under
one, which for this renewal process is `p*D / (1 + p*D)` (D = average
duration, ~11 turns). Retuned to **0.007**, targeting ~7%; measured
**7.0%**. This is a first tuning pass, not settled — re-measure once Phase
2 gives it a real gameplay consequence to weigh against, the same caveat
every other freshly-tuned constant in this project carries.

Climate correlation confirmed by both the debug render and
`dev/test_weather.py`: arid → Drought dominant (~52-58% of that climate's
events across seeds), humid → Storm (~54-58%), cold → Blizzard (~53%), Fog
reaches every climate (no lean, by design). Severity lands near
`SEVERE_CHANCE` (0.25).

**A second real bug, this time in the debug tool itself, also caught before
it could mislead anyone:** `dev/weather_shot.py`'s first version froze a
"snapshot" of active events as bare `WeatherEvent` references. `advance()`
mutates an active event's `turns_left` IN PLACE and keeps returning the
SAME object — so every "snapshotted" event kept drifting for the rest of
the simulation, and by the time the run finished, every single one reported
`turns_left=0` regardless of when it was actually captured. Fixed with
`WeatherEvent.copy()`, an independent frozen copy; `dev/test_weather.py`
asserts on this directly (`test_snapshot_copy_is_independent`) so the same
mistake can't recur in whatever future caller needs a frozen snapshot (a
save summary, a UI card).

`dev/weather_shot.py path/to/world.pkl [seed] [turns]` loads a real
generated world purely for its regions' real `dominant_climate` values
(nothing else about the world is touched), simulates, reports frequency/
duration/correlation numbers, and renders one snapshot turn as a political
thumbnail (reusing `app.ui.world_preview.render_world`, the same renderer
the New Game screen uses) with every active event marked by kind (D/S/B/F
letter) and severity (white=Mild, red=Severe).

### Phase 1: what's built and measured

`app/world/resources.py` now owns the World-facing side of weather (`import
app.world.weather as weather` for the raw generation). `advance_weather(world)`
runs `weather.advance_all` over every faction-owned region's static
`dominant_climate` (lazily creates `world.region_weather` and a seeded
`world._weather_rng`), then folds each region's active event into a new
per-region `region.crop_weather_mult` dict via `_advance_region_crop_weather`
— one multiplier per crop, nudged down by `_CROP_WEATHER_IMPACT[(kind,
severity)]` while that crop is in Plant/Growing under an active event, and
recovered by `CROP_WEATHER_RECOVERY` per turn otherwise, floored at
`CROP_WEATHER_FLOOR` (0.35) so a bad season is never a wipeout. Wired into
`advance_turn` right after `world.season` updates, so it runs once per turn
before yields are produced. `compute_village_yield` applies the multiplier
to crop amounts only (never industry) right after `_crop_yield_core`.
`node_alerts` gets a new `"weather"`/`"warning"` entry whenever a village's
region has an active Drought/Storm/Blizzard (never Fog — it has no crop
impact, so no alert).

**A real bug, caught before it could ship:** the first version let a crop's
multiplier recover on any turn that wasn't Plant/Growing-under-weather,
which includes that same crop's own Harvest stage — since Harvest spans a
full ~25-turn season, the SAME harvest would read a better yield the later
within its own Harvest window it happened to be checked. Fixed by freezing
the multiplier entirely for the whole Harvest stage (`if stage == "Harvest":
continue`, checked first in the per-crop loop). Verified directly: after a
full-season severe drought during Growing, the multiplier hit the floor and
stayed frozen at exactly 0.35 for the entire following Harvest window,
giving identical yield whether checked at the start or 10 turns in.

`dev/test_weather_economy.py` covers the real `resources.py` integration
(Phase 0's `dev/test_weather.py` only covers standalone `weather.py`):
drought measurably cuts a real village's harvest vs. an identical
undamaged baseline, the harvest-window freeze, cross-season recovery, the
alert firing for Drought/Storm/Blizzard and staying silent for Fog, and a
fresh 10-faction, 100-turn simulation with live weather the whole way
through (no crash, no negative resource stocks). All passing, alongside the
full existing regression suite (10 scripts).

### Where to start (for whoever picks this up)

Phase 2 (logistics) is next. It needs a genuinely new mechanism first, not
just a weather hook: today `turn_progress` for caravans/shipments is a flat
`+= 1` per turn and commander/ship movement is a flat cells-per-turn — 
nothing about travel speed varies turn-to-turn at all yet. Build that
live-progress-rate mechanism generically, verify it behaves sanely with
weather OFF first, then hang weather off it the same way Phase 1 hung off
the existing crop-yield pipe. Do NOT start Phase 3 (battle) before Phase 2
is wired, measured and committed on its own — same phasing discipline as
every other multi-part rework in this project.

## 11. Sea lanes for cross-landmass settlements (v0.3.7_2)

Reported bug, with a screenshot: a faction's first city on a different
landmass from its other cities showed several straight lines cutting clean
across open water on the world map — a literal road drawn through the sea.

**Root cause:** two separate call sites shared the same flaw. `construction.
_find_road_path` (run whenever a new City/Town/Castle is founded, to connect
it to the faction's nearest existing settlement) and `worldgen._bridge_
region_to_kingdom` (run at worldgen/expansion time for a settlement-less
region full of villages) both used a land-only Dijkstra path search that
fell back to the straight two-point segment whenever it found no route —
a sensible safety net for a rare local pathfinding hiccup, but exactly what
happens EVERY time when the two endpoints are on different landmasses. That
straight fallback got stored as a real `"stone"`/`"dirt"` road segment in
`world.roads_by_region` and rendered like any other road.

**Fix:** both now refuse that fallback (`_path_between`/`_local_road_path`
grew an `allow_fallback` param, `False` at these two call sites only — every
other caller, where the two points are guaranteed to share a landmass by
construction, keeps the old safety-net behavior). When land genuinely fails,
each tries a real open-water path instead — `construction._sea_lane_between`
/ `worldgen._local_sea_lane`, both the same dock-to-dock Dijkstra
`trade._capital_sea_path` already uses for cross-faction sea trade, just
standalone (construction.py/worldgen.py can't import trade.py without a
cycle). `_find_road_path` also now tries every candidate settlement
nearest-first for land, then again nearest-first for sea, rather than
committing to a single "nearest overall" origin — a faction's capital is
often well inland, and the nearest settlement by raw distance isn't
necessarily the one with a coast. If NEITHER a land nor a sea route exists
(no coast on either side), the connector is skipped entirely — the
settlement/region still exists, it just starts unconnected, same as any
other genuinely isolated case in the game, rather than faking a road again.

New `"sea"` road tier, rendered distinctly (`map_view.py`: dotted, the same
`_TRADE_SEA_COLOR` sea-trade-route blue, on both the flat map and the
globe, visible at every zoom like the stone trunk network). A sea lane has
no construction phase of its own (nothing physical to build across open
water — `SettlementProject.sea_lane` is folded straight into
`roads_by_region` the moment the settlement itself finishes, unlike a land
`RoadProject` which still builds cell-by-cell over `ROAD_CELLS_PER_TURN`).

**Retroactive repair for existing saves:** the code fix only stops NEW fake
roads; a save from before it can still have one baked in. `worldgen.
repair_ocean_crossing_roads` scans every road segment for the bug's own
unambiguous signature — a `"stone"`/`"dirt"` segment whose straight line
crosses an OCEAN cell, which a real Dijkstra-routed road can never do — and
replaces it with a genuine sea lane where one exists, or drops it where it
doesn't. Versioned and idempotent exactly like `resources.migrate_legacy_
overflow` (`world._road_migration_version`), wired into `save.load_game` so
every existing save gets repaired automatically the next time it's opened —
no player action needed.

**Verification:** `dev/test_sea_bridge.py` reproduces the exact scenario
(two real coastal settlements from a real generated world, on different
landmasses) end to end — `_find_road_path` returns a real sea path (never a
straight cut through unrelated terrain), `start_settlement` records a
`sea_lane` instead of queuing a land `RoadProject`, the finished settlement's
region carries a `"sea"` tier segment, and a second test plants exactly what
the OLD code would have produced (a straight `"stone"` segment across real
ocean) and confirms the migration removes/repairs it and is a no-op on
re-run. A fresh 150-turn, 10-faction simulation at scale (ordinary AI play,
no forced scenario) additionally confirmed zero ocean-crossing stone/dirt
segments occur in practice, and the full existing regression suite (10
other scripts) still passes.

Nothing left open here — this was a self-contained bug fix, not a phased
system. If a similar "two points might be on different landmasses" case
turns up elsewhere later (e.g. Phase 2's logistics work, if a caravan route
ever needs to reason about crossing open water), the same `allow_fallback`
pattern and `_local_sea_lane`/`_sea_lane_between` helpers are the template.

---

## 12. v0.3.8 — background end-turn + GPU flat map, and six releases to make it right

Two features shipped together in v0.3.8, then the GPU flat map specifically
took **six more point releases** (v0.3.8_1 through _6) before it was
actually smooth, and a seventh (_7) to fix a HUD-hiding bug that had been
shipping invisibly the whole time. Read this section before touching
`gl_flatmap.py`, `_sync_flatgl`, or anything else GL-related — two real
methodology lessons came out of this that will save real time on the next
GL bug.

### What shipped in v0.3.8 itself

- **Background end-turn processing**: `advance_turn` now runs on a worker
  thread (`MapView._turn_queue`/`_turn_token`/`_run_end_turn`/`_turn_worker`/
  `_turn_drain`) instead of freezing the window every single turn.
  `_end_turn_busy` guards against mashing End Turn stacking panel rebuilds
  mid-teardown; `_turn_token` invalidates a stale in-flight result if
  somehow more than one could ever be running (defensive — `_end_turn_busy`
  already prevents that, but a stale result must never be able to land
  regardless). `_turn_in_flight` is the narrower flag `render()` actually
  gates on, since `_finish_end_turn`'s own post-processing/animation/
  cooldown still needs to render while `_end_turn_busy` is technically
  still true.
- **GPU-rendered flat map** (`app/ui/gl_flatmap.py`, new): an orthographic
  sibling to `gl_globe.py`, reusing what's projection-agnostic from it
  (line/marker/text-glyph shaders, the bitmap font atlas) rather than
  rewriting them — a flat camera is just `u_rot = identity` and an ortho
  `u_viewproj` built from the same `view` rect the flat map already
  tracked. `GLFlatMapFrame` swaps in for `self.canvas` the same way the
  globe swaps in for the canvas (`_activate_flatgl`/`_deactivate_flatgl`),
  with the Tk/PIL canvas kept as the automatic fallback wherever
  `gl_flatmap.gl_available()` is false — no new player-facing toggle, same
  pattern as the globe's own degrade. Picking (`screen_to_cell`) is a
  direct orthographic inverse, no ray-sphere math needed. Full shape-aware
  markers (`SHAPE_CIRCLE`/`TRIANGLE`/`SQUARE`/`DIAMOND`/`HULL`), terrain
  symbols (baked into the base raster instead of drawn as vector polygons
  every frame — a fixed-density tradeoff against the canvas path's
  scale-adaptive one, judged acceptable for a purely decorative flourish),
  and zoom-scaled line widths were all added in the same release, not as
  later follow-ups.

### The stuttering saga (v0.3.8_1 through _6): five real fixes, one false lead

Triggered by user-submitted screen recordings and `flatgl_timing.log` files
from a real, large, developed save (`dev/worlds/dev560.pkl`-scale) showing
the GPU flat map choppy while panning. Every fix below was verified against
real re-test data from the user's machine, not assumed fixed from theory —
several plausible-looking hypotheses were tried, measured, and explicitly
ruled out before landing on the real cause:

1. **v0.3.8_1** — `MapView._map_labels`'s `elif level == 1 and
   region_names:` let a `False` `region_names` fall through to the
   `else:` branch (settlement/village names) instead of doing nothing. A
   correctness bug, not a perf one, but shipped in the same window.
2. **v0.3.8_2** — `gl_flatmap.GLFlatMapFrame.set_map` was re-uploading the
   whole terrain texture to the GPU on **every single frame**,
   unconditionally. Fixed with an identity check
   (`if map_img is not self._map_img or fog_img is not self._fog_img`)
   before marking the texture dirty.
3. **v0.3.8_4 — a real fix that was NOT the actual cause.**
   `App._prepare_world_gc` (`gc.unfreeze(); gc.collect(); gc.freeze()`,
   called once per world load) is a genuine optimization — `gc.collect()`
   on a loaded world measured ~27ms before, ~0ms after — and is still
   worth keeping. **But the user's re-test showed the identical stutter
   pattern, unchanged.** This is the single most important methodology
   note in this whole saga: a mechanism that's confirmed correct **in
   isolation** is not the same as a confirmed **root cause** — that needs
   a before/after test against the actual reported symptom. An antivirus
   hypothesis was also raised and cleanly ruled out the same cheap way
   (user excluded the folder, no change) before the real cause was found.
   Full writeup: memory `shapes_of_war_gc_freeze`.
4. **v0.3.8_5 — the first real fix.** `MapView._sync_flatgl` was rebuilding
   `_map_lines`/`_flat_markers`/`_map_labels` from scratch on **every**
   `render()` call, including every single frame of a mouse-drag pan, even
   though none of those three functions read the camera's pan position at
   all (only `gl_flatmap.py`'s own `_wrap_x` does, applied later at
   GPU-buffer-pack time). Fixed with `_flat_content_signature(level,
   scale)` — a cheap tuple of everything that actually CAN change that
   output (turn, territory_version, level, scale, mode, selections,
   attack/building mode) — and `_sync_flatgl` now only rebuilds when that
   signature changes or a flash/move-animation is actively playing (both
   time-varying, can't be captured by a static signature). The concrete
   lead that found this: the globe never had this problem, because its own
   drag-to-rotate handler calls `render_now()` directly and never touches
   `_map_lines`/`_map_labels` mid-drag at all. Verified: 20 pure-pan frames
   now trigger zero rebuilds; a zoom or selection change still triggers
   exactly one. Full writeup: memory `shapes_of_war_flatgl_content_cache`.
5. **v0.3.8_6 — the second layer of the same bug.** A user-submitted
   follow-up `flatgl_timing.log` showed the exact same alternating-
   magnitude cost signature had just moved one level down: even with the
   *same* cached Python list handed to `gl_flatmap.py`'s `set_lines`/
   `set_markers`/`set_labels` every frame, each one still repacked its GPU
   instance buffer from scratch, because `_wrap_x` needs the current
   camera position to place points correctly across the world's east-west
   seam. But the actual wrap DECISION for any given point only changes
   when the camera crosses that seam, which ordinary panning essentially
   never does. Fixed with a wrap-bucket cache
   (`round(view_center_x / world_w)`) per buffer: skip the repack when
   both the input list (`is` identity) and the bucket are unchanged from
   last call. **User confirmed after this one: "It's perfectt."** General
   pattern for any future GL-frame content fed from a cached Python list
   that still needs per-frame positional wrapping: cache on
   `(identity, wrap_bucket)`, not identity alone.

### v0.3.8_7 — a completely different, unrelated bug found by accident

While scoping an unrelated UI redesign request, a clarifying question about
"what's still wrong with the UI" got the answer **"None of the HUD panels
are displaying."** Root cause: `self._flatgl` (the GPU flat map's Tk
widget) is created lazily on the very first `render()` call — well after
`__init__` had already built and raised every side panel. In Tk, a newly
created/mapped widget joins the **top** of its parent's stacking order by
default, regardless of when its siblings were last `.lift()`-ed. Since
`_flatgl` fills the entire `MapView` area, it silently covered the resource
bar, faction panel, alerts, treasury and trade log the instant the flat map
activated. Fixed with one line: `self._flatgl.lower()` right after packing
it, in `_activate_flatgl`.

**Why this shipped undetected through the entire six-release saga above:**
every visual check used during that whole investigation was
`ctx.screen.read()` — reading the moderngl framebuffer directly to verify
GL rendering correctness. That technique can only ever show the GL
surface's *own* content in isolation; it has **no way to reveal whether
other Tk sibling widgets are stacked above or below it** in the real
composited window. This is a structural blind spot, not a one-off miss —
any future work that layers a new Tk widget as a sibling to existing
raised/layered UI (especially one created lazily after `__init__`, and
especially one that fills its whole parent) needs its stacking order
checked directly (`parent.winfo_children()`, ordered bottom-to-top), not
assumed correct because the GL surface itself renders fine. Full writeup:
memory `shapes_of_war_flatgl_zorder`.

**A separate environment note, hit twice this session:** `PIL.ImageGrab`
(OS-level screenshot) proved **unreliable** for verifying this game's Tk
window specifically — it repeatedly captured content from unrelated
applications instead of the target window, even when using
`win32gui.GetWindowRect()` to compute a precise bounding box. Don't reach
for it here. Use `ctx.screen.read()` for GL surface content, or direct
Tk widget/attribute inspection (`winfo_children()`, `.cget(...)`, building
a real widget tree in a throwaway script and asserting on its state) for
everything else.

**Still open:** `flatgl_timing.log` diagnostic logging
(`MapView._log_flatgl_timing`, threshold `_FLATGL_LOG_THRESHOLD_MS = 20.0`)
is still wired into `_sync_flatgl` as of v0.3.9_4. It was useful — it's how
every fix in this section got found — but nobody has decided whether it
should be stripped out now that the investigation is closed, or kept as a
standing tripwire in case a regression reintroduces per-frame cost. Ask
the user before removing it or leaving it; it was asked once mid-session
and the conversation moved to a different topic before it was answered.

---

## 13. v0.3.9 — fantasy HUD redesign, road merging, zoom-based village view

This session. Three separate, sequential user requests, each shipped as its
own point release with the existing `dev/test_*.py` regression suite run
after every change (all passing throughout — nothing in this section
touched game logic beyond the road-pathing cost function in §13.2).

### 13.1 Fantasy/medieval HUD redesign (v0.3.9 → v0.3.9_2)

Full visual redesign across every panel in the game, in four phases, driven
by two complaints: inconsistent/dated styling, and too much information
crammed into view at once. Confirmed scope up front: fantasy/medieval
theme, "show less at once" (fold detail behind clicks) plus bigger text and
click targets, right-hand faction/region panel as the top priority.

- **Phase A — foundation.** `app/ui/theme.py` went from 3 colors/3 fonts to
  a full palette: warm parchment/aged-leather colors (`PANEL_ALT`, `CANVAS`,
  `ACCENT` gold, `ALERT_BG`, `METER_TRACK`, `ORDER_CUE_*`), a serif display
  font (`Cambria`, built into Windows since Vista — used for
  `FONT_TITLE`/`FONT_HEADER` only, body text stays sans-serif since serif
  reads worse at small sizes) plus a bumped-up body font, and sizing
  constants (`BTN_PAD_Y`, `CARD_HEAD_PAD_Y`) that directly implement
  "bigger click targets." New `app/ui/widgets.py`: `card`/`kv`/`bar_row`/
  `button` factory functions, extracted from `MapView`'s own
  `_card`/`_kv`/`_bar_row` methods (which now just delegate to it) so
  `battle_view.py` can use the same idiom instead of hand-rolling its own.
  Deliberately **not** done: a bundled custom TTF font via
  `ctypes.AddFontResourceExW` (real risk — PyInstaller onefile
  temp-extraction interaction, silent failure with no fallback — for a
  marginal gain over Cambria, which is already installed everywhere this
  game ships) or parchment-texture bitmap backgrounds (Tk widget
  backgrounds are solid colors only).
- **Phase B — the right-hand panel.** `_show_faction`/`_show_region` were
  rewritten from one long paragraph of stats (`self.info.config(text=...)`)
  into a short header plus foldable `SUMMARY`/`RELATIONSHIPS`/`SETTLEMENTS`
  cards — the same idiom `_show_settlement`/`_show_village` already used.
  `_RIGHT_PANEL_W` went 320→360 to give the bigger fonts room; every
  `wraplength=260` literal across the file (25 of them) now derives from
  the constant instead.
- **Phase C — the rest of `map_view.py`.** Resource bar, alerts panel
  (kept a deliberately distinct `ALERT_BG` red tint rather than unifying
  with `PANEL_ALT`), treasury popup (its locally-scoped `header()`/`line()`
  closures — a worse duplicate of `_kv`/`_card` — replaced with real
  `widgets.card`/`widgets.kv` calls, making the Treasury's TOTAL/WHERE IT
  IS/WHERE IT CAME FROM/RECENT TURNS sections genuinely foldable), trade
  log, edge tabs. A global find/replace promoted the two most-repeated
  stray hex literals (`"#232a36"` → `theme.PANEL_ALT`, 35 uses;
  `"#0d1017"` → `theme.CANVAS`, 16 uses) across the whole file in one pass.
- **Phase D — `battle_view.py`.** Same button/card treatment. ORDERS
  stance/fire buttons deliberately **not** folded by default — those are
  time-pressured clicks during a live sim tick, unlike the map's leisurely
  panels. `_ORDER_CUE` moved to `theme.ORDER_CUE_*` constants but kept
  **distinct** from `GOOD`/`WARN`/`BAD` (a stance cue isn't the same
  semantic concept as health-bar status, even though the health bar itself
  does now reference `GOOD`/`WARN`/`BAD` directly since those genuinely are
  the same concept). `widgets.button` grew a `compact=True` option
  (smaller font, tighter padding) specifically for the per-unit-type
  select-button row — the default bigger-click-target sizing measurably
  overflows a 300px-wide row of 5-6 buttons.
- Deliberately left un-migrated: genuine battlefield/gameplay-visualization
  colors in `battle_view.py` (unit selection rings, formation-tool ghost
  color, projectile/effect colors) — these are game content, not HUD
  chrome, and restyling them wasn't part of the ask.
- No dedicated Tk-widget-construction test exists for "does the panel
  widget tree still build without exceptions" the way there is for globe
  rendering (`dev/globe_shot.py`) or battle logic. Verification this
  session used one-off scripts (built in scratch, not committed) that
  construct a real `MapView`/`BattleView` against `dev/worlds/dev*.pkl`
  and call every `_show_*`/`render()` method directly. **Worth turning
  into a real `dev/panel_shot.py`-style script** if UI work continues —
  the pattern (`MapView(root, world, lambda *a, **k: None, ...)`, then
  call `_show_faction`/`_show_region`/`_show_settlement`/`_show_village`/
  `_show_commander` for a real node of each kind) is reusable as-is.

### 13.2 Roads no longer draw redundantly parallel to existing ones (v0.3.9_3)

Reported bug: new roads/dirt paths were frequently drawn as their own line
right next to an already-existing road instead of merging into it.

**Root cause:** `worldgen._elev_cost` already had an opt-in `roads=`
parameter (a cell an existing road runs through becomes much cheaper to
path through — `_ROAD_TRAVEL_MULT = 0.3`) — but it was only ever passed by
callers moving GOODS (`trade._land_path_between`,
`resources._local_path`), never by the callers that actually **build**
new roads (`worldgen._local_road_path`, `construction._path_between`, and
`expansion.ensure_interregion_roads` via the latter). The exclusion was
deliberate — a prior comment argued road construction "must keep pathing
on raw terrain, or every new road would snap onto whatever was built
first" — but real-world testing showed the opposite outcome was worse:
independent, needlessly parallel roads a few cells apart.

**Fix:** pass `roads=road_cells(world)` at all three construction call
sites. Each caller already bounds its search to a padded bounding box
around the two endpoints (`_ROAD_BBOX_PAD`/`_BBOX_PAD`), so this can't pull
a route wildly off-course toward some unrelated road on the far side of
the map — only a road that's already roughly on the way to begin with is
ever cheap to reach. Verified: full regression suite plus a fresh
`generate_world` call inspected for sane, non-degenerate road segments.

**Not retroactive.** This only changes how NEW roads are pathed going
forward — a save with roads already drawn redundantly close together
before this fix keeps them exactly as they are. If that turns out to
bother players on existing saves, the natural next step is a repair
migration in the same shape as §11's `worldgen.repair_ocean_crossing_roads`
(versioned, idempotent, wired into `save.load_game`) — nothing like that
exists yet for this specific case.

### 13.3 Village view replaced by a zoom threshold (v0.3.9_4)

Reported complaint: double-clicking a region to enter "village view" felt
clunky and often didn't seem to register.

**Root cause, found by reading the actual click/zoom code:**
`_enter_village_view` zoomed the camera to `self.zoom_faction.meta["bbox"]`
— **the exact same extent `_enter_region_view` already sat at.** Clicking
through to "village view" changed what was drawn (villages appeared) but
never actually moved the camera at all, so there was no visible feedback
that anything had happened. Separately, a settlement/village marker
sitting under the second click could silently intercept it as a settlement
selection instead of confirming the region.

**Fix, per explicit user design decision** ("merge into one continuous
mode" over "keep the separate chrome, just auto-trigger it"): the whole
discrete "village view" mode is gone. `zoom_region`, `_enter_village_view`,
`_exit_village_view` are deleted entirely. New `MapView._villages_visible()`
returns `True` purely from how far zoomed in the free camera already is
(`min(view_span_x, view_span_y) <= _VILLAGE_REVEAL_SPAN`, currently `26`
world-cells) while inside a faction's own (non-foreign) territory. Villages
simply fade into clickability as the player zooms in on their own — no
click step to get wrong. `_flat_level()` (GPU map), `_draw_villages`/
`_draw_labels` (Tk canvas fallback), and `_on_click`'s region/village
hit-testing were all switched from checking `zoom_region is (not) None` to
calling this one function. Foreign-faction browsing still cannot reach
village level regardless of zoom (unchanged: diplomacy actions only).
`_jump_to_alert_node`'s village branch now zooms the camera in tight on the
specific village's position (`_VILLAGE_REVEAL_SPAN * 0.7` span) rather than
to the whole faction bbox, since there's no discrete mode left to enter.

**`_VILLAGE_REVEAL_SPAN = 26` is a first-pass estimate, not a playtested
number.** It was picked from measured geography on a real save (average
region "diameter" ~14 cells, village nearest-neighbor spacing ~7-10 cells)
— enough to show a region's own villages plus a bit of its neighbors once
zoomed in — but nobody has actually played with it yet. If villages
reveal too early (while still feeling "zoomed out") or too late (having to
zoom in uncomfortably far), this is the one constant to move; nothing else
needs to change.

Verified: full regression suite, plus a throwaway script exercising
`_villages_visible()` at both zoom levels, a simulated click hitting a
real village marker, `_jump_to_alert_node` on a village, the foreign-
browsing guard, and clicking an ocean cell to confirm `_exit_region_view`
still fires correctly.

---

## 14. The economy rework — labour, buildings, coin, cartography

*Released in v0.4.0. Phases 1 and 4 of the plan are here; §16 covers the
rest (2, 3, 5) and the Cartographer's surveys.*

Five commits on `master`, none released. Driven by one reported symptom —
"storage just ends up piling up and spoiling" — which turned out not to be a
storage problem at all.

**Read `dev/storage_audit.py` first.** It is the tool the whole rework is
measured against, and it takes a saved world or `--fresh <seed> <turns>`.
Every number quoted below came out of it and can be reproduced.

### 14.0 The measurement that reframed everything

Fresh 10-faction world, 120 turns, before any of this:

| | household | durable | other | feed |
|---|---|---|---|---|
| mean fill | 0.39 | 0.53 | 0.02 | 0.21 |
| p90 fill | **0.91** | **0.99** | 0.07 | 0.74 |
| production silently throttled away | **53.6%** | **33.1%** | 0.5% | 37.8% |

774,581 units destroyed in 120 turns, plus ~639,000 more that were never
produced at all because `storage_throttle` deleted them at source. Neither
number was ever shown to the player.

The cause was a single ratio: **potential production ran ~50x total demand.**
One village adult harvested 2.58 units of food a turn and ate 0.005. Storage
was not failing — it was the organ absorbing an unbounded surplus, invisibly.

### 14.1 Phase 14: finite village labour (commit `907658b`)

Terrain no longer says what a village produces; it says what it COULD. A
village's `adults` are a finite workforce split across the sectors its land
offers (farming/forestry/mining/fishing), and each sector produces
`min(terrain potential, workers * LABOR_OUTPUT_PER_WORKER)`.

- `LABOR_OUTPUT_PER_WORKER` is **the** calibration knob for total output.
- `LABOR_SECTOR_RESERVE` (0.05) staffs every live sector enough to work what
  it has before the policy splits the rest. Without it, weighting by tonnage
  erases rare resources entirely — a village with 300 units of farming
  potential gave a gold seam a 0.0007 share.
- Under `Auto`, a full pool pulls hands OFF the sector filling it
  (`LABOR_PRESSURE_FLOOR`). This is what finally makes storage pressure mean
  something instead of deleting goods in silence.
- Seasons emerge for free: crops only harvest in season, so hands move to the
  woods over Winter with no seasonal rule written anywhere.

Result: household throttle-loss 53.6% → 2.1%, durable 33.1% → 20.8%, total
destroyed 774,581 → 445,220. **A/B with the limit disabled**
(`dev/labor_ab.py`, same seed): population +1,547, villages +70, gold +1,048,
dead stock −15%. It is a net gain, not a nerf.

One real bug the harness caught: single-pass spillover leaked labour, because
a sector receiving spare hands can hit its own ceiling too. Redistribution now
repeats. `dev/test_labor.py` asserts it as a property across every village.

### 14.2 The buildable menu (commit `bde386a`)

Measured: **one granary and one warehouse across 651 nodes** on the turn-561
world. The buildings existed and were unreachable in practice.

- `app/world/buildings.py` — the model. `build_options(world, node, nation)`
  returns `BuildOption` cards with a priority (urgent/useful/idle/blocked) and
  a human reason drawn from that node's own production and storage pressure,
  plus cost, turns and effects. **This is game logic, not UI** — it is testable
  without a widget tree and `run_storage_ai` reasons about the same question.
  It never spends anything.
- `app/ui/build_menu.py` — a Toplevel card grid, needs-first, with tier pips
  and a PRODUCTION header. The old in-panel build UI is gone; the side panel
  keeps a summary and a door.
- **First real Tk widget-tree harnesses in the project**:
  `dev/test_build_menu.py` and `dev/test_panels.py` — the gap §13.1 flagged.
  Both exit 0 with a message where there is no display.

Two Tk traps, both noted in source: `padx`/`pady` take a scalar in a widget
constructor and only accept the `(before, after)` tuple in `pack`/`grid`; and
mouse-wheel scrolling must be bound on the toplevel or it dies whenever the
pointer is over a card.

### 14.3 Coin (commit `b93f216`)

Gold was a real produced resource that produced almost none. A fresh world at
turn 120 had mined ZERO Gold Ore and minted zero; the only coin in the game
was the starting reserve draining at −77/turn. **Four separate broken links**,
each invisible alone — this is the section's methodology lesson: they were only
findable by walking the whole chain from seam to vault.

1. **Rounding deleted the resource.** The yield cores rounded every resource to
   an int per village per turn, so anything under half a unit became zero
   forever. Gold Ore/Gems/Tin take a 0.0488 share of a mountain against
   Iron/Coal/Stone's 0.2439. Yields are floats now and `_deliver_village_yield`
   carries the fraction on the village.
2. **Labour weighted by tonnage** — fixed by `LABOR_SECTOR_RESERVE` (§14.1).
3. **Priority-list starvation, in TWO places.** `run_local_logistics` and
   `trade.run_sell_to_city` each move one resource per node per turn off a
   fixed list. Local logistics dispatched 1,155 shipments over 20 turns of
   which exactly ONE was Gold Ore; sell-to-city moved 11,102 Coal and zero ore
   because "Coal" sorts before "Gold Ore". Both now use
   `resources.rotate_for_turn` — a pure function of the turn, so determinism is
   unchanged. **Any future "scan a fixed list, dispatch first match, break"
   loop needs this.**
4. **`run_sell_to_city` could not see villages**, and 82 of 85 ore-bearing
   regions have no settlement at all.

Plus `GOLD_ORE_YIELD_PER_CELL` (lifted out of the general mining rate, which
was cut for sink-less goods — ore's whole purpose is to be consumed), and two
buildings: **Gold Mine** (village, gated on a real seam via `has_gold_seam`)
and **Mint** (settlement, tiered throughput plus better refining at the top;
tier 0 is 1.0 so no existing save regresses).

Measured across three seeds at 120 turns: seed 123 mints 6,811 and ends −1,632
instead of −9,288; seed 7 mints 4,453; seed 42 is a genuinely gold-poor world
and mints none, which is correct for a scarce geographic resource, not a bug.

### 14.4 Labour orders (commit `2494e09`)

`apply_labor_policy(world, village, policy, scope)` with scope
`village`/`region`/`realm`, never reaching another faction's villages. It
clears the per-`(turn, season)` allocation cache — without that, a policy set
mid-turn leaves the panel showing, and the turn producing, the old split.
`labor_policy_available` hides a focus with nothing to work (out of season is
deliberately still offered). `village_labor_report` reports idle hands, so a
village where every sector is already land-limited says so rather than letting
the buttons look broken.

The build window also drops the OS titlebar (`overrideredirect`) and supplies
its own border, draggable header, focus, centring and themed scrollbar.

### 14.5 The Cartographer's Guild (commit `b90cc42`)

A Guild does **not** generate knowledge — it multiplies what the realm already
gathers by moving about. This follows what cartographers actually did (Casa de
la Contratación, VOC ships' logs, portolan charts compiled from merchants'
bearings), and it is a better rule than the obvious invention.

- Every reveal `vision.py` already does for your own agents widens by
  `CARTOGRAPHER_TRAFFIC_BONUS` (+4/+8/+13 by tier); caravans additionally
  report the whole route travelled, not just where they stand.
- The bonus is the realm's **best** Guild, not the sum.
- Unaided it surveys only `CARTOGRAPHER_LOCAL_RADIUS` (9/14/20) at 0.3–0.6
  cells/turn, hard-capped. Paper doubles that and is deliberately never
  required (the Preserving-House-and-Stone trap).
- Measured: a tier-3 Guild dropped into the benchmark world reveals 0.19% of
  the map before surveying anything. `dev/test_cartographer.py` asserts that
  negative claim directly — "buying this must not hand you a map" is the
  property a later small change is most likely to break.

Also: the New Game preview now shows only your own starting zone
(`render_world(..., hide_rivals=True)`, the default; dev tools pass `False`),
and `land_summary` no longer names the nearest rival.

### 14.6 Regression suite

**18 scripts, all passing.** New this session: `test_labor`, `test_buildings`,
`test_build_menu`, `test_panels`, `test_gold`, `test_cartographer`. The ones
that take a world take it as `argv[1]` (default `dev/worlds/dev560.pkl`).

---

## 15. The economy plan — what it said, and what is left

*Phases 2, 3 and 5 and Cartographer B/C are DONE — see §16 for what
actually got built and how it differed. What remains live here is §15.4's
mechanic D, and the standing findings in §15.5.*

The user approved a five-phase plan and picked all four player levers. Phases
1 and 4 shipped (§14.1, §14.4). **Phases 2, 3 and 5 remain, in that order**,
plus the rest of the Cartographer (§15.4).

### 15.1 Phase 2 — real demand sinks — **DONE, see §16.1**

Durables still pile up: p90 fill 0.91, 20.8% of durable production still
thrown away. Measured on a fresh world at turn 80 (scratch probe, easy to
rebuild — sum `_deliver_village_yield` output by `storage_class` over 20 turns
and diff node stocks):

    made/turn   978.6 durable units      net accumulation  +722.5/turn

**Only ~26% of durable production is consumed by anything.** Wood is the bulk
(Logs 301 + Softwood 289 + Hardwood 140 per turn).

The plan — continuous consumption so durables have somewhere to go:

- **Fabric upkeep.** Population consumes timber per turn — houses rot, roofs
  need rethatching. Pool Logs/Softwood/Hardwood/Planks the way `_FOOD_SOURCES`
  is pooled, so any of them covers the need.
- **Building maintenance.** Every built tier costs upkeep per turn. This is
  what gives the build decision ongoing weight instead of being a one-off.
- **Add it to `settlement_needs`.** The important implementation note:
  `settlement_needs` already drives `_consume_node_needs`, `node_alerts`, and
  logistics' `_node_wants`/`_node_surplus`. A new need plugs into consumption,
  the alert pipe AND automatic redistribution in one move.
- Shortfall consequence: prosperity penalty via the existing
  `_SHORTAGE_PROSPERITY_PENALTY` machinery. **Do not** degrade building tiers —
  irreversible-feeling and untested.

**Size the sink against ~700/turn net accumulation**, targeting absorption of
most but not all of it. Total population on that world was 34,085, so roughly
0.012–0.02 timber per person per turn is the right starting order.

**CRITICAL — do not add sinks for goods that are not actually produced.**
Measured on the same world: Iron 0.2/turn, Copper 0.1, Coal 0.2, Tin 0.0. A
Stone or Iron upkeep would starve the map instantly. Only wood is genuinely
overproduced. Verify with the probe before choosing any resource.

### 15.2 Phase 3 — market sink + sell-surplus policy — **DONE, see §16.2**

- Supply-driven pricing: a city's price for a good falls as its stock rises.
  `trade.unit_price` and `_regional_unit_price` already exist to build on, and
  `run_sell_to_city`'s own comment notes the surplus factor already half does
  this.
- Per-good player sell policy: what a node auto-sells, and at what threshold.
- This is also where **stockpile targets / rationing** belongs — the fourth
  lever the user picked, still unbuilt. A target reserve per good is the same
  concept as a sell threshold seen from the other side.

### 15.3 Phase 5 — storage as a cost curve, spoilage retune — **DONE, see §16.4**

- Replace `STORAGE_THROTTLE_FLOOR = 0.0` with a soft floor so production
  continues wastefully rather than vanishing silently. The throttle is now much
  less active (2.1% household), so this is safe to revisit.
- Fish + Smoked Fish are still **34% of everything destroyed** (74,529 +
  74,809 over 120 turns). The Preserving House is the existing answer and the
  build menu now surfaces it; re-measure before adding anything new.
- Re-check pool sizing: `other` sits at 2–4% of capacity and `feed` at 8–21%
  while `durable` p90 is 0.91. Space is allocated to pools with nothing to hold.

### 15.4 Cartographer — **B and C DONE (§16.3); D remains**

The user approved all four mechanics. **A shipped** (traffic compilation),
along with the small local survey. Still to build:

- **B — commissioned surveys.** Pay gold and supplies; a surveyor party walks
  outward over N turns revealing its path, and can be lost in wild or hostile
  country. Needs a new expedition object with a turn hook (mirror
  `RoadProject`/`ShipyardProject`) and a UI entry point. Recommend
  auto-targeting the nearest unexplored frontier for v1 — the decision the user
  wanted is *whether and when to pay*, which auto-targeting preserves — with
  compass-direction aiming as a refinement.
- **C — coast before interior.** Surveys from a coastal settlement (more with a
  shipyard) travel further and faster along coastline.
  `construction._is_coastal` already exists.
- **D — Charts as a tradeable good.** A new resource made from Paper at a
  settlement with a Guild; tradeable and giftable, and acquiring a faction's
  charts reveals what they know. Touches the resource registry, `RECIPES`,
  trade and diplomacy — treat it as its own phase.

### 15.5 Standing findings worth acting on

- **`Settlement.tax_income` is a dead stat.** Rolled at founding, read only for
  prosperity valuation, generating no gold since the Currency overhaul moved
  coin onto minting. Either wire it up or delete it.
- ~~**Mining is structurally broken by village placement.**~~ **ADDRESSED —
  see §17.3 (the Mining Camp).** The diagnosis here was right about the cause
  (villages are sited on farmland, only 4 of 185 had a mountain cell in
  catchment) but wrong about the severity: a *fresh* world produces no ore
  because no mountain region has been claimed yet, while a developed save was
  already making 57 Iron/turn. It is not "broken", it is "unavailable until you
  take the mountains". A large part of what looked like this finding was
  actually §17.1's logistics faults sitting on top of it.
- ~~**Prosperity is flatlined near 0–2**~~ **FIXED — see §18.1.** It was not a
  tuning problem at all: shortages subtracted absolute points from a meter that
  only eased 1% of its gap per turn, so every point of penalty cost 100 points
  of a 100-point meter. Medians went 1.13 → 44.83 (settlements) and
  0.47 → 10.54 (villages).
- **The balance lab has no economy section.** All 217 levers in
  `app/core/tuning.py` are battle-side, so every number in this rework is
  source-only and cannot be tuned live. Adding a `resources` section is cheap
  and would pay for itself immediately, given how much of §15 is tuning.

### 15.6 How to work on this

Same discipline the rest of the project runs on, and it earned its keep here:

- **Measure before and after with `dev/storage_audit.py`**, and A/B by
  disabling the new thing (`dev/labor_ab.py` is the template — it raises
  `LABOR_OUTPUT_PER_WORKER` so the limit never binds, rather than adding a
  flag).
- **Walk whole chains, not units.** All four coin faults were invisible in
  isolation; only "can a unit of ore get from the seam to the vault" found
  them. `dev/test_gold.py` is written that way deliberately.
- Run the full 18-script suite after every change. Everything currently
  passes; there are no known-failing tests to work around.

---

## 16. v0.4.0, "The Cartographer Update" — finishing the economy plan

Everything in §15 that was still outstanding, plus two Guild mechanics and
one real bug. All released together as v0.4.0, which also carries the whole
of §14 (which had been sitting unreleased on `master`).

### 16.1 Phase 2 — a real demand sink for durables

Only ~26% of durable production was consumed by anything; the rest piled up
and was thrown away. Added a pooled **Timber** need with two halves:

- **Population upkeep** (`TIMBER_UPKEEP_PER_CAPITA`) — roofs, handles,
  fences. Ordinary wear.
- **Building maintenance** (`BUILDING_MAINTENANCE_PER_TIER`) — every built
  tier costs upkeep per turn, which is what finally gives the build decision
  ongoing weight instead of being a one-off.

Drawn from `_TIMBER_SOURCES` (Planks/Hardwood/Softwood/Logs) as one pool, the
same way `_FOOD_SOURCES` works. It plugs into `settlement_needs`, so
consumption, the alert pipe and automatic redistribution all pick it up in
one move — that is the design note worth remembering for any future need.
A shortfall costs prosperity only, never population and never a building
tier (degrading tiers was considered and explicitly rejected as
irreversible-feeling).

Measured: durable throttle-loss ~22% to ~18%, durable mean fill ~0.39 to
~0.35, household/other/feed unmoved.

**Sized against wood only, deliberately.** Iron/Coal/Copper/Tin are
near-zero (see §15.5's mining finding) and a sink there would starve the
map. Verify with `dev/storage_audit.py` before adding a sink for anything
else.

### 16.2 Phase 3 — a stockpile lever, and the gold question

The user's own pushback reshaped this one and the reasoning is worth
keeping. The plan called for a "market sink" — sell surplus for gold. That
would have **created money from nothing**: gold only ever enters this
economy through minting (a finite, geography-gated resource) or moves from
another faction's treasury via real trade. Paying for surplus out of thin
air is pure inflation with no counterpart.

So the sink is not a sink at all. It is a **per-node, per-good stockpile
target** that widens or tightens how much a node holds back before local
logistics, regional trade or sell-to-city may carry the rest away — working
purely through the reserve every domestic tier already reads via
`_node_surplus`. No new goods, no new gold.

Scoped to ordinary discretionary goods only (`stockpile_eligible`).
Food/Firewood/Clothes/Luxury/Timber/Fodder keep their own tuned survival and
upkeep formulas, so a misclick can never starve a village — that property is
asserted directly in `dev/test_stockpile.py`. Reachable from the
settlement/village panel as a default-closed STOCKPILE card with five coarse
presets.

**Still unbuilt from §15.2:** supply-driven pricing (a city's price falling
as its stock rises). `unit_price`'s surplus factor already half does it.

### 16.3 Cartographer B and C — commissioned surveys

Mechanic A (shipped in §14.5) multiplies what your own traffic reports back
and deliberately never goes looking. B is the half that does: pay gold and
paper, and a `SurveyExpedition` walks out and charts a corridor. Same shape
as every other multi-turn project — precomputed path, per-turn advance hook
— and, **like Commanders, it exists for every faction while only revealing
fog for the player**; that split lives in `vision.recompute`, so nothing in
the world model has to know who is looking.

Two things measurement changed, both worth knowing:

- **It targets the FURTHEST reachable unexplored cell, not the nearest.**
  "Head for the frontier" reads as *nearest*, and that is wrong: fog begins
  at your own border, so the first version charged 60 gold to walk 8 cells
  to the end of the road. Aiming at the far edge of range makes it an actual
  expedition (~49 cells, ~1,600 revealed).
- **Loss chance compounds.** 0.02/turn sounded small and worked out to ~49%
  over a ~30-turn journey — a coin flip on a paid commission. 0.006 gives
  ~17%.

Mechanic C falls out of the same object: a coastal party moves faster and
commits to a longer route (further again with a shipyard). It also spends
fewer turns exposed, so **the coast is genuinely safer as well as quicker** —
unplanned, and exactly why real ages of discovery mapped coastlines decades
before interiors.

**One lifecycle bug caught and guarded:** `advance_surveys` runs BEFORE
`vision.recompute`, so dropping a finished party the same turn silently lost
the last stretch it charted. Finished parties now survive one turn and are
swept up on the next pass.

### 16.4 Phase 5 — waste, and one change that had to be reverted

**Read this one.** It is the clearest example in the project of a measured
improvement that was actually a regression.

`STORAGE_THROTTLE_FLOOR` went 0.0 to 0.15, so a node at capacity is throttled
rather than switched off entirely. Household throttle-loss ~4.1% to ~2.8%,
delivered production up ~3-4%, destruction flat. That part stands.

The investigation then found Fish + Smoked Fish were **~50% of everything
destroyed world-wide**, from two causes:

- **Fish was flagged inedible** — by analogy to Livestock needing
  slaughtering. But a live sheep is not food yet and a landed fish is, and
  historically curing made a catch *storable and tradeable*, not edible. It
  was also the exact bug already fixed once for raw Crops: a village has no
  smokehouse, so it could neither cure nor eat its own catch and watched it
  rot at 0.35. **This fix stands.** Note the food pool keys off *category*,
  not the bare `edible` flag — that flag means "consumed by mouth", which
  also covers Salt, Wine and Beer, and sweeping those in would let a village
  subsist on salt.
- **Settlements landed their full geographic catch every turn**, unthrottled,
  because they have no labour model. 1,210 Fish/turn from settlements alone
  against a world-wide food demand of 181/turn. Capping it halved fish
  destruction and total destruction fell ~30%.

**That cap was then reverted.** On a *developed* save it turned a 60-turn
population trend of -5.6% into **-18.5%**, and even a mild version still
cost -9.9%. It reduced waste by reducing supply — and that same supply was
quietly feeding people. Meanwhile the waste it "fixed" was costing nothing
real: fish rots because it spoils fast, not because storage is full, and the
pools were measured as non-binding.

Three lessons, all recorded next to the code so the audit numbers alone do
not tempt a repeat:

1. **Gross spoilage of an oversupplied good is a cosmetic metric.** Do not
   optimise it by cutting supply.
2. **Verify on a developed save, not just a fresh one.** The cap looked fine
   on a fresh world and only showed its cost on a turn-160 one.
3. **Pool sizing (§15.3's third item) was revisited and deliberately left
   alone.** Durable p90 had already fallen 0.91 to 0.76 and `other` reaches
   capacity in 0 of 20,121 sampled node-turns, so there was no binding
   constraint left to relieve, and giving durable more room would work
   against the Timber sink. Reasoning is next to `STORAGE_POOL_BASE`.

### 16.5 Wildland claims are colonisation now

Not on the §15 plan — raised directly by the user, who was right.

The old price (Gold + Logs + Stone) was not a difficulty setting, it was a
dead end: measured on a real save, **5 of 14 realms could not claim anything
at all** — four short of Stone, one short of Gold. Quarrying barely exists
for most realms (§15.5) and some worlds mint no gold whatsoever, so
expansion was priced in goods whole realms can never obtain.

A claim now costs **settlers drawn from the places nearest the new land,
plus food to provision them**, and nothing else. Neither can lock anyone
out — a realm with no people or no food is already finished — and it is what
taking new land actually cost historically (the Roman *colonia*, the Greek
*apoikia*, the Norse *landnam*, homesteading: you moved families and you
victualled them). Timber and stone are what you spend *building* once you
are there, which is what the BUILD menu is for.

It also bites where the old price did not: population **is** the workforce
(§14.1), so settlers come off the fields at home and expansion competes with
production instead of draining a pile nobody was using. No single node gives
up more than `CLAIM_SETTLER_DRAW_FRACTION` of its people, and none is ever
emptied below the floor a famine respects.

Measured: 0 of 14 realms blocked, the AI still expands (+9 regions in 60
turns), and a small realm gets a couple of claims before it must rebuild its
stores — a self-correcting brake rather than a wall. `claim_cost` returns
`{"Food": N}` and does **not** go through `construction.can_afford` /
`_pay_cost` (those look resources up by literal name; "Food" is a pooled
demand) — use `can_afford_claim` / `_pay_claim`.

### 16.6 The trade log bug

It was the only floating panel parented to `self.canvas` instead of the
MapView. That worked for exactly as long as the canvas was always on screen
— the GPU flat map replaces it (`_activate_flatgl` calls
`self.canvas.pack_forget()`), and an unmapped parent takes its children with
it, silently. The reopen tab was already on the MapView, so it stayed
perfectly clickable while the panel behind it could never appear.

Same family as the v0.3.8_7 z-order bug (§12). `dev/test_panels.py` now
asserts every floating panel hangs off the MapView and that the log still
opens with the canvas swapped out.

### 16.7 Numbers to judge in play, not in a simulator

Per the working note at the top: these are first-pass values, named here so
they can be tuned by feel rather than by another sweep.

| constant | file | now | if it feels wrong |
|---|---|---|---|
| `TIMBER_UPKEEP_PER_CAPITA` | resources.py | 0.016 | timber piling up again / everyone short of wood |
| `BUILDING_MAINTENANCE_PER_TIER` | resources.py | 0.8 | building feels free / feels punishing |
| `STORAGE_THROTTLE_FLOOR` | resources.py | 0.15 | full nodes idle / overflow returns |
| `CLAIM_SETTLERS_BASE` / `_PER_CELL` | expansion.py | 40 / 0.15 | expansion too cheap or too slow |
| `CLAIM_PROVISIONS_PER_SETTLER` | expansion.py | 3 | food is or isn't the real brake |
| `SEA_ONLY_SETTLERS_BASE` / `_PER_CELL` | expansion.py | 180 / 0.35 | amphibious claims too easy/impossible |
| `SURVEY_COST` | resources.py | 60 Gold, 5 Paper | surveys never worth it / always worth it |
| `SURVEY_LOSS_CHANCE_PER_TURN` | resources.py | 0.006 (~17%) | losses feel cheap or brutal |
| `SURVEY_MAX_RANGE` | resources.py | 60 cells | expeditions too short/long |
| `_VILLAGE_REVEAL_SPAN` | map_view.py | 26 | villages appear too early/late |

### 16.8 Regression suite

**22 scripts, all passing.** New in this batch: `test_timber_upkeep`,
`test_stockpile`, `test_spoilage`, `test_claim_cost`; `test_cartographer`
and `test_panels` were extended. The ones that take a world take it as
`argv[1]` (default `dev/worlds/dev560.pkl`; `dev160.pkl` is the faster one
and is what everything above was verified against).

---

## 17. Unreleased on `master`: the logistics chain, two UI bugs, the Mining Camp

Three commits after v0.4.0. The first is the important one and its lesson
generalises: **a stock level cannot tell you why something is missing.**

### 17.1 The domestic chain was severed in four places (`a781b95`)

§15.5 called mining the largest remaining economic hole and read it as a
supply problem. It is one (see §17.3), but sitting on top of it was something
larger and entirely separate: `Tools`, `Weapons`, `Shields`, `Bricks` and
`Cloth` all sat at **exactly zero world-wide**, and 16 of ~22 settlement
recipes were blocked on a zero input — while the raw materials existed in
quantity a few regions away. Four independent plumbing faults, each invisible
on its own, all found by walking a unit of ore from the seam to the workshop.

**1. Route discovery was starved by its own budget.**
`REGIONAL_PATH_BUDGET_PER_TURN` was `1`. On a fresh world at turn 120 — 340
villages, 32 settlements — only 120 village→city pairs had *ever* been looked
up, and every one of the 313 unsolved pairs had a perfectly good route the
moment the budget was refilled. The original reasoning ("a bigger number only
helps once at startup") had it backwards: a solved pair is cached **forever**,
so the cost is transient and the benefit permanent.

Now `4`, and that number is measured. On the turn-561 world:

| budget | 1 | 3 | 4 | 8 |
|---|---|---|---|---|
| ms/turn | 378 | 424 | **446** | 573 |

8 was tried first and costs **+52%** on a developed map — far more than a
fresh-world timing predicted, because searches there are much dearer than the
2.6 ms measured on a small one. 4 buys four times the discovery rate for +18%
and lands on the same ~424-446 ms this project has benchmarked before.

`LOCAL_PATH_BUDGET_PER_TURN` was deliberately **left alone**: a failed local
path falls back to a straight line and the shipment still delivers, so that
budget is cosmetic. Only the regional one blocks goods.

**2. Every node scanned the same order on the same turn.** `rotate_for_turn`
was keyed on the turn alone, so all 340 villages moved in lockstep and a good
only had a chance on the one turn its rotation brought it forward — and only
from nodes under their shipment cap right then. Now offset by the node's own
id. Still a pure function of `(turn, node)`, so determinism is untouched.

**3. Barely-perishable industrial inputs were classed as perishable.**
sell-to-city filtered on `spoil_rate <= 0` *exactly*, which excluded Cotton
(0.02), Wool (0.01), Paper (0.02) and Resin (0.02) alongside Milk (0.40).
Nothing else could move them either — they are not consumption goods so no
need-based tier wants them, and local logistics is region-locked. They fell
through every tier at once, which is why Cloth and Paper were zero. Now
`SELL_TO_CITY_MAX_SPOIL = 0.02`, with **foods excluded by category rather than
by rate**: a bean at 0.02 does not need this tier (regional trade already
moves 18,000 units of grain on need), a bale of cotton has nothing else.

**4. The dispatcher picked cargo by whose turn it was, not by what was needed.**
The clearest trace in the whole investigation: a village holding 128 spare
Clay dispatched a shipment **every single turn for 120 turns and never once
sent Clay**. A bulk good is *always* shippable, so with a dozen of them
scattered through the order one is always ahead; Clay's index crept down one
per turn from 23 while Hardwood, then Logs, then Softwood cycled into the low
slots, and its stock drained faster than the ~33 turns it needed to reach the
front. **Rotation alone cannot fix this** — that is the transferable lesson.

Cargo is now chosen by what the destination city is short of. City stock alone
was *not* enough: a working city consumes what arrives, so it holds zero of
nearly everything and almost every candidate ties at 0, collapsing the sort
straight back into the rotation. Realm-wide scarcity breaks the tie and
encodes the right instinct — a cart is a scarce slot, so spend it on the
scarce cargo. Timber is everywhere and will come anyway; the region's only
clay will not.

Measured, developed save, 120 turns:

| | before | after |
|---|---|---|
| Tools | 0 | 3,671 |
| Weapons | 0 | 502 |
| Shields | 0 | 214 |
| Bricks | 0 | 126 |
| Paper | 0 | 595 |
| Clothes | 0 | 1,345 |

Raw arrivals at settlements: Stone 6.6 → 75.5/turn, Sand 52 → 140/turn,
Cotton 0 → 223/turn. Iron dispatches 0 → 74 per 120 turns, Copper 0 → 88.

**Deliberately not chased further:** Clay never uses the sell-to-city tier
specifically (it reaches settlements via local logistics instead), and Cloth
is still zero because Wool has no producer worth the name.

### 17.2 Two reported UI bugs (`24180e6`)

**Folding cards did nothing on the region and faction panels.**
`_toggle_panel_card` only rebuilt for a selected Settlement or Village, so
elsewhere the card's open/shut state flipped and nothing was redrawn to show
it. `refresh()` already had a correct all-four-kinds sequence, so the two are
now one method (`_rebuild_selection_panel`) and cannot drift apart again —
which is exactly how they came to disagree.

**E and V worked inconsistently.** Both were bound with `bind` on the App
root. A root bind only fires while focus is inside the root's **own** widget
tree, and this game has real child `Toplevel`s: the Compendium, and the Build
Menu, which additionally takes focus for itself because it is undecorated.
Open either and E silently stopped ending turns. Now `bind_all`, with two
things that had to come with it: a guard so a letter typed into a text field
is a letter (`App._TEXT_ENTRY_CLASSES`), and the Build Menu handing focus back
to the game on close, since Windows does not reliably return it when an
`overrideredirect` window is destroyed.

`dev/test_keys.py` asserts the **wiring** (bind_all present, root bind absent
so nothing double-fires, typing guarded, still inert while paused) rather than
driving real keystrokes: which widget holds focus needs a window manager a
headless harness cannot promise, but *where* a binding lives is the thing that
was wrong and is directly inspectable.

`dev/test_panels.py` now folds a card on all four panel kinds, and caught a
subtlety worth keeping: the `_show_*` methods only **draw**, while `_on_click`
is what records the selection — so a test that only calls `_show_*` is testing
a state the game never actually reaches.

### 17.3 The Mining Camp (`4a6e061`)

§15.5's supply half. Villages are sited on farmland — correctly — while Iron,
Coal, Copper, Tin and Gold Ore spawn only on mountain, ~4.5% of the map. On a
fresh world, 4 of 303 villages had a single mountain cell in catchment, 57
cells in the whole world. Sand, Salt and Clay were fine throughout, which is
the tell: they spawn where villages actually get placed. Nothing was wrong
with the mining code — the ore was simply somewhere nobody lived.

A camp works mountain cells in its **region** that lie outside the village's
own catchment: you send people out to the seam and cart ore back, which is
what mining settlements historically were (Kutná Hora, Falun, Rammelsberg,
Potosí — founded on ore, in country that often could not feed them). Gating on
catchment, as the Gold Mine does, is precisely what left the tier unreachable.

Three properties keep it from being a free upgrade:

- **Dug by the village's own hands.** Cells are added to the terrain offer
  *before* the Phase 14 labour limit, so a camp competes with the harvest.
- **The seam is finite and shared.** A second camp in the same region splits
  it rather than doubling it, and the upper tiers deliberately exceed what a
  modest region can supply so the share cap starts to bind.
- **Ore only.** Cells enter the industry sample *after* crops are computed.
  (Borrowing the village's climate for remote cells is exact, not approximate:
  every Mining resource has `climate_affinity` 1.0 in all four climates.)

Tier 1 is priced in timber, stone and coin with **no Tools** — Tools are
smithed from Iron and this is the building that makes Iron exist, so pricing
it in Tools would gate the cure on the disease (the Preserving-House-and-Stone
trap, §16.4).

Sized against the seams that exist rather than a village's catchment: a first
pass at 14/28/45 cells was worth only +17% world Iron across 59 camps, which
is invisible for a paid multi-turn building. `MINING_CAMP_CELLS` is 25/55/90.
Measured with one tier-1 camp per mountainous region: Iron 57.2 → 71.7/turn,
Copper 28.6 → 35.9, Tin 11.5 → 14.3, Gold Ore 169 → 216.

**The §15.5 framing needed correcting.** dev160 already produces 57 Iron/turn;
the 0.35/turn figure was a *fresh* world where no mountain region had been
claimed yet. So it is not "mining is broken" but "ore is unavailable until you
go and take the mountains" — a fair thing for the game to ask. Reachability on
real saves is comfortable: dev160 has 59 mountain regions across all 10
factions and 129 of 380 villages eligible; dev560 has 137 and 281 of 609.

**One real pre-existing bug found by the new test, from Phase 14.**
`village_labor_factors` returned `{}` for a zero workforce, and
`compute_village_yield` reads a *missing* factor as "this resource has no
sector, so no labour limit applies" — so a village that had lost every adult
produced its **full terrain potential** and out-produced a populated one. It
now returns explicit zeros. It surfaced only because the camp's harness
asserted a plain-language property ("with no workforce, a mine produces
nothing") rather than checking a number; guarded in `dev/test_labor.py` too.

### 17.4 Numbers to judge in play

Same contract as §16.7 — first-pass values, named so they can be tuned by feel.

| constant | file | now | if it feels wrong |
|---|---|---|---|
| `REGIONAL_PATH_BUDGET_PER_TURN` | trade.py | 4 | goods slow to start moving on a new map / end turn feels heavy |
| `SELL_TO_CITY_MAX_SPOIL` | trade.py | 0.02 | perishables being carted pointlessly / an input still stranded |
| `MINING_CAMP_CELLS` | resources.py | 25/55/90 | camps trivial or dominant |
| `mining_camp` costs | construction.py | tier 1 = 200 Logs, 120 Stone, 160 Gold | first camp out of reach or free |

### 17.5 Regression suite

**25 scripts, all passing.** New here: `test_logistics_reach`,
`test_mining_camp`, `test_keys`; `test_labor` and `test_panels` extended. The
ones that take a world take it as `argv[1]` (default `dev/worlds/dev560.pkl`;
`dev160.pkl` is faster and is what §17 was verified against).

---

## 18. Prosperity, and the first phase of the biome overhaul

Two more unreleased commits on `master`, after §17.

### 18.1 Prosperity: a meter that could not move (`5d2bde9`)

Prosperity is a visible 0-100 bar on every settlement and village. It read a
median of **1.13** for settlements and **0.47** for villages, so it told the
player nothing. It sat on the open list for a long time looking like a tuning
problem. It was not — it was arithmetic, and this is the transferable part:

**Two mechanisms on incompatible scales.** `_update_prosperity` eases the meter
proportionally, `P += (target - P) * PROSPERITY_EASE` with ease `0.01`, i.e. 1%
of the remaining gap per turn. `_consume_node_needs` subtracted **absolute
points** for every unmet need — Food 8.0, Firewood 5.0, Clothes 2.0, Timber 2.0,
up to 17 a turn.

At equilibrium `(target - P) * 0.01 == penalty`, so `P` settles at
`target - 100 * penalty`. **Every single point of per-turn penalty cost 100
points of a 100-point meter.** A node missing 1% of its Clothes lost 2 points;
a node with no Clothes at all — which was every node in the game, since Clothes
were zero world-wide until §17.1 repaired the logistics chain — took the full
2.0 a turn and was pinned at zero however rich it was.

The targets had been fine the whole time. Settlement targets had a **median of
100.0** while the meters read 1.13.

**The fix:** shortages scale the TARGET instead of subtracting from the meter,
so one easing governs both directions and the halves cannot diverge again.
`PROSPERITY_SHORTAGE_WEIGHT` holds fractions — Food 1.0, Firewood 0.6, Clothes
0.25, Timber 0.25 — and `LUXURY_PROSPERITY_BONUS` (0.25) lifts it.

Combined **multiplicatively, not additively**: each shortage takes a share of
what is left. Summing was tried first and is wrong at the edges, because the
weights add to more than 1.0 — a node merely short of clothes, timber and
firewood hit exactly zero as though it were starving, and the clamp hid the
difference. Multiplying means only Food at a full deficit can reach zero, which
is the intended meaning: destitute when you cannot eat, merely poor when you are
cold and badly dressed.

**A second dead meter underneath.** Village prosperity was keyed to
`village.farm_output` — the decorative stat worldgen rolls at placement.
Measured: **0 of 380 villages saw it change across 120 turns.** A village had
exactly one possible target for the entire game and nothing the player did could
move it: the same "meter that cannot move" defect, one layer down. Villages are
now valued on what they actually deliver, EMA-smoothed (`VILLAGE_OUTPUT_EMA`)
because a crop only harvests in its own season and an unsmoothed figure would
send every farming village to zero for half of every year. Old saves fall back
to `farm_output` until a village's first delivery, so no existing game drops to
zero on load.

Measured, 120 turns on the developed save:

| | before | after |
|---|---|---|
| settlement prosperity (median) | 1.13 | **44.83** |
| village prosperity (median) | 0.47 | **10.54** |
| city prosperity (median) | 1.30 | **70.39** |
| village prosperity (p90) | 0.71 | **36.44** |

`dev/test_prosperity.py`'s sharpest assertion is structural and worth keeping:
**nothing may write to `node.prosperity` except the easing** (and the
city-growth reset). Anything else fights it on a different scale and wins, which
is exactly how this broke. `dev/test_timber_upkeep.py`'s prosperity assertion was
correct for the old mechanism and now checks the new one. Compendium prose
updated — it prints these constants and described the old behaviour.

**Left open deliberately:** `_faction_health_factor` is pinned at its 0.5 floor
55% of the time, halving every target, because production value runs under half
of consumption value for most factions most turns. That is a separate question
about how those two are measured, not a prosperity bug.

### 18.2 Biomes A: a real temperature x moisture matrix (`23b14a2`)

First phase of the overhaul in §19. Biomes came from a threshold cascade that
**never saw temperature** — only `classify_climate` did — so the same moisture
produced the same biome at the equator and at the pole, and latitude meant
nothing a player could see or plan around.

They now come from a temperature x moisture matrix (`_BIOME_MATRIX`), the shape
a Whittaker diagram describes. Relief and water proximity stay as **overrides**
on top, because the landform beats the weather: you cannot farm a cliff however
much rain falls on it. `classify_biome` takes a `temperature` argument now
(defaulted, so any older caller still works); worldgen passes the latitude
gradient it already computed for climate.

**6 biomes to 12.** New: `highland`, `taiga`, `jungle`, `steppe`, `savannah`,
`tundra`. Highland matters most — foothills that are ore-bearing but still
farmable, which is what makes a mountain range habitable rather than a wall, and
it is where Dwarves are meant to live.

**All six original names survive, and that is load-bearing rather than
conservative.** `biome_grid` and `region.biome_counts` are computed at worldgen
and **pickled**, so every dev world and player save already holds those strings;
renaming one silently orphans a region's whole biome profile. The whole suite
runs against pickled turn-161 and turn-561 worlds and passes unchanged, which is
the real proof old saves still load.

**No biome is good at everything**, asserted directly in `dev/test_biomes.py`.
This is the fairness mechanism the whole overhaul rests on — terrain asymmetric
in KIND, not in quality, so every realm needs something its neighbours have.
Highland failed this on the first pass (7 food crops AND 7 ores made a dwarf
homeland simply better rather than shaped) and now keeps only hardy upland
grains and rough-grazing animals:

    plains     10 food,  5 herd,  0 wood,  0 ore   breadbasket, no materials
    highland    2 food,  2 herd,  0 wood,  7 ore   ore country, thin food
    forest      0 food,  2 herd,  5 wood,  0 ore   timber, no grain
    savannah    2 food,  4 herd,  0 wood,  0 ore   grazing
    tundra      0 food,  2 herd,  0 wood,  1 ore   marginal everywhere

Latitude is legible now: poles read tundra, equator jungle, temperate belts
between. All 12 appear on a generated world, none covers more than 20%, and the
economy holds — population and starvation land in the same band as before.

**One thing that will mislead you:** an overview render of the biome map looks
badly speckled and is NOT. That is a downsampling artifact from sampling every
third cell. At 1:1 the biomes form large coherent patches. Do not "fix" it —
check a 1:1 crop first. This matters because §19's naming layer wants "the
Everwood" to be a place rather than scattered pixels.

---

## 19. THE BIOME OVERHAUL — the live thread

**The overhaul is complete.** Phases A (§18.2), B (§20), F (§21), C (§22),
D (§23) and E (§24) have all shipped. Sections 19.0–19.6 are kept as the
record of what was agreed and why — read them before changing any of it.
The user chose the design on every axis already, so these are decisions to
implement, not to re-open.

### 19.0 What was agreed

- **Spawn binding: strong preference.** Species affinity is a heavy term in
  start-site scoring — Elves nearly always begin in forest, Dwarves in
  highland/mountain — but a map that cannot supply one falls back gracefully
  rather than failing. Not a hard guarantee (which would distort worldgen and
  make every opening feel the same), not a soft nudge (which you would never
  notice).
- **Mechanics chosen:** native-terrain aptitude + acclimatisation,
  biome-gated buildings, and terrain in movement/battle.
- **Scope: full rebuild** of the biome system, which phase A delivered.
- **Fantasy biomes are flavour only** — a named skin over a mechanical biome,
  never a different or better resource profile. That was explicit.

The user did **not** pick "asymmetric homeland resource profiles" as a separate
mechanic. It was folded into phase A as a hard constraint of the matrix instead
(no biome good at all four categories, asserted in the harness), which delivers
the same fairness without a separate feature. Say so if it comes up.

### 19.1 Phase B — species homeland affinity — **DONE, see §20**

The actual original ask, and nothing about species touches placement today:
`_site_score` (worldgen.py) weighs fertility, rivers, coast, borders and
elevation — **there is no biome term and no species term anywhere in it.** An
Elf realm is as likely to start in a desert as a Human one.

- Add a species -> biome affinity table (Elves forest/taiga, Dwarves
  highland/mountain, Orcs savannah/steppe/plains, Goblins swamp/jungle/tundra,
  Humans broad — their trait is literally "adaptable realm-builders").
- Add a heavy affinity term to start-site scoring.
- **Guarantee every faction a viable homeland that can feed itself.** This is
  the fairness risk: a species whose biome is rare on a given map, or whose
  homeland cannot grow food, is crippled from turn one. Coastal and desert both
  produce zero crops (coastal has fishing, which is not in `RESOURCE_SPAWN` —
  it comes from `_node_fish_yield`), so check for that specifically.
- `_place_settlements_for_faction` already reads
  `world.factions[fac_idx].meta["species"]` and does nothing with it.

### 19.2 Phase C — native-terrain aptitude — **DONE, see §22**

A species works its own biomes better (~+15% labour) and alien ones worse, with
the penalty eroding as it holds the land. Rides the Phase 14 labour system —
apply it in `_village_terrain_potential` alongside the Mining Camp's cells, so
it flows through `village_labor_factors` and competes for hands like everything
else. Needs a per-node or per-region acclimatisation counter that pickles.

The acclimatisation half is the fairness valve: without it, a realm that
conquers alien terrain is permanently worse at it, which compounds badly.

### 19.3 Phase D — biome-gated buildings — **DONE, see §23**

One terrain-flavoured building per biome family, in the existing build menu
(`app/world/buildings.py` + `construction.py` cost tables — the Mining Camp in
§17.3 is the template, including its region-level gate). **Highest unfairness
risk of the chosen mechanics:** each must be genuinely equivalent in value, and
that is hard to verify. Consider making them all variations on one effect.

### 19.4 Phase E — terrain in movement and battle — **DONE, see §24**

Swamp slows armies, highland favours defenders, jungle hides them. Touches
commander movement (`worldgen._elev_cost` already does some terrain) and the
battle sim. Biggest build of the set and furthest from the economy work.

### 19.5 Phase F — the fantasy naming layer — **DONE, see §21**

Named variants over each mechanical biome — Everwood/Thornwild over `forest`,
Ashwaste over `desert`, Mistfen over `swamp` — chosen at worldgen from climate
and region. Pure naming, colour tint and region-name flavour, **zero balance
effect by construction**, which is the whole point of separating it from the
mechanical layer.

Cheap, zero risk, and it is what makes the world feel like a place. The user was
offered it before B and chose to be asked; it is a reasonable thing to do first
if they want to see the new world before more mechanics land on it.

### 19.6 Numbers to judge in play

| constant | file | now | if it feels wrong |
|---|---|---|---|
| `_BIOME_MATRIX` | resources.py | 4x4 grid | a biome is too rare or too common |
| `_TEMP_BANDS` | resources.py | 0.30/0.62/0.82 | polar or equatorial bands too wide/narrow |
| `_MOISTURE_BANDS` | resources.py | 0.30/0.48/0.68 | too much desert or too much jungle |
| `_HIGHLAND_RELIEF` | resources.py | 0.38 | mountains too walled off or too farmable |
| `PROSPERITY_SHORTAGE_WEIGHT` | resources.py | 1.0/0.6/0.25/0.25 | shortages too punishing or too weak |
| `VILLAGE_OUTPUT_VALUE_SCALE` | resources.py | 2.0 | village meters sit too low or max out |
| `TERRAIN_MOVE_COST` | commander.py | 1.0..2.2 | armies crawl, or terrain never matters |
| `ROAD_MOVE_COST` | commander.py | 0.6 | roads are a must-build, or not worth it |
| `BATTLE_TERRAIN` | battle/battle.py | see §24 | a biome decides fights instead of colouring them |

On a generated world the current matrix gives: forest 19%, savannah 13%, jungle
12%, highland 11%, taiga 10%, plains 9%, tundra 8%, coastal 8%, mountain 4.5%,
steppe 2.2%, desert 2.2%, swamp 0.8%. Steppe, desert and swamp are thin — if a
species homeland is placed on one of those, check it can actually support a
realm before shipping.

---

## 20. Biome phase B — species homelands (SHIPPED)

Phase B of §19. Elves open in forest, Dwarves in mountain and highland, Orcs
in savannah, Goblins in jungle and swamp.

### 20.1 The design choice that matters

`_site_score` weighs fertility, rivers, coast, borders and elevation, and
there is still **no species term in it** — because the affinity was not added
there. Capitals are placed exactly as before, and then **handed out to match
the species roster** (`worldgen._order_capitals_by_affinity`), which is a
reorder of an already-validated list.

That is deliberate and it is what makes the fairness requirement in §19.1 free
rather than hard:

- Every capital in the list already passed the spacing and the farmland check
  (`_capital_has_nearby_farmland`), so **no realm can be moved somewhere it
  cannot live** — the reorder cannot invent a site or drop one.
- It **cannot fail** on a map with no forest. A species whose homeland is
  absent simply gets its next-best country. That is the graceful fallback the
  design asked for, not a hard guarantee.
- The player (roster slot 0) is served first at their own best homeland, then
  the rest are matched globally best-first. A single-player game should not
  open with the player in a swamp because the assignment maths preferred it
  overall.

The table is `lexicon.SPECIES_BIOME_AFFINITY` — weights, not a flat set, so a
Dwarf prefers real mountains but will take highland. Humans are deliberately
broad and shallow (their trait is literally "adaptable realm-builders"), which
also makes them the species most willing to be displaced when someone else's
homeland is scarce.

**One structural consequence worth knowing:** the species roster is now rolled
in step 5b of `generate_world`, before regions are generated, because the
capitals have to be handed out to match it and biomes only exist from step 5.
It is no longer rolled inside the faction loop. That shifts RNG consumption, so
**the same seed builds a different world than before this change** — expected,
but it is what broke the two tests below.

### 20.2 Measured

| | random pairing | matched |
|---|---|---|
| seed 7 mean affinity | 0.192 | **0.526** |
| seed 42 mean affinity | 0.260 | **0.556** |

Every species' single best available homeland goes to that species
(asserted in `dev/test_homeland.py`). 40 turns on a generated world: no realm
eliminated, none halved.

### 20.3 Two suite failures, neither a regression in the feature

Both were tests pinned to incidental properties of one seed's map, which moved
because the roster roll shifted RNG. Worth reading as a pattern — anything that
generates a world and then assumes something specific about the result is
fragile in exactly this way.

- **`test_weather_economy`** demanded a village from faction 0 specifically.
  Weather is not a per-faction mechanic; it now takes a village from any owned
  region.
- **`test_sea_bridge`** picked the *first* unclaimed region on another
  landmass. On the new map that one is inland (no dock) and far away (outside
  `_SEA_LANE_BBOX_PAD`), so no sea route existed to find and the scenario the
  test exists for quietly stopped happening — it passed by skipping. It now
  picks the **nearest** landmass with a dockable cell, which is what the
  original bug report was actually about, and the full sea-lane assertions run
  again.

### 20.4 A real pre-existing bug found on the way

**A starting foothold can end up with zero villages**, including the player's.
`STARTING_VILLAGE_COUNT` is meant to floor the home region at 3, but
`_place_villages_for_region` pops a candidate and `continue`s when
`_too_close_any` rejects it for spacing — the floor stops the viability
`break`, it does not stop the candidate list being exhausted by spacing
conflicts. A faction with no villages produces nothing at all under the
per-village economy.

Measured across 8 seeds x 4 factions: **3 of 32 before this change, 1 of 32
after** (the reorder tends to land species on better-shaped land), so phase B
improves it — but it does not fix it and it is not the fix. Worth doing
properly: either retry with relaxed spacing once the floor is unmet, or place
the floor villages first and let spacing apply only above it.

### 20.5 Numbers to judge in play

| constant | file | now | if it feels wrong |
|---|---|---|---|
| `SPECIES_BIOME_AFFINITY` | lexicon.py | per-species weights | a species keeps opening somewhere that feels wrong for it |
| `_HOMELAND_RADIUS` | worldgen.py | 8 (= the farmland check's own) | homelands judged on too much or too little surrounding land |

A caveat to state plainly if it comes up: **changing species on the New Game
screen does not move your capital.** Identity patching is deliberately not
world-shaping (§8) — it runs in ~0.1ms so browsing species stays instant — and
the homeland was chosen for whichever species the world was generated with.
Rerolling gives a homeland matched to the current pick. Fixing that properly
means regenerating on species change, which is the exact thing §8 exists to
avoid.

---

## 21. Biome phase F — the naming layer, and a voice for Humans (SHIPPED)

### 21.1 Named country over mechanical biome

`Region.flavour_name` gives every region a name for the kind of country it is
— the Everwood rather than "forest", the Ashwaste rather than "desert" — keyed
by dominant biome and the region's dominant climate, so the same forest reads
as the Hollowpine in the frozen north and the Everwood on a warm coast. The
table is `lexicon.BIOME_FLAVOUR_NAMES`; 12 biomes, each with a climate
fallback.

**Flavour only, and it is enforced rather than intended.**
`dev/test_biome_names.py` asserts that not one economy module (resources,
trade, construction, expansion, buildings) so much as *mentions* the naming
layer, and that two regions of the same biome are mechanically identical
whatever they are called. A naming layer that quietly acquired a mechanical
effect would be the worst outcome of the whole overhaul, because it would make
terrain unfair in a way no player could see.

It is a **derived property, not a stored field** — nothing added to the
pickle, so every existing save is named the moment it loads with no migration,
and being derived it cannot drift from the biome underneath it. Verified
against a pre-phase-F save: all 1,451 regions named.

### 21.2 Humans got a naming convention of their own

They were the generic-medieval default (Karnhaven, Brenstead, Aldric the
Bold), which left the one species with no homeland of its own also the one
with no voice of its own. They now draw on the naming **conventions** of
Sanderson's Stormlight Archive at the user's request: storm-shaped descriptive
compounds, oath and highland vocabulary, th/kh/sh/l/n phonetics, and the
fondness for symmetry (Nomon, Tevet, Kanak, Halah all read the same both
ways). Realms read as the Leeward Reach and Highstone Oathhold, cities as
Stormspire and Thalseat, rulers as Queen Dalneth Stormcalled.

**Every name is original.** Not one proper noun of his is reused — that is the
whole point of borrowing a convention rather than a name, and it is worth
keeping that line if the other species are ever given the same treatment.

Also: the shared settlement namer now collapses a letter doubled across the
root/suffix seam, so "Sasas" + "shelter" reads Sasashelter rather than
Sasasshelter. Every species benefits; only the join is touched.

---

## 22. Biome phase C — terrain aptitude and acclimatisation (SHIPPED)

A people works its own country better. `terrain_aptitude` runs 0.85 on wholly
alien ground up to 1.15 on wholly native.

### 22.1 It reuses phase B's homelands on purpose

It scores off `SPECIES_BIOME_AFFINITY` rather than a second table, and that is
a design decision rather than a shortcut: **the land you come from IS the land
you are good at**, and a separate table would be free to drift away from where
the species actually spawns. `worldgen.homeland_affinity` already answers "how
much is this my country" from a biome mix — phase C asks it of a village's
catchment instead of a candidate capital's surroundings. The test asserts that
coupling directly, so it cannot quietly be replaced with a parallel table.

### 22.2 Where it applies, and why there

Inside `_village_terrain_potential`, on what the **land offers**, beside the
Mining Camp's extra cells and the Gold Mine's multiplier — so it flows through
`village_labor_factors` and competes for hands like everything else, rather
than being free output bolted on at the end. Fishing is deliberately excluded:
the catch comes off the water, not out of the ground.

### 22.3 Acclimatisation is the fairness valve

`ACCLIMATISATION_TURNS = 120` of unbroken tenure erodes the alien penalty to
nothing. Without it, a realm that conquers alien terrain is permanently worse
at it than the neighbour it took it from, which compounds every turn and makes
expanding into unlike country a trap rather than a choice.

Two properties worth not breaking, both asserted:

- It erodes the **penalty only** and stops at 1.0. Living somewhere long
  enough stops the ground fighting you; it does not make you native to it.
- It tracks **which species** has been living there (`acclim_species`), so
  taking a people's fields does not hand you their generations of learning
  them. Same species, unbroken tenure → the counter keeps climbing.

Note a village at, say, 1.09 still improves with acclimatisation — a mixed
catchment has an alien share in it and learning that share is the mechanic
working, not a bug. Only a *wholly* native catchment has nothing to learn.

### 22.4 Measured

Economically neutral in aggregate over 60 turns: **-6.4% population with it
against -6.2% without, 84 starving against 87.** That is the right shape — it
redistributes advantage between realms rather than inflating or deflating the
economy.

Counters are read through `getattr`, so a pre-phase-C save needs no migration;
it simply starts learning.

### 22.5 Numbers to judge in play

| constant | file | now | if it feels wrong |
|---|---|---|---|
| `TERRAIN_APTITUDE_BONUS` | resources.py | 0.15 | homelands feel too strong or pointless |
| `TERRAIN_APTITUDE_PENALTY` | resources.py | 0.15 | expanding into alien land feels free or brutal |
| `ACCLIMATISATION_TURNS` | resources.py | 120 | conquered land settles in too fast or never |
| `SPECIES_BIOME_AFFINITY` | lexicon.py | per-species | now drives BOTH spawn and aptitude — changing it moves both |

**One coupling to know before touching that last row:** `SPECIES_BIOME_AFFINITY`
is now load-bearing twice over. Editing it changes where a species spawns
(phase B) *and* what it is good at (phase C), which is intended — but it means
a tweak meant to fix spawn placement will silently move the economy too.

---

## 23. Biome phase D — one terrain building, four kinds of country (SHIPPED)

Phase D of §19. The risk §19.3 names is real: twelve bespoke buildings cannot
be verified equal in value, and getting it wrong quietly makes some homelands
better — which undoes the "asymmetric in KIND, not quality" principle the whole
overhaul rests on.

**So they are not twelve effects. They are one effect with a biome argument.**
The Mining Camp (§17.3) already had the right shape and nobody had noticed it
was a general mechanic: it is not "+X% ore", it is REACH — working cells of a
given kind that lie in your REGION but outside your own catchment. Every biome
family now gets exactly that from the same code path: same reach table, same
cost, same build time, same tiers, same share-splitting, same application
*before* the labour limit. Fair by construction rather than by balancing,
because there is no cross-biome comparison left to get wrong.

`OUTSTATIONS` in `resources.py:4267` is the whole table. Four families cover all
twelve biomes with no overlap and no orphan:

| family | biomes |
|---|---|
| Mining Camp | mountain |
| Woodcutters' Camp | forest, taiga, jungle |
| Grange | plains, steppe, savannah |
| Workings | highland, desert, coastal, tundra, swamp |

The Mining Camp is deliberately left alone rather than widened — it is shipped
and its numbers were measured against mountain alone.

Measured at one tier-1 camp per region per family: Iron and Coal +13%, Barley
+20%, Salt +16% — and **timber DOWN 4%**, which is the mechanic working. Hands
moved to newly reachable ore and farmland, so a camp is a genuine trade rather
than free output. That is the number to watch if outstations ever feel like a
no-brainer.

Two bugs found on the way, both worth knowing because both are easy to
reintroduce:

* **Fractional stock.** Building maintenance is a fractional per-tier figure
  and the Timber need was never rounded, so `_consume_from_pool` subtracted a
  float and stockpiles became `109913.4` — the resource bar was rendering
  `44.20000000000000045`. Rounded at source. `test_timber_upkeep.py` now
  asserts a full turn leaves every stock whole; `_fmt_amount` is a display
  backstop, not the fix.
* **Verdict scale.** `_outstation_verdict` returned a raw cell count as its
  score while every other verdict returns a 0..1 fraction, so an outstation
  outranked a granary that was 100% full and turning production away — purely
  because 182 > 1.0. Normalised. The Mining Camp had the same latent bug and
  only escaped notice because it is offered in far fewer regions. **Any new
  verdict must return 0..1.**

`dev/test_outstation.py` covers it.

---

## 24. Biome phase E — terrain in movement and in battle (SHIPPED)

Phase E of §19, built in two halves.

### 24.1 The march

`COMMANDER_CELLS_PER_TURN` was a flat count regardless of what was underfoot.
It is a **budget** now (`commander.py:31`), and every cell of path spends its
own terrain's share via `cell_move_cost` / `_advance_along_path`: plains 5 cells
a turn, forest 3, swamp and mountain 2.

The road half is the part that changes decisions. `ROAD_MOVE_COST = 0.6` beats
the easiest open country's 1.0, so a column on its own network covers 8 cells a
turn against 5 across open plains and 2 through a marsh. Rome built roads
precisely because moving off one cost so much more, and this finally gives the
network a military value it never had when it only carried trade.

Distinct from `worldgen._elev_cost`, which shapes which way a path is *drawn*.
A route can reasonably run through hills because going round would be longer;
this is what crossing them then costs.

Two guards worth keeping: a column always advances **at least one cell**, so a
commander ordered across a mountain is slowed rather than stranded, and the sea
branch keeps its flat count because there is no terrain out there.
`dev/test_march.py` asserts both.

### 24.2 The battle

The battle sim had **no terrain hooks of any kind** — a fight in a marsh
resolved exactly like one on open plains, which made the new map read as
decoration the moment an army arrived. `BATTLE_TERRAIN` in
`app/battle/battle.py` gives every biome three multipliers:

| | speed | defender hp | archer reach |
|---|---|---|---|
| swamp | 0.75 | — | 0.85 |
| mountain | 0.75 | 1.20 | — |
| jungle | 0.80 | 1.05 | 0.70 |
| forest | 0.90 | 1.05 | 0.75 |
| highland | 0.90 | 1.15 | — |
| taiga | 0.90 | 1.05 | 0.85 |
| tundra, desert | 0.95 | — | — |
| plains, steppe, savannah, coastal | neutral | | |

Four decisions that a future agent should not undo without reading this:

* **Reach, not damage, for cover.** Cover is about not being able to see what
  you are shooting at. Jungle archers keep their punch but must come close
  enough to be charged, which changes how a wood is fought. Weakening their
  damage instead would read as arrows bouncing off trees — a bug, not a
  mechanic.
* **Applied at deploy, never per tick.** Terrain cannot change mid-battle and
  the sim runs to a 16.7ms frame budget (see
  `battle_view._EQUIPMENT_DETAIL_MAX_UNITS`). `Battle.set_terrain` stores the
  profile, `_apply_terrain` bakes it into each unit as it spawns.
  `dev/test_battle_terrain.py` asserts `Battle.update` never mentions terrain.
* **The defender bonus reaches side 1 only.** `DEFENDER_SIDE = 1`; `stage_battle`
  deploys the attacker as 0 and both real defenders and wildland garrisons as 1.
  An even-handed high-ground bonus is not a high-ground bonus. This also means
  claiming a mountain wildland is now genuinely harder than claiming a plain,
  which is consistent with the settler-cost model in §16.5.
* **Unknown or unset terrain is neutral.** A headless sim or an old save that
  names no biome fights exactly as it always did.

One structural change in `app/ui/app.py`: `stage_battle` now resolves `region`
**before** deploying, because the ground has to be known at spawn time. It used
to be worked out afterwards, when nothing downstream cared. The battle banner
carries `terrain_note(biome)` — a modifier the player cannot see is not a
modifier.

Sized to colour a battle, not decide one, and `test_battle_terrain.py` asserts
every multiplier stays inside that band (speed ≥ 0.70, defender ≤ 1.25, ranged
≥ 0.65) so a future tweak past it is a deliberate balance decision. **Judge in
play:** the 1.20x mountain defender is the one most likely to feel wrong in
either direction, and an archer-heavy species fighting in jungle is the matchup
to watch.

---

## 25. Roads — three reworks, and one idea worth reusing

Roads changed more than anything else this session, across three reports that
turned out to be one subject.

### 25.1 They are drawn as routes, not segments

Roads are STORED as endpoint pairs (`world.roads_by_region`), and a region's
list mixes single-cell steps from local paths with thirty-cell straight links
from worldgen's MST. Drawn one segment at a time — which is how it was drawn
until now — that gives exactly the ruler-straight runs meeting at hard elbows
that got reported with a screenshot.

You cannot smooth a line you are drawing two points at a time, so:

- `worldgen.road_chains(world)` joins the loose segments into connected runs,
  one per tier, breaking at real ends and real junctions. 2,982 segments
  become 351 runs on a developed save, nothing lost. Cached on the same
  segment-count signature `road_cells` uses.
- `MapView._road_points` resamples a run evenly, offsets each point by a
  small amount **hashed from the CELL**, and smooths with a **centripetal**
  Catmull-Rom.
- Both renderers draw runs.

Three things there are load-bearing and easy to undo by accident:

* **The offset is hashed from the cell, not the run.** Every road meeting at
  a junction must be displaced identically or the arms come apart.
* **Centripetal, not uniform.** Uniform Catmull-Rom overshoots on tight turns
  and a road network is full of them; one three-point dirt track that doubled
  back swung six and a half cells clear of its own route.
* **Both ends are pinned**, so a road still meets the place it serves.

Measured: the drawn road strays a mean of 0.16 cells from its real route for
stone and 0.39 for dirt, worst 0.72. `dev/test_road_geometry.py` holds that
under one cell, because character is the point and a road drawn through
country it does not pass near is a bug.

### 25.2 Cut into the ground, and the close-zoom lag

Every road is drawn TWICE: a darker, wider band (the cutting, the churned
verge) and the surface sitting inside it. A dirt track's surface runs broken
and narrower so the ground shows through in patches; a stone road runs solid
and fills its cut. `_ROAD_CUT_DARKEN`, `_ROAD_CUT_WIDTH`,
`_DIRT_SURFACE_DASH`, `_DIRT_SURFACE_NARROW`.

The reported close-zoom lag was **self-inflicted by 25.1**: one spline control
point per cell took a developed realm from 5,964 drawn points to 15,786. That
density only ever existed to stop *uniform* Catmull-Rom overshooting, and the
spline became centripetal two commits later, so it had been buying nothing
since. Halved to a point every two cells: 7,938 points, accuracy unchanged.

**If road drawing ever feels heavy again, look at `_ROAD_DENSIFY` and
`_ROAD_SUBDIV` first.**

### 25.3 The relative neighbourhood graph — reusable

Two separate reports ("so many roads overlaying on top of one another", and
"roads should branch out from cities, villages and towns naturally") have the
same answer, and it is worth knowing by name.

A link A-B is dropped when some third node C is closer to BOTH ends than they
are to each other — because the road already goes there via C, and building
A-B as well buys a shortcut nobody needs. That is the **relative
neighbourhood graph**, and it is the rule that makes a network BRANCH, with
roads meeting at the places between things instead of every pair getting its
own private track.

Applied in two places:

- `resources._connect_new_village_to_region` — village mesh. 36 links become
  26 on a 12-village cluster.
- `construction._find_road_routes` — settlements. Replaces
  `_find_road_path`, which returned exactly ONE road to the nearest
  settlement and therefore built a CHAIN: every new town hanging off one
  older town, a city with three towns around it connected to one. Re-routing
  all 42 settlements on a developed save: 42 stone roads become 56, mean 1.33
  each, never more than 2.

`_find_road_routes` returns routes best-first; **the first entry keeps the old
meaning exactly** — it is the one the settlement's construction waits on, and
the sea-lane fallback is still all-or-nothing so an island city gets a lane
and never a land branch alongside it.

### 25.4 Stone over dirt

`worldgen.add_road_segments` is now the single entry point for adding road
segments (all four call sites go through it). A higher tier replaces a lower
one on the same ground rather than leaving both in the list forever, and a
lower tier laid along an existing higher one adds nothing. Sea lanes are rank
0 and neither displace nor are displaced — a lane and a road can share a
port's cell. Both renderers also paint dirt first and the trunk network over
it, so a junction always reads as stone.

---

## 26. Archers — changed, still unresolved, and the reason matters

An archer-heavy army won **100%** of clear-weather fights against foot. That
is not a strong choice, it is the only choice.

Now at accuracy 0.60 (from 0.80) and damage 5.5 (from 6). But the measurements
are more useful than the values, because **both numbers sit on cliffs rather
than slopes**, n=36 per point, archers against foot in clear weather:

| accuracy | 0.80 | 0.65 | 0.60 | 0.55 |
|---|---|---|---|---|
| clear-weather wins | 100% | 97% | 92% | 72% |

| damage | 6.0 | 5.5 | 5.0 |
|---|---|---|---|
| clear-weather wins | 69% | 62% | 19% |

**Range is not a lever at all.** At 130 instead of 180 they still won 100% of
clear-weather fights. That is the finding worth carrying: whatever makes
massed bows dominant is not how far they shoot, and every output-side lever
tried so far collapses their BAD-weather record long before it dents the
clear-weather one. The untested hypothesis is that foot simply has no answer
to being shot — no shield mechanic covers the approach — which would make this
a missing mechanic rather than a wrong number.

**Everything here compounds.** Unit accuracy, unit damage and the weather
multipliers all multiply into the same shot. Dropping accuracy 0.80 → 0.60
took a severe storm from "archers win 72%" to "archers win 0%" with nothing
in `battle.py` changing. `BATTLE_WEATHER`'s accuracy figures were raised to
compensate and carry a comment saying so. **If archer accuracy or damage
moves again, those move with it.**

The tournament in `dev/test_battle_weather.py` now RECORDS win rates instead
of asserting on them, and runs 4 battles a condition instead of 10 — ten
battles measured 30% and then 10% for the same configuration on consecutive
runs.

---

## 27. Weather phase 2 — a live travel rate (`app/world/travel.py`)

Nothing about travel varied turn to turn: every caravan, regional shipment
and local wagon did a flat `turn_progress += 1`, so a route's length was
settled at dispatch. That is why the phasing put "build the live rate" before
"hang weather on it" — there was nothing to hook into.

Two terms, deliberately different in kind:

**Terrain is MEAN-NEUTRAL over a route, by construction.** This matters more
than it sounds. Measured on a developed save, real trade routes average a pace
of 0.65 against open country's 1.00, because they run on roads. A naive
terrain rate would have made every caravan ~50% faster overnight and silently
re-tuned the whole economy. Dividing each cell's cost by the route's OWN
average (`route_pace`, cached on the convoy) means the fast and slow stretches
cancel: a wagon visibly runs ahead on the road and falls behind in the hills,
and still arrives on the turn `trade.py` costed it for. Measured with weather
off across 170 in-flight convoys: mean drift +0.04 turns, every route within
one turn.

**Weather is the only thing that actually delays anyone.** On routes long
enough not to be dominated by rounding: storm 1.39x/1.87x, blizzard
1.59x/2.55x, fog 1.24x/1.50x. **Drought is 1.0 on purpose** — dry ground is
good for a wagon, and four kinds of weather that are all simply bad are one
kind of weather with four names. This also gave Fog its first job; it is
generated in every climate and has no crop effect by design.

A delayed caravan spends more turns exposed to the per-turn raid roll, so bad
weather costs goods as well as time without a separate rule. `MIN_TRAVEL_RATE`
(0.25) bounds the worst journey at 4x.

**Known limit, documented in the module:** weather is simulated only for owned
regions, so open ocean and unclaimed wildland are always clear. A sea storm
would need weather over water, which does not exist.

**A bug worth remembering:** `weather.KINDS` are lowercase constants
(`"storm"`), and the first rate table was keyed `"Storm"` — the entire weather
hook was silently dead. Key off the module's own constants; the test asserts
the two sets match.

---

## 28. Weather phase 3 — weather in battle

Same hook as biome terrain (phase E, §24): baked into each unit at deploy,
never read per tick, and it STACKS with terrain rather than replacing it.

**The one line that matters:** terrain is ASYMMETRIC (high ground favours
whoever holds it — that is the point of high ground); weather is SYMMETRIC
(rain falls on both armies). A storm that helped the defender would be a
second high-ground bonus wearing a cloud. A test asserts both sides come out
of a storm identical.

Three levers, and reach and accuracy are deliberately separate questions:
`speed` (mud, snow), `ranged` (how far a bowman can SEE — reach, not damage),
`accuracy` (whether the shot lands once taken, which fog does not answer and a
wet string does). Mild is exactly half of severe rather than a second table.

`BATTLE_WEATHER` accuracy figures are coupled to unit stats — see §26.

---

## 29. Weather phase 4 — the map overlay (v0.9.0)

Weather is per-region and changes every turn, which rules out the obvious
implementation: the terrain raster is cached and only rebuilt when ownership
changes. So the overlay is made from the two things **both renderers already
share** — a coloured region outline (`_map_lines`) and a badge at its centre
(`_map_labels`). No new primitive, no per-cell work, and the Tk canvas and the
GPU map cannot disagree. A test asserts both methods draw it, because that is
the failure that would otherwise ship silently.

Drought a gold sun, storm a blue thundercloud, blizzard pale ice, fog grey
haze. Severe solid and thick, mild dashed and thin.

- **Drought is on the map** even though it does nothing to travel or battle.
  It is the one that ruins your harvest. Leaving it off because it has no
  combat effect would be reading the mechanics rather than the game.
- **Fog-gated on the region's centre**, exactly like the region's name.
  Weather over unexplored rival territory would quietly make this a scouting
  tool.
- **`_weathered_regions()` is cached per turn.** Both draw methods ask and the
  GPU map calls both every rebuild.

One flaw the test caught rather than the eye: the two severities shared a
minimum line width, so at world scale they clamped equal and a mild fog drew
identically to a severe blizzard — at exactly the zoom where you decide
whether to march. Separate minimums now.

---

## 30. Lakes — one great lake, not a flooded continent (v0.9.0)

Reported from a screenshot: not that lakes existed, but that there were so
many ENORMOUS ones that the land stopped reading as whole. Measured across
three seeds: lakes covered 8.9-14.6% of all land, three to six basins each
over 1% of it, one at 5.4% of the world's land alone.

**`_LAKE_DEPTH` could not fix it, and that is the instructive part.** It is a
single global threshold: raise it enough to drown the inland seas and every
pond goes with them, and the small lakes are pure character. The problem was
never lake DEPTH, it was the size of individual BASINS.

`worldgen._trim_oversized_lakes` labels the 8-connected components and caps
each at `_LAKE_MAX_SHARE` (0.5% of land), with `_GREAT_LAKE_LIMIT` (1) exempt
— the largest keeps whatever size the terrain gave it, because a single huge
lake is a landmark and that was explicit in the report. An oversized basin
recedes to its DEEPEST cells (what a drying lake really does), then keeps the
largest connected component — the deep end of a long lumpy basin can come out
as two pools, and one lake reading as two is the fractured look being fixed.

Drained cells simply become land. Nothing downstream needs telling: the filled
DEM is untouched so rivers route across the old basin exactly as before, and a
drained basin is a low plain.

`_LAKE_DEPTH` also went 0.016 → 0.022, which removes broad shallow sheets
without costing many actual lakes — basin COUNT falls only ~10%, because a
pond is deep for its size.

After: 5.6%, 9.2%, 6.9% of land, one oversized basin each. The 9.2% seed is
almost entirely its single inland sea.

---

## 31. WHERE TO START

The two multi-phase threads that dominated this project — the biome overhaul
and the weather system — are both **finished**. There is no live thread to
resume, which is itself the most important thing on this page. Pick by value:

**The strongest remaining idea is supply-driven pricing (§16.2).** It is the
largest unbuilt economic mechanic, `unit_price`'s surplus factor already does
half of it, and the economy around it has settled down enough to build on.

**The most useful chore is an economy section in the balance lab (§15.5).**
All 217 tunable levers are battle-side. Every economy constant — and there are
now a great many, across `resources.py`, `travel.py`, `trade.py` — is
source-only, which means the user cannot playtest any of it, and playtesting
is how this project decides things.

**The most interesting open question is §26**, the archer one. It is not a
tuning task. Every output-side lever collapses bad-weather performance before
denting clear-weather dominance, and range does nothing at all. Something
structural is missing — most likely that foot has no answer to being shot
during the approach. Read §26 before touching a number.

**Do not re-open** the biome overhaul (§§19-24) or weather (§10, §§27-29)
expecting to find work. They are closed records. Their tuning constants are
listed in §19.6 and in the module comments, and every one of them is a
"judge it in play" number rather than an unfinished job.
