"""One unlocking tool kept (carry.needed) -- the best we carry: skeleton key > lock pick > credit card
-- and locked doors and boxes opened with it, silently, before any kick or #force. lock.c pick_lock: a chance a
turn of 70 + Dex (key), 3 x Dex (lock pick), 2 x Dex (credit card) at a door, 75 + Dex / 4 x Dex / Dex at a box
(halved for a cursed tool, boxes only); an occupation the game runs until done, given up after 50 turns. The tool
never breaks (#force with a blade can; a kick wakes everything near: dokick.c wake_nearby). Not in Minetown (the
watch: "Hey, stop picking that lock!", then an arrest -- monmove.c watch_on_duty) but in Orcish Town (its watch
lies dead). A/B lock_tools +350 [-966, +1591], median +274, box kicks halved."""
import re
from collections import Counter

import nle.nethack as nh

from nhbot.consts import DELTA2KEY

LOCK_RANK = {"skeleton key": 3, "key": 3, "lock pick": 2, "credit card": 1}
LOCK_RE = re.compile(r"\b(skeleton key|key|lock pick|credit card)s?\b", re.I)
LOCK_TRIES = 3                 # attempts (up to 50 turns each) at one door or box before the old ways


class LockToolState:
    """State of unlocking boxes with tools (LockToolMixin)."""
    def __init__(self):
        self.tries = Counter()           # (level key, square) -> unlocking attempts there
        self.stats = Counter()


class LockToolMixin:
    def lock_init(self):
        self.lock = LockToolState()

    def lock_summary(self):
        """Game summary entries."""
        return {"lock_tools": dict(self.lock.stats)}

    @staticmethod
    def lock_rank(text):
        m = LOCK_RE.search(text)
        return LOCK_RANK[m.group(1).lower()] if m else 0

    def lock_tool(self):
        """The unlocking tool we would use -- the best kind, a known-cursed one last."""
        cands = [it for it in self.items() if it.ocls == nh.TOOL_CLASS and self.lock_rank(it.text)]
        return max(cands, key=lambda it: (self.lock_rank(it.text), not it.cursed), default=None)

    def lock_tool_wanted(self, text):
        """A floor tool that beats the one we carry (or the first one)."""
        r = self.lock_rank(text)
        best = self.lock_tool()
        return r > 0 and (best is None or r > self.lock_rank(best.text))

    def lock_door_step(self, lv, target):
        """nav.move into a locked door: unlock it with the tool if we may. True if it used the turn; False: the
        old ways (kick, or the door stays shut)."""
        it = self.lock_tool()
        key = (lv.key, target)
        if it is None or self.lock.tries[key] >= LOCK_TRIES or target in lv.watch_warned \
                or (self.is_minetown(lv) and not self.is_orctown(lv)):
            return False
        y, x = self.pos()
        self.lock.tries[key] += 1
        self.lock.stats["door_try"] += 1
        said = self.lock_apply(it, DELTA2KEY[(target[0] - y, target[1] - x)])
        if "You succeed in" in said or "Lock it?" in said or "no door" in said or "is broken" in said \
                or "open door" in said:                       # lock.c: "unlocking the door" / "picking the lock"
            lv.locked.discard(target)
            self.lock.stats["door_open"] += 1
        elif "stop picking that lock" in said or "under arrest" in said:
            lv.watch_warned.add(target)
            self.no_entry_mark(lv, target)
            self.lock.stats["door_warned"] += 1
        return True

    def lock_box_step(self, key):
        """box_step, a locked box under us: unlock it with the tool. True if it used the turn; False: #force /
        kick as before."""
        it = self.lock_tool()
        if it is None or self.lock.tries[key] >= LOCK_TRIES:
            return False
        self.lock.tries[key] += 1
        self.lock.stats["box_try"] += 1
        self.cur_act = "box"
        said = self.lock_apply(it, None)
        if "You succeed in" in said:
            self.lock.stats["box_open"] += 1
        return True

    def lock_apply(self, it, dirkey):
        """Apply the tool (at a door in direction dirkey; None: the box we stand on) and say yes to the unlock
        question; the game runs the occupation. The text it answered."""
        seq0 = self.msg_seq
        self.cur_act = "unlock"
        if not self.ask("a", "apply"):
            return ""
        self.press(it.letter, expect_prompt=True)
        for _ in range(6):
            m = self.message()
            if "direction" in m.lower():
                self.press(dirkey or ".", expect_prompt=True)   # lock.c get_adjacent_loc: '.' is the box here
            elif "nlock it?" in m or "pick its lock?" in m:     # lock.c: "Unlock it?", "There is a locked chest
                self.press("y", expect_prompt=True)             # here; pick its lock?" (a lock pick, a card)
            elif "ock it?" in m:
                self.press("n", expect_prompt=True)             # "Lock it?": it is unlocked already
            else:
                break
        self.settle()
        return self.text_since(seq0)
