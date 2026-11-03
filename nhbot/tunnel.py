"""Digging sideways through rock and walls (flag dig_through).

dig.c: an applied pick-axe or mattock adds 10 + d4 + bonuses to the effort each turn (twice that for a dwarf);
a rock or wall square is done at 100 -- about 8 turns (4). A wand of digging zapped sideways (zap_dig) bores
8..25 squares at once. Squares on the map's edge, shop walls (the shopkeeper minds) and the walls of levels
that refuse ("too hard to dig in") are left alone.

tunnel_path finds the cheapest way to a set of squares where unknown and wall squares count as passable at
TUNNEL_COST each (entered orthogonally, like the tunnel they become), known floor at 1. tunnel_step takes one
step along it: a move onto known floor, else one dig toward the next square.

Uses (both behind the flag):
  * stuck: nothing left to explore and no way down in reach (where the explorer would start searching for
    hidden passages) -- dig toward a known down staircase, else toward the middle of the widest band of
    columns where we know nothing at all (rooms are spread over the whole width);
  * vault: a closed room of at most 4 squares on the map (magic mapping shows it) -- dig into it; the vault
    module (vault_dig) takes the gold and digs down.
"""
import collections
import heapq
import re

import numpy as np

from nhbot import glyphs as G
from nhbot.consts import COLS, CORRIDOR_GLYPHS, DELTA2KEY, NEIGH, ROWS

TUNNEL_COST = 8           # path cost of a square to dig (turns, roughly)
TUNNEL_TURNS = 500        # turns spent tunnelling on one level at most
TUNNEL_TRIES = 8          # digs at one square before it counts as too hard
BAND_MIN = 8              # columns of nothing known, at least, to dig toward
DOORS = (G.DOOR_OPEN, G.DOOR_CLOSED, G.DOORWAY)
ORTHO = ((-1, 0), (1, 0), (0, -1), (0, 1))


def tunnel_path(passable, diggable, door, start, target):
    """Cheapest path from start to a square of target: [start, ..., goal] or None."""
    INF = 1 << 30
    dist = np.full((ROWS, COLS), INF, dtype=np.int64)
    prev = {}
    dist[start] = 0
    pq = [(0, start)]
    while pq:
        d, (y, x) = heapq.heappop(pq)
        if d > dist[y, x]:
            continue
        if target[y, x]:
            path = [(y, x)]
            while path[-1] != start:
                path.append(prev[path[-1]])
            return path[::-1]
        here_dig = diggable[y, x] and not passable[y, x]
        for dy, dx in NEIGH:
            ny, nx = y + dy, x + dx
            if not (0 <= ny < ROWS and 0 <= nx < COLS):
                continue
            diag = dy and dx
            if passable[ny, nx]:
                if diag and (here_dig or door[y, x] or door[ny, nx]):
                    continue
                c = 1
            elif diggable[ny, nx]:
                if diag:
                    continue
                c = TUNNEL_COST
            else:
                continue
            if d + c < dist[ny, nx]:
                dist[ny, nx] = d + c
                prev[(ny, nx)] = (y, x)
                heapq.heappush(pq, (d + c, (ny, nx)))
    return None


def closed_rooms(k_mem, under, me, max_size=4):
    """Rooms of at most max_size floor squares fully walled in on the map, not holding `me` (vaults)."""
    floorish = np.isin(k_mem, (G.FLOOR, G.GOLD, G.OBJECT, G.CORPSE, G.TRAP)) & ~np.isin(under, CORRIDOR_GLYPHS)
    seen = np.zeros_like(floorish)
    out = []
    for y, x in zip(*np.nonzero(floorish)):
        if seen[y, x]:
            continue
        comp, todo, closed = {(int(y), int(x))}, [(int(y), int(x))], True
        seen[y, x] = True
        while todo:
            cy, cx = todo.pop()
            for dy, dx in NEIGH:
                ny, nx = cy + dy, cx + dx
                if not (0 <= ny < ROWS and 0 <= nx < COLS):
                    closed = False
                    continue
                if floorish[ny, nx]:
                    if not seen[ny, nx]:
                        seen[ny, nx] = True
                        comp.add((ny, nx))
                        todo.append((ny, nx))
                elif k_mem[ny, nx] != G.WALL:
                    closed = False
        if closed and len(comp) <= max_size and me not in comp:
            out.append(comp)
    return out


