"""Shared color palette and helpers for a fantasy/medieval theme."""
from app.world.world_map import Stance

BG = "#1a140f"          # window background -- aged wood
PANEL = "#2a2018"       # side panels / top bar -- parchment-on-leather
PANEL_ALT = "#332619"   # card headers / button faces -- slightly lighter
CANVAS = "#100c08"      # map/battle canvas background
INK = "#ece0c8"         # primary text -- warm parchment-white
MUTED = "#a89778"       # secondary text -- faded ink
ACCENT = "#c9a24b"      # muted gold -- highlights, primary actions
ACCENT_INK = "#241a0a"  # text drawn on an ACCENT background
LINE = "#4a3a26"        # borders / rules
GOOD = "#6fae5a"
WARN = "#d1922f"
BAD = "#b8483a"
METER_TRACK = "#170f09"  # empty-meter background
ALERT_BG = "#241009"     # distinct danger tint for the alerts panel
ALERT_BG_HOVER = "#341412"

# Fonts: a serif display face for titles/headers only (built into Windows
# since Vista, so no bundling risk); body text stays sans-serif since a
# serif reads worse at small sizes and the goal includes bigger, clearer
# text, not fussier text.
FONT_FAMILY_HEAD = "Cambria"
FONT_FAMILY_BODY = "Segoe UI"

FONT_TITLE = (FONT_FAMILY_HEAD, 18, "bold")
FONT_HEADER = (FONT_FAMILY_HEAD, 12, "bold")
FONT_BOLD = (FONT_FAMILY_BODY, 11, "bold")
FONT = (FONT_FAMILY_BODY, 11)
FONT_SMALL = (FONT_FAMILY_BODY, 9)
FONT_SMALL_BOLD = (FONT_FAMILY_BODY, 9, "bold")
FONT_LOG = ("Consolas", 9)

# Sizing -- bigger click targets than Tk's default padding.
BTN_PAD_Y = 10
ROW_PAD_Y = 6
CARD_HEAD_PAD_Y = (14, 6)

# Borders -- what's actually achievable on plain Tk widgets (no rounded
# corners, gradients, or bitmap textures without a full custom-widget
# rewrite): a carved-frame look via relief + a border-colored highlight.
BORDER_RELIEF = "ridge"
BORDER_WIDTH = 2

# Battle order-stance cues (battle_view.py's _ORDER_CUE) -- a separate visual
# vocabulary from GOOD/WARN/BAD: these tag WHICH stance a unit carries, not
# whether something is going well, so they stay their own palette rather
# than being forced to double up on the status colors above.
ORDER_CUE_HOLD = "#7fd6ff"
ORDER_CUE_CHARGE = "#ff9b57"
ORDER_CUE_SHIELD_WALL = "#9fe0a8"
ORDER_CUE_CYCLE_CHARGE = "#ffd166"

# Colors for relationship links / labels, keyed by stance.
STANCE_COLOR = {
    Stance.ALLY: GOOD,
    Stance.ENEMY: BAD,
    Stance.NEUTRAL: "#6b5a3d",
}
