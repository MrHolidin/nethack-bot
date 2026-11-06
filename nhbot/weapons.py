"""Wielding: remember the starting weapon, wield the best one we carry (Excalibur > long sword /
katana > anything else), never a known-cursed one."""
import re
from collections import Counter

import nle.nethack as nh

from nhbot.items import base_name, erosion
from nhbot.carry import WEAPON_NAME_OF
from nhbot.weapondice import WEAPON_DICE


OPENERS = ("dagger", "knife", "stiletto", "athame", "crysknife")   # opens tins, forces locks (a blade we can lose)
UNCURSED_RE = re.compile(r"\b(?:uncursed|blessed)\b")
NOT_MELEE_RE = re.compile(r"\b(arrows?|bolts?|ya|darts?|shuriken|bows?|crossbows?|yumi|slings?|boomerangs?)\b")
# objects.c bimanual weapons: not with the shield the Valkyrie keeps on
TWO_HANDED = {"two-handed sword", "tsurugi", "battle-axe", "dwarvish mattock", "quarterstaff", "partisan", "ranseur",
              "spetum", "glaive", "halberd", "bardiche", "voulge", "fauchard", "guisarme", "bill-guisarme",
              "lucern hammer", "bec de corbin"}
DAGGER_SKILL = {"dagger", "elven dagger", "orcish dagger", "silver dagger", "athame"}     # P_DAGGER
# weapon.c weapon_dam_bonus / weapon_hit_bonus by skill: unskilled, basic, skilled, expert
SKILL_DMG = (-2, 0, 1, 2)
SKILL_HIT = (-4, 0, 2, 3)
SKILL_RE = re.compile(r"You are now (?:more|most) skilled in (.+?)\.")


