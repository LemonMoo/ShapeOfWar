# v0.17.3

Smoothing the day's simulation. On a developed world the heaviest daily
economy phases each ran as one long, unbroken call -- several of them took
longer than a single frame, so once a day (or more) the map visibly hitched
for a frame or two. The work is the same; it is now sliced across frames the
way the real-time design intends.

- **The daily economy phases are now sliced to frame-budget size.** Regional
  trade, settlement-to-city sales, and the per-region local logistics each
  chunk their work and hand the frame back between chunks -- same results,
  same balance, no more multi-frame freeze on the day those phases run.
- **Finer slices on the production loop** and the domestic-trade phase (16
  regions / 8 nodes per slice), so a single chunk stays inside the frame
  budget even on a late-game world.
- Verified by the turn-slice fingerprint: a day run in slices is byte-for-byte
  the same world as a day run whole (dev/test_turn_slice.py).

The remaining brief hitches are the two phases that *cannot* be split without
breaking the world's coherence -- a province changing hands, and the first
path-search of a brand-new trade route -- plus road/settlement construction
finalization. All are rare and small on a mid-size world.

The world itself is unchanged: a day is still a day, saves load as before.
