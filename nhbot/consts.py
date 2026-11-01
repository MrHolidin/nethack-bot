"""Board geometry, movement keys, hunger states and named map glyphs."""
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


def ray_squares(y, x, dy, dx, n=9):
    """The squares a missile thrown from (y, x) in direction (dy, dx) can land on (up to n away)."""
    return [(y + i * dy, x + i * dx) for i in range(1, n + 1) if in_bounds(y + i * dy, x + i * dx)]


# hunger states
SATIATED, NOT_HUNGRY, HUNGRY, WEAK, FAINTING = 0, 1, 2, 3, 4

# stairs/ladders, altar, grave, throne, sink, fountain, water, lava, air, cloud: the game refuses to engrave there
NO_ENGRAVE_CMAP = {23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 34, 39, 40, 41}

# cmap glyphs (display.h / drawing.c S_ indices)
STONE_GLYPH = nh.GLYPH_CMAP_OFF + 0
FLOOR_GLYPH = nh.GLYPH_CMAP_OFF + 19     # S_room
CORRIDOR_GLYPHS = (nh.GLYPH_CMAP_OFF + 21, nh.GLYPH_CMAP_OFF + 22)    # S_corr, S_litcorr
UPSTAIR_GLYPH = nh.GLYPH_CMAP_OFF + 23
DOWNSTAIR_GLYPH = nh.GLYPH_CMAP_OFF + 24
ALTAR_GLYPH = nh.GLYPH_CMAP_OFF + 27
FOUNTAIN_GLYPH = nh.GLYPH_CMAP_OFF + 31
