"""Wand charges: how often we used each wand we carry, which ones are spent, and P(the next zap has a charge).

NetHack 3.6.6 facts (mkobj.c, zap.c):
  charges      a new directional wand has rn1(5, 4) = 4..8 charges, uniformly; a non-directional one 11..15,
               wishing 1..3. Each zap or engraving uses one (zappable); shown as (r:c) only once identified.
  spent        "Nothing happens" (0 charges: 1 in 121 "You wrest one last charge" instead, then it is gone);
               engraving with it: "too worn out to engrave". (r:0) / (r:-1, cancelled) when the charges show.
A wand is known by its inventory letter: the text changes while it stays the same wand (the BUC learned on an
altar, the game identifying it), which used to make a spent wand look new. A different base name at that letter
(another wand picked up into it) starts a new record; only "unidentified look -> wand of X" counts as the same.
Wands a monster used before us may hold fewer charges than the prior says.
"""
import re

import nle.nethack as nh

from nhbot.items import WAND_SPENT_RE, base_name

CHARGES_RE = re.compile(r"\(\d+:(-?\d+)\)")
NEW_CHARGES = range(4, 9)                  # rn1(5, 4): a directional wand
EMPTY_RE = re.compile(r"Nothing happens|You wrest|too worn out to engrave|turns to dust")


class WandChargeMixin:
    def charges_init(self):
        self.wand_recs = {}                # inventory letter -> {"base", "used", "empty"}

    def wand_rec(self, it):
        """The record of the wand it (create / reset it when the letter now holds another wand)."""
        base = base_name(it.text)[2]
        rec = self.wand_recs.get(it.letter)
        if rec is None or (rec["base"] != base and not (base.startswith("wand of")
                                                        and not rec["base"].startswith("wand of"))):
            rec = self.wand_recs[it.letter] = {"base": base, "used": 0, "empty": False}
        rec["base"] = base
        return rec

    def note_wand_use(self, it, said):
        """We zapped / engraved with wand it and the game said `said`: one charge used, or it is spent."""
        rec = self.wand_rec(it)
        rec["used"] += 1
        if EMPTY_RE.search(said):
            rec["empty"] = True

    def wand_spent(self, it):
        """A wand we know is empty: its charges show (n:0) / (n:-1), or using it did nothing."""
        return it.ocls == nh.WAND_CLASS and (bool(WAND_SPENT_RE.search(it.text)) or self.wand_rec(it)["empty"])

    def wand_p_charged(self, it):
        """P(the next zap of attack wand it has a charge): its charges if they show, else the 4..8 prior given
        the charges we used without it running dry (a wand that outlasted the prior: 1/2)."""
        m = CHARGES_RE.search(it.text)
        if m:
            return 1.0 if int(m.group(1)) > 0 else 0.0
        rec = self.wand_rec(it)
        if rec["empty"]:
            return 0.0
        k = rec["used"]
        left = [n for n in NEW_CHARGES if n >= k]
        return sum(n > k for n in left) / len(left) if left else 0.5
