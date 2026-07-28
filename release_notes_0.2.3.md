# Shapes of War v0.2.3

Two big changes. Commanders stop being map decoration and become the thing your
army is built around — and claiming wildland stops being a pure Gold tax you
can't afford, becoming something that pays for itself.

---

## Commanders lead armies

Your army is tied to your commander. You cannot attack a rival or claim wildland
unless your commander is standing in one of your regions bordering the target —
no more armies materialising anywhere on the map you happen to click.

- The panel tells you **why** an attack is refused and where to march to fix it,
  instead of silently offering no targets.
- Every faction has one, AI included, and the AI now marches its commander
  toward what it intends to take.

They're real units on the battlefield now, not just a vision radius: a large
8-pointed star, far tougher than a line soldier, projecting an aura that buffs
every friendly unit around them.

| Species | Commander | Character |
|---|---|---|
| Humans | Marshal | All-round buff to the line |
| Elves | Warden | Ranged; extends your archers' reach |
| Dwarves | Thane | Enormous HP; soaks damage for the line |
| Orcs | Warchief | Heaviest hitter; cleaves through groups |
| Goblins | Chieftain | Fast and evasive |

Losing your commander mid-battle breaks your army's morale on the spot — damage
and speed both drop for the rest of the fight. And a fallen commander is really
gone: the realm cannot attack or claim **at all** until a successor takes the
field 12 turns later at your capital.

Species commanders were tuned across a full battle tournament; the win-rate
spread between species narrowed from about 45 points to about 17.

---

## Claiming land pays for itself

Claiming wildland was a pure Gold check, and a punishing one. Instrumenting the
expansion AI showed **90% of all its claim attempts failing on affordability
alone**, against 0.2% blocked by anything else.

A claim is now an expedition rather than a purchase. Most of the bill is the
timber and stone the crew actually consumes raising palisades and the first
buildings on unsettled ground:

- **25 Gold, 30 Logs, 12 Stone**, plus a small per-cell rate.
- Gold for a typical region falls from about **199 to 44**.

**Winning the fight now seizes spoils.** You take roughly 10 turns of whatever
that region produces, delivered straight into its new villages — so rich land is
worth more than a bog. The Gold taken is 1.8× what you paid, plus a bounty per
point of garrison strength.

So a land claim you win **returns more Gold than it cost**. Measured across all
400 wildland regions on a test map: every one is net-positive, median +54 Gold.
That's the point — early expansion is meant to be how a young realm generates
coin and gets its economy moving, rather than every kingdom simply starting with
a heap of it. The margin per claim is small and compounds over a campaign.

Amphibious claims are deliberately excluded from the profit: spoils are pinned to
the land price, so crossing the sea still runs about 222 Gold in the red and
stays a real commitment rather than a way to farm coin.

The claim panel previews the spoils and the net Gold before you commit, and the
post-battle message reports what was seized.

### No realm sealed in by geography

Because the bill is now mostly materials, a realm founded on barren ground would
have been permanently stuck — so every region scrapes together a trickle of Logs
and Stone each turn regardless of biome. This mattered more than expected: **64%
of regions were producing no Stone at all**, which is why simply cutting the
price hadn't helped them.

It's a floor, not a bonus. A region working real forest or a quarry is far above
it and gains nothing, so it can't re-inflate the timber hoards that storage
throttling exists to contain.

On a late-game test map, factions able to afford a frontier claim went from 2 of
14 to 8 of 14.
