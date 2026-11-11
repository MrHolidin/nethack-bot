"""bag_store (A/B, off by default): the potions and scrolls no step is about to use kept in our bag -- fire and cold
destroy only what is in the inventory (zap.c destroy_item walks invent; a container's contents are safe) -- and taken
out when a use comes up: in a shop (sold, priced), on an altar with one of them untested (altar_step; they draw
us to an altar as the inventory's do: altar_mask), Burdened (carry may drop
them), or one in the bag that a step would now want (carry.needed, an untested scroll still to read).
The bag: one known to be a container -- a sack / oilskin sack by name, a bag of holding, or a "bag" bag_test opened and
named BAG_OK_NAME (all four bags look "bag"; a bag of tricks applied makes a monster: apply.c bagotricks); not known
cursed -- a cursed bag of holding loses what is in it (pickup.c boh_loss), but bags are never made cursed (mkobj.c
mksobj: no blessorcurse for them), only cursed later (a spell's rndcurse). The bag holding our
things stays the one used and is never dropped or sold (carry.needed: store_holds).
bag_test: an unknown "bag" of ours told apart at once -- dropped on plain floor, #looted there (a bag of tricks only
bites, d10, and becomes known: lock.c doloot; a container opens, and what lies in it that the floor rules want is
taken out, as from a box), picked back up and, a container, named."""

from collections import Counter

import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.altar import BUC_RE, buc_key
from nhbot.consts import ALTAR_GLYPH
from nhbot.items import Item
from nhbot.scrolls import TESTING_ENDS

STORE_CLASSES = (nh.POTION_CLASS, nh.SCROLL_CLASS)
STORE_MENU = ("Potions", "Scrolls")              # their lines in a container's "what type of objects?" menu
BAG_OK_NAME = "ok"                               # bag_test: the name given to a "bag" that opened (#name, one object)
BAG_TEST_HP = 15                                 # bag_test: only above this HP (a bag of tricks bites for d10)
HANDS_RETRY = 500                                # turns before a bag is tried again after "You have no free hand"
UNLOAD_HOLD = 100                                # turns nothing goes in after store_unload emptied the bag


class BagStoreState:
    """State of the potions and scrolls kept in the bag (BagStoreMixin)."""
    def __init__(self):
        self.held = []                # (class, text) of what we put in and did not take out (texts as when put in)
        self.bag_letter = None        # the letter of the bag they are in (while held)
        self.test = None              # bag_test: (level key, square, phase "dropped" / "looted", it opened)
        self.hands_busy = -HANDS_RETRY  # the turn a bag would not open for want of a free hand
        self.unloaded = -UNLOAD_HOLD    # the turn store_unload emptied the bag
        self.stats = Counter()


