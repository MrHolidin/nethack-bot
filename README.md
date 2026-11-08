# nethack-bot

Scripted NetHack 3.6.6 bot on the NetHack Learning Environment (NLE). Objective: in-game score (also tracks
max dungeon depth). Plays Valkyries; role-specific behaviour sits behind `self.role` checks so other roles
can be added later.

## Layout

`nhbot/` — the bot, one domain per module (each module is a mixin of `Bot`):

| module | what it does |
|---|---|
| `bot.py` | `Bot`: construction, the game loop (`run`), the summary |
| `policy.py` | the decision order: `tick()` runs the steps in `STEPS`, the first one that acts ends the tick; `HOUSEKEEPING`: the jobs of the housekeeping step, in order |
| `options.py` | every option and its default; unknown names raise |
| `game.py` | keys, prompts, `--More--`, the message log (`log_msg`: new or repeat; `on_message`: the domains' handlers in order), status line, inventory text |
| `actions.py` | the primitive actions, each doing its own bookkeeping: attack, take_stairs, search_turns, throw, zap, engrave, drop_units |
| `events.py` | the message event layer: each message parsed once into typed events (our blows and kills, attacks on us, monsters' missiles / wands / breath, items destroyed, thefts); `Message.repeat`: a message NLE shows again |
| `mapmem.py` | per-level map memory, terrain / passability grids, shop marking, where the stairs we took lead |
| `nav.py` | Dijkstra, single steps, door kicks, walking toward a square |
| `perception.py` | hostile / peaceful monsters, threat gates, line targets |
| `survival.py` | prayer, eating, hunger, healing potions, #enhance, the vault guard |
| `combat.py` | melee targets, throwing targets, unblocking, hunting a shooter, attack wands |
| `elbereth.py` | engraving and standing on Elbereth (`elb_rules.py`: who respects it) |
| `thieves.py`, `weapons.py` | nymphs and monkeys; wielding the best weapon |
| `explore.py` | exploration, descending, searching, the Gnomish Mines (`mines_tick`: the per-tick Mines bookkeeping) |
| `hidden.py` | hidden-passage candidates of the known map (room sides, dead ends) and their features; `search_log` |
| `truemap.py` | experiments only: the true map of the level read from the game's memory (secret doors and corridors, stairs) -- how, in its docstring |
| `excalibur.py`, `equipment.py`, `carry.py`, `shop.py`, `scrolls.py`, `pricemem.py`, `focus.py` | Excalibur, armor, valuables, weight and selling (`carry.py`, also the refused diagonal squeeze), shops, good scrolls, price identification, target choice |
| `vault.py`, `digging.py`, `digthrough.py` | vaults (rob, find, the guard's question); diggers: which one, wielding it, applying it; digging through a refused squeeze / a stuck boulder |
| `consts.py`, `monsters.py`, `glyphs.py`, `monattacks.py`, `weapondice.py` | shared tables (`monsters.py`: monster lists, name -> index maps, monflag / mresists bits) |

Top level:

- `eval.py` runs N games in parallel and writes jsonl; `compare.py` does paired bootstrap comparisons
  (80% CI on the mean difference).
- `regress.py` checks that a refactor does not change behaviour: 32 fixed seeds under the CI clock,
  per game the outcome and a hash of every key sent, against `golden.json`
  (`python regress.py check`; `--level outcome` for changes that only drop free actions; `--kw` plays with
  options, e.g. record with an A/B flag on before making it the default).
- `tools/`: `cases.py` (death analysis from `hist`), `random_baseline.py`.
- `python -m nhbot SEED` plays one game and prints its summary.

Parallel evaluation runs on GitHub Actions: workflow **eval** (`workflow_dispatch`), sharded by character and
seed range; options go in `kw` as JSON (`{"pray_gap": 700}` or `{"role_opts": {...}}`).
