# The Economy Is Readable (v0.19.0 plan)

**Theme: A+B — the economy ledger, visible gated rules, and the tooltips that
back them up. Nothing here changes a balance number or a simulated result; the
pass is observation and presentation, plus one decision lever proposed for
review at the end.**

A player looking at the resource bar should always be able to answer three
questions:

1. **Where does my X come from?** (acquire: which village, which camp, which season)
2. **Where does my X go?** (consume, convert, spoil, sell, build)
3. **Why did the number move?** (the single conflated delta is not an answer)

Today the sim knows all three answers and shows none of them. This plan makes
the sim's own numbers the UI's numbers.

---

## 1. Current state — what is opaque, with receipts

The economy is dense and mostly coherent; the problem is that its rules run
silently and its numbers are only shown node-by-node.

**The resource bar conflates everything** — `map_view.py:2122` draws rows of
`current + one net delta` computed by before/after snapshot diff
(`map_view.py:3966-3973`). Production, conversion, spoilage, trade and
consumption are fused into a single number. There is no per-cause breakdown
anywhere except Gold's Treasury (`map_view.py:2349-2431`), which is the model
this plan generalises.

**Silent rules, each with its receipt:**

| Rule | Where it runs | Player signal today |
|---|---|---|
| Industry gated on camps: no Woodcutters' Camp, no timber | `resources.py:1930-1975` | Compendium prose only (`compendium_data.py:462-463`) |
| Storage throttle tapers production from 85% full down to a 0.15 floor | `resources.py:4035-4247` | One generic "storage nearly full" alert (`:3655`) |
| Spoilage + overflow decay are per-resource taxes | `resources.py:283-332`, `:6355`, `:4003` | Documented in Compendium, shown nowhere live |
| Gold minting is invisible ("nothing announces it") | `resources.py:5030-5037` | Treasury ledger only (`map_view.py:2427`) |
| Coal-for-firewood and winter scrounging substitute silently | `resources.py:3464-3469`, `:3103-3115` | Nothing |
| Trade reserves hold goods back implicitly | `trade.py:62-63` | Not explained at the sell surface |
| Gate rules (no food up the door, blockade radius, under-spoilage 0.35) | `resources.py:6102-6193`, `:4866` | Compendium prose only |
| Acclimatisation yield multiplier exists | `resources.py:1789-1840` | Never shown |
| Faction cartographer tier exists | `resources.py:5124-5135` | Per-settlement survey card only |

**There are no tooltips anywhere** (grep for tooltip/hover/balloon: nothing;
only cursor-to-hand at `parchment.py:510-516`). Help = Compendium (F1), which
is a reference, not an answer to "why is my Iron falling".

---

## 2. The design in one paragraph

Add a **faction-wide economy ledger** — a per-cause, per-resource accounting
window — built by *measuring the sim at phase boundaries* (the project's
"measure once" philosophy: no instrumentation audit, guaranteed to reconcile).
Present it in a **new draggable Ledger panel** (Treasury's foldable-section
idiom) and a **hover-tooltip layer** on the resource bar, storage cards and
village production card. Then surface the silent rules where they bite: camp
gates on resource rows, throttle/spoilage numbers on storage cards, a winter
substitution alert, and a mint line in the ledger.

---

## 3. Part A — the economy ledger

### 3.1 Data: phase-boundary attribution

New world-side helper in `resources.py`:

```python
def faction_resource_snapshot(world, fac_idx):
    """Total stock of every resource across the faction's owned nodes.
    World-side twin of map_view._current_resource_snapshot (map_view.py:2179)."""
```

New per-day accumulator `world._econ_turn[fac_idx][resource][cause]` and a
closed ledger `world.econ_ledger[fac_idx]` (both `getattr`-defaulted for
save-compat, exactly like `_gold_turn`/`gold_ledger` at `resources.py:7113-7128`).

In `day_steps` (`resources.py:7289-7504`), snapshot before and after each
phase group and attribute the *faction-total* delta to a cause:

| day_steps phase group | ledger cause |
|---|---|
| production, herds | `produced` |
| stockpiles (spoilage/clamp/overflow) | `spoiled` |
| workshops (recipes, fungus, mint) | `converted` |
| households (consumption; logistics moves within faction → 0 net) | `consumed` |
| raids | `raided` |
| caravans, trade offers, foreign trade, sell-to-city | `traded` |
| building, construction, expansion, roads, surveys | `built` |
| frontier | `raided` (losses) / `gained` |

