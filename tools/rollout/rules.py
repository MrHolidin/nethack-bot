"""Simple rules from a rollout dataset: "when <condition>, do <option> instead of the scripted default".

    python -m tools.rollout.rules DIR [DIR ...] [--h 300] [--min-n 150]

For each option, a greedy search over conditions `feature <= t` / `feature > t` (thresholds at the feature's
deciles), then a second condition inside the best ones, maximising the deaths avoided: the sum over the decision
points of the condition of (default's death rate - option's death rate within h turns). Many conditions are
tried, so the search runs on half of the games (even seeds: discovery) and every rule it keeps is then measured
on the other half (odd seeds: confirmation) -- that column is the honest one. Intervals: bootstrap over games.
"""
import argparse

import numpy as np

from tools.rollout.analyze import boot_ci, load
from tools.rollout.train import table


def arrays(rows, feats, opt):
    """For the decision points where opt was rolled out: X, gain (default death - option death), seeds."""
    sel = [r for r in rows if opt in r["opts"]]
    X = np.array([[float(r["feat"][k]) for k in feats] for r in sel]).reshape(len(sel), len(feats))
    gain = np.array([np.mean(r["opts"][opt][1]) for r in sel])            # value = alive: option - default
    return X, gain, np.array([r["seed"] for r in sel])


def conditions(X, feats, mask, min_n):
    """Candidate conditions inside mask: (feature index, '<=' or '>', threshold, mask of the condition)."""
    for j, name in enumerate(feats):
        col = X[:, j]
        vals = np.unique(np.quantile(col[mask], np.linspace(0.1, 0.9, 9))) if mask.any() else []
        for t in vals:
            for op, m in (("<=", col <= t), (">", col > t)):
                m = m & mask
                if min_n <= m.sum() < mask.sum():
                    yield j, op, float(t), m


def describe(feats, conds):
    return " and ".join(f"{feats[j]} {op} {t:.3g}" for j, op, t in conds)


def apply(X, conds):
    m = np.ones(len(X), bool)
    for j, op, t in conds:
        m &= (X[:, j] <= t) if op == "<=" else (X[:, j] > t)
    return m


def search(X, gain, feats, min_n, top=4):
    """The best rules of one and of two conditions by total gain on these rows: [(conds, total gain)]."""
    everything = np.ones(len(X), bool)
    one = sorted(((gain[m].sum(), [(j, op, t)]) for j, op, t, m in conditions(X, feats, everything, min_n)),
                 key=lambda e: -e[0])[:top]
    two = []
    for _, c1 in one[:2]:
        m1 = apply(X, c1)
        best = max(((gain[m].sum(), c1 + [(j, op, t)]) for j, op, t, m in conditions(X, feats, m1, min_n)),
                   key=lambda e: e[0], default=None)
        if best:
            two.append(best)
    return [(c, g) for g, c in one + two]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--h", type=int, default=300)
    ap.add_argument("--min-n", type=int, default=150)
    ap.add_argument("--options", default="melee,elbereth,zap,quaff,pray,up,down,retreat")
    a = ap.parse_args()
    rows = table(load(a.dirs), a.h, 0.0)
    feats = [k for k in sorted(rows[0]["feat"]) if k != "turn"]
    n_games = len({r["seed"] for r in rows})
    print(f"{len(rows)} decision points of {n_games} games; gain = deaths within {a.h} turns avoided per 100 decision "
          f"points of the rule (option instead of default); disc = even seeds (searched), conf = odd seeds (honest)")
    for opt in a.options.split(","):
        X, gain, seeds = arrays(rows, feats, opt)
        if len(X) < 2 * a.min_n:
            continue
        disc, conf = seeds % 2 == 0, seeds % 2 == 1
        m, lo, hi = boot_ci(gain, seeds)
        print(f"\n== {opt}: legal at {len(X)} points; always taking it: {m * 100:+.2f} [{lo * 100:+.2f}, {hi * 100:+.2f}]")
        for conds, _ in search(X[disc], gain[disc], feats, a.min_n // 2):
            md, mc = apply(X[disc], conds), apply(X[conf], conds)
            d = boot_ci(gain[disc][md], seeds[disc][md])
            c = boot_ci(gain[conf][mc], seeds[conf][mc])
            print(f"   {describe(feats, conds):58s} disc n={md.sum():5d} {d[0] * 100:+6.2f}   "
                  f"conf n={mc.sum():5d} {c[0] * 100:+6.2f} [{c[1] * 100:+6.2f}, {c[2] * 100:+6.2f}]")


if __name__ == "__main__":
    main()
