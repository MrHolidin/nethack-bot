"""Scripted NetHack bot on top of NLE (NetHackChallenge-v0).

Objective: in-game score; also tracks max depth.
"""
import heapq
import re
from collections import deque

import numpy as np
import gymnasium as gym
import nle  # noqa: F401  (registers envs)
import nle.env.base
import nle.nethack as nh

import glyphs as G
from equipment import EquipMixin
from tactics import TacticsMixin
from abilities import AbilitiesMixin
from roles import RolesMixin, AMMO, ClassTacticsMixin, ExcaliburMixin
from focus import FocusMixin
from scrolls import ScrollMixin
from valk import ValkMixin, ValkMixin2, ElberethMixin, RTHREAT_RE, RTRAP_RE
from shop import ShopMixin
from wandid import WandIdMixin
from armorid import ArmorIdMixin, RANDOM_APPEARANCE
from carry import CarryMixin, CARRY_GLYPH
from pricemem import PriceMemoryMixin

ROWS, COLS = 21, 79
DIRS = {  # key: (dy, dx)
    "k": (-1, 0), "j": (1, 0), "h": (0, -1), "l": (0, 1),
    "y": (-1, -1), "u": (-1, 1), "b": (1, -1), "n": (1, 1),
}
DELTA2KEY = {v: k for k, v in DIRS.items()}
NEIGH = list(DIRS.values())

# hunger states
SATIATED, NOT_HUNGRY, HUNGRY, WEAK, FAINTING = 0, 1, 2, 3, 4

NEVER_MELEE = {"floating eye", "gas spore", "cockatrice", "chickatrice",
               "blue jelly", "spotted jelly", "ochre jelly", "brown mold", "green mold"}
PASSIVE_MOLDS = {"yellow mold", "green mold", "brown mold", "red mold", "lichen" and "", "violet fungus" and ""}
PASSIVE_MOLDS.discard("")
ALWAYS_AVOID = {"gas spore", "cockatrice", "chickatrice", "brown mold", "green mold"}   # even when desperate
RANGED_TARGETS = {"floating eye", "gas spore", "blue jelly", "spotted jelly",
                  "ochre jelly", "brown mold", "green mold", "cockatrice", "chickatrice"}
THROWABLE = ("dagger", "dart", "knife", "shuriken", "javelin", "spear")
THROW_STONES = ("flint stone", "rock")
# fresh-corpse whitelist (eaten only within ~40 turns of the kill)
# trap.c messages for a trap going off on (or found at) our own square, for traps that leave us standing on it
TRAP_HERE_RE = re.compile(r"There is an? [a-z ]*trap here|You escape an? [a-z ]*trap|a rock falls on your head|"
                          r"An arrow shoots out at you|A little dart shoots out at you|A bear trap closes on your|"
                          r"You fall into a pit|You land on a set of sharp iron spikes|A board beneath you squeaks|"
                          r"A gush of water hits (?:you\b|your )|A tower of flame (?:erupts|bursts) from the floor!|"
                          r"A cloud of gas puts you to sleep|"
                          r"You (?:stumble into|are caught in|flounder in) a (?:spider )?web|"
                          r"You trigger a rolling boulder trap|You step onto a (?:polymorph|magic) trap|"
                          r"You are caught in a magical explosion|You feel momentarily lethargic")
# eat.c cannibal test / were.c were_beastie(): the animals that count as our kind once infected
WERE_KIN = {"werejackal": {"jackal", "fox", "coyote", "werejackal"},
            "wererat": {"sewer rat", "giant rat", "rabid rat", "wererat"},
            "werewolf": {"wolf", "warg", "winter wolf", "werewolf"}}
SAFE_CORPSES = {"newt", "jackal", "coyote", "fox", "sewer rat", "giant rat",
                "lichen", "floating eye", "gecko", "iguana", "giant ant",
                "fire ant", "rothe", "wolf", "pony", "horse", "hobbit",
                "giant beetle", "baby crocodile", "crocodile", "lizard", "warg",
                "winter wolf cub", "bugbear", "mumak", "leocrotta", "wumpus",
                "titanothere", "baluchitherium", "ape", "owlbear", "yeti",
                "carnivorous ape", "monkey", "quivering blob", "giant mimic",
                "large mimic", "small mimic", "rock piercer", "iron piercer",
                "jaguar", "lynx", "panther", "tiger", "dingo", "jackalwere" and "",
                "gnome", "gnome lord", "gnomish wizard", "gnome king",
                "dwarf", "dwarf lord", "dwarf king",
                "hill orc", "Mordor orc", "Uruk-hai", "orc shaman", "orc-captain", "snaga" and "",
                "Woodland-elf", "Green-elf", "Grey-elf", "elf-lord",
                "cave spider", "centipede" and "", "giant spider" and "",
                "mountain nymph", "water nymph", "wood nymph",
                "rabbit" and "", "giant turtle", "large cat" and ""}
SAFE_CORPSES.discard("")
RACE_KIN = {"gnome": ("gnome", "gnomish"), "gnomish": ("gnome", "gnomish"),
            "dwarf": ("dwarf",), "dwarven": ("dwarf",),
            "elf": ("elf", "elven"), "elven": ("elf", "elven"),
            "orc": ("orc", "Uruk", "snaga"), "orcish": ("orc", "Uruk", "snaga"),
            "human": ("human",)}
ELBERETH_IGNORERS = {"minotaur", "shopkeeper", "guard", "watchman",
                     "watch captain", "aligned priest", "high priest"}
HUMAN_MLET = nh.permonst(next(i for i in range(nh.NUMMONS)
                              if nh.permonst(i).mname == "human")).mlet
MINOTAUR_MLET = nh.permonst(next(i for i in range(nh.NUMMONS)
                                 if nh.permonst(i).mname == "minotaur")).mlet


# monflag.h (NetHack 3.6)
M1_ACID, M1_POIS = 0x08000000, 0x10000000
M2_UNDEAD, M2_WERE, M2_SHAPESHIFTER = 0x2, 0x4, 0x4000
RACE_FLAG = {"human": 0x8, "elf": 0x10, "elven": 0x10, "dwarf": 0x20, "dwarven": 0x20,
             "gnome": 0x40, "gnomish": 0x40, "orc": 0x80, "orcish": 0x80}

NEVER_EAT = {"cockatrice", "chickatrice", "Medusa", "green slime", "little dog", "dog", "large dog",
             "kitten", "housecat", "large cat", "Death", "Pestilence", "Famine"}
PM_BY_NAME = {nh.permonst(i).mname: nh.permonst(i) for i in range(nh.NUMMONS)}
from monattacks import ATTACKS as _ATK
PASSIVE_ONLY = {nh.permonst(i).mname for i in range(nh.NUMMONS) if all(a[0] == "NONE" for a in _ATK[i])}
# hurt us only when we hit them (a passive attack and no active one): molds, jellies, acid blob, floating eye.
# A shrieker has no attack at all: hitting it is free.
PASSIVE_DMG = {nh.permonst(i).mname for i in range(nh.NUMMONS)
               if _ATK[i] and all(a[0] == "NONE" for a in _ATK[i])}


class GameOver(Exception):
    pass


class Level:
    def __init__(self, key):
        self.key = key
        self.under = np.full((ROWS, COLS), G.STONE_GLYPH, dtype=np.int32)
        self.seen = np.zeros((ROWS, COLS), dtype=bool)
        self.visited = np.zeros((ROWS, COLS), dtype=np.int32)
        self.near = np.zeros((ROWS, COLS), dtype=bool)
        self.searched = np.zeros((ROWS, COLS), dtype=np.int32)
        self.blocked = np.zeros((ROWS, COLS), dtype=bool)
        self.fail = np.zeros((ROWS, COLS), dtype=np.int32)
        self.locked = set()
        self.gold_tried = set()
        self.avoid_down = set()
        self.shop = np.zeros((ROWS, COLS), dtype=bool)
        self.desperate = False
        self.search_turns = 0
        self.turns_here = 0
        self.progress_count = 0
        self.last_progress = 0
        self.last_reset = 0   # downstairs leading into the Gnomish Mines
        self.peaceful = set()     # monster glyphs that turned out peaceful here
        self.entered_turn = None
        self.elbereth = set()     # positions where we engraved
        self.trap_mem = set()     # trap_mem: squares where a trap went off under us (an object may hide its ^)


