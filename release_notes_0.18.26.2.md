# v0.18.26.2 — The Economy Is Readable

The economy always knew where every unit of every resource went. Now it
tells you.

- **The Ledger.** A new panel — open it from the RESOURCES bar header, or
  click any resource row — answers the question the resource bar never
  could: *where does my Wood go?* Every resource your realm holds is
  accounted for by cause across the year: produced, consumed, converted,
  spoiled, traded, built, raided. The causes always add up to the real
  stock change — the ledger is the simulation, measured at the day's own
  phase boundaries, not a parallel estimate that can drift from it.

- **The resource bar explains itself.** Hover any row and it tells you this
  year's breakdown, or why a raw material sits at zero: *"Blocked — no
  Woodcutters' Camp is built."* Storage cards show each good's spoilage
  rate and when fullness is slowing production (and by how much); village
  production cards show the ground-familiarity yield modifier and any
  camp-gated land sitting unworked.

- **The silent rules got voices.** A realm that burns coal for warmth or
  scrounges firewood is told, once a winter, with the quantities — coal
  burned is coal not sold. The camp gate that silently zeroed timber and
  ore is now a visible todo. Minted gold shows up in the ledger instead of
  appearing from nowhere.

- **The food-safety margin is now a dial.** The Ledger's *Food reserve*
  slider sets how many turns of need trade holds back before anything is
  sellable — the default 8 is exactly the game's original rule, and now
  "why won't my caravan sell this" has an answer you can change (1–30
  turns).

- **First hover-help in the game.** A floating tip layer sits on resource
  rows, storage cards and village production cards — the game's first
  tooltips anywhere.

This pass changes nothing simulated: every resource moves exactly as
before, proven by the day-steps fingerprint gate (`dev/test_turn_slice.py`)
and a new A/B test (`dev/test_econ_ledger.py`) that runs the same world
with the ledger recording and switched off and fingerprints them
identical. It is observation and presentation — and one small, reversible
player dial.
