"""Tins (flag tins): pick them up, and open them with nothing threatening us: with the alternate weapon if it
is a dagger or knife (3 turns; swapped in with 'x' and back after), else with what we wield (eat.c: 10 +
rn2(1 + 500 / (Dex + Str)) turns, ~10-26 for a Valkyrie). Opened, the game says what is inside before asking
'Eat it?': spinach always, meat by the corpse rules without the poison / acid ones (eat.c consume_tin skips
eatcorpse(): no poison or acid damage, the intrinsics still come; survival.corpse_ok tin=True).
Satiated is fine while the estimated nutrition (survival.nutrition) is under SATIATED_MAX, and the contents
can't take it to 2000 (choking: eat.c lesshungry).
"""
import re
from collections import Counter

import nle.nethack as nh

from nhbot.consts import SATIATED
from nhbot.items import base_name
from nhbot.monsters import PM_BY_NAME

OPENERS = ("dagger", "knife", "stiletto", "athame", "crysknife")
MAX_TINS = 4
SATIATED_MAX = 1500              # open a tin while Satiated only below this estimated nutrition
CHOKE = 2000
TIN_NUTRITION = {"spinach": 600}  # meat: up to 500 (pureed), counted as that
SMELL_RE = re.compile(r"It smells like (?:an? )?([a-zA-Z' -]+?)\.")


def _plurals(name):
    """objnam.c makeplural, the cases monster names need."""
    out = {name + "s"}
    for a, b in (("man", "men"), ("mouse", "mice"), ("louse", "lice"), ("wolf", "wolves"), ("elf", "elves"),
                 ("dwarf", "dwarves"), ("ox", "oxen"), ("foot", "feet"), ("tooth", "teeth"), ("child", "children")):
        if name.endswith(a):
            out.add(name[:-len(a)] + b)
    if re.search(r"(s|x|z|ch|sh)$", name):
        out.add(name + "es")
    if re.search(r"[^aeiou]y$", name):
        out.add(name[:-1] + "ies")
    if name.endswith("us"):
        out.add(name[:-2] + "i")
    return out


SINGULAR = {}
for _n in PM_BY_NAME:
    SINGULAR[_n] = _n
    for _p in _plurals(_n):
        SINGULAR.setdefault(_p, _n)


class TinMixin:
    def tins_init(self):
        self.tin_swapped = False         # we swapped the alternate weapon in to open a tin
        self.tin_stats = Counter()
        self.tin_eaten_by = Counter()

    def tin_letters(self):
        return [it.letter for it in self.items() if it.ocls == nh.FOOD_CLASS and re.search(r"\btins?\b", it.text)]

    def tins_carried(self):
        return sum(base_name(it.text)[0] for it in self.items()
                   if it.ocls == nh.FOOD_CLASS and re.search(r"\btins?\b", it.text))

    def tin_opener(self):
        """The alternate weapon, if it is a dagger / knife (not known cursed); else None."""
        alt = next((it for it in self.items() if it.alternate), None)
        if alt is None or alt.cursed or not any(w in base_name(alt.text)[2] for w in OPENERS):
            return None
        return alt

    def tin_swap_back(self):
        """Back to the main weapon (done with tins, or a threat in view). True if it used the turn."""
        if not self.tin_swapped:
            return False
        self.tin_swapped = False
        self.cur_act = "tin"
        self.press("x")
        return True

    def tin_step(self, lv):
        """No threat in view (the caller checks): open and maybe eat one tin. True if it used the turn."""
        if not self.opts.tins:
            return False
        if not self.tin_letters() or (self.bl(nh.NLE_BL_HUNGER) <= SATIATED and self.nutrition >= SATIATED_MAX) \
                or int(self.last_bl[nh.NLE_BL_CONDITION]) & (nh.BL_MASK_HALLU | nh.BL_MASK_CONF | nh.BL_MASK_STUN):
            return self.tin_swap_back()                 # done (or can't now): the main weapon back
        wielded = next((it for it in self.items() if it.wielded), None)
        if not (wielded is not None and any(w in base_name(wielded.text)[2] for w in OPENERS)) \
                and self.tin_opener() is not None:
            self.cur_act = "tin"
            self.tin_swapped = True
            self.press("x")
            return True
        letter = self.tin_letters()[0]
        self.cur_act = "tin"
        seq0 = self.msg_seq
        self.press("e", expect_prompt=True)
        for _ in range(3):
            m = self.message().lower()
            if self.obs["misc"][0] and "here" in m and "eat" in m:
                self.press("n", expect_prompt=True)      # something on the floor here: not that
                continue
            break
        if "what do you want to eat" not in self.message().lower():
            self.settle()
            return True
        self.press(letter, expect_prompt=True)
        for _ in range(6):
            if self.obs["misc"][0] and "eat it" in self.message().lower():
                text = self.text_since(seq0)
                sm = SMELL_RE.search(text)
                if "spinach" in text:
                    ok, what = True, "spinach"
                elif sm:
                    what = SINGULAR.get(sm.group(1).strip(), sm.group(1).strip())   # "It smells like geckos."
                    ok = self.corpse_ok(what, tin=True)
                else:
                    ok, what = False, "?"
                gain = TIN_NUTRITION.get(what, 500)
                if ok and self.nutrition + gain >= CHOKE:
                    ok = False
                    self.tin_stats["too_full"] += 1
                if ok:
                    self.nutrition_add(gain)
                self.tin_stats["eaten" if ok else "refused"] += 1
                self.tin_eaten_by[what] += ok
                self.press("y" if ok else "n")
                return True
            if "--more--" in self.tty_text().lower():
                self.raw_step(13)
                continue
            break
        self.settle()
        self.tin_stats["not_opened"] += 1              # interrupted, empty, or no prompt: try again later
        return True
