"""Sokoban (flag sokoban): up the branch from the level below the Oracle, the four levels solved by the plans of
nhbot/soko_data.py (tools/soko_solve.py made them offline), the prize taken, and back down.

The way in: a main-dungeon level of Dlvl 5-10 with two up staircases, one of them taken to the level above
(Level.stairs_to) -- the other is Sokoban's (dungeon.def: the branch is up from the Oracle's level + 1); or one
we took into Sokoban before. With nothing else left to do on that level (explore) and full HP, go up it.

In Sokoban: every level is premapped (sokoban.des FLAGS), so on arrival the walls tell which of the eight
variants this is and where it lies on the screen (soko_identify). The state is read from the map each tick --
the boulders (their glyphs) and the traps still open -- and matched against the plan's states; the next push
is the plan's at that state: walk to the square behind the boulder (no squeezing between boulders, never
diagonally through a door, never onto a trap) and step into it. Nothing in the plan depends on where we stand,
so a fight, a meal or a pick-up in between is harmless. A state that matches none (a boulder where the plan
never had one), a push the game refuses for long, or too many turns on a level: the level is given up and
Sokoban with it (we go back down). The plan done: up the stairs -- on the top level kick the zoo's locked door,
then fetch the prize (bag of holding or amulet of reflection) from its closet, wear an amulet.

While in Sokoban the generic code must not break the puzzle: boulders and traps are impassable to every other
walk (mapmem.passable_grid), unknown scrolls are not read (scroll of earth makes boulders), and the explore step
is this module's.
"""
import time
from collections import Counter, deque

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import COLS, DELTA2KEY, ROWS
from nhbot.soko_data import LEVELS

SOKO_DNUM = 4             # dungeon.def: Dungeons of Doom 0, Gehennom 1, Mines 2, Quest 3, Sokoban 4
SOKO_LEVEL_TURNS = 4000   # a level not solved in this many turns is given up
SOKO_RETREAT = 15         # turns away from a peaceful monster that blocks the plan
SOKO_STUCK = 400          # turns with the plan not advancing (a refused push, an unreachable square): give up
BEHIND_RE = ("behind the boulder", "on the other side")   # moverock: a monster where the boulder would go
ORTHO = ((-1, 0), (1, 0), (0, -1), (0, 1))
DIRS8 = ORTHO + ((-1, -1), (-1, 1), (1, -1), (1, 1))


def plan_states(lv):
    """The (boulders, open traps) before each push of the plan and after the last."""
    bs, ts = set(map(tuple, lv["boulders"])), set(map(tuple, lv["traps"]))
    out = [(frozenset(bs), frozenset(ts))]
    for (b, d) in lv["plan"] or ():
        b = tuple(b)
        to = (b[0] + d[0], b[1] + d[1])
        bs.discard(b)
        if to in ts:
            ts.discard(to)
        else:
            bs.add(to)
        out.append((frozenset(bs), frozenset(ts)))
    return out


STATES = {name: plan_states(lv) for name, lv in LEVELS.items()}


class SokoLevel:
    """What we know of one Sokoban level: its variant, where it lies on the map, how far the plan got."""

    def __init__(self, name, off):
        self.name, self.off = name, off
        self.lv = LEVELS[name]
        self.states = STATES[name]
        self.i = 0                    # the plan's state we were at last
        self.failed = False
        self.solved = False
        self.since = None             # turn the plan last advanced
        self.blocked = -1             # turn a push was refused for a monster beyond the boulder
        self.retreat_until = -1       # soko_retreat: keep away from a peaceful monster in our way till then
        self.retreat_from = None
        self.last_i = -1
        rows = self.lv["map"]
        self.h, self.w = len(rows), len(rows[0])
        self.doors = set(map(tuple, self.lv["doors"]))
        self.floor = {(r, c) for r in range(self.h) for c in range(self.w) if rows[r][c] == "."} | self.doors

    def to_map(self, p):
        return p[0] + self.off[0], p[1] + self.off[1]

    def from_map(self, p):
        return p[0] - self.off[0], p[1] - self.off[1]


