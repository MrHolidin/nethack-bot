# tools/rollout — counterfactual rollouts by fork

A paired micro-evaluation of tactical choices: at a decision point of a live game the process is forked, each
child forces one tactical option (`nhbot/tactic.py`: melee / pray / Elbereth / quaff / zap / up / down / retreat,
or the scripted `default`), then plays on **as the scripted bot** for `horizon` game turns under a fresh RNG seed
and reports what happened (died, HP, score gained, prayers / potions / charges used). The parent plays on
untouched. One decision point with 7 options x 2 futures costs 5–15 s of one core; a whole-game A/B needs
thousands of games to see what a few hundred decision points show here.

What a rollout estimates is `Q(s, a)` of the scripted policy: the value of doing `a` now and following the script
afterwards. Acting greedily on it is one step of policy improvement.

## Files

| file | what |
|---|---|
| `fork.py` | forking a live NLE game safely: the game directory, file descriptions, reseeding (read its docstring) |
| `collect.py` | `Collector` (the bot's tactic hook: trigger, fork, record), `rollout()` (what a child does), the CLI |
| `selftest.py` | isolation / determinism / reseed checks |
| `analyze.py` | the dataset's first reading: every option against the default, paired, by scripted step / HP / win_prob; the fatal fights |
| `rules.py` | simple rules "when <condition>, do <option>": searched on half of the games, measured on the other half |
| `train.py` | fits the chooser (`nhbot/tacticmodel.py` reads its json) and scores it on held-out games |
| `value.py` | a rollout's value in the session's index J for the whole game: banked at a death, V(end state) if alive (V fitted on baseline snapshots: `value_v1.json`) |
| `horizon.py` | deaths and score of each option by turns since the decision (long rollouts), and the 300-turn label checked against the long window |

## What "better" means here — read before trusting a table

"Fewer deaths within 300 turns" is not "a better game". An option that postpones the fight (sit on Elbereth,
rest) wins every fixed window it sits through, gains no experience meanwhile, and meets the same monster after
the window. Three things guard against that, in rising order of cost:

1. the tables show the score gained in the window next to the deaths;
2. `"settle": N` lets a child play past the horizon until the fight is over (no hostile in view, off Elbereth,
   HP >= `rest_frac`; at most N more turns), and `value.py` then values the calm end state by what such a hero
   goes on to score (column `J x1000`);
3. `"horizon": 3000` + `horizon.py`: play the options out for a third of a game and look at deaths and score by
   horizon — the calibration of 1 and 2.

The ground truth stays the whole-game A/B on the farm; a rollout verdict that disagrees with a whole-game result
is a bug in the label until shown otherwise.

## Use

Everything runs on the evaluation machine, in a checkout of the branch, with the bot's venv:

```
cd /workspace/agents/rl/work
PY=/workspace/venv/bin/python
$PY -m tools.rollout.collect --selftest --seeds 400000:400012 -j 6          # ~3 min
$PY -m tools.rollout.collect --seeds 400100:400400 -j 16 --out /dev/shm/rl/d1 \
     --cfg '{"horizon": 300, "reps": 2}'                                    # one jsonl per game + games.jsonl
$PY -m tools.rollout.analyze /dev/shm/rl/d1
```

`collect.py` re-executes itself under libfaketime with regress.py's clock. `-j` is games in parallel; the children
of one game run one at a time (a game with rollouts uses one core), so the farm could run it too.

Settings (`--cfg`, `collect.DEFAULTS`): `horizon`, `settle`, `reps`, `gap` (turns between decision points), `max_dp`,
`max_secs` (rollout budget per game), `options` (subset), the trigger thresholds `hp_frac`, `pdeath`, `win_prob`,
`keep` (thinning), `max_turn`.

## Policy variants (`collect.VARIANTS`)

Besides forcing one action, a child can play on under **changed bot options** (`"variants": "all"` or a list of
names): `v:elb70` is the scripted bot with `elb_hp = 0.7` from this tick on. That is a paired micro-A/B of a
parameter of the scripted policy at the states where it can matter (each variant has a test on the features);
add a line to `VARIANTS` to screen another one. In the records and tables a variant is an option named `v:<name>`.

## A decision point (`Collector.trigger`)

Checked at the policy step `tactic` (before `pray`), at most every `gap` turns:

- a hostile next to us and (HP < `hp_frac` of max, or danger.py's P(death next turn) >= `pdeath`, or
  `win_prob` <= `win_prob`), or
- no hostile next to us, one within 3 squares, HP < `hp_frac`.

## A record (one line of `<seed>.jsonl`)

```
{"seed": 400100, "dp": 3, "t": 3490, "legal": ["default", "melee", "zap", "retreat"],
 "feat": {...},                         # nhbot.tactic.tactic_features: what the chooser sees
 "adj": [["soldier ant", 0, 1]], "vis": [...], "wands": ["sleep"],
 "rolls": [{"opt": "default", "rep": 0, "ok": true, "first": "elbereth",   # first: the step that acted first
            "died": 1, "dt": 4,                                            # died within the horizon; turns played
            "hp": 0, "maxhp": 57, "depth": 7, "xl": 8,                     # at the end (hp: last seen)
            "score": 0, "exp": 0, "max_depth": 0, "prayers": 0, "quaffs": 0, "zaps": 0, "elb": 1, "kills": 0,
            "steps": 31,                                                   # gained / used since the decision
            "marks": [[5, 31], [10, 32], ...],                             # HP at turns +5, +10, +20, +50, +100, +200
            "death": ["...last messages..."]}, ...]}
```

Replicate `rep` uses the same RNG seed for every option (`collect.child_seed`): an option that does what the
default does reproduces the default's outcome exactly, so differences between options are not seed noise at the
first step. `ok` false: the option could not be done after all and the child fell back to the default.

## What was checked (selftest, 12 seeds x 6000 turns, a fork every 150 turns, 372 forks)

- **isolation**: the forking parent sends exactly the keys of a game that never forks (12 / 12 games) — children
  changing level, dying, writing record files do not touch the parent.
- **determinism**: a child that keeps the parent's RNG state and forces `default` sends, over its horizon, exactly
  the keys the parent then sends (372 / 372).
- **reseed**: a reseeded child's keys differ from the parent's continuation in 351 / 372 forks (the rest: quiet
  stretches where 120 turns of searching look the same under any seed).

## Things to know

- `fork.reseed` sets the level generator's seed too (NLE's `lgen`): the levels a child generates from then on
  depend on its seed, the levels that already exist are on disk (copied).
- A child leaves by `os._exit`; its game directory lives in `/dev/shm/rollout*/nlefork*` and is removed when it
  ends (a killed child's: by the parent).
- The features are computed in the parent before forking; computing them may send free keys (a farlook), so a
  collecting game is not key-identical to a plain one (the selftest forks without computing features).
- Open descriptors: a parent that holds other files open for writing (ttyrec recording, `savedir`) is not
  supported — the bot does not.
