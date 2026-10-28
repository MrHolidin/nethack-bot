"""Character development and role abilities (only identified items / known spells).

  * #enhance whenever the game says a skill can be advanced.
  * keep the pet: before descending, wait (a few turns) for a nearby pet to come adjacent.
  * spells: force bolt at hostiles (adjacent or in line), healing on self when hurt.
  * identified healing potions when HP is low and prayer is unavailable.
  * identified scroll of magic mapping when a level runs out of places to explore.
  * missile roles (Tourist darts, Rogue daggers): throw at hostiles in a clear line.
"""
import re

import numpy as np
import nle.nethack as nh

import glyphs as G

ROWS, COLS = 21, 79
DIRS = {"k": (-1, 0), "j": (1, 0), "h": (0, -1), "l": (0, 1),
        "y": (-1, -1), "u": (-1, 1), "b": (1, -1), "n": (1, 1)}
DELTA2KEY = {v: k for k, v in DIRS.items()}
SPELL_COST = {"force bolt": 5, "healing": 5, "extra healing": 15}
HEAL_POTIONS = ("full healing", "extra healing", "healing")      # best first
MISSILE_ROLES = {"Tourist", "Rogue"}
USUALLY_PEACEFUL = {"shopkeeper", "watchman", "watch captain", "aligned priest", "high priest",
                    "guard", "Oracle", "prisoner"}


