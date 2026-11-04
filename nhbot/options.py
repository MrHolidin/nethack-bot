"""Every tunable option of the bot, with its default.

Bot(role_opts={...}) and extra Bot keyword arguments override these (eval.py --kw accepts both forms);
an unknown name raises, so a typo cannot silently run the default configuration.
"""

DEFAULTS = {
    # ---- off by default (accepted features are plain behaviour, not options)
    "avoid_mines": False,      # True / False / "until_excalibur"
    "force_read": None,        # experiments: a scroll type ("destroy armor", control "blank paper") read once, the first
                               #      time it is safe (nhbot.scrolls.force_read_step)
    "gift": None,              # experiments: item names (wish syntax) put into the inventory at the start, identified
                               #      (nhbot.gift)
    "shop_browse": False,      # A/B: every shop visited (not only to sell): step on every item for sale to read
                               #      its price tag (nhbot.pricemem)
    "quaff_test": False,       # A/B: drink an unknown potion of the 100 zm group on Elbereth when calm (nhbot.potiontest)
    "revisit_up": False,       # A/B: before going down, climb back to the level above if we fell past it or left
                               #      it with a reachable frontier (hole, trap door, teleport)
    "elb_full_rest": False,    # A/B: leave Elbereth with nobody in view only at elb_exit HP too (else 60%)
    "flee": False,             # A/B: P(death this turn) > 50%: get away (Elbereth first if not faster), then rest on
                               #      Elbereth; "stairs": away to the up staircase, climb, rest next to it above
    "nymph_wands": False,      # A/B: attack wands at thieves in line (sleep first); a ray only when P(it comes back
                               #      and hits us) < 10% (nhbot.rays)
    "elb_pwin": False,         # A/B: write Elbereth when P(we win the fight with the adjacent ones) < 50% (danger.py
                               #      win_prob) instead of HP < elb_hp
    "elb_shot_seen": False,    # A/B: a weapon user blocks Elbereth only within ELB_SHOT_TURNS of a missile or zap
                               #      message (combat.RTHREAT_RE), else it doesn't
    "track_sleep": False,      # A/B: monsters our sleep ray hit count as asleep for SLEPT_TURNS: not zapped with sleep
                               #      again, attacked after the awake ones, left out of win_prob (combat.asleep)
    "wand_resist": False,      # A/B: no attack wand at a monster that resists it (combat.wand_resisted), not only the
                               #      sleep-resistant elves and zombies by name
    "no_zap_elbereth": False,  # A/B: no attack wand while we stand on Elbereth (the attack would erase it)
    "wand_ev": False,          # A/B (with wand_pwin): a zap only when P(we win) with it as our next action -- its chance
                               #      to hit and its damage (combat.wand_effect) -- beats fighting on; best zap first
    "wand_pwin": False,        # A/B: a number p: an attack wand when P(we win the fight) <= p, at the target whose removal
                               #      raises it most, instead of the HP / damage rule; a ray when P(it comes back and
                               #      hits us) < WAND_RAY_RISK instead of ray_safe (combat.wand_pwin_targets)
    "shk_marks_shop": False,   # A/B: standing in an unmarked room with a shopkeeper in view marks it as a shop
                               #      (mapmem.shop_from_keeper)
    "box_dagger_any": False,   # A/B: force a lock with any dagger we carry (known uncursed first),
                               #      not only the alternate weapon (nhbot.boxes.box_opener)
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
