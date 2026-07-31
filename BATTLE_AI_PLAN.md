# Battle movement AI — the plan

Five things were asked for, and they are one problem seen from five sides:
**every soldier in this sim is an independent agent that runs at its own
best-scored enemy in a straight line.** Nothing in `Unit.update` knows that the
soldier belongs to a formation, that an ally is standing in the way, or that a
cavalryman and a swordsman should not solve "get to that enemy" the same way.
The collision solver then makes the consequences visible: a blob.

So the work is a **movement layer between "who am I fighting" and "where do I
put my feet"** — which does not exist today — plus per-role use of it.

## What each ask maps to

| ask | today | what it needs |
|---|---|---|
| less swarmy armies | every unit seeks its own target; the army has no shape | cohesion: hold a place in the line, don't all converge on one point |
| path around allies | straight line at the target; collisions shove the rest out | local avoidance — slide around a blocking ally instead of into it |
| cavalry ride through | on impact, the rally point is set **straight back the way it came** (`_begin_cycle_withdraw`) — literally bouncing off | continue through, exit the far side, wheel, come in on a **new** angle |
| archers hold a line | archers get HOLD/ADVANCE individually and each walks to its own best target | a real firing line with slots, like the shield wall but for missiles |
| specials feel special | `order_ai` groups by role but every special still *moves* like a swordsman | per-role movement: anchor, flank, bombard, seek the thickest fight |

## Grounding

Kept to how the real thing worked, per this project's standing practice:

- **A line advances as a line.** Roman, Greek, medieval, early modern — the
  unit of manoeuvre was the formation, not the man. Individual soldiers running
  ahead of the line is what a rout looks like, not an attack. Cohesion is
  therefore the default, and breaking it should be a consequence, not the
  opening state.
- **Cavalry rode through.** A charge that stopped in the enemy line was a
  failed charge; the drill was to ride through, reform in the rear, and come
  again from a fresh direction — which is exactly what "not bouncing off like
  a fly" means. Repeated charges at the same face of a formation is the thing
  cavalry manuals warn against.
- **Archers shot from a line.** Massed shooting is a line phenomenon: shafts
  arrive together and the frontage is what makes them count. A clump of archers
  wastes most of its own frontage and blocks its own shooting.
- **Specialists were used for one job.** A sapper is not a bad archer; he is a
  man who breaks up a packed formation. This is already how the *stats* are
  written (see `unit_types.py`) — it is the movement that ignores it.

## Phases

Each phase is built, tested and committed on its own, same discipline as the
weather and biome reworks. Nothing here changes a unit's stats — this is
movement and target choice only, so the species roster's tuning is not being
re-fitted underneath.

### Phase 1 — cohesion and ally-aware movement (`app/battle/movement.py`, new)

One new pure module: given a unit, its desired direction, and its neighbours,
return the direction it should actually walk. Three terms:

1. **seek** — toward the target/move point, as today.
2. **separation** — push away from allies inside a personal-space radius, so a
   line stops compressing into a knot.
3. **avoidance** — if an ally sits inside a short forward cone, steer around
   the side it is *not* on rather than into its back.

Plus an **anti-swarm rule**: a unit whose target already has as many allies in
contact as can physically reach it stops closing and holds at line distance,
instead of joining a pile that cannot swing. This is the movement half of what
`_CROWD_PENALTY` already does in target *scoring*.

Neighbour lookup reuses the spatial hash the collision solver already builds
each tick, hoisted so both use one grid — no new O(n²) pass, and the sim's
frame budget is the reason the whole layer is written as a couple of vector
adds rather than real pathfinding.

**Test:** `dev/test_formation.py` — line width after contact, mean nearest-ally
distance (a blob has a small one), and a hard assertion that nobody walks
through an ally's occupied space when a clear side exists.

### Phase 2 — cavalry ride through and wheel

`_begin_cycle_withdraw` becomes `_begin_ride_through`: keep the current heading
until clear of enemy bodies (or a distance cap), then pick the next approach
**angle**, deliberately offset from the one just used, and re-accelerate along
it. `densest_enemy` still chooses *what* to hit; this chooses *from where*.

**Test:** `dev/test_cavalry_cycle.py` — successive charges arrive on
meaningfully different bearings, a rider crosses the formation rather than
reversing at contact, and momentum is genuinely rebuilt before the next impact.

### Phase 3 — archer firing line

`Battle.form_firing_line(units)`: slots perpendicular to the enemy, wider
spacing than a shield wall, ranks staggered so a rear rank is not standing
behind a front-rank body. Archers in a slot shoot whatever is in reach from
where they stand rather than walking at a chosen target. The order AI issues it
in place of the current per-archer HOLD.

**Test:** `dev/test_firing_line.py` — frontage is wide and depth is shallow,
slots are held under fire, and archers still fall back on the ordinary
behaviour when the line is overrun.

### Phase 4 — specials act like their role

Each reads its existing type flags; no new stats.

- **Shieldwarden** — anchors: positions at the front of the nearest friendly
  cluster, between it and the enemy, so its damage-taken aura covers a line
  instead of walking out of one.
- **Standard Bearer** — stands where its aura covers the most allies, behind
  the line's centre, and moves with it.
- **Bladesinger** — skirmisher: prefers an enemy flank or an isolated body,
  declines to grind at the centre of a formed line.
- **Berserker** — the inverse: seeks the thickest fight and ignores separation.
- **Sapper** — bombardier: holds at its own (short) range and drops bombs on
  the densest enemy knot, which is what its splash is for.
- **Assassin** — keeps `hunts_ranged`, but now goes *around* the line rather
  than through it, which is the thing that has always killed it.

**Test:** `dev/test_special_roles.py` — each is a structural assertion about
position and choice, never a win rate.

### Phase 5 — measure, then ship

One tournament pass for direction only (5 games, `--isolate`), the numbers
**recorded** rather than asserted on — a win rate over a handful of battles is
noise, and this project has failed builds on that mistake twice. Then the full
39-script suite, a release, and HANDOFF.

## Risks, named up front

- **This will move species balance.** Cohesion helps whoever fights in a line
  (Dwarves, Humans) and ride-through helps the cavalry species. The roster was
  fitted to blob behaviour, so some of its tuning is fitted to the bug. The
  numbers get recorded and handed over; they do not get chased here.
- **Frame budget.** Everything added is per-unit-per-tick. The steering must
  stay a handful of arithmetic ops against a grid lookup that already exists,
  and the phase is not done until a large battle is re-timed.
- **"Richer rules measured worse" is on the record** for the *order* AI (§4 #4
  of HANDOFF). This is deliberately not that: no new stances are being issued,
  and the changes are to how a unit walks, not to what it is told to do.
- **Every constant here is a first pass**, to be judged in play. They are
  gathered at the top of `movement.py` for exactly that reason.
