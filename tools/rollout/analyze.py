"""First reading of a rollout dataset: how often the scripted choice is wrong, which option wins where.

    python -m tools.rollout.analyze DIR [DIR ...] [--h 300]

Per decision point and option the rollouts give death within h turns (mean over the replicates). Everything here
is paired: an option is compared with `default` on the decision points where it is legal, and the confidence
intervals are bootstrap over games (the decision points of a game are not independent).
"""
import argparse
import glob
import json
import os
from collections import defaultdict

import numpy as np

HORIZONS = (20, 50, 100, 300)


def load(dirs):
    """The decision points of every game file under dirs, as dicts (rolls with a crash dropped)."""
    recs = []
    for d in dirs:
        for f in sorted(glob.glob(os.path.join(d, "[0-9]*.jsonl"))):
            with open(f) as fh:
                for line in fh:
                    r = json.loads(line)
                    r["rolls"] = [x for x in r["rolls"] if "crash" not in x]
                    recs.append(r)
    return recs


def died_by(x, h):
    return int(bool(x["died"]) and x["dt"] < h)


def option_stats(rec, h):
    """option -> dict of the means over its replicates: death by h, final HP fraction, prayers used, score."""
    by = defaultdict(list)
    for x in rec["rolls"]:
        by[x["opt"]].append(x)
    out = {}
    for o, xs in by.items():
        out[o] = {"death": np.mean([died_by(x, h) for x in xs]),
                  "hp": np.mean([0.0 if x["died"] else x["hp"] / max(x["maxhp"], 1) for x in xs]),
                  "pray": np.mean([x["prayers"] for x in xs]), "score": np.mean([x["score"] for x in xs]),
                  "mdepth": np.mean([x["max_depth"] for x in xs]),
                  "ok": np.mean([x["ok"] for x in xs]), "n": len(xs),
                  "first": xs[0].get("first")}
    return out


def boot_ci(vals, groups, n=400, seed=0):
    """Mean of vals and its 95 % bootstrap interval, resampling whole groups (games)."""
    vals, groups = np.asarray(vals, float), np.asarray(groups)
    if not len(vals):
        return float("nan"), float("nan"), float("nan")
    ug, inv = np.unique(groups, return_inverse=True)
    sums = np.bincount(inv, vals, len(ug))
    cnts = np.bincount(inv, minlength=len(ug))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(ug), (n, len(ug)))
    means = sums[idx].sum(1) / np.maximum(cnts[idx].sum(1), 1)
    return vals.mean(), float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def fmt(m, lo, hi, scale=100):
    return f"{m * scale:+6.2f} [{lo * scale:+6.2f}, {hi * scale:+6.2f}]"


def paired_table(recs, h, where=None, title=""):
    """Per option: the decision points where it is legal (and where holds), death by h of default and of the
    option there, and the paired difference with its interval (percentage points; negative: the option saves);
    the differences in prayers used, final HP fraction, score gained and max depth gained over the whole window
    (the horizon the data was collected with) -- an option that only slows the game down saves lives per turn and
    loses score."""
    rows = defaultdict(lambda: ([], [], [], [], [], [], []))
    n = 0
    for r in recs:
        if where is not None and not where(r):
            continue
        st = r["_st"][h]
        if "default" not in st:
            continue
        n += 1
        for o, s in st.items():
            if o == "default" or s["ok"] < 1:
                continue
            a = rows[o]
            a[0].append(st["default"]["death"]); a[1].append(s["death"]); a[2].append(r["seed"])
            a[3].append(s["pray"] - st["default"]["pray"]); a[4].append(s["hp"] - st["default"]["hp"])
            a[5].append(s["score"] - st["default"]["score"]); a[6].append(s["mdepth"] - st["default"]["mdepth"])
    print(f"\n{title}  ({n} decision points; death within {h} turns, %; diff = option - default)")
    print(f"  {'option':12s} {'n':>6s} {'default':>8s} {'option':>8s}  {'diff [95% CI]':28s} {'prayers':>8s} {'hp_end':>7s} "
          f"{'score [95% CI]':>24s} {'maxdepth':>9s}")
    for o in sorted(rows, key=lambda o: -len(rows[o][0])):
        d, v, g, pr, hp, sc, md = rows[o]
        diff = np.array(v) - np.array(d)
        print(f"  {o:12s} {len(d):6d} {np.mean(d) * 100:8.2f} {np.mean(v) * 100:8.2f}  {fmt(*boot_ci(diff, g)):28s} "
              f"{np.mean(pr):+8.3f} {np.mean(hp):+7.3f} {fmt(*boot_ci(sc, g), scale=1):>24s} {np.mean(md):+9.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--h", type=int, default=300)
    a = ap.parse_args()
    recs = load(a.dirs)
    for r in recs:
        r["_st"] = {h: option_stats(r, h) for h in HORIZONS}
    games = len({r["seed"] for r in recs})
    print(f"{len(recs)} decision points of {games} games; {sum(len(r['rolls']) for r in recs)} rollouts")
    firsts = defaultdict(int)
    for r in recs:
        firsts[r["_st"][a.h].get("default", {}).get("first")] += 1
    print("scripted first step:", dict(sorted(firsts.items(), key=lambda t: -t[1])))
    for h in HORIZONS:
        d = [r["_st"][h]["default"]["death"] for r in recs if "default" in r["_st"][h]]
        print(f"  default: death within {h:3d} turns {np.mean(d) * 100:.2f} %")
    paired_table(recs, a.h, title="ALL")
    paired_table(recs, 50, title="ALL")
    for first in ("melee", "elbereth", "pray", "heal", "wands"):
        paired_table(recs, a.h, lambda r, f=first: r["_st"][a.h]["default"]["first"] == f, f"scripted = {first}")
    paired_table(recs, a.h, lambda r: r["feat"]["n_adj"] == 0, "no hostile adjacent (hurt, one within 3)")
    for lo, hi in ((0, 0.2), (0.2, 0.35), (0.35, 0.5), (0.5, 0.75), (0.75, 1.01)):
        paired_table(recs, a.h, lambda r, lo=lo, hi=hi: lo <= r["feat"]["hp_frac"] < hi and r["feat"]["n_adj"] > 0,
                     f"adjacent, hp_frac in [{lo}, {hi})")
    for lo, hi in ((0, 0.3), (0.3, 0.6), (0.6, 0.85), (0.85, 1.01)):
        paired_table(recs, a.h, lambda r, lo=lo, hi=hi: lo <= r["feat"]["win_prob"] < hi and r["feat"]["n_adj"] > 0,
                     f"adjacent, win_prob in [{lo}, {hi})")
    fatal_report(recs, a.dirs, a.h)
    monster_report(recs, a.h)


