"""Altar BUC test (flag altar_test): carrying items whose curse status we don't know, an altar on the level is
an explore goal (goals 'altar'); standing on it with nothing threatening us, drop them one by one -- the game
flashes black for a cursed item, amber for a blessed one, nothing for an uncursed one, and marks each known
(pray.c doaltarobj; not while blind) -- then pick them all back up. Items on the body are left alone.
Each item is tested once (by name and enchantment: with implicit_uncursed an uncursed item may still show no
status word afterwards).
"""
import re
from collections import Counter

import nle.nethack as nh

from nhbot.consts import ALTAR_GLYPH
from nhbot.items import base_name

BUC_RE = re.compile(r"\b(?:uncursed|cursed|blessed)\b")


def buc_key(text):
    _, ench, name = base_name(text)
    return f"{ench}:{name}"


class AltarMixin:
    def altar_init(self):
        self.altar_known = set()         # buc_key of items whose status we learned (or saw)
        self.altar_dropped = None        # (level key, square, {buc_key}) lying on an altar, to pick back up
        self.altar_stats = Counter()

    def altar_untested(self):
        return [it for it in self.items()
                if it.ocls != nh.COIN_CLASS and not it.on_body and it.key not in self.cant_drop
                and not BUC_RE.search(it.text) and buc_key(it.text) not in self.altar_known
                and "unpaid" not in it.text]

    def altar_mask(self, lv):
        """Altar squares to walk to: something to test, or our things lying on one."""
        alt = self.terrain_glyphs(lv) == ALTAR_GLYPH
        if not self.opts.altar_test or not alt.any():
            return alt & False
        dropped = self.altar_dropped
        if dropped is not None and dropped[0] == lv.key:
            out = alt & False
            out[dropped[1]] = True
            return out
        return alt if self.altar_untested() else alt & False

    def altar_step(self, lv):
        """On an altar, nothing threatening us (the caller checks): drop one untested item, or pick them all
        back up when none is left. True if it used the turn."""
        if not self.opts.altar_test or self.terrain_glyphs(lv)[self.pos()] != ALTAR_GLYPH \
                or int(self.last_bl[nh.NLE_BL_CONDITION]) & (nh.BL_MASK_BLIND | nh.BL_MASK_LEV | nh.BL_MASK_HALLU):
            return False
        here = (lv.key, self.pos())
        untested = self.altar_untested()
        if untested:
            it = untested[0]
            seq0 = self.msg_seq
            self.cur_act = "altar"
            self.drop_units(it.letter)
            m = self.text_since(seq0)
            res = "cursed" if "black flash" in m else "blessed" if "amber flash" in m else "uncursed"
            self.altar_stats[res] += 1
            self.altar_known.add(buc_key(it.text))
            if self.altar_dropped is None or self.altar_dropped[:2] != here:
                self.altar_dropped = (lv.key, self.pos(), set())
            self.altar_dropped[2].add(buc_key(it.text))
            return True
        if self.altar_dropped is not None and self.altar_dropped[:2] == here:
            keys = self.altar_dropped[2]
            self.altar_dropped = None
            self.cur_act = "altar"
            self.pickup(lambda t: "for sale" not in t and buc_key(t) in keys, "altar")
            self.altar_stats["picked_back"] += 1
            return True
        return False
