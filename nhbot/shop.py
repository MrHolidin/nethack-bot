"""Shop visits: the shared state for a visit, selling, paying, and the digger a shopkeeper wants left outside.

Sell: in a shop that buys the class (general store: everything), drop each item we have no use for deep
inside the shop and accept the offer; take back what the shopkeeper won't buy (what we keep: value.keep_reason).
"""
import re

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.carry import DIGGER_WORDS, FIXED_LOOK, describe, is_clear_potion

ALL = None

# what each shop buys -- shknam.c:205-343 shtypes item lists, as shknam.c:782 saleable reads them: a
# class, a (class, type) for an entry of one object type, VEGGY for health food's vegetarian class (shknam.c:373
# veggy_item: food of VEGGY material, eggs). (A/B shop_buys_facts -- by class before (armor to quality apparel, every
# tool to a lighting store, nothing to health food): +473 [-559, +1541], median 8484 -> 8197, 304 of 1000 changed;
# an item of unknown type is offered when any type it may be is bought -- unidentified potions to a delicatessen /
# health food / lighting store are mostly refused.)
VEGGY = "veggy"
VEGGY_FOOD = {"kelp frond", "eucalyptus leaf", "apple", "orange", "pear", "melon", "banana", "carrot",
              "sprig of wolfsbane", "clove of garlic", "slime mold", "lump of royal jelly", "cream pie", "candy bar",
              "fortune cookie", "pancake", "lembas wafer", "cram ration", "food ration", "K-ration", "C-ration", "egg"}
SHOP_SELLS = {
    "general store": ALL,
    "used armor dealership": (nh.ARMOR_CLASS, nh.WEAPON_CLASS),
    "second-hand bookstore": (nh.SCROLL_CLASS, nh.SPBOOK_CLASS),
    "liquor emporium": (nh.POTION_CLASS,),
    "antique weapons outlet": (nh.WEAPON_CLASS, nh.ARMOR_CLASS),
    "delicatessen": (nh.FOOD_CLASS, (nh.POTION_CLASS, "fruit juice"), (nh.POTION_CLASS, "booze"),
                     (nh.POTION_CLASS, "water"), (nh.TOOL_CLASS, "ice box")),
    "jewelers": (nh.RING_CLASS, nh.GEM_CLASS, nh.AMULET_CLASS),
    "quality apparel and accessories": (nh.WAND_CLASS, (nh.ARMOR_CLASS, "leather gloves"),
                                        (nh.ARMOR_CLASS, "elven cloak")),
    "hardware store": (nh.TOOL_CLASS,),
    "rare books": (nh.SPBOOK_CLASS, nh.SCROLL_CLASS),
    "health food store": (VEGGY, (nh.POTION_CLASS, "fruit juice"), (nh.POTION_CLASS, "healing"),
                          (nh.POTION_CLASS, "full healing"), (nh.SCROLL_CLASS, "food detection"),
                          (nh.FOOD_CLASS, "lump of royal jelly")),
    "lighting store": ((nh.TOOL_CLASS, "wax candle"), (nh.TOOL_CLASS, "tallow candle"), (nh.TOOL_CLASS, "brass lantern"),
                       (nh.TOOL_CLASS, "oil lamp"), (nh.TOOL_CLASS, "magic lamp"), (nh.POTION_CLASS, "oil")),
}

LEAVE_RE = re.compile(r"[Ll]eave (?:your|the) .*outside")


# shk.c: "Welcome to Asidonhopo's general store!" -- a name ending in s takes only the apostrophe
# ("Kinojevis' general store"); those shops used to go unmarked (nothing sold there)
# a later visit says "Welcome again to ..." (shk.c u_entered_shop); every greeting marks the shop again -- the
# first one often comes while we stand in the door seeing nothing inside yet (a keeper blocking for a pick-axe,
# a wall just repaired), which marked nothing
SHOP_WELCOME_RE = re.compile(r"Welcome(?: again)? to [A-Z][\w' -]*?(?:'s|s') ([^!]+)!")
# hack.c check_special_room: entering a zoo says "Welcome to David's treasure zoo!" -- the same shape as a shop
# greeting, but no shop (zoo_not_shop)
ZOO_WELCOME = "Welcome to David's treasure zoo!"
ARRIVED_RE = re.compile(r"trap door|fall through|\bhole\b|teleport|wrenching|You materialize")   # this tick


