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
from app.world import resources


# Deliberately narrower than it reads: the cards are dense but short, and a
# wide card wastes the right half of every one of them on empty space while
# forcing a scroll to see the fourth building. Narrower cards plus a bigger
# window is how more of the menu fits on screen at once.
_CARD_W = 250
_CARD_MIN_COLS = 2
_CARD_MAX_COLS = 5

# The window's preferred size, clamped to the game window by _place_over. Big
# enough for four columns of cards, which is the point of the narrower card.
_PREFERRED_SIZE = (1280, 860)

# Priority colour and label. "urgent" is the one that carries information the
# player did not already have -- something at this node is being destroyed
# right now and this building is the answer.
_PRIORITY = {
    "urgent": (theme.BAD, "NEEDED NOW"),
    "useful": (theme.WARN, "WORTH BUILDING"),
    "idle": (theme.MUTED, "NO PRESSURE"),
    "blocked": (theme.LINE, "UNAVAILABLE"),
}

SECTOR_LABEL = {"farming": "Fields", "forestry": "Woods",
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
        # Used to check the node is actually this player's before offering it
        # any orders. The constructor is handed the faction OBJECT, and every
        # ownership check in the game is by index.
        self.nation_idx = (world.factions.index(nation)
                           if nation in world.factions else -1)
        # How wide the next labour order reaches. Sticky across re-renders on
        # purpose: setting the scope once and then trying several policies is
        # the natural way to use this, and resetting it every click would make
        # the wider scopes almost unusable.
        self._scope = "village"

        kind = (node.kind.capitalize() if hasattr(node, "kind") else "Village")
        self.title(f"{node.name} — {kind}")
        self.minsize(700, 480)
        # No OS titlebar or border: the game draws its own chrome in its own
        # style, so a grey Windows frame around a parchment-and-leather panel
        # is exactly the seam we are trying not to have. The cost is that
        # everything the window manager used to provide has to be provided
        # here -- a border, a way to move it, a way to close it, and focus --
        # which is what the rest of this method and _begin_drag/_drag are for.
        self.overrideredirect(True)
        # The frame itself: one flat rule around the whole window, drawn as the
        # Toplevel's own background showing through a 1px inset.
        self.configure(bg=theme.LINE)
        self.transient(master)
        self._place_over(master)

        self._shell = tk.Frame(self, bg=theme.BG)
        self._shell.pack(fill="both", expand=True, padx=1, pady=1)

        self._build_chrome()
        self._render()
        self.bind("<Escape>", lambda e: self.destroy())
        # On the Toplevel, NOT bind_all. Every widget inside a window has its
        # toplevel in its own bindtags, so one binding here reaches the whole
        # menu wherever the pointer happens to be -- and, unlike bind_all,
        # nobody else can take it away. bind_all was the bug: map_view's side
        # panels bind_all the wheel on <Enter> and unbind_all it on <Leave>
        # (map_view.py:1057 and friends), so merely moving the mouse across
        # the map's panels on the way to this window silently deleted this
        # window's scrolling. It also stopped this window clobbering theirs.
        self.bind("<MouseWheel>", self._on_wheel)
        self.bind("<Button-4>", self._on_wheel)
        self.bind("<Button-5>", self._on_wheel)
        self.bind("<Destroy>", self._on_destroy)
        # An undecorated window is not given focus by the window manager, so
        # Escape would do nothing until something inside it were clicked.
        self.after_idle(self._take_focus)

    def _place_over(self, master):
        """Centre on the game window. With no OS frame there is no sensible
        default position -- an undecorated window placed by the window manager
        lands in the top-left corner of the screen."""
        width, height = _PREFERRED_SIZE
        try:
            master.update_idletasks()
            mw, mh = master.winfo_width(), master.winfo_height()
            mx, my = master.winfo_rootx(), master.winfo_rooty()
            if mw > 1 and mh > 1:
                width = max(700, min(width, mw - 60))
                height = max(480, min(height, mh - 60))
                x, y = mx + (mw - width) // 2, my + (mh - height) // 2
                self.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")
                return
        except tk.TclError:
            pass
        self.geometry(f"{width}x{height}")

    def _take_focus(self):
        try:
            self.lift()
            self.focus_force()
        except tk.TclError:
            pass   # already destroyed

    # --- chrome ----------------------------------------------------------
    def _build_chrome(self):
        top = tk.Frame(self._shell, bg=theme.PANEL)
        top.pack(fill="x")
        kind = (self.node.kind.capitalize() if hasattr(self.node, "kind") else "Village")
        title = tk.Label(top, text=self.node.name, bg=theme.PANEL, fg=theme.ACCENT,
                         font=theme.FONT_TITLE)
        title.pack(side="left", padx=14, pady=8)
        subtitle = tk.Label(top, text=kind, bg=theme.PANEL, fg=theme.MUTED,
                            font=theme.FONT)
        subtitle.pack(side="left", pady=8)
        widgets.button(top, "Close (Esc)", self.destroy).pack(side="right", padx=10, pady=8)
        # The header IS the titlebar now. Bound on the header and its labels
        # rather than on the whole window, so dragging still means dragging and
        # a click on a card is still a click on a card.
        for wdg in (top, title, subtitle):
            wdg.bind("<Button-1>", self._begin_drag)
            wdg.bind("<B1-Motion>", self._drag)
            wdg.configure(cursor="fleur")

        self._msg = tk.Label(self._shell, text="", bg=theme.BG, fg=theme.ACCENT,
                             font=theme.FONT_BOLD, anchor="w", padx=16)

        outer = tk.Frame(self._shell, bg=theme.BG)
        outer.pack(fill="both", expand=True)
        self._canvas = tk.Canvas(outer, bg=theme.BG, highlightthickness=0)
        self._canvas.pack(side="left", fill="both", expand=True)
        # Styled rather than left default: with the OS frame gone, a stock grey
        # Tk scrollbar is the only thing left in the window that isn't ours.
        bar = tk.Scrollbar(outer, orient="vertical", command=self._canvas.yview,
                           width=12, borderwidth=0, relief="flat",
                           highlightthickness=0, troughcolor=theme.METER_TRACK,
                           bg=theme.PANEL_ALT, activebackground=theme.ACCENT)
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
        cols = max(1, min(_CARD_MAX_COLS, event.width // (_CARD_W + 14)))
        if cols != getattr(self, "_cols", None):
            self._cols = cols
            self._render()

    def _begin_drag(self, event):
        self._drag_from = (event.x_root - self.winfo_x(),
                           event.y_root - self.winfo_y())

    def _drag(self, event):
        origin = getattr(self, "_drag_from", None)
        if origin is None:
            return
        self.geometry(f"+{event.x_root - origin[0]}+{event.y_root - origin[1]}")

    def _on_wheel(self, event):
        # X11 sends wheel as Button-4/5 with no .delta; Windows sends a signed
        # delta. Three units a notch rather than one -- the cards are tall and
        # a one-unit scroll barely moves the page.
        if getattr(event, "num", None) in (4, 5):
            step = -3 if event.num == 4 else 3
        else:
            step = -3 if event.delta > 0 else 3
        self._canvas.yview_scroll(step, "units")

    def _on_destroy(self, event):
        if event.widget is not self:
            return
        # Hand focus back to the game. An undecorated window has to take focus
        # for itself (see _take_focus), and Windows does not reliably give it
        # back to the parent when one is destroyed -- leaving the keyboard
        # pointed at nothing, which is half of why E stopped ending turns
        # after opening this window. (The other half was the root binding
        # itself; see App.__init__'s bind_all.)
        try:
            master = self.master
            if master is not None and master.winfo_exists():
                master.focus_force()
        except tk.TclError:
            pass   # the whole app is going away

    # --- content ---------------------------------------------------------
    def _render(self):
        # Where the player was looking, so a turn-end refresh does not throw
        # them back to the top of a menu they were reading. Captured before
        # the teardown because an empty body reports a scrollregion of 0.
        try:
            was_at = self._canvas.yview()[0]
        except (tk.TclError, IndexError):
            was_at = None
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
                                          sticky="nsew", padx=5, pady=5)

        if was_at:
            # after_idle, not now: the scrollregion is only correct once Tk has
            # processed the <Configure> this rebuild just queued.
            self.after_idle(lambda f=was_at: self._restore_scroll(f))

    def _restore_scroll(self, fraction):
        try:
            self._canvas.yview_moveto(fraction)
        except tk.TclError:
            pass   # window closed between the rebuild and the idle callback

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
        self._render_labor_orders(box, report)

        for row in report["sectors"]:
            line = tk.Frame(box, bg=theme.PANEL)
            line.pack(fill="x", padx=12, pady=2)
            tk.Label(line, text=SECTOR_LABEL.get(row["sector"], row["sector"].title()),
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

    def _render_labor_orders(self, box, report):
        """Where the player actually decides what this village works on.

        Only offered where the village is your own and the order means
        something: a sector focus is hidden when that sector has nothing to
        work in any season (resources.labor_policy_available). The model
        tolerates an impossible order -- it falls through to Auto rather than
        idling the village -- but offering one as a CHOICE would be a lie about
        what the button does.

        The scope buttons matter as much as the policy ones. A realm can hold
        several hundred villages, and an order that has to be given three
        hundred times is a chore rather than a lever."""
        if self.node.faction_idx != self.nation_idx:
            return
        if report.get("idle"):
            tk.Label(box,
                     text=f"{report['idle']:,} of these hands have nothing left "
                          f"to do — every sector here is already working all "
                          f"the land there is. More land or more buildings will "
                          f"help; moving the labour about will not.",
                     bg=theme.PANEL, fg=theme.MUTED, font=theme.FONT_SMALL,
                     anchor="w", justify="left", wraplength=900
                     ).pack(fill="x", padx=12, pady=(4, 0))
        row = tk.Frame(box, bg=theme.PANEL)
        row.pack(fill="x", padx=12, pady=(6, 0))
        tk.Label(row, text="Put the hands on:", bg=theme.PANEL, fg=theme.MUTED,
                 font=theme.FONT_SMALL, anchor="w").pack(side="left", padx=(0, 6))
        current = report["policy"]
        for policy in resources.LABOR_POLICIES:
            if not resources.labor_policy_available(self.world, self.node, policy):
                continue
            widgets.button(row, policy, lambda p=policy: self._set_labor(p),
                           kind="active" if policy == current else "default",
                           compact=True).pack(side="left", padx=2)

        scope_row = tk.Frame(box, bg=theme.PANEL)
        scope_row.pack(fill="x", padx=12, pady=(4, 8))
        tk.Label(scope_row, text="Apply to:", bg=theme.PANEL, fg=theme.MUTED,
                 font=theme.FONT_SMALL, anchor="w").pack(side="left", padx=(0, 6))
        for scope, label in (("village", "This village"),
                             ("region", "Every village in this region"),
                             ("realm", "Every village in the realm")):
            widgets.button(scope_row, label, lambda s=scope: self._set_scope(s),
                           kind="active" if self._scope == scope else "default",
                           compact=True).pack(side="left", padx=2)

    def _set_scope(self, scope):
        self._scope = scope
        self._render()

    def _set_labor(self, policy):
        changed = resources.apply_labor_policy(self.world, self.node, policy,
                                               scope=self._scope)
        where = {"village": self.node.name,
                 "region": "this region",
                 "realm": "the realm"}[self._scope]
        if changed:
            self._notice(f"{policy}: {changed} village"
                         f"{'s' if changed != 1 else ''} in {where} reassigned.")
        else:
            self._notice(f"Every village in {where} was already set to {policy}.")
        self._render()
        if self.on_change:
            self.on_change()

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
                 font=theme.FONT_HEADER, anchor="w", padx=8,
                 pady=4).pack(side="left")
        tk.Label(head, text=self._tier_pips(option), bg=theme.PANEL_ALT,
                 fg=theme.INK, font=theme.FONT_SMALL, padx=8).pack(side="right")

        tk.Label(frame, text=badge, bg=theme.PANEL, fg=colour,
                 font=theme.FONT_SMALL_BOLD, anchor="w"
                 ).pack(fill="x", padx=8, pady=(4, 0))
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

        tk.Frame(frame, bg=theme.LINE, height=1).pack(fill="x", padx=8, pady=(6, 4))
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
            # Counting DOWN, not up. "3 of 8 turns" makes you do the
            # subtraction yourself every turn; what you actually want to know
            # is how much longer you are waiting.
            elapsed, total = option.in_progress
            left = max(0, total - elapsed)
            when = "finishes this turn" if left <= 0 else (
                "1 turn left" if left == 1 else f"{left} turns left")
            tk.Label(frame, text=f"Under construction — {when}",
                     bg=theme.PANEL, fg=theme.WARN, font=theme.FONT_SMALL_BOLD,
                     anchor="w").pack(fill="x", padx=8, pady=(0, 8))
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
    def _notice(self, message):
        """The one-line result bar under the title. Packed on first use rather
        than up front so the window has no empty strip before anything has
        happened."""
        self._msg.config(text=message)
        self._msg.pack(fill="x", pady=(6, 2))

    def _start(self, option):
        if option.building == "shipyard":
            message = construction.start_shipyard(self.world, self.nation, self.node)
        else:
            message = construction.start_storage_building(
                self.world, self.nation, self.node, option.building)
        self._render()
        self._notice(message)
        if self.on_change:
            self.on_change()


def refresh_open(master):
    """Re-render every build menu that is currently open.

    The menu used to be a snapshot: you started a Granary, ended six turns,
    and the card still said what it said when you opened it -- no countdown,
    and no change from "not built" to "built" until you closed and reopened
    the window. Called from MapView.refresh(), which is the one place that
    already knows a turn has been processed.

    Closed windows are dropped from the registry here rather than in the
    window's own destroy handler: this runs every turn anyway, and it means
    there is exactly one place that knows how the registry is shaped.
    """
    menus = getattr(master, "_build_menus", None)
    if not menus:
        return
    for key, window in list(menus.items()):
        if window is None or not window.winfo_exists():
            menus.pop(key, None)
            continue
        window._render()


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
