"""The buildable menu's model layer (app/world/buildings.py): what a node can
build, and whether it has any reason to want it.

    python dev/test_buildings.py [world.pkl]

Deliberately tests the MODEL, not the window. The recommendation is a claim
about the simulation ("this granary is 94% full and the harvest is being
turned away"), so it has to hold without standing up a widget tree -- which is
also the gap HANDOFF.md flags for every UI change made so far.
"""
import sys
import os
import pickle

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import buildings as B
from app.world import construction
from app.world import resources as R

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "worlds", "dev560.pkl")

w = pickle.load(open(PATH, "rb"))
pidx = w.player_faction_idx if w.player_faction_idx is not None else 0
nation = w.factions[pidx]
villages = [v for v in w.villages if v.faction_idx == pidx]
setts = [s for s in w.settlements if s.faction_idx == pidx]
assert villages and setts, "player faction owns no villages/settlements in this world"
v, st = villages[0], setts[0]
print(f"player: {nation.name}   village={v.name}   settlement={st.name} ({st.kind})")

print("\n--- every node offers a real, ordered list ---")
for node in (v, st):
    opts = B.build_options(w, node, nation)
    assert opts, f"{node.name} offered nothing at all"
    keys = [o.building for o in opts]
    assert len(keys) == len(set(keys)), f"duplicate cards: {keys}"
    assert opts == sorted(opts, key=lambda o: o.sort_key), "not ordered by priority"
    for o in opts:
        assert o.label and o.category
        assert 0 <= o.current_tier <= max(o.max_tier, 1), o
        if o.to_tier is not None:
            assert o.to_tier == o.current_tier + 1, o
            assert o.cost, f"{o.label} offers a tier with no cost"
            assert o.turns > 0, o
        else:
            assert o.blocked or o.in_progress, (
                f"{o.label} has no next tier but no reason given")
    print(f"  ok    {B.node_kind(node):<10} {node.name:<16} {len(opts)} cards: "
          f"{', '.join(k for k in keys)}")

print("\n--- villages and settlements offer different things ---")
vkeys = {o.building for o in B.build_options(w, v, nation)}
skeys = {o.building for o in B.build_options(w, st, nation)}
assert "shipyard" in skeys and "shipyard" not in vkeys, (vkeys, skeys)
# Herd buildings are village-only: a walled city is not a pasture.
assert "pasture" in vkeys, vkeys
pasture = next(o for o in B.build_options(w, st, nation) if o.building == "pasture") \
    if "pasture" in skeys else None
assert pasture is None or pasture.blocked, "a settlement should not be able to build a pasture"
print(f"  ok    shipyard is settlement-only; herd buildings are village-only")

print("\n--- a full pool makes its building urgent, an empty one does not ---")
orig = dict(getattr(v, "resources", {}) or {})
try:
    v.resources = {}
    empty = {o.building: o for o in B.build_options(w, v, nation)}
    assert empty["granary"].priority == "idle", empty["granary"]
    assert "no pressure" in empty["granary"].reason.lower(), empty["granary"].reason
    print(f"  ok    empty granary: {empty['granary'].priority} — "
          f"{empty['granary'].reason}")

    cap = R.node_pool_capacity(v, "household")
    v.resources = {"Barley": int(cap / R.resource_bulk("Barley")) + 10}
    full = {o.building: o for o in B.build_options(w, v, nation)}
    assert full["granary"].priority == "urgent", full["granary"]
    assert "Barley" in full["granary"].reason, (
        "the reason should name what is actually filling the pool")
    assert full["granary"].score > empty["granary"].score
    print(f"  ok    full granary:  {full['granary'].priority} — "
          f"{full['granary'].reason}")

    # And the full one must sort above the empty ones.
    ordered = B.build_options(w, v, nation)
    assert ordered[0].building == "granary", [o.building for o in ordered[:3]]
    print("  ok    the urgent card sorts to the front")
finally:
    v.resources = orig

print("\n--- a fishing village is told to build a Preserving House ---")
# Any faction's village will do -- the verdict is about the node's own
# production, not about who owns it.
fishers = sorted((x for x in w.villages if x.faction_idx >= 0),
                 key=lambda x: -(getattr(x, "fish_yield", 0) or 0))
fishers = [x for x in fishers if (getattr(x, "fish_yield", 0) or 0) >= 20]
if fishers:
    f = fishers[0]
    opt = next(o for o in B.build_options(w, f, w.factions[f.faction_idx])
               if o.building == R.PRESERVING_HOUSE)
    assert opt.priority in ("urgent", "useful"), (f.name, f.fish_yield, opt)
    assert "perishable" in opt.reason.lower(), opt.reason
    print(f"  ok    {f.name} lands {f.fish_yield}/turn: {opt.priority} — {opt.reason}")
else:
    print("  --    no village with a real catch in this world; skipped")

dry = [x for x in villages if not (getattr(x, "fish_yield", 0) or 0)
       and not (getattr(x, "herds", None) or {})]
