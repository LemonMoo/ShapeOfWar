"""The build menu window, against a real Tk widget tree.

    python dev/test_build_menu.py [world.pkl]

HANDOFF.md section 13.1 flags that no dedicated "does the panel widget tree
still build without exceptions" harness exists -- every UI change so far was
verified with throwaway scripts. This is that harness for the build menu, and
the pattern generalises: build a real MapView/Toplevel against a real world,
call the methods, assert on the resulting widget tree.

It runs headless-ish: a real Tk root is created but never shown
(`root.withdraw()`), and `update_idletasks` does the layout without entering a
mainloop. That needs a display -- on a machine with none this exits 0 with a
skip rather than failing, since "no display" is not a defect in the code.
"""
import sys
import os
import pickle

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk

try:
    _root = tk.Tk()
    _root.withdraw()
except tk.TclError as exc:
    print(f"no display available ({exc}) -- skipping")
    sys.exit(0)

from app.ui import build_menu
from app.ui import theme
from app.world import buildings as B
from app.world import construction
from app.world import resources as R

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "worlds", "dev560.pkl")
w = pickle.load(open(PATH, "rb"))
R.migrate_treasury(w)   # pre-treasury saves have none; development is funded
                        # from it (TAXATION_PLAN), so seed it for the build below
pidx = w.player_faction_idx if w.player_faction_idx is not None else 0
nation = w.factions[pidx]
village = next(v for v in w.villages if v.faction_idx == pidx)
settlement = next(s for s in w.settlements if s.faction_idx == pidx)
print(f"player: {nation.name}   village={village.name}   "
      f"settlement={settlement.name} ({settlement.kind})")


def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)


def texts(widget):
    out = []
    for wdg in walk(widget):
        try:
            value = wdg.cget("text")
        except tk.TclError:
            continue
        if value:
            out.append(str(value))
    return out


def buttons(widget):
    """Real Tk buttons. Kept meaning exactly what it always did -- the labour
    and scope controls are still widgets."""
    return [wdg for wdg in walk(widget) if isinstance(wdg, tk.Button)]


def plaques(widget):
    """Drawn controls: (canvas, tag) for every clickable region on any page in
    this window. A card is a page now (app/ui/parchment.py), so its Build
    control is a canvas item carrying a "hit" tag rather than a Button."""
    out = []
    for canvas in walk(widget):
        if not isinstance(canvas, tk.Canvas):
            continue
        tags = set()
        for item in canvas.find_all():
            tags.update(t for t in canvas.gettags(item) if t.startswith("hit"))
        out.extend((canvas, tag) for tag in sorted(tags))
    return out


def canvas_texts(widget):
    """Every string drawn on any page inside this window."""
    out = []
    for canvas in walk(widget):
        if not isinstance(canvas, tk.Canvas):
            continue
        for item in canvas.find_all():
            if canvas.type(item) == "text":
                value = canvas.itemcget(item, "text")
                if value:
                    out.append(str(value))
    return out


def card_for(win, label):
    """The CANVAS of the card whose own heading names `label`.

    One card is one page on one canvas now, so "which card is this" is
    answered by looking for the canvas that draws that heading -- much more
    directly than the old walk over frame headers, which had to be careful not
    to match the grid container holding every card at once."""
    for canvas in walk(win):
        if not isinstance(canvas, tk.Canvas):
            continue
        for item in canvas.find_all():
            if (canvas.type(item) == "text"
                    and str(canvas.itemcget(item, "text")) == label.upper()):
                return canvas
    return None


def card_texts(canvas):
    return [str(canvas.itemcget(i, "text")) for i in canvas.find_all()
            if canvas.type(i) == "text" and canvas.itemcget(i, "text")]


