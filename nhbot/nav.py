"""Path finding and single steps: Dijkstra over the remembered map, moving (door kicks, peaceful
monsters in the way, failed moves), walking toward a square or a set of squares."""
import heapq
from array import array
from collections import Counter

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import COLS, DELTA2KEY, NEIGH, ROWS

# Grotto Town (mines.des minetn-5, map (x, y) on screen (y, x + 2)): its down staircase lies behind the locked
# door at map (50, 6) in every one of its terrain variants; the way to that door has closed doors only
GROTTO_STAIR_DOOR = (6, 52)
# lock.c doopen_indir's answers to a step into a closed door (autoopen): lock.c:709-723, 735


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
_STEPS = tuple((dy * _W + dx, bool(dy and dx)) for dy, dx in NEIGH)
_INF = 1 << 30
_STEP_COST = np.ones(256, dtype=np.int64)           # cost of stepping into a square, by remembered kind
_STEP_COST[G.TRAP], _STEP_COST[G.BOULDER], _STEP_COST[G.DOOR_CLOSED] = 40, 15, 3
_LIVE_COST = np.zeros(256, dtype=np.int64)          # extra cost by what is seen there now
_LIVE_COST[G.MONSTER] = _LIVE_COST[G.INVIS] = 4
_pad_cost = np.full((ROWS + 2, _W), -1, dtype=np.int64)
_pad_door = np.zeros((ROWS + 2, _W), dtype=bool)
_pad_target = np.zeros((ROWS + 2, _W), dtype=bool)


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


class NavState:
    """State of walking: the grids cache, the last step, traps and doors (NavMixin)."""
    def __init__(self):
        self.grids_key, self.grids = None, None      # grids: the cache and its key
        self.last_move_target = None     # the square our last step went for (msg_map reads what it said)
        self.peaceful_waits = 0          # turns waited for a peaceful monster in our way
        self.peaceful_wait_by = Counter()   # ... by species
        self.peace_wait = None           # peace_wait_max: (level, square, turns in a row, last turn) of the wait
        self.peace_wait_blocks = 0       # ... squares given up
        self.shop_kicks_avoided = 0
        self.trapped = None              # (kind, level key, square) while a bear trap / pit / web holds us (msg_map)
        self.trap_stats = Counter()
        self.door_stats = Counter()
        self.mines_kick_stats = Counter()


