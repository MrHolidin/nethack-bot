"""Role-specific behaviour (strategy from the NetHack wiki role pages).

  Archeologist: wield the pick-axe (d6) instead of the bullwhip (d2); dig down instead of
                searching for hidden passages when a level has nothing left to explore.
  Ranger:       wield the launcher (bow/crossbow is the alternate weapon at start) and fire
                quivered missiles; pick them up again; fall back to the dagger when out.
  Knight:       do not melee a monster that just "turns to flee" (-1 alignment, "You caitiff!").
  Rogue:        throw daggers only at range >= 2, melee adjacent foes with the short sword.
"""
import re

import nle.nethack as nh

import glyphs as G

ROWS, COLS = 21, 79
LAUNCHERS = ("bow", "crossbow", "yumi")
AMMO = ("arrow", "crossbow bolt", "ya")


class RolesMixin:
    def roles_init(self):
        self.ranger_bow = False
        self.ranger_out = False
        self.fires = 0
        self.role_setup_done = False

    # ---------------------------------------------------------- helpers
    def find_inv(self, pred):
        for letter, ocls, s in self.inventory():
            if pred(ocls, s):
                return letter, s
        return None

    def wield(self, letter):
        self.press("w", expect_prompt=True)
        if "wield" in self.message().lower():
            self.press(letter)
        else:
            self.settle()

    def role_setup(self):
        """One-time start-of-game adjustments."""
        if self.role_setup_done:
            return False
        self.role_setup_done = True
        if self.role == "Ranger":
            alt = self.find_inv(lambda c, s: "alternate weapon" in s and any(l in s for l in LAUNCHERS))
            if alt:
                self.press("x")
                self.ranger_bow = True
                return True
        return False

    # ---------------------------------------------------------- Ranger: fire
    def ranger_can_fire(self):
        if self.role != "Ranger" or not self.ranger_bow or self.ranger_out:
            return False
        return any(any(a in s for a in AMMO) for _, c, s in self.inventory() if c == nh.WEAPON_CLASS
                   and "weapon in hand" not in s)

    def fire(self, key):
        self.press("f", expect_prompt=True)
        m = self.message().lower()
        if "what do you want to fire" in m or "what do you want to throw" in m:
            it = self.find_inv(lambda c, s: c == nh.WEAPON_CLASS and any(a in s for a in AMMO)
                               and "weapon in hand" not in s)
            if not it:
                self.raw_step(27); self.settle()
                self.ranger_out = True
                return False
            self.press(it[0], expect_prompt=True)
            m = self.message().lower()
        if "direction" in m:
            self.press(key)
        else:
            self.settle()
        self.fires += 1
        return True

    def ranger_check_ammo(self):
        """Out of missiles: switch back to the melee weapon."""
        if self.role == "Ranger" and self.ranger_bow and not self.ranger_can_fire():
            self.ranger_out = True
            self.ranger_bow = False
            self.press("x")
            return True
        return False


# =====================================================================================
# Class tactics v2 (wiki: Healer, Tourist, Wizard, Expensive camera, Wand of sleep pages)
# =====================================================================================
RAY_WANDS = ("sleep", "magic missile", "fire", "cold", "lightning")   # rays bounce off walls
BEAM_WANDS = ("striking",)                                            # no bounce
SAFE_RAY_DIST = 7          # ray range is 7..13: a wall >= 7 away can't bounce it back onto us


