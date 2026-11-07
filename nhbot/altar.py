"""Altar BUC test: carrying items whose curse status we don't know, an altar on the level is
an explore goal (goals 'altar'); standing on it with nothing threatening us, drop them one at a time -- the game
flashes black for a cursed item, amber for a blessed one, nothing for an uncursed one, and marks each known
(pray.c doaltarobj; not while blind) -- each picked back up right after its flash (all dropped first left
a pile whose pick-up menu ran to several pages, and things on the altar for monsters to take). Items on the body are left alone.
Each item is tested once (by name and enchantment: with implicit_uncursed an uncursed item may still show no
status word afterwards).
"""
import re
from collections import Counter

import nle.nethack as nh
import numpy as np

from nhbot import glyphs as G
from nhbot.consts import ALTAR_GLYPH, DELTA2KEY, NEIGH
from nhbot.items import base_name

BUC_RE = re.compile(r"\b(?:uncursed|cursed|blessed)\b")


def buc_key(text):
    _, ench, name = base_name(text)
    return f"{ench}:{name}"


PROTECTION_MAX = 9           # priest.c priest_talk: below this much protection a donation of 400*XL always adds
PROTECTION_TRIES = 6         # donations at most on one level (one that didn't pay: something we don't see is off)
PROTECTION_BUYS = 1          # protection bought at most this many times (A/B buy_protection +40 [-155, +258])


