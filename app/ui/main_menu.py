"""Title screen: New Game / Load Game / Quit."""
import tkinter as tk

from app.ui import theme


class MainMenuView(tk.Frame):
    def __init__(self, master, on_new_game, on_load_game, on_quit, has_save):
        super().__init__(master, bg=theme.BG)
        self._has_save = has_save

        center = tk.Frame(self, bg=theme.BG)
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

        self.refresh()

    def refresh(self):
        """Re-check save-file presence — call whenever the menu is shown, in
        case a save was created since this widget was built."""
        if self._has_save():
            self.load_btn.config(state="normal", fg=theme.INK,
                                 disabledforeground=theme.MUTED)
        else:
            self.load_btn.config(state="disabled", fg=theme.MUTED,
                                 disabledforeground=theme.MUTED)
