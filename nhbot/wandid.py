"""Wand identification by engraving: with nothing threatening us, write in the dust with an unidentified wand and
read what the game says (engrave.c doengrave, NetHack 3.6.6). One charge per test. (A/B wand_engrave over base_i:
score +456 [-871, +1799], max_depth +0.1 [-0.1, +0.4].)

A dust engraving must already lie on the square: teleportation, cancellation and make invisible show only by
making it vanish, polymorph by changing it. So we write "x" with a finger first, then engrave "x" with the wand
(the post-engraving messages of the ray / immediate wands come only after some text is written).

  digging, fire, lightning            "This ... is a wand of X!" -- the game identifies it
  light, secret door detection,       zapnodir: the usual effect, identified by the game when seen (a wish is
  create monster, enlightenment,      answered by elbereth.engrave)
  wishing
  "The bugs on the floor stop moving!"            sleep or death
  "The bugs on the floor slow down!"              slow monster
  "The bugs on the floor speed up!"               speed monster
  "The floor is riddled by bullet holes!"         magic missile
  "A few ice cubes drop from the wand."           cold
  "The wand unsuccessfully fights your attempt"   striking
  "The engraving now reads: ..."                  polymorph
  "The engraving on the floor vanishes!"          cancellation, make invisible or teleportation
  nothing                                         opening, locking, probing, undead turning, nothing, or secret
                                                  door detection with nothing to find
  "The wand is too worn out to engrave."          no charges left
The result is kept per appearance; wand_kind() gives combat (attack_wands), carry (needed) and the value
(type_posterior) the type it narrows to.
"""
import re
from collections import Counter

import nle.nethack as nh

from nhbot.pricemem import appearance

RESULTS = (
    (re.compile(r"bugs on the [a-z ]+ stop moving"), frozenset({"sleep", "death"})),
    (re.compile(r"bugs on the [a-z ]+ slow down"), frozenset({"slow monster"})),
    (re.compile(r"bugs on the [a-z ]+ speed up"), frozenset({"speed monster"})),
    (re.compile(r"riddled by bullet holes"), frozenset({"magic missile"})),
    (re.compile(r"ice cubes drop from the wand"), frozenset({"cold"})),
    (re.compile(r"unsuccessfully fights your attempt to write"), frozenset({"striking"})),
    (re.compile(r"engraving now reads"), frozenset({"polymorph"})),
    (re.compile(r"engraving on the [a-z ]+ vanishes"), frozenset({"cancellation", "make invisible", "teleportation"})),
)
NO_MESSAGE = frozenset({"opening", "locking", "probing", "undead turning", "nothing", "secret door detection"})
WORN_OUT_RE = re.compile(r"too worn out to engrave|turns to dust")
WAND_OF_RE = re.compile(r"wand of ([a-z ]+?)(?: \(| called| named|$)")


class WandIdState:
    """State of identifying wands by engraving (WandIdMixin)."""
    def __init__(self):
        self.engraved = {}               # appearance key -> frozenset of the types the engraving test left
        self.stats = Counter()
        self.refused = set()             # (level key, square) where the game refused an engraving


class WandIdMixin:
    def wandid_init(self):
        self.wandid = WandIdState()

    def wandid_summary(self):
        """Game summary entries."""
        return {"wandid": dict(self.wandid.stats)}

    def wand_kind(self, it):
        """The type of a wand: by name, or what the engraving test narrowed it to (sleep or death: 'sleep',
        a ray either way); None if unknown."""
        m = WAND_OF_RE.search(it.text)
        if m:
            return m.group(1).strip()
        s = self.wandid.engraved.get(appearance(it.text))
        if s is not None and len(s) == 1:
            return next(iter(s))
        if s == {"sleep", "death"}:
            return "sleep"
        return None

    def wand_to_test(self):
        for it in self.items():
            if it.ocls != nh.WAND_CLASS or self.wand_spent(it):
                continue
            key = appearance(it.text)
            if key is not None and key not in self.wandid.engraved:
                return it, key
        return None, None

    def wandid_step(self, lv):
        """No threat in view (the caller checks): test one unidentified wand. True if it used the turn."""
        if self.soko_wands_shut(lv):
            return False
        it, key = self.wand_to_test()
        if it is None or not self.elb_can_write(lv) or lv.shop[self.pos()] \
                or (lv.key, self.pos()) in self.wandid.refused \
                or int(self.last_bl[nh.NLE_BL_CONDITION]) & nh.BL_MASK_HALLU \
                or self.hp_below(self.opts.wandid_hp):
            return False
        self.cur_act = "wandid"
        if not self.read_engraving():
            self.wandid.stats["dust_first"] += 1
            if not self.engrave("-", "x"):       # something to vanish / change
                self.wandid.refused.add((lv.key, self.pos()))   # "You can't write on the fountain!" (no time)
                self.wandid.stats["refused"] += 1
            return True
        seq0 = self.msg_seq
        self.wandid.stats["tests"] += 1
        self.engrave(it.letter, "x")
        msgs = self.text_since(seq0)
        self.note_wand_use(it, msgs)                     # charges.py: a charge used, or it is spent
        now = next((i for i in self.items() if i.letter == it.letter), None)
        if now is None or appearance(now.text) != key:
            self.wandid.engraved[key] = frozenset()        # identified by the game (or gone)
            self.value.type_version += 1
            self.wandid.stats["named_by_game"] += 1
            return True
        if WORN_OUT_RE.search(msgs):
            self.wandid.stats["empty"] += 1
            return True                                  # tested again once recharged? no: empty stays empty
        found = next((s for rx, s in RESULTS if rx.search(msgs)), None)
        self.wandid.engraved[key] = found if found is not None else NO_MESSAGE
        self.value.type_version += 1
        self.wandid.stats["msg" if found is not None else "no_msg"] += 1
        return True