Notes, honestly stated:
- **Local/gate/convoys shipments move goods between own nodes and never
  change the faction total**, so they naturally attribute 0 — which is
  correct for a *faction* ledger (the sidebar shows faction totals).
- Attribution is per-phase-group, so a group that does two things (e.g.
  preservation sits inside `shipments`) is charged to its dominant cause.
  The **reconciliation invariant holds regardless**: for every resource,
  `sum(causes) == real stock change` — that is the test gate (see §7).
- Gold's minted money already has its own treasury ledger; the resource
  ledger's Gold card reuses it (one "minted this year" line from
  `gold_ledger`, cause "minted").

### 3.2 Window and memory

Per-faction:
- `econ_ledger[fac_idx]` — window of recent days (reuse the gold-ledger
  window constant `GOLD_LEDGER_HISTORY_TURNS = 24`, `resources.py:7064`).
- `world.econ_year[fac_idx]` — rolling "this year" totals per resource per
  cause, reset at the year rollover in the season phase (where
  `map_view._show_year_banner` already keys off year change,
  `map_view.py:3973-3980`).

Worst case is small (68 resources × 8 causes × 24 turns of floats). Saves stay
bounded; no migration beyond the `getattr` default.

### 3.3 Panel UI — THE LEDGER

New floating panel in `map_view.py` following the Treasury exactly:
draggable header, `parchment.Page`, foldable sections, `_PANEL_REFRESH_MS`
refresh (`map_view.py:102`).

- **Opened by** a small "Ledger" glyph in the RESOURCES bar header
  (`_build_resource_bar`, `map_view.py:2081-2088`) and by **clicking any
  resource row** (Gold's row already opens the Treasury via
  `page.hit_last_row`, `map_view.py:2268-2273` — extended to every row, and
  the ledger opens pre-focused on that resource).
