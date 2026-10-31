"""Paired comparison of two result files on shared seeds (bootstrap CI on the mean difference).

Strata are defined by facts fixed at game start (alignment), never by the outcome of either arm:
selecting e.g. 'games where A had no Excalibur' conditions on A's result and biases the difference
upwards (regression to the mean).
"""
import json, sys, random, statistics as st
from eval import death_cause

ALIGN = {1: "lawful", 0: "neutral", -1: "chaotic"}


LEVEL = 0.80            # two-sided interval used for decisions (user: 80%)


def boot(d, n=4000):
    random.seed(0)
    b = sorted(st.mean(random.choices(d, k=len(d))) for _ in range(n))
    a = (1 - LEVEL) / 2
    return b[int(n * a)], b[int(n * (1 - a))]


def line(name, a, b, seeds, key):
    if len(seeds) < 2:
        return
    d = [b[s][key] - a[s][key] for s in seeds]
    lo, hi = boot(d)
    print(f"  {name:8s} {key:9s} A {st.mean(a[s][key] for s in seeds):8.1f}  B {st.mean(b[s][key] for s in seeds):8.1f}  "
          f"diff {st.mean(d):+8.1f}  {int(LEVEL*100)}% CI [{lo:+.1f}, {hi:+.1f}]  n={len(seeds)}")


if __name__ == "__main__":
    a = {r["seed"]: r for r in map(json.loads, open(sys.argv[1]))}
    b = {r["seed"]: r for r in map(json.loads, open(sys.argv[2]))}
    seeds = sorted(set(a) & set(b))
    for key in ("score", "max_depth", "turns"):
        line("all", a, b, seeds, key)
        for al, name in ALIGN.items():
            ss = [s for s in seeds if a[s].get("align") == al]
            line(name, a, b, ss, key)
    print("median score A", st.median(a[s]["score"] for s in seeds), " B", st.median(b[s]["score"] for s in seeds))
    starve = lambda r: death_cause(r["last_msgs"]) == "starvation"
    print("starvation A", sum(starve(a[s]) for s in seeds), " B", sum(starve(b[s]) for s in seeds))
