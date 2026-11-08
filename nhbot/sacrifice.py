"""Sacrifice (flag sacrifice): a neutral hero offers fresh corpses of its kills at a neutral altar -- for the first
gift, a role's own artifact when it shares our alignment (artifact.c mk_artifact): Mjollnir for a neutral Valkyrie.

pray.c dosacrifice: a corpse is worth its difficulty + 1 while it is at most 50 turns old (older: "Nothing
happens" -- worth nothing); our own race is cannibalism, a unicorn of our alignment angers our god -- neither is
offered. A worthy offering at a coaligned altar first works off the prayer timeout ("You have a hopeful
feeling"); with no timeout left, at XL 3 and more and Luck not below 0, 1 in (10 + 2 * gifts * artifacts) is a
gift ("An object appears at your feet!"), else Luck.

Which kill: one of ours on this level (survival.kills, the corpse still showing), not too heavy to carry
(SAC_CARRY_WT, unless it lies on the altar already), that we can bring to the altar in time: the walk to it and
from it to the altar (danger-free Dijkstra steps, a turn each) plus SAC_SLACK turns, within 50 of the kill.
An altar's alignment is read from a look on it (':' -- "There is an altar to Mitra (neutral) here."): an altar on
the level whose alignment we don't know is walked to once, when nothing else is to be done here (no fight).
"""
import re
from collections import Counter

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import ALTAR_GLYPH
from nhbot.monsters import PM_BY_NAME, RACE_FLAG

SAC_AGE = 50          # pray.c: a corpse older than this is worth nothing
SAC_SLACK = 6         # turns kept in hand for the pick-up, the offer and a step lost on the way
SAC_CARRY_WT = 600    # corpses heavier than this are offered only where they lie (on the altar)
ALTAR_RE = re.compile(r"There is an altar to .+? \((lawful|neutral|chaotic|unaligned)\) here")
SAC_RESULTS = (("consumed in a burst of flame", "accepted"), ("hopeful feeling", "timeout"), ("feeling of reconciliation", "timeout"),
               ("four-leaf clover", "luck"), ("object appears at your feet", "gift"),
               ("Nothing happens", "too_old"), ("feeling of inadequacy", "inadequate"),
               ("You feel guilty", "guilty"), ("infamous offense", "cannibal"))


class SacrificeState:
    """State of sacrificing corpses at an altar (SacrificeMixin)."""
    def __init__(self):
        self.carry = None                # (kill turn, name): the corpse we carry to the altar
        self.stats = Counter()
        self.gift_here = None            # (level key, square) a gift appeared on: pick it up


