"""Sokoban (flag sokoban): up the branch from the level below the Oracle, the four levels solved by the plans of
nhbot/soko_data.py (tools/soko_solve.py made them offline), the prize taken, and back down.

The way in: a main-dungeon level of Dlvl 5-10 with two up staircases, one of them taken to the level above
(Level.stairs_to) -- the other is Sokoban's (dungeon.def: the branch is up from the Oracle's level + 1); or one
we took into Sokoban before. With nothing else left to do on that level (explore), full HP and not hungry, go
up it.

In Sokoban: every level is premapped (sokoban.des FLAGS), so on arrival the walls tell which of the eight
variants this is and where it lies on the screen (soko_identify). The state is read from the map each tick --
the boulders (their glyphs) and the traps still open -- and matched against the plan's states; the next push
is the plan's at that state: walk to the square behind the boulder (no squeezing between boulders, never
diagonally through a door, never onto a trap) and step into it. Nothing in the plan depends on where we stand,
so a fight, a meal or a pick-up in between is harmless. A state that matches none (a monster's scroll of earth
dropped boulders): solved afresh from what we see (soko_solver, a budget of work for one re-plan and one for the
game). No new plan,
a push the game refuses for long, or too many turns on a level: the level is given up and Sokoban with it (we
go back down). The plan done: up the stairs at full HP -- on the top level kick the zoo's locked door,
then fetch the prize (bag of holding or amulet of reflection) from its closet -- the zoo crossed by the way with the
fewest and weakest monsters, killed one at a time (soko_zoo_step) -- #call its type by its real name, wear an amulet.

While in Sokoban the generic code must not break the puzzle: boulders and traps are impassable to every other
walk (mapmem.passable_grid), unknown scrolls are not read (scroll of earth makes boulders), and the explore step
is this module's.
"""
import heapq
import re
import time
from collections import Counter, deque

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot import soko_solver
from nhbot.consts import COLS, DELTA2KEY, FOUNTAIN_GLYPH, NOT_HUNGRY, ROWS, ray_squares
from nhbot.items import base_name
from nhbot.monattacks import ATTACKS
from nhbot.pricemem import appearance
from nhbot.soko_data import LEVELS

SOKO_DNUM = 4             # dungeon.def: Dungeons of Doom 0, Gehennom 1, Mines 2, Quest 3, Sokoban 4
SOKO_LEVEL_TURNS = 4000   # a level not solved in this many turns is given up
SOKO_BEHIND_WAITS = 10    # waits for a monster beyond the boulder before we go round to attack it
SOKO_RETREAT = 15         # turns away from a peaceful monster that blocks the plan
SOKO_SEARCH_TURNS = 500  # turns spent searching for hidden passages on the level below the Oracle (no entrance seen)
SOKO_REPLANS = 3          # re-plans (soko_replan) a level at most
# the solver's budget (soko_solver: squares its walks visit, ~2-3 million a second): one re-plan, and all of a game's
# together -- counted, not timed, so a game runs the same on any machine (the 2 s it had made games differ between
# CI and here). One re-plan: at most the 2 s it had (measured on every variant from its start: 1.1-2.0 s); the game:
# five of them (sokst_v2: 18 games of 1000 re-planned 3+ times)
SOKO_REPLAN_WORK = 3_600_000
SOKO_GAME_WORK = 5 * SOKO_REPLAN_WORK
SOKO_TRAPPED_REPLANS = 5  # re-plans at most a level with the way back down shut, one every SOKO_TRAPPED_RETRY turns
SOKO_TRAPPED_RETRY = 200
SOKO_DOOR_WAITS = 50      # turns between kicks at a locked door that refused one (wounded legs)
SOKO_LEAVE_EXPLORE = 500  # ticks of the generic explore to leave a level given up, then we only search
SOKO_STUCK = 400          # turns with the plan not advancing (a refused push, an unreachable square): give up
BEHIND_RE = ("behind the boulder", "on the other side")   # moverock: a monster where the boulder would go
FILL_RE = ("fills a pit", "plugs a hole", "plugs a trap door")  # do.c boulder_hits_pool / hack.c moverock
ZOO_NEAR = 1              # two awake hostiles this close: back to the corridor east of the zoo's door (step_soko_zoo),
                          # all the way (a retreat once begun is not given up when they fall behind)