class AltarMixin:
    def altar_init(self):
        self.altar_known = set()         # buc_key of items whose status we learned (or saw)
        self.altar_dropped = None        # (level key, square, {buc_key}) lying on an altar, to pick back up
        self.altar_stats = Counter()
        self.prot_bought = 0             # AC the temple priests' protection gave us
        self.prot_stats = Counter()
        self.temple_levels = set()       # levels where we entered a temple ("Pilgrim, you enter a sacred place!")
        self.prot_tries = Counter()      # level key -> donations there
        self._temple_seq = 0

    def protection_step(self, lv):
        """Buy protection from a temple priest (priest.c priest_talk): a donation of 400 * XL (below 600 * XL)
        gives 2-4 points of AC the first time, one more each time after, every time while the protection is below
        PROTECTION_MAX -- PROTECTION_BUYS times at most; gold in our bag is taken out for it. Only on a level where we entered his temple (out of it he takes a chat for an insult and
        turns hostile), with the gold for it, nothing threatening us (the caller checks): to a square next to him,
        #chat, offer. True if it used the turn."""
        new = self.msgs_since(self._temple_seq) if self._temple_seq else []
        self._temple_seq = self.msg_seq
        if any("enter a sacred place" in m for m in new):
            self.temple_levels.add(lv.key)
        if lv.key not in self.temple_levels or self.prot_bought >= PROTECTION_MAX \
                or self.prot_stats["bought"] >= PROTECTION_BUYS \
                or self.prot_tries[lv.key] >= PROTECTION_TRIES \
                or int(self.last_bl[nh.NLE_BL_CONDITION]) & (nh.BL_MASK_BLIND | nh.BL_MASK_HALLU | nh.BL_MASK_CONF
                                                             | nh.BL_MASK_STUN):
            return False
        offer = 400 * int(self.bl(nh.NLE_BL_XP))
        gold = int(self.bl(nh.NLE_BL_GOLD))
        bag = self.gold_bag()
        if gold < offer and bag is not None and gold + self.bag_gold >= offer:
            self.prot_stats["bag_out"] += 1
            return self.bag_take_out(bag)             # the gold we keep in the bag (nhbot.goldbag) counts too
        if gold < offer:
            return False
        g = self.obs["glyphs"]
        ys, xs = np.nonzero(G.KIND[g] == G.MONSTER)
        priests = [(int(a), int(b)) for a, b in zip(ys, xs) if G.monster_name(int(g[a, b])) == "aligned priest"]
        if not priests:
            return False
        y, x = self.pos()
        p = min(priests, key=lambda q: max(abs(q[0] - y), abs(q[1] - x)))
        if max(abs(p[0] - y), abs(p[1] - x)) == 1:
            if not self.peaceful_now(lv, p):
                self.prot_tries[lv.key] = PROTECTION_TRIES     # angered: leave him be
                self.prot_stats["hostile"] += 1
                return False
            return self.donate(lv, p, offer)
        mask = np.zeros_like(lv.under, dtype=bool)
        for dy, dx in NEIGH:
            if 0 <= p[0] + dy < mask.shape[0] and 0 <= p[1] + dx < mask.shape[1]:
                mask[p[0] + dy, p[1] + dx] = True
        status, _ = self.walk_to(lv, mask, max_cost=200, act="protection")
        return status == "moved"

    def donate(self, lv, p, offer):
        """#chat toward the priest at p, offer `offer` gold (typed into the 'How much will you offer?' line --
        the generic prompt handling would escape it, an offer of 0: "Thou shalt regret thine action!")."""
        self.cur_act = "protection"
        self.prot_tries[lv.key] += 1
        self.prot_stats["donate"] += 1
        ac0 = int(self.bl(nh.NLE_BL_AC))
        seq = self.msg_seq
        y, x = self.pos()
        self.press("#", expect_prompt=True)
        for c in "chat":
            self.raw_step(ord(c))
        self.raw_step(13)
        self.raw_step(ord(DELTA2KEY[(p[0] - y, p[1] - x)]))
        for _ in range(6):
            tty = self.tty_text()
            if "--More--" in tty.replace("\n", ""):
                self.log_msg(self.top_line().replace("--More--", ""))
                self.raw_step(13)
                continue
            if self.obs["misc"][1] and "offer" in (self.message() + self.top_line()).lower():
                for c in str(offer):
                    self.raw_step(ord(c))
                self.raw_step(13)
                self.prot_stats["offered"] += 1
            break
        self.settle()
        said = self.text_since(seq)
        if "rewarded for thy devotion" in said:
            gain = max(1, ac0 - int(self.bl(nh.NLE_BL_AC)))
            self.prot_bought += gain
            self.prot_stats["bought"] += 1
            self.prot_stats["ac"] += gain
        elif "selfless generosity" in said or "pious individual" in said or "Cheapskate" in said:
            self.prot_stats["no_protection"] += 1
        else:
            self.prot_stats["other"] += 1
            self.prot_tries[lv.key] = PROTECTION_TRIES          # not what we expected: no more here
        return True

    def altar_untested(self):
        return [it for it in self.items()
                if it.ocls != nh.COIN_CLASS and not it.on_body and it.key not in self.cant_drop
                and not BUC_RE.search(it.text) and buc_key(it.text) not in self.altar_known
                and "unpaid" not in it.text]

    def altar_mask(self, lv):
        """Altar squares to walk to: something to test, or our things lying on one."""
        alt = self.terrain_glyphs(lv) == ALTAR_GLYPH
        if not alt.any():
            return alt & False
        dropped = self.altar_dropped
        if dropped is not None and dropped[0] == lv.key:
            out = alt & False
            out[dropped[1]] = True
            return out
        return alt if self.altar_untested() else alt & False

    def altar_step(self, lv):
        """On an altar, nothing threatening us (the caller checks): pick back up what we dropped, else drop the
        next untested item. True if it used the turn."""
        if self.terrain_glyphs(lv)[self.pos()] != ALTAR_GLYPH \
                or int(self.last_bl[nh.NLE_BL_CONDITION]) & (nh.BL_MASK_BLIND | nh.BL_MASK_LEV | nh.BL_MASK_HALLU):
            return False
        here = (lv.key, self.pos())
        if self.altar_dropped is not None and self.altar_dropped[:2] == here:
            return self.altar_pick_back()
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
        return False

    def altar_pick_back(self):
        keys = self.altar_dropped[2]
        self.altar_dropped = None
        self.cur_act = "altar"
        self.pickup(lambda t: "for sale" not in t and buc_key(t) in keys, "altar")
        self.altar_stats["picked_back"] += 1
        return True
