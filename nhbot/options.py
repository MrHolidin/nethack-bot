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
    "pace": None,              # A/B: the strength gate on the stairs down (nhbot.pace): a list of [depth, XL] -- no
                               #      descent to that depth or deeper below that experience level; we wait on the
                               #      staircase instead (counted searches), e.g. [[5, 6], [8, 8], [11, 10]]
    "pace_wait": 3000,         # with pace: turns at most on one level since its gate first closed (then it opens)
    "pace_food": 0,            # with pace: the gate is open while our estimated nutrition is below this (0: only when
                               #      Weak) -- 200 leaves before Hungry, the food we carry uneaten
    "pace_patrol": 0,          # with pace: gated, a walk to a far square of the level and back every this many turns
                               #      (0: never) -- it brings out the monsters that stand behind walls
    "pace_dive": 0,           # A/B: the final dive -- with this many keys of the budget (Bot.max_steps) left,
                               #      down the first stairs found, nothing optional (0: never)
    "gift": None,              # experiments: item names (wish syntax) put into the inventory at the start, identified
                               #      (nhbot.gift)
    # ---- HP thresholds (fractions of max HP; Bot.hp_below)
    "rest_frac": 0.5,          # rest (search 20) below this with nothing in view; rest on our Elbereth below it too
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
