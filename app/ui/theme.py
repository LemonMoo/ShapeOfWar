"""Shared color palette and helpers for a simple dark theme."""
from app.world.world_map import Stance

BG = "#12151c"        # window background
PANEL = "#1b2029"     # side panels / top bar
CANVAS = "#0d1017"    # canvas background
INK = "#e7ecf3"       # primary text
MUTED = "#8a94a6"     # secondary text
ACCENT = "#4da3ff"
LINE = "#2a3140"
GOOD = "#59c17a"
BAD = "#e2604a"

FONT = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_TITLE = ("Segoe UI", 14, "bold")

# Colors for relationship links / labels, keyed by stance.
STANCE_COLOR = {
    Stance.ALLY: "#59c17a",
    Stance.ENEMY: "#e2604a",
    Stance.NEUTRAL: "#4a5265",
}
