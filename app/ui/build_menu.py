"""The buildable menu: a Toplevel card window for one settlement or village.

Shows what the place actually produces, then every building it could put up as
a clickable card, most-worth-building first. The layout is deliberately a card
grid rather than the right-hand panel's vertical stack of labels -- a build
menu is a thing you scan and compare across, which a 360px column cannot do.

All the judgement lives in app/world/buildings.py, which is game logic and has
its own harness (dev/test_buildings.py). This module only draws it: it decides
nothing about what is worth building, and it spends nothing -- the Build button
calls the same construction.start_* entry points the side panel already used.

Tk notes worth keeping, both hit while building this:
  * A Canvas-based scroll region does not follow its inner frame on its own.
    The inner frame needs a <Configure> binding to push the new bounding box
    back onto the canvas, and the canvas needs one of its own to keep the
    window item at full width -- without the second, cards stay stuck at their
    requested width and the grid never fills the window.
  * Mouse-wheel scrolling is bound on the TOPLEVEL, not the canvas. Bound to
    the canvas it only fires while the pointer is over background, so the
    wheel dies the moment it is over a card -- which is most of the window.
"""
import tkinter as tk

from app.ui import theme
from app.ui import widgets
from app.world import buildings as B
from app.world import construction


_CARD_W = 300
_CARD_MIN_COLS = 2

# Priority colour and label. "urgent" is the one that carries information the
# player did not already have -- something at this node is being destroyed
# right now and this building is the answer.
_PRIORITY = {
    "urgent": (theme.BAD, "NEEDED NOW"),
    "useful": (theme.WARN, "WORTH BUILDING"),
    "idle": (theme.MUTED, "NO PRESSURE"),
    "blocked": (theme.LINE, "UNAVAILABLE"),
}

_SECTOR_LABEL = {"farming": "Fields", "forestry": "Woods",
                 "mining": "Mines", "fishing": "Water"}

# Which of the three ceilings is holding a sector back, in plain words. This
# is the single most useful line in the window: it is the answer to "why does
# this rich-looking village produce so little?"
_LIMIT_TEXT = {
    "hands": "short of hands",
    "land": "working all the land there is",
    "season": "nothing to harvest this season",
}


def _format_cost(cost):
    return "   ".join(f"{r} {a:,}" for r, a in sorted(cost.items()))


