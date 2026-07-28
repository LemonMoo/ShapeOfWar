# Shapes of War v0.2.1

A follow-up to v0.2.0: Towns and Cities get the panel redesign that Villages
received, and a real problem with older saves is fixed.

---

## Towns & Cities

Settlement panels now use the same folding cards as Villages — **Summary,
Build, Industry, Storage, Held** — instead of the run-on wall of text they were
still using. Moving between a city and one of its villages no longer means
relearning the panel.

- **New: INDUSTRY card.** Shows what a settlement is actually converting right
  now, and at what rate — `Logs → Planks 30/turn`, `Gems → Jewelry 2/turn`. It
  answers a question the old panel couldn't: *why is my city sitting on Wheat
  with no Bread?* Preserving House curing shows here too, and when nothing is
  running it says so plainly.
- **Storage** shows the four typed pools as meters, replacing an aggregate total
  that stopped meaning anything once space became typed.
- **The Shipyard** moved into the Build card, alongside everything else you can
  build there.
- Card fold state is shared and remembered as you click between settlements.

## Fixed: older saves were quietly crippled

Worlds saved before storage became typed (v0.2.0) carried enormous stockpiles
accumulated under the old single shared pool. On a real save, one city held
**1,472,676 space of household goods against a 3,300 capacity**, and 1,278,435
durable against 3,200.

That did drain on its own — but it took roughly **80 turns**, and for every one
of those turns the affected settlements were throttled to **zero production**
while their meters read solid red. Then all of it was destroyed anyway.

On first load, that legacy overflow is now spilled into whatever spare capacity
the realm actually has, and only what genuinely has nowhere to go is discarded.
Measured on that save, over the following 60 turns:

| | before | after |
|---|---|---|
| Population change | −4,731 | **−1,960** |
| Starving settlements | 196 | **128** |
| Storage-overflow alerts | 405 | **55** |

Ordinary overflow is deliberately left alone. A settled realm running a few
percent over on its timber is the overflow rule working as designed, not
damage — only genuine hoards well past capacity are touched, and the migration
runs once per world.
