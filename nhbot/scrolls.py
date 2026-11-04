"""Reading scrolls (read_good; read_unknown) and answering what a scroll asks.

A scroll's appearance ("scroll labeled ZELGO MER") is random per game, its base price is fixed per type
(objects.c). Shop prices narrow an appearance down to the types with that base price (pricemem.py).

Read rule: an appearance whose possible types are all enchant weapon, enchant armor or remove curse -- never
harmful -- is read (and not sold). read_unknown (A/B): also, at full HP above TEST_MIN_HP, with no hostile in view
and no pet next to us, while neither
enchant armor nor identify is known by name (discoveries), a scroll whose price group is unknown or is 20 zm
(identify) or 60 zm (enchant weapon). Before a scroll that may be enchant armor, the worn pieces it could
evaporate come off (equipment.strip_for_enchant) and are worn again after.

What a scroll asks (read.c seffects), answered in game.settle and read_scroll:
  identify        the menu: jewelry.answer_identify_menu
  genocide        GENOCIDE_SPECIES (uncursed; cursed: the same question, reverse genocide), GENOCIDE_CLASS (blessed)
  charging        a wand: attack wands first, never a wand of wishing (a second charge can blow it up)
  fire (blessed)  where the explosion goes: a floor square two steps away, not on us
  stinking cloud  where the cloud goes: nowhere (ESC: "Never mind")
  detections      gold / food / magic mapping (detect.c browse_map): the cursor to look around, ESC
"""
import re

import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import DELTA2KEY, NEIGH
from nhbot.game import PAGE_RE
from nhbot.pricemem import appearance

GOOD_TYPES = {"enchant armor", "enchant weapon", "remove curse"}
GOOD_RE = re.compile(r"\bscrolls? of (?:enchant armor|enchant weapon|remove curse)\b")    # a stack: "3 scrolls of"
UNKNOWN_READ_TYPES = {"identify", "enchant weapon"}     # read_unknown: price groups 20 and 60 zm
TESTING_ENDS = {"enchant armor", "identify"}            # read_unknown: once one of these is known, stop
TEST_MIN_HP = 40                                        # read_unknown: only above this HP
GENOCIDE_SPECIES = ("water nymph", "mountain nymph", "wood nymph")
GENOCIDE_CLASS = ("n",)
CHARGE_FIRST = ("sleep", "magic missile", "fire", "cold", "lightning", "striking", "digging")
DISCO_SCROLL_RE = re.compile(r"scroll of ([a-z ]+?) \(")


