"""Main application window: top nav bar, screen switching, and the glue that
stages battles from the map.
"""
import tkinter as tk

from app.ui import theme
from app.ui.main_menu import MainMenuView
from app.ui.new_game import NewGameView
from app.ui.pause_menu import PauseMenuView
from app.ui.load_game_menu import LoadGameMenuView
from app.ui.map_view import MapView
from app.ui.battle_view import BattleView
from app.core.events import bus
from app.core.save import (save_game, load_game, has_save, list_saves,
                           new_save_id, delete_save)
from app.world.worldgen import generate_world
from app.battle.battle import Battle, Army
from app.battle.unit_types import UNIT_TYPES

_GAME_SCREENS = ("map", "battle")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Shapes of War")
        self.geometry("1180x720")
        self.minsize(880, 560)
        self.configure(bg=theme.BG)

        self.world = None
        self.map_view = None
        self.battle_view = None
        self._battle_context = None
        self._battle_outcome = None
        self._current_screen = None
        self._paused = False
        self._save_id = None
        self._save_created_at = None

        self._build_topbar()

        # Content area holds every screen stacked; switch with tkraise().
        self.content = tk.Frame(self, bg=theme.BG)
        self.content.pack(fill="both", expand=True)

        self.menu_view = MainMenuView(
            self.content, on_new_game=self._goto_new_game,
            on_load_game=self._goto_load_menu, on_quit=self.destroy, has_save=has_save)
        self.new_game_view = NewGameView(
            self.content, on_play=self._start_new_game, on_back=self._goto_menu)
        self.load_game_view = LoadGameMenuView(
            self.content, on_load=self._load_selected_save,
            on_delete=self._delete_selected_save,
            on_cancel=self._cancel_load_menu)
        self.pause_view = PauseMenuView(
            self.content, on_resume=self._resume_from_pause,
            on_save=self._save_from_pause,
            on_return_to_menu=self._return_to_menu_from_pause, on_exit=self.destroy)
        for view in (self.menu_view, self.new_game_view, self.load_game_view,
                     self.pause_view):
            view.place(relx=0, rely=0, relwidth=1, relheight=1)

        bus.on("battle:over", self._on_battle_over)
        self.bind("<Escape>", self._on_escape)

        self.show_screen("menu")

    def _update_status(self):
        self.status.config(
            text=f"{len(self.world.factions)} factions · {len(UNIT_TYPES)} unit types")

    def _ensure_game_views(self):
        """Build the map/battle screens the first time a game actually
        starts (New Game or Load Game) rather than eagerly at launch."""
        if self.map_view is None:
            self.map_view = MapView(self.content, self.world,
                                    on_attack=self.stage_battle,
                                    on_regenerate=self.regenerate_world,
                                    on_end_turn=self.end_turn)
            self.battle_view = BattleView(self.content, on_new_skirmish=self.random_skirmish,
                                         on_continue=self._return_from_battle)
            for view in (self.map_view, self.battle_view):
                view.place(relx=0, rely=0, relwidth=1, relheight=1)
        else:
            self.map_view.set_world(self.world)

    # --- menu / new-game / save-load ---------------------------------------
    def _goto_menu(self):
        self.menu_view.refresh()
        self.show_screen("menu")

    def _goto_new_game(self):
        self.new_game_view.reset()
        self.show_screen("new_game")

    def _start_new_game(self, species, name):
        self.world = generate_world(player_species=species, player_name=name)
        self._ensure_game_views()
        self._save_id = new_save_id()
        self._save_created_at = save_game(self.world, self._save_id)
        self._update_status()
        self.show_screen("map")

    def _goto_load_menu(self):
        self.load_game_view.refresh(list_saves())
        self.load_game_view.tkraise()

    def _cancel_load_menu(self):
        self.menu_view.tkraise()

    def _delete_selected_save(self, save_id):
        delete_save(save_id)
        self.load_game_view.refresh(list_saves())

    def _load_selected_save(self, save_id):
        self.world = load_game(save_id)
        self._save_id = save_id
        meta = next((m for m in list_saves() if m["id"] == save_id), None)
        self._save_created_at = meta["created_at"] if meta else None
        self._ensure_game_views()
        self._update_status()
        self.show_screen("map")

    def regenerate_world(self):
        # Keep playing as the same nation, if this world has a player one.
        species = name = None
        if self.world is not None and self.world.player_faction_idx is not None:
            player = self.world.factions[self.world.player_faction_idx]
            species, name = player.meta["species"], player.name
        self.world = generate_world(player_species=species, player_name=name)
        self.map_view.set_world(self.world)
        if self._save_id is None:
            self._save_id = new_save_id()
            self._save_created_at = None
        self._save_created_at = save_game(self.world, self._save_id, self._save_created_at)
        self.show_screen("map")
        self._update_status()

    def end_turn(self):
        from app.world.resources import advance_turn
        advance_turn(self.world)

    # --- top bar -----------------------------------------------------------
    def _build_topbar(self):
        bar = tk.Frame(self, bg=theme.PANEL)
        bar.pack(fill="x")
        tk.Label(bar, text="Shapes of War", bg=theme.PANEL, fg=theme.INK,
                 font=theme.FONT_TITLE).pack(side="left", padx=14, pady=8)

        # Only shown once a game is underway (map/battle); hidden on the menu
        # and new-game setup screens, which have no in-game nav to offer.
        self.nav_frame = tk.Frame(bar, bg=theme.PANEL)
        self.nav_buttons = {}
        for name, label in (("map", "World Map"), ("battle", "Battlefield")):
            b = tk.Button(self.nav_frame, text=label, relief="flat", font=theme.FONT,
                          command=lambda n=name: self.show_screen(n))
            b.pack(side="left", padx=3, pady=8)
            self.nav_buttons[name] = b

        self.status = tk.Label(bar, text="", bg=theme.PANEL, fg=theme.MUTED,
                               font=theme.FONT)
        self.status.pack(side="right", padx=14)

    def show_screen(self, name):
        view = {"menu": self.menu_view, "new_game": self.new_game_view,
                "map": self.map_view, "battle": self.battle_view}[name]
        if view is None:
            return
        self._paused = False
        self._current_screen = name
        view.tkraise()

        if name in _GAME_SCREENS:
            self.nav_frame.pack(side="left")
            for n, b in self.nav_buttons.items():
                active = n == name
                b.config(bg=theme.ACCENT if active else "#232a36",
                         fg="#06121f" if active else theme.INK,
                         activebackground=theme.ACCENT)
            view.render()
        else:
            self.nav_frame.pack_forget()

    # --- pause menu (world map only) ----------------------------------------
    def _on_escape(self, event):
        if self._paused:
            self._resume_from_pause()
        elif self._current_screen == "map":
            self._enter_pause()

    def _enter_pause(self):
        self._paused = True
        self.pause_view.clear_message()
        self.pause_view.tkraise()

    def _resume_from_pause(self):
        self._paused = False
        self.map_view.tkraise()
        self.map_view.render()

    def _save_from_pause(self):
        try:
            if self._save_id is None:
                self._save_id = new_save_id()
                self._save_created_at = None
            self._save_created_at = save_game(self.world, self._save_id,
                                              self._save_created_at)
            ok = True
        except OSError:
            ok = False
        self.pause_view.show_message(
            "Game saved." if ok else "Save failed!",
            fg=theme.GOOD if ok else theme.BAD)

    def _return_to_menu_from_pause(self):
        self._paused = False
        self._goto_menu()

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

    def stage_battle(self, attacker, defender, county=None):
        w = max(self.battle_view.canvas.winfo_width(), 900)
        h = max(self.battle_view.canvas.winfo_height(), 600)
        battle = Battle(w, h)
        a_army, a_comp = self._army_for(attacker, 0)
        d_army, d_comp = self._army_for(defender, 1)
        battle.deploy(a_army, a_comp, 0)
        battle.deploy(d_army, d_comp, 1)

        # A specific county is normally already chosen by the map's
        # attack-target picker; fall back to a random frontline county (if
        # any) for callers that don't pick one themselves (random skirmishes,
        # sandbox worlds with no player nation).
        if county is None:
            import random
            from app.world.territory import bordering_counties
            attacker_idx = self.world.factions.index(attacker)
            defender_idx = self.world.factions.index(defender)
            frontier = bordering_counties(self.world, attacker_idx, defender_idx)
            county = random.choice(frontier) if frontier else None
        self._battle_context = {"attacker": attacker, "defender": defender,
                                "county": county}

        msg = (f"{attacker.name} marches on {county.name}, held by {defender.name}."
               if county else f"{attacker.name} marches on {defender.name}.")
        self.battle_view.set_battle(battle, msg)
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

    _ACQUISITION_MEANS = "Military Conquest"

    def _on_battle_over(self, payload):
        winner = payload.get("winner")
        ctx, self._battle_context = getattr(self, "_battle_context", None), None
        self._battle_outcome = None
        conquest = ""
        if ctx and ctx["county"]:
            county, attacker, defender = ctx["county"], ctx["attacker"], ctx["defender"]
            if winner and winner.side == 0:
                from app.world.territory import transfer_county
                attacker_idx = self.world.factions.index(attacker)
                transfer_county(self.world, county, attacker_idx)
                conquest = f" {attacker.name} seizes {county.name}!"
                self.map_view.refresh()
                self._battle_outcome = {"result": "success", "county": county,
                                        "attacker": attacker, "defender": defender}
            else:
                self._battle_outcome = {"result": "failure", "county": county,
                                        "attacker": attacker, "defender": defender,
                                        "stalemate": winner is None}
        self.status.config(
            text=(f"{winner.name} won the last battle{conquest}" if winner
                  else "Last battle: stalemate"))

    def _return_from_battle(self):
        """Called once the player dismisses the battle-over screen (click or
        keypress) — back to the map, blinking the contested county's border
        gold (won) or red (lost/stalemate)."""
        outcome = getattr(self, "_battle_outcome", None)
        self._battle_outcome = None
        self.show_screen("map")
        if outcome is None:
            return
        county, attacker, defender = outcome["county"], outcome["attacker"], outcome["defender"]
        if outcome["result"] == "success":
            self.map_view.flash_county(county, "success")
            self.map_view.show_bottom_message(
                f"{attacker.name} successfully acquired {county.name} "
                f"through {self._ACQUISITION_MEANS}.")
        else:
            self.map_view.flash_county(county, "failure")
            if outcome.get("stalemate"):
                msg = f"The battle for {county.name} ended in a stalemate."
            else:
                msg = f"{attacker.name} failed to take {county.name} from {defender.name}."
            self.map_view.show_bottom_message(msg)


def main():
    App().mainloop()
