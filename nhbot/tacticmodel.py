"""The chooser of `tactic_model`: plain-numpy inference of the model tools/rollout/train.py writes.

The weights file (json) holds, per option other than 'default', a small gradient-boosted forest that predicts the
option's *advantage* over the scripted default at a decision point -- the difference in the rollout value (the
chance to be alive `horizon` turns later; tools/rollout/README.md) -- from nhbot.tactic.tactic_features:

  {"features": [names, in the order of the vector],
   "trigger": {"hp_frac": .., "pdeath": .., "win_prob": ..},      the decision points it was trained on
   "options": {"elbereth": {"margin": m, "trees": [{"f": [..], "t": [..], "l": [..], "r": [..], "v": [..]}, ..]}},
   "meta": {...}}

A tree is five parallel arrays over its nodes: feature index (-1: a leaf), threshold (go left when x <= t), left
and right child, leaf value. An option is taken when it is legal, its predicted advantage is the largest and
exceeds its margin; otherwise the scripted steps go on.
"""
import numpy as np


class TacticModel:
    def __init__(self, spec):
        self.features = list(spec["features"])
        self.trigger = dict(spec["trigger"])
        self.options = {}
        for name, o in spec["options"].items():
            trees = [(np.asarray(t["f"], dtype=np.int64), np.asarray(t["t"], dtype=np.float64),
                      np.asarray(t["l"], dtype=np.int64), np.asarray(t["r"], dtype=np.int64),
                      np.asarray(t["v"], dtype=np.float64)) for t in o["trees"]]
            self.options[name] = (float(o.get("margin", 0.0)), float(o.get("base", 0.0)), trees)

    def wants(self, feat):
        """Is this a decision point of the kind the model was trained on (tools/rollout Collector.trigger)?"""
        tr = self.trigger
        if feat["n_adj"] == 0:
            return feat["far_within3"] > 0 and feat["hp_frac"] < tr["hp_frac"]
        return feat["hp_frac"] < tr["hp_frac"] or feat["pdeath1"] >= tr["pdeath"] or feat["win_prob"] <= tr["win_prob"]

    def vector(self, feat):
        return np.array([float(feat[k]) for k in self.features])

    def advantage(self, name, x):
        """Predicted advantage of option `name` over the default at feature vector x."""
        _, base, trees = self.options[name]
        total = base
        for f, t, l, r, v in trees:
            i = 0
            while f[i] >= 0:
                i = l[i] if x[f[i]] <= t[i] else r[i]
            total += v[i]
        return total

    def choose(self, feat, legal):
        """The option to take: the legal one with the largest predicted advantage above its margin, else 'default'."""
        x = self.vector(feat)
        best, best_adv = "default", 0.0
        for name in legal:
            if name not in self.options:
                continue
            adv = self.advantage(name, x) - self.options[name][0]
            if adv > best_adv:
                best, best_adv = name, adv
        return best
