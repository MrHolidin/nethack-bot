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


def deep_unknown(k_mem, min_dist=2, min_area=6):
    """Unknown squares at least min_dist (Chebyshev) from anything known, in blobs of at least min_area:
    space where a not-yet-seen room can still be. Rock between known rooms stays UNKNOWN forever but is
    thin, so it is not 'deep'."""
    known = k_mem != G.UNKNOWN
    near = known.copy()
    rows, cols = k_mem.shape
    for _ in range(min_dist - 1 + 1):
        grown = near.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy or dx:
                    grown[max(0, dy):rows + min(0, dy), max(0, dx):cols + min(0, dx)] |= \
                        near[max(0, -dy):rows + min(0, -dy), max(0, -dx):cols + min(0, -dx)]
        near = grown
    deep = ~near
    deep[0, :] = deep[-1, :] = False
    # drop small blobs
    out = np.zeros_like(deep)
    seen = np.zeros_like(deep)
    for y, x in zip(*np.nonzero(deep)):
        if seen[y, x]:
            continue
        comp = [(y, x)]
        seen[y, x] = True
        i = 0
        while i < len(comp):
            cy, cx = comp[i]
            i += 1
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = cy + dy, cx + dx
                if 0 <= ny < rows and 0 <= nx < cols and deep[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    comp.append((ny, nx))
        if len(comp) >= min_area:
            for cy, cx in comp:
                out[cy, cx] = True
    return out


def search_candidates(under, k_mem, reach, deep_mode=False):
    """weight map over standing squares."""
    rows, cols = k_mem.shape
    cm = CMAP_OF[under]
    corridor = np.isin(cm, list(CORRIDOR_CMAP))
    room = np.isin(cm, list(ROOM_CMAP)) | (np.isin(k_mem, [G.OBJECT, G.GOLD, G.CORPSE, G.TRAP]) & ~corridor)
    walk = np.isin(k_mem, [G.FLOOR, G.DOOR_OPEN, G.DOORWAY, G.OBJECT, G.GOLD, G.CORPSE, G.TRAP,
                           G.UPSTAIR, G.DOWNSTAIR, G.DOOR_CLOSED, G.BOULDER])
    unknown = deep_unknown(k_mem) if deep_mode else (k_mem == G.UNKNOWN)
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
    tips = corridor & reach & (nb <= 1)
    if not deep_mode:
        w[tips] = W_DEAD_END
    else:
        # a tip is worth searching if it points into space where a room can still be
        for y, x in zip(*np.nonzero(tips)):
            dirs = [(dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dy or dx)
                    and 0 <= y + dy < rows and 0 <= x + dx < cols and walk[y + dy, x + dx]]
            if len(dirs) == 1:
                dy, dx = -dirs[0][0], -dirs[0][1]          # continue away from where we came from
                ray = [(y + k * dy + a * (dx != 0), x + k * dx + a * (dy != 0))
                       for k in range(1, 12) for a in (-2, -1, 0, 1, 2)]
                ray = [(a, b) for a, b in ray if 0 <= a < rows and 0 <= b < cols]
                frac = np.mean([unknown[a, b] for a, b in ray]) if ray else 0.0
            else:
                frac = 0.5
            w[y, x] = W_DEAD_END * (0.2 + 0.8 * frac)
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
    def pick_search_spot(self, lv, k_mem, reach, dist, algo="v2"):
        if algo not in ("v2", "deep"):
            return self.pick_search_spot_alt(lv, k_mem, reach, dist, algo)
        w = search_candidates(lv.under, k_mem, reach, deep_mode=bool(self.role_opts.get("search_deep")) or algo == "deep")
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

    def pick_search_spot_alt(self, lv, k_mem, reach, dist, algo):
        """v3: structured candidates (deep), but once their remaining probability is small, hand over to the
        exhaustive coverage rule (return None -> the old wall-count heuristic)."""
        if algo == "v3":
            w = search_candidates(lv.under, k_mem, reach, deep_mode=True)
            covered = _shift_sum(lv.searched.astype(int))
            post = w * np.power(Q_MISS, covered)
            post[~reach] = 0
            if post.max() < self.role_opts.get("sv3_min", 0.15):
                return None
            score = post / (np.minimum(dist, 500) + 10.0)
            best = np.unravel_index(np.argmax(score), score.shape)
            self.sv2_picks += 1
            return int(best[0]), int(best[1])
        return None
