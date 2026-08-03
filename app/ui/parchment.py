"""The illuminated-manuscript layer: parchment, ornament, and drawn panels.

v0.3.9 gave the HUD a fantasy PALETTE (see app/ui/theme.py) -- warm parchment
colours, a serif display face, carved ridge borders. What it could not give it
was a fantasy SURFACE, because a Tk widget is a flat rectangle of one colour
and nothing in the toolkit changes that: no textures, no gradients, no rounded
corners, no corner flourishes.

So this module stops fighting the toolkit. Everything here is DRAWN -- onto a
PIL image for the surfaces, onto a Tk canvas for the ornament and the text --
and the panels built on it are canvas items rather than stacks of Labels. That
is what buys real parchment with fibres in it, a rule that ends in a fleuron,
an illuminated capital at the head of a card, and a meter that reads as ink in
a carved channel.

WHY PROCEDURAL AND NOT ART FILES
--------------------------------
Two reasons, and the second is the one that matters. Bundling art means the
build has to carry it and PyInstaller has to find it -- this project has
already shipped two releases where `assets/` never made it into the exe
(HANDOFF S33, and the memory note about packaging bugs). And a texture
generated from a seed can be regenerated at any size for any panel, which a
fixed PNG cannot.

EVERYTHING IS CACHED
--------------------
A texture costs milliseconds to generate and nothing to reuse, and the panels
rebuild on a throttle while the world runs (see map_view's _PANEL_REFRESH_MS).
Cache keys are (width, height, seed), and the PhotoImage references are held
here on purpose: Tk drops an image the moment its last Python reference goes,
which shows up as panels that render once and then go blank.
"""
import math
import random
import tkinter as tk

from PIL import Image, ImageDraw, ImageFilter, ImageTk

from app.ui import theme

# --- the surface --------------------------------------------------------------
# Aged vellum: a warm base, darker toward the edges where a real sheet is
# handled most, with fibres and a few blotches. Kept close to theme.PANEL so
# every widget that is still an ordinary Tk widget sits on it without a seam.
# Two sheets, because they are two different rooms to be in and the choice is
# the single biggest decision in this whole layer.
#
#   VELLUM     dark, oiled hide. Sits in the existing dark HUD without
#              changing anything else about it.
#   PARCHMENT  a pale, aged sheet with dark ink on it -- the archetype, and
#              far more "a page out of a book", but it inverts every text
#              colour the HUD uses.
#
# Both are the same generator with different numbers, so nothing has to be
# re-tuned twice.
PALETTES = {
    "vellum": {
        "base": (58, 46, 33), "fibre": (84, 68, 47), "blotch": (47, 36, 25),
        "edge": (30, 23, 16), "ink": "#ece0c8", "muted": "#a89778",
        "gold": "#d4ab52", "gold_dim": "#8a6f31", "rule": "#6b5433",
        "track": "#181109", "cap_bg": "#231a10", "leader": "#5b4830",
    },
    "parchment": {
        "base": (222, 202, 162), "fibre": (232, 214, 176),
        "blotch": (206, 183, 141), "edge": (176, 152, 112),
        "ink": "#2b2013", "muted": "#6b5a3d", "gold": "#8a5a12",
        "gold_dim": "#a9812f", "rule": "#9d8353", "track": "#c3ab7d",
        "cap_bg": "#f0e4c6", "leader": "#a9946c",
    },
}
DEFAULT_PALETTE = "vellum"

_texture_cache = {}
_photo_cache = {}


def palette(name=None):
    return PALETTES.get(name or DEFAULT_PALETTE, PALETTES["vellum"])


