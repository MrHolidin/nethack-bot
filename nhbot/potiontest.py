"""Potion test by drinking: an unidentified potion whose possible types all cost 100 (known from
shop prices: pricemem / value.type_posterior) -- healing, extra healing, restore ability, confusion,
hallucination, sleeping -- is drunk with nothing threatening us, standing on Elbereth (sleeping: 25..34 helpless
turns uncursed). Healing, extra healing, confusion, hallucination and sleeping name themselves when drunk;
restore ability does not (potion.c peffects: unkn; the 'Call a ... potion' prompt is escaped by settle) -- its
"This makes you feel ..." marks the appearance restore ability (value.deduce_type).
Each appearance is drunk once, only on a level explored (Level.explored).
A/B q2_v1 (with keep_100, hallu_wait, quaff_no_peace) on seeds 81000: -1083 [-2216, +113].
"""
from collections import Counter

import nle.nethack as nh

from nhbot.pricemem import OBJ, _INDEX, _cls_of, appearance

TEST_PRICE = 100
EFFECTS = (("much better", "extra healing"), ("feel better", "healing"), ("where am i", "confusion"),
           ("trippy", "confusion"), ("cosmic", "hallucination"), ("fall asleep", "sleeping"), ("yawn", "sleeping"),
           ("makes you feel", "restore ability"))     # statistics only: the first message that matches


class PotionTestState:
    """State of test-quaffing unknown potions (PotionTestMixin)."""
    def __init__(self):
        self.tested = set()              # appearance keys drunk
        self.refused = set()             # (level key, square) where Elbereth would not stay written
        self.tries = Counter()           # (level key, square) -> Elbereth engravings for a test there
        self.stats = Counter()


class PotionTestMixin:
    def potiontest_init(self):
        self.ptest = PotionTestState()

    def potiontest_summary(self):
        """Game summary entries."""
        return {"quaff_test": dict(self.ptest.stats)}

    def potion_100(self, text):
        """An unidentified potion whose possible types (by the prices seen) all cost TEST_PRICE: healing, extra
        healing, restore ability, confusion, hallucination, sleeping."""
        key = appearance(text)
        if key is None or key in self.value.deduced:
            return False
        post = self.type_posterior(text)
        return bool(post) and all(OBJ[_INDEX[(_cls_of(n, key), n)]][3] == TEST_PRICE for n in post)

    def potion_to_test(self):
        for it in self.items():
            if it.ocls != nh.POTION_CLASS or it.unpaid:
                continue
            key = appearance(it.text)
            if key is None or key in self.ptest.tested:
                continue
            if self.potion_100(it.text):
                return it, key
        return None, None

    def quaff_test_step(self, lv):
        """No threat in view (the caller checks), on a level explored: stand on Elbereth, then drink one potion of
        the 100 group. True if it used the turn."""
        if not lv.explored:
            return False
        it, key = self.potion_to_test()
        if it is None or (lv.key, self.pos()) in self.ptest.refused or not self.elb_can_write(lv):
            return False
        if self.peaceful_seen(lv):
            return False                     # hallucinating or confused, we'd hit one: shopkeeper, watch, priest
        if not self.elb_confirm(lv):
            here = (lv.key, self.pos())
            if self.ptest.tries[here] >= 2:
                self.ptest.refused.add(here)
                self.ptest.stats["elb_refused"] += 1
                return False
            self.ptest.tries[here] += 1
            self.cur_act = "quaff_test"
            self.ptest.stats["elb_written"] += 1
            if not self.engrave_elbereth():
                self.ptest.refused.add(here)
            return True
        self.cur_act = "quaff_test"
        self.ptest.tested.add(key)
        seq0 = self.msg_seq
        if not self.ask_drink():
            self.ptest.stats["no_prompt"] += 1
            return True
        self.press(it.letter)
        msgs = self.text_since(seq0).lower()
        if "this makes you feel" in msgs:      # "Wow! This makes you feel good!" / "Ulch! ... mediocre!"
            self.deduce_type(nh.POTION_CLASS, key, "restore ability")
            self.ptest.stats["deduced_restore_ability"] += 1
        what = next((n for s, n in EFFECTS if s in msgs), "unknown")
        self.ptest.stats["drunk"] += 1
        self.ptest.stats["got_" + what.replace(" ", "_")] += 1
        return True
