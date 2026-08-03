"""Music and sound effects.

The game had no audio of any kind before this: no player, no assets, and an
empty `datas` list in the PyInstaller spec. So this is the whole subsystem,
and it is built to two rules that matter more than anything else in here.

**Audio never breaks the game.** A missing file, a machine with no sound
card, a driver that will not initialise, pygame not installed at all -- every
one of those has to end in silence and a game that plays exactly as it did
before. Sound is the least important thing this program does and it is not
allowed to take anything else down with it, so every entry point here is
guarded and `available` is the single flag the rest of the app can ask about.

**The caller names an EVENT, not a file.** `audio.play("build")`, never
`audio.play("assets/audio/sfx/wood_01.ogg")`. Which sound a village founding
makes is a decision that belongs in one table here (see `SFX`), not spread
across every call site, and it means re-skinning the whole game's audio is a
change to this file alone.

Assets are CC0 (public domain, no attribution required) -- see
assets/audio/LICENSES.md for provenance. That was a deliberate choice over
the larger CC-BY libraries: CC-BY obliges a credits screen forever, and it is
not an obligation you can undo once you have shipped.
"""
import json
import time
import os
import random
import sys

# pygame is optional at import time on purpose. It is a real dependency of the
# shipped build, but a dev box, a headless test runner or a stripped install
# must still be able to import the game.
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")   # it greets stdout
try:
    import pygame
    _HAVE_PYGAME = True
except Exception:
    pygame = None
    _HAVE_PYGAME = False