class NavMixin:
    def nav_init(self):
        self.nav = NavState()

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
            for off, diag in _STEPS:
                j = i + off
                c = cost[j]
                if c < 0 or (diag and (di or door[j])):
                    continue
                nd = d + c
                # (A/B squeeze_path -- heavy, a rock-to-rock diagonal costs 100 more: -3571 [-5255, -1958], 6603)
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
        key = (self.pol.tick_no, self.steps, lv.key, self.shop_active(lv), tuple(self.perc.avoid_cells))
        if self.nav.grids_key != key:
            k_mem, k_live = self.kinds(lv), G.KIND[self.obs["glyphs"]]
            passable = self.passable_grid(lv, k_mem, k_live)
            for a in (k_mem, k_live, passable):
                a.setflags(write=False)
            self.nav.grids_key, self.nav.grids = key, (k_mem, k_live, passable)
        return self.nav.grids

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
        self.nav.last_move_target = target
        before = (y, x, self.turn())
        lv = self.level()
        self.trap_held(lv)                    # forgets the trap once we are out of it
        if target in lv.locked and self.kinds(lv)[target] != G.DOOR_CLOSED:
            # a monster opened it or it was broken since "This door is locked." -- kicking an open / broken door is
            # "You kick at empty space." (dokick.c:1251-1257), a turn each, for ever
            # (A/B door_kick_stale: -83 [-537, +375], median 7726 -> 7850, 52 of 1000 changed)
            lv.locked.discard(target)
            self.nav.door_stats["stale_locked"] += 1
        if target in lv.locked:
            if any(max(abs(cy - ty), abs(cx - tx)) <= 1 for cy, cx in lv.cfi):
                self.no_entry_mark(lv, target)    # closed shop: kicking the door angers the shopkeeper
                self.nav.shop_kicks_avoided += 1
                return
            if self.lock_door_step(lv, target):
                return                        # lock_tools: unlocked with the tool, silently (nhbot.locktools)
            if target == GROTTO_STAIR_DOOR and self.is_grotto(lv) \
                    and target not in lv.watch_warned:
                if self.law_nearby():         # dokick.c: the watch minds only a kick one of them can see
                    self.nav.mines_kick_stats["waited"] += 1
                    self.press("s")
                    return
                self.nav.mines_kick_stats["kicks"] += 1
                self.kick(key)
                return
            if lv.key[0] == 2:
                self.no_entry_mark(lv, target)    # never kick doors in the Mines (Minetown watch)
                return
            if self.law_nearby():
                lv.blocked[ty, tx] = True     # the watch / a shopkeeper in view: not now
                return
            self.kick(key)
            return
        if G.KIND[self.obs["glyphs"][target]] == G.MONSTER and self.peaceful_now(lv, target):
            # a peaceful monster in the way: wait for it to move (a shopkeeper in a doorway may never move;
            # making the square impassable for good after a few waits was tried and not taken -- peaceful_waits
            # counts)
            lv.fail[ty, tx] += 1
            self.nav.peaceful_waits += 1
            self.nav.peaceful_wait_by[G.monster_name(int(self.obs["glyphs"][target]))] += 1
            if self.opts.peace_wait_max:
                # peace_wait_max: waited that many turns in a row for this square -- it stays shut (Level.blocked,
                # forgotten with the other obstacles on a stalled level): the path goes round, or another goal is
                # taken (300029 waited 12 507 turns for one gnome; a peaceful can't be displaced: hack.c domove swaps
                # only with a pet)
                w = self.nav.peace_wait
                n = w[2] + 1 if w is not None and w[:2] == (lv.key, target) and w[3] >= self.turn() - 2 else 1
                self.nav.peace_wait = (lv.key, target, n, self.turn())
                if n > self.opts.peace_wait_max:
                    lv.blocked[ty, tx] = True
                    self.nav.peace_wait = None
                    self.nav.peace_wait_blocks += 1
                    return
            self.press("s")
            return
        seq0 = self.msg_seq
        known = lv.no_diag[ty, tx] or lv.no_diag[y, x]
        self.press(key)
        after = (*self.pos(), self.turn())
        if "intact doorway" in self.text_since(seq0) and not known:
            self.nav.door_stats["diagonal_refused"] += 1      # msg_map marked the door; the square is not at fault
            return                                         # (a second refusal is counted: no loop without time)
        if self.opts.door_resists and "The door resists!" in self.text_since(seq0):
            self.nav.door_stats["resisted"] += 1    # lock.c doopen: a stuck door, opened with P ~ (Str+Dex+Con)/3 in 20 a try
            return                                # -- try again; not the square's fault (80014: left after two)
        if "The door opens." in self.text_since(seq0):
            # autoopen opened it (hack.c:798 test_move -> lock.c doopen_indir, a turn) -- no failed step into the
            # square (door_stale, which also let "locked" / "resists" off, lost -2049: 40807 such steps)
            # (A/B door_open_ok: -1920 [-3808, -6], median 7726 -> 7768, 966 of 1000 changed)
            self.nav.door_stats["door_opened"] += 1
            return
        if after[:2] == before[:2] and self.cur_key == (self.bl(nh.NLE_BL_DNUM), self.bl(nh.NLE_BL_DLEVEL)):
            if self.nav.trapped is not None and self.nav.trapped[1:] == (lv.key, (y, x)) and after[2] > before[2]:
                # in the trap we were caught in, the step took its turn: held, for however long -- the square is not
                # at fault (A/B trap_noblock +76 [-1081, +1220], median +404)
                self.nav.trap_stats["fail_not_counted"] += 1
                return
            lv.fail[ty, tx] += 1
            if lv.fail[ty, tx] >= 6:
                lv.blocked[ty, tx] = True

    def not_stepping(self):
        """Our action is not a step (an attack): what the game says next is not about a square we went for."""
        self.nav.last_move_target = None

    def trap_caught(self, kind):
        """msg_map: a bear trap / pit / web holds us here (counted once per catch)."""
        if self.nav.trapped is None:
            self.nav.trap_stats[kind] += 1
        self.nav.trapped = (kind, self.cur_key, self.pos())

    def trap_freed(self):
        """msg_map: out of the trap that held us."""
        self.nav.trapped = None

    def trap_held(self, lv):
        """Still held by the trap the messages told of (failed steps that took a turn then are not counted)? Forgotten
        once we are elsewhere."""
        if self.nav.trapped is None:
            return False
        if self.nav.trapped[1:] != (lv.key, self.pos()):
            self.nav.trapped = None
            return False
        return True

    def mines_kick_stat(self, k):
        """Count a Minetown door-kick event the messages told of (the watch warned us, arrested us)."""
        self.nav.mines_kick_stats[k] += 1

    def kick(self, key):
        seq0 = self.msg_seq
        self.press(4, expect_prompt=True)   # ^D
        if self.obs["misc"][0] or "direction" in self.message().lower():
            self.press(key)
        else:
            self.settle()
        m = self.text_since(seq0)
        if "crashes open" in m or "shatters" in m:     # dokick.c:1286-1290
            self.level().locked.discard(self.nav.last_move_target)
