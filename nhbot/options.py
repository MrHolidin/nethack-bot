"""Every tunable option of the bot, with its default.

Bot(role_opts={...}) and extra Bot keyword arguments override these (eval.py --kw accepts both forms);
an unknown name raises, so a typo cannot silently run the default configuration.
"""

DEFAULTS = {
    # ---- feature switches (all on: accepted into the base)
    "use_armor": True,         # pick up and wear armor
    "use_food": True,          # pick up safe food
    "use_enhance": True,       # #enhance skills when the game offers it
    "use_pet": True,           # wait on the stairs for a nearby pet before descending
    "use_abilities": True,     # healing potions, magic mapping
    "use_roles": True,         # attack wands, Excalibur
    "wands": True,             # zap identified attack wands at worthy targets
    "excal": True,             # dip a long sword for Excalibur (lawful, XL >= excal_xl)
    "excal_travel": True,      # walk back up to a remembered fountain
    "focus": True,             # several adjacent hostiles: Smith's rule target choice
    "nymph": True,             # thieves: shoot / melee first, recover the loot
    "nymph_align": True,       # step into line with a thief we can shoot at
    "nymph_elb": True,         # nothing to shoot: Elbereth against a close thief
    "elb2": True,              # Elbereth, verified by reading it back
    "blind_strike": True,      # blind in Minetown: hit an 'I' only if it attacked us
    "hallu_strike": True,      # hallucinating in Minetown: hit only what attacked us
    "hunt_shooter": True,      # shot at from range: close in on the shooter
    "pickup_calm": True,       # collect items when not in combat (not only with nothing in view)
    "items_first": True,       # don't descend while reachable item goals remain
    "read_good": True,         # read (and keep) scrolls that prices pin to good types
    "unblock": True,           # throw things at a never-melee monster that blocks the only way
    "vault_guard": True,       # vault guard protocol
    "mines_return": True,      # leave the Mines after Minetown / at the bottom
    "carry": True,             # pick up valuables, never Burdened, sell in shops
    "weapons": True,           # weapons join the carry pipeline; wield the best one
    # ---- off by default
    "carry_all": False,        # also tools, unworn armor, spellbooks, gems, diggers (kept: owner's decision)
    "avoid_mines": False,      # True / False / "until_excalibur"
    "goal_gate_own": False,    # A/B: missiles and corpses are walked to / consumed only under items_gate
    "goal_gate_gold": False,   # A/B: gold too (walk mask and gold_here)
    "shop_by_square": False,   # A/B: merchandise = items on shop squares only (not 'a shopkeeper is in view');
                               #      missile and corpse goals on shop squares are skipped
    "loot_holds_descent": False,   # A/B: a reachable stolen-items square on this level holds the stairs down
    # ---- parameters
    "rest_frac": 0.5,          # rest (search 20) below this HP fraction with nothing in view
    "pray_div": 7,             # pray for HP when hp * pray_div <= maxhp
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
