# Shapes of War v0.2.0

A large release. The interface has been rebuilt around the map, livestock became
a real system with its own economy, storage was overhauled end to end, and the
numbers the game shows you now reconcile with what you actually own.

> **Version note:** this restarts the version scheme. Everything up to v0.12.3
> is the previous line; v0.2.0 begins the new one.

---

## Interface

- **The map is the base layer and fills the window.** Both side panels fold away
  to slim edge tabs, so you can hand the map the whole screen whenever you want
  to look at it.
- **Alerts are grouped by kind with a count**, instead of eight near-identical
  paragraphs sitting permanently over the map. Click a group to list the
  settlements affected; click a settlement to jump straight there. 150 alerts now
  read as three lines that name *every* problem — the old panel hid 142 of them
  behind "+142 more".
- **The resources sidebar groups into Food / Industry / Luxury**, with a
  **Needs Attention** block that promotes survival goods running low or falling
  fast. Thirty flat rows are now four lines that expand on click.
- **Settlement and village panels are folding cards** — Summary, Build,
  Production, Storage, Herd — with aligned figures and real meters in place of
  run-on prose. End Turn and the view controls are pinned, so build actions can
  no longer fall off the bottom of the panel.
- **The Trade Log is a tab you open**, not an empty black box parked on the map.

## Livestock & herds

- **Herds belong to Villages now**, not regions, and run on the season: births in
  Spring, hay cut in Summer, the cull in Autumn, and Winter fed from stored
  Fodder.
- **Fodder is a new Crop** with its own Barn storage. It grows on plains and
  competes with food crops for the same land.
- **A village that cannot feed its herd through Winter loses it** — culled down
  to what the hay covers (you still get the Meat and Leather), and the remainder
  lost outright.
- **Cull policy per village** — Grow / Balanced / Cull — sets how hard you
  harvest each Autumn.
- **Four new village buildings:** Pasture, Barn, Stable and Slaughterhouse.
- **Horses finally matter.** They add a cavalry bonus to military strength, and a
  realm holding enough of them puts its Commanders in the saddle (5 → 8 cells a
  turn). Unlike Weapons and Shields you cannot smith a horse — it has to be bred,
  fed and not culled.
- **Livestock can be traded.** Buy breeding stock from a neighbour to restock
  after a hard Winter.
- Meat no longer arrives once a year and rots within six turns; it comes four
  times a year, and a Preserving House cures it into **Salted Meat**.

## Storage

- **Space is typed:** Granary (food, firewood), Warehouse (timber, ore, goods),
  Vault (gold, luxuries) and Barn (fodder) — each with its own building and
  upgrade tiers. A timber glut can no longer crowd out your grain.
- **Goods take space by bulk.** A Log eats three times what a sack of grain does;
  gems and coin take almost nothing.
- **Production stops when there is nowhere to put it**, rather than being
  silently destroyed on arrival — so capacity now buys real output instead of a
  higher pile. Storage waste is down roughly three quarters.
- **Villages can build** their own storage, and upgrade it.
- **Preserving Houses** cure Fish, Milk and Meat into forms that keep, burning
  Salt to do it.

## Gold

- **A new Treasury panel** (click the Gold row) shows where your gold is, how
  much is actually spendable, how much is riding home on a caravan, and a
  per-cause breakdown of every coin gained or spent.
- **The trade log marks rows where no coin moved**, so an internal barter
  transfer stops reading as income you never received.

## Conquest

- **Taking a nation's last region removes it from the world** — from the map,
  from diplomacy and from trade. Its part-built works and trade routes pass to
  the conqueror.
- **Losing your own last region ends the game.**

## Fixes

- Conquering a region banked a phantom copy of its goods in a national pool that
  nothing could spend from, so the resources sidebar overstated what you owned.
- The Compendium's growth-cycle line rendered as `Plant: —, Growing: —` for every
  crop in the game.
- The realm panel reported "RESOURCES: None yet." while the sidebar beside it
  listed thirty.
- Map rendering culls off-screen detail: deep zoom draws a fraction of the canvas
  items it used to, and region/village views are roughly 1.5x faster.

## Compendium

Rewritten for all of the above, including a new **Livestock & Herds** article.
Building costs, storage capacities, bulk values and herd figures are all read
from the live game data, so they cannot drift out of sync with the rules.
