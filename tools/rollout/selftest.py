"""The harness's own checks (python -m tools.rollout.collect --selftest --seeds A:B [-j N]).

Per seed, three games up to MAX_TURN turns:
  plain      the bot alone: the reference key sequence.
  forking    every EVERY turns the game is forked twice. Child 1 is reseeded and plays HORIZON turns of another
             future (through level changes, deaths, whatever comes). Child 2 keeps the parent's RNG state and
             forces 'default'.
Checks:
  isolation    the forking game's keys are identical to the plain game's: no child disturbed its parent (the game
               directory, the nhdat file offset, the bot's own state).
  determinism  child 2's keys over its HORIZON turns are identical to what the parent then sent over the same
               turns: a fork replays the scripted continuation exactly.
  reseed       child 1's keys differ from child 2's (a different future) in most forks.
"""
import json
import multiprocessing as mp

from tools.rollout.collect import Collector, key_hash

MAX_TURN, EVERY, HORIZON = 6000, 150, 120


class ForkEvery(Collector):
    """Forks at fixed turns, computes no features: nothing but the forks could disturb the parent."""

    def __init__(self, bot):
        super().__init__(bot, None, horizon=HORIZON)
        self.next_t, self.keys, self.windows, self.results = EVERY, [], [], []
        self.orig_raw, self.orig_play = bot.raw_step, bot.play_tick
        bot.raw_step, bot.play_tick = self.raw_step, self.play_tick

    def raw_step(self, code):
        self.keys.append(code)
        return self.orig_raw(code)

    def play_tick(self):
        self.close_windows(self.bot.turn())
        return self.orig_play()

    def close_windows(self, t, final=False):
        for w in list(self.windows):
            if final or t - w["t0"] >= HORIZON:
                mine = self.keys[w["k0"]:]
                self.results.append({"t0": w["t0"], "same": key_hash(mine) == w["child"].get("keyhash"),
                                     "n": len(mine), "child_n": w["child"].get("nkeys"),
                                     "reseed_differs": w["other"].get("keyhash") != w["child"].get("keyhash"),
                                     "crash": w["child"].get("crash") or w["other"].get("crash")})
                self.windows.remove(w)

    def hook(self, bot, c):
        if c.t < self.next_t:
            return
        self.next_t = c.t + EVERY
        other = self.spawn(c, "default", 1000 + c.t, record_keys=True)
        child = self.spawn(c, "default", None, record_keys=True)
        self.windows.append({"t0": c.t, "k0": len(self.keys), "child": child, "other": other})


def one(seed):
    from nhbot import Bot
    out = {"seed": seed}
    for mode in ("plain", "forking"):
        bot = Bot(seed=seed, character="val", max_turns=MAX_TURN)
        keys, orig = [], bot.raw_step
        if mode == "plain":
            def raw_step(code, keys=keys, orig=orig):
                keys.append(code)
                return orig(code)
            bot.raw_step = raw_step
            bot.run()
            out["plain"] = (len(keys), key_hash(keys))
        else:
            col = {}
            orig_init = bot.tactic_init

            def tactic_init(bot=bot, col=col, orig_init=orig_init):
                orig_init()
                col["c"] = ForkEvery(bot)
            bot.tactic_init = tactic_init
            s = bot.run()
            c = col["c"]
            c.close_windows(bot.turn(), final=True)
            c.close()
            out["forking"] = (len(c.keys), key_hash(c.keys))
            out["turns"] = s["turns"]
            out["forks"] = len(c.results)
            out["determinism_ok"] = sum(1 for r in c.results if r["same"])
            out["reseed_differs"] = sum(1 for r in c.results if r["reseed_differs"])
            out["bad"] = [r for r in c.results if not r["same"] or r["crash"]][:5]
    out["isolation_ok"] = out["plain"] == out["forking"]
    return out


def main(seeds, jobs):
    ok = True
    with mp.Pool(jobs) as pool:
        for r in pool.imap_unordered(one, list(seeds), chunksize=1):
            print(json.dumps(r), flush=True)
            ok &= r["isolation_ok"] and r["determinism_ok"] == r["forks"]
    print("selftest:", "OK" if ok else "FAILED")
    return 0 if ok else 1
