# v0.16.5

The map finally reads as a place, not a faction-coloured blur. Terrain is
distinctive at every zoom and in every view:

- **New fantasy palette**: each of the twelve biomes has its own colour
  family -- violet mountains, deep-emerald forest, teal taiga, tropical
  jungle, olive swamp, amber desert, ice tundra, seafoam coastal. Water
  re-inked to match (deeper ocean, brighter shallows, lake and river blues
  pulled apart).
- **Per-biome terrain texture**: the terrain raster now carries procedural
  detail -- blotchy forest canopy, desert dune ripples, frost mottle,
  wet swamp patches, rocky mountain flecks. Deterministic, so the map
  never flickers when ownership changes.
- **Terrain symbols on the political map**: trees, reeds, cacti, acacia,
  peaks and hills for ten biomes, now drawn on the GPU flat map too, with
  a legend on both surfaces.
- **Political view tints harder and smarter**: each biome pulls its owner's
  colour toward the biome's own hue, so a desert reads warm and a forest
  reads green even under a faction whose flag is olive.
