"""Path finding and single steps: Dijkstra over the remembered map, moving (door kicks, peaceful
monsters in the way, failed moves), walking toward a square or a set of squares."""
import heapq

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import COLS, DELTA2KEY, NEIGH, ROWS


class NavMixin:
    def dijkstra(self, lv, k_mem, k_live, passable, start, targets_mask=None, max_cost=10_000):
        INF = 1 << 30
        dist = np.full((ROWS, COLS), INF, dtype=np.int64)
        prev = {}
        sy, sx = start
        dist[sy, sx] = 0
        pq = [(0, sy, sx)]
        door_like = (k_mem == G.DOOR_OPEN) | (k_mem == G.DOOR_CLOSED)
        monster_here = (k_live == G.MONSTER) | (k_live == G.INVIS)
        while pq:
            d, y, x = heapq.heappop(pq)
            if d > dist[y, x]:
                continue
            if targets_mask is not None and targets_mask[y, x]:
                return dist, prev, (y, x)
            if d > max_cost:
                break
            for dy, dx in NEIGH:
                ny, nx = y + dy, x + dx
                if not (0 <= ny < ROWS and 0 <= nx < COLS) or not passable[ny, nx]:
                    continue
                if dy and dx and (door_like[y, x] or door_like[ny, nx]):
                    continue
                c = 1
                km = k_mem[ny, nx]
                if km == G.TRAP:
                    c = 40
                elif km == G.BOULDER or k_live[ny, nx] == G.BOULDER:
                    c = 15
                elif km == G.DOOR_CLOSED:
                    c = 3 if (ny, nx) not in lv.locked else 12
                if monster_here[ny, nx]:
                    c += 4
                if lv.fail[ny, nx]:
                    c += 5 * lv.fail[ny, nx]
                nd = d + c
                if nd < dist[ny, nx]:
                    dist[ny, nx] = nd
                    prev[(ny, nx)] = (y, x)
                    heapq.heappush(pq, (nd, ny, nx))
        return dist, prev, None

    @staticmethod
    def first_step(prev, start, goal):
        cur = goal
        while prev.get(cur) != start:
            cur = prev.get(cur)
            if cur is None:
                return None
        return cur

    def go_toward(self, lv, goal):
        k_mem, k_live = self.kind_grid(lv)
        p = self.passable_grid(lv, k_mem, k_live)
        mask = np.zeros((ROWS, COLS), dtype=bool)
        mask[goal] = True
        start = self.pos()
        dist, prev, reached = self.dijkstra(lv, k_mem, k_live, p, start, mask)
        if reached is None:
            return False
        step = self.first_step(prev, start, reached)
        if step is None:
            return False
        self.move(step)
        return True

    def go_toward_mask(self, lv, mask):
        k_mem, k_live = self.kind_grid(lv)
        p = self.passable_grid(lv, k_mem, k_live)
        start = self.pos()
        dist, prev, reached = self.dijkstra(lv, k_mem, k_live, p, start, mask)
        if reached is None:
            self.shops_done.add(lv.key)
            self.shopping = None
            return False
        step = self.first_step(prev, start, reached)
        if step is None:
            return False
        self.move(step)
        return True

    def move(self, target):
        y, x = self.pos()
        ty, tx = target
        key = DELTA2KEY[(ty - y, tx - x)]
        self.last_move_target = target
        before = (y, x, self.turn())
        lv = self.level()
        if target in lv.locked:
            if any(max(abs(cy - ty), abs(cx - tx)) <= 1 for cy, cx in lv.cfi):
                lv.blocked[ty, tx] = True     # closed shop: kicking the door angers the shopkeeper
                self.shop_kicks_avoided += 1
                return
            if lv.key[0] == 2 or self.law_nearby():
                lv.blocked[ty, tx] = True     # never kick doors in the Mines (Minetown watch)
                return
            self.kick(key)
            return
        if G.KIND[self.obs["glyphs"][target]] == G.MONSTER and self.is_peaceful(target):
            lv.fail[ty, tx] += 1
            self.press("s")
            return
        self.press(key)
        after = (*self.pos(), self.turn())
        if after[:2] == before[:2] and self.cur_key == (self.bl(nh.NLE_BL_DNUM), self.bl(nh.NLE_BL_DLEVEL)):
            lv.fail[ty, tx] += 1
            if lv.fail[ty, tx] >= 6:
                lv.blocked[ty, tx] = True

    def kick(self, key):
        self.press(4, expect_prompt=True)   # ^D
        if self.obs["misc"][0] or "direction" in self.message().lower():
            self.press(key)
        else:
            self.settle()
        m = " ".join(t for _, t in list(self.messages)[-3:])
        if "crashes open" in m or "shatters" in m or "breaks open" in m:
            self.level().locked.discard(self.last_move_target)
