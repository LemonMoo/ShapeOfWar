"""Phase 14: finite village labor -- production is an allocation, not a
terrain readout.

    python dev/test_labor.py [world.pkl]

Asserts the contract the whole phase rests on: output is min(land, hands),
both ceilings really bind, the policy actually moves hands, and storage
pressure feeds back into where they go.
"""
import sys
import os
import pickle

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import resources as R

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "worlds", "dev560.pkl")

w = pickle.load(open(PATH, "rb"))
season = w.season


def clear_cache(v):
    if hasattr(v, "_labor_cache"):
        del v._labor_cache


def potential(v, s=None):
    _raw, by_sector, _bsr = R._village_terrain_potential(w, v, s or season)
    return by_sector


def yield_for(v, s=None):
    clear_cache(v)
    return R.compute_village_yield(w, v, s or season)


def sector_total(y, sector):
    return sum(a for r, a in y.items() if R.production_sector(r) == sector)


# A village with real farmland to work, so both ceilings are reachable.
farm_villages = [v for v in w.villages
                 if v.faction_idx >= 0 and potential(v).get("farming", 0) > 30
                 and R.village_workforce(v) > 0]
assert farm_villages, "no village with meaningful farming potential in this world"
v = max(farm_villages, key=lambda x: potential(x)["farming"])
print(f"test village: {v.name}  adults={R.village_workforce(v)}  "
      f"potential={ {k: round(x) for k, x in potential(v).items()} }")

print("\n--- output is min(land, hands) ---")
orig_out = dict(R.LABOR_OUTPUT_PER_WORKER)
try:
    # Hands effectively infinite -> the land is the only ceiling left, which
    # is exactly the pre-Phase-14 behaviour.
    R.LABOR_OUTPUT_PER_WORKER.update({k: 1e9 for k in orig_out})
    land_bound = yield_for(v)
    assert sector_total(land_bound, "farming") == potential(v)["farming"], (
        sector_total(land_bound, "farming"), potential(v)["farming"])
    print(f"  ok    unlimited hands -> land ceiling  {sector_total(land_bound, 'farming')}")

    # Hands effectively worthless -> nothing comes in, however good the land.
    R.LABOR_OUTPUT_PER_WORKER.update({k: 1e-9 for k in orig_out})
    hand_bound = yield_for(v)
    assert sector_total(hand_bound, "farming") == 0, hand_bound
    print("  ok    worthless hands -> nothing comes in, however good the land")
finally:
    R.LABOR_OUTPUT_PER_WORKER.update(orig_out)
    clear_cache(v)

real = yield_for(v)
assert 0 < sector_total(real, "farming") < potential(v)["farming"], (
    "at live settings this village should be genuinely hand-limited, not "
    f"free: got {sector_total(real, 'farming')} of {potential(v)['farming']}")
print(f"  ok    at live settings, hands bind  "
      f"{sector_total(real, 'farming')} of {potential(v)['farming']}")

print("\n--- more hands really do produce more ---")
before_adults = v.adults
try:
    v.adults = before_adults * 3
    tripled = sector_total(yield_for(v), "farming")
    assert tripled > sector_total(real, "farming"), (tripled, sector_total(real, "farming"))
    print(f"  ok    3x the adults -> {sector_total(real, 'farming')} to {tripled}")
finally:
    v.adults = before_adults
    clear_cache(v)

print("\n--- policy moves the hands ---")
# Fishing is deliberately excluded here: compute_village_yield doesn't return
# Fish (see _produce_fishing), so a fishing sector is invisible to
# sector_total and can't be measured this way. It gets its own check below.
def worked_sectors(village):
    return {s: p for s, p in potential(village).items() if p > 0 and s != "fishing"}


multi = [x for x in w.villages
         if x.faction_idx >= 0 and R.village_workforce(x) > 0
         and len(worked_sectors(x)) >= 2]
assert multi, "no village works more than one non-fishing sector in this world"

