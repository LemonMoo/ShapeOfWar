"""Frontier event dialog: a small modal Toplevel for the one-time decisions
a freshly-claimed region throws at you (see app/world/frontier.py). The
world pauses while it is up; choosing applies the consequence immediately
via frontier.resolve_event and calls on_done so the app can surface the
next staged event or hand the clock back to the player.
"""
import tkinter as tk

from app.ui import theme


class FrontierDialog(tk.Toplevel):
    def __init__(self, master, world, event, on_done):
        super().__init__(master)
        self.title("A Frontier Event")
        self.geometry("460x300")
        self.minsize(380, 220)
        self.configure(bg=theme.BG)
        self.transient(master)
        self._on_done = on_done

        tk.Label(self, text=event["title"], bg=theme.BG, fg=theme.ACCENT,
                 font=theme.FONT_TITLE).pack(anchor="w", padx=18, pady=(16, 4))
        tk.Label(self, text=event["text"], bg=theme.BG, fg=theme.INK,
                 font=theme.FONT, wraplength=420, justify="left"
                 ).pack(anchor="w", padx=18, pady=(0, 14))

        from app.world import frontier
        for choice in event["choices"]:
            tk.Button(self, text=choice["label"], command=lambda c=choice["id"]:
                      self._choose(world, event, c),
                      bg=theme.PANEL, fg=theme.INK,
                      activebackground=theme.ACCENT, activeforeground=theme.INK,
                      relief="flat", font=theme.FONT, anchor="w", padx=12,
                      pady=8).pack(fill="x", padx=18, pady=3)

        self.bind("<Escape>", lambda e: self._choose(world, event,
                                                     event["choices"][0]["id"]))
        self.protocol("WM_DELETE_WINDOW", lambda: self._choose(
            world, event, event["choices"][0]["id"]))
        self.grab_set()
        self.lift()
        self.focus_set()

    def _choose(self, world, event, choice_id):
        from app.world import frontier
        message = frontier.resolve_event(world, event, choice_id)
        self.destroy()
        self._on_done(message)
