"""Phase 3 of the economy pass: a player stockpile-target policy.

    python dev/test_stockpile.py [world.pkl]

The fourth lever the user picked, alongside labour policy (Phase 1): how
much of a good a node holds back before local logistics/regional trade/
sell-to-city can carry any more of it away. This does NOT invent a new
"sell for gold" mechanic -- gold only ever comes from minting or a real
trading partner's treasury (see resources.py's Currency section) -- it
works by loosening/tightening the existing reserve every domestic tier
already reads through _node_surplus. Deliberately scoped to ordinary
discretionary goods only, never Food/Firewood/Clothes/Luxury/Timber, which
already have their own survival/upkeep reserve formulas.
"""
import sys
import os
import pickle

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import resources as R

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "worlds", "dev560.pkl")
w = pickle.load(open(PATH, "rb"))
pidx = w.player_faction_idx if w.player_faction_idx is not None else 0
st = next(s for s in w.settlements if s.faction_idx == pidx and s.population > 0)

print("--- an unset policy changes nothing ---")
before_res = dict(st.resources or {})
before_targets = dict(getattr(st, "stockpile_target", None) or {})
try:
    st.resources = dict(before_res)
    st.resources["Stone"] = 1000
    st.stockpile_target = {}
    needs = R.settlement_needs(st, w.season)
    default_surplus = R._node_surplus(st, "Stone", needs)
    assert R.stockpile_target(st, "Stone") is None
    assert R.stockpile_reserve(st, "Stone") is None
    print(f"  ok    no policy set -> surplus {default_surplus} "
          f"(the flat LOCAL_SURPLUS_RESERVE default)")

    print("\n--- a target raises or lowers the reserve, both directions ---")
    R.set_stockpile_target(st, "Stone", 0.5)
    tightened = R._node_surplus(st, "Stone", needs)
    assert tightened < default_surplus, (tightened, default_surplus)
    R.set_stockpile_target(st, "Stone", 0.0)
    loosened = R._node_surplus(st, "Stone", needs)
    assert loosened > tightened
    assert loosened == 1000, "a 0.0 target should offer up everything"
    print(f"  ok    0.5 target -> {tightened} spare, 0.0 target -> {loosened} spare "
          f"(default was {default_surplus})")

    print("\n--- clearing the policy returns to the exact default ---")
    R.set_stockpile_target(st, "Stone", None)
    cleared = R._node_surplus(st, "Stone", needs)
    assert cleared == default_surplus
    print(f"  ok    cleared -> {cleared}, matches the pre-policy default exactly")

    print("\n--- reserve is converted through this resource's own bulk, not raw item count ---")
    R.set_stockpile_target(st, "Stone", 0.5)
    reserve = R.stockpile_reserve(st, "Stone")
    cap = R.node_pool_capacity(st, R.storage_class("Stone"))
    bulk = R.resource_bulk("Stone")
    assert abs(reserve - (0.5 * cap) / bulk) < 1e-9
    print(f"  ok    0.5 of {cap} space capacity, at bulk {bulk}, is a "
          f"{reserve:.1f}-item reserve")
finally:
    st.resources = before_res
    st.stockpile_target = before_targets

print("\n--- CRITICAL: survival/upkeep goods are never affected by this policy ---")
protected = list(R._FOOD_SOURCES) + list(R._LUXURY_GOODS) + list(R._TIMBER_SOURCES) \
    + ["Firewood", "Clothes", "Fodder"]
before_res = dict(st.resources or {})
before_targets = dict(getattr(st, "stockpile_target", None) or {})
try:
    st.resources = dict(before_res)
    for res in protected:
        st.resources[res] = 1000
    needs = R.settlement_needs(st, w.season)
    baseline = {res: R._node_surplus(st, res, needs) for res in protected}
    for res in protected:
        R.set_stockpile_target(st, res, 0.9)   # would hoard hard, if it applied at all
    after = {res: R._node_surplus(st, res, needs) for res in protected}
    assert baseline == after, "a stockpile target leaked into a protected resource"
    print(f"  ok    all {len(protected)} survival/upkeep resources ignore a "
          f"stockpile target entirely")
