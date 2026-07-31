"""Pause menu overlay, raised on top of the world map via Escape."""
import tkinter as tk

from app.ui import theme


class PauseMenuView(tk.Frame):
    def __init__(self, master, on_resume, on_save, on_return_to_menu, on_exit,
                 on_settings=None):
        super().__init__(master, bg=theme.BG)
        self._msg_after_id = None

        center = tk.Frame(self, bg=theme.BG)
        center.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(center, text="Paused", bg=theme.BG, fg=theme.INK,
                 font=("Segoe UI", 24, "bold")).pack(pady=(0, 24))

        self.message = tk.Label(center, text="", bg=theme.BG, fg=theme.GOOD,
                                font=theme.FONT_BOLD)
        self.message.pack(pady=(0, 14))

        def btn(text, command):
            tk.Button(center, text=text, command=command, width=22,
                      bg="#232a36", fg=theme.INK, activebackground=theme.ACCENT,
                      relief="flat", font=theme.FONT_BOLD, pady=10).pack(pady=6)

        btn("Resume", on_resume)
        btn("Save Game", on_save)
        if on_settings is not None:
            btn("Settings", on_settings)
        btn("Return to Menu", on_return_to_menu)
        btn("Exit Game", on_exit)

    def show_message(self, text, fg=None, ms=2200):
        self.message.config(text=text, fg=fg or theme.GOOD)
        if self._msg_after_id is not None:
            self.after_cancel(self._msg_after_id)
        self._msg_after_id = self.after(ms, self._clear_message)

    def clear_message(self):
        if self._msg_after_id is not None:
            self.after_cancel(self._msg_after_id)
            self._msg_after_id = None
        self.message.config(text="")

    def _clear_message(self):
        self._msg_after_id = None
        self.message.config(text="")