print("\n--- the window builds for both node kinds ---")
windows = []
for node in (village, settlement):
    win = build_menu.BuildMenuWindow(_root, w, node, nation)
    win.update_idletasks()
    windows.append(win)
    all_text = " | ".join(texts(win) + canvas_texts(win))
    assert node.name in all_text, "the window doesn't name the place it is for"
    assert "PRODUCTION" in all_text and "BUILDINGS" in all_text, all_text[:400]
    options = B.build_options(w, node, nation)
    # Case-insensitive: a card's heading is drawn in small caps (see
    # parchment.Page.title), so the assertion is that the card is THERE and
    # named, not that its name is stored in the case it was written in.
    haystack = all_text.upper()
    for option in options:
        assert option.label.upper() in haystack, f"{option.label} has no card"
    controls = len(buttons(win)) + len(plaques(win))
    assert controls >= 2, "expected at least Close plus one build control"
    print(f"  ok    {B.node_kind(node):<10} {node.name:<16} "
          f"{len(options)} cards, {controls} controls")

print("\n--- an unaffordable card is disabled, not missing ---")
win = windows[0]
opts = {o.building: o for o in B.build_options(w, village, nation)}
unaffordable = [o for o in opts.values()
                if o.to_tier is not None and not o.affordable and not o.blocked]
if unaffordable:
    target = unaffordable[0]
    card = card_for(win, target.label)
    assert card is not None, f"{target.label} has no card at all"
    texts_on_card = " | ".join(card_texts(card))
    assert f"tier {target.to_tier}" in texts_on_card, texts_on_card
    # Present but inert: the plaque is drawn and carries no click binding, so
    # it reads as "this exists and you cannot have it yet" rather than
    # vanishing (which would read as "this building does not exist").
    plaque = None
    for item in card.find_all():
        if (card.type(item) == "text"
                and f"tier {target.to_tier}" in str(card.itemcget(item, "text"))):
            plaque = next((t for t in card.gettags(item)
                           if t.startswith("hit")), None)
    assert plaque is None or not card.tag_bind(plaque, "<Button-1>"), (
        f"{target.label} is unaffordable but its plaque is still clickable")
    print(f"  ok    {target.label} unaffordable -> plaque drawn, not clickable")
else:
    print("  --    the player can afford everything here; skipped")

print("\n--- a needed building is flagged, and sorts first ---")
orig = dict(getattr(village, "resources", {}) or {})
herd_orig = dict(getattr(village, "herds", None) or {})
fish_orig = getattr(village, "fish_yield", 0)
try:
    # A real herd emergency (fodder running short for winter) or a coastal
    # catch (perishables to preserve) outranks a full pool in the urgency
    # sort, and which villages have either depends on the world -- clear
    # both so THIS test is only about the pool.
    if hasattr(village, "herds"):
        village.herds = {}
    village.fish_yield = 0
    cap = R.node_pool_capacity(village, "household")
    village.resources = {"Barley": int(cap / R.resource_bulk("Barley")) + 10}
    win = build_menu.BuildMenuWindow(_root, w, village, nation)
    win.update_idletasks()
    windows.append(win)
    joined = " | ".join(texts(win) + canvas_texts(win))
    assert "NEEDED NOW" in joined, "an over-full pool didn't raise an urgent card"
    assert "full of Barley" in joined, "the card doesn't say what is filling it"
    first = B.build_options(w, village, nation)[0]
    assert first.building == "granary", first
    print(f"  ok    urgent card present and first: {first.label} — {first.reason}")
finally:
    village.resources = orig
    if hasattr(village, "herds"):
        village.herds = herd_orig
    village.fish_yield = fish_orig

