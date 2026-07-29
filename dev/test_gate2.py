"""Force the refusal path: commander far from the front."""
import sys, pickle
sys.path.insert(0, r"D:\Claude Project")
import tkinter as tk
from app.ui.map_view import MapView
from app.world import commander as C, expansion, vision
from app.world.territory import bordering_regions

w = pickle.load(open(sys.argv[1], "rb"))
C.ensure_faction_commanders(w)
# pick a faction that actually borders someone, and play as them
pidx = w.player_faction_idx or 0
for i in range(len(w.factions)):
    if any(bordering_regions(w, i, j) for j in range(len(w.factions)) if j != i):
        pidx = i
        break
w.player_faction_idx = pidx
print("playing as:", w.factions[pidx].name)
vision.init_fog(w)
cmd = C.faction_commanders(w, pidx)[0]

# find an enemy we actually share a border with
enemy_idx = enemy = None
for i, f in enumerate(w.factions):
    if i == pidx:
        continue
    if bordering_regions(w, pidx, i):
        enemy_idx, enemy = i, f
        break
print("bordering enemy:", enemy.name if enemy else "none")
if enemy is None:
    print("SKIP: this world has no bordering enemy"); sys.exit()

front = bordering_regions(w, pidx, enemy_idx)
target = front[0]
print(f"target region: {target.name} ({len(front)} frontline regions)")

root = tk.Tk(); mv = MapView(root, w, lambda *a: None, lambda *a: None); mv.pack(); root.update()

# 1) commander parked ON the frontier -> attack allowed
staging = next(r for r in w.regions
               if r.faction_idx == pidx and r.cells
               and target.id in __import__("app.world.worldgen", fromlist=["x"])._adjacent_region_ids(w, r))
cmd.pos = staging.cells[0]; cmd.path = None
mv._begin_attack_setup(enemy); root.update()
print(f"\ncommander in '{staging.name}' (adjacent): {len(mv._attack_frontier)} targets offered")
assert mv._attack_frontier, "should be able to attack from an adjacent owned region"

# 2) commander marched far away -> refused, with an explanation
far = max((r for r in w.regions if r.faction_idx == pidx and r.cells),
          key=lambda r: abs(r.cells[0][0] - staging.cells[0][0])
                        + abs(r.cells[0][1] - staging.cells[0][1]))
cmd.pos = far.cells[0]; cmd.path = None
mv.attack_mode = None; mv._attack_frontier = []
mv._begin_attack_setup(enemy); root.update()
offered = len(mv._attack_frontier)
info = " ".join(mv.info.cget("text").split())
print(f"commander in '{far.name}' (far): {offered} targets offered")
print("  message:", info[:130])

# 3) direct launch must still refuse even if the picker were bypassed
blocked = C.commander_block_reason(w, pidx, target)
print("  direct gate says:", (blocked or "allowed")[:100])

root.destroy()
print("\nGATE REFUSAL TEST DONE")
