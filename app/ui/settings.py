"""The settings panel.

One widget, built once and reachable from both the main menu and the pause
menu, rather than two panels that drift apart. Audio is all it held at first;
it is shaped as a general settings panel because the next thing that needs a
slider or a toggle should not have to invent this again. (The video frame-rate
toggle is that next thing.)

Two things here are deliberate and easy to get wrong:

**Every change applies immediately, and is heard immediately.** There is no
OK button. A volume slider you have to confirm is a volume slider you cannot
actually judge, because the only way to know whether 40% is right is to hear
40%. Moving the effects slider plays a sound at the new level for the same
reason -- otherwise you are setting a number, not a volume. The video toggle
is the same principle: flipping it takes effect on the map the moment you go
back to it, not on some future restart.

**Nothing is saved on every drag.** A slider fires a callback per pixel, and
writing a JSON file a hundred times while somebody drags a knob is silly. The
write is debounced onto the Tk event loop and also happens on close, so the
setting survives even if the debounce never fires.
"""
import tkinter as tk

from app.core import audio
from app.core import video
from app.ui import theme
from app.ui import widgets

_SAVE_DEBOUNCE_MS = 600


class SettingsPanel(tk.Frame):
    """Settings. `on_close`, if given, is called by the Back button -- the
    caller owns what "back" means (raise a screen, destroy a window), and this
    widget deliberately does not guess. `on_video_change`, if given, is called
    after the frame-rate mode flips, so the caller can push it into the live
    GPU map frame immediately."""

    def __init__(self, master, on_close=None, on_video_change=None,
                 title="Settings"):
        super().__init__(master, bg=theme.BG)
        self._on_close = on_close
        self._on_video_change = on_video_change
        self._save_after_id = None
        # Tk fires a Scale's command when you .set() it, including the initial
        # set below -- so without this, merely OPENING the settings panel
        # played a click at you and queued a pointless save. Cleared once the
        # widget tree is up.
        self._building = True

        center = tk.Frame(self, bg=theme.BG)
        center.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(center, text=title, bg=theme.BG, fg=theme.ACCENT,
                 font=theme.FONT_TITLE).pack(pady=(0, 20))

        card = tk.Frame(center, bg=theme.PANEL, relief=theme.BORDER_RELIEF,
                        borderwidth=theme.BORDER_WIDTH,
                        highlightbackground=theme.LINE)
        card.pack(fill="x", ipadx=18, ipady=14)

        tk.Label(card, text="SOUND", bg=theme.PANEL, fg=theme.ACCENT,
                 font=theme.FONT_HEADER, anchor="w").pack(fill="x", padx=16,
                                                          pady=(8, 4))

        if not audio.state()["available"]:
            # Say so plainly rather than showing dead sliders. A machine with
            # no sound device is a normal thing to be, and a panel that
            # pretends otherwise just looks broken.
            tk.Label(card, text="No audio device was found on this machine.\n"
                               "The game runs exactly as it does with sound.",
                     bg=theme.PANEL, fg=theme.MUTED, font=theme.FONT_SMALL,
                     justify="left", anchor="w").pack(fill="x", padx=16,
                                                      pady=(0, 12))
        else:
            state = audio.state()
            self._music = self._slider(card, "Music", state["music"],
                                       self._on_music)
            self._sfx = self._slider(card, "Effects", state["sfx"],
                                     self._on_sfx)

            self._mute_btn = widgets.button(card, "", self._toggle_mute)
            self._mute_btn.pack(fill="x", padx=16, pady=(10, 12))
            self._refresh_mute()

        vcard = tk.Frame(center, bg=theme.PANEL, relief=theme.BORDER_RELIEF,
                         borderwidth=theme.BORDER_WIDTH,
                         highlightbackground=theme.LINE)
        vcard.pack(fill="x", ipadx=18, ipady=14, pady=(14, 0))
        tk.Label(vcard, text="DISPLAY", bg=theme.PANEL, fg=theme.ACCENT,
                 font=theme.FONT_HEADER, anchor="w").pack(fill="x", padx=16,
                                                          pady=(8, 4))
        self._video_btn = widgets.button(vcard, "", self._toggle_video)
        self._video_btn.pack(fill="x", padx=16, pady=(10, 12))
        self._refresh_video()

        widgets.button(center, "Back", self._close, kind="accent"
                       ).pack(fill="x", pady=(18, 0))
        self._building = False
    # --- controls --------------------------------------------------------
    def _slider(self, parent, label, value, command):
        row = tk.Frame(parent, bg=theme.PANEL)
        row.pack(fill="x", padx=16, pady=(6, 0))
        tk.Label(row, text=label, bg=theme.PANEL, fg=theme.INK,
                 font=theme.FONT_BOLD, anchor="w").pack(side="left")
        readout = tk.Label(row, text=f"{round(value * 100)}%", bg=theme.PANEL,
                           fg=theme.MUTED, font=theme.FONT_SMALL, anchor="e")
        readout.pack(side="right")

        scale = tk.Scale(parent, from_=0, to=100, orient="horizontal",
                         showvalue=False, bg=theme.PANEL, fg=theme.INK,
                         troughcolor=theme.METER_TRACK, activebackground=theme.ACCENT,
                         highlightthickness=0, borderwidth=0, sliderrelief="flat",
                         length=280, sliderlength=18,
                         command=lambda v, r=readout, c=command: c(int(v), r))
        scale.set(round(value * 100))
        scale.pack(fill="x", padx=16)
        return scale

    def _on_music(self, percent, readout):
        readout.config(text=f"{percent}%")
        if self._building:
            return
        audio.set_music_volume(percent / 100.0)
        self._queue_save()

    def _on_sfx(self, percent, readout):
        readout.config(text=f"{percent}%")
        if self._building:
            return
        audio.set_sfx_volume(percent / 100.0)
        # Play at the new level as you drag. The only way to judge an effects
        # volume is to hear an effect at it.
        audio.play("click")
        self._queue_save()

    def _toggle_mute(self):
        audio.set_muted(not audio.state()["muted"])
        self._refresh_mute()
        if not audio.state()["muted"]:
            audio.play("click")
        self._queue_save()

    def _refresh_mute(self):
        muted = audio.state()["muted"]
        self._mute_btn.config(text="Sound is OFF — click to unmute" if muted
                              else "Sound is ON — click to mute")

    def _toggle_video(self):
        video.set_uncapped(not video.state()["uncapped"])
        self._refresh_video()
        video.save_settings()
        if self._on_video_change:
            self._on_video_change()

    def _refresh_video(self):
        uncapped = video.state()["uncapped"]
        self._video_btn.config(
            text="Frame rate: Uncapped (up to 200 FPS) — click for smooth"
            if uncapped else
            "Frame rate: Smooth (vsync) — click for uncapped")

    # --- saving ----------------------------------------------------------
    def _queue_save(self):
        """Debounced: a Scale fires per pixel of drag, and writing the file a
        hundred times while somebody moves a knob helps nobody."""
        if self._save_after_id is not None:
            self.after_cancel(self._save_after_id)
        self._save_after_id = self.after(_SAVE_DEBOUNCE_MS, self._save_now)

    def _save_now(self):
        self._save_after_id = None
        audio.save_settings()

    def _close(self):
        # Saved here too, not only on the debounce: closing quickly after a
        # change must not lose it.
        if self._save_after_id is not None:
            self.after_cancel(self._save_after_id)
            self._save_after_id = None
        audio.save_settings()
        if self._on_close:
            self._on_close()
