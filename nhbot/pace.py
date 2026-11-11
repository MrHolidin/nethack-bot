"""Pace: how fast we go down, against how strong we are (option `pace`; off: nothing here runs).

Why. The score is ~4 x the experience points (botl.c botl_score: u.urexp, raised 4 * exp per kill in exper.c
more_experienced), plus 50 a level reached (1000 below Dlvl 20). The game makes a random monster about every 70
turns on any level (allmain.c moveloop: !rn2(70), 50 below the Castle), of level at most (depth + XL) / 2 (makemon.c
rndmonst: maxmlev = (zlevel + u.ulevel) / 2) -- so turns spent waiting come back as kills, experience, HP and
score; turns cost nothing, only keys are limited (Bot.max_steps) and a counted search is 3 keys for 20 turns.
On base_d1 (983 games) the chance to die on a level falls steeply with the XL we arrive with: Dlvl 7-8 at XL 4-5
14-22 %, at XL 8-9 3-8 %; Dlvl 10-12 at XL 6-9 11-24 %, at XL 10-11 9-12 %; Dlvl 13-15 at XL 8-9 9-14 %, at
XL 10-11 3-5 %.

What. A strength gate on the stairs down (pace_gate, asked by explore.go_down as we stand on them): no descent to
depth d below the experience level the schedule `pace` asks for d. Gated, we wait on the staircase (pace_wait: a
counted search -- the fight, food, prayer and Elbereth steps before explore go on as ever; NetHack 3.6 lets us
engrave on stairs, consts.NO_ENGRAVE_CMAP). Valves: pace_wait turns on a level since its gate first closed, and
hunger -- Weak with no prayer to be had (step_pray acts before us) the level has nothing more for us; pace_food
opens it earlier, below that much nutrition (survival.nutrition_tick's estimate).

Food is what waiting costs: a turn burns a point of nutrition, and a prayer for hunger is no free meal -- one
said less than rnz(350) - 200 turns after the last angers the god (pray.c can_pray: u.ublesscnt > 200 in major
trouble; ~8 % of prayers 850 turns apart), and an angry god never helps again. First screens (500 games, valve
at Weak only): prayers a game 2.4 -> 5-9, games with an angry god 4 % -> 30-40 %, deaths by starvation x 3-5.
So the gate may only hold us where the kills feed us: pace_food.

The final dive (pace_dive): with that many keys left of the budget, everything optional stops and we go down the
first stairs we find: a truncated game cannot die, each new level is 50 points (1000 below Dlvl 20) and depth.
"""
from collections import Counter

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import WEAK

WAIT_COUNT = 20             # turns of one counted search at the gate with nothing in view (3 keys)
WAIT_COUNT_SEEN = 5         # ... with a hostile in view that no step went for (2 keys)
PATROL_HP = 0.8             # a patrol trip only from this fraction of max HP on
PATROL_MAX = 150            # path cost at most to a patrol goal; turns at most on the way out


class PaceState:
    """State of the strength gate and the final dive (PaceMixin)."""
    def __init__(self):
        self.since = {}                  # level key -> Level.turns_here when its gate first closed
        self.opened = set()              # level keys whose gate a valve opened for good
        self.turns = 0                   # turns waited at the gate (summary 'pace')
        self.keys = 0                    # keys sent for them
        self.stats = Counter()           # holds (levels gated), valve_time, valve_food (ticks), dive (levels)
        self.dive_from = None            # (turn, depth) the final dive began at
        self.hold = None                 # the hold in progress: level key, depth, pace_now() at its start
        self.log = []                    # holds over: ... and pace_now() at the end, how it ended
        # pace_patrol: the level patrolled, the square we walk to (None: waiting on the stairs), the turn the
        # next trip starts / this one is given up, the last goals (the next one lies away from them)
        self.patrol_key, self.patrol_goal, self.patrol_next, self.patrol_until = None, None, 0, 0
        self.patrol_seen = []


class PaceMixin:
    def pace_init(self):
        self.pace = PaceState()

    def pace_need(self, depth):
        """The experience level the schedule asks for before going down to depth: `pace` is a list of
        [depth, XL] -- from that depth on, at least that XL (the last entry at or above depth counts)."""
        need = 0
        for d, xl in self.opts.pace or ():
            if depth >= d:
                need = xl
        return need

    def pace_diving(self):
        """The final dive is on: fewer than pace_dive keys of the budget are left."""
        if not self.opts.pace_dive or self.steps < self.max_steps - self.opts.pace_dive:
            return False
        if self.pace.dive_from is None:
            self.pace.dive_from = (self.turn(), self.bl(nh.NLE_BL_DEPTH))
        return True

    def pace_gate(self, lv):
        """The gate of this level's stairs down is closed: we are below the XL asked for the next depth, no valve
        is open (pace_wait turns here since it first closed; Weak or worse -- step_pray had no prayer) and the
        final dive is not on."""
        if not self.opts.pace or lv.key in self.pace.opened:
            return False
        if self.pace_diving():
            return self.pace_hold_end("dive")
        # pace_ac: armor counts as strength too -- base_d1, Dlvl 9-12 at XL 10-11: 2.8 % die on a level at AC -7 or
        # better, 7 % at -6..-4, 14 % at -3..0; XL 8-9 at AC <= -7 does as well as XL 10-11 at -6..-4
        strength = self.bl(nh.NLE_BL_XP) - self.opts.pace_ac * self.bl(nh.NLE_BL_AC)
        if strength >= self.pace_need(self.bl(nh.NLE_BL_DEPTH) + 1):
            return self.pace_hold_end("xl")
        if lv.key not in self.pace.since:
            self.pace.since[lv.key] = lv.turns_here
            self.pace.stats["holds"] += 1
        if lv.turns_here - self.pace.since[lv.key] >= self.opts.pace_wait:
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
        """The gate lets us through (how: "xl", "time", "food", "dive"; "end": the game is over): the hold in
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

    def pace_summary(self):
        if not self.opts.pace and not self.opts.pace_dive:
            return {}
        self.pace_hold_end("end")
        return {"pace": dict(self.pace.stats, turns=self.pace.turns, keys=self.pace.keys,
                             dive_from=self.pace.dive_from, log=self.pace.log)}
