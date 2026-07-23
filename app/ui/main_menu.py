"""Title screen: New Game / Load Game / Quit, with a "What's New" panel
docked to the right (see app/core/changelog.py for the data/persistence
side) — an always-visible part of the menu now rather than a popup, so it
reads like a patch-notes sidebar instead of an interruption.
"""
import tkinter as tk

from app.ui import theme
from app.core import changelog

_CHANGELOG_PANEL_WIDTH = 320
_RECENT_ENTRY_COUNT = 2   # how many past entries to keep showing once caught up


class MainMenuView(tk.Frame):
    def __init__(self, master, on_new_game, on_load_game, on_quit, has_save):
        super().__init__(master, bg=theme.BG)
        self._has_save = has_save

        menu_col = tk.Frame(self, bg=theme.BG)
        menu_col.pack(side="left", fill="both", expand=True)
        center = tk.Frame(menu_col, bg=theme.BG)
        center.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(center, text="Shapes of War", bg=theme.BG, fg=theme.INK,
                 font=("Segoe UI", 28, "bold")).pack(pady=(0, 40))

        tk.Button(center, text="New Game", command=on_new_game, width=22,
                  bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                  relief="flat", font=theme.FONT_BOLD, pady=10).pack(pady=6)

        self.load_btn = tk.Button(
            center, text="Load Game", command=on_load_game, width=22,
            bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
            relief="flat", font=theme.FONT_BOLD, pady=10)
        self.load_btn.pack(pady=6)

        tk.Button(center, text="Quit", command=on_quit, width=22,
                  bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                  relief="flat", font=theme.FONT_BOLD, pady=10).pack(pady=6)

        self._build_changelog_panel()
        self.refresh()

    # --- "What's New" panel -------------------------------------------------
    def _build_changelog_panel(self):
        panel = tk.Frame(self, bg=theme.PANEL, width=_CHANGELOG_PANEL_WIDTH)
        panel.pack(side="right", fill="y")
        panel.pack_propagate(False)

        tk.Label(panel, text="What's New", bg=theme.PANEL, fg=theme.INK,
                 font=theme.FONT_TITLE).pack(anchor="w", padx=16, pady=(18, 10))

        body = tk.Frame(panel, bg=theme.PANEL)
        body.pack(fill="both", expand=True, padx=(2, 0))
        canvas = tk.Canvas(body, bg=theme.PANEL, highlightthickness=0)
        scrollbar = tk.Scrollbar(body, orient="vertical", command=canvas.yview)
        self._changelog_inner = tk.Frame(canvas, bg=theme.PANEL)
        self._changelog_inner.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self._changelog_inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(14, 0))
        scrollbar.pack(side="right", fill="y")

        self._changelog_dismiss_btn = tk.Button(
            panel, text="Got it", command=self._dismiss_changelog,
            bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
            relief="flat", font=theme.FONT)
        # packed on demand in _refresh_changelog_panel, only while there's
        # something unseen to dismiss

    def _refresh_changelog_panel(self):
        for w in self._changelog_inner.winfo_children():
            w.destroy()

        unseen = changelog.unseen_entries()
        entries = unseen or changelog.CHANGELOG_ENTRIES[:_RECENT_ENTRY_COUNT]

        for entry in entries:
            tk.Label(self._changelog_inner, text=entry["title"], bg=theme.PANEL,
                     fg=theme.ACCENT, font=theme.FONT_BOLD, anchor="w",
                     justify="left", wraplength=_CHANGELOG_PANEL_WIDTH - 34
                     ).pack(fill="x", pady=(8, 4))
            for item in entry["items"]:
                tk.Label(self._changelog_inner, text=f"• {item}", bg=theme.PANEL,
                         fg=theme.INK, font=theme.FONT, anchor="w", justify="left",
                         wraplength=_CHANGELOG_PANEL_WIDTH - 42
                         ).pack(fill="x", pady=2, padx=(8, 8))

        if unseen:
            self._changelog_dismiss_btn.pack(side="bottom", fill="x", padx=14, pady=14)
        else:
            self._changelog_dismiss_btn.pack_forget()

    def _dismiss_changelog(self):
        changelog.mark_seen(changelog.CHANGELOG_VERSION)
        self._refresh_changelog_panel()

    # --- ------------------------------------------------------------------
    def refresh(self):
        """Re-check save-file presence — call whenever the menu is shown, in
        case a save was created since this widget was built. Also re-checks
        the changelog panel, in case a version was dismissed elsewhere."""
        if self._has_save():
            self.load_btn.config(state="normal", fg=theme.INK,
                                 disabledforeground=theme.MUTED)
        else:
            self.load_btn.config(state="disabled", fg=theme.MUTED,
                                 disabledforeground=theme.MUTED)
        self._refresh_changelog_panel()
