"""Screen stacking: the game starts on the menu, and every screen can be left.

    python dev/test_screens.py

Written after a one-word bug shipped in v0.12.0 and survived a whole release
cycle: the Credits view was parented to the App instead of to the content
frame every other screen lives in. That put it in a different stacking
context -- a sibling of `content`, created after it -- so it covered the whole
window permanently. The game booted into the credits screen and its Back
button did nothing, because show_screen() raises a view INSIDE content and
nothing inside content can rise above a sibling stacked over it.

Nothing in the suite could have caught it, because nothing in the suite built
the App. What is asserted here is deliberately structural rather than visual:

  * every screen shares one parent, so tkraise() can order all of them;
  * a fresh App is showing the MENU;
  * and every screen that can be opened can also be left, back to the menu.

A visual check would have caught it too -- and did, eventually, on a launch
before publishing -- but a structural one runs in the suite.
"""
import os
import sys
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    probe = tk.Tk()
    probe.destroy()
except tk.TclError as exc:
    print(f"no display available ({exc}) -- skipping")
    sys.exit(0)

from app.ui.app import App

app = App()
app.withdraw()          # never flash a real window during a test run

try:
    print("--- every screen lives in the same stacking context ---")
    screens = {
        "menu": app.menu_view,
        "new_game": app.new_game_view,
        "load_game": app.load_game_view,
        "pause": app.pause_view,
        "game_over": app.game_over_view,
        "settings": app.settings_view,
        "credits": app.credits_view,
    }
    parents = {name: str(view.master) for name, view in screens.items()}
    distinct = set(parents.values())
    assert len(distinct) == 1, (
        "screens are parented to different widgets, so raising one cannot "
        f"order it against the others: {parents}")
    assert str(app.content) in distinct, (
        f"screens are not children of the content frame: {distinct}")
    print(f"  ok    {len(screens)} screens, all children of {list(distinct)[0]}")

    print("\n--- a fresh app is showing the menu, not something else ---")
    app.update_idletasks()
    assert app._current_screen == "menu", app._current_screen
    # The real test of "showing": nothing else is stacked above it. Tk lists
    # a parent's children in stacking order, lowest first.
    order = app.content.winfo_children()
    above = order[order.index(app.menu_view) + 1:]
    for view in above:
        assert not view.winfo_ismapped() or view is app.menu_view, (
            f"{view} is stacked above the menu on a fresh launch -- this is "
            "exactly the credits bug")
    print("  ok    the menu is on top on a fresh launch")

    print("\n--- everything that opens can be closed again ---")
    app._open_credits()
    assert app._current_screen == "credits"
    app._close_credits()
    assert app._current_screen == "menu", (
        f"Back from the credits left the app on {app._current_screen!r} -- "
        "the screen cannot be left")
    print("  ok    credits opens and closes")

    app._open_settings()
    assert app._current_screen == "settings"
    app._close_settings()
    assert app._current_screen == "menu"
    print("  ok    settings opens and closes")

    # ...and the two of them in sequence, which is the path that has its own
    # special case in _close_credits (credits opened FROM settings).
    app._open_settings()
    app._open_credits()
    app._close_credits()
    assert app._current_screen == "settings", app._current_screen
    app._close_settings()
    assert app._current_screen == "menu"
    print("  ok    credits opened from settings goes back to settings")
finally:
    try:
        app.destroy()
    except tk.TclError:
        pass

print("\nSCREENS TEST PASSED")
