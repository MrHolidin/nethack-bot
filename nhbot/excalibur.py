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
        k_mem, k_live = self.kind_grid(lv)
        p = self.passable_grid(lv, k_mem, k_live)
        p |= fmask
        dist, prev, reached = self.dijkstra(lv, k_mem, k_live, p, (y, x), fmask, max_cost=self.opts.excal_cost)
        if reached is None:
            self.excal_skip.add(lv.key)            # can't reach it: don't keep coming back
            return False
        step = self.first_step(prev, (y, x), reached)
        if step is None:
            return False
        self.cur_act = "excal"
        self.move(step)
        return True

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
        k_mem, k_live = self.kind_grid(lv)
        up = k_mem == G.UPSTAIR
        if not up.any():
            return False
        y, x = self.pos()
        if up[y, x]:
            self.cur_act = "excal"
            self.excal_trips += 1
            self.press("<")
            return True
        p = self.passable_grid(lv, k_mem, k_live)
        dist, prev, reached = self.dijkstra(lv, k_mem, k_live, p, (y, x), up, max_cost=self.opts.excal_cost_up)
        if reached is None:
            return False
        step = self.first_step(prev, (y, x), reached)
        if step is None:
            return False
        self.cur_act = "excal"
        self.move(step)
        return True

    def dip(self, lv):
        it = self.long_sword()
        if not it:
            return False
        self.cur_act = "excal"
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
        if "Excalibur" in recent or "hand reaches up" in recent or \
                any("Excalibur" in s for _, _, s in self.inventory()):
            self.excalibur = True
            self.excal_turn = self.turn()
            lv.under[y, x] = FLOOR_GLYPH
            self.dip_events.append((self.turn(), "excalibur"))
        elif "dries up" in recent or "fountain disappears" in recent or "anything to dip" in recent:
            lv.under[y, x] = FLOOR_GLYPH
            self.dip_events.append((self.turn(), "dried"))
        return True
