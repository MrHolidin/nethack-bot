"""Reading scrolls that can only be good (read_good).

A scroll's appearance ("scroll labeled ZELGO MER") is random per game, its base price is fixed per type
(objects.c). Shop prices narrow an appearance down to the types with that base price (pricemem.py).

Read rule: an appearance whose possible types are all enchant weapon, enchant armor or remove curse -- never
harmful -- is read (and not sold). Everything else stays unread.
"""
import re

import nle.nethack as nh

GOOD_NAMES = ("scroll of enchant armor", "scroll of enchant weapon", "scroll of remove curse")
GOOD_TYPES = {"enchant armor", "enchant weapon", "remove curse"}


def cha_factor(cha):
    """(multiplier, divisor) from shk.c get_cost."""
    if cha > 18: return 1, 2
    if cha == 18: return 2, 3
    if cha >= 16: return 3, 4
    if cha <= 5: return 2, 1
    if cha <= 7: return 3, 2
    if cha <= 10: return 4, 3
    return 1, 1



class ScrollMixin:
    def scroll_init(self):
        self.scroll_stats = {"read": 0, "read_names": []}

    def sucker(self):
        """Visible dunce cap or a shirt with nothing over it: shopkeepers add 1/3."""
        worn = [it.text for it in self.items() if it.worn]
        if any("dunce cap" in s for s in worn):
            return True
        shirt = any("shirt" in s for s in worn)
        over = any(re.search(r"mail|armor|jacket|cloak|robe|apron|tunic|coat", s) for s in worn if "shirt" not in s)
        return shirt and not over

    def scroll_is_good(self, s):
        """Identified as one of GOOD_NAMES, or every type its shop prices allow is one of them."""
        if any(n in s for n in GOOD_NAMES):
            return True
        post = self.price_of_text(s) if "labeled" in s else None
        return bool(post) and set(post) <= GOOD_TYPES

    def read_good_scroll(self):
        cond = int(self.last_bl[nh.NLE_BL_CONDITION])
        if cond & (nh.BL_MASK_BLIND | nh.BL_MASK_CONF | nh.BL_MASK_STUN | nh.BL_MASK_HALLU):
            return False              # confused remove curse / enchant armor do other things
        inv = self.inventory()
        worn_ench = [int(m.group(1)) for it in self.items() if it.ocls == nh.ARMOR_CLASS and it.worn
                     for m in [re.search(r"([+-]\d+) ", it.text)] if m]
        for letter, c, s in inv:
            if c != nh.SCROLL_CLASS or not self.scroll_is_good(s):
                continue
            maybe_armor = "enchant armor" in s or "labeled" in s
            if maybe_armor and worn_ench and max(worn_ench) >= 4 and "remove curse" not in s:
                continue              # enchant armor on a +4 piece may evaporate it
            if "enchant weapon" in s and not any(it.wielded for it in self.items()):
                continue
            if not self.ask("r", "read"):
                return False
            self.press(letter)
            self.scroll_stats["read"] += 1
            self.scroll_stats["read_names"].append(s[:60])
            return True
        return False
