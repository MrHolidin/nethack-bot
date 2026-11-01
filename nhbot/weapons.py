"""Wielding: remember the starting weapon, wield the best one we carry (Excalibur > long sword /
katana > anything else), never a known-cursed one."""
import re

import nle.nethack as nh


class WeaponsMixin:
    def weapons_init(self):
        self.main_weapon = None
        self.rewields = 0
        self._wield_tried = set()      # wield candidates already tried

    def wield(self, letter):
        if self.ask("w", "wield"):
            self.press(letter)

    def weapon_check(self):
        """Remember the starting weapon; re-wield it if we got it back after a theft."""
        inv = self.inventory()
        wielded = [it.text for it in self.items() if it.wielded]
        if self.main_weapon is None:
            if wielded:
                base = re.sub(r"\s*\(.*?\)", "", wielded[0])
                base = re.sub(r"^(a|an|the|\d+)\s+", "", base)
                base = re.sub(r"\b(uncursed|cursed|blessed|rustproof|[+-]\d+)\s+", "", base).strip()
                self.main_weapon = base
            return False
        return self.weapon_upgrade(inv)

    def weapon_rank(self, s):
        """weapons: Excalibur > the two long-sword-skill blades > anything else. Lawful: katana < long sword
        (a long sword can still become Excalibur); others: long sword < katana. Ties: known enchantment."""
        m = re.search(r"(?:^|\s)([+-]\d+) ", s)
        ench = int(m.group(1)) if m else 0
        lawful = int(self.last_bl[nh.NLE_BL_ALIGN]) == 1
        if "Excalibur" in s:
            return (3, ench)
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
        t0, seq0 = self.turn(), self.msg_seq
        self.wield(l)
        recent = " ".join([t for tt, t in list(self.messages)[-4:] if tt >= t0] + [self.message()])
        if self.audit("wield", recent, seq0, lambda s: "Don't be ridiculous" in s):
            self.polyd = True                # a form we failed to notice; retry after "You return to ... form"
            return True
        self._wield_tried = tried | {(l, s)}
        self.rewields += 1
        return True
