"""The decision order: one tick = one action.

tick() updates the map memory, then runs the steps in STEPS in order; the first step that acts (returns
True) ends the tick. A step that only updates bookkeeping returns False. The order is the policy: emergencies
first, then fighting, then food and items, then exploring.
"""
import re
from dataclasses import dataclass

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.combat import THROWABLE, THROW_STONES
from nhbot.consts import FAINTING, FLOOR_GLYPH, HUNGRY, NOT_HUNGRY, WEAK, ray_squares
from nhbot.mapmem import Level
from nhbot.monsters import M2_STALK, PASSIVE_MOLDS, PM_BY_NAME

STEPS = (
    "level_arrival",     # bounce off the Mines staircase (avoid_mines); Mines-return bookkeeping
    "progress",          # no-time loop guard; forget obstacles / go desperate on a stalled level
    "engulfed",
    "pray",              # low HP, Weak / Fainting, lycanthropy, deadly conditions
    "weight",            # never Burdened (carry), shed weight when Strained
    "perceive",          # #enhance; hostiles next to us (blind / hallucinating: only proven attackers)
    "stunned",
    "vault_guard",
    "blind",
    "heal",
    "history",           # per-tick record of the fight state (summary 'hist')
    "elbereth",
    "thieves",
    "weapon",
    "wands",
    "melee",
    "hunt_shooter",
    "rest_on_elbereth",
    "throw_at_blocker",  # missiles at monsters we never melee, in a clear line
    "ammo_here",
    "retrieve_missiles",
    "eat",
    "eat_corpse",
    "digger_stash",
    "housekeeping",      # shop, Excalibur, loot, scrolls, armor, the pile we stand on
    "rest",
    "gold_here",
    "explore",
)


@dataclass
class Tick:
    """What every step of one tick sees."""
    lv: Level
    y: int
    x: int
    t: int
    hp: int
    maxhp: int
    hunger: int
    hostiles: list = None        # set by the perceive step
    vis: list = None             # set by the housekeeping step (view_threats)


