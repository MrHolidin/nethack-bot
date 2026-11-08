"""Wielding: remember the starting weapon, wield the best one we carry (Excalibur > long sword /
katana > anything else), never a known-cursed one."""
import re

import nle.nethack as nh

from nhbot.items import base_name, erosion


OPENERS = ("dagger", "knife", "stiletto", "athame", "crysknife")   # opens tins, forces locks (a blade we can lose)
# missiles we throw, by a word of the name -- a crysknife too, being named "knife" (combat.throwables, kept by
# carry.needed); pickup.MISSILE_TYPES, the types we pick up to throw, leaves it out
THROWABLE = ("dagger", "dart", "knife", "shuriken", "javelin", "spear")


class WeaponsMixin:
    def weapons_init(self):
        self.main_weapon = None
        self.rewields = 0
        self._wield_tried = set()      # wield candidates already tried
        self.swapped_for = None        # "tin" / "box": a dagger swapped in for that job
        self.swap_main = None          # the letter to wield back after it ('w'); None: 'x' swaps back
        self.swap_welded = 0           # swap_in put a cursed dagger in our hands

    def dagger_alternate(self):
        """The alternate weapon, if it is a dagger / knife (not known cursed); else None."""
        alt = next((it for it in self.items() if it.alternate), None)
        if alt is None or alt.cursed or not any(w in base_name(alt.text)[2] for w in OPENERS):
            return None
        return alt

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
        """Wield the best weapon we carry (weapon_upgrade). The first call with a weapon in hand only notes it
        (main_weapon: its base name); before that nothing is wielded here."""
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