def monster_report(recs, h, top=25, opts=("melee", "elbereth", "zap", "up", "down", "quaff")):
    """Per monster kind next to us (the commonest): the default's death rate and each option's paired difference."""
    by = defaultdict(list)
    for r in recs:
        for name in {a[0] for a in r.get("adj", [])}:
            by[name].append(r)
    print(f"\nBY MONSTER next to us (death within {h} turns, %; per option: diff to default (n))")
    print(f"  {'monster':18s} {'n':>5s} {'default':>8s}  " + "  ".join(f"{o:>14s}" for o in opts))
    for name, rs in sorted(by.items(), key=lambda t: -len(t[1]))[:top]:
        cells = []
        for o in opts:
            d = [r["_st"][h][o]["death"] - r["_st"][h]["default"]["death"] for r in rs
                 if o in r["_st"][h] and r["_st"][h][o]["ok"] == 1 and "default" in r["_st"][h]]
            cells.append(f"{np.mean(d) * 100:+6.1f} ({len(d):4d})" if d else " " * 14)
        dd = [r["_st"][h]["default"]["death"] for r in rs if "default" in r["_st"][h]]
        print(f"  {name:18s} {len(rs):5d} {np.mean(dd) * 100:8.1f}  " + "  ".join(cells))


def fatal_report(recs, dirs, h, within=25):
    """The fights the collecting games died in: each game's last decision point when the game ended within
    `within` turns of it. These states are chosen by their outcome under the parent's own seed, so the default's
    death rate here is high by selection -- but every option, the default too, is re-rolled with fresh seeds, and
    the table says what share of such deaths an option averts."""
    turns = {}
    for d in dirs:
        path = os.path.join(d, "games.jsonl")
        if os.path.exists(path):
            with open(path) as fh:
                for line in fh:
                    g = json.loads(line)
                    if "turns" in g:
                        turns[g["seed"]] = g
    last = {}
    for r in recs:
        if r["seed"] in turns and (r["seed"] not in last or r["t"] > last[r["seed"]]["t"]):
            last[r["seed"]] = r
    fatal = [r for s, r in last.items() if turns[s]["turns"] - r["t"] <= within]
    print(f"\n{len(turns)} finished games, {len(last)} with a decision point, {len(fatal)} died within {within} turns "
          f"of their last one ({sum(turns[r['seed']]['score'] for r in fatal) / max(1, sum(g['score'] for g in turns.values())) * 100:.0f} % "
          f"of the total score is in those games)")
    for hh in (50, h):
        paired_table(fatal, hh, title="FATAL FIGHTS (the last decision point before the game's death)")
    ids = {id(r) for r in fatal}
    paired_table([r for r in recs if id(r) not in ids], h, title="all other decision points")


if __name__ == "__main__":
    main()
