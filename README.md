# nethack-bot

Scripted NetHack 3.6.6 bot on the NetHack Learning Environment (NLE). Objective: in-game score (also tracks
max dungeon depth). Plays Valkyries; role-specific behaviour sits behind `self.role` checks so other roles
can be added later.

## Layout

`nhbot/` — the bot, one domain per module (each module is a mixin of `Bot`):

| module | what it does |
|---|---|
| `bot.py` | `Bot`: construction, the game loop (`run`), the summary |
| `policy.py` | the decision order: `tick()` runs the steps in `STEPS`, the first one that acts ends the tick |
| `options.py` | every option and its default; unknown names raise |
| `game.py` | keys, prompts, `--More--`, the message log (`on_message`), status line, inventory text |
| `mapmem.py` | per-level map memory, terrain / passability grids, shop marking |
| `nav.py` | Dijkstra, single steps, door kicks, walking toward a square |
| `perception.py` | hostile / peaceful monsters, threat gates, line targets |
| `survival.py` | prayer, eating, weight, healing potions, #enhance, the vault guard |
| `combat.py` | melee, throwing, unblocking, hunting a shooter, attack wands |
| `elbereth.py` | engraving and standing on Elbereth (`elb_rules.py`: who respects it) |
| `thieves.py`, `weapons.py` | nymphs and monkeys; wielding the best weapon |
| `explore.py` | exploration, descending, searching, the Gnomish Mines |
| `excalibur.py`, `equipment.py`, `carry.py`, `shop.py`, `scrolls.py`, `pricemem.py`, `focus.py` | Excalibur, armor, valuables and selling, shops, good scrolls, price identification, target choice |
| `consts.py`, `monsters.py`, `glyphs.py`, `monattacks.py`, `weapondice.py` | shared tables |

Top level:

- `eval.py` runs N games in parallel and writes jsonl; `compare.py` does paired bootstrap comparisons
  (80% CI on the mean difference).
- `regress.py` checks that a refactor does not change behaviour: 32 fixed seeds under the CI clock,
  per game the outcome and a hash of every key sent, against `golden.json`
  (`python regress.py check`; `--level outcome` for changes that only drop free actions).
- `tools/`: `cases.py` (death analysis from `hist`), `random_baseline.py`.
- `python -m nhbot SEED` plays one game and prints its summary.

Parallel evaluation runs on GitHub Actions: workflow **eval** (`workflow_dispatch`), sharded by character and
seed range; options go in `kw` as JSON (`{"pray_gap": 700}` or `{"role_opts": {...}}`).
