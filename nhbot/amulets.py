"""Amulets (flag amulets): wear the best one we know by name, identify the unknown ones with a scroll of identify,
buy that scroll in a shop when we have none.

Wear: life saving > reflection > ESP > versus poison > magical breathing > unchanging (the owner's order); an
amulet still unknown is never put on (strangulation, restful sleep), nor a known-cursed one.
Identify: a scroll of identify -- by name, or by shop price (20 zm, the only scroll of that price: pricemem) --
is read with nothing threatening us while we carry an unidentified amulet; the menu (invent.c menu_identify:
one item, sometimes more) gets the amulets only, the rest of the menu is declined with ESC.
Buy: on a shop visit (carry.carry_shop_greeted: also started for this, in a shop that sells scrolls) with an
unknown amulet and no identify scroll: step on the scrolls for sale to read their tags, pick up an identify
scroll we can pay for, pay.
"""
import re
from collections import Counter

import numpy as np
import nle.nethack as nh

from nhbot.items import base_name
from nhbot.pricemem import appearance

WEAR_ORDER = ("life saving", "reflection", "ESP", "versus poison", "magical breathing", "unchanging")
AMULET_RE = re.compile(r"\bamulets? (?:of )?(life saving|reflection|ESP|versus poison|magical breathing|unchanging)\b")
IDENTIFY_RE = re.compile(r"\bscrolls? of identify\b")
SCROLL_SHOPS = ("general store", "second-hand bookstore", "rare books")
PRICE_RE = re.compile(r"for sale, (\d+) zorkmids?")
ID_MENU = "What would you like to identify"
MIN_PRICE = 20                   # the base price: no identify scroll costs less

SCROLL_GLYPH = np.zeros(nh.MAX_GLYPH, dtype=bool)
for _g in range(nh.MAX_GLYPH):
    if nh.glyph_is_object(_g) and ord(nh.objclass(nh.glyph_to_obj(_g)).oc_class) == nh.SCROLL_CLASS:
        SCROLL_GLYPH[_g] = True


def amulet_rank(text):
    """Index in WEAR_ORDER (0 best), None for an amulet we don't wear."""
    m = AMULET_RE.search(text)
    return WEAR_ORDER.index(m.group(1)) if m else None


