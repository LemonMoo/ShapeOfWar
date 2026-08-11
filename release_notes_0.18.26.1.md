# v0.18.26.1 — A Lighter Day

The world thinks faster. Nothing about *what* it thinks changes — the same
days, the same routes, the same economy — but thinking it costs less, and
the map keeps up.

- **The door stops being re-found every day.** A cave realm's lifeline —
  food down to the hold, ore and gems up to the gate town — used to
  re-search its route through the mountain from scratch on every single
  day. It is now computed once and reused until the tunnels or roads
  actually change: carve a new tunnel or finish a new road and the route
  is recomputed, nothing more. The search itself is about 4x faster to
  run. On a developed world a whole day now costs about 30% less sim
  time — a faster day, a faster save, and a shorter stall before a
  battle.

- **A trade lane that can't connect gives up fast.** When two ports have
  no land or sea route between them, the game used to search the whole
  map before admitting it. A cost-free connectivity check now runs first
  and stops that search almost immediately; a connected route is computed
  exactly as before, bit for bit.

Covered by the day-steps fingerprint gate (`dev/test_turn_slice.py`,
`dev/bench_turn.py --fingerprint`), a 200-case old-vs-new route
equivalence check, and the under/gate suites (`dev/test_under_move.py`,
`dev/test_gate_lifeline.py`, `dev/test_holds.py`).
