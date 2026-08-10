# v0.18.23 — A Real Map Preview

- Load menu: the map preview on save select is now an actual map. It shipped
  showing only a 30x30 corner of the world (usually the seam ocean) because
  the per-cell drawer could not fit a full 1100x660 world into the 120px
  box. The preview now uses the same thumbnail renderer as the New Game
  screen — a miniature of the whole map, with ocean depth, lakes and rivers,
  your realm in its own colour, and a ring on the capital.
