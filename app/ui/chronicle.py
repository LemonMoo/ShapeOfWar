"""The Realm Chronicle window: a Toplevel overlay listing the player realm's
dated milestones (see app/world/chronicle.py for the world-side log and
its recording points). Opens and closes without disturbing the map, in the
same create-or-raise idiom as the Compendium -- it reads like turning to
the front page of your realm's history rather than leaving the game.
"""
import tkinter as tk

from app.ui import theme
from app.world.chronicle import entries


class ChronicleWindow(tk.Toplevel):
    def __init__(self, master, world, faction):
        super().__init__(master)
        self.title("Realm Chronicle")
        self.geometry("520x460")
        self.minsize(360, 260)
        self.configure(bg=theme.BG)
        self.transient(master)

        top = tk.Frame(self, bg=theme.PANEL)
        top.pack(fill="x")
        tk.Label(top, text=f"Realm Chronicle — {faction.name}",
                 bg=theme.PANEL, fg=theme.INK, font=theme.FONT_TITLE
                 ).pack(side="left", padx=14, pady=10)
        tk.Button(top, text="Close (Esc)", command=self.destroy,
                  bg=theme.PANEL_ALT, fg=theme.INK, activebackground=theme.ACCENT,
                  relief="flat", font=theme.FONT).pack(side="right", padx=10, pady=8)

        self._text = tk.Text(self, bg=theme.BG, fg=theme.INK,
                             font=theme.FONT, wrap="word", relief="flat",
                             padx=14, pady=10, highlightthickness=0,
                             state="disabled")
        self._text.pack(fill="both", expand=True)

        for entry in reversed(entries(faction)):
            self._append(entry["date"], entry["text"])
        if not entries(faction):
            self._append("", "(Nothing yet — your realm's history begins "
                             "with its first milestone.)")

        self.bind("<Escape>", lambda e: self.destroy())
        self._text.yview_moveto(0.0)   # newest first, so the latest milestone is on screen

    def _append(self, date, text):
        self._text.configure(state="normal")
        if date:
            self._text.insert("end", f"{date}  ", ("date",))
        self._text.insert("end", f"{text}\n", ("body",))
        self._text.configure(state="disabled")
        self._text.tag_configure("date", foreground=theme.MUTED)
        self._text.tag_configure("body", foreground=theme.INK,
                                 spacing3=6)
