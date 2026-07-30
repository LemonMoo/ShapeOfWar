# Shapes of War v0.3.7

Every world used to be built the same way: a handful of shapes placed on the
map, noise smeared over their edges to make them look less like shapes. It
worked, but there was never a *reason* a mountain range or a coastline was
where it was.

World generation is tectonic now.

---

## The map is built from moving plates

Before any land or sea exists, the world is divided into tectonic plates —
some continental, some oceanic — each drifting in its own direction. Where
they meet, what happens depends on how they're actually moving relative to
each other:

- **Two plates colliding** raises a real mountain range along the line where
  they meet.
- **An ocean plate sliding under a continent** carves a coastal trench on the
  ocean side and a mountain range on the continental side — the same
  subduction process that built the Andes.
- **Plates pulling apart** open a rift valley, or a mid-ocean ridge if neither
  side is land.
- **A handful of plates carry a hotspot** — a point fixed in place that the
  plate drifts *over* — leaving a trailing chain of islands, each one older
  and smaller than the last. It's the same mechanism that built the Hawaiian
  islands.

None of this is decorative. A mountain range you see on the map is there
because two plates are pushing into each other right along that line, and the
biome/climate systems read it the same way they always have — the geology
just has an actual cause now.

Land is still exactly 40% of the map, every time, same as before.

## A first pass, not a finished tuning

This is new enough that it's worth being upfront: some worlds come out with
land more fragmented into small scattered islands than intended, and
river/lake density has shifted a little from the last release and hasn't
been re-tuned to match yet. Both are actively being worked on. What *is*
solid is the geology itself — where a mountain range or a coastline actually
forms, and why.