def texture(width, height, seed=0, name=None):
    """A sheet of this size, as a PIL image. Cached.

    Deliberately quiet: an earlier pass had big soft blotches and a heavy
    vignette, and rendered (dev/hud_shot.py) they read as smudges on leather
    rather than as a sheet. A texture under DATA has to be felt and not seen --
    if you can point at a stain, it is too strong."""
    pal = palette(name)
    key = (width, height, seed, name or DEFAULT_PALETTE)
    got = _texture_cache.get(key)
    if got is not None:
        return got
    width, height = max(1, int(width)), max(1, int(height))
    rng = random.Random(seed * 7919 + width * 31 + height)
    img = Image.new("RGB", (width, height), pal["base"])
    draw = ImageDraw.Draw(img)

    # Fibres: short strokes at shallow angles, the way a laid sheet looks.
    for _ in range(max(40, width * height // 700)):
        x = rng.randrange(width)
        y = rng.randrange(height)
        length = rng.randint(5, 18)
        angle = rng.uniform(-0.2, 0.2) + (0 if rng.random() < 0.5 else math.pi / 2)
        shade = rng.randint(-4, 6)
        draw.line([(x, y), (x + math.cos(angle) * length,
                            y + math.sin(angle) * length)],
                  fill=tuple(max(0, min(255, c + shade)) for c in pal["fibre"]))

    # Stains: small, few, and near the edges where a handled sheet takes them.
    for _ in range(max(2, width * height // 26000)):
        cx = rng.choice([rng.randrange(max(1, width // 4)),
                         rng.randrange(width * 3 // 4, width)])
        cy = rng.randrange(height)
        r = rng.randint(6, max(8, min(width, height) // 7))
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=pal["blotch"])
    img = img.filter(ImageFilter.GaussianBlur(1.1))

    # Handled edges -- a light touch, so the sheet meets its own border rather
    # than fading out well inside it.
    vignette = Image.new("L", (width, height), 0)
    vdraw = ImageDraw.Draw(vignette)
    pad = max(2, min(width, height) // 40)
    vdraw.rectangle([pad, pad, width - pad, height - pad], fill=255)
    vignette = vignette.filter(ImageFilter.GaussianBlur(pad * 1.6))
    img = Image.composite(img, Image.new("RGB", (width, height), pal["edge"]),
                          vignette)

    _texture_cache[key] = img
    return img


def photo(width, height, seed=0, name=None):
    """The same sheet as a Tk PhotoImage, cached and REFERENCED -- see the
    module docstring on why the reference has to live somewhere."""
    key = (int(width), int(height), seed, name or DEFAULT_PALETTE)
    got = _photo_cache.get(key)
    if got is None:
        got = ImageTk.PhotoImage(texture(width, height, seed, name))
        _photo_cache[key] = got
    return got


# --- ornament -----------------------------------------------------------------
# Every mark below takes its colours from the page's palette, so the same
# ornament vocabulary works on dark hide and on pale paper without a second
# set of drawing code.


def fleuron(canvas, x, y, size=5, colour=None, tags=(), pal=None):
    """The little four-lobed diamond that ends a rule. One shape, used
    everywhere -- an ornament vocabulary of one mark repeated reads as a style;
    six different marks read as clutter."""
    pal = pal or palette()
    s = size
    canvas.create_polygon(x, y - s, x + s * 0.6, y, x, y + s, x - s * 0.6, y,
                          fill=colour or pal["gold"], outline="", tags=tags)


def rule(canvas, x0, x1, y, colour=None, ends=True, tags=(), pal=None):
    """A horizontal rule with a fleuron at each end -- the manuscript's own
    way of closing a line, and the reason a drawn panel does not need boxes to
    separate its sections."""
    pal = pal or palette()
    colour = colour or pal["rule"]
    canvas.create_line(x0, y, x1, y, fill=colour, tags=tags)
    if ends:
        fleuron(canvas, x0, y, 3, colour, tags, pal)
        fleuron(canvas, x1, y, 3, colour, tags, pal)


def corner(canvas, x, y, dx, dy, size=14, colour=None, tags=(), pal=None):
    """A corner flourish: two strokes and a curl, mirrored by (dx, dy)."""
    pal = pal or palette()
    colour = colour or pal["gold_dim"]
    s = size
    canvas.create_line(x, y + dy * s, x, y, x + dx * s, y, fill=colour,
                       width=2, tags=tags)
    canvas.create_line(x + dx * s * 0.35, y + dy * s * 0.35,
                       x + dx * s * 0.35, y + dy * s * 0.9,
                       fill=colour, tags=tags)
    canvas.create_line(x + dx * s * 0.35, y + dy * s * 0.35,
                       x + dx * s * 0.9, y + dy * s * 0.35,
                       fill=colour, tags=tags)


def frame(canvas, x0, y0, x1, y1, colour=None, tags=(), pal=None):
    """A double rule with flourished corners: the border a page has, rather
    than the bevel a widget has."""
    pal = pal or palette()
    colour = colour or pal["gold_dim"]
    canvas.create_rectangle(x0, y0, x1, y1, outline=colour, tags=tags)
    canvas.create_rectangle(x0 + 3, y0 + 3, x1 - 3, y1 - 3,
                            outline=pal["rule"], tags=tags)
    for cx, cy, dx, dy in ((x0, y0, 1, 1), (x1, y0, -1, 1),
                           (x0, y1, 1, -1), (x1, y1, -1, -1)):
        corner(canvas, cx, cy, dx, dy, 13, colour, tags, pal)


def drop_cap(canvas, x, y, letter, size=20, tags=(), pal=None):
    """An illuminated capital: the letter on a panel of its own, boxed in
    gold. The word it belongs to is drawn WHOLE beside it (see Page.title) --
    an earlier pass dropped the letter from the word, which is how a real
    manuscript does it and which reads, in a HUD, as a bug."""
    pal = pal or palette()
    box = size
    canvas.create_rectangle(x, y, x + box, y + box, fill=pal["cap_bg"],
                            outline=pal["gold"], tags=tags)
    canvas.create_rectangle(x + 2, y + 2, x + box - 2, y + box - 2,
                            outline=pal["gold_dim"], tags=tags)
    canvas.create_text(x + box / 2, y + box / 2 + 1, text=letter.upper()[:1],
                       fill=pal["gold"],
                       font=(theme.FONT_FAMILY_HEAD, int(box * 0.62), "bold"),
                       tags=tags)
    return x + box


def seal(canvas, x, y, r=11, colour=theme.BAD, tags=()):
    """A wax seal, for an alert badge. A blob with a pressed rim and a
    highlight -- the thing an urgent message actually arrived under."""
    canvas.create_oval(x - r, y - r, x + r, y + r, fill=colour,
                       outline="#2a0d08", width=2, tags=tags)
    canvas.create_oval(x - r * 0.66, y - r * 0.66, x + r * 0.66, y + r * 0.66,
                       outline="#2a0d08", tags=tags)
    canvas.create_arc(x - r + 2, y - r + 2, x + r - 2, y + r - 2,
                      start=55, extent=70, style="arc", outline="#ffffff",
                      tags=tags)
    canvas.create_text(x, y + 1, text="!", fill="#2a0d08",
                       font=(theme.FONT_FAMILY_HEAD, max(9, int(r * 1.1)), "bold"),
                       tags=tags)


# --- the drawn panel ----------------------------------------------------------
PAD_X = 12
ROW_H = 18
HEAD_H = 30


class Page:
    """A panel drawn as a page rather than stacked out of widgets.

    Owns a Tk canvas, a sheet of parchment and a running y cursor, and hands
    back the same four idioms the widget kit does -- card, kv, bar, button --
    so a caller converts by changing which module it calls, not by rewriting
    its layout. Anything genuinely interactive is a canvas item with a
    tag_bind, so there is no Tk widget anywhere on the page to break the
    surface with its own flat rectangle.
    """

    def __init__(self, parent, width, seed=0, palette_name=None, **canvas_kwargs):
        self.pal = palette(palette_name)
        self.palette_name = palette_name or DEFAULT_PALETTE
        self.canvas = tk.Canvas(parent, width=width, highlightthickness=0,
                                bd=0, bg=theme.PANEL, **canvas_kwargs)
        self.width = width
        self.seed = seed
        self.y = 0
        self._height = 400
        self._next_tag = 0

    # -- surface -----------------------------------------------------------
    def begin(self, height=None):
        """Clear the page and lay a fresh sheet on it."""
        self.canvas.delete("all")
        self.y = 12
        self._height = height or self._height
        self._sheet()

    def _sheet(self):
        self.canvas.create_image(0, 0, anchor="nw", tags="sheet",
                                 image=photo(self.width, self._height,
                                             self.seed, self.palette_name))
        self.canvas.tag_lower("sheet")
        frame(self.canvas, 4, 4, self.width - 5, self._height - 5,
              tags="sheet_frame", pal=self.pal)

    def finish(self):
        """Size the canvas to what was actually drawn, and re-lay the sheet at
        that height -- the first one was drawn against a guess."""
        used = int(self.y + 14)
        self.canvas.config(height=used)
        self.canvas.delete("sheet")
        self.canvas.delete("sheet_frame")
        self._height = used
        self._sheet()
        return used

    # -- content -----------------------------------------------------------
    def title(self, text, subtitle=None):
        """A page heading: an illuminated capital, the name beside it, and a
        flourished rule under the lot.

        The subtitle gets its OWN line. It is usually a phrase rather than a
        word, and set beside the title it simply ran underneath it -- caught
        by dev/hud_shot.py before any of this reached a real panel, which is
        the whole reason that tool exists."""
        end = drop_cap(self.canvas, PAD_X, self.y, text[:1], 24, pal=self.pal)
        self.canvas.create_text(end + 9, self.y + 12, anchor="w",
                                text=text.upper(), fill=self.pal["gold"],
                                font=(theme.FONT_FAMILY_HEAD, 13, "bold"))
        self.y += 28
        if subtitle:
            item = self.canvas.create_text(
                PAD_X + 2, self.y, anchor="nw", text=subtitle,
                fill=self.pal["muted"],
                font=(theme.FONT_FAMILY_HEAD, 9, "italic"),
                width=self.width - 2 * PAD_X)
            box = self.canvas.bbox(item)
            self.y += (box[3] - box[1]) + 4
        rule(self.canvas, PAD_X, self.width - PAD_X, self.y, pal=self.pal)
        self.y += 12

    def card(self, key, title, open_state, subtitle=None, on_toggle=None,
             default_open=True):
        """A foldable section head. Returns whether it is open, so a caller
        keeps exactly the shape it had with the widget kit."""
        expanded = open_state.get(key, default_open)
        tag = self._tag()
        mark = "▾" if expanded else "▸"
        self.canvas.create_rectangle(0, self.y - 3, self.width, self.y + 16,
                                     fill="", outline="", tags=(tag,))
        self.canvas.create_text(PAD_X, self.y + 7, anchor="w",
                                text=mark + "  " + title.upper(),
                                fill=self.pal["gold"],
                                font=(theme.FONT_FAMILY_HEAD, 11, "bold"),
                                tags=(tag,))
        if subtitle:
            self.canvas.create_text(self.width - PAD_X, self.y + 7, anchor="e",
                                    text=subtitle, fill=self.pal["muted"],
                                    font=theme.FONT_SMALL, tags=(tag,))

        def _toggle(_e=None):
            open_state[key] = not open_state.get(key, default_open)
            if on_toggle:
                on_toggle()

        self._bind(tag, _toggle)
        self.y += 20
        if expanded:
            rule(self.canvas, PAD_X + 8, self.width - PAD_X - 8, self.y,
                 ends=False, pal=self.pal)
            self.y += 10
        return expanded

    def kv(self, label, value, fg=None, indent=0):
        """One line of the record: the thing on the left, what it is worth on
        the right, and a leader of dots between them -- which is how a ledger
        has always kept the eye on the line."""
        left = PAD_X + 4 + indent
        right = self.width - PAD_X - 4
        value = str(value)
        self.canvas.create_text(left, self.y, anchor="w", text=label,
                                fill=self.pal["muted"], font=theme.FONT_SMALL)
        self.canvas.create_text(right, self.y, anchor="e", text=value,
                                fill=fg or self.pal["ink"],
                                font=theme.FONT_SMALL_BOLD)
        dot_a = left + self._text_width(label, theme.FONT_SMALL) + 6
        dot_b = right - self._text_width(value, theme.FONT_SMALL_BOLD) - 6
        if dot_b > dot_a:
            self.canvas.create_line(dot_a, self.y + 1, dot_b, self.y + 1,
                                    fill=self.pal["leader"], dash=(1, 3))
        self.y += ROW_H

    def bar(self, label, used, cap, warn_at=0.85):
        """A meter as ink in a carved channel: a sunken track, a fill, and a
        highlight along its top edge."""
        frac = (used / cap) if cap else 0
        colour = (theme.BAD if frac > 1.0 else
                  theme.WARN if frac > warn_at else theme.GOOD)
        self.kv(label, f"{used:,} / {cap:,}", fg=colour)
        x0, x1 = PAD_X + 4, self.width - PAD_X - 4
        y = self.y + 1
        self.canvas.create_rectangle(x0, y, x1, y + 8, fill=self.pal["track"],
                                     outline=self.pal["rule"])
        fill_to = x0 + (x1 - x0) * max(0.0, min(1.0, frac))
        if fill_to > x0 + 1:
            self.canvas.create_rectangle(x0 + 1, y + 1, fill_to, y + 7,
                                         fill=colour, outline="")
            self.canvas.create_line(x0 + 1, y + 1, fill_to, y + 1,
                                    fill="#ffffff", stipple="gray25")
        # Air under the channel. Without it the fill reads as an underline on
        # the row below rather than as a meter of its own -- visible in the
        # first render, invisible in the source.
        self.y += 22

    def text(self, body, fill=None, font=None, indent=0):
        """A run of prose, wrapped to the page."""
        item = self.canvas.create_text(
            PAD_X + 4 + indent, self.y, anchor="nw", text=body,
            fill=fill or self.pal["ink"], font=font or theme.FONT_SMALL,
            width=self.width - 2 * PAD_X - 8 - indent)
        box = self.canvas.bbox(item)
        self.y += (box[3] - box[1]) + 6

    def alert(self, message, severity="warning"):
        """A message under a wax seal."""
        colour = theme.BAD if severity == "critical" else theme.WARN
        item = self.canvas.create_text(
            PAD_X + 32, self.y, anchor="nw", text=message,
            fill=self.pal["ink"], font=theme.FONT_SMALL,
            width=self.width - PAD_X - 46)
        box = self.canvas.bbox(item)
        seal(self.canvas, PAD_X + 14, self.y + 10, 11, colour)
        self.y += max(28, (box[3] - box[1]) + 10)

    def button(self, text, command, kind="default", width=None):
        """A carved plaque, not a Tk button: a bevelled block on the sheet with
        the word cut into it. Drawn, because a real widget here would put a
        flat grey rectangle in the middle of a page."""
        pal = self.pal
        faces = {"default": pal["cap_bg"], "accent": pal["gold"],
                 "danger": "#5c241d", "success": "#26401f"}
        face = faces.get(kind, faces["default"])
        ink = ("#241a0a" if kind == "accent"
               else theme.INK if kind in ("danger", "success") else pal["ink"])
        x0 = PAD_X + 4
        x1 = (x0 + width) if width else (self.width - PAD_X - 4)
        y0, y1 = self.y, self.y + 26
        tag = self._tag()
        self.canvas.create_rectangle(x0, y0, x1, y1, fill=face,
                                     outline=pal["gold_dim"], tags=(tag,))
        self.canvas.create_line(x0 + 1, y1 - 1, x1 - 1, y1 - 1,
                                fill=pal["rule"], tags=(tag,))
        self.canvas.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=text,
                                fill=ink,
                                font=(theme.FONT_FAMILY_HEAD, 10, "bold"),
                                tags=(tag,))
        fleuron(self.canvas, x0 + 10, (y0 + y1) / 2, 3, pal["gold_dim"],
                (tag,), pal)
        fleuron(self.canvas, x1 - 10, (y0 + y1) / 2, 3, pal["gold_dim"],
                (tag,), pal)
        self._bind(tag, lambda _e=None: command())
        self.y += 32
        return tag

    def alert_group(self, text, expanded, severity, command):
        """A foldable row of alerts of one kind, under a seal.

        Its own idiom rather than card()+alert(): what the player is scanning
        here is "how bad, and how many", so the count and the seal carry the
        line and the words come second."""
        colour = theme.BAD if severity == "critical" else theme.WARN
        tag = self._tag()
        self.canvas.create_rectangle(0, self.y - 2, self.width, self.y + 20,
                                     fill="", outline="", tags=(tag,))
        seal(self.canvas, PAD_X + 12, self.y + 9, 9, colour, tags=(tag,))
        mark = "▾" if expanded else "▸"
        self.canvas.create_text(PAD_X + 26, self.y + 9, anchor="w",
                                text=mark + " " + text, fill=colour,
                                font=theme.FONT_SMALL_BOLD, tags=(tag,))
        self._bind(tag, lambda _e=None: command())
        self.y += 22

    def entry(self, text, command, indent=26):
        """A clickable name in a list -- the detail under an alert group."""
        tag = self._tag()
        self.canvas.create_rectangle(0, self.y - 2, self.width, self.y + 14,
                                     fill="", outline="", tags=(tag,))
        item = self.canvas.create_text(PAD_X + indent, self.y, anchor="nw",
                                       text=text, fill=self.pal["muted"],
                                       font=theme.FONT_SMALL, tags=(tag,))
        self.canvas.tag_bind(tag, "<Enter>",
                             lambda _e: self.canvas.itemconfig(item,
                                                               fill=self.pal["gold"]))
        self.canvas.tag_bind(tag, "<Leave>",
                             lambda _e: self.canvas.itemconfig(item,
                                                               fill=self.pal["muted"]))
        self._bind(tag, lambda _e=None: command())
        self.y += 16

    def gap(self, amount=8):
        self.y += amount

    def divider(self):
        rule(self.canvas, PAD_X, self.width - PAD_X, self.y, pal=self.pal)
        self.y += 12

    # -- plumbing ----------------------------------------------------------
    def _tag(self):
        self._next_tag += 1
        return "hit%d" % self._next_tag

    def _bind(self, tag, handler):
        self.canvas.tag_bind(tag, "<Button-1>", handler)
        self.canvas.tag_bind(tag, "<Enter>",
                             lambda _e: self.canvas.config(cursor="hand2"))
        self.canvas.tag_bind(tag, "<Leave>",
                             lambda _e: self.canvas.config(cursor=""))

    _font_probe = {}

    def _text_width(self, text, font):
        """Measured, not guessed -- a dotted leader that overlaps its own label
        is worse than no leader at all."""
        try:
            import tkinter.font as tkfont
            key = tuple(font)
            probe = Page._font_probe.get(key)
            if probe is None:
                probe = Page._font_probe[key] = tkfont.Font(font=font)
            return probe.measure(text)
        except Exception:
            return len(text) * 6
