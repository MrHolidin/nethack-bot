"""Shop visits: the shared state for a visit (scroll price-ID in scrolls.py) and paying."""
import re

import numpy as np
import nle.nethack as nh

import glyphs as G


class ShopMixin:
    def shop_init(self):
        self.shopping = None

    def shop_greeted(self, lv, m):
        mm = re.search(r"Welcome to [A-Z][\w' -]*?'s ([a-z ]+)!", m)
        if not mm:
            return
        stype = mm.group(1)
        lv.shop_type = stype
        if self.shopping is None:
            self.scroll_shop_greeted(lv, stype)

    def shop_active(self, lv):
        s = self.shopping
        return s is not None and s["key"] == lv.key and self.turn() < s["until"]

    def pay(self):
        self.press("p", expect_prompt=True)
        for _ in range(4):
            m = self.message().lower()
            if "itemized billing" in m:
                self.press("n", expect_prompt=True)
                continue
            if self.obs["misc"][0] and "pay" in m:
                self.press("y", expect_prompt=True)
                continue
            break
        self.settle()

    def shop_step(self, lv):
        """Returns True if it used the turn (or did a free action worth re-ticking)."""
        if self.shopping is None:
            return False
        if not self.shop_active(lv):
            self.shops_done.add(self.shopping["key"])
            self.shopping = None
            return False
        return self.scroll_shop_step(lv)
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
