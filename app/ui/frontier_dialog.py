"""Frontier event dialog: a modal in-game overlay for the one-time decisions
a freshly-claimed region throws at you (see app/world/frontier.py). The
world pauses while it is up; choosing applies the consequence immediately
via frontier.resolve_event and calls on_done so the app can surface the
next staged event or hand the clock back to the player.

This used to be a tk.Toplevel -- an OS window of its own, which Windows
opened UNFOCUSED beside the game: the decision sat in a separate box you
could miss while the map underneath kept living. It is now an in-game
overlay in the same idiom as the Treasury and the Ledger (see
app/ui/map_view.py): a page drawn on the game's own window, over a
full-window blocker that absorbs every click aimed at the map or the top
bar, with the app's global shortcuts suspended until a choice is made
(see App._modal_open).

Drawn on the parchment kit (app/ui/parchment.py) like every other page --
a vellum sheet, an illuminated title, and the choices as carved plaques --
so the one modal the map can throw at you does not read as a flat widget
box from a different program (kit-coverage pass, v0.18.27).
"""
import tkinter as tk

from app.ui import theme
from app.ui import parchment

_BLOCKER = "#0c0906"   # dim behind the sheet; stippled so the map still reads


class FrontierDialog(tk.Frame):
    def __init__(self, master, world, event, on_done):
        super().__init__(master, bg=theme.BG)
        self._on_done = on_done
        self._world = world
        self._event = event
        master._modal_open = True

        # Modal, in-game: the blocker sits over the whole game window and
        # eats every click meant for the map or the top bar, the way the old
        # Toplevel's grab did -- without being a window of its own that can
        # lose focus or fall behind the game.
        self._blocker = tk.Canvas(master, highlightthickness=0, bd=0,
                                  bg=_BLOCKER)
        self._blocker.place(x=0, y=0, relwidth=1, relheight=1)
        self._blocker.bind("<Configure>", self._redraw_blocker)
        self._redraw_blocker()

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
        for choice in event["choices"]:
            page.button(choice["label"],
                        lambda c=choice["id"]: self._choose(world, event, c))
        used = page.finish()

        # Size the sheet to its content, exactly as the Toplevel's geometry
        # call did, and centre it in the game window -- it can never be
        # dragged off the edge or dropped behind the map, because it is not
        # a window the OS can move.
        w, h = width + 20, used + 30
        self.configure(width=w, height=h)
        mw, mh = master.winfo_width(), master.winfo_height()
        self.place(x=max(0, (mw - w) // 2), y=max(0, (mh - h) // 2))
        self.lift()

        # Escape resolves to the first choice, the same default the old
        # dialog offered. Bound app-wide so it works whichever widget under
        # the blocker happens to hold focus; the app's own Escape handler is
        # gated on _modal_open, so this cannot open the pause menu instead.
        master.bind_all("<Escape>", self._first_choice)
        self.focus_set()

    def _redraw_blocker(self, _event=None):
        w, h = self._blocker.winfo_width(), self._blocker.winfo_height()
        if w < 2 or h < 2:
            return
        self._blocker.delete("all")
        self._blocker.create_rectangle(0, 0, w, h, fill=_BLOCKER, outline="",
                                       stipple="gray50")

    def _first_choice(self, _event=None):
        self._choose(self._world, self._event,
                     self._event["choices"][0]["id"])

    def _choose(self, world, event, choice_id):
        from app.world import frontier
        message = frontier.resolve_event(world, event, choice_id)
        master = self.master
        master.unbind_all("<Escape>")
        self._blocker.destroy()
        self.destroy()
        master._modal_open = False
        self._on_done(message)
