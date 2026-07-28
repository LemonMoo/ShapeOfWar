# Shapes of War v0.2.2

The Treasury becomes a proper in-game panel, and a fix shipped in v0.2.1 is
corrected — it was doing more harm than good.

---

## Treasury is now in-game

It used to open as a separate desktop window, which meant it floated free of the
game, could be dragged off it entirely, and dropped behind the main window the
moment you touched the map. So you couldn't keep it open and watch it while you
ended a turn — which is exactly when its numbers are worth watching.

- Lives inside the game window and stays there. Drag it anywhere by its header;
  it can't be moved off the edge, and it re-clamps if you resize the window.
- Keeps its place while you pan, zoom, or fold the side panels away.
- **Leave it open across End Turn** and it rebuilds in step with the turn, so
  minting, trade income and construction spend land while you watch.
- Click the Gold row to toggle it open or closed.

## Correction: v0.2.1's legacy-save cleanup was harmful

v0.2.1 added a one-time cleanup for worlds saved before storage became typed,
which clamped over-capacity stockpiles down to capacity and **discarded the
excess**. That was wrong. Measured over 100 turns on a real save:

| | gold earned | population |
|---|---|---|
| No cleanup at all | +952 | −4,737 |
| **v0.2.1 (discards excess)** | +10 | **−5,198** |
| **v0.2.2 (moves only)** | **+952** | **−1,197** |

The discarded pile was the reserve the population had been eating, and it held
the Gold Ore the realm was minting from — so v0.2.1's cleanup was measurably
*worse than leaving the save alone*.

The cleanup now only **moves** goods into real spare capacity — settlements
first, since only they run the conversion recipes — and destroys nothing.
Anything that still can't be rehoused stays where it is and drains through the
ordinary overflow rule, so it can be eaten and converted on the way down rather
than deleted.

Saves that already went through v0.2.1's version are eligible for the corrected
pass. What it destroyed is gone, but any overflow still sitting in them now gets
rehoused instead of skipped.

**A note on what this doesn't do:** on a legacy save some settlements will still
show as over capacity, because the realm genuinely doesn't have room for that
much. That's a true number, and it drains on its own. Deleting your grain to
make a bar look green is what v0.2.1 did, and it cost you more than it saved.
