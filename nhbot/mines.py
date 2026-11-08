"""The Gnomish Mines as a trip: closed below mines_xl and while Excalibur can still be made (mines_blocked), the
way there (mines_trip_step: Excalibur's fountain level first, then the branch level's Mines staircase -- mines_stairs,
two_down_mines), the bounce back up from a closed Mines level and Minetown seen (mines_tick, every tick), and the
climb back out once Minetown is passed / the bottom or no way on is reached (mines_return_start, mines_return_step);
after it the Mines are done."""
from collections import Counter

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import CORRIDOR_GLYPHS

MINES_TRIP_RETRY = 500      # the Mines staircase out of reach -- try again this many turns later (by then
                            # step_progress may have forgotten the obstacles in the way)


class MinesState:
    """State of the Mines trip / return (MinesMixin)."""
    def __init__(self):
        self.return_descents = 0         # descents while climbing out of the Mines (the up/down loop)
        self.trip_stats = Counter()        # ticks of the trip to the Mines by what they did
        self.two_down_levels = set()       # branch levels whose Mines staircase we inferred (two_down_mines)
        self.trip_retry = 0                # no trip to the Mines before this turn (the staircase was out of reach)
        self.pending_mines_mark = False  # next tick: mark the Mines staircase we stand by (mines_tick)
        self.bounced = set()             # Mines levels we went straight back up from (mines_tick)
        self.return_on = False           # mines_return: climbing out of the Mines
        self.done = False                # ... and out: the Mines are finished
        self.done_turn = 0
        self.minetown_seen = False
        self.return_log = []             # (turn, level key, why, depth) per mines_return


