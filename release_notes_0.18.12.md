# v0.18.12 — Under the Mountain

Dwarves and Goblins now **truly live under the mountain**. Their capital is
the underground hold (or warren) itself — not a surface city with a cave
bonus underneath it.

- At worldgen, a cave realm's only above-ground settlement is a **gate
  town** at the doors: that is where caravans and commanders anchor, while
  the realm's seat — the great hall — sits deep beneath, and the founding
  chronicle fires there.
- The **New Game preview** for a Dwarf or Goblin start now says whether the
  site sits over a cave network and ranks cave-over sites first: pick a
  mountain with caves beneath, and your city *is* under it.
- Cave players open the map on the **Underworld layer**, looking at their
  own capital.
- A cave realm whose mountains have no reachable cave network (rare —
  mostly AI scatter) falls back to a plain surface capital rather than
  starting homeless.

Also fixed, two genuine underground economy bugs:

- **The terrace food chain was broken for holds.** Villages are planted
  deep (that's what defensible means), and the per-region terrace model
  left every holding in a doorless region unable to reach a single terrace
  cell — holds slowly ate their larders dry. Terraces are now a
  whole-network asset shared across the claimed galleries, and holds feed
  themselves again.
- **The underground mining inheritance was dead.** A gallery under an iron
  range offered no ore because industry was camp-gated and no camp could be
  built below. The rock overhead is now the mine itself: a hold under a
  range mines it, one under chalk doesn't, and no surface building family
  is offered below.