class TunnelMixin:
    def tunnel_init(self):
        self.tunnel_hard = set()        # (level key, square) that refused to be dug
        self.tunnel_tries = collections.Counter()
        self.tunnel_turns = collections.Counter()   # level key -> turns spent tunnelling
        self.tunnel_last = None         # turn of the last tunnel step
        self.known_vaults = {}          # level key -> [set of squares], vaults seen on the map
        self.tunnel_vault_counted = set()
        self.tunnel_stats = collections.Counter()

    def tunnel_active(self):
        """A tunnel step was taken just now: keep the digger in hand (weapon_check waits)."""
        return self.tunnel_last is not None and self.turn() - self.tunnel_last <= 10

    def diggable_grid(self, lv, k_mem):
        dig = np.isin(k_mem, (G.UNKNOWN, G.WALL))
        dig[:1, :] = dig[-1:, :] = False
        dig[:, :2] = dig[:, -2:] = False
        shop = lv.shop.copy()
        for y, x in zip(*np.nonzero(lv.shop)):
            shop[max(0, y - 1):y + 2, max(0, x - 1):x + 2] = True      # the shop's walls
        dig &= ~shop
        dig[lv.blocked] = False
        for key, p in self.tunnel_hard:
            if key == lv.key:
                dig[p] = False
        return dig

    def tunnel_to(self, lv, target, why):
        """One step of digging / walking toward a square of target. True if it used the turn."""
        if self.tunnel_turns[lv.key] >= TUNNEL_TURNS:
            return False
        d = self.digger()
        if d is None:
            return False
        k_mem, _, passable = self.grids(lv)
        door = np.isin(k_mem, DOORS) | lv.door_intact | lv.no_diag
        path = tunnel_path(passable, self.diggable_grid(lv, k_mem), door, self.pos(), target)
        if path is None or len(path) < 2:
            self.tunnel_stats["no_path_" + why] += 1
            return False
        nxt = path[1]
        t0 = self.turn()
        self.tunnel_last = t0
        self.cur_act = "tunnel"
        if passable[nxt]:
            self.move(nxt)
        else:
            y, x = self.pos()
            key = DELTA2KEY[(nxt[0] - y, nxt[1] - x)]
            seq0 = self.msg_seq
            self.tunnel_tries[(lv.key, nxt)] += 1
            self.tunnel_stats["digs_" + why] += 1
            if d[0] == "zap":
                self.zap(d[1], key)
            elif self.ask("a", "apply"):
                self.press(d[1], expect_prompt=True)
                if "direction" in self.message().lower():
                    self.press(key)
                else:
                    self.settle()
            msgs = self.text_since(seq0)
            if re.search(r"too hard to|cannot|can't dig|not enough room", msgs) \
                    or self.tunnel_tries[(lv.key, nxt)] >= TUNNEL_TRIES:
                self.tunnel_hard.add((lv.key, nxt))
                self.tunnel_stats["hard"] += 1
        self.tunnel_turns[lv.key] += max(1, self.turn() - t0)
        return True

    # ------------------------------------------------------------------ uses
    def tunnel_stuck_step(self, lv):
        """dig_through, called by the explorer with nothing left to walk to and no way down in reach."""
        if not self.opts.dig_through or lv.key[0] != 0 or self.visible_hostiles(lv):
            return False
        k_mem = self.grids(lv)[0]
        down = k_mem == G.DOWNSTAIR
        if down.any():
            if self.tunnel_to(lv, down, "stairs"):
                return True
        known = (k_mem != G.UNKNOWN).any(axis=0)
        best, run, start = None, 0, None
        for x in range(2, COLS - 2):
            if not known[x]:
                if run == 0:
                    start = x
                run += 1
                if best is None or run > best[1] - best[0]:
                    best = (start, x + 1)
            else:
                run = 0
        if best is None or best[1] - best[0] < BAND_MIN:
            return False
        target = np.zeros((ROWS, COLS), dtype=bool)
        target[3:ROWS - 3, (best[0] + best[1]) // 2] = True
        return self.tunnel_to(lv, target, "band")

    def tunnel_vault_step(self, lv, hostiles):
        """dig_through: a vault seen on the map, not entered yet: dig into it."""
        if not self.opts.dig_through or hostiles or lv.key[0] != 0 or lv.key in self.vault_entered:
            return False
        if self.digger() is None or self.visible_hostiles(lv):
            return False
        k_mem = self.grids(lv)[0]
        rooms = closed_rooms(k_mem, lv.under, self.pos())
        if rooms:
            self.known_vaults[lv.key] = rooms
        rooms = self.known_vaults.get(lv.key)
        if not rooms:
            return False
        target = np.zeros((ROWS, COLS), dtype=bool)
        for r in rooms:
            for p in r:
                target[p] = True
        if target[self.pos()]:
            return False
        if lv.key not in self.tunnel_vault_counted:
            self.tunnel_vault_counted.add(lv.key)
            self.tunnel_stats["vault_seen"] += 1
        return self.tunnel_to(lv, target, "vault")
