"""Nymphs and monkeys steal and teleport: shoot them from range, melee them first, after a theft
hunt them and loot the square they die on.

nymph_wands: a thief in a clear line (next to us too) gets an attack wand first -- sleep first (attack_wands
order) -- a ray only when our own ray would come back and hit us with probability below NYMPH_RAY_RISK
(nhbot.rays); a target a sleep ray hit is not zapped again while asleep (combat.asleep).
"""
import re
from collections import Counter

import nle.nethack as nh
import numpy as np

from nhbot import glyphs as G
from nhbot.consts import COLS, ROWS, ray_squares
from nhbot.monsters import THIEVES
from nhbot.items import base_name
from nhbot.nav import line_clear
from nhbot.pickup import STOLE_RE
from nhbot.combat import RAY_WANDS

NYMPH_RAY_RISK = 0.10


LEP_HALL_MIN = 3          # lep_hall: leprechauns in view (and nothing else hostile) that make their room closed
LEP_ROOM_MAX = 300        # a bigger flood is no room
LEP_SEED_TURNS = 150      # lep_stash: turns at most for one seeding of the hall (lep_seed_step)
LEP_LOST_TURNS = 20      # lep_stash: turns out of sight after which the leprechaun fought (lep_target) is given up
LEP_GONE = ("escapes downstairs", "escapes upstairs", "snatches", "purse feels lighter", "cannot see the leprechaun",
            "vanishes", "disappears")    # lep_stash: the leprechaun fought left the level, teleported or went unseen
LEP_STASH_DIST = 7        # lep_stash: our gold dropped at least this far from the hall (monmove.c: gold seen near)


