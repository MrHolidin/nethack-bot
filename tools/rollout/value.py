"""A state value for the end of a rollout: what a hero in this state goes on to score, under the scripted bot.

Why: "alive 300 turns later" overrates passive options. Elbereth below 70 % HP instead of 50 % saves 1.3 deaths
per 100 decision points in the rollouts -- and lost 1209 points a game (-18 %) in the owner's whole-game A/B
(JOURNAL_AUTO.md): the turns spent standing are turns of food and of monsters arriving with no experience gained.
So a rollout is valued by the index the session is judged by, J = score / 27000 + max depth / 11, of the whole
game: what it had at its death, or V(state at the window's end) if it is alive, where

    V(state) = E[J at the end of the game | turn, depth, max depth, XL, HP, max HP, AC, gold, prayers, kills]

is fitted on the snapshots (every 500 turns) of baseline games (`fit`: LightGBM, squared loss -- the mean, heavy
tail and all). Two hands of the same game that differ at the window's end in kills, XL, depth, HP or prayers used
get different values; equal turn counts cancel. This is one step of fitted value iteration: V is the scripted
policy's value, the rollout adds the option's first 300 turns in front of it.

    python -m tools.rollout.value fit RESULTS.jsonl-or-parts-dir [...] --out tools/rollout/value_v1.json
"""
import argparse
import glob
import json
import os

import numpy as np

FEATS = ("t", "depth", "max_depth", "xl", "hp_frac", "maxhp", "ac", "gold", "prayers", "kills")
SCORE0, DEPTH0 = 27000.0, 11.0


def j_index(score, max_depth):
    return score / SCORE0 + max_depth / DEPTH0


def vector(t, depth, max_depth, xl, hp, maxhp, ac, gold, prayers, kills):
    return [t, depth, max_depth, xl, hp / max(maxhp, 1), maxhp, ac, gold, prayers, kills]


class Value:
    """V from its json (trees in nhbot.tacticmodel's format)."""

    def __init__(self, path=None):
        path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "value_v1.json")
        with open(path) as fh:
            spec = json.load(fh)
        assert tuple(spec["features"]) == FEATS
        self.trees = [tuple(np.asarray(t[k]) for k in "ftlrv") for t in spec["trees"]]

    def __call__(self, x):
        total = 0.0
        for f, t, l, r, v in self.trees:
            i = 0
            while f[i] >= 0:
                i = l[i] if x[f[i]] <= t[i] else r[i]
            total += v[i]
        return total

    def of_rollout(self, rec, x):
        """J of the game a rollout stands for: banked at its death, V at the window's end if alive.
        rec: the decision point's record (with state0), x: one of its rolls."""
        s0 = rec["state0"]
        score, mdepth = s0["score"] + x["score"], s0["max_depth"] + x["max_depth"]
        if x["died"]:
            return j_index(score, mdepth)
        v = self(vector(rec["t"] + x["dt"], x["depth"], mdepth, x["xl"], x["hp"], x["maxhp"], x["ac"], x["gold"],
                        s0["prayers"] + x["prayers"], s0["kills"] + x["kills"]))
        return max(v, j_index(score, mdepth))         # never less than what is already banked


def games(paths):
    for p in paths:
        files = glob.glob(os.path.join(p, "*.json")) if os.path.isdir(p) else [p]
        for f in files:
            with open(f) as fh:
                if f.endswith(".jsonl"):
                    yield from (json.loads(line) for line in fh)
                else:
                    yield json.load(fh)


def fit(a):
    import lightgbm as lgb
    from tools.rollout.train import export_tree
    X, y, g = [], [], []
    for r in games(a.paths):
        if "crash" in r or not r.get("snaps"):
            continue
        target = j_index(r["score"], r["max_depth"])
        for s in r["snaps"]:
            X.append(vector(s["t"], s["dlvl"], s["max_depth"], s["xl"], s["hp"], s["maxhp"], s["ac"], s["gold"],
                            s["prayers"], s["kills"]))
            y.append(target)
            g.append(r["seed"])
    X, y, g = np.array(X, float), np.array(y), np.array(g)
    params = dict(objective="regression", learning_rate=0.05, num_leaves=16, min_data_in_leaf=200,
                  feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=10.0, verbose=-1, num_threads=8)
    te = g % 5 == 0
    m = lgb.train(params, lgb.Dataset(X[~te], y[~te]), 300)
    p = m.predict(X[te])
    r2 = 1 - ((y[te] - p) ** 2).sum() / ((y[te] - y[te].mean()) ** 2).sum()
    print(f"{len(y)} snapshots of {len(set(g))} games; held-out games: R2 {r2:.3f}, mean J {y[te].mean():.3f}, "
          f"mean prediction {p.mean():.3f}")
    m = lgb.train(params, lgb.Dataset(X, y), 300)
    trees = []
    for t in m.dump_model()["tree_info"]:
        arr = {k: [] for k in "ftlrv"}
        export_tree(t["tree_structure"], arr)
        trees.append(arr)
    with open(a.out, "w") as fh:
        json.dump({"features": FEATS, "trees": trees, "meta": {"snapshots": len(y), "games": len(set(g)), "r2": r2}},
                  fh, separators=(",", ":"))
    imp = sorted(zip(m.feature_importance("gain"), FEATS), reverse=True)
    print("importance (gain):", ", ".join(f"{n} {v / sum(i for i, _ in imp) * 100:.0f}%" for v, n in imp))
    print("wrote", a.out, os.path.getsize(a.out) // 1024, "KB")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fit"])
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--out", required=True)
    fit(ap.parse_args())