class MinesMixin:
    def mines_init(self):
        self.mines = MinesState()

    def mines_blocked(self):
        """The Mines staircase is closed: below XL mines_xl (mines_xl_open), while Excalibur can still be made
        at a fountain we know (excal_fountain_level), and once mines_return brought us back (the Mines are
        finished). A/B mines_xl 5 vs the Mines always open: +1041 [+135, +2013], then +2636 [+1582, +3695]."""
        if self.mines.done:
            return True                       # mines_return brought us back: the Mines are finished
        return not self.mines_xl_open() or self.excal_fountain_level() is not None

    def mines_xl_open(self):
        """The Mines open from XL mines_xl on -- or once a main-dungeon level got desperate (no way on
        found there: the Mines are the way on)."""
        return self.bl(nh.NLE_BL_XP) >= self.opts.mines_xl or any(l.desperate for k, l in self.levels.items()
                                                                 if k[0] == 0)

    def mines_trip_step(self, lv, grids):
        """The Mines open (mines_xl_open), in the main dungeon, their staircase known (mines_stairs) and
        the Mines not done: Excalibur first -- while it can be made at a fountain we know (excal_fountain_level),
        go to that level (the dip itself is excalibur.excal_step, housekeeping; below its HP we rest there) --
        then to the branch level and down its Mines staircase. A level we know no way to (an up staircase never
        seen: we fell past it): its fountain is given up (excal_skip), the Mines tried again MINES_TRIP_RETRY
        turns later. True if it used the turn."""
        if lv.key[0] != 0 or self.mines.done or not self.mines_xl_open() \
                or self.turn() < self.mines.trip_retry:
            return False
        branch = next((k for k, l in self.levels.items() if k[0] == 0 and self.mines_stairs(l)), None)
        if branch is None:
            return False
        fk = self.excal_fountain_level()
        if fk is not None:
            if fk != lv.key:
                if self.level_travel_step(lv, grids, fk, "excal", "excal_travel"):
                    return True
                self.mines.trip_stats["excal_no_way"] += 1
                self.excal.skip.add(fk)
                return False
            hp, maxhp = self.bl(nh.NLE_BL_HP), self.bl(nh.NLE_BL_HPMAX)
            if hp >= maxhp * self.opts.excal_hp or self.visible_hostiles(lv):
                return False
            self.cur_act = "rest"                # excal_step dips from excal_hp of max HP on
            self.mines.trip_stats["excal_rest"] += 1
            self.search_turns(20)
            return True
        if lv.key != branch:
            if self.level_travel_step(lv, grids, branch, "mines", "travel"):
                return True
            self.mines.trip_stats["no_way"] += 1
            self.mines.trip_retry = self.turn() + MINES_TRIP_RETRY
            return False
        down = np.zeros_like(grids[0], dtype=bool)
        for p in self.mines_stairs(lv):
            down[p] = True
        on = bool(down[self.pos()])
        if self.stairs_step(lv, grids, down, ">"):
            self.cur_act = "mines"
            self.mines.trip_stats["enter" if on else "to_stairs"] += 1
            return True
        self.mines.trip_stats["unreachable"] += 1
        self.mines.trip_retry = self.turn() + MINES_TRIP_RETRY
        return False

    def mines_stairs(self, lv):
        """The down staircases of this level we know lead into the Mines -- marked on a bounce
        (avoid_down) or taken (Level.stairs_to) -- as linked_stairs places them."""
        marks = {p: (2, 1) for p in lv.avoid_down}
        marks.update({p: k for p, k in lv.stairs_to.items() if k[0] == 2})
        return self.linked_stairs(lv, marks, G.DOWNSTAIR) or self.two_down_mines(lv)

    def minetown_rooms(self, lv):
        """A Minetown of rooms and corridors -- mines.des minetn-2/3/4/7 (RANDOM_CORRIDORS): its staircases lie
        in rooms of their own, joined by corridors whose doors may be secret (mklev.c dodoor: 1 in 8) and whose
        squares may be (dig_corridor) -- so searching there finds the way down, as on a main level (75022,
        75017: left the Mines from such a Minetown, no way down found). Told by corridor squares. A/B
        minetown_search vs base_v: +286 [-8, +589]; no_way returns 122 -> 95, games reaching Mines 5 183 -> 208."""
        return bool(self.is_minetown(lv) and np.isin(lv.under, CORRIDOR_GLYPHS).any())

    def two_down_mines(self, lv):
        """On main Dlvl 2-4 (where the Mines branch: dungeon.def) two down staircases in view, one of them taken
        to the next main level (Level.stairs_to) -- the other is the Mines'. Known so without a bounce off it
        (442 of 834 base_v games past Dlvl 4 never learned where the Mines were). A/B two_down vs base_v: +597
        [-222, +1397], neutral +1601 [+1034, +2198], median 5439 -> 6592; games in the Mines 380 -> 620."""
        if lv.key[0] != 0 or not 2 <= lv.key[1] <= 4:
            return set()
        downs = {(int(y), int(x)) for y, x in zip(*np.nonzero(self.kinds(lv) == G.DOWNSTAIR))} - lv.not_stairs
        if len(downs) != 2:
            return set()
        main = self.linked_stairs(lv, {p: k for p, k in lv.stairs_to.items() if k == (0, lv.key[1] + 1)},
                                  G.DOWNSTAIR) & downs
        if len(main) != 1:
            return set()
        if lv.key not in self.mines.two_down_levels:
            self.mines.two_down_levels.add(lv.key)
            self.mines.trip_stats["two_down"] += 1
        return downs - main

    def mines_tick(self, lv):
        """Every tick, before the steps: the branch level's Mines staircase marked (avoid_down) where mines_return or a
        bounce brought us back up; on a Mines level reached by a staircase while the Mines are closed (mines_blocked)
        -- straight back up (once a level); Minetown seen (or passed: mines_return); out of the Mines after
        mines_return -- the Mines are done. True if it took the stairs."""
        if self.mines.pending_mines_mark:
            self.mines.pending_mines_mark = False
            if lv.key[0] == 0:
                lv.avoid_down.add(self.pos())
        if self.mines_blocked() and lv.key[0] == 2 and lv.key not in self.mines.bounced \
                and self.arrived_by_stairs:
            self.mines.bounced.add(lv.key)
            self.mines.pending_mines_mark = True
            self.take_stairs("<")
            return True
        if lv.key[0] == 2:
            folk = self.town_folk_visible()
            if folk and lv.key[1] in (3, 4):
                lv.town_heard = True                  # its watch / priest / shopkeeper in view (minetown_folk,
                                                      # accepted before its A/B was in)
            if self.is_minetown(lv) or folk:
                self.mines.minetown_seen = True
            if not self.mines.minetown_seen and lv.key[1] >= 5:
                self.mines_return_start(lv, "no_town")    # Minetown is Mines level 3 or 4: we passed it
        elif self.mines.return_on:
            self.mines.return_on = False
            self.mines.done = True
            self.mines.done_turn = self.turn()
        return False

    def mines_return_start(self, lv, why):
        if not self.mines.return_on:
            self.mines.return_on = True
            self.mines.return_log.append((self.turn(), list(lv.key), why, self.bl(nh.NLE_BL_DEPTH)))

    def mines_return_step(self, lv, grids):
        """mines_return: climb back to the main dungeon -- walk to this level's up staircase and take it; the
        branch staircase we arrive on gets the Mines mark (avoid_down), and mines_done keeps us out."""
        self.cur_act = "minesup"
        start = self.pos()
        up = self.stairs_mask(lv, G.UPSTAIR, grids[0])
        if up[start]:
            if lv.key[1] == 1:
                self.mines.pending_mines_mark = True      # next tick, on the branch level: mark its Mines staircase
            self.take_stairs("<")
            return True
        return up.any() and self.walk_to(lv, up, grids=grids)[0] == "moved"