m = max(multi, key=lambda x: min(worked_sectors(x).values()))
pair = sorted(worked_sectors(m), key=lambda s: -worked_sectors(m)[s])
big, small = pair[0], pair[1]
policy_for = {v_: k for k, v_ in R.LABOR_POLICY_SECTOR.items()}
orig_policy = R.labor_policy(m)
try:
    # Compared focus-against-focus rather than focus-against-Auto: Auto damps
    # by storage pressure and a named focus doesn't, so an Auto baseline would
    # confound "the policy moved hands" with "the pool was full".
    R.set_labor_policy(m, policy_for[big])
    on_big = yield_for(m)
    R.set_labor_policy(m, policy_for[small])
    on_small = yield_for(m)
    assert sector_total(on_small, small) > sector_total(on_big, small), (
        f"focusing {small} should raise it: "
        f"{sector_total(on_big, small)} -> {sector_total(on_small, small)}")
    assert sector_total(on_small, big) < sector_total(on_big, big), (
        f"focusing {small} should cost {big}: "
        f"{sector_total(on_big, big)} -> {sector_total(on_small, big)}")
    print(f"  ok    focus {big} vs focus {small}: "
          f"{small} {sector_total(on_big, small)}->{sector_total(on_small, small)}, "
          f"{big} {sector_total(on_big, big)}->{sector_total(on_small, big)}")

    # A named focus is an emphasis, never an exclusive assignment: a village
    # ordered to mine must not stop feeding itself.
    assert sector_total(on_small, big) > 0, (
        "a focused village abandoned its other sector entirely -- "
        "LABOR_FOCUS_SHARE is supposed to leave the rest staffed")
    print("  ok    a focused village still works its other sectors")
finally:
    R.set_labor_policy(m, orig_policy)
    clear_cache(m)

print("\n--- an impossible order falls back rather than idling ---")
dry = [x for x in w.villages if x.faction_idx >= 0 and R.village_workforce(x) > 0
       and not potential(x).get("fishing") and potential(x).get("farming", 0) > 0]
assert dry, "no landlocked village with farmland in this world"
d = dry[0]
orig_policy = R.labor_policy(d)
try:
    R.set_labor_policy(d, "Auto")
    before = sector_total(yield_for(d), "farming")
    R.set_labor_policy(d, "Fishing")
    after = sector_total(yield_for(d), "farming")
    assert after == before, (
        f"ordered to fish with no water, the village should fall through to "
        f"Auto, not idle: farming {before} -> {after}")
    print(f"  ok    ordered to fish with no water in reach: still farms {after}")
finally:
    R.set_labor_policy(d, orig_policy)
    clear_cache(d)

print("\n--- no hands idle while any sector is still short ---")
# The spillover invariant, stated as a property rather than as one hand-picked
# village: labor left over on a sector that has already hit its terrain
# ceiling must be handed to one that hasn't. If ANY sector is short, every
# worker must be placed.
checked = short_seen = 0
for x in w.villages:
    if x.faction_idx < 0 or R.village_workforce(x) <= 0:
        continue
    _raw, pots, bsr = R._village_terrain_potential(w, x, season)
    if not pots:
        continue
    factors = R.village_labor_factors(w, x, pots, bsr)
    if not factors:
        continue
    checked += 1
    used = sum(pots[s] * f / R.LABOR_OUTPUT_PER_WORKER[s] for s, f in factors.items())
    if any(f < 0.999 for f in factors.values()):
        short_seen += 1
        assert used >= R.village_workforce(x) - 1e-6, (
            f"{x.name}: {R.village_workforce(x) - used:.1f} hands idle while "
            f"a sector is still short {factors}")
    assert used <= R.village_workforce(x) + 1e-6, (
        f"{x.name}: placed {used:.1f} workers out of {R.village_workforce(x)}")
assert checked > 50 and short_seen > 10, (checked, short_seen)
print(f"  ok    {checked} villages, {short_seen} with a short sector: no idle "
      f"hands anywhere, and none over-staffed")

print("\n--- Auto responds to storage pressure ---")
# Filling the pool a sector's output lands in must pull hands off it. This is
# the feedback loop that makes a full warehouse mean something rather than
# silently deleting the timber.
#
# Measured on the SHARES, not on the output: a sector whose small terrain
# ceiling its remaining workers can still cover shows no output change even
# though the hands really did move, so output alone would under-report this.
def durable_forestry(x):
    _raw, pots, bsr = R._village_terrain_potential(w, x, season)
    if pots.get("farming", 0) <= 0 or pots.get("forestry", 0) <= 0:
        return None
    if not any(R.storage_class(r) == "durable" for r in bsr.get("forestry", {})):
        return None   # this village only cuts Firewood, which is a granary good
    return pots, bsr


cands = [(x, dq) for x in w.villages
         if x.faction_idx >= 0 and R.village_workforce(x) > 0
         for dq in [durable_forestry(x)] if dq]
