"""Counterfactual rollouts at the decision points of a live game (see README.md).

A Collector is installed as the bot's tactic hook (nhbot.tactic.TacticState.hook). At a decision point -- a
hostile next to us and the fight matters (`trigger`) -- it forks the game once per (legal option, replicate); each
child forces its option for this tick (a macro option for its ticks), plays on as the scripted bot for `horizon`
game turns under a fresh RNG seed, and reports what happened. The parent then plays on, untouched.

    python -m tools.rollout.collect --seeds 400000:400016 -j 16 --out /dev/shm/rl/d0
    python -m tools.rollout.collect --selftest --seeds 400000:400004

Output: one jsonl per game, a line per decision point:
    {"seed", "dp", "t", "feat": {...}, "legal": [...], "rolls": [{"opt", "rep", "ok", "first", "died", ...}]}
"""
import argparse
import atexit
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time

import nle.nethack as nh

from nhbot.game import GameOver
from tools.rollout import fork

CHECKPOINTS = (5, 10, 20, 50, 100, 200)
DEFAULTS = {
    "horizon": 300,            # game turns a child plays on
    "reps": 2,                 # children per option, each with its own future (the same seeds for every option)
    "gap": 8,                  # game turns at least between two decision points
    "max_dp": 150,             # decision points at most per game
    "max_secs": 2700,          # ... and wall-clock seconds of rollouts per game
    "options": None,           # the options tried (None: every legal one)
    "variants": (),            # the policy variants tried (names of VARIANTS; "all")
    "hp_frac": 0.5,            # trigger: HP below this fraction
    "pdeath": 0.003,           # ... or danger.py's P(death next turn) at least this
    "win_prob": 0.85,          # ... or win_prob at most this
    "keep": 1.0,               # the fraction of triggered ticks rolled out (drawn from the game seed)
    "max_turn": None,          # stop the parent game at this turn
}


# Policy variants: a child plays on as the scripted bot with these options changed (a sustained change of the
# policy, not a forced first action) -- name: (option overrides, where it can matter: a test on the features)
VARIANTS = {
    "elb70": ({"elb_hp": 0.7}, lambda f: f["elb_can"] and 0.4 <= f["hp_frac"] < 0.85),
    "elb35": ({"elb_hp": 0.35}, lambda f: f["elb_can"] and f["hp_frac"] < 0.6),
    "elbexit70": ({"elb_exit": 0.7}, lambda f: f["elb_can"] and f["hp_frac"] < 0.7),
    "elbexit100": ({"elb_exit": 1.0, "elb_early": 0.85}, lambda f: f["elb_can"] and f["hp_frac"] < 0.85),
    "rest70": ({"rest_frac": 0.7}, lambda f: f["hp_frac"] < 0.7),
    "rest90": ({"rest_frac": 0.9}, lambda f: f["hp_frac"] < 0.9),
    "pray300": ({"pray_gap": 300}, lambda f: f["prayers"] > 0 and 250 < f["pray_gap"] <= 520 and f["hp_frac"] < 0.4),
    "pray800": ({"pray_gap": 800}, lambda f: f["prayers"] > 0 and 480 < f["pray_gap"] <= 800 and f["hp_frac"] < 0.4),
    "heal50": ({"heal_hp": 0.5}, lambda f: f["n_heal"] > 0 and f["hp_frac"] < 0.6),
}


def child_seed(seed, dp, rep):
    """The RNG seed of replicate `rep` at decision point `dp` of game `seed`: the same for every option (common
    random numbers: an option that does what the default does gets the default's outcome)."""
    h = hashlib.sha256(f"{seed}/{dp}/{rep}".encode()).digest()
    return int.from_bytes(h[:4], "little") & 0x7FFFFFFF


def key_hash(keys):
    return hashlib.sha256(b"".join(k.to_bytes(4, "little") for k in keys)).hexdigest()[:16]


def state_of(bot):
    return {"hp": bot.bl(nh.NLE_BL_HP), "maxhp": bot.bl(nh.NLE_BL_HPMAX), "depth": bot.bl(nh.NLE_BL_DEPTH),
            "max_depth": bot.max_depth, "xl": bot.bl(nh.NLE_BL_XP), "exp": bot.bl(nh.NLE_BL_EXP),
            "score": bot.reward, "prayers": bot.surv.prayers, "quaffs": bot.surv.quaffs, "zaps": bot.acts.zaps,
            "elb": bot.elb.elbereths, "steps": bot.steps, "kills": bot.combat.kill_count,
            "god_angry": int(bot.surv.god_angry), "pray_failed": bot.surv.pray_failed}


