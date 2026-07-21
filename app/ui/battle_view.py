"""Micro battlefield screen: renders a Battle each frame and runs the sim loop
via Tk's after(). Controls: Start/Pause, Step, New Skirmish.
"""
import math
import tkinter as tk

from app.ui import theme
from app.battle.shapes import draw_shape

_FRAME_MS = 16          # ~60 fps
_DT = 1 / 60            # fixed simulation step (seconds)
_SPEEDS = [1, 2, 4]     # sim sub-steps per frame (battle speed multiplier)


class BattleView(tk.Frame):
    def __init__(self, master, on_new_skirmish):
        super().__init__(master, bg=theme.BG)
        self.on_new_skirmish = on_new_skirmish
        self.battle = None
        self.running = False
        self._after_id = None
        self._log_lines = []
        self.speed = 1

        self.canvas = tk.Canvas(self, bg=theme.CANVAS, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.render())

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

        controls = tk.Frame(p, bg=theme.PANEL)
        controls.pack(fill="x", padx=14, pady=12)
        for text, cmd in (("Start / Pause", self.toggle),
                          ("Step", self.step_once),
                          ("New Skirmish", self.on_new_skirmish)):
            tk.Button(controls, text=text, command=cmd, bg="#232a36",
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
        self.battle = battle
        self._log_lines = [subtitle] if subtitle else []
        self._render_log()
        battle.on_attack = self._on_attack
        counts = " vs ".join(f"{a.name} ({len(a.units)})" for a in battle.armies)
        self.info.config(fg=theme.INK, text=counts)
        self.render()

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
        self.running = not self.running
        if self.running:
            self._tick()

    def stop(self):
        self.running = False
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None

    def step_once(self):
        if self.battle and not self.battle.over:
            self.battle.update(_DT)
            self.render()

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
            return
        self._after_id = self.after(_FRAME_MS, self._tick)

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
        for army in self.battle.armies:
            for u in army.units:
                if u.alive:
                    draw_shape(c, u.type["shape"], u.x, u.y,
                               u.type["radius"], army.color)
                    self._draw_equipment(c, u)

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