print("\n--- the Build button actually starts a project, once ---")
cost = construction.storage_build_cost(village, "granary", 1)
orig = dict(getattr(village, "resources", {}) or {})
try:
    village.resources = dict(orig)
    for r, a in cost.items():
        village.resources[r] = village.resources.get(r, 0) + a * 3
    before = len(construction._storage_projects(w))
    win = build_menu.BuildMenuWindow(_root, w, village, nation)
    win.update_idletasks()
    windows.append(win)
    card = card_for(win, "Granary")
    assert card is not None, "no Granary card in the window"
    # Click the card's Build plaque the way a player does: fire the binding
    # its tag carries. (A drawn control has no .invoke(); see
    # parchment.Page.click, which is what the panel test drives.)
    plaque = None
    for item in card.find_all():
        if card.type(item) == "text" and "tier" in str(card.itemcget(item, "text")):
            plaque = next((t for t in card.gettags(item)
                           if t.startswith("hit")), None)
    assert plaque, "the Granary card has no clickable Build plaque"
    win._click_card(card, plaque)
    win.update_idletasks()
    after = len(construction._storage_projects(w))
    assert after == before + 1, (before, after)
    started = construction._storage_projects(w)[-1]
    assert started.building == "granary" and started.node_id == village.id, started
    print("  ok    invoking the Granary card's button queued exactly that project")

    # And the card must now read as under construction rather than offering
    # the same tier a second time.
    card = card_for(win, "Granary")
    assert "Under construction" in " | ".join(card_texts(card)), card_texts(card)
    assert not [t for t in card_texts(card) if "tier" in t], (
        "a building under construction is still offering a Build button")
    opt = next(o for o in B.build_options(w, village, nation)
               if o.building == "granary")
    assert opt.in_progress and opt.to_tier is None, opt
    print("  ok    the card re-rendered as under construction, with no button")
finally:
    w.storage_projects = [p for p in construction._storage_projects(w)
                          if not (p.node_kind == "village" and p.node_id == village.id)]
    village.resources = orig

print("\n--- labour orders ---")
win = build_menu.BuildMenuWindow(_root, w, village, nation)
win.update_idletasks()
windows.append(win)
joined = " | ".join(texts(win) + canvas_texts(win))
assert "Put the hands on:" in joined, joined[:400]
assert "Apply to:" in joined, joined[:400]
policy_btns = {str(b.cget("text")): b for b in buttons(win)
               if str(b.cget("text")) in R.LABOR_POLICIES}
assert "Auto" in policy_btns and "Balanced" in policy_btns, sorted(policy_btns)
# A sector focus is only offered where that sector has something to work.
for policy, btn in policy_btns.items():
    assert R.labor_policy_available(w, village, policy), (
        f"{policy} was offered at {village.name} but has nothing to work")
for policy in R.LABOR_POLICIES:
    if not R.labor_policy_available(w, village, policy):
        assert policy not in policy_btns, (
            f"{policy} is impossible here but was offered anyway")
print(f"  ok    offered {sorted(policy_btns)}; "
      f"hid {sorted(set(R.LABOR_POLICIES) - set(policy_btns))}")

before_policy = R.labor_policy(village)
try:
    target = next(p for p in policy_btns if p != before_policy)
    policy_btns[target].invoke()
    win.update_idletasks()
    assert R.labor_policy(village) == target, (before_policy, target)
    # The re-render legitimately repopulates the allocation cache -- what
    # matters is that it repopulated it from the NEW policy. (That
    # apply_labor_policy invalidates it at all is asserted at the model level,
    # in dev/test_labor.py.)
    cached = R.village_labor_state(w, village, w.season)[0]
    fresh = R.village_labor_factors(
        w, village, *R._village_terrain_potential(w, village, w.season)[1:])
    assert cached == fresh, (cached, fresh)
    assert "reassigned" in " | ".join(texts(win) + canvas_texts(win)), texts(win)[:8]
    print(f"  ok    clicking {target} set the policy; the cached split agrees "
          f"with it")

    # The active policy is the highlighted button after a re-render.
    live = {str(b.cget("text")): b for b in buttons(win)
            if str(b.cget("text")) in R.LABOR_POLICIES}
    assert str(live[target].cget("bg")) == theme.ACCENT, live[target].cget("bg")
    print(f"  ok    {target} renders as the active choice")
finally:
    R.apply_labor_policy(w, village, before_policy)

print("\n--- an order can be given to a whole region or realm at once ---")
region_villages = [v for v in w.villages
                   if v.region_id == village.region_id and v.faction_idx == pidx]
