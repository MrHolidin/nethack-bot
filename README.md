# nethack-bot

Scripted NetHack 3.6.6 bot on the NetHack Learning Environment (NLE). Objective: in-game score
(also tracks max dungeon depth).

- `bot.py` main loop: exploration, combat, prayer, food, descending
- `equipment.py`, `tactics.py` (staircase escapes), `abilities.py` (#enhance, pet, spells, potions),
  `roles.py` (class tactics, Excalibur), `shop.py` (off by default)
- `eval.py` runs N games in parallel and writes jsonl; `compare.py` does paired bootstrap comparisons

Parallel evaluation runs on GitHub Actions: workflow **eval** (`workflow_dispatch`), sharded by
character and seed range.
