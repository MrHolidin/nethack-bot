"""Path finding and single steps: Dijkstra over the remembered map, moving (door kicks, peaceful
monsters in the way, failed moves), walking toward a square or a set of squares."""
import heapq
from array import array

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import COLS, DELTA2KEY, NEIGH, ROWS

# Grotto Town (mines.des minetn-5, map (x, y) on screen (y, x + 2)): its down staircase lies behind the locked
# door at map (50, 6) in every one of its terrain variants; the way to that door has closed doors only
GROTTO_STAIR_DOOR = (6, 52)


def line_clear(k_mem, glyphs, y, x, dy, dx, d):
    """The d - 1 squares between (y, x) and the square d steps away in direction (dy, dx) are passable terrain
    with no monster, pet or boulder on them."""
    return all(G.PASSABLE[k_mem[y + i * dy, x + i * dx]] and
               G.KIND[glyphs[y + i * dy, x + i * dx]] not in (G.MONSTER, G.PET, G.BOULDER)
               for i in range(1, d))


# Dijkstra runs over flat Python lists of the map padded by an impassable border (list indexing is much faster
# than numpy scalar indexing); heap entries (cost, flat index) pop in the same order as (cost, y, x)
_W = COLS + 2
_N = (ROWS + 2) * _W
_STEPS = tuple((dy * _W + dx, bool(dy and dx), dy * _W, dx) for dy, dx in NEIGH)   # + the two orthogonal steps
SQUEEZE_COST = 1000           # squeeze_reach: a diagonal between two rock squares, once our weight was refused
_INF = 1 << 30
_STEP_COST = np.ones(256, dtype=np.int64)           # cost of stepping into a square, by remembered kind
_STEP_COST[G.TRAP], _STEP_COST[G.BOULDER], _STEP_COST[G.DOOR_CLOSED] = 40, 15, 3
_LIVE_COST = np.zeros(256, dtype=np.int64)          # extra cost by what is seen there now
_LIVE_COST[G.MONSTER] = _LIVE_COST[G.INVIS] = 4
_pad_cost = np.full((ROWS + 2, _W), -1, dtype=np.int64)
_pad_door = np.zeros((ROWS + 2, _W), dtype=bool)
_pad_target = np.zeros((ROWS + 2, _W), dtype=bool)
_pad_rock = np.ones((ROWS + 2, _W), dtype=bool)


