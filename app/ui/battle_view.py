"""Micro battlefield screen: renders a Battle each frame and runs the sim loop
via Tk's after(). Controls: Deploy Army (planning) / Start-Pause (live), Step.

Every battle opens in a planning phase before the simulation runs: the
attacker's units (army 0 — see Battle.deploy/App.stage_battle, always the
side the player clicked "Attack" with) can be dragged into position one at a
time, or multi-selected by rubber-band-dragging a box over empty ground and
then dragged as a group — classic RTS marquee-select. The defender's side
is fixed; only your own army is ever plannable. "Deploy Army" ends planning
and starts the fight in the same click.
"""
import math
import tkinter as tk

from app.ui import theme
from app.ui import widgets
from app.ui import gl_battle
from app.battle import orders
from app.battle.shapes import draw_shape
from app.battle.unit_types import UNIT_TYPES
from app.world.lexicon import SPECIES

_FRAME_MS = 16              # ~60 fps
_DT = 1 / 60                # fixed simulation step (seconds)
_SPEEDS = [1, 2, 4, 8]      # sim sub-steps per frame (battle speed multiplier)
_CLICK_SLOP = 4             # px of movement still counted as a click, not a drag
_EQUIPMENT_DETAIL_MAX_UNITS = 160   # above this many living soldiers, stop drawing
                                     # per-soldier sword/shield glyphs -- see render().
                                     # Set from measurement, not taste: the glyphs cost
                                     # ~0.13ms per soldier, so 160 is about where a
                                     # fully-detailed frame still fits in the 16.7ms
                                     # 60fps budget


