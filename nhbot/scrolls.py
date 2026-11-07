"""Reading scrolls: the good ones, and untested ones while it pays; answering what a scroll asks.

A scroll's appearance ("scroll labeled ZELGO MER") is random per game, its base price is fixed per type
(objects.c). Shop prices narrow an appearance down to the types with that base price (pricemem.py).

Good scrolls: an appearance whose possible types are all enchant weapon, enchant armor or remove curse -- never
harmful -- is read (and not sold). Before a scroll that may be enchant armor, the worn pieces it could evaporate
come off (equipment.strip_for_enchant) and are worn again after.

Untested scrolls (A/B read_unknown + test_strip_plus over base ev_on_f: score +753 [-679, +2146]; over read_unknown
alone +1504 [+240, +2831]): with no hostile in view, at full HP above TEST_MIN_HP, no pet next to us, and while
neither enchant armor nor identify is known by name (discoveries), a scroll whose price group is unknown or is 20 zm
(identify) or 60 zm (enchant weapon) is read; every worn piece +3 or better comes off first
(equipment.strip_for_test) -- destroy armor would otherwise take the Valkyrie's +3 shield. One forced read in that
state against a blank one (an experiment, 861 games): enchant armor +0.58 depth, destroy armor -0.81, fire -0.38,
earth -0.24, amnesia -0.08.

What a scroll asks (read.c seffects), answered in game.settle and read_scroll:
  identify        the menu: jewelry.answer_identify_menu
  genocide        GENOCIDE_SPECIES (uncursed; cursed: the same question, reverse genocide), GENOCIDE_CLASS (blessed)
  charging        a wand: attack wands first, never a wand of wishing (a second charge can blow it up)
  fire (blessed)  where the explosion goes: a floor square two steps away, not on us
  stinking cloud  where the cloud goes: nowhere (ESC: "Never mind")
  detections      gold / food / magic mapping (detect.c browse_map): the cursor to look around, ESC
"""
import re
from collections import Counter

import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import DELTA2KEY, NEIGH
from nhbot.game import PAGE_RE
from nhbot.pricemem import appearance

GOOD_TYPES = {"enchant armor", "enchant weapon", "remove curse"}
GOOD_RE = re.compile(r"\bscrolls? of (?:enchant armor|enchant weapon|remove curse)\b")    # a stack: "3 scrolls of"
UNKNOWN_READ_TYPES = {"identify", "enchant weapon"}     # untested scrolls: price groups 20 and 60 zm
TESTING_ENDS = {"enchant armor", "identify"}            # untested scrolls: once one of these is known, stop
TEST_MIN_HP = 40                                        # untested scrolls: only above this HP
GENOCIDE_SPECIES = ("water nymph", "mountain nymph", "wood nymph")
GENOCIDE_CLASS = ("n",)
CHARGE_FIRST = ("sleep", "magic missile", "fire", "cold", "lightning", "striking", "digging")
DISCO_SCROLL_RE = re.compile(r"scroll of ([a-z ]+?) \(")
# read.c / wield.c: "Your <xname> [violently ]glow(s) <colour> for a moment|while[, then evaporate(s)]" (an
# artifact by name: "Excalibur glows blue ...")
ENCHANT_RE = re.compile(r"((?:Your )?[\w'-]+(?: [\w'-]+)*?) (violently )?glows? (silver|blue|black) for a (?:moment|while)"
                        r"(,? (?:and )?then evaporates?)?")
ENCHANT_LOG = 20


