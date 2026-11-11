"""Pace: how fast we go down, against how strong we are (option `pace`; off: nothing here runs).

Why. The score is ~4 x the experience points (botl.c botl_score: u.urexp, raised 4 * exp per kill in exper.c
more_experienced), plus 50 a level reached (1000 below Dlvl 20). The game makes a random monster about every 70
turns on any level (allmain.c moveloop: !rn2(70), 50 below the Castle), of level at most (depth + XL) / 2 (makemon.c
rndmonst: maxmlev = (zlevel + u.ulevel) / 2) -- so turns spent waiting come back as kills, experience, HP and
score. On base_d1 the chance to die on a level falls with the XL and the AC we arrive with (Dlvl 9-12: XL 8-9
12-18 % a level, XL 10-11 9 %; at XL 10-11 2.8 % with AC -7 or better, 14 % at -3..0; max HP adds nothing), and
Dlvl 10-12 is where exploring is deadliest: 0.24 deaths per 1000 turns, 0.31-0.44 on Dlvl 10 and 12.

What. A strength gate on the stairs down (pace_gate, asked by explore.go_down): no descent to depth d below the
strength the schedule `pace` asks for d -- XL, or XL - pace_ac * AC. Gated, we hold: wait on the staircase
(pace_wait: a counted search, 3 keys for 20 turns; the fight, food, prayer and Elbereth steps before explore go on
as ever, the drops of our kills are fetched) -- or by it where at most two can reach us (pace_spot). The hold
ends with the strength reached, after the entry's cap of turns on the level, or by hunger.

What a hold is (500-game screens against base_d1, hold logs):
  * the monsters come to us: 8-18 kills per 1000 turns standing on the stairs of an ordinary level, the game's
    creation rate is 14 (on Medusa's island they cannot: water). 0.35-0.7 keys a turn, fights included.
  * experience per turn grows with depth as the monsters' level does: 0.01-0.07 on Dlvl 1-5, 0.3-0.6 on 9-12,
    ~1.1 on 13-19 -- on Dlvl 9-12 the same rate as exploring there.
  * deaths per 1000 turns of a level held on: Dlvl 9: 0.054, 12: 0.09, 17 and 20: 0.04 -- a fifth of exploring
    Dlvl 10-12, no better than exploring Dlvl 17-20 (0.06-0.11). So a hold before Dlvl 10-12 pays, a capped hold
    further down only adds a level's worth of deaths (per arrival, Dlvl 17: 4.9 % -> 12.7 %, Dlvl 20: 4.5 % -> 15.8 %).
  * food is what it costs: a turn burns a point of nutrition, the corpses of the kills give back ~0.1 on Dlvl 2-5
    and ~0.5 on Dlvl 8-12; the rest is prayer, and a prayer for hunger is no free meal -- said less than
    rnz(350) - 200 turns after the last it angers the god for good (pray.c can_pray: u.ublesscnt > 200 in major
    trouble; ~8 % of prayers 850 turns apart, 1.5 % at 1500). A gate on Dlvl 2-6 (XL 3..8) lost for that: prayers
    a game 2.4 -> 5-9, an angry god in 30-40 % of the games (4 %), starvation x 3-5 -- for no experience.
    pace_food / pace_pray open the gate on an emptying stomach unless a safe prayer is ahead.
  * pace=[[10,10],[13,11],[18,12],[21,13]], 5000 turns a level (pace_late_s): score +9255 [+6331, +12316], depth
    -0.43 [-0.70, -0.15], J +0.304 [+0.174, +0.440]. The gain is the weak half of the arrivals on Dlvl 9
    (XL - AC/2 <= 9: 30-43 k -> 41-73 k); the depth is lost in the holds on Dlvl 17 and 20.
"""
from collections import Counter

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import COLS, CORRIDOR_GLYPHS, FLOOR_GLYPH, NEIGH, ROWS, WEAK

WAIT_COUNT = 20             # turns of one counted search at the gate with nothing in view (3 keys)
WAIT_COUNT_SEEN = 5         # ... with a hostile in view that no step went for (2 keys)
RETREAT_AFTER = 200         # pace_retreat: turns searched on a level of water (Medusa's) before we leave it
RETREAT_SLOW = 1500         # ... on any other level: base_d1/d2, levels from Dlvl 20 on that we got past -- 6.7 %
                            # were searched for more than 200 turns, 1.9 % for more than 1500
