# v0.18.3 — Dated Ledger

The Trade Log and the Treasury's "RECENT TURNS" now timestamp entries by
in-game date instead of a bare turn number — e.g. "Winter 18, Year 3" —
so you can actually track when a deal happened across the seasons.

- Trade Log turn dividers: "Turn 126" → "Summer 1, Year 2".
- Treasury RECENT TURNS rows: same date formatting.
- The date derivation is the game's own (same season/day/year math the
  persistent year counter uses), so the log always agrees with the
  banner in the corner.
