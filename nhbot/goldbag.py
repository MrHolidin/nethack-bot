"""gold_bag: our gold kept in a bag while a leprechaun is in view -- a leprechaun steals only the gold we carry
loose (steal.c stealgold: findgold(invent)), not what is in a container -- and taken back out in a shop, where it
pays. One bag that is not a bag of tricks is needed (carry.py: never sold, never dropped)."""

import re
from collections import Counter

import numpy as np
import nle.nethack as nh

from nhbot.game import MENU_ITEM_GOLD_RE

BAG_WORDS = ("bag", "sack")
BAG_RANK = ("holding", "oilskin", "sack")      # the bag used: the first of these we carry, else a plain "bag"
BAG_PRICE_RE = re.compile(r"for sale, (\d+) zorkmids?")
# the four bags look alike ("bag", objects.c): sack, oilskin sack, bag of holding, bag of tricks
BAG_GLYPH = np.zeros(nh.MAX_GLYPH, dtype=bool)
for _g in range(nh.MAX_GLYPH):
    if nh.glyph_is_object(_g) and nh.OBJ_DESCR(nh.objclass(nh.glyph_to_obj(_g))) == "bag":
        BAG_GLYPH[_g] = True


class GoldBagMixin:
    def goldbag_init(self):
        self.bag_gold = 0             # gold we put in the bag and did not take out
        self.bag_bad = set()          # item keys of bags that are not containers (a bag of tricks: no menu)
        self.bag_stats = Counter()
        self.bag_moved = False        # gold moved between us and the bag since the last tick (gold_flow_tick)

    def gold_bag(self):
        """The bag our gold goes in: carried, not a bag of tricks, not known cursed (a cursed bag of holding
        loses what is in it, pickup.c boh_loss) -- a bag of holding first. None: no such bag."""
        if not self.opts.gold_bag:
            return None
        bags = [it for it in self.items() if it.ocls == nh.TOOL_CLASS and any(w in it.text for w in BAG_WORDS)
                and "tricks" not in it.text and not it.cursed and it.key not in self.bag_bad]
        rank = lambda it: next((i for i, w in enumerate(BAG_RANK) if w in it.text), len(BAG_RANK))
        return min(bags, key=rank) if bags else None

    def gold_bag_step(self, lv, hostiles):
        """gold_bag: in a shop, the gold in the bag taken out; elsewhere, a leprechaun in view, no other hostile
        next to us and gold on us -- put in the bag. True if it used the turn."""
        bag = self.gold_bag()
        if bag is None:
            return False
        in_shop = bool(lv.shop[self.pos()])
        if in_shop and self.bag_gold > 0:
            return self.bag_take_out(bag)
        if not in_shop and int(self.bl(nh.NLE_BL_GOLD)) > 0 and self.lep_visible() \
                and not any(n != "leprechaun" for _, n in hostiles):
            return self.bag_put_in(bag)
        return False

    def gold_bag_unload(self, it):
        """gold_bag: it, about to be dropped (carry_drop_step: Burdened, a squeeze refused for our weight), is
        the bag with our gold in it -- the gold taken out first (coins are never what that step drops). True if
        it used the turn."""
        bag = self.gold_bag()
        if bag is None or bag.letter != it.letter or self.bag_gold <= 0:
            return False
        self.bag_stats["unload_before_drop"] += 1
        return self.bag_take_out(bag)

    def bag_buy_step(self, lv):
        """gold_bag, on a shop visit (shop.shop_step), no bag of ours to use and nothing unpaid: a bag for sale we
        can pay for -- the cheapest (a 2-zorkmid one is a sack, never a bag of tricks) -- picked up (paid for
        by shop_buy_step); bags whose tags we have not read: walked onto. True if it acted."""
        if not self.opts.gold_bag or self.gold_bag() is not None or any("unpaid" in it.text for it in self.items()):
            return False
        gold = int(self.bl(nh.NLE_BL_GOLD))
        here = self.pos()

        is_bag = lambda t: any(w in t for w in BAG_WORDS) and "tricks" not in t

        def price(t):                                     # a line of the pick-up menu
            m = BAG_PRICE_RE.search(t)
            return int(m.group(1)) if m and is_bag(t) else None

        offers = {}                                       # square -> cheapest affordable bag there
        for (k, p), tags in self.for_sale.items():
            ok = [pr for t, pr in tags.items() if is_bag(t) and pr <= gold]
            if k == lv.key and lv.shop[p] and ok:
                offers[p] = min(ok)
        if offers:
            best = min(offers, key=lambda p: (offers[p], max(abs(p[0] - here[0]), abs(p[1] - here[1]))))
            if here == best:
                self.cur_act = "buy_bag"
                taken = []
                self.pickup(lambda t: not taken and price(t) == offers[best] and not taken.append(t), "buy_bag")
                self.for_sale.pop((lv.key, here), None)
                self.shop_browsed.add((lv.key, here))     # not walked onto again to read its tag
                got = any("unpaid" in it.text and any(w in it.text for w in BAG_WORDS) for it in self.items())
                self.bag_stats["picked_up_for_sale" if got else "not_lifted"] += 1   # too heavy: Burdened
                return True
            mask = np.zeros(lv.under.shape, dtype=bool)
            mask[best] = True
            if self.walk_to(lv, mask, act="buy_bag")[0] == "moved":
                return True
        return self.browse_step(lv, BAG_GLYPH, "buy_bag_browse")

    def bag_open(self, bag):
        """Apply the bag: True if its "Do what with ..." menu is up. A bag that gives none (a bag of tricks
        makes a monster or bites) is not used again."""
        self.cur_act = "gold_bag"
        if not self.ask("a", "apply"):
            return False
        self.press(bag.letter, expect_prompt=True)
        if "Do what with" in self.tty_text():
            return True
        self.settle()
        self.bag_bad.add(bag.key)
        self.bag_stats["not_a_container"] += 1
        return False

    def bag_choose(self, key):
        """A pick-one entry of the bag's menu (pickup.c in_or_out_menu: o take out, s stash one item)."""
        self.raw_step(ord(key))
        if "Do what with" in self.tty_text():             # the selection did not close it
            self.raw_step(13)

    def bag_put_in(self, bag):
        g0 = int(self.bl(nh.NLE_BL_GOLD))
        if not self.bag_open(bag):
            return True
        self.bag_choose("s")
        if "stash" in self.message().lower():             # "What do you want to stash? [$a-z or ?*]"
            self.raw_step(ord("$"))
        self.settle()
        put = g0 - int(self.bl(nh.NLE_BL_GOLD))
        self.bag_gold += max(0, put)
        self.bag_moved = True
        self.bag_stats["put_in" if put > 0 else "put_in_failed"] += 1
        self.bag_stats["put_in_gold"] += max(0, put)
        return True

    def bag_take_out(self, bag):
        g0 = int(self.bl(nh.NLE_BL_GOLD))
        if not self.bag_open(bag):
            return True
        self.bag_choose("o")
        tty = self.tty_text()
        if "Take out what type" in tty:                   # the class menu: coins ('$'), confirmed
            self.raw_step(ord("$"))
            self.raw_step(13)
            tty = self.tty_text()
        if "Take out what?" in tty:                       # the objects: the gold's line
            for line in self.menu_lines(tty, "Take out what?"):
                m = MENU_ITEM_GOLD_RE.match(line.strip())
                if m and "gold piece" in m.group(2):
                    self.raw_step(ord(m.group(1)))
            self.raw_step(13)
        self.settle()
        got = int(self.bl(nh.NLE_BL_GOLD)) - g0
        self.bag_gold = 0                                 # all of it out (nothing came: none in it, as we know)
        self.bag_moved = True
        self.bag_stats["take_out" if got > 0 else "take_out_failed"] += 1
        self.bag_stats["take_out_gold"] += max(0, got)
        return True
