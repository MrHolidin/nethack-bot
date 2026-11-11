# Working rules for agents on nethack-bot (autonomous session, 2026-11-11/12)

Goal of the whole session: raise, as far as possible by **08:00 UTC 2026-11-12**, two numbers of the bot on
Valkyrie games — **mean in-game score** (baseline ~27 000) and **mean max dungeon depth** (baseline ~11.3). Wall
time is the scarce resource: prefer the experiment that answers soonest. The orchestrator (the session that
started you) owns priorities, merges and the documents in `auto/`; you own your task and your branch.

## What we know (read before you design anything)

- Score ≈ 4 × experience points + gold carried + 50 × (deepest level − 1) (+1000 per level below 20). Experience
  for a kill ≈ 1 + level² (+50 above level 8, + bonuses): deep kills are worth 5–10 × shallow ones.
- The game makes a random monster every ~70 turns anywhere; its level is at most (depth + our XL) / 2.
- Games end by death, or are **truncated at 200 000 keys sent** (`Bot(max_steps=200_000)`, a fixed rule of the
  evaluation — do not change it). Today ~1 % of games are truncated; the bot spends ~4.4 keys per game turn.
- (Corrected: the bot sends ~1.85 keys per game turn on average, 2.4 in long games — not 4.4.)
- The score is heavy-tailed: on 2000 baseline games the 14 % that reach depth 21+ hold 59 % of the total score;
  half of the games die with under 9 000. Deep games stand for tens of thousands of turns in `search`
  (stuck at Medusa / the Castle) and collect score from the monsters that come to them.
- Baseline per 1000 games: mean 25–29 k, median 7.5–9.5 k, mean depth 11.1–11.5, mean 10 000 turns, 20 000 keys,
  ~60 s of CPU a game.
- Older experiment history: `JOURNAL_AUTO.md`, the A/B notes in code comments (`A/B name: diff [CI]`), and the
  `results` branch of origin (`git show origin/results:results/TAG.jsonl`, 650 runs; newest bases `base22_80k`,
  `base22_81k`). Branches of origin (`oil`, `bag-store`, `hold-position`, `elb-sim`, `fountain-ask`, ...) are
  the owner's own experiments in flight: do not redo them.

## Code rules

- Read `README.md` and `nhbot/policy.py` first; then the module docstrings of what you touch.
- One idea = one option in `nhbot/options.py`, **off by default**, documented there like the others. Behaviour
  with the option off must be byte-identical (`regress.py check`, see below). The orchestrator turns accepted
  options into plain behaviour at merge time.
- **Improve the player, do not game the evaluation.** Nothing may depend on the evaluation's own rules — above
  all the 200 000-key cut-off (no "dive when the keys run out, a truncated game cannot die", no behaviour that
  reads the remaining key budget). The test: would this be better play in a game with no key limit? (Owner's
  rule, 2026-11-11.)
- The bot plays from the screen only: no reading of the game's memory at play time (`truemap.py`, `gift.py` and
  process forks are for experiments and training data only).
- Facts about NetHack 3.6.6 come from its source or the wiki (you may search the web: nethackwiki.com, the
  NetHack 3.6.6 source on GitHub) — cite file:line or the page in the docstring, as the existing code does.
- Style of the code base: mixins with a `*_init` and a state object, steps return True when they acted,
  docstrings say what and why, line length ≤ 120. Leave the code you touch more readable than you found it.
- Commit often on your branch `a/<your-name>` (in your worktree), message = what changed and why. End commit
  messages with `Co-Authored-By: Claude <noreply@anthropic.com>`. Never push to `origin`; never commit to
  `auto`, `arch` or `main`.

## The evaluation machine (`ssh nhbox ...`)

107 cores, 2 GPUs, shared by all agents through one scheduler. Nothing is installed locally: every run goes
through the machine.

```
git push -q box HEAD:refs/heads/a/<name>                 # publish your branch to the machine
ssh nhbox nhq submit --ref a/<name> --tag <name>_<what>_s --start 300000 -n 500 --prio 4 [--kw '{"opt": true}']
ssh nhbox nhq status                                     # what runs
ssh nhbox nhq wait TAG [TAG ...]                         # blocks until done (run it in the background)
ssh nhbox nhq cmp BASE_TAG TAG                           # paired B − A: score, depth, J, log10; 80 % and 95 % CI
ssh nhbox nhq show TAG
ssh nhbox nhq cancel TAG
ssh nhbox "nhq run a/<name> -- python -m nhbot 300123"   # one game, prints its summary (pinned clock)
ssh nhbox "nhq run a/<name> -- python regress.py check -j 32"         # strict: keys identical to golden.json
```

- A tag is unique for ever (results/TAG.jsonl): prefix it with your name.
- `--prio`: 1 smoke (≤ 32 games), 4 screening (500), 5 full runs, 7 sweeps and anything bulky. Do not submit
  more than ~3000 games at a time without a reason; cancel runs you no longer need.
- Results are jsonl in `/workspace/nh/results/` (one summary per game — every counter of `Bot.summary()`);
  analyse them on the machine (`/workspace/venv/bin/python`), copy nothing big back.
- Anything else you run there (training, data generation) must stay within the cores the orchestrator gave
  you in your brief; work under `/workspace/agents/<name>/`. The disk has 16 GB in all: keep datasets small or
  in `/dev/shm` (62 GB RAM disk, lost on reboot).
- Seeds: dev sets **D1 = 300000..300999**, **D2 = 301000..301999**. Baselines of the current base exist as
  tags named in your brief (first: `base_d1`, `base_d2` = `arch` 631a213). 310000+ is the orchestrator's
  holdout: never run on it.
- `golden.json` on `auto` matches the base commit for seeds 61000..61031.

## Statistics

- The decision metric is the index **J = score / 27000 + depth / 11** (relative gains summed), by paired
  bootstrap on shared seeds; `nhq cmp` prints it. Accept: the 80 % CI of J above zero and neither score nor
  depth significantly down. Screening on 500 games tells only large effects (score CI ≈ ±2000, depth ≈ ±0.4);
  a promising screen goes to the full D1 + D2 (2000 games).
- Do not select on outcomes, do not pick the best of many variants on the same seeds and call it a result: a
  winner of a sweep is re-run on the other dev set. Report every run, the losers too.
- A crash counts as a game with score 0. Look at `crash` fields in your results and fix what you caused.
- Look beyond the mean: `games changed`, deaths by cause, depth, truncated count, keys (`steps`) and `secs`.

## Reporting

Your final message goes to the orchestrator only. Give: branch and commit; the option name(s); every run
(tag, base tag, n, the `nhq cmp` lines verbatim); what you conclude; what you would do next. If you are
blocked or find something that changes the plan for others (a bug in the base, a much bigger lever), stop and
report at once rather than working around it.
