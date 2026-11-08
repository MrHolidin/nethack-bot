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
    "desperate_time": False,   # A/B: step_progress's stall (500: obstacles forgotten, 1500: desperate) and its 2500-turn
                               #      rule count turns spent ON the level (Level.turns_here), not since the first
                               #      arrival -- a level re-entered went desperate at once (nhbot.policy)
    "safe_pickup": False,      # A/B: ',' only after a ':' look (no game time): a lone item (taken without a menu,
                               #      pickup.c AUTOSELECT_SINGLE) only if want accepts it; never a cockatrice /
                               #      chickatrice corpse without gloves (nhbot.pickup)
    "mines_mask": False,       # A/B: the closed Mines staircase explore keeps away from is mines_stairs (linked
                               #      arrival marks, stairs taken, two_down), not only the avoid_down marks (nhbot.explore)
    "goal_here": False,        # A/B: explore's targets leave out our own square -- a goal there whose step declined
                               #      (an altar with a hostile in view) no longer ends exploring (nhbot.explore)
    "door_stale": False,       # A/B: a door in Level.locked is kicked only while the map shows it closed (else
                               #      forgotten: opened / broken since); door messages ("The door opens.", "This door
                               #      is locked.", "The door resists!") are no failed step (nhbot.nav.move)
    "heal_first": False,       # A/B: the heal step (a healing potion below 1/3 HP) before unihorn / stunned / blind:
                               #      a non-cursed healing potion cures blindness too (nhbot.policy step order)
    "engrave_more": False,     # A/B: Elbereth (and the engrave tests) also on stairs, ladders, a throne, a sink --
                               #      engrave.c doengrave refuses none of them (nhbot.elbereth)
    "dmg_model": False,        # A/B: danger's melee model corrected (mhitu.c / attrib.c / uhitm.c): rust / corrode /
                               #      disenchant / slime / gold-stealing hits do damage, negative AC takes rnd(-AC)
                               #      off each hit, poison's extra damage 24 in 240, a gelatinous cube's passive
                               #      d(1, 4) on misses too, cold zeroed only when we resist it (nhbot.danger)
    "history_always": False,   # A/B: perception and the fight record (danger_tick -- our hits counted for win_prob --,
                               #      summary 'hist') every tick before the steps that act, not only in ticks no
                               #      step before 'history' (pray, heal, blind, ...) acted in (nhbot.policy.tick)
    "prey_cache": False,       # A/B: prey_win's cache keyed also on the monster's square, our hits on it and whether it
                               #      is asleep (all read by win_prob), and kept for one tick only -- it grew without
                               #      limit and went stale (nhbot.combat.prey_win)
    "statue_free": False,      # A/B: a statue is floor for planning (mapmem.kinds, nav.grids), no boulder (cost 15,
                               #      never walked in Sokoban): no statue stops a step (hack.c test_move)
    "ranges": False,           # A/B: a gas spore is thrown at from 2 on (its explosion covers 3x3, explode.c); a
                               #      shooter hunted within 7 (m_lined_up: distmin < BOLT_LIM); our to-hit / damage
                               #      count our weapon skill (#enhance read, weapon.c), +4 on one our sleep ray put
                               #      down, +2 on one that turned to flee (uhitm.c) (nhbot.combat, danger, threats)
    "stairs_refused": False,   # A/B: "You can't go up / down here" noted (Level.not_stairs) by msg_map whatever pressed
                               #      the key, and every walk to stairs (explore's way down, mines_return, excal_go_up,
                               #      level travel) leaves those squares out (mapmem.stairs_mask)
    "merch_one": False,        # A/B: one merchandise rule (pickup.merch_risk) for an item's walk mask and the step
                               #      that takes it: gold not walked to where step_gold_here won't pick it up (a
                               #      shopkeeper in view, no shop marked); a corpse judged where it lies, not where we
                               #      stand (nhbot.goals.goal_masks, policy.step_eat_corpse)
    "nymph_elb": False,        # A/B: on a confirmed Elbereth (read back) a nymph / monkey next to us is not hit (the
                               #      blow erases it, setmangry) -- we wait, nymph_wait_max turns at most; the
                               #      nymph's Elbereth is written by elbereth.elb_write (retries a misspelling)
                               #      (nhbot.thieves.nymph_step)
    "attacked_us": False,      # A/B: one table / parser of the attacks on us (messages.attacks_on_us) for every reader
                               #      -- the threat tracker (no longer "The jackal bites the little dog."), the
                               #      peaceful-attacker marks, blind_strike / hallu_strike ("thrusts" / "swings" lines)
    "melee_policy": False,     # A/B: one (fight, avoid, shoot) answer per monster (perception.melee_policy) for
                               #      avoid_cells, adjacent_hostiles, ranged_target and unblock_step: on a desperate
                               #      level a never-melee monster is walked round below 90% HP too (no walking into
                               #      a jelly we won't hit); missiles at every avoided non-peaceful one alike
    "slots": False,            # A/B: the 52 inventory letters count: a floor stack that won't merge takes the last
                               #      free letter only if worth more than the stack we'd give up (value.slot_ok),
                               #      and with all 52 taken the drop step drops that one (carry.carry_drop_step)
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
    "gift": None,              # experiments: item names (wish syntax) put into the inventory at the start, identified
                               #      (nhbot.gift)
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
