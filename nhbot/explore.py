"""Exploring a level and leaving it: frontier and item goals, when to descend, searching for hidden
passages, the Gnomish Mines (mines_blocked, mines_trip_step, mines_return), waiting for the pet, magic mapping."""
import re
from collections import Counter

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import COLS, CORRIDOR_GLYPHS, NEIGH, ROWS, WEAK
from nhbot.goals import GOALS

REST_DESCEND_HP = 0.95      # rest on the down staircase below this fraction of max HP
REST_DESCEND_MAX = 600      # ... at most this many turns a level
MINES_TRIP_RETRY = 500      # the Mines staircase out of reach -- try again this many turns later (by then
                            # step_progress may have forgotten the obstacles in the way)


class ExploreMixin:
    def explore_init(self):
        self.maps_read = 0
        self.pet_waits = 0
        self.pet_waited_total = 0
        self.mines_return_descents = 0   # descents while climbing out of the Mines (the up/down loop)
        self.mines_trip_stats = Counter()  # ticks of the trip to the Mines by what they did
        self.two_down_levels = set()       # branch levels whose Mines staircase we inferred (two_down_mines)
        self.mines_trip_retry = 0          # no trip to the Mines before this turn (the staircase was out of reach)
        self.descent_rest = Counter()    # level key -> turns rested on its down staircase
        self.items_first_holds = 0       # descents held for an item goal still on the level
        self.pending_mines_mark = False  # next tick: mark the Mines staircase we stand by (mines_tick)
        self.mines_bounced = set()       # Mines levels we went straight back up from (mines_tick)
        self.mines_return_on = False     # mines_return: climbing out of the Mines
        self.mines_done = False          # ... and out: the Mines are finished
        self.mines_done_turn = 0
        self.minetown_seen = False
        self.mines_return_log = []       # (turn, level key, why, depth) per mines_return

    def explore(self, lv):
        self.cur_act = "explore"
        self.goal_observe(lv)
        k_mem, k_live, passable = grids = self.grids(lv)
        start = self.pos()
        y, x = start

        unknown = (k_mem == G.UNKNOWN) & ~lv.near
        dil = np.zeros_like(unknown)
        for dy, dx in NEIGH:
            dil[max(0, dy):ROWS + min(0, dy), max(0, dx):COLS + min(0, dx)] |= \
                unknown[max(0, -dy):ROWS + min(0, -dy), max(0, -dx):COLS + min(0, -dx)]
        frontier = passable & dil & (lv.visited == 0)
        lv.explored = not frontier.any()
        if self.mines_return_on and lv.key[0] == 2 and self.mines_return_step(lv, grids):
            return
        if self.mines_trip_step(lv, grids):
            return
        gold = (G.KIND[lv.under] == G.GOLD) & passable    # an item: the top glyph, not the terrain under it
        for p in self.goal_closed_set("gold", lv.key):
            gold[p] = False
        downstairs = self.stairs_mask(lv, G.DOWNSTAIR, k_mem)
        # level_time: turns spent on this level (Level.turns_here) -- since the first arrival, a level re-entered
        # counted the whole time away: descend_after / the mines_after hatch ran out at once
        on_level = lv.turns_here if self.opts.level_time else self.turn() - lv.entered_turn
        # the mines_after hatch counts from our first arrival here -- or, after mines_return, from the return
        # (the branch level was first entered long before, which re-opened the Mines at once)
        hatch = self.turn() - self.mines_done_turn if self.mines_done else on_level
        # mines_mask: the closed Mines staircase as mines_stairs places it -- an avoid_down mark is the square we
        # arrived on, often beside the staircase (linked_stairs), and the stairs taken / two_down count too
        closed = (self.mines_stairs(lv) if lv.key[0] == 0 else set()) if self.opts.mines_mask else lv.avoid_down
        if closed and hatch < self.opts.mines_after and self.mines_blocked():
            for p in closed:
                downstairs[p] = False
        if self.mines_return_on and lv.key[0] == 2:
            # climbing out of the Mines: no way down is a way on -- a level whose up staircase is unknown is explored
            # for it (descend_after, counted from the first visit, used to send us down at once and back up: a loop)
            downstairs[:] = False
        want_down = downstairs.any() and self.should_descend(lv, frontier, on_level)
        if want_down and lv.key[0] == 2 and lv.key[1] >= 4 \
                and not self.minetown_seen and not self.is_minetown(lv):
            # mines level 4 done and no Minetown on 3 or 4: it won't come further down
            self.mines_return_start(lv, "no_town")
            if self.mines_return_step(lv, grids):
                return
        if want_down \
                and on_level <= self.opts.descend_after:
            # explored, but something worth having still lies here: the same goals the target step below
            # will walk to (gold, armor/food/carry piles not yet inspected), so holding off is never idle
            stuff = np.zeros_like(gold)
            for kind, m in self.goal_masks(lv, passable, gold).items():
                if kind in GOALS and GOALS[kind].holds_descent:
                    stuff |= m
            stuff[y, x] = False
            if stuff.any():
                _, _, got = self.dijkstra(lv, k_mem, k_live, passable, start, stuff, want_dist=False)
                if got is not None and got != start:
                    want_down = False
                    self.items_first_holds += 1

        if self.sokoban_trip_step(lv, grids, want_down or lv.explored):
            return
        if want_down and self.go_down(lv, grids, downstairs):
            return

        goals = self.goal_masks(lv, passable, gold)
        targets = frontier.copy()
        for m in goals.values():
            targets |= m
        if self.opts.goal_here:
            # goal_here: a goal on our own square was the consuming step's to take this tick (housekeeping, gold_here,
            # melee); it declined (the altar with a hostile in view) -- walk on to the others instead of "here" ending
            # exploring (frontier never covers our square: visited) -- as the descent hold above leaves it out
            targets[y, x] = False
        if targets.any():
            status, _ = self.walk_to(lv, targets, grids=grids,
                                     chase=lambda r: next((k for k, m in goals.items() if m[r]), "frontier"))
            if status == "unreachable":
                lv.explored = True            # what frontier is left we can't get to
            if status == "moved":
                return
            if status == "here":
                lv.visited[start] += 1

        # nothing left to walk to here: go down if we know the way
        if downstairs.any() and self.go_down(lv, grids, downstairs):
            return

        # mines_return: nothing left to explore and no way down on a deep Mines level: Mines' End, the bottom
        if lv.key[0] == 2 and lv.key[1] >= 8 and not downstairs.any():
            self.mines_return_start(lv, "bottom")
            if self.mines_return_step(lv, grids):
                return
        # nothing left: a monster we won't melee may be all that separates us from the rest of the level
        if self.unblock_step(lv, grids, frontier | downstairs):
            return
        # the Mines' cave levels (mkmap) have no secret doors or corridors -- no way on found: leave the Mines
        # instead of searching -- but a Minetown of rooms and corridors is searched (minetown_rooms)
        if lv.key[0] == 2 and not self.mines_return_on and not self.minetown_rooms(lv):
            self.mines_return_start(lv, "no_way")
            if self.mines_return_step(lv, grids):
                return
        # nothing left: map the level if we can, else search for hidden passages
        if self.magic_map_step(lv):
            return
        self.search_mode(lv, grids)

    def go_down(self, lv, grids, downstairs):
        """On a down staircase: take it (after waiting a few turns for the pet); else step toward the nearest."""
        start = self.pos()
        if downstairs[start]:
            if self.pet_wait_before_stairs():
                self.press("s")
                return True
            if self.rest_before_descent(lv):
                return True
            self.mines_return_descents += self.mines_return_on
            self.take_stairs(">")
            return True
        return self.walk_to(lv, downstairs, chase="downstairs", grids=grids)[0] == "moved"

    def rest_before_descent(self, lv):
        """On the down staircase below REST_DESCEND_HP of max HP, nothing in view, not Weak: search (20s, the
        game stops it when something shows up) -- at most REST_DESCEND_MAX turns a level. True if it used the
        turn. (A/B rest_descend: +1416 [+390, +2448] over 1000 games.)"""
        hp, maxhp = self.bl(nh.NLE_BL_HP), self.bl(nh.NLE_BL_HPMAX)
        if hp >= maxhp * REST_DESCEND_HP or self.bl(nh.NLE_BL_HUNGER) >= WEAK or self.visible_hostiles(lv) \
                or self.descent_rest[lv.key] >= REST_DESCEND_MAX:
            return False
        t0 = self.turn()
        self.cur_act = "rest"
        self.search_turns(20)
        self.descent_rest[lv.key] += max(1, self.turn() - t0)
        return True

    def should_descend(self, lv, frontier, on_level):
        """Explored (no frontier left) or on this level for longer than descend_after turns."""
        return not frontier.any() or on_level > self.opts.descend_after

    def search_mode(self, lv, grids):
        k_mem, k_live, passable = grids
        if self.opts.search_log:
            self.search_log_note(lv, k_mem)
        self.cur_act = "search"
        start = self.pos()
        dist, prev, _ = self.dijkstra(lv, k_mem, k_live, passable, start, None)
        reach = dist < (1 << 30)
        wallish = (k_mem == G.WALL) | (k_mem == G.UNKNOWN)
        cnt = np.zeros((ROWS, COLS), dtype=np.int32)
        for dy, dx in NEIGH:
            cnt[max(0, dy):ROWS + min(0, dy), max(0, dx):COLS + min(0, dx)] += \
                wallish[max(0, -dy):ROWS + min(0, -dy), max(0, -dx):COLS + min(0, -dx)]
        wall_term = cnt * 10.0
        score = np.where(reach & passable, wall_term - lv.searched * 2.0 - np.minimum(dist, 500) * 0.3, -1e9)
        # dead-end corridors are prime spots
        goal = lv.search_goal
        if goal is not None and reach[goal] and passable[goal]:
            best = goal                       # committed: the distance term must not re-pick it every step
        else:
            best = self.search_v2_goal(lv, grids, dist) if self.opts.search_v2 else None
            if best is None:
                best = np.unravel_index(np.argmax(score), score.shape)
                if score[best] <= -1e8:
                    self.press("s")
                    return
                best = (int(best[0]), int(best[1]))
            lv.search_goal = best
        if best == start:
            lv.search_goal = None             # searched here: choose afresh next time
            lv.searched[start] += 10
            self.search_turns(10)
            return
        step = self.first_step(prev, start, best)
        if step:
            self.move(step)
        else:
            self.press("s")

    def mines_blocked(self):
        """The Mines staircase is closed: below XL mines_xl (mines_xl_open), while Excalibur can still be made
        at a fountain we know (excal_fountain_level), and once mines_return brought us back (the Mines are
        finished). A/B mines_xl 5 vs the Mines always open: +1041 [+135, +2013], then +2636 [+1582, +3695]."""
        if self.mines_done:
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
        if lv.key[0] != 0 or self.mines_done or not self.mines_xl_open() \
                or self.turn() < self.mines_trip_retry:
            return False
        branch = next((k for k, l in self.levels.items() if k[0] == 0 and self.mines_stairs(l)), None)
        if branch is None:
            return False
        fk = self.excal_fountain_level()
        if fk is not None:
            if fk != lv.key:
                if self.level_travel_step(lv, grids, fk, "excal", "excal_travel"):
                    return True
                self.mines_trip_stats["excal_no_way"] += 1
                self.excal_skip.add(fk)
                return False
            hp, maxhp = self.bl(nh.NLE_BL_HP), self.bl(nh.NLE_BL_HPMAX)
            if hp >= maxhp * self.opts.excal_hp or self.visible_hostiles(lv):
                return False
            self.cur_act = "rest"                # excal_step dips from excal_hp of max HP on
            self.mines_trip_stats["excal_rest"] += 1
            self.search_turns(20)
            return True
        if lv.key != branch:
            if self.level_travel_step(lv, grids, branch, "mines", "travel"):
                return True
            self.mines_trip_stats["no_way"] += 1
            self.mines_trip_retry = self.turn() + MINES_TRIP_RETRY
            return False
        down = np.zeros_like(grids[0], dtype=bool)
        for p in self.mines_stairs(lv):
            down[p] = True
        on = bool(down[self.pos()])
        if self.stairs_step(lv, grids, down, ">"):
            self.cur_act = "mines"
            self.mines_trip_stats["enter" if on else "to_stairs"] += 1
            return True
        self.mines_trip_stats["unreachable"] += 1
        self.mines_trip_retry = self.turn() + MINES_TRIP_RETRY
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
        if lv.key not in self.two_down_levels:
            self.two_down_levels.add(lv.key)
            self.mines_trip_stats["two_down"] += 1
        return downs - main

    def linked_stairs(self, lv, marks, kind):
        """The staircases of `kind` (G.UPSTAIR / G.DOWNSTAIR) that the noted squares of marks stand for. We note
        the square we arrive on, and that may be beside the staircase: a monster on it, half the time we land
        next to it (do.c u_collide_m, no message). So a noted square the map shows as that staircase -- or a
        boulder on it -- is it; one that shows something else stands for the staircases of that kind next to it.
        Squares where the game said there is no staircase (Level.not_stairs) never count."""
        k_mem = self.kinds(lv)
        out = set()
        for p in marks:
            if k_mem[p] in (kind, G.BOULDER):
                out.add(p)
                continue
            for dy, dx in NEIGH:
                q = (p[0] + dy, p[1] + dx)
                if 0 <= q[0] < ROWS and 0 <= q[1] < COLS and k_mem[q] == kind:
                    out.add(q)
        return out - lv.not_stairs

    def stairs_step(self, lv, grids, mask, key, max_cost=10_000):
        """To a staircase of mask and take it (down: go_down, with its pet wait and rest; up: within max_cost). The
        game saying there is none here: the square is noted (Level.not_stairs) -- no turn passed. True if it acted."""
        if key == ">":
            if not self.go_down(lv, grids, mask):
                return False
        elif mask[self.pos()]:
            self.take_stairs("<")
        else:
            return self.walk_to(lv, mask, grids=grids, max_cost=max_cost)[0] == "moved"
        if re.search(r"You can't go (?:down|up) here", self.message()):
            if not self.opts.stairs_refused:          # stairs_refused: msg_map records it, for every step
                lv.not_stairs.add(self.pos())
            self.mines_trip_stats["not_stairs"] += 1
        return True

    def level_travel_step(self, lv, grids, key, act, stat, known_only=False, max_cost=10_000):
        """One step toward main-dungeon level `key` from this one by the stairs we know: to an up staircase and
        up it, or down a down staircase -- never one we know leads elsewhere than the next main level (Sokoban's
        up staircase, the Mines'; Level.stairs_to, avoid_down, placed by linked_stairs); one we know leads there
        counts even if the map shows a boulder on it. known_only: while one is known to lead there, only that one
        (an up staircase not taken yet may be Sokoban's). Up: walked to within max_cost. False: no way known."""
        k_mem = grids[0]
        up_way = key[1] < lv.key[1]
        nxt = (0, lv.key[1] - 1 if up_way else lv.key[1] + 1)
        kind = G.UPSTAIR if up_way else G.DOWNSTAIR
        there = self.linked_stairs(lv, {p: k for p, k in lv.stairs_to.items() if k == nxt}, kind)
        elsewhere = self.linked_stairs(lv, {p: k for p, k in lv.stairs_to.items() if k != nxt}, kind)
        if not up_way:
            elsewhere |= self.mines_stairs(lv)
        mask = self.stairs_mask(lv, kind, k_mem)
        if known_only and there - lv.not_stairs:
            mask[:] = False
        for p in there:
            mask[p] = True
        for p in (elsewhere - there) | lv.not_stairs:
            mask[p] = False
        if not mask.any():
            return False
        self.cur_act = act
        if mask[self.pos()]:
            self.mines_trip_stats[stat + ("_up" if up_way else "_down")] += 1
        return self.stairs_step(lv, grids, mask, "<" if up_way else ">", max_cost=max_cost)

    def mines_tick(self, lv):
        """Every tick, before the steps: the branch level's Mines staircase marked (avoid_down) where mines_return or a
        bounce brought us back up; on a Mines level reached by a staircase while the Mines are closed (mines_blocked)
        -- straight back up (once a level); Minetown seen (or passed: mines_return); out of the Mines after
        mines_return -- the Mines are done. True if it took the stairs."""
        if self.pending_mines_mark:
            self.pending_mines_mark = False
            if lv.key[0] == 0:
                lv.avoid_down.add(self.pos())
        if self.mines_blocked() and lv.key[0] == 2 and lv.key not in self.mines_bounced \
                and self.arrived_by_stairs:
            self.mines_bounced.add(lv.key)
            self.pending_mines_mark = True
            self.take_stairs("<")
            return True
        if lv.key[0] == 2:
            folk = self.town_folk_visible()
            if folk and lv.key[1] in (3, 4):
                lv.town_heard = True                  # its watch / priest / shopkeeper in view (minetown_folk,
                                                      # accepted before its A/B was in)
            if self.is_minetown(lv) or folk:
                self.minetown_seen = True
            if not self.minetown_seen and lv.key[1] >= 5:
                self.mines_return_start(lv, "no_town")    # Minetown is Mines level 3 or 4: we passed it
        elif self.mines_return_on:
            self.mines_return_on = False
            self.mines_done = True
            self.mines_done_turn = self.turn()
        return False

    def mines_return_start(self, lv, why):
        if not self.mines_return_on:
            self.mines_return_on = True
            self.mines_return_log.append((self.turn(), list(lv.key), why, self.bl(nh.NLE_BL_DEPTH)))

    def mines_return_step(self, lv, grids):
        """mines_return: climb back to the main dungeon -- walk to this level's up staircase and take it; the
        branch staircase we arrive on gets the Mines mark (avoid_down), and mines_done keeps us out."""
        self.cur_act = "minesup"
        start = self.pos()
        up = self.stairs_mask(lv, G.UPSTAIR, grids[0])
        if up[start]:
            if lv.key[1] == 1:
                self.pending_mines_mark = True      # next tick, on the branch level: mark its Mines staircase
            self.take_stairs("<")
            return True
        return up.any() and self.walk_to(lv, up, grids=grids)[0] == "moved"

    def magic_map_step(self, lv):
        if lv.mapped:
            return False
        it = self.find_item(nh.SCROLL_CLASS, ("magic mapping",))
        if not it:
            return False
        lv.mapped = True
        if self.ask("r", "read"):
            self.press(it[0])
            self.maps_read += 1
            return True
        return False

    def pet_wait_before_stairs(self):
        """True if we should wait a turn on the stairs for a nearby pet."""
        g = self.obs["glyphs"]
        ys, xs = np.nonzero(G.KIND[g] == G.PET)
        if len(ys) == 0:
            self.pet_waits = 0
            return False
        y, x = self.pos()
        d = min(max(abs(a - y), abs(b - x)) for a, b in zip(ys, xs))
        far, turns = 7, 15
        if d <= 1 or d > far or self.pet_waits >= turns:
            self.pet_waits = 0
            return False
        self.pet_waits += 1
        self.pet_waited_total += 1
        return True