ZOO_WAIT = 20             # ... where we wait this long for them; none came: they cannot (other monsters in their way)
ZOO_BACKS = 5             # ... this many times a level at most; then they are fought where they stand
ZOO_ENTER_HP = 0.85       # into the zoo (its door open) only above this share of HP: rested outside first
ZOO_PRAY_WAIT = 1500      # turns at most waited at the zoo's door, after the level is solved, for a prayer in hand
ZOO_KILL_COST = 20        # zoo way: a hostile on a square costs this many steps, plus its level (soko_zoo_walk)
ZOO_UNSEEN_LEVEL = 7      # ... an unseen one ('I'): its level taken as an invisible stalker's (a black light: 5)
ZOO_PEACE_TURNS = 50      # a square a look found a peaceful monster on stays closed to the zoo way this long
ZOO_PEACE_WAIT_MAX = 300  # ticks waited with no way to what is left (peaceful monsters on it), before giving it up
# monsters that explode, by permonst index: a sphere's or a light's attack is to explode at us (mhitu.c explmu ends in
# wake_nearto(x, y, 7*7): every sleeper within ~6 squares wakes), a gas spore explodes when it dies (explode.c
# wake_nearto) -- sokst_v3, 20 games without the prize: 13-29 woken at once in 9 of them. In the zoo never fought hand
# to hand; the zoo way never through their squares, and next to them only when there is no other way
ZOO_EXPLODERS = frozenset(i for i, atts in enumerate(ATTACKS) if any(a[0] in ("EXPL", "BOOM") for a in atts))
# a monster that was hidden shows itself next to us: under the gold every zoo square has (mkroom.c fill_zoo), on the
# ceiling, as a mimic posing as gold -- awake (uhitm.c wakeup) the moment it shows
ZOO_REVEAL_RE = re.compile(r"hiding under|drops from the ceiling|was an? [a-z ]*mimic")
# an ettin does not stay asleep: it wakes 9 times in 10 even when we are stealthy (monmove.c disturb) -- counted awake
# and fought first. (A chameleon's "The X turns into a Y!" is no sign of it: mon.c m_calcdistress changes its shape
# asleep too -- 79288's slept through the bot's death.)
ZOO_ATTACK_RE = re.compile(r"The ([a-z][a-z' -]*?) (?:hits|bites|misses|just misses|stings|butts|kicks|claws|touches|"
                           r"thrusts|swings|strikes|grabs|engulfs|spits|breathes|gazes)")
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
        self.real_extra = set()       # boulders the plan doesn't know that answered no attack (soko_mimic_hunt)
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
        self.zoo_last = frozenset()   # top level: squares of the hostiles in view on the last zoo tick (map) ...
        self.zoo_seq = None           # ... and the message count then (soko_zoo_track reads what came since)
        self.zoo_first = set()        # the ettins in view (map): fought first (soko_zoo_fight)
        self.zoo_active = set()       # ... and of those awake: seen moving, or next to us when we were hurt
        self.zoo_peace = {}           # zoo way: square -> turn a look there found a peaceful monster
        self.zoo_unseen = set()       # zoo way: squares where the map showed an unseen monster ('I') -- kept after the
                                      # mark is gone (we stepped away); forgotten when we stand there or hit only air
        self.zoo_hp = None            # our HP on the last zoo tick
        self.zoo_back_turn = None     # turn we went back to the corridor last (a wait there follows: ZOO_WAIT)
        self.zoo_backs = 0            # times we went back to the corridor (ZOO_BACKS at most)
        self.zoo_exit_held = False    # the hunt over: back at the goal square, the hold there for what follows begun
        self.zoo_exit_done = False    # ... and over: soko_leave from there
        self.zoo_peace_waits = 0      # ticks waited with every way closed by peaceful monsters
        self.solved_turn = None       # turn the plan was done (soko_prize)
        self.prize_inv0 = None        # soko_prize_items() when the prize hunt began
        self.filled = set()           # traps our pushes filled (the message said so): closed unless the map shows a trap
        self.seen_traps = set()       # traps the map shows that the variant has none of (a monster's wand of digging
                                      # made a hole: 79366 fell through one 60 times) -- never walked onto
        self.trapped_replans = 0      # soko_trapped_replan: re-plans made with the way down shut ...
        self.trapped_retry = -1       # ... and the turn of the next
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
        self.soko_prize_named = False   # the prize was told and called by its name (soko_name_prize)
        self.soko_track_pos = None      # soko_track: our square, and the amulets / bags we had on coming onto it
        self.soko_inv_arrival = frozenset()
        self.soko_failed = False        # a level given up: Sokoban is over for this game
        self.soko_stats = Counter()
        self.soko_secs = 0.0            # compute time spent in this module (the tick that acted included)
        self.soko_work = 0              # the solver's work spent this game (SOKO_GAME_WORK at most)
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
            lv = self.levels[key]
            # found once: it stays -- unless it proved no staircase, or taking it led to a main level (79927: up
            # to Dlvl 6 and straight back down to "the entrance" on 7, 30000 turns)
            if not got & lv.not_stairs and not any(lv.stairs_to.get(p, (SOKO_DNUM,))[0] != SOKO_DNUM for p in got):
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
        if self.bl(nh.NLE_BL_XP) < self.opts.soko_xl:
            return False                                   # soko_xl: not before this experience level
        if self.lock_tool() is None:
            # no key, lock pick or credit card: the zoo's locked door would be kicked -- the whole zoo awake at
            # once (dokick.c wake_nearby), where the deaths are; unlocked quietly its monsters sleep
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
        if self.bl(nh.NLE_BL_HUNGER) > NOT_HUNGRY:
            self.soko_stats["hungry_hold"] += 1
            return False                                   # not up hungry: four levels of pushing ahead
        if self.soko_rest(lv):
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
        # A trap the map shows is open, whatever we noted (a fill message may have come from another push); a boulder
        # on a square we saw as floor since is on a filled trap (filled by a push the message of which we did not
        # read as ours -- a fight step's: 79285, 79980 gave up a step before the end).
        def is_open(t):
            k, tk = top[t[0] + oy, t[1] + ox], terr[t[0] + oy, t[1] + ox]
            if k == G.TRAP:
                return True
            if t in st.filled:
                return False
            return (k == G.BOULDER or G.IS_COVERED[k]) and tk in (G.TRAP, G.UNKNOWN)
        ts = frozenset(tuple(t) for t in st.lv["traps"] if is_open(tuple(t)))
        plan_traps = {tuple(t) for t in st.lv["traps"]}
        st.seen_traps = {p for p in st.floor if p not in plan_traps
                         and (top[p[0] + oy, p[1] + ox] == G.TRAP or terr[p[0] + oy, p[1] + ox] == G.TRAP)}
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
                if n in prev or not free(n) or n in ts or n in st.seen_traps:
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

    def soko_mimic_hunt(self, lv, st, bs, ts, extra):
        """A boulder the plan doesn't know is a giant mimic posing as one (the top level has two): fight it while
        we can still reach its side -- once the plan's boulders close it in (a corridor of holes) only missiles
        reach it, and it stops the push. One that answers no attack is a real boulder (st.real_extra). True if
        it acted."""
        here = st.from_map(self.pos())
        for m in sorted(extra, key=lambda p: abs(p[0] - here[0]) + abs(p[1] - here[1])):
            if max(abs(here[0] - m[0]), abs(here[1] - m[1])) == 1 and not (
                    here[0] != m[0] and here[1] != m[1] and (here in st.doors or m in st.doors)):
                seq = self.msg_seq
                self.soko_stats["mimic_hunt"] += 1
                self.cur_act = "fight"
                ty, tx = st.to_map(m)
                self.press("F")
                self.press(DELTA2KEY[(ty - self.pos()[0], tx - self.pos()[1])])
                said = self.text_since(seq)
                if "harmlessly" in said or "thin air" in said or "nothing" in said.lower():
                    st.real_extra.add(m)
                return True
            sides = [(m[0] + dr, m[1] + dc) for dr, dc in DIRS8]
            for n in sides:
                if n in st.floor and n not in bs and n not in ts:
                    nxt = self.soko_walk(st, here, n, bs, ts)
                    if nxt is not None and nxt != here:
                        self.cur_act = "soko"
                        self.move(st.to_map(nxt))
                        return True
        return False

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
        missile, else a gem, a spare weapon, unworn armor or a tool (combat.expendables). True if thrown; a few
        more push tries before the next throw."""
        th = [] if self.hallu_blind_ranged() else self.expendables()
        if not th:
            return False
        y, x = self.pos()
        self.soko_stats["behind_throw"] += 1
        self.throw(th[0][0], DELTA2KEY[d], ray_squares(y, x, d[0], d[1]))
        st.behind_waits = SOKO_BEHIND_WAITS - 3
        return True

    def soko_retreat(self, lv, st, blocker, bs, ts):
        """A monster in the way (a peaceful one on our path, one beyond the boulder that won't go): for
        SOKO_RETREAT turns stand at least 4 squares from it (the nearest such square we reach), then try again."""
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
        bs, ts = self.soko_state(lv, st)
        trapped = not st.solved and self.soko_trapped(st, bs, ts)
        if not st.solved and self.turn() - (lv.entered_turn or self.turn()) > SOKO_LEVEL_TURNS and not trapped:
            return self.soko_give_up(lv, st, "turns")
        i = self.soko_match(st, bs, ts)
        if i is None and self.soko_replan(st, bs, ts):
            i = 0
        if i is None:
            if trapped:
                return self.soko_trapped_replan(lv, st, bs, ts)
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
        if i < len(st.plan) and self.soko_mimic_hunt(lv, st, bs, ts, extra - st.real_extra):
            return True
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
                # nothing to throw: walk away for a while -- it stays there to get at us; gone from its sight it
                # may move off, and the push goes
                st.behind_waits = 0
                self.soko_stats["behind_retreat"] += 1
                return self.soko_retreat(lv, st, st.to_map(beyond), bs, ts)
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
            if stuck > SOKO_STUCK // 2 and not trapped:
                return self.soko_give_up(lv, st, "no_way_to_push")
            return self.soko_wait()
        return self.soko_finish(lv, st, bs, ts, extra)

    def soko_trapped(self, st, bs, ts):
        """No way back to the staircase we arrived on (by Sokoban's rules)."""
        here = st.from_map(self.pos())
        arrive = tuple(st.lv["arrive"])
        return here != arrive and self.soko_walk(st, here, arrive, bs, ts) is None

    def soko_replan(self, st, bs, ts, walls=(), force=False):
        """The level no longer matches the plan (a monster's scroll of earth dropped boulders, a wand of striking
        broke one): solve it afresh from what we see (soko_solver, SOKO_REPLAN_WORK of work, what is left of
        SOKO_GAME_WORK at most), at most SOKO_REPLANS times a level (force: whatever the count). True if a new plan
        was found -- we follow it from its start."""
        if st.replans >= SOKO_REPLANS and not force:
            return False
        left = SOKO_GAME_WORK - self.soko_work
        if left <= 0:
            self.soko_stats["replan_no_work"] += 1
            return False
        st.replans += 1
        solver = SOLVERS.get(st.name)
        if solver is None:
            solver = SOLVERS[st.name] = soko_solver.Level(st.lv)
        here = st.from_map(self.pos())
        plan = None
        if here in st.floor:
            plan = solver.solve(budget=min(SOKO_REPLAN_WORK, left), start=(bs, ts, here), walls=walls)
            self.soko_work += solver.spent
        if plan is None:
            self.soko_stats["replan_fail"] += 1
            return False
        self.soko_stats["replan"] += 1
        st.plan, st.states, st.i, st.last_i = plan, plan_states(bs, ts, plan), 0, -1
        return True

    def soko_trapped_replan(self, lv, st, bs, ts):
        """No plan fits and the way back down is shut (Sokoban's pushes go one way): giving up would leave us on the
        level for good -- searching till we starve (79285, 79673, 79717, 79980). Re-plan (the same compute) every
        SOKO_TRAPPED_RETRY turns, SOKO_TRAPPED_REPLANS times -- the monsters that stopped a push may have moved
        meanwhile; wait in between. True: it acted."""
        if self.turn() >= st.trapped_retry and st.trapped_replans < SOKO_TRAPPED_REPLANS:
            st.trapped_replans += 1
            st.trapped_retry = self.turn() + SOKO_TRAPPED_RETRY
            if self.soko_replan(st, bs, ts, force=True):
                self.soko_stats["trapped_replan"] += 1
                return self.soko_wait()
        if st.trapped_replans >= SOKO_TRAPPED_REPLANS and self.turn() >= st.trapped_retry:
            return self.soko_give_up(lv, st, "trapped")
        self.soko_stats["trapped_wait"] += 1
        return self.soko_wait()

    def soko_rest(self, lv):
        """Below full HP with no hostile in view: rest (20s, the game stops it when something shows up). True if
        it used the turn."""
        if self.bl(nh.NLE_BL_HP) >= self.bl(nh.NLE_BL_HPMAX) or self.visible_hostiles(lv):
            return False
        self.cur_act = "rest"
        self.soko_stats["rest"] += 1
        self.press("2"); self.press("0"); self.press("s")
        return True

    def soko_stealth(self, lv):
        """Stealth on Sokoban's top level: the plan done, the prize not ours yet and the zoo's door not broken (shut,
        or unlocked and opened: its monsters sleep) -- no wand is zapped, no scroll read (a ray bouncing through the
        zoo, a scroll's noise or monsters wake it: 79059, a fire bolt at ~15 sleepers)."""
        if not self.opts.sokoban or self.soko_done or not self.in_sokoban(lv):
            return False
        st = self.soko.get(lv.key)
        if st is None or not st.solved or st.lv["up"] is not None or st.zoo_door is None:
            return False
        return self.kinds(lv)[st.to_map(st.zoo_door)] in (G.DOOR_CLOSED, G.DOOR_OPEN)

    def soko_wands_shut(self, lv):
        """No wand zapped in Sokoban while the level is unsolved -- a force bolt breaks a boulder, a ray or a digging
        beam does the puzzle no good -- nor in its stealth on the top level (soko_stealth)."""
        if not self.opts.sokoban or not self.in_sokoban(lv):
            return False
        st = self.soko.get(lv.key)
        return st is None or not st.solved or self.soko_stealth(lv)

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
                if self.bl(nh.NLE_BL_HP) < self.bl(nh.NLE_BL_HPMAX):
                    return self.soko_rest(lv) or self.soko_wait()     # up the stairs only at full HP
                self.soko_stats["up"] += 1
                self.take_stairs("<")
                return True
            return self.soko_step_to(lv, st, goal, bs, ts, extra) or self.soko_wait()
        return self.soko_prize(lv, st, bs, ts, extra)

    def soko_prize(self, lv, st, bs, ts, extra):
        """Top level: open the zoo's locked door (west of the goal), walk to the closets on the far side of the
        zoo (the prize lies in one of them), pick up an amulet or a bag there, put the amulet on. Done after
        the closets were seen (or the prize taken)."""
        if st.prize_inv0 is None:
            st.prize_inv0 = self.soko_prize_items()
        hp, maxhp = self.bl(nh.NLE_BL_HP), self.bl(nh.NLE_BL_HPMAX)
        here = st.from_map(self.pos())
        closets = [(p[0], p[1] - 1) for p, s in st.lv["doors"].items() if s == "closed"]
        if here in closets:
            self.soko_name_prize()
        if self.soko_prize_named:
            self.soko_done = True                          # the prize is ours: the zoo's other piles are not worth it
            self.soko_stats["prize_elsewhere"] += 1
            return self.soko_leave(lv, st)
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
        # a monster of the zoo may have carried the prize off (they go for an amulet of reflection) and dropped
        # it where it died -- under its corpse, the pile shows its top: the piles in the zoo and on its door
        # are looked into too
        todo = [p for p in closets + sorted(self.soko_piles(lv, st)) if p not in st.closet_done]
        if here in todo:
            had = self.soko_prize_items()
            seq = self.msg_seq
            self.pickup_matching(["amulet", "bag"], own=True)
            if "cannot accommodate" in self.text_since(seq) and self.soko_make_room():
                return True                                # the pick-up again on the next tick
            st.closet_done.add(here)
            new = self.soko_prize_items() - had
            if new:
                self.soko_stats["prize"] += 1
                if here in closets:
                    self.soko_name_prize()
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
        if not shut:
            nxt = self.soko_zoo_next(lv, st, here, todo, closets, bs, ts, extra)
            if nxt is not None:
                return self.soko_zoo_step(lv, st, nxt, extra - st.real_extra)
            st.zoo_peace_waits += 1
            if st.zoo_peace_waits <= ZOO_PEACE_WAIT_MAX:
                self.soko_stats["zoo_no_way_wait"] += 1
                return self.soko_wait()                  # every way closed (peaceful monsters): they may move
            self.soko_stats["zoo_no_way_gave_up"] += 1
            st.closet_done.update(todo)
            return True
        todo.sort(key=lambda p: (p not in like, p not in closets, abs(p[0] - here[0]) + abs(p[1] - here[1])))
        tgt = todo[0]
        if self.soko_step_to(lv, st, tgt, bs, ts, extra):
            return True
        self.soko_stats["zoo_no_way"] += 1
        st.closet_done.add(tgt)
        return self.soko_wait()

    def soko_make_room(self):
        """The knapsack's 52 letters all taken and the prize here (79009, 79175: the amulet / the bag in the closet,
        "Your knapsack cannot accommodate any more items"): the item worth least (value.est_value: what we wear,
        wield or need comes last; never an amulet or a bag) dropped here, never picked up again (pickup.never_take).
        True: it dropped one."""
        inv = [it for it in self.items() if it.ocls not in (nh.COIN_CLASS, nh.AMULET_CLASS) and "bag" not in it.text
               and not it.on_body and it.key not in self.cant_drop and not self.sac_carrying(it)]
        if not inv:
            return False
        looks = self.carried_by_look()
        same = lambda it: looks[appearance(it.text)] if appearance(it.text) is not None else 1
        it = min(inv, key=lambda it: self.est_value(it, same(it)))
        self.never_take.add(base_name(it.text)[2])
        self.soko_stats["room_dropped"] += 1
        self.drop_units(it.letter)
        return True

    def soko_track(self, lv):
        """Every tick in Sokoban: the amulets and bags we carried when we came onto this square (soko_name_prize
        tells what this square gave us by them)."""
        if not self.in_sokoban(lv):
            return
        pos = self.pos()
        if pos != self.soko_track_pos:
            self.soko_track_pos = pos
            self.soko_inv_arrival = self.soko_prize_items()

    def soko_name_prize(self):
        """Standing in a prize closet: an amulet or a bag that came since we stepped in came from it -- whichever
        step picked it up -- and is the prize (sokoban.des: the bag of holding or the amulet of reflection). Its
        type called so at once, so everything reading item names knows it -- "reflection" (jewelry, equipment,
        rays), "bag of holding" (goldbag's bag rank) -- and the amulet put on. Once a game."""
        if self.soko_prize_named:
            return
        got = self.soko_prize_items() - self.soko_inv_arrival
        for it in self.items():
            if it.letter not in got:
                continue
            if it.ocls == nh.AMULET_CLASS:
                name = "reflection"
            elif "bag" in it.text:
                name = "bag of holding"
            else:
                continue
            self.soko_prize_named = True
            if name not in it.text and self.call_type(it.letter, name):
                self.soko_stats["prize_named"] += 1
            if it.ocls == nh.AMULET_CLASS and not it.worn:
                am = next((a for a in self.items() if a.letter == it.letter), None)
                if am is not None and not am.cursed:
                    self.jewelry_put_on(am)
                    self.soko_stats["amulet_worn"] += 1
            return

    def soko_zoo_todo(self, lv, st):
        """(the places left to look into for the prize: the closets, the piles in the zoo and on its door -- a monster
        of the zoo may have carried the prize off and dropped it where it died -- ; the closets), variant coords."""
        closets = [(p[0], p[1] - 1) for p, s in st.lv["doors"].items() if s == "closed"]
        todo = [p for p in closets + sorted(self.soko_piles(lv, st)) if p not in st.closet_done]
        return todo, closets

    def soko_zoo_next(self, lv, st, here, todo, closets, bs, ts, extra):
        """The zoo open: the next step (variant coords) toward the place left with the easiest way (soko_zoo_walk),
        an amulet or a tool seen first, then the closets -- a peaceful monster sleeping before a closet's door
        closes that closet, not the hunt (79059: a pony by the first closet, the bot backed off from it for 6000
        turns). None: no way to any."""
        like = self.soko_prize_like(lv, st)
        mimics = extra - st.real_extra
        for near_ok in (False, True):                      # not next to a monster that explodes, if any way can
            ways = [(p, self.soko_zoo_walk(lv, st, here, p, bs, ts, mimics, near_ok)) for p in todo]
            ways = [(p, w) for p, w in ways if w[0] is not None]
            if ways:
                return min(ways, key=lambda pw: (pw[0] not in like, pw[0] not in closets, pw[1][1]))[1][0]
        return None

    def soko_zoo_walk(self, lv, st, start, goal, bs, ts, mimics=frozenset(), near_ok=True):
        """(first step (variant coords), cost) of the way from start to goal with the fewest and weakest monsters
        to kill on it -- a hostile's square costs ZOO_KILL_COST plus its level, a pet's two steps (we swap), a
        peaceful's is closed, a monster's that explodes is closed (ZOO_EXPLODERS) and, unless near_ok, the squares
        next to it too, a boulder the plan doesn't know (mimics: the top level's giant mimics pose as boulders)
        costs a kill -- by Sokoban's rules (soko_walk). (None, None): no way."""
        g = self.obs["glyphs"]
        t = self.turn()
        cost = {}
        boom = set()
        for p in st.floor:
            k = G.KIND[int(g[st.to_map(p)])]
            if k == G.PET:
                cost[p] = 2
            elif k == G.MONSTER and p != start:
                mp = st.to_map(p)
                if self.soko_exploder_at(mp):
                    boom.add(p)
                    cost[p] = None
                elif t - st.zoo_peace.get(p, -ZOO_PEACE_TURNS) < ZOO_PEACE_TURNS \
                        or self.peaceful_now(lv, mp, look=False):
                    cost[p] = None
                else:
                    cost[p] = ZOO_KILL_COST + nh.permonst(nh.glyph_to_mon(int(g[mp]))).mlevel
        if not near_ok:
            for b in boom:
                for dr, dc in DIRS8:
                    n = (b[0] + dr, b[1] + dc)
                    if n != start:
                        cost[n] = None
        for p in mimics:
            cost[p] = ZOO_KILL_COST + 8                    # giant mimic: level 8
        for p in st.zoo_unseen - {start}:
            if cost.get(p, 1) == 1:                        # (one in view there now counts as itself)
                cost[p] = ZOO_KILL_COST + ZOO_UNSEEN_LEVEL
        bs = bs - mimics
        free = lambda p: p in st.floor and p not in bs
        dist, prev = {start: 0}, {start: None}
        q = [(0, start)]
        while q:
            d, cur = heapq.heappop(q)
            if d > dist[cur]:
                continue
            if cur == goal:
                while cur != start and prev[cur] != start:
                    cur = prev[cur]
                return cur, d
            for dr, dc in DIRS8:
                n = (cur[0] + dr, cur[1] + dc)
                if not free(n) or n in ts or n in st.seen_traps or cost.get(n, 1) is None:
                    continue
                if dr and dc and (cur in st.doors or n in st.doors
                                  or (not free((cur[0] + dr, cur[1])) and not free((cur[0], cur[1] + dc)))):
                    continue
                nd = d + cost.get(n, 1)
                if nd < dist.get(n, 1 << 30):
                    dist[n], prev[n] = nd, cur
                    heapq.heappush(q, (nd, n))
        return None, None

    def soko_zoo_to(self, lv, st, here, target, bs, ts):
        """A step toward target through the zoo by soko_zoo_walk -- what sleeps on the way is attacked (79042: a
        plain walk back to the corridor met a sleeper on its next square and stood there 400 turns). True: it
        acted."""
        for near_ok in (False, True):                      # not next to a monster that explodes, if any way can
            nxt = self.soko_zoo_walk(lv, st, here, target, bs, ts, near_ok=near_ok)[0]
            if nxt is not None:
                return self.soko_zoo_step(lv, st, nxt)
        return False

    def soko_zoo_step(self, lv, st, nxt, mimics=frozenset()):
        """The zoo's door open (unlocked quietly its monsters still sleep; kicked, the wave is over): one step nxt
        (variant coords) along the way with the fewest and weakest monsters to the prize (soko_zoo_walk), killing
        them one at a time -- the one on the next square is attacked ('F'), the others sleep on. A peaceful one
        there (a look decides): that square closed for a while, the way chosen afresh. True: it acted."""
        if nxt == st.from_map(self.pos()):
            return self.soko_wait()
        mp = st.to_map(nxt)
        y, x = self.pos()
        if nxt in mimics:
            # a boulder the plan doesn't know: a giant mimic shows itself when hit -- one that answers no attack is
            # a real boulder (st.real_extra), the way chosen without it
            seq = self.msg_seq
            self.soko_stats["zoo_mimic_attack"] += 1
            self.cur_act = "fight"
            self.press("F")
            self.press(DELTA2KEY[(mp[0] - y, mp[1] - x)])
            said = self.text_since(seq)
            if "harmlessly" in said or "thin air" in said or "nothing" in said.lower():
                st.real_extra.add(nxt)
            return True
        k = G.KIND[int(self.obs["glyphs"][mp])]
        if nxt in st.zoo_unseen and k not in (G.MONSTER, G.PET):
            # an unseen monster there (79016: bumped into one -- "Wait! There's something there you can't see!" --
            # then walked into it again: a black light, it blew up, hallucination, the zoo around awake): attacked
            # where we last knew it; only air there: it went, the square is free
            seq = self.msg_seq
            self.soko_stats["zoo_unseen_attack"] += 1
            self.cur_act = "fight"
            self.press("F")
            self.press(DELTA2KEY[(mp[0] - y, mp[1] - x)])
            if "thin air" in self.text_since(seq):
                st.zoo_unseen.discard(nxt)
            return True
        self.cur_act = "soko_zoo"
        if k == G.MONSTER:
            if self.peaceful_now(lv, mp):
                st.zoo_peace[nxt] = self.turn()
                self.soko_stats["zoo_peaceful"] += 1
                return self.soko_wait()
            self.soko_stats["zoo_attack"] += 1
            self.cur_act = "fight"
            self.press("F")
            self.press(DELTA2KEY[(mp[0] - y, mp[1] - x)])
            return True
        self.soko_stats["zoo_walk"] += 1
        self.move(mp)
        return True

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

    def soko_exploder_at(self, mp):
        """The monster shown at mp (map coords) explodes (ZOO_EXPLODERS)."""
        g = int(self.obs["glyphs"][mp])
        return G.KIND[g] == G.MONSTER and nh.glyph_to_mon(g) in ZOO_EXPLODERS

    def soko_no_melee(self, lv, pos):
        """In the zoo (soko_zoo_level): a monster that explodes is never fought hand to hand -- the fight steps ask."""
        return self.soko_exploder_at(pos) and self.soko_zoo_level(lv) is not None

    def soko_zoo_fight(self, cands, first=frozenset()):
        """Attack the weakest (lowest level) of cands (map squares next to us) -- of those in first (an ettin) if any
        is among them -- monsters that explode aside. False: none to attack."""
        g = self.obs["glyphs"]
        cands = [p for p in cands if G.KIND[int(g[p])] == G.MONSTER and not self.soko_exploder_at(p)]
        if not cands:
            return False
        cands = [p for p in cands if p in first] or cands
        self.soko_stats["zoo_fight"] += 1
        self.attack(min(cands, key=lambda p: nh.permonst(nh.glyph_to_mon(int(g[p]))).mlevel))
        return True

    def soko_zoo_level(self, lv):
        """Our Sokoban top level with the plan done and the zoo's door open, the prize hunt on -- or over (the
        prize ours, or every place looked into) and we not yet back out at the goal square with the hold there done:
        the zoo's rules hold on the way out too (79003, 79009, 79011, 79123, 79244 died 14-42 turns after the prize,
        walking out through the woken zoo by soko_leave). Its SokoLevel, else None."""
        if not self.opts.sokoban or not self.in_sokoban(lv) or self.soko_failed:
            return None
        st = self.soko.get(lv.key)
        if st is None or not st.solved or st.lv["up"] is not None or st.zoo_door is None \
                or self.kinds(lv)[st.to_map(st.zoo_door)] == G.DOOR_CLOSED:
            return None                                    # (levels 2 and 3 have a locked door too: no zoo)
        if (self.soko_done or self.soko_prize_named) and st.zoo_exit_done:
            return None                                    # out: soko_leave
        return st

    def soko_zoo_track(self, lv, st, c):
        """Every zoo tick: which hostiles in view are awake -- one that stands where none stood, with a square left
        empty within 2 (it moved; a monster coming into view or a kill does not count), or one next to us when our HP
        fell (it hit us). Those stay awake while they stay put. The awake ones within ZOO_NEAR of us (map coords):
        next to us."""
        now = frozenset(p for p, _ in self.visible_hostiles(lv))
        gone = st.zoo_last - now
        moved = {p for p in now - st.zoo_last if any(max(abs(p[0] - q[0]), abs(p[1] - q[1])) <= 2 for q in gone)}
        y, x = self.pos()
        g = self.obs["glyphs"]
        adj = {p for p in now if max(abs(p[0] - y), abs(p[1] - x)) == 1}
        hit = adj if st.zoo_hp is not None and c.hp < st.zoo_hp else set()
        said = self.text_since(st.zoo_seq) if st.zoo_seq is not None else ""
        # one that showed itself next to us (hidden under gold, on the ceiling, a mimic: 79003, 79039, 79184 fought
        # the sleeper on the way while it bit) and one a message names attacking (a miss leaves our HP as it was)
        revealed = (adj - st.zoo_last) if ZOO_REVEAL_RE.search(said) else set()
        names = set(ZOO_ATTACK_RE.findall(said))
        attackers = {p for p in adj if G.monster_name(int(g[p])) in names} if names else set()
        st.zoo_first = {p for p in now if G.monster_name(int(g[p])) == "ettin"}
        st.zoo_active = (st.zoo_active & now) | moved | hit | revealed | attackers | st.zoo_first
        st.zoo_last, st.zoo_hp, st.zoo_seq = now, c.hp, self.msg_seq
        st.zoo_unseen |= {p for p in st.floor if G.KIND[int(g[st.to_map(p)])] == G.INVIS}
        st.zoo_unseen.discard(st.from_map((y, x)))
        return [p for p in st.zoo_active if max(abs(p[0] - y), abs(p[1] - x)) <= ZOO_NEAR]

    def step_soko_zoo(self, c):
        """The zoo's door open, the prize not ours: before the fight steps, which would hold us on whatever stands
        next to us. Two awake hostiles next to us (soko_zoo_track): back to the goal square in the corridor east of
        the door, the zoo's only way out, where they come one at a time -- there, the one next to us is fought (the
        fight steps), else we wait ZOO_WAIT turns for them; none came: they cannot, and we go on (79599: a fight at
        the door carried the bot into the zoo, surrounded 19 turns after the door opened). Otherwise on toward the prize: the monster on the next square
        of the way is attacked, the rest sleep on (79009 fought what stood beside it and went nowhere). Below
        ZOO_ENTER_HP of max HP with none awake near: rest at the goal square first (soko_prize rests there)."""
        lv = c.lv
        st = self.soko_zoo_level(lv)
        if st is None:
            return False
        t0 = time.perf_counter()
        try:
            return self._soko_zoo(lv, st, c)
        finally:
            self.soko_secs += time.perf_counter() - t0

    def _soko_zoo(self, lv, st, c):
        active = self.soko_zoo_track(lv, st, c)
        here = st.from_map(self.pos())
        goal = tuple(st.lv["goal"])
        inside = st.zoo | {st.zoo_door}
        bs, ts = self.soko_state(lv, st)
        t = self.turn()
        # a retreat once begun goes all the way to the goal square: one step back put the two out of reach and the
        # next went forward again, back and forth for thousands of turns (sokst_v2 79632, 79008: 8335 steps back)
        if here != goal and (st.zoo_back_turn is not None or (len(active) >= 2 and st.zoo_backs < ZOO_BACKS)):
            # two that stay by the door and never come out (79042: a yeti and a black unicorn, the bot went back and
            # forth 1451 times till it died): ZOO_BACKS times, then they are fought
            if st.zoo_back_turn is None:
                st.zoo_backs += 1
                self.soko_stats["zoo_back"] += 1
            st.zoo_back_turn = t
            if self.soko_zoo_to(lv, st, here, goal, bs, ts):
                return True
            st.zoo_back_turn = None                        # no way back (a peaceful one in it): the retreat is off
            return False
        y, x = self.pos()
        boom = [p for p in active if self.soko_exploder_at(p)]
        if boom:
            # an awake one that explodes next to us: never hit -- away along the zoo way to the goal square
            self.soko_stats["zoo_boom_away"] += 1
            if here != goal and self.soko_zoo_to(lv, st, here, goal, bs, ts):
                return True
            return self.soko_wait()
        near = [p for p, _ in self.visible_hostiles(lv) if max(abs(p[0] - y), abs(p[1] - x)) == 1]
        if not near and self.step_eat(c):
            return True                                    # hungry, none next to us: eat -- the eat step comes after
                                                           # this one (79011 fainted from hunger in the zoo)
        if here == goal and st.zoo_back_turn is not None:
            if near:
                st.zoo_back_turn = t                       # the one next to us fought here: an awake one first
                if self.soko_zoo_fight(active, st.zoo_first) or self.soko_zoo_fight(near, st.zoo_first):
                    return True
            if t - st.zoo_back_turn <= ZOO_WAIT:
                self.soko_stats["zoo_hold"] += 1
                self.cur_act = "soko_zoo"
                return self.soko_wait()                    # waiting for the awake ones to come through the door
            st.zoo_back_turn = None
            st.zoo_active.clear()                          # none came: they cannot -- fought where they stand
        if active and self.soko_zoo_fight(active, st.zoo_first):
            return True                                    # one awake next to us: fought first, not the sleeper on the way
        if self.soko_done or self.soko_prize_named:
            # the hunt over: out to the goal square by the zoo way, then the hold there (what follows comes through
            # the door one at a time), then soko_leave
            if here == goal:
                if not st.zoo_exit_held:
                    st.zoo_exit_held = True
                    st.zoo_back_turn = t
                    return self.soko_wait()
                st.zoo_exit_done = True
                return False
            self.soko_stats["zoo_exit"] += 1
            return self.soko_zoo_to(lv, st, here, goal, bs, ts)
        # from here on soko_prize, not the fight steps, has the turn: those attack whatever sleeps next to us
        # (79016: at a pile in the zoo a panther, then a zruty beside it, at the door a rope golem -- woken, they
        # mauled it, four retreats)
        todo, closets = self.soko_zoo_todo(lv, st)
        extra = bs - st.states[st.i][0]
        if not todo or here in todo:
            return self.soko_prize(lv, st, bs, ts, extra)  # pick up here / done
        if c.hp < c.maxhp * ZOO_ENTER_HP:
            if here in inside:
                self.soko_stats["zoo_back_rest"] += 1
                return self.soko_zoo_to(lv, st, here, goal, bs, ts)
            return self.soko_prize(lv, st, bs, ts, extra)  # it rests outside the zoo
        nxt = self.soko_zoo_next(lv, st, here, todo, closets, bs, ts, extra)
        if nxt is None:
            return self.soko_prize(lv, st, bs, ts, extra)  # it waits, then gives the rest up
        return self.soko_zoo_step(lv, st, nxt, extra - st.real_extra)

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
                self.take_stairs(">")
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