class WeaponsMixin:
    def weapons_init(self):
        self.main_weapon = None
        self.rewields = 0
        self._wield_tried = set()      # wield candidates already tried
        self.swapped_for = None        # "tin" / "box": a dagger swapped in for that job
        self.swap_main = None          # the letter to wield back after it ('w'); None: 'x' swaps back
        self.swap_welded = 0           # swap_in put a cursed dagger in our hands
        self.skill_lvl = {"long sword": 1, "dagger": 1}   # 0 unskilled .. 3 expert: a Valkyrie starts at Basic
        self.backup_fail = set()       # backup_weapon: (letter, text) that would not be wielded
        self.backup_stats = Counter()

    def dagger_alternate(self):
        """The alternate weapon, if it is a dagger / knife (not known cursed); else None."""
        alt = next((it for it in self.items() if it.alternate), None)
        if alt is None or alt.cursed or not any(w in base_name(alt.text)[2] for w in OPENERS):
            return None
        return alt

    def opener_daggers(self):
        """Daggers / knives we could put in our hands for a job, best first: known uncursed (or blessed) ones and
        the alternate weapon, then those of unknown curse status; never a known-cursed one (it would weld)."""
        cands = [it for it in self.items() if it.ocls == nh.WEAPON_CLASS and not it.cursed and not it.wielded
                 and any(w in base_name(it.text)[2] for w in OPENERS)]
        return sorted(cands, key=lambda it: not (it.alternate or UNCURSED_RE.search(it.text)))

    def swap_in(self, job, it=None):
        """A dagger into our hands for job (swap_back undoes it): the alternate weapon with 'x', another one
        with 'w' (the main weapon is wielded back after)."""
        self.swapped_for = job
        self.cur_act = job
        if it is None or it.alternate:
            self.swap_main = None
            self.press("x")
            return
        main = next((i for i in self.items() if i.wielded), None)
        self.swap_main = main.letter if main is not None else None
        seq0 = self.msg_seq
        self.wield(it.letter)
        if "welded" in self.text_since(seq0):
            self.swap_welded += 1             # a cursed one: stuck with it until uncursed (weapon_upgrade can't)
            self.swapped_for = None

    def swap_back(self, job=None):
        """Back to the main weapon after a swap_in (for job, or any). True if it used the turn."""
        if self.swapped_for is None or (job is not None and self.swapped_for != job):
            return False
        self.cur_act = self.swapped_for
        self.swapped_for = None
        if self.swap_main is None:
            self.press("x")
        elif any(it.letter == self.swap_main for it in self.items()):
            self.wield(self.swap_main)
        return True

    def wield(self, letter):
        if self.ask("w", "wield"):
            self.press(letter)

    def weapon_check(self):
        """Remember the starting weapon; re-wield it if we got it back after a theft."""
        inv = self.inventory()
        wielded = [it.text for it in self.items() if it.wielded]
        if self.main_weapon is None:
            if wielded:
                self.main_weapon = base_name(wielded[0])[2]
            return False
        return self.weapon_upgrade(inv)

    def weapon_rank(self, s):
        """weapons: Excalibur > the two long-sword-skill blades > anything else. Lawful: katana < long sword
        (a long sword can still become Excalibur); others: long sword < katana. Ties: known enchantment minus
        the erosion (weapon.c dmgval takes greatest_erosion off the damage)."""
        m = re.search(r"(?:^|\s)([+-]\d+) ", s)
        ench = int(m.group(1)) if m else 0
        ench -= erosion(s)
        lawful = int(self.last_bl[nh.NLE_BL_ALIGN]) == 1
        if "Excalibur" in s:
            return (3, ench)
        if self.opts.sacrifice and "Mjollnir" in s and int(self.last_bl[nh.NLE_BL_ALIGN]) == 0:
            return (3, ench)                 # sacrifice: the neutral Valkyrie's gift (war hammer: Expert)
        if re.search(r"\blong swords?\b", s):
            return (2 if lawful else 1, ench)
        if re.search(r"\bkatanas?\b", s) or (re.search(r"\bsamurai swords?\b", s) and "long samurai" not in s):
            return (1 if lawful else 2, ench)
        return (0, ench)

    def msg_weapons(self, m):
        mm = SKILL_RE.search(m)
        if mm:
            k = "dagger" if mm.group(1) in DAGGER_SKILL else mm.group(1)
            self.skill_lvl[k] = min(3, self.skill_lvl.get(k, 0) + 1)

    def weapon_est(self, text):
        """What a weapon does to a small monster a swing: weapon.c dmgval -- rnd(small die) + enchantment - its
        erosion, at least 1 -- plus the skill's damage bonus and a quarter of its to-hit bonus and of the
        weapon's own (weapon_hit_bonus). None: not a one-handed melee weapon we know."""
        if NOT_MELEE_RE.search(text) or "Excalibur" in text:
            return None
        _, ench, name = base_name(text)
        name = WEAPON_NAME_OF.get(name, name)
        if name.endswith("s") and name not in WEAPON_DICE:
            name = name[:-1]
        if name not in WEAPON_DICE or name in TWO_HANDED:
            return None
        die, _, hitbon = WEAPON_DICE[name]
        ench, eros = ench or 0, erosion(text)
        mean = sum(max(1, r + ench - eros) for r in range(1, die + 1)) / die
        lvl = self.skill_lvl.get("dagger" if name in DAGGER_SKILL else name, 0)
        return mean + SKILL_DMG[lvl] + 0.25 * SKILL_HIT[lvl] + 0.25 * hitbon

    def backup_weapon(self):
        """backup_weapon, lawful without Excalibur: the weapon that hits hardest now (weapon_est), when it is not
        the long sword -- the sword then only goes into the fountains (a dip rusts it: the fight that follows is
        fought with this one). None: the long sword is the best (no backup then)."""
        if not self.opts.backup_weapon or self.excalibur or int(self.last_bl[nh.NLE_BL_ALIGN]) != 1:
            return None
        sword = self.long_sword()
        items = self.items()
        cands = [(self.weapon_est(it.text), it) for it in items
                 if it.ocls == nh.WEAPON_CLASS and not it.cursed and (it.letter, it.text) not in self.backup_fail
                 and not re.search(r"\blong swords?\b", it.text)]
        cands = [(e, it) for e, it in cands if e is not None]
        if not cands:
            return None
        e, best = max(cands, key=lambda c: c[0])
        if sword is not None:
            se = self.weapon_est(sword[1])
            if se is not None and se >= e:
                return None
        return best

    def weapon_upgrade(self, inv):
        """Wield the best-ranked weapon we carry if it beats the wielded one (or nothing is wielded).
        Never a known-cursed one; never switch away from a cursed (welded) one; each candidate tried once."""
        if self.polyd or self.handless():
            return False                     # animal forms can't hold weapons ("Don't be ridiculous!")
        items = self.items()
        cur_it = next((it for it in items if it.wielded), None)
        cur = cur_it.text if cur_it else None
        if cur_it is not None and cur_it.cursed:
            return False
        bk = self.backup_weapon()
        if bk is not None:                   # backup_weapon: it, not the long sword, in our hands
            if cur_it is not None and cur_it.letter == bk.letter:
                return False
            self.cur_act = "wield"
            self.wield(bk.letter)
            if not any(it.wielded and it.letter == bk.letter for it in self.items()):
                self.backup_fail.add((bk.letter, bk.text))
            self.backup_stats["wield_backup"] += 1
            self.rewields += 1
            return True
        tried = self._wield_tried
        cands = [(self.weapon_rank(it.text), it.letter, it.text) for it in items
                 if it.ocls == nh.WEAPON_CLASS and not it.held and not it.cursed
                 and not re.search(r"\b(arrows?|bolts?|ya|darts?|shuriken|bows?|crossbows?|yumi|sling)\b", it.text)
                 and (it.letter, it.text) not in tried]
        if not cands:
            return False
        rank, l, s = max(cands, key=lambda x: x[0])
        if cur is not None and rank <= self.weapon_rank(cur):
            return False
        if cur is not None and rank[0] == 0:
            return False                     # only the long-sword-skill blades replace a wielded weapon
        self.cur_act = "wield"
        seq0 = self.msg_seq
        self.wield(l)
        if "Don't be ridiculous" in self.text_since(seq0):
            self.polyd = True                # a form we failed to notice; retry after "You return to ... form"
            return True
        self._wield_tried = tried | {(l, s)}
        self.rewields += 1
        return True
