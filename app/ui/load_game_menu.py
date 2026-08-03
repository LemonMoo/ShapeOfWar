"""Load Game popup: lists saves on disk, pick one, then Load, Delete or
Cancel.

Drawn on app/ui/parchment.py's Page -- a shelf of saved chronicles, which is
what a load screen is.
"""
import tkinter as tk
from tkinter import messagebox

from app.ui import parchment
from app.ui import theme

_WIDTH = 460


class LoadGameMenuView(tk.Frame):
    def __init__(self, master, on_load, on_delete, on_cancel):
        super().__init__(master, bg=theme.BG)
        self.on_load = on_load
        self.on_delete = on_delete
        self.on_cancel = on_cancel
        self._selected_id = None
        self._selected_name = None
        self._saves = []

        holder = tk.Frame(self, bg=theme.BG)
        holder.place(relx=0.5, rely=0.5, anchor="center", width=_WIDTH, height=460)

        # The list scrolls internally: with enough saves an unscrolled list's
        # natural height used to exceed the fixed panel and push the action
        # row off-screen entirely. The page borrows this canvas, so it scrolls
        # for free -- the pinned action row stays a separate strip below it.
        list_container = tk.Frame(holder, bg=theme.PANEL)
        list_container.pack(fill="both", expand=True)
        canvas = tk.Canvas(list_container, bg=theme.PANEL, highlightthickness=0)
        scrollbar = tk.Scrollbar(list_container, orient="vertical",
                                 command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self._list_canvas = canvas
        self._page = parchment.Page(None, _WIDTH - 20, seed=51, canvas=canvas)
        canvas.bind("<Enter>", lambda e: canvas.bind_all(
            "<MouseWheel>", lambda ev: canvas.yview_scroll(int(-ev.delta / 120), "units")))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        # The action row stays widgets: three fixed buttons whose enabled state
        # tracks the selection, which is exactly what a drawn plaque handles
        # worst (it has no disabled look). A page for the list, buttons for the
        # verbs -- each where it is strongest.
        self._actions = tk.Frame(holder, bg=theme.PANEL)
        self._actions.pack(fill="x", pady=(1, 0))
        tk.Button(self._actions, text="Cancel", command=self._cancel, width=10,
                  bg=theme.PANEL_ALT, fg=theme.INK, relief="flat", font=theme.FONT,
                  activebackground=theme.ACCENT).pack(side="left", padx=8, pady=8)
        self.delete_btn = tk.Button(self._actions, text="Delete Save",
                                    command=self._delete, width=12,
                                    bg=theme.PANEL_ALT, fg=theme.BAD, relief="flat",
                                    font=theme.FONT, activebackground=theme.ACCENT,
                                    state="disabled")
        self.delete_btn.pack(side="left")
        self.load_btn = tk.Button(self._actions, text="Load", command=self._load,
                                  width=12, bg=theme.ACCENT, fg="#241a0a",
                                  relief="flat", font=theme.FONT_BOLD,
                                  activebackground=theme.ACCENT, state="disabled")
        self.load_btn.pack(side="right", padx=8, pady=8)

    def refresh(self, saves):
        self._saves = list(saves)
        self._selected_id = None
        self._selected_name = None
        self.load_btn.config(state="disabled")
        self.delete_btn.config(state="disabled")
        self._render()

    def _render(self):
        page = self._page
        page.begin(max(320, self._list_canvas.winfo_height() or 320))
        page.title("Load Game", "choose a chronicle to return to")
        if not self._saves:
            page.text("No saved realms found.", fill=theme.MUTED)
            page.finish()
            return
        for meta in self._saves:
            save_id = meta["id"]
            name = meta.get("name", "Unnamed World")
            selected = save_id == self._selected_id
            top = page.mark()
            page.kv(f"{name}  ({meta.get('species', '?')})",
                    "‹ selected" if selected else "",
                    fg=theme.ACCENT if selected else theme.INK)
            page.text(f"Created {meta.get('created_at', 'unknown date')}",
                      fill=theme.MUTED, indent=6)
            page.hit_region(top, lambda sid=save_id, n=name: self._select(sid, n))
            page.gap(4)
        page.finish()

    def _select(self, save_id, name):
        self._selected_id = save_id
        self._selected_name = name
        self.load_btn.config(state="normal")
        self.delete_btn.config(state="normal")
        self._render()

    def _load(self):
        if self._selected_id is not None:
            self.on_load(self._selected_id)

    def _delete(self):
        if self._selected_id is None:
            return
        if messagebox.askyesno(
                "Delete Save",
                f'Permanently delete "{self._selected_name}"? '
                "This cannot be undone.", parent=self):
            self.on_delete(self._selected_id)

    def _cancel(self):
        self._selected_id = None
        self._selected_name = None
        self.on_cancel()
