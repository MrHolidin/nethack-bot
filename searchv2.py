"""Where to search for hidden doors/corridors, from how NetHack 3.6 builds levels (mklev.c, sp_lev.c):

* every door is secret with p = 1/8, every corridor square with p = 1/100;
* rooms are joined to their neighbours (sorted left to right); the door of a corridor sits on the wall of
  the room that FACES the other room;
* a few extra corridors may simply stop (true dead ends).

So a hidden connection is behind (a) the tip of a dead-end corridor, or (b) a room wall that faces the
part of the map we have not seen.  One search turn finds an adjacent hidden square with p ~ 1/7 (rnl(7)),
so after n turns of searching near a spot the chance something is still hidden there is (6/7)^n.

Choice: maximise  weight * (6/7)^searched_nearby / (path length + 10).
"""
import numpy as np
import nle.nethack as nh

import glyphs as G

CORRIDOR_CMAP = {21, 22}
ROOM_CMAP = {19, 20}
Q_MISS = 6.0 / 7.0
W_DEAD_END = 1.0
W_WALL = 0.6
BAND = 3            # half-width of the strip looked at beyond a wall


def _shift_sum(a):
    """3x3 neighbourhood max of an int array."""
    r, c = a.shape
    out = a.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx:
                s = np.zeros_like(a)
                s[max(0, dy):r + min(0, dy), max(0, dx):c + min(0, dx)] = \
                    a[max(0, -dy):r + min(0, -dy), max(0, -dx):c + min(0, -dx)]
                out = np.maximum(out, s)
    return out


CMAP_OF = np.full(nh.MAX_GLYPH, -1, dtype=np.int16)
for _g in range(nh.MAX_GLYPH):
    if nh.glyph_is_cmap(_g):
        CMAP_OF[_g] = nh.glyph_to_cmap(_g)


def search_candidates(under, k_mem, reach):
    """weight map over standing squares."""
    rows, cols = k_mem.shape
    cm = CMAP_OF[under]
    corridor = np.isin(cm, list(CORRIDOR_CMAP))
    room = np.isin(cm, list(ROOM_CMAP)) | (np.isin(k_mem, [G.OBJECT, G.GOLD, G.CORPSE, G.TRAP]) & ~corridor)
    walk = np.isin(k_mem, [G.FLOOR, G.DOOR_OPEN, G.DOORWAY, G.OBJECT, G.GOLD, G.CORPSE, G.TRAP,
                           G.UPSTAIR, G.DOWNSTAIR, G.DOOR_CLOSED, G.BOULDER])
    unknown = k_mem == G.UNKNOWN
    w = np.zeros(k_mem.shape)
    # (a) dead-end corridor tips
    nb = np.zeros(k_mem.shape, dtype=int)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx:
                s = np.zeros_like(nb)
                s[max(0, dy):rows + min(0, dy), max(0, dx):cols + min(0, dx)] = \
                    walk[max(0, -dy):rows + min(0, -dy), max(0, -dx):cols + min(0, -dx)]
                nb += s
    w[corridor & reach & (nb <= 1)] = W_DEAD_END
    # (b) room squares next to a wall: weight = share of unseen squares in the strip beyond the wall
    ys, xs = np.nonzero(room & reach)
    for y, x in zip(ys, xs):
        best = 0.0
        for dy, dx in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            wy, wx = y + dy, x + dx
            if not (0 <= wy < rows and 0 <= wx < cols) or k_mem[wy, wx] != G.WALL:
                continue
            if dx:
                xa, xb = (0, wx) if dx < 0 else (wx + 1, cols)
                strip = unknown[max(0, y - BAND):y + BAND + 1, xa:xb]
            else:
                ya, yb = (0, wy) if dy < 0 else (wy + 1, rows)
                strip = unknown[ya:yb, max(0, x - BAND * 3):x + BAND * 3 + 1]
            if strip.size >= 6:
                best = max(best, strip.mean())
        if best > 0:
            w[y, x] = max(w[y, x], W_WALL * best)
    return w


class SearchV2Mixin:
    def pick_search_spot(self, lv, k_mem, reach, dist):
        w = search_candidates(lv.under, k_mem, reach)
        if not (w > 0).any():
            return None
        covered = _shift_sum(lv.searched.astype(int))           # searches made at or next to the square
        score = w * np.power(Q_MISS, covered) / (np.minimum(dist, 500) + 10.0)
        score[~reach] = 0
        best = np.unravel_index(np.argmax(score), score.shape)
        if score[best] <= 1e-6:
            return None
        self.sv2_picks += 1
        return int(best[0]), int(best[1])
