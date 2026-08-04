"""Video settings: frame-rate mode.

Audio owns its own settings file, and video owns its. One knob today: whether
the GPU map's buffer swap is vsync-paced or uncapped.

  smooth (default)  wglSwapIntervalEXT(1): SwapBuffers blocks until the
                    display's vertical blank, so the visible rate is exactly
                    the monitor's refresh, with no tearing. The frame loop's
                    adaptive scheduler then paces to that rate on its own.
  uncapped          wglSwapIntervalEXT(0): the loop renders as fast as its
                    frame target allows (up to 200Hz) and the display shows
                    whatever it can -- genuinely smoother only on a display
                    whose refresh is that fast, and it can tear otherwise.

Same persistence pattern as audio: a small JSON next to saves/ (see
app.core.save._app_root), and a corrupt or missing file means the defaults,
never an error -- losing a setting is a shrug, failing to start over it is not.
"""
import json

from app.core.save import _app_root


class _Video:
    def __init__(self):
        self.uncapped = False   # vsync on by default: no tearing

    def _settings_path(self):
        return _app_root() / "video_settings.json"

    def set_uncapped(self, value):
        self.uncapped = bool(value)

    def load_settings(self):
        """Read the mode back. A corrupt or missing file means the default."""
        try:
            data = json.loads(self._settings_path().read_text(encoding="utf-8"))
        except Exception:
            return
        try:
            self.uncapped = bool(data.get("uncapped", self.uncapped))
        except Exception:
            pass

    def save_settings(self):
        try:
            self._settings_path().write_text(
                json.dumps({"uncapped": self.uncapped}), encoding="utf-8")
        except Exception:
            pass   # read-only install, no disk, no permission: not our problem


_video = _Video()

# The module-level API, same shape as audio's: call sites never touch _video.
set_uncapped = _video.set_uncapped
load_settings = _video.load_settings
save_settings = _video.save_settings


def state():
    return {"uncapped": _video.uncapped}
