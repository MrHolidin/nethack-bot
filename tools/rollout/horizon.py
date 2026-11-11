"""How a verdict depends on the horizon: deaths and score of each option against the default, by turns since the
decision (a dataset collected with a long `horizon`, e.g. 3000).

    python -m tools.rollout.horizon DIR [DIR ...]

A sustained variant that slows the game down (more Elbereth, more resting) looks good at 300 turns -- fewer
deaths -- and what it costs (experience not gained, turns of food) only shows later. Per horizon h: deaths by h
(percentage points, option - default) and score gained by h (a game dead before h keeps what it had), paired on the
replicate's seed, 95 % bootstrap intervals over games.
"""
import argparse
from collections import defaultdict

import numpy as np

from tools.rollout.analyze import boot_ci, load
from tools.rollout.value import Value

HS = (50, 100, 300, 500, 1000, 1500, 2000, 3000)


def at(x, h):
    """(dead by h, score gained by h) of a roll."""
    dead = int(bool(x["died"]) and x["dt"] < h)
    score = next((m[2] for m in x["marks"] if m[0] == h and len(m) > 2), None)
    return dead, x["score"] if score is None or dead else score


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    a = ap.parse_args()
    recs = load(a.dirs)
    longest = max(x["dt"] for r in recs for x in r["rolls"])
    hs = [h for h in HS if h <= longest + 5]
    pairs = defaultdict(list)                    # option -> [(seed, default roll, option roll)]
    value = Value()
    for r in recs:
        d = {x["rep"]: x for x in r["rolls"] if x["opt"] == "default"}
        for x in r["rolls"]:
            if "state0" in r and "u300" not in x:
                x["u300"] = value.at_300(r, x)
        for x in r["rolls"]:
            if x["opt"] != "default" and x["rep"] in d and x.get("ok", True) and not x.get("alias"):
                pairs[x["opt"]].append((r["seed"], d[x["rep"]], x))
    print(f"{len(recs)} decision points of {len({r['seed'] for r in recs})} games")
    for o, ps in sorted(pairs.items(), key=lambda t: -len(t[1])):
        g = [p[0] for p in ps]
        print(f"\n{o}  ({len(ps)} pairs)")
        print(f"  {'h':>5s} {'default dead %':>15s} {'deaths diff pp [95% CI]':>30s} {'default score':>14s} "
              f"{'score diff [95% CI]':>32s}")
        for h in hs:
            dd, do = zip(*[(at(p[1], h), at(p[2], h)) for p in ps])
            death = boot_ci([b[0] - a_[0] for a_, b in zip(dd, do)], g)
            score = boot_ci([b[1] - a_[1] for a_, b in zip(dd, do)], g)
            print(f"  {h:5d} {np.mean([v[0] for v in dd]) * 100:15.2f} "
                  f"{death[0] * 100:+10.2f} [{death[1] * 100:+7.2f}, {death[2] * 100:+7.2f}] "
                  f"{np.mean([v[1] for v in dd]):14.0f} {score[0]:+12.0f} [{score[1]:+8.0f}, {score[2]:+8.0f}]")
        # the label check: what a 300-turn rollout would have said (u300) against the whole long window (uj)
        both = [(p[0], p[2]["u300"] - p[1]["u300"], p[2]["uj"] - p[1]["uj"]) for p in ps
                if p[1].get("u300") is not None and p[2].get("u300") is not None and "uj" in p[1] and "uj" in p[2]]
        if both:
            gg = [b[0] for b in both]
            a300, along = boot_ci([b[1] for b in both], gg), boot_ci([b[2] for b in both], gg)
            print(f"  value in J x1000 ({len(both)} pairs): the 300-turn label {a300[0] * 1000:+.0f} "
                  f"[{a300[1] * 1000:+.0f}, {a300[2] * 1000:+.0f}]   the whole window {along[0] * 1000:+.0f} "
                  f"[{along[1] * 1000:+.0f}, {along[2] * 1000:+.0f}]")


if __name__ == "__main__":
    main()
