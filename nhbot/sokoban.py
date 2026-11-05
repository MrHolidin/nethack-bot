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
so a fight, a meal or a pick-up in between is harmless. A state that matches none (a monster's scroll of earth
dropped boulders): solved afresh from what we see (soko_solver, a few seconds of compute at most). No new plan,
a push the game refuses for long, or too many turns on a level: the level is given up and Sokoban with it (we
go back down). The plan done: up the stairs -- on the top level kick the zoo's locked door,
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
from nhbot import soko_solver
from nhbot.consts import COLS, DELTA2KEY, FOUNTAIN_GLYPH, ROWS, ray_squares
from nhbot.soko_data import LEVELS

SOKO_DNUM = 4             # dungeon.def: Dungeons of Doom 0, Gehennom 1, Mines 2, Quest 3, Sokoban 4
SOKO_LEVEL_TURNS = 4000   # a level not solved in this many turns is given up
SOKO_BEHIND_WAITS = 10    # waits for a monster beyond the boulder before we go round to attack it
SOKO_RETREAT = 15         # turns away from a peaceful monster that blocks the plan
SOKO_SEARCH_TURNS = 500  # turns spent searching for hidden passages on the level below the Oracle (no entrance seen)
SOKO_REPLANS = 3          # re-plans (soko_replan) a level at most
SOKO_REPLAN_SECS = 2.0    # compute for one re-plan
SOKO_DOOR_WAITS = 50      # turns between kicks at a locked door that refused one (wounded legs)
SOKO_LEAVE_EXPLORE = 500  # ticks of the generic explore to leave a level given up, then we only search
SOKO_STUCK = 400          # turns with the plan not advancing (a refused push, an unreachable square): give up
BEHIND_RE = ("behind the boulder", "on the other side")   # moverock: a monster where the boulder would go
FILL_RE = ("fills a pit", "plugs a hole", "plugs a trap door")  # do.c boulder_hits_pool / hack.c moverock
ZOO_QUIET = 8             # turns with the zoo's monsters in view all where they were: the wave is over (the rest sleep)
ZOO_HOLD_MAX = 300        # turns at most spent holding the zoo's doorway
ZOO_BACK_HP = 0.7         # in the zoo below this share of HP with its monsters moving: back to the doorway
ZOO_ENTER_HP = 0.85       # into the zoo (its door open) only above this share of HP: rested outside first
ZOO_PRAY_WAIT = 1500      # turns at most waited at the zoo's door, after the level is solved, for a prayer in hand
ORTHO = ((-1, 0), (1, 0), (0, -1), (0, 1))
DIRS8 = ORTHO + ((-1, -1), (-1, 1), (1, -1), (1, 1))


def plan_states(boulders, traps, plan):
    """The (boulders, open traps) before each push of the plan and after the last."""
    bs, ts = set(map(tuple, boulders)), set(map(tuple, traps))
    out = [(frozenset(bs), frozenset(ts))]
    for (b, d) in plan or ():
        b = tuple(b)
        to = (b[0] + d[0], b[1] + d[1])
        bs.discard(b)
        if to in ts:
            ts.discard(to)
        else:
            bs.add(to)
        out.append((frozenset(bs), frozenset(ts)))
    return out


STATES = {name: plan_states(lv["boulders"], lv["traps"], lv["plan"]) for name, lv in LEVELS.items()}
SOLVERS = {}                  # variant -> soko_solver.Level, made on the first re-plan
CENTAUR_STATUES = [nh.GLYPH_STATUE_OFF + i for i in range(nh.NUMMONS) if "centaur" in nh.permonst(i).mname]


