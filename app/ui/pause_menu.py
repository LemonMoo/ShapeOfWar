"""Pause menu overlay, raised on top of the world map via Escape.

Drawn on app/ui/parchment.py's Page, like the title screen and the map HUD.
"""
import tkinter as tk

from app.ui import parchment
from app.ui import theme

_WIDTH = 320


class PauseMenuView(tk.Frame):
    def __init__(self, master, on_resume, on_save, on_return_to_menu, on_exit,
                 on_settings=None):
        super().__init__(master, bg=theme.BG)
        self._msg_after_id = None
        self._message = ""
        self._message_fg = theme.GOOD
        self._actions = [("Resume", on_resume, "accent"),
                         ("Save Game", on_save, "default")]
        if on_settings is not None:
            self._actions.append(("Settings", on_settings, "default"))
        self._actions += [("Return to Menu", on_return_to_menu, "default"),
                          ("Exit Game", on_exit, "danger")]

        holder = tk.Frame(self, bg=theme.BG)
        holder.place(relx=0.5, rely=0.5, anchor="center")
        self._page = parchment.Page(holder, _WIDTH, seed=31)
        self._page.canvas.pack()
        self._render()

    def _render(self):
        page = self._page
        page.begin(340)
        page.title("Paused", "the world is holding its breath")
        if self._message:
            page.text(self._message, fill=self._message_fg,
                      font=theme.FONT_SMALL_BOLD)
            page.gap(2)
        for text, command, kind in self._actions:
            page.button(text, command, kind=kind)
        page.finish()

    def show_message(self, text, fg=None, ms=2200):
        self._message, self._message_fg = text, fg or theme.GOOD
        self._render()
        if self._msg_after_id is not None:
            self.after_cancel(self._msg_after_id)
        self._msg_after_id = self.after(ms, self._clear_message)

    def clear_message(self):
        if self._msg_after_id is not None:
            self.after_cancel(self._msg_after_id)
            self._msg_after_id = None
        self._message = ""
        self._render()

    def _clear_message(self):
        self._msg_after_id = None
        self._message = ""
        self._render()
