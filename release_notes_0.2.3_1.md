# Shapes of War v0.2.3_1

A combat-feel patch on top of v0.2.3, plus a fog-of-war leak worth fixing on its
own.

---

## Lines stand and fight

Melee had a habit of turning into two formations shoving each other back and
forth across the field instead of actually fighting.

The cause: the springy collision impulse was driven by how much two units
overlapped, and nothing else. A packed melee overlaps on *every single tick*, so
the shoving never stopped — the longer a scrum lasted, the more it pushed.

Knockback now applies only while a unit is still closing on its target:

- A charge slamming into a line still lands with full force.
- Soldiers already locked in and trading blows hold their ground.

Fights resolve about **26% faster** as a result (58.5s to 44.2s across eight test
battles, all decisive). Units spend the fight killing each other rather than
being pushed apart.

> Also tried and rejected: anchoring the engaged rank so the whole overlap came
> out of the moving unit. It measured worse — displacing an advancing soldier
> further just made him rebound and come again, and front-rank travel after
> contact rose from 150px to 336px. The even split stays.

---

## Commanders read properly on the map

**Enemy commanders were visible through fog of war.** On a test save, 12 of 13
rival commanders could be seen marching across ground the player had never
explored. Their queued-path preview leaked their destination as well — you could
see where an enemy was headed over terrain you'd never scouted. Both are now
gated per cell, exactly like settlement markers.

**Rival commanders now wear their own realm's colour**, so a marker on the map
tells you whose army that is at a glance rather than every faction sharing one
hue. Your own keeps its distinct orchid — it's the one you give orders to, and it
should never be mistaken for a rival's.

On the battlefield, the Commander is now an oversized disc with a contrasting
centre, replacing the spiked star and its halo ring. The ring sat outside his
body and mostly read as clutter once a melee closed in around him.
