"""Title screen: New Game / Load Game / Quit, with a "What's New" panel
docked to the right (see app/core/changelog.py for the data/persistence
side) — an always-visible part of the menu now rather than a popup, so it
reads like a patch-notes sidebar instead of an interruption.

Drawn on app/ui/parchment.py's Page, like the map HUD. The buttons here were
the last things in the game still painted a hard-coded blue-grey (#232a36)
from before the palette existed at all -- the title screen is the first thing
anybody sees, and it was the least fantasy surface in the program.
"""
import tkinter as tk

from app.ui import parchment
from app.ui import theme
from app.core import changelog

_CHANGELOG_PANEL_WIDTH = 340
_MENU_WIDTH = 320


class MainMenuView(tk.Frame):
    def __init__(self, master, on_new_game, on_load_game, on_quit, has_save,
                 on_settings=None, on_balance_lab=None, on_credits=None):
        super().__init__(master, bg=theme.BG)
        self._has_save = has_save
        self._on_new_game = on_new_game
        self._on_load_game = on_load_game
        self._on_quit = on_quit
        self._on_settings = on_settings
        self._on_credits = on_credits
        self._on_balance_lab = on_balance_lab

        menu_col = tk.Frame(self, bg=theme.BG)
        menu_col.pack(side="left", fill="both", expand=True)
        holder = tk.Frame(menu_col, bg=theme.BG)
        holder.place(relx=0.5, rely=0.5, anchor="center")
        self._menu_page = parchment.Page(holder, _MENU_WIDTH, seed=21)
        self._menu_page.canvas.pack()

        self._build_changelog_panel()
        self.refresh()

    # --- the menu itself ----------------------------------------------------
    def _render_menu(self):
        """Draw the menu from state -- Load Game is present or absent rather
        than greyed out, because a drawn plaque has no disabled look and
        "there is no save" is better said by the plaque not being there."""
        page = self._menu_page
        page.begin(400)
        page.title("Shapes of War", "a world that does not wait")
        page.gap(6)
        page.button("New Game", self._on_new_game, kind="accent")
        if self._has_save():
            page.button("Load Game", self._on_load_game)
        else:
            page.text("No saved realm yet.", fill=theme.MUTED)
        if self._on_settings is not None:
            page.button("Settings", self._on_settings)
        if self._on_credits is not None:
            page.button("Credits", self._on_credits)
        page.button("Quit", self._on_quit)
        # Dev-only: only present when running from source with dev/ on disk
        # (see App._balance_lab_path) -- a packaged build never ships dev/,
        # so this simply doesn't exist there rather than erroring.
        if self._on_balance_lab is not None:
            page.gap(6)
            page.button("Balance Lab (dev)", self._on_balance_lab)
        page.finish()

    # --- "What's New" panel -------------------------------------------------
    def _build_changelog_panel(self):
        panel = tk.Frame(self, bg=theme.PANEL, width=_CHANGELOG_PANEL_WIDTH)
        panel.pack(side="right", fill="y")
        panel.pack_propagate(False)

        body = tk.Frame(panel, bg=theme.PANEL)
        body.pack(fill="both", expand=True)
        canvas = tk.Canvas(body, bg=theme.PANEL, highlightthickness=0)
        scrollbar = tk.Scrollbar(body, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self._changelog_page = parchment.Page(None, _CHANGELOG_PANEL_WIDTH - 20,
                                              seed=22, canvas=canvas)
        # The Scrollbar alone is draggable but easy to miss -- bind the
        # mousewheel too, only while actually hovering this canvas (same
        # bind_all-on-Enter/unbind-on-Leave pattern as the map's RESOURCES
        # sidebar), so scrolling here doesn't hijack the wheel everywhere
        # else on the title screen.
        canvas.bind("<Enter>", lambda e: canvas.bind_all(
            "<MouseWheel>", lambda ev: canvas.yview_scroll(int(-ev.delta / 120), "units")))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        self._changelog_canvas = canvas

    def _refresh_changelog_panel(self):
        """The full version history, oldest entries still just a scroll
        away instead of vanishing once dismissed -- a real rolling patch-
        notes log, not a one-shot popup. Unseen entries (newer than the
        last version the player dismissed) get a "NEW" tag and the
        brighter title color so they're easy to spot at the top; older,
        already-seen ones are still right there below, just muted."""
        page = self._changelog_page
        page.begin(max(360, self._changelog_canvas.winfo_height() or 360))
        page.title("What's New")

        unseen_versions = {e["version"] for e in changelog.unseen_entries()}
        for entry in changelog.CHANGELOG_ENTRIES:
            is_new = entry["version"] in unseen_versions
            page.gap(4)
            page.text(entry["title"] + ("   NEW" if is_new else ""),
                      fill=theme.ACCENT if is_new else theme.MUTED,
                      font=theme.FONT_BOLD)
            for item in entry["items"]:
                page.text(f"— {item}",
                          fill=theme.INK if is_new else theme.MUTED,
                          indent=6)
        if unseen_versions:
            page.gap(6)
            page.button("Got it", self._dismiss_changelog, kind="accent")
        page.finish()

    def _dismiss_changelog(self):
        changelog.mark_seen(changelog.CHANGELOG_VERSION)
        self._refresh_changelog_panel()

    # --- ------------------------------------------------------------------
    def refresh(self):
        """Re-check save-file presence — call whenever the menu is shown, in
        case a save was created since this widget was built. Also re-checks
        the changelog panel, in case a version was dismissed elsewhere."""
        self._render_menu()
        self._refresh_changelog_panel()