class SokoLevel:
    """What we know of one Sokoban level: its variant, where it lies on the map, how far the plan got."""

    def __init__(self, name, off):
        self.name, self.off = name, off
        self.lv = LEVELS[name]
        self.plan = self.lv["plan"]   # the pushes we follow: the variant's, or one made here (soko_replan)
        self.states = STATES[name]
        self.replans = 0
        self.hallu_seen = False       # we hallucinated here: items in the memory may be boulders (soko_state)
        self.leave_explore = 0        # soko_leave: ticks the generic explore had to find the way down
        self.door_wait_until = -1     # no kicking a locked door till then: our legs refused (soko_step_to)
        self.i = 0                    # the plan's state we were at last
        self.failed = False
        self.solved = False
        self.since = None             # turn the plan last advanced
        self.blocked = -1             # turn a push was refused for a monster beyond the boulder
        self.behind_waits = 0         # turns waited in a row for a monster beyond the boulder to move
        self.retreat_until = -1       # soko_retreat: keep away from a peaceful monster in our way till then
        self.retreat_from = None
        self.last_i = -1
        self.closet_done = set()      # top level: the prize closets and the zoo piles looked into
        self.zoo_seen = frozenset()   # top level: the zoo's hostiles in view (variant coords) ...
        self.zoo_moved = -1           # ... and the turn that set last changed
        self.zoo_hold = 0             # turns spent holding the doorway
        self.solved_turn = None       # turn the plan was done (soko_prize)
        self.prize_inv0 = None        # soko_prize_items() when the prize hunt began
        self.filled = set()           # traps our pushes filled (the message said so): closed whatever the map shows
        rows = self.lv["map"]
        self.h, self.w = len(rows), len(rows[0])
        self.doors = set(map(tuple, self.lv["doors"]))
        self.floor = {(r, c) for r in range(self.h) for c in range(self.w) if rows[r][c] == "."} | self.doors
        # top level: the zoo's locked door (the goal is east of it) and the zoo, the room behind it
        self.zoo_door = next((p for p, s in self.lv["doors"].items() if s == "locked"), None)
        self.zoo = set()
        if self.zoo_door is not None:
            todo = [(self.zoo_door[0], self.zoo_door[1] - 1)]
            while todo:
                p = todo.pop()
                if p in self.zoo or p not in self.floor or p in self.doors:
                    continue
                self.zoo.add(p)
                todo += [(p[0] + dr, p[1] + dc) for dr, dc in DIRS8]

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
        self.soko_search_from = None    # turn we began searching the level below the Oracle for the entrance
        self.soko_oracle = None         # the Oracle's Dlvl once seen (soko_oracle_dlvl)
        self.soko_ent = None            # Sokoban's entrance once found (soko_entrance)

    # ------------------------------------------------------------------ in the main dungeon
    def soko_entrance(self):
        """(level key, squares) of Sokoban's up staircase on the main level that has it, or None: a staircase we
        took into Sokoban (Level.stairs_to), or the second up staircase of a main Dlvl 5-10 level whose other
        one we know leads to the level above."""
        if self.soko_ent is not None:
            key, got = self.soko_ent
            if not got & self.levels[key].not_stairs:      # found once: it stays, unless it proved no staircase
                return self.soko_ent
            self.soko_ent = None
        for key, lv in self.levels.items():
            if key[0] != 0 or not 5 <= key[1] <= 10:      # the entrance: the Oracle's Dlvl (5-9) plus one
                continue
            marks = {p: k for p, k in lv.stairs_to.items() if k[0] == SOKO_DNUM}
            got = self.linked_stairs(lv, marks, G.UPSTAIR) if marks else set()
            if not got:
                ups = {(int(y), int(x)) for y, x in zip(*np.nonzero(self.kinds(lv) == G.UPSTAIR))} - lv.not_stairs
                if len(ups) == 2:
                    main = self.linked_stairs(lv, {p: k for p, k in lv.stairs_to.items() if k == (0, key[1] - 1)},
                                              G.UPSTAIR) & ups
                    if len(main) == 1:
                        got = ups - main
            if got:
                self.soko_ent = (key, got)
                return self.soko_ent
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
            return self.soko_search_step(lv, grids, nothing_left)
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

    def soko_oracle_dlvl(self):
        """Dlvl of the Oracle's level if we saw it, else None: main Dlvl 5-9 with centaur statues (oracle.des puts
        them round the centre room, whose four fountains we may not have seen) or four fountains."""
        lv = self.level()                    # what we see of a level changes only while we are on it
        if self.soko_oracle is None and lv.key[0] == 0 and 5 <= lv.key[1] <= 9 and (
                np.isin(lv.under, CENTAUR_STATUES).sum() >= 2
                or (self.terrain_glyphs(lv) == FOUNTAIN_GLYPH).sum() >= 4):
            self.soko_oracle = lv.key[1]
        return self.soko_oracle

    def soko_search_step(self, lv, grids, nothing_left):
        """The level below the Oracle has Sokoban's up staircase. Explored with only one up staircase seen: the
        rest of it lies past a hidden door or corridor -- search (explore.search_mode), SOKO_SEARCH_TURNS at most.
        True if it used the turn."""
        if not nothing_left or self.soko_oracle_dlvl() is None or lv.key != (0, self.soko_oracle_dlvl() + 1):
            return False
        t = self.turn()
        if self.soko_search_from is None:
            self.soko_search_from = t
        if t - self.soko_search_from > SOKO_SEARCH_TURNS:
            return False
        self.soko_stats["search"] += 1
        self.search_mode(lv, grids)
        return True

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
        me = st.from_map(self.pos())          # the memory keeps what lay where we stand: a boulder we just pushed on
        bs = frozenset(p for p in st.floor if top[p[0] + oy, p[1] + ox] == G.BOULDER and p != me)
        if st.hallu_seen:
            # hallucinating, the boulders showed as random objects -- and the memory keeps that till we see the
            # square again: an item where the plan's state has a boulder is that boulder
            bs |= {p for p in st.states[st.i][0] if p != me and G.IS_COVERED[top[p[0] + oy, p[1] + ox]]}
        # an open trap: shown as one; or an item on it (a level's random objects lie on traps too, we arrive to
        # see the item) with the trap under it -- or never seen there; unless a push of ours filled it (an item on
        # the filled square hides that from the map). A filled pit or hole shows the floor. A boulder shown on a
        # trap we did not fill is a giant mimic posing as one (a real one would have filled it): still open.
        def is_open(t):
            k = top[t[0] + oy, t[1] + ox]
            return k in (G.TRAP, G.BOULDER) or (G.IS_COVERED[k] and terr[t[0] + oy, t[1] + ox] in (G.TRAP, G.UNKNOWN))
        ts = frozenset(tuple(t) for t in st.lv["traps"] if tuple(t) not in st.filled and is_open(t))
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
        if self.turn() < st.door_wait_until and self.kinds(lv)[mp] == G.DOOR_CLOSED:
            # a locked door we could not kick (wounded legs: no turn passes, it would loop): wait, try again later
            self.soko_stats["door_wait"] += 1
            return self.soko_wait()
        seq = self.msg_seq
        self.move(mp)
        if "no shape for kicking" in self.text_since(seq):
            st.door_wait_until = self.turn() + SOKO_DOOR_WAITS
        return True

    def soko_attack_at(self, lv, st, target, bs, ts):
        """Fight whatever is on target (variant coords): from a square next to it, 'F' toward it; else walk to
        the nearest such square. Done (behind_waits reset) once a push works again or nothing answers. False if
        no square next to it is reachable."""
        here = st.from_map(self.pos())
        if max(abs(here[0] - target[0]), abs(here[1] - target[1])) == 1:
            seq = self.msg_seq
            self.soko_stats["behind_attack"] += 1
            y, x = self.pos()
            ty, tx = st.to_map(target)
            self.press("F")
            self.press(DELTA2KEY[(ty - y, tx - x)])
            said = self.text_since(seq)
            if "harmlessly" in said or "You attack thin air" in said or "nothing" in said.lower():
                st.behind_waits = 0          # nothing there (any more): back to the plan
            return True
        for dr, dc in DIRS8:
            n = (target[0] + dr, target[1] + dc)
            if n in st.floor and n not in bs and n not in ts:
                nxt = self.soko_walk(st, here, n, bs, ts)
                if nxt is not None and nxt != here:
                    self.move(st.to_map(nxt))
                    return True
        return False                         # no way to its side

    def soko_throw_over(self, st, d):
        """Throw a missile from the push square along the push (over the boulder) at the monster beyond it -- a
        missile, else a gem or a spare weapon (combat.expendables). True if thrown; a few more push tries before
        the next throw."""
        ocls = {it.letter: it.ocls for it in self.items()}
        th = [] if self.hallu_blind_ranged() else \
            [t for t in self.expendables() if ocls.get(t[0]) in (nh.WEAPON_CLASS, nh.GEM_CLASS)]
        if not th:
            return False
        y, x = self.pos()
        self.soko_stats["behind_throw"] += 1
        self.throw(th[0][0], DELTA2KEY[d], ray_squares(y, x, d[0], d[1]))
        st.behind_waits = SOKO_BEHIND_WAITS - 3
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
        if st.plan is None:
            return self.soko_give_up(lv, st, "no_plan")
        cond = int(self.last_bl[nh.NLE_BL_CONDITION])
        st.hallu_seen |= bool(cond & nh.BL_MASK_HALLU)
        if cond & (nh.BL_MASK_HALLU | nh.BL_MASK_CONF | nh.BL_MASK_STUN | nh.BL_MASK_BLIND):
            # a confused or stunned push may go any way; hallucinating, boulders look like anything; blind,
            # the map isn't kept: wait it out (the other steps still fight)
            self.soko_stats["impaired_wait"] += 1
            return self.soko_wait()
        if not st.solved and self.turn() - (lv.entered_turn or self.turn()) > SOKO_LEVEL_TURNS:
            return self.soko_give_up(lv, st, "turns")
        bs, ts = self.soko_state(lv, st)
        i = self.soko_match(st, bs, ts)
        if i is None and self.soko_replan(st, bs, ts):
            i = 0
        if i is None:
            return self.soko_give_up(lv, st, "deviation")
        st.i = i
        if i != st.last_i or st.since is None:
            st.since, st.last_i, st.behind_waits = self.turn(), i, 0
        stuck = self.turn() - st.since
        if stuck > SOKO_STUCK and i < len(st.plan):
            # the push won't go (a monster stays beyond the boulder): a plan that leaves that square alone
            b, d = st.plan[i]
            if self.soko_replan(st, bs, ts, walls=((b[0] + d[0], b[1] + d[1]),)):
                return self.soko_wait()
            if not self.soko_trapped(st, bs, ts):
                return self.soko_give_up(lv, st, "stuck")
            # the way back down is shut behind us (Sokoban's pushes go one way): giving up would leave us here
            # for good -- wait on, the monster may yet go or die
            st.since = self.turn()
            self.soko_stats["trapped_wait"] += 1
        extra = bs - st.states[i][0]
        if st.retreat_until >= self.turn():
            return self.soko_retreat_step(lv, st, bs, ts)
        if i < len(st.plan):
            b, d = st.plan[i]
            b, d = tuple(b), tuple(d)
            stand = (b[0] - d[0], b[1] - d[1])
            here = st.from_map(self.pos())
            beyond = (b[0] + d[0], b[1] + d[1])
            if st.behind_waits > SOKO_BEHIND_WAITS:
                # it doesn't go away (a mimic posing as an object, something stuck between the boulder and a
                # trap): attack it from beside, else throw over the boulder at it (missiles fly over boulders)
                if self.soko_attack_at(lv, st, beyond, bs, ts):
                    return True
                if here == stand and self.soko_throw_over(st, d):
                    return True
                st.behind_waits = 0
                return self.soko_wait()
            if here == stand:
                if st.blocked == self.turn():
                    self.soko_stats["wait_behind"] += 1
                    st.behind_waits += 1
                    return self.soko_wait()          # a monster beyond the boulder: the push costs no time -- wait
                seq = self.msg_seq
                self.soko_stats["push"] += 1
                self.move(st.to_map(b))
                said = self.text_since(seq)
                if any(w in said for w in FILL_RE):
                    st.filled.add(beyond)
                if any(w in said for w in BEHIND_RE):
                    st.blocked = self.turn()
                else:
                    st.behind_waits = 0
                return True
            if self.soko_step_to(lv, st, stand, bs, ts, extra):
                return True
            return self.soko_give_up(lv, st, "no_way_to_push") if stuck > SOKO_STUCK // 2 else self.soko_wait()
        return self.soko_finish(lv, st, bs, ts, extra)

    def soko_trapped(self, st, bs, ts):
        """No way back to the staircase we arrived on (by Sokoban's rules)."""
        here = st.from_map(self.pos())
        arrive = tuple(st.lv["arrive"])
        return here != arrive and self.soko_walk(st, here, arrive, bs, ts) is None

    def soko_replan(self, st, bs, ts, walls=()):
        """The level no longer matches the plan (a monster's scroll of earth dropped boulders, a wand of striking
        broke one): solve it afresh from what we see (soko_solver, SOKO_REPLAN_SECS of compute), at most
        SOKO_REPLANS times a level. True if a new plan was found -- we follow it from its start."""
        if st.replans >= SOKO_REPLANS:
            return False
        st.replans += 1
        solver = SOLVERS.get(st.name)
        if solver is None:
            solver = SOLVERS[st.name] = soko_solver.Level(st.lv)
        here = st.from_map(self.pos())
        plan = solver.solve(budget=SOKO_REPLAN_SECS, start=(bs, ts, here), walls=walls) if here in st.floor else None
        if plan is None:
            self.soko_stats["replan_fail"] += 1
            return False
        self.soko_stats["replan"] += 1
        st.plan, st.states, st.i, st.last_i = plan, plan_states(bs, ts, plan), 0, -1
        return True

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
        if not self.opts.soko_zoo:
            self.soko_done = True
            self.soko_stats["zoo_skipped"] += 1
            return self.soko_leave(lv, st)
        return self.soko_prize(lv, st, bs, ts, extra)

    def soko_prize(self, lv, st, bs, ts, extra):
        """Top level: open the zoo's locked door (west of the goal), walk to the closets on the far side of the
        zoo (the prize lies in one of them), pick up an amulet or a bag there, put the amulet on. Done after
        the closets were seen (or the prize taken)."""
        if st.prize_inv0 is None:
            st.prize_inv0 = self.soko_prize_items()
        hp, maxhp = self.bl(nh.NLE_BL_HP), self.bl(nh.NLE_BL_HPMAX)
        here = st.from_map(self.pos())
        shut = self.kinds(lv)[st.to_map(st.zoo_door)] == G.DOOR_CLOSED
        if st.solved_turn is None:
            st.solved_turn = self.turn()
        y, x = self.pos()
        vis = self.visible_hostiles(lv)
        near = any(max(abs(p[0] - y), abs(p[1] - x)) <= 2 for p, _ in vis)
        # the zoo wakes all at once when its door is kicked (dokick.c wake_nearby): full HP and a prayer in hand
        # first (waiting ZOO_PRAY_WAIT turns at most for the prayer); once open, into the zoo only fit -- rest
        # outside it first (its monsters still asleep in view don't stop that)
        if (shut and not vis and (hp < maxhp or (not self.can_pray()
                                                 and self.turn() - st.solved_turn < ZOO_PRAY_WAIT))) \
                or (not shut and not near and here not in st.zoo and hp < maxhp * ZOO_ENTER_HP):
            self.soko_stats["zoo_rest"] += 1
            self.cur_act = "rest"
            self.press("2"); self.press("0"); self.press("s")
            return True
        closets = [(p[0], p[1] - 1) for p, s in st.lv["doors"].items() if s == "closed"]
        # a monster of the zoo may have carried the prize off (they go for an amulet of reflection) and dropped
        # it where it died -- under its corpse, the pile shows its top: the piles in the zoo and on its door
        # are looked into too
        todo = [p for p in closets + sorted(self.soko_piles(lv, st)) if p not in st.closet_done]
        if here in todo:
            had = self.soko_prize_items()
            self.pickup_matching(["amulet", "bag"], own=True)
            st.closet_done.add(here)
            new = self.soko_prize_items() - had
            if new:
                self.soko_stats["prize"] += 1
                # an amulet from a closet is the prize, reflection (one from a pile in the zoo may be anything)
                am = next((it for it in self.items() if it.letter in new and it.ocls == nh.AMULET_CLASS), None)
                if am is not None and here in closets:
                    self.jewelry_put_on(am)
                    self.soko_stats["amulet_worn"] += 1
                self.soko_done = True
            return True
        if not todo:
            self.soko_done = True
            # taken on this level by the generic pick-up (from where a monster dropped it) -- or not found
            got = self.soko_prize_items() - st.prize_inv0
            self.soko_stats["prize_elsewhere" if got else "prize_missing"] += 1
            return self.soko_leave(lv, st)
        # an amulet or a tool seen first, then the closets, then the nearest
        like = self.soko_prize_like(lv, st)
        todo.sort(key=lambda p: (p not in like, p not in closets, abs(p[0] - here[0]) + abs(p[1] - here[1])))
        tgt = todo[0]
        if self.soko_step_to(lv, st, tgt, bs, ts, extra):
            return True
        self.soko_stats["zoo_no_way"] += 1
        st.closet_done.add(tgt)
        return self.soko_wait()

    def soko_prize_items(self):
        """Inventory letters of the amulets and bags we carry."""
        return frozenset(it.letter for it in self.items() if it.ocls == nh.AMULET_CLASS or "bag" in it.text)

    def soko_piles(self, lv, st):
        """Squares of the zoo and its door (variant coords) where the map shows an item or a corpse (gold, which
        the whole zoo lies under, aside)."""
        k = G.KIND[lv.under]
        return {p for p in st.zoo | {st.zoo_door} if k[st.to_map(p)] in (G.OBJECT, G.CORPSE)}

    def soko_prize_like(self, lv, st):
        """Squares of the zoo and its closets (variant coords) where the map shows an amulet or a tool."""
        out = set()
        for p in st.zoo | {(d[0], d[1] - 1) for d, s in st.lv["doors"].items() if s == "closed"}:
            g = int(lv.under[st.to_map(p)])
            if nh.glyph_is_object(g) and ord(nh.objclass(nh.glyph_to_obj(g)).oc_class) in (nh.AMULET_CLASS,
                                                                                           nh.TOOL_CLASS):
                out.add(p)
        return out

    def step_soko_zoo(self, c):
        """Top level, the plan done and the zoo's door open: fight the zoo at the goal square -- the zoo's only
        way out is the door west of it, so its monsters come one at a time -- while those in view keep moving
        (the ones still asleep stay put); inside the zoo, hurt with its monsters moving: back to that square."""
        lv = c.lv
        if not self.opts.sokoban or not self.in_sokoban(lv) or self.soko_done or self.soko_failed:
            return False
        st = self.soko.get(lv.key)
        if st is None or not st.solved or st.zoo_door is None:
            return False
        t0 = time.perf_counter()
        try:
            return self._soko_zoo(lv, st, c)
        finally:
            self.soko_secs += time.perf_counter() - t0

    def _soko_zoo(self, lv, st, c):
        if self.kinds(lv)[st.to_map(st.zoo_door)] == G.DOOR_CLOSED:
            return False                                   # not open yet: soko_prize kicks it
        t = self.turn()
        inside = st.zoo | {st.zoo_door}
        seen = frozenset(q for q in (st.from_map(p) for p, _ in self.visible_hostiles(lv)) if q in inside)
        if seen != st.zoo_seen:
            st.zoo_seen, st.zoo_moved = seen, t
        if not seen or t - st.zoo_moved >= ZOO_QUIET:
            return False
        here = st.from_map(self.pos())
        goal = tuple(st.lv["goal"])
        if here == goal:
            if st.zoo_hold >= ZOO_HOLD_MAX:
                return False
            st.zoo_hold += 1
            self.soko_stats["zoo_hold"] += 1
            self.cur_act = "soko_zoo"
            return self.soko_wait()
        if here in inside and c.hp < c.maxhp * ZOO_BACK_HP:
            bs, ts = self.soko_state(lv, st)
            self.soko_stats["zoo_back"] += 1
            self.cur_act = "soko_zoo"
            return self.soko_step_to(lv, st, goal, bs, ts)
        return False

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
        if st is not None:
            st.leave_explore += 1
            if st.leave_explore > SOKO_LEAVE_EXPLORE:
                # boulders shut us in for good: search (cheap), the other steps keep us alive
                self.cur_act = "search"
                self.press("2"); self.press("0"); self.press("s")
                return True
        self.explore(lv)
        return True
