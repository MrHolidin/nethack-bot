"""Where a hidden passage may lie, read from the known part of a level: the candidates are the sides of the rooms we
know (a secret door in their wall) and the dead ends of the corridors we know (a secret corridor square, or a
secret door, next to the end), each with the features a predictor of "a hidden passage is here" uses.

NetHack 3.6.6 (mklev.c, sp_lev.c): every room is joined to the next one in x order, then to the one after that
every other time, then whatever is still apart, then a few extra corridors; a door is secret 1 time in 8 (dodoor),
a corridor square 1 time in 100 (dig_corridor), an extra corridor may stop dead (1 in 35 a step). Niches above a
room's top wall hide behind a secret door 4 times in 5. Vaults (2x2, no door) are joined to nothing.

search_log (experiments): at the first search on a level, the candidates with their features and, from the true
map (nhbot.truemap), whether a hidden square is there and whether it lies on a way to the down staircase with the
fewest hidden squares -- one record per level in the summary ("search_log").
"""
import heapq
from collections import deque

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import COLS, ROWS

CMAP = nh.GLYPH_CMAP_OFF
ROOM_FLOOR = (19, 20)                                   # S_room, S_darkroom
ROOM_FEATURE = (19, 20, 23, 24, 25, 26, 27, 28, 29, 30, 31, 33)   # floor, stairs, ladders, altar .. sink, ice
CORRIDOR = (21, 22)
DOORS = (12, 13, 14, 15, 16)
ITEM_KINDS = (G.OBJECT, G.GOLD, G.CORPSE, G.BOULDER)
SIDES = ("N", "E", "S", "W")
VAULT_AREA = 4
FIND = 1.0 / 7                   # a search finds a hidden square next to us with this chance (detect.c dosearch0:
                                 # rnl(7) at Luck 0)
SEARCH_BURST = 10                # turns searched at a spot before choosing again ("10s")
SEARCH_V2_MIN = 1e-4             # search_v2: below this expected find per turn anywhere, the old wall count decides


def side_x(f):
    """Predictor inputs of a room side (hidden_candidates features)."""
    return [1.0, min(f["depth"], 30) / 10.0, f["side"] == 0, f["side"] == 1, f["side"] == 2, f["length"] / 10.0,
            np.log1p(f["area"]), f["doors"] == 0, min(f["room_doors"], 4) / 4.0, np.log1p(f["space"]),
            np.log1p(f["band_unknown"]), f["band_frac"], min(f["rooms"], 9) / 9.0,
            f["rooms_left"] == 0, f["rooms_right"] == 0, f["known_frac"]]


def dead_x(f):
    """Predictor inputs of a dead end."""
    return [1.0, min(f["depth"], 30) / 10.0, f["unknown_nb"] / 8.0, min(f["edge"], 10) / 10.0,
            min(f["rooms"], 9) / 9.0, f["known_frac"]]


SIDE_W = None                    # logistic weights over side_x (fitted on search_log data: see hidden_prob)
DEAD_W = None                    # ... over dead_x


def hidden_prob(cand):
    """P(a hidden square is among this candidate's squares), from the known map only."""
    x, w = (side_x, SIDE_W) if cand["kind"] == "side" else (dead_x, DEAD_W)
    z = float(np.dot(np.asarray(x(cand["f"]), dtype=float), w))
    return 1.0 / (1.0 + np.exp(-z))


def nb_sum(a):
    """Sum over the 8 neighbours of every square."""
    out = np.zeros(a.shape, dtype=float)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx:
                out[max(0, dy):ROWS + min(0, dy), max(0, dx):COLS + min(0, dx)] += \
                    a[max(0, -dy):ROWS + min(0, -dy), max(0, -dx):COLS + min(0, -dx)]
    return out


def cmap_of(glyphs):
    """cmap index of each glyph, -1 where it is no map symbol."""
    c = glyphs - CMAP
    return np.where((c >= 0) & (c < nh.MAXPCHARS), c, -1)


def neighbours8(y, x):
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if (dy or dx) and 0 <= y + dy < ROWS and 0 <= x + dx < COLS:
                yield y + dy, x + dx


