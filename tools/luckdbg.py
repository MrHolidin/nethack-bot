"""Debug: luck_squeeze's state at each call near a turn (keys agent).  python tools/luckdbg.py SEED TURN"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nhbot import Bot
from nhbot.luckstone import NAMED_RE

seed, turn = int(sys.argv[1]), int(sys.argv[2])
orig = Bot.luck_squeeze
n = [0]


def wrap(self, lv):
    if self.turn() >= turn - 5 and n[0] < 12:
        n[0] += 1
        cands = [it.text for it in self.items() if not it.on_body and not NAMED_RE.search(it.text)
                 and it.key not in self.carry.cant_drop]
        print(f"t{self.turn()} pos {self.pos()} refused {self.luck.squeeze_refused} wt {self.inventory_weight()} "
              f"cands {cands[:6]} stash {self.luck.stash} msgs {[m for _, m in list(self.messages)[-2:]]}")
        r = orig(self, lv)
        print(f"   -> {r} refused now {self.luck.squeeze_refused} status {self.luck.status}")
        return r
    return orig(self, lv)


Bot.luck_squeeze = wrap
s = Bot(seed=seed, character="val", max_turns=turn + 3).run()
print(s["turns"], s["loops"])
