# v0.18.27

Time and Tide: the clock that could freeze, and the sea that shelves at
every shore.

## The clock always moves now

- **Fixed: a new game could sit on day 1 forever.** The world runner was
  born with the first world of the session, and never rebound when a new
  game (or a load) replaced it — so a second game, easiest to hit as a
  dwarf or goblin start after any earlier game, kept quietly advancing the
  *previous* world while the realm on screen never left Spring 1, Year 1.
  New games and loads now rebind the runner to the world actually on
  screen, and open paused, exactly like the first game always did.

## The sea shelves at every shore

- **Coasts slope out to sea.** Water now ramps up over a shallow shelf
  from every beach instead of dropping straight to depth at the waterline
  — a coast reads as a coast, not a cliff into the abyss.
- **The current carves its own coastline.** Where the longshore flow runs
  fast or accelerates (a headland squeezing the streamlines, a channel
  mouth funnelling them) it cuts; where it slackens (a sheltered bay, the
  lee of a headland) it lays down spits and bars. The carving compounds
  over three passes — shaped by the current, not by coincidence of noise.

---

**Changelog 118.**
