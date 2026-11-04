"""Excalibur (wiki "Excalibur"): lawful, XL >= 5, dip an unnamed long sword into a fountain;
1/6 per dip, the fountain disappears on success."""
import re

import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import FLOOR_GLYPH, FOUNTAIN_GLYPH

DEMON_WIN = 0.7      # fountain_wish: dip only while P(we beat a water demon) is above this


class ExcaliburMixin:
    def excal_init(self):
        self.excalibur = False
        self.excal_turn = None
        self.dips = 0
        self.dip_events = []
        self.fountain_levels = set()
        self.excal_trips = 0
        self.excal_skip = set()
        self.demon_win = (None, 0.0)     # fountain_wish: (state key, P(we beat a water demon))

    def long_sword(self):
        for it in self.items():
            if it.ocls == nh.WEAPON_CLASS and re.search(r"\blong sword\b", it.text) and "named" not in it.text \
                    and "Excalibur" not in it.text and not it.cursed:
                return it.letter, it.text
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
        fmask = self.terrain_glyphs(lv) == FOUNTAIN_GLYPH
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
                   and (self.terrain_glyphs(l) == FOUNTAIN_GLYPH).any()
                   and not (l.shop.any() and (self.terrain_glyphs(l) == FOUNTAIN_GLYPH)[l.shop].all())]
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
        recent = self.dip_into_fountain(lv, it[0])
        if recent is None:
            return False
        y, x = self.pos()
        if "Excalibur" in recent or "hand reaches up" in recent or \
                any("Excalibur" in s for _, _, s in self.inventory()):
            self.excalibur = True
            self.excal_turn = self.turn()
            lv.set_terrain((y, x), FLOOR_GLYPH)
            self.dip_events.append((self.turn(), "excalibur"))
        elif self.fountain_gone(recent):
            lv.set_terrain((y, x), FLOOR_GLYPH)
            self.dip_events.append((self.turn(), "dried"))
        return True

    @staticmethod
    def fountain_gone(recent):
        return "dries up" in recent or "fountain disappears" in recent or "anything to dip" in recent

    def dip_into_fountain(self, lv, letter):
        """#dip an inventory item into the fountain we stand on. The messages since, or None if no dip
        happened (no fountain here any more: forgotten)."""
        seq0 = self.msg_seq
        self.raw_step(228)                       # M-d: #dip
        if "dip" not in self.message().lower():
            self.settle(); return None
        self.raw_step(ord(letter))
        m = self.message().lower()
        if "fountain" in m and self.obs["misc"][0]:
            self.press("y")
        else:
            self.settle()
            if "nothing to dip" in m or "anything to dip" in m or "into" in m:
                lv.set_terrain(self.pos(), FLOOR_GLYPH)       # no fountain here any more
            return None
        self.dips += 1
        return self.text_since(seq0)

    def demon_win_prob(self):
        """P(we win a fight with a water demon next to us, from full HP) -- danger.win_prob, cached while what it
        depends on stays the same (level, XL, max HP, AC, the weapon in hand)."""
        weapon = next((it.text for it in self.items() if it.wielded), None)
        key = (self.bl(nh.NLE_BL_DEPTH), self.bl(nh.NLE_BL_XP), self.bl(nh.NLE_BL_HPMAX), self.bl(nh.NLE_BL_AC),
               weapon)
        if self.demon_win[0] != key:
            self.demon_win = (key, self.win_prob([(None, "water demon")]))
        return self.demon_win[1]

    def fountain_wish_step(self, lv):
        """fountain_wish (no threat in view, the caller checks): Excalibur in hand at full HP, dip it into a
        fountain of this level -- fountain.c dipfountain: 1/30 a water demon, a wish at (20 - depth)%, else
        hostile (M2_HOSTILE). Only while P(we beat that demon) > DEMON_WIN. Not in the Mines (Minetown's watch),
        not a shop's. True if it used the turn."""
        if not (self.opts.fountain_wish and self.excalibur) or lv.key[0] == 2:
            return False
        exc = next((it for it in self.items() if "Excalibur" in it.text and it.wielded), None)
        if exc is None or self.bl(nh.NLE_BL_HP) < self.bl(nh.NLE_BL_HPMAX):
            return False
        fmask = self.terrain_glyphs(lv) == FOUNTAIN_GLYPH
        if lv.shop.any():
            fmask &= ~lv.shop
        if not fmask.any() or lv.key in self.excal_skip:
            return False
        if self.demon_win_prob() <= DEMON_WIN:
            return False                          # the demon a dip may bring could kill us (danger.win_prob)
        self.cur_act = "fountain_wish"
        y, x = self.pos()
        if fmask[y, x]:
            recent = self.dip_into_fountain(lv, exc.letter)
            if recent is None:
                return False
            if "water demon" in recent:
                self.dip_events.append((self.turn(), "wish" if "grants you a wish" in recent else "demon"))
            if self.fountain_gone(recent):
                lv.set_terrain((y, x), FLOOR_GLYPH)
                self.dip_events.append((self.turn(), "dried"))
            return True
        if self.walk_to(lv, fmask, max_cost=self.opts.excal_cost, act="fountain_wish", also=fmask)[0] == "moved":
            return True
        self.excal_skip.add(lv.key)
        return False