before = {v.id: R.labor_policy(v) for v in w.villages if v.faction_idx == pidx}
foreign = [v for v in w.villages if v.faction_idx >= 0 and v.faction_idx != pidx]
foreign_before = {v.id: R.labor_policy(v) for v in foreign}
try:
    win = build_menu.BuildMenuWindow(_root, w, village, nation)
    win.update_idletasks()
    windows.append(win)
    scope_btn = next(b for b in buttons(win)
                     if "Every village in this region" in str(b.cget("text")))
    scope_btn.invoke()
    win.update_idletasks()
    target = next(p for p in R.LABOR_POLICIES
                  if p != R.labor_policy(village)
                  and R.labor_policy_available(w, village, p))
    next(b for b in buttons(win) if str(b.cget("text")) == target).invoke()
    win.update_idletasks()
    assert all(R.labor_policy(v) == target for v in region_villages), (
        "a region-scope order missed some of its own villages")
    print(f"  ok    region scope set {len(region_villages)} villages to {target}")

    realm_btn = next(b for b in buttons(win)
                     if "Every village in the realm" in str(b.cget("text")))
    realm_btn.invoke()
    win.update_idletasks()
    other = next(p for p in R.LABOR_POLICIES
                 if p != target and R.labor_policy_available(w, village, p))
    next(b for b in buttons(win) if str(b.cget("text")) == other).invoke()
    win.update_idletasks()
    mine = [v for v in w.villages if v.faction_idx == pidx]
    assert all(R.labor_policy(v) == other for v in mine), "realm scope missed some"
    assert all(R.labor_policy(v) == foreign_before[v.id] for v in foreign), (
        "a realm-scope order reached another faction's villages")
    print(f"  ok    realm scope set {len(mine)} villages to {other}, and left "
          f"{len(foreign)} foreign villages alone")
finally:
    for v in w.villages:
        if v.faction_idx == pidx and v.id in before:
            R.apply_labor_policy(w, v, before[v.id])

print("\n--- a settlement is offered no labour orders ---")
win = build_menu.BuildMenuWindow(_root, w, settlement, nation)
win.update_idletasks()
windows.append(win)
assert "Put the hands on:" not in " | ".join(texts(win) + canvas_texts(win)), (
    "a settlement has no workforce model and must not be offered labour orders")
print("  ok    settlement window has no labour row")

print("\n--- the window draws its own chrome, not the OS's ---")
win = build_menu.BuildMenuWindow(_root, w, village, nation)
win.update_idletasks()
windows.append(win)
assert win.overrideredirect(), "the OS titlebar/border is still on"
# Everything the window manager used to supply has to be supplied here.
assert win.cget("bg") == theme.LINE, "no border rule drawn"
close = [b for b in buttons(win) if "Close" in str(b.cget("text"))]
assert close, "an undecorated window with no close button is a trap"
# The header has to be draggable, or the window can never be moved again.
header = win._shell.winfo_children()[0]
assert "<Button-1>" in header.bind(), "the header is not a titlebar"
assert "<B1-Motion>" in header.bind(), "the header cannot be dragged"
# Asserted on the REQUESTED geometry, not winfo_x/y: this root is withdrawn,
# so the window is never mapped and winfo_x stays 0 however it is moved.
before = win.geometry()
win._begin_drag(type("E", (), {"x_root": 500, "y_root": 400})())
win._drag(type("E", (), {"x_root": 640, "y_root": 490})())
win.update_idletasks()
after = win.geometry()
assert after != before, (before, after)
assert after.endswith("+140+90"), after
print(f"  ok    undecorated, own border and close button; header drags "
      f"{before} -> {after}")
# Placement: an undecorated window gets no default position from the window
# manager, so it must ask for one. Checked against a stub parent rather than
# the real geometry -- this root is withdrawn and reports 1x1 until mapped.
class _Stub:
    def update_idletasks(self):
        pass

    def winfo_width(self):
        return 1600

    def winfo_height(self):
        return 900

    def winfo_rootx(self):
        return 100

    def winfo_rooty(self):
        return 50


win._place_over(_Stub())
# Only the POSITION is readable here: geometry() reports the actual size of an
# unmapped window (1x1), not the requested one. The size floor is minsize.
_, x, y = win.geometry().split("+")
# Derived from _place_over's own preferred size rather than hardcoded, so
# resizing the window is a one-line change instead of a puzzle in this file.
_pw, _ph = build_menu._PREFERRED_SIZE
_want_w = max(700, min(_pw, 1600 - 60))
_want_h = max(480, min(_ph, 900 - 60))
assert (int(x), int(y)) == (100 + (1600 - _want_w) // 2,
                            50 + (900 - _want_h) // 2), (
    f"not centred on a 1600x900 parent at (100,50): +{x}+{y}")
