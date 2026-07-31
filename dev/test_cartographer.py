"""The Cartographer's Guild: a multiplier on your own traffic, not free vision.

    python dev/test_cartographer.py [world.pkl]

The design claim this has to hold up is a negative one: buying the building
must NOT hand the player a map. It widens what caravans, roads and commanders
already report and surveys its own neighbourhood, and that is all -- so a realm
with nothing out in the world gains almost nothing from it. That is the
assertion most worth having, because it is the one a later "small" change is
most likely to quietly break.
"""
import sys
import os
import pickle

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.world import buildings as B
from app.world import construction
from app.world import resources as R
from app.world import vision

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "worlds", "dev560.pkl")


def fresh():
    w = pickle.load(open(PATH, "rb"))
    if w.player_faction_idx is None:
        w.player_faction_idx = 0
    return w


def revealed(w):
    return sum(w.fog)


def refog(w):
    """Start from full fog, then recompute -- so a measurement is 'what does
    this configuration reveal', not 'what has ever been revealed'. Fog is
    monotonic by design, which makes any before/after comparison meaningless
    without this."""
    w.fog = bytearray(w.w * w.h)
    w.fog_fully_revealed = False
    w.fog_bbox = None
    vision.recompute(w)
    return revealed(w)


w = fresh()
pidx = w.player_faction_idx
nation = w.factions[pidx]
city = next(s for s in w.settlements if s.faction_idx == pidx)
print(f"player {nation.name}, guild candidate {city.name} ({city.kind})")

print("\n--- gating ---")
village = next(v for v in w.villages if v.faction_idx == pidx)
assert R.storage_max_tier(village, R.CARTOGRAPHER) == 0, (
    "a village is not where a guild of surveyors and copyists lives")
assert R.storage_max_tier(city, R.CARTOGRAPHER) == 3
cost = construction.storage_build_cost(city, R.CARTOGRAPHER, 1)
assert {"Planks", "Glass", "Tools"} <= set(cost), cost
print(f"  ok    settlement-only, 3 tiers; tier 1 needs {sorted(cost)}")

print("\n--- a guild does not hand you a map ---")
base = refog(w)
R.set_storage_tier(city, R.CARTOGRAPHER, 3)
try:
    with_guild = refog(w)
    gained = with_guild - base
    total = w.w * w.h
    assert gained >= 0
    # The local survey has not run yet (survey_radius is still 0), so at this
    # instant the ONLY difference is the widened traffic reveal.
    assert gained < total * 0.06, (
        f"a freshly-built guild revealed {gained:,} cells "
        f"({100*gained/total:.1f}% of the map) before surveying anything")
    print(f"  ok    tier 3 guild, nothing surveyed yet: +{gained:,} cells "
          f"({100*gained/total:.2f}% of the map), all of it from existing traffic")
finally:
    R.set_storage_tier(city, R.CARTOGRAPHER, 0)

print("\n--- the local survey is small, slow and hard-capped ---")
R.set_storage_tier(city, R.CARTOGRAPHER, 1)
city.survey_radius = 0.0
try:
    for _ in range(5):
        R.advance_cartographers(w)
    after_five = R.cartographer_radius(city)
    assert 0 < after_five <= 5 * R.CARTOGRAPHER_SURVEY_PER_TURN[1] * R.CARTOGRAPHER_PAPER_SPEEDUP
    for _ in range(500):
        R.advance_cartographers(w)
    capped = R.cartographer_radius(city)
    assert capped == R.CARTOGRAPHER_LOCAL_RADIUS[1], (capped,)
    assert capped <= 12, "the 'local' survey is not local any more"
    print(f"  ok    5 turns -> {after_five:.2f} cells; 500 turns -> {capped} "
          f"and capped there")
finally:
    R.set_storage_tier(city, R.CARTOGRAPHER, 0)
    city.survey_radius = 0.0

print("\n--- paper doubles the local survey, and is never required ---")
R.set_storage_tier(city, R.CARTOGRAPHER, 2)
before_res = dict(city.resources or {})
try:
    city.resources = dict(before_res)
    city.resources.pop("Paper", None)
    city.survey_radius = 0.0
    R.advance_cartographers(w)
    dry = R.cartographer_radius(city)
    assert dry > 0, "a guild with no paper stopped surveying entirely"

    city.resources["Paper"] = 50
    city.survey_radius = 0.0
    R.advance_cartographers(w)
    wet = R.cartographer_radius(city)
    assert abs(wet - dry * R.CARTOGRAPHER_PAPER_SPEEDUP) < 1e-6, (dry, wet)
    assert city.resources["Paper"] == 50 - R.CARTOGRAPHER_PAPER_PER_TURN
    print(f"  ok    without paper {dry:.2f}/turn, with paper {wet:.2f}/turn, "
          f"{R.CARTOGRAPHER_PAPER_PER_TURN} paper burned")
finally:
    R.set_storage_tier(city, R.CARTOGRAPHER, 0)
    city.resources = before_res
    city.survey_radius = 0.0

