"""Every balance lever in the game, addressable by name.

The numbers that decide how this game plays are scattered across five modules by
subject -- unit stats in `unit_types`, species multipliers in `lexicon`, stance
effects in `orders`, the order AI's thresholds, the targeting weights in
`battle`. That is the right place for them to LIVE, next to the comments
explaining why each one is what it is. It is a poor place to tune from, because
tuning means holding a dozen of them in view at once and moving one at a time.

So this module does not move any of them. It builds an index over the tables
where they already sit, addresses each by a dotted path, and can write a set of
overrides to JSON and apply it back. `dev/balance_lab.py` is the UI on top.

    tuning.get("units.infantry.max_hp")        -> 30
    tuning.set("units.infantry.max_hp", 34)
    tuning.changes()                           -> {"units.infantry.max_hp": 34}
    tuning.save()                              -> writes dev/balance.json

Two rules the implementation depends on, both load-bearing:

  * Tables are mutated IN PLACE, never rebound. `unit.py` does
    `from app.battle.unit_types import UNIT_TYPES`, which binds the same dict
    object -- mutating it is visible everywhere, rebinding the module attribute
    would be visible nowhere.
  * Scalars imported by value cannot work that way, so the few that are get an
    explicit list of modules to mirror into. There are two of them and they are
    named below; if a third appears, it goes in that list or it silently does
    nothing.

Overrides are a DEV file. `load()` is called at startup and is a no-op when the
file is absent, which is the case in any packaged build -- `dev/` is not shipped.
"""
import copy
import json
import os
import sys

from app.battle import battle as battle_mod
from app.battle import order_ai
from app.battle import orders
from app.battle import unit as unit_mod
from app.battle import unit_types
from app.world import lexicon


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


OVERRIDES_PATH = os.path.join(_repo_root(), "dev", "balance.json")


class Section:
    """One table (or one bag of module constants) worth of levers.

    `note` is shown at the top of the section in the UI -- the one-line version
    of why these numbers are delicate, so nobody has to open the source to find
    out that e.g. the roster is measured on spread rather than on any single
    species' win rate.
    """

    def __init__(self, key, label, target, note="", groups=None, mirror=()):
        self.key = key
        self.label = label
        self.target = target      # a dict to walk, or (module, [attr names])
        self.note = note
        self.group_labels = groups or {}
        self.mirror = mirror      # modules to copy scalar changes into

    @property
    def is_scalars(self):
        return isinstance(self.target, tuple)


