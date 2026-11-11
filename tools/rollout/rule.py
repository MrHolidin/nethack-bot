"""A hand-written rule as a `tactic_model` file: "at a decision point, when <conditions>, take <option>".

    python -m tools.rollout.rule --out nhbot/data/rule_pray.json \\
        --rule "pray: crit_low > 0.5, can_pray <= 0.5, pray_gap > 150" [--rule "up: win_prob <= 0.6, up_cost <= 15"] \\
        [--trigger '{"hp_frac": 0.5, "pdeath": 0.003, "win_prob": 0.85}']

A rule is an option and a conjunction of `feature <= t` / `feature > t` tests on nhbot.tactic.tactic_features; it
becomes one tree whose leaf is +1 where every test holds and -1 elsewhere (nhbot/tacticmodel.py takes an option
when its value is above its margin, 0; it must also be legal there: nhbot.tactic.tactic_legal). When several rules
hold, the option that comes first in tactic_legal's order wins (melee, pray, elbereth, quaff, zap, up, down). The
same option
`tactic_model` and the same code path as the learned chooser, so a rule found in the rollouts can go to a
whole-game A/B without new code in the bot.
"""
import argparse
import json
import os
import re




def tree_of(tests, feats):
    """The conjunction as a chain: node i tests tests[i]; failing it is a -1 leaf, passing the last one +1."""
    f, t, l, r, v = [], [], [], [], []
    for name, op, thr in tests:
        i = len(f)
        f.append(feats.index(name)); t.append(thr); l.append(0); r.append(0); v.append(0.0)
        fail = len(f)
        f.append(-1); t.append(0.0); l.append(0); r.append(0); v.append(-1.0)
        nxt = len(f)
        if op == "<=":
            l[i], r[i] = nxt, fail
        else:
            l[i], r[i] = fail, nxt
    f.append(-1); t.append(0.0); l.append(0); r.append(0); v.append(1.0)
    return {"f": f, "t": t, "l": l, "r": r, "v": v}


def parse(rule):
    opt, conds = rule.split(":", 1)
    tests = []
    for c in conds.split(","):
        m = re.fullmatch(r"\s*(\w+)\s*(<=|>)\s*(-?[\d.]+)\s*", c)
        if not m:
            raise SystemExit(f"cannot read the test {c!r} (use 'feature <= number' or 'feature > number')")
        tests.append((m.group(1), m.group(2), float(m.group(3))))
    return opt.strip(), tests


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rule", action="append", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--trigger", default='{"hp_frac": 0.5, "pdeath": 0.003, "win_prob": 0.85}')
    a = ap.parse_args()
    rules = [parse(r) for r in a.rule]
    feats = sorted({name for _, tests in rules for name, _, _ in tests})
    spec = {"features": feats, "trigger": json.loads(a.trigger), "options": {}, "meta": {"rules": a.rule}}
    for opt, tests in rules:
        if opt in spec["options"]:
            raise SystemExit(f"two rules for {opt}: write one conjunction per option")
        spec["options"][opt] = {"margin": 0.0, "trees": [tree_of(tests, feats)]}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w") as fh:
        json.dump(spec, fh, indent=1)
    print("wrote", a.out, "options", list(spec["options"]), "features", feats)


if __name__ == "__main__":
    main()
