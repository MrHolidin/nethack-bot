# diag: where the bot loses score and depth (agent `diag`, 2026-11-11)

Data: 3662 games: base22_80k + base22_81k (2000), base_d1 (995 of 1000), base_d2 (667 of 1000, still running).
Mean score 25 933, mean depth 11.08, 33 truncated, 0 crashes. Scripts: `tools/diag/` (load.py = rows + a better
death cause; main.py, main2.py, main3.py; run on nhbox in /workspace/agents/diag, output out3.txt).

**How "gain" is computed.** A death at max depth d with XL bucket x is replaced by the mean final score (depth) of
the games that were on depth d in the same XL bucket and went deeper (the continuation value V(d,x)). gain = Σ(V −
score) / all games: the mean-score gain **if every death of that cause were avoided**. This is an upper bound: the
survivor pool is selected (better games), and no fix removes every death. Summed over all causes it is 42 k per game,
so do not add rows. Assume a real fix gets 20–40 % of it.

## Ranked opportunities

| # | What | Evidence | Upper bound gain (score / depth) | Realistic | Hard | Suggested fix |
|---|---|---|---|---|---|---|
| 1 | **Die after the emergency prayer in the same fight** | 49 % of deaths (1788/3629) end with `can_pray` False and god not angry; **turns since last prayer at death: median 40**, 73 % < 200. So the bot prays, gets its HP back, goes on fighting the same monsters and dies. A further 37 % (1361) die from above the prayer threshold (burst) while a prayer was available | cuts across all families (~0.5 of the 42 k) | +1000–2000 / +0.3 | M | After an HP prayer, while the monsters that brought us down are still in view: disengage (up stairs if close, Elbereth if they respect it, unknown potions / scrolls / wands as escapes) and do not resume melee before HP ≥ 2/3. Also: escape earlier when expected damage next turn ≥ HP − threshold (bursts) |
| 2 | **Fountain: water demon / moccasins** | 330 deaths = **9.0 %** of games, median XL 5, depth 6, score 4.7 k. Pre-Excalibur water demon lethal (died < 80 turns): XL≤4 at snap before 83 %, XL5 73 %, XL6 30 %, XL7+ 5–15 %; post-Excalibur ≤ 10 %. By max HP: 30–44 → 66 %, 45–59 → 38 %, 60–74 → 13 %. 217/330 had **no prayer available** at death; Elbereth never tried (0/330); 9 % on/next to stairs | +3060 / +0.66 | +1000–1500 / +0.3 | E–M | Gating by XL was A/B'd and lost (`excal_xl` 6: −675, 7: −952; `excal_hp` 0.95: −754, JOURNAL_AUTO.md:35-44), so change the *conditions and the response*, not the XL: (a) dip only while `can_pray()` (the prayer is the rescue); (b) on "You unleash a water demon" / "endless stream of snakes": step off the fountain (engrave.c:524: you can't write on a fountain) and engrave — `elb_rules` puts the water demon among the blockers because it has AT_WEAP, although a water demon carries no weapon. Moccasins (S_SNAKE, animal) respect Elbereth; (c) prefer fountains ≤ 3 steps from the up stairs and leave by them. Note `dip_events` logs no moccasin event (excalibur.py:166) |
| 3 | **Soldier ants / fire ants / killer bees** | 275 deaths = 7.5 %, depth 8, XL 7; burst 71 %, 2.4 adjacent, 91 % faster than us (18), Elbereth tried in 26 % | +3180 / +0.56 | +700–1000 / +0.15 | M | Elbereth *before* engagement when an `a` is in view and HP < ~70 % (they respect it, can't outrun them); never fight 2+ in the open; up stairs when ≤ 2 steps |
| 4 | **Starvation with an angry god** | 142 deaths = 3.9 %; **117 god_angry**, prayers median 6, weak+fainting ~1000 turns, median 6363 turns on the death level, 45 die on a shallow main level with no down stairs found. Praying too soon = p_type 0 → `gods_upset` → angry (pray.c:1820, 1911-1915). 350 god-angry games in all, 198 with `pray_failed` | +1270 / +0.25 | +400–700 / +0.1 | M | god angry / no prayer left: stop counting on prayer for food — keep a ration, eat every safe corpse, when Hungry leave the level (new level = food) instead of searching; fix the anger at an altar (sacrifice exists). Reduce failed prayers: model the timeout as rnz(350) (pray.c:1220) |
| 5 | **Elves** (Green/Grey/Woodland-elf, elf-lord, Elvenking) | 183 deaths = 5.0 %, depth 11, XL 9, burst 67 %, 2.3 adjacent, ignore Elbereth (@) | +2430 / +0.35 | +500 / +0.1 | H | fight in corridors / doorways, one at a time; up stairs when ≥ 2 adjacent and losing; mostly a fight-model "retreat" problem (see #1) |
| 6 | **Trolls** (troll, rock troll, Olog-hai, ice troll) | 169 = 4.6 %, depth 15, XL 10; **slow grind** (burst only 43 %, 16 % faster than us), 111/169 prayer timeout | +2240 / +0.26 | +500 / +0.1 | M | it is a grind: retreat when the fight model says losing (time exists); after a kill stand on / eat / tin the corpse (revives) |
| 7 | **Unseen ("It bites!") melee** | 140 = 3.8 %, 2–5 adjacent shown as `invisible`, only 12 with blindness messages | +1700 / +0.27 | ? | M (investigate) | add Blind / the `I` glyph state to `hist`; likely blind (yellow light) or dark-room swarms; unihorn / retreat to a corridor |
| 8 | **Mumak, leocrotta** | mumak 61 (1.7 %), speed 9 < our 12, burst 75 %, Elbereth 46 %; leocrotta 74 (2.0 %), speed 18, burst 81 %, Elbereth 45 %. Neither is named anywhere in nhbot/ | +760 + 1015 / +0.26 | +400 / +0.08 | E | mumak: never melee below full HP / AC worse than −3: walk away (it is slower). leocrotta: Elbereth before contact (respects it) |
| 9 | **Stuck shallow levels** | 1068 level visits ≥ 3000 turns; D1–4 take 4491 turns per game = 45 % of all turns (1094 of them search); 1032 turns/game on stuck levels ≤ D6; 94 main-dungeon stuck visits with no down stairs (64 die there, 45 starve) | via #4 + depth | +0.1–0.2 depth, +300 | M | no down stairs after ~1500 turns: try the Mines branch, read unknown scrolls (teleport/mapping), engrave-test wands (digging), kick/force; don't search 20 000 turns (80007: 27 707 turns on D4, 26 939 searching) |
| 10 | **Deep games stuck at Medusa / Castle** | depth ≥ 21: 12.5 % of games hold **56 % of the score**; their longest level is D22–27 with no down stairs known; killers: trolls 39, starvation 37, gremlins 35 (5.4 adjacent: they multiply in water), gargoyles 25, soldiers 23, electric eels 22 | big but diffuse | ? | H | no fighting next to water (eels drown, gremlins split); food for 20 k-turn waits (37 starve); kill gremlins away from pools |
| 11 | **Truncation / keys** | 33 games (0.9 %) hit 200 k keys, mean score ~100 k, 4–7.6 keys/turn, 40–67 % of turns searching. Overall 1.88 keys/turn; least-squares keys/turn by activity: search 2.5, explore 2.0, fight 5.4, minesup 7.1, luckstone 8, retrieve_missiles 24 | — | +200–400 | E–M | `search_turns` sends "20s" but "You stop searching" interrupts (in last msgs of 316 games); in long games use larger counts / stop re-issuing each tick; retrieve_missiles keys |
| 12 | **Monster wands / rays** | wand of striking + rays: 109 deaths = 3.0 %, depth 6–7 | +1260 / +0.2 | +200 | M | kill zappers first, pick up their wands; don't stand in line with a known zapper |

Smaller (each < 1.3 %): trap 44 (spiked pits repeatedly, rolling boulder, chest trap), own wand exploded 27 (mostly
electricity destroying wands, not self-breaking), owlbear 33, wolf 40, minotaur 33, fire giant 26, ogre king 30,
watch / angered law 17, Medusa's gaze 6, mind flayer psychic 5, bad prayer 9.

## Five numbers

1. **49 %** of deaths happen with the prayer on timeout, **median 40 turns** after it — the prayer saved the HP, the fight continued.
2. **9.0 %** of games die to a fountain (water demon / moccasins), median XL 5; a pre-Excalibur water demon kills **73–83 %** of the time at XL ≤ 5 and ≤ 15 % at XL ≥ 7 — but delaying the dip was already A/B'd negative, so fix the response.
3. Starvation 3.9 %: **117 of 142** starve with an angry god (pray too soon → `gods_upset`).
4. D1–4 eat **45 % of all turns** (4491 / game), 1068 level visits last ≥ 3000 turns.
5. At arrival on Dlvl 10, AC predicts success best: AC ≤ −6 → 78 % reach D15, mean 85 k; AC 0 → 51 %, 48 k; AC 2 → 36 %, 37 k (corr −0.35; max HP +0.39; XL +0.19).

## Supporting tables

### Top killers (by family; columns: n, % games, median depth, median XL, mean score, lost per death, gain score, gain depth, burst, adjacent, cpray, prayed, stairs, fast, Elbereth)

```
ants/bees            275  7.5   8  7 10737 42369 3182 0.56  burst.71 adj2.4 cpray.52 prayd.02 stair.09 fast.91 elb.26
FOUNTAIN             330  9.0   6  5  4667 33970 3061 0.66  .75 3.2 .60 .02 .09 .49 .02
elves                183  5.0  11  9 23872 48682 2433 0.35  .67 2.3 .60 .03 .09 .23 .03
trolls               169  4.6  15 10 47305 48550 2241 0.26  .43 1.6 .47 .02 .07 .16 .01
unseen/blind melee   140  3.8  10  8 19162 44505 1701 0.27  .55 2.3 .48 .06 .11 .07 .01
starvation           142  3.9   7  6 42399 32720 1269 0.25
soldiers              89  2.4  18 11 55393 52105 1266 0.12  .60 2.6 .60 .01 .04 .12 .03
orcs                 118  3.2   6  6  4879 37190 1198 0.25  .48 2.4 .42 .03 .08 .15 .03
gargoyles             87  2.4  14 10 50092 47398 1126 0.14  .71 1.7 .62 .03 .15 .63 .00
leocrotta             74  2.0  11  9 20601 50220 1015 0.14  .81 1.8 .64 .00 .09 .88 .45
monster wand/ray      73  2.0   7  7 15117 42864  854 0.15
mumak                 61  1.7  10  8 16443 45860  764 0.12  .75 1.6 .64 .00 .11 .25 .46
gremlin               50  1.4  23 12 87475 37220  508 0.05  .72 5.4
```
burst = ≤ 3 turns from HP ≥ 50 % to death; cpray = a tick with HP < 1/3 and prayer available (HP was still above
the bot's prayer threshold then); fast = an adjacent monster faster than 12; Elbereth = engraving in the last 10
messages. "prayed" is low because the prayer usually happened > 10 messages before the end (see #1).

### Prayer state at death (3526 with hist)
prayer on timeout 1719 · prayer available, killed from above threshold 1361 · god angry 350 · prayed in last msgs 96.

### Phase (depth × XL at death), share of games, top killers
- D1–4 XL1–5: 7.4 % — starvation 39, fountain 31, djinni 20, traps 10
- D5–9 XL1–5: 15.5 % — **fountain 178**, ants 53, orcs 35, starvation 24
- D5–9 XL6–8: 22.7 % — ants 106, fountain 66, orcs 53, elves 44, unseen 33
- D10–14 XL6–8: 11.9 % — ants 33, unseen 29, leocrotta 24, trolls 21
- D10–14 XL9–10: 16.4 % — elves 57, ants 50, trolls 38, gargoyles 25, fountain 22
- D15–20 XL9+: 8.6 % — trolls 49, soldiers 41, elves 16, gargoyles 13
- D21+ XL11+: 12.0 % — starvation 37, trolls 34, gremlins 33, gargoyles 24, eels 21, soldiers 21

### Predictors (alive at the checkpoint; success = reaches D15)
- Arrival D5, XL: 3–4 → 22–24 % (26–28 k); 5 → 30 % (31 k); 6–8 → 31–36 % (40–43 k). Arrival turn 4–7 k → 33 %
  (38 k) vs < 2 k → 24 % (28 k): slower, stronger early descents do better (confounded with XL).
- Arrival D5, AC: −6 → 50 % (60 k); 0 → 25 % (30 k); 6 → 16 % (21 k). Excalibur by D5: 42 % (47 k) vs 23 % (27 k).
- Arrival D10, XL: 7 → 43 % (35 k); 9 → 59 % (61 k); 10 → 65 % (81 k). Excalibur 60 % vs 36 %.
- Turn 6000: corr with success — Excalibur +0.27, AC −0.24, max depth +0.23, XL / max HP +0.21, prayers used −0.14,
  pet 0 (no pet survives to 6000 turns in practice: 1 %).
- Excalibur overall: 1718 games mean 44 k / depth 14.5 vs 1944 without 9.8 k / 8.0 (heavily survivor-selected).

### Time
explore 50.6 %, search 27.1 %, rest 4.4 %, eat_corpse 3.8 %, fight 3.6 %, Mines up/down 2.6 %, fountain_wish 0.5 %
(175 k turns for 185 wishes and 817 post-Excalibur water demons, 50 deaths). Turns per game by depth: D1–4 4491,
D5–9 2831, D10–14 812, D15–20 742, D21+ 951. Loops > 0 in 89 games (max 631), all `None/other`.

## Odd things / possible bugs
- `hist` names every unseen adjacent hostile `invisible` (the remembered `I`); there is no Blind flag in `hist` — add
  one to tell blindness from invisible monsters.
- `dip_events` records water demons only, not water moccasins (excalibur.py:166) — moccasins kill 136 games.
- Pyrolisk gazing from out of reach while the bot keeps searching ("You stop searching" loops): 37 games, 300431
  died at 3/56 HP so.
- "A mysterious force prevents the tengu/unicorn from teleporting!" fills the last messages of 92 games (deep
  levels) — harmless spam but hides the real death messages (11 games end with 6 identical lines).
- 300912 ate a tainted corpse ("Ulch - that meat was tainted") then died after a too-early prayer: corpse age check miss.
- Electric shocks (chest trap, lightning) explode wands in inventory: 27 deaths "own wand exploded".
- No crashes; 1 non-crash game with score 0.

## Not done (time box)
Elbereth effectiveness per monster (elb_exits / elb_stats); keys per activity measured directly (only a regression);
`goals` / `danger` fields; per-seed comparison of base22 vs base_d (they are mixed here); `search_log` of stuck levels.