class BattleView(tk.Frame):
    def __init__(self, master, on_continue=None):
        super().__init__(master, bg=theme.BG)
        self.on_continue = on_continue
        self.battle = None
        self.running = False
        self._after_id = None
        self._log_lines = []
        self.speed = 1
        self._continue_armed = False

        # Planning phase: drag-to-move / rubber-band multi-select for the
        # attacker's (army 0) units before the fight starts — see the
        # module docstring and _on_press/_on_drag/_on_release below.
        self.planning = False
        self.selected_units = set()
        self._drag_mode = None      # None | "move" | "marquee"
        self._drag_start = None     # (x, y) canvas coords at mouse-down
        self._drag_last = None      # (x, y) last motion event, for move deltas
        self._marquee = None        # (x0, y0, x1, y1) while box-selecting
        # Formation tool (right-drag): draw a line, preview rally-flag slots,
        # snap the selection into ranks on release — see _on_rmb_* below.
        self._formation_line = None    # (x0, y0, x1, y1) while right-dragging
        self._formation_slots = []     # [(unit, x, y), ...] previewed placement
        self._planning_keys_bound = False
        self._select_types = []        # this battle's select-button/hotkey order
        self._bound_select_keys = []   # exactly what _bind_planning_keys bound

        # The battlefield surface. Preferred path is the GPU renderer
        # (app/ui/gl_battle.py) -- it draws the whole field in one instanced
        # draw call, which is what lets every soldier keep its sword and shield
        # at any army size. Falls back to the Tk canvas whenever a GL context
        # cannot be had (libraries missing, no driver, remote session), so the
        # game still runs everywhere it did before.
        self.gl = None
        self.canvas = None
        self._make_viewport()
        for seq, fn in (("<Configure>", lambda e: self.render()),
                        ("<ButtonPress-1>", self._on_press),
                        ("<B1-Motion>", self._on_drag),
                        ("<ButtonRelease-1>", self._on_release),
                        ("<ButtonPress-3>", self._on_rmb_press),
                        ("<B3-Motion>", self._on_rmb_drag),
                        ("<ButtonRelease-3>", self._on_rmb_release)):
            self.viewport.bind(seq, fn)

        # Battle-over banner: an ordinary Tk overlay, not something the GPU
        # path draws. The canvas renderer has always painted "X is victorious
        # / click to continue" as canvas items in the tail of render(); the
        # GPU path has no text primitive at all and skipped that tail
        # entirely, so a battle ending under GPU rendering left the field
        # frozen with no visible sign it was over or that anything was
        # clickable -- click-to-continue was still armed underneath (see
        # _arm_continue), there was simply nothing on screen saying so. A
        # plain Label placed on top works for either renderer and inherits
        # the "all" bindtag, so a click on the label itself still reaches
        # the globally-bound continue handler.
        self.over_banner = tk.Frame(self, bg="#000000")
        self.over_title = tk.Label(self.over_banner, text="", bg="#000000",
                                   fg="#ffffff", font=theme.FONT_TITLE)
        self.over_title.pack(pady=(10, 2), padx=40)
        self.over_sub = tk.Label(self.over_banner, text="Click anywhere to continue...",
                                 bg="#000000", fg=theme.MUTED,
                                 font=theme.FONT_BOLD)
        self.over_sub.pack(pady=(0, 10))

        self._build_panel()

    def _make_viewport(self):
        """Build the battlefield surface, GPU if we can get one."""
        # Created optimistically and judged LAZILY. A GL context only exists
        # once Tk has actually mapped the widget, and this view is built long
        # before the battle screen is ever raised -- testing for a context here
        # always failed and silently demoted every machine to the canvas.
        # Failure is detected in render() instead, where the frame is on screen.
        if gl_battle.gl_available():
            try:
                frame = gl_battle.GLBattleFrame(self, self, width=900, height=600)
                frame.pack(side="left", fill="both", expand=True)
                self.gl = frame
                self.viewport = frame
                return
            except Exception:
                self.gl = None
        self.canvas = tk.Canvas(self, bg=theme.CANVAS, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.viewport = self.canvas

    def _fallback_to_canvas(self):
        """Swap a dead GL surface for the canvas, mid-session if need be."""
        dead, self.gl = self.gl, None
        try:
            dead.destroy()
        except Exception:
            pass
        self.canvas = tk.Canvas(self, bg=theme.CANVAS, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.viewport = self.canvas
        for seq, fn in (("<Configure>", lambda e: self.render()),
                        ("<ButtonPress-1>", self._on_press),
                        ("<B1-Motion>", self._on_drag),
                        ("<ButtonRelease-1>", self._on_release),
                        ("<ButtonPress-3>", self._on_rmb_press),
                        ("<B3-Motion>", self._on_rmb_drag),
                        ("<ButtonRelease-3>", self._on_rmb_release)):
            self.viewport.bind(seq, fn)

    def viewport_size(self):
        """(width, height) of the battlefield surface, whichever backend."""
        return (self.viewport.winfo_width(), self.viewport.winfo_height())

    @property
    def using_gpu(self):
        return self.gl is not None and not self.gl.failed

    def _build_panel(self):
        p = tk.Frame(self, bg=theme.PANEL, width=300)
        p.pack(side="right", fill="y")
        p.pack_propagate(False)

        tk.Label(p, text="Battle", bg=theme.PANEL, fg=theme.INK,
                 font=theme.FONT_TITLE).pack(anchor="w", padx=14, pady=(14, 6))
        self.info = tk.Label(p, text="No battle staged.", bg=theme.PANEL,
                             fg=theme.MUTED, font=theme.FONT, justify="left",
                             wraplength=270, anchor="w")
        self.info.pack(anchor="w", padx=14)
        self.plan_hint = tk.Label(p, text="", bg=theme.PANEL, fg=theme.ACCENT,
                                  font=theme.FONT_SMALL_BOLD, justify="left",
                                  wraplength=270, anchor="w")
        self.plan_hint.pack(anchor="w", padx=14, pady=(4, 0))

        controls = tk.Frame(p, bg=theme.PANEL)
        controls.pack(fill="x", padx=14, pady=12)
        self.toggle_btn = widgets.button(controls, "Start / Pause", self.toggle)
        self.toggle_btn.pack(side="left", padx=2)
        widgets.button(controls, "Step", self.step_once).pack(side="left", padx=2)

        self.speed_btn = widgets.button(controls, "Speed 1x", self._cycle_speed)
        self.speed_btn.pack(side="left", padx=2)

        # Per-type quick-select: click a unit, rubber-band a box over several,
        # or use one of these buttons (or its hotkey) to grab every living
        # unit of that type at once -- the base three plus, dynamically, this
        # army's own species specials (see _build_select_buttons, called from
        # set_battle once the battle's actual species is known). Each button
        # carries a live "selected / alive" count so it also doubles as a
        # roster readout, not just a selector.
        tk.Label(p, text="Select (click a unit, drag a box, or a button below):",
                bg=theme.PANEL, fg=theme.MUTED, font=theme.FONT_SMALL
                ).pack(anchor="w", padx=14, pady=(0, 2))
        self.select_frame = tk.Frame(p, bg=theme.PANEL)
        self.select_frame.pack(fill="x", padx=14, pady=(0, 4))
        self._select_buttons = {}    # type_key -> (button, base label)

        # --- orders (app/battle/orders.py) ---------------------------------
        # Available during the fight, not just planning: an order you cannot
        # give once the lines meet is not much of an order.
        self.orders_frame = tk.Frame(p, bg=theme.PANEL)
        self.orders_frame.pack(fill="x", padx=14, pady=(8, 0))
        tk.Label(self.orders_frame, text="ORDERS", bg=theme.PANEL, fg=theme.ACCENT,
                 font=theme.FONT_HEADER).pack(anchor="w")
        self.order_hint = tk.Label(self.orders_frame, text="", bg=theme.PANEL,
                                   fg=theme.MUTED, font=theme.FONT_SMALL,
                                   justify="left", wraplength=270, anchor="w")
        self.order_hint.pack(anchor="w", pady=(0, 3))

        # Live-phase orders, not folded behind a click: these are given under
        # time pressure mid-fight, unlike the map's leisurely detail panels,
        # so every stance/fire button stays one click away at all times.
        self._order_buttons = {}
        for label, hot, kind, value in (
                ("Hold Here", "H", "stance", orders.STANCE_HOLD),
                ("Charge", "C", "stance", orders.STANCE_CHARGE),
                ("Advance", "A", "stance", orders.STANCE_ADVANCE),
                ("Shield Wall", "S", "stance", orders.STANCE_SHIELD_WALL),
                ("Firing Line", "L", "stance", orders.STANCE_FIRING_LINE),
                ("Charge & Regroup", "R", "stance", orders.STANCE_CYCLE_CHARGE),
                ("Fire at Will", "F", "fire", True),
                ("Hold Fire", "X", "fire", False)):
            btn = widgets.button(self.orders_frame, f"{label}  ({hot})",
                                  lambda k=kind, v=value: self._issue_order(k, v))
            btn.pack(fill="x", pady=1)
            self._order_buttons[(kind, value)] = btn

        self.log = tk.Label(p, text="", bg=theme.PANEL, fg=theme.MUTED,
                            font=theme.FONT_LOG, justify="left",
                            wraplength=270, anchor="nw")
        self.log.pack(anchor="w", padx=14, pady=8, fill="both")

    # --- issuing orders ----------------------------------------------------
    def _issue_order(self, kind, value):
        """Apply an order to the current selection. Reports what ACTUALLY took
        it, not what was clicked -- selecting a mixed group and pressing Shield
        Wall should say '12 Swordsmen form a shield wall', not silently do
        nothing to the archers in the box."""
        if not self.battle or self.battle.over:
            return
        units = [u for u in self.selected_units if u.alive]
        if not units:
            self.order_hint.config(text="Select units first — drag a box over "
                                        "your troops, or press 1/2/3.")
            return
        if kind == "stance":
            n = self.battle.issue_stance(units, value)
            if n:
                self._add_log(f"» {n} ordered: {orders.STANCE_LABEL[value]}")
            else:
                self._add_log(f"» Nobody selected can {orders.STANCE_LABEL[value]}")
        else:
            n = self.battle.issue_fire_discipline(units, value)
            if n:
                self._add_log(f"» {n} archers: "
                              f"{'fire at will' if value else 'hold fire'}")
            else:
                self._add_log("» No archers selected")
        self._refresh_order_buttons()
        self.render()

    def _refresh_order_buttons(self):
        """Grey out orders the current selection cannot carry out, so the panel
        teaches which arm does what instead of failing silently on click."""
        if not hasattr(self, "_order_buttons"):
            return
        units = [u for u in self.selected_units if u.alive]
        types = {u.type_key for u in units}
        has_ranged = any(u._ranged for u in units)
        for (kind, value), btn in self._order_buttons.items():
            if kind == "fire":
                ok = has_ranged
            else:
                ok = any(value in orders.allowed_stances(t) for t in types)
            btn.config(state="normal" if ok else "disabled",
                       fg=theme.INK if ok else theme.LINE)
        if not units:
            self.order_hint.config(text="No units selected.")
        else:
            stances = {orders.STANCE_LABEL.get(u.stance, u.stance) for u in units}
            self.order_hint.config(
                text=f"{len(units)} selected — {', '.join(sorted(stances))}")

    # --- battle wiring -----------------------------------------------------
    def set_battle(self, battle, subtitle=""):
        self.stop()
        self._disarm_continue()
        self.battle = battle
        self._log_lines = [subtitle] if subtitle else []
        self._render_log()
        battle.on_attack = self._on_attack
        # The player orders army 0; every other side is driven by the order AI
        # (app/battle/order_ai.py) so both armies fight with the same toolkit.
        battle.player_side = 0
        counts = " vs ".join(f"{a.name} ({len(a.units)})" for a in battle.armies)
        self.info.config(fg=theme.INK, text=counts)
        # Say which renderer is live. A packaged build that quietly failed to
        # get a GL context looks exactly like one that never had the GPU path,
        # and the only visible symptom is soldiers losing their weapons in big
        # battles -- which is easy to mistake for a design choice.
        self._add_log("Renderer: GPU (accelerated)" if self.using_gpu
                      else "Renderer: canvas (no GPU context)")

        self._build_select_buttons()

        self.planning = True
        self.selected_units = set()
        self._drag_mode = None
        self._marquee = None
        self._formation_line = None
        self._formation_slots = []
        hotkeys = "/".join(str(i + 1) for i in range(len(self._select_types)))
        self.plan_hint.config(text="Planning phase — click a unit to select it, "
                              "left-drag your units into position, or drag a box "
                              f"over several. Keys {hotkeys} (or the buttons "
                              "above) select every living unit of that type at "
                              "once; 0 selects everyone, Commander included. "
                              "Right-drag a line to form the selection up "
                              "along it. Space (or \"Deploy Army\") starts the "
                              "fight.")
        self._bind_planning_keys()
        self._update_toggle_label()
        self.render()

    def _end_planning(self):
        self.planning = False
        self.selected_units = set()
        self._drag_mode = None
        self._marquee = None
        self._formation_line = None
        self._formation_slots = []
        # Keys stay bound through the fight -- selection and order hotkeys are
        # exactly what the live phase needs. They come off when the battle ends
        # (_arm_continue), so the battle-over screen isn't taking order presses.
        hotkeys = "/".join(str(i + 1) for i in range(len(self._select_types)))
        self.plan_hint.config(text="Click a unit, drag a box, or a button above "
                                   f"({hotkeys}, 0 for everyone) to select troops, "
                                   "then give orders below. Right-click a spot to "
                                   "move the selection there, or an enemy to send "
                                   "them straight at it -- overrides the "
                                   "Commander's usual caution. Space pauses so you "
                                   "can think.")
        self._refresh_order_buttons()
        self._update_toggle_label()

    # --- per-type select buttons: base three plus this army's own species
    # specials (see app.world.lexicon.SPECIES) -- built fresh per battle since
    # which specials exist (and how many: Goblins alone field two) depends on
    # which species army 0 actually is. ------------------------------------
    _BASE_SELECT_TYPES = ("infantry", "cavalry", "archer")

    def _build_select_buttons(self):
        for w in self.select_frame.winfo_children():
            w.destroy()
        self._select_buttons = {}

        species = None
        if self.battle and self.battle.armies:
            species = getattr(self.battle.armies[0], "species", None)
        specials = [spec["unit"] for spec in SPECIES.get(species, {}).get("specials", ())]
        self._select_types = list(self._BASE_SELECT_TYPES) + specials

        for i, type_key in enumerate(self._select_types):
            label = UNIT_TYPES.get(type_key, {}).get("name", type_key.capitalize())
            hot = str(i + 1)
            btn = widgets.button(self.select_frame, f"{label} ({hot})",
                                  lambda k=type_key: self._select_type(k),
                                  compact=True)
            btn.pack(side="left", padx=1)
            self._select_buttons[type_key] = (btn, label)
        # Separate from the per-type buttons (own key, own colour) rather than
        # just another entry in _select_types: "everyone" isn't a unit type,
        # it's the complement of all of them, and it's the one selection that
        # also grabs the Commander -- nothing else does, since he has no type
        # button of his own (see _plannable_units, which never excludes him).
        self.select_all_btn = widgets.button(
            self.select_frame, "All (0)", self._select_all, kind="accent", compact=True)
        self.select_all_btn.pack(side="left", padx=(6, 1))
        self._update_select_counts()

    def _update_select_counts(self):
        """Refresh each select button's '(selected/alive)' count -- live, not
        just at plan time, so a button also reads as a roster count that
        thins out as the fight actually goes (see render()'s call to this)."""
        if not hasattr(self, "_select_buttons"):
            return
        units = self._plannable_units()
        for type_key, (btn, label) in self._select_buttons.items():
            alive = [u for u in units if u.type_key == type_key]
            selected = sum(1 for u in alive if u in self.selected_units)
            hot = str(self._select_types.index(type_key) + 1)
            count = f"{selected}/{len(alive)}" if selected else str(len(alive))
            btn.config(text=f"{label} ({hot}) · {count}")
        if hasattr(self, "select_all_btn"):
            total = len(units)
            selected = sum(1 for u in units if u in self.selected_units)
            count = f"{selected}/{total}" if selected else str(total)
            self.select_all_btn.config(text=f"All (0) · {count}")

    # --- key bindings: per-type select, order hotkeys, Space ---------------
    # Bound for the whole battle, not just planning: orders are given during
    # the fight, so the selection keys have to keep working then too.
    _ORDER_KEYS = {
        "h": ("stance", orders.STANCE_HOLD),
        "c": ("stance", orders.STANCE_CHARGE),
        "a": ("stance", orders.STANCE_ADVANCE),
        "s": ("stance", orders.STANCE_SHIELD_WALL),
        "r": ("stance", orders.STANCE_CYCLE_CHARGE),
        "l": ("stance", orders.STANCE_FIRING_LINE),
        "f": ("fire", True),
        "x": ("fire", False),
    }

    def _bind_planning_keys(self):
        if self._planning_keys_bound:
            return
        self._planning_keys_bound = True
        self._bound_select_keys = list(self._select_types)
        for i, type_key in enumerate(self._select_types):
            self.bind_all(f"<Key-{i + 1}>",
                          lambda e, k=type_key: self._select_type(k), add="+")
        # 0 for "all" -- the natural complement of the 1-5 per-type keys, and
        # never collides with them since a real species fields at most 5
        # distinct selectable types (3 base + Goblins' 2 specials).
        self.bind_all("<Key-0>", lambda e: self._select_all(), add="+")
        self.bind_all("<space>", self._on_space_deploy, add="+")
        for key, (kind, value) in self._ORDER_KEYS.items():
            self.bind_all(f"<Key-{key}>",
                          lambda e, k=kind, v=value: self._issue_order(k, v),
                          add="+")

    def _unbind_planning_keys(self):
        if not self._planning_keys_bound:
            return
        self._planning_keys_bound = False
        for i in range(len(getattr(self, "_bound_select_keys", ()))):
            self.unbind_all(f"<Key-{i + 1}>")
        self.unbind_all("<Key-0>")
        self.unbind_all("<space>")
        for key in self._ORDER_KEYS:
            self.unbind_all(f"<Key-{key}>")

    def _on_space_deploy(self, event):
        # Planning: deploy. Live: tactical pause -- Space is how you stop the
        # fight to look at it and give several orders at once.
        if self.planning or (self.battle and not self.battle.over):
            self.toggle()

    def _select_type(self, type_key):
        """Select every living army-0 unit of ``type_key`` (the 1/2/3 hotkeys
        and the panel buttons both land here)."""
        if not self._can_select():
            return
        self.selected_units = {u for u in self._plannable_units()
                               if u.type_key == type_key}
        self._refresh_order_buttons()
        self.render()

    def _select_all(self):
        """Select every living army-0 unit, of any type -- including the
        Commander, who has no per-type button of his own (see
        _plannable_units, which never filters him out)."""
        if not self._can_select():
            return
        self.selected_units = set(self._plannable_units())
        self._refresh_order_buttons()
        self.render()

    def _update_toggle_label(self):
        self.toggle_btn.config(text="Deploy Army" if self.planning else "Start / Pause")

    def _on_attack(self, attacker, target, outcome="hit"):
        import random
        if outcome == "block":
            if random.random() < 0.15:   # sample blocks so the log isn't spammed
                self._add_log(f"{target.faction.name} {target.type['name']} "
                              f"blocks with their shield")
            return
        if outcome == "dodge":
            if random.random() < 0.15:   # sampled, same reasoning as blocks
                self._add_log(f"{target.faction.name} {target.type['name']} "
                              f"ducks under the blow")
            return
        if not target.alive and random.random() < 0.5:
            downs = (f"{attacker.faction.name} {attacker.type['name']} "
                     f"downs a {target.type['name']}")
            if attacker.type.get("charge") and attacker.charge == 0.0:
                # charge just spent on this killing blow -> it was a couched hit
                downs = (f"{attacker.faction.name} {attacker.type['name']} "
                         f"rides down a {target.type['name']}")
            self._add_log(downs)

    def _add_log(self, line):
        self._log_lines.insert(0, line)
        del self._log_lines[16:]
        self._render_log()

    def _render_log(self):
        self.log.config(text="\n".join(self._log_lines))

    # --- loop --------------------------------------------------------------
    def toggle(self):
        if not self.battle:
            return
        if self.planning:
            self._end_planning()   # "Deploy Army" -> confirm placement and...
        self.running = not self.running    # ...start the fight in the same click
        if self.running:
            self._tick()

    def stop(self):
        self.running = False
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None

    def step_once(self):
        if self.planning:
            return
        if self.battle and not self.battle.over:
            self.battle.update(_DT)
            self.render()
            if self.battle.over:
                self._arm_continue()

    def _cycle_speed(self):
        self.speed = _SPEEDS[(_SPEEDS.index(self.speed) + 1) % len(_SPEEDS)]
        self.speed_btn.config(text=f"Speed {self.speed}x")

    def _tick(self):
        if not self.running or not self.battle:
            return
        for _ in range(self.speed):        # more sub-steps = faster battle
            self.battle.update(_DT)
            if self.battle.over:
                break
        self.render()
        if self.battle.over:
            self.running = False
            self._arm_continue()
            return
        self._after_id = self.after(_FRAME_MS, self._tick)

    # --- planning phase: drag-to-move + rubber-band multi-select -----------
    def _plannable_units(self):
        """Army 0's living units — the only ones a player ever repositions
        (see the module docstring for why it's always army 0)."""
        if not self.battle or not self.battle.armies:
            return []
        return [u for u in self.battle.armies[0].units if u.alive]

    def _unit_at(self, x, y):
        """The plannable unit under (x, y), nearest first, or None."""
        best, best_d2 = None, None
        for u in self._plannable_units():
            r = u.radius
            d2 = (u.x - x) ** 2 + (u.y - y) ** 2
            if d2 <= r * r and (best_d2 is None or d2 < best_d2):
                best, best_d2 = u, d2
        return best

    def _any_unit_at(self, x, y):
        """The nearest LIVING unit under (x, y) from ANY army, own or enemy --
        used by the live-phase right-click order (see _on_rmb_press) to tell
        "attack that specific enemy" apart from "move to this empty ground"."""
        if not self.battle:
            return None
        best, best_d2 = None, None
        for army in self.battle.armies:
            for u in army.units:
                if not u.alive:
                    continue
                r = u.radius
                d2 = (u.x - x) ** 2 + (u.y - y) ** 2
                if d2 <= r * r and (best_d2 is None or d2 < best_d2):
                    best, best_d2 = u, d2
        return best

    def _on_press(self, event):
        # Selection works during the fight too, not just in planning -- orders
        # are given to whatever is selected, so being unable to select mid-battle
        # would make the whole order system unreachable once the fight started.
        # Only DRAGGING units to a new position stays planning-only.
        if not self._can_select():
            return
        x, y = event.x, event.y
        self._drag_start = (x, y)
        self._drag_last = (x, y)
        hit = self._unit_at(x, y)
        if hit is not None:
            if hit not in self.selected_units:
                self.selected_units = {hit}
            self._drag_mode = "move" if self.planning else "marquee"
            if self._drag_mode == "marquee":
                self._marquee = (x, y, x, y)
        else:
            self._drag_mode = "marquee"
            self._marquee = (x, y, x, y)
        self._refresh_order_buttons()
        self.render()

    def _can_select(self):
        return self.battle is not None and not self.battle.over

    def _on_drag(self, event):
        if not self._can_select() or self._drag_mode is None:
            return
        x, y = event.x, event.y
        if self._drag_mode == "move":
            lx, ly = self._drag_last
            dx, dy = x - lx, y - ly
            x_min, x_max = self.battle.zone_bounds(0)
            for u in self.selected_units:
                r = u.radius
                u.x = min(x_max - r, max(x_min + r, u.x + dx))
                u.y = min(self.battle.height - r, max(r, u.y + dy))
            self._drag_last = (x, y)
        else:   # marquee
            sx, sy = self._drag_start
            self._marquee = (sx, sy, x, y)
        self.render()

    def _on_release(self, event):
        if not self._can_select():
            return
        if self._drag_mode == "marquee" and self._marquee is not None:
            x0, y0, x1, y1 = self._marquee
            if abs(x1 - x0) > _CLICK_SLOP or abs(y1 - y0) > _CLICK_SLOP:
                lo_x, hi_x = sorted((x0, x1))
                lo_y, hi_y = sorted((y0, y1))
                self.selected_units = {u for u in self._plannable_units()
                                       if lo_x <= u.x <= hi_x and lo_y <= u.y <= hi_y}
            else:
                self.selected_units = set()   # plain click on empty ground -> deselect
        self._drag_mode = None
        self._drag_start = None
        self._marquee = None
        self._refresh_order_buttons()
        self.render()

    # --- formation tool: right-drag a line, snap the selection into ranks ---
    _SLOT_SPACING = 16   # px between soldiers in a formation (matches deploy grid)

    def _on_rmb_press(self, event):
        if self.planning:
            if not self.selected_units:
                return
            self._formation_line = (event.x, event.y, event.x, event.y)
            self._formation_slots = self._compute_formation_slots(
                self.selected_units, event.x, event.y, event.x, event.y)
            self.render()
            return
        self._issue_direct_order(event.x, event.y)

    def _issue_direct_order(self, x, y):
        """MOBA-style right-click order for whatever's currently selected,
        live-phase only: an enemy under the cursor becomes a pinned attack
        target (Unit.manual_target), empty ground becomes a move-to point
        (Unit.move_point) -- both override Battle.choose_target's own
        scoring and the commander's screening safety net (see
        Unit._player_directed) for exactly as long as they're active. This
        is the one place either attribute is ever written, so a save/load or
        a fresh battle never carries a stale order forward."""
        if not self.battle or self.battle.over or not self.selected_units:
            return
        hit = self._any_unit_at(x, y)
        mine_sides = {u.faction.side for u in self.selected_units}
        is_enemy = hit is not None and hit.alive and hit.faction.side not in mine_sides
        for u in self.selected_units:
            if not u.alive:
                continue
            if is_enemy:
                u.manual_target = hit
                u.move_point = None
            else:
                u.move_point = (x, y)
                u.manual_target = None
        if is_enemy:
            self._add_log(f"» {len(self.selected_units)} ordered to attack "
                          f"{hit.faction.name}'s {hit.type['name']}")
        else:
            self._add_log(f"» {len(self.selected_units)} ordered to move")
        self.render()

    def _on_rmb_drag(self, event):
        if not self.planning or self._formation_line is None:
            return
        x0, y0, _, _ = self._formation_line
        self._formation_line = (x0, y0, event.x, event.y)
        self._formation_slots = self._compute_formation_slots(
            self.selected_units, x0, y0, event.x, event.y)
        self.render()

    def _on_rmb_release(self, event):
        if not self.planning or self._formation_line is None:
            return
        for u, sx, sy in self._formation_slots:
            u.x, u.y = sx, sy
        self._formation_line = None
        self._formation_slots = []
        self.render()

    def _compute_formation_slots(self, units, x0, y0, x1, y1):
        """One target (x, y) per selected unit, laid out in ranks along the
        drawn line A->B: units fill the front rank left-to-right along the
        line, then wrap into successive ranks stacked *behind* it (toward your
        own edge, away from the enemy), spaced by _SLOT_SPACING and clamped to
        your half. Sorted by type so like troops cluster. Returns
        [(unit, x, y), ...]."""
        order = {"infantry": 0, "cavalry": 1, "archer": 2}
        us = sorted(units, key=lambda u: (order.get(u.type_key, 9), id(u)))
        if not us:
            return []
        ax, ay = x0, y0
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        if length < 1.0:
            along = (0.0, 1.0)         # a mere click -> a single column downward
        else:
            along = (dx / length, dy / length)
        # "behind" = the perpendicular pointing toward your own (left) edge, so
        # extra ranks stack away from the enemy rather than toward them.
        p1 = (-along[1], along[0])
        perp = p1 if p1[0] <= 0 else (-p1[0], -p1[1])

        spacing = self._SLOT_SPACING
        capacity = max(1, int(length // spacing) + 1)
        x_min, x_max = self.battle.zone_bounds(0)
        h = self.battle.height
        slots = []
        for i, u in enumerate(us):
            col, rank = i % capacity, i // capacity
            sx = ax + along[0] * col * spacing + perp[0] * rank * spacing
            sy = ay + along[1] * col * spacing + perp[1] * rank * spacing
            r = u.radius
            sx = min(x_max - r, max(x_min + r, sx))
            sy = min(h - r, max(r, sy))
            slots.append((u, sx, sy))
        return slots

    # --- "click any button to continue" after a battle ----------------------
    def _arm_continue(self):
        if self._continue_armed:
            return
        self._continue_armed = True
        # Orders are over -- drop the hotkeys before binding the dismiss-any-key
        # handler, or a stray "h" would both try to issue an order and dismiss.
        self._unbind_planning_keys()
        self.selected_units = set()
        # bind_all so *any* click or keypress anywhere in the app dismisses
        # the battle-over screen — not just clicks on this canvas.
        self.bind_all("<Button-1>", self._on_continue, add="+")
        self.bind_all("<Key>", self._on_continue, add="+")
        # The canvas renderer draws its own "X is victorious" banner as
        # canvas items every render() call, so it needs nothing further. The
        # GPU renderer draws no text at all, so without this overlay a
        # battle ending under it left the field simply frozen -- see the
        # comment where over_banner is built.
        if self.using_gpu and self.battle is not None:
            winner = self.battle.winner
            self.over_title.config(
                text=f"{winner.name} is victorious" if winner else "Mutual annihilation")
            # Centered over the BATTLEFIELD, not the whole frame (which also
            # includes the 300px side panel) -- matches where the canvas
            # renderer's own banner lands, via place()'s in_ parameter rather
            # than reparenting the widget.
            self.over_banner.place(relx=0.5, rely=0.5, anchor="center",
                                   in_=self.viewport)
            self.over_banner.lift()

    def _disarm_continue(self):
        if not self._continue_armed:
            return
        self._continue_armed = False
        self.unbind_all("<Button-1>")
        self.unbind_all("<Key>")
        self.over_banner.place_forget()

    def _on_continue(self, event):
        self._disarm_continue()
        if self.on_continue:
            self.on_continue()

    def _living_unit_count(self):
        return sum(1 for army in self.battle.armies for u in army.units if u.alive)

    # A unit under a non-default order gets a small coloured tick above it, so
    # you can see at a glance which parts of your line are braced, walled or
    # running -- and read the enemy's intent the same way. One canvas item, and
    # only for units actually carrying an order, so a default-stance army costs
    # nothing extra to draw.
    _ORDER_CUE = {
        orders.STANCE_HOLD: theme.ORDER_CUE_HOLD,
        orders.STANCE_CHARGE: theme.ORDER_CUE_CHARGE,
        orders.STANCE_SHIELD_WALL: theme.ORDER_CUE_SHIELD_WALL,
        orders.STANCE_CYCLE_CHARGE: theme.ORDER_CUE_CYCLE_CHARGE,
        orders.STANCE_FIRING_LINE: theme.ORDER_CUE_FIRING_LINE,
    }

    def _draw_order_cue(self, c, u):
        colour = self._ORDER_CUE.get(u.stance)
        if colour is not None:
            y = u.y - u.radius - 4
            c.create_line(u.x - 3, y, u.x + 3, y, fill=colour, width=2)
        # Archers drawing a held volley show it filling up -- the whole point of
        # holding fire is knowing when the volley is worth releasing.
        if u._ranged and not u.fire_at_will and u.volley > 0:
            y = u.y - u.radius - 8
            c.create_line(u.x - 4, y, u.x - 4 + 8 * u.volley, y,
                          fill="#e8c46a", width=2)

    def _draw_commander(self, c, u, army):
        """The Commander: an oversized disc in the army's colour with a
        contrasting inner disc, plus a health bar no other unit gets.

        Triple radius and the bullseye centre carry the identification on their
        own -- the separate halo ring this used to draw sat outside the body and
        mostly read as clutter once a melee closed around him.
        """
        r = u.radius
        draw_shape(c, u.type["shape"], u.x, u.y, r, army.color)
        ir = r * 0.5
        c.create_oval(u.x - ir, u.y - ir, u.x + ir, u.y + ir,
                      fill="#ffffff", outline="")
        # Health bar -- unique to the commander, because he is the only unit
        # whose individual health is worth tracking.
        frac = max(0.0, min(1.0, u.hp / u.max_hp))
        bw, by = r * 2.2, u.y - r - 12
        c.create_rectangle(u.x - bw / 2, by, u.x + bw / 2, by + 4,
                           fill=theme.METER_TRACK, outline="")
        if frac > 0:
            colour = (theme.GOOD if frac > 0.5 else
                      theme.WARN if frac > 0.25 else theme.BAD)
            c.create_rectangle(u.x - bw / 2, by, u.x - bw / 2 + bw * frac, by + 4,
                               fill=colour, outline="")

    def _draw_equipment(self, c, u):
        """Sword ('t') in the right hand, shield ('o') in the left, oriented to
        whichever way the unit is facing (toward its target)."""
        eq = u.type.get("equipment")
        if not eq:
            return
        # Unit.facing is the shared source of truth (also drives the shield's
        # frontal block arc) — defaults to east until the unit picks a target.
        fx, fy = u.facing
        # Right-hand / left-hand offset directions (perpendicular to facing).
        rhx, rhy = -fy, fx
        lhx, lhy = fy, -fx
        r = u.radius
        if "sword" in eq:
            # Scimitar thrust forward: the blade points in the facing direction
            # (tip toward the enemy, hilt toward the body), held out in front and
            # slightly to the right hand. An upright 't' has its tip pointing
            # screen-down (0,1); Tk's `angle` rotates counterclockwise, so
            # angle = atan2(fx, fy) aligns the blade with the forward direction.
            fwd, side = r * 0.7, r * 0.5
            angle = math.degrees(math.atan2(fx, fy))
            c.create_text(u.x + fx * fwd + rhx * side,
                          u.y + fy * fwd + rhy * side, text="t",
                          fill="#f0e6c8", font=("Consolas", 9, "bold"),
                          angle=angle)
        if "shield" in eq:                    # 'o' is symmetric — no rotation needed
            c.create_text(u.x + lhx * (r + 4), u.y + lhy * (r + 4), text="o",
                          fill="#a9d4ff", font=("Consolas", 8, "bold"))
        if "daggers" in eq:
            # Two short blades, one per hand, angled slightly outward — small
            # and paired so an Assassin never reads as a swordsman even at the
            # sizes a real battle draws at.
            fwd = r * 0.55
            angle = math.degrees(math.atan2(fx, fy))
            for hx, hy in ((rhx, rhy), (lhx, lhy)):
                c.create_text(u.x + fx * fwd + hx * (r * 0.8),
                              u.y + fy * fwd + hy * (r * 0.8), text="i",
                              fill="#e6d2a8", font=("Consolas", 7, "bold"),
                              angle=angle)

    def _draw_effects(self, c):
        """Block sparks (a quick light-blue ring where a shield deflected a
        blow) and charge impacts (a bigger burst in the rider's color where a
        couched hit landed) — both from battle.effects, fading as t/dur → 1."""
        for e in self.battle.effects:
            f = min(1.0, e.t / e.dur)      # 0 (fresh) .. 1 (faded)
            if e.kind == "block":
                r = 5 + 6 * f
                c.create_oval(e.x - r, e.y - r, e.x + r, e.y + r,
                              outline=e.color, width=max(1, int(2 * (1 - f))))
            elif e.kind == "dodge":
                # A quick sidestep: a short motion-blur streak that drifts and
                # fades, rather than the ring a solid parry gets.
                off = 10 * f
                c.create_line(e.x - off, e.y - off * 0.4, e.x + off, e.y + off * 0.4,
                              fill=e.color, width=max(1, int(2 * (1 - f))))
            elif e.kind == "shock":
                # The charge's AOE going off: a heavy ring racing out to the
                # real radius that was damaged (Effect.size), with a second
                # ring chasing it, so a cavalry charge slamming a line reads as
                # one big shared event rather than a scatter of single hits.
                r = e.size * (0.35 + 0.65 * f)
                width = max(1, int(4 * (1 - f)))
                c.create_oval(e.x - r, e.y - r, e.x + r, e.y + r,
                              outline=e.color, width=width)
                r2 = r * 0.6
                c.create_oval(e.x - r2, e.y - r2, e.x + r2, e.y + r2,
                              outline=e.color, width=max(1, width - 1))
                for ang in (0.0, 1.05, 2.09, 3.14, 4.19, 5.24):
                    c.create_line(e.x + math.cos(ang) * r2, e.y + math.sin(ang) * r2,
                                  e.x + math.cos(ang) * r, e.y + math.sin(ang) * r,
                                  fill=e.color, width=width)
            else:  # "impact" — a couched charge landing
                r = 7 + 12 * f
                c.create_oval(e.x - r, e.y - r, e.x + r, e.y + r,
                              outline=e.color, width=max(1, int(3 * (1 - f))))
                # a couple of radial spokes for a "slam" read
                for ang in (0.4, 2.0, 3.6, 5.2):
                    c.create_line(e.x, e.y,
                                  e.x + math.cos(ang) * r, e.y + math.sin(ang) * r,
                                  fill=e.color, width=max(1, int(2 * (1 - f))))

    # --- rendering ---------------------------------------------------------
    def render(self):
        # Select-button counts are UI chrome, not battlefield geometry -- kept
        # live regardless of which renderer draws the field below, so they
        # keep thinning out as units actually die during a running fight.
        self._update_select_counts()
        # GPU path: the whole field is one instanced draw call, so there is no
        # per-item work to do here at all. Everything below is the canvas
        # fallback, kept intact and still correct.
        if self.gl is not None:
            self.gl.render_now()
            if not self.gl.failed:
                return
            self._fallback_to_canvas()   # GL died on a live machine; carry on
        c = self.canvas
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w <= 1 or h <= 1:
            return
        c.create_line(w / 2, 0, w / 2, h, fill=theme.LINE)

        if not self.battle:
            return

        if self.planning:
            x_min, x_max = self.battle.zone_bounds(0)
            c.create_line(x_max, 0, x_max, h, fill=theme.ACCENT, dash=(4, 3))
            c.create_text(10, 8, text="PLANNING PHASE — drag your units into position",
                         fill=theme.ACCENT, font=theme.FONT_BOLD, anchor="nw")

        # Level of detail: the per-soldier sword/shield glyphs are two extra
        # canvas items each, one of them ROTATED text, and they measure at
        # ~70-80% of the entire frame cost. Armies now scale with a realm's
        # population (see resources._recompute_military), so a developed one
        # fields hundreds of soldiers -- at which point each is a few pixels
        # across and the glyphs are illegible anyway. Drop them past the
        # threshold and the same frame costs ~5x less; below it nothing
        # changes and every soldier still shows its kit.
        show_equipment = self._living_unit_count() <= _EQUIPMENT_DETAIL_MAX_UNITS
        for army in self.battle.armies:
            for u in army.units:
                if u.alive:
                    if getattr(u, "is_commander", False):
                        self._draw_commander(c, u, army)
                        continue
                    draw_shape(c, u.type["shape"], u.x, u.y,
                               u.radius, army.color)
                    if show_equipment:
                        self._draw_equipment(c, u)
                    if u in self.selected_units:
                        r = u.radius
                        c.create_oval(u.x - r - 3, u.y - r - 3, u.x + r + 3, u.y + r + 3,
                                     outline="#ffffff", width=2)
                    self._draw_order_cue(c, u)

        if self._marquee is not None:
            x0, y0, x1, y1 = self._marquee
            c.create_rectangle(x0, y0, x1, y1, outline=theme.ACCENT, dash=(3, 2))

        # Formation tool: the drawn line + a rally flag / ghost at each slot
        # the selection will snap into.
        if self._formation_line is not None:
            fx0, fy0, fx1, fy1 = self._formation_line
            c.create_line(fx0, fy0, fx1, fy1, fill=theme.ACCENT, dash=(2, 2))
        for u, sx, sy in self._formation_slots:
            r = u.radius
            draw_shape(c, u.type["shape"], sx, sy, r, "#3d4757")   # dim ghost
            c.create_line(sx, sy - r, sx, sy - r - 11, fill=theme.ACCENT)  # flag pole
            c.create_polygon(sx, sy - r - 11, sx + 7, sy - r - 8,
                             sx, sy - r - 5, fill=theme.ACCENT, outline="")

        self._draw_effects(c)

        # Arrows in flight, drawn on top as '.'.
        for p in self.battle.projectiles:
            c.create_text(p.x, p.y, text=".", fill=p.color,
                          font=("Consolas", 13, "bold"))

        if self.battle.over:
            msg = (f"{self.battle.winner.name} is victorious"
                   if self.battle.winner else "Mutual annihilation")
            c.create_rectangle(0, h / 2 - 26, w, h / 2 + 26,
                               fill="#000000", stipple="gray50", outline="")
            c.create_text(w / 2, h / 2, text=msg, fill="#ffffff",
                          font=theme.FONT_TITLE)
            c.create_text(w / 2, h - 22, text="Click any button to continue...",
                          fill=theme.MUTED, font=theme.FONT_BOLD)
