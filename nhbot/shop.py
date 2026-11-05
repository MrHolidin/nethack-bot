"""Shop visits: the shared state for a visit (selling in carry.py) and paying."""
import re

import numpy as np
import nle.nethack as nh

from nhbot.carry import LEAVE_RE


# shk.c: "Welcome to Asidonhopo's general store!" -- a name ending in s takes only the apostrophe
# ("Kinojevis' general store"); those shops used to go unmarked (nothing sold there)
# a later visit says "Welcome again to ..." (shk.c u_entered_shop); every greeting marks the shop again -- the
# first one often comes while we stand in the door seeing nothing inside yet (a keeper blocking for a pick-axe,
# a wall just repaired), which marked nothing
SHOP_WELCOME_RE = re.compile(r"Welcome(?: again)? to [A-Z][\w' -]*?(?:'s|s') ([^!]+)!")
# hack.c check_special_room: entering a zoo says "Welcome to David's treasure zoo!" -- the same shape as a shop
# greeting, but no shop (zoo_not_shop)
ZOO_WELCOME = "Welcome to David's treasure zoo!"
# merchandise: an object glyph other than a boulder / statue (ROCK_CLASS)
ITEM_GLYPH = np.zeros(nh.MAX_GLYPH, dtype=bool)
for _g in range(nh.MAX_GLYPH):
    if nh.glyph_is_object(_g) and ord(nh.objclass(nh.glyph_to_obj(_g)).oc_class) != nh.ROCK_CLASS:
        ITEM_GLYPH[_g] = True
ARRIVED_RE = re.compile(r"trap door|fall through|\bhole\b|teleport|wrenching|You materialize")   # this tick


class ShopMixin:
    def shop_init(self):
        self.shopping = None
        self.shop_browsed = set()        # (level key, square) of shop squares we stood on to read the tags
        self.browse_stats = {"steps": 0, "looks": 0}

    def shop_welcome(self, m):
        """A shopkeeper's greeting in m (the regex match, its group 1 the shop type), or None. zoo_not_shop: the
        zoo's greeting is none -- taken for one, the zoo was marked a shop, closed to us from outside (80014:
        the only way between two halves of the level, 4000 turns of searching)."""
        if self.opts.zoo_not_shop:
            m = m.replace(ZOO_WELCOME, "")
        return SHOP_WELCOME_RE.search(m)

    def shop_greeted(self, lv, m):
        mm = self.shop_welcome(m)
        if not mm:
            return
        stype = mm.group(1)
        lv.shop_type = stype
        if self.shopping is None:
            self.carry_shop_greeted(lv, stype)

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
        if self.carry_sell_step(lv):
            return True
        if self.shopping is not None and self.shop_buy_step(lv):
            return True
        if self.shopping is not None and self.opts.shop_browse and self.browse_step(lv, ITEM_GLYPH, "browse"):
            return True
        if self.shopping is not None:
            self.shops_done.add(self.shopping["key"])
            self.shopping = None
        return False

    def browse_step(self, lv, glyph_mask, act):
        """In a shop: walk onto the shop squares showing an item of glyph_mask whose tag we have not read
        ('You see here ... (for sale, N zorkmids)' when we step there, ':' on a pile). True if it acted."""
        here = self.pos()
        todo = lv.shop & glyph_mask[lv.under]
        for k, p in self.shop_browsed | set(self.for_sale):
            if k == lv.key:
                todo[p] = False
        if todo[here]:
            self.shop_browsed.add((lv.key, here))
            self.look_here()                       # a pile: the tags show in the 'Things that are here' window
            self.browse_stats["looks"] += 1
            return True
        if todo.any() and self.walk_to(lv, todo, act=act)[0] == "moved":
            self.browse_stats["steps"] += 1
            return True
        return False

    def msg_shop(self, m, lv):
        """Price tags, entering a shop, the digger request, the bill."""
        if "for sale" in m:
            self.price_note_text(m)
        # the square under us is often not in our map memory yet, so 'on the door' can't be checked;
        # instead: we are inside only if we just fell / were teleported onto this level
        if lv and self.shop_welcome(m) and not ARRIVED_RE.search(self.text_since(self.tick_seq)):
            # shop entrance: mark the shop from the door -- after falling in through a trap door we are
            # inside, and marking from there walls us in
            self.mark_shop(lv, self.pos())
            self.shops_seen += 1
            self.shop_greeted(lv, m)
        if LEAVE_RE.search(m):
            self.stash_request()
        if "Please pay before leaving" in m or "you owe" in m.lower() and "zorkmid" in m:
            self.need_pay = True
