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
ALWAYS_AVOID = {"gas spore", "cockatrice", "chickatrice"}   # even when desperate
RANGED_TARGETS = {"floating eye", "gas spore", "blue jelly", "spotted jelly",
                  "ochre jelly", "brown mold", "green mold", "cockatrice", "chickatrice"}
THROWABLE = ("dagger", "dart", "knife", "shuriken", "javelin", "spear")
THROW_STONES = ("flint stone", "rock")
# fresh-corpse whitelist (eaten only within ~40 turns of the kill)
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
        self.avoid_down = set()
        self.shop = np.zeros((ROWS, COLS), dtype=bool)
        self.desperate = False
        self.progress_count = 0
        self.last_progress = 0
        self.last_reset = 0   # downstairs leading into the Gnomish Mines
        self.peaceful = set()     # monster glyphs that turned out peaceful here
        self.entered_turn = None
        self.elbereth = set()     # positions where we engraved


class Bot:
    def __init__(self, seed=None, character="@", verbose=False, max_steps=200_000, max_turns=None,
                 avoid_mines=True, rest_frac=0.5, elb_frac=0.0, descend_hp=0.0,
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
        self.raw_step(code)
        self.settle(expect_prompt)

    def settle(self, expect_prompt=False):
        for _ in range(50):
            tty = self.tty_text()
            msg = self.message()
            if self.obs["misc"][2] or "--More--" in tty.replace("\n", ""):
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
                self.raw_step(27)
                continue
            if re.search(r"\(end\)|\(\d+ of \d+\)", tty):
                self.raw_step(27)
                continue
            self.log_msg(msg)
            return

    def answer_yn(self, msg):
        m = msg.lower()
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
        lv.visited[y, x] += 1
        lv.near[max(0, y - 1):y + 2, max(0, x - 1):x + 2] = True
        self.max_depth = max(self.max_depth, self.bl(nh.NLE_BL_DEPTH))
        pc = int(lv.seen.sum()) + int((lv.visited > 0).sum())
        if pc > lv.progress_count:
            lv.progress_count = pc
            lv.last_progress = self.turn()
        return lv

    def on_message(self, m):
        lv = self.levels.get(self.cur_key) if self.cur_key else None
        if "This door is locked" in m and self.last_move_target and lv:
            lv.locked.add(self.last_move_target)
        if lv and self.last_move_target and any(s in m for s in (
                "You try to move the boulder, but in vain",
                "Perhaps that's why you cannot move past it",
                "There is a boulder in your way",
                "You are carrying too much to get through",
                "You don't have enough room to maneuver")):
            lv.blocked[self.last_move_target] = True
        if "Closed for inventory" in m and lv:
            y, x = self.pos()
            for dy, dx in NEIGH:
                ny, nx = y + dy, x + dx
                if 0 <= ny < ROWS and 0 <= nx < COLS and G.KIND[lv.under[ny, nx]] == G.DOOR_CLOSED:
                    lv.blocked[ny, nx] = True
        mk = re.search(r"You (kill|destroy) (?:the |an? )?(.+?)!", m)
        if mk and self.last_attack_target:
            self.kills.append((self.turn(), mk.group(2), self.last_attack_target, self.cur_key))
        if "You feel that" in m and "displeased" in m:
            self.pray_failed += 1
        if self.last_pray is not None and self.turn() - self.last_pray <= 5 and any(
                p in m for p in ("Thou hast angered me", "Thou must relearn", "You feel guilty",
                                 "Then die, mortal", "Thou durst", "You feel that Mitra is angry",
                                 "is displeased.") if p != "is displeased."):
            self.god_angry = True
        if lv and re.search(r"Welcome to [A-Z][\w' -]*'s ", m):
            # shop entrance: never go inside (we get trapped / risk shoplifting)
            self.mark_shop(lv, self.pos())
            self.shops_seen += 1
        if "You die" in m or "You starve" in m:
            self.death_msgs = list(self.messages)[-8:]

    # ------------------------------------------------------------ helpers
    def kind_grid(self, lv):
        """Terrain kind map from memory, with live monsters/objects overlaid."""
        g = self.obs["glyphs"]
        k_live = G.KIND[g]
        k_mem = G.KIND[lv.under]
        return k_mem, k_live

    def passable_grid(self, lv, k_mem, k_live):
        p = G.PASSABLE[k_mem].copy()
        p |= (k_mem == G.BOULDER) | (k_live == G.BOULDER)   # try pushing; failures mark blocked
        p[lv.blocked] = False
        if not lv.shop[self.pos()]:
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
        y, x = self.pos()
        key = DELTA2KEY[(target[0] - y, target[1] - x)]
        self.last_attack_target = target
        self.last_move_target = None
        self.press("F")
        self.press(key)

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
        self.last_pray = self.turn()
        self.prayers += 1
        self.press("#", expect_prompt=True)
        for c in "pray":
            self.raw_step(ord(c))
        self.press(13)

    def can_pray(self, hunger_emergency=None):
        if self.god_angry:
            return False
        t = self.turn()
        if self.last_pray is None:
            return t > 300 or (hunger_emergency and t > 100)
        gap = t - self.last_pray
        if hunger_emergency:          # fainting: starving is certain death
            return gap > 300
        return gap > 1000 if hunger_emergency is None else gap > 700

    def engrave_elbereth(self):
        lv = self.level()
        self.press("E", expect_prompt=True)
        if "write with" not in self.message().lower():
            self.settle()
            return
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
        else:
            self.settle()

    def eat_from_inventory(self):
        for letter, ocls, s in self.inventory():
            if ocls == nh.FOOD_CLASS and "corpse" not in s and "tin" not in s and "egg" not in s:
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
        if name not in SAFE_CORPSES:
            return False
        kin = RACE_KIN.get((self.race or "").lower(), ())
        return not any(k.lower() in name.lower() for k in kin)

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
            if "weapon in hand" in s or "wielded" in s or " cursed" in s:
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

    def pickup_matching(self, words):
        self.press(",", expect_prompt=True)
        tty = self.tty_text()
        if "Pick up what?" not in tty:
            self.settle()
            return
        chosen = 0
        for line in tty.split("\n"):
            m = re.match(r"^\s*([a-zA-Z]) - (.*)$", line.strip())
            if m and any(w in m.group(2) for w in words):
                self.raw_step(ord(m.group(1)))
                chosen += 1
        self.raw_step(13 if chosen else 27)
        self.settle()

    def retrieve_goal(self, lv):
        t = self.turn()
        self.retrieve = [r for r in self.retrieve if r[2] > t]
        g = self.obs["glyphs"]
        for key, ray, _ in self.retrieve:
            if key != lv.key:
                continue
            for p in ray:
                if G.KIND[g[p]] == G.OBJECT and nh.glyph_is_object(int(g[p])) and \
                        nh.objclass(nh.glyph_to_obj(int(g[p]))).oc_class in (nh.WEAPON_CLASS, nh.GEM_CLASS):
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
                    if name in NEVER_MELEE and not (lv.desperate and name not in ALWAYS_AVOID) \
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
                if name in NEVER_MELEE and not (lv.desperate and name not in ALWAYS_AVOID
                                                and self.bl(nh.NLE_BL_HP) * 10 >= self.bl(nh.NLE_BL_HPMAX) * 9) \
                        and not self.spore_ok(name):
                    continue
                if self.is_peaceful((ny, nx)):
                    continue
                out.append(((ny, nx), name))
            elif k == G.INVIS and (ny, nx):
                out.append(((ny, nx), "invisible"))
        return out

    def spore_ok(self, name):
        # gas spore explosion is 4d6 (max 24): meleeing it is safe above that
        return name == "gas spore" and self.bl(nh.NLE_BL_HP) >= 25

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
            self.prev_key = lv.key
        self.took_stairs = False
        if self.avoid_mines and lv.key[0] == 2 and lv.key not in self.mines_bounced \
                and arrived_by_stairs:
            self.mines_bounced.add(lv.key)
            self.pending_mines_mark = True
            self.press("<")
            return
        y, x = self.pos()
        hp, maxhp = self.bl(nh.NLE_BL_HP), self.bl(nh.NLE_BL_HPMAX)
        hunger = self.bl(nh.NLE_BL_HUNGER)

        t = self.turn()
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

        # engulfed: hit anything
        if G.KIND[self.obs["glyphs"][y, x]] == G.EFFECT and self.obs["glyphs"][y, x] >= nh.GLYPH_SWALLOW_OFF \
                and self.obs["glyphs"][y, x] < nh.GLYPH_WARNING_OFF:
            self.last_attack_target = None
            self.press("F"); self.press("h")
            return

        # emergencies
        low = hp <= 5 or hp * 7 <= maxhp
        if low and self.can_pray():
            self.pray(); return
        if hunger >= WEAK and self.can_pray(hunger_emergency=hunger >= FAINTING):
            self.pray(); return

        hostiles = self.adjacent_hostiles(lv)
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
            self.attack(target)
            return
        if (y, x) in lv.elbereth and hp * 2 < maxhp:
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
        if hunger >= HUNGRY:
            if self.eat_from_inventory():
                return

        # fresh corpse nearby
        if hunger >= NOT_HUNGRY and self.kills:
            goal = self.corpse_goal(lv)
            if goal is not None:
                if goal == (y, x):
                    self.eat_corpse_here()
                    self.kills = [k for k in self.kills if k[2] != goal or k[3] != lv.key]
                    return
                if self.go_toward(lv, goal):
                    return

        # rest if hurt and nothing around
        vis = self.visible_hostiles(lv)
        if hp < maxhp * self.rest_frac and not vis:
            self.press("2"); self.press("0"); self.press("s")
            return

        # gold under us
        if G.KIND[lv.under[y, x]] == G.GOLD:
            self.press(",")
            lv.under[y, x] = G.STONE_GLYPH + 19   # assume floor now
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
        gold = (k_mem == G.GOLD) & passable
        downstairs = k_mem == G.DOWNSTAIR
        on_level = self.turn() - (lv.entered_turn or 0)
        if lv.avoid_down and on_level < 3000:
            for p in lv.avoid_down:
                downstairs[p] = False
        want_down = downstairs.any() and self.should_descend(lv, frontier, on_level)

        if want_down:
            if downstairs[y, x]:
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

        targets = frontier | gold
        if targets.any():
            dist, prev, reached = self.dijkstra(lv, k_mem, k_live, passable, start, targets)
            if reached is not None and reached != start:
                step = self.first_step(prev, start, reached)
                if step:
                    self.move(step)
                    return
            if reached == start:
                lv.visited[start] += 1

        if downstairs.any():
            if downstairs[y, x]:
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

        # nothing left: search for hidden passages
        self.search_mode(lv, k_mem, k_live, passable)

    def should_descend(self, lv, frontier, on_level):
        if self.bl(nh.NLE_BL_HP) < self.bl(nh.NLE_BL_HPMAX) * self.descend_hp:
            return False
        if self.descend_policy == "dive":
            return True
        xl = self.bl(nh.NLE_BL_XP)
        depth = self.bl(nh.NLE_BL_DEPTH)
        if self.descend_policy == "explore":
            return not frontier.any() or on_level > 2000
        if self.descend_policy == "careful":
            # explore fully; only go deeper when experienced enough
            if depth >= xl + 3 and on_level < 4000:
                return False
            return not frontier.any() or on_level > 2000
        return not frontier.any()

    def search_mode(self, lv, k_mem, k_live, passable):
        start = self.pos()
        dist, prev, _ = self.dijkstra(lv, k_mem, k_live, passable, start, None)
        reach = dist < (1 << 30)
        wallish = (k_mem == G.WALL) | (k_mem == G.UNKNOWN)
        cnt = np.zeros((ROWS, COLS), dtype=np.int32)
        for dy, dx in NEIGH:
            cnt[max(0, dy):ROWS + min(0, dy), max(0, dx):COLS + min(0, dx)] += \
                wallish[max(0, -dy):ROWS + min(0, -dy), max(0, -dx):COLS + min(0, -dx)]
        score = np.where(reach & passable, cnt * 10.0 - lv.searched * 2.0 - np.minimum(dist, 500) * 0.3, -1e9)
        # dead-end corridors are prime spots
        best = np.unravel_index(np.argmax(score), score.shape)
        if score[best] <= -1e8:
            self.press("s")
            return
        best = (int(best[0]), int(best[1]))
        if best == start:
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
        self.shops_seen = 0
        self.loop_turn, self.loop_steps, self.loops = -1, 0, 0
        self.desperations = 0
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
            while True:
                self.tick()
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
            "shops": self.shops_seen,
            "desperate": self.desperations,
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
