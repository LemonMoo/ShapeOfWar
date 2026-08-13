"""End to end: a commander dying in a real battle removes him from the world."""
import sys, pickle
sys.path.insert(0, r"D:\Claude Project")
import tkinter as tk
from app.ui.app import App
from app.world import commander as C, vision
from app.core import save as save_mod

w = pickle.load(open(sys.argv[1], "rb"))
C.ensure_faction_commanders(w)
# play as a faction that borders someone
from app.world.territory import bordering_regions
pidx = next((i for i in range(len(w.factions))
             if any(bordering_regions(w, i, j) for j in range(len(w.factions)) if j != i)),
            None)
if pidx is None:
    print("SKIP: this world has no bordering factions"); sys.exit()
w.player_faction_idx = pidx
vision.init_fog(w)
player = w.factions[pidx]
enemy_idx = next(j for j in range(len(w.factions))
                 if j != pidx and bordering_regions(w, pidx, j))
enemy = w.factions[enemy_idx]
print(f"{player.name} vs {enemy.name}")

app = App()
app.world = w
app._ensure_game_views()
app.update()

region = bordering_regions(w, pidx, enemy_idx)[0]
app.stage_battle(player, enemy, region)
app.update()
battle = app.battle_view.battle
atk, dfn = battle.armies[0], battle.armies[1]
print(f"armies deployed: {len(atk.units)} vs {len(dfn.units)}; "
      f"commanders {atk.commander.title} / {dfn.commander.title}")

before = {i: len(C.faction_commanders(w, i)) for i in (pidx, enemy_idx)}
# kill the defender's commander outright, then run the battle out
dfn.commander.hp = 0
ticks = 0
while not battle.over and ticks < 20000:
    battle.update(1 / 60)
    ticks += 1
print(f"battle resolved in {ticks/60:.0f}s; winner "
      f"{battle.winner.name if battle.winner else 'none'}")
print(f"  defender commander_lost latched: {dfn.commander_lost}")
print(f"  attacker commander_lost: {atk.commander_lost}")

after = {i: len(C.faction_commanders(w, i)) for i in (pidx, enemy_idx)}
print(f"\nworld commanders  {enemy.name}: {before[enemy_idx]} -> {after[enemy_idx]}"
      f"  (respawn in {C.commander_respawn_turns(w, enemy_idx)})")
print(f"world commanders  {player.name}: {before[pidx]} -> {after[pidx]}")
assert after[enemy_idx] == 0, "defender should have lost their commander"
assert C.commander_respawn_turns(w, enemy_idx) == C.COMMANDER_RESPAWN_TURNS
if not atk.commander_lost:
    assert after[pidx] == before[pidx], "attacker kept theirs"

app.destroy()
print("\nBATTLE DEATH -> WORLD TEST PASSED")
