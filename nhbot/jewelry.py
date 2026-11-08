"""Amulets and rings: wear the useful ones we know by name, identify the unknown ones with a scroll
of identify, buy that scroll in a shop when we have none; identify scrolls and the amulets and rings still to
identify are needed (carry.needed: never sold or dropped).

Wear (the owner's order; an item still unknown is never put on, nor a known-cursed one):
  amulet  life saving > reflection > ESP > versus poison > magical breathing > unchanging
  rings   free action > regeneration > protection > increase damage > increase accuracy > gain strength >
          gain constitution (these five only with a known positive charge) > slow digestion > poison resistance >
          fire resistance > shock resistance > see invisible > warning; the best two, one per hand
  (left out: conflict -- peacefuls and shopkeepers turn on us --, cold resistance and stealth -- a Valkyrie's
  own --, and the rest: useless alone, or harmful)
Identify: a scroll of identify -- by name, or by shop price (20 zm, the only scroll of that price: pricemem) --
is read with nothing threatening us while we carry an unknown amulet or ring (or a ring of a charged type whose
charge we don't know); the menu (invent.c menu_identify: one item, sometimes more) gets those only, amulets
first (the inventory order), the rest is declined with ESC.
Buy: on a shop visit (carry.carry_shop_greeted: also started for this, in a shop that sells scrolls) with no
identify scroll: step on the scrolls for sale to read their tags, pick up an identify
scroll we can pay for, pay.
"""
import re
from collections import Counter

import numpy as np
import nle.nethack as nh

from nhbot.game import MENU_ITEM_RE, PAGE_RE
from nhbot.items import base_name
from nhbot.pricemem import appearance, buy_price

AMULET_ORDER = ("life saving", "reflection", "ESP", "versus poison", "magical breathing", "unchanging")
RING_ORDER = ("free action", "regeneration", "protection", "increase damage", "increase accuracy", "gain strength",
              "gain constitution", "slow digestion", "poison resistance", "fire resistance", "shock resistance",
              "see invisible", "warning")
CHARGED = {"protection", "increase damage", "increase accuracy", "gain strength", "gain constitution"}
AMULET_RE = re.compile(r"\bamulets? (?:of |called )?(%s)\b" % "|".join(AMULET_ORDER))   # called: a type we named
                                                                                            # by what it is
RING_RE = re.compile(r"\brings? of (%s)\b" % "|".join(sorted(RING_ORDER, key=len, reverse=True)))
IDENTIFY_RE = re.compile(r"\bscrolls? of identify\b")
ID_MENU = "What would you like to identify"         # invent.c menu_identify ("first" / "next")
SCROLL_SHOPS = ("general store", "second-hand bookstore", "rare books")
PRICE_RE = re.compile(r"for sale, (\d+) zorkmids?")
MIN_PRICE = 20                   # the base price: no identify scroll costs less (shop_facts: identify_min_price)
IDENTIFY_COST = 20               # objects.c SCROLL("identify", ..., 20)

SCROLL_GLYPH = np.zeros(nh.MAX_GLYPH, dtype=bool)
for _g in range(nh.MAX_GLYPH):
    if nh.glyph_is_object(_g) and ord(nh.objclass(nh.glyph_to_obj(_g)).oc_class) == nh.SCROLL_CLASS:
        SCROLL_GLYPH[_g] = True


def wear_rank(it):
    """Rank among what we wear in its slot (0 best), None for jewelry we don't wear."""
    if it.ocls == nh.AMULET_CLASS:
        m = AMULET_RE.search(it.text)
        return AMULET_ORDER.index(m.group(1)) if m else None
    if it.ocls == nh.RING_CLASS:
        m = RING_RE.search(it.text)
        if not m:
            return None
        ench = base_name(it.text)[1]
        if m.group(1) in CHARGED and (ench is None or ench <= 0):
            return None
        return RING_ORDER.index(m.group(1))
    return None


def is_regen(it):
    return it.ocls == nh.RING_CLASS and bool(re.search(r"\brings? of regeneration\b", it.text))


def to_identify(ocls, text):
    """An amulet or ring worth a scroll of identify: an unknown look, or a ring of a charged type we would wear
    whose charge we don't know."""
    if ocls not in (nh.AMULET_CLASS, nh.RING_CLASS):
        return False
    if appearance(text) is not None:
        return True
    m = RING_RE.search(text) if ocls == nh.RING_CLASS else None
    return m is not None and m.group(1) in CHARGED and base_name(text)[1] is None


def wear_name(it):
    m = (AMULET_RE if it.ocls == nh.AMULET_CLASS else RING_RE).search(it.text)
    return m.group(1).replace(" ", "_") if m else "unidentified"


