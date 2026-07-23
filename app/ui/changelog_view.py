"""What's-new popup shown once per update on game start (see
app/core/changelog.py for the data/persistence side) — a small Toplevel,
same styling conventions as the Compendium window, dismissed with a single
button that marks the shown version seen so it doesn't reappear until the
next update ships.
"""
import tkinter as tk

from app.ui import theme
from app.core import changelog


class ChangelogWindow(tk.Toplevel):
    def __init__(self, master, entries):
        super().__init__(master)
        self.title("What's New")
        self.geometry("560x480")
        self.minsize(420, 320)
        self.configure(bg=theme.BG)
        self.transient(master)
        self.resizable(True, True)

        top = tk.Frame(self, bg=theme.PANEL)
        top.pack(fill="x")
        tk.Label(top, text="What's New", bg=theme.PANEL, fg=theme.INK,
                 font=theme.FONT_TITLE).pack(side="left", padx=14, pady=8)

        body = tk.Frame(self, bg=theme.BG)
        body.pack(fill="both", expand=True, padx=14, pady=(10, 6))

        canvas = tk.Canvas(body, bg=theme.BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(body, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=theme.BG)
        inner.bind("<Configure>",
                  lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for entry in entries:
            tk.Label(inner, text=entry["title"], bg=theme.BG, fg=theme.ACCENT,
                     font=theme.FONT_BOLD, anchor="w", justify="left",
                     wraplength=500).pack(fill="x", pady=(10, 4))
            for item in entry["items"]:
                tk.Label(inner, text=f"• {item}", bg=theme.BG, fg=theme.INK,
                         font=theme.FONT, anchor="w", justify="left",
                         wraplength=500).pack(fill="x", pady=2, padx=(8, 0))

        newest_version = entries[0]["version"]
        tk.Button(self, text="Got it", command=lambda: self._dismiss(newest_version),
                  bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                  relief="flat", font=theme.FONT).pack(side="bottom", fill="x",
                                                       padx=14, pady=(0, 14))
        self.bind("<Escape>", lambda e: self._dismiss(newest_version))
        self.protocol("WM_DELETE_WINDOW", lambda: self._dismiss(newest_version))

    def _dismiss(self, version):
        changelog.mark_seen(version)
        self.destroy()
