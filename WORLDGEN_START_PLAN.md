# Worldgen coherence + choosing your start — a plan

Two asks, one document, because they lean on each other: a world worth
choosing a spot in has to exist before a start-picker means anything, and
bigger, fewer continents (Part A) are what create room for the interior lakes
and the sustainable start sites (Part B) to sit in.

Neither is a rewrite. The pipeline — plates → height → current-carved
coastline → hydrology/lakes → climate → biomes → fertility — is already the
right logical chain (HANDOFF §9). Part A tunes its output to convergence, the
tuning pass §9 flagged as never finished. Part B refactors *where the player's
location is decided*, not how the world is made.

Decisions taken with the user, up front:

1. A Standard world aims for **4–5 major continents.**
2. Interior water reads as **a few medium lakes plus one great lake.**
3. The player **picks a start and sees its resources first**, and is
   **warned — not blocked** — if the site cannot sustain a start.

---

## Why it looks fragmented today

The screenshot is the §9 symptom. `_target_n = rng.randint(4, 7)` already aims
at 4–7 *substantial* landmasses and retries toward it — so the continent
COUNT is not what is failing. The clutter is **islets that do not count as
substantial but still fill the sea**, manufactured by four knobs:

- `FRACTION_CONTINENTAL = 0.40` — continental plates cover ~40% of area and
  the land target is also ~40%, so much of the required land must come from
  scattered oceanic-boundary bumps and hotspot chains rather than from
  continental bodies. Those are disconnected by nature.
- `AMP_CONVERGENT_OO = 0.40` (island arcs) and `AMP_DIVERGENT_OTHER = 0.15`
  (mid-ocean ridges) push oceanic boundaries above sea level.
- `HOTSPOT_CHAIN_LINKS = 6` with a hotspot per ~4 plates — a lot of Hawaii.
- `DETAIL_AMPLITUDE = 0.6` — noise on top of plate structure flings off
  detached specks along every coast.

And the lakes: `_GREAT_LAKE_LIMIT = 1` keeps exactly one big basin and shrinks
every other oversized one to `_LAKE_MAX_SHARE = 0.005` (0.5% of land) — which,
on today's small fragmented continents, drains them to puddles. One Caspian
and a scatter of ponds, never the medium interior lakes.

The two asks reinforce: **bigger, fewer continents create the interiors that
medium lakes need.**

---

## Part A — coherent worldgen (do this first)

A dedicated tuning pass. Every knob below already exists; the work is moving
them together and **proving it by rendering, not by feel** — the project rule
that has caught five real worldgen bugs. `dev/coastline_metrics.py` already
reports landmass count, land %, coastline irregularity and a PNG per seed.

**Targets to tune against** (Standard, 1100×660), recorded not eyeballed:

- 4–5 substantial landmasses (≥3% of land each), reliably, not 10.
- Islands present but incidental — an arc off a subduction zone, not a
  scattergun. A rough bar: the sum of *non-substantial* land bodies well under
  a tenth of total land.