class ShopState:
    """State of shop visits: browsing, paying, selling, the digger stash (ShopMixin)."""
    def __init__(self):
        self.shopping = None
        self.browsed = set()             # (level key, square) of shop squares we stood on to read the tags
        self.browse_stats = {"steps": 0, "looks": 0}
        self.seen = 0                    # shop entrances we were welcomed at (summary 'shops')
        self.done = set()                # level keys whose shop visit is over
        self.need_pay = False            # a shopkeeper asked us to pay (step_housekeeping: pay_step)
        self.selling = False
        self.sell_tried = set()          # (shop level key, item text) the shopkeeper would not take
        self.selling_item = (None, "")   # (class, text) of the item on offer
        self.stash_pending = None        # (level key, door) -- a shopkeeper asked us to leave the digger outside
        self.dig_stash = None            # dict(key, pos, turn): where we left it
        self.stash_stats = {"asked": 0, "stashed": 0, "retrieved": 0, "lost": 0}


class ShopMixin:
    def shop_init(self):
        self.shop = ShopState()

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
        if self.shop.shopping is None:
            self.sell_greeted(lv, stype)

    def shop_active(self, lv):
        s = self.shop.shopping
        return s is not None and s["key"] == lv.key and self.turn() < s["until"]

    def pay_step(self):
        """The shopkeeper wants paying (need_pay, msg_shop): pay. True if it acted."""
        if not self.shop.need_pay:
            return False
        self.shop.need_pay = False
        self.pay()
        return True

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
        if self.shop.shopping is None:
            return False
        if not self.shop_active(lv):
            self.shop.done.add(self.shop.shopping["key"])
            self.shop.shopping = None
            return False
        if self.sell_step(lv):
            return True
        if self.shop.shopping is not None and self.shop_buy_step(lv):
            return True
        if self.shop.shopping is not None:
            self.shop.done.add(self.shop.shopping["key"])
            self.shop.shopping = None
        return False

    def browse_step(self, lv, glyph_mask, act):
        """In a shop: walk onto the shop squares showing an item of glyph_mask whose tag we have not read
        ('You see here ... (for sale, N zorkmids)' when we step there, ':' on a pile). True if it acted."""
        here = self.pos()
        todo = lv.shop & glyph_mask[lv.under]
        for k, p in self.shop.browsed | set(self.prices.for_sale):
            if k == lv.key:
                todo[p] = False
        if todo[here]:
            self.shop.browsed.add((lv.key, here))
            self.look_here()                       # a pile: the tags show in the 'Things that are here' window
            self.shop.browse_stats["looks"] += 1
            return True
        if todo.any() and self.walk_to(lv, todo, act=act)[0] == "moved":
            self.shop.browse_stats["steps"] += 1
            return True
        return False

    def msg_shop(self, m, lv):
        """Price tags, entering a shop, the digger request, the bill."""
        if "for sale" in m:
            self.price_note_text(m)
        # the square under us is often not in our map memory yet, so 'on the door' can't be checked;
        # instead: we are inside only if we just fell / were teleported onto this level
        if lv and self.shop_welcome(m) and not ARRIVED_RE.search(self.text_since(self.pol.tick_seq)):
            # shop entrance: mark the shop from the door -- after falling in through a trap door we are
            # inside, and marking from there walls us in
            self.mark_shop(lv, self.pos())
            self.shop.seen += 1
            self.shop_greeted(lv, m)
        if LEAVE_RE.search(m):
            self.stash_request()
        if "Please pay before leaving" in m or "you owe" in m.lower() and "zorkmid" in m:
            self.shop.need_pay = True

    # ------------------------------------------------------------ selling
    def sellables(self, lv, stype):
        return [(it.letter, it.ocls, it.text) for it in self.items()
                if it.ocls in self.carry_classes()
                and self.shop_buys(stype, it) and not self.offer_zero(it)
                and (self.keep_reason(it) is None or self.luck_price_check(it))
                and (lv.key, it.text) not in self.shop.sell_tried
                and not it.on_body and not it.alternate and not it.quivered and not it.unpaid]

    def item_types(self, it):
        """The object types Item it may be -- one when identified (or a look fixed to one type), else
        what value.type_posterior still allows for its look."""
        if is_clear_potion(it.ocls, it.text):
            return {"water"}
        post = self.type_posterior(it.text)
        if post is not None:
            return set(post)
        name = describe(it.ocls, it.text)["key"][1]
        return {FIXED_LOOK.get((it.ocls, name), name)}

    def shop_buys(self, stype, it):
        """May a shop of this type buy Item it (shknam.c:782 saleable, SHOP_SELLS)? An item whose type
        we don't know: if any type it may be is bought (the shopkeeper's refusal then goes to sell_tried)."""
        wants = SHOP_SELLS.get(stype, ())
        if wants is ALL:
            return True
        types = None
        for w in wants:
            if w == VEGGY:
                ok = it.ocls == nh.FOOD_CLASS and describe(it.ocls, it.text)["key"][1] in VEGGY_FOOD
            elif isinstance(w, tuple):
                if it.ocls != w[0]:
                    continue
                types = self.item_types(it) if types is None else types
                ok = w[1] in types
            else:
                ok = it.ocls == w
            if ok:
                return True
        return False

    @staticmethod
    def offer_zero(it):
        """An item a shopkeeper offers nothing for, so won't buy (shk.c:3398-3412 getprice: uncursed
        water -- a clear potion not known blessed / cursed --, a cancelled wand, partly eaten food)."""
        if is_clear_potion(it.ocls, it.text):
            return not re.search(r"\b(?:blessed|cursed)\b", it.text) or "uncursed" in it.text
        if it.ocls == nh.WAND_CLASS and re.search(r"\(\d+:-1\)", it.text):
            return True
        return it.ocls == nh.FOOD_CLASS and "partly eaten" in it.text

    def keep_after_offer(self, msg):
        """read_good: the offer just recorded may show the scroll we are selling is a good one: keep it;
        keep_100: likewise a potion of the 100 group; luckstone.py: the offer (msg) shows a gray stone of ours is
        the luckstone (luck_offer_keep)."""
        c, s = self.shop.selling_item
        if self.luck_offer_keep(c, s, msg):
            return True
        if c == nh.SCROLL_CLASS and self.scroll_is_good(s):
            self.scroll_stat("kept_good")
            return True                    # the offer just showed it is enchant armor/weapon or remove curse
        if c == nh.POTION_CLASS and self.potion_100(s):
            self.carry_stat("kept_100")
            return True                    # the offer just showed it is of the 100 group
        return False

    def sell_greeted(self, lv, stype):
        if lv.key in self.shop.done or not (self.sellables(lv, stype) or self.buy_wanted(stype)):
            return
        self.shop.shopping = {"key": lv.key, "until": self.turn() + 150, "kind": "sell", "stype": stype}

    def sell_step(self, lv):
        stype = self.shop.shopping.get("stype")
        items = self.sellables(lv, stype)
        if not items:
            return False                             # shop_step: buying, or the end of the visit
        y, x = self.pos()
        k = self.kinds(lv)
        door = np.isin(k, [G.DOOR_OPEN, G.DOOR_CLOSED, G.DOORWAY])
        near = door.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                near |= np.roll(np.roll(door, dy, 0), dx, 1)
        if lv.shop[y, x] and not near[y, x]:
            l, c, s = items[0]
            gold0 = self.bl(nh.NLE_BL_GOLD)
            self.shop.selling_item = (c, s)
            self.shop.selling = True
            self.drop_units(l)
            self.shop.selling = False
            got = self.bl(nh.NLE_BL_GOLD) - gold0
            if got > 0:
                self.carry_stat("sold")
                self.carry_stat("gold", got)
            else:                                    # not bought: it is still ours, take it back
                self.shop.sell_tried.add((lv.key, s))
                self.carry_stat("kept_back")
                self.pickup_matching((re.sub(r"^(a|an|the|\d+)\s+", "", re.sub(r"\s*\(.*?\)", "", s)).strip(),),
                                     own=True)
            return True
        targets = lv.shop & ~near
        targets[y, x] = False
        if not targets.any():
            self.shop.done.add(lv.key)
            self.shop.shopping = None
            return False
        if self.walk_to(lv, targets)[0] == "moved":
            return True
        self.shop.done.add(lv.key)          # can't get further in: the visit is over
        self.shop.shopping = None
        return False

    # ------------------------------------------------------------ the digger left outside
    def digger_letters(self):
        return [it.letter for it in self.items() if any(w in it.text for w in DIGGER_WORDS) and not it.held]

    def stash_request(self):
        """shk.c:626-663 u_entered_shop: 'Will you please leave your pick-axe outside?' -- the keeper blocks the
        way in while one is in the open inventory, a dwarvish mattock too (DIGGER_WORDS): put it down next to the
        door, outside the shop."""
        if self.cur_key is None:
            return
        self.shop.stash_stats["asked"] += 1
        sh = self.shop.shopping                          # the keeper greets and blocks in the same breath
        if sh is None or sh["key"] != self.cur_key:
            self.shop.stash_stats["skipped"] = self.shop.stash_stats.get("skipped", 0) + 1
            return                                   # the greeting found nothing to do in there
        self.shop.stash_pending = (self.cur_key, self.pos())

    def stash_step(self, lv):
        sp = self.shop.stash_pending
        if sp is not None:
            if sp[0] != lv.key or not self.digger_letters():
                self.shop.stash_pending = None
                return False
            door = sp[1]
            k = self.kinds(lv)
            ok = ~lv.shop & ~np.isin(k, [G.DOOR_OPEN, G.DOOR_CLOSED, G.DOORWAY]) & np.isin(k, [G.FLOOR, G.GOLD,
                                                                                            G.OBJECT, G.CORPSE])
            near = np.zeros_like(ok)
            near[max(0, door[0] - 1):door[0] + 2, max(0, door[1] - 1):door[1] + 2] = True
            ok &= near
            here = self.pos()
            if ok[here]:
                self.cur_act = "stash"
                self.drop_units(self.digger_letters()[0])
                if not self.digger_letters():
                    self.shop.stash_stats["stashed"] += 1
                    self.shop.dig_stash = {"key": lv.key, "pos": here, "turn": self.turn()}
                    self.shop.stash_pending = None
                return True
            if self.walk_to(lv, ok, act="stash")[0] == "moved":
                return True
            self.shop.stash_pending = None
            return False
        st = self.shop.dig_stash
        if st is None:
            return False
        if st["key"] != lv.key:
            self.shop.dig_stash = None
            self.shop.stash_stats["lost"] += 1            # left the level without it
            return False
        if self.shop_active(lv) or lv.shop[self.pos()]:
            return False                             # the visit (on since the greeting) is not over
        if self.pos() == st["pos"]:
            self.cur_act = "stash"
            self.pickup_matching(DIGGER_WORDS, own=True)
            self.shop.dig_stash = None
            self.shop.stash_stats["retrieved"] += 1
            return True
        m = np.zeros(lv.under.shape, dtype=bool)
        m[st["pos"]] = True
        if self.walk_to(lv, m)[0] == "moved":
            self.cur_act = "stash"
            return True
        self.shop.dig_stash = None
        self.shop.stash_stats["lost"] += 1
        return False
