# Shapes of War v0.2.6

A performance release. Battles are handed to the graphics card, the battle
simulation stops being quadratic, and End Turn gets nearly three times faster on
a large realm.

---

## Battles are drawn by the GPU

The battlefield used to be rebuilt every frame as thousands of individual canvas
items — one per soldier, plus two more for its sword and shield. That is why
per-soldier equipment switched itself off past 160 living units: at that point
the glyphs alone were most of the frame.

The whole field is now **one instanced draw call**. Every soldier, weapon, arrow
and spark is an instance of the same quad, expanded by the GPU.

- **Every soldier keeps its kit, at any army size.** The detail cutoff is gone.
- Measured on a real battle: **15 fps → 141 fps** at ~590 living units, with full
  equipment drawn throughout.
- Machines without a working GPU context fall back to the old canvas renderer
  automatically — including mid-session, if a context is lost. Nothing stops
  working.

## The simulation stops being the bottleneck

Rendering was never the only cost. Target selection scanned every living enemy
for every unit, which is quadratic: quadrupling an army raised its cost about
twentyfold, and it — not the drawing — was what actually capped battle size.

It now scores the entire enemy army in one vectorised pass.

| Army size | Simulation before | Simulation after |
|---|---|---|
| 1,000 | 116 fps | **241 fps** |
| 2,400 | 30 fps | **91 fps** |
| 4,700 | 6.7 fps | **31 fps** |
| 9,000 | 1.5 fps | **8.7 fps** |

Armies of around **5,000 are playable**, where roughly 1,000 was the practical
ceiling before.

> **Battle outcomes shift slightly in this version.** Target selection now reads
> unit positions from the start of each tick rather than partway through it —
> which is how the anti-dogpile count already worked, so targeting is internally
> consistent for the first time rather than half-live. Battles remain fully
> reproducible from a given starting point.

## End Turn is 2.8x faster

On a 300-region realm, a turn went from **1,199ms to 424ms**.

- Storage-class and bulk lookups are memoised — they are pure functions of a
  resource name and were being called nearly a million times per turn.
- Region adjacency is computed once instead of on every call. Region *shapes*
  never change after worldgen; only who owns them does.
- The expansion AI no longer rescans a faction's entire territory once per
  frontier region. That single fix was the largest share of the win.

This one is verified **identical**, not merely faster: ownership, stockpiles,
population and faction stats were hashed across ten turns before and after, and
match exactly. It is a pure speed change with no effect on the game.
