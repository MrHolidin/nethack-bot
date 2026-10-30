"""Buying armor in shops (wiki, Tourist: "Shops are the best early upgrade").

Only armor shops ("used armor dealership") and general stores, only with gold in hand and
no pick-axe (shopkeepers bar diggers). Inside: walk to each '[' pile, read the price with
':', take what the armor module considers an upgrade if we can afford it, pay at once,
then leave. Wearing happens through the normal equipment logic.
"""
import re

import numpy as np
import nle.nethack as nh

import glyphs as G
from equipment import parse_armor

BUY_TYPES = ("used armor dealership", "general store")


class ShopMixin:
    def shop_init(self):
        self.shopping = None
        self.purchases = []
        self.shop_visits = 0

    def can_shop(self):
        if not self.role_opts.get("shop", False):
            return False
        if self.bl(nh.NLE_BL_GOLD) < 20:
            return False
        if any(("pick-axe" in s or "mattock" in s) for _, _, s in self.inventory()):
            return False
        return True

    def shop_greeted(self, lv, m):
        mm = re.search(r"Welcome to [A-Z][\w' -]*?'s ([a-z ]+)!", m)
        if not mm:
            return
        stype = mm.group(1)
        lv.shop_type = stype
        if self.shopping is None and hasattr(self, "scroll_shop_greeted"):
            self.scroll_shop_greeted(lv, stype)
        if stype in BUY_TYPES and self.can_shop() and lv.key not in self.shops_done:
            self.shopping = {"key": lv.key, "until": self.turn() + 200}
            self.shop_visits += 1

    def shop_active(self, lv):
        s = self.shopping
        return s is not None and s["key"] == lv.key and self.turn() < s["until"]

    def shop_targets(self, lv):
        mask = G.ARMOR_GLYPH[lv.under] & lv.shop
        for p in self.inspected.get(lv.key, ()):
            mask[p] = False
        return mask

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
        if self.shopping.get("kind") == "scroll":
            return self.scroll_shop_step(lv)
        targets = self.shop_targets(lv)
        y, x = self.pos()
        if not targets.any() or self.bl(nh.NLE_BL_GOLD) < 20:
            self.shops_done.add(lv.key)
            self.shopping = None
            return False
        if targets[y, x]:
            self.inspected.setdefault(lv.key, set()).add((y, x))
            worn = self.worn_by_slot()
            gold = self.bl(nh.NLE_BL_GOLD)
            for n in self.look_here():
                pm = re.search(r"for sale, (\d+) zorkmids", n)
                if not pm:
                    continue
                price = int(pm.group(1))
                a = parse_armor(n)
                if a and self.improves(a, worn) and price <= gold:
                    self.pickup_matching([a["name"]])
                    self.pay()
                    self.purchases.append((self.turn(), a["name"], price))
                    return True
            return True
        return self.go_toward_mask(lv, targets)

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
        if hasattr(self, "set_nav"):
            self.set_nav(lv, reached)
        self.move(step)
        return True