finally:
    st.resources = before_res
    st.stockpile_target = before_targets

print("\n--- scope: village/region/realm, never another faction's nodes ---")
sibling_settlements = [s for s in w.settlements if s.faction_idx == pidx]
other = next(s for s in w.settlements if s.faction_idx != pidx)
before = {s.id: dict(getattr(s, "stockpile_target", None) or {}) for s in w.settlements}
try:
    changed = R.apply_stockpile_target(st, "Stone", 0.3, scope="realm", world=w)
    assert changed == len(sibling_settlements)
    assert all(R.stockpile_target(s, "Stone") == 0.3 for s in sibling_settlements)
    assert R.stockpile_target(other, "Stone") is None, (
        "realm scope must never reach another faction's settlements")
    print(f"  ok    realm scope reached all {changed} of this faction's own "
          f"settlements, none of anyone else's")
finally:
    for s in w.settlements:
        s.stockpile_target = before[s.id]

print("\n--- eligibility matches _node_surplus's own branch structure ---")
for res in protected:
    assert not R.stockpile_eligible(res), (
        f"{res} has its own reserve formula and must not be offered as a lever")
assert R.stockpile_eligible("Stone"), "an ordinary discretionary good should be eligible"
print(f"  ok    all {len(protected)} protected goods are ineligible; Stone is eligible")

print("\n--- the panel exposes it, and the preset cycle round-trips ---")
try:
    import tkinter as tk
    root = tk.Tk()
except Exception as exc:      # no display (CI, headless) -- same guard
    print(f"  skip  no Tk display available ({type(exc).__name__})")
else:
    from app.ui.map_view import MapView
    from app.world import commander as C, vision
    root.geometry("900x600")
    C.ensure_faction_commanders(w)
    vision.init_fog(w)
    w.player_faction_idx = pidx
    mv = MapView(root, w, lambda *a, **k: None, lambda *a, **k: None)
    mv.pack(fill="both", expand=True)
    root.update()

    st.resources = dict(st.resources or {})
    st.resources["Stone"] = 500
    mv._panel_cards_open["stockpile"] = True
    mv._show_settlement(st)
    root.update()

    # The selection panel is a drawn page now (app/ui/parchment.py), so what
    # it says lives in canvas text items rather than a tree of Labels.
    canvas = mv._panel_canvas
    texts = [str(canvas.itemcget(i, "text")) for i in canvas.find_all()
             if canvas.type(i) == "text" and canvas.itemcget(i, "text")]
    assert any("STOCKPILE" in t for t in texts), "no STOCKPILE card in the panel"
    assert any("Stone" in t for t in texts), "the held good isn't listed"
    print("  ok    STOCKPILE card renders with the node's eligible goods")

    start = R.stockpile_target(st, "Stone")
    seen = []
    for _ in range(len(R.STOCKPILE_PRESETS)):
        mv._cycle_stockpile_target(st, "Stone")
        root.update()
        seen.append(R.stockpile_target(st, "Stone"))
    assert seen[-1] == start, (
        f"a full cycle must return to where it started: {start} -> {seen}")
    assert len(set(map(str, seen))) == len(R.STOCKPILE_PRESETS), seen
    print(f"  ok    cycling hits all {len(R.STOCKPILE_PRESETS)} presets and "
          f"returns to the start")
    root.destroy()

print("\n--- a real turn still runs, and nothing goes negative ---")
for _ in range(3):
    R.advance_turn(w)
for node in list(w.settlements) + list(w.villages):
    for res, amt in (node.resources or {}).items():
        assert amt >= 0, (node.name, res, amt)
print("  ok    3 turns, no negative stock anywhere")

print("\nSTOCKPILE POLICY TEST PASSED")
