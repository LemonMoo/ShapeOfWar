"""Phase 1: commanders exist for everyone and gate attacks + claims."""
import sys, pickle
sys.path.insert(0, r"D:\Claude Project")
import tkinter as tk
from app.ui.map_view import MapView
from app.world import resources as R, commander as C, expansion, vision
from app.world.worldgen import _adjacent_region_ids

w = pickle.load(open(sys.argv[1], "rb"))
spawned = C.ensure_faction_commanders(w)
print(f"commanders: {len(w.commanders)} for {len(w.factions)} factions "
      f"(spawned {spawned} on load)")
assert len(w.commanders) >= len(w.factions)

pidx = w.player_faction_idx or 0
w.player_faction_idx = pidx
vision.init_fog(w)
player = w.factions[pidx]
cmd = C.faction_commanders(w, pidx)[0]

# --- the gate itself -------------------------------------------------------
front = expansion.claimable_frontier(w, pidx)
reachable = [r for r in front if C.commander_can_reach(w, pidx, r)]
print(f"\nfrontier {len(front)} regions, commander can reach {len(reachable)}")
assert reachable, "commander at capital should reach something"

far = next((r for r in front if not C.commander_can_reach(w, pidx, r)), None)
if far is not None:
    msg = expansion.start_claim(w, pidx, far)
    print("claim on unreachable region ->", msg[:70])
    assert "commander" in msg.lower(), "should be refused for commander reasons"

near = reachable[0]
print("claim on reachable region  ->", expansion.start_claim(w, pidx, near)[:70])

# --- move the commander away, the gate must close --------------------------
own_regions = [r for r in w.regions if r.faction_idx == pidx and r.cells]
target = next((r for r in own_regions
               if r.id not in _adjacent_region_ids(w, near) and r is not near), None)
if target is not None:
    cmd.pos = target.cells[0]
    cmd.path = None
    still = C.commander_can_reach(w, pidx, near)
    print(f"\nmoved commander to '{target.name}'; can still reach '{near.name}':", bool(still))

# --- UI: attack picker refuses when out of range ---------------------------
root = tk.Tk()
mv = MapView(root, w, lambda *a: None, lambda *a: None)
mv.pack(); root.update()
enemy = next((f for i, f in enumerate(w.factions)
              if i != pidx and f.meta.get("regions")), None)
if enemy is not None:
    mv._begin_attack_setup(enemy)
    root.update()
    picked = len(mv._attack_frontier)
    # The panel is a drawn page now (app/ui/parchment.py), not an `info`
    # Label, so its message lives in canvas text items rather than a widget.
    canvas = mv._panel_canvas
    info = " ".join(
        " ".join(canvas.itemcget(i, "text") for i in canvas.find_all()
                 if canvas.type(i) == "text" and canvas.itemcget(i, "text")).split())
    print(f"\nattack setup vs {enemy.name}: {picked} targets offered")
    if picked == 0:
        print("  message:", info[:110])
    else:
        for r in mv._attack_frontier:
            assert C.commander_can_reach(w, pidx, r), "offered an unreachable target"
        print("  every offered target is commander-reachable: OK")
root.destroy()
print("\nCOMMANDER GATE TEST PASSED")
