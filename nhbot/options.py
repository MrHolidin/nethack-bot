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
    "desperate_level": False,  # A/B: step_progress's desperation (1500-turn stall, the 2500-turn rule) counts turns
                               #      spent ON the level (Level.turns_here), not since the first arrival -- a level
                               #      re-entered went desperate at once; the 500-turn obstacle reset as before
    "door_kick_stale": False,  # A/B: a door in Level.locked is kicked only while the map shows it closed (else
                               #      forgotten: opened / broken since -- "You kick at empty space.") (nhbot.nav.move)
    "door_open_ok": False,     # A/B: "The door opens." (autoopen, a turn) is no failed step into the square (nhbot.nav)
    # danger's melee model corrected, one fix a flag (dmg_model, all five at once, lost -1300 [-2630, +9]):
    "dmg_nodmg": False,        # A/B: rust / corrode / disenchant / slime / gold-stealing hits do their d(n, d)
                               #      (mhitu.c hitmu) (nhbot.danger.monster_turn_pmf)
    "dmg_ac": False,           # A/B: negative AC takes rnd(-AC) off each damaging hit (mhitu.c:1699-1703)
    "dmg_poison": False,       # A/B: a poisonous hit's extra rn1(10, 6) damage 24 in 240, not 5 (attrib.c poisoned)
    "dmg_cube": False,         # A/B: a gelatinous cube's passive paralysis d(1, 4), and on our misses too (uhitm.c
                               #      passive) (nhbot.danger monster_paralysis / the fight simulator)
    "dmg_cold": False,         # A/B: a cold hit zeroed only when we resist cold (our_resists), not always
    "posterior_one": False,    # A/B: scroll_is_good / unknown_readable read value.type_posterior (known types left out,
                               #      oc_prob prior, deductions) like every other item decision, not pricemem's uniform
                               #      price-only posterior (nhbot.scrolls)
    "ammo_one": False,         # A/B: step_ammo_here stops for what take_ammo takes (pickup.ammo_want: the flint / rocks
                               #      we throw too) (nhbot.policy)
    "pile_one": False,         # A/B: one pile mask (pickup.pile_mask) for explore's walk, the inspection where we stand and
                               #      the goal statistics -- food piles only while we carry less than MAX_FOOD (nhbot.pickup)
    "spore_range": False,      # A/B: a gas spore is thrown at from 2 on (its explosion covers 3x3, explode.c), not 3
    "shooter_range": False,    # A/B: a shooter hunted within 7 (m_lined_up: distmin < BOLT_LIM), not 8 (nhbot.combat)
    "skill_bonus": False,      # A/B: our to-hit / damage count our weapon skill (#enhance read, weapon.c) (nhbot.danger)
    "helpless_bonus": False,   # A/B: our to-hit +4 on one our sleep ray put down, +2 on one that turned to flee
                               #      (uhitm.c:276-291; threats.fleeing) (nhbot.danger)
    "melee_policy": False,     # A/B: one (fight, avoid) answer per monster (perception.melee_policy) for avoid_cells,
                               #      adjacent_hostiles and unblock_step: on a desperate level a never-melee monster is
                               #      walked round below 90% HP too (no walking into a jelly we won't hit). (With the
                               #      shooting below in it: -2813 [-4546, -1050], 877 games changed -- split.)
    "shoot_avoided": False,    # A/B: missiles (ranged_target, unblock_step) at every avoided monster that is not
                               #      peaceful (shoot_cells), not only RANGED_TARGETS -- and never at the Oracle
    "spore_elb": False,        # A/B: a gas spore next to us blocking the only way (unblock_step), too close to throw at:
                               #      Elbereth written and waited on until it drifts off (combat.spore_back_off)
    "drink_prompt": False,     # A/B: 'q' on a fountain / sink answers "Drink from the fountain?" 'n' and goes on to the
                               #      potion question -- the heal / quaff_test steps typed the potion letter into it
                               #      (game.ask_drink)
    "fight_model": False,      # A/B: focus fire (several hostiles next to us) scored with danger's fight model --
                               #      adjusted monster level (makemon.c adj_lev), the weapon in hand whatever its
                               #      class, erosion, encumbrance, our speed, the hits danger_tick counted -- not
                               #      focus.py's own estimates (nhbot.focus.focus_score_model)
    "walk_fight_all": False,   # A/B: every win_prob fight played by the full walk_fight model (approach {}): prey_win
                               #      and the water demon check too, not the simple loop that left out paralysis,
                               #      regeneration, sleep, stun, stoning, brain-eating (nhbot.danger.win_prob)
    "dragon_mc": False,        # A/B: the MC of a worn piece from objects.c a_can (equipment.MC_CAN): dragon scales and
                               #      dragon scale mail 0, not the 1 every suit got (nhbot.equipment.wear_gain)
    "excal_sword": False,      # A/B: any one long sword of ours is dipped for Excalibur -- cursed or named too (fountain.c
                               #      dipfountain asks neither, and blesses it); not an artifact (nhbot.excalibur.long_sword)
    "level_time": False,       # A/B: explore's descend_after and the mines_after hatch count turns spent ON the level
                               #      (Level.turns_here), not since the first arrival (nhbot.explore.explore)
    "elb_respect": False,      # A/B: one rule who ignores a written Elbereth (elb_rules.onscary_ignores, monmove.c
                               #      onscary: @, minotaurs, lawful minions / Angels, the Riders) for both elb_blocked
                               #      and elbereth.respects -- respects let the Riders count as scared
    "food_facts": False,       # A/B: a prayer that fixes hunger sets nutrition to 900 ("Your stomach feels content.",
                               #      pray.c / eat.c init_uhunger; the golden glow too), a slime mold is 250; no
                               #      mimic corpse (helpless), violet fungus / yellow mold (hallucination), quantum
                               #      mechanic while Fast (speed lost) -- tins too (nhbot.survival)
    "shop_facts": False,       # A/B: what a shop buys from shknam.c saleable (quality apparel: wands, leather gloves,
                               #      elven cloaks only; lighting: candles, lamps, potions of oil; the health food
                               #      store; the delicatessen's drinks), nothing offered it pays 0 for (uncursed water,
                               #      a cancelled wand); the cheapest identify scroll by our Charisma (shk.c get_cost)
                               #      (nhbot.shop.shop_buys, jewelry.identify_min_price)
    "excal_travel": False,     # A/B: Excalibur's walk back up by level_travel_step toward the nearest level with a
                               #      fountain we may use -- no up staircase known to lead elsewhere (Sokoban's), only the
                               #      one known to lead there while one is; one fountain mask (excalibur.fountains) for
                               #      the dip, the climb and the target (nhbot.excalibur.excal_go_up)
    "blocked_split": False,    # A/B: squares a standing rule keeps us out of (watch-warned / closed-for-inventory /
                               #      Mines doors, lock warnings, a squeeze we can't shed for, a boulder given up) in
                               #      Level.no_entry, never forgotten; the stall reset forgets only the learned
                               #      failures (Level.blocked / fail) (nhbot.mapmem.no_entry_mark)
    "squeeze_path": False,     # A/B: carrying more than 600, a diagonal step between two rock / wall squares (refused:
                               #      hack.c test_move, cant_squeeze_thru) costs Dijkstra SQUEEZE_COST more -- walked
                               #      round when a way round exists; the only way, it is still tried and the refusal
                               #      sheds (squeeze_step) or digs as before (nhbot.nav.dijkstra)
    "name_parse": False,       # A/B: item names made singular by one resolver (items.singular_name: objnam.c
                               #      makeplural inverted over the object / monster names -- "knives" was "knif",
                               #      "cloves of garlic" no food); a corpse weighs its monster's cwt, an unidentified
                               #      gem its type's weight (1, was 10) and any gem look counts as unidentified
                               #      ("yellowish brown gem" was worth 0); a stack's food counts one piece's nutrition
                               #      (carry.describe, pickup.floor_kind, value.stack_key / unid_gem, survival)
    "keep_rule": False,        # A/B: one rule what we keep (value.keep_reason / keep_plan) for est_value, selling,
                               #      throwing (expendables) and taking: worn, the alternate weapon, water, one digger
                               #      (taken now: "digger"), the best wield candidate (+ a long sword for Excalibur),
                               #      MISSILE_KEEP missile pieces (no crysknife), MAX_FOOD pieces of food we eat (no
                               #      corpses, no tins), what carry.needed keeps; no lamp to rub thrown, no water sold
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
    "pray_gap": 1000,          # turns since the last prayer before praying for HP
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
