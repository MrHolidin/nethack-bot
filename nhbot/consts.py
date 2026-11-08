"""Board geometry, movement keys, hunger states and named map glyphs."""
import re

import nle.nethack as nh


ROWS, COLS = 21, 79

DIRS = {  # key: (dy, dx)
    "k": (-1, 0), "j": (1, 0), "h": (0, -1), "l": (0, 1),
    "y": (-1, -1), "u": (-1, 1), "b": (1, -1), "n": (1, 1),
}

DELTA2KEY = {v: k for k, v in DIRS.items()}

NEIGH = list(DIRS.values())

def in_bounds(y, x):
    return 0 <= y < ROWS and 0 <= x < COLS


def in_line(dy, dx):
    """The offset (dy, dx) lies on a row, a column or a diagonal: what a missile, ray or monster's shot follows."""
    return dy == 0 or dx == 0 or abs(dy) == abs(dx)


def ray_squares(y, x, dy, dx, n=9):
    """The squares a missile thrown from (y, x) in direction (dy, dx) can land on (up to n away)."""
    return [(y + i * dy, x + i * dx) for i in range(1, n + 1) if in_bounds(y + i * dy, x + i * dx)]


# hunger states
SATIATED, NOT_HUNGRY, HUNGRY, WEAK, FAINTING = 0, 1, 2, 3, 4

# squares the bot never engraves on (elbereth.can_engrave_here; cmap S_ indices): only what doengrave really refuses
# (engrave.c:521-533: lava, pool / water, fountain, the Planes of Air / Water -- S_air, S_cloud, S_water) or wastes
# (engrave.c:574-583: an altar angers its god, a finger only smudges a grave); stairs, ladders, a throne and a sink
# are written on (and onscary, monmove.c:175, has no terrain test) (A/B engrave_more: +85 [-495, +657])
NO_ENGRAVE_CMAP = {27, 28, 31, 32, 34, 39, 40, 41}

# cmap glyphs (display.h / drawing.c S_ indices)
STONE_GLYPH = nh.GLYPH_CMAP_OFF + 0
FLOOR_GLYPH = nh.GLYPH_CMAP_OFF + 19     # S_room
CORRIDOR_GLYPHS = (nh.GLYPH_CMAP_OFF + 21, nh.GLYPH_CMAP_OFF + 22)    # S_corr, S_litcorr
UPSTAIR_GLYPH = nh.GLYPH_CMAP_OFF + 23
DOWNSTAIR_GLYPH = nh.GLYPH_CMAP_OFF + 24
ALTAR_GLYPH = nh.GLYPH_CMAP_OFF + 27
FOUNTAIN_GLYPH = nh.GLYPH_CMAP_OFF + 31
# feature_here: invent.c look_here "There is <dfeature> here." (dfeature_at: defsyms' explanations) -> its cmap glyph
FEATURE_HERE_RE = re.compile(r"There is an? (staircase down|staircase up|ladder down|ladder up|fountain|sink|"
                             r"opulent throne|grave|altar)\b[^.]* here\.")
FEATURE_GLYPH = {"staircase up": nh.GLYPH_CMAP_OFF + 23, "staircase down": nh.GLYPH_CMAP_OFF + 24,
                 "ladder up": nh.GLYPH_CMAP_OFF + 25, "ladder down": nh.GLYPH_CMAP_OFF + 26,
                 "altar": nh.GLYPH_CMAP_OFF + 27, "grave": nh.GLYPH_CMAP_OFF + 28,
                 "opulent throne": nh.GLYPH_CMAP_OFF + 29, "sink": nh.GLYPH_CMAP_OFF + 30,
                 "fountain": nh.GLYPH_CMAP_OFF + 31}