class AmuletMixin:
    def amulets_init(self):
        self.amulet_stats = Counter()
        self.buy_browsed = set()         # (level key, square) of shop squares we stood on to read the tags
        self.pay_fails = 0
        self.amulet_refused = set()      # letters of amulets the game would not put on / take off

    # ------------------------------------------------------------ what we have
    def unknown_amulets(self):
        return [it for it in self.items() if it.ocls == nh.AMULET_CLASS and appearance(it.text) is not None
                and "unpaid" not in it.text]

    def is_identify(self, text):
        if IDENTIFY_RE.search(text):
            return True
        if appearance(text) is None or "labeled" not in text:
            return False
        post = self.type_posterior(text)
        return bool(post) and set(post) == {"identify"}

    def identify_scrolls(self):
        return [it for it in self.items() if it.ocls == nh.SCROLL_CLASS and "unpaid" not in it.text
                and self.is_identify(it.text)]

    def identify_wanted(self):
        """Carry an unknown amulet and no scroll to identify it (buying one is worth it)."""
        return self.opts.amulets and bool(self.unknown_amulets()) and not self.identify_scrolls()

    def identify_needed(self, it):
        """carry.needed: an identify scroll is kept (not sold / dropped) while an amulet is unknown."""
        return self.opts.amulets and it.ocls == nh.SCROLL_CLASS and bool(self.unknown_amulets()) \
            and self.is_identify(it.text)

    def buy_wanted(self, stype):
        return self.identify_wanted() and stype in SCROLL_SHOPS and self.bl(nh.NLE_BL_GOLD) >= MIN_PRICE

    # ------------------------------------------------------------ wear
    def amulet_wear_step(self, lv):
        """No threat in view: put on the best amulet we know (taking off a worse one). True if it acted."""
        if not self.opts.amulets or self.polyd or self.handless():
            return False
        items = self.items()
        worn = next((it for it in items if it.ocls == nh.AMULET_CLASS and it.worn), None)
        cands = [(amulet_rank(it.text), it) for it in items
                 if it.ocls == nh.AMULET_CLASS and not it.worn and not it.cursed and "unpaid" not in it.text
                 and amulet_rank(it.text) is not None and it.letter not in self.amulet_refused]
        if not cands:
            return False
        rank, best = min(cands, key=lambda c: c[0])
        if worn is not None:
            wr = amulet_rank(worn.text)
            if (wr is not None and wr <= rank) or worn.cursed or worn.letter in self.amulet_refused:
                return False
            self.cur_act = "amulet"
            seq0 = self.msg_seq
            self.press("R", expect_prompt=True)
            if self.obs["misc"][0] and "remove" in self.message().lower():
                self.press(worn.letter)
            else:
                self.settle()
            if "cursed" in self.text_since(seq0):
                self.amulet_refused.add(worn.letter)      # welded to our neck: keep it
            self.amulet_stats["removed"] += 1
            return True
        self.cur_act = "amulet"
        seq0 = self.msg_seq
        if not self.ask("P", "put on"):
            self.amulet_refused.add(best.letter)
            return True
        self.press(best.letter)
        if not any(it.worn and it.letter == best.letter for it in self.items()):
            self.amulet_refused.add(best.letter)
            self.amulet_stats["wear_failed"] += 1
        else:
            self.amulet_stats["worn_" + WEAR_ORDER[rank].replace(" ", "_")] += 1
        return True

    # ------------------------------------------------------------ identify
    def amulet_id_step(self, lv):
        """No threat in view: read an identify scroll on an unknown amulet. True if it used the turn."""
        if not self.opts.amulets or not self.unknown_amulets():
            return False
        cond = int(self.last_bl[nh.NLE_BL_CONDITION])
        if cond & (nh.BL_MASK_BLIND | nh.BL_MASK_CONF | nh.BL_MASK_STUN | nh.BL_MASK_HALLU):
            return False                       # confused: identifies only the scroll itself
        scrolls = self.identify_scrolls()
        if not scrolls:
            return False
        amulets = {it.letter for it in self.unknown_amulets()}
        self.cur_act = "identify"
        if not self.ask("r", "read"):
            return False
        self.press(scrolls[0].letter, expect_prompt=True)
        self.amulet_stats["read"] += 1
        for _ in range(4):
            tty = self.tty_text()
            if ID_MENU not in tty:
                break
            picks = [l for l, _ in self.menu_items(tty, ID_MENU) if l in amulets]
            if not picks:
                self.raw_step(27)                  # the rest of what a blessed scroll allows: declined
                break
            for l in picks:
                self.raw_step(ord(l))
                amulets.discard(l)
            self.amulet_stats["picked"] += len(picks)
            self.raw_step(13)
        self.settle()
        self.amulet_stats["named"] += sum(1 for it in self.items()
                                          if it.ocls == nh.AMULET_CLASS and appearance(it.text) is None)
        return True

    # ------------------------------------------------------------ buy
    def shop_buy_step(self, lv):
        """On a shop visit (shop.shop_step, after selling): pay for what we picked up, else go for an identify
        scroll for sale, else read the tags of the scrolls not looked at yet. True if it acted."""
        if not self.opts.amulets:
            return False
        unpaid = [it for it in self.items() if "unpaid" in it.text]
        if unpaid:
            self.cur_act = "buy"
            if self.pay_fails >= 3:                # can't pay: put it back
                self.drop_units(unpaid[0].letter)
                self.amulet_stats["put_back"] += 1
                return True
            gold0 = self.bl(nh.NLE_BL_GOLD)
            self.pay()
            if self.bl(nh.NLE_BL_GOLD) < gold0:
                self.amulet_stats["bought"] += 1
                self.pay_fails = 0
            else:
                self.pay_fails += 1
            return True
        gold = self.bl(nh.NLE_BL_GOLD)
        if not self.identify_wanted() or not lv.shop.any() or gold < MIN_PRICE:
            return False
        here = self.pos()

        def affordable(t, price):
            return self.is_identify(t) and price <= gold

        goals = np.zeros(lv.under.shape, dtype=bool)
        for (k, p), tags in self.for_sale.items():
            if k == lv.key and lv.shop[p] and any(affordable(t, pr) for t, pr in tags.items()):
                goals[p] = True
        if goals[here]:
            self.cur_act = "buy"
            self.pickup(lambda t: "for sale" in t and PRICE_RE.search(t) is not None
                        and affordable(t, int(PRICE_RE.search(t).group(1))), "buy")
            self.for_sale.pop((lv.key, here), None)
            self.amulet_stats["picked_up"] += 1
            return True
        if goals.any() and self.walk_to(lv, goals, act="buy")[0] == "moved":
            return True
        browse = lv.shop & SCROLL_GLYPH[lv.under]
        for k, p in self.buy_browsed | set(self.for_sale):
            if k == lv.key:
                browse[p] = False
        if browse[here]:
            self.buy_browsed.add((lv.key, here))
            self.look_here()                       # a pile: the tags show in the 'Things that are here' window
            return True
        if browse.any() and self.walk_to(lv, browse, act="buy_browse")[0] == "moved":
            self.amulet_stats["browse_steps"] += 1
            return True
        return False
