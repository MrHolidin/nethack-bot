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
from nhbot.consts import COLS, CORRIDOR_GLYPHS, ROWS, ray_squares
from nhbot.monsters import THIEVES
from nhbot.items import base_name
from nhbot.nav import line_clear
from nhbot.pickup import STOLE_RE
from nhbot.combat import RAY_WANDS

NYMPH_RAY_RISK = 0.10


LEP_HALL_MIN = 3          # lep_hall: leprechauns in view (and nothing else hostile) that make their room closed
LEP_ROOM_MAX = 300        # a bigger flood is no room
LEP_BAIT_TURNS = 150      # lep_stash: turns at most for one baiting before a sleeper is hit (lep_bait_step)
LEP_LOST_TURNS = 20      # lep_stash: turns an awake leprechaun gone out of sight is expected back into view
LEP_STILL = 2             # lep_stash: ticks still (not fought) that make one taken for an awake leprechaun a sleeper
LEP_GONE = ("escapes downstairs", "escapes upstairs", "snatches", "purse feels lighter", "cannot see the leprechaun",
            "vanishes", "disappears")    # lep_stash: an awake leprechaun left the level, teleported or went unseen
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
        self.lep_sleep = {}              # lep_stash: level key -> the squares sleeping leprechauns are on (lep_track)
        self.lep_lost = []               # lep_stash: (square, turn) where awake ones went out of sight (lep_track)
        self.lep_assumed = set()         # lep_stash: the squares of ones taken for an awake one back in view
        self.lep_still = {}              # lep_stash: awake one's square -> ticks it stayed on it
        self.lep_sure = set()            # lep_stash: the awake ones we hit (lep_track)
        self._lep_seen = (None, 0, 0, None)  # lep_stash: level key, leprechaun kills there, message counter, our square
        self.lep_bait = {}               # lep_stash: level key -> the baiting under way (lep_bait_step)
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

    def lep_stash_step(self, lv, hostiles=()):
        """lep_stash: a leprechaun hall in view and gold on us -- first take the gold where the hall can't see it
        (a square of ours at least LEP_STASH_DIST from every square of the room: a leprechaun goes for gold it sees
        near it, monmove.c) and drop it there; then the hall. It is picked back up once no leprechaun is in view
        (lep_hold_gold). True if it used the turn."""
        if not self.opts.lep_stash:
            return False
        room = self.lep_hall_note(lv)
        if room is None or lv.shop[self.pos()] or int(self.last_bl[nh.NLE_BL_CONDITION]) & nh.BL_MASK_BLIND:
            return False
        if any(n != "leprechaun" for _, n in hostiles):
            return False                                       # another one next to us: the melee step first
        if self.lep_bait_step(lv, room):
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
        """lep_stash, every tick: the leprechauns in view, and which of them are awake. A sleeping one stays on its
        square, so the squares sleepers were seen on are kept (lep_sleep) and the others in view are awake: the
        one we hit; one that moved (while we stood: on a new square near one left -- our own step changes what we
        see); one seen anew near where an awake one went out of sight (lep_lost: it came back into view). One seen
        anew otherwise sleeps; so does one taken for awake that stays still LEP_STILL ticks unfought (not one we
        hit: lep_sure)."""
        g = self.obs["glyphs"]
        now = {(int(a), int(b)) for a, b in zip(*np.nonzero(G.KIND[g] == G.MONSTER))
               if G.monster_name(int(g[a, b])) == "leprechaun"}
        key, turn, here = self.level().key, self.turn(), self.pos()
        kills = self.lep_kills(key)
        key0, kills0, seq0, here0 = self._lep_seen
        if key != key0:
            self.lep_now, self.lep_awake, self.lep_lost, kills0 = set(), set(), [], kills
            self.lep_assumed, self.lep_still, self.lep_sure = set(), {}, set()
        if any(w in self.text_since(seq0).lower() for w in LEP_GONE):
            self.lep_lost = []
        self.lep_lost = [(p, t) for p, t in self.lep_lost if turn - t <= LEP_LOST_TURNS]
        sleep = self.lep_sleep.setdefault(key, set())
        hit = {self.last_attack_target} if turn - (self.attack_turn or -9) <= 1 else set()
        hit &= self.lep_now | now
        sleep -= hit
        left = self.lep_now - now
        new = now - self.lep_now
        moved = set()
        if here == here0:
            for p in new - sleep:                              # speed 15: up to 2 squares a turn
                near = {q for q in left if max(abs(p[0] - q[0]), abs(p[1] - q[1])) <= 2}
                if near:
                    moved.add(p)
                    sleep -= near                              # it was one of them: woke
        awake = moved | (now & (self.lep_awake | hit))
        # known awake for sure: hit by us (followed as it moves) -- the stillness rule below is not for it
        self.lep_sure = (now & (self.lep_sure | hit)) | {p for p in moved if any(
            max(abs(p[0] - q[0]), abs(p[1] - q[1])) <= 2 for q in self.lep_sure - now)}
        # awake ones gone out of view: not on a square now, not the one that moved from it, not the one killed
        out = [p for p in sorted(self.lep_awake - now)
               if not any(max(abs(p[0] - q[0]), abs(p[1] - q[1])) <= 2 for q in moved)]
        if kills > kills0:
            out = sorted(out, key=lambda p: p != self.last_attack_target)[kills - kills0:]
        self.lep_lost += [(p, turn) for p in out]
        # an awake one moves (speed 15) unless we fight it: one taken for awake still LEP_STILL ticks and not
        # hit is a sleeper
        recent = turn - (self.attack_turn or -9) <= LEP_STILL
        self.lep_still = {p: (self.lep_still.get(p, -1) + 1 if p in self.lep_now else 0) for p in awake}
        for p, n in self.lep_still.items():
            if n >= LEP_STILL and p not in self.lep_sure and not (recent and p == self.last_attack_target):
                awake.discard(p)
                sleep.add(p)
                if p in self.lep_assumed:
                    self.lep_lost.append((p, turn))           # the one out of sight is still out of it
        self.lep_assumed &= awake
        for p in sorted(new - sleep - awake):
            reach = [(max(abs(p[0] - q[0]), abs(p[1] - q[1])), i) for i, (q, t) in enumerate(self.lep_lost)
                     if max(abs(p[0] - q[0]), abs(p[1] - q[1])) <= 2 * (turn - t) + 2]
            if reach:
                self.lep_lost.pop(min(reach)[1])
                awake.add(p)
                self.lep_assumed.add(p)
            else:
                sleep.add(p)
        self.lep_awake = awake
        self.lep_now = now
        self._lep_seen = (key, kills, self.msg_seq, here)

    def lep_kills(self, key):
        return sum(1 for k in self.kill_log if k[1] == "leprechaun" and k[3] == key)

    def lep_bait_step(self, lv, room):
        """lep_stash, in the hall, no awake leprechaun in view and a sleeping one there -- before waking one: all
        the gold we can get at in the hall picked up (its piles in view without a monster on them, the squares its
        leprechauns were killed on: what one carried drops there), all of it dropped next to the sleeper to hit
        (lep_bait: the bait square), then a step to a square next to both it and the sleeper with no gold on it
        (a leprechaun hitting us snatches the gold under us and teleports, steal.c) -- the sleeper is hit from
        there (lep_focus_target). LEP_BAIT_TURNS at most a time. True if it used the turn."""
        key = lv.key
        bait = self.lep_bait.get(key)
        sleep = self.lep_sleep.get(key, set())
        sleepers = self.lep_now & sleep & room
        if self.lep_awake or not sleepers:
            self.lep_bait.pop(key, None)
            return False
        if bait is None:
            bait = self.lep_bait[key] = {"until": self.turn() + LEP_BAIT_TURNS, "plan": None}
            self.thief_stats["lep_bait"] += 1
        g = self.obs["glyphs"]
        k = G.KIND[lv.under]
        here = self.pos()
        dead = {q[2] for q in self.kill_log if q[1] == "leprechaun" and q[3] == key}
        emptied = self.lep_emptied.setdefault(key, set())
        mon = G.KIND[g] == G.MONSTER
        gold_sq = {p for p in room if (k[p] == G.GOLD or p in dead) and p not in emptied}
        self.cur_act = "lep_bait"
        late = self.turn() > bait["until"]
        bait_sq = bait["plan"][1] if bait["plan"] else None      # the bait down already stays there
        piles = [p for p in gold_sq if (not mon[p] or p == here) and p != bait_sq]
        if piles and not late:                                 # collect
            if here in piles:
                self.pickup_matching(("gold piece",))
                emptied.add(here)
                self.thief_stats["lep_bait_pick"] += 1
                return True
            if self.lep_bait_walk(lv, piles):
                return True
            self.thief_stats["lep_bait_no_path"] += 1
            bait["until"] = -1
        plan = bait["plan"]
        if plan is None or plan[0] not in sleepers:
            plan = bait["plan"] = self.lep_bait_plan(lv, room, sleepers, gold_sq)
            if plan is None:
                self.thief_stats["lep_bait_no_square"] += 1
                self.lep_bait.pop(key, None)
                return False
        target, drop, stand = plan
        gold = int(self.bl(nh.NLE_BL_GOLD))
        if gold > 0:
            if here != drop:
                if self.lep_bait_walk(lv, [drop]):
                    return True
                bait["plan"] = None
                self.thief_stats["lep_bait_no_path"] += 1
                return False
            if self.ask("d", "drop"):                          # the bait
                self.press("$")
            emptied.discard(here)
            self.thief_stats["lep_bait_drop"] += 1
            self.thief_stats["lep_bait_gold"] += gold
            return True
        if here != stand:
            if self.lep_bait_walk(lv, [stand]):
                return True
            bait["plan"] = None
            return False
        self.thief_stats["lep_bait_hit"] += 1
        return False                                           # the melee step hits the target (lep_focus_target)

    def lep_bait_plan(self, lv, room, sleepers, gold_sq):
        """(sleeper, bait square, our square). The sleeper: the farthest from the hall's way out (a woken one runs
        off through it: lep_exit_dist) of those with squares for us. Our square: next to it, no monster, no gold
        (a leprechaun hitting us snatches the gold under us and teleports, steal.c); best one that cuts it off from
        every way out (the other leprechauns stay where they sleep), else the one that leaves it the longest way
        out, then the nearest to the way out. The bait: next to our square, no monster; the farthest from the way
        out. None: no such squares."""
        g = self.obs["glyphs"]
        k = G.KIND[lv.under]
        here = self.pos()
        free = {p for p in room if k[p] in (G.FLOOR, G.GOLD, G.CORPSE, G.OBJECT)
                and (G.KIND[int(g[p])] != G.MONSTER or p == here)}
        out = self.lep_exit_dist(lv, room)
        if not out:
            return None
        far = len(room) + 1                                    # no way out left
        for t in sorted(sleepers, key=lambda t: -out.get(t, 0)):
            best = None
            for a in free:
                if a in gold_sq or max(abs(a[0] - t[0]), abs(a[1] - t[1])) != 1:
                    continue
                baits = [d for d in free if d != a and max(abs(d[0] - a[0]), abs(d[1] - a[1])) == 1]
                if not baits:
                    continue
                left = self.lep_exit_dist(lv, room, blocked=(self.lep_now - {t}) | {a}).get(t, far)
                score = (-left, out.get(a, far))
                if best is None or score < best[0]:
                    best = (score, a, max(baits, key=lambda d: out.get(d, 0)))
            if best:
                self.thief_stats["lep_bait_exit_dist"] += out.get(t, 0)
                self.thief_stats["lep_bait_cut_off" if -best[0][0] == far else "lep_bait_not_cut_off"] += 1
                return t, best[2], best[1]
        return None

    def lep_exit_dist(self, lv, room, blocked=()):
        """Square of the hall -> moves to its nearest way out seen (lep_exits), through the hall but its blocked
        squares; none: not in it."""
        dist = self.lep_room_bfs(set(room) - set(blocked), self.lep_exits(lv, room))
        return {q: n for q, n in dist.items() if q in room}

    def lep_bait_walk(self, lv, squares):
        mask = np.zeros(lv.under.shape, dtype=bool)
        for p in squares:
            mask[p] = True
        status, _ = self.walk_to(lv, mask, max_cost=60, act="lep_bait")
        return status == "moved"

    def lep_approach(self, lv, room):
        """lep_stash, our gold stashed and the hall not cleared: an awake leprechaun in view and none next to us
        -- after it, within the hall (out of it: we wait); sleepers next to us wait (hitting one wakes another);
        none awake in view and none next to us -- to the nearest of the hall's (none in view: its floor). True if
        it used the turn."""
        y, x = self.pos()
        adj = {p for p in self.lep_now if max(abs(p[0] - y), abs(p[1] - x)) == 1}
        if adj & self.lep_awake or (adj and not self.lep_awake):
            return False                                       # the melee step (lep_focus_target)
        if self.lep_awake and (y, x) in room:
            return self.lep_chase(lv, room)
        mask = np.zeros(lv.under.shape, dtype=bool)
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

    def lep_chase(self, lv, room):
        """lep_stash, in the hall, an awake leprechaun in view and none next to us: a step after it, within the hall
        -- of the steps (and staying) that leave us nearest to it, the one nearest to its nearest way out (staying
        if as good); none (it is out of the hall, or no way to it in it): we wait. The one we hit is chased
        first, else the nearest. Uses the turn."""
        y, x = self.pos()
        cheb = lambda p, q: max(abs(p[0] - q[0]), abs(p[1] - q[1]))
        mon = G.KIND[self.obs["glyphs"]] == G.MONSTER
        passable = self.grids(lv)[2]
        lep = min(self.lep_sure & self.lep_awake or self.lep_awake, key=lambda p: cheb(p, (y, x)))
        walk = {p for p in room if passable[p] and (not mon[p] or p == (y, x))}
        to_lep = self.lep_room_bfs(walk, {p for p in walk if cheb(p, lep) == 1})
        exits = self.lep_exits(lv, room)
        from_lep = self.lep_room_bfs(room | exits, {lep})
        out = [e for e in exits if e in from_lep]
        to_exit = self.lep_room_bfs(room, {min(out, key=lambda e: from_lep[e])}) if out else {}
        far = len(room) + 1
        options = [p for p in walk if cheb(p, (y, x)) <= 1 and p in to_lep]     # a step, or staying
        best = min(options, key=lambda p: (to_lep[p], to_exit.get(p, far), p != (y, x))) if options else None
        if best is not None and sum(1 for p in options if to_lep[p] == to_lep[best]) > 1:
            self.thief_stats["lep_chase_tie"] += 1             # statistics: the way out decided
        if best is None or best == (y, x):
            self.press("s")                                    # out of the hall, or no better: we wait in it
            self.thief_stats["lep_chase_wait"] += 1
            return True
        self.cur_act = "lep_hall"
        self.move(best)
        self.thief_stats["lep_chase"] += 1
        return True

    @staticmethod
    def lep_room_bfs(walk, sources):
        """Square -> king moves from the nearest of sources, over the squares of walk (sources count as walked
        on but are not walked through unless in walk)."""
        dist = {q: 0 for q in sources}
        todo = list(sources)
        while todo:
            nxt = []
            for a, b in todo:
                if (a, b) not in walk and dist[(a, b)] > 0:
                    continue
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        q = (a + dy, b + dx)
                        if q in walk and q not in dist:
                            dist[q] = dist[(a, b)] + 1
                            nxt.append(q)
            todo = nxt
        return dist

    def lep_exits(self, lv, room):
        """The hall's ways out seen: a door, a doorway or a corridor next to its floor."""
        k = G.KIND[lv.under]
        h, w = lv.under.shape
        exits = set()
        for a, b in room:
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    q = (a + dy, b + dx)
                    if 0 <= q[0] < h and 0 <= q[1] < w and q not in room and \
                            (k[q] in (G.DOOR_OPEN, G.DOOR_CLOSED, G.DOORWAY) or int(lv.under[q]) in CORRIDOR_GLYPHS):
                        exits.add(q)
        return exits

    def lep_focus_target(self, lv, hostiles):
        """lep_stash: the leprechaun to hit among those next to us -- an awake one (lep_track), the one we hit
        last first, so one is fought until it dies instead of waking the next; none awake: the sleeper baited, from
        our square of the bait plan (lep_bait_step); None: no preference."""
        if not self.opts.lep_stash:
            return None
        adj = [p for p, n in hostiles if n == "leprechaun" and p in self.lep_awake]
        if not adj:
            bait = self.lep_bait.get(lv.key)
            plan = bait and bait["plan"]
            if plan and self.pos() == plan[2] and any(p == plan[0] for p, _ in hostiles):
                return plan[0]                                 # the sleeper baited (lep_bait_step)
            return None
        return self.last_attack_target if self.last_attack_target in adj else adj[0]

    def lep_melee_cands(self, hostiles):
        """lep_stash: the hostiles next to us the melee step may hit -- any other one before a leprechaun; a
        sleeping leprechaun not while an awake one is in view (one is woken at a time)."""
        if not self.opts.lep_stash:
            return hostiles
        other = [(p, n) for p, n in hostiles if n != "leprechaun"]
        if other:
            return other
        if self.lep_awake:
            return [(p, n) for p, n in hostiles if p in self.lep_awake]
        return hostiles

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

    def lep_hall_note(self, lv):
        """lep_stash, lep_nogold, every tick: the floor of this level's leprechaun hall (lep_room: seen part by
        part, kept) until it is cleared -- we are in it and no leprechaun is in view. The floor, or None."""
        room = self.lep_hall_room(lv)
        if room is not None:
            self.lep_room[lv.key] = room | self.lep_room.get(lv.key, set())
        room = self.lep_room.get(lv.key)
        if room is not None and self.pos() in room and not self.lep_visible():
            self.lep_room.pop(lv.key)                          # in the hall, no leprechaun left in view: done
            self.thief_stats["lep_hall_cleared"] += 1
            return None
        return room

    def lep_gold_shut(self, lv):
        """Squares whose gold is not picked up: lep_stash -- our stashed gold while its hall is not cleared;
        lep_nogold -- the hall's floor while it is not (its leprechauns would steal it from us)."""
        shut = self.lep_stash_held(lv)
        if self.opts.lep_nogold and lv.key in self.lep_room:
            shut = shut | self.lep_room[lv.key]
        return shut

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
            if self.bag_moved:
                self.gold_flow["bag_in" if d < 0 else "bag_out"] += abs(d)      # gold_bag: ours all the same
            elif d > 0:
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
        self.bag_moved = False

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
