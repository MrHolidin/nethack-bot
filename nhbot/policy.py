"""The decision order: one tick = one action.

tick() updates the map memory (and what the arrival on a level tells), the per-tick trackers and the Mines
bookkeeping (which may bounce us back up a staircase), then runs the steps in STEPS in order; the first step that
acts (returns True) ends the tick. A step that only updates bookkeeping returns False. The order is the policy:
emergencies first, then fighting, then food and items, then exploring.
"""
import re
from collections import Counter, deque
from dataclasses import dataclass, field
from functools import cached_property

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import FAINTING, FLOOR_GLYPH, HUNGRY, NOT_HUNGRY, WEAK, ray_squares
from nhbot.mapmem import Level
from nhbot.monsters import M2_STALK, PASSIVE_MOLDS, PM_BY_NAME
from nhbot.items import CURSED_RE
from nhbot.pickup import MISSILE_TYPES
from nhbot.survival import HORN_FIXES, HORN_SICK


STEPS = (
    "progress",          # no-time loop guard; forget obstacles / go desperate on a stalled level
    "engulfed",
    "unihorn_sick",      # food poisoning / illness: a unicorn horn before a prayer
    "pray",              # low HP, Weak / Fainting, lycanthropy, deadly conditions
    "weight",            # a squeeze refused for our weight: shed a unit (carry.squeeze_step); never Burdened
    "perceive",          # #enhance; hostiles next to us (blind / hallucinating: only proven attackers)
    "heal",              # a known healing potion below 1/3 HP -- before unihorn / stunned / blind, which wait while it
                         # would mend the HP and blindness too (potion.c:993-1010 healup's cureblind)
                         # (A/B heal_first: -206 [-412, 0], 2 games of 1000 changed)
    "unihorn",           # blind / confused / stunned / hallucinating, nothing next to us: the horn
    "stunned",
    "vault_guard",
    "vault_rob",         # vault_rob: the gold of a vault we stand in, then down through the floor (nhbot.vault)
    "blind",
    "history",           # per-tick record of the fight state (summary 'hist')
    "loot_here",         # loot_now: standing where our things fell -- picked up at once, fight or not
    "elbereth",
    "thieves",
    "regen",             # ring of regeneration on below full HP, off at full (nothing next to us)
    "soko_zoo",          # Sokoban's zoo open: two awake near -- back to the corridor; else on to the prize, the one
                         # in the way attacked (nhbot.sokoban) -- before the fight steps
    "weapon",
    "wands",
    "melee",
    "hunt_shooter",
    "rest_on_elbereth",
    "throw_at_blocker",  # missiles at monsters we never melee, in a clear line
    "dig_through",       # dig_through: the corner of a refused squeeze / a boulder that won't move, dug (nhbot.digthrough)
    "ammo_here",
    "retrieve_missiles",
    "eat",
    "sacrifice",         # sacrifice: a fresh corpse of a kill to an altar of our alignment, in time
    "eat_corpse",
    "hallu",             # hallu_wait: hallucinating, after fights / healing / food: wait -- no trips, no exploring
    "digger_stash",
    "housekeeping",      # shop, Excalibur, loot, scrolls, armor, the pile we stand on
    "vault_find",        # vault_find: dig to a vault our map shows (nhbot.vault)
    "rest",
    "gold_here",
    "explore",
)


def step_order(opts):
    """STEPS as the options order them. history_always: perceive and history out of the list -- tick runs them
    first, every tick."""
    order = list(STEPS)
    if opts.history_always:
        order.remove("perceive")             # history_always: both run every tick ahead of the list (tick)
        order.remove("history")
    return tuple(order)