print("\n--- the bonus is the realm's best guild, not the sum of them ---")
others = [s for s in w.settlements if s.faction_idx == pidx and s is not city][:3]
try:
    R.set_storage_tier(city, R.CARTOGRAPHER, 2)
    one = R.cartographer_traffic_bonus(w, pidx)
    for s in others:
        R.set_storage_tier(s, R.CARTOGRAPHER, 2)
    many = R.cartographer_traffic_bonus(w, pidx)
    assert one == many == R.CARTOGRAPHER_TRAFFIC_BONUS[2], (one, many)
    R.set_storage_tier(others[0], R.CARTOGRAPHER, 3) if others else None
    if others:
        assert R.cartographer_traffic_bonus(w, pidx) == R.CARTOGRAPHER_TRAFFIC_BONUS[3]
    print(f"  ok    {1 + len(others)} guilds still give "
          f"{R.CARTOGRAPHER_TRAFFIC_BONUS[2]} cells at tier 2; the best one wins")
finally:
    R.set_storage_tier(city, R.CARTOGRAPHER, 0)
    for s in others:
        R.set_storage_tier(s, R.CARTOGRAPHER, 0)

print("\n--- it multiplies traffic: same guild, more caravans, more map ---")
w2 = fresh()
pidx2 = w2.player_faction_idx
city2 = next(s for s in w2.settlements if s.faction_idx == pidx2)
mine = [c for c in w2.trade_caravans if pidx2 in (c.seller_idx, c.buyer_idx)]
if not mine:
    # Put a real caravan in flight rather than skipping the assertion the whole
    # design rests on. Whether a given save happens to have one of the player's
    # own moving is not something this mechanic should be tested at the mercy
    # of -- and the point being measured is precisely "traffic is what a guild
    # multiplies", so the test has to be able to supply traffic.
    from app.world.trade import TradeCaravan
    far = max((s for s in w2.settlements if s.faction_idx == pidx2),
              key=lambda s: abs(s.pos[0] - city2.pos[0]) + abs(s.pos[1] - city2.pos[1]))
    (x0, y0), (x1, y1) = city2.pos, far.pos
    steps = max(abs(x1 - x0), abs(y1 - y0)) or 1
    path = [(x0 + (x1 - x0) * i // steps, y0 + (y1 - y0) * i // steps)
            for i in range(steps + 1)]
    caravan = TradeCaravan("land", pidx2, pidx2, "Logs", 10, 1.0, path)
    caravan.turn_progress = caravan.turns_total   # a completed voyage to log
    w2.trade_caravans.append(caravan)
    mine = [caravan]
    print(f"  (none in flight; put one on the road {city2.name} -> {far.name}, "
          f"{len(path)} cells)")
no_guild = refog(w2)
R.set_storage_tier(city2, R.CARTOGRAPHER, 3)
guilded = refog(w2)
# Now take the traffic away and re-measure with the SAME guild.
kept = list(w2.trade_caravans)
w2.trade_caravans = [c for c in kept if pidx2 not in (c.seller_idx, c.buyer_idx)]
guild_no_traffic = refog(w2)
w2.trade_caravans = kept
R.set_storage_tier(city2, R.CARTOGRAPHER, 0)
print(f"  player caravans in flight: {len(mine)}")
print(f"  no guild                 {no_guild:,} cells")
print(f"  guild + traffic          {guilded:,} cells")
print(f"  guild, traffic removed   {guild_no_traffic:,} cells")
assert guilded >= guild_no_traffic, (guilded, guild_no_traffic)
if mine:
    assert guilded > guild_no_traffic, (
        "the guild revealed the same amount with and without the player's "
        "caravans -- the traffic multiplier is not doing anything")
    print(f"  ok    the same guild reveals {guilded - guild_no_traffic:,} more "
          f"cells purely because traffic exists")
else:
    print("  --    no player caravans in flight in this world; comparison skipped")

print("\n--- the card tells the truth about what it needs ---")
w3 = fresh()
pidx3 = w3.player_faction_idx
n3 = w3.factions[pidx3]
city3 = next(s for s in w3.settlements if s.faction_idx == pidx3)
opt = next(o for o in B.build_options(w3, city3, n3) if o.building == R.CARTOGRAPHER)
assert opt.category == "Knowledge", opt.category
assert "compile" in opt.reason.lower() or "guild" in opt.reason.lower() \
    or "caravans" in opt.reason.lower(), opt.reason
print(f"  ok    with traffic: {opt.priority} — {opt.reason}")

kept = (list(w3.trade_caravans), list(w3.trade_routes), list(w3.commanders))
w3.trade_caravans, w3.trade_routes, w3.commanders = [], [], []
opt = next(o for o in B.build_options(w3, city3, n3) if o.building == R.CARTOGRAPHER)
assert opt.priority == "idle", opt
assert "does not go looking" in opt.reason, opt.reason
print(f"  ok    with nothing out there: {opt.priority} — {opt.reason}")
w3.trade_caravans, w3.trade_routes, w3.commanders = kept

print("\n--- a real turn still runs ---")
w4 = fresh()
c4 = next(s for s in w4.settlements if s.faction_idx == w4.player_faction_idx)
R.set_storage_tier(c4, R.CARTOGRAPHER, 2)
for _ in range(3):
    R.advance_turn(w4)
assert R.cartographer_radius(c4) > 0, "three turns of surveying did nothing"
print(f"  ok    3 turns with a guild; surveyed radius "
      f"{R.cartographer_radius(c4):.2f}")

print("\n=== mechanic B: commissioned surveys ===")

print("\n--- a survey has to be paid for, and needs a Guild to commission it ---")
w5 = fresh()
refog(w5)
w5.survey_expeditions = []
st5 = next(s for s in w5.settlements if s.faction_idx == w5.player_faction_idx)
assert "Guild" in R.can_commission_survey(w5, st5), R.can_commission_survey(w5, st5)
R.set_storage_tier(st5, R.CARTOGRAPHER, 3)
st5.resources = dict(st5.resources or {})
for name in R.SURVEY_COST:
    st5.resources[name] = 0
blocked = R.can_commission_survey(w5, st5)
assert blocked and "Needs" in blocked, blocked
print(f"  ok    no Guild -> refused; Guild but no funds -> {blocked!r}")

for name, amount in R.SURVEY_COST.items():
    st5.resources[name] = amount * 4
assert R.can_commission_survey(w5, st5) is None
paid_before = {n: st5.resources[n] for n in R.SURVEY_COST}
msg = R.start_survey(w5, st5)
assert w5.survey_expeditions, msg
for name, amount in R.SURVEY_COST.items():
    assert paid_before[name] - st5.resources[name] == amount, name
print(f"  ok    commissioned, and it actually cost "
      f"{', '.join(f'{a} {n}' for n, a in R.SURVEY_COST.items())}")

print("\n--- one party per settlement at a time ---")
again = R.can_commission_survey(w5, st5)
assert again and "already in the field" in again, again
print(f"  ok    {again!r}")

print("\n--- it heads OUT, not to the nearest scrap of fog next door ---")
exp = w5.survey_expeditions[0]
_speed, reach = R.survey_speed_and_range(w5, st5)
assert len(exp.path) > 10, (
    f"a commissioned expedition walked only {len(exp.path)} cells -- targeting "
    f"the NEAREST fog rather than the furthest reachable is the bug here")
print(f"  ok    {len(exp.path)}-cell route out of a {reach}-cell range")

print("\n--- it charts only what it has actually walked ---")
assert exp.charted == exp.path[:1], exp.charted
before = revealed(w5)
for _ in range(400):
    R.advance_surveys(w5)
    vision.recompute(w5)
    if all(e.finished for e in w5.survey_expeditions):
        break
assert exp.finished, "the party never finished or died"
if not exp.lost:
    assert exp.charted == exp.path, "a completed survey must have charted it all"
gained = revealed(w5) - before
assert gained > 0, "a completed survey revealed nothing"
print(f"  ok    walked it and revealed {gained:,} cells "
      f"({'lost on the way' if exp.lost else 'came home'})")

print("\n--- a finished party is swept up only after vision has read it ---")
# The bug this guards: advance_surveys runs BEFORE vision.recompute, so
# dropping a finished expedition the same turn silently loses the last
# stretch it charted.
assert exp in w5.survey_expeditions, (
    "a party that finished this turn must survive until the next sweep")
R.advance_surveys(w5)
assert exp not in w5.survey_expeditions, "the next sweep should clear it"
print("  ok    kept for one turn after finishing, then cleared")

print("\n=== mechanic C: coast before interior ===")
w6 = fresh()
from app.world.construction import _is_coastal
inland = next((s for s in w6.settlements if not _is_coastal(w6, s.pos)), None)
coastal = next((s for s in w6.settlements if _is_coastal(w6, s.pos)), None)
if inland and coastal:
    i_speed, i_reach = R.survey_speed_and_range(w6, inland)
    coastal.has_shipyard = False
    c_speed, c_reach = R.survey_speed_and_range(w6, coastal)
    assert c_speed > i_speed and c_reach > i_reach, (i_speed, c_speed, i_reach, c_reach)
    coastal.has_shipyard = True
    y_speed, y_reach = R.survey_speed_and_range(w6, coastal)
    assert y_speed > c_speed and y_reach > c_reach, (c_speed, y_speed)
    print(f"  ok    inland {i_speed:g}/turn to {i_reach}; coastal {c_speed:g} to "
          f"{c_reach}; with a shipyard {y_speed:g} to {y_reach}")
else:
    print("  skip  this world has no inland/coastal pair to compare")

print("\n--- a survey is dangerous, but not a coin flip ---")
# The per-turn chance compounds over a ~30-turn journey; the first value
# tried worked out to ~49% and had to come down. Guard the total, not the
# per-turn number.
p_survive = (1.0 - R.SURVEY_LOSS_CHANCE_PER_TURN) ** 30
assert 0.7 < p_survive < 0.97, (
    f"over a typical 30-turn survey the party comes home {p_survive:.0%} of "
    f"the time -- that is not a risk the player can reason about")
print(f"  ok    ~{1 - p_survive:.0%} chance of loss over a 30-turn expedition")

print("\nCARTOGRAPHER TEST PASSED")