SECTIONS = [
    Section(
        "units", "Units", unit_types.UNIT_TYPES,
        "Per-unit stats. Speeds and ranges are battlefield pixels, cooldowns "
        "seconds. Range dominates this sim -- a unit that gives up reach pays "
        "for it far more than its damage suggests.",
        groups={k: v.get("name", k) for k, v in unit_types.UNIT_TYPES.items()},
    ),
    Section(
        "species", "Species", lexicon.SPECIES,
        "Tactical multipliers applied to every soldier of that species, and "
        "the `specials` shares deciding how many signature units it fields. "
        "THE SHARES ARE THE STRONGER KNOB: the Bladesinger swung from +25 to "
        "-25 points on a share change alone, with only its dodge touched.",
    ),
    Section(
        "commanders", "Commanders", unit_types.COMMANDER_BY_SPECIES,
        "Each species' champion. These are corrective, not just flavour -- a "
        "commander inheriting species multipliers amplifies the raw-stat "
        "species and does nothing for the utility ones, which is why the "
        "strong rosters get commanders with little raw power.",
    ),
    Section(
        "stances", "Battlefield orders", orders.STANCE_MODS,
        "What each order does to a unit. Every richer version of the ORDER AI "
        "measured worse (see order_ai.py); these are the effects themselves, "
        "which is a different and safer thing to move.",
        groups=dict(orders.STANCE_LABEL),
    ),
    Section(
        "composition", "Army composition", lexicon.CORE_SHARES,
        "Fractions of military rating spent on each arm before species "
        "specials. A no-cavalry species redistributes its cavalry share "
        "rather than losing the headcount.",
    ),
    Section(
        "formations", "Walls, volleys & bracing", (orders, [
            "BRACE_CHARGE_MULT", "WALL_SPACING", "WALL_MAX_RANK",
            "WALL_RANK_GAP", "WALL_SLOT_TOLERANCE", "WALL_LINK_DIST",
            "WALL_COHESION_PER_NEIGHBOUR", "WALL_COHESION_MAX",
            "VOLLEY_FULL_SECONDS", "VOLLEY_DAMAGE_BONUS",
            "VOLLEY_ACCURACY_BONUS",
        ]),
        "Bracing is deliberately the clearest counter in the order set -- if "
        "it only shaved a little off a charge, nobody would spend an order on "
        "it. Volley strength is only built while something is actually in "
        "range, so it is paid for with shots given up.",
    ),
    Section(
        "order_ai", "Order AI thresholds", (order_ai, [
            "DECIDE_INTERVAL", "BRACE_RANGE", "BRACE_MOMENTUM",
            "PRESS_ADVANTAGE", "VOLLEY_HOLD_RANGE", "CLOSING_RANGE",
        ]),
        "When the AI reaches for each order. It is deliberately conservative: "
        "every richer version measured worse (walling under fire took Orcs to "
        "0% and Elves to 100%; charging under fire took Dwarves to 4%). Move "
        "these only with a tournament run to hand.",
    ),
    Section(
        "targeting", "Targeting & physics", (battle_mod, [
            "_FINISH_WEIGHT", "_CROWD_PENALTY", "_CAVALRY_ARCHER_BONUS",
            "_RETARGET_INTERVAL", "_BOUNCE", "_FRICTION", "_ARROW_SPEED",
        ]),
        "Distance dominates the target score and these are the corrections on "
        "top of it, in the same pixel scale: finish the wounded, do not "
        "dogpile, let cavalry favour archers.",
    ),
    Section(
        "commander_rules", "Commander rules", (unit_types, [
            "COMMANDER_AURA_RADIUS", "COMMANDER_SCREEN_MIN",
        ]),
        "How far a commander's aura reaches, and how many of his own soldiers "
        "must stand between him and a fight before he will advance into it.",
        # Imported BY VALUE into app/battle/unit.py -- changing the attribute
        # here alone would do nothing at all there.
        mirror=(unit_mod,),
    ),
    Section(
        "morale", "Morale", (battle_mod.Battle, [
            "MORALE_DAMAGE_MULT", "MORALE_SPEED_MULT",
        ]),
        "Applied once to every survivor the moment their commander falls.",
    ),
    Section(
        "charge", "Charge impact", (unit_mod, ["_IMPACT_CHARGE_MIN"]),
        "Momentum above which a couched hit counts as a real charge -- it "
        "spawns the impact burst, splashes, and reads as a charge in the log.",
    ),
]

_SECTIONS_BY_KEY = {s.key: s for s in SECTIONS}


# --- walking the tables -------------------------------------------------------
def _is_leaf(value):
    """Numbers and flags only.

    Strings (a unit's name, its shape), equipment lists and stance-eligibility
    tuples are deliberately NOT levers: they are structure, not balance, and a
    text box that can put an unregistered shape name into UNIT_TYPES is a crash
    waiting to be typed."""
    return isinstance(value, (bool, int, float))


def _walk(node, prefix, out):
    if isinstance(node, dict):
        for key, value in node.items():
            _walk(value, prefix + (str(key),), out)
    elif isinstance(node, (list, tuple)):
        for i, value in enumerate(node):
            _walk(value, prefix + (str(i),), out)
    elif _is_leaf(node):
        out[".".join(prefix)] = node


def _section_values(section):
    out = {}
    if section.is_scalars:
        holder, names = section.target
        for name in names:
            value = getattr(holder, name, None)
            if _is_leaf(value):
                out[name] = value
    else:
        _walk(section.target, (), out)
    return out


