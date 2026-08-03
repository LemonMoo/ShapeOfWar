# v0.13.1 — Let Us Out

A one-word fix for a bug that made the game unplayable from the moment you
opened it.

**The game booted straight into the Credits screen, and nothing would leave
it.** The Credits view was attached to the application window instead of to
the frame every other screen lives in, which put it in a different stacking
order — permanently on top of everything. Closing it raised the menu
underneath a screen that was still covering the whole window, so the button
appeared to do nothing.

It shipped in v0.12.0 and survived v0.13.0. If you launched either of those
and could not get past the credits, this is why, and this fixes it.

`dev/test_screens.py` is new and asserts the structure rather than the
symptom: every screen shares one parent, a fresh launch is showing the menu
with nothing stacked over it, and every screen that can be opened can be
closed again. It fails on the old code and passes on this one.

Everything in v0.13.0 — the underworld, holds and warrens, marching through
gates, darkness, the food economy — is unchanged and is now reachable.
