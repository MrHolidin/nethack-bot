# rl: a learned tactical policy for fights — working notes (agent `rl`, branch `a/rl`)

All times UTC, 2026-11-11/12. Findings for the orchestrator are in `rl-findings.md`; this file is the log.

## Stage 1 — counterfactual rollouts by fork: DONE 20:45 (gate 22:45)

- `tools/rollout/` (README there): `fork.py` (privatize + reseed), `collect.py` (Collector, rollout, CLI),
  `selftest.py`, `analyze.py`, `rules.py`, `train.py`. `nhbot/tactic.py`: the options as code, the features, the
  policy step `tactic` (before `pray`; inert without a hook / `tactic_model`). `nhbot/tacticmodel.py`: numpy
  inference.
- What a fork shares with its parent and how it is undone (read from NLE 1.3.0's source, `nle.c`, `nlernd.c`,
  NetHack's `files.c` / `dlb.c`):
  - the game directory (level files `<uid><name>.<n>`, `record`, `save/`): all of `fqn_prefix[]` point at
    `settings.hackdir`, a `char[4096]` in the library's globals -> the child copies the directory and overwrites
    that buffer in place (ctypes on the dlopen handle NLE itself uses);
  - the offset of the one file the game keeps open (`nhdat`): reopened + `dup2` in the child;
  - the RNG: `Nethack.set_current_seeds(core, disp, reseed=False, lgen)` -> `nle_set_seed` re-inits isaac64.
- Selftest (12 seeds x 6000 turns, a fork every 150 turns): parent key-identical to a game that never forks
  12 / 12; an un-reseeded `default` child reproduces the parent's next 120 turns key for key 372 / 372; a
  reseeded child differs 351 / 372.
- `regress.py check` strict 32 / 32 with the new step in place (option off).
- Cost: a child playing 300 turns ~0.5-1 s; a decision point (7 options x 2 futures) ~6 s of one core.
- Refactors needed in the bot (no behaviour change): `Bot.run`'s loop body is `play_tick` / `after_tick`;
  `PolicyMixin.tick`'s loop is `run_steps(c, after=None)`.

## Stage 2 — dataset

- Pilot `p0` (seeds 400100..400131, 662 points, with `retreat`, stairs within cost 40): found that the stairs
  macro suppressed the prayer (it sits before `pray`) and walked 10-20 squares with the monster biting: `up` cost
  +17 pp deaths. Fixed: a macro yields at critically low HP; stairs only within path cost 15.
- `d1` (400200.., 493 points, no variants), `d2` (400400.., running, 16 procs): options default / melee / pray /
  elbereth / quaff / zap / up / down + variants elb70, elb35, elbexit70, pray300, pray800, heal50; horizon 300,
  2 futures per option, a decision point at most every 5 turns.
- Coverage (pilot, 31 games): 21 games died within 20 turns of a decision point, 25 within 300 -> about two
  thirds of all deaths are fights the trigger sees.

### 21:30 — the label problem (read this before trusting any table)

First 1300 points said: more Elbereth is safer — `v:elb70` (Elbereth below 70 % HP, not 50 %) −1.3 pp deaths
within 300 turns [−2.9, 0.0], `v:elbexit100` (stay until full HP) −1.7 pp [−3.3, −0.2]; both gain less score in
the window (−58 [−80, −40] and −23 [−43, −4] points). But JOURNAL_AUTO.md has the whole-game A/B of
`elb_hp=0.7` on an older base: **−1209 [−1710, −741] (−18 %), depth −0.4**; `rest_frac=0.7`: −418.
So "alive 300 turns later" overrates options that slow the game down. Actions taken:

- `value.py`: a rollout is now valued in the session's index J for the whole game — banked J at a death,
  V(end state) + score gained if alive, V fitted on the snapshots of base_d1 + base_d2 (39 600 snapshots, held-out
  R² 0.42; it reads max depth 47 %, XL 28 %, AC 9 %; kills 0 % — so it does not see the experience a passive
  option fails to gain unless XL moves).
- Calibration on the current base, two ways:
  - whole games on the farm: `rl_elb70_s` ({"elb_hp": 0.7}) and `rl_elbexit100_s` ({"elb_exit": 1.0,
    "elb_early": 0.85}), 500 games of D1 each against `base_d1` (queued 21:28, prio 4, the farm is saturated);
  - long rollouts in the harness (`c1`: default / v:elb70 / v:elbexit100 played 3000 turns from each decision
    point, `horizon.py` gives deaths and score by horizon 50 … 3000).
- The collection now records the start state (`state0`) and a richer end state; `d6`/`d7` have them (`d1`–`d5`
  do not: death tables only).
