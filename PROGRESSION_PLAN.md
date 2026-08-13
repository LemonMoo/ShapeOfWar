# Progression: Governance & Development (plan)

**Theme: make growth legible, and make the reason you can or cannot expand a
real one — instead of a flat number.** Nothing in slice 1 changes a simulated
result; it adds the development score + named ages and surfaces them. Slice 2
wires the score into expansion as a soft governance limit.

---

## 1. Current state — one flat gate, no eras

Expansion today is gated by exactly one blunt instrument:
`CLAIM_DEVELOPMENT_FRACTION = 0.5` in `expansion.py:start_claim` — a land claim
is refused outright until the faction's own regions average 50% of their
village capacity. That is simultaneously:

- **Overhanded** — a binary lock. A realm at 49% is told "no", a realm at 50%
  can claim freely. Nothing in between, no sense of *progress toward* the door
  opening.
- **Meaningless** — the message ("fill your village lands … before reaching
  for new territory") names a number, not a reason. It does not say *why* a
  realm cannot govern more land, because nothing in the model knows.
- **Flat** — there is no era structure. "Late game" is not a destination with
  milestones, it is the moment you happen to have built a city and a
  weaponsmith; after that the game is just bigger numbers.

Everything a *real* progression system needs already exists in the sim and is
already tracked:

| signal | where | what it means |
|---|---|---|
| settlement kinds reached | `world.settlements[].kind` (city/castle/town) | the settlement-first ladder (village → town → city/castle) |
| storage building tiers | `resources.storage_tier(node, b)` | economic infrastructure depth |
| resource tiers 1..4 | `resources.RESOURCES[name]["tier"]` | the crafting chain (raw → extracted → processed → manufactured) |
| population / adults | `node.population` / `node.adults` | the workforce that is also the army |
| military | `nation.stats["military"]` | how much of that workforce you can arm |
| territory | regions with `faction_idx == yours` | how far your rule actually extends |
| trade routes | `world.trade_routes` | inter-realm economy |

---

## 2. The design in one paragraph

Introduce a **realm development score** (computed from the signals above, not a
new currency) with **named ages** — *Homestead → Age of Villages → Age of
Towns → Age of Cities → Age of Kingdoms → Age of Empire*. Each age is a set of
concrete, legible milestones drawn from the ladder the game already has ("raise
a village to a Town", "raise a Town to a City", "raise a Castle and arm your
levy", "hold 4 regions and stock craft goods"). The age is a *label and a
milestone spine*, not a wall: it explains where a realm is and what to build
next. Slice 2 then turns the continuous score into a **governance capacity**
that replaces the flat 0.5 gate — expansion stays always-possible but becomes
self-correcting (dearer, slower, "under-governed" land) past what your
development can govern, and *pressure* (villages near capacity, food tight)
becomes the reason to expand.

---

## 3. Why this meets the four requirements

| requirement | how |
|---|---|
| **natural expansion, not overhanded** | no hard lock; cost/benefit shifts continuously with development instead of a 50% on/off |
| **a good reason when you can't** | every block names the missing thing: "no way to govern distant land — build a Town/City or roads" |
| **no expansion for no reason** | expansion is *pulled* by pressure (full villages, tight food) and *earned* by milestones; its absence is the reason not to |
| **a long road to late game** | the age spine stretches the mid-game: five named milestones between a fresh foothold and an empire |

---

## 4. Slice 1 (this change) — score + ages, observation-only

New module `app/world/progression.py`, pure functions of world state (no
randomness, no writes, save-compatible):

- `AGES` — the ordered age ladder, each with `name`, `milestones` (names from
  the registry below), and `next` (the human-readable "to advance" hint).
- `faction_age(world, faction_idx)` → `(index, age_dict)` — the highest age
  whose milestones are all met.
- `age_label(world, faction_idx)` → the one-line UI string
  (`"Age of Towns — raise a Castle and arm your levy"`).
- `development_components(world, faction_idx)` → the raw named signals
  (population, settlement kinds, storage tiers, military, regions) — exposed so
  the UI/tests can show *why* the score is what it is.
- `development_score(world, faction_idx)` → a documented weighted sum of those
  components. First-pass weights; the scalar's real job is governance capacity
  in slice 2.

Milestones (each a named predicate, cheap and deterministic):
`town` (≥1 Town), `second_city` (≥2 Cities — the capital plus one raised),
`castle` (≥1 Castle), `armed` (Weapons cover ≥ half the levy), `four_regions`
(≥4 regions), `eight_regions` (≥8), `craft_goods` (holds a tier-4+
manufactured/luxury good), `trade` (≥1 active trade route).

Surfacing: the region panel header (`map_view.py` `_show_region`) prints the
faction's `age_label` under the region name — the same place the `n/m villages`
readout already lives, so a player expanding sees their realm's age and what
builds it next. No other UI change.

**Measured on `dev/worlds/dev560.pkl` (turn 561):** every faction scores as
Homestead or Age of Villages — none has a second City, none has a Castle, and
only one is even 1% armed (Weapons sit at ~0 everywhere), while tier-4/5
civilian goods (Glass, Leather, Furniture, Wine) are produced in quantity and
most realms hold 3–16 regions and 6–10 Towns. Two things follow. First, the
ladder has the headroom the request asks for — "late game" is genuinely a long
way off because the top rungs (City upgrade, Castle, an armed levy) are almost
never climbed. Second, and this is the part slice 2 must own: those top rungs
are not *reached* because they are under-exercised — the AI raises villages to
Towns prolifically but never raises a Town to a City and never runs a
Weaponsmith. That is the real "progression cliff" to address when the score is
wired into expansion, not a threshold tweak here.

Verification: `dev/test_progression.py` (project conventions: `SHAPES_SILENT=1`,
`dev/worlds/dev560.pkl`):

1. **Deterministic** — the score/age are pure functions: same world, same
   answer, and no randomness is drawn.
2. **Bounded & sane** — a starting faction lands in an early age (Homestead or
   Age of Villages); no faction scores an empty/negative development.
3. **Milestones gate correctly** — mutating a faction's settlements in place
   (add a Town → age advances; raise it to a City → advances again; add a
   Castle + weapons → Age of Cities) moves the age exactly as the ladder
   promises, and removing them moves it back.
4. **Score is monotonic** — adding population/towns/cities/regions never
   lowers the score.

Then the standing full suite (`HANDOFF.md:143`).

---

## 5. Slice 2 (next, not in this change) — governance capacity + pressure

- `governance_capacity(world, faction_idx)` derived from `development_score`:
  how many regions/villages the realm can hold *well*.
- `expansion.py:start_claim` replaces the `CLAIM_DEVELOPMENT_FRACTION` block
  with: below capacity claims are cheap/fast; above capacity they stay legal
  but cost more settlers/food, run slower, and the new region starts
  "under-governed" (lower yields, frontier unrest) until development catches
  up. The refusal message becomes the legible "govern distant land" line.
- **Pressure signal**: when villages are near capacity or food is tight, the
  region panel and alerts say "your people need land" — the *reason* to expand.

## 6. Out of scope (explicitly)

- No balance constants change in slice 1; the score is observation-only and is
  proven so by the fingerprint-style determinism test, not by a ledger.
- No worldgen, save-format, or sim-behaviour change.
- Ages do not gate any building/claim yet — that is slice 2's job.
