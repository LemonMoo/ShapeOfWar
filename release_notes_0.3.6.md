# Shapes of War v0.3.6

A bug fix, a battle UI pass, and the globe stops looking like it's covered
in blobs.

---

## Fixed: your kingdom's name could quietly grow letters

If you typed your kingdom's name during setup and then played normally,
stray letters could get appended to it later — most noticeably an extra
**E** every time you pressed E to end a turn. The Realm Name field never
actually released keyboard focus once the game started; it kept silently
receiving keystrokes from behind the map screen and re-applying them to your
kingdom's name in real time (that live-update is what makes the name preview
work while you're still typing it — the bug was that it kept happening long
after you'd stopped). Fixed at the root: switching screens now always moves
keyboard focus properly, so nothing hidden keeps eating keystrokes.

## Villages and commanders are real 3D shapes on the globe now

Villages and commanders used to render as flat, camera-facing colored dots —
tolerable when a region held a handful of villages, but once village
placement stopped being capped, a developed region could carpet the globe in
a hundred identical blobs with no way to tell them apart. Both now use the
same real 3D pin geometry settlements already had: villages get a small
version of a settlement's spire, and your commander gets a distinct tall,
thin pin that never reads as "a tiny town."

## Battles deploy with an actual formation now

Default deployment used to just be whatever order happened to fall out of
the army's composition data — not a real formation. Swordsmen now anchor
the front line by default, Archers hang back, and everything else starts in
the middle. You can still drag anyone anywhere before deploying; this only
changes where the fight begins.

## Battle planning's select buttons match your actual species

The per-type quick-select row was hardcoded to a slot for Goblin Assassins
and nothing else — missing the Goblins' *second* signature unit (Sapper)
entirely, and showing nothing at all for Human, Elf, Dwarf, or Orc specials.
Every species now gets a button (and a hotkey) for each of its own signature
units, and every button — base troops and specials alike — shows a live
selected/alive count.
