# v0.18.4 — Earned Growth

Growth is now the real currency of your realm. The ladder is
**population-gated**: a Village must grow to half its population ceiling
before it can be raised to a Town, and a Town to two-thirds before it can
become a City. Frontier communities (Villages and Towns) grow far faster
than established Cities, so a fed and sheltered village reaches its first
rung in about a year of game time — and the village/settlement panels now
show how far along each community is toward its next rung.

Also in this release:

- **Fixed:** an impossible labor order (e.g. "fish" with no water in
  reach) now falls back to Auto exactly — the fallback previously skipped
  the storage-feedback loop and silently shifted a worker.
- **Fixed:** the AI was planting whole Cities in empty regions instead of
  climbing the ladder. It now founds villages, raises them to Towns, then
  upgrades to Cities in order — rival realms raise real Towns now.
