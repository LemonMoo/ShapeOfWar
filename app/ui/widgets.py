"""Shared Tk widget-factory helpers for the medieval-styled HUD.

Extracted from MapView's _card/_kv/_bar_row (app/ui/map_view.py) so every
panel -- map_view.py's side panels and battle_view.py's battle HUD -- can
build the same foldable-card / label-value-row / meter-row / button idiom
instead of each hand-rolling its own inline Frame/Label/Button construction.
"""
import tkinter as tk

from app.ui import theme

_BUTTON_KINDS = {
    "default": dict(bg=theme.PANEL_ALT, fg=theme.INK, activebackground=theme.ACCENT,
                     activeforeground=theme.ACCENT_INK),
    "accent": dict(bg=theme.ACCENT, fg=theme.ACCENT_INK, activebackground=theme.INK,
                    activeforeground=theme.ACCENT_INK),
    "danger": dict(bg=theme.BAD, fg=theme.INK, activebackground=theme.WARN,
                    activeforeground=theme.ACCENT_INK),
    "success": dict(bg="#1f3a24", fg=theme.GOOD, activebackground=theme.ACCENT,
                     activeforeground=theme.ACCENT_INK),
    "active": dict(bg=theme.ACCENT, fg=theme.ACCENT_INK, activebackground=theme.ACCENT,
                    activeforeground=theme.ACCENT_INK),
}


def card(parent, open_state, key, title, subtitle=None, default_open=True,
         on_toggle=None):
    """A titled, foldable section. `open_state` is a dict the CALLER owns
    (e.g. MapView._panel_cards_open) so independent panels can each keep
    their own fold state without this module owning any state itself.
    `on_toggle`, if given, is called (with no arguments) after the state
    flips -- callers use this to trigger a redraw, since this module has no
    way to know how the caller's panel is rebuilt. Returns the body frame to
    build into, or None when folded shut."""
    expanded = open_state.get(key, default_open)
    head = tk.Frame(parent, bg=theme.PANEL_ALT, cursor="hand2",
                     highlightbackground=theme.LINE, highlightthickness=1)
    head.pack(fill="x", pady=theme.CARD_HEAD_PAD_Y)
    tk.Label(head, text=("▾ " if expanded else "▸ ") + title.upper(),
             bg=theme.PANEL_ALT, fg=theme.ACCENT, font=theme.FONT_HEADER,
             anchor="w", padx=10, pady=6).pack(side="left")
    if subtitle:
        tk.Label(head, text=subtitle, bg=theme.PANEL_ALT, fg=theme.MUTED,
                 font=theme.FONT_SMALL, anchor="e", padx=10).pack(side="right")

    def _toggle(_e=None):
        open_state[key] = not open_state.get(key, default_open)
        if on_toggle:
            on_toggle()

    for wdg in (head,) + tuple(head.winfo_children()):
        wdg.bind("<Button-1>", _toggle)
    if not expanded:
        return None
    body = tk.Frame(parent, bg=theme.PANEL, relief=theme.BORDER_RELIEF,
                     borderwidth=theme.BORDER_WIDTH,
                     highlightbackground=theme.LINE)
    body.pack(fill="x", padx=(2, 0))
    return body


def kv(parent, label, value, fg=None):
    """One aligned label/value row."""
    row = tk.Frame(parent, bg=theme.PANEL)
    row.pack(fill="x", pady=(theme.ROW_PAD_Y // 2, 0))
    tk.Label(row, text=label, bg=theme.PANEL, fg=theme.MUTED,
             font=theme.FONT_SMALL, anchor="w").pack(side="left")
    tk.Label(row, text=value, bg=theme.PANEL, fg=fg or theme.INK,
             font=theme.FONT_SMALL, anchor="e").pack(side="right")


def bar_row(parent, label, used, cap, warn_at=0.85):
    """A compact labelled meter -- used/cap plus a fill bar."""
    frac = (used / cap) if cap else 0
    colour = (theme.BAD if frac > 1.0 else
              theme.WARN if frac > warn_at else theme.GOOD)
    row = tk.Frame(parent, bg=theme.PANEL)
    row.pack(fill="x", pady=(theme.ROW_PAD_Y, 0))
    tk.Label(row, text=label, bg=theme.PANEL, fg=theme.MUTED,
             font=theme.FONT_SMALL, anchor="w").pack(side="left")
    tk.Label(row, text=f"{used:,} / {cap:,}", bg=theme.PANEL, fg=colour,
             font=theme.FONT_SMALL, anchor="e").pack(side="right")
    meter = tk.Canvas(parent, height=6, bg=theme.METER_TRACK, highlightthickness=0)
    meter.pack(fill="x", pady=(2, 3))
    meter.update_idletasks()
    width = max(1, meter.winfo_width())
    meter.create_rectangle(0, 0, width * min(1.0, frac), 6,
                            fill=colour, outline="")


def button(parent, text, command, kind="default", state="normal", compact=False,
           **pack_kwargs):
    """A styled button. `kind` is one of "default", "accent", "danger",
    "active" -- see `_BUTTON_KINDS` above. `compact=True` drops to a smaller
    font and tighter padding for dense multi-button rows (e.g. battle_view's
    per-unit-type select buttons packed several to a row) where the normal
    bigger-click-target sizing would overflow the row."""
    style = _BUTTON_KINDS.get(kind, _BUTTON_KINDS["default"])
    btn = tk.Button(parent, text=text, command=command,
                     font=theme.FONT_SMALL_BOLD if compact else theme.FONT_BOLD,
                     relief="flat", pady=2 if compact else theme.BTN_PAD_Y,
                     cursor="hand2", state=state, **style)
    if pack_kwargs:
        btn.pack(**pack_kwargs)
    return btn
