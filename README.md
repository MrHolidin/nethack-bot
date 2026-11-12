# nethack-bot

Scripted NetHack 3.6.6 bot on the NetHack Learning Environment (NLE). Objective: in-game score (also tracks
max dungeon depth). Plays Valkyries; role-specific behaviour sits behind `self.role` checks so other roles
can be added later.

## Layout

`nhbot/` — the bot, one domain per module (each module is a mixin of `Bot`):

| module | what it does |
|---|---|
| `bot.py` | `Bot`: construction, the game loop (`run`), the summary; `__main__.py`: `python -m nhbot SEED` |
| `policy.py` | the decision order: `tick()` runs the steps in `STEPS`, the first one that acts ends the tick; `HOUSEKEEPING`: the jobs of the housekeeping step, in order |
| `options.py` | every option and its default (experiments and A/B flags, all off; HP thresholds; parameters); unknown names raise |
| `game.py` | keys, prompts, `--More--`, the message log (`log_msg`: new or repeat; `on_message`: the domains' handlers in order), status line, inventory text, farlook; the hook lists `pile_readers` / `level_holders` / `digger_holders` |
| `actions.py` | the primitive actions, each doing its own bookkeeping: attack, take_stairs, search_turns, throw, zap, engrave, drop_units |
| `events.py` | the message event layer: each message parsed once into typed events (our blows and kills, attacks on us, monsters' missiles / wands / breath, items destroyed, thefts); `Message.repeat`: a message NLE shows again |
| `items.py` | one parse of each inventory line, so every module reads the same state |
| `mapmem.py` | per-level map memory, terrain / passability grids, shop marking, where the stairs we took lead |
| `nav.py` | Dijkstra, single steps, door kicks, walking toward a square |
| `goals.py` | the squares we walk to for something lying there (gold, piles, altars, boxes, ...), in one registry |
| `perception.py` | hostile / peaceful monsters, threat gates, line targets |
| `threats.py` | which monsters in view are coming for us: their tracks from tick to tick |
| `survival.py` | prayer, eating, hunger, healing potions, #enhance, the vault guard |
| `combat.py` | melee targets, throwing targets, unblocking, hunting a shooter, attack wands |
| `danger.py`, `fightmodel.py` | the melee danger estimate (the damage of the next turn, P(death), `win_prob`); the model's parts beyond the plain attack dice (spells, negative AC, ...) |
| `rays.py` | our own ray bouncing back at us, and the walk of a ray / beam square by square |
| `retreat.py` | leave a melee fight being lost -- by the stairs, Elbereth, a teleport scroll or a wand of digging; rest on the arrival staircase after a flight |
| `tactic.py`, `tacticmodel.py` | the fight's tactical options as explicit choices, chosen by the model of `tactic_model` (rule R1: Elbereth when mobbed and losing); its plain-numpy inference |
| `elbereth.py` | engraving and standing on Elbereth (`elb_rules.py`: who respects it) |
| `thieves.py`, `weapons.py` | nymphs and monkeys; wielding the best weapon |
| `goldbag.py` | our gold kept in a bag while a leprechaun is in view |
| `explore.py` | exploration, descending, searching, level travel by known stairs |
| `mines.py` | the Gnomish Mines as a trip: closed below `mines_xl` and before Excalibur, Minetown, the way back out |
| `luckstone.py` | the Mines' End luckstone: the hunt, picking it up, keeping it |
| `sokoban.py`, `soko_data.py`, `soko_solver.py` | `sokoban` (option, off): up into Sokoban, its levels solved by the plans of `soko_data` (`tools/soko_solve.py`); the solver |
| `deep.py` | the water dead ends at the bottom of the main dungeon: Medusa's level and the Castle told from the map; back up and a patrol of the level above instead of searching walls; hooks in explore / mapmem (`deep_explore`, `dead_end_step`, `deep_stairs`, `deep_passable`, `deep_up_closed`) |
| `hidden.py` | hidden-passage candidates of the known map (room sides, dead ends) and their features; `search_log` |
| `truemap.py` | experiments only: the true map of the level read from the game's memory (secret doors and corridors, stairs) -- how, in its docstring |
| `excalibur.py`, `materials.py` | Excalibur (the dip, and holding Elbereth against what a dip lets out); what water does to an object |
| `equipment.py`, `jewelry.py` | armor (and the answer to a wish); amulets and rings: worn when known useful, identified with a scroll |
| `pickup.py`, `value.py`, `carry.py` | what lies where and is worth a walk, what to take from a pile; what an item is worth to us; weight, valuables, selling (also the refused diagonal squeeze) |
| `shop.py`, `pricemem.py` | shops; price identification |
| `scrolls.py`, `wandid.py`, `charges.py`, `potiontest.py`, `altar.py` | good scrolls; wands identified by engraving; wand charges; potions tested by drinking; the altar BUC test |
| `tins.py`, `boxes.py`, `locktools.py` | tins picked up and opened; large boxes and chests opened; the best unlocking tool kept |
| `wishing.py` | going after wishes |
| `focus.py` | target choice |
| `poly.py` | polymorphed: the form we are in and whether it has hands |
| `vault.py`, `digging.py`, `digthrough.py`, `rockdig.py` | vaults (rob, find, the guard's question); diggers: which one, wielding it, applying it; `dig_through` (option, off): a refused squeeze / a stuck boulder; gold and gems inside solid rock |
| `sacrifice.py`, `gift.py` | `sacrifice` (option, off): corpses offered at a neutral altar; `gift` (experiments): items put into the inventory at the start |
| `consts.py`, `monsters.py`, `glyphs.py`, `monattacks.py`, `monalign.py`, `weapondice.py` | shared tables (`monsters.py`: monster lists, name -> index maps, monflag / mresists bits) |

Top level:

- `eval.py` runs N games in parallel and writes jsonl; `compare.py` does paired bootstrap comparisons
  (80% CI on the mean difference).
- `regress.py` checks that a refactor does not change behaviour: 32 fixed seeds under the CI clock,
  per game the outcome and a hash of every key sent, against `golden.json` -- recorded from `gen2`
  (`python regress.py check`; `--level outcome` for changes that only drop free actions; `--kw` plays with
  options, e.g. record with an A/B flag on before making it the default).
- `python -m nhbot SEED` plays one game and prints its summary.

`tools/`:

- `farm/nhq.py`: the game farm on the evaluation machine -- one scheduler for every agent's runs (`nhq submit`,
  `status`, `wait`, `cmp A B`; `nhq run REF -- CMD` runs a command in a checkout of REF under the pinned clock);
  `farm/nhdash.py`: its one-page dashboard.
- `rollout/`: counterfactual rollouts by fork at the fight's decision points, and the training of the
  `tactic_model` chooser (its own README).
- `diag/`: death taxonomy, score at stake, survivor predictors over result files.
- `replay.py` records one game as a replay for `replay_viewer.html` (or a self-contained HTML).
- `cases.py` (death analysis from `hist`), `random_baseline.py`; debugging of no-time loops and keys:
  `keytrace.py` (option `key_stats`), `loopstack.py`, `farlook_check.py`, `luckdbg.py`.
- `soko_solve.py`, `soko_import_aa.py`: the Sokoban plans of `nhbot/soko_data.py` (from `tools/data/`).

Parallel evaluation runs on GitHub Actions: workflow **eval** (`workflow_dispatch`), sharded by character and
seed range; options go in `kw` as JSON (`{"pray_gap": 700}` or `{"role_opts": {...}}`).