class SokobanMixin:
    def sokoban_init(self):
        self.soko = {}                  # level key -> SokoLevel
        self.soko_done = False          # the top level's prize taken (or the zoo given up)
        self.soko_failed = False        # a level given up: Sokoban is over for this game
        self.soko_stats = Counter()
        self.soko_secs = 0.0            # compute time spent in this module (the tick that acted included)

    # ------------------------------------------------------------------ in the main dungeon
    def soko_entrance(self):
        """(level key, squares) of Sokoban's up staircase on the main level that has it, or None: a staircase we
        took into Sokoban (Level.stairs_to), or the second up staircase of a main Dlvl 5-10 level whose other
        one we know leads to the level above."""
        for key, lv in self.levels.items():
            if key[0] != 0:
                continue
            marks = {p: k for p, k in lv.stairs_to.items() if k[0] == SOKO_DNUM}
            got = self.linked_stairs(lv, marks, G.UPSTAIR) if marks else set()
            if not got and 5 <= key[1] <= 10:
                ups = {(int(y), int(x)) for y, x in zip(*np.nonzero(self.kinds(lv) == G.UPSTAIR))} - lv.not_stairs
                if len(ups) == 2:
                    main = self.linked_stairs(lv, {p: k for p, k in lv.stairs_to.items() if k == (0, key[1] - 1)},
                                              G.UPSTAIR) & ups
                    if len(main) == 1:
                        got = ups - main
            if got:
                return key, got
        return None

    def sokoban_trip_step(self, lv, grids, nothing_left):
        if not self.opts.sokoban:
            return False
        t0 = time.perf_counter()
        try:
            return self._sokoban_trip_step(lv, grids, nothing_left)
        finally:
            self.soko_secs += time.perf_counter() - t0

    def _sokoban_trip_step(self, lv, grids, nothing_left):
        """Main dungeon, Sokoban not done: to the level with its entrance, and -- with nothing left to do there
        (nothing_left) and full HP -- up into it. True if it used the turn."""
        if not self.opts.sokoban or self.soko_done or self.soko_failed or lv.key[0] != 0:
            return False
        ent = self.soko_entrance()
        if ent is None:
            return False
        key, ups = ent
        if key != lv.key:
            if not nothing_left:
                return False
            if self.level_travel_step(lv, grids, key, "soko", "soko_travel"):
                self.soko_stats["travel"] += 1
                return True
            return False
        if not nothing_left:
            return False
        hp, maxhp = self.bl(nh.NLE_BL_HP), self.bl(nh.NLE_BL_HPMAX)
        if hp < maxhp and not self.visible_hostiles(lv):
            self.cur_act = "rest"
            self.soko_stats["rest"] += 1
            self.press("2"); self.press("0"); self.press("s")
            return True
        mask = np.zeros_like(grids[0], dtype=bool)
        for p in ups:
            mask[p] = True
        self.cur_act = "soko"
        if mask[self.pos()]:
            self.soko_stats["enter"] += 1
        return self.stairs_step(lv, grids, mask, "<")

    # ------------------------------------------------------------------ in Sokoban
    def in_sokoban(self, lv):
        return lv is not None and lv.key[0] == SOKO_DNUM

    def soko_identify(self, lv):
        """The variant and its offset on the map: the one whose walls all show as walls there, and whose floor
        shows none. None if no variant fits (yet)."""
        k = self.kinds(lv)
        wall = k == G.WALL
        known = k != G.UNKNOWN
        best = None
        for name, data in LEVELS.items():
            rows = data["map"]
            h, w = len(rows), len(rows[0])
            walls = [(r, c) for r in range(h) for c in range(w) if rows[r][c] in "-|"]
            floors = [(r, c) for r in range(h) for c in range(w) if rows[r][c] == "."]
            wr = np.array([p[0] for p in walls]); wc = np.array([p[1] for p in walls])
            fr = np.array([p[0] for p in floors]); fc = np.array([p[1] for p in floors])
            for oy in range(0, ROWS - h + 1):
                for ox in range(0, COLS - w + 1):
                    if not wall[wr + oy, wc + ox].all():
                        continue
                    if wall[fr + oy, fc + ox].any() or not known[fr + oy, fc + ox].mean() > 0.9:
                        continue
                    n = int(wall[wr + oy, wc + ox].sum())
                    if best is None or n > best[0]:
                        best = (n, name, (oy, ox))
        return None if best is None else SokoLevel(best[1], best[2])

    def soko_level(self, lv):
        st = self.soko.get(lv.key)
        if st is None:
            st = self.soko_identify(lv)
            if st is None:
                self.soko_stats["unidentified"] += 1
                return None
            self.soko[lv.key] = st
            self.soko_stats["level_" + st.name] += 1
        return st

    def soko_state(self, lv, st):
        """(boulders, open traps) of the variant now, in its coordinates (from the map memory)."""
        top = G.KIND[lv.under]
        terr = G.KIND[lv.terrain]
        oy, ox = st.off
        bs = frozenset(p for p in st.floor if top[p[0] + oy, p[1] + ox] == G.BOULDER)
        ts = frozenset(tuple(t) for t in st.lv["traps"] if terr[t[0] + oy, t[1] + ox] == G.TRAP)
        return bs, ts

    def soko_match(self, st, bs, ts):
        """The plan's state index we are at: the first from st.i on whose traps are ours and whose boulders we
        see (more boulders seen: mimics on the top level). None if none."""
        for i in range(st.i, len(st.states)):
            pbs, pts = st.states[i]
            if pts == ts and pbs <= bs and (len(bs) - len(pbs) <= 2 or pbs == bs):
                return i
        return None

    def soko_walk(self, st, start, goal, bs, ts):
        """First step (variant coords) of a shortest walk from start to goal by Sokoban's rules, or None."""
        if start == goal:
            return start
        free = lambda p: p in st.floor and p not in bs
        prev = {start: None}
        q = deque([start])
        while q:
            cur = q.popleft()
            for dr, dc in DIRS8:
                n = (cur[0] + dr, cur[1] + dc)
                if n in prev or not free(n) or n in ts:
                    continue
                if dr and dc and (cur in st.doors or n in st.doors
                                  or (not free((cur[0] + dr, cur[1])) and not free((cur[0], cur[1] + dc)))):
                    continue
                prev[n] = cur
                if n == goal:
                    while prev[n] != start:
                        n = prev[n]
                    return n
                q.append(n)
        return None

    def soko_step_to(self, lv, st, target, bs, ts, extra=frozenset()):
        """One step toward target (variant coords). True if it acted. A peaceful monster on the next square:
        back off (soko_retreat) -- in a dead end it waits for us to leave its only way out. No way at all but
        through a boulder the plan doesn't know (extra: on the top level a giant mimic posing as one): attack
        that boulder ('F'), the mimic shows itself and the fight steps take over."""
        here = st.from_map(self.pos())
        nxt = self.soko_walk(st, here, target, bs, ts)
        if nxt is None and extra:
            nxt = self.soko_walk(st, here, target, bs - extra, ts)
            if nxt is not None and nxt in extra:
                self.soko_stats["mimic_attack"] += 1
                y, x = self.pos()
                ty, tx = st.to_map(nxt)
                self.press("F")
                self.press(DELTA2KEY[(ty - y, tx - x)])
                return True
        if nxt is None:
            return False
        if nxt == here:
            return True
        mp = st.to_map(nxt)
        if G.KIND[int(self.obs["glyphs"][mp])] == G.MONSTER and self.peaceful_now(lv, mp):
            return self.soko_retreat(lv, st, mp, bs, ts)
        self.move(mp)
        return True

    def soko_retreat(self, lv, st, blocker, bs, ts):
        """A peaceful monster in the way: for SOKO_RETREAT turns stand at least 4 squares from it (the nearest
        such square we reach), then try again."""
        if st.retreat_until < self.turn():
            st.retreat_until = self.turn() + SOKO_RETREAT
            st.retreat_from = st.from_map(blocker)
            self.soko_stats["retreat"] += 1
        return self.soko_retreat_step(lv, st, bs, ts)

    def soko_retreat_step(self, lv, st, bs, ts):
        here = st.from_map(self.pos())
        far = lambda p: max(abs(p[0] - st.retreat_from[0]), abs(p[1] - st.retreat_from[1])) >= 4
        if far(here):
            return self.soko_wait()
        cands = sorted((abs(p[0] - here[0]) + abs(p[1] - here[1]), p) for p in st.floor
                       if far(p) and p not in bs and p not in ts)
        for _, p in cands[:12]:
            nxt = self.soko_walk(st, here, p, bs, ts)
            if nxt is not None and nxt != here:
                self.move(st.to_map(nxt))
                return True
        return self.soko_wait()

    def sokoban_step(self, lv):
        """In Sokoban: the explore step's place. True always (we never explore here)."""
        if not self.in_sokoban(lv):
            return False
        t0 = time.perf_counter()
        try:
            return self._sokoban_step(lv)
        finally:
            self.soko_secs += time.perf_counter() - t0

    def _sokoban_step(self, lv):
        self.cur_act = "soko"
        st = self.soko_level(lv)
        if st is None or st.failed or self.soko_failed or self.soko_done:
            return self.soko_leave(lv, st)
        if st.lv["plan"] is None:
            return self.soko_give_up(lv, st, "no_plan")
        if self.turn() - (lv.entered_turn or self.turn()) > SOKO_LEVEL_TURNS:
            return self.soko_give_up(lv, st, "turns")
        bs, ts = self.soko_state(lv, st)
        i = self.soko_match(st, bs, ts)
        if i is None:
            return self.soko_give_up(lv, st, "deviation")
        st.i = i
        if i != st.last_i or st.since is None:
            st.since, st.last_i = self.turn(), i
        stuck = self.turn() - st.since
        if stuck > SOKO_STUCK and i < len(st.lv["plan"]):
            return self.soko_give_up(lv, st, "stuck")
        extra = bs - st.states[i][0]
        if st.retreat_until >= self.turn():
            return self.soko_retreat_step(lv, st, bs, ts)
        if i < len(st.lv["plan"]):
            b, d = st.lv["plan"][i]
            b, d = tuple(b), tuple(d)
            stand = (b[0] - d[0], b[1] - d[1])
            here = st.from_map(self.pos())
            if here == stand:
                if st.blocked == self.turn():
                    self.soko_stats["wait_behind"] += 1
                    return self.soko_wait()          # a monster beyond the boulder: the push costs no time -- wait
                seq = self.msg_seq
                self.soko_stats["push"] += 1
                self.move(st.to_map(b))
                if any(w in self.text_since(seq) for w in BEHIND_RE):
                    st.blocked = self.turn()
                return True
            if self.soko_step_to(lv, st, stand, bs, ts, extra):
                return True
            return self.soko_give_up(lv, st, "no_way_to_push") if stuck > SOKO_STUCK // 2 else self.soko_wait()
        return self.soko_finish(lv, st, bs, ts, extra)

    def soko_wait(self):
        self.press("s")
        return True

    def soko_finish(self, lv, st, bs, ts, extra):
        """The plan done: up the stairs; on the top level into the zoo for the prize."""
        if not st.solved:
            st.solved = True
            self.soko_stats["solved_" + st.name[:5]] += 1
        goal = tuple(st.lv["goal"])
        here = st.from_map(self.pos())
        if st.lv["up"] is not None:
            if here == goal:
                self.soko_stats["up"] += 1
                self.took_stairs = True
                self.press("<")
                return True
            return self.soko_step_to(lv, st, goal, bs, ts, extra) or self.soko_wait()
        return self.soko_prize(lv, st, bs, ts, extra)

    def soko_prize(self, lv, st, bs, ts, extra):
        """Top level: open the zoo's locked door (west of the goal), walk to the closets on the far side of the
        zoo (the prize lies in one of them), pick up an amulet or a bag there, put the amulet on. Done after
        the closets were seen (or the prize taken)."""
        closets = [(p[0], p[1] - 1) for p, s in st.lv["doors"].items() if s == "closed"]
        here = st.from_map(self.pos())
        for p in closets:
            if here == p:
                seq = self.msg_seq
                self.pickup_matching(["amulet", "bag"], own=True)
                got = self.text_since(seq)
                st.closet_done = getattr(st, "closet_done", set()) | {p}
                if "amulet" in got or "bag" in got:
                    self.soko_stats["prize"] += 1
                    am = next((it for it in self.items() if it.ocls == nh.AMULET_CLASS and not it.on_body), None)
                    if am is not None:
                        self.jewelry_put_on(am)
                        self.soko_stats["amulet_worn"] += 1
                    self.soko_done = True
                return True
        todo = [p for p in closets if p not in getattr(st, "closet_done", set())]
        if not todo:
            self.soko_done = True
            self.soko_stats["prize_missing"] += 1
            return self.soko_leave(lv, st)
        # the closets with the prize first: an amulet or tool glyph there
        def has_item(p):
            k = G.KIND[lv.under[st.to_map(p)]]
            return k in (G.OBJECT,)
        todo.sort(key=lambda p: (not has_item(p), abs(p[0] - here[0]) + abs(p[1] - here[1])))
        tgt = todo[0]
        if self.soko_step_to(lv, st, tgt, bs, ts, extra):
            return True
        self.soko_stats["zoo_no_way"] += 1
        st.closet_done = getattr(st, "closet_done", set()) | {tgt}
        return self.soko_wait()

    def soko_give_up(self, lv, st, why):
        if st is not None and not st.failed:
            st.failed = True
            self.soko_failed = True
            self.soko_stats["fail_" + why] += 1
            self.soko_stats["fail_at_" + st.name[:5]] += 1
        return self.soko_leave(lv, st)

    def soko_leave(self, lv, st):
        """Back down: to this level's down staircase (where we arrived), by Sokoban's rules, and down it. No such
        way (a level we gave up, boulders across it): the generic explore, which pushes boulders like anywhere
        else now (mapmem.passable_grid) and goes down the stairs when it can."""
        self.cur_act = "soko_leave"
        if st is not None:
            arrive = tuple(st.lv["arrive"])
            here = st.from_map(self.pos())
            if here == arrive:
                self.took_stairs = True
                self.press(">")
                self.soko_stats["left_level"] += 1
                return True
            bs, ts = self.soko_state(lv, st)
            if self.soko_step_to(lv, st, arrive, bs, ts):
                return True
        self.soko_stats["leave_explore"] += 1
        self.explore(lv)
        return True
