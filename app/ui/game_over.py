"""Defeat screen, shown when the player's realm loses its last region.

Deliberately a full screen rather than a bottom_message banner: unlike every
other event the map reports, this one ends the run, and the map behind it no
longer has anything of the player's left to look at.

Drawn on app/ui/parchment.py's Page -- and this is the one screen where the
page reads as what it is: an entry closing a chronicle.
"""
import tkinter as tk

from app.ui import parchment
from app.ui import theme

_WIDTH = 460


class GameOverView(tk.Frame):
    def __init__(self, master, on_return_to_menu, on_exit):
        super().__init__(master, bg=theme.BG)
        self._detail = ""
        self._on_return = on_return_to_menu
        self._on_exit = on_exit

        holder = tk.Frame(self, bg=theme.BG)
        holder.place(relx=0.5, rely=0.5, anchor="center")
        self._page = parchment.Page(holder, _WIDTH, seed=41)
        self._page.canvas.pack()
        self._render()

    def _render(self):
        page = self._page
        page.begin(300)
        page.title("Your realm has fallen")
        if self._detail:
            page.text(self._detail, fill=theme.MUTED)
        page.gap(6)
        page.button("Return to Menu", self._on_return, kind="accent")
        page.button("Exit Game", self._on_exit, kind="danger")
        page.finish()

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
        self._detail = f"{lead}\n{when}"
        self._render()
