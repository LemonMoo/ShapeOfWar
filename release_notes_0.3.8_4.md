## v0.3.8_4 - Fixed a Real Stutter on Large, Developed Saves

- FIXED: panning/zooming the flat map could pause for 100-150ms+ on a big kingdom. Root cause (found from a user-submitted timing log): the GPU flat map's per-frame work creates lots of small, short-lived Python objects, which was enough to periodically trigger a full garbage-collection scan of the *entire world* -- regions, villages, settlements, roads, everything. The world is now frozen out of that scan entirely once a game loads, so only the actual per-frame garbage gets scanned.
