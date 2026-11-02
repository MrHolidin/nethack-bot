"""Every tunable option of the bot, with its default.

Bot(role_opts={...}) and extra Bot keyword arguments override these (eval.py --kw accepts both forms);
an unknown name raises, so a typo cannot silently run the default configuration.
"""

DEFAULTS = {
    # ---- off by default (accepted features are plain behaviour, not options)
    "carry_all": False,        # also tools, unworn armor, spellbooks, gems, diggers (kept: owner's decision)
    "avoid_mines": False,      # True / False / "until_excalibur"
    "trap_escape": False,      # A/B: out of a bear trap by diagonal attempts (hack.c trapmove: a diagonal one always
                               #      counts, a straight one 1 in 5), into a square without a monster
    "stairs_memory": False,    # A/B: a staircase stays known under an item / corpse on it (as door_memory for doors);
                               #      mines_return lost its up staircase under a corpse and went down and up again
    "mines_return_explore": False,  # A/B: while climbing out of the Mines (mines_return) no staircase down is a way
                               #      on: a level whose up staircase is unknown is explored for it (descend_after
                               #      counted from the first visit sent us down at once, and back up: a loop)
    "terrain_memory": False,   # A/B: a terrain layer per square (the last dungeon feature seen there) that items and
                               #      corpses don't overwrite: traps, stairs, doors, water stay known under an item
                               #      (MapMixin.kinds), fountains and altars too (terrain_glyphs)
    # ---- parameters
    "rest_frac": 0.5,          # rest (search 20) below this HP fraction with nothing in view
    "pray_gap": 1000,          # turns since the last prayer before praying for HP
    "hunger_gap": 500,         # ... before praying when Weak
    "faint_wait": 200,         # turns Fainting before the emergency prayer
    "descend_after": 2000,     # turns on a level before descending anyway
    "mines_after": 3000,       # avoid_mines: the Mines staircase opens after this many turns
    "elb_hp": 0.5,             # write Elbereth below this HP fraction
    "elb_exit": 0.85,          # leave Elbereth at this HP fraction
    "elb_max": 400,            # turns at most on one Elbereth
    "nymph_hold": 4,           # wait for a thief within this distance
    "nymph_wait_max": 8,       # turns at most waiting for it
    "excal_xl": 5,
    "excal_hp": 0.7,
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
