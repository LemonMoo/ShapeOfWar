# Governance & Loyalty (plan)

**Theme: every species rules its realm its own way. A realm has a *government
form*; its people have a *loyalty* toward that form; loyalty shapes how the
land runs — economy, army, how much it can govern, and whether it holds
together at all.**

Decisions locked with the user: **(1a)** one shared menu of government forms
with per-species affinity (a ruler can reform, at a loyalty cost); **(2abcd)**
loyalty drives economy + military + governance capacity + revolt risk; **(3a)**
build it slice-by-slice, starting with an observation-only foundation — no
balance changes in slice 1, exactly like `progression.py`'s slice-1/slice-2
split.

---

## 1. Current state — what is there and what is not, with receipts

Species are already a first-class, per-realm thing, but they stop at the
military/economic stat line. There is no government, no law, and no
loyalty/approval anywhere in the sim.

| thing | where | status |
|---|---|---|
| 5 species (`Humans/Elves/Dwarves/Orcs/Goblins`) with `mil`/`eco`/`trait` + tactical traits | `app/world/lexicon.py:55` `SPECIES` | `mil` used (`worldgen.py:3128`, `resources.py:6670`); **`eco` declared but never read anywhere — dead axis** |
| species biome affinity + diplomacy affinity (`-2..+2`) | `lexicon.py:187`, `diplomacy.py:24` | live, and the `-2..+2` scale is the precedent to copy |
| a realm is a `Nation` with free-form `stats = {military, morale}` and `meta = {species, trait, …}` | `app/world/nation.py:58` | `stats`/`meta` are dicts — a `government`/`loyalty` field drops in with no schema change |
| `morale` today | set `worldgen.py:3130`; costs 3 on terrorize `diplomacy.py:177`; shown `map_view.py:4601` | **nearly inert** — no link to laws/government/populace |
| "governance" = how many *regions* a realm can run well (City 3 / Castle 2 / Town 1 + 1) | `app/world/progression.py:219` `governance_capacity` | about **land capacity**, not consent |
| tax is a static per-kind roll | `worldgen.py:84` `SETTLEMENT_TAX_INCOME`, `worldgen.py:140` | `Settlement.tax_income` still feeds prosperity via `resources.py:6735`/`6859`, but it is rolled once and never reacts — HANDOFF.md:109 flags it "dead stat — wire it up or delete it" |
| levy = `MOBILIZATION_RATE` (0.08) of adults | `resources.py:6577`, `_recompute_military:6617` | the military hook loyalty will modulate |
| faction prosperity health factor | `resources.py:6819` `_faction_health_factor` | the economy hook |
| rulers already exist (name + title) | `nation.py:44`, `ensure_rulers:76`, `ruler_title` in `lexicon.py` | government forms only need a *title* per form, not new identity plumbing |
| species naming banks already encode each people's government | `lexicon.py:384` `_FACTION_NAMES` | Elves → Council/Court/Circle/Enclave; Dwarves → Clanhold/Stronghold/Hold; Orcs → Warband/Horde/Clan/Tribe; Goblins → Gang/Mob/Den; Humans → Princedom/Dominion/Covenant/Accord/Sovereignty |

**No loyalty / approval / unrest / revolt system exists at all** (grep for
loyalty, approval, revolt, unrest, satisfaction, content turns up nothing
gameplay-side). This is greenfield, but every hook it needs already exists.

---

## 2. The design in one paragraph

Introduce a shared menu of **government forms** (Elder Council, Clan Council,
Warband, Gang-Boss, Feudal Monarchy, Republic, Theocracy, Guild Oligarchy).
Every realm has a **current form** (defaulting to its species' preferred
form). Each species carries an **affinity** (`-2..+2`) toward each form — the
"what its general populace wants" the design is built around. A realm's
**loyalty** (0–100) is `base affinity` + how well the realm's *actual
behavior* matches what that form's people want (raid vs trade, war vs peace,
tax light vs heavy, faith, growth). Loyalty then modulates the four live
systems already in place: economy (tax/prosperity), military (levy), governance
capacity (how much land it can hold well), and — at the bottom — revolt/
secession. Slice 1 builds only the observation layer: the form + affinity
tables and a pure-function loyalty score, surfaced in the UI, changing no
simulated result.

---

## 3. Government forms (slice 1 data)

