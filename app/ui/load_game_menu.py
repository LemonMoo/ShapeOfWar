"""Load Game popup: lists saves on disk, pick one, then Load, Delete or
Cancel."""
import tkinter as tk
from tkinter import messagebox

from app.ui import theme

_ROW_BG = "#232a36"


class LoadGameMenuView(tk.Frame):
    def __init__(self, master, on_load, on_delete, on_cancel):
        super().__init__(master, bg=theme.BG)
        self.on_load = on_load
        self.on_delete = on_delete
        self.on_cancel = on_cancel
        self._selected_id = None
        self._selected_name = None
        self._rows = {}

        panel = tk.Frame(self, bg=theme.PANEL)
        panel.place(relx=0.5, rely=0.5, anchor="center", width=420, height=420)

        tk.Label(panel, text="Load Game", bg=theme.PANEL, fg=theme.INK,
                 font=("Segoe UI", 18, "bold")).pack(padx=24, pady=(20, 12))

        self.list_frame = tk.Frame(panel, bg=theme.PANEL)
        self.list_frame.pack(padx=24, fill="both", expand=True)

        actions = tk.Frame(panel, bg=theme.PANEL)
        actions.pack(padx=24, pady=(12, 20), fill="x")
        tk.Button(actions, text="Cancel", command=self._cancel, width=10,
                  bg=_ROW_BG, fg=theme.INK, relief="flat", font=theme.FONT,
                  activebackground=theme.ACCENT).pack(side="left")
        self.delete_btn = tk.Button(actions, text="Delete Save", command=self._delete,
                                    width=12, bg=_ROW_BG, fg=theme.BAD,
                                    relief="flat", font=theme.FONT,
                                    activebackground=theme.ACCENT, state="disabled")
        self.delete_btn.pack(side="left", padx=(8, 0))
        self.load_btn = tk.Button(actions, text="Load", command=self._load,
                                  width=12, bg=theme.ACCENT, fg="#06121f",
                                  relief="flat", font=theme.FONT_BOLD,
                                  activebackground=theme.ACCENT, state="disabled")
        self.load_btn.pack(side="right")

    def refresh(self, saves):
        for w in self.list_frame.winfo_children():
            w.destroy()
        self._rows = {}
        self._selected_id = None
        self._selected_name = None
        self.load_btn.config(state="disabled")
        self.delete_btn.config(state="disabled")

        if not saves:
            tk.Label(self.list_frame, text="No saves found.", bg=theme.PANEL,
                     fg=theme.MUTED, font=theme.FONT).pack(pady=30)
            return

        for meta in saves:
            row = tk.Frame(self.list_frame, bg=_ROW_BG)
            row.pack(fill="x", pady=3)
            text = (f"{meta.get('name', 'Unnamed World')}  "
                    f"({meta.get('species', '?')})\n"
                    f"Created {meta.get('created_at', 'unknown date')}")
            lbl = tk.Label(row, text=text, bg=_ROW_BG, fg=theme.INK,
                          font=theme.FONT, justify="left", anchor="w",
                          padx=10, pady=6)
            lbl.pack(fill="x")
            save_id = meta["id"]
            name = meta.get("name", "Unnamed World")
            for widget in (row, lbl):
                widget.bind("<Button-1>", lambda e, sid=save_id, n=name: self._select(sid, n))
            self._rows[save_id] = (row, lbl)

    def _select(self, save_id, name):
        self._selected_id = save_id
        self._selected_name = name
        for sid, (row, lbl) in self._rows.items():
            active = sid == save_id
            bg = theme.ACCENT if active else _ROW_BG
            fg = "#06121f" if active else theme.INK
            row.config(bg=bg)
            lbl.config(bg=bg, fg=fg)
        self.load_btn.config(state="normal")
        self.delete_btn.config(state="normal")

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
