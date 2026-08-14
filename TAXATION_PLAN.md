# Taxation & the Kingdom Treasury (plan)

**Theme: every realm runs on coin, and the crown takes its cut. Settlements
pay tax, trade pays tax, and the tax lands in a single *kingdom treasury* —
which is the only pot that funds new buildings, villages, towns and cities.**

Design locked with the user (via decision prompts):

1. **Gold keeps living in settlements/villages** (minted at the Mint, moved
   by trade). On top of that there is a **separate central kingdom treasury**
   per faction.
2. **Two taxes fill it:** a per-settlement **income tax** (revives the dead
   `Settlement.tax_income`) and a **transaction tax** (a cut of gold that
   changes hands in trade).
3. **Redistribute only — no money from nothing.** Tax moves gold that already
   exists; it never creates it (the project's standing "gold only enters via
   minting / real trade" rule, HANDOFF §16.2).
4. **The treasury funds development.** The Gold line of every build cost
   (buildings, settlements, upgrades, ships, tunnels) is paid from the
   treasury instead of per-settlement gold, and village founding/raising gains
   a Gold cost paid the same way.

---

## 1. Current state (receipts)

| thing | where | status |
|---|---|---|
| Gold minted from Gold Ore, held per-node | `resources.py` Currency section; `node.resources["Gold"]` | live; `faction_gold` sums it |
| Gold already in build costs | `construction.py` `BUILD_COSTS` / `SETTLEMENT_BUILD_COST` / `SHIP_COST` | paid from node gold via `can_afford`/`_pay_cost` |
| `Settlement.tax_income` | `worldgen.py:85` `SETTLEMENT_TAX_INCOME`, rolled at founding | **dead** — only feeds prosperity valuation (`resources.py:6741`), never gold |
| No central treasury | `Nation.stats` = `{military, morale, resources}` | none |
| Gold ledger attributes node-gold flows | `resources.py` gold-ledger section | live; Treasury panel reads it |

---

## 2. The model

- **Treasury** = `nation.stats["treasury"]` (int, `get`-defaulted 0 → old
  saves just read 0 until they earn). Helpers `faction_treasury` /
  `_add_treasury(cause)` / `_spend_treasury` in `resources.py`.
- **Income tax** (`resources.collect_income_tax`): each settlement pays
  `min(tax_income, gold it holds)` per turn into its treasury — revives the
  dead stat, capped by what actually exists (no negative gold, no minting).
- **Transaction tax** (`trade.TRADE_TAX_RATE`): `_deliver_payment` diverts
  that fraction of every Gold it credits to the payee's faction treasury
  instead of the payee settlement. Foreign trade is gold-first so it is where
  the tax mostly bites; domestic trade is barter-first so it rarely pays
  coin at all.
- **Treasury funds development**: `can_afford`/`_pay_cost` treat `"Gold"` as
  a treasury draw (not node stock). `VILLAGE_BUILD_COST` /
  `RAISE_VILLAGE_COST` gain a Gold line. Claims stay settlers+food
  (`expansion.py`'s documented reason: pricing claims in gold locked realms
  out — not re-litigated here).
- **Starting treasury**: seeded once at world-gen (`STARTING_TREASURY_PER_
  FACTION`) alongside the existing node-gold seed, so turn-1 construction
  isn't frozen while the first taxes land.

---

## 3. Ledgers & UI

- New **treasury ledger** (`world._treasury_turn` / `world.treasury_ledger`),
  mirroring the gold ledger: causes `income tax`, `trade tax`, `spent`.
- Gold ledger gains a `tax` cause (income tax is a node-gold drain, bracketed
  in `day_steps`). Transaction tax stays inside the trade causes (the seller
  simply receives less node gold) so the gold ledger still reconciles.
- Treasury panel (`map_view._refresh_treasury`) gains a **KINGDOM TREASURY**
  section: balance + per-cause breakdown over the recent window.

---

## 4. Constants (first-pass, tune by feel)

| constant | file | value |
|---|---|---|
| `TRADE_TAX_RATE` | trade.py | 0.10 |
| `STARTING_TREASURY_PER_FACTION` | resources.py | 2000 |
| `TREASURY_LEDGER_HISTORY_TURNS` | resources.py | 24 |
| `VILLAGE_BUILD_COST["Gold"]` | construction.py | 200 |
| `RAISE_VILLAGE_COST["Gold"]` | construction.py | 400 |

---

## 5. Save compatibility

`Nation.stats` is a free-form dict; `treasury` is simply absent on old saves
and reads 0 via `.get`. `world._treasury_turn`/`treasury_ledger` use the same
`getattr` default the gold ledger already does. No migration, no version bump.

---

## 6. Verification

`dev/test_taxation.py` (conventions: `SHAPES_SILENT=1`, `dev/worlds/dev560.pkl`):

1. **Income tax redistributes, never creates** — run a turn; treasury delta +
   node-gold delta == 0 across the faction (tax moves coin, mints nothing).
2. **Cap respects held gold** — a settlement with 0 gold pays 0 tax.
3. **Transaction tax** — a synthetic sale credits `(1 - TRADE_TAX_RATE)` to
   the seller settlement and the rest to its treasury.
4. **Treasury funds construction** — `can_afford` checks the treasury, not
   node gold, for a Gold-only cost; `_pay_cost` draws it from the treasury.
5. **Ledger reconciles** — treasury ledger `sum(causes) == real treasury
   change` over the window.

Then the standing full suite (`HANDOFF.md:143`).