class Bot(EquipMixin, TacticsMixin, AbilitiesMixin, RolesMixin, ClassTacticsMixin, ShopMixin, ExcaliburMixin, ValkMixin, ValkMixin2, ElberethMixin, FocusMixin, ScrollMixin, ArmorIdMixin, CarryMixin, PriceMemoryMixin, WandIdMixin):
    def __init__(self, seed=None, character="@", verbose=False, max_steps=200_000, max_turns=None,
                 avoid_mines=False, use_armor=True, use_food=True, use_tactics=False,
                 use_enhance=True, use_pet=True, use_abilities=True, use_roles=True, role_opts=None,
                 flee_hp=0.5, danger_k=3, recover_hp=0.8, corpse_policy="flags", flee_turns=4.0, rest_frac=0.5, elb_frac=0.0, descend_hp=0.0,
                 descend_policy="explore"):
        from nle.env.tasks import NetHackScore
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
        self.avoid_mines = avoid_mines
        self.use_armor = use_armor
        self.use_food, self.use_tactics = use_food, use_tactics
        self.use_enhance, self.use_pet, self.use_abilities = use_enhance, use_pet, use_abilities
        self.use_roles = use_roles
        self.role_opts = role_opts or {}
        self.flee_hp, self.danger_k, self.recover_hp = flee_hp, danger_k, recover_hp
        self.corpse_policy = corpse_policy
        self.flee_turns = flee_turns
        self.rest_frac, self.elb_frac, self.descend_hp = rest_frac, elb_frac, descend_hp
        self.descend_policy = descend_policy
        acts = self.env.unwrapped.actions
        self.key2act = {}
        for i, a in enumerate(acts):
            self.key2act.setdefault(int(a), i)

    # ------------------------------------------------------------------ io
    def raw_step(self, code):
        if code not in self.key2act:
            raise ValueError(f"key {code!r} not in action set")
        self.obs, r, term, trunc, info = self.env.step(self.key2act[code])
        self.steps += 1
        self.reward += r
        self.done = term or trunc
        if not self.done:
            self.last_bl = self.obs["blstats"].copy()
            self.last_tty = self.obs["tty_chars"]
        if self.done:
            raise GameOver()
        if self.steps >= self.max_steps or (self.max_turns and self.turn() >= self.max_turns):
            self.truncated = True
            raise GameOver()

    def tty_text(self):
        return "\n".join(bytes(r).decode("latin1") for r in self.obs["tty_chars"])

    def top_line(self):
        return bytes(self.obs["tty_chars"][0]).decode("latin1").rstrip()

    def log_msg(self, m):
        m = m.strip()
        if m and m == self._last_logged and self.steps == self._last_logged_step:
            return
        self._last_logged, self._last_logged_step = m, self.steps
        if m:
            self.messages.append((self.turn(), m))
            self.msg_seq += 1
            if self.verbose:
                self.all_msgs.append((self.turn(), m))
            if len(self.messages) > 60:
                self.messages.popleft()
            self.on_message(m)

    def message(self):
        return bytes(self.obs["message"]).decode("latin1").rstrip("\x00 ").strip()

    def press(self, key, expect_prompt=False):
        """Send one key, then clear --More-- and unexpected menus/prompts."""
        code = ord(key) if isinstance(key, str) else key
        if key in ("<", ">"):
            self.last_stair_dir = key
        self.raw_step(code)
        self.settle(expect_prompt)

    def settle(self, expect_prompt=False):
        for _ in range(50):
            tty = self.tty_text()
            msg = self.message()
            flat = tty.replace("\n", "")
            menu = re.search(r"\(end\)|\(\d+ of \d+\)", tty)
            if "--More--" in flat or (self.obs["misc"][2] and not menu):
                self.log_msg(msg if msg else self.top_line().replace("--More--", ""))
                self.raw_step(13)
                continue
            if expect_prompt:
                self.log_msg(msg)
                return
            misc = self.obs["misc"]
            if misc[0]:      # yn question
                self.log_msg(msg)
                self.answer_yn(msg)
                continue
            if misc[1]:      # getlin
                self.log_msg(msg)
                if "for what do you wish" in (msg + self.top_line()).lower() and self.role_opts.get("wish", False):
                    for c in "blessed +2 gray dragon scale mail":
                        self.raw_step(ord(c))
                    self.raw_step(13)
                    self.wishes_made = getattr(self, "wishes_made", 0) + 1
                    continue
                if "who are you" in (msg + self.top_line()).lower() and self.role_opts.get("vault_guard", True):
                    for c in "Agent":                       # our real name (lawful: lying costs alignment)
                        self.raw_step(ord(c))
                    self.raw_step(13)
                    continue
                self.raw_step(27)
                continue
            if re.search(r"\(end\)|\(\d+ of \d+\)", tty):
                self.raw_step(27)
                continue
            self.log_msg(msg)
            return

    def answer_yn(self, msg):
        m = msg.lower()
        if "offers" in m and "sell" in m:
            self.price_note_offer(msg + " " + self.top_line())       # every offer is a price reading
        if self.selling and ("sell it" in m or "sell them" in m):
            self.raw_step(ord("n" if self.keep_after_offer() else "y"))
            return
        if getattr(self, "sell_probe", None) and "sell" in m:
            self.on_sell_offer(msg + " " + self.top_line())
            self.raw_step(ord("n"))
            return
        if "really attack" in m:
            self.mark_peaceful_target()
            self.raw_step(27)
        elif "are you sure you want to pray" in m:
            self.raw_step(ord("y"))
        elif "still climb" in m:
            self.raw_step(ord("n"))
        elif "continue eating" in m:
            self.raw_step(ord("n"))
        elif "eat it" in m or "eat one" in m:
            self.raw_step(ord("n"))
        elif "itemized billing" in m:
            self.raw_step(ord("n"))
        elif "sell it?" in m:
            self.raw_step(ord("y"))
        elif m.rstrip().endswith("pay? [yn] (n)") or "pay?" in m:
            self.raw_step(ord("y"))
        elif "possessions identified" in m:
            self.raw_step(ord("q"))
        else:
            self.raw_step(27)

    # ----------------------------------------------------------- state
    def bl(self, idx):
        return int(self.last_bl[idx])

    def turn(self):
        return int(self.last_bl[nh.NLE_BL_TIME]) if hasattr(self, "last_bl") else 0

    def pos(self):
        return self.bl(nh.NLE_BL_Y), self.bl(nh.NLE_BL_X)

    def level(self):
        key = (self.bl(nh.NLE_BL_DNUM), self.bl(nh.NLE_BL_DLEVEL))
        lv = self.levels.get(key)
        if lv is None:
            lv = self.levels[key] = Level(key)
            lv.entered_turn = self.turn()
        return lv

    def update_memory(self):
        lv = self.level()
        g = self.obs["glyphs"]
        known = ~G.TRANSIENT[g]
        lv.under[known] = g[known]
        lv.seen |= known & (g != G.STONE_GLYPH)
        y, x = self.pos()
        if getattr(self, "_cur_pos", None) != (y, x):
            self.prev_pos, self._cur_pos = getattr(self, "_cur_pos", None), (y, x)
        lv.visited[y, x] += 1
        lv.near[max(0, y - 1):y + 2, max(0, x - 1):x + 2] = True
        if self.role_opts.get("shop_side", True) and not lv.shop[y, x] and lv.shop[max(0, y - 1):y + 2, max(0, x - 1):x + 2].any() \
                and G.KIND[lv.under[y, x]] not in (G.DOOR_OPEN, G.DOOR_CLOSED, G.DOORWAY) \
                and int(lv.under[y, x]) not in (nh.GLYPH_CMAP_OFF + 21, nh.GLYPH_CMAP_OFF + 22):
            # mark_shop floods from the door over what was visible at the greeting: squares the shopkeeper
            # or an item hid are missing. Standing on such a hole (an item goal there, or the end of a shop
            # visit) locked us in, since shop squares are impassable from outside. Next to the shop and
            # neither door nor corridor means inside it.
            lv.shop[y, x] = True
        self.max_depth = max(self.max_depth, self.bl(nh.NLE_BL_DEPTH))
        pc = int(lv.seen.sum()) + int((lv.visited > 0).sum())
        if pc > lv.progress_count:
            lv.progress_count = pc
            lv.last_progress = self.turn()
        return lv

    def on_message(self, m):
        lv = self.levels.get(self.cur_key) if self.cur_key else None
        # eat.c givit(POISON_RES): "You feel healthy."; eating poison while resistant: "You seem unaffected"
        if "You feel healthy" in m or "You seem unaffected by the poison" in m:
            self.poison_res = True
        if self.role_opts.get("focus", True):
            self.focus_note(m)
        self.rthreat_note(m)
        if "This door is locked" in m and self.last_move_target and lv:
            lv.locked.add(self.last_move_target)
        if lv and self.last_move_target and any(s in m for s in (
                "You try to move the boulder, but in vain",
                "Perhaps that's why you cannot move past it",
                "There is a boulder in your way",
                "You are carrying too much to get through",
                "You don't have enough room to maneuver")):
            lv.blocked[self.last_move_target] = True
        if "no shape for kicking" in m and lv and self.last_move_target:
            lv.blocked[self.last_move_target] = True
        if "Closed for inventory" in m and lv:
            y, x = self.pos()
            for dy, dx in NEIGH:
                ny, nx = y + dy, x + dx
                if 0 <= ny < ROWS and 0 <= nx < COLS and G.KIND[lv.under[ny, nx]] == G.DOOR_CLOSED:
                    lv.blocked[ny, nx] = True
        if lv is not None and ("You see here" in m or "Things that are here" in m or "several objects here" in m):
            self.seen_here = (self.turn(), self.pos(), m)
        if "more confident in your" in m:
            self.skill_msgs += 1
            self.want_enhance = True
        if re.search(r"You (kill|destroy) ", m):
            self.kill_count += 1
        mk = re.search(r"You (kill|destroy) (?:the |an? )?(.+?)!", m)
        if mk and self.last_attack_target:
            lvk = self.levels.get(self.cur_key)
            old_corpse = lvk is not None and G.KIND[lvk.under[self.last_attack_target]] == G.CORPSE
            if not old_corpse:      # an older corpse already lay there: what we'd eat may be that one
                self.kills.append((self.turn(), mk.group(2), self.last_attack_target, self.cur_key))
            if hasattr(self, "kill_loot"):
                self.note_kill(mk.group(2), self.last_attack_target)
        if "You feel that" in m and "displeased" in m:
            self.pray_failed += 1
        if self.last_pray is not None and self.turn() - self.last_pray <= 5 and any(
                p in m for p in ("Thou hast angered me", "Thou must relearn", "You feel guilty",
                                 "Then die, mortal", "Thou durst", "You feel that Mitra is angry",
                                 "is displeased.") if p != "is displeased."):
            self.god_angry = True
        if "for sale" in m:
            self.price_note_text(m)
        if RTHREAT_RE.search(m) and not RTRAP_RE.search(m) and self.turn() - getattr(self, "own_zap_turn", -99) > 1:
            self.last_shot_turn = self.turn()
        if self.role_opts.get("hunt_shooter", True) and RTHREAT_RE.search(m) and not RTRAP_RE.search(m) \
                and self.turn() - getattr(self, "own_zap_turn", -99) > 1:
            mm = re.search(r"The ([a-z][a-z' -]*?) (?:zaps|shoots|throws|hurls|fires|spits|breathes)", m)
            self.shot_event = (self.turn(), mm.group(1) if mm else None)
        if "Invisible customers are not welcome" in m and lv is not None:
            lv.shk_wait = 99                    # he won't let us in while we're invisible: stop waiting at the door
        if self.role_opts.get("trap_mem", False) and lv is not None and TRAP_HERE_RE.search(m):
            lv.trap_mem.add(self.pos())   # it went off under us; a falling rock / arrow / dart on it hides the ^
        if "unleash a water demon" in m or "stream of snakes pours" in m or "hear something hissing" in m:
            self.dip_threat_until = self.turn() + 150
        if self.role_opts.get("vault_guard", True):
            if "drop that gold" in m or "drop that money" in m:
                self.vault_drop = True
            if "follow me" in m:
                self.vault_follow_until = self.turn() + 300
                self.guard_trail = []
        if self.role_opts.get("shop_fix", True) and lv is not None and "Closed for inventory" in m:
            lv.cfi = getattr(lv, "cfi", set()) | {self.pos()}
        on_door = lv is not None and G.KIND[lv.under[self.pos()]] in (G.DOOR_OPEN, G.DOOR_CLOSED, G.DOORWAY)
        if self.role_opts.get("shop_fix2", True):
            # the square under us is often not in our map memory yet, so 'on the door' can't be checked;
            # instead: we are inside only if we just fell / were teleported onto this level
            recent = " ".join(mm for _, mm in list(self.messages)[-6:])
            on_door = not any(k in recent for k in ("trap door", "fall through", "hole", "teleport",
                                                     "wrenching", "You materialize"))
        if lv and re.search(r"Welcome to [A-Z][\w' -]*'s ", m) and (on_door or not self.role_opts.get("shop_fix", True)):
            # shop entrance: never go inside (we get trapped / risk shoplifting).
            # shop_fix: only when we are at the door -- after falling in through a trap door we are
            # inside, and marking from here walls us in
            self.mark_shop(lv, self.pos())
            self.shops_seen += 1
            self.shop_greeted(lv, m)
        if "Please pay before leaving" in m or "you owe" in m.lower() and "zorkmid" in m:
            self.need_pay = True
        if hasattr(self, "thefts"):
            self.on_valk_message(m)
        if "You feel feverish" in m:
            self.lycanthropy = True
            mk = re.search(r"\b(were(?:jackal|rat|wolf))\b", m)
            self.lyc_kind = mk.group(1) if mk else None      # None: infected by something we didn't see
        if "You feel purified" in m:
            self.lycanthropy = False
        if "carrying so much" in m:
            self.no_eat_until = self.turn() + 20
        if "You die" in m or "You starve" in m:
            self.death_msgs = [mm for _, mm in list(self.messages)[-8:]]

    # ------------------------------------------------------------ helpers
    def kind_grid(self, lv):
        """Terrain kind map from memory, with live monsters/objects overlaid."""
        g = self.obs["glyphs"]
        k_live = G.KIND[g]
        k_mem = G.KIND[lv.under]
        if lv.trap_mem:
            k_mem = k_mem.copy()
            for p in lv.trap_mem:
                if k_mem[p] in (G.FLOOR, G.OBJECT, G.CORPSE, G.GOLD, G.TRAP):
                    k_mem[p] = G.TRAP
        return k_mem, k_live

    def passable_grid(self, lv, k_mem, k_live):
        p = G.PASSABLE[k_mem].copy()
        p |= (k_mem == G.BOULDER) | (k_live == G.BOULDER)   # try pushing; failures mark blocked
        p[lv.blocked] = False
        if not lv.shop[self.pos()] and not self.shop_active(lv):
            p[lv.shop] = False
        # stationary dangerous monsters block
        for (y, x) in self.avoid_cells:
            p[y, x] = False
        return p

    def dijkstra(self, lv, k_mem, k_live, passable, start, targets_mask=None, max_cost=10_000):
        INF = 1 << 30
        dist = np.full((ROWS, COLS), INF, dtype=np.int64)
        prev = {}
        sy, sx = start
        dist[sy, sx] = 0
        pq = [(0, sy, sx)]
        door_like = (k_mem == G.DOOR_OPEN) | (k_mem == G.DOOR_CLOSED)
        monster_here = (k_live == G.MONSTER) | (k_live == G.INVIS)
        while pq:
            d, y, x = heapq.heappop(pq)
            if d > dist[y, x]:
                continue
            if targets_mask is not None and targets_mask[y, x]:
                return dist, prev, (y, x)
            if d > max_cost:
                break
            for dy, dx in NEIGH:
                ny, nx = y + dy, x + dx
                if not (0 <= ny < ROWS and 0 <= nx < COLS) or not passable[ny, nx]:
                    continue
                if dy and dx and (door_like[y, x] or door_like[ny, nx]):
                    continue
                c = 1
                km = k_mem[ny, nx]
                if km == G.TRAP:
                    c = 40
                elif km == G.BOULDER or k_live[ny, nx] == G.BOULDER:
                    c = 15
                elif km == G.DOOR_CLOSED:
                    c = 3 if (ny, nx) not in lv.locked else 12
                if monster_here[ny, nx]:
                    c += 4
                if lv.fail[ny, nx]:
                    c += 5 * lv.fail[ny, nx]
                nd = d + c
                if nd < dist[ny, nx]:
                    dist[ny, nx] = nd
                    prev[(ny, nx)] = (y, x)
                    heapq.heappush(pq, (nd, ny, nx))
        return dist, prev, None

    @staticmethod
    def first_step(prev, start, goal):
        cur = goal
        while prev.get(cur) != start:
            cur = prev.get(cur)
            if cur is None:
                return None
        return cur

    def inventory(self):
        items = []
        for letter, ocls, s in zip(self.obs["inv_letters"], self.obs["inv_oclasses"],
                                   self.obs["inv_strs"]):
            if letter == 0:
                break
            items.append((chr(letter), int(ocls), bytes(s).decode("latin1").rstrip("\x00")))
        return items

    # ------------------------------------------------------------ actions
    def move(self, target):
        y, x = self.pos()
        ty, tx = target
        key = DELTA2KEY[(ty - y, tx - x)]
        self.last_move_target = target
        before = (y, x, self.turn())
        lv = self.level()
        if target in lv.locked:
            if self.role_opts.get("shop_fix", True) and any(max(abs(cy - ty), abs(cx - tx)) <= 1
                                                       for cy, cx in getattr(lv, "cfi", ())):
                lv.blocked[ty, tx] = True     # closed shop: kicking the door angers the shopkeeper
                self.shop_kicks_avoided += 1
                return
            if lv.key[0] == 2 or self.law_nearby():
                lv.blocked[ty, tx] = True     # never kick doors in the Mines (Minetown watch)
                return
            self.kick(key)
            return
        if G.KIND[self.obs["glyphs"][target]] == G.MONSTER and self.is_peaceful(target):
            lv.fail[ty, tx] += 1
            self.press("s")
            return
        self.press(key)
        after = (*self.pos(), self.turn())
        if after[:2] == before[:2] and self.cur_key == (self.bl(nh.NLE_BL_DNUM), self.bl(nh.NLE_BL_DLEVEL)):
            lv.fail[ty, tx] += 1
            if lv.fail[ty, tx] >= 6:
                lv.blocked[ty, tx] = True

    def attack(self, target):
        self.cur_act = "fight"
        y, x = self.pos()
        if (target[0] - y, target[1] - x) not in DELTA2KEY:   # we were moved this tick (e.g. teleported)
            self.press("s")
            return
        key = DELTA2KEY[(target[0] - y, target[1] - x)]
        self.last_attack_target = target
        self.last_move_target = None
        self.press("F")
        self.press(key)

    def view_threats(self, lv):
        """Visible hostiles that should stop housekeeping (pickups, equipment, shopping). The SAME list
        gates those steps and the explore goals they consume."""
        vis = self.visible_hostiles(lv)
        if self.shop_visits_on():
            vis = [v for v in vis if v[1] != "shopkeeper"]     # a peaceful shopkeeper is not a threat
        if self.role_opts.get("vis_mobile", True):
            # a monster that cannot move (molds, lichens' kin with speed 0) only matters next to us; otherwise
            # stepping in and out of its line of sight flips this gate and two goals take turns
            y, x = self.pos()
            vis = [(p, n) for p, n in vis if max(abs(p[0] - y), abs(p[1] - x)) <= 1
                   or n not in PM_BY_NAME or PM_BY_NAME[n].mmove > 0]
        if self.role_opts.get("vis_passive", True):
            # no active attack at all (molds, jellies, floating eye, shrieker): harmless unless we hit it, and
            # we never do. Counting it only when adjacent made the gate flip on the square next to it (an item
            # beside a brown mold was a goal from 2 squares away and forbidden on arrival).
            vis = [(p, n) for p, n in vis if n not in PASSIVE_ONLY]
        return vis

    def shopkeeper_in_view(self):
        g = self.obs["glyphs"]
        ys, xs = np.nonzero(G.KIND[g] == G.MONSTER)
        return any(G.monster_name(int(g[a, c])) == "shopkeeper" for a, c in zip(ys, xs))

    def vault_step(self, lv, hostiles):
        """Vault guard protocol: drop the gold, then follow the guard out along his corridor."""
        if self.vault_drop:
            self.vault_drop = False
            self.vault_drops += 1
            self.press("d", expect_prompt=True)
            if "drop" in self.message().lower():
                self.press("$")
            else:
                self.settle()
            return True
        if self.turn() > self.vault_follow_until:
            return False
        if any(n != "guard" for _, n in hostiles):
            return False                      # something else is attacking: fight first
        g = self.obs["glyphs"]
        ys, xs = np.nonzero(G.KIND[g] == G.MONSTER)
        guards = [(int(a), int(b)) for a, b in zip(ys, xs) if G.monster_name(int(g[a, b])) == "guard"]
        y, x = self.pos()
        if not guards:
            if self.guard_trail and self.turn() - self.guard_trail[-1][1] > 20:
                self.vault_follow_until = -1
                return False
        else:
            gp = min(guards, key=lambda p: max(abs(p[0] - y), abs(p[1] - x)))
            if not self.guard_trail or self.guard_trail[-1][0] != gp:
                self.guard_trail.append((gp, self.turn()))
        # step onto the newest square the guard has left that is next to us
        gnow = self.guard_trail[-1][0] if self.guard_trail else None
        for p, _ in reversed(self.guard_trail[:-1]):
            d = (p[0] - y, p[1] - x)
            if p != gnow and d in DELTA2KEY:
                self.vault_moves += 1
                self.cur_act = "vault"
                self.press(DELTA2KEY[d])
                return True
        self.cur_act = "vault"
        self.press("s")
        return True

    def always_avoid(self):
        s = ALWAYS_AVOID
        if self.role_opts.get("eye_avoid", True) and not int(self.last_bl[nh.NLE_BL_CONDITION]) & nh.BL_MASK_BLIND:
            s = s | {"floating eye"}          # its passive gaze paralyses for up to ~127 turns
        return s

    def mark_shop(self, lv, door):
        g = lv.under.copy()
        g[self.pos()] = g[self.pos()]
        corridor = {nh.GLYPH_CMAP_OFF + 21, nh.GLYPH_CMAP_OFF + 22}
        k = G.KIND[g]
        inside_ok = np.isin(k, [G.FLOOR, G.OBJECT, G.GOLD, G.CORPSE, G.TRAP, G.BOULDER]) & \
            ~np.isin(g, list(corridor))
        seen = set()
        q = deque()
        y, x = door
        came = getattr(self, "_cur_pos", None)          # map memory is not updated yet for the door square
        if came == door:
            came = getattr(self, "prev_pos", None)
        if self.role_opts.get("shop_side", True) and came is not None and max(abs(came[0] - y), abs(came[1] - x)) == 1:
            # the greeting comes as we step onto the door from outside: the square we came from is outside.
            # Flooding both sides marked a room beyond the door as shop and left us stuck on the door.
            outside = self._flood(inside_ok, [came]) if inside_ok[came] else {came}
            inside_ok = inside_ok.copy()
            for c in outside:
                inside_ok[c] = False
        for dy, dx in NEIGH:
            ny, nx = y + dy, x + dx
            if 0 <= ny < ROWS and 0 <= nx < COLS and inside_ok[ny, nx]:
                q.append((ny, nx)); seen.add((ny, nx))
        # keep only the side that is a room (more cells); corridor side is excluded by glyph
        while q and len(seen) < 300:
            cy, cx = q.popleft()
            for dy, dx in NEIGH:
                ny, nx = cy + dy, cx + dx
                if 0 <= ny < ROWS and 0 <= nx < COLS and (ny, nx) not in seen and inside_ok[ny, nx]:
                    seen.add((ny, nx)); q.append((ny, nx))
        for c in seen:
            lv.shop[c] = True

    def _flood(self, ok, seeds, cap=300):
        seen = set(seeds)
        q = deque(seeds)
        while q and len(seen) < cap:
            cy, cx = q.popleft()
            for dy, dx in NEIGH:
                ny, nx = cy + dy, cx + dx
                if 0 <= ny < ROWS and 0 <= nx < COLS and (ny, nx) not in seen and ok[ny, nx]:
                    seen.add((ny, nx)); q.append((ny, nx))
        return seen

    def mines_blocked(self):
        """avoid_mines: True/False, or "until_excalibur": lawful long-sword users first look for
        Excalibur in the main dungeon (the Mines have no usable fountains)."""
        if self.avoid_mines == "until_excalibur":
            return int(self.last_bl[nh.NLE_BL_ALIGN]) == 1 and not self.excalibur \
                and self.long_sword() is not None and self.turn() < 8000
        return bool(self.avoid_mines)

    def law_nearby(self):
        g = self.obs["glyphs"]
        ys, xs = np.nonzero(G.KIND[g] == G.MONSTER)
        for yy, xx in zip(ys, xs):
            n = G.monster_name(int(g[yy, xx]))
            if n in ("watchman", "watch captain", "shopkeeper"):
                return True
        return False

    def kick(self, key):
        self.press(4, expect_prompt=True)   # ^D
        if self.obs["misc"][0] or "direction" in self.message().lower():
            self.press(key)
        else:
            self.settle()
        m = " ".join(t for _, t in list(self.messages)[-3:])
        if "crashes open" in m or "shatters" in m or "breaks open" in m:
            self.level().locked.discard(self.last_move_target)

    def pray(self):
        self.cur_act = "pray"
        self.last_pray = self.turn()
        self.prayers += 1
        self.press("#", expect_prompt=True)
        for c in "pray":
            self.raw_step(ord(c))
        self.press(13)

    def drop_heavy(self):
        """Strained or worse (e.g. polymorphed into something small): shed non-essentials."""
        order = (nh.GEM_CLASS, nh.ROCK_CLASS, nh.TOOL_CLASS, nh.WEAPON_CLASS, nh.ARMOR_CLASS,
                 nh.SPBOOK_CLASS, nh.POTION_CLASS, nh.WAND_CLASS, nh.SCROLL_CLASS)
        inv = self.inventory()
        for cls in order:
            for letter, ocls, s in inv:
                if ocls == cls and "being worn" not in s and "weapon in hand" not in s \
                        and (letter, s) not in self.undroppable:
                    self.undroppable.add((letter, s))   # try each item once
                    self.drop_letter(letter)
                    return True
        return False

    def can_pray(self, hunger_emergency=None, weak=False):
        # Weak/Fainting is major trouble (timeout <= 200 suffices); 500 turns after a prayer is ~88% safe.
        # A/B (1000 games): +273 [-1, +553], deaths while fainted 108 -> 76
        if self.god_angry:
            return False
        t = self.turn()
        if self.last_pray is None:
            return t > 300 or (hunger_emergency and t > 100)
        gap = t - self.last_pray
        if hunger_emergency:          # fainting for 200+ turns: death is close, take the risk
            return gap > 300
        if weak:
            return gap > self.role_opts.get("hunger_gap", 500)
        return gap > self.role_opts.get("pray_gap", 1000)

    def engrave_elbereth(self):
        lv = self.level()
        self.press("E", expect_prompt=True)
        if "write with" not in self.message().lower():
            self.settle()
            return False
        self.press("-", expect_prompt=True)
        for _ in range(5):
            m = self.message().lower()
            if self.obs["misc"][0]:          # "Do you want to add to the current engraving?"
                self.press("n", expect_prompt=True)
                continue
            if "--more--" in self.tty_text().lower():
                self.raw_step(13)
                continue
            break
        if self.obs["misc"][1]:
            for c in "Elbereth":
                self.raw_step(ord(c))
            self.press(13)
            lv.elbereth.add(self.pos())
            self.elbereths += 1
            return True
        self.settle()
        return False

    def edible_now(self, s):
        return not re.search(r"\btins?\b", s) and "corpse" not in s and "egg" not in s

    def eat_from_inventory(self):
        for letter, ocls, s in self.inventory():
            if ocls != nh.FOOD_CLASS or not self.edible_now(s):
                continue
            self.press("e", expect_prompt=True)
            for _ in range(3):
                m = self.message().lower()
                if self.obs["misc"][0] and "eat" in m and "here" in m:
                    self.press("n", expect_prompt=True)
                    continue
                break
            if "what do you want to eat" in self.message().lower():
                self.press(letter)
            else:
                self.settle()
            return True
        return False

    def corpse_ok(self, name):
        """Fresh corpse of our own kill: decide from the species' flags."""
        if self.lycanthropy:
            kind = getattr(self, "lyc_kind", None)
            kin = WERE_KIN.get(kind) if kind else set().union(*WERE_KIN.values())
            if name in kin:
                return False                  # eat.c: our own were-kind is cannibalism (Luck, aggravate)
        if self.corpse_policy == "whitelist":
            if name not in SAFE_CORPSES:
                return False
            kin = RACE_KIN.get((self.race or "").lower(), ())
            return not any(k.lower() in name.lower() for k in kin)
        pm = PM_BY_NAME.get(name)
        if pm is None or name in NEVER_EAT:
            return False
        if self.role_opts.get("no_bats", True) and name in ("bat", "giant bat", "vampire bat"):
            return False                      # eat.c: bat corpses stun for 30 (giant bat 60) turns
        f1, f2 = pm.mflags1, pm.mflags2
        if f2 & (M2_UNDEAD | M2_WERE | M2_SHAPESHIFTER):
            return False
        if f2 & RACE_FLAG.get((self.race or "").lower(), 0):
            return False                      # cannibalism
        hp, hunger = self.bl(nh.NLE_BL_HP), self.bl(nh.NLE_BL_HUNGER)
        if f1 & M1_POIS and not f1 & M1_ACID and self.poison_res and self.role_opts.get("pois_eat", True):
            return True                       # poison resistant: a poisonous corpse is ordinary food
        if f1 & (M1_POIS | M1_ACID):          # up to 15 damage: only when starving and healthy
            return hunger >= WEAK and hp > 20
        if self.role == "Monk":
            return hunger >= HUNGRY           # vegetarian conduct: meat only when needed
        return True

    def eat_corpse_here(self):
        self.press("e", expect_prompt=True)
        m = self.message().lower()
        if self.obs["misc"][0] and "corpse here" in m:
            name = re.search(r"there (?:is|are) (?:an? |\d+ )?(.+?) corpses? here", m)
            if name and self.corpse_ok(name.group(1)):
                self.press("y")
                self.corpses_eaten += 1
                return True
            self.press("n", expect_prompt=True)
        if "what do you want to eat" in self.message().lower():
            self.press(27)
        else:
            self.settle()
        return False

    def describe_adjacent(self, pos):
        y, x = self.pos()
        key = DELTA2KEY[(pos[0] - y, pos[1] - x)]
        self.raw_step(ord(";"))
        self.raw_step(ord(key))
        desc = self.top_line()
        self.raw_step(27)
        self.settle()
        return desc

    def is_peaceful(self, pos):
        g = int(self.obs["glyphs"][pos])
        if G.KIND[g] != G.MONSTER:
            return False
        ck = (self.cur_key, g, pos)
        hit = self.hostile_cache.get(ck)
        if hit is not None and self.turn() - hit[1] <= 5:
            return hit[0]
        desc = self.describe_adjacent(pos)
        peaceful = "peaceful" in desc or "tame" in desc
        self.hostile_cache[ck] = (peaceful, self.turn())
        if peaceful:
            self.peaceful_seen += 1
        return peaceful

    def throwables(self):
        out = []
        for letter, ocls, s in self.inventory():
            if "weapon in hand" in s or "(wielded)" in s or " cursed" in s:
                continue
            if ocls == nh.WEAPON_CLASS and any(t in s for t in THROWABLE):
                out.append((0, letter, s))
            elif ocls == nh.GEM_CLASS and any(t in s for t in THROW_STONES):
                out.append((1, letter, s))
        out.sort()
        return [(l, s) for _, l, s in out]

    def ranged_target(self, lv):
        """Floating eyes / gas spores in a clear straight line -> (dir_key, dist, pos)."""
        if not self.avoid_cells:
            return None
        y, x = self.pos()
        g = self.obs["glyphs"]
        k_mem = G.KIND[lv.under]
        for (ty, tx) in self.avoid_cells:
            dy, dx = ty - y, tx - x
            d = max(abs(dy), abs(dx))
            if d == 0 or d > 6 or not (dy == 0 or dx == 0 or abs(dy) == abs(dx)):
                continue
            name = G.monster_name(g[ty, tx])
            if name not in RANGED_TARGETS:
                continue
            if name == "gas spore" and d < 3:
                continue
            sy, sx = (dy > 0) - (dy < 0), (dx > 0) - (dx < 0)
            clear = all(G.PASSABLE[k_mem[y + i * sy, x + i * sx]] and
                        G.KIND[g[y + i * sy, x + i * sx]] not in (G.MONSTER, G.PET, G.BOULDER)
                        for i in range(1, d))
            if clear:
                return DELTA2KEY[(sy, sx)], d, (ty, tx), (sy, sx)
        return None

    def throw(self, letter, key, ray):
        self.press("t", expect_prompt=True)
        if "throw" not in self.message().lower():
            self.settle(); return
        self.press(letter, expect_prompt=True)
        if "direction" in self.message().lower() or self.obs["misc"][0] == 0:
            self.press(key)
        else:
            self.settle()
        self.throws += 1
        self.retrieve.append((self.cur_key, ray, self.turn() + 60))

    def pickup_matching(self, words, no_sale=False, own=False):
        if self.shop_visits_on() and not own:
            lv = self.level()
            if lv.shop[self.pos()] or self.shopkeeper_in_view():
                return                        # in a shop: anything here may be merchandise
        self.press(",", expect_prompt=True)
        tty = self.tty_text()
        if "Pick up what?" not in tty:
            self.settle()
            return
        chosen = 0
        lines = tty.split("\n")
        if own or self.role_opts.get("menu_fix", True):
            lines = self.menu_lines(tty, "Pick up what?")
        for line in lines:
            m = re.match(r"^\s*([a-zA-Z]) - (.*)$", line.strip())
            if m and any(w in m.group(2) for w in words) and not (no_sale and "for sale" in m.group(2)):
                self.raw_step(ord(m.group(1)))
                chosen += 1
        self.raw_step(13 if chosen else 27)
        self.settle()

    @staticmethod
    def menu_lines(tty, header):
        """Lines of a menu: a short menu is drawn over the map from the header's column (tty overlay), so
        each line is cut there; a full-screen menu has the header at column 0 and is unchanged."""
        lines = tty.split("\n")
        hi = next(i for i, l in enumerate(lines) if header in l)
        col = lines[hi].index(header)
        return [l[col:] for l in lines[hi + 1:]]

    def retrieve_goal(self, lv):
        t = self.turn()
        self.retrieve = [r for r in self.retrieve if r[2] > t]
        g = self.obs["glyphs"]
        for key, ray, _ in self.retrieve:
            if key != lv.key:
                continue
            for p in ray:
                if G.KIND[g[p]] == G.OBJECT and nh.glyph_is_object(int(g[p])) and \
                        ord(nh.objclass(nh.glyph_to_obj(int(g[p]))).oc_class) in (nh.WEAPON_CLASS, nh.GEM_CLASS):
                    return p
        return None

    def mark_peaceful_target(self):
        t = self.last_attack_target
        if t is None:
            return
        g = int(self.obs["glyphs"][t])
        lv = self.levels.get(self.cur_key)
        if lv is not None:
            lv.peaceful.add(g)

    # ------------------------------------------------------------ policy
    def adjacent_hostiles(self, lv):
        y, x = self.pos()
        g = self.obs["glyphs"]
        out = []
        self.avoid_cells = []
        for yy in range(max(0, y - 7), min(ROWS, y + 8)):
            for xx in range(max(0, x - 7), min(COLS, x + 8)):
                k = G.KIND[g[yy, xx]]
                if k == G.MONSTER:
                    name = G.monster_name(g[yy, xx])
                    if self.never_melee(name) and not (lv.desperate and name not in self.always_avoid()) \
                            and not self.spore_ok(name):
                        self.avoid_cells.append((yy, xx))
        for dy, dx in NEIGH:
            ny, nx = y + dy, x + dx
            if not (0 <= ny < ROWS and 0 <= nx < COLS):
                continue
            gg = int(g[ny, nx])
            k = G.KIND[gg]
            if k == G.MONSTER and gg not in lv.peaceful:
                name = G.monster_name(gg)
                if self.never_melee(name) and not (lv.desperate and name not in self.always_avoid()
                                                and self.bl(nh.NLE_BL_HP) * 10 >= self.bl(nh.NLE_BL_HPMAX) * 9) \
                        and not self.spore_ok(name):
                    continue
                if self.is_peaceful((ny, nx)):
                    continue
                out.append(((ny, nx), name))
            elif k == G.INVIS and (ny, nx):
                out.append(((ny, nx), "invisible"))
        return out

    def never_melee(self, name):
        """passive_nomelee: one rule from monster data instead of the hand list -- don't hit what has only a
        passive attack (it never hurts us otherwise); desperate (stuck) still may."""
        if name in ("cockatrice", "chickatrice") and self.role_opts.get("cocka_melee", True) \
                and any("weapon in hand" in s for _, _, s in self.inventory()):
            return False       # hitting it with a wielded weapon is safe; standing by while it touches us is not
        if name in ("brown mold", "blue jelly") and self.role == "Valkyrie" and self.role_opts.get("cold_melee", False):
            return False       # their passive is cold only, and Valkyries are born cold resistant
        return name in NEVER_MELEE or (self.role_opts.get("passive_nomelee", True) and name in PASSIVE_DMG)

    def spore_ok(self, name):
        # gas spore explosion is 4d6 (max 24): meleeing it is safe above that
        return name == "gas spore" and self.bl(nh.NLE_BL_HP) >= 25 and self.role_opts.get("spore_melee", True)

    def visible_hostiles(self, lv):
        g = self.obs["glyphs"]
        ys, xs = np.nonzero(G.KIND[g] == G.MONSTER)
        py, px = self.pos()
        res = []
        for yy, xx in zip(ys, xs):
            if (yy, xx) == (py, px):
                continue
            gg = int(g[yy, xx])
            if gg in lv.peaceful:
                continue
            res.append(((int(yy), int(xx)), G.monster_name(gg)))
        return res

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
        if self.role_opts.get("engulf_fix", True):
            ring = gg[max(0, y - 1):y + 2, max(0, x - 1):x + 2]
            engulfed = int(((ring >= nh.GLYPH_SWALLOW_OFF) & (ring < nh.GLYPH_WARNING_OFF)).sum()) >= 5
        else:
            engulfed = G.KIND[gg[y, x]] == G.EFFECT and nh.GLYPH_SWALLOW_OFF <= gg[y, x] < nh.GLYPH_WARNING_OFF
        if engulfed:
            self.last_attack_target = None
            self.press("F"); self.press("h")
            return

        # emergencies
        low = hp <= 5 or hp * 7 <= maxhp
        if (low or hp * self.role_opts.get("pray_div", 7) <= maxhp) and self.can_pray():
            self.pray(); return
        if hunger >= FAINTING:
            if self.faint_since is None:
                self.faint_since = t
        else:
            self.faint_since = None
        if hunger >= WEAK and self.can_pray(hunger_emergency=(
                self.faint_since is not None and t - self.faint_since > self.role_opts.get("faint_wait", 200)), weak=True):
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

        if self.use_roles and (self.role_setup() or self.healer_early_quaff()):
            return
        if self.use_enhance:
            self.enhance_step()
        hostiles = self.adjacent_hostiles(lv)
        cond2 = int(self.last_bl[nh.NLE_BL_CONDITION])
        if cond2 & (nh.BL_MASK_STUN | nh.BL_MASK_CONF) and self.role_opts.get("stun_wait", True):
            # moves and attacks go in random directions while stunned/confused
            only_passive = all(n in PASSIVE_MOLDS for _, n in hostiles)
            if not hostiles or only_passive:
                self.stun_waits += 1
                self.press("s")
                return
        if self.role_opts.get("vault_guard", True) and self.vault_step(lv, hostiles):
            return
        if cond2 & nh.BL_MASK_BLIND and self.role_opts.get("blind_wait", True) and not hostiles \
                and self.bl(nh.NLE_BL_HUNGER) < HUNGRY:
            self.blind_waits += 1             # wandering blind walks into things we can't see
            self.press("s")
            return
        if self.use_abilities and self.heal_step(hostiles):
            return
        if hostiles and low and not self.can_pray() and self.role_opts.get("dig_escape", True) and self.dig_down(lv, "escape"):
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
        if self.role_opts.get("dip_prep", False) and self.dip_flee_step(lv, hostiles):
            return
        if self.role_opts.get("flee_stairs", False) and self.flee_stairs_step(lv, hostiles):
            return
        if self.use_tactics and self.tactical_step(lv, hostiles):
            return
        if self.role_opts.get("ward", False) and self.ward_step(lv, hostiles):
            return
        if self.elb_step(lv, hostiles):
            return
        if self.nymph_step(lv, hostiles):
            return
        if not hostiles and self.weapon_check():
            return
        if self.use_roles and (self.camera_step(lv, hostiles) or self.wand_step(lv, hostiles)):
            return
        if self.use_abilities and self.ranged_step(lv, hostiles):
            return
        if hostiles:
            if hp < maxhp * self.elb_frac and (y, x) not in lv.elbereth and self.elbereths < 40:
                if all(self.respects_elbereth(n, p) for p, n in hostiles):
                    self.engrave_elbereth()
                    return
            if (y, x) in lv.elbereth and hp < maxhp * self.elb_frac and all(
                    self.respects_elbereth(n, p) for p, n in hostiles):
                self.press("s")   # rest on Elbereth instead of attacking (attacking erases it)
                return
            # attack the weakest-looking (lowest level) target
            target = min(hostiles, key=lambda t: self.mon_level(t[0]))[0]
            if self.role_opts.get("focus", True) and len(hostiles) > 1:
                target = self.focus_target(hostiles, target)
            self.attack(target)
            return
        if self.role_opts.get("hunt_shooter", True) and self.hunt_step(lv):
            return
        if (y, x) in lv.elbereth and hp * 2 < maxhp and not self.rthreat_active():
            self.cur_act = "rest"
            self.press("2"); self.press("0"); self.press("s")
            return

        # ranged attacks on things we refuse to melee
        rt = self.ranged_target(lv)
        if rt:
            th = self.throwables()
            if th:
                key, d, tpos, (sy, sx) = rt
                ray = [(y + i * sy, x + i * sx) for i in range(1, 10)
                       if 0 <= y + i * sy < ROWS and 0 <= x + i * sx < COLS]
                self.last_attack_target = tpos
                self.throw(th[0][0], key, ray)
                return

        # missiles lying where we stand (our own thrown ones, or new ammo for missile roles)
        sh = self.seen_here
        if sh and sh[0] == self.turn() and sh[1] == (y, x) and (self.throws or self.role in ("Tourist", "Rogue", "Ranger")) \
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

        vis = self.view_threats(lv)
        if (self.use_armor or self.use_food) and not vis:
            if self.need_pay:
                self.need_pay = False
                self.pay()
                return
            if self.use_armor and self.shop_step(lv):
                return
            if self.excal_step(lv):
                return
            if self.wand_id_step(lv):
                return
            if self.loot_step(lv) or self.kill_loot_step(lv):
                return
            if self.role_opts.get("read_good", True) and not self.role_opts.get("scroll_id") and self.read_good_scroll():
                return
            if self.role_opts.get("scroll_id") and self.scroll_step(lv):
                return
            if self.use_armor and self.equip_step(lv):
                return
            if (G.ARMOR_GLYPH[lv.under[y, x]] or G.FOOD_GLYPH[lv.under[y, x]]
                    or self.carry_glyph(lv.under[y, x])) and (y, x) not in self.inspected.get(lv.key, ()) \
                    and not lv.shop[y, x]:
                if self.armor_pickup_here(lv):
                    return
        elif (self.use_armor or self.use_food) and self.role_opts.get("pickup_calm", True) and self.items_gate(lv):
            # monsters in view but none in reach and nobody shooting: still collect what lies here
            if self.loot_step(lv) or self.kill_loot_step(lv):
                return
            if (G.ARMOR_GLYPH[lv.under[y, x]] or G.FOOD_GLYPH[lv.under[y, x]]
                    or self.carry_glyph(lv.under[y, x])) and (y, x) not in self.inspected.get(lv.key, ()) \
                    and not lv.shop[y, x]:
                if self.armor_pickup_here(lv):
                    return

        # rest if hurt and nothing around
        if hp < maxhp * self.rest_frac and not vis:
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

    def respects_elbereth(self, name, pos):
        if name == "invisible" or name in ELBERETH_IGNORERS:
            return False
        g = int(self.obs["glyphs"][pos])
        m = nh.glyph_to_mon(g)
        if 0 <= m < nh.NUMMONS:
            let = nh.permonst(m).mlet
            if let == HUMAN_MLET or let == MINOTAUR_MLET:
                return False
        return True

    def mon_level(self, pos):
        g = int(self.obs["glyphs"][pos])
        m = nh.glyph_to_mon(g)
        return nh.permonst(m).mlevel if 0 <= m < nh.NUMMONS else 0

    def corpse_goal(self, lv):
        t = self.turn()
        self.kills = [k for k in self.kills if t - k[0] < 40]
        best = None
        for kt, name, pos, key in self.kills:
            if key != lv.key or not self.corpse_ok(name):
                continue
            if G.KIND[lv.under[pos]] != G.CORPSE:
                continue
            d = max(abs(pos[0] - self.pos()[0]), abs(pos[1] - self.pos()[1]))
            if d <= 8 and (best is None or d < best[0]):
                best = (d, pos)
        return best[1] if best else None

    def go_toward(self, lv, goal):
        k_mem, k_live = self.kind_grid(lv)
        p = self.passable_grid(lv, k_mem, k_live)
        mask = np.zeros((ROWS, COLS), dtype=bool)
        mask[goal] = True
        start = self.pos()
        dist, prev, reached = self.dijkstra(lv, k_mem, k_live, p, start, mask)
        if reached is None:
            return False
        step = self.first_step(prev, start, reached)
        if step is None:
            return False
        self.move(step)
        return True

    def explore(self, lv):
        self.cur_act = "explore"
        k_mem, k_live = self.kind_grid(lv)
        passable = self.passable_grid(lv, k_mem, k_live)
        start = self.pos()
        y, x = start

        unknown = (k_mem == G.UNKNOWN) & ~lv.near
        dil = np.zeros_like(unknown)
        for dy, dx in NEIGH:
            dil[max(0, dy):ROWS + min(0, dy), max(0, dx):COLS + min(0, dx)] |= \
                unknown[max(0, -dy):ROWS + min(0, -dy), max(0, -dx):COLS + min(0, -dx)]
        frontier = passable & dil & (lv.visited == 0)
        dt = self.door_target_mask(lv, k_mem, passable)
        if dt is not None:
            frontier = frontier | dt
        if self.role_opts.get("door_targets") == "shop" and not getattr(lv, "shop_type", None) \
                and start in getattr(lv, "shk_doors", ()) and k_mem[start] in (G.DOOR_OPEN, G.DOOR_CLOSED, G.DOORWAY) \
                and lv.__dict__.get("shk_wait", 0) < 15:
            g = self.obs["glyphs"]
            if any(0 <= y + dy < ROWS and 0 <= x + dx < COLS and G.KIND[g[y + dy, x + dx]] == G.MONSTER
                   and G.monster_name(int(g[y + dy, x + dx])) == "shopkeeper" for dy, dx in NEIGH):
                lv.shk_wait = lv.__dict__.get("shk_wait", 0) + 1
                self.cur_act = "shopdoor"
                self.press("s")               # in the doorway, in line with him: he steps aside (shk.c shk_move)
                return
        gold = (k_mem == G.GOLD) & passable
        for p in lv.gold_tried:
            gold[p] = False
        downstairs = k_mem == G.DOWNSTAIR
        on_level = self.turn() - (lv.entered_turn or 0)
        if lv.avoid_down and on_level < self.role_opts.get("mines_after", 3000) and self.mines_blocked():
            for p in lv.avoid_down:
                downstairs[p] = False
        want_down = downstairs.any() and self.should_descend(lv, frontier, on_level) and not self.excal_holds(lv)
        if want_down and self.role_opts.get("items_first", True) \
                and on_level <= self.role_opts.get("descend_after", 2000):
            # explored, but something worth having still lies here: the same goals the target step below
            # will walk to (gold, armor/food/carry piles not yet inspected), so holding off is never idle
            stuff = gold & ~lv.shop if self.shop_visits_on() else gold.copy()
            ok = self.items_gate(lv) if self.role_opts.get("item_consistent", True) else True
            im = passable & ~lv.shop if self.role_opts.get("item_consistent", True) else passable
            if self.role_opts.get("calm_target", False):
                im = im & ~self.near_hostile_mask(lv)
            if ok and (self.use_armor or self.use_food):
                stuff |= self.armor_targets(lv, G) & im
                ct = self.carry_targets(lv)
                if ct is not None:
                    stuff |= ct & im
            if ok and self.role_opts.get("scroll_id"):
                stuff |= self.scroll_targets(lv) & im
            stuff[y, x] = False
            if stuff.any():
                _, _, got = self.dijkstra(lv, k_mem, k_live, passable, start, stuff)
                if got is not None and got != start:
                    want_down = False
                    self.items_first_holds += 1

        if want_down:
            if downstairs[y, x]:
                if self.use_pet and self.pet_wait_before_stairs():
                    self.press("s"); return
                self.descents += 1
                self.took_stairs = True
                self.press(">")
                return
            dist, prev, reached = self.dijkstra(lv, k_mem, k_live, passable, start, downstairs)
            if reached is not None:
                step = self.first_step(prev, start, reached)
                if step:
                    self.move(step)
                    return

        if self.shop_visits_on():
            gold = gold & ~lv.shop                     # shop gold belongs to the shopkeeper
        targets = frontier | gold
        items_ok = True
        item_mask = passable
        if self.role_opts.get("item_consistent", True):
            # an item square is only a goal if the step that inspects it (and so removes the goal) will run:
            # that step needs no hostile in view and skips shop squares
            items_ok = self.items_gate(lv)
            item_mask = passable & ~lv.shop
            if self.role_opts.get("calm_target", False):
                # pickup_calm judges where we stand; an item next to a hostile would take us into its reach
                item_mask = item_mask & ~self.near_hostile_mask(lv)
        if items_ok and self.role_opts.get("scroll_id"):
            targets = targets | (self.scroll_targets(lv) & item_mask)
        if items_ok and (self.use_armor or self.use_food):
            targets = targets | (self.armor_targets(lv, G) & item_mask)
            ct = self.carry_targets(lv)
            if ct is not None:
                targets = targets | (ct & item_mask)
        if targets.any():
            dist, prev, reached = self.dijkstra(lv, k_mem, k_live, passable, start, targets)
            if reached is not None and reached != start:
                step = self.first_step(prev, start, reached)
                if step:
                    self.move(step)
                    return
            if reached == start:
                lv.visited[start] += 1

        if downstairs.any() and not self.excal_holds(lv):
            if downstairs[y, x]:
                if self.use_pet and self.pet_wait_before_stairs():
                    self.press("s"); return
                self.descents += 1
                self.took_stairs = True
                self.press(">")
                return
            dist, prev, reached = self.dijkstra(lv, k_mem, k_live, passable, start, downstairs)
            if reached is not None:
                step = self.first_step(prev, start, reached)
                if step:
                    self.move(step)
                    return

        # stuck for good on this level: a wand of digging makes the way down
        if lv.desperate and self.dig_down(lv, "stuck"):
            return
        # nothing left: a monster we won't melee may be all that separates us from the rest of the level
        if self.role_opts.get("unblock", True) and self.unblock_step(lv, k_mem, k_live, passable, frontier | downstairs):
            return
        # nothing left: map the level if we can, else search for hidden passages
        if self.use_abilities and self.magic_map_step(lv):
            return
        self.search_mode(lv, k_mem, k_live, passable)

    def expendables(self):
        """Inventory items worth less than a way through: missiles first, then gems/rocks, spare weapons,
        unworn armor, ordinary tools."""
        out = [(0, l, s) for l, s in self.throwables()]
        for letter, ocls, s in self.inventory():
            if any(w in s for w in ("weapon in hand", "(wielded", "being worn", "(in use", " cursed", "alternate weapon")):
                continue
            if ocls == nh.GEM_CLASS:
                out.append((1, letter, s))
            elif ocls == nh.WEAPON_CLASS:
                out.append((2, letter, s))
            elif ocls == nh.ARMOR_CLASS:
                out.append((3, letter, s))
            elif ocls == nh.TOOL_CLASS and not any(w in s for w in ("pick-axe", "mattock", "unicorn horn", "key", "lock pick", "bag", "sack")):
                out.append((4, letter, s))
        out.sort()
        seen, res = set(), []
        for _, l, s in out:
            if l not in seen:
                seen.add(l); res.append((l, s))
        return res

    def unblock_step(self, lv, k_mem, k_live, passable, goal):
        """Explore/descend goals are reachable only through squares held by monsters we refuse to melee
        (a floating eye in a doorway, a mold in a corridor): throw whatever is expendable at the blocker;
        stuck long with nothing to throw, hit a floating eye anyway (paralysis beats starving)."""
        if not self.avoid_cells:
            return False
        p2 = passable.copy()
        for c in self.avoid_cells:
            p2[c] = bool(G.PASSABLE[k_mem[c]]) or k_mem[c] == G.DOORWAY
        start = self.pos()
        blocker = None
        if goal.any():
            dist, prev, reached = self.dijkstra(lv, k_mem, k_live, p2, start, goal)
            if reached is not None:
                path, c = [], reached
                while c != start:
                    path.append(c)
                    c = prev[c]
                blocker = next((c for c in reversed(path) if c in self.avoid_cells), None)
        if blocker is None:
            # no goal left, but we are shut in a pocket: most of the known level lies past the blocker
            d1, _, _ = self.dijkstra(lv, k_mem, k_live, passable, start, None)
            d2, _, _ = self.dijkstra(lv, k_mem, k_live, p2, start, None)
            r1, r2 = d1 < (1 << 29), d2 < (1 << 29)
            if r1.sum() * 2 >= r2.sum():
                return False
            near = [c for c in self.avoid_cells if r2[c] and any(
                0 <= c[0] + a < ROWS and 0 <= c[1] + b < COLS and r1[c[0] + a, c[1] + b] for a, b in NEIGH)]
            if not near:
                return False
            blocker = min(near, key=lambda c: d2[c])
        name = G.monster_name(int(self.obs["glyphs"][blocker]))
        self.unblocks += 1
        y, x = start
        dy, dx = blocker[0] - y, blocker[1] - x
        d = max(abs(dy), abs(dx))
        if d <= 6 and (dy == 0 or dx == 0 or abs(dy) == abs(dx)) and not (name == "gas spore" and d < 3):
            sy, sx = (dy > 0) - (dy < 0), (dx > 0) - (dx < 0)
            clear = all(G.PASSABLE[k_mem[y + i * sy, x + i * sx]] and
                        G.KIND[self.obs["glyphs"][y + i * sy, x + i * sx]] not in (G.MONSTER, G.PET, G.BOULDER)
                        for i in range(1, d))
            ex = self.expendables() if clear else []
            if ex:
                ray = [(y + i * sy, x + i * sx) for i in range(1, 10) if 0 <= y + i * sy < ROWS and 0 <= x + i * sx < COLS]
                self.cur_act = "unblock"
                self.last_attack_target = blocker
                self.unblock_throws += 1
                self.throw(ex[0][0], DELTA2KEY[(sy, sx)], ray)
                return True
            since = lv.__dict__.setdefault("unblock_since", self.turn())
            wait = self.role_opts.get("unblock_wait", None)
            if d == 1 and name == "floating eye" and (lv.desperate or (wait is not None and self.turn() - since > wait)):
                self.unblock_melee += 1
                self.attack(blocker)
                return True
        # get next to it (any adjacent square is in line)
        if d > 1:
            adj = np.zeros((ROWS, COLS), dtype=bool)
            for ny, nx in ((blocker[0] + a, blocker[1] + b) for a, b in NEIGH):
                if 0 <= ny < ROWS and 0 <= nx < COLS and passable[ny, nx]:
                    adj[ny, nx] = True
            if adj.any():
                dist, prev, r2 = self.dijkstra(lv, k_mem, k_live, passable, start, adj)
                if r2 is not None and r2 != start:
                    step = self.first_step(prev, start, r2)
                    if step:
                        self.cur_act = "unblock"
                        self.move(step)
                        return True
        return False

    def ward_step(self, lv, hostiles):
        """ward: a lycanthrope (either form: the @ form can turn into the infecting animal at any moment) or an
        incubus/succubus within ward_r squares (default 5) -> stand on Elbereth (write it if the square has none)
        and wait there while it is in view, plus ward_linger turns (default 5) after it was last seen. Same rule
        for every such monster: fight normally if something that ignores Elbereth (e.g. a were in @ form) is
        next to us; give up after 150 turns. Version 1 = ward_r=2, ward_linger=0, ward_human=False (animal form
        only)."""
        g = self.obs["glyphs"]
        y, x = self.pos()
        r = self.role_opts.get("ward_r", 5)
        t = self.turn()
        danger = False
        for p, n in self.visible_hostiles(lv):
            if max(abs(p[0] - y), abs(p[1] - x)) > r:
                continue
            m = nh.glyph_to_mon(int(g[p]))
            if not (0 <= m < nh.NUMMONS):
                continue
            if n in ("incubus", "succubus") or (n.startswith("were") and (self.role_opts.get("ward_human", True)
                                                                        or nh.permonst(m).mlet != HUMAN_MLET)):
                danger = True
                break
        on_elb = (y, x) in lv.elbereth and self.read_engraving() == "Elbereth"
        if danger:
            self.ward_seen = t
        elif not (on_elb and t - getattr(self, "ward_seen", -99) <= self.role_opts.get("ward_linger", 5)):
            self.ward_since = None
            return False
        if getattr(self, "ward_since", None) is None:
            self.ward_since = t
        if t - self.ward_since > 150:
            return False
        if any(not self.respects_elbereth(n, p) for p, n in hostiles):
            return False
        if not on_elb:
            if not self.can_engrave_here(lv):
                return False
            self.ward_writes += 1
            self.cur_act = "ward"
            self.engrave_elbereth()
            return True
        self.ward_waits += 1
        self.cur_act = "ward"
        self.press("s")
        return True

    def near_hostile_mask(self, lv, r=1):
        """Squares within r steps of a visible hostile: an item there is reached only by stepping into its reach."""
        m = np.zeros((ROWS, COLS), dtype=bool)
        for (yy, xx), _ in self.visible_hostiles(lv):
            m[max(0, yy - r):yy + r + 1, max(0, xx - r):xx + r + 1] = True
        return m

    def items_gate(self, lv):
        """May item goals be pursued / piles inspected now? Default: no hostile in view. pickup_calm: not in
        combat -- nothing in melee range and not shot at in the last 5 turns. Goals and the inspecting step
        use this same test."""
        if self.role_opts.get("pickup_calm", True):
            return not self.adjacent_hostiles(lv) and self.turn() - getattr(self, "last_shot_turn", -99) > 5
        return not self.view_threats(lv)

    def hunt_step(self, lv):
        """hunt_shooter: something hit us from range and nothing is next to us -> close in on the likeliest
        shooter: a visible hostile of the named kind, else one standing on a line with us within 8 squares
        (monsters only fire when lined up, BOLT_LIM). Pursue it for at most 25 turns, while HP >= 40%."""
        t = self.turn()
        y, x = self.pos()
        hp, maxhp = self.bl(nh.NLE_BL_HP), self.bl(nh.NLE_BL_HPMAX)
        if hp < maxhp * 0.4:
            self.hunt = None
            return False
        ev = getattr(self, "shot_event", None)
        dist = lambda p: max(abs(p[0] - y), abs(p[1] - x))
        if ev and t - ev[0] <= 2:
            self.shot_event = None
            vis = self.visible_hostiles(lv)
            lined = [(p, n) for p, n in vis if dist(p) <= 8 and (p[0] == y or p[1] == x or abs(p[0] - y) == abs(p[1] - x))]
            cands = lined
            if ev[1]:
                cands = [c for c in lined if c[1] == ev[1]] or [c for c in vis if c[1] == ev[1]] or lined
            if cands:
                p, n = min(cands, key=lambda c: dist(c[0]))
                self.hunt = {"key": lv.key, "pos": p, "name": n, "until": t + 25, "lost": 0}
                self.hunts += 1
        h = getattr(self, "hunt", None)
        if not h:
            return False
        if h["key"] != lv.key or t > h["until"]:
            self.hunt = None
            return False
        same = [p for p, n in self.visible_hostiles(lv) if n == h["name"]]
        if same:
            h["pos"] = min(same, key=lambda p: max(abs(p[0] - h["pos"][0]), abs(p[1] - h["pos"][1])))
            h["lost"] = 0
        else:
            h["lost"] += 1
            if h["lost"] > 5:
                self.hunt = None
                return False
        if dist(h["pos"]) <= 1:
            return False                       # next to it: the fight step takes over
        k_mem, k_live = self.kind_grid(lv)
        passable = self.passable_grid(lv, k_mem, k_live)
        if self.role_opts.get("hunt_offline", True):
            # among the steps that get as close as any, prefer one off the target's lines (it fires only when
            # lined up); distances from the target over the same grid
            ty, tx = h["pos"]
            p2 = passable.copy()
            p2[ty, tx] = True
            dmap, _, _ = self.dijkstra(lv, k_mem, k_live, p2, (ty, tx), None, max_cost=80)
            INF = 1 << 29
            if dmap[y, x] < INF:
                cands = []
                for dy, dx in NEIGH:
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < ROWS and 0 <= nx < COLS and passable[ny, nx] and dmap[ny, nx] < dmap[y, x] \
                            and G.KIND[self.obs["glyphs"][ny, nx]] not in (G.MONSTER, G.PET) \
                            and not ((k_mem[y, x] in (G.DOOR_OPEN, G.DOOR_CLOSED) or k_mem[ny, nx] in (G.DOOR_OPEN, G.DOOR_CLOSED)) and dy and dx):
                        cands.append((int(dmap[ny, nx]), (ny, nx)))
                if cands:
                    best = min(c[0] for c in cands)
                    pool = [p for d, p in cands if d == best]
                    lined = lambda p: p[0] == ty or p[1] == tx or abs(p[0] - ty) == abs(p[1] - tx)
                    off = [p for p in pool if not lined(p)]
                    self.cur_act = "hunt"
                    self.hunt_steps += 1
                    self.hunt_offline_steps = getattr(self, "hunt_offline_steps", 0) + bool(off and any(lined(p) for p in pool))
                    self.move((off or pool)[0])
                    return True
        adj = np.zeros((ROWS, COLS), dtype=bool)
        for dy, dx in NEIGH:
            ny, nx = h["pos"][0] + dy, h["pos"][1] + dx
            if 0 <= ny < ROWS and 0 <= nx < COLS and passable[ny, nx]:
                adj[ny, nx] = True
        if adj.any():
            _, prev, got = self.dijkstra(lv, k_mem, k_live, passable, (y, x), adj, max_cost=60)
            if got is not None and got != (y, x):
                step = self.first_step(prev, (y, x), got)
                if step:
                    self.cur_act = "hunt"
                    self.hunt_steps += 1
                    self.move(step)
                    return True
        self.hunt = None
        return False

    def door_target_mask(self, lv, k_mem, passable):
        """door_targets: doors we have not stood on count as unexplored ground (a lit room seen whole from
        outside leaves its door off the frontier, so a shop could be walked past).
          "all"  -- every door/doorway;  "shop" -- doors next to a shopkeeper seen on this level, until greeted.
        Each door is a goal for at most door_ttl turns from when it first became one: a door we can't get onto
        (a monster in it, a misread) expires instead of holding exploration forever."""
        mode = self.role_opts.get("door_targets")
        if not mode:
            return None
        t = self.turn()
        doors = (k_mem == G.DOOR_OPEN) | (k_mem == G.DOOR_CLOSED) | (k_mem == G.DOORWAY)
        if mode == "shop":
            if getattr(lv, "shop_type", None):
                return None                          # greeted: we have been in
            sd = lv.__dict__.setdefault("shk_doors", set())
            g = self.obs["glyphs"]
            ys, xs = np.nonzero(G.KIND[g] == G.MONSTER)
            for a, c in zip(ys, xs):
                if G.monster_name(int(g[a, c])) != "shopkeeper":
                    continue
                for dy, dx in NEIGH:
                    ny, nx = int(a) + dy, int(c) + dx
                    if 0 <= ny < ROWS and 0 <= nx < COLS and doors[ny, nx]:
                        # the door and the shopkeeper's post just inside it: standing in the doorway is not
                        # entering (no greeting); he steps aside when we wait there in line with him
                        sd.add((ny, nx))
                        sd.add((int(a), int(c)))
            cand = np.zeros_like(doors)
            for p in sd:
                cand[p] = True
        else:
            cand = doors.copy()
        cand &= (lv.visited == 0) & passable
        if not cand.any():
            return None
        since = lv.__dict__.setdefault("door_since", {})
        ttl = self.role_opts.get("door_ttl", 300)
        for p in zip(*np.nonzero(cand)):
            p = (int(p[0]), int(p[1]))
            if t - since.setdefault(p, t) > ttl:
                cand[p] = False
        return cand

    def should_descend(self, lv, frontier, on_level):
        if self.bl(nh.NLE_BL_HP) < self.bl(nh.NLE_BL_HPMAX) * self.descend_hp:
            return False
        if self.descend_policy == "dive":
            return True
        xl = self.bl(nh.NLE_BL_XP)
        depth = self.bl(nh.NLE_BL_DEPTH)
        if self.descend_policy == "explore":
            dd = self.role_opts.get("dive_depth", None)
            if dd is not None and depth >= dd and self.bl(nh.NLE_BL_HP) >= self.bl(nh.NLE_BL_HPMAX) * 0.6:
                return True                    # deep: 50 points a level, 1000 past DL20, and richer kills below
            return not frontier.any() or on_level > self.role_opts.get("descend_after", 2000)
        if self.descend_policy == "careful":
            # explore fully; only go deeper when experienced enough
            if depth >= xl + 3 and on_level < 4000:
                return False
            return not frontier.any() or on_level > 2000
        return not frontier.any()

    def search_mode(self, lv, k_mem, k_live, passable):
        self.cur_act = "search"
        start = self.pos()
        dist, prev, _ = self.dijkstra(lv, k_mem, k_live, passable, start, None)
        reach = dist < (1 << 30)
        wallish = (k_mem == G.WALL) | (k_mem == G.UNKNOWN)
        cnt = np.zeros((ROWS, COLS), dtype=np.int32)
        for dy, dx in NEIGH:
            cnt[max(0, dy):ROWS + min(0, dy), max(0, dx):COLS + min(0, dx)] += \
                wallish[max(0, -dy):ROWS + min(0, -dy), max(0, -dx):COLS + min(0, -dx)]
        wall_term = cnt * 10.0
        if self.role_opts.get("search_blank", False):
            # weight by how much of the map around is still blank: hidden passages lead to undiscovered
            # rooms, which need room; the 8-neighbour count alone rates every corridor square alike
            blank = (k_mem == G.UNKNOWN) & ~lv.near
            blank[:, 0] = False
            ry, rx = 4, 9
            cs = np.zeros((ROWS + 1, COLS + 1), dtype=np.int32)
            cs[1:, 1:] = np.cumsum(np.cumsum(blank, axis=0), axis=1)
            yy, xx = np.mgrid[0:ROWS, 0:COLS]
            y0, y1 = np.clip(yy - ry, 0, ROWS), np.clip(yy + ry + 1, 0, ROWS)
            x0, x1 = np.clip(xx - rx, 0, COLS), np.clip(xx + rx + 1, 0, COLS)
            mass = cs[y1, x1] - cs[y0, x1] - cs[y1, x0] + cs[y0, x0]
            wall_term = wall_term * (0.4 + 1.6 * mass / ((2 * ry + 1) * (2 * rx + 1)))
        score = np.where(reach & passable, wall_term - lv.searched * 2.0 - np.minimum(dist, 500) * 0.3, -1e9)
        # dead-end corridors are prime spots
        goal = getattr(lv, "search_goal", None) if self.role_opts.get("search_goal", True) else None
        if goal is not None and reach[goal] and passable[goal]:
            best = goal                       # committed: the distance term must not re-pick it every step
        else:
            best = np.unravel_index(np.argmax(score), score.shape)
            if score[best] <= -1e8:
                self.press("s")
                return
            best = (int(best[0]), int(best[1]))
            lv.search_goal = best
        if best == start:
            lv.search_goal = None             # searched here: choose afresh next time
            lv.searched[start] += 10
            self.press("1"); self.press("0"); self.press("s")
            return
        step = self.first_step(prev, start, best)
        if step:
            self.move(step)
        else:
            self.press("s")

    # ------------------------------------------------------------ main
    def run(self):
        if self.seed is not None:
            self.env.unwrapped.seed( core=self.seed, disp=self.seed, reseed=False)
        obs, _ = self.env.reset()
        self.obs = obs
        self.last_bl = obs["blstats"].copy()
        self.hostile_cache = {}
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
        self.tactics_init()
        self.abilities_init()
        self.roles_init()
        self.class_init()
        self.excal_init()
        self.valk_init()
        self.valk2_init()
        self.elb2_init()
        self.shop_init()
        self.scroll_init()
        self.armor_id_init()
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
            "casts": self.casts,
            "quaffs": self.quaffs,
            "maps_read": self.maps_read,
            "pet_waited": self.pet_waited_total,
            "missiles": self.missiles,
            "zaps": self.zaps,
            "thefts": self.thefts,
            "elb_engraves": self.elb_engraves,
            "elb_misspelled": self.elb_misspelled,
            "elb_fail": getattr(self, "elb_fail", 0),
            "focus_calls": self.focus_calls, "focus_picks": self.focus_picks,
            "scrolls": dict(self.scroll_stats), "price_memory": dict(self.price_stats, appearances=self.price_report()),

            "blind_waits": self.blind_waits, "poison_res": self.poison_res, "shop_kicks_avoided": self.shop_kicks_avoided,

            "elb_fail_msgs": getattr(self, "elb_fail_msgs", [])[:5],
            "elb_rewrites": getattr(self, "elb_rewrites", 0),
            "elb_blocked": dict(getattr(self, "elb_block_reasons", {})),
            "carry": dict(self.carry_stats),
            "armor_id": dict(self.armor_id_stats,
                             random_worn=[e for e in self.equip_events if e[1] == "wear" and e[2] in RANDOM_APPEARANCE]),
            "elb_only_c": getattr(self, "elb_only_c", 0),
            "rthreat_events": dict(getattr(self, "rthreat_events", {})),
            "rthreat_msgs": getattr(self, "rthreat_msgs", []),
            "elb_turns": self.elb_turns,
            "elb_exits": dict(self.elb_exits),
            "kill_loot_checks": self.kill_loot_checks,
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
            "flashes": self.flashes,
            "early_quaffs": self.early_quaffs,
            "fires": self.fires,
            "ammo_pickups": self.ammo_pickups,
            "pet_last_seen": self.pet_last_seen,
            "time_by": self.time_by,
            "levels_seen": len(self.levels),
            "level_stats": [dict(key=list(k), turns=v.turns_here, search=v.search_turns,
                                 down_known=bool((G.KIND[v.under] == G.DOWNSTAIR).any()),
                                 mines_branch=bool(v.avoid_down), desperate=v.desperate,
                                 seen=int(v.seen.sum()))
                            for k, v in self.levels.items()],
            "flees": self.flees,
            "escape_log": self.escape_log,
            "stair_rests": self.stair_rests,
            "stair_runs": self.stair_runs,
            "food_picked": self.food_picked,
            "hist": list(self.hist),
            "last_pray": self.last_pray,
            "ac": self.bl(nh.NLE_BL_AC),
            "worn": [e[2] for e in self.equip_events if e[1] == "wear"],
            "equip_fail": sum(1 for e in self.equip_events if e[1] == "fail"),
            "shops": self.shops_seen,
            "desperate": self.desperations,
            "unblock": [self.unblocks, self.unblock_throws, self.unblock_melee],
            "unknown_quaffs": getattr(self, "unknown_quaffs", 0),
            "vault": [self.vault_drops, self.vault_moves],
            "wishes": getattr(self, "wishes_made", 0),
            "items_first": self.items_first_holds,
            "hunt": [self.hunts, self.hunt_steps, getattr(self, "hunt_offline_steps", 0)],
            "ward": [self.ward_writes, self.ward_waits],
            "dip_prep": getattr(self, "dip_prep_stats", None),
            "flee_stairs": getattr(self, "flee_stairs_stats", None),
            "nymph_pk": [getattr(self, "nymph_pk_elbs", 0), getattr(self, "nymph_pk_wait_total", 0)],
            "wand_id": [getattr(self, "wand_stats", None), getattr(self, "wand_log", None)],
            "resets": self.resets,
            "god_angry": self.god_angry,
            "truncated": self.truncated,
            "role": self.role,
            "race": self.race,
            "dnum": self.bl(nh.NLE_BL_DNUM),
            "last_msgs": self.death_msgs or last,
        }


if __name__ == "__main__":
    import sys, time, json
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    t = time.time()
    s = Bot(seed=seed).run()
    s["secs"] = round(time.time() - t, 1)
    print(json.dumps(s, ensure_ascii=False, indent=1))
