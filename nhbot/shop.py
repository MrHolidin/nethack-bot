"""Shop visits: the shared state for a visit (selling in carry.py) and paying."""
import re
from nhbot.carry import LEAVE_RE


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
            self.carry_shop_greeted(lv, stype)

    def shop_visits_on(self):
        """An option that walks into shops is on: shop safety rules apply (merchandise, shop gold,
        a peaceful shopkeeper is not a threat)."""
        return self.carry_on()

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
        return self.carry_sell_step(lv)

    def msg_shop(self, m, lv):
        """Price tags, entering a shop, the digger request, the bill."""
        if "for sale" in m:
            self.price_note_text(m)
        # the square under us is often not in our map memory yet, so 'on the door' can't be checked;
        # instead: we are inside only if we just fell / were teleported onto this level
        recent = " ".join(mm for _, mm in list(self.messages)[-6:])
        on_door = not any(k in recent for k in ("trap door", "fall through", "hole", "teleport",
                                                 "wrenching", "You materialize"))
        if lv and re.search(r"Welcome to [A-Z][\w' -]*'s ", m) and on_door:
            # shop entrance: mark the shop from the door -- after falling in through a trap door we are
            # inside, and marking from there walls us in
            self.mark_shop(lv, self.pos())
            self.shops_seen += 1
            self.shop_greeted(lv, m)
        if LEAVE_RE.search(m):
            self.stash_request()
        if "Please pay before leaving" in m or "you owe" in m.lower() and "zorkmid" in m:
            self.need_pay = True
