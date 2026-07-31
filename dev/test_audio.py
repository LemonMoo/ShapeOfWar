"""Music and sound effects.

    python dev/test_audio.py

The game had no audio at all before this, so almost everything here is about
one property rather than about sound: **audio must never break the game.**
Sound is the least important thing this program does. A machine with no
device, a driver that will not start, a missing file, a typo in a call site,
pygame not installed -- every one of those has to end in silence and a game
that plays exactly as it did before.

So most of this file deliberately runs the module in states a working machine
never reaches, because those are the states a player's machine reaches.
"""
import sys
import os
import importlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import audio

print("--- every event names files that actually exist ---")
# The whole point of the event table is that call sites never name a file. If
# a name in it is wrong, the sound silently never plays and nobody notices.
root = audio._asset_root()
missing = []
for event, options in audio.SFX.items():
    assert options, f"{event} has no sounds at all"
    for name in options:
        if not os.path.exists(os.path.join(root, "sfx", name)):
            missing.append((event, name))
assert not missing, f"events point at files that do not exist: {missing}"
total = sum(len(v) for v in audio.SFX.values())
print(f"  ok    {len(audio.SFX)} events, {total} files, all present")

for track, name in audio.MUSIC.items():
    assert os.path.exists(os.path.join(root, "music", name)), (track, name)
print(f"  ok    {len(audio.MUSIC)} music tracks present")

print("\n--- an event with one sample repeated is a fault you can hear ---")
# A click that plays the identical sample forty times running stops reading
# as a click. The packs ship numbered variants precisely so it does not have
# to, so the events a player triggers constantly should use them.
for event in ("click", "end_turn", "coins"):
    assert len(audio.SFX[event]) > 1, (
        f"{event} fires often and has only one sample -- it will start "
        f"sounding like a stuck record")
print("  ok    the frequently-fired events all have variants")

print("\n--- CRITICAL: none of it raises, ever ---")
# Called before init(), which is the state a headless run is permanently in.
audio.play("click")
audio.play_music("map")
audio.stop_music()
audio.set_muted(True)
audio.set_music_volume(0.5)
audio.set_sfx_volume(0.5)
audio.set_muted(False)
print("  ok    every entry point is safe before init()")

audio.play("no-such-event")
audio.play_music("no-such-track")
print("  ok    an unknown event or track is ignored, not raised")

print("\n--- ...including with no sound device at all ---")
# The case that actually happens: a CI box, a remote session, a VM. Faked by
# making the mixer refuse to start, which is exactly what those machines do.
real_pygame = audio.pygame
real_have = audio._HAVE_PYGAME


class _DeadMixer:
    class mixer:
        @staticmethod
        def pre_init(**kwargs):
            raise RuntimeError("no audio device")

        @staticmethod
        def init():
            raise RuntimeError("no audio device")


try:
    audio._audio.available = False
    audio.pygame = _DeadMixer
    assert audio.init() is False, "init() claimed success with no device"
    audio.play("click")
    audio.play_music("map")
    audio.set_muted(True)
    audio.shutdown()
    print("  ok    a machine with no device gets silence, not an exception")
finally:
    audio.pygame = real_pygame
    audio._audio.available = False

print("\n--- ...and with pygame not installed ---")
try:
    audio._HAVE_PYGAME = False
    audio._audio.available = False
    assert audio.init() is False
    audio.play("click")
    print("  ok    no pygame, no sound, no crash")
finally:
    audio._HAVE_PYGAME = real_have

print("\n--- a missing file is remembered, not retried forever ---")
audio._audio._missing.clear()
audio._audio.available = True     # pretend, so _sound() is reached
try:
    audio._audio._sound("definitely_not_here.ogg")
    assert "definitely_not_here.ogg" in audio._audio._missing, (
        "a missing file will be re-opened from disk on every single play")
    print("  ok    a missing file is recorded once and skipped after that")
finally:
    audio._audio.available = False
    audio._audio._missing.clear()

print("\n--- the real mixer, if this machine has one ---")
if audio.init():
    for event in audio.SFX:
        audio.play(event)
    audio.play_music("map")
    assert audio.state()["track"] == "map"
    audio.play_music("map")           # idempotent: must not restart
    assert audio.state()["track"] == "map"
    audio.play_music("battle")
    assert audio.state()["track"] == "battle", (
        "asking for a different track did not switch")
    audio.set_muted(True)
    audio.play("click")               # muted: silent, still must not raise
    audio.set_muted(False)
    audio.stop_music(0)
    assert audio.state()["track"] is None
    audio.shutdown()
    assert audio.state()["available"] is False
    print(f"  ok    played all {len(audio.SFX)} events, switched music, "
          f"muted and shut down cleanly")
else:
    print("  skip  no audio device on this machine (which is itself fine)")

print("\n--- the assets are accounted for ---")
licences = os.path.join(root, "LICENSES.md")
assert os.path.exists(licences), (
    "no LICENSES.md -- shipped audio with no record of where it came from")
text = open(licences, encoding="utf-8").read()
assert "CC0" in text
for word in ("rubberduck", "cynicmusic", "opengameart.org"):
    assert word in text, f"{word} is not credited in the licence record"
print("  ok    LICENSES.md names every source, and all of it is CC0")

print("\n--- callers name events, never files ---")
# If a file path ever appears at a call site, swapping a sound stops being a
# one-line change to the table in audio.py.
import glob
offenders = []
for path in glob.glob("app/**/*.py", recursive=True):
    if path.replace("\\", "/").endswith("app/core/audio.py"):
        continue
    for n, line in enumerate(open(path, encoding="utf-8"), 1):
        if "audio.play" in line and (".ogg" in line or ".mp3" in line):
            offenders.append(f"{path}:{n}")
assert not offenders, f"call sites naming audio files directly: {offenders}"
print("  ok    no call site names a sound file")

print("\nAUDIO TEST PASSED")
