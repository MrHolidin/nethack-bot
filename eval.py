"""Run N games in parallel, write jsonl, print summary."""
import argparse, json, multiprocessing as mp, statistics as st, time, collections, re, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def play(args):
    seed, kw = args
    from nhbot import Bot
    t = time.monotonic()
    try:
        s = Bot(seed=seed, **kw).run()
    except Exception as e:  # keep the batch going, record crash
        import traceback
        return {"seed": seed, "crash": traceback.format_exc()[-800:], "score": 0, "max_depth": 0}
    s["secs"] = round(time.monotonic() - t, 1)
    return s


def _child(seed, kw, conn):
    conn.send(play((seed, kw)))
    conn.close()


def play_all(seeds, kw, j):
    """play() for every seed, j at a time, each game in a process of its own: a game that kills its process (a
    crash in the game's C code: 79670, a bus error) is recorded as a crash -- under a Pool its task was lost and
    the pool waited for it for ever, the shard never finished. Waits on the pipes and the process sentinels only
    (no timed sleep: libfaketime breaks those)."""
    from multiprocessing.connection import wait
    ctx = mp.get_context("fork")
    todo, running, out = list(seeds), {}, {}
    while todo or running:
        while todo and len(running) < j:
            s = todo.pop(0)
            r, w = ctx.Pipe(duplex=False)
            p = ctx.Process(target=_child, args=(s, kw, w))
            p.start()
            w.close()
            running[s] = (p, r)
        ready = set(wait([o for p, r in running.values() for o in (r, p.sentinel)]))
        for s, (p, r) in list(running.items()):
            if r in ready:
                try:
                    out[s] = r.recv()
                except EOFError:
                    out[s] = None
            elif p.sentinel not in ready:
                continue
            p.join()
            if out.get(s) is None:
                out[s] = {"seed": s, "crash": f"the game's process died (exit code {p.exitcode})",
                          "score": 0, "max_depth": 0}
            del running[s]
    return [out[s] for s in seeds]


def death_cause(msgs):
    txt = " ".join(msgs[-4:])
    for pat, lab in [(r"faint from lack of food|starve", "starvation"),
                     (r"Keystone Kop|You murderer|under arrest", "angered law"),
                     (r"You hit it|You miss it|It bites|It hits", "unseen"),
                     (r"Rotten food", "rotten food"),
                     ]:
        if re.search(pat, txt):
            return lab
    m = re.findall(r"The ([a-z \-]+?) (?:hits|bites|stings|kicks|butts|touches|claws|thrusts|swings|shoots|zaps|breathes|explodes|casts)", txt)
    if m:
        return m[-1]
    return "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=40)
    ap.add_argument("--start", type=int, default=1000)
    ap.add_argument("--char", default="@")
    ap.add_argument("--out", default="results.jsonl")
    ap.add_argument("-j", type=int, default=2)
    ap.add_argument("--kw", default="{}", help="extra Bot kwargs as JSON")
    a = ap.parse_args()
    kw = {"character": a.char, **json.loads(a.kw)}
    t = time.monotonic()
    res = play_all(list(range(a.start, a.start + a.n)), kw, a.j)
    with open(a.out, "w") as f:
        for r in res:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    crashes = [r for r in res if "crash" in r]
    ok = [r for r in res if "crash" not in r]
    sc = [r["score"] for r in ok]
    dp = [r["max_depth"] for r in ok]
    print(f"games {len(res)}  crashes {len(crashes)}  wall {time.monotonic()-t:.0f}s")
    print(f"score  mean {st.mean(sc):.0f}  median {st.median(sc):.0f}  max {max(sc):.0f}")
    print(f"depth  mean {st.mean(dp):.2f}  median {st.median(dp)}  max {max(dp)}  hist {sorted(collections.Counter(dp).items())}")
    print(f"turns  median {st.median([r['turns'] for r in ok])}   xl median {st.median([r['xl'] for r in ok])}")
    print("truncated:", sum(r["truncated"] for r in ok))
    print("causes:", collections.Counter(death_cause(r["last_msgs"]) for r in ok if not r["truncated"]).most_common(12))
    print("died in mines:", sum(1 for r in ok if r.get("dnum") == 2 and not r["truncated"]), "/", len(ok))
    byrole = collections.defaultdict(list)
    for r in ok:
        byrole[r["role"]].append(r["score"])
    print("by role:", {k: (len(v), round(st.median(v))) for k, v in sorted(byrole.items(), key=lambda kv: -st.median(kv[1]))})
    for c in crashes[:3]:
        print("CRASH seed", c["seed"], c["crash"])


if __name__ == "__main__":
    main()