class SacrificeMixin:
    def sacrifice_init(self):
        self.sac = SacrificeState()

    def sacrifice_summary(self):
        """Game summary entries."""
        return {"sacrifice": dict(self.sac.stats)}

    def msg_sacrifice(self, m, lv):
        """An altar's alignment; what an offering did."""
        if not self.opts.sacrifice or lv is None:
            return
        mm = ALTAR_RE.search(m)
        if mm:
            lv.altar_align[self.pos()] = mm.group(1)

    def sac_carrying(self, it):
        """The corpse we carry to the altar (the weight step keeps it)."""
        return self.sac.carry is not None and it.ocls == nh.FOOD_CLASS and self.sac.carry[1] + " corpse" in it.text

    def sac_ok(self, name):
        """A corpse we may offer: known, not our race, not a unicorn."""
        pm = PM_BY_NAME.get(name)
        if pm is None or "unicorn" in name:
            return False
        return not pm.mflags2 & RACE_FLAG.get((self.race or "").lower(), 0)

    def sac_altars(self, lv):
        """Squares of the altars of our alignment on this level (read on stepping there)."""
        ours = {1: "lawful", 0: "neutral", -1: "chaotic"}.get(int(self.last_bl[nh.NLE_BL_ALIGN]))
        alt = self.terrain_glyphs(lv) == ALTAR_GLYPH
        return [p for p, a in lv.altar_align.items() if a == ours and alt[p]]

    def sacrifice_step(self, lv, hostiles):
        """Not in a fight: offer the corpse we carry or that lies on the altar under us; carry one there in time;
        pick up a gift. True if it used the turn."""
        if not self.opts.sacrifice or int(self.last_bl[nh.NLE_BL_ALIGN]) != 0 or hostiles:
            return False
        here = self.pos()
        if self.sac.gift_here == (lv.key, here):
            self.sac.gift_here = None
            self.pickup_matching(["Mjollnir", "named", "war hammer"], own=True)
            self.sac.stats["gift_picked"] += 1
            return True
        if self.sac_learn_altar(lv):
            return True
        altars = self.sac_altars(lv)
        if not altars:
            return False
        t = self.turn()
        k_mem, k_live, passable = grids = self.grids(lv)
        amask = np.zeros_like(passable)
        for p in altars:
            amask[p] = True
        if self.sac.carry is not None:
            kt, name = self.sac.carry
            if t - kt >= SAC_AGE or not any(name + " corpse" in it.text for it in self.items()):
                self.sac.carry = None            # too old now (or gone): it is only weight
                self.sac.stats["carry_late"] += 1
                return False
            if amask[here]:
                return self.offer(lv, name, carried=True)
            self.cur_act = "sacrifice"
            return self.walk_to(lv, amask, grids=grids, act="sacrifice")[0] == "moved"
        cands = []
        for kt, name, pos, key in self.combat.kills:
            if key != lv.key or t - kt >= SAC_AGE or G.KIND[lv.under[pos]] != G.CORPSE or not self.sac_ok(name):
                continue
            if amask[pos]:
                cands.append((0, kt, name, pos))
                continue
            if PM_BY_NAME[name].cwt > SAC_CARRY_WT:
                continue
            tm = np.zeros_like(passable)
            tm[pos] = True
            d1 = self.dijkstra(lv, k_mem, k_live, passable, here, tm, want_dist=True)[0][pos]
            d2 = self.dijkstra(lv, k_mem, k_live, passable, pos, amask, want_dist=True)[0][amask].min()
            if t + d1 + d2 + SAC_SLACK < kt + SAC_AGE:
                cands.append((d1, kt, name, pos))
        if not cands:
            return False
        _, kt, name, pos = min(cands)
        self.cur_act = "sacrifice"
        if here == pos:
            if amask[here]:
                return self.offer(lv, name, carried=False)
            self.pickup_matching([name + " corpse"], own=True)
            if any(name + " corpse" in it.text for it in self.items()):
                self.sac.carry = (kt, name)
                self.sac.stats["picked"] += 1
                self.combat.kills = [k for k in self.combat.kills if k[2] != pos or k[3] != lv.key]
            else:
                self.combat.kills = [k for k in self.combat.kills if k[2] != pos or k[3] != lv.key]   # can't lift it
                self.sac.stats["not_lifted"] += 1
            return True
        tm = np.zeros_like(passable)
        tm[pos] = True
        return self.walk_to(lv, tm, grids=grids, act="sacrifice")[0] == "moved"

    def sac_learn_altar(self, lv):
        """An altar here whose alignment we don't know: on it, look (free); else walk to the nearest such one.
        One we can't reach is noted '?' (not tried again)."""
        alt = self.terrain_glyphs(lv) == ALTAR_GLYPH
        unknown = [(int(a), int(b)) for a, b in zip(*np.nonzero(alt)) if (int(a), int(b)) not in lv.altar_align]
        if not unknown:
            return False
        here = self.pos()
        if here in unknown:
            seq0 = self.msg_seq
            tty0 = self.tty_text()
            seen = " | ".join(self.look_here()) + " | " + self.text_since(seq0) + " | " + tty0
            mm = ALTAR_RE.search(seen)
            if mm:
                lv.altar_align[here] = mm.group(1)
            if here not in lv.altar_align:
                lv.altar_align[here] = "?"
            self.sac.stats["altar_looked"] += 1
            return False                          # a look takes no time
        mask = np.zeros_like(alt)
        for p in unknown:
            mask[p] = True
        status, reached = self.walk_to(lv, mask, act="sacrifice")
        if status == "moved":
            return True
        for p in unknown:
            lv.altar_align[p] = "?"
        return False

    def offer(self, lv, name, carried):
        """#offer (M-o) the corpse: the one on the floor here, or the carried one by its letter."""
        seq0 = self.msg_seq
        self.raw_step(239)                       # M-o: #offer
        m = self.message()
        if self.obs["misc"][0] and "corpse here" in m and name in m and not carried:
            self.press("y")
        else:
            if self.obs["misc"][0] and "corpse here" in m:
                self.press("n", expect_prompt=True)
            it = next((i for i in self.items() if name + " corpse" in i.text), None)
            if it is None or "sacrifice" not in self.message().lower():
                self.settle()
                self.sac.carry = None
                self.sac.stats["offer_failed"] += 1
                return True
            self.press(it.letter)
        said = self.text_since(seq0)
        self.sac.carry = None
        self.combat.kills = [k for k in self.combat.kills if not (k[1] == name and k[3] == lv.key and k[2] == self.pos())]
        self.sac.stats["offered"] += 1
        for phrase, what in SAC_RESULTS:
            if phrase in said:
                self.sac.stats[what] += 1
                if what == "gift":
                    self.sac.gift_here = (lv.key, self.pos())
        return True