def _resolve(path):
    """'units.infantry.max_hp' -> (container, key) ready to read or assign."""
    section_key, _, rest = path.partition(".")
    section = _SECTIONS_BY_KEY.get(section_key)
    if section is None or not rest:
        raise KeyError(path)
    if section.is_scalars:
        holder, names = section.target
        if rest not in names:
            raise KeyError(path)
        return section, holder, rest
    node = section.target
    parts = rest.split(".")
    for part in parts[:-1]:
        node = node[int(part)] if isinstance(node, (list, tuple)) else node[part]
    last = parts[-1]
    if isinstance(node, (list, tuple)):
        raise KeyError(f"{path}: cannot assign into a tuple")
    return section, node, last


# Captured before anything can be applied, so "default" always means "what the
# source says", not "what the last override happened to leave behind".
DEFAULTS = {}
for _s in SECTIONS:
    for _k, _v in _section_values(_s).items():
        DEFAULTS[f"{_s.key}.{_k}"] = _v
DEFAULTS = copy.deepcopy(DEFAULTS)


def levers():
    """Every lever, in section order: (path, section, group, key, value).

    The group is the FIRST component under the section, not the last -- so a
    Shieldwarden's `aura.damage_taken_mult` belongs to the Shieldwarden and
    reads as `aura.damage_taken_mult` beside its other stats, rather than
    becoming a phantom "shieldwarden.aura" group of its own sitting next to the
    unit it belongs to. Same for a commander's `stats.`/`aura.`/`cleave.` and a
    species' `specials.0.`."""
    out = []
    for section in SECTIONS:
        for key, value in _section_values(section).items():
            head, _, tail = key.partition(".")
            group, leaf = (head, tail) if tail else ("", head)
            out.append((f"{section.key}.{key}", section, group, leaf, value))
    return out


def get(path):
    _, container, key = _resolve(path)
    return container[key] if isinstance(container, dict) else getattr(container, key)


def set(path, value):                                  # noqa: A001 - it is a setter
    """Assign a lever, coercing to the default's type.

    Coercion is not politeness: a JSON round-trip turns every int into an int
    but a hand-typed "18" into a string, and an int where a float belongs
    silently changes integer division nowhere but reads wrong everywhere."""
    default = DEFAULTS.get(path)
    if isinstance(default, bool):
        value = bool(value)
    elif isinstance(default, int) and not isinstance(value, bool):
        value = int(round(float(value)))
    elif isinstance(default, float):
        value = float(value)
    section, container, key = _resolve(path)
    if isinstance(container, dict):
        container[key] = value
    else:
        setattr(container, key, value)
        for module in section.mirror:
            setattr(module, key, value)
    return value


def changes():
    """Only what differs from the source defaults -- what gets saved."""
    out = {}
    for path, default in DEFAULTS.items():
        try:
            current = get(path)
        except KeyError:
            continue
        if current != default:
            out[path] = current
    return out


def apply(overrides):
    """Set many levers. Unknown paths are reported, not raised: a lever can be
    renamed or retired between builds, and an old override file should cost you
    a warning rather than a game that will not start."""
    unknown = []
    for path, value in sorted(overrides.items()):
        try:
            set(path, value)
        except (KeyError, ValueError, TypeError):
            unknown.append(path)
    return unknown


def reset():
    for path, default in DEFAULTS.items():
        try:
            if get(path) != default:
                set(path, default)
        except KeyError:
            pass


def save(path=None):
    path = path or OVERRIDES_PATH
    data = changes()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return path, len(data)


def load(path=None, quiet=False):
    """Apply the overrides file if there is one. Returns how many were applied.

    Called at startup. A missing file is the normal case and not an error --
    packaged builds do not ship `dev/`, so the game runs on source defaults."""
    path = path or OVERRIDES_PATH
    if not os.path.exists(path):
        return 0
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        if not quiet:
            print(f"[tuning] ignoring unreadable {path}: {exc}", file=sys.stderr)
        return 0
    unknown = apply(data)
    if unknown and not quiet:
        print(f"[tuning] {len(unknown)} unknown lever(s) ignored: "
              + ", ".join(unknown[:5]), file=sys.stderr)
    applied = len(data) - len(unknown)
    if applied and not quiet:
        print(f"[tuning] applied {applied} balance override(s) from {path}")
    return applied
