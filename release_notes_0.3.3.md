# Shapes of War v0.3.3

A follow-up to v0.3.2's globe work: the camera pitch didn't do what it was
supposed to, and a region-selection bug the last release notes didn't
mention yet is fixed. Also, the Balance Lab finally has a door into it.

---

## The globe flies lower

v0.3.2 added camera pitch, but it swung the eye around the *planet's*
center rather than tilting a close-up on the ground — so full zoom still
framed the whole globe, just from a wider angle. That's fixed: the camera
now hovers directly above the ground point you're looking at and tilts its
gaze from there, and the closest zoom is genuinely low over the surface
instead of low-orbit. Closing in finally reads as flying down to
somewhere, horizon and all.

## Fixed: region selection on the globe

Clicking a region while already in region view was silently kicking the
view back out to the world map instead of just highlighting the region —
it was quietly overwriting flat-map-only state on the way. Selecting a
region now does exactly what it looks like it should.

## Balance Lab has a front door

`dev/balance_lab.py` needed running by hand from a terminal. There's now a
"Balance Lab (dev)" button on the main menu that opens it directly — a
dev-only tool, so it doesn't appear in packaged builds. Note that it
edits a separate process's numbers: changes only reach a game you already
have open after you save and relaunch.