def rollout(bot, c, opt, horizon, record_keys=False):
    """In a child: force `opt` at this tick, play on for `horizon` turns; the outcome as a dict. record_keys: also
    the number and a hash of the keys sent (the determinism check)."""
    keys = None
    if record_keys:
        keys, orig = [], bot.raw_step

        def raw_step(code):
            keys.append(code)
            return orig(code)
        bot.raw_step = raw_step
    bot.tac.hook = None
    t0, s0 = c.t, state_of(bot)
    res = {"opt": opt, "ok": True, "first": None}
    marks, cps = [], list(CHECKPOINTS)
    try:
        if opt.startswith("v:"):                 # a policy variant: the scripted steps under changed options
            bot.opts._values.update(VARIANTS[opt[2:]][0])
            acted = False
        else:
            acted = opt != "default" and bot.tactic_start(opt, c)
            res["ok"] = acted or opt == "default"
        if acted:
            bot.pol.last_step = "tactic"
        else:
            bot.run_steps(c, after="tactic")
        res["first"] = bot.pol.last_step
        bot.after_tick(t0)
        while True:
            dt = bot.turn() - t0
            while cps and dt >= cps[0]:
                marks.append((cps.pop(0), bot.bl(nh.NLE_BL_HP)))
            if dt >= horizon:
                break
            bot.play_tick()
    except GameOver:
        pass
    s1 = state_of(bot)
    res.update(died=int(bot.done and not bot.truncated), dt=bot.turn() - t0, marks=marks,
               **{k: s1[k] - s0[k] if k not in ("hp", "maxhp", "depth", "xl", "god_angry") else s1[k] for k in s1})
    if res["died"]:
        res["death"] = (bot.death_msgs or [m for _, m in list(bot.messages)[-3:]])[-3:]
    if keys is not None:
        res.update(nkeys=len(keys), keyhash=key_hash(keys))
    return res


class Collector:
    """The tactic hook of one game: finds the decision points, forks the rollouts, writes the records."""

    def __init__(self, bot, out=None, **cfg):
        unknown = set(cfg) - set(DEFAULTS)
        if unknown:
            raise ValueError(f"unknown rollout setting(s): {sorted(unknown)}")
        self.cfg = {**DEFAULTS, **cfg}
        self.bot, self.out = bot, out
        self.n_dp, self.last_t, self.secs, self.triggered = 0, -10 ** 9, 0.0, 0
        self.root = None
        self.records = []
        bot.tac.hook = self.hook
        atexit.register(self.close)              # the parent's exit only: a child leaves by os._exit

    def trigger(self, f):
        """A decision point: a hostile next to us and we are hurt, or danger.py says the fight is a risk; or hurt
        with a hostile within 3 squares."""
        cfg = self.cfg
        if f["n_adj"] == 0:
            return f["far_within3"] > 0 and f["hp_frac"] < cfg["hp_frac"]
        return f["hp_frac"] < cfg["hp_frac"] or f["pdeath1"] >= cfg["pdeath"] or f["win_prob"] <= cfg["win_prob"]

    def hook(self, bot, c):
        cfg = self.cfg
        if cfg["max_turn"] and c.t >= cfg["max_turn"]:
            bot.truncated = True
            raise GameOver()
        if self.n_dp >= cfg["max_dp"] or self.secs >= cfg["max_secs"] or c.t - self.last_t < cfg["gap"]:
            return
        hostiles = bot.tactic_hostiles(c)
        if not hostiles and (c.hp >= c.maxhp * cfg["hp_frac"] or not c.vis):
            return
        feat = bot.tactic_features(c, hostiles)
        if not self.trigger(feat):
            return
        self.triggered += 1
        if cfg["keep"] < 1.0:
            h = hashlib.sha256(f"{bot.seed}/keep/{c.t}".encode()).digest()
            if int.from_bytes(h[:4], "little") / 2 ** 32 >= cfg["keep"]:
                return
        legal = bot.tactic_legal(c, hostiles)
        opts = [o for o in legal if cfg["options"] is None or o in cfg["options"]]
        names = VARIANTS if cfg["variants"] == "all" else cfg["variants"]
        opts += ["v:" + v for v in names if VARIANTS[v][1](feat)]
        t = time.monotonic()
        rolls = []
        for rep in range(cfg["reps"]):
            seed = child_seed(bot.seed, self.n_dp, rep)
            for opt in opts:
                r = self.spawn(c, opt, seed)
                r["rep"] = rep
                rolls.append(r)
        self.secs += time.monotonic() - t
        rec = {"seed": bot.seed, "dp": self.n_dp, "t": c.t, "feat": feat, "legal": legal,
               "adj": [(n, p[0] - c.y, p[1] - c.x) for p, n in hostiles],
               "vis": [(n, p[0] - c.y, p[1] - c.x) for p, n in c.vis][:16],
               "wands": [k for _, k in bot.attack_wands()], "rolls": rolls, "secs": round(time.monotonic() - t, 1)}
        self.n_dp += 1
        self.last_t = c.t
        self.write(rec)

    def spawn(self, c, opt, seed, record_keys=False):
        """One child: `opt` forced under RNG seed `seed` (None: the parent's RNG state, untouched)."""
        if self.root is None:
            base = "/dev/shm" if os.path.isdir("/dev/shm") else None
            self.root = tempfile.mkdtemp(prefix="rollout", dir=base)
        bot = self.bot

        def child_main(bot):
            if seed is not None:
                fork.reseed(bot, seed, lgen=seed)
            return json.dumps(rollout(bot, c, opt, self.cfg["horizon"], record_keys)).encode()

        raw = fork.fork_child(bot, child_main, root=self.root)
        for name in os.listdir(self.root):               # a killed child's directory
            shutil.rmtree(os.path.join(self.root, name), ignore_errors=True)
        if not raw or raw.startswith(b"CRASH"):
            return {"opt": opt, "crash": raw.decode(errors="replace")[-1500:] or "no answer (killed or died)"}
        return json.loads(raw)

    def write(self, rec):
        if self.out is None:
            self.records.append(rec)
            return
        with open(self.out, "a") as fh:
            fh.write(json.dumps(rec) + "\n")

    def close(self):
        if self.root is not None:
            shutil.rmtree(self.root, ignore_errors=True)


