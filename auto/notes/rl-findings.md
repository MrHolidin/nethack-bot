# rl — findings for the orchestrator (agent `rl`, branch `a/rl`)

Updated 22:45 UTC. Tools and how to read them: `tools/rollout/README.md`; log: `rl-notes.md`.
Intervals are 95 % bootstrap over games. "Deaths" are percentage points, option − scripted default, paired on the
future's seed. J ×10⁻³ = the difference in the game's value in the session's index (score / 27000 + depth / 11),
banked at a death or valued at the calm end of the window (`tools/rollout/value.py`).

## 1. Two rules worth a whole-game A/B (candidates; micro-evidence strong, whole-game run queued)

Both are in `nhbot/data/rule_r12.json`, switched on by the option `tactic_model: "data/rule_r12.json"` (off by
default; `regress.py check` strict 32 / 32 with it off; branch `a/rl`, commit aa7cef6). They act in the fights
that are nearly lost and nowhere else.

**R1 — mobbed and losing: write Elbereth even where the script holds it back.**
`elbereth: >= 2 hostiles next to us, >= 2 of them respect Elbereth, danger.win_prob <= 0.3, HP <= 75 %` (and
Elbereth can be written here). In 68 % of these states the script is not writing because of `elb_blocked` (some
monster in view ignores Elbereth or might shoot), in the rest because HP is still above half. Typical: 3 next to
us, 7 hostiles in view, HP 40 %, depth 9, XL 7; soldier ants, wolves / jackals, moccasins off the fountain,
leocrottas, mixed mobs.

- search sample (seeds 400100–406030, one forced Elbereth then the script, any HP; 164 pairs, 58 games): dead within 300
  turns −10.4 [−20.2, −0.6], J +308 [+69, +538];
- **confirmation on fresh seeds** (414000–414065, the rule written down first — `rl-notes.md` 22:27 — and run as
  a *sustained* policy against the script, 1000 turns and on until calm; 111 pairs, 24 games): dead within 50
  turns 40.5 % → **−22.5 [−34.4, −13.5]**, within 300 turns **−19.8 [−30.3, −9.1]**, within 1000 turns 64.9 % →
  **−23.4 [−33.3, −12.4]**; J **+342 [+150, +533]**; score in the window +540. The gap does not close with the
  horizon: these are deaths avoided, not postponed.
- frequency: the rule acts at once in ~0.5 fights a game (37 such decision points in 66 games, at most one per 25
  turns).

**R2 — critically low HP and the script's prayer timer says no: pray from 150 turns after the last prayer.**
`pray: HP critically low (pray.c's own test), can_pray false, > 150 turns since the last prayer, no healing
potion in the pack, god not angry`. NetHack's rule (pray.c: timeout rnz(350) after a prayer, heard in major
trouble when it is <= 200; my Monte Carlo of rnz): a prayer g turns after the last is heard with P = 0.50 at
g = 150, 0.55 at 200, 0.66 at 300, 0.77 at 400, 0.87 at 500. The script waits for 500 (`pray_gap`).

- rollouts of 3000 turns at critically-low-HP states (seeds 410000+, 3 futures; the default is dead within 300
  turns in 72 % and within 3000 in 85 %):

  | against the script | pairs / games | dead ≤ 300 | dead ≤ 1000 | dead ≤ 3000 | score by turn 3000 | J ×10⁻³ |
  |---|---|---|---|---|---|---|
  | pray now (once) | 126 / 21 | −17.5 [−36.5, −3.7] | −14.3 [−31.4, −2.8] | −8.7 [−22.6, +2.0] | +1140 [−503, +3619] (default 2601) | +173 [−172, +602] |
  | `pray_gap` 150, sustained | 96 / 19 | −25.0 [−40.4, −11.1] | −17.7 [−34.5, −4.4] | −11.5 [−25.7, −1.0] | +1508 [+234, +3049] (default 1717) | +312 [+29, +676] |
  | `pray_gap` 300, sustained | 63 / 13 | −30.2 [−52.2, −8.7] | | | | +335 [−116, +815] |
  | melee (once) | 271 / 51 | +10.0 [+3.6, +16.0] | | | | −211 [−441, −7] |

  The 3000-turn window includes what an unheard prayer costs (the god angered, the bot never prays again). Games
  are still few (13–21): the size is uncertain, the sign is not in doubt at 300–1000 turns.
- The rule is narrower than `pray_gap: 150` on purpose: `pray_gap` also governs the prayers for lycanthropy and
  a handless polymorph, where nothing is lost by waiting.

Whole game: `rl_r12b_s` (500 games of D1 against `base_d1`, commit aa7cef6) is queued behind `rl_elb70_s`. One
game of the smoke test, seed 400201: the script dies at turn 5221 with 4 678 points mobbed by wolves and gnomes;
with the rules it is alive at depth 21 with 96 212 points when my 60 000-key cap stops it (the rule acted twice).
One game is an anecdote; it shows why a few avoided deaths can move the mean.

## 2. What the rollouts say about everything else: the script's choices stand

One forced action, then the script (general decision points: a hostile next to us and HP < 50 %, or danger.py
flags the fight; ~4 000 points, 300 games):