class HiddenMixin:
    # ------------------------------------------------------------------ the known map
    def known_rooms(self, lv):
        """Rooms of the known map: 4-connected squares of room floor (or a room feature, or an item on a square
        whose floor we never saw), with at least one floor square; each as (bounding box, interior squares)."""
        cm = cmap_of(self.terrain_glyphs(lv))
        under_kind = G.KIND[lv.under]
        inner = np.isin(cm, ROOM_FEATURE) | ((cm <= 0) & np.isin(under_kind, ITEM_KINDS))
        floor = np.isin(cm, ROOM_FLOOR)
        seen = np.zeros_like(inner)
        rooms = []
        for y0, x0 in zip(*np.nonzero(floor)):
            if seen[y0, x0]:
                continue
            comp, q = [], deque([(y0, x0)])
            seen[y0, x0] = True
            while q:
                y, x = q.popleft()
                comp.append((y, x))
                for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                    if 0 <= ny < ROWS and 0 <= nx < COLS and inner[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        q.append((ny, nx))
            ys, xs = zip(*comp)
            rooms.append(((int(min(ys)), int(min(xs)), int(max(ys)), int(max(xs))), comp))
        return rooms

    def room_sides(self, lv, k_mem, box):
        """The four walls of a room box: per side its squares between the corners, how many of them we know as
        wall or door, the doors on it."""
        ly, lx, hy, hx = box
        lines = {"N": [(ly - 1, x) for x in range(lx, hx + 1)], "S": [(hy + 1, x) for x in range(lx, hx + 1)],
                 "W": [(y, lx - 1) for y in range(ly, hy + 1)], "E": [(y, hx + 1) for y in range(ly, hy + 1)]}
        out = {}
        for side, sq in lines.items():
            sq = [p for p in sq if 0 <= p[0] < ROWS and 0 <= p[1] < COLS]
            kinds = [k_mem[p] for p in sq]
            doors = sum(1 for p, k in zip(sq, kinds) if k in (G.DOOR_OPEN, G.DOOR_CLOSED, G.DOORWAY)
                        or lv.door_seen[p])
            walls = sum(1 for k in kinds if k == G.WALL)
            out[side] = (sq, walls, doors)
        return out

    def dead_ends(self, lv, k_mem):
        """Known corridor squares with exactly one walkable known neighbour."""
        cm = cmap_of(self.terrain_glyphs(lv))
        walk = G.PASSABLE[k_mem] | (k_mem == G.BOULDER)
        out = []
        for y, x in zip(*np.nonzero(np.isin(cm, CORRIDOR))):
            n = sum(1 for p in neighbours8(y, x) if walk[p])
            if n == 1:
                out.append((int(y), int(x)))
        return out

    # ------------------------------------------------------------------ candidates and their features
    def hidden_candidates(self, lv, k_mem):
        """Room sides (known at least half as wall / door) and dead ends, each a dict: kind, squares a hidden
        passage of it would be on (its wall squares / the unknown and wall squares next to a dead end), features."""
        rooms = self.known_rooms(lv)
        unknown = k_mem == G.UNKNOWN
        known_frac = float(1.0 - unknown.mean())
        centres = [((b[1] + b[3]) / 2.0) for b, _ in rooms]
        depth = self.bl(nh.NLE_BL_DEPTH)
        cands = []
        for (box, comp), cx in zip(rooms, centres):
            ly, lx, hy, hx = box
            w, h = hx - lx + 1, hy - ly + 1
            if len(comp) <= VAULT_AREA and w <= 2 and h <= 2:
                continue                                  # a vault (or a closet): joined to nothing
            sides = self.room_sides(lv, k_mem, box)
            room_doors = sum(s[2] for s in sides.values())
            left = sum(1 for c in centres if c < cx)
            right = len(centres) - 1 - left
            for side, (sq, walls, doors) in sides.items():
                if not sq or (walls + doors) * 2 < len(sq):
                    continue
                if side == "N":
                    band, space = unknown[:max(0, ly - 1), lx:hx + 1], ly - 1
                elif side == "S":
                    band, space = unknown[hy + 2:, lx:hx + 1], ROWS - 2 - hy
                elif side == "W":
                    band, space = unknown[ly:hy + 1, :max(0, lx - 1)], lx - 1
                else:
                    band, space = unknown[ly:hy + 1, hx + 2:], COLS - 2 - hx
                cands.append(dict(
                    kind="side", squares=[p for p in sq if k_mem[p] == G.WALL],
                    f=dict(depth=depth, side=SIDES.index(side), length=len(sq), w=w, h=h, area=len(comp),
                           doors=doors, room_doors=room_doors, space=int(space),
                           band_unknown=int(band.sum()), band_frac=float(band.mean()) if band.size else 0.0,
                           rooms=len(rooms), rooms_left=left, rooms_right=right, known_frac=known_frac,
                           searched=int(sum(lv.searched[p] for p in sq)))))
        for y, x in self.dead_ends(lv, k_mem):
            unk = [p for p in neighbours8(y, x) if unknown[p]]
            cands.append(dict(
                kind="dead_end", squares=[p for p in neighbours8(y, x) if unknown[p] or k_mem[p] == G.WALL],
                f=dict(depth=depth, unknown_nb=len(unk), edge=min(y, ROWS - 1 - y, x, COLS - 1 - x),
                       rooms=len(rooms), known_frac=known_frac,
                       searched=int(sum(lv.searched[p] for p in neighbours8(y, x))))))
        return cands

    # ------------------------------------------------------------------ search_v2
    def hidden_posterior(self, lv, k_mem):
        """Per square: the chance a hidden square is there and still unfound. A candidate's prior (hidden_prob)
        is spread evenly over its squares; every search turn next to a square leaves it unfound with 1 - FIND
        (Bayes over the candidate: P(there | not found yet))."""
        miss = (1.0 - FIND) ** nb_sum(lv.searched)
        post = np.zeros((ROWS, COLS))
        for c in self.hidden_candidates(lv, k_mem):
            sq = c["squares"]
            if not sq:
                continue
            p = hidden_prob(c)
            m = float(np.mean([miss[q] for q in sq]))
            still = p * m / (1.0 - p + p * m)
            for q in sq:
                post[q] += still * miss[q] / (m * len(sq))
        return post

    def search_v2_goal(self, lv, grids, dist):
        """search_v2: the reachable square where searching SEARCH_BURST turns finds the most per turn spent
        (walking there included); None when nothing is worth it (SEARCH_V2_MIN)."""
        k_mem, _, passable = grids
        gain = nb_sum(self.hidden_posterior(lv, k_mem)) * (1.0 - (1.0 - FIND) ** SEARCH_BURST)
        rate = np.where((dist < (1 << 30)) & passable, gain / (np.minimum(dist, 500) + SEARCH_BURST), -1.0)
        best = np.unravel_index(np.argmax(rate), rate.shape)
        if rate[best] < SEARCH_V2_MIN:
            return None
        self.search_v2_stats["picked"] += 1
        return int(best[0]), int(best[1])

    # ------------------------------------------------------------------ search_log
    def search_log_note(self, lv, k_mem):
        """search_log: the first search on this level -- its candidates, labelled from the true map."""
        if lv.key in self.search_logged:
            return
        self.search_logged.add(lv.key)
        from nhbot.truemap import SCORR, SDOOR, read_true_map   # experiments only
        tm = read_true_map(self.env)
        hidden = (tm.typ == SDOOR) | (tm.typ == SCORR)
        way = set(fewest_hidden_way(tm, self.pos())) if tm.down is not None else set()
        recs = []
        for c in self.hidden_candidates(lv, k_mem):
            sq = c["squares"]
            recs.append(dict(c["f"], kind=c["kind"], hidden=int(any(hidden[p] for p in sq)),
                             on_way=int(any(p in way and hidden[p] for p in sq))))
        self.search_log.append(dict(key=list(lv.key), turn=self.turn(), down=tm.down is not None,
                                    way_hidden=sum(1 for p in way if hidden[p]), cands=recs))


def fewest_hidden_way(tm, start):
    """Squares of a way from start to the down staircase with the fewest hidden squares (0-1 Dijkstra on the true
    map; no diagonal step into or out of a door)."""
    from nhbot.truemap import DOOR, SCORR, SDOOR, WALKABLE
    typ = tm.typ
    INF = 1 << 30
    dist = np.full(typ.shape, INF, dtype=np.int64)
    prev = {}
    dist[start] = 0
    q = [(0, start)]
    goal = tm.down
    while q:
        d, (y, x) = heapq.heappop(q)
        if d > dist[y, x]:
            continue
        if (y, x) == goal:
            break
        here_door = int(typ[y, x]) in (DOOR, SDOOR)
        for ny, nx in neighbours8(y, x):
            t = int(typ[ny, nx])
            if t not in WALKABLE and t not in (SDOOR, SCORR):
                continue
            if ny != y and nx != x and (here_door or t in (DOOR, SDOOR)):
                continue
            nd = d + (t in (SDOOR, SCORR))
            if nd < dist[ny, nx]:
                dist[ny, nx] = nd
                prev[(ny, nx)] = (y, x)
                heapq.heappush(q, (nd, (ny, nx)))
    if dist[goal] >= INF:
        return []
    path = [goal]
    while path[-1] != start:
        path.append(prev[path[-1]])
    return path
