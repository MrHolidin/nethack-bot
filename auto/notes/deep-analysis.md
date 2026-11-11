# The late game (max depth 18+): where the games end and where the score comes from

Agent `deep`, branch `a/deep`. Data: the 2000 baseline games of origin/results (`base22_80k`, `base22_81k`,
seeds 80000..81999); the same script on `base_d1` + `base_d2` (1857 of 2000 games done at the time) gives the same
picture. Scripts: `/workspace/agents/deep/an2.py`, `an3.py`, `an4.py` on the machine.

## Numbers

- 379 of 2000 games reach Dlvl 18+ (19 %); they hold 69 % of all score (mean 102 700).
  By max depth: 18-20: 89 games, mean 59.6 k; 21-23: 139, 98.5 k; 24-26: 118, 125.9 k; 27-29: 33, 153.8 k.
  None reaches Gehennom (dungeon 1); 9 deep games end in Fort Ludios (dungeon 5, by a vault's portal).
- Where a deep game ends (level kind guessed from `level_stats`: depth, `down_known`, `seen` squares):

  | terminal level                                   | games | truncated | mean score | turns on it | keys   |
  |--------------------------------------------------|-------|-----------|------------|-------------|--------|
  | in transit (an ordinary level, < 3000 turns)     | 192   | 2         | 78 900     | 350         | 34 k   |
  | Medusa, lit variants (seen > 900, no `>`)        | 108   | 6         | 122 100    | 9 150       | 75 k   |
  | Medusa-2 (the closed arrival building: seen 100) | 30    | 0         | 132 900    | 6 130       | 44 k   |
  | the Castle (25+, no `>`, seen < 420)             | 12    | 0         | 174 300    | 15 500      | 81 k   |
  | another level with no way down found             | 24    | 1         | 130 300    | 11 300      | 81 k   |
  | a stuck level whose `>` was known                | 4     | 2         | 225 500    | 15 900      | 126 k  |

  So 150 of 2000 games (7.5 %) end at Medusa or the Castle; only 15 of the 153 games that see Medusa's level get
  below it (trap doors / holes of the level above that drop two levels: trap.c fall_through, 1 in 4 a further
  level), 2 of 14 leave the Castle downward, none through its trap doors.
- **The score of the deep games is made on the way down, not while stuck.** Kills per 500 turns (snaps):
  Dlvl 15-20 moving 4.96, stuck 0.80; Dlvl 21-24 moving 6.43, **stuck 0.31**; Dlvl 25+ moving 6.19, stuck 0.78.
  Score against the turns spent on the terminal stuck level: 0-1000 turns 118.6 k, 3-6 k turns 125 k, 10-15 k turns
  135 k, 25 k+ turns 179 k: about 1.5-2.5 points a turn stuck, against ~15-20 a turn while descending (each level
  from 15 to 22 adds ~8-9 k). A level's own monsters are the income; the 1-in-70-turns random monster mostly never
  reaches a hero who stands on an island or in a dead end.
- Deaths at Medusa (132 of 138): gremlins 16.5 (they multiply in the water), starvation / fainting 14, electric
  eels 11.5 (Medusa-2: all of them -- the bot finds the west secret door, which opens on the lake), winged
  gargoyles 8.5, mind flayers 10, Medusa's gaze 4 (see below), vampire bats, jabberwocks, explosions (gas spores /
  yellow lights) ... At the Castle (12): starvation 5, the rest single. In transit (190): trolls 21 (troll, rock,
  ice, Olog-hai 6.7), minotaurs 8-10, soldiers / lieutenants 13, lightning / fire / magic missile / death rays 16,
  invisible things 9.5, elf-lords 6, winged gargoyles 6, cockatrices 4.5.
- Starvation: 24 of the 170 deaths on stuck levels. Stuck games pray 12 times a game (others 3.6), 1.1 % of their
  turns Fainting.
- Truncated at 200 000 keys: 20 games (mean 120.7 k), 11 of them deep; the other 9 are stuck at Dlvl 5-13 for
  17-37 k turns (searching: not my area -- the generic dig-down of agent `dig` is the answer there).
- `revisit_up` kills: climbing to a level above that we fell past is fatal when that level is Medusa's (we arrive
  on her island, next to her): 4 "gaze" deaths + 2 "Medusa" melee deaths per 2000 games.

## Facts checked in the 3.6.6 source (NLE's copy, /workspace/agents/rl/nle-src)

- dungeon.def: `medusa @ (-5, 4)` -- 1 to 4 levels above the Castle (the bottom level, Dlvl 25-29), so Medusa is
  Dlvl 21-28; the levels between are ordinary. `castle @ (-1)`, Gehennom chained to it `no_down`.
- medusa.des: flags `noteleport` only, not hardfloor -- dungeon.c:1300 Can_dig_down is true: **a hole can be dug
  on Medusa's level**. dig.c:504 fillholetyp: a hole (and the pit before it, dig.c dig -> dighole(pit_only)) fills
  with water with chance n/(n+1), n = moat squares among the 3x3 around it -- then we fall in, crawl out, the
  inventory is wet (trap.c drown -> water_damage_chain). So: dig on a square with no water next to it. Such squares
  exist on the arrival island of medusa-1 (33 of them), in the arrival building of medusa-2 (46), on one of the four
  arrival islets of medusa-4 (14 of 45 stair positions); none on medusa-3 (every square touches water: 1/4 per try
  with a pick-axe, two rolls; 1/2 with a wand of digging, one roll).
- medusa-2: the up stairs are in a closed building (4 x 14) with three pool squares; its only doors are secret:
  west (1,5) opens on the lake (eels), east (6,14) can be reached only across the pool. Searching there is deadly
  and useless.
- castle.des: arrival (falling or by stairs) in the maze west of the moat, up stairs there too; no stairs down; the
  five trap doors are inside, behind the drawbridge (raised) -- the walls are undiggable (NON_DIGGABLE), the floor
  cannot be dug (bottom level: dig.c dighole "too hard to dig in" after the pit). Giant eels at (5,7) and (5,9), next
  to the lit court in front of the drawbridge; sharks at the corners.
- zap.c bhitpos / dbridge.c: a wand of striking / force bolt destroys the bridge (raised too, hit on the portcullis
  square) and leaves a moat square -- no way in. Opening (wand, spell, the passtune) is the only entry without
  levitation / cold; the bot has none of them as a rule. The Castle is the end for this bot.
- 259 of the 379 deep games picked up a digger at some time (pick-axe / mattock; `pickup_stats.digger`), kept by
  carry.py ("never sold").

## What follows

1. More levels are worth more than more turns: each new level at Dlvl 21+ is ~6 kills and ~8-10 k points, +1
   depth. Digging down past Medusa (1-4 levels to the Castle) is the only source of new levels the bot can use.
   Expected: ~40 % of the Medusa games (a dry square x a digger) -> ~3 % of all games gain ~2.5 levels.
2. Standing still when stuck earns almost nothing (0.3 kills / 500 turns) and still dies (gremlins, eels,
   starvation). "Camp safely until the key limit" is worth little: +2 points a turn. Walking the level above
   (ordinary, explored) should meet the random monsters that never reach an island -- to be measured (patrol).
3. Never climb onto Medusa's level from below (revisit_up to a level never seen at Dlvl 21-28, or the level we
   dug out of).
4. Not searching walls at Medusa / the Castle saves keys only; the 11 deep truncated games gain little from it.