class ScrollMixin:
    def scroll_init(self):
        self.scroll_stats = {"read": 0, "read_names": []}
        self.scroll_known = None         # scroll types known by name (discoveries); None: ask again
        self.genocide_typed = set()      # names given to a genocide question (never twice)
        self.read_seq = 0                # msg_seq when the last read began
        self.enchant_stats = Counter()   # msg_enchant: what enchant armor / weapon did, from the game's words
        self.enchant_log = []            # (turn, effect, item) of the first ENCHANT_LOG of them

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

    # ------------------------------------------------------------ what enchanting did
    def msg_enchant(self, m):
        """Count what enchant armor / enchant weapon did (read.c seffects, wield.c chwepon): +1 or more to a piece
        of armor (silver) or the weapon (blue), -1 / a curse (black), a piece gone (evaporates), wasted (skin)."""
        for mm in ENCHANT_RE.finditer(m):
            item, colour, rest = re.sub(r"^Your ", "", mm.group(1)), mm.group(3), mm.group(4) or ""
            if "evaporate" in rest:
                effect = "evaporated"
            elif colour == "black":
                effect = "down"
            else:
                effect = "armor_up" if colour == "silver" else "weapon_up"
            self.enchant_stats[effect] += 1
            if len(self.enchant_log) < ENCHANT_LOG:
                self.enchant_log.append((self.turn(), effect, item))
        if "Your skin glows then fades" in m:
            self.enchant_stats["skin"] += 1

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
        """A scroll worth reading untested: its price group unknown, or 20 / 60 zm."""
        if appearance(s) is None:
            return False                       # known by name, or blank paper ("unlabeled": not shuffled)
        post = self.price_of_text(s)
        return not post or set(post) <= UNKNOWN_READ_TYPES

    def test_safe(self):
        """Safe enough to read a scroll that may be harmful: full HP and more than TEST_MIN_HP (earth drops a
        boulder on us: d20 without a hard helmet), no pet next to us (earth's boulders and fire's explosion hit
        the 8 squares around: a killed pet costs alignment and maybe Luck)."""
        hp = self.bl(nh.NLE_BL_HP)
        if hp < self.bl(nh.NLE_BL_HPMAX) or hp <= TEST_MIN_HP:
            return False
        y, x = self.pos()
        g = self.obs["glyphs"]
        return not (G.KIND[g[max(0, y - 1):y + 2, max(0, x - 1):x + 2]] == G.PET).any()

    def test_reading_on(self):
        """Untested scrolls: test_safe, and neither enchant armor nor identify known by name yet."""
        return self.test_safe() and not self.known_scroll_types() & TESTING_ENDS

    def read_state(self):
        """The state a read happens in (logged for untested reads)."""
        return {"t": self.turn(), "dlvl": self.bl(nh.NLE_BL_DEPTH), "xl": self.bl(nh.NLE_BL_XP),
                "hp": self.bl(nh.NLE_BL_HP), "maxhp": self.bl(nh.NLE_BL_HPMAX), "ac": self.bl(nh.NLE_BL_AC)}

    # ------------------------------------------------------------ read
    def read_scroll_step(self, lv):
        """Housekeeping (no hostile in view): read a good scroll, else an untested one."""
        cond = int(self.last_bl[nh.NLE_BL_CONDITION])
        if cond & (nh.BL_MASK_BLIND | nh.BL_MASK_CONF | nh.BL_MASK_STUN | nh.BL_MASK_HALLU):
            return False              # confused remove curse / enchant armor do other things
        if self.opts.sokoban and self.in_sokoban(lv):
            return False              # a scroll of earth would drop boulders into the puzzle
        inv = [(it.letter, it.text) for it in self.items() if it.ocls == nh.SCROLL_CLASS]
        good = [(l, s) for l, s in inv if self.scroll_is_good(s)]
        todo = [(l, s, "good") for l, s in good]
        if not good:
            unknown = [(l, s) for l, s in inv if self.unknown_readable(s)]
            if unknown and self.test_reading_on():
                todo = [(l, s, "unknown") for l, s in unknown]
        for letter, s, why in todo:
            if why == "unknown":
                if self.strip_for_test():
                    return True                       # a +3 or better piece came off: destroy armor can't take it
                maybe_armor = False                   # what is left on may be bare (+4 and up are off already)
            else:
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
            state = self.read_state()
            if not self.read_scroll(lv, letter):
                return False
            self.scroll_stats["read"] += 1
            self.scroll_stats["read_names"].append(s[:60])
            if why == "unknown":
                self.scroll_stats["tested"] = self.scroll_stats.get("tested", 0) + 1
                self.scroll_stats.setdefault("tested_log", []).append(
                    dict(state, said=self.text_since(self.read_seq)[-90:]))
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