One menu, ~8 forms. Each has a display name, the ruler **title** it grants
(reuses `ruler_title`'s contract — a short string), and a one-line "what the
people want" (the policies whose match drives loyalty in slice 2+).

| form | ruler title | the people want |
|---|---|---|
| **Elder Council** | Elder | conservation, slow deliberate growth, peace with the forest, tradition over expansion |
| **Clan Council** | Thane / Clan-Lord | self-sufficiency, mining & smithing, honoring oaths, holds over conquest |
| **Guild Oligarchy** | Master | trade, craft, coin, law by contract |
| **Theocracy** | Hierophant / Seer | faith, tithes, holy sites, laws from scripture |
| **Feudal Monarchy** | King / Queen | a landed nobility, heraldry, farms and castles, order |
| **Republic** | Consul / Speaker | elected rule, the accord of the free, open trade, law by debate |
| **Warband** | Warlord | raid and war, glory, tribute, the strongest leads |
| **Gang-Boss** | Boss | scavenge and swindle, tribute, the den over all, might and cunning |

**Species affinity** (first-pass, `-2..+2`, mirroring `diplomacy.SPECIES_AFFINITY`):

| species | Elder Council | Clan Council | Guild Oligarchy | Theocracy | Feudal Monarchy | Republic | Warband | Gang-Boss |
|---|---|---|---|---|---|---|---|---|
| Humans | 0 | 0 | +1 | +1 | +2 | +2 | -1 | -2 |
| Elves | +2 | +1 | 0 | 0 | 0 | +1 | -2 | -2 |
| Dwarves | +1 | +2 | +1 | 0 | 0 | 0 | -1 | -1 |
| Orcs | -2 | 0 | -2 | -1 | -1 | -2 | +2 | +1 |
| Goblins | -2 | 0 | -2 | -2 | -2 | -1 | +1 | +2 |

`DEFAULT_GOVERNMENT = {species: highest-affinity form}` — Elder Council for
Elves, Clan Council for Dwarves, Warband for Orcs, Gang-Boss for Goblins;
Humans tie-break to Feudal Monarchy (their "adaptable" trait is expressed by
*affinity spread*, not by a single archetype).

Where it lives: the `GOVERNMENT_FORMS` and `SPECIES_GOVERNMENT_AFFINITY` tables
sit in `app/world/lexicon.py` next to `SPECIES`/`SPECIES_BIOME_AFFINITY`, so
they draw from the same word banks and stay one screen away from the balance
tables.

---

## 4. Loyalty (slice 1: the score; slices 2+: the drift)

A pure function — like `progression.py`, it writes nothing and reads only world
state, so a given save always scores the same:

```python
# app/world/governance.py  (new, mirrors progression.py)
def government_form(world, fac_idx):      # nation.meta["government"], or DEFAULT_GOVERNMENT
def government_loyalty(world, fac_idx):   # 0..100: base + behavior match
```

**Slice 1** computes loyalty as a *constant per species+form*:
`loyalty = 50 + affinity * 10` (affinity −2 → 30, +2 → 70, neutral → 50),
clamped 15..99 to match the game's existing morale floor. This is
**observation-only** — it changes no simulated result; it just gives the UI a
real number to show and the test suite a real number to assert on.

**Slice 2** adds the *behavior match* term (the "what the populace wants to do"
half): a set of named policy axes per form, each compared against the realm's
actual recent behavior — e.g. Warband wants raids/war and is offended by
sitting idle or trading with Elves; Elder Council wants forest conservation and
is offended by over-clearing or sprawling claims. Each mismatch nudges loyalty
down, each match up, eased toward the target (the same `PROSPERITY_EASE`-style
smoothing `resources.py` already uses). The ruler can **reform** to another
form at a one-time loyalty cost scaled by how far the species' affinity
disagrees.

---

## 5. The four effects (slices 2–4, each a separate landing)

These are the *why* of the system — the concrete jobs loyalty does. They land
one slice at a time, each independently shippable and revertable, so none of
them blocks the others.

- **(a) Economy** — loyalty scales `Settlement.tax_income` (turning the dead
  static roll into a live rate) and/or the faction prosperity health factor
  (`resources.py:6819`). This is also where the dead `eco` species axis gets
  its first real job: high-`eco` species lean on trade/tax, low-`eco` on raid.
- **(b) Military** — loyalty scales the levy that answers the call: a fraction
  of `_recompute_military`'s `adults * MOBILIZATION_RATE` (`resources.py:6617`),
  so a loyal Warband fields a full levy while a disloyal one's army melts.
- **(c) Governance capacity** — loyalty nudges `progression.governance_capacity`
  (`progression.py:219`): a loyal realm holds its land well; an unpopular
  government's rule thins at the edges (higher overstretch).
- **(d) Revolt / secession** — below a loyalty floor, owned regions begin to
  revolt: first a prosperity/economy drag, then a region flipping to neutral or
  declaring independence (reusing `territory.py`'s existing transfer /
  `eliminate_faction` machinery). This is the one hard failure mode and lands
  **last**, once (a)–(c) are proven, because it needs the most care and the
  strongest regression coverage.

---

## 6. Slice breakdown

| slice | scope | changes a simulated result? |
|---|---|---|
| **1** | `GOVERNMENT_FORMS` + `SPECIES_GOVERNMENT_AFFINITY` + `DEFAULT_GOVERNMENT` in `lexicon.py`; new `app/world/governance.py` with `government_form`/`government_loyalty`; `nation.meta["government"]` seeded at worldgen; region panel shows the form + loyalty; compendium article; tests | **no** |
| **2** | behavior-match loyalty drift + the **reform** action; surfaces the four axes | yes (loyalty moves) |
| **3** | effect (a) economy + effect (b) military | yes |
| **4** | effect (c) governance capacity | yes |
| **5** | effect (d) revolt/secession | yes |

Slice 1 is the only thing in scope for the first implementation pass. It is
deliberately reversible and touches no balance number.

---

## 7. Numbers to judge in play, not in a simulator

First-pass values, named here so they can be tuned by feel (the project's
standing rule — HANDOFF.md:66, §16.7). **None of these are implemented in
slice 1**; they're the hand-off targets for slices 2+.

| constant | file | now | if it feels wrong |
|---|---|---|---|
| `LOYALTY_BASE` | governance.py | 50 | loyalty always high/low |
| `LOYALTY_AFFINITY_WEIGHT` | governance.py | 10 (→ 30..70 band) | species feel samey / extreme |
| `LOYALTY_FLOOR` / `_CEIL` | governance.py | 15 / 99 | matches existing morale clamp |
| `REFORM_LOYALTY_COST` (per affinity step) | governance.py | TBD, ~12 | reforming free / impossible |
| `LOYALTY_TAX_MULT` (min..max) | resources.py | ~0.6..1.4 | economy swings too hard |
| `LOYALTY_LEVY_MULT` | resources.py | ~0.6..1.4 | armies collapse too fast |
| `LOYALTY_GOVERNANCE_STEP` | progression.py | ~1 region per 20 loyalty | overstretch too sharp |
| `REVOLT_LOYALTY_FLOOR` | governance.py | ~25 | regions rebel constantly / never |

---

## 8. Save compatibility

`Nation.meta` is a free-form dict already (`nation.py:44`), so a
`meta["government"]` field is simply absent on old saves — read it through a
helper (`government_form`) that falls back to `DEFAULT_GOVERNMENT[species]`,
exactly like `nation.is_eliminated`'s `getattr` default (`nation.py:24`). No
save migration, no version bump needed for slice 1.

---

## 9. Tests

Follow the `dev/test_*.py` convention (world-path optional, `SHAPES_SILENT=1`):

- `dev/test_governance.py` — new. Asserts: every species maps to a valid
  `DEFAULT_GOVERNMENT`; `government_loyalty` is in 15..99 and equal to
  `50 + affinity*10` for every species/form; a save with no
  `meta["government"]` falls back to the species default; loyalty is
  deterministic (same world, same score) and a pure function (no world mutation).
- Extend `dev/test_progression.py` if `governance.py` shares helpers.

Run gate: `export SHAPES_SILENT=1; python dev/test_governance.py` (and the
region-panel/UI script it touches, `dev/test_panels.py`, since slice 1 edits
`map_view.py`).

---

## 10. Release notes hook

When slice 1 ships: changelog entry (newest-first, `CHANGELOG_VERSION` bumped,
`release_notes_0.X.Y.md`, `build.bat` version — the standing release process,
"push != ship": the exe is the ship, via GitHub Release).
