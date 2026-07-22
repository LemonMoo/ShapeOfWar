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

        self.canvas = tk.Canvas(self, bg=theme.CANVAS, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.render())
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

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
        self.plan_hint.config(text="Planning phase — drag your units (highlighted "
                              "outline when selected) into position. Drag over "
                              "empty ground to box-select several at once. Click "
                              "\"Deploy Army\" when ready.")
        self._update_toggle_label()
        self.render()

    def _end_planning(self):
        self.planning = False
        self.selected_units = set()
        self._drag_mode = None
        self._marquee = None
        self.plan_hint.config(text="")
        self._update_toggle_label()

    def _update_toggle_label(self):
        self.toggle_btn.config(text="Deploy Army" if self.planning else "Start / Pause")

    def _on_attack(self, attacker, target):
        import random
        if not target.alive and random.random() < 0.5:
            self._add_log(f"{attacker.faction.name} {attacker.type['name']} "
                          f"downs a {target.type['name']}")

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
            r = u.type["radius"]
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
                r = u.type["radius"]
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

    def _draw_equipment(self, c, u):
        """Sword ('t') in the right hand, shield ('o') in the left, oriented to
        whichever way the unit is facing (toward its target)."""
        eq = u.type.get("equipment")
        if not eq:
            return
        t = u.target
        if t and t.alive:
            fx, fy = t.x - u.x, t.y - u.y
            d = math.hypot(fx, fy) or 1.0
            fx, fy = fx / d, fy / d
        else:
            fx, fy = 1.0, 0.0                 # default facing: east
        # Right-hand / left-hand offset directions (perpendicular to facing).
        rhx, rhy = -fy, fx
        lhx, lhy = fy, -fx
        r = u.type["radius"]
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

        for army in self.battle.armies:
            for u in army.units:
                if u.alive:
                    draw_shape(c, u.type["shape"], u.x, u.y,
                               u.type["radius"], army.color)
                    self._draw_equipment(c, u)
                    if u in self.selected_units:
                        r = u.type["radius"]
                        c.create_oval(u.x - r - 3, u.y - r - 3, u.x + r + 3, u.y + r + 3,
                                     outline="#ffffff", width=2)

        if self._marquee is not None:
            x0, y0, x1, y1 = self._marquee
            c.create_rectangle(x0, y0, x1, y1, outline=theme.ACCENT, dash=(3, 2))

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
