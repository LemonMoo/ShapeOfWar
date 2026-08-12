"""New Game setup: build a realm, look at the world it will live in, then play.

The screen this replaced asked two questions (species, realm name) and showed a
line of trait text. Everything else about the run you were about to start -- who
you were, what your realm looked like, how big the world was, how many rivals
were in it, and whether your corner of it was any good -- you found out after
committing.

Two things make the richer version affordable:

  * **Generating a world takes 8-37 seconds**, so it runs on a background thread
    from the moment the screen opens and while you are still naming things. By
    the time most players press Play it is already done, and Play uses the world
    you were LOOKING AT rather than rolling a fresh one. The old screen made you
    wait for a world you had never seen.
  * **Almost nothing about a world depends on who you are.** Terrain, regions and
    every rival are identical whoever you pick, so species, name, colour and
    monarch are patched onto the generated world in a fraction of a millisecond
    (worldgen.apply_player_identity). Only size, rival count and a reroll are
    world-shaping enough to need a new one.
"""
import queue
import random
import threading
import tkinter as tk

from PIL import ImageDraw, ImageTk

from app.ui import theme
from app.ui.world_preview import land_summary, render_world
from app.world.lexicon import (RULER_TITLES, SPECIES, make_faction_namer,
                               make_ruler_namer, species_palette,
                               species_stat_chips, species_units)
from app.world.worldgen import apply_player_identity, generate_world, OCEAN
from app.world import startsites
from app.world.holds import UNDERGROUND_SPECIES

# (label, width, height, rivals, blurb). Measured generation cost is 8s / 18s /
# 37s respectively -- which is exactly why the preview generates in the
# background instead of on demand.
WORLD_SIZES = [
    ("Small", 760, 456, 9, "tight and quarrelsome"),
    ("Standard", 1100, 660, 14, "the default world"),
    ("Large", 1500, 900, 18, "room to grow into"),
]
DEFAULT_SIZE = 1
MIN_RIVALS, MAX_RIVALS = 3, 24

# The preview box, in pixels. Everything in the right-hand column is sized off
# it, so the column and the map can never disagree about how wide they are.
PREVIEW_W, PREVIEW_H = 640, 384

# Cave-door marker on the preview: a violet diamond per network gate mouth --
# the mountainous cells a cave people can walk into the underearth from. The
# gold dots are start sites, the green ring is your chosen start; the door
# diamonds are a third thing and get their own colour so none of them blur.
_DOOR_FILL = "#b06ad4"
_DOOR_RING = "#2a1233"

# Was a blue-grey set (#1b2029, #0d1017, ...) left from before the palette
# existed -- the New Game screen was the last place in the game still painted
# in the pre-theme colours. Now derived from the parchment theme so it matches
# the drawn HUD and menus rather than looking like a different program.
_CARD_BG = theme.PANEL
_FIELD_BG = theme.METER_TRACK
_ROW_BG = theme.PANEL_ALT
# Selection is a MARKER, not a fill. A full bright-gold row (the first pass)
# left white text stranded on gold and unreadable; it also shouts, which is
# wrong for a dense list you read five rows of to compare. So a picked row
# keeps a dark background -- lifted a shade so it still reads as "this one" --
# and is flagged by a gold bar down its left edge and its name in gold, both
# of which stay legible because the background under them is still dark.
_ROW_SEL_BG = theme.ROW_SELECT    # a warm lift on _ROW_BG, not the accent
_ROW_MARK = theme.ACCENT         # the left-edge selection bar
_BTN_BG = theme.PANEL_ALT        # the old blue-grey button face
_BTN_SEL_INK = theme.ACCENT_INK  # text on an accent/selected control


