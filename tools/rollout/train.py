"""Fit the chooser of `tactic_model` on rollout datasets and say what it is worth on held-out games.

    /workspace/agents/rl/venv/bin/python -m tools.rollout.train DIR [DIR ...] --out nhbot/data/tactic_v1.json

Per option other than 'default', a small gradient-boosted forest (LightGBM, squared loss) predicts the option's
advantage over the default at a decision point: the paired difference of the rollout value (same replicate seed),
value = alive after `--h` turns (+ `--hp-w` x the final HP fraction, 0 by default). The policy: take the legal
option with the largest predicted advantage if it exceeds the option's margin, else the default.

Validation is by game: the games with seed % K == fold are held out; the policy picked by the model fitted on the
others is scored there with the rollouts of the option it picks -- they played no part in the fit, so the mean
difference to the default's rollouts is an unbiased estimate of what the choice changes (per decision point;
bootstrap over games). Margins are chosen on the training folds only (inner out-of-fold predictions).
The file written is fitted on everything; nhbot/tacticmodel.py reads it with numpy alone.
"""
import argparse
import json
import os

import numpy as np

from tools.rollout.analyze import boot_ci, died_by, load

EXCLUDE = ("turn",)                       # features left out of the model (the game clock: a proxy, not a cause)
PARAMS = dict(objective="regression", learning_rate=0.05, num_leaves=6, min_data_in_leaf=150, feature_fraction=0.8,
              bagging_fraction=0.8, bagging_freq=1, lambda_l2=5.0, verbose=-1, num_threads=4)
ROUNDS = 120
MARGINS = (0.0, 0.01, 0.02, 0.03, 0.05, 0.08)


SCORE_C = 30000.0                         # expected score still to come for a hero alive (base_d1 + base_d2: 27k at
                                          # depth 1-5, 35-55k at depth 8-21): score gained now counts 1 / SCORE_C


def value(x, h, hp_w):
    """The rollout's value: alive after h turns, plus the score it gained in the window over SCORE_C (so that an
    option which only slows the game down -- fewer deaths per turn, less progress -- is not a gain), plus
    hp_w x the final HP fraction."""
    alive = 1 - died_by(x, h)
    return alive + x["score"] / SCORE_C + (hp_w * x["hp"] / max(x["maxhp"], 1) if alive and hp_w else 0.0)


def table(recs, h, hp_w, min_ok=1):
    """Per decision point: features, and per option the mean value over its replicates and the paired differences
    to the default, replicate by replicate."""
    rows = []
    for r in recs:
        by = {}
        for x in r["rolls"]:
            by.setdefault(x["opt"], {})[x["rep"]] = x
        if "default" not in by:
            continue
        d = by["default"]
        opts = {}
        for o, xs in by.items():
            reps = [k for k in xs if k in d and (o == "default" or xs[k]["ok"])]
            if not reps:
                continue
            v = [value(xs[k], h, hp_w) for k in reps]
            dv = [value(xs[k], h, hp_w) - value(d[k], h, hp_w) for k in reps]
            opts[o] = (float(np.mean(v)), dv)
        rows.append({"seed": r["seed"], "feat": r["feat"], "opts": opts, "legal": r["legal"]})
    return rows


def fit_option(rows, feats, opt, rounds=ROUNDS, seed=0):
    import lightgbm as lgb
    X, y = [], []
    for r in rows:
        if opt in r["opts"]:
            for dv in r["opts"][opt][1]:
                X.append([float(r["feat"][k]) for k in feats])
                y.append(dv)
    if len(y) < 400:
        return None
    return lgb.train(dict(PARAMS, seed=seed), lgb.Dataset(np.array(X), np.array(y)), rounds)


def predict_all(models, rows, feats):
    X = np.array([[float(r["feat"][k]) for k in feats] for r in rows])
    return {o: m.predict(X) for o, m in models.items()}


def policy_value(rows, preds, margins):
    """Per decision point: value of the option the policy picks minus the default's; and what it picked."""
    diffs, picks = [], []
    for i, r in enumerate(rows):
        best, best_adv = "default", 0.0
        for o in preds:
            if o in r["opts"]:
                adv = preds[o][i] - margins.get(o, 0.0)
                if adv > best_adv:
                    best, best_adv = o, adv
        diffs.append(r["opts"][best][0] - r["opts"]["default"][0])
        picks.append(best)
    return np.array(diffs), picks