class ScrollMixin:
    def scroll_init(self):
        self.scroll_stats = {"read": 0, "read_names": []}
        self.scroll_known = None         # scroll types known by name (discoveries); None: ask again
        self.genocide_typed = set()      # names given to a genocide question (never twice)
        self.read_seq = 0                # msg_seq when the last read began

    def sucker(self):
        """Visible dunce cap or a shirt with nothing over it: shopkeepers add 1/3."""
        worn = [it.text for it in self.items() if it.worn]
        if any("dunce cap" in s for s in worn):
            return True
        shirt = any("shirt" in s for s in worn)
        over = any(re.search(r"mail|armor|jacket|cloak|robe|apron|tunic|coat", s) for s in worn if "shirt" not in s)
        return shirt and not over

    def scroll_is_good(self, s):
        """Identified as one of GOOD_TYPES, or every type its shop prices allow is one of them."""
        if GOOD_RE.search(s):
            return True
        post = self.price_of_text(s) if "labeled" in s else None
        return bool(post) and set(post) <= GOOD_TYPES

    # ------------------------------------------------------------ what we know
    def known_scroll_types(self):
        """Scroll types known by name: the discoveries list ('\\'), read once after every scroll we read."""
        if self.scroll_known is None:
            self.raw_step(ord("\\"))
            text = ""
            for _ in range(10):
                tty = self.tty_text()
                text += "\n" + tty
                page = PAGE_RE.search(tty)
                if page and int(page.group(1)) < int(page.group(2)):
                    self.raw_step(ord(">"))
                elif "--More--" in tty.replace("\n", "") and "(end)" not in tty:
                    self.raw_step(13)
                else:
                    self.raw_step(27)
                    break
            self.settle()
            self.scroll_known = set(DISCO_SCROLL_RE.findall(text))
        return self.scroll_known

    def unknown_readable(self, s):
        """read_unknown: a scroll worth reading untested -- its price group unknown, or 20 / 60 zm."""
        if appearance(s) is None:
            return False                       # known by name, or blank paper ("unlabeled": not shuffled)
        post = self.price_of_text(s)
        return not post or set(post) <= UNKNOWN_READ_TYPES

    def test_reading_on(self):
        """read_unknown: full HP and more than TEST_MIN_HP (earth drops a boulder on us: d20 without a hard
        helmet), no pet next to us (earth's boulders and fire's explosion hit the 8 squares around: a killed pet
        costs alignment and maybe Luck), and neither enchant armor nor identify known by name yet."""
        hp = self.bl(nh.NLE_BL_HP)
        if hp < self.bl(nh.NLE_BL_HPMAX) or hp <= TEST_MIN_HP:
            return False
        y, x = self.pos()
        g = self.obs["glyphs"]
        if (G.KIND[g[max(0, y - 1):y + 2, max(0, x - 1):x + 2]] == G.PET).any():
            return False
        return not self.known_scroll_types() & TESTING_ENDS

    # ------------------------------------------------------------ read
    def read_scroll_step(self, lv):
        """Housekeeping (no hostile in view): read a good scroll, else (read_unknown) an untested one."""
        cond = int(self.last_bl[nh.NLE_BL_CONDITION])
        if cond & (nh.BL_MASK_BLIND | nh.BL_MASK_CONF | nh.BL_MASK_STUN | nh.BL_MASK_HALLU):
            return False              # confused remove curse / enchant armor do other things
        inv = [(it.letter, it.text) for it in self.items() if it.ocls == nh.SCROLL_CLASS]
        good = [(l, s) for l, s in inv if self.scroll_is_good(s)]
        todo = [(l, s, "good") for l, s in good]
        if self.opts.read_unknown and not good:
            unknown = [(l, s) for l, s in inv if self.unknown_readable(s)]
            if unknown and self.test_reading_on():
                todo = [(l, s, "unknown") for l, s in unknown]
        for letter, s, why in todo:
            if why == "unknown" and self.opts.test_strip and self.strip_for_test():
                return True                           # the suit came off: destroy armor would take it
            maybe_armor = "enchant armor" in s or "labeled" in s
            if maybe_armor:
                ready = self.strip_for_enchant()      # the pieces it could evaporate come off first
                if ready == "acted":
                    self.scroll_stats["stripped"] = self.scroll_stats.get("stripped", 0) + 1
                    return True
                if ready == "wait":
                    continue
            if "enchant weapon" in s and not any(it.wielded for it in self.items()):
                continue
            if not self.read_scroll(lv, letter):
                return False
            self.scroll_stats["read"] += 1
            self.scroll_stats["read_names"].append(s[:60])
            if why == "unknown":
                self.scroll_stats["tested"] = self.scroll_stats.get("tested", 0) + 1
                self.scroll_stats.setdefault("tested_said", []).append(self.text_since(self.read_seq)[-90:])
            return True
        return False

    def read_scroll(self, lv, letter):
        """r + letter; the questions it asks are answered (game.settle; the position ones here). False if the
        game did not ask what to read."""
        if not self.ask("r", "read"):
            return False
        seq0 = self.read_seq = self.msg_seq
        self.press(letter)
        self.scroll_known = None
        said = self.text_since(seq0) + " " + self.top_line()
        if "center the explosion" in said:
            self.aim_away(lv)                      # blessed fire
        elif "For instructions type a" in said:
            self.raw_step(27)                      # stinking cloud: not here; a detection's map browse: done
        self.settle()
        tail = " ".join(self.msgs_since(seq0))
        for name in ("genocide", "charg", "explosion", "cloud", "identify"):
            if name in tail.lower():
                self.scroll_stats["asked_" + name] = self.scroll_stats.get("asked_" + name, 0) + 1
        return True

    # ------------------------------------------------------------ answers
    def aim_away(self, lv):
        """getpos is open (blessed fire): put the cursor on a floor square two steps away along a floor line,
        then '.'; with none, ESC (the explosion stays on us)."""
        y, x = self.pos()
        k = self.kinds(lv)
        rows, cols = k.shape
        for dy, dx in NEIGH:
            sq = [(y + dy * i, x + dx * i) for i in (1, 2)]
            if all(0 <= a < rows and 0 <= b < cols and k[a, b] == G.FLOOR for a, b in sq):
                key = DELTA2KEY[(dy, dx)]
                self.raw_step(ord(key))
                self.raw_step(ord(key))
                self.raw_step(ord("."))
                return
        self.raw_step(27)

    def answer_genocide(self, prompt):
        """getlin: the genocide question. A class (blessed) or a species (uncursed, or cursed: reverse)."""
        names = GENOCIDE_CLASS if "class" in prompt.lower() else GENOCIDE_SPECIES
        name = next((n for n in names if n not in self.genocide_typed), None)
        if name is None:
            self.raw_step(27)
            return
        self.genocide_typed.add(name)
        self.scroll_stats["genocide"] = name
        for c in name:
            self.raw_step(ord(c))
        self.raw_step(13)

    def answer_charge(self):
        """'What do you want to charge?': a wand -- attack wands and digging first, never wishing."""
        wands = [it for it in self.items() if it.ocls == nh.WAND_CLASS and "wishing" not in it.text]

        def rank(it):
            kind = self.wand_kind(it)
            return CHARGE_FIRST.index(kind) if kind in CHARGE_FIRST else len(CHARGE_FIRST)
        if not wands:
            self.raw_step(27)
            return
        it = min(wands, key=rank)
        self.scroll_stats["charged"] = it.text[:40]
        self.raw_step(ord(it.letter))
