"""Every tunable option of the bot, with its default.

Bot(role_opts={...}) and extra Bot keyword arguments override these (eval.py --kw accepts both forms);
an unknown name raises, so a typo cannot silently run the default configuration.
"""

DEFAULTS = {
    # ---- off by default (accepted features are plain behaviour, not options)
    "sacrifice": False,        # A/B: a neutral hero offers fresh corpses of its kills at a neutral altar, carried there
                               #      in time (nhbot.sacrifice: Mjollnir, the Valkyrie's first gift)
    "peace_shut": False,       # A/B: PEACE_SHUT_WAITS waits for a peaceful monster on a square of our path close it
                               #      for PEACE_SHUT_TURNS turns (nav.move, mapmem.passable_grid)
    "lep_hall": False,         # A/B: 3+ leprechauns in view and no other hostile: their room closed to us from outside
                               #      like a shop (nhbot.thieves.lep_hall_mark, mapmem.passable_grid)
    "gold_bag": True,          # gold put in a bag (one kept, not a bag of tricks) while a leprechaun is in view, taken out in shops (nhbot.goldbag; A/B goldbag_v1 +1076)
    "mc_value": True,          # armor choice counts magic cancellation (MC_VALUE AC a point the outfit gains) and magic resistance / reflection (PROP_VALUE each) (nhbot.equipment; A/B mc_v1 +289 [-191, +792])
    "no_dagger_need": False,   # A/B: daggers are not needed (carry.needed): valued at their price like any loot, sold
    "lift_heavy": False,       # A/B: a pick-up into Burdened is let through when we asked for that item (worth_taking: worth more than what the drop step sheds next)
    "bag_buy": False,          # A/B: gold_bag and no bag of ours: the cheapest bag for sale we can pay for is bought (nhbot.goldbag)
    "lep_nogold": False,       # A/B: no gold picked up (nor gone for) on the floor of a leprechaun hall until it is cleared (nhbot.thieves)
    "lep_stash": False,        # A/B: a leprechaun hall in view: our gold dropped out of its sight first (taken back once no
                               #      leprechaun is in view); next to us, the leprechaun we hit last is hit on (nhbot.thieves)
    "lep_drop": False,         # A/B: a leprechaun in view: drop our gold where we stand, fight; take it back once none
                               #      is in view (nhbot.thieves.lep_step)
    "menu_gold": False,        # A/B: item menus (pick up, ...) take gold's "$ - ..." line too: gold lying with other things is picked up
    "buy_protection": False,   # A/B: buy AC from a temple priest, 400 * XL gold a time while below 9 (nhbot.altar)
    "sokoban": False,          # A/B: up into Sokoban from the level below the Oracle (full HP), its four levels solved
                               #      by the plans of soko_data (tools/soko_solve.py), the prize taken (nhbot.sokoban)
    "soko_zoo": True,          # with sokoban: open the top level's zoo for the prize (False: the four puzzles only --
                               #      kicking its locked door wakes the whole zoo, dokick.c wake_nearby)
    "door_resists": False,     # A/B: "The door resists!" (a stuck door, not locked) is no failed step: tried again
    "zoo_not_shop": False,     # A/B: "Welcome to David's treasure zoo!" is no shop greeting (nhbot.shop.shop_welcome)
    "squeeze_plan": False,     # A/B: a diagonal squeeze refused for our weight is shut (explored round); only when
                               #      nothing else is left to walk to past it, stand at it and shed a unit per
                               #      refusal till through (explore.squeeze_open_step); "stairs": that only while
                               #      the level's up or down staircase is unknown
    "force_read": None,        # experiments: a scroll type ("destroy armor", control "blank paper") read once, the first
                               #      time it is safe (nhbot.scrolls.force_read_step)
    "gift": None,              # experiments: item names (wish syntax) put into the inventory at the start, identified
                               #      (nhbot.gift)
    "shop_browse": False,      # A/B: every shop visited (not only to sell): step on every item for sale to read
                               #      its price tag (nhbot.pricemem)
    "hallu_wait": False,       # A/B: hallucinating: hit only what attacked us (hallu_strike everywhere, not only Minetown); nothing such next to us: rest
    "keep_100": False,         # A/B: an unknown potion of the 100 zm group is never sold (needed; an offer showing it: kept)
    "quaff_test": False,       # A/B: drink an unknown potion of the 100 zm group on Elbereth when calm (nhbot.potiontest);
                               #      "explored": only on a level explored (mapmem.Level.explored)
    "eat_plural": False,       # A/B: "There are 2 jackal corpses here; eat one?" is answered as for one corpse (else no)
    "read_explored": False,    # A/B: untested scrolls are read only on a level explored (mapmem.Level.explored)
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
    "mines_xl": 5,             # the Mines are closed below this XL; from it on, with their staircase known
                               # (Level.avoid_down, from a bounce), walk to it and go in -- Excalibur first at the
                               # fountains we know (explore.mines_trip_step)
    "mines_after": 3000,       # a closed Mines staircase opens after this many turns on its level anyway
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
