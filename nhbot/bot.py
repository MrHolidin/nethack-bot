"""Scripted NetHack bot on top of NLE (NetHackChallenge-v0).

Objective: in-game score; also tracks max depth."""
import re
from collections import Counter, deque

import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.boxes import BoxMixin
from nhbot.carry import CarryMixin
from nhbot.combat import CombatMixin
from nhbot.elbereth import ElberethMixin
from nhbot.equipment import EquipMixin
from nhbot.excalibur import ExcaliburMixin
from nhbot.explore import ExploreMixin
from nhbot.focus import FocusMixin
from nhbot.game import GameMixin, GameOver
from nhbot.charges import WandChargeMixin
from nhbot.threats import ThreatMixin
from nhbot.goals import GoalsMixin
from nhbot.mapmem import MapMixin
from nhbot.nav import NavMixin
from nhbot.options import Options
from nhbot.perception import PerceptionMixin
from nhbot.pickup import PickupMixin
from nhbot.policy import PolicyMixin
from nhbot.pricemem import PriceMemoryMixin, appearance
from nhbot.scrolls import ScrollMixin
from nhbot.shop import ShopMixin
from nhbot.survival import SurvivalMixin
from nhbot.thieves import ThievesMixin
from nhbot.value import ValueMixin
from nhbot.wandid import WandIdMixin
from nhbot.danger import DangerMixin
from nhbot.tins import TinMixin
from nhbot.altar import AltarMixin
from nhbot.potiontest import PotionTestMixin
from nhbot.jewelry import JewelryMixin
from nhbot.gift import GiftMixin
from nhbot.weapons import WeaponsMixin
from nhbot.wishing import WishMixin
from nhbot.sacrifice import SacrificeMixin
from nhbot.sokoban import SokobanMixin

SNAP_EVERY = 500                 # turns between state snapshots (stats "snaps")
MAGIC_CLASSES = (nh.POTION_CLASS, nh.SCROLL_CLASS, nh.RING_CLASS, nh.WAND_CLASS, nh.AMULET_CLASS)

