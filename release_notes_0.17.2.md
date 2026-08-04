# v0.17.2

The GPU map is back. A missing import in the shared OpenGL code has been
silently disabling the GPU renderer since it was extracted from the old globe
view -- every build since then fell back to the slower Tk/PIL canvas renderer
on every machine, which is what the recent frame-rate work was fighting
against. Restoring it lands all of that work at once.

- **FIXED: the GPU map now actually runs.** A missing `import math` in the
  shared GL module made the GPU frame fail at construction on every machine,
  silently dropping the game to the Tk canvas fallback (an 11ms+ per-frame
  render -- and much worse at higher resolutions). With the GPU map active the
  same frame costs about 0.3ms, the movement and drag rendering hit the
  frame-rate target, and panning stops falling behind the mouse.
- **PERFORMANCE: the trade log no longer rebuilds hundreds of row widgets
  every day while it is closed** -- entries are still recorded and counted on
  the reopen plaque; the rows are built when you open the log.
- The 0.17.0/0.17.1 optimizations (fast terrain rebuilds, cached markers,
  frame-rate modes) were all built for the GPU path and now apply for real.

The world itself is unchanged: a day is still a day, saves load as before.