| forced instead of the script | where | deaths ≤ 300 turns | note |
|---|---|---|---|
| melee | script says Elbereth (782 pairs) | −0.1 [−2.2, +1.9]; ≤ 50 turns +1.2 [+0.1, +2.4] | no pace gain either (score −16) |
| melee | fights nearly lost (789 pairs, 75 games) | +2.8 [0.0, +6.0]; ≤ 50 turns +4.9 [+2.6, +8.2] | |
| zap the attack wand | everywhere (320) | +3.0 [−0.3, +5.7]; win_prob 0.3–0.6: +16.7 [+7.6, +28.6] | the script's wand rule is right to hold back |
| quaff a healing potion | everywhere (160 in dangerous fights) | +0.6 [−4.4, +7.1] | |
| down / up the stairs within 15 squares | everywhere (222 / 309) | +3.8 [−0.6, +8.9] / +0.5 [−3.2, +3.7] | at win_prob < 0.3: −10 [−30, +4] / −6 [−18, +1]: open |
| Elbereth | ordinary fights where the script fights | −2.8 [−5.5, −0.2] at 300 turns, gone later | see 3. |

Sustained parameter variants: `pray_gap` 800: +13.2 [+5.3, +21.9] (n 19) — waiting longer is clearly worse;
`rest_frac` 0.7 / 0.9: 0.0 / −0.1 deaths, −26 / −31 score a window; `elb_hp` 0.35: +1.3 [−0.1, +2.7], +41 score;
`elb_exit` 0.7: −0.4 [−1.2, +0.4], +14 score.

## 3. The trap in the method: a 300-turn window overrates anything that postpones a fight

`elb_hp` 0.7 and `elb_exit` 1.0 cut deaths within 300 turns (−1.3 [−2.9, 0.0], −1.7 [−3.3, −0.2]); played out
for 3000 turns (389 points, 49 games) the gain is gone and the score is a little behind: `elb_hp` 0.7: deaths
−0.4 at 1000 turns, score −137 at 1000, −295 [−886, +271] at 3000 (default 5760). One forced Elbereth in an
ordinary fight: deaths +1.2 [−5.9, +7.9] at 3000. A window that ends with the bot still on its square and the
monster still there counts a postponed fight as a won one; and about half of the default's rollouts are dead by
turn 3000 in either hand, so the score is made by pace. That is why I queued `rl_elb70_s` (the owner's −1209 was
on a much older bot): as a calibration of the label, not as a candidate. Since then every rollout plays on until
the fight is over (`settle`) and is valued in J, and a rule counts only if its gain holds at 1000+ turns (R1, R2
do). `rl_elbexit100_s` cancelled.

## 4. Where the deaths are (for the other agents)

- 42 of 60 collecting games died within 25 turns of a decision point: the trigger sees about two thirds of all
  deaths. In those last fights the default is dead within 50 turns in 74 % of fresh re-rolls.
- 11 of 43 fatal fights were at the fountain: 4–5 water moccasins or a water demon at XL 5, full HP, standing on
  the fountain (no Elbereth there). base_d1 + base_d2 (2000 games), commonest attacker in the last messages:
  water demon 4.5 % of games, water moccasin 3.9 % (mean score 3.3 k / 4.4 k), troll 2.5 %, soldier ant 2.5 %,
  starvation 2.5 % (mean 61 k), killer bee 2.4 %, fire ant 2.2 %, leocrotta 2.2 %, gremlin 1.8 % (mean 78 k).
- danger.win_prob against what happens (2 853 points, the script playing): where it says >= 0.99 (974 points)
  2.6 % are dead within 20 turns; unseen attackers ('I': 1.0 by construction) 16.7 % within 50; dwarf, jackal
  packs, hill orc, fire ant are worse than modelled; pony, giant bat, giant ant, rothe much safer.

## 5. Open

- R1 / R2 whole-game (`rl_r12b_s`), more confirmation points (`m2`), R2's size (`x3` still collecting).
- A learned chooser over the same states (stage 3) only if it beats R1 + R2 on held-out games.
- The harness can screen any tactical option of another branch the same way in under an hour (merge the branch
  into an evaluation checkout, add a line to `collect.VARIANTS`).

## 6. Whole game, 23:21 UTC: `rl_r12c_s` (R1 + R2, 500 games of D1, commit a7475f2) against `base_d1`

```
A base_d1                  n 500  score mean 26179 median 9410  depth mean 10.95  crashes 0  truncated 7  turns 10335  steps 20134  secs/game 86
B rl_r12c_s                n 500  score mean 27999 median 9630  depth mean 11.35  crashes 0  truncated 5  turns 10599  steps 20968  secs/game 42
  score  diff +1820  80% CI [+390, +3267]  95% CI [-358, +4040]  <-- WIN
  depth  diff +0.398  80% CI [+0.196, +0.594]  95% CI [+0.082, +0.702]  <-- WIN
  J      diff +0.104  80% CI [+0.035, +0.173]  95% CI [-0.000, +0.208]  <-- WIN
  log10  diff +0.039  80% CI [+0.018, +0.058]  95% CI [+0.008, +0.069]  <-- WIN
  games changed: 245 of 500
```

- R1 acted in 225 games (1.11 times a game), R2 in 77 games (0.19 times a game).
- R2's cost shows: prayers a game 3.16 → 3.37, unheard prayers a game 0.058 → 0.080, games ending with an
  angered god 48 → 64, starvation deaths 36 → 40. This run cannot split the net of R2 from R1's: run
  `data/rule_r1.json` and `data/rule_r2.json` apart before taking R2.
- The calibration run `rl_elb70_s` (elb_hp 0.7): score −1478 80 % CI [−4573, +1475], depth −0.010, J −0.056
  [−0.207, +0.086], median 9410 → 7980: as the 3000-turn rollouts said, not as the 300-turn deaths said.
