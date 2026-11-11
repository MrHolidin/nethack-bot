"""Scripted NetHack bot on top of NLE (NetHackChallenge-v0).

Objective: in-game score; also tracks max depth."""
import re

import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.boxes import BoxMixin
from nhbot.carry import CarryMixin
from nhbot.combat import CombatMixin
from nhbot.elbereth import ElberethMixin
from nhbot.equipment import EquipMixin
from nhbot.excalibur import ExcaliburMixin
from nhbot.explore import ExploreMixin
from nhbot.mines import MinesMixin
from nhbot.focus import FocusMixin
from nhbot.game import GameMixin, GameOver
from nhbot.charges import WandChargeMixin
from nhbot.threats import ThreatMixin
from nhbot.goals import GoalsMixin
from nhbot.goldbag import GoldBagMixin
from nhbot.mapmem import MapMixin
from nhbot.nav import NavMixin
from nhbot.options import Options
from nhbot.perception import PerceptionMixin
from nhbot.pickup import PickupMixin
from nhbot.policy import PolicyMixin
from nhbot.poly import PolyMixin
from nhbot.pricemem import PriceMemoryMixin, appearance
from nhbot.scrolls import ScrollMixin
from nhbot.shop import ShopMixin
from nhbot.survival import SurvivalMixin
from nhbot.thieves import ThievesMixin
from nhbot.value import ValueMixin
from nhbot.wandid import WandIdMixin
from nhbot.danger import DangerMixin
from nhbot.deep import DeepMixin
from nhbot.tins import TinMixin
from nhbot.actions import ActionsMixin
from nhbot.altar import AltarMixin
from nhbot.potiontest import PotionTestMixin
from nhbot.jewelry import JewelryMixin
from nhbot.gift import GiftMixin
from nhbot.hidden import HiddenMixin
from nhbot.weapons import WeaponsMixin
from nhbot.wishing import WishMixin
from nhbot.sacrifice import SacrificeMixin
from nhbot.sokoban import SokobanMixin
from nhbot.vault import VaultMixin
from nhbot.digging import DiggingMixin
from nhbot.digthrough import DigThroughMixin
from nhbot.rockdig import RockDigMixin
from nhbot.locktools import LockToolMixin
from nhbot.luckstone import LuckstoneMixin

SNAP_EVERY = 500                 # turns between state snapshots (stats "snaps")
MAGIC_CLASSES = (nh.POTION_CLASS, nh.SCROLL_CLASS, nh.RING_CLASS, nh.WAND_CLASS, nh.AMULET_CLASS)

