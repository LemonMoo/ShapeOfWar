"""Main application window: top nav bar, screen switching, and the glue that
stages battles from the map.
"""
import tkinter as tk

from app.ui import theme
from app.ui.map_view import MapView
from app.ui.battle_view import BattleView
from app.core.events import bus
from app.world.worldgen import generate_world
from app.battle.battle import Battle, Army
from app.battle.unit_types import UNIT_TYPES


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Shapes of War")
        self.geometry("1180x720")
        self.minsize(880, 560)
        self.configure(bg=theme.BG)

        self.world = generate_world()
        self._build_topbar()

        # Content area holds both screens stacked; switch with tkraise().
        self.content = tk.Frame(self, bg=theme.BG)
        self.content.pack(fill="both", expand=True)

        self.map_view = MapView(self.content, self.world,
                                on_attack=self.stage_battle,
                                on_regenerate=self.regenerate_world)
        self.battle_view = BattleView(self.content, on_new_skirmish=self.random_skirmish)
        for view in (self.map_view, self.battle_view):
            view.place(relx=0, rely=0, relwidth=1, relheight=1)

        bus.on("battle:over", self._on_battle_over)

        self.show_screen("map")
        self._update_status()

    def _update_status(self):
        self.status.config(
            text=f"{len(self.world.factions)} factions · {len(UNIT_TYPES)} unit types")

    def regenerate_world(self):
        self.world = generate_world()
        self.map_view.set_world(self.world)
        self.show_screen("map")
        self._update_status()

    # --- top bar -----------------------------------------------------------
    def _build_topbar(self):
        bar = tk.Frame(self, bg=theme.PANEL)
        bar.pack(fill="x")
        tk.Label(bar, text="Shapes of War", bg=theme.PANEL, fg=theme.INK,
                 font=theme.FONT_TITLE).pack(side="left", padx=14, pady=8)

        self.nav_buttons = {}
        for name, label in (("map", "World Map"), ("battle", "Battlefield")):
            b = tk.Button(bar, text=label, relief="flat", font=theme.FONT,
                          command=lambda n=name: self.show_screen(n))
            b.pack(side="left", padx=3, pady=8)
            self.nav_buttons[name] = b

        self.status = tk.Label(bar, text="", bg=theme.PANEL, fg=theme.MUTED,
                               font=theme.FONT)
        self.status.pack(side="right", padx=14)

    def show_screen(self, name):
        view = self.map_view if name == "map" else self.battle_view
        view.tkraise()
        for n, b in self.nav_buttons.items():
            active = n == name
            b.config(bg=theme.ACCENT if active else "#232a36",
                     fg="#06121f" if active else theme.INK,
                     activebackground=theme.ACCENT)
        view.render()

    # --- battle staging ----------------------------------------------------
    def _army_for(self, nation, side):
        army = Army(nation.name, nation.color, side)
        power = nation.stats["military"]
        composition = {
            "infantry": round(power * 0.4),
            "archer": round(power * 0.25),
            "cavalry": round(power * 0.2),
        }
        return army, composition

    def stage_battle(self, attacker, defender):
        w = max(self.battle_view.canvas.winfo_width(), 900)
        h = max(self.battle_view.canvas.winfo_height(), 600)
        battle = Battle(w, h)
        a_army, a_comp = self._army_for(attacker, 0)
        d_army, d_comp = self._army_for(defender, 1)
        battle.deploy(a_army, a_comp, 0)
        battle.deploy(d_army, d_comp, 1)
        self.battle_view.set_battle(battle, f"{attacker.name} marches on {defender.name}.")
        self.show_screen("battle")

    def random_skirmish(self):
        import random
        from app.world.world_map import Stance
        factions = self.world.factions
        if len(factions) < 2:
            return
        # Prefer a real rivalry; fall back to any two factions.
        enemy_pairs = []
        for f in factions:
            for r in self.world.world_map.relationships_of(f.id):
                if r["stance"] == Stance.ENEMY:
                    enemy_pairs.append((f, r["other"]))
        if enemy_pairs:
            self.stage_battle(*random.choice(enemy_pairs))
        else:
            self.stage_battle(*random.sample(factions, 2))

    def _on_battle_over(self, payload):
        winner = payload.get("winner")
        self.status.config(
            text=f"{winner.name} won the last battle" if winner
            else "Last battle: stalemate")


def main():
    App().mainloop()
