"""Potion test by drinking (flag quaff_test): an unidentified potion whose possible types all cost 100 (known from
shop prices: pricemem / value.type_posterior) -- healing, extra healing, restore ability, confusion,
hallucination, sleeping -- is drunk with nothing threatening us, standing on Elbereth (sleeping: 25..34 helpless
turns uncursed). Healing, extra healing, confusion, hallucination and sleeping name themselves when drunk;
restore ability does not (potion.c peffects: unkn; the 'Call a ... potion' prompt is escaped by settle) -- its
"This makes you feel ..." marks the appearance restore ability (value.deduce_type).
Each appearance is drunk once. quaff_test="explored": only on a level explored (Level.explored).

"""
from collections import Counter

import nle.nethack as nh

from nhbot.consts import WEAK as WEAK_HUNGER
from nhbot.pricemem import OBJ, _INDEX, _cls_of, appearance

TEST_PRICE = 100
EFFECTS = (("much better", "extra healing"), ("feel better", "healing"), ("where am i", "confusion"),
           ("trippy", "confusion"), ("cosmic", "hallucination"), ("fall asleep", "sleeping"), ("yawn", "sleeping"),
           ("makes you feel", "restore ability"))     # statistics only: the first message that matches


class PotionTestMixin:
    def potiontest_init(self):
        self.quaff_tested = set()        # appearance keys drunk
        self.quaff_refused = set()       # (level key, square) where Elbereth would not stay written
        self.quaff_tries = Counter()     # (level key, square) -> Elbereth engravings for a test there
        self.quaff_stats = Counter()
        self.attr_best = {}              # restore_fix: NLE_BL index -> the best it has been (attr_track)

    # ---------------------------------------------------------------- restore_fix
    ATTRS = (nh.NLE_BL_STR125, nh.NLE_BL_DEX, nh.NLE_BL_CON, nh.NLE_BL_INT, nh.NLE_BL_WIS, nh.NLE_BL_CHA)

    def attr_track(self):
        """restore_fix, every tick: the best each attribute has been (not while Weak: hunger lowers Strength for a
        while, attrib.c ATEMP)."""
        if self.bl(nh.NLE_BL_HUNGER) >= WEAK_HUNGER:
            return
        for i in self.ATTRS:
            self.attr_best[i] = max(self.attr_best.get(i, 0), self.bl(i))

    def restore_potion(self, it):
        """A potion of restore ability we know as one (named, or its look worked out: value.deduce_type), not
        known cursed (a cursed one does nothing)."""
        if it.ocls != nh.POTION_CLASS or it.cursed or "unpaid" in it.text:
            return False
        key = appearance(it.text)
        return "restore ability" in it.text if key is None else self.deduced.get(key) == "restore ability"

    def restore_step(self, hostiles):
        """restore_fix: an attribute below the best it has been (poison: eat_bees, a sting), nothing next to us,
        not Weak: drink a potion of restore ability (potion.c: the first lowered attribute back up, all if
        blessed). True if it used the turn."""
        if not self.opts.restore_fix or hostiles or self.bl(nh.NLE_BL_HUNGER) >= WEAK_HUNGER:
            return False
        if not any(self.bl(i) < self.attr_best.get(i, 0) for i in self.ATTRS):
            return False
        it = next((it for it in self.items() if self.restore_potion(it)), None)
        if it is None:
            return False
        self.cur_act = "restore"
        if not self.ask("q", "drink"):
            return True
        self.press(it.letter)
        self.quaff_stats["restore_fix"] += 1
        for i in self.ATTRS:                 # what is still lower now stays so: not drunk for again
            self.attr_best[i] = self.bl(i)
        return True

    def potion_100(self, text):
        """An unidentified potion whose possible types (by the prices seen) all cost TEST_PRICE: healing, extra
        healing, restore ability, confusion, hallucination, sleeping."""
        key = appearance(text)
        if key is None or key in self.deduced:
            return False
        post = self.type_posterior(text)
        return bool(post) and all(OBJ[_INDEX[(_cls_of(n, key), n)]][3] == TEST_PRICE for n in post)

    def potion_to_test(self):
        for it in self.items():
            if it.ocls != nh.POTION_CLASS or "unpaid" in it.text:
                continue
            key = appearance(it.text)
            if key is None or key in self.quaff_tested:
                continue
            if self.potion_100(it.text):
                return it, key
        return None, None

    def quaff_test_step(self, lv):
        """No threat in view (the caller checks): stand on Elbereth, then drink one potion of the 100 group.
        True if it used the turn."""
        if not self.opts.quaff_test or (self.opts.quaff_test == "explored" and not lv.explored):
            return False
        it, key = self.potion_to_test()
        if it is None or (lv.key, self.pos()) in self.quaff_refused or not self.elb_can_write(lv):
            return False
        if self.peaceful_seen(lv):
            return False                     # hallucinating or confused, we'd hit one: shopkeeper, watch, priest
        if not self.elb_confirm(lv):
            here = (lv.key, self.pos())
            if self.quaff_tries[here] >= 2:
                self.quaff_refused.add(here)
                self.quaff_stats["elb_refused"] += 1
                return False
            self.quaff_tries[here] += 1
            self.cur_act = "quaff_test"
            self.quaff_stats["elb_written"] += 1
            if not self.engrave_elbereth():
                self.quaff_refused.add(here)
            return True
        self.cur_act = "quaff_test"
        self.quaff_tested.add(key)
        seq0 = self.msg_seq
        if not self.ask("q", "drink"):
            self.quaff_stats["no_prompt"] += 1
            return True
        self.press(it.letter)
        msgs = self.text_since(seq0).lower()
        if "this makes you feel" in msgs:      # "Wow! This makes you feel good!" / "Ulch! ... mediocre!"
            self.deduce_type(nh.POTION_CLASS, key, "restore ability")
            self.quaff_stats["deduced_restore_ability"] += 1
        what = next((n for s, n in EFFECTS if s in msgs), "unknown")
        self.quaff_stats["drunk"] += 1
        self.quaff_stats["got_" + what.replace(" ", "_")] += 1
        return True
