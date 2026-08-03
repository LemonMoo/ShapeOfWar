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

from app.ui import theme
from app.ui import widgets

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
    """A plain, scrollable list. Reached from the main menu and from the
    settings screen, because that is where somebody wondering about the music
    goes looking."""

    def __init__(self, master, on_close=None, title="Credits"):
        super().__init__(master, bg=theme.BG)
        self.on_close = on_close

        tk.Label(self, text=title, bg=theme.BG, fg=theme.INK,
                 font=("Segoe UI", 22, "bold")).pack(pady=(28, 6))
        tk.Label(self, text="Shapes of War is built on work other people gave "
                            "away. This is who.",
                 bg=theme.BG, fg=theme.MUTED, font=theme.FONT).pack(pady=(0, 18))

        body = tk.Frame(self, bg=theme.BG)
        body.pack(fill="both", expand=True, padx=60)
        for name, entries in sections():
            tk.Label(body, text=name.upper(), bg=theme.BG, fg=theme.ACCENT,
                     font=theme.FONT_HEADER, anchor="w").pack(
                         fill="x", pady=(14, 4))
            for entry in entries:
                self._entry(body, entry)

        widgets.button(self, "Back", self._close, kind="accent").pack(
            pady=(24, 30), ipadx=30)

    def _entry(self, parent, entry):
        card = tk.Frame(parent, bg=theme.PANEL, relief=theme.BORDER_RELIEF,
                        borderwidth=theme.BORDER_WIDTH)
        card.pack(fill="x", pady=3)
        line = f"{entry['title']} — {entry['author']}"
        courtesy = COURTESY_LINES.get(entry["author"])
        if courtesy:
            line += f" ({courtesy})"
        tk.Label(card, text=line, bg=theme.PANEL, fg=theme.INK,
                 font=theme.FONT_BOLD, anchor="w").pack(
                     fill="x", padx=12, pady=(8, 0))
        tag = entry["licence"]
        if entry["requires_credit"]:
            tag += " — credit required"
        tk.Label(card, text=f"{tag} · {entry['url']}", bg=theme.PANEL,
                 fg=theme.MUTED, font=theme.FONT_SMALL, anchor="w").pack(
                     fill="x", padx=12)
        if entry.get("note"):
            tk.Label(card, text=entry["note"], bg=theme.PANEL, fg=theme.MUTED,
                     font=theme.FONT_SMALL, anchor="w", justify="left",
                     wraplength=760).pack(fill="x", padx=12, pady=(0, 8))

    def _close(self):
        if self.on_close is not None:
            self.on_close()