def _asset_root():
    """Where the audio lives, working both from source and from a
    PyInstaller --onefile build (which unpacks to a temp dir and points
    sys._MEIPASS at it)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "assets", "audio")
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(here, "assets", "audio")


# --- what a thing SOUNDS like -----------------------------------------------
# Event name -> one or more sound files, chosen at random per play. Several
# options for the same event is not decoration: a click that plays the
# identical sample forty times in a row stops reading as a click and starts
# reading as a fault, and these packs ship numbered variants precisely so it
# does not have to.
#
# Nothing here fires per frame or per unit. These are events a PLAYER causes
# or a turn produces -- a handful a minute at most.
SFX = {
    # Interface
    "click":        ["item_misc_01.ogg", "item_misc_02.ogg"],
    "panel":        ["book_01.ogg", "book_02.ogg"],
    "menu_open":    ["book_03.ogg", "book_04.ogg"],
    "denied":       ["item_stone_01.ogg"],
    # The turn
    "end_turn":     ["chain_01.ogg", "chain_02.ogg"],
    "coins":        ["item_coins_01.ogg", "item_coins_02.ogg", "item_coins_03.ogg"],
    "alert":        ["item_gem_01.ogg"],
    # Building and settling
    "build_start":  ["wood_01.ogg", "wood_02.ogg"],
    "build_done":   ["item_stone_02.ogg", "item_stone_03.ogg"],
    # War
    "battle_start": ["blade_01.ogg", "blade_02.ogg"],
    "victory":      ["jingle_win_01.mp3"],
    "defeat":       ["jingle_lose_01.mp3"],
    # --- the battle itself ----------------------------------------------
    # The library already held all of this and the game never played a note
    # of it: a battle was one sword-draw at the start and then silence, while
    # eighty files sat in the folder. These are the ones a fight actually
    # needs, and every one of them is throttled (see THROTTLE_MS) because a
    # real battle lands hundreds of blows a second and playing them all is
    # not a sound, it is a wall.
    # Ten real sword attacks and ten real clashes, recorded as such, instead
    # of three generic blade noises doing all the work.
    "sword_hit":    [f"sword_attack_{i:02d}.ogg" for i in range(1, 11)],
    "shield_block": ([f"sword_clash_{i:02d}.ogg" for i in range(1, 11)]
                     + ["metal_01.ogg", "metal_02.ogg", "metal_03.ogg"]),
    "unit_down":    ["creature_die_01.ogg", "creature_hurt_01.ogg",
                     "creature_hurt_02.ogg"],
    "charge_hit":   ["stones_01.ogg", "stones_02.ogg", "stones_03.ogg",
                     "rubble_01.ogg", "rubble_02.ogg", "rubble_03.ogg"],
    "arrow":        ["item_wood_01.ogg", "item_wood_02.ogg"],
    "bomb":         ["spell_fire_01.ogg", "spell_fire_02.ogg",
                     "spell_fire_03.ogg"],
    "commander_falls": ["creature_roar_01.ogg", "creature_roar_02.ogg"],
    # --- interface ------------------------------------------------------
    "order":        ["lock_01.ogg", "lock_02.ogg", "mechanism_01.ogg"],
    "march":        ["step_01.ogg", "step_02.ogg", "step_wood_01.ogg",
                     "step_wood_02.ogg"],
    "select":       ["menu_select_01.mp3"],
    # Voices. Who is fighting changes what a battle sounds like at the moment
    # it begins -- goblins jabber, a wildland garrison is something worse.
    "goblin_voice": [f"goblin_{i:02d}.mp3" for i in range(1, 6)],
    "beast_roar":   ["dragon_01.mp3", "dragon_02.mp3"],
    # Building and breaking
    "hammer":       ["hammer_01.ogg", "hammer_02.ogg"],
    "gate":         ["gate_01.ogg", "door_01.ogg", "door_02.ogg"],
    "breaking":     ["wood_break_01.ogg", "wood_break_02.ogg"],
}

# The least time between two plays of the SAME event, in milliseconds. A
# battle lands hundreds of blows a second across hundreds of soldiers; without
# this, "a sword hit makes a sound" turns the mixer into a solid tone and eats
# every channel the game has. With it, a melee reads as a rolling clash --
# which is what a battle sounds like from where the player is standing anyway.
#
# Zero means unthrottled: a deliberate choice per event, not an oversight. The
# things the PLAYER does are all zero, because feedback that gets dropped is
# worse than no feedback at all.
THROTTLE_MS = {
    "sword_hit": 90,
    "shield_block": 130,
    "unit_down": 160,
    "charge_hit": 200,
    "arrow": 110,
    "bomb": 240,
    "commander_falls": 1500,
}

MUSIC = {
    "map": "town_theme.mp3",
    "battle": "battle_theme.mp3",
}

# Ambience loops, played on the music channel because that is what they are:
# a bed, not an event. The underworld gets one, and it is most of what makes
# descending feel like going somewhere rather than switching a view.
AMBIENCE = {
    "underworld": "cave_ambience_01.mp3",
}

DEFAULT_MUSIC_VOLUME = 0.35   # music sits UNDER everything; it is background
DEFAULT_SFX_VOLUME = 0.65
_CHANNELS = 16                # simultaneous effects before the oldest is cut


class _Audio:
    """Deliberately one instance (see the module-level functions at the
    bottom). Two mixers fighting over one sound device is a class of bug with
    no upside, and the game has exactly one pair of ears."""

    def __init__(self):
        self.available = False
        self.music_volume = DEFAULT_MUSIC_VOLUME
        self.sfx_volume = DEFAULT_SFX_VOLUME
        self.muted = False
        self._sounds = {}          # filename -> Sound, loaded lazily
        self._missing = set()      # complained about once, then left alone
        self._current_music = None
        self._last_played = {}     # event -> when it last sounded (see play)
        self._root = _asset_root()

    def init(self):
        """Bring the mixer up. Safe to call twice; safe to call on a machine
        with no audio device at all, which is the case that actually happens
        (a CI box, a remote session, a VM)."""
        if self.available or not _HAVE_PYGAME:
            return self.available
        try:
            # A small buffer keeps a UI click feeling like it belongs to the
            # click. The default is tuned for a game loop that submits audio
            # every frame; this app submits a sound when the player does
            # something, and a big buffer just adds latency to it.
            pygame.mixer.pre_init(frequency=44100, size=-16, channels=2,
                                  buffer=512)
            pygame.mixer.init()
            pygame.mixer.set_num_channels(_CHANNELS)
            self.available = True
        except Exception:
            self.available = False   # no device, no driver, no sound. Fine.
        return self.available

    def shutdown(self):
        if not self.available:
            return
        try:
            pygame.mixer.music.stop()
            pygame.mixer.quit()
        except Exception:
            pass
        self.available = False

    # --- effects ---------------------------------------------------------
    def _sound(self, filename):
        if filename in self._sounds:
            return self._sounds[filename]
        if filename in self._missing:
            return None
        path = os.path.join(self._root, "sfx", filename)
        try:
            sound = pygame.mixer.Sound(path)
        except Exception:
            self._missing.add(filename)
            return None
        self._sounds[filename] = sound
        return sound

    def play(self, event, volume=1.0):
        """Play the sound for `event` (a key of SFX). Unknown events are
        silently ignored rather than raising -- a typo in a call site should
        cost a sound, not a turn.

        Throttled per event (see THROTTLE_MS): the battle events fire from a
        simulation that resolves hundreds of blows a second, and the honest
        way to say "a sword hit makes a sound" is to let one through every so
        often rather than to try to play them all."""
        if not self.available or self.muted:
            return
        options = SFX.get(event)
        if not options:
            return
        gap = THROTTLE_MS.get(event, 0)
        if gap:
            now = time.monotonic() * 1000.0
            if now - self._last_played.get(event, -1e9) < gap:
                return
            self._last_played[event] = now
        sound = self._sound(random.choice(options))
        if sound is None:
            return
        try:
            sound.set_volume(max(0.0, min(1.0, self.sfx_volume * volume)))
            sound.play()
        except Exception:
            pass

    def play_ambience(self, key, loop=True):
        """Play an AMBIENCE loop in place of the music.

        Same channel as the music on purpose: a cave ambience and a town theme
        are competing for the same ears, and layering them turns "you are
        underground" into "you are underground at a fair"."""
        if not self.available:
            return
        if key == self._current_music:
            return
        name = AMBIENCE.get(key)
        if not name:
            return
        # Ambience lives in sfx/ because that is where it was shipped; the
        # music CHANNEL is what plays it, which is the part that matters.
        path = os.path.join(self._root, "sfx", name)
        if not os.path.exists(path):
            return
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.set_volume(0.0 if self.muted else self.music_volume)
            pygame.mixer.music.play(-1 if loop else 0)
            self._current_music = key
        except Exception:
            self._current_music = None

    # --- music -----------------------------------------------------------
    def play_music(self, track, loop=True):
        """Start `track` (a key of MUSIC), looping by default. Asking for the
        track that is already playing does nothing -- otherwise every screen
        change would restart the music from the top."""
        if not self.available:
            return
        if track == self._current_music:
            return
        name = MUSIC.get(track)
        if not name:
            return
        path = os.path.join(self._root, "music", name)
        if not os.path.exists(path):
            return
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.set_volume(0.0 if self.muted else self.music_volume)
            pygame.mixer.music.play(-1 if loop else 0)
            self._current_music = track
        except Exception:
            self._current_music = None

    def stop_music(self, fade_ms=600):
        if not self.available:
            return
        try:
            pygame.mixer.music.fadeout(fade_ms)
        except Exception:
            pass
        self._current_music = None

    # --- settings --------------------------------------------------------
    def set_music_volume(self, value):
        self.music_volume = max(0.0, min(1.0, value))
        if self.available and not self.muted:
            try:
                pygame.mixer.music.set_volume(self.music_volume)
            except Exception:
                pass

    def set_sfx_volume(self, value):
        self.sfx_volume = max(0.0, min(1.0, value))

    def set_muted(self, muted):
        """Mute silences music AND effects, but does not stop the music --
        unmuting picks it up where it got to, rather than restarting a track
        the player has been listening to."""
        self.muted = bool(muted)
        if self.available:
            try:
                pygame.mixer.music.set_volume(0.0 if self.muted
                                              else self.music_volume)
            except Exception:
                pass


    # --- persistence -----------------------------------------------------
    # Next to saves/, not next to __file__: a --onefile exe unpacks into a
    # throwaway temp dir every launch, so anything written relative to the
    # module vanishes when the game closes. Same reasoning (and the same
    # helper) as save.py and the changelog's seen-file.
    def _settings_path(self):
        from app.core.save import _app_root
        return _app_root() / "audio_settings.json"

    def load_settings(self):
        """Read volumes and mute back. A corrupt or missing file means the
        defaults, never an error -- losing your volume setting is a shrug,
        failing to start the game over it is not."""
        try:
            data = json.loads(self._settings_path().read_text(encoding="utf-8"))
        except Exception:
            return
        try:
            self.set_music_volume(float(data.get("music", self.music_volume)))
            self.set_sfx_volume(float(data.get("sfx", self.sfx_volume)))
            self.set_muted(bool(data.get("muted", self.muted)))
        except Exception:
            pass

    def save_settings(self):
        try:
            self._settings_path().write_text(json.dumps(
                {"music": round(self.music_volume, 3),
                 "sfx": round(self.sfx_volume, 3),
                 "muted": self.muted}), encoding="utf-8")
        except Exception:
            pass   # read-only install, no disk, no permission: not our problem


_audio = _Audio()

# The module-level API the rest of the game uses. Free functions rather than
# an exported object, so a call site never has to know whether audio exists.
init = _audio.init
shutdown = _audio.shutdown
play = _audio.play
play_music = _audio.play_music
play_ambience = _audio.play_ambience
stop_music = _audio.stop_music
set_music_volume = _audio.set_music_volume
set_sfx_volume = _audio.set_sfx_volume
set_muted = _audio.set_muted
load_settings = _audio.load_settings
save_settings = _audio.save_settings


def state():
    """Everything worth saving or showing in a settings panel."""
    return {"available": _audio.available, "muted": _audio.muted,
            "music": _audio.music_volume, "sfx": _audio.sfx_volume,
            "track": _audio._current_music}
