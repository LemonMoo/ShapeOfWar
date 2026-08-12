"""Frontier event dialog: a small modal Toplevel for the one-time decisions
a freshly-claimed region throws at you (see app/world/frontier.py). The
world pauses while it is up; choosing applies the consequence immediately
via frontier.resolve_event and calls on_done so the app can surface the
next staged event or hand the clock back to the player.

Drawn on the parchment kit (app/ui/parchment.py) like every other page --
a vellum sheet, an illuminated title, and the choices as carved plaques --
so the one modal the map can throw at you does not read as a flat widget
box from a different program (kit-coverage pass, v0.18.27).
"""
import tkinter as tk

from app.ui import theme
from app.ui import parchment


class FrontierDialog(tk.Toplevel):
    def __init__(self, master, world, event, on_done):
        super().__init__(master)
        self.title("A Frontier Event")
        self.transient(master)
        self.configure(bg=theme.BG)
        self._on_done = on_done

        width = 460
        canvas = tk.Canvas(self, width=width, highlightthickness=0, bd=0,
                           bg=theme.BG)
        canvas.pack(fill="both", expand=True, padx=10, pady=10)

        page = parchment.Page(self, width, canvas=canvas)
        page.begin()
        page.title(event["title"])
        page.gap(6)
        page.text(event["text"])
        page.gap(10)
        from app.world import frontier
        for choice in event["choices"]:
            page.button(choice["label"],
                        lambda c=choice["id"]: self._choose(world, event, c))
        used = page.finish()
        # Size the window to the page it drew -- a sheet is as tall as its
        # content, and a fixed 460x300 box would leave dead vellum or clip.
        self.geometry(f"{width + 20}x{used + 30}")

        # Escape and the window's close button resolve to the first choice,
        # the same default the old widget dialog offered.
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