assert cands, "no village cuts structural timber alongside real farmland"
q, (pots, bsr) = cands[0]
orig_res = dict(getattr(q, "resources", {}) or {})
orig_policy = R.labor_policy(q)
try:
    R.set_labor_policy(q, "Auto")
    q.resources = {}
    empty = R._labor_shares(q, pots, bsr)
    cap = R.node_pool_capacity(q, "durable")
    q.resources = {"Softwood": int(cap / R.resource_bulk("Softwood")) + 50}
    full = R._labor_shares(q, pots, bsr)
    assert full["forestry"] < empty["forestry"], (
        f"a full warehouse should pull hands out of the woods: "
        f"{empty['forestry']:.3f} -> {full['forestry']:.3f}")
    assert full["farming"] > empty["farming"], (
        f"the hands pulled out of the woods should turn up in the fields: "
        f"{empty['farming']:.3f} -> {full['farming']:.3f}")
    print(f"  ok    durable pool full: forestry share "
          f"{empty['forestry']:.3f} -> {full['forestry']:.3f}, farming "
          f"{empty['farming']:.3f} -> {full['farming']:.3f}")

    # And a named focus must ignore the pressure -- an explicit order is the
    # player overriding exactly this automation.
    R.set_labor_policy(q, "Forestry")
    forced = R._labor_shares(q, pots, bsr)
    assert forced["forestry"] > full["forestry"], (forced, full)
    print(f"  ok    an explicit Forestry order overrides the pressure "
          f"({forced['forestry']:.3f})")
finally:
    q.resources = orig_res
    R.set_labor_policy(q, orig_policy)
    clear_cache(q)

print("\n--- fish is labor-limited and never double-counted ---")
fishers = [x for x in w.villages if x.faction_idx >= 0
           and (getattr(x, "fish_yield", 0) or 0) > 0 and R.village_workforce(x) > 0]
if fishers:
    f = fishers[0]
    y = yield_for(f)
    assert "Fish" not in y, (
        "compute_village_yield must not return Fish -- _produce_fishing lands "
        "it at the node directly, and returning it here too would double it")
    print("  ok    compute_village_yield excludes Fish")
    before = dict(getattr(f, "resources", {}) or {})
    f.resources = {}
    clear_cache(f)
    R._produce_fishing(w)
    landed = f.resources.get("Fish", 0)
    assert landed <= f.fish_yield, (landed, f.fish_yield)
    print(f"  ok    catch is labor-limited: {landed} of a {f.fish_yield} potential")
    f.resources = before
    clear_cache(f)
else:
    print("  --    no fishing village in this world; skipped")

print("\n--- old saves and round-trips ---")
fresh = [x for x in w.villages if not hasattr(x, "labor_policy")]
assert R.labor_policy(fresh[0] if fresh else v) in R.LABOR_POLICIES
if fresh:
    assert R.labor_policy(fresh[0]) == R.DEFAULT_LABOR_POLICY
    print(f"  ok    a village with no labor_policy attribute reads as "
          f"{R.DEFAULT_LABOR_POLICY}")
R.set_labor_policy(v, "Mining")
assert R.labor_policy(pickle.loads(pickle.dumps(v))) == "Mining"
R.set_labor_policy(v, "not a real policy")
assert R.labor_policy(v) == "Mining", "an unknown policy must be refused, not stored"
R.set_labor_policy(v, "Auto")
clear_cache(v)
print("  ok    policy survives a pickle round-trip; an unknown policy is refused")

print("\n--- the panel report agrees with what is produced ---")
rep = R.village_labor_report(w, v, season)
produced = yield_for(v)
for row in rep["sectors"]:
    assert row["output"] <= row["potential"], row
    if row["sector"] != "fishing":
        assert abs(row["output"] - sector_total(produced, row["sector"])) <= 2, (
            row, sector_total(produced, row["sector"]))
assert rep["workforce"] == R.village_workforce(v)
print(f"  ok    report matches production across {len(rep['sectors'])} sectors")

print("\n--- a real turn still runs ---")
before_pop = sum(n.population for n in list(w.settlements) + list(w.villages))
for _ in range(3):
    R.advance_turn(w)
after_pop = sum(n.population for n in list(w.settlements) + list(w.villages))
for node in list(w.settlements) + list(w.villages):
    for r, amt in getattr(node, "resources", {}).items():
        assert amt >= 0, (node.name, r, amt)
print(f"  ok    3 turns, no negative stock anywhere; pop {before_pop:,} -> {after_pop:,}")

print("\nLABOR TEST PASSED")