if dry:
    opt = next(o for o in B.build_options(w, dry[0], nation)
               if o.building == R.PRESERVING_HOUSE)
    assert opt.priority == "idle", opt
    print(f"  ok    {dry[0].name} produces nothing perishable: {opt.priority}")

print("\n--- affordability is reported, never enforced by spending ---")
before_nation = {r: a for r, a in nation.stats.get("resources", {}).items()}
# Keyed by (kind, id): settlement ids and village ids are independent,
# overlapping id spaces, so a bare id silently compares a village against a
# settlement (the same care resources._local_path's cache key takes).
before_stock = {(B.node_kind(n), n.id): dict(getattr(n, "resources", {}) or {})
                for n in list(w.settlements) + list(w.villages)}
for node in (v, st):
    B.build_options(w, node, nation)
    B.recommended(w, node, nation)
    B.production_report(w, node)
assert nation.stats.get("resources", {}) == before_nation, "listing options spent from the nation"
for n in list(w.settlements) + list(w.villages):
    assert dict(getattr(n, "resources", {}) or {}) == before_stock[(B.node_kind(n), n.id)], (
        f"listing options changed {n.name}'s stock")
print("  ok    building the card list moved nothing anywhere")

print("\n--- affordable vs not ---")
opt = next(o for o in B.build_options(w, v, nation) if o.to_tier is not None)
assert opt.affordable == construction.can_afford(nation, opt.cost, w)
assert opt.buildable == (opt.affordable and not opt.blocked)
print(f"  ok    {opt.label}: cost {opt.cost}, affordable={opt.affordable}")

print("\n--- a build in progress is shown as such, not offered again ---")
# Funded outright rather than hoping the save happens to be rich enough: the
# unaffordable branch is the common case on a real world, and skipping the
# in-progress assertion whenever it fires would leave this untested most runs.
granary_cost = construction.storage_build_cost(v, "granary", 1)
before_v = dict(getattr(v, "resources", {}) or {})
v.resources = dict(before_v)
for r, a in granary_cost.items():
    v.resources[r] = v.resources.get(r, 0) + a * 2
msg = construction.start_storage_building(w, nation, v, "granary")
assert msg.startswith(("Building", "Upgrading")), msg
opt = next(o for o in B.build_options(w, v, nation) if o.building == "granary")
assert opt.in_progress is not None, opt
assert opt.to_tier is None, "a building under construction must not be offered again"
assert opt.blocked is None, "under construction is busy, not blocked"
elapsed, total = opt.in_progress
assert 0 <= elapsed <= total and total > 0, opt.in_progress
print(f"  ok    granary shows as under construction {elapsed}/{total}")
w.storage_projects = [p for p in w.storage_projects
                      if not (p.node_kind == "village" and p.node_id == v.id)]
v.resources = before_v

print("\n--- a maxed building is blocked with a reason, not silently dropped ---")
R.set_storage_tier(v, "granary", R.storage_max_tier(v, "granary"))
try:
    opt = next(o for o in B.build_options(w, v, nation) if o.building == "granary")
    assert opt.to_tier is None and opt.blocked, opt
    assert "highest tier" in opt.blocked, opt.blocked
    assert opt.priority == "blocked", opt
    assert B.build_options(w, v, nation)[-1].priority == "blocked", (
        "blocked cards should sort to the back")
    print(f"  ok    maxed granary: blocked — {opt.blocked}")
finally:
    R.set_storage_tier(v, "granary", 0)

print("\n--- production report ---")
vrep = B.production_report(w, v)
assert vrep["kind"] == "village"
assert vrep["policy"] in R.LABOR_POLICIES
assert vrep["workforce"] == R.village_workforce(v)
for row in vrep["sectors"]:
    assert row["sector"] in R.PRODUCTION_SECTORS
    assert row["output"] <= row["potential"]
    assert row["limited_by"] in ("hands", "land")
print(f"  ok    village: {vrep['workforce']} hands, "
      + ", ".join(f"{r['sector']} {r['output']}/{r['potential']} ({r['limited_by']})"
                  for r in vrep["sectors"]))

srep = B.production_report(w, st)
assert srep["kind"] == "settlement"
assert srep["recipes"], "a settlement should list its conversion recipes"
for r in srep["recipes"]:
    assert r["rate"] <= r["cap"]
    assert r["note"]
running = [r for r in srep["recipes"] if r["rate"] > 0]
print(f"  ok    settlement: {len(srep['recipes'])} recipes, {len(running)} running; "
      f"top: " + ", ".join(f"{r['output']} {r['rate']}/turn" for r in running[:3]))

print("\n--- recommended() only ever offers things it could actually start ---")
for node in list(villages[:20]) + list(setts[:10]):
    for o in B.recommended(w, node, nation):
        assert o.buildable and o.priority in ("urgent", "useful"), (node.name, o)
print("  ok    every recommendation across 30 nodes is startable right now")

print("\n--- it survives a real turn ---")
R.advance_turn(w)
for node in (v, st):
    assert B.build_options(w, node, nation)
    assert B.production_report(w, node)
print("  ok    still builds a full card list after advance_turn")

print("\nBUILDINGS TEST PASSED")
