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
from app.world import buildings as B
from app.world import construction
from app.world import resources as R

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "worlds", "dev560.pkl")
w = pickle.load(open(PATH, "rb"))
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
    return [wdg for wdg in walk(widget) if isinstance(wdg, tk.Button)]


def card_for(win, label):
    """The card frame whose own header names `label`. Every build button reads
    "Build — tier N", so finding one by its own text alone would pick whichever
    building happened to be laid out first.

    Matched on the header's DIRECT children only. Searching the header
    subtree matches the grid container too (its first child is the first card,
    whose header is one level further down), and the grid holds every button
    in the window."""
    for frame in walk(win):
        if not isinstance(frame, tk.Frame):
            continue
        children = frame.winfo_children()
        if not children or not isinstance(children[0], tk.Frame):
            continue
        for wdg in children[0].winfo_children():
            try:
                if str(wdg.cget("text")) == label:
                    return frame
            except tk.TclError:
                continue
    return None


print("\n--- the window builds for both node kinds ---")
windows = []
for node in (village, settlement):
    win = build_menu.BuildMenuWindow(_root, w, node, nation)
    win.update_idletasks()
    windows.append(win)
    all_text = " | ".join(texts(win))
    assert node.name in all_text, "the window doesn't name the place it is for"
    assert "PRODUCTION" in all_text and "BUILDINGS" in all_text, all_text[:400]
    options = B.build_options(w, node, nation)
    for option in options:
        assert option.label in all_text, f"{option.label} has no card"
    assert len(buttons(win)) >= 2, "expected at least Close plus one build button"
    print(f"  ok    {B.node_kind(node):<10} {node.name:<16} "
          f"{len(options)} cards, {len(buttons(win))} buttons")

print("\n--- an unaffordable card is disabled, not missing ---")
win = windows[0]
opts = {o.building: o for o in B.build_options(w, village, nation)}
unaffordable = [o for o in opts.values()
                if o.to_tier is not None and not o.affordable and not o.blocked]
if unaffordable:
    labels = [b.cget("text") for b in buttons(win)]
    target = unaffordable[0]
    match = [b for b in buttons(win)
             if f"tier {target.to_tier}" in str(b.cget("text"))]
    assert match, (target.label, labels)
    assert any(str(b.cget("state")) == "disabled" for b in match), (
        f"{target.label} is unaffordable but its button is enabled")
    print(f"  ok    {target.label} unaffordable -> button disabled")
else:
    print("  --    the player can afford everything here; skipped")

print("\n--- a needed building is flagged, and sorts first ---")
orig = dict(getattr(village, "resources", {}) or {})
try:
    cap = R.node_pool_capacity(village, "household")
    village.resources = {"Barley": int(cap / R.resource_bulk("Barley")) + 10}
    win = build_menu.BuildMenuWindow(_root, w, village, nation)
    win.update_idletasks()
    windows.append(win)
    joined = " | ".join(texts(win))
    assert "NEEDED NOW" in joined, "an over-full pool didn't raise an urgent card"
    assert "full of Barley" in joined, "the card doesn't say what is filling it"
    first = B.build_options(w, village, nation)[0]
    assert first.building == "granary", first
    print(f"  ok    urgent card present and first: {first.label} — {first.reason}")
finally:
    village.resources = orig

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
    granary_btn = next(b for b in buttons(card)
                       if str(b.cget("state")) != "disabled")
    granary_btn.invoke()
    win.update_idletasks()
    after = len(construction._storage_projects(w))
    assert after == before + 1, (before, after)
    started = construction._storage_projects(w)[-1]
    assert started.building == "granary" and started.node_id == village.id, started
    print("  ok    invoking the Granary card's button queued exactly that project")

    # And the card must now read as under construction rather than offering
    # the same tier a second time.
    card = card_for(win, "Granary")
    assert "Under construction" in " | ".join(texts(card)), texts(card)
    assert not [b for b in buttons(card) if "tier" in str(b.cget("text"))], (
        "a building under construction is still offering a Build button")
    opt = next(o for o in B.build_options(w, village, nation)
               if o.building == "granary")
    assert opt.in_progress and opt.to_tier is None, opt
    print("  ok    the card re-rendered as under construction, with no button")
finally:
    w.storage_projects = [p for p in construction._storage_projects(w)
                          if not (p.node_kind == "village" and p.node_id == village.id)]
    village.resources = orig

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
# The wheel binding is bind_all, so a closed window must not leave one behind
# that scrolls a dead canvas.
other.update_idletasks()
other.event_generate("<MouseWheel>", delta=120)
print("  ok    reopened cleanly; the surviving window still handles the wheel")

for win in windows + [other, reopened]:
    try:
        win.destroy()
    except tk.TclError:
        pass
_root.update_idletasks()
_root.destroy()
print("\nBUILD MENU TEST PASSED")
