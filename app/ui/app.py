"""Main application window: top nav bar, screen switching, and the glue that
stages battles from the map.
"""
import gc
import os
import subprocess
import sys
import tkinter as tk

from app.ui import theme
from app.ui.main_menu import MainMenuView
from app.ui.new_game import NewGameView
from app.ui.pause_menu import PauseMenuView
from app.ui.load_game_menu import LoadGameMenuView
from app.ui.map_view import MapView
from app.ui.battle_view import BattleView
from app.ui.game_over import GameOverView
from app.core.events import bus
from app.core.save import (save_game, load_game, has_save, list_saves,
                           new_save_id, delete_save)
from app.world.worldgen import generate_world
from app.core import audio
from app.core import clock
from app.ui.settings import SettingsPanel
from app.battle.battle import (Battle, Army, terrain_note,
                               weather_note)
from app.battle.unit_types import UNIT_TYPES

_GAME_SCREENS = ("map", "battle")


class _WildlandDefender:
    """Stand-in 'nation' for a wildland-garrison battle (see
    stage_wildland_battle) — just enough attributes for Army composition
    and battle messaging (App._army_for/stage_battle) to treat it like a
    normal defender. Never added to world.factions; region.faction_idx
    stays UNCLAIMED throughout, which territory.transfer_region already
    knows how to move land out of."""

    def __init__(self, military):
        self.name = "Wildland Garrison"
        self.color = "#6b4a3a"
        self.stats = {"military": military}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Shapes of War")
        self.geometry("1180x720")
        self.minsize(880, 560)
        self.configure(bg=theme.BG)

        # Sound. Never fatal: audio.init() returns False on a machine with no
        # device and everything downstream of it no-ops, so the game plays
        # exactly as it did before rather than refusing to start.
        audio.init()
        audio.load_settings()

        self.world = None
        self.map_view = None
        self.battle_view = None
        self._battle_context = None
        self._battle_outcome = None
        self._current_screen = None
        self._paused = False
        self._save_id = None
        self._save_created_at = None
        self._pending_elimination = None   # see _on_faction_eliminated
        self._pending_defeat = None        # see _on_faction_eliminated/_flush_pending_defeat

        self._build_topbar()

        # Content area holds every screen stacked; switch with tkraise().
        self.content = tk.Frame(self, bg=theme.BG)
        self.content.pack(fill="both", expand=True)

        self.menu_view = MainMenuView(
            self.content, on_new_game=self._goto_new_game,
            on_load_game=self._goto_load_menu, on_quit=self.destroy, has_save=has_save,
            on_settings=self._open_settings,
            on_balance_lab=self._open_balance_lab if self._balance_lab_path() else None)
        self.new_game_view = NewGameView(
            self.content, on_play=self._start_new_game, on_back=self._goto_menu)
        self.load_game_view = LoadGameMenuView(
            self.content, on_load=self._load_selected_save,
            on_delete=self._delete_selected_save,
            on_cancel=self._cancel_load_menu)
        self.pause_view = PauseMenuView(
            self.content, on_resume=self._resume_from_pause,
            on_save=self._save_from_pause, on_settings=self._open_settings,
            on_return_to_menu=self._return_to_menu_from_pause, on_exit=self.destroy)
        self.game_over_view = GameOverView(
            self.content, on_return_to_menu=self._return_to_menu_from_defeat,
            on_exit=self.destroy)
        # One settings panel, not one per menu -- two would drift apart. It
        # remembers which screen asked for it so Back goes where you came
        # from rather than always dumping you at the main menu.
        self._settings_return = "menu"
        self.settings_view = SettingsPanel(
            self.content, on_close=self._close_settings)
        for view in (self.menu_view, self.new_game_view, self.load_game_view,
                     self.pause_view, self.game_over_view, self.settings_view):
            view.place(relx=0, rely=0, relwidth=1, relheight=1)

        bus.on("battle:over", self._on_battle_over)
        bus.on("faction:eliminated", self._on_faction_eliminated)
        # The other two auto-pause rules. Both exist because a running world
        # scrolls past things a turn-based one left sitting in a panel until
        # you looked.
        bus.on("region:transferred", self._on_region_transferred)
        bus.on("work:finished", self._on_work_finished)
        self.bind("<Escape>", self._on_escape)
        self.bind("<F1>", self._on_f1)
        # bind_all, not bind: a plain bind on the root only fires while focus
        # is somewhere inside the root's own widget tree, and this game has
        # real child Toplevels -- the Compendium and the Build Menu -- which
        # take focus when opened. With a root bind, E and V simply stopped
        # working after opening either one, and started again if you happened
        # to click back on the map, which is exactly the "works sometimes"
        # this fixes. bind_all reaches every window in the application.
        for key, handler in (("e", self._on_skip_day_key),
                             ("E", self._on_skip_day_key),
                             ("space", self._on_time_key),
                             ("v", self._on_toggle_mode_key),
                             ("V", self._on_toggle_mode_key)):
            self.bind_all(f"<{key}>", handler)

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
                                    on_end_turn=self.end_turn,
                                    on_wildland_claim=self.stage_wildland_battle,
                                    on_turn_settled=self._flush_pending_defeat)
            self.battle_view = BattleView(self.content, on_continue=self._return_from_battle)
            for view in (self.map_view, self.battle_view):
                view.place(relx=0, rely=0, relwidth=1, relheight=1)
        else:
            self.map_view.set_world(self.world)

    # --- menu / new-game / save-load ---------------------------------------
    def _balance_lab_path(self):
        """Path to dev/balance_lab.py, or None if this is a packaged build
        (build.bat's PyInstaller run never bundles dev/) or the script isn't
        there for some other reason. Checked once at startup so a frozen exe
        never even shows the button."""
        if getattr(sys, "frozen", False):
            return None
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        path = os.path.join(repo_root, "dev", "balance_lab.py")
        return path if os.path.isfile(path) else None

    def _open_balance_lab(self):
        """Balance Lab is its own Tk root running a tournament in-process
        (see dev/balance_lab.py) -- a second tk.Tk() sharing this process's
        mainloop isn't something Tkinter supports, so it launches as a
        separate process instead of a Toplevel."""
        path = self._balance_lab_path()
        if path is not None:
            subprocess.Popen([sys.executable, path])

    def _goto_menu(self):
        self.menu_view.refresh()
        self.show_screen("menu")

    def _goto_new_game(self):
        self.new_game_view.reset()
        self.show_screen("new_game")

    def _prepare_world_gc(self):
        """Exclude the just-loaded world's object graph from the cyclic
        GC's periodic scans. Diagnosed from a reported GPU-flat-map stutter
        that turned out not to be GPU-bound at all (GPU usage stayed near
        0% through it) or GL-specific (the GPU map, sharing the same
        moderngl/pyopengltk plumbing, never showed it): a developed world
        is one big, long-lived object graph (regions, villages,
        settlements, roads, factions...) that Python's cyclic collector
        tracks like everything else, and _sync_flatgl's own per-frame work
        (rebuilding line/marker/label lists while panning) allocates enough
        short-lived garbage to periodically cross the threshold for a full
        generation-2 collection -- which has to scan EVERY tracked object,
        not just the garbage. On a large save that scan alone measured
        150ms+. gc.freeze() moves everything currently alive (the world,
        essentially) into a permanent generation the collector skips
        entirely, so only the actual per-frame garbage ever gets scanned.

        gc.unfreeze() first: without it, loading a SECOND world in the same
        session (new game after new game, or load after load) would pin
        the previous world's cyclic garbage in memory forever instead of
        letting it be collected -- freezing is otherwise permanent."""
        gc.unfreeze()
        gc.collect()
        gc.freeze()

    def _start_new_game(self, world):
        # The world arrives already generated: the New Game screen builds it in
        # the background while the player is still naming things, and hands over
        # the exact one they were looking at in its preview. Generating a fresh
        # one here would mean the preview was a lie.
        self.world = world
        self._prepare_world_gc()
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
        self._prepare_world_gc()
        self._save_id = save_id
        meta = next((m for m in list_saves() if m["id"] == save_id), None)
        self._save_created_at = meta["created_at"] if meta else None
        self._ensure_game_views()
        self._update_status()
        self.show_screen("map")

    def end_turn(self):
        from app.world.resources import advance_turn
        advance_turn(self.world)

    # --- faction elimination -----------------------------------------------
    def _on_faction_eliminated(self, payload):
        """A nation has lost its last region (see
        app/world/territory.py's eliminate_faction). Somebody else's defeat
        is news; the player's own ends the run.

        The defeat screen is deferred with after_idle rather than raised
        inline: this fires from deep inside transfer_region, which is itself
        called from the middle of resolving a battle or a turn, and tearing
        the map out from under that mid-resolution leaves the caller drawing
        into a screen that's no longer showing."""
        if self.world is None:
            return
        dead_idx = payload["faction_idx"]
        if dead_idx != self.world.player_faction_idx:
            # Queued rather than shown now: this fires while the battle screen
            # is still up, and _return_from_battle overwrites the bottom
            # message with its own conquest line the moment the player
            # dismisses it — so announcing here would be invisible or
            # instantly clobbered. Flushed there instead.
            self._pending_elimination = payload
            return
        if False:   # was: a background turn thread owned `world` and could
                    # reach this listener off the main thread. There is no
                    # such thread any more -- the day is stepped between
                    # frames on the main thread (MapView._on_frame) -- so
                    # after_idle here is always safe. Kept as a branch rather
                    # than deleted so the stash/flush path below, which is
                    # still exercised by the battle case above, reads the
                    # same as it always did.
            # advance_turn can reach eliminate_faction (and this listener)
            # from MapView's background turn-processing thread, through
            # ordinary AI claim resolution -- after_idle must never be
            # called off the main thread. Stash it instead; MapView calls
            # _flush_pending_defeat once the turn has actually finished
            # settling back on the main thread.
            self._pending_defeat = payload
            return
        self.after_idle(lambda: self._show_defeat(payload))

    def _flush_pending_defeat(self):
        """MapView's on_turn_settled callback (main thread, right after a
        background turn finishes) -- see _on_faction_eliminated."""
        payload = self._pending_defeat
        if payload is not None:
            self._pending_defeat = None
            self._show_defeat(payload)

    def _show_defeat(self, payload):
        from app.world import resources
        turn = getattr(self.world, "turn", 0)
        self.game_over_view.set_result(
            payload["faction"].name, payload["conqueror"].name, turn,
            year=resources.current_year(turn))
        self._paused = False
        self.show_screen("game_over")

    def _return_to_menu_from_defeat(self):
        """Back to the main menu after a defeat. The save is deliberately
        left on disk: deleting the player's run for them is not this
        screen's call to make, and the Load Game menu can still delete it."""
        self.world = None
        self._save_id = None
        self._save_created_at = None
        self._goto_menu()

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
        for name, label in (("map", "World Map"),):
            b = tk.Button(self.nav_frame, text=label, relief="flat", font=theme.FONT,
                          command=lambda n=name: self.show_screen(n))
            b.pack(side="left", padx=3, pady=8)
            self.nav_buttons[name] = b

        self.status = tk.Label(bar, text="", bg=theme.PANEL, fg=theme.MUTED,
                               font=theme.FONT)
        self.status.pack(side="right", padx=14)

    def _open_settings(self):
        self._settings_return = self._current_screen
        self.settings_view.tkraise()
        self._current_screen = "settings"

    def _close_settings(self):
        back = self._settings_return
        if back in ("map", "battle") and self.map_view is None:
            back = "menu"      # settings opened before a game existed
        if back == "pause":
            self.pause_view.tkraise()
            self._current_screen = "pause"
            return
        self.show_screen(back if back != "settings" else "menu")

    def show_screen(self, name):
        view = {"menu": self.menu_view, "new_game": self.new_game_view,
                "map": self.map_view, "battle": self.battle_view,
                "game_over": self.game_over_view}[name]
        if view is None:
            return
        self._paused = False
        self._current_screen = name
        # Music follows the screen. play_music ignores a request for the track
        # already playing, so moving between the menu and the map does not
        # restart it -- only actually going to war changes the tune.
        audio.play_music("battle" if name == "battle" else "map")
        view.tkraise()
        # tkraise() only changes stacking order, never keyboard focus -- an
        # Entry on the screen being left (the New Game screen's realm-name/
        # ruler-name fields are the real case this bit: their StringVars
        # carry a live trace that re-applies whatever they contain onto the
        # actual game world on every keystroke, by design, so the preview
        # updates as you type) would otherwise go on quietly receiving and
        # inserting every keypress from behind whatever screen is now on
        # top, including single-letter shortcuts like E for End Turn --
        # silently renaming your kingdom one keystroke at a time, turn
        # after turn. Moving focus to the new screen's own frame on every
        # transition means a leftover Entry never keeps eating keystrokes
        # once its screen isn't the one showing any more.
        view.focus_set()

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

    def _on_f1(self, event):
        """Global shortcut for the Compendium (see MapView.open_compendium) —
        works from any game screen, not just the map, since the content
        doesn't depend on world state."""
        if self.map_view is not None:
            self.map_view.open_compendium()

    _TEXT_ENTRY_CLASSES = frozenset(("Entry", "TEntry", "Text", "Spinbox",
                                     "TSpinbox", "TCombobox"))

    def _is_typing(self, event):
        """True when the key belongs to a text field rather than to the game.

        Needed because these are bind_all now (see __init__): a single letter
        is both a shortcut and a character, and the Compendium's search box is
        a real Entry the player types into. Checked on the event's own widget,
        which is the one the keystroke was actually delivered to."""
        widget = getattr(event, "widget", None)
        try:
            return widget.winfo_class() in self._TEXT_ENTRY_CLASSES
        except (AttributeError, tk.TclError):
            return False

    def _on_time_key(self, event):
        """Space: stop or start the world. The one control that matters in a
        real-time game is the one that stops it, so it gets the biggest key.

        Same gating End Turn had: only while actually looking at the map, and
        never while typing (a faction name on the New Game screen contains
        spaces)."""
        if self._is_typing(event):
            return
        if self._current_screen == "map" and not self._paused:
            self.map_view._toggle_pause()

    def _on_skip_day_key(self, event):
        """E: run one whole day right now, whatever the clock is doing --
        the old End Turn cadence, kept because stepping the world by hand is
        how most of this project's testing is done."""
        if self._is_typing(event):
            return
        if self._current_screen == "map" and not self._paused:
            self.map_view.skip_a_day()

    def _on_toggle_mode_key(self, event):
        """V: cycle the map's view mode (Political/Fertility/Elevation/
        Biome/Climate -- see MapView._toggle_mode), same gating as End Turn.
        Also inert while a background turn is processing (MapView.render()
        would just no-op it anyway -- skipping the call keeps the key
        feeling inert rather than silently swallowed)."""
        if self._is_typing(event):
            return
        if self._current_screen == "map" and not self._paused:
            self.map_view._toggle_mode()

    # --- pause menu (world map only) ----------------------------------------
    def _on_escape(self, event):
        # Ignored outright while a turn is processing in the background: the
        # only things Escape can reach from here -- entering the pause menu
        # (whose Save writes `world` to disk) and _resume_from_pause's
        # map_view.render() call -- are both unsafe while the worker thread
        # in MapView still owns `world`. See MapView._run_end_turn.
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
        """Build a side's Army + unit composition from its military rating.

        Composition itself lives in lexicon.army_composition, which is the one
        place that decides it -- the balance tournament calls the same function
        rather than keeping a hand-copied duplicate that can silently drift out
        of step with what the game actually fields. A _WildlandDefender has no
        `meta` and so no species: it gets the default mix and baseline stats."""
        from app.world.lexicon import army_composition
        species = getattr(nation, "meta", {}).get("species")
        army = Army(nation.name, nation.color, side, species=species)
        return army, army_composition(species, nation.stats["military"])

    def stage_battle(self, attacker, defender, region=None, claim_project=None,
                     defender_strength_mult=1.0):
        # The world stops for a battle. Strongest of the auto-pause rules and
        # the one that makes real time survivable at all: a fight takes real
        # minutes, and a map that kept running through them would hand back a
        # world the player had no chance to act in.
        self._pause_world_for(clock.BATTLE)
        # Via viewport_size, not .canvas: the battlefield surface may be the
        # GPU frame rather than a Tk canvas (see BattleView._make_viewport).
        vw, vh = self.battle_view.viewport_size()
        w = max(vw, 900)
        h = max(vh, 600)
        battle = Battle(w, h)

        # A specific region is normally already chosen by the map's
        # attack-target picker; fall back to a random frontline region (if
        # any) for callers that don't pick one themselves (random skirmishes,
        # sandbox worlds with no player nation). Never hit for a wildland
        # claim battle — stage_wildland_battle always supplies `region`, and
        # a _WildlandDefender isn't in world.factions for .index() to find.
        #
        # Resolved BEFORE deploying: the ground a battle is fought on is baked
        # into each unit as it spawns (Battle.set_terrain), so it has to be
        # known first. It used to be worked out after, when nothing downstream
        # of it cared.
        if region is None:
            import random
            from app.world.territory import bordering_regions
            attacker_idx = self.world.factions.index(attacker)
            defender_idx = self.world.factions.index(defender)
            frontier = bordering_regions(self.world, attacker_idx, defender_idx)
            region = random.choice(frontier) if frontier else None
        battle.set_terrain(getattr(region, "dominant_biome", None))
        # ...and what the sky is doing over it (weather phase 4). Only owned
        # regions have weather simulated at all (resources.advance_weather),
        # so a fight in the wildlands is fought on a clear day -- the same
        # limit travel.py documents, and for the same reason.
        battle.set_weather((getattr(self.world, "region_weather", None) or {}
                            ).get(region.id) if region is not None else None)

        a_army, a_comp = self._army_for(attacker, 0)
        d_army, d_comp = self._army_for(defender, 1)
        battle.deploy(a_army, a_comp, 0)
        battle.deploy(d_army, d_comp, 1, strength_mult=defender_strength_mult)
        self._battle_context = {"attacker": attacker, "defender": defender,
                                "region": region, "claim_project": claim_project,
                                "armies": (a_army, d_army)}

        msg = (f"{attacker.name} marches on {region.name}, held by {defender.name}."
               if region else f"{attacker.name} marches on {defender.name}.")
        note = terrain_note(battle.biome)
        if note:
            msg += f"  ({battle.biome.capitalize()}: {note}.)"
        sky = weather_note(battle.weather_event)
        if sky:
            msg += f"  ({sky.capitalize()}.)"
        audio.play("battle_start")
        self.battle_view.set_battle(battle, msg)
        self.show_screen("battle")

    def stage_wildland_battle(self, project):
        """Fight for a region whose claim construction has finished — the
        interactive battlefield replaces the old instant win/loss formula
        (still used for AI claims, see app/world/expansion.py). The
        garrison's Army is sized from the region's wildland_strength via
        the exact same composition formula _army_for already uses for a
        real nation's military stat, but each of its soldiers fights at
        WILDLAND_COMBAT_STRENGTH_MULT — the same discount the AI's instant
        formula applies to wildland_strength itself. An amphibious
        (sea-only) claim faces a bigger garrison, SEA_ONLY_STRENGTH_MULT
        more, matching the tougher odds its instant-resolve path rolls
        against."""
        from app.world import expansion
        player = self.world.factions[project.faction_idx]
        region = self.world.regions[project.region_id]
        strength = region.wildland_strength
        if getattr(project, "sea_only", False):
            strength = round(strength * expansion.SEA_ONLY_STRENGTH_MULT)
        defender = _WildlandDefender(strength)
        self.stage_battle(player, defender, region, claim_project=project,
                          defender_strength_mult=expansion.WILDLAND_COMBAT_STRENGTH_MULT)

    _ACQUISITION_MEANS = "Military Conquest"

    def _on_battle_over(self, payload):
        """Fires synchronously the instant the battle simulation itself
        detects a winner (see Battle.update/bus.emit) -- still mid-frame
        inside battle_view's own animation loop, well before the player
        has dismissed the battle-over screen. World-state mutations
        (transferring the region, resolving a claim) happen here since
        they're cheap and need to take effect immediately regardless of
        when the visuals catch up -- but map_view.refresh() specifically
        does NOT: it's the single most expensive thing MapView ever does
        (a full O(w*h) political-color rebuild once territory actually
        changed hands), and running it here used to inject that cost into
        the battle's own final animation frame, showing up as a visible
        hitch right at the moment of victory, before the screen had even
        switched. It's deferred to _return_from_battle instead, so any
        pause lands on the screen transition the player already expects
        to take a beat, not mid-fight."""
        winner = payload.get("winner")
        ctx, self._battle_context = getattr(self, "_battle_context", None), None
        self._resolve_commander_losses(ctx)
        self._battle_outcome = None
        conquest = ""
        if ctx and ctx["region"]:
            region, attacker, defender = ctx["region"], ctx["attacker"], ctx["defender"]
            claim_project = ctx.get("claim_project")
            if winner and winner.side == 0:
                attacker_idx = self.world.factions.index(attacker)
                spoils = None
                if claim_project is not None:
                    from app.world import expansion
                    spoils = expansion.resolve_claim_win(self.world, region,
                                                         attacker_idx)
                else:
                    from app.world.territory import transfer_region
                    transfer_region(self.world, region, attacker_idx)
                conquest = f" {attacker.name} seizes {region.name}!"
                # Spoils are the whole point of the rebalance -- say what was
                # taken, or the player just sees an empty region arrive.
                if spoils:
                    gold = spoils.get("Gold", 0)
                    goods = sum(v for k, v in spoils.items() if k != "Gold")
                    bits = []
                    if gold:
                        bits.append(f"{gold:,} Gold")
                    if goods:
                        bits.append(f"{goods:,} units of stores")
                    if bits:
                        conquest += f" Spoils: {' and '.join(bits)}."
                self._battle_outcome = {"result": "success", "region": region,
                                        "attacker": attacker, "defender": defender}
            else:
                if claim_project is not None:
                    from app.world import expansion
                    expansion.resolve_claim_loss(self.world, region)
                self._battle_outcome = {"result": "failure", "region": region,
                                        "attacker": attacker, "defender": defender,
                                        "stalemate": winner is None}
            if claim_project is not None and claim_project in self.world.claim_projects:
                self.world.claim_projects.remove(claim_project)
        self.status.config(
            text=(f"{winner.name} won the last battle{conquest}" if winner
                  else "Last battle: stalemate"))

    def _resolve_commander_losses(self, ctx):
        """Carry a commander's death on the battlefield back to the world.

        Army.commander_lost is latched the moment he falls (see
        Battle._check_morale), so this reads the same flag the morale penalty
        used rather than re-deriving anything. A wildland garrison has no
        faction and so no world commander to lose -- only real nations do.
        """
        self._commander_losses = []
        if not ctx:
            return
        from app.world import commander as commander_mod
        armies = ctx.get("armies") or ()
        for army, nation in zip(armies, (ctx.get("attacker"), ctx.get("defender"))):
            if nation is None or not getattr(army, "commander_lost", False):
                continue
            try:
                fac_idx = self.world.factions.index(nation)
            except ValueError:
                continue        # _WildlandDefender -- not a real faction
            if commander_mod.kill_commander(self.world, fac_idx):
                self._commander_losses.append((fac_idx, nation.name))

    def _on_region_transferred(self, payload):
        """Territory changed hands. Stop the clock if it was OURS -- losing a
        province while reading a panel is exactly the failure real time
        introduces, and the one the player asked to be protected from."""
        if self.world is None or self.world.player_faction_idx is None:
            return
        old_faction = payload.get("old_faction")
        if old_faction is None:
            return
        player = self.world.factions[self.world.player_faction_idx]
        if old_faction is player:
            self._pause_world_for(clock.ATTACKED)

    def _on_work_finished(self, payload):
        """Something the player ordered built is finished."""
        if self.world is None:
            return
        if payload.get("faction_idx") == self.world.player_faction_idx:
            self._pause_world_for(clock.PROJECT_DONE)

    def _pause_world_for(self, reason):
        """Stop the clock because something happened, and leave the world in a
        state it is safe to walk away from.

        The part-done day is FINISHED first rather than left mid-phase. A
        battle can change territory and kill commanders, and resuming a day
        that was half-run before all that happened would apply the rest of it
        to a world it was no longer written against."""
        if self.map_view is None:
            return
        # Only when we are NOT inside a phase. Two of the three rules fire
        # from world code running mid-day (a region changing hands, a
        # settlement finishing), and finishing the day from in there means
        # calling next() on the generator currently executing. Pausing the
        # clock is enough by itself -- it stops the NEXT day, and the one in
        # progress completes on its own on the following frame.
        if self.map_view.runner.busy and not self.map_view.runner.stepping:
            self.map_view.runner.finish_day()
            self.map_view._finish_day()
        self.map_view.clock.auto_pause_for(reason)
        self.map_view._refresh_time_controls()

    def _return_from_battle(self):
        """Called once the player dismisses the battle-over screen (click or
        keypress) — back to the map, blinking the contested region's border
        gold (won) or red (lost/stalemate). The expensive map_view.refresh()
        deferred from _on_battle_over (see its docstring) runs here, right
        before the screen actually switches, so any recompute cost lands on
        the transition itself rather than the battle's last animation frame."""
        outcome = getattr(self, "_battle_outcome", None)
        self._battle_outcome = None
        eliminated = getattr(self, "_pending_elimination", None)
        self._pending_elimination = None
        losses = getattr(self, "_commander_losses", None) or []
        self._commander_losses = []
        if outcome is not None:
            self.map_view.refresh()
        # Real minutes spent fighting are not days the world owes. The clock
        # stays PAUSED -- coming back from a battle to a world already running
        # is how you lose the province you just won without seeing it happen.
        self.map_view.clock.forgive_backlog()
        self.map_view.reset_frame_clock()
        self.show_screen("map")
        if outcome is None:
            return
        # A commander falling outranks the battle result as news: it decides
        # whether the realm can fight at all for the next dozen turns.
        player = (self.world.factions[self.world.player_faction_idx]
                  if self.world.player_faction_idx is not None else None)
        for fac_idx, name in losses:
            if player is not None and fac_idx == self.world.player_faction_idx:
                from app.world import commander as commander_mod
                turns = commander_mod.COMMANDER_RESPAWN_TURNS
                self.map_view.show_bottom_message(
                    f"Your commander has fallen. A successor takes the field in "
                    f"{turns} turns \u2014 until then your realm cannot march.",
                    ms=7000)
            else:
                self.map_view.show_bottom_message(
                    f"{name}'s commander has fallen.", ms=5000)

        region, attacker, defender = outcome["region"], outcome["attacker"], outcome["defender"]
        if outcome["result"] == "success":
            self.map_view.flash_region(region, "success")
            if eliminated is not None:
                # Taking a nation's last region is the bigger news of the two
                # — lead with that rather than the region line.
                self.map_view.show_bottom_message(
                    f"{attacker.name} takes {region.name} — the last of "
                    f"{eliminated['faction'].name}, which is now no more.",
                    ms=6200)
            else:
                self.map_view.show_bottom_message(
                    f"{attacker.name} successfully acquired {region.name} "
                    f"through {self._ACQUISITION_MEANS}.")
        else:
            self.map_view.flash_region(region, "failure")
            if outcome.get("stalemate"):
                msg = f"The battle for {region.name} ended in a stalemate."
            else:
                msg = f"{attacker.name} failed to take {region.name} from {defender.name}."
            self.map_view.show_bottom_message(msg)


def main():
    # Balance overrides from dev/balance_lab.py, if any. A no-op when the file
    # is absent, which is every packaged build -- `dev/` is not shipped, so a
    # release always runs on the numbers in the source.
    from app.core import tuning
    tuning.load()
    App().mainloop()
