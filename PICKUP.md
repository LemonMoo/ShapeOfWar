# Pickup notes — Shapes of War

Read this first. Skip `HANDOFF.md` (written for a different, weaker tool).
`README.md` covers architecture but is **stale** — it predates everything
below except the resource/turn-loop economy. Update it before trusting it
for diplomacy/trade/naval/castle mechanics.

## Status right now

- Last commit: `e788c3f`. **Everything below is uncommitted** — ask before
  committing. `git status` / `git diff --stat` for the live picture.
- Run: `python main.py` (source) or double-click `Play.bat` (rebuilds
  `dist\ShapesOfWar.exe` then launches it — prefer this over the raw exe or
  `build.bat` alone; a running exe can't rebuild itself on Windows).

## What it is now

Standalone Tkinter game. Procedural world (World→Country→County→Village)
plus a real-time shape battle sim, now tied together by a genuine turn-based
layer: species, economy, diplomacy, trade and construction all interact
through one `resources.advance_turn()` loop (the **End Turn** button).

## Built this session (chronological; one module each, read its docstring first)

1. **Fantasy species** — Humans/Elves/Dwarves/Orcs/Goblins (`lexicon.py`),
   species-flavored naming everywhere.
2. **Global trade routes** (visual land+sea lines, terrain-pathfound) —
   `worldgen._generate_trade_routes`.
3. **Territory conquest** — `territory.py` (`bordering_counties`,
   `naval_reachable_counties`, `transfer_county`), post-battle blink/flash +
   banner in `map_view.py`.
4. **Main menu / saves** — `main_menu.py`, `new_game.py`, `pause_menu.py`,
   `load_game_menu.py`, `app/core/save.py` (multi-slot, delete-save,
   `Play.bat` fixes a "saves vanish on exe close" onefile-temp-dir bug).
5. **Diplomatic-only foreign view** — own territory fully manageable;
   foreign nations read-only; double-click → Attack (if enemy) or county
   browsing (if not).
6. **Resource economy** — `resources.py`: 15 resources/4 tiers, biomes +
   climates (`worldgen.biome_grid`/`climate_grid`) + 4 seasons drive county
   yield; storage caps + spoilage; military/gold derived from real
   stockpiles; `advance_turn()` is the loop.
7. **Diplomacy** — `diplomacy.py`: numeric `standing` per relationship;
   Improve Relations / Fabricate Claim / Terrorize Locals (1/turn cooldown);
   Declare War / Form Alliance unlock at thresholds. Alliance requests are
   now **AI-evaluated** (`SPECIES_AFFINITY` table + resource complementarity
   can refuse) and grant real benefits (15% cheaper trade, 20% faster
   allied caravans). "Form Alliance" button correctly disappears once allied.
8. **Naval attacks** — `territory.naval_reachable_counties`: a coastal
   settlement (port) lets you invade non-land-adjacent "island" nations.
9. **Autonomous trade** — `trade.py`: Gold currency (settlement tax income);
   every faction independently prices/dispatches `TradeCaravan`s (land) or
   ships (sea) each turn, capped 3 concurrent/faction, greedy first-match.
   Capital-to-capital routes (cached), 5-20 turns each way (real-distance
   scaled), goods delivered + buyer pays on arrival, **seller paid only when
   the caravan gets home** — lost outright if the two go to war mid-transit,
   or raided crossing hostile third-party land. Safety-reserve rule (sized
   off real upkeep) means a faction physically can't sell food it needs.
10. **Player-built castles** — `construction.py`: costs Stone/Wood/Iron/Gold,
    ~15 turns at full speed, half speed until a connecting `RoadProject`
    (same terrain-aware pathfinding as trade routes, visibly grows a few
    cells/turn on the map) finishes. "Build Castle..." only in your own
    county view.

## Known simplifications (by design, not oversights)

- Trade/construction AI is greedy first-match, not an optimizer.
- Trade + castle roads run capital/nearest-settlement based, not arbitrary
  settlement-to-settlement — no per-settlement trade UI yet.
- Caravan/road risk is war-driven only — no bandits/piracy system.
- Only trade is autonomous — wars/alliances/attacks are still 100%
  player-triggered, no AI-initiated diplomacy yet.
- Save format keeps changing with each feature — old saves won't load, no
  migration path. Clear `saves/` if you hit load errors after a pull.

## Operational notes

- Test headless first, always: `App(); app.withdraw(); app.update()`, call
  methods directly, `app.update()` after each step, `app.destroy()` at the
  end. Only screenshot for final visual confirmation.
- **Careful with screenshots**: a full-screen grab can capture the user's
  real desktop, not just the app window (happened once this session —
  caught it, stopped doing blind full-screen captures). Prefer headless
  checks; if a screenshot is truly needed, confirm it's actually the app
  before relying on it.
- Clean up test saves after scripted runs: `rm saves/*.pkl saves/*.json saves/*.tmp`.
- PyInstaller build fails with a file-lock error if `ShapesOfWar.exe` is
  still running — `Get-Process ShapesOfWar | Stop-Process -Force` first.

## Natural next steps (not started)

- Player-initiated trade (pick resource/qty/destination yourself) — the
  pricing/safety-reserve engine in `trade.py` already supports it, just
  needs a UI entry point.
- Update `README.md` — stale since before diplomacy/naval/trade/castle.
- Tune constants (prices, thresholds, turn counts, AI weights) from actual play.