class PathPrev:
    """prev[(y, x)]: the square before (y, x) on its shortest path; a dict-like view of the flat array."""
    __slots__ = ("a",)

    def __init__(self, a):
        self.a = a

    def get(self, p, default=None):
        if p is None:
            return default
        j = self.a[(p[0] + 1) * _W + p[1] + 1]
        return default if j < 0 else (j // _W - 1, j % _W - 1)

    def __getitem__(self, p):
        r = self.get(p)
        if r is None:
            raise KeyError(p)
        return r

    def __contains__(self, p):
        return self.get(p) is not None


class NavMixin:
    def dijkstra(self, lv, k_mem, k_live, passable, start, targets_mask=None, max_cost=10_000, want_dist=True):
        """Shortest paths from start: (dist array or None without want_dist, prev, the first target square
        reached or None). Stops at the first square of targets_mask popped, or past max_cost."""
        cost = _STEP_COST[k_mem]
        cost[(k_live == G.BOULDER) & (k_mem != G.TRAP)] = 15
        for p in lv.locked:
            if cost[p] == 3:
                cost[p] = 12
        cost += _LIVE_COST[k_live]
        cost += 5 * lv.fail
        cost[~passable] = -1
        _pad_cost[1:-1, 1:-1] = cost
        cost = _pad_cost.ravel().tolist()
        # an item on a door hides it from k_mem: the doors remembered and the refused diagonals count too
        _pad_door[1:-1, 1:-1] = (k_mem == G.DOOR_OPEN) | (k_mem == G.DOOR_CLOSED) | lv.door_intact | lv.no_diag
        door = _pad_door.ravel().tolist()
        tm = None
        if targets_mask is not None:
            _pad_target[1:-1, 1:-1] = targets_mask
            tm = _pad_target.ravel().tolist()
        rock, squeeze_cost = None, 0
        if self.opts.squeeze_last and lv.squeeze_refused and not lv.squeeze_ok:
            squeeze_cost = -1                    # squeeze_last: too heavy to squeeze here -- none (explore decides)
        elif lv.squeeze_refused and self.opts.squeeze_reach:
            squeeze_cost = SQUEEZE_COST
        if squeeze_cost:
            # hack.c test_move: a diagonal step between two rock squares (or boulders) is a squeeze -- refused
            # above 600 weight
            _pad_rock[1:-1, 1:-1] = (k_mem == G.WALL) | (k_mem == G.UNKNOWN) | (k_mem == G.BOULDER) | \
                (k_live == G.BOULDER)
            rock = _pad_rock.ravel().tolist()
        dist = [_INF] * _N
        prev = [-1] * _N
        s = (start[0] + 1) * _W + start[1] + 1
        dist[s] = 0
        pq = [(0, s)]
        pop, push = heapq.heappop, heapq.heappush
        reached = None
        while pq:
            d, i = pop(pq)
            if d > dist[i]:
                continue
            if tm is not None and tm[i]:
                reached = (i // _W - 1, i % _W - 1)
                break
            if d > max_cost:
                break
            di = door[i]
            for off, diag, oy, ox in _STEPS:
                j = i + off
                c = cost[j]
                if c < 0 or (diag and (di or door[j])):
                    continue
                nd = d + c
                if diag and rock is not None and rock[i + oy] and rock[i + ox]:
                    if squeeze_cost < 0:
                        continue
                    nd += squeeze_cost
                if nd < dist[j]:
                    dist[j] = nd
                    prev[j] = i
                    push(pq, (nd, j))
        if want_dist:
            dist = np.frombuffer(array("q", dist), dtype=np.int64).reshape(ROWS + 2, _W)[1:-1, 1:-1]
        else:
            dist = None
        return dist, PathPrev(prev), reached

    @staticmethod
    def first_step(prev, start, goal):
        cur = goal
        while prev.get(cur) != start:
            cur = prev.get(cur)
            if cur is None:
                return None
        return cur

    def grids(self, lv):
        """(k_mem, k_live, passable) for this level now, computed once per tick and game state: the key changes
        every tick (a move that sends no key -- a door we won't kick -- still changes the map memory), with
        every key sent (any observation change), the shop visit state and the never-melee squares.
        The arrays are read-only: copy before changing."""
        key = (self.tick_no, self.steps, lv.key, self.shop_active(lv), tuple(self.avoid_cells))
        if self._grids_key != key:
            k_mem, k_live = self.kind_grid(lv)
            passable = self.passable_grid(lv, k_mem, k_live)
            for a in (k_mem, k_live, passable):
                a.setflags(write=False)
            self._grids_key, self._grids = key, (k_mem, k_live, passable)
        return self._grids

    def walk_to(self, lv, mask, max_cost=10_000, act=None, chase=None, grids=None, also=None):
        """One step toward the nearest square of mask by path. Returns (status, square):
          "here"         we stand on a square of the mask (the caller does what it came for)
          "moved"        stepped toward square (act: cur_act label; chase: goal-statistics label, or a
                         function of the square giving it)
          "unreachable"  no square of the mask within max_cost
        grids: (k_mem, k_live, passable) to use instead of self.grids(lv); also: squares made passable."""
        here = self.pos()
        if mask[here]:
            return "here", here
        k_mem, k_live, passable = grids if grids is not None else self.grids(lv)
        if also is not None:
            passable = passable | also
        _, prev, reached = self.dijkstra(lv, k_mem, k_live, passable, here, mask, max_cost=max_cost,
                                          want_dist=False)
        step = self.first_step(prev, here, reached) if reached is not None else None
        if step is None:
            return "unreachable", None
        if act is not None:
            self.cur_act = act
        if chase is not None:
            self.goal_chase(chase(reached) if callable(chase) else chase)
        self.move(step)
        return "moved", reached

    def move(self, target):
        y, x = self.pos()
        ty, tx = target
        key = DELTA2KEY[(ty - y, tx - x)]
        self.last_move_target = target
        before = (y, x, self.turn())
        lv = self.level()
        self.trap_held(lv)                    # forgets the trap once we are out of it (or after 30 tries)
        if target in lv.locked:
            if any(max(abs(cy - ty), abs(cx - tx)) <= 1 for cy, cx in lv.cfi):
                lv.blocked[ty, tx] = True     # closed shop: kicking the door angers the shopkeeper
                self.shop_kicks_avoided += 1
                return
            if target == GROTTO_STAIR_DOOR and self.is_grotto(lv) \
                    and target not in lv.watch_warned:
                if self.law_nearby():         # dokick.c: the watch minds only a kick one of them can see
                    self.mines_kick_stats["waited"] += 1
                    self.press("s")
                    return
                self.mines_kick_stats["kicks"] += 1
                self.kick(key)
                return
            if lv.key[0] == 2 or self.law_nearby():
                lv.blocked[ty, tx] = True     # never kick doors in the Mines (Minetown watch)
                return
            self.kick(key)
            return
        if G.KIND[self.obs["glyphs"][target]] == G.MONSTER and self.peaceful_now(lv, target):
            # a peaceful monster in the way: wait for it to move (a shopkeeper in a doorway may never move;
            # making the square impassable after a few waits was tried and not taken -- peaceful_waits counts)
            lv.fail[ty, tx] += 1
            self.peaceful_waits += 1
            self.peaceful_wait_by[G.monster_name(int(self.obs["glyphs"][target]))] += 1
            self.press("s")
            return
        seq0 = self.msg_seq
        known = lv.no_diag[ty, tx] or lv.no_diag[y, x]
        self.press(key)
        after = (*self.pos(), self.turn())
        if "intact doorway" in self.text_since(seq0) and not known:
            self.door_stats["diagonal_refused"] += 1      # msg_map marked the door; the square is not at fault
            return                                         # (a second refusal is counted: no loop without time)
        if after[:2] == before[:2] and self.cur_key == (self.bl(nh.NLE_BL_DNUM), self.bl(nh.NLE_BL_DLEVEL)):
            if self.trapped is not None:
                self.trap_stats["fail_not_counted"] += 1    # held by a trap: the square is not at fault
                return
            lv.fail[ty, tx] += 1
            if lv.fail[ty, tx] >= 6:
                lv.blocked[ty, tx] = True

    def trap_held(self, lv):
        """Still held by the trap the messages told of (failed steps then are not counted)? Forgotten once we are elsewhere, and after
        30 attempts (a missed 'free' message must not keep failed steps uncounted for ever)."""
        if self.trapped is None:
            return False
        if self.trapped[1:] != (lv.key, self.pos()) or self.trap_stats["_tries"] >= 30:
            self.trapped = None
            self.trap_stats["_tries"] = 0
            return False
        self.trap_stats["_tries"] += 1
        return True

    def kick(self, key):
        seq0 = self.msg_seq
        self.press(4, expect_prompt=True)   # ^D
        if self.obs["misc"][0] or "direction" in self.message().lower():
            self.press(key)
        else:
            self.settle()
        m = self.text_since(seq0)
        if "crashes open" in m or "shatters" in m or "breaks open" in m:
            self.level().locked.discard(self.last_move_target)