class ThievesMixin:
    def thieves_init(self):
        self.thefts = 0
        self.stolen_pending = False
        self.loot_sq = None
        self.loot_key = None
        self.nymph_kills = 0
        self.loot_pickups = 0
        self.nymph_waits = 0
        self.nymph_elbs = 0
        self._theft_turn = None
        self.polyd = False             # polymorphed: no wearing / wielding
        self.were_drop = None          # (level key, pos) where our armor fell when we turned into an animal
        self.nymph_zap_stats = Counter()
        self.thief_stats = Counter()     # lep_drop, lep_hall, lep_stash
        self.lep_room = {}               # lep_stash: level key -> the leprechaun hall's floor (until cleared)
        self.lep_stash_at = {}           # lep_stash: level key -> squares we dropped our gold on
        self.lep_now, self.lep_awake = set(), set()  # lep_stash: leprechauns' squares, the awake ones (lep_track)
        self.lep_target = None           # lep_stash: the leprechaun we woke and fight until it dies (lep_track)
        self._lep_msg_seq = 0
        self.lep_seed = {}               # lep_stash: level key -> the seeding under way (lep_seed_step)
        self.lep_seeded = {}             # lep_stash: level key -> leprechauns killed there at the last seeding
        self.lep_coins = {}              # lep_stash: level key -> squares we seeded a coin on
        self.lep_emptied = {}            # lep_stash: level key -> squares of the hall we picked the gold up from
        self.gold_flow = Counter()       # gold got / lost by cause (gold_flow_tick), summary 'gold_flow'
        self._gold_prev = None
        self._gold_seq = 0
        self._gold_xl = {}               # XL -> most gold carried at it

    def lep_visible(self):
        """A leprechaun in view (not hallucinating: then any letter may be one)."""
        if int(self.last_bl[nh.NLE_BL_CONDITION]) & nh.BL_MASK_HALLU:
            return False
        g = self.obs["glyphs"]
        return any(G.monster_name(int(g[p])) == "leprechaun"
                   for p in zip(*np.nonzero(G.KIND[g] == G.MONSTER)))

    def lep_hall_room(self, lv):
        """More than LEP_HALL_MIN - 1 leprechauns in view and no other hostile: the floor of their room (a set of
        squares), else None."""
        if int(self.last_bl[nh.NLE_BL_CONDITION]) & nh.BL_MASK_HALLU:
            return None
        vis = self.visible_hostiles(lv)
        leps = [p for p, n in vis if n == "leprechaun"]
        if len(leps) < LEP_HALL_MIN or len(leps) < len(vis):
            return None
        ok = self.shop_floor(lv)
        for p in leps:
            ok[p] = True
        room = self._flood(ok, leps, cap=LEP_ROOM_MAX + 1)
        return room if len(room) <= LEP_ROOM_MAX else None

    def lep_stash_step(self, lv):
        """lep_stash: a leprechaun hall in view and gold on us -- first take the gold where the hall can't see it
        (a square of ours at least LEP_STASH_DIST from every square of the room: a leprechaun goes for gold it sees
        near it, monmove.c) and drop it there; then the hall. It is picked back up once no leprechaun is in view
        (lep_hold_gold). True if it used the turn."""
        if not self.opts.lep_stash:
            return False
        room = self.lep_hall_room(lv)
        if room is not None:
            self.lep_room[lv.key] = room
        room = self.lep_room.get(lv.key)
        if room is not None and self.pos() in room and not self.lep_visible():
            self.lep_room.pop(lv.key)                          # in the hall, no leprechaun left in view: done
            self.thief_stats["lep_hall_cleared"] += 1
            return False
        if room is None or lv.shop[self.pos()] or int(self.last_bl[nh.NLE_BL_CONDITION]) & nh.BL_MASK_BLIND:
            return False
        if self.lep_seed_step(lv, room):
            return True
        if int(self.bl(nh.NLE_BL_GOLD)) <= 0:
            return self.lep_approach(lv, room)
        ry = np.array([p[0] for p in room])
        rx = np.array([p[1] for p in room])
        y, x = self.pos()
        if int(np.min(np.maximum(np.abs(ry - y), np.abs(rx - x)))) >= LEP_STASH_DIST and not lv.shop[y, x]:
            self.cur_act = "lep_stash"
            self.thief_stats["lep_stash"] += 1
            self.thief_stats["lep_stash_gold"] += int(self.bl(nh.NLE_BL_GOLD))
            if self.ask("d", "drop"):
                self.press("$")
            self.goal_closed_set("gold", lv.key).discard((y, x))
            self.lep_stash_at.setdefault(lv.key, set()).add((y, x))
            return True
        near = np.zeros(lv.under.shape, dtype=bool)          # within LEP_STASH_DIST - 1 of the room
        r = LEP_STASH_DIST - 1
        for a, b in room:
            near[max(0, a - r):a + r + 1, max(0, b - r):b + r + 1] = True
        mask = ~near & ~lv.shop
        status, _ = self.walk_to(lv, mask, max_cost=60, act="lep_stash")
        if status == "moved":
            return True
        self.thief_stats["lep_stash_none"] += 1           # nowhere near: keep it on us, as before
        self.lep_room.pop(lv.key, None)
        return False

    def lep_track(self):
        """lep_stash, every tick: the leprechauns' squares, and which of them are awake -- one that moved since the
        tick before, one still on a square an awake one was on, the one we hit (a sleeping one stays put)."""
        g = self.obs["glyphs"]
        now = {(int(a), int(b)) for a, b in zip(*np.nonzero(G.KIND[g] == G.MONSTER))
               if G.monster_name(int(g[a, b])) == "leprechaun"}
        hit = {self.last_attack_target} if self.turn() - (self.attack_turn or -9) <= 1 else set()
        # moved: on a square no leprechaun was on, near one that was left (speed 15: up to 2 squares a turn); a
        # leprechaun just come into view (no square left near it) is not known awake
        left = self.lep_now - now
        moved = {p for p in now - self.lep_now if any(max(abs(p[0] - q[0]), abs(p[1] - q[1])) <= 2 for q in left)}
        self.lep_awake = moved | (now & (self.lep_awake | hit))
        hit &= self.lep_now | now
        self.lep_now = now
        self.lep_target_track(hit)

    def lep_kills(self, key):
        return sum(1 for k in self.kills if k[1] == "leprechaun" and k[3] == key)

    def lep_target_track(self, hit):
        """The leprechaun we woke: no other is hit until it dies -- followed while in view (the awake one nearest
        its last square), looked for where it was last seen while not; given up when it left the level,
        teleported or went unseen (LEP_GONE), or LEP_LOST_TURNS out of sight."""
        key, turn = self.level().key, self.turn()
        kills = self.lep_kills(key)
        t = self.lep_target
        text = self.text_since(self._lep_msg_seq).lower()
        self._lep_msg_seq = self.msg_seq
        if t is not None:
            if t["key"] != key or kills > t["kills"]:
                t = None                                       # killed, or we left the level
            elif any(w in text for w in LEP_GONE):
                self.thief_stats["lep_target_gone"] += 1
                t = None
            elif self.lep_awake:
                a, b = t["pos"]
                t["pos"] = min(self.lep_awake, key=lambda p: max(abs(p[0] - a), abs(p[1] - b)))
                t["seen"] = turn
            elif turn - t["seen"] > LEP_LOST_TURNS:
                self.thief_stats["lep_target_lost"] += 1
                t = None
        if t is None and hit:
            t = {"key": key, "kills": kills, "pos": next(iter(hit)), "seen": turn}
        self.lep_target = t

    def lep_seed_step(self, lv, room):
        """lep_stash, in the hall: a leprechaun of it killed, no awake one in view, sleeping ones left -- before
        waking the next, a coin on every square of the hall's floor without a monster (a leprechaun picks up the
        gold it finds, so a woken one stays to gather instead of running off with ours): gold picked up (the
        hall's piles, and the squares its leprechauns were killed on -- a killed one drops its gold, its corpse
        on top hides it) as much as the squares without gold need, one coin dropped on each, the rest dropped
        where we stand; then the fight goes on. LEP_SEED_TURNS at most a time. True if it used the turn."""
        key = lv.key
        dead = [k[2] for k in self.kills if k[1] == "leprechaun" and k[3] == key]
        seed = self.lep_seed.get(key)
        if seed is None:
            if len(dead) <= self.lep_seeded.get(key, 0) or self.lep_awake or self.lep_target is not None \
                    or not (self.lep_now & room) \
                    or self.pos() not in room:
                return False
            k = G.KIND[lv.under]
            sq = {p for p in room if k[p] in (G.FLOOR, G.GOLD, G.CORPSE, G.OBJECT)}
            seed = self.lep_seed[key] = {"squares": sq, "done": set(), "until": self.turn() + LEP_SEED_TURNS,
                                         "kills": len(dead)}
            self.thief_stats["lep_seed"] += 1
        if self.lep_awake or self.lep_target is not None or self.turn() > seed["until"]:
            return self.lep_seed_end(lv, seed, "awake" if self.lep_awake else "timeout")
        g = self.obs["glyphs"]
        k = G.KIND[lv.under]
        here = self.pos()
        coins = self.lep_coins.setdefault(key, set())          # our coins of the seedings before
        emptied = self.lep_emptied.setdefault(key, set())      # picked up by us
        free = {p for p in seed["squares"] if G.KIND[int(g[p])] != G.MONSTER or p == here}
        gold_on = {p for p in free if k[p] == G.GOLD or p in dead} - emptied
        todo = [p for p in free - gold_on if p not in seed["done"]]
        piles = [p for p in gold_on if p not in coins and p not in seed["done"]]
        if not todo:
            return self.lep_seed_end(lv, seed, "done")
        self.cur_act = "lep_seed"
        gold = int(self.bl(nh.NLE_BL_GOLD))
        if gold < len(todo) and piles:                         # collect
            if here in piles:
                self.pickup_matching(("gold piece",))
                emptied.add(here)
                coins.discard(here)
                self.thief_stats["lep_seed_pick"] += 1
                return True
            return self.lep_seed_walk(lv, piles) or self.lep_seed_end(lv, seed, "no_path")
        if gold <= 0:
            return self.lep_seed_end(lv, seed, "no_gold")
        if here in todo:                                       # place: one coin
            if self.ask("d", "drop"):
                self.raw_step(ord("1"))
                self.press("$")
            seed["done"].add(here)
            coins.add(here)
            emptied.discard(here)
            self.thief_stats["lep_seed_coin"] += 1
            return True
        return self.lep_seed_walk(lv, todo) or self.lep_seed_end(lv, seed, "no_path")

    def lep_seed_walk(self, lv, squares):
        mask = np.zeros(lv.under.shape, dtype=bool)
        for p in squares:
            mask[p] = True
        status, _ = self.walk_to(lv, mask, max_cost=60, act="lep_seed")
        return status == "moved"

    def lep_seed_end(self, lv, seed, why):
        """The seeding over: the gold left on us dropped where we stand (it would be stolen)."""
        self.lep_seed.pop(lv.key, None)
        self.lep_seeded[lv.key] = seed["kills"]
        self.thief_stats["lep_seed_" + why] += 1
        if int(self.bl(nh.NLE_BL_GOLD)) > 0:
            self.cur_act = "lep_seed"
            if self.ask("d", "drop"):
                self.press("$")
            return True
        return False

    def lep_approach(self, lv, room):
        """lep_stash, our gold stashed and the hall not cleared: an awake leprechaun in view and none next to us
        -- after it (sleepers next to us wait: hitting one wakes another); none awake in view and none next to us
        -- to the nearest of the hall's (none in view: its floor). True if it used the turn."""
        y, x = self.pos()
        adj = {p for p in self.lep_now if max(abs(p[0] - y), abs(p[1] - x)) == 1}
        t = self.lep_target
        if adj & self.lep_awake or (adj and not self.lep_awake and t is None):
            return False                                       # the melee step (lep_focus_target)
        mask = np.zeros(lv.under.shape, dtype=bool)
        if t is not None and not self.lep_awake:               # the one we fight out of sight: where it was
            if (y, x) == t["pos"]:
                self.press("s")                                # there: look around, a turn
                self.thief_stats["lep_target_wait"] += 1
                return True
            mask[t["pos"]] = True
            status, _ = self.walk_to(lv, mask, max_cost=80, act="lep_hall")
            if status != "moved":
                self.press("s")
                self.thief_stats["lep_target_wait"] += 1
            else:
                self.thief_stats["lep_target_seek"] += 1
            return True
        goal = self.lep_awake or [p for p in self.lep_now if p in room]
        if goal:
            for a, b in goal:
                mask[max(0, a - 1):a + 2, max(0, b - 1):b + 2] = True
        else:
            for p in room:                                     # none in view (we stashed the gold out of
                mask[p] = True                                 # sight of the hall): back into it
        status, _ = self.walk_to(lv, mask, max_cost=80, act="lep_hall")
        if status == "moved":
            self.thief_stats["lep_chase" if self.lep_awake else "lep_approach"] += 1
            return True
        return False

    def lep_focus_target(self, lv, hostiles):
        """lep_stash: the leprechaun to hit among those next to us -- an awake one (lep_track), the one we hit
        last first, so one is fought until it dies instead of waking the next; None: no preference."""
        if not self.opts.lep_stash:
            return None
        adj = [p for p, n in hostiles if n == "leprechaun" and p in self.lep_awake]
        if not adj:
            return None
        return self.last_attack_target if self.last_attack_target in adj else adj[0]

    def lep_melee_cands(self, hostiles):
        """lep_stash: the hostiles next to us the melee step may hit -- a sleeping leprechaun not while the one we
        woke is alive (lep_target)."""
        if not self.opts.lep_stash or self.lep_target is None:
            return hostiles
        return [(p, n) for p, n in hostiles if n != "leprechaun" or p in self.lep_awake]

    def lep_hall_mark(self, lv):
        """lep_hall: a leprechaun hall in view (lep_hall_room): its floor is closed to us from outside, like a shop
        (mapmem.passable_grid); from inside we walk as before, and it closes once we are out."""
        if not self.opts.lep_hall:
            return
        room = self.lep_hall_room(lv)
        if room is None:
            return
        if not lv.lep_shut.any():
            self.thief_stats["lep_hall"] += 1
        for c in room:
            lv.lep_shut[c] = True

    def lep_step(self, lv):
        """lep_drop: a leprechaun in view and gold on us -- drop it all where we stand (steal.c stealgold takes a
        part of the gold carried with every hit, the leprechaun teleporting off with it), then fight on; it is
        picked back up only once no leprechaun is in view (step_gold_here, the gold goal). Not in a shop (the
        keeper would take it) nor blind. True if it used the turn."""
        if not self.opts.lep_drop or int(self.bl(nh.NLE_BL_GOLD)) <= 0 or lv.shop[self.pos()] \
                or int(self.last_bl[nh.NLE_BL_CONDITION]) & nh.BL_MASK_BLIND or not self.lep_visible():
            return False
        self.cur_act = "lep_drop"
        self.thief_stats["lep_drop"] += 1
        self.thief_stats["lep_drop_gold"] += int(self.bl(nh.NLE_BL_GOLD))
        if self.ask("d", "drop"):
            self.press("$")
        self.goal_closed_set("gold", lv.key).discard(self.pos())      # ours again once it is safe
        return True

    def lep_hold_gold(self, lv=None):
        """lep_drop, lep_stash: no gold picked up while a leprechaun is in view (it would be stolen again)."""
        return (self.opts.lep_drop or self.opts.lep_stash) and self.lep_visible()

    def lep_stash_held(self, lv):
        """lep_stash: the squares of our stashed gold, left alone while their hall is not cleared."""
        return self.lep_stash_at.get(lv.key, set()) if lv.key in self.lep_room else set()

    def gold_flow_tick(self):
        """Stats only: a change of the gold we carry since the last tick, by the messages that came with it --
        a leprechaun's touch ("Your purse feels lighter."), a foocubus, a vault guard, a shop, a fountain."""
        g = int(self.bl(nh.NLE_BL_GOLD))
        if self._gold_prev is not None and g != self._gold_prev:
            d = g - self._gold_prev
            m = self.text_since(self._gold_seq)
            if d > 0:
                self.gold_flow["got_sold" if "You sold" in m else "got_other"] += d
            else:
                why = ("leprechaun" if "purse feels lighter" in m else
                       "foocubus" if ("attracted" in m or "seduc" in m or "prettier" in m) else
                       "vault" if self.vault_drops and "drop" in m and "gold" in m else
                       "shop" if ("bought" in m or "zorkmid" in m or "pay" in m.lower()) else
                       "fountain" if "fountain" in m else
                       "drop" if "You drop" in m else "other")
                self.gold_flow["lost_" + why] -= d
        xl = int(self.bl(nh.NLE_BL_XP))
        self._gold_xl[xl] = max(self._gold_xl.get(xl, 0), g)
        self._gold_prev, self._gold_seq = g, self.msg_seq

    # ================================================================== nymphs
    def msg_thieves(self, m):
        for what in STOLE_RE.findall(m):                    # "She stole a +0 orcish helm." / "It steals ...!"
            self.stolen_names.add(base_name(what)[2])
        stole = (re.search(r"\b(stole|steals|stolen)\b", m) or "charms you" in m) and \
            (any(t in m for t in THIEVES) or "She stole" in m or "He stole" in m)
        if stole or "It stole" in m or "It steals" in m or "She charms you" in m:
            if self.turn() != self._theft_turn:
                self._theft_turn = self.turn()
                self.thefts += 1
            self.stolen_pending = True
        if self.killed and any(t in self.killed for t in THIEVES) and self.last_attack_target:
            self.nymph_kills += 1
            if self.stolen_pending:
                self.goal_event("loot", "abandoned", self.loot_sq is not None)    # replaced by a newer one
                self.goal_event("loot", "created")
                self.loot_sq = self.last_attack_target
                self.loot_key = self.cur_key
        if re.search(r"You turn into an? \w+|shrink out of your|break out of your armor|armor falls around you", m):
            self.were_drop = (self.cur_key, self.pos())      # armor fell here; collect it once human again
        if re.search(r"You turn into an? ", m):
            self.polyd = True                                 # weapons: no wielding in a borrowed body
        if re.search(r"You return to \w+ form|You feel like a new ", m):
            self.polyd = False
        if re.search(r"You return to \w+ form", m) and self.were_drop:   # dwarves: "dwarven form"
            self.goal_event("loot", "abandoned", self.loot_sq is not None)
            self.goal_event("loot", "created")
            self.loot_key, self.loot_sq = self.were_drop
            self.were_drop = None

    def nymph_zap(self, lv):
        """nymph_wands: zap a thief in a clear line within 7. True if we zapped."""
        if not self.opts.nymph_wands:
            return False
        wands = self.attack_wands()
        if not wands:
            return False
        for key, d, pos, step, name in self.line_targets(lv, max_d=7):
            if name not in THIEVES or self.peaceful_now(lv, pos, far=True):
                continue
            for letter, kind in wands:
                if kind == "sleep" and self.asleep(lv, pos):
                    continue                     # asleep already: melee / missiles finish it
                if kind in RAY_WANDS:
                    p, _ = self.ray_risk(lv, step, kind, letter)
                    if p >= NYMPH_RAY_RISK:
                        self.nymph_zap_stats["held_risk"] += 1
                        continue
                self.cur_act = "fight"
                self.last_attack_target = pos
                if not self.zap(letter, key):
                    return False
                self.nymph_zap_stats["zaps_" + kind] += 1
                if kind == "sleep" and self.asleep(lv, pos):
                    self.nymph_zap_stats["slept"] += 1
                return True
        return False

    def nymph_step(self, lv, hostiles):
        if self.nymph_zap(lv):
            return True
        y, x = self.pos()
        # 1) adjacent thief: hit it first (normal melee would pick the lowest level target)
        adj = [(p, n) for p, n in hostiles if n in THIEVES]
        if adj:
            self.attack(adj[0][0])
            return True
        th = self.thieves_visible(lv)
        if not th:
            return False
        # 2) thief in a clear line at range: throw / fire / bolt
        for key, d, pos, (dy, dx), name in self.line_targets(lv, max_d=7):
            if name not in THIEVES or d < 2:
                continue
            if self.peaceful_now(lv, pos, far=True):
                continue
            self.last_attack_target = pos
            self.cur_act = "fight"
            tw = self.throwables()
            if tw:
                ray = ray_squares(y, x, dy, dx)
                self.throw(tw[0][0], key, ray)
                return True
        have_shot = bool(self.throwables())
        # 2b) we could shoot but it isn't in line: step to a square that lines us up, at distance >= 2
        if have_shot:
            step = self.align_step(lv, th)
            if step is not None:
                self.cur_act = "fight"
                self.move(step)
                return True
        # 2c) no way to shoot: stand on Elbereth (nymphs respect it and won't steal in melee)
        if not have_shot and (y, x) not in lv.elbereth:
            close = [t for t in th if max(abs(t[0][0] - y), abs(t[0][1] - x)) <= 4]
            if close and self.nymph_elbs < 30 and self.elb_can_write(lv):
                self.nymph_elbs += 1
                self.cur_act = "fight"
                if not self.engrave_elbereth():
                    self.elb_fail += 1
                    self.elb_fail_at = (lv.key, self.pos(), self.turn())
                    self.elb_stats["nymph_fail"] += 1
                elif not self.elb_confirm(lv):
                    self.elb_misspelled += 1
                    self.elb_stats["nymph_misspelled"] += 1
                else:
                    self.elb_stats["nymph_ok"] += 1
                return True
        # 3) no shot: never step next to a thief (that hands it the first move). Hold still and
        #    let it come; nymphs come back to steal more, so waiting is also how we get our items back.
        close = [t for t in th if 2 <= max(abs(t[0][0] - y), abs(t[0][1] - x)) <= self.opts.nymph_hold]
        if close and self.nymph_waits < self.opts.nymph_wait_max:
            self.nymph_waits += 1
            self.cur_act = "fight"
            self.press("s")
            return True
        if not close:
            self.nymph_waits = 0
        return False

    def align_step(self, lv, th):
        """A neighbouring free square from which some thief is in a straight clear line, 2..6 away."""
        y, x = self.pos()
        k_mem, _, p = self.grids(lv)
        g = self.obs["glyphs"]
        best = None
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if not (dy or dx):
                    continue
                ny, nx = y + dy, x + dx
                if not (0 <= ny < ROWS and 0 <= nx < COLS) or not p[ny, nx] or G.KIND[g[ny, nx]] in (G.MONSTER, G.PET):
                    continue
                if dy and dx and (k_mem[y, x] in (G.DOOR_OPEN, G.DOOR_CLOSED) or k_mem[ny, nx] in (G.DOOR_OPEN, G.DOOR_CLOSED)):
                    continue
                for (ty, tx), _ in th:
                    ry, rx = ty - ny, tx - nx
                    d = max(abs(ry), abs(rx))
                    if d < 2 or d > 6 or not (ry == 0 or rx == 0 or abs(ry) == abs(rx)):
                        continue
                    sy, sx = (ry > 0) - (ry < 0), (rx > 0) - (rx < 0)
                    if line_clear(k_mem, g, ny, nx, sy, sx, d):
                        if best is None or d < best[0]:
                            best = (d, (ny, nx))
        return best[1] if best else None

    def loot_step(self, lv):
        if self.loot_sq is None or self.loot_key != lv.key:
            return False
        return self.pursue("loot", lv, [self.loot_sq], self.loot_consume)

    def loot_consume(self, goal):
        self.pickup_all()
        self.loot_pickups += 1
        self.stolen_pending = False