class ClassTacticsMixin:
    def class_init(self):
        self.zaps = 0
        self.flashes = 0
        self.early_quaffs = 0
        self.flashed = {}
        self.empty_wands = set()

    def opt(self, name, default=True):
        return self.role_opts.get(name, default)

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
        out += self.extra_attack_wands()
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
        if not self.opt("wands"):
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

    # ------------------------------------------------------------ Healer
    def healer_early_quaff(self):
        """Wiki: drink the starting extra healing at full HP for +2 (+5 blessed) max HP each."""
        if self.role != "Healer" or not self.opt("hea_xh"):
            return False
        if self.bl(nh.NLE_BL_HP) < self.bl(nh.NLE_BL_HPMAX) or self.turn() > 300:
            return False
        for letter, ocls, s in self.inventory():
            if ocls == nh.POTION_CLASS and "potion" in s and "extra healing" in s and " cursed" not in s:
                self.press("q", expect_prompt=True)
                if "drink" in self.message().lower():
                    self.press(letter)
                    self.early_quaffs += 1
                    return True
                self.settle()
                return False
        return False

    # ------------------------------------------------------------ Tourist camera
    def camera_step(self, lv, hostiles):
        if self.role != "Tourist" or not self.opt("camera") or hostiles:
            return False
        cam = None
        for letter, ocls, s in self.inventory():
            if "expensive camera" in s and not re.search(r"\(0:0\)", s):
                cam = letter
        if cam is None:
            return False
        for key, d, pos, (dy, dx), name in self.line_targets(lv, max_d=2):
            if d != 2 or not self.worth_special(pos, name):
                continue
            g = int(self.obs["glyphs"][pos])
            if self.turn() - self.flashed.get(g, -999) < 30:
                continue
            if self.peaceful_far(lv, pos, key, d):
                continue
            self.flashed[g] = self.turn()
            self.press("a", expect_prompt=True)
            if "apply" not in self.message().lower():
                self.settle(); return False
            self.press(cam, expect_prompt=True)
            if "direction" in self.message().lower():
                self.press(key)
            else:
                self.settle()
            self.flashes += 1
            self.cur_act = "fight"
            return True
        return False


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
        if self.excalibur or not self.use_roles or not self.role_opts.get("excal", True):
            return False
        if int(self.last_bl[nh.NLE_BL_ALIGN]) != 1:
            return False
        if self.bl(nh.NLE_BL_XP) < self.role_opts.get("excal_xl", 5):
            return False
        hp, maxhp = self.bl(nh.NLE_BL_HP), self.bl(nh.NLE_BL_HPMAX)
        if hp < maxhp * self.role_opts.get("excal_hp", 0.7):
            return False
        return self.long_sword() is not None

    def excal_holds(self, lv):
        """excal_hold: while the Excalibur errand is on (a usable fountain here, or one to walk back up to),
        exploration must not take the stairs down: a monster in view pauses the errand, and the explore
        fallback used to descend straight away, bouncing between the levels until the trips ran out."""
        if not self.role_opts.get("excal_hold", True) or lv.key[0] != 0 or not self.excal_eligible():
            return False
        hc = self.__dict__.setdefault("excal_hold_count", {})
        if hc.get(lv.key, 0) > 500:
            return False                           # held long enough here: let the level go
        hc[lv.key] = hc.get(lv.key, 0) + 1
        fm = lv.under == FOUNTAIN_GLYPH
        if lv.shop.any():
            fm = fm & ~lv.shop
        if fm.any() and lv.key not in self.excal_skip:
            return True
        if not self.role_opts.get("excal_travel", True) or self.excal_trips >= self.role_opts.get("excal_trips", 30):
            return False
        dl = lv.key[1]
        return any(k[0] == 0 and dl - self.role_opts.get("excal_up", 8) <= k[1] < dl and k not in self.excal_skip
                   and (l.under == FOUNTAIN_GLYPH).any() for k, l in self.levels.items())

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
        dist, prev, reached = self.dijkstra(lv, k_mem, k_live, p, (y, x), fmask, max_cost=self.role_opts.get("excal_cost", 2000))
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
        if not self.role_opts.get("excal_travel", True) or lv.key[0] != 0 or self.excal_trips >= self.role_opts.get("excal_trips", 30):
            return False
        dl = lv.key[1]
        targets = [k for k, l in self.levels.items()
                   if k[0] == 0 and dl - self.role_opts.get("excal_up", 8) <= k[1] < dl and k not in self.excal_skip
                   and (l.under == FOUNTAIN_GLYPH).any() and not (l.shop.any() and (l.under == FOUNTAIN_GLYPH)[l.shop].all())]
        if not targets:
            return False
        k_mem, k_live = self.kind_grid(lv)
        up = k_mem == G.UPSTAIR
        if not up.any():
            return False
        y, x = self.pos()
        if up[y, x]:
            cool = self.role_opts.get("excal_cool", 0)
            if cool and self.turn() - getattr(self, "excal_last_up", -10**9) < cool:
                return False                       # just bounced back down (a threat at the top?): later
            self.excal_last_up = self.turn()
            self.cur_act = "excal"
            self.excal_trips += 1
            self.press("<")
            return True
        p = self.passable_grid(lv, k_mem, k_live)
        dist, prev, reached = self.dijkstra(lv, k_mem, k_live, p, (y, x), up, max_cost=self.role_opts.get("excal_cost_up", 2000))
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
