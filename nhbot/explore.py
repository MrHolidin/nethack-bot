"""Exploring a level and leaving it: frontier and item goals, when to descend, searching for hidden
passages, travel between levels (linked_stairs, stairs_step, level_travel_step), waiting for the pet, magic mapping.
The Gnomish Mines trip and return: nhbot.mines."""
import re
from collections import Counter

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import COLS, NEIGH, ROWS, WEAK
from nhbot.goals import GOALS

REST_DESCEND_MAX = 600      # ... at most this many turns a level


PET_GONE_WAIT = 10          # pet_gone_wait: turns at most waiting for a pet that just went out of view

class ExploreState:
    """State of exploring and descending (ExploreMixin)."""
    def __init__(self):
        self.maps_read = 0
        self.pet_waits = 0
        self.pet_waited_total = 0
        self.pet_gone = None        # pet_gone_wait: (turn the pet was last seen, turn we began waiting)
        self.pet_gone_waits = 0
        self.descent_rest = Counter()    # level key -> turns rested on its down staircase
        self.items_first_holds = 0       # descents held for an item goal still on the level
        self.revisit_done = set()        # revisit_up: level keys we climbed back to
        self.revisit_stats = Counter()


class ExploreMixin:
    def explore_init(self):
        self.expl = ExploreState()

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
        if self.mines.return_on and lv.key[0] == 2 and self.mines_return_step(lv, grids):
            return
        if self.mines_trip_step(lv, grids):
            return
        gold = (G.KIND[lv.under] == G.GOLD) & passable    # an item: the top glyph, not the terrain under it
        for p in self.goal_closed_set("gold", lv.key):
            gold[p] = False
        downstairs = self.stairs_mask(lv, G.DOWNSTAIR, k_mem)
        # turns spent on this level (Level.turns_here) -- since the first arrival, a level re-entered counted the
        # whole time away: descend_after / the mines_after hatch ran out at once
        # (A/B level_time: -466 [-1860, +966], median 7726 -> 7768, 470 of 1000 changed)
        on_level = lv.turns_here
        # the mines_after hatch counts from our first arrival here -- or, after mines_return, from the return
        # (the branch level was first entered long before, which re-opened the Mines at once)
        hatch = self.turn() - self.mines.done_turn if self.mines.done else on_level
        # the closed Mines staircase as mines_stairs places it -- an avoid_down mark is the square we arrived on,
        # often beside the staircase (linked_stairs), and the stairs taken / two_down count too
        # (A/B mines_mask: -43 [-100, +6], 6 games of 1000 changed)
        closed = self.mines_stairs(lv) if lv.key[0] == 0 else set()
        if closed and hatch < self.opts.mines_after and self.mines_blocked():
            for p in closed:
                downstairs[p] = False
        if self.mines.return_on and lv.key[0] == 2:
            # climbing out of the Mines: no way down is a way on -- a level whose up staircase is unknown is explored
            # for it (descend_after, counted from the first visit, used to send us down at once and back up: a loop)
            downstairs[:] = False
        want_down = downstairs.any() and self.should_descend(lv, frontier, on_level)
        if want_down and lv.key[0] == 2 and lv.key[1] >= 4 \
                and not self.mines.minetown_seen and not self.is_minetown(lv):
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
                    self.expl.items_first_holds += 1

        if self.sokoban_trip_step(lv, grids, want_down or lv.explored):
            return
        if want_down and self.revisit_up(lv, grids):
            return
        if want_down and self.go_down(lv, grids, downstairs):
            return

        goals = self.goal_masks(lv, passable, gold)
        targets = frontier.copy()
        for m in goals.values():
            targets |= m
        # a goal on our own square was the consuming step's to take this tick (housekeeping, gold_here, melee); it
        # declined (the altar with a hostile in view) -- walk on to the others instead of "here" ending exploring
        # (frontier never covers our square: visited) (A/B goal_here: +618 [-96, +1316], median 7777 -> 7571)
        targets[y, x] = False
        if targets.any():
            status, reached = self.walk_to(lv, targets, grids=grids,
                                           chase=lambda r: next((k for k, m in goals.items() if m[r]), "frontier"))
            lv.unexplored = status == "moved" and bool(frontier[reached]) and on_level <= self.opts.descend_after
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
        if lv.key[0] == 2 and lv.key[1] >= 8 and not downstairs.any() and not self.level_held(lv):
            self.mines_return_start(lv, "bottom")
            if self.mines_return_step(lv, grids):
                return
        # (A/B look_under -- stood once on every item / statue square before searching: -1889 [-3311, -454], median 7561)
        # nothing left: a monster we won't melee may be all that separates us from the rest of the level
        if self.unblock_step(lv, grids, frontier | downstairs):
            return
        # the Mines' cave levels (mkmap) have no secret doors or corridors -- no way on found: leave the Mines
        # instead of searching -- but a Minetown of rooms and corridors is searched (minetown_rooms)
        if lv.key[0] == 2 and not self.mines.return_on and not self.minetown_rooms(lv) and not self.level_held(lv):
            self.mines_return_start(lv, "no_way")
            if self.mines_return_step(lv, grids):
                return
        # nothing left: map the level if we can, else search for hidden passages
        if self.magic_map_step(lv):
            return
        self.search_mode(lv, grids)

    def revisit_up(self, lv, grids):
        """Done here and about to go down, but the level above (same branch) was never seen (we fell past it) or
        was left with a frontier still in reach (a hole, a trap door, a teleport): climb back to it first -- once
        per level. True if it used the turn. (A/B revisit_up: +194 [-1192, +1616] on 79k with 2 crashes in other
        code, fixed at 10c24b1 -- +431 with those two games replayed; in the 379 games it fired median +2343;
        accepted, the user's decision.)"""
        if self.mines.return_on or lv.key[1] <= 1:
            return False
        above = (lv.key[0], lv.key[1] - 1)
        prev = self.levels.get(above)
        if above in self.expl.revisit_done or (prev is not None and not prev.unexplored):
            return False
        up = grids[0] == G.UPSTAIR
        if up[self.pos()]:
            self.expl.revisit_done.add(above)
            lv.unexplored = False             # done here too
            self.expl.revisit_stats["never_seen" if prev is None else "unexplored"] += 1
            self.cur_act = "revisit"
            self.take_stairs("<")
            return True
        return bool(up.any()) and self.walk_to(lv, up, act="revisit", grids=grids)[0] == "moved"

    def go_down(self, lv, grids, downstairs):
        """On a down staircase: take it (after waiting a few turns for the pet); else step toward the nearest."""
        start = self.pos()
        if downstairs[start]:
            if self.pet_wait_before_stairs():
                self.press("s")
                return True
            if self.rest_before_descent(lv):
                return True
            self.mines_descent()
            lv.unexplored = False             # left on purpose: done here
            self.take_stairs(">")
            return True
        return self.walk_to(lv, downstairs, chase="downstairs", grids=grids)[0] == "moved"

    def rest_before_descent(self, lv):
        """On the down staircase below descend_rest_hp of max HP, nothing in view, not Weak: search (20s, the
        game stops it when something shows up) -- at most REST_DESCEND_MAX turns a level. True if it used the
        turn. (A/B rest_descend: +1416 [+390, +2448] over 1000 games.)"""
        if not self.hp_below(self.opts.descend_rest_hp) or self.bl(nh.NLE_BL_HUNGER) >= WEAK \
                or self.visible_hostiles(lv) or self.expl.descent_rest[lv.key] >= REST_DESCEND_MAX:
            return False
        t0 = self.turn()
        self.cur_act = "rest"
        self.search_turns(20)
        self.expl.descent_rest[lv.key] += max(1, self.turn() - t0)
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
            self.mines_trip_stat("not_stairs")           # msg_map recorded it (Level.not_stairs)
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
            self.mines_trip_stat(stat + ("_up" if up_way else "_down"))
        return self.stairs_step(lv, grids, mask, "<" if up_way else ">", max_cost=max_cost)

    def magic_map_step(self, lv):
        if lv.mapped:
            return False
        it = self.find_item(nh.SCROLL_CLASS, ("magic mapping",))
        if not it:
            return False
        lv.mapped = True
        if self.ask("r", "read"):
            self.press(it[0])
            self.expl.maps_read += 1
            return True
        return False

    def pet_gone_wait_step(self):
        """A/B pet_gone_wait: the pet was in view a turn ago and is not now -- wait for it on the spot ("s"), up to
        PET_GONE_WAIT turns, till it shows again (once per time it goes out of view). True if it waited."""
        if not self.opts.pet_gone_wait:
            return False
        t, last, st = self.turn(), self.pol.pet_last_seen, self.expl
        if last == t or last == 0:
            return False                      # in view, or never had one
        if st.pet_gone is None or st.pet_gone[0] != last:
            if last < t - 1:
                return False                  # not gone just now
            st.pet_gone = (last, t)
        if t - st.pet_gone[1] >= PET_GONE_WAIT:
            return False
        self.cur_act = "pet_wait"
        st.pet_gone_waits += 1
        self.press("s")
        return True

    def pet_wait_before_stairs(self):
        """True if we should wait a turn on the stairs for a nearby pet."""
        g = self.obs["glyphs"]
        ys, xs = np.nonzero(G.KIND[g] == G.PET)
        if len(ys) == 0:
            self.expl.pet_waits = 0
            return False
        y, x = self.pos()
        d = min(max(abs(a - y), abs(b - x)) for a, b in zip(ys, xs))
        far, turns = 7, 15
        if d <= 1 or d > far or self.expl.pet_waits >= turns:
            self.expl.pet_waits = 0
            return False
        self.expl.pet_waits += 1
        self.expl.pet_waited_total += 1
        return True