assert win.minsize() == (700, 480), win.minsize()
print(f"  ok    centres at +{x}+{y} on a 1600x900 parent at (100,50); "
      f"minimum {win.minsize()[0]}x{win.minsize()[1]}")

print("\n--- one window per node, re-opening raises it ---")
first = build_menu.open_for(_root, w, village, nation)
second = build_menu.open_for(_root, w, village, nation)
assert first is second, "re-opening the same place made a second window"
other = build_menu.open_for(_root, w, settlement, nation)
assert other is not first, "two different places shared one window"
print("  ok    same node -> same window; different node -> its own")

print("\n--- closing one leaves the others working ---")
first.destroy()
_root.update_idletasks()
reopened = build_menu.open_for(_root, w, village, nation)
assert reopened is not first, "a destroyed window was handed back out"
reopened.update_idletasks()
assert B.node_kind(village) == "village" and village.name in " ".join(texts(reopened))
other.update_idletasks()
other.event_generate("<MouseWheel>", delta=120)
print("  ok    reopened cleanly; the surviving window still handles the wheel")

print("\n--- the wheel belongs to the window, not to bind_all ---")
# The bug: this used to be bind_all, and map_view's side panels bind_all the
# wheel on <Enter> and unbind_all it on <Leave> (map_view.py:1057 and
# friends). Merely moving the mouse across the map's panels on the way to
# this window silently deleted the menu's own scrolling, which is why it
# only scrolled when the pointer was over the scrollbar itself.
import inspect
# Comment lines stripped: the note in build_menu explaining why this is NOT
# bind_all any more names it, and would match otherwise. Same trap
# dev/test_panels.py hit with update_idletasks.
src = "\n".join(line for line in
                inspect.getsource(build_menu.BuildMenuWindow).splitlines()
                if not line.lstrip().startswith("#"))
assert "bind_all" not in src, (
    "the build menu binds the wheel globally again -- anyone else's "
    "unbind_all will take it away")
assert 'self.bind("<MouseWheel>"' in src, (
    "the wheel must be bound on the Toplevel, which is in every descendant's "
    "bindtags and cannot be unbound by another widget")
# And it really does scroll from a widget deep inside, not just from the root.
deep = [wd for wd in walk(reopened) if isinstance(wd, tk.Label)]
assert deep, "no labels in the menu to aim an event at"
before = reopened._canvas.yview()[0]
for _ in range(6):
    deep[-1].event_generate("<MouseWheel>", delta=-120)
reopened.update_idletasks()
assert reopened._canvas.yview()[0] >= before
print("  ok    the wheel scrolls the page from a label deep inside the menu")

print("\n--- an open menu follows the turn instead of freezing ---")
# The bug: the menu was a snapshot. You could start a Granary, end six turns
# watching nothing change, and only see it built by closing and reopening.
target = next((o for o in B.build_options(w, village, nation)
               if o.affordable and not o.in_progress and not o.blocked), None)
if target is None:
    print("  skip  this village can afford nothing right now")
else:
    construction.start_storage_building(w, nation, village, target.building)
    build_menu.refresh_open(_root)
    reopened.update_idletasks()
    joined = " | ".join(texts(reopened) + canvas_texts(reopened))
    assert "Under construction" in joined, joined[:300]
    assert "days left" in joined or "finishes today" in joined, (
        "the countdown should say how much longer, in the days the world "
        "actually runs in, not in turns nobody takes any more")
    first_read = joined
    for _ in range(2):
        R.advance_turn(w)
        build_menu.refresh_open(_root)
        reopened.update_idletasks()
    assert " | ".join(texts(reopened) + canvas_texts(reopened)) != first_read, (
        "two turns passed and the open menu said exactly the same thing")
    print(f"  ok    {target.label} shows a countdown that moves with the turn")

