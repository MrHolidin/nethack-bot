"""Where to search for a hidden passage (search_model): the expected find per turn of searching from a square.

Facts from NetHack 3.6.6 that the model rests on:
  * mklev.c makecorridors: rooms are sorted left to right and joined to their neighbours in that order, so a
    level spans the 80-column map; a big part of the map with nothing seen in it holds the rooms not found yet
  * mklev.c dodoor: 1 door in 8 is a secret door, in a room wall; sp_lev.c dig_corridor: 1 corridor square in
    100 is a secret corridor square
  * detect.c dosearch0: one turn of searching finds a hidden square next to us with probability ~1/7 (rnl(7)
    at Luck 0); the 8 squares around us are searched at once

Candidates (squares that may hide the way on) and their outward side:
  * a straight room-wall square with room floor on one side and nothing seen on the other: a secret door
  * the unseen square that continues a dead-end corridor: a secret corridor square
Prior of a candidate: P(an unseen room beyond) from the room-sized unseen space beyond it (5x5 boxes of
never-seen squares, nearer ones weighing more; on the outward side of a wall, all around a dead end since
corridors turn), shared out along a wall's straight stretch. A wall between two known rooms, or with a known
corridor behind it, gets nothing. Posterior: prior * (6/7) ** (turns searched next to it).
"""
import numpy as np

from nhbot import glyphs as G
from nhbot.consts import COLS, CORRIDOR_GLYPHS, ROWS

ROOM_BOX = 5          # an unseen room needs at least this many unseen squares across (walls included)
REACH = 12.0          # distance scale for the room space beyond a candidate
MISS = 6.0 / 7.0      # one search turn misses a hidden square next to us
ROOM_SPACE = 3.0      # room space at which an unseen room beyond is ~63% likely


def box_sum(a, r):
    """Sum of a over the (2r+1)x(2r+1) box around every square (zero outside the map)."""
    p = np.pad(a.astype(np.int32), r)
    c = p.cumsum(0).cumsum(1)
    c = np.pad(c, ((1, 0), (1, 0)))
    k = 2 * r + 1
    return c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]


def candidates(k_mem, under):
    """[(square, outward direction or None, share)] of the squares that may hide a passage. A wall square's
    share is 1 / the length of its straight wall stretch facing the same way (one secret door per wall is what
    the mass stands for); a dead end's continuation has share 1 and no direction (corridors turn)."""
    unseen = k_mem == G.UNKNOWN
    corridor = np.isin(under, list(CORRIDOR_GLYPHS))
    floor = G.PASSABLE[k_mem] & ~corridor & (k_mem != G.DOOR_OPEN) & (k_mem != G.DOOR_CLOSED) \
        & (k_mem != G.DOORWAY)
    ok = lambda y, x: 0 <= y < ROWS and 0 <= x < COLS
    walls = {}
    for y, x in zip(*np.nonzero(k_mem == G.WALL)):
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            fy, fx, oy, ox = y - dy, x - dx, y + dy, x + dx
            if ok(fy, fx) and ok(oy, ox) and floor[fy, fx] and unseen[oy, ox]:
                walls[(int(y), int(x))] = (dy, dx)
    out = []
    for (y, x), d in walls.items():
        ay, ax = abs(d[1]), abs(d[0])          # along the wall
        n = 1
        for sgn in (1, -1):
            k = 1
            while walls.get((y + sgn * k * ay, x + sgn * k * ax)) == d:
                n += 1
                k += 1
        out.append(((y, x), d, 1.0 / n))
    walk = G.PASSABLE[k_mem]
    for y, x in zip(*np.nonzero(corridor)):
        nb = [(dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1)
              if (dy or dx) and ok(y + dy, x + dx) and walk[y + dy, x + dx]]
        if len(nb) == 1:                      # a dead end: continue it away from its one neighbour
            ny, nx = y - nb[0][0], x - nb[0][1]
            if ok(ny, nx) and unseen[ny, nx]:
                out.append(((int(ny), int(nx)), None, 1.0))
    return out


def remaining(k_mem, under, searched):
    """Map of the remaining probability of a hidden passage at each candidate square (0 elsewhere):
    P(an unseen room beyond) * share * (6/7) ** (search turns next to it)."""
    unseen = (k_mem == G.UNKNOWN)
    r = ROOM_BOX // 2
    room = box_sum(unseen, r) == ROOM_BOX * ROOM_BOX
    room[:r, :] = room[-r:, :] = False
    ry, rx = np.nonzero(room)
    covered = box_sum(searched, 1)            # search turns made from a square next to each square
    out = np.zeros((ROWS, COLS))
    if not len(ry):
        return out
    for (y, x), d, share in candidates(k_mem, under):
        vy, vx = ry - y, rx - x
        if d is not None:
            ahead = vy * d[0] + vx * d[1] > 0
            vy, vx = vy[ahead], vx[ahead]
        if not len(vy):
            continue
        space = float(np.exp(-np.hypot(vy, vx) / REACH).sum())
        p_room = 1.0 - np.exp(-space / ROOM_SPACE)
        out[y, x] = max(out[y, x], p_room * share * MISS ** covered[y, x])
    return out


def best_spot(rem, dist, reach, passable, block=10):
    """The square to search from: the most expected find per turn spent (walking there + one block of
    searching). None if nothing is left to find."""
    gain = box_sum_float(rem)
    rate = np.where(reach & passable, gain / (np.minimum(dist, 10_000) + block), -1.0)
    best = np.unravel_index(np.argmax(rate), rate.shape)
    if rate[best] <= 1e-9:
        return None
    return int(best[0]), int(best[1])


def box_sum_float(a):
    p = np.pad(a, 1)
    return sum(p[1 + dy:1 + dy + ROWS, 1 + dx:1 + dx + COLS] for dy in (-1, 0, 1) for dx in (-1, 0, 1))
