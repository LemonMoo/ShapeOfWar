"""Global keyboard shortcuts, against a real Tk widget tree.

    python dev/test_keys.py

E (run a day), Space (stop the clock) and V (cycle view mode) are bound
application-wide, not with `bind` on the App root.
A root bind only fires while focus is somewhere inside the root's OWN widget
tree, and this game has real child Toplevels -- the Compendium and the Build
Menu, the latter of which takes focus for itself because it has no OS titlebar.
Open either and E silently stopped ending turns; click back on the map and it
started again. That is the "works inconsistently" this guards.

Asserted on the binding wiring rather than by driving real keystrokes: which
widget has focus depends on a window manager actually being there, which a
headless harness cannot promise, but WHERE the binding lives is exactly the
thing that was wrong and it is directly inspectable.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk

from app.ui.app import App

# Built straight off, with no throwaway probe root first: creating and
# destroying a second Tk makes ttk fire a ThemeChanged at the dead one and spew
# a Tcl traceback on stderr, which reads like a failure and is not one.
try:
    app = App()
except tk.TclError as exc:
    print(f"no display available ({exc}) -- skipping")
    sys.exit(0)
app.withdraw()

print("--- the shortcuts are bound application-wide, not just on the root ---")
# bind_all installs on the "all" bindtag, which every widget in every toplevel
# carries. bind installs on the root's own path, which a child Toplevel does
# not have in its bindtags at all.
try:
    for seq in ("<e>", "<E>", "<v>", "<V>", "<space>"):
        on_all = app.bind_all(seq)
        on_root = app.bind(seq)
        assert on_all, (
            f"{seq} is not bound application-wide, so it cannot fire while the "
            f"Compendium or the Build Menu has focus")
        assert not on_root, (
            f"{seq} is bound BOTH on the root and application-wide, so it will "
            f"fire twice for every press")
    print("  ok    e/E/v/V/space are bind_all, and not double-bound on the root")

    print("\n--- a letter typed into a text field is not a shortcut ---")
    calls = []
    app.map_view = type("Stub", (), {"skip_a_day": lambda s: calls.append("day"),
                                     "_toggle_pause": lambda s: calls.append("pause"),
                                     "_toggle_mode": lambda s: calls.append("mode")})()
    app._current_screen = "map"
    app._paused = False

    entry = tk.Entry(app)
    entry.pack()
    app.update_idletasks()

    class Ev:
        pass

    typing = Ev()
    typing.widget = entry
    app._on_skip_day_key(typing)
    app._on_time_key(typing)
    assert not calls, "typing in an Entry drove the world clock"
    assert app._is_typing(typing)
    print(f"  ok    Entry ({entry.winfo_class()}) is treated as typing")

    # Every text-ish class the game could put on screen.
    for cls in ("Entry", "TEntry", "Text", "Spinbox", "TSpinbox", "TCombobox"):
        assert cls in App._TEXT_ENTRY_CLASSES, cls
    print(f"  ok    {len(App._TEXT_ENTRY_CLASSES)} text classes guarded")

    print("\n--- but on the map they drive the world ---")
    on_map = Ev()
    on_map.widget = app
    app._on_skip_day_key(on_map)
    assert calls == ["day"], calls
    app._on_time_key(on_map)
    assert calls == ["day", "pause"], calls
    app._on_toggle_mode_key(on_map)
    assert calls == ["day", "pause", "mode"], calls
    print("  ok    E runs a day, Space stops the clock, V cycles the mode")

    print("\n--- and not while paused or off the map ---")
    calls.clear()
    app._paused = True
    app._on_skip_day_key(on_map)
    app._on_time_key(on_map)
    app._paused = False
    app._current_screen = "menu"
    app._on_skip_day_key(on_map)
    app._on_time_key(on_map)
    assert not calls, f"a time key fired while paused or on a menu: {calls}"
    print("  ok    inert while paused, and on other screens")

    print("\n--- a widget that has been destroyed is not a crash ---")
    dead = Ev()
    dead.widget = entry
    entry.destroy()
    app._current_screen = "map"
    app._is_typing(dead)          # must not raise
    print("  ok    _is_typing survives a destroyed widget")
finally:
    try:
        app.destroy()
    except tk.TclError:
        pass

print("\nKEYS TEST PASSED")
