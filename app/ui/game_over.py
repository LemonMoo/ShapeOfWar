"""Defeat screen, shown when the player's realm loses its last region.

Deliberately a full screen rather than a bottom_message banner: unlike every
other event the map reports, this one ends the run, and the map behind it no
longer has anything of the player's left to look at.
"""
import tkinter as tk

from app.ui import theme


class GameOverView(tk.Frame):
    def __init__(self, master, on_return_to_menu, on_exit):
        super().__init__(master, bg=theme.BG)

        center = tk.Frame(self, bg=theme.BG)
        center.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(center, text="Your realm has fallen", bg=theme.BG, fg=theme.BAD,
                 font=("Segoe UI", 28, "bold")).pack(pady=(0, 10))

        self.detail = tk.Label(center, text="", bg=theme.BG, fg=theme.MUTED,
                               font=("Segoe UI", 11), justify="center",
                               wraplength=520)
        self.detail.pack(pady=(0, 26))

        def btn(text, command):
            tk.Button(center, text=text, command=command, width=22,
                      bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                      relief="flat", font=theme.FONT_BOLD, pady=10).pack(pady=6)

        btn("Return to Menu", on_return_to_menu)
        btn("Exit Game", on_exit)

    def set_result(self, player_name, conqueror_name, turn, year=None):
        """Fill in who fell, to whom, and when. `conqueror_name` may be None
        for the (currently unreachable, but cheap to allow) case of a realm
        ending without a single identifiable conqueror."""
        when = f"Turn {turn}" if year is None else f"Year {year} · Turn {turn}"
        if conqueror_name:
            lead = (f"{player_name} has lost its last region to "
                    f"{conqueror_name}.")
        else:
            lead = f"{player_name} has lost its last region."
        self.detail.config(text=f"{lead}\n{when}")
