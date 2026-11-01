"""Wands (attack wands at worthy targets) and Excalibur.

Role-specific behaviour lives behind self.role checks; the bot currently plays Valkyries only.
"""
import re

import nle.nethack as nh

import glyphs as G

ROWS, COLS = 21, 79


class RolesMixin:
    def roles_init(self):
        pass

    def wield(self, letter):
        self.press("w", expect_prompt=True)
        if "wield" in self.message().lower():
            self.press(letter)
        else:
            self.settle()


# =====================================================================================
# Attack wands (wiki: Wand of sleep and the ray wand pages)
# =====================================================================================
RAY_WANDS = ("sleep", "magic missile", "fire", "cold", "lightning")   # rays bounce off walls
BEAM_WANDS = ("striking",)                                            # no bounce
SAFE_RAY_DIST = 7          # ray range is 7..13: a wall >= 7 away can't bounce it back onto us


class ClassTacticsMixin:
    def class_init(self):
        self.zaps = 0
        self.empty_wands = set()

    # ------------------------------------------------------------ danger of one monster
    def worth_special(self, pos, name):
        """Is this target worth a charge / energy / a flash?"""
        g = self.obs["glyphs"][pos]
        hp, maxhp = self.bl(nh.NLE_BL_HP), self.bl(nh.NLE_BL_HPMAX)
        if hp < maxhp * 0.5:
            return True
        return self.est_dmg(g, name) >= 2.0 or self.threat(g) >= 1

    # ------------------------------------------------------------ ray geometry
    def ray_safe(self, lv, dy, dx):
        """Distance from us to the first wall/unknown along the line, doors absorb rays."""
        y, x = self.pos()
        k_mem = G.KIND[lv.under]
        for i in range(1, SAFE_RAY_DIST + 1):
            yy, xx = y + i * dy, x + i * dx
            if not (0 <= yy < ROWS and 0 <= xx < COLS):
                return False
            k = k_mem[yy, xx]
            if k in (G.DOOR_OPEN, G.DOOR_CLOSED, G.DOORWAY):
                return True                      # doors absorb the ray
            if k in (G.WALL, G.UNKNOWN, G.BOULDER):
                return False
        return True

    # ------------------------------------------------------------ wands
    def attack_wands(self):
        out = []
        for letter, ocls, s in self.inventory():
            if ocls != nh.WAND_CLASS or letter in self.empty_wands:
                continue
            m = re.search(r"wand of ([a-z ]+?)(?: \(|$)", s)
            if not m:
                continue
            kind = m.group(1).strip()
            if re.search(r"\(\d+:0\)", s):
                continue
            if kind in RAY_WANDS or kind in BEAM_WANDS:
                out.append((letter, kind))
        prio = {"sleep": 0, "striking": 1, "magic missile": 2, "cold": 3, "fire": 4, "lightning": 5}
        return sorted(out, key=lambda t: prio.get(t[1], 9))

    def zap(self, letter, key):
        self.own_zap_turn = self.turn()           # a bouncing ray of ours is not an enemy shooter
        self.press("z", expect_prompt=True)
        if "zap" not in self.message().lower():
            self.settle(); return False
        self.press(letter, expect_prompt=True)
        m = self.message().lower()
        if "direction" in m:
            self.press(key)
        else:
            self.settle()
        msgs = " ".join(t for _, t in list(self.messages)[-3:])
        if "Nothing happens" in msgs or "You wrest" in msgs:
            self.empty_wands.add(letter)
        self.zaps += 1
        return True

    def wand_step(self, lv, hostiles):
        if not self.opts.wands:
            return False
        wands = self.attack_wands()
        if not wands:
            return False
        for key, d, pos, (dy, dx), name in self.line_targets(lv, max_d=6):
            if d == 1 and pos not in [p for p, _ in hostiles]:
                continue
            if not self.worth_special(pos, name):
                continue
            if d > 1 and self.peaceful_far(lv, pos, key, d):
                continue
            for letter, kind in wands:
                if kind == "sleep" and ("elf" in name or "zombie" in name or "Elvenking" in name):
                    continue                     # sleep resistant
                if kind in RAY_WANDS and not self.ray_safe(lv, -dy, -dx) and not self.ray_far_wall(lv, dy, dx):
                    continue
                self.cur_act = "fight"
                self.last_attack_target = pos
                return self.zap(letter, key)
        return False

    def ray_far_wall(self, lv, dy, dx):
        """Wall in the firing direction is far enough that a bounce cannot come back to us."""
        y, x = self.pos()
        k_mem = G.KIND[lv.under]
        for i in range(1, SAFE_RAY_DIST + 1):
            yy, xx = y + i * dy, x + i * dx
            if not (0 <= yy < ROWS and 0 <= xx < COLS):
                return False
            k = k_mem[yy, xx]
            if k in (G.DOOR_OPEN, G.DOOR_CLOSED, G.DOORWAY):
                return True
            if k in (G.WALL, G.UNKNOWN, G.BOULDER):
                return False
        return True


# =====================================================================================
# Excalibur (wiki "Excalibur"): lawful, XL >= 5, dip an unnamed long sword into a fountain;
# 1/6 per dip, the fountain disappears on success.
# =====================================================================================
import numpy as _np

FOUNTAIN_GLYPH = nh.GLYPH_CMAP_OFF + 31
FLOOR_GLYPH = nh.GLYPH_CMAP_OFF + 19


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
        if self.excalibur or not self.opts.use_roles or not self.opts.excal:
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
        if not self.opts.excal_travel or lv.key[0] != 0 or self.excal_trips >= self.opts.excal_trips:
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
