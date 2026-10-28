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
        self.digs = 0
        self.dig_fail_levels = set()
        self.fled = {}                  # monster name -> turn it turned to flee
        self.ranger_bow = False
        self.ranger_out = False
        self.fires = 0
        self.role_setup_done = False
        self.prev_weapon = None
        self.dig_level = None

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
        if self.role == "Archeologist" and self.role_opts.get("arc_wield", False):
            it = self.find_inv(lambda c, s: c == nh.TOOL_CLASS and "pick-axe" in s)
            if it:
                self.wield(it[0])
                return True
        if self.role == "Ranger":
            alt = self.find_inv(lambda c, s: "alternate weapon" in s and any(l in s for l in LAUNCHERS))
            if alt:
                self.press("x")
                self.ranger_bow = True
                return True
        return False

    # ---------------------------------------------------------- Archeologist: dig down
    def can_dig(self, lv):
        if lv.key in self.dig_fail_levels or lv.shop[self.pos()]:
            return None
        if G.KIND[lv.under[self.pos()]] in (G.UPSTAIR, G.DOWNSTAIR):
            return None
        it = self.find_inv(lambda c, s: c == nh.TOOL_CLASS and ("pick-axe" in s or "mattock" in s))
        return it

    def dig_down(self, lv):
        if not self.role_opts.get("dig", False):
            return False
        if lv.search_turns < self.role_opts.get("dig_after", 300):
            return False
        it = self.can_dig(lv)
        if not it:
            return False
        key0 = lv.key
        cur = self.find_inv(lambda c, s: "weapon in hand" in s)
        if cur and "pick-axe" not in cur[1] and "mattock" not in cur[1]:
            self.prev_weapon = (cur[0], cur[1].replace(" (weapon in hand)", "").replace(" (weapon in hands)", ""))
        self.dig_level = key0
        self.press("a", expect_prompt=True)
        if "apply" not in self.message().lower():
            self.settle(); return False
        self.press(it[0], expect_prompt=True)
        m = self.message().lower()
        if "direction" not in m and "dig" not in m:
            self.settle()
            self.dig_fail_levels.add(key0)
            return True
        self.press(">")
        msgs = " ".join(t for _, t in list(self.messages)[-5:]).lower()
        if any(s in msgs for s in ("too hard to dig", "cannot dig", "can't dig", "not enough room",
                                   "stairs are too hard", "here is too hard")):
            self.dig_fail_levels.add(key0)
        self.digs += 1
        return True

    def rewield_after_dig(self, hostiles=()):
        """Applying a pick-axe wields it; go back to the trained weapon (e.g. +2 bullwhip)
        once we fell through (or must fight)."""
        if self.prev_weapon is None:
            return False
        if self.cur_key == self.dig_level and not hostiles and self.cur_key not in self.dig_fail_levels:
            return False
        cur = self.find_inv(lambda c, s: "weapon in hand" in s)
        if cur and ("pick-axe" in cur[1] or "mattock" in cur[1]):
            it = self.find_inv(lambda c, s: s == self.prev_weapon[1] or
                               (self.prev_weapon[1].split("(")[0].strip() in s and "weapon in hand" not in s))
            self.prev_weapon = None
            if it:
                self.wield(it[0])
                return True
        self.prev_weapon = None
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

    # ---------------------------------------------------------- Knight
    def knight_skip(self, name):
        if self.role != "Knight" or not self.role_opts.get("knight_flee", False):
            return False
        t = self.fled.get(name)
        return t is not None and self.turn() - t <= 10
