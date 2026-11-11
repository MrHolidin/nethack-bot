"""Debug: every farlook done twice -- by direction keys and by the 'm' jump -- and the answers compared (keys agent).

  python tools/farlook_check.py SEED [MAX_TURNS]"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nhbot import Bot
from nhbot.game import cursor_keys

seed = int(sys.argv[1])
max_turns = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
new = Bot.describe_at
diffs = [0, 0]


def old(self, pos):
    y, x = self.pos()
    self.raw_step(ord(";"))
    for k in cursor_keys(pos[0] - y, pos[1] - x):
        self.raw_step(ord(k))
    desc = self.top_line()
    cur = tuple(int(v) for v in self.obs["tty_cursor"])
    self.raw_step(27)
    self.settle()
    return desc, cur


def both(self, pos):
    d1, c1 = old(self, pos)
    jump = self.monster_rank(pos)
    d2 = new(self, pos)
    diffs[1] += 1
    if d1 != d2:
        diffs[0] += 1
        if diffs[0] <= 15:
            print(f"DIFF t{self.turn()} me {self.pos()} pos {pos} jump {jump} cursor_old {c1}\n  old={d1!r}\n  new={d2!r}")
    return d1


def twice(self, pos):
    y, x = self.pos()
    far = max(abs(pos[0] - y), abs(pos[1] - x)) > 1
    if os.environ.get("ONLY", "") != ("near" if far else "far"):
        old(self, pos)
        diffs[1] += 1
    return old(self, pos)[0]


Bot.describe_at = twice if os.environ.get("MODE") == "twice" else both
s = Bot(seed=seed, character="val", max_turns=max_turns).run()
print("looks", diffs[1], "diffs", diffs[0], s["turns"], s["msg_audit"])
