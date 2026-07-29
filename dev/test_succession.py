"""Phase 4: commander death, the attack lockout, and succession."""
import sys, pickle
sys.path.insert(0, r"D:\Claude Project")
from app.world import commander as C, resources as R, expansion
from app.world.territory import bordering_regions

w = pickle.load(open(sys.argv[1], "rb"))
C.ensure_faction_commanders(w)
pidx = w.player_faction_idx or 0
w.player_faction_idx = pidx
region = next(r for r in expansion.claimable_frontier(w, pidx))

print("--- before ---")
print("  commanders:", len(C.faction_commanders(w, pidx)),
      "| can act on frontier:", bool(C.commander_can_reach(w, pidx, region)))
assert C.commander_block_reason(w, pidx, region) is None

print("\n--- commander falls ---")
assert C.kill_commander(w, pidx) is True
print("  commanders now:", len(C.faction_commanders(w, pidx)),
      "| respawn in:", C.commander_respawn_turns(w, pidx))
reason = C.commander_block_reason(w, pidx, region)
print("  gate says:", reason)
assert reason and "fallen" in reason
print("  claim refused:", expansion.start_claim(w, pidx, region)[:60])
assert C.kill_commander(w, pidx) is False, "cannot lose one twice"

print("\n--- a reload must not undo the death ---")
before = C.commander_respawn_turns(w, pidx)
C.ensure_faction_commanders(w)
print("  after ensure_faction_commanders: commanders =",
      len(C.faction_commanders(w, pidx)), "| respawn still",
      C.commander_respawn_turns(w, pidx))
assert not C.faction_commanders(w, pidx), "backfill must respect succession"

print("\n--- succession counts down ---")
turns_waited = 0
while not C.faction_commanders(w, pidx) and turns_waited < 40:
    arrived = C.advance_commander_succession(w)
    turns_waited += 1
    if arrived:
        fac, cmd = arrived[0]
        cap = w.factions[fac].meta.get("capital")
        print(f"  turn {turns_waited}: successor took the field at {cmd.pos} "
              f"(capital {cap}) -> matches: {cmd.pos == cap}")
print(f"  waited {turns_waited} turns (COMMANDER_RESPAWN_TURNS="
      f"{C.COMMANDER_RESPAWN_TURNS})")
assert turns_waited == C.COMMANDER_RESPAWN_TURNS
assert C.faction_commanders(w, pidx), "successor should exist"
assert C.commander_respawn_turns(w, pidx) == 0

print("\n--- realm can act again ---")
print("  gate says:", C.commander_block_reason(w, pidx, region) or "allowed")

print("\n--- succession also runs from the real turn loop ---")
C.kill_commander(w, pidx)
for _ in range(C.COMMANDER_RESPAWN_TURNS + 1):
    R.advance_turn(w)
print("  commanders after advancing turns:", len(C.faction_commanders(w, pidx)))
assert C.faction_commanders(w, pidx)

print("\nSUCCESSION TEST PASSED")