class JewelryMixin:
    def jewelry_init(self):
        self.jewelry_stats = Counter()
        self.pay_fails = 0
        self.jewelry_refused = set()     # letters the game would not put on / take off
        self.id_menu_open, self.id_picked = False, 0     # answer_identify_menu: pages of one menu

    # ------------------------------------------------------------ what we have
    def unknown_jewelry(self):
        """Amulets and rings worth a scroll of identify: an unknown look, or a ring of a charged type we would
        wear whose charge we don't know."""
        return [it for it in self.items() if "unpaid" not in it.text and to_identify(it.ocls, it.text)]

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
        """No scroll of identify on us: buying one is worth it."""
        return not self.identify_scrolls()

    def jewelry_needed(self, it):
        """carry.needed (never sold or dropped): identify scrolls, and the amulets and rings still to identify."""
        if it.ocls == nh.SCROLL_CLASS:
            return self.is_identify(it.text)
        if is_regen(it):
            return True                                 # off at full HP (regen_step), still ours
        return to_identify(it.ocls, it.text)            # in the inventory or on the floor (worth_taking)

    def buy_wanted(self, stype):
        return self.identify_wanted() and stype in SCROLL_SHOPS and self.bl(nh.NLE_BL_GOLD) >= self.identify_min_price()

    def identify_min_price(self):
        """The least an identify scroll can cost us. MIN_PRICE; shop_facts: shk.c get_cost of its base cost by our
        Charisma (16+: 15, 18: 13, 19+: 10 -- below 20) and a dunce cap / visible shirt (pricemem.buy_price)."""
        if not self.opts.shop_facts:
            return MIN_PRICE
        return buy_price(IDENTIFY_COST, self.bl(nh.NLE_BL_CHA), self.sucker())

    # ------------------------------------------------------------ wear
    def jewelry_wear_step(self, lv):
        """No threat in view: put on the best amulet / rings we know (taking off a worse one). True if it acted."""
        if self.polyd or self.handless():
            return False
        items = self.items()
        for ocls, slots in ((nh.AMULET_CLASS, 1), (nh.RING_CLASS, 2)):
            on = [it for it in items if it.ocls == ocls and (it.worn or it.ring_on)]
            cands = [(wear_rank(it), it) for it in items
                     if it.ocls == ocls and not it.on_body and not it.cursed and "unpaid" not in it.text
                     and wear_rank(it) is not None and it.letter not in self.jewelry_refused
                     and not is_regen(it)]                                  # regen_step's ring
            if not cands:
                continue
            rank, best = min(cands, key=lambda c: c[0])
            if len(on) >= slots:
                free = [it for it in on if not it.cursed and it.letter not in self.jewelry_refused
                        and not is_regen(it)]
                if not free:
                    continue
                worst = max(free, key=lambda it: 99 if wear_rank(it) is None else wear_rank(it))
                wr = wear_rank(worst)
                if wr is not None and wr <= rank:
                    continue
                return self.jewelry_remove(worst)
            return self.jewelry_put_on(best)
        return False

    def regen_step(self):
        """Nothing next to us (the caller checks): a ring of regeneration is on only while HP is below
        the maximum -- it costs a nutrition point every other turn (eat.c gethungry) and does nothing at full HP.
        Put on into a free ring finger, taken off at full HP. True if it acted."""
        if self.polyd or self.handless():
            return False
        rings = [it for it in self.items() if it.ocls == nh.RING_CLASS]
        regen = [it for it in rings if is_regen(it) and it.letter not in self.jewelry_refused]
        if not regen:
            return False
        full = self.bl(nh.NLE_BL_HP) >= self.bl(nh.NLE_BL_HPMAX)
        on = [it for it in regen if it.ring_on]
        if full and on:
            self.jewelry_stats["regen_off"] += 1
            return self.jewelry_remove(on[0])
        if not full and not on and sum(it.ring_on for it in rings) < 2:
            off = [it for it in regen if not it.cursed and "unpaid" not in it.text]
            if off:
                self.jewelry_stats["regen_on"] += 1
                return self.jewelry_put_on(off[0])
        return False

    def jewelry_remove(self, it):
        self.cur_act = "jewelry"
        self.press("R", expect_prompt=True)
        if self.obs["misc"][0] and "remove" in self.message().lower():
            self.press(it.letter)
        else:
            self.settle()
        if any(i.letter == it.letter and i.on_body for i in self.items()):
            self.jewelry_refused.add(it.letter)        # cursed: stays on ("You remove an uncursed ring" said cursed)
        self.jewelry_stats["removed"] += 1
        return True

    def jewelry_put_on(self, it):
        self.cur_act = "jewelry"
        if not self.ask("P", "put on"):
            self.jewelry_refused.add(it.letter)
            return True
        self.press(it.letter, expect_prompt=True)
        if self.obs["misc"][0] and "ring-finger" in self.message():
            self.press("l")                            # "Which ring-finger, Right or Left?"
        else:
            self.settle()
        if not any(i.letter == it.letter and i.on_body for i in self.items()):
            self.jewelry_refused.add(it.letter)        # cursed gloves, a form without hands, ...
            self.jewelry_stats["wear_failed"] += 1
        else:
            self.jewelry_stats["worn_" + wear_name(it)] += 1
        return True

    # ------------------------------------------------------------ identify
    def jewelry_id_step(self, lv):
        """No threat in view: read an identify scroll on unknown jewelry. True if it used the turn."""
        if not self.unknown_jewelry() or self.soko_stealth(lv):
            return False
        cond = int(self.last_bl[nh.NLE_BL_CONDITION])
        if cond & (nh.BL_MASK_BLIND | nh.BL_MASK_CONF | nh.BL_MASK_STUN | nh.BL_MASK_HALLU):
            return False                       # confused: identifies only the scroll itself
        scrolls = self.identify_scrolls()
        if not scrolls:
            return False
        self.cur_act = "identify"
        if not self.read_scroll(lv, scrolls[0].letter):        # the menu: answer_identify_menu
            return False
        self.jewelry_stats["read"] += 1
        return True

    def identify_choice(self):
        """Letters to pick in the identify menu: the first non-empty group of unknown jewelry, unknown scrolls
        that are not identify or good by price, unknown potions, unknown wands. One group only: the game
        identifies the picks in inventory order up to its limit, so a lower group picked too could take the
        place of a higher one."""
        mine = [it for it in self.items() if "unpaid" not in it.text and appearance(it.text) is not None]
        groups = [self.unknown_jewelry(),
                  [it for it in mine if it.ocls == nh.SCROLL_CLASS and not self.scroll_is_good(it.text)
                   and not self.is_identify(it.text)],
                  [it for it in mine if it.ocls == nh.POTION_CLASS],
                  [it for it in mine if it.ocls == nh.WAND_CLASS]]
        return {it.letter for it in next((g for g in groups if g), [])}

    def identify_menu_shown(self, tty, menu):
        """settle: is a page of an identify menu on screen (its header, or a later page of the one we answer)? An
        identify menu closed some other way is forgotten."""
        if not menu and ID_MENU not in tty:
            self.id_menu_open = False
        return ID_MENU in tty or bool(menu and self.id_menu_open)

    def answer_identify_menu(self, tty):
        """settle: an identify menu page is on screen (page 2 on has no header: every "x - ..." line is an
        entry). Pick identify_choice on this page, next page, and at the end confirm -- or ESC with nothing
        picked (the menu would come back)."""
        if not self.id_menu_open:
            self.id_menu_open, self.id_picked = True, 0
        want = self.identify_choice()
        items = self.menu_items(tty, ID_MENU) if ID_MENU in tty else \
            [(m.group(1), m.group(2)) for l in tty.split("\n") for m in [MENU_ITEM_RE.match(l.strip())] if m]
        for l in [l for l, _ in items if l in want]:
            self.raw_step(ord(l))
            self.id_picked += 1
        page = PAGE_RE.search(tty)
        if page and int(page.group(1)) < int(page.group(2)):
            self.raw_step(ord(">"))
            return
        self.jewelry_stats["picked"] += self.id_picked
        self.raw_step(13 if self.id_picked else 27)
        self.id_menu_open = False              # a blessed scroll may ask for the next ones: a new menu

    # ------------------------------------------------------------ buy
    def shop_buy_step(self, lv):
        """On a shop visit (shop.shop_step, after selling): pay for what we picked up, else go for an identify
        scroll for sale, else read the tags of the scrolls not looked at yet. True if it acted."""
        unpaid = [it for it in self.items() if "unpaid" in it.text]
        if unpaid:
            self.cur_act = "buy"
            if self.pay_fails >= 3:                # can't pay: put it back
                self.drop_units(unpaid[0].letter)
                self.jewelry_stats["put_back"] += 1
                return True
            gold0 = self.bl(nh.NLE_BL_GOLD)
            self.pay()
            if self.bl(nh.NLE_BL_GOLD) < gold0:
                self.jewelry_stats["bought"] += 1
                self.pay_fails = 0
            else:
                self.pay_fails += 1
            return True
        gold = self.bl(nh.NLE_BL_GOLD)
        if not self.identify_wanted() or not lv.shop.any() or gold < self.identify_min_price():
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
            self.jewelry_stats["picked_up"] += 1
            return True
        if goals.any() and self.walk_to(lv, goals, act="buy")[0] == "moved":
            return True
        return self.browse_step(lv, SCROLL_GLYPH, "buy_browse")
