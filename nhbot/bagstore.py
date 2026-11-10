"""bag_store (A/B, off by default): the potions and scrolls no step is about to use kept in our bag -- fire and cold
destroy only what is in the inventory (zap.c destroy_item walks invent; a container's contents are safe) -- and taken
out when a use comes up: in a shop (sold, priced), on an altar with one of them untested (altar_step; they draw
us to an altar as the inventory's do: altar_mask), Burdened (carry may drop
them), or one in the bag that a step would now want (carry.needed, an untested scroll still to read). The bag is
gold_bag's (nhbot.goldbag: never sold or dropped); a bag of holding only known not cursed (a cursed one loses what is
in it: pickup.c boh_loss)."""

from collections import Counter

import nle.nethack as nh

from nhbot.altar import BUC_RE, buc_key
from nhbot.consts import ALTAR_GLYPH
from nhbot.items import Item
from nhbot.scrolls import TESTING_ENDS

STORE_CLASSES = (nh.POTION_CLASS, nh.SCROLL_CLASS)
STORE_MENU = ("Potions", "Scrolls")              # their lines in a container's "what type of objects?" menu


class BagStoreState:
    """State of the potions and scrolls kept in the bag (BagStoreMixin)."""
    def __init__(self):
        self.held = []                # (class, text) of what we put in and did not take out (texts as when put in)
        self.stats = Counter()


class BagStoreMixin:
    def bagstore_init(self):
        self.bstore = BagStoreState()

    def bagstore_summary(self):
        """Game summary entries."""
        return {"bag_store": dict(self.bstore.stats, held=len(self.bstore.held))}

    def store_bag(self):
        """gold_bag's bag, a bag of holding only if known uncursed / blessed; None: no such bag."""
        bag = self.gold_bag()
        if bag is None or "holding" in bag.text and "uncursed" not in bag.text and "blessed" not in bag.text:
            return None
        return bag

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

    def bag_out_step(self, lv):
        """Housekeeping, before the shop and altar jobs: what is in the bag taken out when a use comes up. True if
        it used the turn."""
        if not self.opts.bag_store or not self.bstore.held:
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
        if not self.opts.bag_store:
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
        if not self.bag_open(bag):
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
        self.bstore.held += moved
        self.bstore.stats["put_in" if moved else "put_in_failed"] += 1
        self.bstore.stats["put_in_items"] += len(moved)
        return True

    def store_take_out(self, bag):
        n0 = len(self.items())
        if not self.bag_open(bag):
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
