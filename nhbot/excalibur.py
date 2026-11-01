"""Excalibur (wiki "Excalibur"): lawful, XL >= 5, dip an unnamed long sword into a fountain;
1/6 per dip, the fountain disappears on success."""
import re

import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import FLOOR_GLYPH, FOUNTAIN_GLYPH


class ExcaliburMixin:
    def excal_init(self):
        self.excalibur = False
        self.excal_turn = None
        self.dips = 0
        self.dip_events = []
        self.fountain_levels = set()
        self.excal_trips = 0
        self.excal_skip = set()

    def long_sword(self):
        for letter, ocls, s in self.inventory():
            if ocls == nh.WEAPON_CLASS and re.search(r"\blong sword\b", s) and "named" not in s \
                    and "Excalibur" not in s and " cursed" not in s:
                return letter, s
        return None

    def excal_eligible(self):
        if self.excalibur:
            return False
        if int(self.last_bl[nh.NLE_BL_ALIGN]) != 1:
            return False
        if self.bl(nh.NLE_BL_XP) < self.opts.excal_xl:
            return False
        hp, maxhp = self.bl(nh.NLE_BL_HP), self.bl(nh.NLE_BL_HPMAX)
        if hp < maxhp * self.opts.excal_hp:
            return False
        return self.long_sword() is not None

    def excal_step(self, lv):
        fmask = lv.under == FOUNTAIN_GLYPH
        if fmask.any():
            self.fountain_levels.add(lv.key)
        if not self.excal_eligible():
            return False
        if not fmask.any():
            return self.excal_go_up(lv)
        if lv.shop.any() and fmask[lv.shop].any():
            fmask &= ~lv.shop
        if lv.key[0] == 2:
            fmask[:] = False          # Minetown: a fountain drying up angers the watch
        y, x = self.pos()
        if fmask[y, x]:
            return self.dip(lv)
        if self.walk_to(lv, fmask, max_cost=self.opts.excal_cost, act="excal", also=fmask)[0] == "moved":
            return True
        self.excal_skip.add(lv.key)                # can't reach it: don't keep coming back
        return False

    def excal_go_up(self, lv):
        """No fountain here, but one is remembered a few levels up: walk back up to it."""
        if lv.key[0] != 0 or self.excal_trips >= self.opts.excal_trips:
            return False
        dl = lv.key[1]
        targets = [k for k, l in self.levels.items()
                   if k[0] == 0 and dl - self.opts.excal_up <= k[1] < dl and k not in self.excal_skip
                   and (l.under == FOUNTAIN_GLYPH).any() and not (l.shop.any() and (l.under == FOUNTAIN_GLYPH)[l.shop].all())]
        if not targets:
            return False
        k_mem = self.grids(lv)[0]
        up = k_mem == G.UPSTAIR
        if not up.any():
            return False
        y, x = self.pos()
        if up[y, x]:
            self.cur_act = "excal"
            self.excal_trips += 1
            self.press("<")
            return True
        return self.walk_to(lv, up, max_cost=self.opts.excal_cost_up, act="excal")[0] == "moved"

    def dip(self, lv):
        it = self.long_sword()
        if not it:
            return False
        self.cur_act = "excal"
        seq0 = self.msg_seq
        self.raw_step(228)                       # M-d: #dip
        if "dip" not in self.message().lower():
            self.settle(); return False
        self.raw_step(ord(it[0]))
        m = self.message().lower()
        if "fountain" in m and self.obs["misc"][0]:
            self.press("y")
        else:
            self.settle()
            y, x = self.pos()
            if "nothing to dip" in m or "anything to dip" in m or "into" in m:
                lv.under[y, x] = FLOOR_GLYPH       # no fountain here any more
            return False
        self.dips += 1
        recent = " ".join(t for _, t in list(self.messages)[-6:])
        y, x = self.pos()
        if self.audit("dip", recent, seq0, lambda s: "Excalibur" in s or "hand reaches up" in s) or \
                any("Excalibur" in s for _, _, s in self.inventory()):
            self.excalibur = True
            self.excal_turn = self.turn()
            lv.under[y, x] = FLOOR_GLYPH
            self.dip_events.append((self.turn(), "excalibur"))
        elif "dries up" in recent or "fountain disappears" in recent or "anything to dip" in recent:
            lv.under[y, x] = FLOOR_GLYPH
            self.dip_events.append((self.turn(), "dried"))
        return True
