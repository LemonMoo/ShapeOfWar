# Shapes of War v0.2.5

Battles stop being something you watch and start being something you fight. You
can now give orders in the middle of one — and so can the enemy.

---

## Orders

Select troops (drag a box, or press 1/2/3/4) and command them while the fight is
running. **Space pauses**, so you can stop, read the field, and give several
orders at once.

| Order | Who | What it does |
|---|---|---|
| **Hold Here** | everyone | Stand braced. Takes only **42%** of a cavalry charge's impact *and* its splash |
| **Charge** | everyone | +30% speed, +15% damage — but your guard drops |
| **Shield Wall** | Swordsmen | Dresses a real line facing the enemy, shields up |
| **Charge & Regroup** | Cavalry | Hit, pull out, then charge the thickest formation on the field |
| **Hold Fire / Fire at Will** | Archers | Draw a volley worth up to **+150%** on release |

They're built as counters, not as four buffs. Bracing is the answer to horse.
Charging is the answer to a static line — at the cost of your shield. A shield
wall only counts *contiguous* neighbours, so a wall that gets broken up stops
protecting, and since shields only ever block frontally, walking around one still
beats it.

Holding fire only builds a volley while something is actually in range, so it
costs you shots rather than being a free opening salvo.

**The enemy uses all of this too.** AI armies brace when your cavalry commits,
cycle their own horse, and time their volleys. Orders are a toolkit, not a
player-only advantage.

---

## Dwarves charge behind the shield

Every other species drops its guard to run. A dwarven line does not — and you can
watch arrows visibly glance off it as it comes on. They are the one army that can
cross open ground under fire without paying for it.

## Goblins get the Assassin

Twin daggers, the fastest thing on foot, and a hunter of **archers specifically**:
an Assassin will run straight past a shield line and refuses to touch a swordsman
until the last enemy archer on the field is dead. Its opening blow on each victim
lands at **3.5x**.

They're funded from three places — a little off the bows, a little off the line,
and a few granted free as a species bonus.

Goblin dodge is partly restored (0.15 → 0.17) after the previous cut proved far
too harsh, and they swing a little faster. Assassins are slipperier still, at
0.22.

**Elves** have had their attack speed reduced. An all-archer roster that never has
to close was winning 92% of its matchups.

---

## Fixes

**Commanders were being shoved around the battlefield.** A commander in contact
with a ring of soldiers took a half-share of the overlap from every one of them,
so the crowd bodily carried him — measured on a losing side, one was transported
most of the way across the field and pinned against the far edge for over twenty
seconds before dying. Collisions now account for mass (a commander weighs nine
soldiers), and he holds behind his own line rather than walking into the enemy —
which is what the game has always claimed he does. Commander losses in testing
fell from 10 in 16 to 5 in 16.

**Battles were not reproducible.** The collision solver ordered units by memory
address, which changes every run, so the same battle from the same starting point
could resolve differently — and quietly invalidated balance measurement. Fixed
with a stable per-unit ordinal.