def choose_margins(rows, feats, options, folds=4):
    """Per option the margin that maximises the out-of-fold gain of 'take it when predicted advantage > margin'
    (over the rows where it is legal), from fits that never saw the rows they score."""
    seeds = np.array([r["seed"] for r in rows])
    oof = {o: np.zeros(len(rows)) for o in options}
    for f in range(folds):
        tr = [r for r, s in zip(rows, seeds) if s % folds != f]
        te_idx = [i for i, s in enumerate(seeds) if s % folds == f]
        models = {o: m for o in options if (m := fit_option(tr, feats, o)) is not None}
        p = predict_all(models, [rows[i] for i in te_idx], feats)
        for o in models:
            oof[o][te_idx] = p[o]
    margins = {}
    for o in options:
        best, best_gain = None, 0.0
        for m in MARGINS:
            gain = sum(np.mean(r["opts"][o][1]) for i, r in enumerate(rows) if o in r["opts"] and oof[o][i] > m)
            if gain > best_gain:
                best, best_gain = m, gain
        margins[o] = best                        # None: never worth taking out of fold -> the option is dropped
    return margins, oof


def export_tree(node, out):
    """A LightGBM tree (dump_model's nested dict) appended to the five parallel arrays; returns the node's index."""
    i = len(out["f"])
    for k in "ftlrv":
        out[k].append(0)
    if "leaf_value" in node:
        out["f"][i], out["v"][i] = -1, node["leaf_value"]
        return i
    assert node["decision_type"] == "<=", node["decision_type"]
    out["f"][i], out["t"][i] = node["split_feature"], node["threshold"]
    out["l"][i] = export_tree(node["left_child"], out)
    out["r"][i] = export_tree(node["right_child"], out)
    return i


def export(models, margins, feats, trigger, meta):
    spec = {"features": feats, "trigger": trigger, "options": {}, "meta": meta}
    for o, m in models.items():
        trees = []
        for t in m.dump_model()["tree_info"]:
            arr = {k: [] for k in "ftlrv"}
            export_tree(t["tree_structure"], arr)
            trees.append(arr)
        spec["options"][o] = {"margin": margins[o], "trees": trees}
    return spec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--out", default=None)
    ap.add_argument("--h", type=int, default=300)
    ap.add_argument("--hp-w", type=float, default=0.0)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--options", default="melee,elbereth,zap,quaff,pray,up,down,retreat")
    ap.add_argument("--trigger", default='{"hp_frac": 0.5, "pdeath": 0.003, "win_prob": 0.85}')
    a = ap.parse_args()
    recs = load(a.dirs)
    rows = table(recs, a.h, a.hp_w)
    feats = [k for k in sorted(rows[0]["feat"]) if k not in EXCLUDE]
    options = [o for o in a.options.split(",") if sum(1 for r in rows if o in r["opts"]) >= 200]
    seeds = np.array([r["seed"] for r in rows])
    print(f"{len(rows)} decision points, {len(set(seeds))} games, {len(feats)} features, options {options}")
    # ---- outer validation by game
    all_d, all_g, all_p = [], [], []
    for f in range(a.folds):
        tr = [r for r, s in zip(rows, seeds) if s % a.folds != f]
        te = [r for r, s in zip(rows, seeds) if s % a.folds == f]
        margins, _ = choose_margins(tr, feats, options)
        keep = [o for o in options if margins[o] is not None]
        models = {o: m for o in keep if (m := fit_option(tr, feats, o)) is not None}
        d, picks = policy_value(te, predict_all(models, te, feats), margins)
        all_d += list(d); all_g += [r["seed"] for r in te]; all_p += picks
        print(f"  fold {f}: {len(te)} points, margins {margins}, gain {d.mean() * 100:+.2f} pp, "
              f"picked non-default {np.mean([p != 'default' for p in picks]) * 100:.0f} %")
    gain, lo, hi = boot_ci(all_d, all_g)
    print(f"held-out policy gain per decision point: {gain * 100:+.2f} pp [{lo * 100:+.2f}, {hi * 100:+.2f}] (value units)")
    from collections import Counter
    cnt = Counter(all_p)
    for o, n in cnt.most_common():
        dd = [d for d, p in zip(all_d, all_p) if p == o]
        print(f"    picks {o:9s} {n:6d} ({n / len(all_p) * 100:4.1f} %)  mean gain where picked {np.mean(dd) * 100:+.2f} pp")
    # ---- the final model on everything
    if a.out:
        margins, _ = choose_margins(rows, feats, options)
        keep = [o for o in options if margins[o] is not None]
        models = {o: m for o in keep if (m := fit_option(rows, feats, o)) is not None}
        spec = export(models, margins, feats, json.loads(a.trigger),
                      {"h": a.h, "hp_w": a.hp_w, "points": len(rows), "games": len(set(seeds)),
                       "heldout_gain_pp": [round(v * 100, 2) for v in (gain, lo, hi)], "dirs": a.dirs})
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w") as fh:
            json.dump(spec, fh, separators=(",", ":"))
        print(f"wrote {a.out}: options {keep}, margins {margins}, {os.path.getsize(a.out) // 1024} KB")


if __name__ == "__main__":
    main()
