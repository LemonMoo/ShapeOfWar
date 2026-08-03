"""Who made the things this game is built out of.

The point of this screen is not politeness, though it is that too. It is what
makes attribution-required work USABLE: CC0 asks for nothing, CC-BY asks for a
visible credit, and until there was somewhere to put one the game could only
ever use the first kind. That ruled out most of what exists -- the CC-BY sound
libraries are far larger and far better than the CC0 ones -- for want of a
list.

So this is the list, and CREDITS below is the single source of truth for it.
`assets/audio/LICENSES.md` is the long-form record, and dev/test_audio.py
asserts the two agree: a credit that lives only in a markdown file nobody
ships is not a credit, and a screen that has drifted from the licence record
is worse than no screen at all.

Two of the entries here (cynicmusic, rubberduck) are CC0 and legally require
nothing. They asked nicely, and it costs nothing to say so.
"""
import tkinter as tk

from app.ui import parchment
from app.ui import theme

# One entry per source. `licence` is the actual licence, `requires_credit`
# says whether this screen is an obligation or a courtesy -- kept explicit
# rather than inferred from the licence string, because that is the field
# anybody adding an asset has to think about.
CREDITS = [
    {
        "section": "Sound effects",
        "title": "80 CC0 RPG SFX",
        "author": "rubberduck",
        "licence": "CC0",
        "requires_credit": False,
        "url": "https://opengameart.org/content/80-cc0-rpg-sfx",
        "note": "Blades, shields, chains, coin, stone, timber and fire — the "
                "whole voice of the game, from the build menu to the battle "
                "line.",
    },
    {
        "section": "Sound effects",
        "title": "20 Sword Sound Effects (Attacks and Clashes)",
        "author": "StarNinjas",
        "licence": "CC0",
        "requires_credit": False,
        "url": "https://opengameart.org/content/20-sword-sound-effects-attacks-and-clashes",
        "note": "Ten sword attacks and ten clashes — what a melee actually "
                "sounds like, and what a shield turning a blow sounds like.",
    },
    {
        "section": "Sound effects",
        "title": "100 CC0 SFX #2 and 100 CC0 metal and wood SFX",
        "author": "rubberduck",
        "licence": "CC0",
        "requires_credit": False,
        "url": "https://opengameart.org/content/100-cc0-sfx-2",
        "note": "Footsteps, impacts, rubble, thunder, doors, hammers and "
                "gates. The same hands as the library above, which is why "
                "none of it sounds borrowed.",
    },
    {
        "section": "Sound effects",
        "title": "Fantasy Sound Effects Library",
        "author": "Little Robot Sound Factory",
        "licence": "CC-BY 3.0",
        "requires_credit": True,
        "url": "https://opengameart.org/content/fantasy-sound-effects-library",
        "note": "Goblin voices, the roar of something in the wildland, the "
                "cave you hear when you go below the mountains, and the "
                "sound of winning and losing a battle.",
    },
    {
        "section": "Music",
        "title": "Town Theme RPG",
        "author": "cynicmusic",
        "licence": "CC0",
        "requires_credit": False,
        "url": "https://opengameart.org/content/town-theme-rpg",
        "note": "The map theme. Harps and recorders.",
    },
    {
        "section": "Music",
        "title": "Battle Theme A",
        "author": "cynicmusic",
        "licence": "CC0",
        "requires_credit": False,
        "url": "https://opengameart.org/content/battle-theme-a",
        "note": "What plays when the lines meet.",
    },
]

# Authors who ask for a particular form of words. Honoured exactly as asked.
COURTESY_LINES = {
    "cynicmusic": "cynicmusic.com / pixelsphere.org",
    # NOT a courtesy: CC-BY 3.0, and this is the wording and the link they ask
    # for. It is the reason this screen exists at all.
    "Little Robot Sound Factory": "www.littlerobotsoundfactory.com",
}


def sections():
    """CREDITS grouped in the order the sections first appear."""
    order = []
    grouped = {}
    for entry in CREDITS:
        if entry["section"] not in grouped:
            grouped[entry["section"]] = []
            order.append(entry["section"])
        grouped[entry["section"]].append(entry)
    return [(name, grouped[name]) for name in order]


class CreditsView(tk.Frame):
    """A scrolling page of who made what. Reached from the main menu and from
    the settings screen, because that is where somebody wondering about the
    music goes looking. Drawn on app/ui/parchment.py's Page -- a colophon,
    which is exactly the manuscript-page idiom the kit is for."""

    def __init__(self, master, on_close=None, title="Credits"):
        super().__init__(master, bg=theme.BG)
        self.on_close = on_close
        self._title = title

        body = tk.Frame(self, bg=theme.PANEL)
        body.pack(fill="both", expand=True, padx=60, pady=24)
        canvas = tk.Canvas(body, bg=theme.PANEL, highlightthickness=0)
        scrollbar = tk.Scrollbar(body, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self._canvas = canvas
        self._page = parchment.Page(None, 720, seed=61, canvas=canvas)
        canvas.bind("<Enter>", lambda e: canvas.bind_all(
            "<MouseWheel>", lambda ev: canvas.yview_scroll(int(-ev.delta / 120), "units")))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        canvas.bind("<Configure>", lambda e: self._render())
        self._render()

    def _render(self):
        page = self._page
        page.begin(max(400, self._canvas.winfo_height() or 400))
        page.title(self._title, "Shapes of War is built on work other people "
                                "gave away. This is who.")
        for name, entries in sections():
            page.gap(6)
            page.text(name.upper(), fill=theme.ACCENT, font=theme.FONT_HEADER)
            page.divider()
            for entry in entries:
                self._entry(page, entry)
        page.gap(6)
        page.button("Back", self._close, kind="accent")
        page.finish()

    def _entry(self, page, entry):
        line = f"{entry['title']} — {entry['author']}"
        courtesy = COURTESY_LINES.get(entry["author"])
        if courtesy:
            line += f" ({courtesy})"
        page.text(line, font=theme.FONT_BOLD)
        tag = entry["licence"]
        if entry["requires_credit"]:
            tag += " — credit required"
        page.text(f"{tag} · {entry['url']}", fill=theme.MUTED, indent=6)
        if entry.get("note"):
            page.text(entry["note"], fill=theme.MUTED, indent=6)
        page.gap(6)

    def _close(self):
        if self.on_close is not None:
            self.on_close()
