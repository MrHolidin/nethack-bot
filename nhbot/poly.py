"""Polymorphed: the form we are in, as the status lines show it, and whether it has hands."""
import re

import nle.nethack as nh

from nhbot.monsters import M1_NOHANDS, PM_BY_NAME, PM_INDICES, S_HUMAN

_HANDLESS = {}                     # polymorph form name -> handless (permonst lookup is slow for were forms)


class PolyMixin:
    def poly_form(self):
        """Name of the form we are polymorphed into, else None. Polymorphed, the second status line shows "HD:n"
        instead of "Xp:n/m" (botl.c bot2: Upolyd) and the first the form instead of the rank title -- any role's
        (a Valkyrie-only rank list took every other role's title for a handless form: no Elbereth)."""
        if not re.search(r"\bHD:\d", bytes(self.obs["tty_chars"][23]).decode("latin1")):
            return None
        m = re.match(r"\S+ the (.+?)\s{2,}St:", bytes(self.obs["tty_chars"][22]).decode("latin1"))
        return m.group(1).lower() if m else None

    def handless(self):
        """Polymorphed into a form that can't wear or wield (nohands / very small: do_wear.c, wield.c)."""
        form = self.poly_form()
        if form is None:
            return False
        if form not in _HANDLESS:
            pm = PM_BY_NAME.get(form)
            if form.startswith("were"):      # lycanthrope: the status line names it, the body is the animal
                pm = next(nh.permonst(i) for i in PM_INDICES.get(form, ()) if nh.permonst(i).mlet != S_HUMAN)
            _HANDLESS[form] = pm is None or bool(pm.mflags1 & M1_NOHANDS) or pm.msize == 0
        return _HANDLESS[form]
