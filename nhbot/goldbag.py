"""gold_bag: our gold kept in a bag while a leprechaun is in view -- a leprechaun steals only the gold we carry
loose (steal.c stealgold: findgold(invent)), not what is in a container -- and taken back out in a shop, where it
pays. One bag that is not a bag of tricks is needed (carry.py: never sold, never dropped)."""

from collections import Counter

import nle.nethack as nh

from nhbot.game import MENU_ITEM_GOLD_RE

BAG_WORDS = ("bag", "sack")
BAG_RANK = ("holding", "oilskin", "sack")      # the bag used: the first of these we carry, else a plain "bag"


class GoldBagState:
    """State of the gold kept in a bag (GoldBagMixin)."""
    def __init__(self):
        self.gold = 0                 # gold we put in the bag and did not take out
        self.bad = set()              # item keys of bags that are not containers (a bag of tricks: no menu)
        self.stats = Counter()
        self.moved = False            # gold moved between us and the bag since the last tick (gold_flow_tick)


class GoldBagMixin:
    def goldbag_init(self):
        self.bag = GoldBagState()

    def goldbag_summary(self):
        """Game summary entries."""
        return {"gold_bag": dict(self.bag.stats, in_bag=self.bag.gold)}

    def gold_bag(self):
        """The bag our gold goes in: carried, not a bag of tricks, not known cursed (a cursed bag of holding
        loses what is in it, pickup.c boh_loss) -- a bag of holding first. None: no such bag. (A/B goldbag_v1
        +1076.)"""
        bags = [it for it in self.items() if it.ocls == nh.TOOL_CLASS and any(w in it.text for w in BAG_WORDS)
                and "tricks" not in it.text and not it.cursed and it.key not in self.bag.bad]
        rank = lambda it: next((i for i, w in enumerate(BAG_RANK) if w in it.text), len(BAG_RANK))
        return min(bags, key=rank) if bags else None

    def gold_bag_step(self, lv, hostiles):
        """gold_bag: in a shop, the gold in the bag taken out; elsewhere, a leprechaun in view, no other hostile
        next to us and gold on us -- put in the bag. True if it used the turn."""
        bag = self.gold_bag()
        if bag is None:
            return False
        in_shop = bool(lv.shop[self.pos()])
        if in_shop and self.bag.gold > 0:
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
        if bag is None or bag.letter != it.letter or self.bag.gold <= 0:
            return False
        self.bag.stats["unload_before_drop"] += 1
        return self.bag_take_out(bag)

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
        self.bag.bad.add(bag.key)
        self.bag.stats["not_a_container"] += 1
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
        self.bag.gold += max(0, put)
        self.bag.moved = True
        self.bag.stats["put_in" if put > 0 else "put_in_failed"] += 1
        self.bag.stats["put_in_gold"] += max(0, put)
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
        self.bag.gold = 0                                 # all of it out (nothing came: none in it, as we know)
        self.bag.moved = True
        self.bag.stats["take_out" if got > 0 else "take_out_failed"] += 1
        self.bag.stats["take_out_gold"] += max(0, got)
        return True