class AbilitiesMixin:
    def abilities_init(self):
        self.want_enhance = False
        self.enhances = 0
        self.spells = None             # name -> (letter, fail%)
        self.casts = {}
        self.quaffs = 0
        self.maps_read = 0
        self.pet_waits = 0
        self.pet_waited_total = 0
        self.missiles = 0
        self.far_peaceful = {}         # (level, glyph, pos) -> (peaceful, turn)

    # ---------------------------------------------------------- #enhance
    def enhance_step(self):
        if not self.want_enhance:
            return False
        self.want_enhance = False
        for _ in range(6):
            self.raw_step(229)                       # M-e: #enhance
            tty = self.tty_text()
            if "Pick a skill to advance" not in tty:
                self.raw_step(27); self.settle()
                break
            m = re.search(r"(?<![\w-])([a-zA-Z]) - +[a-z][a-z \-]+?\s+\[", tty)
            if not m:
                self.raw_step(27); self.settle()
                break
            self.raw_step(ord(m.group(1)))
            self.settle()
            self.enhances += 1
        return False                                 # takes no game time

    # ---------------------------------------------------------- spells
    def load_spells(self):
        self.spells = {}
        self.raw_step(ord("Z"))
        tty = self.tty_text()
        for m in re.finditer(r"([a-zA-Z]) - ([a-z ]+?)\s+\d+\s+\w+\s+(\d+)%", tty):
            self.spells[m.group(2).strip()] = (m.group(1), int(m.group(3)))
        self.raw_step(27)
        self.settle()

    def can_cast(self, name, max_fail=25):
        if self.spells is None:
            self.load_spells()
        if name not in self.spells:
            return False
        letter, fail = self.spells[name]
        return fail <= max_fail and self.bl(nh.NLE_BL_ENE) >= SPELL_COST.get(name, 5)

    def cast(self, name, dirkey):
        letter, _ = self.spells[name]
        self.raw_step(ord("Z"))
        if "Choose which spell" not in self.tty_text():
            self.settle(); return False
        self.press(letter, expect_prompt=True)
        if "direction" in self.message().lower():
            self.press(dirkey)
        else:
            self.settle()
        self.casts[name] = self.casts.get(name, 0) + 1
        return True

    # ---------------------------------------------------------- items
    def find_item(self, ocls, names):
        for n in names:
            for letter, c, s in self.inventory():
                if c == ocls and re.search(r"\b(potions?|scrolls?) of " + re.escape(n) + r"\b", s) \
                        and "cursed" not in s.replace("uncursed", ""):
                    return letter, n
        return None

    def heal_step(self, hostiles):
        hp, maxhp = self.bl(nh.NLE_BL_HP), self.bl(nh.NLE_BL_HPMAX)
        if hp * 3 >= maxhp or self.can_pray():
            return False
        if self.can_cast("healing", max_fail=20) and not hostiles:
            self.cur_act = "heal"
            return self.cast("healing", ".")
        it = self.find_item(nh.POTION_CLASS, HEAL_POTIONS)
        if it:
            self.cur_act = "heal"
            self.press("q", expect_prompt=True)
            if "drink" in self.message().lower():
                self.press(it[0])
                self.quaffs += 1
                return True
            self.settle()
        if self.can_cast("healing", max_fail=20):
            self.cur_act = "heal"
            return self.cast("healing", ".")
        return False

    def magic_map_step(self, lv):
        if getattr(lv, "mapped", False):
            return False
        it = self.find_item(nh.SCROLL_CLASS, ("magic mapping",))
        if not it:
            return False
        lv.mapped = True
        self.press("r", expect_prompt=True)
        if "read" in self.message().lower():
            self.press(it[0])
            self.maps_read += 1
            return True
        self.settle()
        return False

    # ---------------------------------------------------------- pet
    def pet_wait_before_stairs(self):
        """True if we should wait a turn on the stairs for a nearby pet."""
        g = self.obs["glyphs"]
        ys, xs = np.nonzero(G.KIND[g] == G.PET)
        if len(ys) == 0:
            self.pet_waits = 0
            return False
        y, x = self.pos()
        d = min(max(abs(a - y), abs(b - x)) for a, b in zip(ys, xs))
        far, turns = (12, 30) if (self.role == "Archeologist" and self.use_roles
                                  and self.role_opts.get("arc_pet", True)) else (7, 15)
        if d <= 1 or d > far or self.pet_waits >= turns:
            self.pet_waits = 0
            return False
        self.pet_waits += 1
        self.pet_waited_total += 1
        return True

    # ---------------------------------------------------------- ranged
    def describe_far(self, dirkey, d):
        self.raw_step(ord(";"))
        for _ in range(d):
            self.raw_step(ord(dirkey))
        desc = self.top_line()
        self.raw_step(27)
        self.settle()
        return desc

    def peaceful_far(self, lv, pos, dirkey, d):
        g = int(self.obs["glyphs"][pos])
        ck = (lv.key, g, pos)
        hit = self.far_peaceful.get(ck)
        if hit is not None and self.turn() - hit[1] <= 5:
            return hit[0]
        desc = self.describe_far(dirkey, d)
        res = ("peaceful" in desc) or ("tame" in desc) or not desc
        self.far_peaceful[ck] = (res, self.turn())
        return res

    def line_targets(self, lv, max_d=6):
        """Hostile-looking monsters in a clear straight line: [(dirkey, d, pos, step)]."""
        y, x = self.pos()
        g = self.obs["glyphs"]
        k_mem = G.KIND[lv.under]
        out = []
        for (dy, dx), key in DELTA2KEY.items():
            for i in range(1, max_d + 1):
                yy, xx = y + i * dy, x + i * dx
                if not (0 <= yy < ROWS and 0 <= xx < COLS):
                    break
                k = G.KIND[g[yy, xx]]
                if k == G.MONSTER:
                    name = G.monster_name(int(g[yy, xx]))
                    if name not in USUALLY_PEACEFUL and int(g[yy, xx]) not in lv.peaceful:
                        out.append((key, i, (yy, xx), (dy, dx), name))
                    break
                if k in (G.PET, G.BOULDER) or not G.PASSABLE[k_mem[yy, xx]] and k_mem[yy, xx] != G.UNKNOWN:
                    break
        return sorted(out, key=lambda t: t[1])

    def ranged_step(self, lv, hostiles):
        """Force bolt (if known) or missiles (missile roles). Returns True if acted."""
        use_bolt = self.can_cast("force bolt") if self.spells is not False else False
        use_missiles = self.role in MISSILE_ROLES and self.throwables()
        use_fire = self.use_roles and self.ranger_can_fire()
        if self.use_roles and self.ranger_check_ammo():
            return True
        if not (use_bolt or use_missiles or use_fire):
            return False
        for key, d, pos, (dy, dx), name in self.line_targets(lv):
            if name in ("floating eye",) and not use_missiles:
                continue
            if d == 1:
                if pos not in [p for p, _ in hostiles]:
                    continue                     # adjacent but peaceful/unchecked
                if self.use_roles and self.role == "Rogue" and not use_bolt:
                    continue                     # melee adjacent foes, throw only at range
            elif self.peaceful_far(lv, pos, key, d):
                continue
            y, x = self.pos()
            if use_bolt and self.use_roles and self.role_opts.get("bolt_conserve", True) \
                    and not self.worth_special(pos, name):
                if not (use_missiles or use_fire):
                    continue                     # melee weak stuff, keep energy for real threats
                use_bolt = False
            self.last_attack_target = pos
            self.cur_act = "fight"
            if use_bolt:
                return self.cast("force bolt", key)
            if use_fire:
                self.fire(key)
                return True
            ray = [(y + i * dy, x + i * dx) for i in range(1, 10)
                   if 0 <= y + i * dy < ROWS and 0 <= x + i * dx < COLS]
            self.missiles += 1
            self.throw(self.throwables()[0][0], key, ray)
            return True
        return False