class BagStoreMixin:
    def bagstore_init(self):
        self.bstore = BagStoreState()

    def bagstore_summary(self):
        """Game summary entries."""
        return {"bag_store": dict(self.bstore.stats, held=len(self.bstore.held))}

    @staticmethod
    def is_bag(it):
        return it.ocls == nh.TOOL_CLASS and ("bag" in it.text or "sack" in it.text) and "tricks" not in it.text

    def known_container(self, it):
        """A bag of ours known to be a container we may keep things in (see the module notes)."""
        if not self.is_bag(it) or it.cursed or it.unpaid:
            return False
        return "sack" in it.text or "holding" in it.text or f"named {BAG_OK_NAME}" in it.text

    def store_bag(self):
        """The bag our things go in: the one holding them already, else the best known container (a bag of holding
        first: it weighs less full). None: no such bag."""
        if self.bstore.held:
            return next((it for it in self.items() if it.letter == self.bstore.bag_letter and self.is_bag(it)), None)
        bags = [it for it in self.items() if self.known_container(it)]
        rank = lambda it: (0 if "holding" in it.text else 1 if "oilskin" in it.text else 2)  # noqa: E731
        return min(bags, key=rank) if bags else None

    def store_unload(self, it):
        """carry_drop_step is about to drop it (Burdened, a squeeze refused for our weight, a smaller form): if it is
        the bag our things are in, they come out first and are weighed one by one (the bag went with all of them --
        80080, 80144, 80341, 80461, 80644, 80880 dropped it at a squeeze). True if it used the turn."""
        if not self.store_holds(it) or self.hands_busy():
            return False                          # can't open it now: it goes as it is
        bag = self.store_bag()
        if bag is None:
            return False
        self.bstore.stats["unload_before_drop"] += 1
        self.bstore.unloaded = self.turn()
        return self.store_take_out(bag)

    def store_holds(self, it):
        """carry.needed: the bag our things are in (never dropped, never sold)."""
        return bool(self.bstore.held) and it.letter == self.bstore.bag_letter

    def storable(self, it):
        """A potion / scroll of ours no step is about to use: not unpaid, not carry.needed (healing, the good scrolls,
        the 100 zm potions for quaff_test, identify, the vault-finding ones), not an untested scroll that may still
        be read (scrolls.read_scroll_step: testing goes on while enchant armor and identify are unknown)."""
        if it.ocls not in STORE_CLASSES or it.unpaid or self.needed(it):
            return False
        return not (it.ocls == nh.SCROLL_CLASS and self.unknown_readable(it.text)
                    and not self.known_scroll_types() & TESTING_ENDS)

    def store_out_reason(self, lv):
        """Why what is in the bag should come out now, or None."""
        if not self.bstore.held:
            return None
        here = self.pos()
        if lv.shop[here]:
            return "shop"
        if self.terrain_glyphs(lv)[here] == ALTAR_GLYPH and self.store_untested():
            return "altar"
        if self.bl(nh.NLE_BL_CAP) >= 1:
            return "burdened"
        if any(not self.storable(Item(letter="?", ocls=c, text=t)) for c, t in self.bstore.held):
            return "wanted"
        return None

    def store_untested(self):
        """Something in the bag of a BUC not known (altar.altar_untested's test on our texts)."""
        return any(not BUC_RE.search(t) and buc_key(t) not in self.altar.known for _, t in self.bstore.held)

    def hands_busy(self):
        return self.turn() - self.bstore.hands_busy < HANDS_RETRY

    def store_open(self, bag):
        """bag_open; one that fails leaves our bag alone HANDS_RETRY turns -- "You have no free hand" (a welded
        two-hander, or a welded weapon and a cursed shield: apply.c use_container, freehand -- 80648 tried 79046
        times), a form that can't apply (80657, a wererat: 66521 tries) -- and "no free hand" says nothing of the
        bag itself."""
        seq0 = self.msg_seq
        if self.bag_open(bag):
            return True
        self.bstore.hands_busy = self.turn()
        self.bstore.stats["open_failed"] += 1
        if "no free hand" in self.text_since(seq0):
            self.bag.bad.discard(bag.key)
            self.bstore.stats["no_free_hand"] += 1
        return False

    def bag_out_step(self, lv):
        """Housekeeping, before the shop and altar jobs: what is in the bag taken out when a use comes up. True if
        it used the turn."""
        if not self.opts.bag_store or not self.bstore.held or self.hands_busy():
            return False
        bag = self.store_bag()
        if bag is None:
            self.bstore.held = []                 # the bag is gone (stolen, cursed found): nothing left to take out
            self.bstore.stats["bag_lost"] += 1
            return False
        why = self.store_out_reason(lv)
        if why is None:
            return False
        self.bstore.stats["out_" + why] += 1
        return self.store_take_out(bag)

    def bag_in_step(self, lv):
        """Housekeeping, late: the storable potions and scrolls put in the bag -- not where they'd come out at once.
        True if it used the turn."""
        if not self.opts.bag_store or self.hands_busy() or self.turn() - self.bstore.unloaded < UNLOAD_HOLD:
            return False
        bag = self.store_bag()
        if bag is None:
            return False
        here = self.pos()
        if lv.shop[here] or self.terrain_glyphs(lv)[here] == ALTAR_GLYPH or self.bl(nh.NLE_BL_CAP) >= 1:
            return False
        put = [it for it in self.items() if self.storable(it)]
        if not put:
            return False
        return self.store_put_in(bag, put)

    def store_put_in(self, bag, put):
        texts = {it.text: it.ocls for it in put}
        if not self.store_open(bag):
            return True
        self.cur_act = "bag_store"
        self.bag_choose("i")
        if "Put in what type" in self.tty_text():
            self.menu_pick("Put in what type", lambda t: t in STORE_MENU)
        if "Put in what?" in self.tty_text():
            self.menu_pick("Put in what?", lambda t: t in texts)
        self.settle()
        left = {it.text for it in self.items()}
        moved = [(c, t) for t, c in texts.items() if t not in left]
        if moved and not self.bstore.held:
            self.bstore.bag_letter = bag.letter
        self.bstore.held += moved
        self.bstore.stats["put_in" if moved else "put_in_failed"] += 1
        self.bstore.stats["put_in_items"] += len(moved)
        return True

    def store_take_out(self, bag):
        n0 = len(self.items())
        if not self.store_open(bag):
            return True
        self.cur_act = "bag_store"
        self.bag_choose("o")
        if "Take out what type" in self.tty_text():
            self.menu_pick("Take out what type", lambda t: t in STORE_MENU)
        if "Take out what?" in self.tty_text():
            self.menu_pick("Take out what?", lambda t: "gold piece" not in t)
        self.settle()
        got = len(self.items()) - n0
        self.bstore.held = []                     # all of them out (what did not come is not there, as we know)
        self.bstore.stats["take_out" if got > 0 else "take_out_failed"] += 1
        return True

    # ------------------------------------------------------------ bag_test
    def bag_unknown(self, it):
        """A "bag" of ours that may be a bag of tricks: not known by name, not named by us."""
        return self.is_bag(it) and not it.unpaid and "sack" not in it.text and "holding" not in it.text \
            and "named" not in it.text and it.key not in self.bag.bad

    def bag_test_step(self, lv):
        """Housekeeping: tell an unknown bag of ours apart (module notes), one phase a tick -- drop, #loot, pick up
        and name. A bag that holds our gold opened already: named at once. True if it used the turn."""
        if not self.opts.bag_store or self.hands_busy() and self.bstore.test is None:
            return False
        here = (lv.key, self.pos())
        t = self.bstore.test
        if t is not None:
            if t[:2] != here:
                self.bstore.test = None           # moved off: the bag stays there (the pile rules may take it again)
                self.bstore.stats["test_left"] += 1
                return False
            if t[2] == "dropped":
                opened = self.bag_loot_test()
                self.bstore.test = here + ("looted", opened)
                return True
            return self.bag_test_pickup(t[3])
        unknown = [it for it in self.items() if self.bag_unknown(it)]
        if not unknown:
            return False
        gb = self.gold_bag()
        for it in unknown:
            if self.bag.gold > 0 and gb is not None and gb.letter == it.letter:
                self.cur_act = "bag_test"
                self.name_item(it.letter, BAG_OK_NAME)
                self.bstore.stats["test_gold_named"] += 1
                return False                      # naming costs no game time
        cond = int(self.last_bl[nh.NLE_BL_CONDITION])
        if lv.shop[self.pos()] or self.bl(nh.NLE_BL_HP) <= BAG_TEST_HP or self.poly_form() is not None \
                or cond & (nh.BL_MASK_LEV | nh.BL_MASK_BLIND | nh.BL_MASK_HALLU) \
                or G.KIND[int(self.terrain_glyphs(lv)[self.pos()])] != G.FLOOR:
            return False
        self.cur_act = "bag_test"
        self.drop_units(unknown[0].letter)
        self.bstore.test = here + ("dropped", None)
        self.bstore.stats["test_dropped"] += 1
        return True

    def bag_loot_test(self):
        """#loot the bag under us: True if it opened (a container: what the floor rules want taken out of it),
        False if it bit (a bag of tricks, now known), None if neither."""
        seq0 = self.msg_seq
        self.cur_act = "bag_test"
        self.press("#", expect_prompt=True)
        for c in "loot":
            self.raw_step(ord(c))
        self.press(13, expect_prompt=True)
        opened = took = False
        for _ in range(12):
            tty, msg = self.tty_text(), self.message()
            if self.obs["misc"][0] and "loot it?" in msg:
                self.press("y" if "bag" in msg else "n", expect_prompt=True)
                continue
            if "Do what with" in tty:
                opened = True
                if took:
                    self.raw_step(27)
                    break
                took = True
                self.raw_step(ord("o"))           # no "take out" line when it is empty: pressed again, closed
                continue
            if "Take out what type" in tty:
                self.raw_step(ord("a"))
                self.raw_step(13)
                continue
            if "Take out what?" in tty:
                n = self.menu_pick("Take out what?", lambda x: self.take_reason(x) is not None)
                self.bstore.stats["test_took"] += n
                continue
            break
        self.settle()
        said = self.text_since(seq0)
        if "no free hand" in said:
            self.bstore.hands_busy = self.turn()
            self.bstore.stats["no_free_hand"] += 1
        if "teeth" in said or "bites you" in said:
            self.bstore.stats["test_tricks"] += 1
            return False
        if opened or "open the" in said or "is empty" in said:
            self.bstore.stats["test_container"] += 1
            return True
        self.bstore.stats["test_unclear"] += 1
        return None

    def bag_test_pickup(self, opened):
        """The tested bag picked back up; one that opened named BAG_OK_NAME. True (the turn used)."""
        self.bstore.test = None
        before = {it.letter for it in self.items()}
        self.cur_act = "bag_test"
        self.pickup(lambda x: ("bag" in x or "sack" in x) and "for sale" not in x, "bag_test")
        new = [it for it in self.items() if it.letter not in before and self.is_bag(it) and "named" not in it.text]
        if opened and len(new) == 1:
            self.name_item(new[0].letter, BAG_OK_NAME)
            self.bstore.stats["test_named"] += 1
        return True
