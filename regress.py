"""Regression check for refactors that must not change behaviour.

Plays a fixed set of seeds with the default configuration under a pinned clock (as in CI) and records,
per game, the outcome and a hash of every key sent to the game. Refactor commits are checked against a
golden file recorded from the code before the refactor.

  python regress.py record [--out golden.json] [-n 32] [--start 61000]
  python regress.py check  [--golden golden.json] [--level strict|outcome]

strict:  the key sequence is identical (nothing changed, not even free actions such as menus or farlook)
outcome: score, turns, depth, XL and the last messages are identical (for changes that drop free actions)
"""
import argparse, hashlib, json, multiprocessing as mp, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
FAKETIME_LIB = "/usr/lib/x86_64-linux-gnu/faketime/libfaketime.so.1"
CLOCK = "@2026-10-14 12:00:00"           # same as .github/workflows/eval.yml
OUTCOME = ("score", "turns", "max_depth", "xl", "last_msgs", "truncated")


def ensure_pinned_clock():
    """NetHack reads the clock (night, moon phase, Friday 13th): re-exec under libfaketime."""
    if os.environ.get("FAKETIME") == CLOCK:
        return
    if not os.path.exists(FAKETIME_LIB):
        sys.exit(f"libfaketime not found ({FAKETIME_LIB}); apt-get install faketime")
    env = dict(os.environ, FAKETIME=CLOCK, TZ="UTC", LD_PRELOAD=FAKETIME_LIB)
    os.execvpe(sys.executable, [sys.executable] + sys.argv, env)


def play(seed):
    sys.path.insert(0, HERE)
    from bot import Bot
    h, n = hashlib.sha256(), [0]
    orig = Bot.raw_step

    def raw_step(self, code):
        h.update(code.to_bytes(4, "little"))
        n[0] += 1
        return orig(self, code)

    Bot.raw_step = raw_step
    t = time.time()
    try:
        s = Bot(seed=seed, character="val").run()
    except Exception:
        import traceback
        return seed, {"crash": traceback.format_exc()[-1500:]}
    out = {k: s[k] for k in OUTCOME}
    out.update(steps=s["steps"], keys=n[0], keyhash=h.hexdigest()[:16], secs=round(time.time() - t, 1))
    return seed, out


def run(seeds, jobs):
    with mp.Pool(jobs) as pool:
        return dict(pool.map(play, seeds, chunksize=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("record", "check"))
    ap.add_argument("--golden", "--out", dest="golden", default=os.path.join(HERE, "golden.json"))
    ap.add_argument("-n", type=int, default=32)
    ap.add_argument("--start", type=int, default=61000)
    ap.add_argument("-j", type=int, default=os.cpu_count())
    ap.add_argument("--level", choices=("strict", "outcome"), default="strict")
    a = ap.parse_args()
    ensure_pinned_clock()
    t = time.time()
    if a.mode == "record":
        res = run(range(a.start, a.start + a.n), a.j)
        json.dump({str(k): v for k, v in sorted(res.items())}, open(a.golden, "w"), indent=1)
        bad = [k for k, v in res.items() if "crash" in v]
        print(f"recorded {len(res)} games in {time.time() - t:.0f}s; crashes: {bad}")
        return
    gold = {int(k): v for k, v in json.load(open(a.golden)).items()}
    res = run(sorted(gold), a.j)
    fails = []
    for seed in sorted(gold):
        g, r = gold[seed], res[seed]
        if "crash" in r:
            fails.append((seed, "CRASH " + r["crash"]))
            continue
        diff = [k for k in OUTCOME if g[k] != r[k]]
        if a.level == "strict" and g["keyhash"] != r["keyhash"]:
            diff.append(f"keys ({g['keys']} -> {r['keys']})")
        if diff:
            fails.append((seed, f"{', '.join(diff)}: score {g['score']} -> {r['score']}, "
                                f"turns {g['turns']} -> {r['turns']}"))
    print(f"{a.level}: {len(gold) - len(fails)}/{len(gold)} identical  ({time.time() - t:.0f}s)")
    for seed, why in fails:
        print(f"  seed {seed}: {why}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
