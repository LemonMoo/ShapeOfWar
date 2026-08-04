# v0.17.1

A frame-rate pass. The map was running on a ~60fps timer with the Windows
default 15.6ms clock granularity, and it showed: the visible rate drifted
toward 30-40fps on a 60Hz screen and panning fell behind the mouse. The world
driver now targets 200fps scheduling and paces itself to whatever your display
can actually show.

- **The world driver now targets up to 200 FPS** (1ms timer resolution
  requested at launch, adaptive frame scheduling). The map animates and pans
  at the full rate of your display instead of a drifting 30-40.
- **FIXED: drag-pan renders were unthrottled** — motion events fired a render
  per event as fast as the loop could go, so the map visibly fell behind the
  cursor while dragging. Drags now render at the frame target, coalescing all
  mouse movement inside each frame.
- **New setting: frame-rate mode.** Settings (main menu or pause) now has a
  Display section: **Smooth (vsync)** paces the visible rate to the monitor's
  refresh with no tearing — the default — and **Uncapped** lets the map run at
  the full 200 FPS (smoothest on a display whose refresh is that fast; may
  tear otherwise). Applies immediately; remembered between sessions.

The world itself is unchanged: a day is still a day, saves load as before, and
the simulation ticks correctly at any frame rate.
