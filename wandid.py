"""Engrave-identify unknown wands (flag wand_id) and use what they turn out to be.

Engraving with a wand shows its type class (NetHack 3.6.6 engrave.c doengrave/zapwand):
  digging / fire / lightning     auto-identified ("wand of digging" in the inventory afterwards)
  "bullet holes"                 magic missile
  "bugs ... stop moving"         sleep or death (both: zap at the enemy)
  "unsuccessfully fights"        striking
  "ice cubes"                    cold
  "bugs ... slow down"           slow monster
  "bugs ... speed up"            speed monster (never at an enemy)
  nothing visible                light / nothing / opening / locking / probing / undead turning / ...
The verdict is kept per appearance ("oak wand"), the shuffle being fixed for the game.

Use:
  * attack: the attack-wand list (roles.attack_wands) also gets unknown-named wands whose verdict is an attack
  * digging: zap down to leave a level we are stuck on (desperate) or to escape when nearly dead and prayer
    is not available (monsters next to us do not follow through a hole)
"""
import re

import nle.nethack as nh

ATTACK = {"magic missile": "magic missile", "sleep/death": "sleep", "striking": "striking", "cold": "cold"}
_VERDICTS = [
    (r"gravel flies up|wand of digging", "digging"),
    (r"burn into the|wand of fire", "fire"),
    (r"[Ll]ightning arcs|wand of lightning|blinded by the flash", "lightning"),
    (r"bullet holes", "magic missile"),
    (r"stop moving", "sleep/death"),
    (r"unsuccessfully fights", "striking"),
    (r"ice cubes", "cold"),
    (r"slow down", "slow monster"),
    (r"speed up", "speed monster"),
    (r"engraving now reads", "polymorph"),
    (r"vanishes", "vanish"),
]


def wand_appearance(s):
    m = re.search(r"\b([a-z][a-z -]*?) wands?\b", s)
    if not m or "wand of" in s:
        return None
    a = re.sub(r"^(an?|the|\d+|uncursed|cursed|blessed)\s+", "", m.group(1).strip())
    a = re.sub(r"^(uncursed|cursed|blessed)\s+", "", a)
    return a


class WandIdMixin:
    def wand_init(self):
        if not hasattr(self, "wand_kind"):
            self.wand_kind = {}                     # appearance -> verdict
            self.wand_stats = {"tested": 0, "digs": 0, "dig_escapes": 0, "unknown_zaps": 0, "wishes": 0}
            self.wand_log = []

    def unknown_wands(self):
        self.wand_init()
        out = []
        for letter, ocls, s in self.inventory():
            if ocls != nh.WAND_CLASS or "wand of" in s:
                continue
            a = wand_appearance(s)
            if a is not None:
                out.append((letter, a, s))
        return out

    def wand_id_step(self, lv):
        """One engrave test of an untested unknown wand, when nothing threatens us."""
        if not self.role_opts.get("wand_id", False):
            return False
        self.wand_init()
        todo = [(l, a, s) for l, a, s in self.unknown_wands() if a not in self.wand_kind]
        if not todo:
            return False
        cond = int(self.last_bl[nh.NLE_BL_CONDITION])
        if cond & (nh.BL_MASK_BLIND | nh.BL_MASK_LEV | nh.BL_MASK_STUN | nh.BL_MASK_CONF | nh.BL_MASK_HALLU):
            return False
        if self.bl(nh.NLE_BL_HP) < self.bl(nh.NLE_BL_HPMAX) * 0.6:
            return False
        y, x = self.pos()
        k = int(self.obs["glyphs"][y, x])
        under = int(lv.under[y, x])
        import glyphs as G
        if G.KIND[under] in (G.UPSTAIR, G.DOWNSTAIR, G.LIQUID) or lv.shop[y, x]:
            return False
        letter, app, s = todo[0]
        self.cur_act = "wand_id"
        t0 = self.turn()
        seen = []
        self.press("E", expect_prompt=True)
        if "write with" not in self.message().lower():
            self.settle()
            self.wand_kind[app] = "?"
            return True
        self.press(letter, expect_prompt=True)
        for _ in range(8):
            m = self.message()
            tty = self.tty_text()
            seen.append(m)
            if "--More--" in tty:
                self.raw_step(13)
                continue
            if "wish" in m.lower() and "for?" in m.lower():
                for c in "blessed +2 gray dragon scale mail":
                    self.raw_step(ord(c))
                self.raw_step(13)
                self.wand_stats["wishes"] += 1
                continue
            if self.obs["misc"][0]:                  # yes/no: "Do you want to add to the current engraving?"
                self.press("n", expect_prompt=True)
                continue
            if self.obs["misc"][1] or re.search(r"(write|engrave|burn|melt|scrawl|carve)[^?]*\?", m.lower()):
                self.raw_step(ord("x"))
                self.raw_step(13)
                continue
            break
        self.settle()
        seen.append(self.message())
        msgs = " ".join(seen + [t for tt, t in list(self.messages) if tt >= t0])
        inv = " ".join(s2 for l2, _, s2 in self.inventory() if l2 == letter)
        verdict = "none"
        for pat, v in _VERDICTS:
            if re.search(pat, msgs) or re.search(pat, inv):
                verdict = v
                break
        if "too worn out" in msgs or "You wrest" in msgs:
            verdict = "empty"
        self.wand_kind[app] = verdict
        self.wand_stats["tested"] += 1
        if len(self.wand_log) < 20:
            self.wand_log.append((self.turn(), app, verdict, msgs[:160]))
        return True

    def extra_attack_wands(self):
        """(letter, kind) for unknown-named wands whose engrave verdict is an attack."""
        if not self.role_opts.get("wand_id", False):
            return []
        self.wand_init()
        out = []
        for letter, a, s in self.unknown_wands():
            v = self.wand_kind.get(a)
            if v in ATTACK and not re.search(r"\(\d+:0\)", s) and letter not in self.empty_wands:
                out.append((letter, ATTACK[v]))
        return out

    def digging_wand(self):
        if not self.role_opts.get("wand_id", False):
            return None
        for letter, ocls, s in self.inventory():
            if ocls == nh.WAND_CLASS and "wand of digging" in s and not re.search(r"\(\d+:0\)", s) \
                    and letter not in self.empty_wands:
                return letter
        return None

    def dig_down(self, lv, why):
        """Zap digging downwards: we fall to the next level. Not on stairs/fountains/altars, not in shops."""
        letter = self.digging_wand()
        if letter is None:
            return False
        import glyphs as G
        y, x = self.pos()
        if G.KIND[int(lv.under[y, x])] in (G.UPSTAIR, G.DOWNSTAIR, G.LIQUID) or lv.shop[y, x] or lv.key[0] == 4:
            return False
        self.wand_init()
        self.cur_act = "dig"
        self.wand_stats["digs" if why == "stuck" else "dig_escapes"] += 1
        self.took_stairs = True
        return self.zap(letter, ">")
