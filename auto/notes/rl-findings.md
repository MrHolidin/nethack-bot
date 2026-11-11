# rl — findings for the orchestrator (agent `rl`, branch `a/rl`)

Status 21:45 UTC: **preliminary** — 1 700 decision points of ~150 games (seeds 400100+), 2 futures per option,
300 turns each. Intervals are 95 % bootstrap over games. "Deaths" = died within 300 turns of the decision, in
percentage points, option − scripted default, paired on the future's seed. Tools and how to read them:
`tools/rollout/README.md`. Log: `rl-notes.md`.

## 0. Answer to "what was the rollout evidence for elb_hp 0.7?" (rl_elb70_s, rl_elbexit100_s)

The rollouts say more Elbereth saves lives over 300 turns and costs score in the window:

| sustained variant (child plays on under the changed option) | n | deaths | score gained in the window |
|---|---|---|---|
| `elb_hp` 0.7 (Elbereth below 70 % HP) | 470 | −1.28 [−2.90, 0.00]; within 50 turns −1.17 [−2.11, −0.46] | −58 [−80, −40] |
| `elb_exit` 1.0, `elb_early` 0.85 (stay until full HP) | 470 | −1.70 [−3.33, −0.22] | −23 [−43, −4] |
| `elb_hp` 0.35 | 596 | +1.34 [−0.07, +2.73] | +41 [+24, +60] |
| `rest_frac` 0.7 / 0.9 | 455 / 494 | 0.00 / −0.10 | −26 / −31 |

I know the owner's whole-game result (−1209 [−1710, −741] on base b4). I queued the two runs **as a calibration
of the harness's label, not as candidates**: the rollouts and the old whole-game A/B disagree in sign, and I need
to know which holds on today's bot before any chooser is trained on "alive 300 turns later". What I found since
in the old run itself (results branch, `a4_elbhp7` vs `b4`, 1000 seeds): with elb_hp 0.7 the games were
*shorter* — turns 6064 → 5863, kills 98 → 93, Elbereths 5.5 → 13.5 a game, starved 100 → 109 — so on that bot
more Elbereth meant dying earlier, not only playing slower; Elbereth has been reworked since (read-back,
`elb_stale` +609), so the old sign may not hold. Also relevant: the owner's `elb_sim` (Elbereth when the fight
sim with it beats fighting on) on today's base: −1163, 80 % CI [−3247, +1072] (`elb_sim_80k` − `base22_80k`,
my recomputation): no gain. **If rl_elb70_s comes back negative, every "safer" row below is suspect** and the
label needs a pace correction; I am measuring that directly too (rollouts of 3000 turns, `tools/rollout/horizon.py`).
`rl_elbexit100_s` has not started: cancel it if you want the workers (`nhq cancel rl_elbexit100_s`).

## 1. How often is the scripted choice wrong? (one forced action, then the script)

| forced instead of the script | where | n | deaths | score in window |
|---|---|---|---|---|
| melee | script says Elbereth | 620 | +0.08 [−2.22, +2.55] | +21 |
| Elbereth | script says melee (HP ≥ 50 % or Elbereth "blocked") | 428 | −2.80 [−5.46, −0.23] | −51 [−114, −3] |
| … of which Elbereth not blocked, HP ≥ 50 %, the fight flagged by danger.py (win_prob ≤ 0.85 or P(death next turn) ≥ 0.3 %) | | 188 | **−4.26 [−7.50, −1.30]** (10.1 % → 5.9 %); within 50 turns −3.72 [−6.58, −1.87] | +49 [−10, +120] |
| … of which Elbereth blocked (`elb_blocked`: a monster in view that ignores it / may shoot), HP < 50 % | | 186 | −0.54 [−5.31, +3.71]; within 50 turns −4.30 [−8.51, −0.24] | −76 |
| zap the attack wand | everywhere it is possible | 320 | +2.97 [−0.31, +5.74] | −7 |
| zap | script says Elbereth | 211 | +4.27 [0.00, +8.02] | +6 |
| down the stairs (within 15 squares) | everywhere | 222 | +3.83 [−0.63, +8.86] | +12, max depth +0.28 |
| up the stairs | everywhere | 309 | +0.49 [−3.17, +3.69] | −82 |
| quaff a healing potion | everywhere | 61 | +3.28 [−1.67, +13.10] | −29 |
| pray although the script's timer says no | critically low HP | 9 | 0.00 [−46, +39] | |
| `pray_gap` 800 (sustained) | HP < 40 %, 480–800 turns since a prayer | 19 | **+13.2 [+5.3, +21.9]** | −65 |
| `pray_gap` 300 (sustained) | HP < 40 %, 250–520 turns since a prayer | 35 | −1.43 [−3.12, 0.00] | +30 |

Reading: the script's melee / wand / potion / stairs choices are not beaten by any single alternative — the wand
and stairs logic is right to hold back, praying later is clearly worse, earlier is not clearly better. The one
place the rollouts disagree with the script is **Elbereth in a dangerous fight while HP is still above half**
(see 0. for why this is not yet a recommendation).

## 2. The fights the games died in

42 of 60 finished collecting games died within 25 turns of their last decision point (63 % of the total score
is in those games): the trigger sees about two thirds of all deaths. At that last point, every option re-rolled
with fresh seeds (the default too — these states are picked by their outcome, so the default's death rate is
high by selection):

- default: dead within 50 turns in 74 % of the re-rolls;
- Elbereth forced where the script did something else (31 points): 42 % (**−32 [−52, −15]**); within 300 turns
  77 % → 60 % (−18 [−34, −5]);
- 11 of 43 fatal fights (one more game had finished by then) are at the **fountain**: 4–5 water moccasins or a water demon at XL 5 with full HP,
  standing on the fountain (no Elbereth possible there). On base_d1 + base_d2 (2000 games) the commonest
  attacker in the last messages: water demon 4.5 % of games, water moccasin 3.9 % (mean score 3.3 k / 4.4 k),
  troll 2.5 %, soldier ant 2.5 %, starvation 2.5 % (mean 61 k), killer bee 2.4 %, fire ant 2.2 %, leocrotta
  2.2 %, gremlin 1.8 % (mean 78 k). The fountain agent's work covers the first two; the rollouts at water
  moccasins (47 points): default dies 27.7 %, up the stairs −8 (n 12), down −17 (n 6), Elbereth −4.5 (n 11).

## 3. What is in doubt

- **The label.** "Alive 300 turns later" favours anything that slows the game down. `tools/rollout/value.py`
  values a rollout by the game's index J instead (banked at a death; a value fitted on baseline snapshots if
  alive), but that value does not see experience not gained (XL is its only growth feature). The calibration runs
  in 0. decide how far the tables can be trusted.
- Sample: 1 700 points; the cells above with n < 100 are hints, not results.