- **Sections** (Treasury's `section()` idiom, `map_view.py:2378-2383`):
  - `THIS YEAR` — per-cause totals across all resources, sorted by |net|,
    each cause with a one-line help (Treasury's `_TREASURY_CAUSE_HELP`
    pattern, `map_view.py:2349-2356`), plus the reconciliation line
    `sum(causes) == net`.
  - `PER RESOURCE` (default open) — foldable cards, one per resource with a
    nonzero year: current stock, net, then
    `produced +X · consumed −Y · converted ±Z · spoiled −W · traded ±T ·
    built −B · raided −R`, each with a muted explanation line.
  - `RECENT TURNS` (default closed) — last few days per resource, mirroring
    the Treasury's `RECENT TURNS` (`map_view.py:2433-2440`).
- Docked default position beside the Treasury, same `_clamp_to_view` drag.

### 3.4 Tooltips — the hover layer

New minimal mechanism in `parchment.py`: rows/cards accept an optional
`tip=`; on `<Enter>` (the existing hover binding, `parchment.py:510-516`) show
a small floating label near the pointer; on `<Leave>` hide it. One new method,
no behavioural change to existing rows.

Tooltip content:
- **Resource row**: the last day's cause breakdown, e.g.
  `Produced 12 · Consumed 8 · Spoiled 1 · Sold 3` — the delta, explained.
- **Gated raw material row**: `Blocked — no Woodcutters' Camp` (see §4.1).
- **Storage card** (`map_view.py:4881-4919`): that resource's spoil rate and
  the live throttle note when active (see §4.2).
- **Village PRODUCTION card**: acclimatisation factor
  (`resources.py:1789-1840`) and any blocked-but-extractable resources.

---

## 4. Part B — visible gated rules

### 4.1 Camp gating on the resource bar

New world-side helper `blocked_industry_resources(world, fac_idx)`: for each
owned village, cross `_village_terrain_potential` (`resources.py:1885-2038`)
against the `OUTSTATIONS` table (`resources.py:4652-4714`) — "this catchment
can yield Logs, but no Woodcutters' Camp exists."

Resource rows for such resources render a muted sub-line:
`needs Woodcutters' Camp` (and the village PRODUCTION card lists them as
"blocked by missing camp: …"). This turns the single most silent gate in the
economy into a visible todo.

### 4.2 Storage cards tell the truth

- **Spoil rate**: each storage card already knows the resource; render its
  `spoil_rate` (`resources.py:283-332`) as a muted line — `Spoils X%/turn`.
- **Throttle**: when `storage_throttle` (`resources.py:4135`) is active,
  show `storage N% full — production slowed to M%` on the card and in the
  alert's own line (`resources.py:3655-3660`), instead of the current bare
  "storage nearly full".

### 4.3 Winter substitution alert

When coal substitutes for firewood (`resources.py:3464-3469`) or scrounging
engages (`:3103-3115`), emit one faction alert per winter with the quantities,
e.g. `Burned 14 coal for warmth (no firewood)`. One alert per winter, not per
day — alerts are a feed, not a dump.

### 4.4 Minting line

The Ledger's Gold card gets `minted this year: N` from the treasury ledger
(cause "minted", `resources.py:7124`), closing the "nothing announces it"
gap (`compendium_data.py:611-619`).

---

## 5. The one decision lever (proposed for review)

**Per-faction trade safety reserve.** Today food is never sold below 8 turns
of need and non-food below 10% of capacity (`trade.py:62-63`), and the sell
UI never says so — players report "why won't my caravan sell this". Proposal:

- A faction setting `trade_reserve_turns` (default 8, matching today) with a
  `1..30` slider in the Ledger's `THIS YEAR` section.
- `sellable_surplus` (`trade.py:488`) reads the override.
- **This is the only balance-touching piece in the pass.** It is small,
  player-facing, and reversible; it is also exactly the "why won't my
  caravan sell this" gap. If the preference is a strictly observation-only
  pass, drop §5 entirely and the rest of the plan is untouched.

**Deliberately not in this pass:** converting firewood substitution or
scrounging into player toggles — that changes survival math and deserves its
own balanced pass (and the project's "ground in how the real thing worked"
rule applies: it needs a historic anchor before it becomes a button).

---

## 6. Out of scope (explicitly)

- **C — loop teeth** (morale wired into real effects, AI-initiated wars,
  win/loss shape): its own later pass; none of it is touched here.
- **D — supply-driven pricing** (the HANDOFF §31 open item): unchanged.
- No balance constants change except the optional §5 lever.
- No worldgen, save-format, or sim-behaviour change. The ledger is
  **observation-only**, proven by fingerprint (below).

---

## 7. Verification

New `dev/test_econ_ledger.py` (project conventions: `SHAPES_SILENT=1`,
`dev/worlds/dev560.pkl`, `python dev/test_econ_ledger.py [world.pkl]`):

1. **Reconciliation invariant** — run N days; for every resource,
   `sum(ledger causes) == real stock change` (the load-bearing assertion:
   the ledger is the sim, measured).
2. **Observation-only** — run the same world twice with the ledger on/off
   (guarded by a `LEDGER_ENABLED` flag) and fingerprint all region/node/
   faction/gold state identical, same instrument as
   `dev/test_turn_slice.py`. Proves the pass changes nothing simulated.
3. **Year rollover** — `econ_year` resets at the year boundary and its
   totals match the year-banner deltas (`map_view.py:3975-3979`).
4. **Panel smoke** — `_refresh_ledger` renders without error with data, and
   with an empty ledger (the "end a turn" placeholder, Treasury's pattern
   `map_view.py:2418-2419`).

Then the standing full suite:
`export SHAPES_SILENT=1; for f in dev/test_*.py; do out=$(python "$f" 2>&1); [ $? -ne 0 ] && echo "FAIL $f" && echo "$out" | tail -6; done` (HANDOFF.md:143).

---

## 8. Release

- Changelog entry 115 (next after 114, per the release cadence), version
  bump in `build.bat` (`APP_VERSION=0.19.0`), `release_notes_0.19.0.md`.
- Exe rebuild + GitHub Release + ShapesOfWar.exe asset per the standing
  release process (push != ship); launcher marker via `make_version_file.py`.
- Known good: `build_version_game.txt`, `game_version.txt` handling.

---

## 9. Working-tree note

The tree currently carries the uncommitted two-layer path-cache performance
change (`commander.py`/`layers.py`/`worldgen.py`). This plan touches none of
those files; the ledger work lands cleanly on top. It should be committed
first (or left as-is) at implementation time, and this pass's diff kept
separate.

---

## 10. Open questions for review

1. **§5 reserve slider in or out?** (only balance-touching piece; recommend in)
2. Ledger window: 24-turn window + this-year totals (recommended) — or
   this-year only, to keep the panel minimal?
3. Tooltip layer: resource bar + storage + village production card
   (recommended) — or also group headers / alerts?
