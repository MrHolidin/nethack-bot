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

### 21:42 — merged `auto` (perf's memoised fight simulation)

`git merge box/auto` clean. The memo key of `win_prob` holds the generator's state, and the features' win_prob
runs on a generator of its own swapped into `danger.win_rng` — both still right. Re-checked on the merged code:
`regress.py check` strict 32 / 32; selftest 6 seeds, 197 forks: isolation 6 / 6, determinism 197 / 197, reseeded
children differ in 184 / 197 (as before: the bot's own numpy generator is copied by the fork and gives every
child the same *estimates*; the game's dice are NetHack's RNG, which `fork.reseed` re-inits). Collection is ~3×
faster (80 decision points a minute on 10 procs).

### 21:52 — first long rollouts (3000 turns, 162 points; wide intervals, direction only)

- `v:elb70`: deaths ±0 up to 1000 turns, score gap growing: −39 at 300, −139 at 1000, −563 at 2000, −834 at
  3000 (default 5628: −15 %) — the size of the owner's whole-game −18 %. `v:elbexit100` the same shape (−245 at
  1000 [−463, −32], −1117 at 3000).
- So the 300-turn death gain of "more Elbereth" is a postponement: the window ends with the bot still on its
  square and the monster still there. And turns are not free: deaths by turn 3000 are the same (~50 %) in both
  hands, so the score is made by pace.
- Fixes: `settle` (a child plays on until the fight is over, ≤ 1200 turns more; `d9` is collected that way);
  `value_v2` blind to the HP fraction (V_v1 priced 30 % HP at 0.06–0.24 J against 0.008–0.04 J for 300 turns: by
  that rate resting always pays). V does price time (−205 … −1124 score per 300 turns at depth < 12), kills
  (+10 kills: +534 … +5556) and a used prayer (−1462 … −2137).

### 22:06 — long rollouts, 389 points of 49 games (c1–c4), and what follows

- `v:elb70` (235 pairs): deaths −3.0 at 300 turns, −0.4 at 1000, −4.3 [−11.7, +3.4] at 3000; score −82 at 300
  [−161, −19], −137 at 1000, −295 at 3000 [−886, +271] (default 5760: −5 %). No sign of the old −18 %, no gain.
- one forced Elbereth where the script fights (161 pairs): deaths +0.6 at 300, +1.2 at 3000 [−5.9, +7.9]; score
  −70 at 3000 [−1044, +711]. One forced blow where the script writes (131 pairs): deaths −6.9 at 300
  [−13.5, +1.2], −3.1 at 3000; score +227 [−680, +1101]. Nothing lasts.
- Reading: on the ordinary fight the script's Elbereth / melee choice makes no measurable long-run difference
  either way. The states where options differ by 5–20 pp are the fights nearly lost (win_prob < 0.6, HP < 25 %):
  there melee is +8 … +10 pp worse than the script, the forced wand +11 … +17 pp worse, and the candidates are
  the staircase up (win_prob 0.3–0.6, stairs within 15: −9.8 pp [−18.2, 0.0], J +116 [+49, +294] ×10⁻³, n 56) and a
  prayer against the script's timer (HP < 25 %: −18.8 pp [−38.1, +3.0], n 16).
- So the collection now concentrates there: `x1` (6 procs): trigger win_prob ≤ 0.7 or HP < 30 %, options
  default / melee / pray / elbereth / quaff / up / down, `settle` 1200. `d9` (10 procs) goes on with the general
  trigger for the chooser.
- danger.win_prob against what happens (2 853 points, default policy): where it says ≥ 0.99 (974 points) 2.6 %
  are dead within 20 turns and 3.5 % within 50; unseen attackers ('I': win_prob 1.0 by construction) 16.7 % dead
  within 50; dwarf, jackal packs, hill orc, fire ant worse than modelled; pony, giant bat, giant ant, rothe much
  safer than modelled.

### 22:27 — two rules written down before their confirmation (pre-registration)

Search sample: d1–d9 + x1 (seeds 400100..403105, 406000..406030; ~4 000 decision points, 300 games; x1 = fights
nearly lost, with `settle`). What it shows in the fights nearly lost (win_prob < 0.3; default dead within 50
turns in 51 %):

- Elbereth forced where the script does something else: dead ≤ 50 turns −13.4 pp [−21.1, −6.6], ≤ 300 turns
  −5.0 [−12.8, +1.9], J +151 ×10⁻³ [−8, +342] (298 pairs, 90 games). The script was not writing because of
  `elb_blocked` in 250 of them (a monster in view that ignores Elbereth or may shoot). Concentrated where two or
  more of the monsters next to us respect it (164 pairs, 58 games: ≤ 300 turns −10.4 [−20.2, −0.6], J +308
  [+69, +538]) and HP < 75 %; at HP ≥ 75 % nothing (+4.0, J −64).
- A prayer against the script's timer (critically low HP, < 500 turns since the last): dead ≤ 300 turns −13.6
  [−27.3, −5.6] (66 pairs, only 14 games). NetHack's rule (pray.c, rnz(350), my Monte Carlo): a prayer at
  critically low HP g turns after the last one is heard with P = 0.50 at g = 150, 0.55 at 200, 0.66 at 300,
  0.77 at 400, 0.87 at 500 — the script waits for 500.
- Melee instead of the script: +2.8 … +4.9 pp worse; quaff: nothing; stairs up / down at win_prob < 0.3: −6 / −10
  pp with intervals over zero.

The cells were picked after looking, so they are hypotheses. Written down now, tested on fresh seeds (414000+)
as **sustained** rules (the bot with `tactic_model` = the rule file, tools/rollout/rule.py, against the script,
1000 turns + until calm, 3 futures, only where the rule acts at once; `m1`):

- **R1** `elbereth: n_adj >= 2, adj_respect >= 2, win_prob <= 0.3, hp_frac <= 0.75` (where Elbereth can be written)
- **R2** `pray: critically low HP, the script's timer says no, pray_gap > 150` (god not angry)
- files: nhbot/data/rule_r1.json, rule_r2.json, rule_r12.json (both).

`x3` (10 procs): 3000-turn rollouts at critically low HP (default / pray / melee / elbereth / quaff,
pray_gap 150 / 300 sustained) for R2's long-run cost (an unheard prayer angers the god: the bot never prays
again).