class BuildMenuWindow(tk.Toplevel):
    """One window per open node. `on_change` is called after anything is
    actually started, so the map's own panels and resource bar refresh
    alongside this one instead of drifting out of date behind it."""

    def __init__(self, master, world, node, nation, on_change=None):
        super().__init__(master)
        self.world = world
        self.node = node
        self.nation = nation
        self.on_change = on_change

        kind = (node.kind.capitalize() if hasattr(node, "kind") else "Village")
        self.title(f"{node.name} — {kind}")
        self.geometry("1000x700")
        self.minsize(700, 480)
        self.configure(bg=theme.BG)
        self.transient(master)

        self._build_chrome()
        self._render()
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind_all("<MouseWheel>", self._on_wheel)
        self.bind("<Destroy>", self._on_destroy)

    # --- chrome ----------------------------------------------------------
    def _build_chrome(self):
        top = tk.Frame(self, bg=theme.PANEL)
        top.pack(fill="x")
        kind = (self.node.kind.capitalize() if hasattr(self.node, "kind") else "Village")
        tk.Label(top, text=self.node.name, bg=theme.PANEL, fg=theme.ACCENT,
                 font=theme.FONT_TITLE).pack(side="left", padx=14, pady=8)
        tk.Label(top, text=kind, bg=theme.PANEL, fg=theme.MUTED,
                 font=theme.FONT).pack(side="left", pady=8)
        widgets.button(top, "Close (Esc)", self.destroy).pack(side="right", padx=10, pady=8)

        self._msg = tk.Label(self, text="", bg=theme.BG, fg=theme.ACCENT,
                             font=theme.FONT_BOLD, anchor="w", padx=16)

        outer = tk.Frame(self, bg=theme.BG)
        outer.pack(fill="both", expand=True)
        self._canvas = tk.Canvas(outer, bg=theme.BG, highlightthickness=0)
        self._canvas.pack(side="left", fill="both", expand=True)
        bar = tk.Scrollbar(outer, orient="vertical", command=self._canvas.yview)
        bar.pack(side="right", fill="y")
        self._canvas.configure(yscrollcommand=bar.set)

        self._body = tk.Frame(self._canvas, bg=theme.BG)
        self._window = self._canvas.create_window((0, 0), window=self._body, anchor="nw")
        # Both bindings are needed -- see the module docstring.
        self._body.bind("<Configure>", lambda e: self._canvas.configure(
            scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", self._on_canvas_resize)

    def _on_canvas_resize(self, event):
        self._canvas.itemconfigure(self._window, width=event.width)
        cols = max(1, min(4, event.width // (_CARD_W + 16)))
        if cols != getattr(self, "_cols", None):
            self._cols = cols
            self._render()

    def _on_wheel(self, event):
        self._canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def _on_destroy(self, event):
        if event.widget is self:
            self.unbind_all("<MouseWheel>")

    # --- content ---------------------------------------------------------
    def _render(self):
        for child in self._body.winfo_children():
            child.destroy()
        cols = max(_CARD_MIN_COLS, getattr(self, "_cols", _CARD_MIN_COLS))

        self._render_production(self._body)

        options = B.build_options(self.world, self.node, self.nation)
        tk.Label(self._body, text="BUILDINGS", bg=theme.BG, fg=theme.ACCENT,
                 font=theme.FONT_HEADER, anchor="w").pack(fill="x", padx=16, pady=(16, 2))
        urgent = [o for o in options if o.priority == "urgent"]
        if urgent:
            tk.Label(self._body,
                     text="Sorted by what this place actually needs. "
                          f"{len(urgent)} building"
                          f"{'s are' if len(urgent) != 1 else ' is'} needed now.",
                     bg=theme.BG, fg=theme.MUTED, font=theme.FONT_SMALL,
                     anchor="w").pack(fill="x", padx=16, pady=(0, 6))
        else:
            tk.Label(self._body,
                     text="Sorted by what this place actually needs. "
                          "Nothing here is under pressure right now.",
                     bg=theme.BG, fg=theme.MUTED, font=theme.FONT_SMALL,
                     anchor="w").pack(fill="x", padx=16, pady=(0, 6))

        grid = tk.Frame(self._body, bg=theme.BG)
        grid.pack(fill="both", expand=True, padx=10, pady=(0, 16))
        for col in range(cols):
            grid.grid_columnconfigure(col, weight=1, uniform="card")
        for i, option in enumerate(options):
            self._card(grid, option).grid(row=i // cols, column=i % cols,
                                          sticky="nsew", padx=6, pady=6)

    def _render_production(self, parent):
        report = B.production_report(self.world, self.node)
        tk.Label(parent, text="PRODUCTION", bg=theme.BG, fg=theme.ACCENT,
                 font=theme.FONT_HEADER, anchor="w").pack(fill="x", padx=16, pady=(14, 2))
        box = tk.Frame(parent, bg=theme.PANEL, relief=theme.BORDER_RELIEF,
                       borderwidth=theme.BORDER_WIDTH)
        box.pack(fill="x", padx=16, pady=(0, 4))

        if report["kind"] == "village":
            self._render_village_production(box, report)
        else:
            self._render_settlement_production(box, report)

    def _render_village_production(self, box, report):
        head = tk.Frame(box, bg=theme.PANEL)
        head.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(head, text=f"{report['workforce']:,} pairs of hands",
                 bg=theme.PANEL, fg=theme.INK, font=theme.FONT_BOLD,
                 anchor="w").pack(side="left")
        tk.Label(head, text=f"labour: {report['policy']}", bg=theme.PANEL,
                 fg=theme.MUTED, font=theme.FONT_SMALL, anchor="e").pack(side="right")

        if not report["sectors"]:
            tk.Label(box, text="This land offers nothing to work.", bg=theme.PANEL,
                     fg=theme.MUTED, font=theme.FONT_SMALL, anchor="w"
                     ).pack(fill="x", padx=12, pady=(0, 10))
            return

        for row in report["sectors"]:
            line = tk.Frame(box, bg=theme.PANEL)
            line.pack(fill="x", padx=12, pady=2)
            tk.Label(line, text=_SECTOR_LABEL.get(row["sector"], row["sector"].title()),
                     bg=theme.PANEL, fg=theme.INK, font=theme.FONT_SMALL,
                     width=8, anchor="w").pack(side="left")
            tk.Label(line, text=f"{row['workers']:,} hands", bg=theme.PANEL,
                     fg=theme.MUTED, font=theme.FONT_SMALL, width=11,
                     anchor="w").pack(side="left")
            # The two ceilings, side by side -- this is the whole labor model
            # in one line, and it is the number the player needs to see to
            # understand why a rich-looking village produces so little.
            colour = {"hands": theme.WARN, "season": theme.MUTED}.get(
                row["limited_by"], theme.GOOD)
            tk.Label(line, text=f"{row['output']:,} of {row['potential']:,}",
                     bg=theme.PANEL, fg=colour, font=theme.FONT_SMALL,
                     width=16, anchor="w").pack(side="left")
            tk.Label(line, text=_LIMIT_TEXT[row["limited_by"]], bg=theme.PANEL,
                     fg=theme.MUTED, font=theme.FONT_SMALL,
                     anchor="w").pack(side="left")
        tk.Frame(box, bg=theme.PANEL, height=8).pack()

    def _render_settlement_production(self, box, report):
        running = [r for r in report["recipes"] if r["rate"] > 0]
        idle = [r for r in report["recipes"] if r["rate"] <= 0]
        tk.Label(box,
                 text=f"{len(running)} of {len(report['recipes'])} workshops running",
                 bg=theme.PANEL, fg=theme.INK, font=theme.FONT_BOLD, anchor="w"
                 ).pack(fill="x", padx=12, pady=(10, 4))
        for recipe in running[:10]:
            line = tk.Frame(box, bg=theme.PANEL)
            line.pack(fill="x", padx=12, pady=1)
            tk.Label(line, text=recipe["output"], bg=theme.PANEL, fg=theme.INK,
                     font=theme.FONT_SMALL, width=14, anchor="w").pack(side="left")
            tk.Label(line, text=f"{recipe['rate']:,}/turn", bg=theme.PANEL,
                     fg=theme.GOOD if recipe["note"] == "at capacity" else theme.WARN,
                     font=theme.FONT_SMALL, width=10, anchor="w").pack(side="left")
            tk.Label(line, text="from " + " + ".join(recipe["inputs"]),
                     bg=theme.PANEL, fg=theme.MUTED, font=theme.FONT_SMALL,
                     anchor="w").pack(side="left")
        if idle:
            tk.Label(box,
                     text="Idle for want of input: "
                          + ", ".join(r["output"] for r in idle[:8])
                          + ("…" if len(idle) > 8 else ""),
                     bg=theme.PANEL, fg=theme.MUTED, font=theme.FONT_SMALL,
                     anchor="w", justify="left",
                     wraplength=900).pack(fill="x", padx=12, pady=(6, 10))
        else:
            tk.Frame(box, bg=theme.PANEL, height=8).pack()

    # --- one card --------------------------------------------------------
    def _card(self, parent, option):
        colour, badge = _PRIORITY.get(option.priority, _PRIORITY["idle"])
        frame = tk.Frame(parent, bg=theme.PANEL, relief=theme.BORDER_RELIEF,
                         borderwidth=theme.BORDER_WIDTH,
                         highlightbackground=colour,
                         highlightthickness=2 if option.priority == "urgent" else 0)

        head = tk.Frame(frame, bg=theme.PANEL_ALT)
        head.pack(fill="x")
        tk.Label(head, text=option.label, bg=theme.PANEL_ALT, fg=theme.ACCENT,
                 font=theme.FONT_HEADER, anchor="w", padx=10,
                 pady=6).pack(side="left")
        tk.Label(head, text=self._tier_pips(option), bg=theme.PANEL_ALT,
                 fg=theme.INK, font=theme.FONT_SMALL, padx=10).pack(side="right")

        tk.Label(frame, text=badge, bg=theme.PANEL, fg=colour,
                 font=theme.FONT_SMALL_BOLD, anchor="w"
                 ).pack(fill="x", padx=10, pady=(6, 0))
        if option.reason:
            tk.Label(frame, text=option.reason, bg=theme.PANEL, fg=theme.INK,
                     font=theme.FONT_SMALL, anchor="w", justify="left",
                     wraplength=_CARD_W - 30
                     ).pack(fill="x", padx=10, pady=(2, 4))
        tk.Label(frame, text=B.BUILDING_BLURB.get(option.building, ""),
                 bg=theme.PANEL, fg=theme.MUTED, font=theme.FONT_SMALL,
                 anchor="w", justify="left", wraplength=_CARD_W - 30
                 ).pack(fill="x", padx=10, pady=(0, 6))

        for line in option.effects:
            tk.Label(frame, text="• " + line, bg=theme.PANEL, fg=theme.INK,
                     font=theme.FONT_SMALL, anchor="w", justify="left",
                     wraplength=_CARD_W - 34).pack(fill="x", padx=12)

        tk.Frame(frame, bg=theme.LINE, height=1).pack(fill="x", padx=10, pady=(8, 6))
        self._card_footer(frame, option)
        return frame

    def _tier_pips(self, option):
        """Tier as filled/empty pips -- a build menu wants to show progress
        toward a ceiling at a glance, not make the player read '2 of 3'."""
        if option.max_tier <= 0:
            return ""
        return ("●" * option.current_tier
                + "○" * max(0, option.max_tier - option.current_tier))

    def _card_footer(self, frame, option):
        if option.in_progress:
            elapsed, total = option.in_progress
            tk.Label(frame, text=f"Under construction — {elapsed} of {total} turns",
                     bg=theme.PANEL, fg=theme.WARN, font=theme.FONT_SMALL_BOLD,
                     anchor="w").pack(fill="x", padx=10, pady=(0, 10))
            return
        if option.blocked:
            tk.Label(frame, text=option.blocked, bg=theme.PANEL, fg=theme.MUTED,
                     font=theme.FONT_SMALL, anchor="w", justify="left",
                     wraplength=_CARD_W - 30).pack(fill="x", padx=10, pady=(0, 10))
            return

        tk.Label(frame, text=_format_cost(option.cost), bg=theme.PANEL,
                 fg=theme.INK if option.affordable else theme.BAD,
                 font=theme.FONT_SMALL, anchor="w", justify="left",
                 wraplength=_CARD_W - 30).pack(fill="x", padx=10)
        tk.Label(frame, text=f"{option.turns} turns to build", bg=theme.PANEL,
                 fg=theme.MUTED, font=theme.FONT_SMALL, anchor="w"
                 ).pack(fill="x", padx=10, pady=(0, 4))
        verb = "Upgrade" if option.current_tier > 0 else "Build"
        widgets.button(
            frame, f"{verb} — tier {option.to_tier}",
            lambda o=option: self._start(o),
            kind="accent" if option.priority == "urgent" else "default",
            state="normal" if option.affordable else "disabled",
        ).pack(fill="x", padx=10, pady=(0, 10))

    # --- actions ---------------------------------------------------------
    def _start(self, option):
        if option.building == "shipyard":
            message = construction.start_shipyard(self.world, self.nation, self.node)
        else:
            message = construction.start_storage_building(
                self.world, self.nation, self.node, option.building)
        self._render()
        self._msg.config(text=message)
        self._msg.pack(fill="x", pady=(6, 2))
        if self.on_change:
            self.on_change()


def open_for(master, world, node, nation, on_change=None):
    """Open (or re-focus) the build menu for `node`. One window per node --
    re-opening the same place raises the window that is already up rather
    than stacking a second copy of it."""
    existing = getattr(master, "_build_menus", None)
    if existing is None:
        existing = {}
        master._build_menus = existing
    key = (B.node_kind(node), node.id)
    window = existing.get(key)
    if window is not None and window.winfo_exists():
        window.deiconify()
        window.lift()
        window.focus_set()
        return window
    window = BuildMenuWindow(master, world, node, nation, on_change=on_change)
    existing[key] = window
    return window
