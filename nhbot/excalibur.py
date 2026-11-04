"""Excalibur (wiki "Excalibur"): lawful, XL >= 5, dip an unnamed long sword into a fountain;
1/6 per dip, the fountain disappears on success."""
import re

import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import FLOOR_GLYPH, FOUNTAIN_GLYPH
from nhbot.equipment import CLOAK, GLOVES, SHIRT, SUIT

JUNK_CLASSES = (nh.GEM_CLASS, nh.ROCK_CLASS, nh.WEAPON_CLASS, nh.TOOL_CLASS, nh.ARMOR_CLASS)   # water spoils little
CONTAINERS = ("bag", "sack", "box", "chest", "lamp", "candle")
FOUNTAIN_DIP_DEPTH = 20     # fountain_dip: on dungeon levels above this only
DEMON_WIN = 0.7      # dip Excalibur for a wish only while P(we beat a water demon) is above this


class ExcaliburMixin:
    def excal_init(self):
        self.excalibur = False
        self.excal_turn = None
        self.dips = 0
        self.dip_events = []
        self.fountain_levels = set()
        self.excal_trips = 0
        self.excal_skip = set()
        self.demon_win = (None, 0.0)     # (state key, P(we beat a water demon))

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
        recent = self.text_since(seq0)
        if "water demon" in recent:              # fountain.c dipfountain case 21, either reason to dip
            self.dip_events.append((self.turn(), "wish" if "grants you a wish" in recent else "demon"))
        if "glows for a moment" in recent:       # cases 17..20: the dipped item was cursed and is not now
            self.dip_events.append((self.turn(), "uncursed"))
        return recent

    def demon_win_prob(self):
        """P(we win a fight with a water demon next to us, from full HP) -- danger.win_prob, cached while what it
        depends on stays the same (level, XL, max HP, AC, the weapon in hand)."""
        weapon = next((it.text for it in self.items() if it.wielded), None)
        key = (self.bl(nh.NLE_BL_DEPTH), self.bl(nh.NLE_BL_XP), self.bl(nh.NLE_BL_HPMAX), self.bl(nh.NLE_BL_AC),
               weapon)
        if self.demon_win[0] != key:
            self.demon_win = (key, self.win_prob([(None, "water demon")]))
        return self.demon_win[1]

    def fountains(self, lv):
        """Fountains of this level we may use: not a shop's, not in the Mines (Minetown's watch), not on a
        level we gave up reaching them on."""
        fmask = self.terrain_glyphs(lv) == FOUNTAIN_GLYPH
        if lv.key[0] == 2 or lv.key in self.excal_skip:
            return fmask & False
        return fmask & ~lv.shop if lv.shop.any() else fmask

    def dip_at_fountain(self, lv, fmask, letter, act):
        """On a fountain of fmask: dip `letter`; else walk toward the nearest. True if it used the turn."""
        self.cur_act = act
        y, x = self.pos()
        if fmask[y, x]:
            recent = self.dip_into_fountain(lv, letter)
            if recent is None:
                return False
            if self.fountain_gone(recent):
                lv.set_terrain((y, x), FLOOR_GLYPH)
                self.dip_events.append((self.turn(), "dried"))
            return True
        if self.walk_to(lv, fmask, max_cost=self.opts.excal_cost, act=act, also=fmask)[0] == "moved":
            return True
        self.excal_skip.add(lv.key)
        return False

    def fountain_wish_step(self, lv):
        """No threat in view (the caller checks): Excalibur in hand at full HP, dip it into a fountain of this
        level -- fountain.c dipfountain: 1/30 a water demon, a wish at (20 - depth)%, else hostile
        (M2_HOSTILE). Only while P(we beat that demon) > DEMON_WIN. True if it used the turn. (A/B
        fountain_wish: +310 [-562, +1180]; wishes in 35 games of 1000 against 23.)"""
        if not self.excalibur:
            return False
        exc = next((it for it in self.items() if "Excalibur" in it.text and it.wielded), None)
        if exc is None or self.bl(nh.NLE_BL_HP) < self.bl(nh.NLE_BL_HPMAX):
            return False
        fmask = self.fountains(lv)
        if not fmask.any() or self.demon_win_prob() <= DEMON_WIN:
            return False                          # the demon a dip may bring could kill us (danger.win_prob)
        return self.dip_at_fountain(lv, fmask, exc.letter, "fountain_wish")

    # ------------------------------------------------------------------ flag fountain_dip
    def dippable_cursed(self):
        """A known-cursed thing on us the water can reach (do_wear.c inaccessible_equipment: no suit under a
        cloak, no shirt under a suit or cloak, no ring under gloves); not lawful, not a long sword (a dip at
        XL 5+ curses it, may take a point off it and dries the fountain). We know of a curse mostly from taking
        a piece off for a better one (equipment.wear): just when lifting it pays."""
        lawful = int(self.last_bl[nh.NLE_BL_ALIGN]) == 1
        worn = self.worn_by_slot()
        covered = set()
        if CLOAK in worn:
            covered |= {SUIT, SHIRT}
        if SUIT in worn:
            covered.add(SHIRT)
        covered = {worn[s]["letter"] for s in covered if s in worn}
        for it in self.items():
            if not (it.cursed and it.on_body) or it.letter in covered \
                    or (not lawful and re.search(r"\blong sword\b", it.text)):
                continue
            if it.ring_on and GLOVES in worn:
                continue
            return it
        return None

    def junk_to_dip(self):
        """Something we don't need that water spoils little: not on us, not kept (carry.needed), no food,
        container or light; gems and stones first."""
        cands = [it for it in self.items() if it.ocls in JUNK_CLASSES and not it.on_body and not it.alternate
                 and not it.quivered and "unpaid" not in it.text and not self.needed(it)
                 and not any(w in it.text for w in CONTAINERS) and not re.search(r"\blong sword\b", it.text)]
        return min(cands, key=lambda it: JUNK_CLASSES.index(it.ocls), default=None)

    def fountain_dip_step(self, lv):
        """fountain_dip (no threat in view -- the caller checks), above dungeon level FOUNTAIN_DIP_DEPTH, HP at
        excal_hp: dip a cursed thing on us (4/30 the water uncurses it); else, not lawful (the lawful dip
        Excalibur: fountain_wish_step) and while P(we beat a water demon) > DEMON_WIN, a thing we don't need
        (1/30 a water demon). True if it used the turn."""
        if not self.opts.fountain_dip or self.bl(nh.NLE_BL_DEPTH) >= FOUNTAIN_DIP_DEPTH:
            return False
        if self.bl(nh.NLE_BL_HP) < self.bl(nh.NLE_BL_HPMAX) * self.opts.excal_hp:
            return False
        fmask = self.fountains(lv)
        if not fmask.any():
            return False
        it = self.dippable_cursed()
        if it is not None:
            return self.dip_at_fountain(lv, fmask, it.letter, "fountain_uncurse")
        if int(self.last_bl[nh.NLE_BL_ALIGN]) == 1:
            return False
        it = self.junk_to_dip()
        if it is None or self.demon_win_prob() <= DEMON_WIN:
            return False
        return self.dip_at_fountain(lv, fmask, it.letter, "fountain_wish")