- Coastline irregularity still organic (the metric's current healthy range),
  not smoothed into circles.
- A few medium interior lakes + one great one.

**The knobs, in `app/world/plates.py` unless noted:**

| goal | knob | now | direction |
|---|---|---|---|
| land from continents, not bumps | `FRACTION_CONTINENTAL` | 0.40 | ↑ ~0.52–0.58 |
| boundary bumps stop crossing sea level | `BASE_CONTINENTAL` / `BASE_OCEANIC` | ±0.75 | widen the gap |
| fewer, larger continents | `_pick_n_plates` coefficient (`worldgen.py`) | 11·√area | ↓ |
| fewer island arcs | `AMP_CONVERGENT_OO` | 0.40 | ↓ ~0.20 |
| fewer ocean ridges breaking surface | `AMP_DIVERGENT_OTHER` | 0.15 | ↓ ~0.06 |
| fewer island chains | `HOTSPOT_CHAIN_LINKS`, hotspot count | 6, ~n/4 | ↓ both |
| smoother coasts, fewer specks | `DETAIL_AMPLITUDE` (`worldgen.py`) | 0.6 | ↓ ~0.4 |
| medium interior lakes, not puddles | `_LAKE_MAX_SHARE` (`worldgen.py`) | 0.005 | ↑ ~0.015 |
| keep exactly one great lake | `_GREAT_LAKE_LIMIT` | 1 | keep |
| retry bar matches the new target | `_target_n` | randint(4,7) | randint(4,6) |

`AMP_CONVERGENT_CC = 1.35` (the big continent-collision range) stays — that is
the mountain spine, and it is what the underworld carves into.

**Guard rails, because this is coupled tuning:**

- Land % must still hit its target — the percentile threshold contract in
  `generate_world` already enforces this, so raising continental area shifts
  the sea-level threshold rather than flooding the map. Watch it, don't assume.
- Generation time and the retry cap: fewer, larger continents is an *easier*
  target than 6–7, so retries should fall, not rise. If they climb, the
  amplitudes were cut too far and land is short.
- **The underworld sits on the mountains** (§37). After tuning, re-run
  `dev/test_underworld.py` and `dev/under_shot.py`: fewer but larger ranges
  should give fewer, bigger holds — fine, but it must still carve and no
  network may be sealed.

**How it is verified:** sweep 15–20 seeds through `dev/coastline_metrics.py`
before changing anything to record the baseline, tune, sweep again, and put
before/after renders in front of the user. Record the numbers in the commit,
the same discipline as the plate and lake passes before it.

---

## Part B — choose your start, with a resource preview

Today the player is auto-placed at their best-affinity capital
(`_order_capitals_by_affinity`, slot 0). There is no choice. The clean way to
add one is one honest refactor plus wiring.

### The refactor

Split `generate_world` into two responsibilities:

1. **Grow the world and place the rivals** — terrain, hydrology, biomes,
   regions, wildland strength, and every AI faction's foothold — leaving the
   player *unplaced*. This is the "logical placement" reintroduction the user
   asked for: nothing about the player is baked into the map until they choose.
2. **Settle the player** at a chosen cell — foothold, settlements, villages,
   commander, starting fog — run on confirm.

The New Game screen already generates in the background and hands `Play` the
*exact* world object the preview showed (the identity-patching guarantee in
§8). Start selection extends that guarantee: the site you inspected is the site
you get, because it is the same world object.

### The picker

On the New Game preview (which already renders a world thumbnail via
`world_preview.render_world`):

- **Offer candidate sites** — spaced, farmland-valid cells
  (`_capital_has_nearby_farmland`) clear of the rivals already placed. A
  handful, marked on the thumbnail.
- **Click one → a card of what is actually there**, read from the real world:
  biome mix, likely resources (the biome→resource tables), farmland %,
  coast/river access, homeland fit for the chosen species
  (`homeland_affinity` / `_homeland_biomes`), and elbow room (`land_summary`).
  Everything the card promises is what the start delivers.
- **Free placement, with a warning.** Per the user's call, the player may also
  drop a start on any land cell — but a site that cannot sustain a start
  (no farmland in reach, fertility below a floor) shows a clear **warning**
  and lets them proceed anyway. Warn, don't block.

### On confirm

Run the player-placement step at the chosen cell. Reuses the existing
farmland/affinity/summary checks, so it is mostly wiring around one refactor of
*where the location is decided*.

---

## Phasing

Each phase built, tested and committed on its own, house style.

1. **Worldgen tuning pass (Part A).** Baseline sweep, tune, sweep, renders to
   the user, re-verify the underworld. Ships as its own release — it changes
   every new map and wants to be judged in play before the UI work lands on
   top of it.
2. **The `generate_world` refactor.** Split world-growth from player-placement
   with the player left unplaced; the old entry point keeps working (auto-place
   as today) so nothing breaks while Part B is built. Gate: a fresh world is
   byte-identical whether placed the old way or the new two-step way, for the
   same seed and chosen cell.
3. **The start-site evaluator.** Pure logic: given a world and a cell, return
   the resource/farmland/coast/affinity summary and a sustain verdict. Tested
   headless against real worlds before any UI.
4. **The picker UI + confirm.** Candidate markers on the preview, the card,
   the warning, and the confirm that runs placement.
5. **Suite, a v0.14.1 save proving migration, ship.**

---

## Risks, named up front

- **Coupled tuning drifts.** Six amplitude/base knobs interact; moving one
  masks another. The metric sweep is the discipline, and land % is the canary.
- **The picker must not leak fog.** Candidate sites and their resource cards
  describe ground the player has not "seen" — but this is pre-game, before fog
  exists, so it is legitimate here in a way an in-game survey is not. Keep it
  to the New Game screen; do not reuse the evaluator to peek mid-game.
- **A warned-but-doomed start is still a real game.** If the player overrides
  the sustain warning, the start must degrade gracefully (a hungry opening),
  not crash — the same robustness the wildland-with-no-villages edge case
  already demands.
- **Underworld coupling.** Fewer, larger ranges change hold count and size.
  Expected, but re-verified rather than assumed.
