# v0.18.11 — Claims That Work, Villages That Connect

## Claiming is repaired

A variable-shadowing bug in the expansion gate made every claim — yours
*and* every rival's — start on the realm's **last owned region** instead
of the wildland target you clicked. The result: claims never actually
began, clicking the same frontier repeatedly piled up dead projects (and
paid the cost every time), and no realm on the map could genuinely
expand. Fixed at the root:

- Claims now target the land you clicked.
- Repeat clicks are refused ("A claim is already underway there.").
- Stale completed claims on land a rival has since taken are retired
  instead of accumulating.
- A commander that marched into unclaimed wildland now authorises claims
  from where it physically stands, instead of being treated as absent and
  blocking every claim.
- The wildland panel tells you up front when your commander needs to
  march to the frontier first — no more silent failures on click.

## Villages connect to the road network

A founded village is no longer an island: it is linked to nearby villages
with the same terrain-aware road pathfinding the city-growth path uses,
and a village founded on bare claimed land gets a road to the realm's
nearest village or settlement instead of standing alone.
