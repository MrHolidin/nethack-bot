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