class Bot(DeepMixin, PolicyMixin, GoalsMixin, GameMixin, ActionsMixin, MapMixin, NavMixin, PerceptionMixin, SurvivalMixin, CombatMixin,
          ElberethMixin, ThievesMixin, WeaponsMixin, ExploreMixin, MinesMixin, ExcaliburMixin, ShopMixin, EquipMixin,
          CarryMixin, PickupMixin, FocusMixin, ScrollMixin, PriceMemoryMixin, ValueMixin, WandIdMixin, DangerMixin, TinMixin, AltarMixin,
          PotionTestMixin, JewelryMixin, GiftMixin, HiddenMixin, WishMixin, BoxMixin, WandChargeMixin, ThreatMixin,
          SacrificeMixin, SokobanMixin, GoldBagMixin, VaultMixin, DiggingMixin, DigThroughMixin, RockDigMixin, LockToolMixin, PolyMixin,
          LuckstoneMixin):
    OBS_KEYS = ("glyphs", "blstats", "message", "inv_strs", "inv_letters", "inv_oclasses", "tty_chars", "misc",
                "tty_cursor")

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
        self.time_by = {}
        self.cur_act = "other"
        self.snaps, self.next_snap = [], SNAP_EVERY
        self.start_ac = None             # AC once the game is set up (summary)
        self.death_msgs = []
        self.game_init()
        self.map_init()
        self.nav_init()
        self.focus_init()
        self.equip_init()
        self.actions_init()
        self.perception_init()
        self.survival_init()
        self.explore_init()
        self.mines_init()
        self.hidden_init()
        self.combat_init()
        self.excal_init()
        self.thieves_init()
        self.goldbag_init()
        self.vault_init()
        self.digging_init()
        self.dig_through_init()
        self.rock_dig_init()
        self.lock_init()
        self.luckstone_init()
        self.deep_init()
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
                self.prev_act, self.cur_act = self.cur_act, "other"
                self.tick()
                dt = self.turn() - t0
                if self.klog is not None:
                    self.key_stats_tick(dt)
                if dt > 0:
                    # time per activity: the label an action set (fight, rest, explore, search, ...), else the
                    # policy step that acted
                    act = self.cur_act if self.cur_act != "other" else (self.pol.last_step or "other")
                    self.time_by[act] = self.time_by.get(act, 0) + dt
                    if self.goals.chasing:
                        self.goals.stats[self.goals.chasing]["chase_turns"] += dt
                    lvc = self.levels.get(self.cur_key)
                    if lvc is not None:
                        lvc.turns_here += dt
                        if self.cur_act == "search":
                            lvc.search_turns += dt
                if self.gift.stats and self.turn() // 50 != t0 // 50:
                    self.gift_check()
                while self.turn() >= self.next_snap:
                    self.snaps.append(self.snapshot())
                    self.next_snap += SNAP_EVERY
        except GameOver:
            pass
        return self.summary()

    def key_stats_tick(self, dt):
        """key_stats: the keys of the tick just played, by activity (the time_by label), free (no turn passed) or
        not; the tick's key sequence (runs of one key shortened) by activity."""
        if not hasattr(self, "kstat"):
            from collections import Counter
            self.kstat = {"keys": Counter(), "free": Counter(), "turns": Counter(), "ticks": Counter(),
                          "key": Counter(), "seq": Counter(), "seqk": Counter()}
        k, ks = self.klog, self.kstat
        act = self.cur_act if self.cur_act != "other" else (self.pol.last_step or "other")
        ks["keys"][act] += len(k)
        ks["turns"][act] += dt
        ks["ticks"][act] += 1
        if dt == 0:
            ks["free"][act] += len(k)
        for c in k:
            ks["key"][c] += 1
        s = "".join(chr(c) if 32 < c < 127 else {13: "<CR>", 27: "<ESC>", 32: "<SP>"}.get(c, f"<{c}>") for c in k)
        s = re.sub(r"(.)\1{3,}", lambda m: f"{m.group(1)}*{len(m.group(0))}", s)[:40]
        ks["seq"][f"{act}|{dt > 0}|{s}"] += 1
        ks["seqk"][f"{act}|{dt > 0}|{s}"] += len(k)
        self.klog = []

    def key_stats_summary(self):
        ks = getattr(self, "kstat", None)
        if ks is None:
            return {}
        return {"key_stats": {"keys": dict(ks["keys"]), "free": dict(ks["free"]), "turns": dict(ks["turns"]),
                              "ticks": dict(ks["ticks"]), "key": {str(c): n for c, n in ks["key"].items()},
                              "count": dict(self.kcount),
                              "seq": {q: [ks["seq"][q], n] for q, n in ks["seqk"].most_common(80)}}}

    def snapshot(self):
        """State every SNAP_EVERY turns (stats "snaps"): to see where two runs of one seed part, and in what."""
        magic = [it for it in self.items() if it.ocls in MAGIC_CLASSES]
        unknown = sum(1 for it in magic if appearance(it.text) is not None)
        return {"t": self.turn(), "dlvl": self.bl(nh.NLE_BL_DEPTH), "dnum": self.bl(nh.NLE_BL_DNUM),
                "max_depth": self.max_depth,
                "xl": self.bl(nh.NLE_BL_XP), "hp": self.bl(nh.NLE_BL_HP), "maxhp": self.bl(nh.NLE_BL_HPMAX),
                "ac": self.bl(nh.NLE_BL_AC), "gold": self.bl(nh.NLE_BL_GOLD),
                "pet": self.turn() - self.pol.pet_last_seen <= 100, "magic_known": len(magic) - unknown,
                "magic_unknown": unknown, "kills": len(self.combat.kills), "prayers": self.surv.prayers,
                "score": int(self.reward), "keys": self.steps}

    def summary(self):
        last = [m for _, m in list(self.messages)[-10:]]
        return {
            "seed": self.seed,
            "score": self.reward,
            "max_depth": self.max_depth,
            "turns": self.turn(),
            "steps": self.steps,
            "xl": self.bl(nh.NLE_BL_XP),
            "prayers": self.surv.prayers,
            "elbereths": self.elb.elbereths,
            "corpses": self.surv.corpses_eaten,
            "throws": self.acts.throws,
            "loops": self.pol.loops,
            "loop_by": dict(self.pol.loop_by),
            "map_stats": dict(self.map_stats),
            "start_ac": self.start_ac,
            "exp": self.bl(nh.NLE_BL_EXP),
            "gold": self.bl(nh.NLE_BL_GOLD),
            "maxhp": self.bl(nh.NLE_BL_HPMAX),
            "kills": self.combat.kill_count,
            "skill_msgs": self.surv.skill_msgs,
            "enhances": self.surv.enhances,
            "quaffs": self.surv.quaffs, "unihorn": dict(self.surv.horn_stats),
            "maps_read": self.expl.maps_read,
            "pet_waited": self.expl.pet_waited_total,
            "zaps": self.acts.zaps, "zap_stats": dict(self.combat.zap_stats), "wishes": self.equip.wishes, **self.wishing_summary(), "ray_risk": {"counts": dict(self.combat.ray_risk_stats), "log": self.combat.ray_risk_log}, "wand_pwin_log": self.combat.wand_pwin_log, **self.wandid_summary(), "danger": self.danger_summary(), "descent_rest": sum(self.expl.descent_rest.values()), "revisit": dict(self.expl.revisit_stats), "tins": dict(self.tin.stats), **self.altar_summary(), **self.potiontest_summary(), **self.jewelry_summary(), "browse": dict(self.shop.browse_stats), **self.gift_summary(), "tins_eaten": dict(self.tin.eaten_by),
            "thefts": self.thief.thefts, "gold_flow": dict(self.thief.gold_flow), "poly": dict(self.thief.poly_stats), "gold_by_xl": self.thief.gold_xl,
            **self.goldbag_summary(),
            "elb_engraves": self.elb.engraves,
            "elb_misspelled": self.elb.misspelled,
            "elb_fail": self.elb.fail,
            "focus_calls": self.focus.calls, "focus_picks": self.focus.picks,
            **self.box_summary(),
            **self.scroll_summary(), "snaps": self.snaps, **self.price_summary(),

            "blind_waits": self.pol.blind_waits, "hallu_waits": self.pol.hallu_waits, "poison_res": self.surv.poison_res, "shop_kicks_avoided": self.nav.shop_kicks_avoided,

            "elb_fail_msgs": self.elb.fail_msgs[:5],
            "elb_rewrites": self.elb.rewrites,
            "elb_blocked": dict(self.elb.block_reasons),
            "goals": self.goal_summary(),
            "carry": dict(self.carry.stats),
            "stash": dict(self.shop.stash_stats),
            "elb_only_c": self.elb.only_c,
            "elb_stats": dict(self.elb.stats),
            "elb_turns": self.elb.turns,
            "elb_exits": dict(self.elb.exits),
            "deadly_prayers": self.pol.deadly_prayers,
            "pray_failed": self.surv.pray_failed,
            "stun_waits": self.pol.stun_waits,
            "nymph_kills": self.thief.nymph_kills,
            "loot_pickups": self.thief.loot_pickups,
            **self.weapons_summary(),
            **self.excal_summary(),
            "align": int(self.last_bl[nh.NLE_BL_ALIGN]),
            "ammo_pickups": self.pol.ammo_pickups,
            "pet_last_seen": self.pol.pet_last_seen,
            "time_by": self.time_by,
            "levels_seen": len(self.levels),
            "level_stats": [dict(key=list(k), entered=v.entered_turn, xl=v.entered_xl, turns=v.turns_here,
                                 search=v.search_turns,
                                 down_known=bool((G.KIND[v.under] == G.DOWNSTAIR).any()),
                                 mines_branch=bool(v.avoid_down), desperate=v.desperate,
                                 seen=int(v.seen.sum()))
                            for k, v in self.levels.items()],
            "food_picked": self.pick.food_picked,
            "hist": list(self.pol.hist),
            "last_pray": self.surv.last_pray,
            "ac": self.bl(nh.NLE_BL_AC),
            "worn": [e[2] for e in self.equip.events if e[1] == "wear"],
            "equip_fail": sum(1 for e in self.equip.events if e[1] == "fail"),
            "shops": self.shop.seen,
            "desperate": self.pol.desperations,
            "unblock": [self.combat.unblocks, self.combat.unblock_throws],
            "vault": [self.surv.vault_drops, self.surv.vault_moves, self.surv.vault_approach, self.surv.vault_bag_outs], **self.vault_summary(), **self.dig_through_summary(), **self.rock_dig_summary(), **self.lock_summary(), **self.luckstone_summary(), **self.deep_summary(), "stun_peace_waits": self.pol.stun_peace_waits,
            "items_first": self.expl.items_first_holds,
            **self.hidden_summary(),
            "mines_return_descents": self.mines.return_descents,
            "peaceful_waits": self.nav.peaceful_waits,
            "peace_wait_blocks": self.nav.peace_wait_blocks,
            "msg_audit": dict(self.msg_audit),
            "farlooks": self.perc.farlooks,
            "peaceful_hits": dict(self.perc.peaceful_hits),
            "peace_turned": self.perc.peace_turned,
            "really_attacks": self.really_attacks,
            "empty_looks": self.perc.empty_looks,
            "pickup_stats": dict(self.pick.stats),
            "trap_stats": dict(self.nav.trap_stats),
            "door_stats": dict(self.nav.door_stats),
            "squeeze_stats": dict(self.carry.squeeze_stats),
            "mines_kick_stats": dict(self.nav.mines_kick_stats),
            "hunger_turns": {["satiated", "not_hungry", "hungry", "weak", "fainting", "fainted", "starved"][k] if k < 7 else str(k): v for k, v in sorted(self.surv.hunger_turns.items())},
            "eaten_by": dict(self.surv.eaten_by.most_common(12)),
            "kill_by": dict(self.combat.kill_by.most_common(15)),
            "peaceful_wait_by": dict(self.nav.peaceful_wait_by.most_common(8)),
            "hunt": [self.combat.hunts, self.combat.hunt_steps, self.combat.hunt_offline_steps],
            "blind_held": self.perc.blind_held,
            "mines_return": self.mines.return_log, "mines_trip": dict(self.mines.trip_stats), **self.sacrifice_summary(), "sokoban": dict(self.soko_stats, secs=round(self.soko_secs, 1), work=self.soko_work),
            "minetown_seen": self.mines.minetown_seen,
            "hallu_held": self.perc.hallu_held,
            "resets": self.pol.resets,
            "god_angry": self.surv.god_angry,
            "truncated": self.truncated,
            "role": self.role,
            "race": self.race,
            "dnum": self.bl(nh.NLE_BL_DNUM),
            "last_msgs": self.death_msgs or last,
            **self.key_stats_summary(),
        }