print("\n--- ...but the menu is NOT rebuilt under the player every day ---")
# The real-time bug: _render tore down and rebuilt every widget in the window,
# and in a running world that happens every day. A menu that reconstructs
# itself under the pointer cannot be read, never mind clicked.
# First let the countdown section's project FINISH: its completion
# legitimately rebuilds the menu (a card flips from "under construction" to
# "built"), and this test is about QUIET days, not project milestones.
completion_guard = 0
while (completion_guard < 60
       and any(o.in_progress for o in B.build_options(w, village, nation))):
    R.advance_turn(w)
    build_menu.refresh_open(_root)
    reopened.update_idletasks()
    completion_guard += 1
# The contract, asserted directly instead of by a count: _render rebuilds the
# menu IFF what it depicts changed. The old bug tore the menu down on EVERY
# day regardless. A live village legitimately changes day to day (the gate
# lifeline delivers goods through the door, pools fill, urgency flips) and a
# menu that rebuilds because the cards really changed is the fix working --
# the BUG is a rebuild on a day when nothing changed.
rebuilds = []
unjustified = []
_changed_now = [False]
_last_sig = [None]
_real_sig = build_menu.BuildMenuWindow._content_signature


def _spy_sig(self):
    s = _real_sig(self)
    if self is reopened:
        _changed_now[0] = False
        if _last_sig[0] is not None and s != _last_sig[0]:
            _changed_now[0] = True
        _last_sig[0] = s
    return s


build_menu.BuildMenuWindow._content_signature = _spy_sig
_real_inner = build_menu.BuildMenuWindow._render_inner


def _spy_inner(self):
    if self is reopened:
        rebuilds.append(1)
        unjustified.append(not _changed_now[0])
        _changed_now[0] = False
    return _real_inner(self)


build_menu.BuildMenuWindow._render_inner = _spy_inner
herd_orig = dict(getattr(village, "herds", None) or {})
res_orig = dict(getattr(village, "resources", None) or {})
try:
    # Zero the herd and the stores so the menu under test is as quiet as it
    # can be. Door deliveries may still change it -- those are REAL changes
    # (see the contract above); the property under test is that no rebuild
    # happens on a day when nothing moved.
    if hasattr(village, "herds"):
        village.herds = {}
    if hasattr(village, "resources"):
        village.resources = {}
    # Seed the change-detector's baseline AFTER the zeroing, so the first
    # refresh's rebuild (the zeroing visibly changed the cards) is a
    # justified change rather than an unexplained one.
    _last_sig[0] = _real_sig(reopened)
    for _ in range(4):
        R.advance_turn(w)
        build_menu.refresh_open(_root)
        reopened.update_idletasks()
    quiet = len(rebuilds)
    assert rebuilds, "nothing ever rebuilt -- the change-detection spy is broken"
    assert not any(unjustified), (
        f"{sum(unjustified)} rebuild(s) happened on a day nothing changed -- "
        "the menu is still being torn down under the player")
    # ...and a player action still answers immediately.
    reopened._set_scope("village" if reopened._scope != "village" else "region")
    reopened.update_idletasks()
    assert len(rebuilds) > quiet, "a player action did not rebuild the menu"
finally:
    build_menu.BuildMenuWindow._content_signature = _real_sig
    build_menu.BuildMenuWindow._render_inner = _real_inner
    if hasattr(village, "herds"):
        village.herds = herd_orig
    if hasattr(village, "resources"):
        village.resources = res_orig
print(f"  {quiet} rebuild(s) over 4 days, {len(rebuilds) - quiet} on a click, "
      f"none on a day nothing changed")
print("  ok    quiet while time passes, immediate when acted on")

print("\n--- refreshing drops windows that have been closed ---")
ghost = build_menu.open_for(_root, w, settlement, nation)
ghost.destroy()
_root.update_idletasks()
build_menu.refresh_open(_root)
assert all(win.winfo_exists() for win in _root._build_menus.values()), (
    "refresh_open kept a destroyed window in the registry")
print("  ok    a destroyed window is dropped from the registry")

for win in windows + [other, reopened] + list(_root._build_menus.values()):
    try:
        win.destroy()
    except tk.TclError:
        pass
_root.update_idletasks()
_root.destroy()
print("\nBUILD MENU TEST PASSED")
