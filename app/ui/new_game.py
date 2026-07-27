"""New Game setup: pick a species, name your realm, then play."""
import random
import tkinter as tk

from app.ui import theme
from app.world.lexicon import SPECIES, make_faction_namer, species_trait_summary


class NewGameView(tk.Frame):
    def __init__(self, master, on_play, on_back):
        super().__init__(master, bg=theme.BG)
        self.on_play = on_play
        self.on_back = on_back
        self._namer = make_faction_namer(random.Random())
        self._name_is_custom = False
        self._suppress_trace = False

        center = tk.Frame(self, bg=theme.BG)
        center.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(center, text="New Game", bg=theme.BG, fg=theme.INK,
                 font=theme.FONT_TITLE).pack(pady=(0, 24))

        tk.Label(center, text="Choose your species", bg=theme.BG,
                 fg=theme.MUTED, font=theme.FONT).pack(anchor="w")
        species_row = tk.Frame(center, bg=theme.BG)
        species_row.pack(pady=(6, 22))
        self._species_buttons = {}
        for sp in SPECIES:
            b = tk.Button(species_row, text=sp, width=10,
                          command=lambda s=sp: self._pick_species(s),
                          bg="#232a36", fg=theme.INK, relief="flat",
                          font=theme.FONT, activebackground=theme.ACCENT)
            b.pack(side="left", padx=4)
            self._species_buttons[sp] = b

        # What the picked species actually does differently -- generated from
        # the real trait numbers (see lexicon.species_trait_summary), so it can
        # never drift out of sync with the balance values themselves.
        self._trait_lbl = tk.Label(center, text="", bg=theme.BG, fg=theme.ACCENT,
                                   font=("Segoe UI", 9), justify="left",
                                   anchor="w", wraplength=430)
        self._trait_lbl.pack(anchor="w", pady=(0, 18))

        tk.Label(center, text="Name your realm", bg=theme.BG, fg=theme.MUTED,
                 font=theme.FONT).pack(anchor="w")
        name_row = tk.Frame(center, bg=theme.BG)
        name_row.pack(pady=(6, 26))
        self._name_var = tk.StringVar()
        self._name_var.trace_add("write", self._on_name_edit)
        self._entry = tk.Entry(name_row, textvariable=self._name_var, width=26,
                               bg="#0d1017", fg=theme.INK, relief="flat",
                               insertbackground=theme.INK, font=theme.FONT)
        self._entry.pack(side="left", ipady=4, padx=(0, 6))
        tk.Button(name_row, text="Random Name", command=self._random_name,
                  bg="#232a36", fg=theme.INK, relief="flat", font=theme.FONT,
                  activebackground=theme.ACCENT).pack(side="left")

        actions = tk.Frame(center, bg=theme.BG)
        actions.pack()
        tk.Button(actions, text="← Back", command=on_back, width=10,
                  bg="#232a36", fg=theme.INK, relief="flat", font=theme.FONT,
                  activebackground=theme.ACCENT).pack(side="left", padx=6)
        tk.Button(actions, text="Play Game", width=14, command=self._play,
                  bg=theme.ACCENT, fg="#06121f", relief="flat",
                  font=theme.FONT_BOLD, activebackground=theme.ACCENT
                  ).pack(side="left", padx=6)

        # Shown only while the (synchronous, blocking) world generator runs
        # for a much bigger map than before — created last so it's on top
        # of everything else in this frame once placed.
        self._generating_lbl = tk.Label(self, text="Generating world...",
                                        bg=theme.BG, fg=theme.ACCENT,
                                        font=theme.FONT_TITLE)

        self.reset()

    def reset(self):
        """Call each time the screen is entered from the menu, so it always
        starts on a clean, freshly-randomized first species/name."""
        self._pick_species(next(iter(SPECIES)))

    def _pick_species(self, species):
        self.species = species
        for sp, b in self._species_buttons.items():
            picked = sp == species
            b.config(bg=theme.ACCENT if picked else "#232a36",
                     fg="#06121f" if picked else theme.INK)
        traits = species_trait_summary(species)
        flavor = SPECIES[species]["trait"]
        self._trait_lbl.config(
            text=f"{flavor}  ·  " + "   ".join(traits) if traits else flavor)
        if not self._name_is_custom:
            self._random_name()

    def _random_name(self):
        self._suppress_trace = True
        self._name_var.set(self._namer(self.species))
        self._suppress_trace = False
        self._name_is_custom = False

    def _on_name_edit(self, *_args):
        if not self._suppress_trace:
            self._name_is_custom = True

    def _play(self):
        name = self._name_var.get().strip() or self._namer(self.species)
        self._generating_lbl.place(relx=0.5, rely=0.5, anchor="center")
        self.update_idletasks()   # force the label to actually paint before the blocking call
        self.on_play(self.species, name)
        self._generating_lbl.place_forget()
