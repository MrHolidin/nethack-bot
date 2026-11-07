"""Wielding: remember the starting weapon, wield the best one we carry (Excalibur > long sword /
katana > anything else), never a known-cursed one."""
import re
from collections import Counter

import numpy as np
import nle.nethack as nh

from nhbot.items import base_name, erosion
from nhbot.carry import WEAPON_GLYPH, WEAPON_NAME_OF
from nhbot.weapondice import WEAPON_DICE


OPENERS = ("dagger", "knife", "stiletto", "athame", "crysknife")   # opens tins, forces locks (a blade we can lose)
UNCURSED_RE = re.compile(r"\b(?:uncursed|blessed)\b")
NOT_MELEE_RE = re.compile(r"\b(arrows?|bolts?|ya|darts?|shuriken|bows?|crossbows?|yumi|slings?|boomerangs?)\b")
# objects.c bimanual weapons: not with the shield the Valkyrie keeps on
TWO_HANDED = {"two-handed sword", "tsurugi", "battle-axe", "dwarvish mattock", "quarterstaff", "partisan", "ranseur",
              "spetum", "glaive", "halberd", "bardiche", "voulge", "fauchard", "guisarme", "bill-guisarme",
              "lucern hammer", "bec de corbin"}
DAGGER_SKILL = {"dagger", "elven dagger", "orcish dagger", "silver dagger", "athame"}     # P_DAGGER
# objects.c oc_skill of the one-handed melee weapons, by the skill's name in weapon.c skill_names (the "You are now
# more skilled in ..." messages); a weapon not here is its own skill's name
WEAPON_SKILL = {**{n: "dagger" for n in DAGGER_SKILL},
                **{n: "knife" for n in ("knife", "stiletto", "scalpel", "crysknife", "worm tooth")},
                **{n: "short sword" for n in ("short sword", "elven short sword", "orcish short sword",
                                              "dwarvish short sword")},
                **{n: "broadsword" for n in ("broadsword", "elven broadsword", "runesword")},
                **{n: "spear" for n in ("spear", "elven spear", "orcish spear", "dwarvish spear", "silver spear")},
                "katana": "long sword", "silver saber": "saber", "war hammer": "hammer", "aklys": "club",
                "bullwhip": "whip", "rubber hose": "whip"}
BACKUP_SWAP_MARGIN = 0.05      # backup_weapon: a fight's P(win) the swap (a turn without a blow) must add (WIN_SIMS noise)
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
        self._backup_glyphs = (None, None)   # backup_weapon: (key, weapon glyphs worth a walk)

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
            k = WEAPON_SKILL.get(mm.group(1), mm.group(1))
            self.skill_lvl[k] = min(3, self.skill_lvl.get(k, 0) + 1)

    def weapon_skill(self, name):
        """Our skill level (0 unskilled / restricted .. 3 expert) with this weapon type."""
        return self.skill_lvl.get(WEAPON_SKILL.get(name, name), 0)

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
        return self.weapon_est_of(name, ench or 0, erosion(text))

    def weapon_est_of(self, name, ench, eros):
        if name not in WEAPON_DICE or name in TWO_HANDED:
            return None
        die, _, hitbon = WEAPON_DICE[name]
        mean = sum(max(1, r + ench - eros) for r in range(1, die + 1)) / die
        lvl = self.weapon_skill(name)
        return mean + SKILL_DMG[lvl] + 0.25 * SKILL_HIT[lvl] + 0.25 * hitbon

    def backup_on(self):
        return self.opts.backup_weapon and not self.excalibur and int(self.last_bl[nh.NLE_BL_ALIGN]) == 1

    def backup_best(self):
        """backup_weapon, lawful without Excalibur: (weapon_est, item) of the weapon we carry that hits hardest
        now, the long sword not counted -- kept (carry.needed) also while the sword beats it. None: no such."""
        if not self.backup_on():
            return None
        cands = [(self.weapon_est(it.text), it) for it in self.items()
                 if it.ocls == nh.WEAPON_CLASS and not it.cursed and (it.letter, it.text) not in self.backup_fail
                 and not re.search(r"\blong swords?\b", it.text)]
        cands = [(e, it) for e, it in cands if e is not None]
        return max(cands, key=lambda c: c[0]) if cands else None

    def backup_weapon(self):
        """backup_weapon: the backup_best weapon when it beats the long sword -- the one we fight with then; the
        sword only goes into the fountains (a dip rusts it). None: the long sword is the best (no backup then)."""
        best = self.backup_best()
        if best is None:
            return None
        e, it = best
        sword = self.long_sword()
        if sword is not None:
            se = self.weapon_est(sword[1])
            if se is not None and se >= e:
                return None
        return it

    def backup_wants(self, text):
        """backup_weapon: a floor weapon (not a long sword) that would hit harder than our backup_best -- taken."""
        if not self.backup_on() or re.search(r"\blong swords?\b", text):
            return False
        e = self.weapon_est(text)
        best = self.backup_best()
        return e is not None and (best is None or e > best[0])

    def backup_glyphs(self):
        """backup_weapon: the weapon glyphs (types fixed: weapon appearances are not shuffled) that backup_wants
        at +0, not eroded -- explore goals."""
        best = self.backup_best() if self.backup_on() else None
        key = (self.backup_on(), best[0] if best else None, tuple(sorted(self.skill_lvl.items())))
        if self._backup_glyphs[0] != key:
            mask = np.zeros(nh.MAX_GLYPH, dtype=bool)
            if key[0]:
                for g in np.flatnonzero(WEAPON_GLYPH):
                    name = nh.OBJ_NAME(nh.objclass(nh.glyph_to_obj(int(g))))
                    e = self.weapon_est_of(name, 0, 0) if name != "long sword" else None
                    mask[g] = e is not None and (best is None or e > best[0])
            self._backup_glyphs = (key, mask)
        return self._backup_glyphs[1]

    def backup_fight_step(self, hostiles):
        """backup_weapon: in a fight with the long sword (or another) in hand while the backup hits harder (the
        dip that just rusted the sword brought out what we fight): the swap, if the fight's P(win) with it after
        a turn without a blow beats that with the weapon in hand by BACKUP_SWAP_MARGIN. True if it used the turn."""
        bk = self.backup_weapon()
        if bk is None or self.polyd or self.handless():
            return False
        cur = next((it for it in self.items() if it.wielded), None)
        if cur is not None and (cur.letter == bk.letter or cur.cursed):
            return False
        stay = self.win_prob(hostiles, weapon=cur)
        swap = self.win_prob(hostiles, weapon=bk, opening=lambda rng, alive_at, apply: (0, 0, None))
        if swap < stay + BACKUP_SWAP_MARGIN:
            self.backup_stats["fight_stay"] += 1
            return False
        self.backup_stats["fight_swap"] += 1
        self.cur_act = "wield"
        self.wield(bk.letter)
        if not any(it.wielded and it.letter == bk.letter for it in self.items()):
            self.backup_fail.add((bk.letter, bk.text))
        self.rewields += 1
        return True

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