class NewGameView(tk.Frame):
    def __init__(self, master, on_play, on_back):
        super().__init__(master, bg=theme.BG)
        self.on_play = on_play
        self.on_back = on_back
        # Its own Random, not the module-global one: worldgen runs on another
        # thread and both would otherwise be drawing from the same state.
        self._rng = random.Random()
        self._faction_namer = make_faction_namer(self._rng)
        self._ruler_namer = make_ruler_namer(self._rng)

        self.species = next(iter(SPECIES))
        self.color = species_palette(self.species)[0]
        self._name_is_custom = False
        self._ruler_is_custom = False
        self._suppress = False

        # Background world generation (see the module docstring).
        self._world = None            # the world Play will actually use
        self._pending = 0             # token of the in-flight request, 0 = idle
        self._start_cell = None       # player's chosen start, or None = auto-place
        self._start_ok = True         # is the chosen start sustainable
        self._candidates = []         # [(x, y, eval), ...] good sites to offer
        self._preview_scale = 1.0     # world->preview px, for mapping clicks
        self._results = queue.Queue()
        self._preview_img = None      # ImageTk ref; Tk drops unreferenced ones

        self._build()
        self.reset()
        self.after(120, self._drain)

    # --- layout ---------------------------------------------------------------
    def _build(self):
        head = tk.Frame(self, bg=theme.BG)
        head.pack(fill="x", padx=28, pady=(18, 6))
        tk.Label(head, text="New Game", bg=theme.BG, fg=theme.INK,
                 font=theme.FONT_TITLE).pack(side="left")
        tk.Label(head, text="Choose a people, name your realm, and see the "
                            "world before you commit to it.",
                 bg=theme.BG, fg=theme.MUTED, font=theme.FONT).pack(side="left",
                                                                    padx=(14, 0))

        self._build_actions()          # packed to the bottom before the body,
                                       # so a tall body can never push it off

        body = tk.Frame(self, bg=theme.BG)
        body.pack(fill="both", expand=True, padx=28, pady=(6, 0))
        left = tk.Frame(body, bg=theme.BG)
        left.pack(side="left", fill="both", expand=True)
        right = tk.Frame(body, bg=theme.BG, width=PREVIEW_W + 20)
        right.pack(side="right", fill="y", padx=(22, 0))
        right.pack_propagate(False)

        self._build_species(left)
        self._build_identity(left)
        self._build_world(left)
        self._build_card(right)

    def _section(self, parent, text, pady=(14, 6)):
        tk.Label(parent, text=text.upper(), bg=theme.BG, fg=theme.MUTED,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=pady)

    def _build_species(self, parent):
        self._section(parent, "Your people", pady=(4, 6))
        self._species_rows = {}
        for sp in SPECIES:
            row = tk.Frame(parent, bg=_ROW_BG, cursor="hand2")
            row.pack(fill="x", pady=2)
            # The selection marker: a thin strip down the left edge, gold when
            # this row is picked and the row's own colour (invisible) otherwise.
            mark = tk.Frame(row, bg=_ROW_BG, width=4)
            mark.pack(side="left", fill="y")
            inner = tk.Frame(row, bg=_ROW_BG)
            inner.pack(side="left", fill="x", expand=True, padx=10, pady=5)
            name = tk.Label(inner, text=sp, bg=_ROW_BG, fg=theme.INK,
                            font=theme.FONT_BOLD, width=9, anchor="w")
            name.pack(side="left")
            chips = "  ·  ".join(species_stat_chips(sp))
            units = species_units(sp)
            if units:
                chips += "  ·  " + " + ".join(units)
            detail = tk.Label(inner, text=chips, bg=_ROW_BG, fg=theme.MUTED,
                              font=("Segoe UI", 8), anchor="w", justify="left",
                              wraplength=500)
            detail.pack(side="left", fill="x", expand=True)
            self._species_rows[sp] = (row, mark, inner, name, detail)
            # Bind the frame AND its children: a click landing on the label
            # would otherwise do nothing, which reads as a broken row.
            for widget in (row, mark, inner, name, detail):
                widget.bind("<Button-1>", lambda e, s=sp: self._pick_species(s))

    def _build_identity(self, parent):
        self._section(parent, "Your realm")
        grid = tk.Frame(parent, bg=theme.BG)
        grid.pack(fill="x")

        self._name_var = self._labelled_entry(grid, 0, "Realm name",
                                              self._random_realm_name)
        self._name_var.trace_add("write", lambda *_: self._on_edit("name"))

        # Ruler: a title picker beside the name, because "King Aldric" is one
        # thing to read but two decisions -- and the title is species flavour
        # (Archon, High King, Warlord, Boss) worth showing off.
        tk.Label(grid, text="Ruler", bg=theme.BG, fg=theme.MUTED,
                 font=theme.FONT, width=11, anchor="w").grid(row=1, column=0,
                                                             sticky="w", pady=4)
        ruler_row = tk.Frame(grid, bg=theme.BG)
        ruler_row.grid(row=1, column=1, sticky="ew", pady=4)
        self._title_var = tk.StringVar()
        self._title_btn = tk.Button(ruler_row, textvariable=self._title_var,
                                    command=self._cycle_title, width=10,
                                    bg=_BTN_BG, fg=theme.INK, relief="flat",
                                    font=theme.FONT, activebackground=theme.ACCENT)
        self._title_btn.pack(side="left", padx=(0, 6))
        self._ruler_var = tk.StringVar()
        entry = tk.Entry(ruler_row, textvariable=self._ruler_var, bg=_FIELD_BG,
                         fg=theme.INK, relief="flat", insertbackground=theme.INK,
                         font=theme.FONT)
        entry.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 6))
        self._dice(ruler_row, self._random_ruler_name).pack(side="left")
        self._ruler_var.trace_add("write", lambda *_: self._on_edit("ruler"))
        grid.columnconfigure(1, weight=1)

        self._section(parent, "Banner colour")
        self._swatch_row = tk.Frame(parent, bg=theme.BG)
        self._swatch_row.pack(fill="x")
        self._swatches = []

    def _labelled_entry(self, grid, row, label, dice_cmd):
        tk.Label(grid, text=label, bg=theme.BG, fg=theme.MUTED, font=theme.FONT,
                 width=11, anchor="w").grid(row=row, column=0, sticky="w", pady=4)
        holder = tk.Frame(grid, bg=theme.BG)
        holder.grid(row=row, column=1, sticky="ew", pady=4)
        var = tk.StringVar()
        entry = tk.Entry(holder, textvariable=var, bg=_FIELD_BG, fg=theme.INK,
                         relief="flat", insertbackground=theme.INK,
                         font=theme.FONT)
        entry.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 6))
        self._dice(holder, dice_cmd).pack(side="left")
        return var

    def _dice(self, parent, command):
        return tk.Button(parent, text="⟳", command=command, width=3,
                         bg=_BTN_BG, fg=theme.INK, relief="flat",
                         font=theme.FONT, activebackground=theme.ACCENT)

    def _build_world(self, parent):
        self._section(parent, "The world")
        row = tk.Frame(parent, bg=theme.BG)
        row.pack(fill="x")
        self._size_var = tk.IntVar(value=DEFAULT_SIZE)
        self._size_buttons = []
        for i, (label, _w, _h, _rivals, blurb) in enumerate(WORLD_SIZES):
            b = tk.Button(row, text=f"{label}\n{blurb}", width=16,
                          command=lambda i=i: self._pick_size(i),
                          bg=_BTN_BG, fg=theme.INK, relief="flat",
                          font=("Segoe UI", 9), activebackground=theme.ACCENT)
            b.pack(side="left", padx=(0, 6))
            self._size_buttons.append(b)

        rivals = tk.Frame(parent, bg=theme.BG)
        rivals.pack(fill="x", pady=(8, 0))
        tk.Label(rivals, text="Rival realms", bg=theme.BG, fg=theme.MUTED,
                 font=theme.FONT, width=11, anchor="w").pack(side="left")
        self._rivals_var = tk.IntVar(value=WORLD_SIZES[DEFAULT_SIZE][3] - 1)
        self._rivals_scale = tk.Scale(
            rivals, from_=MIN_RIVALS, to=MAX_RIVALS, orient="horizontal",
            variable=self._rivals_var, bg=theme.BG, fg=theme.INK,
            troughcolor=_FIELD_BG, highlightthickness=0, relief="flat",
            activebackground=theme.ACCENT, font=("Segoe UI", 8), length=250)
        # Bound to release, not to the variable: dragging the slider fires a
        # value change per pixel, and each one would start a 20-second world.
        self._rivals_scale.bind("<ButtonRelease-1>", self._on_world_shape_changed)
        self._rivals_scale.pack(side="left")

    def _build_card(self, parent):
        """The realm as it will be: banner, name, monarch, what they can do."""
        card = tk.Frame(parent, bg=_CARD_BG)
        card.pack(fill="x")
        self._banner = tk.Frame(card, bg=self.color, height=8)
        self._banner.pack(fill="x")
        pad = tk.Frame(card, bg=_CARD_BG)
        pad.pack(fill="x", padx=14, pady=10)
        self._card_realm = tk.Label(pad, text="", bg=_CARD_BG, fg=theme.INK,
                                    font=("Segoe UI", 14, "bold"), anchor="w",
                                    justify="left", wraplength=PREVIEW_W - 30)
        self._card_realm.pack(fill="x")
        self._card_ruler = tk.Label(pad, text="", bg=_CARD_BG, fg=theme.ACCENT,
                                    font=theme.FONT, anchor="w")
        self._card_ruler.pack(fill="x", pady=(2, 6))
        self._card_traits = tk.Label(pad, text="", bg=_CARD_BG, fg=theme.MUTED,
                                     font=("Segoe UI", 9), anchor="w",
                                     justify="left", wraplength=PREVIEW_W - 30)
        self._card_traits.pack(fill="x")

        self._section(parent, "The world you will play", pady=(10, 6))
        # The box is a fixed-size FRAME with the content centred inside it,
        # rather than a label sized to its own content. A label's width/height
        # are characters when it holds text and pixels when it holds an image,
        # so sizing the label directly gets it wrong in one state or the other
        # no matter which units you pick -- a 430x258 map squeezed into a 54px
        # sliver, or a placeholder 258 text-lines tall that shoves everything
        # below it off the screen. Both of those happened.
        holder = tk.Frame(parent, bg=_FIELD_BG, width=PREVIEW_W, height=PREVIEW_H)
        holder.pack(anchor="w")
        holder.pack_propagate(False)
        self._preview = tk.Label(holder, bg=_FIELD_BG, fg=theme.MUTED,
                                 font=theme.FONT, text="Charting a world…",
                                 justify="center")
        self._preview.place(relx=0.5, rely=0.5, anchor="center")
        # Click the map to choose where your realm begins. The gold dots are
        # good, spread-out sites; you may also click anywhere else, and be
        # warned if the ground cannot feed a realm (see startsites).
        self._preview.bind("<Button-1>", self._on_preview_click)
        self._preview_note = tk.Label(parent, text="", bg=theme.BG,
                                      fg=theme.MUTED, font=("Segoe UI", 9),
                                      anchor="w", justify="left", wraplength=PREVIEW_W)
        self._preview_note.pack(fill="x", pady=(6, 0))
        self._start_note = tk.Label(parent, text="Click the map to choose your "
                                    "start — or press Play to be placed for you.",
                                    bg=theme.BG, fg=theme.ACCENT,
                                    font=("Segoe UI", 9, "bold"), anchor="w",
                                    justify="left", wraplength=PREVIEW_W)
        self._start_note.pack(fill="x", pady=(4, 0))
        self._start_warn = tk.Label(parent, text="", bg=theme.BG, fg=theme.BAD,
                                    font=("Segoe UI", 9, "bold"), anchor="w",
                                    justify="left", wraplength=PREVIEW_W)
        self._start_warn.pack(fill="x")
        self._reroll_btn = tk.Button(parent, text="⟳  Roll a different world",
                                     command=self._reroll, bg=_BTN_BG,
                                     fg=theme.INK, relief="flat",
                                     font=theme.FONT,
                                     activebackground=theme.ACCENT)
        self._reroll_btn.pack(fill="x", pady=(8, 0))

    def _build_actions(self):
        actions = tk.Frame(self, bg=theme.BG)
        actions.pack(fill="x", padx=28, pady=14, side="bottom")
        tk.Button(actions, text="← Back", command=self.on_back, width=10,
                  bg=_BTN_BG, fg=theme.INK, relief="flat", font=theme.FONT,
                  activebackground=theme.ACCENT).pack(side="left")
        self._play_btn = tk.Button(actions, text="Play Game", width=18,
                                   command=self._play, bg=theme.ACCENT,
                                   fg=_BTN_SEL_INK, relief="flat",
                                   font=theme.FONT_BOLD,
                                   activebackground=theme.ACCENT)
        self._play_btn.pack(side="right")
        self._status = tk.Label(actions, text="", bg=theme.BG, fg=theme.MUTED,
                                font=theme.FONT)
        self._status.pack(side="right", padx=12)

    # --- state ----------------------------------------------------------------
    def reset(self):
        """Called every time the screen is entered from the menu, so it always
        opens on a clean realm and starts charting a world immediately."""
        self._name_is_custom = False
        self._ruler_is_custom = False
        self._pick_size(DEFAULT_SIZE, regenerate=False)
        self._pick_species(next(iter(SPECIES)), regenerate=False)
        self._request_world()

    def _pick_species(self, species, regenerate=True):
        self.species = species
        for sp, (row, mark, inner, name, detail) in self._species_rows.items():
            picked = sp == species
            bg = _ROW_SEL_BG if picked else _ROW_BG
            for widget in (row, inner, name, detail):
                widget.config(bg=bg)
            # The marker is the one thing that turns gold; the row stays dark,
            # so name (gold) and detail (muted) both stay readable on it.
            mark.config(bg=_ROW_MARK if picked else bg)
            name.config(bg=bg, fg=theme.ACCENT if picked else theme.INK)
        self._title_var.set(RULER_TITLES.get(species, RULER_TITLES["Humans"])[0])
        self._build_swatches()
        if not self._name_is_custom:
            self._random_realm_name(apply=False)
        if not self._ruler_is_custom:
            self._random_ruler_name(apply=False)
        self._refresh_card()
        if regenerate:
            # Species is NOT world-shaping -- it is patched onto the world that
            # already exists, which is what makes browsing the five of them
            # instant instead of a 20-second wait each.
            self._apply_identity()

    def _build_swatches(self):
        for widget in self._swatch_row.winfo_children():
            widget.destroy()
        self._swatches = []
        palette = species_palette(self.species)
        if self.color not in palette:
            self.color = palette[0]
        for hex_color in palette:
            b = tk.Frame(self._swatch_row, bg=hex_color, width=28, height=22,
                         cursor="hand2", highlightthickness=2,
                         highlightbackground=theme.BG)
            b.pack(side="left", padx=2)
            b.pack_propagate(False)
            b.bind("<Button-1>", lambda e, c=hex_color: self._pick_color(c))
            self._swatches.append((hex_color, b))
        self._mark_swatch()

    def _mark_swatch(self):
        for hex_color, widget in self._swatches:
            widget.config(highlightbackground=theme.INK
                          if hex_color == self.color else theme.BG)

    def _pick_color(self, hex_color):
        self.color = hex_color
        self._mark_swatch()
        self._refresh_card()
        self._apply_identity()

    def _cycle_title(self):
        pair = RULER_TITLES.get(self.species, RULER_TITLES["Humans"])
        options = list(dict.fromkeys(pair))     # a species may offer only one
        current = self._title_var.get()
        nxt = (options[(options.index(current) + 1) % len(options)]
               if current in options else options[0])
        self._title_var.set(nxt)
        self._refresh_card()
        self._apply_identity()

    def _pick_size(self, index, regenerate=True):
        self._size_var.set(index)
        for i, b in enumerate(self._size_buttons):
            picked = i == index
            b.config(bg=theme.ACCENT if picked else _BTN_BG,
                     fg=_BTN_SEL_INK if picked else theme.INK)
        self._suppress = True
        self._rivals_var.set(WORLD_SIZES[index][3] - 1)
        self._suppress = False
        if regenerate:
            self._request_world()

    def _random_realm_name(self, apply=True):
        self._set_quietly(self._name_var, self._faction_namer(self.species))
        self._name_is_custom = False
        if apply:
            self._refresh_card()
            self._apply_identity()

    def _random_ruler_name(self, apply=True):
        self._set_quietly(self._ruler_var, self._ruler_namer(self.species))
        self._ruler_is_custom = False
        if apply:
            self._refresh_card()
            self._apply_identity()

    def _set_quietly(self, var, value):
        self._suppress = True
        var.set(value)
        self._suppress = False

    def _on_edit(self, which):
        if self._suppress:
            return
        if which == "name":
            self._name_is_custom = True
        else:
            self._ruler_is_custom = True
        self._refresh_card()
        self._apply_identity()

    # --- the realm card -------------------------------------------------------
    def _refresh_card(self):
        realm = self._name_var.get().strip() or "Unnamed Realm"
        self._banner.config(bg=self.color)
        self._card_realm.config(text=realm)
        ruler = self._ruler_var.get().strip()
        self._card_ruler.config(
            text=f"{self._title_var.get()} {ruler}".strip() if ruler
            else "an unnamed throne")
        chips = species_stat_chips(self.species)
        units = species_units(self.species)
        lines = [f"{self.species} — {SPECIES[self.species]['trait']}"]
        if chips:
            lines.append("  ·  ".join(chips))
        if units:
            lines.append("Fields " + " and ".join(units)
                         + (" — units no other people has" if len(units) > 1
                            else ", a unit no other people has"))
        self._card_traits.config(text="\n".join(lines))

    # --- world generation -----------------------------------------------------
    def _ruler_dict(self):
        return {"name": (self._ruler_var.get().strip()
                         or self._ruler_namer(self.species)),
                "title": self._title_var.get()}

    def _apply_identity(self):
        """Re-skin the already-generated world. Costs a fraction of a
        millisecond, so it can run on every keystroke."""
        if self._world is None:
            return
        apply_player_identity(self._world, species=self.species,
                              name=self._name_var.get().strip() or None,
                              color=self.color, ruler=self._ruler_dict())
        self._draw_preview()

    def _on_world_shape_changed(self, *_args):
        if self._suppress:
            return
        self._request_world()

    def _reroll(self):
        self._request_world(seed=self._rng.randrange(1 << 30))

    def _request_world(self, seed=None):
        """Start generating in the background. Any result still in flight is
        abandoned by token, so clicking through three sizes leaves only the last
        one's world standing rather than whichever thread happens to finish
        last."""
        index = self._size_var.get()
        _label, width, height, _default_rivals, _blurb = WORLD_SIZES[index]
        n_factions = max(1, int(self._rivals_var.get())) + 1
        self._pending += 1
        token = self._pending
        self._world = None
        self._set_busy(True)
        args = dict(width=width, height=height, seed=seed, n_factions=n_factions,
                    player_species=self.species,
                    player_name=self._name_var.get().strip() or None,
                    player_color=self.color, player_ruler=self._ruler_dict())
        threading.Thread(target=self._worker, args=(token, args),
                         daemon=True).start()

    def _worker(self, token, args):
        try:
            world = generate_world(**args)
            self._results.put((token, world, None))
        except Exception as exc:            # a failed roll must not wedge the UI
            self._results.put((token, None, exc))

    def _drain(self):
        while True:
            try:
                token, world, exc = self._results.get_nowait()
            except queue.Empty:
                break
            if token != self._pending:
                continue                    # superseded; throw it away
            self._receive(world, exc)
        self.after(120, self._drain)

    def _receive(self, world, exc):
        if exc is not None:
            self._preview.config(image="", text="Could not chart a world.\n"
                                                "Try rolling another.")
            self._preview_note.config(text=str(exc))
        else:
            self._world = world
            self._start_cell = None
            self._start_warn.config(text="")
            self._start_note.config(
                text="Click the map to choose your start — or press Play to be "
                     "placed for you.")
            # The dots to offer. Cells only; affinity/order is recomputed per
            # species when the card is shown, so switching people needs no
            # rebuild here.
            import random as _random
            self._candidates = startsites.candidate_sites(
                world, 6, self.species, rng=_random.Random(world.seed))
            self._apply_identity()
        self._set_busy(False)

    def _set_busy(self, busy):
        self._reroll_btn.config(state="disabled" if busy else "normal")
        # Play stays ENABLED while charting: pressing it is a perfectly
        # reasonable "I don't care, just start", and it simply waits.
        self._status.config(text="charting a world…" if busy else "")
        if busy:
            self._preview.config(image="", text="Charting a world…")
            self._preview_note.config(text="Bigger worlds take longer. You can "
                                           "keep naming things while it runs.")

    def _draw_preview(self):
        world = self._world
        if world is None:
            return
        # Once a start is CHOSEN, the default capital ring (render_world's
        # white one) must not linger where the realm would otherwise be
        # founded -- the green ring at the chosen cell replaces it, so
        # suppressing the default here is what stops the stray circle that
        # used to stay behind at the original spot.
        img = render_world(world, (PREVIEW_W, PREVIEW_H),
                           mark_player=self._start_cell is None).copy()
        # render_world takes the aspect from the world, so the image can be
        # letterboxed inside the box; this is the exact scale it used, and the
        # one _on_preview_click inverts to turn a click back into a cell.
        scale = min(PREVIEW_W / world.w, PREVIEW_H / world.h)
        self._preview_scale = scale
        draw = ImageDraw.Draw(img)
        # A cave people reads the mountain doors straight off the map: every
        # network gate's surface mouth, so the player can pick a start by one.
        # (Gates are only placed on mountain cells -- see underworld.py's
        # adits -- so each diamond sits on exactly the terrain it means.)
        if self.species in UNDERGROUND_SPECIES and world.gates:
            for gate in world.gates:
                gx, gy = gate["pos"]
                px, py = gx * scale, gy * scale
                draw.polygon([(px, py - 4), (px + 4, py), (px, py + 4),
                              (px - 4, py)], fill=_DOOR_FILL, outline=_DOOR_RING)
        for cx, cy, _ev in self._candidates:
            px, py = cx * scale, cy * scale
            draw.ellipse([px - 2, py - 2, px + 2, py + 2],
                         fill="#e8c24a", outline="#3a2c10")
        if self._start_cell is not None:
            px, py = self._start_cell[0] * scale, self._start_cell[1] * scale
            ok = self._start_ok
            ring = "#5fd06a" if ok else theme.BAD
            draw.ellipse([px - 5, py - 5, px + 5, py + 5], outline=ring, width=2)
            draw.ellipse([px - 2, py - 2, px + 2, py + 2], fill=ring)
        self._preview_img = ImageTk.PhotoImage(img)
        self._preview.config(image=self._preview_img, text="")
        idx = world.player_faction_idx
        self._preview_note.config(
            text=land_summary(world, idx) if idx is not None else "")

    def _nearest_land(self, wx, wy, reach=20):
        """The nearest settleable land cell to a click, or None if the click
        is far out to sea. Mirrors generate_world's own snap so the marker
        sits where the realm would actually be founded."""
        world = self._world
        if (0 <= wx < world.w and 0 <= wy < world.h
                and world.owner[wy][wx] != OCEAN and (wx, wy) not in world.lake_cells):
            return (wx, wy)
        best = None
        for dy in range(-reach, reach + 1):
            cy = wy + dy
            if not (0 <= cy < world.h):
                continue
            for dx in range(-reach, reach + 1):
                cx = wx + dx
                if not (0 <= cx < world.w):
                    continue
                if world.owner[cy][cx] != OCEAN and (cx, cy) not in world.lake_cells:
                    d = dx * dx + dy * dy
                    if best is None or d < best[0]:
                        best = (d, cx, cy)
        return (best[1], best[2]) if best else None

    def _on_preview_click(self, event):
        """Choose a start. Snap to the nearest offered site if the click is
        close to one; otherwise free-place wherever there is land, warning if
        the ground cannot feed a realm."""
        world = self._world
        if world is None:
            return
        wx = int(event.x / self._preview_scale)
        wy = int(event.y / self._preview_scale)
        # Snap to a candidate dot if the click is within a few cells of one.
        snap = None
        snap_d = (12 / self._preview_scale) ** 2
        for cx, cy, ev in self._candidates:
            d = (cx - wx) ** 2 + (cy - wy) ** 2
            if d <= snap_d and (snap is None or d < snap[0]):
                snap = (d, cx, cy, ev)
        if snap is not None:
            _d, cx, cy, ev = snap
            self._start_cell = (cx, cy)
        else:
            land = self._nearest_land(wx, wy)
            if land is None:
                return                       # clicked far out to sea; ignore
            self._start_cell = land
            ev = startsites.evaluate_site(world, land[0], land[1], self.species)
        self._start_ok = ev["sustain"]["ok"]
        self._show_start_card(ev)
        self._draw_preview()

    def _show_start_card(self, ev):
        biome = ev["dominant_biome"] or "open water"
        water = " · ".join(w for w, on in (("coast", ev["coast"]),
                                           ("river", ev["river"])) if on)
        goods = ", ".join(ev["resources"][:6]) or "little of note"
        parts = [f"Chosen start: {biome}, {int(ev['farmland_pct'] * 100)}% farmland"]
        if water:
            parts.append(water)
        if ev["room"]:
            parts.append(ev["room"])
        # Cave peoples read their underground prospects on the card: the
        # capital will be under the mountain here, so "no caves beneath" is
        # a surface-bound realm and worth saying before the player commits.
        under = ev.get("underground")
        if under is not None:
            parts.append("sits above a cave network"
                         if under["ok"] else "no caves beneath (this realm "
                         "would live above ground)")
        self._start_note.config(text=" · ".join(parts) + "\n" + f"Goods: {goods}")
        self._start_warn.config(
            text="" if ev["sustain"]["ok"] else "⚠  " + ev["sustain"]["reason"])

    # --- play -----------------------------------------------------------------
    def _play(self):
        """Hand over the world that is on screen.

        If one is still generating, wait for it rather than rolling a second --
        the whole promise of the preview is that you play the world you looked
        at, and quietly starting a different one would break it."""
        self._play_btn.config(state="disabled")
        try:
            while self._world is None:
                self._status.config(text="charting a world…")
                self.update()               # keep the window alive while waiting
                try:
                    token, world, exc = self._results.get(timeout=0.1)
                except queue.Empty:
                    continue
                if token != self._pending:
                    continue
                self._receive(world, exc)
                if self._world is None:     # generation failed -- let them retry
                    return
            self._apply_identity()
            self._settle_chosen_start()
            self.on_play(self._world)
        finally:
            self._play_btn.config(state="normal")
            self._status.config(text="")

    def _settle_chosen_start(self):
        """If the player picked a start, regenerate the world with them founded
        there before handing it over.

        Regenerated rather than re-homed: generation is deterministic from the
        seed, and terrain does not depend on where the player sits (Part B1),
        so the same seed yields the SAME map the preview showed -- only the
        player's capital moves to the chosen cell. Re-homing an already-settled
        world (moving its settlements, villages, foothold and commander) would
        be far more code and far more ways to be wrong. The cost is one more
        generation, behind a 'founding' status line; it only runs when a start
        was actually chosen."""
        world = self._world
        if world is None or self._start_cell is None:
            return
        current = (world.factions[world.player_faction_idx].meta.get("capital")
                   if world.player_faction_idx is not None else None)
        if current is not None and tuple(current) == tuple(self._start_cell):
            return                         # already founded there
        self._status.config(text="founding your realm…")
        self.update()
        # regenerate_with_start reproduces the previewed terrain from the
        # stashed generation params (world.seed alone cannot, for a world that
        # retried internally) and founds the player at the chosen cell.
        self._world = startsites.regenerate_with_start(
            world, self._start_cell, species=self.species,
            name=self._name_var.get().strip() or None,
            color=self.color, ruler=self._ruler_dict())
