# v0.18.25 — Weather You Can See

The sky finally does something. Storms rain on the map, blizzards streak
snow, and fog banks drift over the land — drawn on the flat map and on the
canvas, alongside the outline and badge that already told you what the sky
was doing.

- **Physical precipitation.** A storm now rains on the map: pale rain
  streaks and dark cloud puffs over the affected region. A blizzard
  streaks snow, and fog drifts as soft banks. Drought gets no rain at all
  — the outline and the sun badge carry it. All of it is deterministic
  per region and turn, drawn only where the fog of war has lifted, and
  never below ground.

Lakes are water again — four things a lake is, and one it is not.

- **Not a road.** Foot commanders no longer march across a lake. A lake
  cell is not the ocean, but it is not land either — an army stops at the
  shore, and a stale save that was already mid-lake stops there too.
- **Not a beach.** A ship can't disembark its men onto a lake.
- **Not a home.** No realm starts in a lake: a player-chosen start that
  lands on a lake snaps to the nearest shore, and AI capitals are drawn
  from dry land only. (Settlements already refused to build on water.)
- **Exactly like the sea for the land around it.** Lake shores irrigate
  the surrounding land with the same fertility bonus as a coast, and a
  settlement near a lake gets the same water bonus as one near the sea.

Covered by `dev/test_weather_overlay.py` (all four weather kinds, drawn,
fog-gated) and `dev/test_screens.py`; the lake fixes were verified against
a generated world — no capital or settlement in a lake, a lake-pinned
player start snaps to shore, and commander pathfinding plus two full sim
days never put a commander on a lake.
