"""One question to a rollout dataset: how does option X do against the default where <condition> holds?

    python -m tools.rollout.cells DIR [DIR ...] --opt up --where "win_prob < 0.6 and up_cost < 16"
    python -m tools.rollout.cells DIR ... --opt elbereth --script melee --where "hp_frac >= 0.5" --by win_prob:0,0.3,0.6,0.85,1.01

--where   a Python expression over the features (nhbot.tactic.tactic_features) and `script` (the step the scripted
          bot took first), `depth_cls` etc. are not there: use the feature names
--script  only the decision points where the scripted step is this one (melee, elbereth, pray, ...)
--by      FEATURE:edge,edge,...  one line per bin of that feature
Per line: pairs, games (the intervals resample games: 100 pairs from 3 games are 3 observations), the default's
deaths within 50 and 300 turns and the option's difference (percentage points), the difference in the game's
value J x1000 (tools/rollout/value.py; only records that carry their start state), score gained in the window.
"""
import argparse

import numpy as np

from tools.rollout.analyze import boot_ci, died_by, load


def pairs_of(recs, opt, script=None):
    """(record, default roll, option roll) for every replicate where both exist and the option was really done
    (not where the scripted step is the option itself)."""
    out = []
    for r in recs:
        d = {x["rep"]: x for x in r["rolls"] if x["opt"] == "default"}
        for x in r["rolls"]:
            if x["opt"] != opt or x["rep"] not in d or not x.get("ok", True) or x.get("alias"):
                continue
            if script is not None and d[x["rep"]].get("first") != script:
                continue
            out.append((r, d[x["rep"]], x))
    return out


def line(name, ps):
    if not ps:
        print(f"{name:44s} n=   0")
        return
    g = [p[0]["seed"] for p in ps]
    cells = []
    for h in (50, 300):
        m, lo, hi = boot_ci([died_by(p[2], h) - died_by(p[1], h) for p in ps], g)
        cells.append(f"{np.mean([died_by(p[1], h) for p in ps]) * 100:5.1f}% {m * 100:+6.1f} [{lo * 100:+6.1f}, {hi * 100:+6.1f}]")
    uj = [(p[2]["uj"] - p[1]["uj"], p[0]["seed"]) for p in ps if "uj" in p[2] and "uj" in p[1]]
    js = ""
    if uj:
        m, lo, hi = boot_ci([u[0] for u in uj], [u[1] for u in uj])
        js = f"{m * 1000:+5.0f} [{lo * 1000:+5.0f}, {hi * 1000:+5.0f}] ({len(uj)})"
    sc = boot_ci([p[2]["score"] - p[1]["score"] for p in ps], g)
    print(f"{name:44s} n={len(ps):5d} games={len(set(g)):4d}  {cells[0]}  {cells[1]}  {js:28s} {sc[0]:+6.0f} [{sc[1]:+6.0f}, {sc[2]:+6.0f}]")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--opt", required=True)
    ap.add_argument("--where", default="True")
    ap.add_argument("--script", default=None)
    ap.add_argument("--by", default=None)
    a = ap.parse_args()
    cond = compile(a.where, "<where>", "eval")
    ps = [p for p in pairs_of(load(a.dirs), a.opt, a.script)
          if eval(cond, {}, dict(p[0]["feat"], script=p[1].get("first")))]          # noqa: S307 -- our own CLI
    print(f"{a.opt} - default where {a.where}" + (f", script = {a.script}" if a.script else ""))
    print(f"{'':44s} {'pairs':>7s} {'':10s}  {'dead<=50: default, diff [95% CI]':32s}  {'dead<=300: default, diff':32s}  "
          f"{'J x1000 [95% CI] (n)':28s} {'score':>6s}")
    line("all", ps)
    if a.by:
        feat, edges = a.by.split(":")
        edges = [float(e) for e in edges.split(",")]
        for lo, hi in zip(edges, edges[1:]):
            line(f"{feat} in [{lo:g}, {hi:g})", [p for p in ps if lo <= p[0]["feat"][feat] < hi])


if __name__ == "__main__":
    main()
