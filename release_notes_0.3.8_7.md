## v0.3.8_7 - GPU Flat Map Was Hiding All Your HUD Panels

- FIXED: the resource bar, faction panel, alerts, treasury and trade log were being drawn UNDER the GPU flat map instead of over it, making the whole HUD invisible the moment the map activated. The GL surface is created lazily on first use, well after the panels are built and raised, and a new widget joins the top of its parent's stacking order by default -- it just needed to be sent back to the bottom, where the old canvas always was.
