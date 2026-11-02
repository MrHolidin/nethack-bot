"""Every tunable option of the bot, with its default.

Bot(role_opts={...}) and extra Bot keyword arguments override these (eval.py --kw accepts both forms);
an unknown name raises, so a typo cannot silently run the default configuration.
"""

DEFAULTS = {
    # ---- off by default (accepted features are plain behaviour, not options)
    "carry_all": False,        # also tools, unworn armor, spellbooks, gems, diggers (kept: owner's decision)
    "avoid_mines": False,      # True / False / "until_excalibur"
    "goal_gate_own": False,    # A/B: missiles and corpses are walked to / consumed only under items_gate
    "shop_by_square": False,   # A/B: merchandise = items on shop squares only (not 'a shopkeeper is in view');
                               #      missile and corpse goals on shop squares are skipped
    "loot_holds_descent": False,   # A/B: a reachable stolen-items square on this level holds the stairs down
    "lift_upgrades": False,    # A/B: "trouble lifting X. Continue?" -> yes when X is an equipment upgrade (armor in
                               #      any slot, a better weapon); the weight step keeps it and drops something else
    "pray_rules": False,       # A/B: prayer timing by the game's rules: the first prayer in major trouble from turn
                               #      101 (u.ublesscnt starts at 300, major trouble needs <= 200); low HP by
                               #      critically_low_hp (hp <= 5 or hp * 5/6/7/8/9 by XL rank <= min(maxhp, 15 * XL))
    "pray_angry": False,       # A/B: "You feel that <god> is displeased." after our prayer -> god_angry (a prayer
                               #      too soon raises u.ugangr, after which every prayer fails); drops a message
                               #      the game never prints ("You feel that Mitra is angry")
    "misc_fixes": False,       # A/B: plural good scrolls ("2 scrolls of remove curse") are good; carried lichen /
                               #      lizard corpses (never rot) are eaten, after other food; tier-4 drops skip what
                               #      can't come off (welded weapon, cursed armor, worn rings / amulets, refused
                               #      before); one direction-prompt rule for throw / zap / kick
    "ray_rules": False,        # A/B: a ray wand is zapped only if the forward direction can't bounce back (not
                               #      "forward or backward"); only a closed door absorbs (zap.c zap_over_floor),
                               #      open doors / doorways and boulders pass it; range 7..13 -> a wall 7+ away is safe
    "elb_consistent": False,   # A/B: a square counts as Elbereth (lv.elbereth) only once read back as "Elbereth"
                               #      (forgotten when a read shows otherwise); rest_on_elbereth only on a square
                               #      read as Elbereth now, with no hostile in view; the nymph Elbereth with the
                               #      usual checks (engravable square, not the failed square, not stairs / levitating /
                               #      blind / stunned / confused) and read back
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
