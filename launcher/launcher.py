"""ShapesOfWarLauncher: a small, standalone Tkinter app players run instead
of the game directly. On open it checks GitHub for a newer release of
ShapesOfWar.exe, downloads it if one exists, and a Play button launches
whatever's currently installed next to the launcher.

Deliberately independent of the `app` package (the actual game code) --
no imports from it, no shared dependencies (Pillow, etc.) -- so this stays
a tiny, simple build with nothing to do with game logic. See
app/core/save.py's _app_root() for the pattern this file's own _app_root()
copies (a PyInstaller --onefile exe unpacks into a throwaway temp dir every
launch; sys.executable, not __file__, is the actual persistent .exe path
once frozen).
"""
import json
import os
import subprocess
import sys
import threading
import tkinter as tk
import urllib.error
import urllib.request
from pathlib import Path

GITHUB_REPO = "LemonMoo/ShapeOfWar"
RELEASE_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GAME_EXE_NAME = "ShapesOfWar.exe"
REQUEST_TIMEOUT = 10   # seconds -- a hung connection shouldn't freeze the launcher indefinitely

# Colors mirror app/ui/theme.py's palette (not imported -- see module
# docstring on why this file stays decoupled from the game package).
_BG = "#12151c"
_INK = "#e7ecf3"
_MUTED = "#8a94a6"
_ACCENT = "#4da3ff"
_GOOD = "#59c17a"
_BAD = "#e2604a"


def _app_root():
    """Where the launcher's own persistent files live -- see this module's
    docstring. Same reasoning as save.py's _app_root(), just for the
    launcher's own frozen exe rather than the game's."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


APP_ROOT = _app_root()
GAME_EXE_PATH = APP_ROOT / GAME_EXE_NAME
VERSION_MARKER_PATH = APP_ROOT / "game_version.txt"
DOWNLOAD_TMP_PATH = APP_ROOT / f"{GAME_EXE_NAME}.download"


def _read_installed_version():
    try:
        return VERSION_MARKER_PATH.read_text().strip()
    except OSError:
        return None


def _write_installed_version(tag):
    VERSION_MARKER_PATH.write_text(tag)


def check_latest_release():
    """(tag, download_url) for the latest GitHub release's ShapesOfWar.exe
    asset, or None on any network/parse failure -- the repo is public (see
    the plan this was built from), so this is a plain unauthenticated GET,
    no token needed and nothing to leak if this exe is shared around."""
    req = urllib.request.Request(
        RELEASE_API_URL, headers={"Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None
    tag = data.get("tag_name")
    if not tag:
        return None
    for asset in data.get("assets", []):
        if asset.get("name") == GAME_EXE_NAME:
            url = asset.get("browser_download_url")
            if url:
                return tag, url
    return None   # release exists but has no matching asset -- treat as unavailable


def download_and_replace(url, on_progress=None):
    """Stream `url` to a staging file, then atomically swap it in as the
    live game exe. The live exe is never touched until the download is
    100% complete -- os.replace only runs after the full byte count has
    landed on disk, so a failed/interrupted download (network drop, the
    player closing the launcher) can never leave a half-written or missing
    game exe behind; whatever was there before stays exactly as it was.
    Raises on any failure -- caller (the UI thread) decides how to react."""
    req = urllib.request.Request(url, headers={"Accept": "application/octet-stream"})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        with open(DOWNLOAD_TMP_PATH, "wb") as f:
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if on_progress is not None:
                    on_progress(done, total)
    os.replace(DOWNLOAD_TMP_PATH, GAME_EXE_PATH)


class LauncherApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Shapes of War Launcher")
        self.geometry("420x220")
        self.resizable(False, False)
        self.configure(bg=_BG)

        tk.Label(self, text="Shapes of War", bg=_BG, fg=_INK,
                 font=("Segoe UI", 20, "bold")).pack(pady=(28, 6))

        self.status_lbl = tk.Label(self, text="Checking for updates…", bg=_BG,
                                   fg=_MUTED, font=("Segoe UI", 10))
        self.status_lbl.pack(pady=(0, 14))

        self.play_btn = tk.Button(self, text="Play", command=self._on_play,
                                  width=18, state="disabled",
                                  bg="#232a36", fg=_INK, activebackground=_ACCENT,
                                  relief="flat", font=("Segoe UI", 11, "bold"), pady=8)
        self.play_btn.pack(pady=6)

        self.after(100, self._start_update_check)

    def _set_status(self, text, color=None):
        self.status_lbl.config(text=text, fg=color or _MUTED)

    def _enable_play(self):
        self.play_btn.config(state="normal")

    def _start_update_check(self):
        threading.Thread(target=self._update_check_worker, daemon=True).start()

    def _update_check_worker(self):
        """Runs off the main thread (network I/O shouldn't freeze the UI);
        every call back into Tkinter is scheduled via self.after so widget
        access always happens on the main thread, the standard pattern for
        mixing a worker thread with Tkinter."""
        result = check_latest_release()
        if result is None:
            self.after(0, self._on_check_failed)
            return
        latest_tag, download_url = result
        installed_tag = _read_installed_version()
        if installed_tag == latest_tag and GAME_EXE_PATH.exists():
            self.after(0, lambda: self._on_up_to_date(latest_tag))
            return
        self.after(0, lambda: self._set_status(f"Downloading update {latest_tag}…"))
        try:
            download_and_replace(download_url, on_progress=self._on_progress)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            self.after(0, lambda: self._on_download_failed(e))
            return
        _write_installed_version(latest_tag)
        self.after(0, lambda: self._on_updated(latest_tag))

    def _on_progress(self, done, total):
        if total > 0:
            pct = int(done * 100 / total)
            self.after(0, lambda: self._set_status(f"Downloading update… {pct}%"))

    def _on_up_to_date(self, tag):
        self._set_status(f"Up to date ({tag}).", _GOOD)
        self._enable_play()

    def _on_updated(self, tag):
        self._set_status(f"Updated to {tag}. Ready to play.", _GOOD)
        self._enable_play()

    def _on_check_failed(self):
        if GAME_EXE_PATH.exists():
            self._set_status("Couldn't check for updates — playing installed version.", _MUTED)
            self._enable_play()
        else:
            self._set_status("No internet connection — first install needs one.", _BAD)

    def _on_download_failed(self, error):
        if GAME_EXE_PATH.exists():
            self._set_status("Update download failed — playing installed version.", _BAD)
            self._enable_play()
        else:
            self._set_status(f"Update download failed: {error}", _BAD)

    def _on_play(self):
        if not GAME_EXE_PATH.exists():
            self._set_status("Game not found — update failed or hasn't run yet.", _BAD)
            return
        subprocess.Popen([str(GAME_EXE_PATH)], cwd=str(APP_ROOT))
        self.destroy()


def main():
    LauncherApp().mainloop()


if __name__ == "__main__":
    main()
