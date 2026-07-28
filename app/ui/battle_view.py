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
from app.battle.shapes import draw_shape

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

        self.canvas = tk.Canvas(self, bg=theme.CANVAS, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.render())
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<ButtonPress-3>", self._on_rmb_press)
        self.canvas.bind("<B3-Motion>", self._on_rmb_drag)
        self.canvas.bind("<ButtonRelease-3>", self._on_rmb_release)

        self._build_panel()

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
                                  font=("Segoe UI", 9, "bold"), justify="left",
                                  wraplength=270, anchor="w")
        self.plan_hint.pack(anchor="w", padx=14, pady=(4, 0))

        controls = tk.Frame(p, bg=theme.PANEL)
        controls.pack(fill="x", padx=14, pady=12)
        self.toggle_btn = tk.Button(controls, text="Start / Pause", command=self.toggle,
                                    bg="#232a36", fg=theme.INK,
                                    activebackground=theme.ACCENT, relief="flat",
                                    font=theme.FONT)
        self.toggle_btn.pack(side="left", padx=2)
        tk.Button(controls, text="Step", command=self.step_once, bg="#232a36",
                  fg=theme.INK, activebackground=theme.ACCENT,
                  relief="flat", font=theme.FONT).pack(side="left", padx=2)

        self.speed_btn = tk.Button(controls, text="Speed 1x",
                                   command=self._cycle_speed, bg="#232a36",
                                   fg=theme.INK, activebackground=theme.ACCENT,
                                   relief="flat", font=theme.FONT)
        self.speed_btn.pack(side="left", padx=2)

        # Per-type quick-select (planning only) — mirror the 1/2/3 hotkeys.
        self.select_frame = tk.Frame(p, bg=theme.PANEL)
        self.select_frame.pack(fill="x", padx=14, pady=(0, 4))
        tk.Label(self.select_frame, text="Select:", bg=theme.PANEL, fg=theme.MUTED,
                 font=("Segoe UI", 9)).pack(side="left", padx=(0, 4))
        for label, key, hot in (("Swordsmen", "infantry", "1"),
                                ("Cavalry", "cavalry", "2"),
                                ("Archers", "archer", "3")):
            tk.Button(self.select_frame, text=f"{label} ({hot})",
                      command=lambda k=key: self._select_type(k),
                      bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                      relief="flat", font=("Segoe UI", 8)).pack(side="left", padx=1)

        self.log = tk.Label(p, text="", bg=theme.PANEL, fg=theme.MUTED,
                            font=("Consolas", 8), justify="left",
                            wraplength=270, anchor="nw")
        self.log.pack(anchor="w", padx=14, pady=8, fill="both")

    # --- battle wiring -----------------------------------------------------
    def set_battle(self, battle, subtitle=""):
        self.stop()
        self._disarm_continue()
        self.battle = battle
        self._log_lines = [subtitle] if subtitle else []
        self._render_log()
        battle.on_attack = self._on_attack
        counts = " vs ".join(f"{a.name} ({len(a.units)})" for a in battle.armies)
        self.info.config(fg=theme.INK, text=counts)

        self.planning = True
        self.selected_units = set()
        self._drag_mode = None
        self._marquee = None
        self._formation_line = None
        self._formation_slots = []
        self.plan_hint.config(text="Planning phase — left-drag your units into "
                              "position, or box-select several. Keys 1/2/3 (or "
                              "the buttons) select all Swordsmen / Cavalry / "
                              "Archers. Right-drag a line to form the selection "
                              "up along it. Space (or \"Deploy Army\") starts "
                              "the fight.")
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
        self._unbind_planning_keys()
        self.plan_hint.config(text="")
        self._update_toggle_label()

    # --- planning-phase key bindings (per-type select + Space deploy) -------
    def _bind_planning_keys(self):
        if self._planning_keys_bound:
            return
        self._planning_keys_bound = True
        self.bind_all("<Key-1>", lambda e: self._select_type("infantry"), add="+")
        self.bind_all("<Key-2>", lambda e: self._select_type("cavalry"), add="+")
        self.bind_all("<Key-3>", lambda e: self._select_type("archer"), add="+")
        self.bind_all("<space>", self._on_space_deploy, add="+")

    def _unbind_planning_keys(self):
        if not self._planning_keys_bound:
            return
        self._planning_keys_bound = False
        for seq in ("<Key-1>", "<Key-2>", "<Key-3>", "<space>"):
            self.unbind_all(seq)

    def _on_space_deploy(self, event):
        if self.planning:
            self.toggle()   # "Deploy Army" — end planning + start in one press

    def _select_type(self, type_key):
        """Select every living army-0 unit of ``type_key`` (the 1/2/3 hotkeys
        and the panel buttons both land here)."""
        if not self.planning:
            return
        self.selected_units = {u for u in self._plannable_units()
                               if u.type_key == type_key}
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

    def _on_press(self, event):
        if not self.planning:
            return
        x, y = event.x, event.y
        self._drag_start = (x, y)
        self._drag_last = (x, y)
        hit = self._unit_at(x, y)
        if hit is not None:
            if hit not in self.selected_units:
                self.selected_units = {hit}
            self._drag_mode = "move"
        else:
            self._drag_mode = "marquee"
            self._marquee = (x, y, x, y)
        self.render()

    def _on_drag(self, event):
        if not self.planning or self._drag_mode is None:
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
        if not self.planning:
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
        self.render()

    # --- formation tool: right-drag a line, snap the selection into ranks ---
    _SLOT_SPACING = 16   # px between soldiers in a formation (matches deploy grid)

    def _on_rmb_press(self, event):
        if not self.planning or not self.selected_units:
            return
        self._formation_line = (event.x, event.y, event.x, event.y)
        self._formation_slots = self._compute_formation_slots(
            self.selected_units, event.x, event.y, event.x, event.y)
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
        # bind_all so *any* click or keypress anywhere in the app dismisses
        # the battle-over screen — not just clicks on this canvas.
        self.bind_all("<Button-1>", self._on_continue, add="+")
        self.bind_all("<Key>", self._on_continue, add="+")

    def _disarm_continue(self):
        if not self._continue_armed:
            return
        self._continue_armed = False
        self.unbind_all("<Button-1>")
        self.unbind_all("<Key>")

    def _on_continue(self, event):
        self._disarm_continue()
        if self.on_continue:
            self.on_continue()

    def _living_unit_count(self):
        return sum(1 for army in self.battle.armies for u in army.units if u.alive)

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
                           fill="#11151b", outline="")
        if frac > 0:
            colour = ("#59c17a" if frac > 0.5 else
                      "#d9a441" if frac > 0.25 else "#e2604a")
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
        c = self.canvas
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w <= 1 or h <= 1:
            return
        c.create_line(w / 2, 0, w / 2, h, fill="#1c222c")

        if not self.battle:
            return

        if self.planning:
            x_min, x_max = self.battle.zone_bounds(0)
            c.create_line(x_max, 0, x_max, h, fill=theme.ACCENT, dash=(4, 3))
            c.create_text(10, 8, text="PLANNING PHASE — drag your units into position",
                         fill=theme.ACCENT, font=("Segoe UI", 11, "bold"), anchor="nw")

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
                          font=("Segoe UI", 18, "bold"))
            c.create_text(w / 2, h - 22, text="Click any button to continue...",
                          fill=theme.MUTED, font=("Segoe UI", 11, "bold"))