# ---------------------------------------------------------------------------------------------- command line
def play(args):
    seed, out_dir, cfg = args
    from nhbot import Bot
    t = time.monotonic()
    out = os.path.join(out_dir, f"{seed}.jsonl")
    if os.path.exists(out):
        os.remove(out)
    bot = Bot(seed=seed, character="val", rollout={"out": out_dir, **cfg})     # nhbot.tactic installs the Collector
    try:
        s = bot.run()
        col = bot.tac.hook.__self__
        info = {"seed": seed, "score": s["score"], "max_depth": s["max_depth"], "turns": s["turns"],
                "dp": col.n_dp, "triggered": col.triggered, "roll_secs": round(col.secs),
                "secs": round(time.monotonic() - t)}
    except Exception:
        import traceback
        info = {"seed": seed, "crash": traceback.format_exc()[-1500:]}
    with open(os.path.join(out_dir, "games.jsonl"), "a") as fh:
        fh.write(json.dumps(info) + "\n")
    return info


def pinned_clock():
    """Re-exec under libfaketime with regress.py's clock (NetHack reads the clock: night, moon phase, Friday 13th)."""
    sys.path.insert(0, os.getcwd())
    import regress
    if os.environ.get("FAKETIME") == regress.CLOCK:
        return
    env = dict(os.environ, FAKETIME=regress.CLOCK, TZ="UTC", LD_PRELOAD=regress.FAKETIME_LIB, DONT_FAKE_MONOTONIC="1",
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
    os.execvpe(sys.executable, [sys.executable, "-m", "tools.rollout.collect"] + sys.argv[1:], env)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", required=True, help="A:B (B exclusive)")
    ap.add_argument("--out", default=None)
    ap.add_argument("-j", type=int, default=1, help="games in parallel (the children of a game run one at a time)")
    ap.add_argument("--cfg", default="{}", help="Collector settings as JSON (collect.DEFAULTS)")
    ap.add_argument("--selftest", action="store_true", help="the isolation and determinism checks (selftest.py)")
    a = ap.parse_args()
    pinned_clock()
    lo, hi = (int(v) for v in a.seeds.split(":"))
    if a.selftest:
        from tools.rollout import selftest
        sys.exit(selftest.main(range(lo, hi), a.j))
    os.makedirs(a.out, exist_ok=True)
    import multiprocessing as mp
    cfg = json.loads(a.cfg)
    with mp.Pool(a.j) as pool:
        for info in pool.imap_unordered(play, [(s, a.out, cfg) for s in range(lo, hi)], chunksize=1):
            print(json.dumps(info), flush=True)


if __name__ == "__main__":
    main()