# step_housekeeping: (name, job(bot, tick) -> True if it acted), in order -- with no hostile in view
HOUSEKEEPING = (
    ("pay", lambda b, c: b.pay_step()),
    ("tin_wait", lambda b, c: b.tin_wait_step(c.lv)),
    ("shop", lambda b, c: b.shop_step(c.lv)),
    ("fountain_plan", lambda b, c: b.fountain_plan_step(c.lv)),
    ("loot", lambda b, c: b.loot_step(c.lv)),
    ("wishwand", lambda b, c: not b.soko_wands_shut(c.lv) and b.wishwand_step()),   # no wand in Sokoban before its
                                                                                    # level is solved
    ("lamp", lambda b, c: not b.soko_stealth(c.lv) and b.lamp_step()),              # no lamp's djinni by a sleeping zoo
    ("read_scroll", lambda b, c: b.read_scroll_step(c.lv)),
    ("jewelry_id", lambda b, c: b.jewelry_id_step(c.lv)),
    ("wandid", lambda b, c: b.wandid_step(c.lv)),
    ("quaff_test", lambda b, c: b.quaff_test_step(c.lv)),
    ("tin", lambda b, c: b.tin_step(c.lv)),
    ("equip", lambda b, c: b.equip_step(c.lv)),
    ("jewelry_wear", lambda b, c: b.jewelry_wear_step(c.lv)),
    ("altar", lambda b, c: b.altar_step(c.lv)),
    ("protection", lambda b, c: b.protection_step(c.lv)),
    ("box", lambda b, c: b.box_step(c.lv)),
    ("pile", lambda b, c: b.pile_to_inspect(c.lv, c.y, c.x) and b.armor_pickup_here(c.lv)),
)
HOUSEKEEPING_CALM = ("loot", "pile")    # hostiles in view, but none in reach and nobody shooting (items_gate)


@dataclass
class Tick:
    """What every step of one tick sees."""
    bot: object = field(repr=False)
    lv: Level
    y: int
    x: int
    t: int
    hp: int
    maxhp: int
    hunger: int
    hostiles: list = None        # set by the perceive step

    @cached_property
    def vis(self):
        """The hostiles in view (visible_hostiles), read once a tick: by the first step that asks (housekeeping)."""
        return self.bot.visible_hostiles(self.lv)


