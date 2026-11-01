"""Scripted NetHack bot on top of NLE (NetHackChallenge-v0).

Objective: in-game score; also tracks max depth."""
import re
from collections import deque

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.carry import CarryMixin
from nhbot.combat import CombatMixin, THROWABLE, THROW_STONES
from nhbot.consts import COLS, FAINTING, HUNGRY, NOT_HUNGRY, ROWS, WEAK
from nhbot.elbereth import ElberethMixin
from nhbot.equipment import EquipMixin
from nhbot.excalibur import ExcaliburMixin
from nhbot.explore import ExploreMixin
from nhbot.focus import FocusMixin
from nhbot.game import GameMixin, GameOver
from nhbot.mapmem import MapMixin
from nhbot.messages import MessagesMixin
from nhbot.monsters import PASSIVE_MOLDS, PM_BY_NAME
from nhbot.nav import NavMixin
from nhbot.options import Options
from nhbot.perception import PerceptionMixin
from nhbot.pricemem import PriceMemoryMixin
from nhbot.scrolls import ScrollMixin
from nhbot.shop import ShopMixin
from nhbot.survival import SurvivalMixin
from nhbot.thieves import ThievesMixin
from nhbot.weapons import WeaponsMixin


class Bot(GameMixin, MapMixin, NavMixin, PerceptionMixin, MessagesMixin, SurvivalMixin, CombatMixin,
          ElberethMixin, ThievesMixin, WeaponsMixin, ExploreMixin, ExcaliburMixin, ShopMixin, EquipMixin,
          CarryMixin, FocusMixin, ScrollMixin, PriceMemoryMixin):
    def __init__(self, seed=None, character="@", verbose=False, max_steps=200_000, max_turns=None,
                 role_opts=None, **options):
        """role_opts and any other keyword arguments are options (options.py); unknown names raise."""
        from nle.env.tasks import NetHackScore
        self.opts = Options({**(role_opts or {}), **options})
        self.env = NetHackScore(character=character,
                                actions=nh.ACTIONS, allow_all_yn_questions=True,
                                allow_all_modes=True, max_episode_steps=1_000_000,
                                penalty_step=0.0, penalty_time=0.0,
                                observation_keys=("glyphs", "blstats", "message", "inv_strs",
                                                  "inv_letters", "inv_oclasses", "tty_chars", "misc"))
        self.seed = seed
        self.verbose = verbose
        self.max_steps = max_steps
        self.max_turns = max_turns
        self.last_bl = None
        acts = self.env.unwrapped.actions
        self.key2act = {}
        for i, a in enumerate(acts):
            self.key2act.setdefault(int(a), i)

    def tick(self):
        lv = self.update_memory()
        self.cur_key = lv.key
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
            return
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
        y, x = self.pos()
        hp, maxhp = self.bl(nh.NLE_BL_HP), self.bl(nh.NLE_BL_HPMAX)
        hunger = self.bl(nh.NLE_BL_HUNGER)

        t = self.turn()
        if (G.KIND[self.obs["glyphs"]] == G.PET).any():
            self.pet_last_seen = t
        if t != self.loop_turn:
            self.loop_turn, self.loop_steps = t, self.steps
        elif self.steps - self.loop_steps > 300:      # stuck in a no-time loop
            self.loops += 1
            self.loop_steps = self.steps
            self.raw_step(27); self.press("s")
            return
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

        # engulfed: hit anything. The engulfer is drawn on the 8 squares AROUND us (display.c swallowed());
        # our own square shows us, so the old test on it never fired (engulf_fix)
        gg = self.obs["glyphs"]
        ring = gg[max(0, y - 1):y + 2, max(0, x - 1):x + 2]
        engulfed = int(((ring >= nh.GLYPH_SWALLOW_OFF) & (ring < nh.GLYPH_WARNING_OFF)).sum()) >= 5
        if engulfed:
            self.last_attack_target = None
            self.press("F"); self.press("h")
            return

        # emergencies
        low = hp <= 5 or hp * 7 <= maxhp
        if (low or hp * self.opts.pray_div <= maxhp) and self.can_pray():
            self.pray(); return
        if hunger >= FAINTING:
            if self.faint_since is None:
                self.faint_since = t
        else:
            self.faint_since = None
        if hunger >= WEAK and self.can_pray(hunger_emergency=(
                self.faint_since is not None and t - self.faint_since > self.opts.faint_wait), weak=True):
            self.pray(); return
        if self.lycanthropy and self.can_pray() and \
                not any(n.startswith("were") for _, n in self.visible_hostiles(lv)):
            self.pray(); return                # not while a lycanthrope in view can bite us again right after
        cond = int(self.last_bl[nh.NLE_BL_CONDITION])
        deadly = nh.BL_MASK_STONE | nh.BL_MASK_SLIME | nh.BL_MASK_STRNGL | nh.BL_MASK_FOODPOIS | nh.BL_MASK_TERMILL
        if cond & deadly and not self.god_angry and self.turn() - (self.last_pray or -9999) > 2:
            # certain death otherwise: pray even if the timeout may not have expired
            self.deadly_prayers += 1
            self.pray(); return
        if self.carry_drop_step():
            return
        if self.bl(nh.NLE_BL_CAP) >= 2 and self.drop_heavy():
            return

        if self.opts.use_enhance:
            self.enhance_step()
        hostiles = self.adjacent_hostiles(lv)
        if self.opts.blind_strike:
            hostiles = self.blind_attackers(lv, hostiles)
        if self.opts.hallu_strike:
            hostiles = self.hallu_attackers(lv, hostiles)
        cond2 = int(self.last_bl[nh.NLE_BL_CONDITION])
        if cond2 & (nh.BL_MASK_STUN | nh.BL_MASK_CONF):
            # moves and attacks go in random directions while stunned/confused
            only_passive = all(n in PASSIVE_MOLDS for _, n in hostiles)
            if not hostiles or only_passive:
                self.stun_waits += 1
                self.press("s")
                return
        if self.opts.vault_guard and self.vault_step(lv, hostiles):
            return
        if cond2 & nh.BL_MASK_BLIND and not hostiles \
                and self.bl(nh.NLE_BL_HUNGER) < HUNGRY:
            self.blind_waits += 1             # wandering blind walks into things we can't see
            # blind_strike: rest with '.', not search: searching reveals unseen neighbours as fresh 'I's, which
            # would look like the attacker when something else hits us in the same turn (61688)
            self.press("." if self.opts.blind_strike and self.strike_scope_ok(lv) else "s")
            return
        if self.opts.use_abilities and self.heal_step(hostiles):
            return
        vis_n = len(self.visible_hostiles(lv))
        km = G.KIND[lv.under]
        sy, sx = np.nonzero((km == G.UPSTAIR) | (km == G.DOWNSTAIR))
        d_st = int(min((max(abs(a - y), abs(b - x)) for a, b in zip(sy, sx)), default=99))
        st_here = self.stairs_kind_here(lv)
        adj_info = [(n, bool(PM_BY_NAME[n].mflags2 & 0x01000000) if n in PM_BY_NAME else None,
                     PM_BY_NAME[n].mmove if n in PM_BY_NAME else None) for _, n in hostiles]
        self.hist.append((t, hp, maxhp, len(hostiles), vis_n, self.can_pray(), self.bl(nh.NLE_BL_DEPTH),
                          self.bl(nh.NLE_BL_XP), self.bl(nh.NLE_BL_AC), d_st,
                          int(st_here) if st_here is not None else 0, adj_info))
        if len(self.hist) > 40:
            self.hist.popleft()
        if self.elb_step(lv, hostiles):
            return
        if not self.hallu_blind_ranged() and self.nymph_step(lv, hostiles):
            return
        if not hostiles and self.weapon_check():
            return
        if self.opts.use_roles and not self.hallu_blind_ranged() and self.wand_step(lv, hostiles):
            return
        if hostiles:
            # attack the weakest-looking (lowest level) target
            target = min(hostiles, key=lambda t: self.mon_level(t[0]))[0]
            if self.opts.focus and len(hostiles) > 1:
                target = self.focus_target(hostiles, target)
            self.attack(target)
            return
        if self.opts.hunt_shooter and not self.hallu_blind_ranged() and self.hunt_step(lv):
            return
        if (y, x) in lv.elbereth and hp * 2 < maxhp:
            self.cur_act = "rest"
            self.press("2"); self.press("0"); self.press("s")
            return

        # ranged attacks on things we refuse to melee
        rt = None if self.hallu_blind_ranged() else self.ranged_target(lv)
        if rt:
            th = self.throwables()
            if th:
                key, d, tpos, (sy, sx) = rt
                ray = [(y + i * sy, x + i * sx) for i in range(1, 10)
                       if 0 <= y + i * sy < ROWS and 0 <= x + i * sx < COLS]
                self.last_attack_target = tpos
                self.throw(th[0][0], key, ray)
                return

        # missiles lying where we stand (our own thrown ones)
        sh = self.seen_here
        if sh and sh[0] == self.turn() and sh[1] == (y, x) and self.throws \
                and re.search(r"\b(darts?|daggers?|knives|knife|shuriken|spears?|javelins?|arrows?|crossbow bolts?)\b", sh[2]) \
                and "for sale" not in sh[2] and not lv.shop[y, x]:
            self.seen_here = None
            n_before = len(self.inventory())
            self.pickup_matching(THROWABLE + ("arrow", "crossbow bolt"))
            self.ammo_pickups += 1
            return

        # pick thrown weapons back up
        if self.retrieve:
            goal = self.retrieve_goal(lv)
            if goal is not None:
                if goal == (y, x):
                    self.pickup_matching(THROWABLE + THROW_STONES)
                    self.retrieve = [r for r in self.retrieve if goal not in r[1]]
                    return
                if self.go_toward(lv, goal):
                    return
                self.retrieve = [r for r in self.retrieve if goal not in r[1]]

        # hunger
        if hunger >= HUNGRY and self.turn() >= self.no_eat_until:
            if self.eat_from_inventory():
                return

        # fresh corpse nearby
        if hunger >= NOT_HUNGRY and self.kills and not (self.shop_visits_on() and (
                self.shopkeeper_in_view() or lv.shop[y, x])):     # shop corpses are merchandise
            goal = self.corpse_goal(lv)
            if goal is not None:
                if goal == (y, x):
                    self.eat_corpse_here()
                    self.kills = [k for k in self.kills if k[2] != goal or k[3] != lv.key]
                    return
                if self.go_toward(lv, goal):
                    return

        # leave a digger (pick-axe, mattock) by the shop door / take it back -- also with monsters in view
        # (Minetown always has some): the shopkeeper asked just now, fights were handled above
        if self.stash_step(lv):
            return

        vis = self.view_threats(lv)
        if (self.opts.use_armor or self.opts.use_food) and not vis:
            if self.need_pay:
                self.need_pay = False
                self.pay()
                return
            if self.opts.use_armor and self.shop_step(lv):
                return
            if self.excal_step(lv):
                return
            if self.loot_step(lv):
                return
            if self.opts.read_good and self.read_good_scroll():
                return
            if self.opts.use_armor and self.equip_step(lv):
                return
            if (G.ARMOR_GLYPH[lv.under[y, x]] or G.FOOD_GLYPH[lv.under[y, x]]
                    or self.carry_glyph(lv.under[y, x])) and (y, x) not in self.inspected.get(lv.key, ()) \
                    and not lv.shop[y, x]:
                if self.armor_pickup_here(lv):
                    return
        elif (self.opts.use_armor or self.opts.use_food) and self.opts.pickup_calm and self.items_gate(lv):
            # monsters in view but none in reach and nobody shooting: still collect what lies here
            if self.loot_step(lv):
                return
            if (G.ARMOR_GLYPH[lv.under[y, x]] or G.FOOD_GLYPH[lv.under[y, x]]
                    or self.carry_glyph(lv.under[y, x])) and (y, x) not in self.inspected.get(lv.key, ()) \
                    and not lv.shop[y, x]:
                if self.armor_pickup_here(lv):
                    return

        # rest if hurt and nothing around
        if hp < maxhp * self.opts.rest_frac and not vis:
            self.cur_act = "rest"
            self.press("2"); self.press("0"); self.press("s")
            return

        # gold under us
        if G.KIND[lv.under[y, x]] == G.GOLD and (y, x) not in lv.gold_tried \
                and not (self.shop_visits_on() and (lv.shop[y, x] or self.shopkeeper_in_view())):
            lv.gold_tried.add((y, x))          # a pile shows '$' on top again after we leave: try once
            self.pickup_matching(("gold piece",))
            lv.under[y, x] = G.STONE_GLYPH + 19
            return

        self.explore(lv)

    def run(self):
        if self.seed is not None:
            self.env.unwrapped.seed( core=self.seed, disp=self.seed, reseed=False)
        obs, _ = self.env.reset()
        self.obs = obs
        self.last_bl = obs["blstats"].copy()
        self.hostile_cache = {}
        self._cur_pos = self.prev_pos = None
        self.it_attacked = self.melee_on_us = False      # blind_strike / hallu_strike evidence this turn
        self.prev_inv, self.inv_attackers, self.hallu_targets = set(), set(), set()
        self.blind_held = self.hallu_held = 0
        self.last_shot_turn = -99
        self.hunt_offline_steps = 0
        self.lyc_kind = None
        self.steps = 0
        self.reward = 0.0
        self.done = False
        self.truncated = False
        self.levels = {}
        self.messages = deque()
        self.msg_seq = 0          # total messages logged so far (the deque keeps only the last 60)
        self.focus_init()
        self.all_msgs = []
        self._last_logged, self._last_logged_step = None, -1
        self.cur_key = None
        self.last_move_target = None
        self.last_attack_target = None
        self.last_pray = None
        self.prayers = 0
        self.pray_failed = 0
        self.peaceful_seen = 0
        self.throws = 0
        self.lycanthropy = False
        self.deadly_prayers = 0
        self.stun_waits = 0
        self.poison_res = False
        self.blind_waits = 0
        self.shop_kicks_avoided = 0
        self.seen_here = None
        self.ammo_pickups = 0
        self.time_by = {}
        self.cur_act = "other"
        self.skill_msgs = 0
        self.kill_count = 0
        self.pet_last_seen = 0
        self.faint_since = None
        self.hist = deque()
        self.no_eat_until = 0
        self.undroppable = set()
        self.shops_seen = 0
        self.loop_turn, self.loop_steps, self.loops = -1, 0, 0
        self.desperations = 0
        self.vault_drop = False
        self.vault_follow_until = -1
        self.guard_trail = []
        self.vault_moves = 0
        self.vault_drops = 0
        self.unblocks = self.unblock_throws = self.unblock_melee = 0
        self.items_first_holds = 0
        self.hunt = None
        self.shot_event = None
        self.hunts = self.hunt_steps = 0
        self.ward_since = None
        self.ward_writes = self.ward_waits = 0
        self.resets = 0
        self.god_angry = False
        self.pending_mines_mark = False
        self.mines_bounced = set()
        self.mines_return_on = False
        self.mines_done = False
        self.mines_done_turn = 0
        self.minetown_seen = False
        self.mines_return_log = []
        self.prev_key = None
        self.took_stairs = False
        self.retrieve = []
        self.elbereths = 0
        self.descents = 0
        self.corpses_eaten = 0
        self.kills = []
        self.avoid_cells = []
        self.max_depth = 1
        self.death_msgs = []
        self.intro = self.message()
        self.equip_init()
        self.last_stair_dir = None
        self.perception_init()
        self.survival_init()
        self.explore_init()
        self.class_init()
        self.excal_init()
        self.valk_init()
        self.elb2_init()
        self.shop_init()
        self.scroll_init()
        self.carry_init()
        self.price_init()
        self.shops_done = set()
        self.need_pay = False
        self.role = self.race = None
        try:
            self.settle()
            # turn autopickup off (shops); gold picked up manually
            self.press("@")
            self.raw_step(24)   # ^X attributes
            m = re.search(r"level \d+ (.*?)\.", self.tty_text())
            if m:
                words = m.group(1).split()
                self.role, self.race = words[-1], words[-2]
            self.raw_step(27)
            self.settle()
            self.start_ac = self.bl(nh.NLE_BL_AC)
            while True:
                t0 = self.turn()
                self.cur_act = "other"
                self.tick()
                dt = self.turn() - t0
                if dt > 0:
                    self.time_by[self.cur_act] = self.time_by.get(self.cur_act, 0) + dt
                    lvc = self.levels.get(self.cur_key)
                    if lvc is not None:
                        lvc.turns_here += dt
                        if self.cur_act == "search":
                            lvc.search_turns += dt
        except GameOver:
            pass
        return self.summary()

    def summary(self):
        last = [m for _, m in list(self.messages)[-10:]]
        return {
            "seed": self.seed,
            "score": self.reward,
            "max_depth": self.max_depth,
            "turns": self.turn(),
            "steps": self.steps,
            "xl": self.bl(nh.NLE_BL_XP),
            "prayers": self.prayers,
            "elbereths": self.elbereths,
            "corpses": self.corpses_eaten,
            "throws": self.throws,
            "loops": self.loops,
            "start_ac": self.start_ac,
            "exp": self.bl(nh.NLE_BL_EXP),
            "gold": self.bl(nh.NLE_BL_GOLD),
            "maxhp": self.bl(nh.NLE_BL_HPMAX),
            "kills": self.kill_count,
            "skill_msgs": self.skill_msgs,
            "enhances": self.enhances,
            "quaffs": self.quaffs,
            "maps_read": self.maps_read,
            "pet_waited": self.pet_waited_total,
            "zaps": self.zaps,
            "thefts": self.thefts,
            "elb_engraves": self.elb_engraves,
            "elb_misspelled": self.elb_misspelled,
            "elb_fail": self.elb_fail,
            "focus_calls": self.focus_calls, "focus_picks": self.focus_picks,
            "scrolls": dict(self.scroll_stats), "price_memory": dict(self.price_stats, appearances=self.price_report()),

            "blind_waits": self.blind_waits, "poison_res": self.poison_res, "shop_kicks_avoided": self.shop_kicks_avoided,

            "elb_fail_msgs": self.elb_fail_msgs[:5],
            "elb_rewrites": self.elb_rewrites,
            "elb_blocked": dict(self.elb_block_reasons),
            "carry": dict(self.carry_stats),
            "stash": dict(self.stash_stats),
            "elb_only_c": self.elb_only_c,
            "elb_turns": self.elb_turns,
            "elb_exits": dict(self.elb_exits),
            "deadly_prayers": self.deadly_prayers,
            "pray_failed": self.pray_failed,
            "stun_waits": self.stun_waits,
            "nymph_kills": self.nymph_kills,
            "loot_pickups": self.loot_pickups,
            "rewields": self.rewields,
            "excalibur": self.excal_turn,
            "dips": self.dips,
            "excal_trips": self.excal_trips,
            "dip_events": self.dip_events,
            "fountain_levels": len(self.fountain_levels),
            "align": int(self.last_bl[nh.NLE_BL_ALIGN]),
            "ammo_pickups": self.ammo_pickups,
            "pet_last_seen": self.pet_last_seen,
            "time_by": self.time_by,
            "levels_seen": len(self.levels),
            "level_stats": [dict(key=list(k), turns=v.turns_here, search=v.search_turns,
                                 down_known=bool((G.KIND[v.under] == G.DOWNSTAIR).any()),
                                 mines_branch=bool(v.avoid_down), desperate=v.desperate,
                                 seen=int(v.seen.sum()))
                            for k, v in self.levels.items()],
            "food_picked": self.food_picked,
            "hist": list(self.hist),
            "last_pray": self.last_pray,
            "ac": self.bl(nh.NLE_BL_AC),
            "worn": [e[2] for e in self.equip_events if e[1] == "wear"],
            "equip_fail": sum(1 for e in self.equip_events if e[1] == "fail"),
            "shops": self.shops_seen,
            "desperate": self.desperations,
            "unblock": [self.unblocks, self.unblock_throws, self.unblock_melee],
            "vault": [self.vault_drops, self.vault_moves],
            "items_first": self.items_first_holds,
            "hunt": [self.hunts, self.hunt_steps, self.hunt_offline_steps],
            "ward": [self.ward_writes, self.ward_waits],
            "blind_held": self.blind_held,
            "mines_return": self.mines_return_log,
            "minetown_seen": self.minetown_seen,
            "hallu_held": self.hallu_held,
            "resets": self.resets,
            "god_angry": self.god_angry,
            "truncated": self.truncated,
            "role": self.role,
            "race": self.race,
            "dnum": self.bl(nh.NLE_BL_DNUM),
            "last_msgs": self.death_msgs or last,
        }
