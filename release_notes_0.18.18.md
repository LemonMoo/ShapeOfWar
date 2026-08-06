# v0.18.18 — The Map Is a Seamless Sea

The world's east-west wrap no longer meets itself with a ruler-straight
cut of ocean.

The map has always been a cylinder, and the noise fields under it were
already periodic — but the seam itself was a straight, perfectly vertical
band of deep ocean, so scrolling past the edge read as hitting an abrupt,
artificial line. Now the seam is a **wandering deep channel**: its
centreline meanders down the map like a real strait (a few gentle waves,
seeded per world), and the elevation falloff follows the curve, so
coastlines and depth contours run with the meander instead of parallel to
a straight edge. The channel floor varies along its length too — deep
pools and shallower sills — so it reads as geography rather than a
rendered fade.

Everything that made the old seam safe still holds, by construction:

- **The seam stays open ocean at every latitude** — land still never
  straddles the east-west wrap, so regions, roads and trade lanes keep
  all their no-crossing assumptions.
- **Same world size, same land fraction** — only the shape of the channel
  changed, not the amount of map it takes.
- **Deterministic** — the same world seed reproduces the same meander,
  cell for cell.

Also fixed along the way: a frontier event ("wanderers") could crash when
a claim's faction had no settlements anywhere to take them in — it now
quietly passes instead.

(Seam-shape before/after, per seed, measured by `dev/coastline_metrics.py`:
trench wander 0–2.5 → 8.7–12.3, channel depth variation 0.000–0.003 →
0.023–0.036, seam ocean 100% before and after.)
