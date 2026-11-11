#!/usr/bin/env python3
"""nhq: the game farm on the evaluation machine -- one scheduler for every agent's runs.

A job is (commit, seeds, options); the daemon plays its games one process each, at most WORKERS at a time over all
jobs: the job with the lowest prio number first, among equals the one with the fewest games running (a 20-game
smoke test never waits behind a 1000-game A/B). Games run under the pinned clock of CI (regress.py).

    nhq submit --ref REF --tag TAG [--start S] [-n N] [--kw JSON] [--char val] [--prio 5]
    nhq status                      jobs running and queued
    nhq wait TAG [TAG ...]          block until these jobs are done
    nhq cancel TAG
    nhq cmp A B                     paired comparison of two finished jobs (B - A), both objectives
    nhq show TAG                    one job's numbers
    nhq run REF -- CMD ...          run a command in a checkout of REF (pinned clock, the venv's python)
    nhq daemon                      the scheduler (one instance)

REF is anything the bare repository /workspace/nethack.git resolves (a branch pushed there, a sha).
Results: /workspace/nh/results/TAG.jsonl, one summary per game (eval.py's format), sorted by seed.
"""
import argparse, glob, json, math, os, shutil, subprocess, sys, time

ROOT = "/workspace/nh"
GIT = "/workspace/nethack.git"
PY = "/workspace/venv/bin/python"
Q, RES, SRC = (os.path.join(ROOT, d) for d in ("queue", "results", "src"))
WORKERS = int(os.environ.get("NHQ_WORKERS", 104))
GAME_TIMEOUT = 5400                      # seconds of wall clock before a game is killed and counted as a crash
CLOCK_ENV = {"TZ": "UTC", "FAKETIME": "2026-10-14 12:00:00", "DONT_FAKE_MONOTONIC": "1",
             "LD_PRELOAD": "/usr/lib/x86_64-linux-gnu/faketime/libfaketime.so.1"}
SCORE0, DEPTH0 = 27000.0, 11.0           # the index J = score / SCORE0 + depth / DEPTH0 (relative gains, summed)


def checkout(ref):
    """The tree of ref under SRC/<sha> (exported once); returns (sha, path)."""
    sha = subprocess.check_output(["git", "--git-dir", GIT, "rev-parse", "--verify", ref + "^{commit}"],
                                  text=True).strip()
    path = os.path.join(SRC, sha)
    if not os.path.isdir(path):
        tmp = path + ".tmp%d" % os.getpid()
        os.makedirs(tmp)
        ar = subprocess.Popen(["git", "--git-dir", GIT, "archive", sha], stdout=subprocess.PIPE)
        subprocess.check_call(["tar", "-x", "-C", tmp], stdin=ar.stdout)
        ar.wait()
        os.rename(tmp, path)
    return sha, path


# ---------------------------------------------------------------------------------------------- one game
def play(a):
    sys.path.insert(0, os.getcwd())
    t = time.monotonic()
    kw = json.loads(a.kw)
    try:
        from nhbot import Bot
        s = Bot(seed=a.seed, **kw).run()
    except Exception:
        import traceback
        s = {"seed": a.seed, "crash": traceback.format_exc()[-1500:], "score": 0, "max_depth": 0}
    s["secs"] = round(time.monotonic() - t, 1)
    with open(a.out + ".tmp", "w") as f:
        f.write(json.dumps(s, ensure_ascii=False))
    os.rename(a.out + ".tmp", a.out)