RETREAT_WATER = 60          # squares of water we remember: Medusa's level (medusa-1..4.des: an island in a lake)
SPOT_MAX = 25               # pace_spot: path cost at most from the stairs to the square we hold on
SPOT_EVERY = 500            # ... chosen again after this many turns (the map may have grown)
PATROL_HP = 0.8             # a patrol trip only from this fraction of max HP on
PATROL_MAX = 150            # path cost at most to a patrol goal; turns at most on the way out


class PaceState:
    """State of the strength gate (PaceMixin)."""
    def __init__(self):
        self.since = {}                  # level key -> Level.turns_here when its gate first closed
        self.opened = set()              # level keys whose gate a valve opened for good
        self.turns = 0                   # turns waited at the gate (summary 'pace')
        self.keys = 0                    # keys sent for them
        self.stats = Counter()           # holds (levels gated), valve_time, valve_food (ticks), patrols, retreats
        self.hold = None                 # the hold in progress: level key, depth, pace_now() at its start
        self.log = []                    # holds over: ... and pace_now() at the end, how it ended
        # pace_patrol: the level patrolled, the square we walk to (None: waiting on the stairs), the turn the
        # next trip starts / this one is given up, the last goals (the next one lies away from them)
        self.patrol_key, self.patrol_goal, self.patrol_next, self.patrol_until = None, None, 0, 0
        self.patrol_seen = []
        self.forever = set()             # pace_retreat: levels we hold on for good (the one below has no way on)
        self.spot = (None, 0, None)      # pace_spot: (level key, turn chosen, the square we hold on or None)


