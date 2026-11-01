"""Scripted NetHack bot on top of NLE (NetHackChallenge-v0).

Objective: in-game score; also tracks max depth."""
import re
from collections import deque

import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.carry import CarryMixin
from nhbot.combat import CombatMixin
from nhbot.elbereth import ElberethMixin
from nhbot.equipment import EquipMixin
from nhbot.excalibur import ExcaliburMixin
from nhbot.explore import ExploreMixin
from nhbot.focus import FocusMixin
from nhbot.game import GameMixin, GameOver
from nhbot.goals import GoalsMixin
from nhbot.mapmem import MapMixin
from nhbot.nav import NavMixin
from nhbot.options import Options
from nhbot.perception import PerceptionMixin
from nhbot.policy import PolicyMixin
from nhbot.pricemem import PriceMemoryMixin
from nhbot.scrolls import ScrollMixin
from nhbot.shop import ShopMixin
from nhbot.survival import SurvivalMixin
from nhbot.thieves import ThievesMixin
from nhbot.weapons import WeaponsMixin


class Bot(PolicyMixin, GoalsMixin, GameMixin, MapMixin, NavMixin, PerceptionMixin, SurvivalMixin, CombatMixin,
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

    def run(self):
        if self.seed is not None:
            self.env.unwrapped.seed( core=self.seed, disp=self.seed, reseed=False)
        obs, _ = self.env.reset()
        self.obs = obs
        self.last_bl = obs["blstats"].copy()
        self.hostile_cache = {}
        self._grids_key, self._grids = None, None
        self.tick_no = 0
        self.peaceful_waits = 0
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
        self.combat_init()
        self.excal_init()
        self.thieves_init()
        self.weapons_init()
        self.elbereth_init()
        self.shop_init()
        self.scroll_init()
        self.carry_init()
        self.price_init()
        self.policy_init()
        self.goals_init()
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
                    # time per activity: the label an action set (fight, rest, explore, search, ...), else the
                    # policy step that acted
                    act = self.cur_act if self.cur_act != "other" else (self.last_step or "other")
                    self.time_by[act] = self.time_by.get(act, 0) + dt
                    if self.chasing:
                        self.goal_stats[self.chasing]["chase_turns"] += dt
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
            "goals": self.goal_summary(),
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
            "loot_holds": self.loot_holds,
            "mines_return_descents": self.mines_return_descents,
            "peaceful_waits": self.peaceful_waits,
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
