# v0.19.1

The Road to the Gate: a village road ends at the city it is meant for.

## Roads reach the door

- **A founded surface village's road now anchors at the nearest surface
  node — for a cave realm, the gate town actually sitting on its mountain
  gate — instead of the nearest faction village of any layer.** A hold's
  other villages live UNDERGROUND, at (x, y) positions on the mountainside
  beside the front gate; a surface road anchored at one of those ended a
  cell or two off to the side of the city, looking like the road stopped
  beside the gate instead of at it. An under node is not addressable from
  the surface at all, so it can never be the anchor of a surface road.
- **Same rule for settlements:** a village with no village to reach still
  connects to its realm through the nearest surface settlement, not through
  a hall under the mountain.
- **Regression-tested** against a generated dwarf hold: a village founded
  on the bare surface around the gate now draws its road to the gate town,
  and the test fails if the road ever terminates at an underground node
  again.

---

**Changelog 120.**