class Bot(PolicyMixin, GoalsMixin, GameMixin, MapMixin, NavMixin, PerceptionMixin, SurvivalMixin, CombatMixin,
          ElberethMixin, ThievesMixin, WeaponsMixin, ExploreMixin, ExcaliburMixin, ShopMixin, EquipMixin,
          CarryMixin, PickupMixin, FocusMixin, ScrollMixin, PriceMemoryMixin, ValueMixin, WandIdMixin, DangerMixin, TinMixin, AltarMixin,
          PotionTestMixin, JewelryMixin, GiftMixin, WishMixin, BoxMixin, WandChargeMixin, ThreatMixin,
          SacrificeMixin, SokobanMixin):
    OBS_KEYS = ("glyphs", "blstats", "message", "inv_strs", "inv_letters", "inv_oclasses", "tty_chars", "misc")

    def __init__(self, seed=None, character="@", verbose=False, max_steps=200_000, max_turns=None,
                 role_opts=None, **options):
        """role_opts and any other keyword arguments are options (options.py); unknown names raise."""
        from nle.env.tasks import NetHackScore
        self.opts = Options({**(role_opts or {}), **options})
        self.env = NetHackScore(character=character,
                                actions=nh.ACTIONS, allow_all_yn_questions=True,
                                allow_all_modes=True, max_episode_steps=1_000_000,
                                penalty_step=0.0, penalty_time=0.0,
                                observation_keys=self.OBS_KEYS)
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
        self.killed = None        # msg_combat: what the message being handled says we killed
        self.asked = ""          # game.ask: the last question's message
        self.really_attacks = 0   # "Really attack?" questions (answered no)
        self._items, self._items_at = [], -1
        self._items_parsed, self._items_inv = [], None
        self._inv, self._inv_at = (), -1
        self.msg_audit = Counter()  # cases where message reading may go wrong (game.audit, pickup, ...)
        self.here_window = None   # (turn, pos, text) of the last 'Things that are here' window
        self.tick_seq = 0         # msg_seq at the start of this tick
        self.cur_key = None
        self.last_move_target = None
        self.last_attack_target = None
        self.last_pray = None
        self.prayers = 0
        self.pray_failed = 0
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
        self.snaps, self.next_snap = [], SNAP_EVERY
        self.faint_since = None
        self.hist = deque()
        self.no_eat_until = 0
        self.shops_seen = 0
        self.shops_from_keeper = 0   # mapmem.shop_from_keeper: shops marked from a shopkeeper in view
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
        self.stair_from = None           # (level key, square) of the staircase we last took
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
        self.wandid_init()
        self.charges_init()
        self.threats_init()
        self.danger_init()
        self.tins_init()
        self.altar_init()
        self.sacrifice_init()
        self.sokoban_init()
        self.gift_init()
        self.potiontest_init()
        self.jewelry_init()
        self.box_init()
        self.wishing_init()
        self.value_init()
        self.policy_init()
        self.goals_init()
        self.pickup_init()
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
            self.gift_apply()
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
                if self.gift_stats and self.turn() // 50 != t0 // 50:
                    self.gift_check()
                while self.turn() >= self.next_snap:
                    self.snaps.append(self.snapshot())
                    self.next_snap += SNAP_EVERY
        except GameOver:
            pass
        return self.summary()

    def snapshot(self):
        """State every SNAP_EVERY turns (stats "snaps"): to see where two runs of one seed part, and in what."""
        magic = [it for it in self.items() if it.ocls in MAGIC_CLASSES]
        unknown = sum(1 for it in magic if appearance(it.text) is not None)
        return {"t": self.turn(), "dlvl": self.bl(nh.NLE_BL_DEPTH), "dnum": self.bl(nh.NLE_BL_DNUM),
                "max_depth": self.max_depth,
                "xl": self.bl(nh.NLE_BL_XP), "hp": self.bl(nh.NLE_BL_HP), "maxhp": self.bl(nh.NLE_BL_HPMAX),
                "ac": self.bl(nh.NLE_BL_AC), "gold": self.bl(nh.NLE_BL_GOLD),
                "pet": self.turn() - self.pet_last_seen <= 100, "magic_known": len(magic) - unknown,
                "magic_unknown": unknown, "kills": len(self.kills), "prayers": self.prayers}

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
            "quaffs": self.quaffs, "unihorn": dict(self.horn_stats),
            "maps_read": self.maps_read,
            "pet_waited": self.pet_waited_total,
            "zaps": self.zaps, "zap_stats": dict(self.zap_stats), "wishes": self.wishes, "wishing": dict(self.wish_stats), "ray_risk": {"counts": dict(self.ray_risk_stats), "log": self.ray_risk_log}, "wand_pwin_log": self.wand_pwin_log, "wandid": dict(self.wandid_stats), "danger": self.danger_summary(), "flee": dict(self.flee_stats), "descent_rest": sum(self.descent_rest.values()), "revisit": dict(self.revisit_stats), "tins": dict(self.tin_stats), "altar": dict(self.altar_stats), "protection": dict(self.prot_stats, ac=self.prot_bought), "quaff_test": dict(self.quaff_stats), "jewelry": dict(self.jewelry_stats), "browse": dict(self.browse_stats), "gift": self.gift_stats, "tins_eaten": dict(self.tin_eaten_by),
            "thefts": self.thefts,
            "elb_engraves": self.elb_engraves,
            "elb_misspelled": self.elb_misspelled,
            "elb_fail": self.elb_fail,
            "focus_calls": self.focus_calls, "focus_picks": self.focus_picks,
            "boxes": dict(self.box_stats, welded=self.swap_welded),
            "enchant": dict(self.enchant_stats, log=self.enchant_log), "scrolls": dict(self.scroll_stats), "force_read": self.force_read_log, "snaps": self.snaps, "price_memory": dict(self.price_stats, appearances=self.price_report()),

            "blind_waits": self.blind_waits, "poison_res": self.poison_res, "shop_kicks_avoided": self.shop_kicks_avoided,

            "elb_fail_msgs": self.elb_fail_msgs[:5],
            "elb_rewrites": self.elb_rewrites,
            "elb_blocked": dict(self.elb_block_reasons),
            "goals": self.goal_summary(),
            "carry": dict(self.carry_stats),
            "stash": dict(self.stash_stats),
            "elb_only_c": self.elb_only_c,
            "elb_stats": dict(self.elb_stats),
            "elb_turns": self.elb_turns,
            "elb_exits": dict(self.elb_exits),
            "deadly_prayers": self.deadly_prayers,
            "pray_failed": self.pray_failed,
            "stun_waits": self.stun_waits,
            "nymph_kills": self.nymph_kills, "nymph_zaps": dict(self.nymph_zap_stats),
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
            "level_stats": [dict(key=list(k), entered=v.entered_turn, xl=v.entered_xl, turns=v.turns_here,
                                 search=v.search_turns,
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
            "shops": self.shops_seen, "shops_from_keeper": self.shops_from_keeper,
            "desperate": self.desperations,
            "unblock": [self.unblocks, self.unblock_throws, self.unblock_melee],
            "vault": [self.vault_drops, self.vault_moves],
            "items_first": self.items_first_holds,
            "mines_return_descents": self.mines_return_descents,
            "peaceful_waits": self.peaceful_waits, "peace_shut": self.peace_shut_count,
            "msg_audit": dict(self.msg_audit),
            "farlooks": self.farlooks,
            "peaceful_hits": dict(self.peaceful_hits),
            "peace_turned": self.peace_turned,
            "really_attacks": self.really_attacks,
            "empty_looks": self.empty_looks,
            "pickup_stats": dict(self.pickup_stats),
            "trap_stats": {k: v for k, v in self.trap_stats.items() if not k.startswith("_")},
            "door_stats": dict(self.door_stats),
            "squeeze_stats": dict(self.squeeze_stats),
            "mines_kick_stats": dict(self.mines_kick_stats),
            "hunger_turns": {["satiated", "not_hungry", "hungry", "weak", "fainting", "fainted", "starved"][k] if k < 7 else str(k): v for k, v in sorted(self.hunger_turns.items())},
            "eaten_by": dict(self.eaten_by.most_common(12)),
            "kill_by": dict(self.kill_by.most_common(15)),
            "peaceful_wait_by": dict(self.peaceful_wait_by.most_common(8)),
            "hunt": [self.hunts, self.hunt_steps, self.hunt_offline_steps],
            "ward": [self.ward_writes, self.ward_waits],
            "blind_held": self.blind_held,
            "mines_return": self.mines_return_log, "mines_trip": dict(self.mines_trip_stats), "sacrifice": dict(self.sac_stats), "sokoban": dict(self.soko_stats, secs=round(self.soko_secs, 1)),
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
