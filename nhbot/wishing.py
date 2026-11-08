"""Going after wishes (what to wish for: equipment.answer_wish, whatever grants the wish).

Lamps: a lamp not known to be an oil lamp or cursed is rubbed with nothing threatening us (#rub wields it; the
weapon is wielded back after, or at once when a threat shows up). apply.c dorub: a magic lamp releases its
djinni in 1/3 of rubs (potion.c djinni_from_bottle: a wish 80% blessed / 20% uncursed / 5% cursed -- a known
cursed lamp is left alone: its djinni is hostile 80%), "You see a puff of smoke." in 1/3 (only a magic lamp
says it), "Nothing happens." in 1/3; an oil lamp only ever says "Nothing happens.", so after LAMP_NOTHING of
those in a row with no smoke the lamp is taken for an oil lamp.

A wand of wishing (by name, or the only type its shop price allows) is zapped with nothing threatening us until
"Nothing happens."
"""
import re
from collections import Counter

import nle.nethack as nh

from nhbot.items import base_name

LAMP_NOTHING = 6                  # magic lamp: (1/3)^6 = 0.14% to say "Nothing happens." six times in a row
LAMP_MAX_RUBS = 30                # magic lamp: (2/3)^30 < 0.001% to keep its djinni
LAMP_NAMES = ("lamp", "magic lamp")


class WishMixin:
    def wishing_init(self):
        self.lamp_seen = Counter()       # lamp letter -> "Nothing happens." in a row
        self.lamp_rubs = Counter()       # lamp letter -> rubs
        self.lamp_magic = set()          # lamp letters that showed smoke
        self.lamp_done = set()           # letters of lamps taken for oil lamps (or emptied)
        self.rub_back = None             # (weapon letter or None,) while a lamp is wielded for rubbing
        self.wish_stats = Counter()

    # ------------------------------------------------------------------ what we keep
    def is_lamp(self, it):
        return it.ocls == nh.TOOL_CLASS and base_name(it.text)[2] in LAMP_NAMES

    def wish_needed(self, it):
        """carry.needed: lamps still to rub, wands of wishing."""
        if self.is_lamp(it):
            return it.letter not in self.lamp_done
        return self.is_wishing_wand(it)

    def is_wishing_wand(self, it):
        if it.ocls != nh.WAND_CLASS:
            return False
        if "wand of wishing" in it.text:
            return True
        post = self.type_posterior(it.text) if "wand of" not in it.text else None
        return bool(post) and set(post) == {"wishing"}

    # ------------------------------------------------------------------ lamps
    def lamp_to_rub(self):
        return next((it for it in self.items() if self.is_lamp(it) and it.letter not in self.lamp_done
                     and not it.cursed and not it.unpaid), None)

    def lamp_step(self):
        """Nothing threatening us (the caller checks): rub the next lamp, or wield the weapon back when done.
        True if it used the turn."""
        if self.polyd or self.handless():
            return False
        lamp = self.lamp_to_rub()
        if lamp is None:
            return self.rub_rewield()
        if self.rub_back is None:
            cur = next((it for it in self.items() if it.wielded), None)
            if cur is not None and cur.cursed:
                return False                     # a welded weapon: the lamp can't be wielded
            self.rub_back = (cur.letter if cur is not None else None,)
        self.cur_act = "wish"
        seq0 = self.msg_seq
        self.press(int(nh.Command.RUB), expect_prompt=True)
        if not (self.obs["misc"][0] and "rub" in self.message().lower()):
            self.settle()
            self.lamp_done.add(lamp.letter)
            return True
        self.press(lamp.letter)
        msgs = self.text_since(seq0)
        self.wish_stats["rubs"] += 1
        self.lamp_rubs[lamp.letter] += 1
        if "emerges" in msgs or "acrid fumes" in msgs or "turns out to be empty" in msgs:
            self.lamp_done.add(lamp.letter)      # the djinni is out ("In a cloud of smoke ..."): an oil lamp now
            self.wish_stats["djinni"] += 1
        elif "puff of smoke" in msgs or "You smell smoke" in msgs:
            self.lamp_magic.add(lamp.letter)
            self.lamp_seen[lamp.letter] = 0
            self.wish_stats["smoke"] += 1
        elif self.lamp_rubs[lamp.letter] >= LAMP_MAX_RUBS:
            self.lamp_done.add(lamp.letter)      # (2/3)^LAMP_MAX_RUBS: a magic lamp keeps its djinni this long
            self.wish_stats["gave_up"] += 1
        elif "Nothing happens" in msgs:
            self.lamp_seen[lamp.letter] += 1
            if self.lamp_seen[lamp.letter] >= LAMP_NOTHING and lamp.letter not in self.lamp_magic:
                self.lamp_done.add(lamp.letter)
                self.wish_stats["oil_lamp"] += 1
        elif not any(it.letter == lamp.letter and it.wielded for it in self.items()):
            self.lamp_done.add(lamp.letter)      # couldn't wield it
            self.wish_stats["rub_failed"] += 1
        return True

    def rub_rewield(self):
        """Wield back the weapon a lamp displaced. True if it used the turn."""
        if self.rub_back is None:
            return False
        letter = self.rub_back[0]
        self.rub_back = None
        if letter is None or any(it.letter == letter and it.wielded for it in self.items()):
            return False
        if not any(it.letter == letter for it in self.items()):
            return False
        self.cur_act = "wield"
        self.wield(letter)
        return True

    # ------------------------------------------------------------------ wand of wishing
    def wishwand_step(self):
        """Nothing threatening us: zap a wand of wishing (equipment.answer_wish answers). True if it acted."""
        wand = next((it for it in self.items() if self.is_wishing_wand(it) and not self.wand_spent(it)), None)
        if wand is None or self.polyd or self.handless():
            return False
        self.cur_act = "wish"
        seq0 = self.msg_seq
        if not self.ask("z", "zap"):
            return False
        self.press(wand.letter)                 # settle answers the wish
        msgs = self.text_since(seq0)
        self.wish_stats["wand_zaps"] += 1
        self.note_wand_use(wand, msgs)                   # charges.py
        if not re.search(r"wish", msgs):
            self.wand_rec(wand)["empty"] = True
        return True