class PolicyMixin:
    def policy_init(self):
        self.steps_by_name = [(n, getattr(self, "step_" + n)) for n in STEPS]
        self.last_step = None

    def tick(self):
        lv = self.update_memory()
        self.cur_key = lv.key
        self.last_step = None
        if self.step_level_arrival(lv):          # runs before the tick state is read: it may change level
            self.last_step = "level_arrival"
            return
        y, x = self.pos()
        c = Tick(lv=lv, y=y, x=x, t=self.turn(), hp=self.bl(nh.NLE_BL_HP), maxhp=self.bl(nh.NLE_BL_HPMAX),
                 hunger=self.bl(nh.NLE_BL_HUNGER))
        for name, step in self.steps_by_name[1:]:
            if step(c):
                self.last_step = name
                return

    # ------------------------------------------------------------------ emergencies
    def step_level_arrival(self, lv):
        if self.pending_mines_mark:
            self.pending_mines_mark = False
            if lv.key[0] == 0:
                lv.avoid_down.add(self.pos())
        arrived_by_stairs = False
        if lv.key != self.prev_key:
            arrived_by_stairs = self.took_stairs
            self.note_stair_arrival(lv, True)
            self.prev_key = lv.key
        else:
            self.last_stair_dir = None
        self.took_stairs = False
        if self.mines_blocked() and lv.key[0] == 2 and lv.key not in self.mines_bounced \
                and arrived_by_stairs:
            self.mines_bounced.add(lv.key)
            self.pending_mines_mark = True
            self.press("<")
            return True
        if self.opts.mines_return:
            if lv.key[0] == 2:
                if self.is_minetown(lv) or self.town_folk_visible():
                    self.minetown_seen = True
                if not self.minetown_seen and lv.key[1] >= 5:
                    self.mines_return_start(lv, "no_town")    # Minetown is Mines level 3 or 4: we passed it
            elif self.mines_return_on:
                self.mines_return_on = False
                self.mines_done = True
                self.mines_done_turn = self.turn()
        return False

    def step_progress(self, c):
        lv, t = c.lv, c.t
        if (G.KIND[self.obs["glyphs"]] == G.PET).any():
            self.pet_last_seen = t
        if t != self.loop_turn:
            self.loop_turn, self.loop_steps = t, self.steps
        elif self.steps - self.loop_steps > 300:      # stuck in a no-time loop
            self.loops += 1
            self.loop_steps = self.steps
            self.raw_step(27); self.press("s")
            return True
        stall = t - max(lv.last_progress, lv.entered_turn or 0)
        if stall > 500 and t - lv.last_reset > 500:
            # forget learned obstacles: they are often transient (monsters, misreads)
            lv.fail[:] = 0
            lv.blocked[:] = False
            lv.last_reset = t
            self.resets += 1
        if not lv.desperate and (stall > 1500 or (t - (lv.entered_turn or t) > 2500 and
                                                 not (G.KIND[lv.under] == G.DOWNSTAIR).any())):
            lv.desperate = True
            self.desperations += 1
        return False

    def step_engulfed(self, c):
        """Engulfed: hit anything. The engulfer is drawn on the 8 squares AROUND us (display.c swallowed())."""
        gg = self.obs["glyphs"]
        y, x = c.y, c.x
        ring = gg[max(0, y - 1):y + 2, max(0, x - 1):x + 2]
        if int(((ring >= nh.GLYPH_SWALLOW_OFF) & (ring < nh.GLYPH_WARNING_OFF)).sum()) >= 5:
            self.last_attack_target = None
            self.press("F"); self.press("h")
            return True
        return False

    def step_pray(self, c):
        hp, maxhp, hunger, t = c.hp, c.maxhp, c.hunger, c.t
        low = hp <= 5 or hp * 7 <= maxhp
        if (low or hp * self.opts.pray_div <= maxhp) and self.can_pray():
            self.pray(); return True
        if hunger >= FAINTING:
            if self.faint_since is None:
                self.faint_since = t
        else:
            self.faint_since = None
        if hunger >= WEAK and self.can_pray(hunger_emergency=(
                self.faint_since is not None and t - self.faint_since > self.opts.faint_wait), weak=True):
            self.pray(); return True
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
        if self.carry_drop_step():
            return True
        return self.bl(nh.NLE_BL_CAP) >= 2 and self.drop_heavy()

    # ------------------------------------------------------------------ monsters around
    def step_perceive(self, c):
        if self.opts.use_enhance:
            self.enhance_step()
        hostiles = self.adjacent_hostiles(c.lv)
        if self.opts.blind_strike:
            hostiles = self.blind_attackers(c.lv, hostiles)
        if self.opts.hallu_strike:
            hostiles = self.hallu_attackers(c.lv, hostiles)
        c.hostiles = hostiles
        return False

    def step_stunned(self, c):
        """Moves and attacks go in random directions while stunned / confused: wait it out."""
        if int(self.last_bl[nh.NLE_BL_CONDITION]) & (nh.BL_MASK_STUN | nh.BL_MASK_CONF):
            if not c.hostiles or all(n in PASSIVE_MOLDS for _, n in c.hostiles):
                self.stun_waits += 1
                self.press("s")
                return True
        return False

    def step_vault_guard(self, c):
        return self.opts.vault_guard and self.vault_step(c.lv, c.hostiles)

    def step_blind(self, c):
        """Wandering blind walks into things we can't see: wait."""
        if int(self.last_bl[nh.NLE_BL_CONDITION]) & nh.BL_MASK_BLIND and not c.hostiles \
                and self.bl(nh.NLE_BL_HUNGER) < HUNGRY:
            self.blind_waits += 1
            # blind_strike: rest with '.', not search: searching reveals unseen neighbours as fresh 'I's, which
            # would look like the attacker when something else hits us in the same turn (61688)
            self.press("." if self.opts.blind_strike and self.strike_scope_ok(c.lv) else "s")
            return True
        return False

    def step_heal(self, c):
        return self.opts.use_abilities and self.heal_step(c.hostiles)

    def step_history(self, c):
        lv, y, x, hostiles = c.lv, c.y, c.x, c.hostiles
        vis_n = len(self.visible_hostiles(lv))
        km = G.KIND[lv.under]
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
        return not self.hallu_blind_ranged() and self.nymph_step(c.lv, c.hostiles)

    def step_weapon(self, c):
        return not c.hostiles and self.weapon_check()

    def step_wands(self, c):
        return self.opts.use_roles and not self.hallu_blind_ranged() and self.wand_step(c.lv, c.hostiles)

    def step_melee(self, c):
        """Attack the weakest-looking (lowest level) adjacent hostile; focus: Smith's rule among several."""
        if not c.hostiles:
            return False
        target = min(c.hostiles, key=lambda t: self.mon_level(t[0]))[0]
        if self.opts.focus and len(c.hostiles) > 1:
            target = self.focus_target(c.hostiles, target)
        self.attack(target)
        return True

    def step_hunt_shooter(self, c):
        return self.opts.hunt_shooter and not self.hallu_blind_ranged() and self.hunt_step(c.lv)

    def step_rest_on_elbereth(self, c):
        if (c.y, c.x) in c.lv.elbereth and c.hp * 2 < c.maxhp:
            self.cur_act = "rest"
            self.press("2"); self.press("0"); self.press("s")
            return True
        return False

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
        if sh and sh[0] == self.turn() and sh[1] == (y, x) and self.throws \
                and re.search(r"\b(darts?|daggers?|knives|knife|shuriken|spears?|javelins?|arrows?|crossbow bolts?)\b", sh[2]) \
                and "for sale" not in sh[2] and not c.lv.shop[y, x]:
            self.seen_here = None
            self.pickup_matching(THROWABLE + ("arrow", "crossbow bolt"))
            self.ammo_pickups += 1
            return True
        return False

    def step_retrieve_missiles(self, c):
        """Pick thrown weapons back up."""
        if self.retrieve:
            goal = self.retrieve_goal(c.lv)
            if goal is not None:
                if goal == (c.y, c.x):
                    self.pickup_matching(THROWABLE + THROW_STONES)
                    self.retrieve = [r for r in self.retrieve if goal not in r[1]]
                    return True
                if self.go_toward(c.lv, goal):
                    return True
                self.retrieve = [r for r in self.retrieve if goal not in r[1]]
        return False

    def step_eat(self, c):
        return c.hunger >= HUNGRY and self.turn() >= self.no_eat_until and self.eat_from_inventory()

    def step_eat_corpse(self, c):
        """A fresh corpse of our own kill nearby (shop corpses are merchandise)."""
        lv, y, x = c.lv, c.y, c.x
        if c.hunger >= NOT_HUNGRY and self.kills and not (self.shop_visits_on() and (
                self.shopkeeper_in_view() or lv.shop[y, x])):
            goal = self.corpse_goal(lv)
            if goal is not None:
                if goal == (y, x):
                    self.eat_corpse_here()
                    self.kills = [k for k in self.kills if k[2] != goal or k[3] != lv.key]
                    return True
                if self.go_toward(lv, goal):
                    return True
        return False

    def step_digger_stash(self, c):
        """Leave a digger by the shop door / take it back -- also with monsters in view (Minetown always has
        some): the shopkeeper asked just now, fights were handled above."""
        return self.stash_step(c.lv)

    def pile_to_inspect(self, lv, y, x):
        """An armor / food / carried-class pile under us that we have not looked at, outside a shop."""
        return bool((G.ARMOR_GLYPH[lv.under[y, x]] or G.FOOD_GLYPH[lv.under[y, x]]
                     or self.carry_glyph(lv.under[y, x])) and (y, x) not in self.inspected.get(lv.key, ())
                    and not lv.shop[y, x])

    def step_housekeeping(self, c):
        """No hostile in view: pay, shop visit, Excalibur, recover stolen loot, read good scrolls, wear armor,
        inspect the pile here. Hostiles in view but not in combat (pickup_calm): loot and the pile only."""
        lv, y, x = c.lv, c.y, c.x
        c.vis = self.view_threats(lv)
        if not (self.opts.use_armor or self.opts.use_food):
            return False
        if not c.vis:
            if self.need_pay:
                self.need_pay = False
                self.pay()
                return True
            if self.opts.use_armor and self.shop_step(lv):
                return True
            if self.excal_step(lv):
                return True
            if self.loot_step(lv):
                return True
            if self.opts.read_good and self.read_good_scroll():
                return True
            if self.opts.use_armor and self.equip_step(lv):
                return True
            if self.pile_to_inspect(lv, y, x) and self.armor_pickup_here(lv):
                return True
        elif self.opts.pickup_calm and self.items_gate(lv):
            # monsters in view but none in reach and nobody shooting: still collect what lies here
            if self.loot_step(lv):
                return True
            if self.pile_to_inspect(lv, y, x) and self.armor_pickup_here(lv):
                return True
        return False

    def step_rest(self, c):
        """Rest if hurt and nothing in view."""
        if c.hp < c.maxhp * self.opts.rest_frac and not c.vis:
            self.cur_act = "rest"
            self.press("2"); self.press("0"); self.press("s")
            return True
        return False

    def step_gold_here(self, c):
        lv, y, x = c.lv, c.y, c.x
        if G.KIND[lv.under[y, x]] == G.GOLD and (y, x) not in lv.gold_tried \
                and not (self.shop_visits_on() and (lv.shop[y, x] or self.shopkeeper_in_view())):
            lv.gold_tried.add((y, x))          # a pile shows '$' on top again after we leave: try once
            self.pickup_matching(("gold piece",))
            lv.under[y, x] = FLOOR_GLYPH
            return True
        return False

    def step_explore(self, c):
        self.explore(c.lv)
        return True
