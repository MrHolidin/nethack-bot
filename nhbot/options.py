"""Every tunable option of the bot, with its default.

Bot(role_opts={...}) and extra Bot keyword arguments override these (eval.py --kw accepts both forms);
an unknown name raises, so a typo cannot silently run the default configuration.
"""

DEFAULTS = {
    # ---- off by default (accepted features are plain behaviour, not options)
    "avoid_mines": False,      # True / False / "until_excalibur"
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
    "unihorn_fight": False,    # A/B: blind or stunned, the horn is applied with something next to us too
    "quaff_test_horn": False,  # A/B: quaff_test while we carry a unicorn horn we would apply
    "smoky_quaff": False,      # A/B: drink smoky potions for their djinni (on Elbereth, calm; nhbot.potiontest)
    "fountain_wish": False,    # A/B: Excalibur in hand, dip it into fountains for a water demon's wish
    "squeeze_reach": False,    # A/B: once a diagonal squeeze was refused for our weight, squeezes on that level cost
                               #      SQUEEZE_COST in paths, and items are shed for one only when no other way exists
    "squeeze_last": False,     # A/B: once a squeeze was refused for our weight on a level, diagonal squeezes there only
                               #      while neither the way down nor any frontier is reachable without one
    "nymph_wands": False,      # A/B: attack wands at thieves in line (sleep first); a ray only when P(it comes back
                               #      and hits us) < 10% (nhbot.rays)
    "elb_with_prayer": False,  # A/B: write Elbereth below elb_hp even while a prayer is available (else not)
    "elb_pdeath": False,       # A/B: write Elbereth when P(death this turn) > 50% (danger.py) instead of HP < elb_hp
    "elb_pwin": False,         # A/B: write Elbereth when P(we win the fight with the adjacent ones) < 50% (danger.py
                               #      win_prob) instead of HP < elb_hp
    "elb_shot_seen": False,    # A/B: a weapon user blocks Elbereth only within ELB_SHOT_TURNS of a missile or zap
                               #      message (combat.RTHREAT_RE), else it doesn't
    "door_ambush": False,      # A/B: more than 2 hostiles coming at us and none next to us: wait beside an entrance
                               #      of their room, behind its wall (nhbot.ambush)
    "wear_known": False,       # A/B: put on only armor known to be uncursed or blessed (an altar, the start kit, a wish)
    "vault_dig": False,        # A/B: with a digger, into a vault by its hint, its gold, dig down (nhbot.vault)
    "wand_engrave": False,     # A/B: with no threat in view, identify unknown wands by engraving (nhbot.wandid)
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
