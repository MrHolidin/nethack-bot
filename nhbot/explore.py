"""Exploring a level and leaving it: frontier and item goals, when to descend, searching for hidden
passages, the Gnomish Mines (avoid_mines, mines_return), waiting for the pet, magic mapping."""
import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import COLS, NEIGH, ROWS
from nhbot.goals import GOALS


class ExploreMixin:
    def explore_init(self):
        self.maps_read = 0
        self.pet_waits = 0
        self.pet_waited_total = 0
        self.loot_holds = 0
        self.mines_return_descents = 0   # descents while climbing out of the Mines (the up/down loop)

    def explore(self, lv):
        self.cur_act = "explore"
        self.goal_observe(lv)
        k_mem, k_live = self.kind_grid(lv)
        passable = self.passable_grid(lv, k_mem, k_live)
        start = self.pos()
        y, x = start

        unknown = (k_mem == G.UNKNOWN) & ~lv.near
        dil = np.zeros_like(unknown)
        for dy, dx in NEIGH:
            dil[max(0, dy):ROWS + min(0, dy), max(0, dx):COLS + min(0, dx)] |= \
                unknown[max(0, -dy):ROWS + min(0, -dy), max(0, -dx):COLS + min(0, -dx)]
        frontier = passable & dil & (lv.visited == 0)
        if self.mines_return_on and lv.key[0] == 2 and self.mines_return_step(lv, k_mem, k_live, passable, start):
            return
        gold = (k_mem == G.GOLD) & passable
        for p in self.goal_closed_set("gold", lv.key):
            gold[p] = False
        downstairs = k_mem == G.DOWNSTAIR
        if self.opts.mines_up_first and self.mines_return_on and lv.key[0] == 2 and not (k_mem == G.UPSTAIR).any():
            # mines_up_first: climbing out of the Mines and this level's up staircase is not known yet -- find it
            # instead of going down (below, we stand on the up stairs and climb straight back: a loop)
            downstairs[:] = False
        on_level = self.turn() - (lv.entered_turn or 0)
        # the mines_after hatch counts from our first arrival here -- or, after mines_return, from the return
        # (the branch level was first entered long before, which re-opened the Mines at once)
        hatch = self.turn() - self.mines_done_turn if self.mines_done else on_level
        if lv.avoid_down and hatch < self.opts.mines_after and self.mines_blocked():
            for p in lv.avoid_down:
                downstairs[p] = False
        want_down = downstairs.any() and self.should_descend(lv, frontier, on_level)
        if want_down and lv.key[0] == 2 and lv.key[1] >= 4 \
                and not self.minetown_seen and not self.is_minetown(lv):
            # mines level 4 done and no Minetown on 3 or 4: it won't come further down
            self.mines_return_start(lv, "no_town")
            if self.mines_return_step(lv, k_mem, k_live, passable, start):
                return
        hold_loot = False
        if self.opts.loot_holds_descent and self.loot_sq is not None and self.loot_key == lv.key \
                and on_level <= self.opts.descend_after:
            m = np.zeros_like(gold)
            m[self.loot_sq] = True
            hold_loot = self.dijkstra(lv, k_mem, k_live, passable, start, m)[2] is not None
            if hold_loot and want_down:
                want_down = False
                self.loot_holds += 1
        if want_down \
                and on_level <= self.opts.descend_after:
            # explored, but something worth having still lies here: the same goals the target step below
            # will walk to (gold, armor/food/carry piles not yet inspected), so holding off is never idle
            stuff = np.zeros_like(gold)
            for kind, m in self.goal_masks(lv, passable, gold).items():
                if GOALS[kind].holds_descent:
                    stuff |= m
            stuff[y, x] = False
            if stuff.any():
                _, _, got = self.dijkstra(lv, k_mem, k_live, passable, start, stuff)
                if got is not None and got != start:
                    want_down = False
                    self.items_first_holds += 1

        if want_down and self.go_down(lv, k_mem, k_live, passable, downstairs):
            return

        goals = self.goal_masks(lv, passable, gold)
        targets = frontier.copy()
        for m in goals.values():
            targets |= m
        if targets.any():
            dist, prev, reached = self.dijkstra(lv, k_mem, k_live, passable, start, targets)
            if reached is not None and reached != start:
                step = self.first_step(prev, start, reached)
                if step:
                    self.goal_chase(next((k for k, m in goals.items() if m[reached]), "frontier"))
                    self.move(step)
                    return
            if reached == start:
                lv.visited[start] += 1

        # nothing left to walk to here: go down if we know the way
        if downstairs.any() and not hold_loot and self.go_down(lv, k_mem, k_live, passable, downstairs):
            return

        # mines_return: nothing left to explore and no way down on a deep Mines level: Mines' End, the bottom
        if lv.key[0] == 2 and lv.key[1] >= 8 and not downstairs.any():
            self.mines_return_start(lv, "bottom")
            if self.mines_return_step(lv, k_mem, k_live, passable, start):
                return
        # nothing left: a monster we won't melee may be all that separates us from the rest of the level
        if self.unblock_step(lv, k_mem, k_live, passable, frontier | downstairs):
            return
        # nothing left: map the level if we can, else search for hidden passages
        if self.magic_map_step(lv):
            return
        self.search_mode(lv, k_mem, k_live, passable)

    def go_down(self, lv, k_mem, k_live, passable, downstairs):
        """On a down staircase: take it (after waiting a few turns for the pet); else step toward the nearest."""
        start = self.pos()
        if downstairs[start]:
            if self.pet_wait_before_stairs():
                self.press("s")
                return True
            self.descents += 1
            self.mines_return_descents += self.mines_return_on
            self.took_stairs = True
            self.press(">")
            return True
        dist, prev, reached = self.dijkstra(lv, k_mem, k_live, passable, start, downstairs)
        if reached is not None:
            step = self.first_step(prev, start, reached)
            if step:
                self.goal_chase("downstairs")
                self.move(step)
                return True
        return False

    def should_descend(self, lv, frontier, on_level):
        """Explored (no frontier left) or on this level for longer than descend_after turns."""
        return not frontier.any() or on_level > self.opts.descend_after

    def search_mode(self, lv, k_mem, k_live, passable):
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
            best = np.unravel_index(np.argmax(score), score.shape)
            if score[best] <= -1e8:
                self.press("s")
                return
            best = (int(best[0]), int(best[1]))
            lv.search_goal = best
        if best == start:
            lv.search_goal = None             # searched here: choose afresh next time
            lv.searched[start] += 10
            self.press("1"); self.press("0"); self.press("s")
            return
        step = self.first_step(prev, start, best)
        if step:
            self.move(step)
        else:
            self.press("s")

    def mines_blocked(self):
        """avoid_mines: True/False, or "until_excalibur": lawful long-sword users first look for
        Excalibur in the main dungeon (the Mines have no usable fountains)."""
        if self.mines_done:
            return True                       # mines_return brought us back: the Mines are finished
        if self.opts.avoid_mines == "until_excalibur":
            return int(self.last_bl[nh.NLE_BL_ALIGN]) == 1 and not self.excalibur \
                and self.long_sword() is not None and self.turn() < 8000
        return bool(self.opts.avoid_mines)

    def mines_return_start(self, lv, why):
        if not self.mines_return_on:
            self.mines_return_on = True
            self.mines_return_log.append((self.turn(), list(lv.key), why, self.bl(nh.NLE_BL_DEPTH)))

    def mines_return_step(self, lv, k_mem, k_live, passable, start):
        """mines_return: climb back to the main dungeon -- walk to this level's up staircase and take it; the
        branch staircase we arrive on gets the Mines mark (avoid_down), and mines_done keeps us out."""
        self.cur_act = "minesup"
        up = k_mem == G.UPSTAIR
        if up[start]:
            if lv.key[1] == 1:
                self.pending_mines_mark = True      # next tick, on the branch level: mark its Mines staircase
            self.took_stairs = True
            self.press("<")
            return True
        if not up.any():
            return False
        dist, prev, reached = self.dijkstra(lv, k_mem, k_live, passable, start, up)
        if reached is None:
            return False
        step = self.first_step(prev, start, reached)
        if not step:
            return False
        self.move(step)
        return True

    def magic_map_step(self, lv):
        if lv.mapped:
            return False
        it = self.find_item(nh.SCROLL_CLASS, ("magic mapping",))
        if not it:
            return False
        lv.mapped = True
        self.press("r", expect_prompt=True)
        if "read" in self.message().lower():
            self.press(it[0])
            self.maps_read += 1
            return True
        self.settle()
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
