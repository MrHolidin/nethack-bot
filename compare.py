"""Paired comparison of two result files on shared seeds (bootstrap CI on mean diff)."""
import json, sys, random, statistics as st
from eval import death_cause
a = {r["seed"]: r for r in map(json.loads, open(sys.argv[1]))}
b = {r["seed"]: r for r in map(json.loads, open(sys.argv[2]))}
seeds = sorted(set(a) & set(b))
for key in ("score", "max_depth"):
    d = [b[s][key] - a[s][key] for s in seeds]
    random.seed(0)
    boots = sorted(st.mean(random.choices(d, k=len(d))) for _ in range(4000))
    print(f"{key:9s} A {st.mean(a[s][key] for s in seeds):7.1f}  B {st.mean(b[s][key] for s in seeds):7.1f}  "
          f"diff {st.mean(d):+7.1f}  95% CI [{boots[100]:+.1f}, {boots[3900]:+.1f}]  n={len(seeds)}")
starve = lambda r: death_cause(r["last_msgs"]) == "starvation"
print("starvation A", sum(starve(a[s]) for s in seeds), " B", sum(starve(b[s]) for s in seeds))
