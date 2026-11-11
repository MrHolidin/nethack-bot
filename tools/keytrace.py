"""Debug: play a seed and print the keys, messages and screen around the first no-time loops (keys agent).

  python tools/keytrace.py SEED [--kw JSON] [--loops N] [--at-turn T]"""
import argparse, json, os, sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nhbot import Bot

ap = argparse.ArgumentParser()
ap.add_argument("seed", type=int)
ap.add_argument("--kw", default="{}")
ap.add_argument("--loops", type=int, default=2)
ap.add_argument("--at-turn", type=int, default=None)
ap.add_argument("--keys", type=int, default=60)
a = ap.parse_args()

hist = deque(maxlen=a.keys)
orig = Bot.raw_step
state = {"loops": 0, "dumped_turn": False}


def dump(self, why):
    print(f"==== {why} turn {self.turn()} pos {self.pos()} steps {self.steps} last_step {self.pol.last_step} "
          f"prev {getattr(self.pol, 'prev_step', None)} act {self.cur_act}")
    for t, k, m, top in hist:
        print(f"  t{t} {k!r:8} msg={m!r} top={top!r}")
    print("\n".join(self.tty_text().split("\n")[:24]))


def raw_step(self, code):
    orig(self, code)
    hist.append((self.turn(), chr(code) if 32 <= code < 127 else code, self.message()[:90], self.top_line()[:90]))
    if self.pol.loops > state["loops"]:
        state["loops"] = self.pol.loops
        if state["loops"] <= a.loops:
            dump(self, f"loop {state['loops']}")
    if a.at_turn is not None and not state["dumped_turn"] and self.turn() >= a.at_turn:
        state["dumped_turn"] = True
        dump(self, "at turn")


Bot.raw_step = raw_step
s = Bot(seed=a.seed, character="val", **json.loads(a.kw)).run()
print({k: s[k] for k in ("score", "turns", "steps", "max_depth", "loops", "loop_by", "truncated")})