class PolicyMixin:
    def policy_init(self):
        self.steps_by_name = [(n, getattr(self, "step_" + n)) for n in step_order(self.opts)]
        self.last_step = None
        self.tick_no = 0
        self.tick_seq = 0                # msg_seq at the start of this tick
        self.hist = deque()              # step_history: the fight state of the last 40 ticks (summary 'hist')
        self.loop_turn, self.loop_steps, self.loops = -1, 0, 0     # step_progress: the no-time loop guard
        self.loop_by = Counter()         # the guard fired: "last step/activity" then (summary 'loop_by')
        self.resets = 0
        self.desperations = 0
        self.pet_last_seen = 0
        self.faint_since = None          # step_pray: the turn Fainting began
        self.deadly_prayers = 0
        self.stun_waits = 0
        self.stun_peace_waits = 0
        self.blind_waits = 0
        self.hallu_waits = 0             # hallu_wait: turns rested hallucinating
        self.ammo_pickups = 0

    def tick(self):
        lv = self.update_memory()
        self.cur_key = lv.key
        self.last_step = None
        self.chasing = None
        self.tick_no += 1
        self.nutrition_tick()                    # survival.py: hunger
        self.tick_seq = self.msg_seq
        self.threat_track()                      # threats.py: who is coming for us
        self.gold_flow_tick()                    # thieves.py: stats of the gold we got and lost
        self.poly_track()                        # thieves.py: what fell from us when we changed form
        if self.opts.sokoban:
            self.soko_track(lv)                  # sokoban.py: what we carried on coming onto this square
        if self.mines_tick(lv):                  # explore.py; before the tick state is read: it may change level
            self.last_step = "level_arrival"     # its time_by label
            return
        y, x = self.pos()
        c = Tick(bot=self, lv=lv, y=y, x=x, t=self.turn(), hp=self.bl(nh.NLE_BL_HP),
                 maxhp=self.bl(nh.NLE_BL_HPMAX), hunger=self.bl(nh.NLE_BL_HUNGER))
        if self.opts.history_always:
            # history_always: perception and the fight record (danger_tick: our hits counted for win_prob, the
            # damage prediction scored; summary 'hist') every tick, ahead of the steps that act -- in STEPS the
            # record sat after pray / heal / blind / ..., and a tick one of those acted in recorded nothing
            self.step_perceive(c)
            self.step_history(c)
        for name, step in self.steps_by_name:
            if step(c):
                self.last_step = name
                return

    # ------------------------------------------------------------------ emergencies
    def step_progress(self, c):
        lv, t = c.lv, c.t
        if (G.KIND[self.obs["glyphs"]] == G.PET).any():
            self.pet_last_seen = t
        if t != self.loop_turn:
            self.loop_turn, self.loop_steps = t, self.steps
        elif self.steps - self.loop_steps > 300:      # stuck in a no-time loop
            self.loops += 1
            self.loop_by[f"{self.last_step}/{self.cur_act}"] += 1
            self.loop_steps = self.steps
            self.raw_step(27); self.press("s")
            return True
        stall = t - max(lv.last_progress, lv.entered_turn)
        if stall > 500 and t - lv.last_reset > 500:
            # forget learned obstacles: they are often transient (monsters, misreads)
            lv.fail[:] = 0
            lv.blocked[:] = False
            lv.last_reset = t
            self.resets += 1
        if self.opts.desperate_level:
            # desperate_level: desperation by the level's own clock, turns spent on it (Level.turns_here) -- counted
            # from the first arrival, a level re-entered had been "stalled" the whole time away: desperate at once.
            # The obstacle reset above keeps its old timing (desperate_time, which moved both, lost -1027)
            stall, age = lv.turns_here - lv.progress_here, lv.turns_here
        else:
            age = t - lv.entered_turn
        if not lv.desperate and (stall > 1500 or (age > 2500 and
                                                 not (self.kinds(lv) == G.DOWNSTAIR).any())):
            lv.desperate = True
            self.desperations += 1
        return False

    def step_engulfed(self, c):
        """Engulfed: hit anything. The engulfer is drawn on the 8 squares AROUND us (display.c swallowed())."""
        gg = self.obs["glyphs"]
        y, x = c.y, c.x
        ring = gg[max(0, y - 1):y + 2, max(0, x - 1):x + 2]
        if int(((ring >= nh.GLYPH_SWALLOW_OFF) & (ring < nh.GLYPH_WARNING_OFF)).sum()) >= 5:
            self.attack_engulfer()
            return True
        return False

    def step_pray(self, c):
        hp, maxhp, hunger, t = c.hp, c.maxhp, c.hunger, c.t
        if self.critically_low_hp(hp, maxhp) and self.can_pray():
            self.pray(); return True
        if hunger >= FAINTING:
            if self.faint_since is None:
                self.faint_since = t
        else:
            self.faint_since = None
        if hunger >= WEAK and self.can_pray(hunger_emergency=(
                self.faint_since is not None and t - self.faint_since > self.opts.faint_wait), weak=True):
            self.pray(); return True
        if self.polyd and self.handless() and self.can_pray():
            self.poly_stats["prayed"] += 1
            self.pray(); return True           # pray.c: a handless form is major trouble, fixed by rehumanize()
            #                                    (A/B poly_recover +1066 [+675, +1502])
        if self.lycanthropy and self.can_pray() and \
                not any(n.startswith("were") for _, n in self.visible_hostiles(c.lv)):
            self.pray(); return True           # not while a lycanthrope in view can bite us again right after
        cond = int(self.last_bl[nh.NLE_BL_CONDITION])
        deadly = nh.BL_MASK_STONE | nh.BL_MASK_SLIME | nh.BL_MASK_STRNGL | nh.BL_MASK_FOODPOIS | nh.BL_MASK_TERMILL
        if cond & deadly and not self.god_angry and self.turn() - (self.last_pray or -9999) > 2:
            # certain death otherwise: pray even if the timeout may not have expired
            self.deadly_prayers += 1
            self.pray(); return True
        return False

    def step_weight(self, c):
        return self.squeeze_step(c.lv) or self.carry_drop_step()

    # ------------------------------------------------------------------ monsters around
    def step_perceive(self, c):
        self.enhance_step()
        hostiles = self.adjacent_hostiles(c.lv)
        hostiles = self.blind_attackers(c.lv, hostiles)
        hostiles = self.hallu_attackers(c.lv, hostiles)
        c.hostiles = hostiles
        return False

    def step_unihorn_sick(self, c):
        return self.unihorn_step(HORN_SICK)

    def step_unihorn(self, c):
        return not c.hostiles and self.unihorn_step(HORN_FIXES)

    def step_stunned(self, c):
        """Moves and attacks go in random directions while stunned / confused: wait it out."""
        if int(self.last_bl[nh.NLE_BL_CONDITION]) & (nh.BL_MASK_STUN | nh.BL_MASK_CONF):
            if not c.hostiles or all(n in PASSIVE_MOLDS for _, n in c.hostiles):
                self.stun_waits += 1
                self.press("s")
                return True
            if self.is_minetown(c.lv) and self.peaceful_next(c.lv, c.hostiles):
                # a blow could go to the watch (cmd.c getdir confdir: stunned, or confused 1 in 5 -- a random
                # direction): no melee in Minetown. A/B stun_peace +164 [-345, +656]; in the 10 games it fired +141
                # a game, 4 deaths to the watch gone
                self.stun_peace_waits += 1
                self.press("s")
                return True
        return False

    def step_vault_guard(self, c):
        return self.vault_step(c.lv, c.hostiles)

    def step_vault_rob(self, c):
        return self.vault_rob_step(c.lv, c.hostiles)

    def step_blind(self, c):
        """Wandering blind walks into things we can't see: wait."""
        if int(self.last_bl[nh.NLE_BL_CONDITION]) & nh.BL_MASK_BLIND and not c.hostiles \
                and self.bl(nh.NLE_BL_HUNGER) < HUNGRY:
            self.blind_waits += 1
            # blind_strike: rest with '.', not search: searching reveals unseen neighbours as fresh 'I's, which
            # would look like the attacker when something else hits us in the same turn (61688)
            self.press("." if self.strike_scope_ok(c.lv) else "s")
            return True
        return False

    def step_hallu(self, c):
        """hallu_wait: hallucinating -- every monster looks random (a peaceful can't be told apart) and Elbereth
        won't come out right (engrave.c: each letter garbled 1 in 2): fights, healing and food go on as ever (the
        steps before), but no trips (shop, Excalibur, loot, ...), no exploring, no going to another level -- not
        Hungry, rest a turn instead."""
        if int(self.last_bl[nh.NLE_BL_CONDITION]) & nh.BL_MASK_HALLU and self.bl(nh.NLE_BL_HUNGER) < HUNGRY:
            self.hallu_waits += 1
            self.press(".")
            return True
        return False

    def step_heal(self, c):
        return self.heal_step(c.hostiles)

    def step_history(self, c):
        lv, y, x, hostiles = c.lv, c.y, c.x, c.hostiles
        self.danger_tick(c.t, c.hp, hostiles)
        vis_n = len(self.visible_hostiles(lv))
        km = self.kinds(lv)
        sy, sx = np.nonzero((km == G.UPSTAIR) | (km == G.DOWNSTAIR))
        d_st = int(min((max(abs(a - y), abs(b - x)) for a, b in zip(sy, sx)), default=99))
        st_here = self.stairs_kind_here(lv)
        adj_info = [(n, bool(PM_BY_NAME[n].mflags2 & M2_STALK) if n in PM_BY_NAME else None,
                     PM_BY_NAME[n].mmove if n in PM_BY_NAME else None) for _, n in hostiles]
        self.hist.append((c.t, c.hp, c.maxhp, len(hostiles), vis_n, self.can_pray(), self.bl(nh.NLE_BL_DEPTH),
                          self.bl(nh.NLE_BL_XP), self.bl(nh.NLE_BL_AC), d_st,
                          int(st_here) if st_here is not None else 0, adj_info))
        if len(self.hist) > 40:
            self.hist.popleft()
        return False

    def step_elbereth(self, c):
        return self.elb_step(c.lv, c.hostiles)

    def step_thieves(self, c):
        return self.gold_bag_step(c.lv, c.hostiles) or (not self.hallu_blind_ranged() and self.nymph_step(c.lv, c.hostiles))

    def step_regen(self, c):
        return not c.hostiles and self.regen_step()

    def step_loot_here(self, c):
        """On the loot square (our armor fell there when we changed form, a thief died there): one turn picks it all
        up, also with hostiles next to us or on Elbereth (a pick-up does not erase it). A/B loot_now +1481
        [+671, +2300]."""
        if self.polyd or self.loot_sq is None or self.loot_key != c.lv.key \
                or (c.y, c.x) != self.loot_sq:
            return False
        return self.pursue("loot", c.lv, [self.loot_sq], self.loot_consume)

    def step_weapon(self, c):
        if self.rub_back is not None:            # a lamp wielded to rub it: the weapon back once a threat shows
            return bool(c.hostiles or self.visible_hostiles(c.lv)) and self.rub_rewield()
        if self.tin_glib():
            return False                         # tins: slippery fingers, whatever we wield now slips too
        if self.swapped_for is not None:
            # the dagger was swapped in for a tin / a box / digging; a threat: back. No other wielding meanwhile:
            # the main weapon in hand would make the job use it (a long sword forcing a lock can break) and the
            # later swap_back put the dagger in our hands
            return bool(c.hostiles or self.visible_hostiles(c.lv)) and self.swap_back()
        if self.tin_slipped is not None:
            return False
        if c.hostiles:
            return not any(it.wielded for it in self.items()) and self.weapon_check()   # bare hands in a fight
        return self.weapon_check()

    def step_wands(self, c):
        return not self.hallu_blind_ranged() and self.wand_step(c.lv, c.hostiles)

    def step_melee(self, c):
        """Attack the adjacent hostile; among several, the one focus picks (Smith's rule)."""
        hostiles = [t for t in c.hostiles if not self.soko_no_melee(c.lv, t[0])]   # Sokoban's zoo: no exploder
        if not hostiles:
            return False
        awake = [t for t in hostiles if not self.asleep(c.lv, t[0])]
        cands = awake or hostiles                # one put to sleep comes after every awake one
        self.attack(cands[0][0] if len(cands) == 1 else self.focus_target(cands))
        return True

    def step_hunt_shooter(self, c):
        return not self.hallu_blind_ranged() and self.hunt_step(c.lv)

    def step_rest_on_elbereth(self, c):
        """Hurt, on a square read as Elbereth just now, no hostile in view: rest."""
        if (c.y, c.x) not in c.lv.elbereth or c.hp * 2 >= c.maxhp or self.visible_hostiles(c.lv) \
                or not self.elb_confirm(c.lv):
            return False
        self.elb_stats["rest_confirmed"] += 1
        self.cur_act = "rest"
        self.search_turns(20)
        return True

    def step_throw_at_blocker(self, c):
        """Ranged attacks on things we refuse to melee."""
        rt = None if self.hallu_blind_ranged() else self.ranged_target(c.lv)
        if rt:
            th = self.throwables()
            if th:
                key, d, tpos, (sy, sx) = rt
                ray = ray_squares(c.y, c.x, sy, sx)
                self.last_attack_target = tpos
                self.throw(th[0][0], key, ray)
                return True
        return False

    # ------------------------------------------------------------------ items and food
    def step_ammo_here(self, c):
        """Missiles lying where we stand (our own thrown ones)."""
        sh = self.seen_here
        y, x = c.y, c.x
        hw = self.here_window
        # the pile window lists what "Things that are here" leaves out
        txt = (sh[2] if sh else "") + (" | " + hw[2] if hw and sh and hw[:2] == sh[:2] else "")
        if sh and sh[0] == self.turn() and sh[1] == (y, x) and self.throws and not c.lv.shop[y, x] \
                and any(self.kind_of(t)[1] in MISSILE_TYPES and "for sale" not in t and not CURSED_RE.search(t)
                        for t in re.split(r" \| |You see here |\.$", txt) if t.strip()):
            self.seen_here = None
            self.take_ammo()
            self.ammo_pickups += 1
            return True
        return False

    def step_retrieve_missiles(self, c):
        """Pick thrown weapons back up."""
        if self.retrieve:
            goals = self.retrieve_goals(c.lv)
            if goals:
                return self.pursue("retrieve", c.lv, goals, lambda g: self.take_ammo())
        return False

    def step_eat(self, c):
        return c.hunger >= HUNGRY and self.turn() >= self.no_eat_until and self.eat_from_inventory()

    def step_sacrifice(self, c):
        return self.sacrifice_step(c.lv, c.hostiles)

    def step_eat_corpse(self, c):
        """A fresh corpse of our own kill nearby (shop corpses are merchandise)."""
        lv, y, x = c.lv, c.y, c.x
        # merch_one: merch_risk only where the corpse lies (corpse_goals) -- not also at our own square
        if c.hunger >= NOT_HUNGRY and self.kills and (self.opts.merch_one or not self.merch_risk(lv, (y, x))):
            goals = self.corpse_goals(lv)
            if goals:
                return self.pursue("corpse", lv, goals, lambda g: self.eat_corpse_here())
        return False

    def step_digger_stash(self, c):
        """Leave a digger by the shop door / take it back -- also with monsters in view (Minetown always has
        some): the shopkeeper asked just now, fights were handled above."""
        return self.stash_step(c.lv)

    def step_housekeeping(self, c):
        """No hostile in view: the HOUSEKEEPING jobs in order (pay, shop visit, Excalibur, stolen loot, good scrolls,
        armor, the pile here, ...). Hostiles in view but not in combat (pickup_calm, items_gate): loot and the pile
        only. The first job that acts ends the tick."""
        if not c.vis:
            jobs = HOUSEKEEPING
        elif self.items_gate(c.lv):
            jobs = [j for j in HOUSEKEEPING if j[0] in HOUSEKEEPING_CALM]
        else:
            return False
        return any(job(self, c) for _, job in jobs)

    def step_dig_through(self, c):
        return self.dig_through_step(c.lv, c.hostiles)

    def step_vault_find(self, c):
        return self.vault_find_step(c.lv, c.vis)

    def step_rest(self, c):
        """Rest if hurt and nothing in view."""
        if c.hp < c.maxhp * self.opts.rest_frac and not c.vis:
            self.cur_act = "rest"
            self.search_turns(20)
            return True
        return False

    def step_gold_here(self, c):
        lv, y, x = c.lv, c.y, c.x
        if G.KIND[lv.under[y, x]] == G.GOLD and (y, x) not in self.goal_closed_set("gold", lv.key) \
                and not self.merch_risk(lv, (y, x)) and self.items_gate(lv):
            self.goal_done("gold", lv, (y, x))
            self.pickup_matching(("gold piece",))
            lv.under[y, x] = FLOOR_GLYPH
            return True
        return False

    def step_explore(self, c):
        if self.opts.sokoban and self.in_sokoban(c.lv):
            return self.sokoban_step(c.lv)             # Sokoban: the plan, never the generic explore
        self.explore(c.lv)
        return True
