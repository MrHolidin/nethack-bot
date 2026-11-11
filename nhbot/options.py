"""Every tunable option of the bot, with its default.

Bot(role_opts={...}) and extra Bot keyword arguments override these (eval.py --kw accepts both forms);
an unknown name raises, so a typo cannot silently run the default configuration.
"""

DEFAULTS = {
    # ---- off by default (accepted features are plain behaviour, not options)
    "sacrifice": False,        # A/B: a neutral hero offers fresh corpses of its kills at a neutral altar, carried there
                               #      in time (nhbot.sacrifice: Mjollnir, the Valkyrie's first gift)
    "sokoban": False,          # A/B: up into Sokoban from the level below the Oracle (full HP), its four levels solved
                               #      by the plans of soko_data (tools/soko_solve.py), the prize taken (nhbot.sokoban)
    "soko_xl": 0,              # with sokoban: up into it only from this experience level on (0: any)
    "door_resists": False,     # A/B: "The door resists!" (a stuck door, not locked) is no failed step: tried again
    "zoo_not_shop": False,     # A/B: "Welcome to David's treasure zoo!" is no shop greeting (nhbot.shop.shop_welcome)
    "dig_through": False,      # A/B: a diagonal squeeze refused for our weight -- one of its two corners dug (pick-axe,
                               #      mattock, wand of digging) and walked round; a boulder that won't move -- broken
                               #      with the pick-axe / mattock (nhbot.digthrough); not in Sokoban, Minetown (but
                               #      Orcish Town: its watch is dead), by shops
    "stair_refuse": False,     # A/B: "You can't go down here" clears a staircase remembered in the terrain layer under an
                               #      item too (not only a shown one): no '>' pressed again and again for no time
    "search_v2": False,        # A/B: search where a hidden passage is likeliest per turn spent: each room side / dead end
                               #      of the known map gets a predicted chance (hidden.hidden_prob), lowered by every
                               #      search next to it (1 - 1/7 a turn); walking there counted (hidden.search_v2_goal)
    "search_log": False,       # experiments: at the first search on a level, the hidden-passage candidates of the
                               #      known map with features and true labels -> summary "search_log" (nhbot.hidden)
    "loop_ticks": 20,          # A/B: the no-time loop guard (policy.step_progress) fires after this many ticks in one turn
                               #      too, not only after 300 keys (0: off) -- a no-time loop spent up to 300 keys a turn;
                               #      accepted 2026-11-11, keys_all4_s vs base_d1, 500 games: keys/game 20134 -> 12753,
                               #      CPU 86 -> 35 s, depth +0.410 [+0.026, +0.772], score +791 [-1880, +3455],
                               #      truncated 7 -> 0
    "peace_cache": 20,         # A/B: a look (';') telling a monster peaceful or not holds this many turns (0: the turn
                               #      only) -- for the monster on that square, or followed to a square within 2 when no
                               #      other one of its glyph is near (perception.peace_followed); looks cost 3-15 keys;
                               #      accepted with loop_ticks (keys_all4_s)
    "elb_rest_count": 20,      # A/B: resting on our Elbereth with nothing in view, search this many turns at once
                               #      ("20s"; the game stops it for a monster that ignores Elbereth) instead of one a tick
                               #      with a ':' read every 4 (0: off); accepted with loop_ticks (keys_all4_s)
    "peace_wait_max": 20,      # A/B: a peaceful monster in our way waited for this many turns in a row -- its square
                               #      shut (Level.blocked) and the path goes round (nav.move; 0: wait for ever);
                               #      accepted with loop_ticks (keys_all4_s)
    "farlook_jump": True,      # A/B: a farlook's cursor jumps to the monster with 'm' / 'M' when that takes fewer keys
                               #      (game.describe_at, monster_rank); not neutral: other squares are described on the way
                               #      (accepted with loop_ticks: keys_all4_s)
    "key_stats": False,        # experiments: keys sent per activity, the keys and the key sequences of a tick -> summary
                               #      "key_stats" (Bot.key_stats_tick); no effect on play
    "medusa_dig": False,       # A/B: on Medusa's level (water, Dlvl 21-28, no way down) a hole dug through the floor on a
                               #      square with no water around it (pick-axe, mattock, wand of digging), past her
                               #      island; the stairs back up to her level never taken (nhbot.deep)
    "medusa_dive": False,      # A/B, with medusa_dig: below Medusa's level no exploring (mazes, minotaurs) -- the next
                               #      hole at once, down to the Castle
    "dead_end_patrol": True,   # A/B: at Medusa's level with no hole to dig, and at the Castle: no searching of walls --
                               #      back up the stairs and a patrol of the level above for the rest of the game
                               #      (nhbot.deep); accepted 2026-11-11, D1, 1000 games (133 seeds replayed):
                               #      score +4776 [+3784, +5809], depth -0.002
    "patrol_rise": 0,          # with dead_end_patrol: the patrol is this many levels above the level over the dead
                               #      end (weaker random monsters: makemon.c rndmonst, (depth + XL) / 2)
    "patrol_stale": 400,       # with dead_end_patrol: a square not within 2 squares of us for this many turns is
                               #      walked to again; nothing that old in reach: a counted search
    "patrol_look": 0,          # with dead_end_patrol: on the patrol level a look (';') at a far monster only every
                               #      this many turns (0 / 1: every tick, as elsewhere)
    "patrol_hp": 0.0,          # with dead_end_patrol: below this share of max HP, nothing in view, the patrol rests
                               #      (0: only step_rest's rest_frac)
    "dip_pray": 500,           # A/B: dip into a fountain (any reason) only this many turns after the last prayer (none
                               #      yet: from turn 100) and with the god not angry -- the prayer is the rescue from
                               #      the water demon (excalibur.dip_prayer_ok); 0: off. 500 = survival.can_pray's gap;
                               #      accepted 2026-11-11 with dip_elb 1.01, fountain_both3_s vs base_d1, 500 games:
                               #      score +2526 [+59, +5055], depth +0.646 [+0.336, +0.952], fountain deaths 50 -> 31
    "dip_elb": 1.01,           # A/B: a dip let out water moccasins, or a water demon we beat with P below this
                               #      (danger.win_prob): off the fountain, Elbereth, hold it while they are in view
                               #      (excalibur.step_fountain_trouble); 0: off, 1.01: against every demon;
                               #      accepted with dip_pray (fountain_both3_s)
    "dip_mines": False,        # A/B: the Mines' fountains that no watch minds -- Mines' End's, Orcish Town's -- used too
                               #      (excalibur.fountains); a watched Minetown's never (Excalibur there angers the watch)
    "dip_hold": 200,           # with dip_elb: turns at most holding that Elbereth
    "retreat": False,          # A/B: leave a melee fight we are losing (prayer not available, HP below retreat_hp,
                               #      win_prob below retreat_win): by the stairs, Elbereth, an escape item (nhbot.retreat)
    "retreat_hp": 0.5,         # with retreat: losing only below this fraction of max HP
    "retreat_win": 0.5,        # ... and danger.win_prob of the fight next to us below this
    "retreat_pp_window": 0,    # ... for this many turns after a prayer (0: none) the thresholds below instead
    "retreat_pp_hp": 0.7,
    "retreat_pp_win": 0.8,
    "retreat_far": 30,         # path cost at most to a staircase when no chaser is faster than us
    "retreat_near": 3,         # ... when one is
    "retreat_cool": 30,        # turns after a flight a stalker followed: no stairs again
    "retreat_rest": 0.9,       # after a flight: rest on the arrival staircase up to this fraction of max HP (0: off)
    "retreat_elb": True,       # Elbereth when only class-C monsters (may carry missiles / wands) block it
    "gift": None,              # experiments: item names (wish syntax) put into the inventory at the start, identified
                               #      (nhbot.gift)
    # ---- HP thresholds (fractions of max HP; Bot.hp_below)
    "rest_frac": 0.7,          # rest (search 20) below this with nothing in view; rest on our Elbereth below it too
                               #      (accepted 2026-11-11, 0.5 -> 0.7, orc_rest70_s vs base_d1, 500 games: score +3487
                               #      [+190, +6779], depth +0.440 [-0.010, +0.878])
    "elb_hp": 0.5,             # write Elbereth below this
    "elb_exit": 0.85,          # leave Elbereth at this
    "elb_early": 0.6,          # ... or at this with nothing in view
    "heal_hp": 1 / 3,          # quaff a known healing potion below this (when no prayer is safe)
    "hunt_hp": 0.4,            # hunt a shooter only from this on
    "desperate_melee_hp": 0.9, # on a desperate level, melee a kind we never melee (not always_avoid) from this on
    "vault_dig_hp": 0.6,       # dig to a vault only from this on
    "descend_rest_hp": 0.95,   # rest on the down staircase below this before descending
    "wandid_hp": 0.6,          # engrave-test a wand only from this on
    "excal_hp": 0.7,           # Excalibur trip / dip only from this on
    # ---- parameters
    "pray_gap": 500,           # turns since the last prayer before praying for HP (A/B pray500, 1000 -> 500: +639
                               # [+75, +1200], median 7726 -> 8016, 170 of 1000 changed)
    "hunger_gap": 500,         # ... before praying when Weak
    "faint_wait": 200,         # turns Fainting before the emergency prayer
    "descend_after": 2000,     # turns on a level before descending anyway
    "mines_xl": 5,             # the Mines are closed below this XL; from it on, with their staircase known
                               # (Level.avoid_down, from a bounce), walk to it and go in -- Excalibur first at the
                               # fountains we know (explore.mines_trip_step)
    "mines_after": 3000,       # a closed Mines staircase opens after this many turns on its level anyway
    "elb_max": 400,            # turns at most on one Elbereth
    "nymph_hold": 4,           # wait for a thief within this distance
    "nymph_wait_max": 8,       # turns at most waiting for it
    "excal_xl": 5,
    "excal_cost": 200,         # max path cost to a fountain on this level
    "excal_cost_up": 150,      # max path cost to the up staircase on the way to one
    "excal_up": 4,             # levels at most to walk back up
    "excal_trips": 12,         # climbs at most
}


class Options:
    """Read-only attribute access to the effective options: opts.pray_gap."""

    def __init__(self, overrides=None):
        overrides = dict(overrides or {})
        unknown = sorted(set(overrides) - set(DEFAULTS))
        if unknown:
            raise ValueError(f"unknown option(s): {', '.join(unknown)}")
        object.__setattr__(self, "_values", {**DEFAULTS, **overrides})

    def __getattr__(self, name):
        try:
            return self._values[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name, value):
        raise AttributeError("options are read-only")

    def changed(self):
        """Options that differ from the defaults (for logs)."""
        return {k: v for k, v in self._values.items() if v != DEFAULTS[k]}
