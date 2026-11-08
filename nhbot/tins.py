"""Tins: pick them up, and open them with nothing threatening us: with the alternate weapon if it
is a dagger or knife (3 turns; swapped in with 'x' and back after), else with what we wield (eat.c: 10 +
rn2(1 + 500 / (Dex + Str)) turns, ~10-26 for a Valkyrie). Opened, the game says what is inside before asking
'Eat it?': spinach always, meat by the corpse rules without the poison / acid ones (eat.c consume_tin skips
eatcorpse(): no poison or acid damage, the intrinsics still come; survival.corpse_ok tin=True).
Satiated is fine while the estimated nutrition (survival.nutrition) is under SATIATED_MAX, and the contents
can't take it to 2000 (choking: eat.c lesshungry).
The variety ("You consume deep fried ...") is fixed when the tin is made but shown only once eaten. Its
aftermath is waited out on the spot while nothing threatens us:
  greasy (french / deep / stir fried)  Glib 5..15 turns: what we wield slips to the floor every turn
                                       (do_wear.c glibr); nothing is wielded or swapped in meanwhile (step_weapon),
                                       then the slipped weapon is picked back up and wielded again
  rotten                               vomiting 10..24 turns: confused, then stunned, then 2 helpless turns
                                       (timeout.c vomiting_dialogue)
"""
import re
from collections import Counter

import numpy as np
import nle.nethack as nh

from nhbot.consts import SATIATED
from nhbot.items import base_name
from nhbot.monsters import PM_BY_NAME
from nhbot.weapons import OPENERS

MAX_TINS = 4
SATIATED_MAX = 1500              # open a tin while Satiated only below this estimated nutrition
CHOKE = 2000
TIN_NUTRITION = {"spinach": 600}  # meat: up to 500 (pureed), counted as that
SMELL_RE = re.compile(r"It smells like (?:an? )?([a-zA-Z' -]+?)\.")
VARIETY_NUT = {"rotten": -20, "homemade": 50, "soup made from": 20, "french fried": 40, "pickled": 40,
               "boiled": 50, "smoked": 50, "dried": 55, "deep fried": 60, "szechuan": 70, "broiled": 80,
               "stir fried": 80, "sauteed": 95, "candied": 100, "pureed": 500}   # eat.c tintxts (rotten: the vomit)
GREASY = {"french fried", "deep fried", "stir fried"}
CONSUME_RE = re.compile(r"You consume (" + "|".join(sorted(VARIETY_NUT, key=len, reverse=True)) + r") ")
GLIB_TURNS = 16                  # make_glib(rn1(11, 5)): 5..15
VOMIT_TURNS = 25                 # make_vomiting(rn1(15, 10)): 10..24
RECOVER_TURNS = 300              # give up on a slipped weapon this long after the slip


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


class TinState:
    """State of opening and eating tins (TinMixin)."""
    def __init__(self):
        self.stats = Counter()
        self.eaten_by = Counter()
        self.glib_until = -1             # turn: our fingers are slippery until then
        self.vomit_until = -1            # turn: vomiting until then
        self.slipped = None              # (level key, square, name, turn) of the weapon the grease made us drop


class TinMixin:
    def tins_init(self):
        self.tin = TinState()

    def tin_glib(self):
        return self.turn() < self.tin.glib_until

    def tin_wait_step(self, lv):
        """No threat in view (the caller checks): wait out the slippery fingers / the vomiting of a tin, then
        pick up the weapon that slipped and wield it again. True if it used the turn."""
        if self.turn() < max(self.tin.glib_until, self.tin.vomit_until):
            self.cur_act = "tin_wait"
            self.tin.stats["wait"] += 1
            self.press("s")
            return True
        if self.tin.slipped is None:
            return False
        key, sq, name, t0 = self.tin.slipped
        mine = next((it for it in self.items() if base_name(it.text)[2] == name and not it.on_body), None)
        if mine is not None:
            self.tin.slipped = None
            if any(it.wielded for it in self.items()):
                return False
            self.tin.stats["rewielded"] += 1
            self.cur_act = "tin"
            self.wield(mine.letter)                     # the swapped state again: swap_back still applies
            return True
        if key != lv.key or self.turn() > t0 + RECOVER_TURNS:
            self.tin.slipped = None
            self.tin.stats["slip_lost"] += 1
            return self.swap_back("tin")
        if self.pos() != sq:
            mask = np.zeros(lv.under.shape, dtype=bool)
            mask[sq] = True
            if self.walk_to(lv, mask, max_cost=200, act="tin")[0] == "moved":
                return True
            self.tin.slipped = None
            self.tin.stats["slip_lost"] += 1
            return self.swap_back("tin")
        self.cur_act = "tin"
        self.pickup(lambda t: base_name(t)[2] == name and "for sale" not in t, "tin")
        if not any(base_name(it.text)[2] == name for it in self.items()):
            self.tin.slipped = None                     # not here after all
            self.tin.stats["slip_lost"] += 1
        return True

    def tin_letters(self):
        return [it.letter for it in self.items() if it.ocls == nh.FOOD_CLASS and re.search(r"\btins?\b", it.text)]

    def tins_carried(self):
        return sum(base_name(it.text)[0] for it in self.items()
                   if it.ocls == nh.FOOD_CLASS and re.search(r"\btins?\b", it.text))

    def tin_step(self, lv):
        """No threat in view (the caller checks): open and maybe eat one tin. True if it used the turn."""
        if not self.tin_letters() or (self.bl(nh.NLE_BL_HUNGER) <= SATIATED and self.surv.nutrition >= SATIATED_MAX) \
                or int(self.last_bl[nh.NLE_BL_CONDITION]) & (nh.BL_MASK_HALLU | nh.BL_MASK_CONF | nh.BL_MASK_STUN):
            return self.swap_back("tin")                 # done (or can't now): the main weapon back
        wielded = next((it for it in self.items() if it.wielded), None)
        if not (wielded is not None and any(w in base_name(wielded.text)[2] for w in OPENERS)) \
                and self.dagger_alternate() is not None:
            self.swap_in("tin")
            return True
        letter = self.tin_letters()[0]
        self.cur_act = "tin"
        seq0 = self.msg_seq
        if not self.eat_prompt():
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
                if ok and self.surv.nutrition + gain >= CHOKE:
                    ok = False
                    self.tin.stats["too_full"] += 1
                self.tin.stats["eaten" if ok else "refused"] += 1
                self.tin.eaten_by[what] += ok
                wielded = next((it for it in self.items() if it.wielded), None)
                seq1 = self.msg_seq
                self.press("y" if ok else "n")
                if ok:
                    self.tin_eaten(what, gain, wielded, self.text_since(seq1))
                return True
            if "--more--" in self.tty_text().lower():
                self.raw_step(13)
                continue
            break
        self.settle()
        self.tin.stats["not_opened"] += 1              # interrupted, empty, or no prompt: try again later
        return True

    def tin_eaten(self, what, gain, wielded, text):
        """After 'y': the nutrition by the variety, and the aftermath to wait out."""
        m = CONSUME_RE.search(text)
        variety = m.group(1) if m else None
        if variety is not None:
            gain = VARIETY_NUT[variety]
            self.tin.stats["v_" + variety.replace(" ", "_")] += 1
        self.nutrition_add(gain)
        if variety == "rotten":
            self.tin.vomit_until = self.turn() + VOMIT_TURNS
        if variety in GREASY or "very slippery" in text:
            self.tin.glib_until = self.turn() + GLIB_TURNS
            if wielded is not None:
                self.tin.slipped = (self.level().key, self.pos(), base_name(wielded.text)[2], self.turn())