# ---------------------------------------------------------------------------------------------- daemon
class Job:
    def __init__(self, tag, spec):
        self.tag, self.spec = tag, spec
        self.parts = os.path.join(RES, tag + ".parts")
        os.makedirs(self.parts, exist_ok=True)
        seeds = list(range(spec["start"], spec["start"] + spec["n"]))
        self.todo = [s for s in seeds if not os.path.exists(self.part(s))]
        self.n, self.running, self.t0 = len(seeds), {}, time.time()

    def part(self, seed):
        return os.path.join(self.parts, "%d.json" % seed)

    def start(self):
        seed = self.todo.pop(0)
        kw = json.dumps({"character": self.spec["char"], **self.spec["kw"]})
        p = subprocess.Popen([PY, os.path.join(ROOT, "bin", "nhq.py"), "play", "--seed", str(seed), "--kw", kw,
                              "--out", self.part(seed)], cwd=os.path.join(SRC, self.spec["sha"]),
                             env=dict(os.environ, **CLOCK_ENV), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.running[seed] = (p, time.time())

    def reap(self):
        for seed, (p, t0) in list(self.running.items()):
            rc = p.poll()
            if rc is None and time.time() - t0 > GAME_TIMEOUT:
                p.kill()
                rc = p.wait()
                why = "timeout: killed after %d s" % GAME_TIMEOUT
            elif rc is None:
                continue
            else:
                why = "the game's process died (exit code %s)" % rc
            if not os.path.exists(self.part(seed)):
                with open(self.part(seed), "w") as f:
                    json.dump({"seed": seed, "crash": why, "score": 0, "max_depth": 0}, f)
            del self.running[seed]

    def finish(self):
        rows = []
        for f in glob.glob(os.path.join(self.parts, "*.json")):
            rows.append(json.load(open(f)))
        rows.sort(key=lambda r: r["seed"])
        with open(os.path.join(RES, self.tag + ".jsonl.tmp"), "w") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.rename(os.path.join(RES, self.tag + ".jsonl.tmp"), os.path.join(RES, self.tag + ".jsonl"))
        shutil.rmtree(self.parts)
        os.makedirs(os.path.join(Q, "done"), exist_ok=True)
        os.rename(os.path.join(Q, self.tag + ".json"), os.path.join(Q, "done", self.tag + ".json"))


def daemon(a):
    for d in (Q, RES, SRC):
        os.makedirs(d, exist_ok=True)
    jobs = {}
    while True:
        for f in glob.glob(os.path.join(Q, "*.json")):
            tag = os.path.basename(f)[:-5]
            if tag not in jobs:
                try:
                    jobs[tag] = Job(tag, json.load(open(f)))
                except Exception as e:                     # a spec half written: next round
                    print("bad spec", f, e, flush=True)
        for f in glob.glob(os.path.join(Q, "*.cancel")):
            tag = os.path.basename(f)[:-7]
            j = jobs.pop(tag, None)
            if j:
                for p, _ in j.running.values():
                    p.kill()
                shutil.rmtree(j.parts, ignore_errors=True)
                if os.path.exists(os.path.join(Q, tag + ".json")):
                    os.remove(os.path.join(Q, tag + ".json"))
            os.remove(f)
        for tag, j in list(jobs.items()):
            j.reap()
            if not j.todo and not j.running:
                j.finish()
                del jobs[tag]
                print(time.strftime("%H:%M:%S"), "done", tag, flush=True)
        busy = sum(len(j.running) for j in jobs.values())
        while busy < WORKERS:
            cand = [j for j in jobs.values() if j.todo]
            if not cand:
                break
            min(cand, key=lambda j: (j.spec["prio"], len(j.running), j.t0)).start()
            busy += 1
        st = {"t": time.time(), "workers": WORKERS, "busy": busy,
              "jobs": [{"tag": j.tag, "prio": j.spec["prio"], "n": j.n, "running": len(j.running),
                        "left": len(j.todo), "done": j.n - len(j.todo) - len(j.running),
                        "age": round(time.time() - j.t0), "sha": j.spec["sha"][:8], "kw": j.spec["kw"]}
                       for j in sorted(jobs.values(), key=lambda j: (j.spec["prio"], j.t0))]}
        with open(os.path.join(ROOT, "status.json.tmp"), "w") as f:
            json.dump(st, f)
        os.rename(os.path.join(ROOT, "status.json.tmp"), os.path.join(ROOT, "status.json"))
        time.sleep(2)


# ---------------------------------------------------------------------------------------------- client
def submit(a):
    if os.path.exists(os.path.join(RES, a.tag + ".jsonl")) or os.path.exists(os.path.join(Q, a.tag + ".json")):
        sys.exit("tag %s exists already: pick another" % a.tag)
    sha, _ = checkout(a.ref)
    spec = {"sha": sha, "ref": a.ref, "start": a.start, "n": a.n, "kw": json.loads(a.kw), "char": a.char,
            "prio": a.prio, "submitted": time.time()}
    os.makedirs(Q, exist_ok=True)
    with open(os.path.join(Q, a.tag + ".json.tmp"), "w") as f:
        json.dump(spec, f)
    os.rename(os.path.join(Q, a.tag + ".json.tmp"), os.path.join(Q, a.tag + ".json"))
    print("queued %s: %s seeds %d..%d kw %s prio %d" % (a.tag, sha[:8], a.start, a.start + a.n - 1, a.kw, a.prio))


def status(a):
    st = json.load(open(os.path.join(ROOT, "status.json")))
    print("workers %d busy %d  (status %ds old)" % (st["workers"], st["busy"], time.time() - st["t"]))
    for j in st["jobs"]:
        print("  %-28s prio %d  done %4d/%-4d running %3d  age %5ds  %s %s" % (
            j["tag"], j["prio"], j["done"], j["n"], j["running"], j["age"], j["sha"], json.dumps(j["kw"]) if j["kw"] else ""))


def wait(a):
    while not all(os.path.exists(os.path.join(RES, t + ".jsonl")) for t in a.tags):
        time.sleep(5)
    print("done:", " ".join(a.tags))


def cancel(a):
    open(os.path.join(Q, a.tag + ".cancel"), "w").close()


def run(a):
    _, path = checkout(a.ref)
    env = dict(os.environ, **CLOCK_ENV)
    env["PATH"] = os.path.dirname(PY) + ":" + env["PATH"]
    os.chdir(path)
    argv = a.argv[1:] if a.argv[:1] == ["--"] else a.argv
    os.execvpe(argv[0], argv, env)


def load(tag):
    path = tag if os.path.exists(tag) else os.path.join(RES, tag + ".jsonl")
    return {r["seed"]: r for r in map(json.loads, open(path))}


def boot(d, level=0.80, n=4000):
    import numpy as np
    d = np.asarray(d, dtype=float)
    rng = np.random.default_rng(0)
    means = d[rng.integers(0, len(d), size=(n, len(d)))].mean(axis=1)
    lo, hi = np.quantile(means, [(1 - level) / 2, 1 - (1 - level) / 2])
    return float(lo), float(hi)


def describe(rows):
    import statistics as st
    sc = [r["score"] for r in rows]
    dp = [r["max_depth"] for r in rows]
    ok = [r for r in rows if "crash" not in r]
    return ("n %d  score mean %.0f median %.0f  depth mean %.2f  crashes %d  truncated %d  turns %.0f  secs/game %.0f"
            % (len(rows), st.mean(sc), st.median(sc), st.mean(dp), len(rows) - len(ok),
               sum(bool(r.get("truncated")) for r in ok), st.mean(r["turns"] for r in ok) if ok else 0,
               st.mean(r.get("secs", 0) for r in rows)))


def show(a):
    print(a.tag, describe(list(load(a.tag).values())))


def cmp(a):
    import statistics as st
    A, B = load(a.a), load(a.b)
    seeds = sorted(set(A) & set(B))
    print("A %-24s %s" % (a.a, describe([A[s] for s in seeds])))
    print("B %-24s %s" % (a.b, describe([B[s] for s in seeds])))
    val = {"score": lambda r: r["score"], "depth": lambda r: r["max_depth"],
           "J": lambda r: r["score"] / SCORE0 + r["max_depth"] / DEPTH0,
           "log10": lambda r: math.log10(r["score"] + 10)}
    for name, f in val.items():
        d = [f(B[s]) - f(A[s]) for s in seeds]
        lo, hi = boot(d)
        lo2, hi2 = boot(d, 0.95)
        fmt = "%+.0f" if name == "score" else "%+.3f"
        print(("  %-6s diff " + fmt + "  80%% CI [" + fmt + ", " + fmt + "]  95%% CI [" + fmt + ", " + fmt + "]%s")
              % (name, st.mean(d), lo, hi, lo2, hi2, "  <-- " + ("WIN" if lo > 0 else "LOSS") if lo > 0 or hi < 0 else ""))
    same = sum(A[s]["score"] == B[s]["score"] and A[s].get("turns") == B[s].get("turns") for s in seeds)
    print("  games changed: %d of %d" % (len(seeds) - same, len(seeds)))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="sub", required=True)
    p = sub.add_parser("play"); p.add_argument("--seed", type=int); p.add_argument("--kw"); p.add_argument("--out")
    p.set_defaults(f=play)
    sub.add_parser("daemon").set_defaults(f=daemon)
    p = sub.add_parser("submit")
    p.add_argument("--ref", required=True); p.add_argument("--tag", required=True)
    p.add_argument("--start", type=int, default=300000); p.add_argument("-n", type=int, default=1000)
    p.add_argument("--kw", default="{}"); p.add_argument("--char", default="val")
    p.add_argument("--prio", type=int, default=5)
    p.set_defaults(f=submit)
    sub.add_parser("status").set_defaults(f=status)
    p = sub.add_parser("wait"); p.add_argument("tags", nargs="+"); p.set_defaults(f=wait)
    p = sub.add_parser("cancel"); p.add_argument("tag"); p.set_defaults(f=cancel)
    p = sub.add_parser("show"); p.add_argument("tag"); p.set_defaults(f=show)
    p = sub.add_parser("cmp"); p.add_argument("a"); p.add_argument("b"); p.set_defaults(f=cmp)
    p = sub.add_parser("run"); p.add_argument("ref"); p.add_argument("argv", nargs=argparse.REMAINDER)
    p.set_defaults(f=run)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
