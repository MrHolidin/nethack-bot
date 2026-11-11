"""Debug: after the loop guard first fires, the call stacks of the next keys sent (keys agent).

  python tools/loopstack.py SEED [N_STACKS]"""
import os, sys, traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nhbot import Bot

seed = int(sys.argv[1])
want = int(sys.argv[2]) if len(sys.argv) > 2 else 3
orig = Bot.raw_step
seen, state = set(), {"armed": False, "done": 0, "loop_turn": None}


def raw_step(self, code):
    if not state["armed"] and self.pol.loops > 0:
        state["armed"], state["loop_turn"] = True, self.turn()
        print(f"loop at turn {self.turn()} pos {self.pos()} msgs {[m for _, m in list(self.messages)[-3:]]}")
    if state["armed"] and state["done"] < want and self.turn() <= state["loop_turn"] + 3:
        st = "".join(traceback.format_stack(limit=9)[:-1])
        if st not in seen:
            seen.add(st)
            state["done"] += 1
            print(f"---- key {chr(code) if 32 <= code < 127 else code} turn {self.turn()}\n{st}")
    if state["armed"] and state["done"] >= want:
        raise SystemExit(0)
    return orig(self, code)


Bot.raw_step = raw_step
Bot(seed=seed, character="val").run()
