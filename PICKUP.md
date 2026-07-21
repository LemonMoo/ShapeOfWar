# Pickup notes — Shapes of War

Read this first, then `README.md` for architecture/extension points. Skip
`HANDOFF.md` unless you need deep background — it's a long onboarding doc
written for a different, weaker external tool; this file is the fast path.

## Status right now

- 2 commits: `01f19b0` (initial), `55e9090` (village view).
- **Uncommitted changes in `app/ui/map_view.py` and `app/world/worldgen.py`**
  (see "This session" below). Ask the user if they want these committed
  before doing anything else — don't commit without being asked.
- `git status`/`git diff --stat` to see the live diff.

## Run / build

```
python main.py                 # from source (needs Pillow)
build.bat                       # rebuilds dist\ShapesOfWar.exe (PyInstaller)
```

## What it is

Standalone Tkinter desktop game, no art assets (Canvas shapes only). Two
scales: a procedurally generated fantasy world map (World → Country → County
→ Village, click-to-zoom) and a real-time shape-based battle simulator.
Battles and the map are **not yet connected** — that's the next big feature
(see below).

## This session (uncommitted)

1. **River mouth blending fix** — rivers now fade to the *correct* water
   color (ocean vs lake, previously always ocean) and the fade segments use
   `smooth=True` consistently with the base line (was causing a visible seam).
2. **Border chaos tuning** — territory/county growth cost field rebalanced
   toward high-frequency noise (`_cost_field` in `worldgen.py`), so borders
   are jagged/torn with enclaves instead of smooth curves. Was too straight
   before; now confirmed visually much more organic.
3. **Black coastline outline + river shadow casing** — every land cell
   touching water gets darkened (~-0.8 shade); rivers draw a dark casing
   pass underneath the colored fill so they "pop" and adjacent rivers' fades
   don't clip into each other.
4. **FPS investigation** — zoom animation (World↔Country↔County↔Village) was
   ~25fps because `render()` fully deletes and recreates ~1000 canvas items
   every frame (~40ms), dominated by river drawing. Fixed with a **level-of-
   detail flag**: while `self._animating` is true, rivers draw as a single
   plain line (skip shadow + mouth-fade); full detail renders once on
   settle. Verified ~20ms during animation, ~45ms on settle (one-time, not
   per-frame, so it doesn't read as choppy).
5. **Tried and reverted: caching river canvas items + `coords()`/
   `itemconfigure()` reposition instead of delete+recreate.** Measured
   *slower*, not faster (45.6ms → 49.6ms, clean isolated A/B). Reason: Tk's
   canvas only gets a dirty-region win from `coords()` when items move a
   *small* local distance; our zoom rescales the whole view every frame, so
   old/new bounding boxes barely overlap and Tk repaints almost everything
   regardless — plus the approach doubled Tcl calls per river. **Don't
   re-attempt this** without a different angle (e.g. only cache items that
   truly don't move, or reduce item *count* instead of item *lifecycle*).
   The comment block above the river-drawing code in `map_view.py` documents
   this so it isn't retried blindly.

## Suggested next step if performance still matters

Not yet tried: cull rivers below some pixel-length threshold at low zoom
(they're imperceptible anyway) — reduces item *count*, which is the one
lever that actually helps in Tk's canvas model, unlike caching.

## The real next feature (user's stated direction)

Counties were explicitly built as "the future unit of control" — winning a
battle staked on a border county should transfer it (and its settlements) to
the victor, updating both factions' stats. Currently `battle:over` only
updates a status message. This is the natural thing to build next if asked.

## Operational notes

- **User plays games on their primary monitor.** For any visual
  verification, target the **second monitor** directly instead of grabbing
  the primary display: `[System.Windows.Forms.Screen]::AllScreens` in
  PowerShell to find it (was at `X=1920,Y=0,1920x1080` this session, may
  differ). Launch a scratch script with `app.geometry("1550x950+1930+40")`,
  screenshot only that monitor's region, don't touch the primary.
- Scratch/diagnostic scripts go in the scratchpad temp dir, never in the
  repo. Headless smoke tests (`python -c "..."`) first, then a real
  screenshot for anything visual — don't trust either alone.
- PyInstaller build sometimes fails with a file-lock error if a previous
  `ShapesOfWar.exe` is still running — `Get-Process ShapesOfWar | Stop-Process
  -Force` first.
- Performance numbers in this file are single-machine, noisy (±30-50%
  run-to-run) — trust relative comparisons (A vs B in the same test) over
  absolute ms figures.