class PaceMixin:
    def pace_init(self):
        self.pace = PaceState()

    def pace_need(self, depth):
        """(the experience level the schedule asks for before going down to depth, the turns at most a hold for
        it lasts on one level): `pace` is a list of [depth, XL] or [depth, XL, turns] -- from that depth on, at
        least that XL (the last entry at or above depth counts); turns: pace_wait unless the entry has its own."""
        need, wait = 0, self.opts.pace_wait
        for d, xl, *cap in self.opts.pace or ():
            if depth >= d:
                need, wait = xl, cap[0] if cap else self.opts.pace_wait
        return need, wait

    def pace_gate(self, lv):
        """The gate of this level's stairs down is closed: we are below the XL asked for the next depth, no valve
        is open (pace_wait turns here since it first closed; Weak or worse -- step_pray had no prayer)."""
        if lv.key in self.pace.forever:
            # pace_retreat: the level below has no way on -- nothing opens this gate, hunger neither (there is
            # no food for us down there)
            if self.pace.hold is None:
                self.pace.hold = dict(key=list(lv.key), depth=int(self.bl(nh.NLE_BL_DEPTH)), start=self.pace_now())
            return True
        if not self.opts.pace or lv.key in self.pace.opened:
            return False
        # pace_ac: armor counts as strength too -- base_d1, Dlvl 9-12 at XL 10-11: 2.8 % die on a level at AC -7 or
        # better, 7 % at -6..-4, 14 % at -3..0; XL 8-9 at AC <= -7 does as well as XL 10-11 at -6..-4
        strength = self.bl(nh.NLE_BL_XP) - self.opts.pace_ac * self.bl(nh.NLE_BL_AC)
        need, wait = self.pace_need(self.bl(nh.NLE_BL_DEPTH) + 1)
        if strength >= need:
            return self.pace_hold_end("xl")
        if lv.key not in self.pace.since:
            self.pace.since[lv.key] = lv.turns_here
            self.pace.stats["holds"] += 1
        if lv.turns_here - self.pace.since[lv.key] >= wait:
            self.pace.opened.add(lv.key)
            self.pace.stats["valve_time"] += 1
            return self.pace_hold_end("time")
        if self.bl(nh.NLE_BL_HUNGER) >= WEAK or (self.surv.nutrition < self.opts.pace_food
                                                 and not self.pace_prayer_ahead()):
            self.pace.stats["valve_food"] += 1
            return self.pace_hold_end("food")
        if self.pace.hold is None:
            self.pace.hold = dict(key=list(lv.key), depth=int(self.bl(nh.NLE_BL_DEPTH)), start=self.pace_now())
        return True

    def pace_holding(self, lv):
        """A hold is on at this level's gate (it began when pace_gate first found it closed; no side effect)."""
        return self.pace.hold is not None and self.pace.hold["key"] == list(lv.key)

    def pace_prayer_ahead(self):
        """pace_pray: the prayer we will say when Weak (step_pray) comes at least pace_pray turns after the last one
        -- late enough to be safe (pray.c can_pray: major trouble is helped while u.ublesscnt <= 200, set to
        rnz(350) by the last prayer: above 1700 for 1.5 % of them, above 2200 for 0.4 %), so the gate may stay
        closed on an emptying stomach. The first prayer of a game: its timeout began at 300."""
        if not self.opts.pace_pray or self.surv.god_angry:
            return False
        weak_at = self.turn() + max(0, self.surv.nutrition - 49)       # eat.c newuhs: Weak below 50
        return weak_at - (self.surv.last_pray or 0) >= self.opts.pace_pray

    def pace_now(self):
        """[turn, XL, experience points, kills, estimated nutrition, max HP, prayers, keys] now (the hold log)."""
        return [int(self.bl(f)) for f in (nh.NLE_BL_TIME, nh.NLE_BL_XP, nh.NLE_BL_EXP)] + \
            [self.combat.kill_count, self.surv.nutrition, int(self.bl(nh.NLE_BL_HPMAX)), self.surv.prayers,
             self.steps]

    def pace_hold_end(self, how):
        """The gate lets us through (how: "xl", "time", "food"; "end": the game is over): the hold in
        progress goes to the log (summary 'pace'). False."""
        if self.pace.hold is not None:
            self.pace.log.append(dict(self.pace.hold, end=self.pace_now(), how=how))
            self.pace.hold = None
        return False

    def pace_wait(self, lv):
        """Gated, on the stairs down: a counted search (the game stops it when something shows up or hits us:
        monmove.c dochugw, mhitu.c mattacku nomul(0)). Waiting is no stall: the level's progress clock is kept
        fresh (policy.step_progress would call it desperate after 1500 turns and melee what we never melee)."""
        t0, k0 = self.turn(), self.steps
        self.cur_act = "pace"
        lv.progress_here, lv.last_progress = lv.turns_here, t0
        self.search_turns(WAIT_COUNT_SEEN if self.visible_hostiles(lv) else WAIT_COUNT)
        self.pace.turns += self.turn() - t0
        self.pace.keys += self.steps - k0
        return True

    def pace_patrol_step(self, lv, grids):
        """pace_patrol, gated: every pace_patrol turns a trip to a far square of the level and back -- the monsters
        the game makes come for us along the straight line (monmove.c m_move: the neighbour square nearest to
        us) and stand behind a wall until we move; a walk brings them out (kills are experience and food).
        Not with a hostile in view or below PATROL_HP. The way back is go_down's. True if it stepped."""
        p, t = self.pace, self.turn()
        if not self.opts.pace_patrol or self.visible_hostiles(lv) or self.hp_below(PATROL_HP):
            return False
        if p.patrol_key != lv.key:
            p.patrol_key, p.patrol_goal, p.patrol_next, p.patrol_seen = lv.key, None, t + self.opts.pace_patrol, []
        if p.patrol_goal is None:
            if t < p.patrol_next:
                return False
            p.patrol_goal, p.patrol_until = self.pace_patrol_goal(lv, grids), t + PATROL_MAX
            p.stats["patrols"] += p.patrol_goal is not None
        if p.patrol_goal is not None and t < p.patrol_until:
            mask = np.zeros_like(grids[2])
            mask[p.patrol_goal] = True
            if self.walk_to(lv, mask, act="pace", grids=grids)[0] == "moved":
                lv.progress_here, lv.last_progress = lv.turns_here, t      # no stall (pace_wait)
                p.stats["patrol_turns"] += self.turn() - t
                return True
        # there, out of reach or too long on the way: back to the stairs, the next trip pace_patrol turns from now
        if p.patrol_goal is not None:
            p.patrol_seen = (p.patrol_seen + [p.patrol_goal])[-3:]
        p.patrol_goal, p.patrol_next = None, t + self.opts.pace_patrol
        return False

    def pace_patrol_goal(self, lv, grids):
        """The square a patrol trip walks to: far from us by path (within PATROL_MAX) and away from the last
        goals -- so the trips go round the level; plain floor or corridor outside shops. None: nowhere to go."""
        k_mem, k_live, passable = grids
        dist, _, _ = self.dijkstra(lv, k_mem, k_live, passable, self.pos(), None, max_cost=PATROL_MAX)
        ok = passable & (dist <= PATROL_MAX) & (k_mem == G.FLOOR) & ~lv.shop
        if not ok.any():
            return None
        score = dist.astype(np.int64)
        ys, xs = np.indices(score.shape)
        for gy, gx in self.pace.patrol_seen:
            score = np.minimum(score, 3 * np.maximum(abs(ys - gy), abs(xs - gx)))
        score = np.where(ok, score, -1)
        best = np.unravel_index(np.argmax(score), score.shape)
        return (int(best[0]), int(best[1])) if score[best] > 5 else None

    def pace_spot_step(self, lv, grids, downstairs):
        """pace_spot, gated: hold where at most two can come at us at once -- a corridor square or an open door
        (no diagonal step through a door: hack.c test_move) within SPOT_MAX of the stairs -- not on the staircase
        in the open, where a pack stands all round us (the holds lost at Dlvl 9: four hill orcs, ants). True if
        it used the turn."""
        if not self.opts.pace_spot:
            return False
        key, t, spot = self.pace.spot
        if key != lv.key or self.turn() - t >= SPOT_EVERY:
            spot = self.pace_spot(lv, grids, downstairs)
            self.pace.spot = (lv.key, self.turn(), spot)
        if spot is None:
            return False
        if self.pos() == spot:
            return self.pace_wait(lv)
        mask = np.zeros_like(grids[2])
        mask[spot] = True
        if self.walk_to(lv, mask, act="pace", grids=grids)[0] == "moved":
            return True
        self.pace.spot = (lv.key, self.turn(), None)       # out of reach now: the stairs until chosen again
        return False

    def pace_spot(self, lv, grids, downstairs):
        """The square to hold on: plain floor, corridor or an open door within SPOT_MAX (by path) of the down
        staircase nearest to us, outside shops, with the fewest neighbours a monster can step at us from (at most
        two; the nearest to the stairs among equals). None: the staircase is as good as anything."""
        k_mem, k_live, passable = grids
        y, x = self.pos()
        stair = min(zip(*map(lambda a: a.tolist(), np.nonzero(downstairs))),
                    key=lambda p: max(abs(p[0] - y), abs(p[1] - x)), default=None)
        if stair is None:
            return None
        dist, _, _ = self.dijkstra(lv, k_mem, k_live, passable, stair, None, max_cost=SPOT_MAX)
        door = (k_mem == G.DOOR_OPEN) | (k_mem == G.DOOR_CLOSED) | lv.door_intact | lv.no_diag
        plain = np.isin(self.terrain_glyphs(lv), (FLOOR_GLYPH,) + CORRIDOR_GLYPHS) & (k_mem == G.FLOOR)
        ok = passable & (dist <= SPOT_MAX) & (plain | (k_mem == G.DOOR_OPEN)) & ~lv.shop
        best = None
        for sy, sx in zip(*map(lambda a: a.tolist(), np.nonzero(ok))):
            n, shop = 0, False
            for dy, dx in NEIGH:
                qy, qx = sy + dy, sx + dx
                if not (0 <= qy < ROWS and 0 <= qx < COLS):
                    continue
                shop |= bool(lv.shop[qy, qx])
                if passable[qy, qx] and not (dy and dx and (door[sy, sx] or door[qy, qx])):
                    n += 1
            if n and not shop and (best is None or (n, dist[sy, sx]) < best[0]):
                best = ((n, int(dist[sy, sx])), (sy, sx))
        return best[1] if best is not None and best[0][0] <= 2 else None

    def pace_retreat_step(self, lv, grids):
        """pace_retreat: a main-dungeon level at that depth or below with nothing left to explore, no way down and
        RETREAT_AFTER turns of searching behind us on Medusa's island (the way on is across the water;
        RETREAT_SLOW on a level without a lake: its stairs may be hidden) -- back up
        the stairs, to hold for good on the level above: its depth is ours already, and a hold on a staircase
        of an ordinary level is where the monsters come to us (on the island they cannot) at a third of the
        deaths per turn (base_d1 at Dlvl 21+: 0.15 per 1000 turns; holds at Dlvl 17-20: 0.04). True if it acted."""
        if not self.opts.pace_retreat or lv.key[0] != 0 or self.bl(nh.NLE_BL_DEPTH) < self.opts.pace_retreat \
                or lv.search_turns < RETREAT_AFTER:
            return False
        if lv.search_turns < RETREAT_SLOW and int((grids[0] == G.LIQUID).sum()) < RETREAT_WATER:
            return False
        up = self.stairs_mask(lv, G.UPSTAIR, grids[0])
        if not up.any():
            return False
        self.cur_act = "pace"
        if up[self.pos()]:
            self.pace.forever.add((lv.key[0], lv.key[1] - 1))
            self.pace.stats["retreats"] += 1
            self.take_stairs("<")
            return True
        return self.walk_to(lv, up, act="pace", grids=grids)[0] == "moved"

    def pace_summary(self):
        if not self.opts.pace and not self.opts.pace_retreat:
            return {}
        self.pace_hold_end("end")
        return {"pace": dict(self.pace.stats, turns=self.pace.turns, keys=self.pace.keys, log=self.pace.log)}
