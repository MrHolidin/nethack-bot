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
hunger -- Weak with no prayer to be had (step_pray acts before us) the level has nothing more for us.

The final dive (pace_dive): with that many keys left of the budget, everything optional stops and we go down the
first stairs we find: a truncated game cannot die, each new level is 50 points (1000 below Dlvl 20) and depth.
"""
from collections import Counter

import nle.nethack as nh

from nhbot.consts import WEAK

WAIT_COUNT = 20             # turns of one counted search at the gate with nothing in view (3 keys)
WAIT_COUNT_SEEN = 5         # ... with a hostile in view that no step went for (2 keys)


class PaceState:
    """State of the strength gate and the final dive (PaceMixin)."""
    def __init__(self):
        self.since = {}                  # level key -> Level.turns_here when its gate first closed
        self.opened = set()              # level keys whose gate a valve opened for good
        self.turns = 0                   # turns waited at the gate (summary 'pace')
        self.keys = 0                    # keys sent for them
        self.stats = Counter()           # holds (levels gated), valve_time, valve_food (ticks), dive (levels)
        self.dive_from = None            # (turn, depth) the final dive began at
        self.hold = None                 # the hold in progress: [level key, depth, turn, XL, exp] at its start
        self.log = []                    # holds over: [key, depth, turn, XL, exp, turn, XL, exp, how it ended]


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
        if self.bl(nh.NLE_BL_XP) >= self.pace_need(self.bl(nh.NLE_BL_DEPTH) + 1):
            return self.pace_hold_end("xl")
        if lv.key not in self.pace.since:
            self.pace.since[lv.key] = lv.turns_here
            self.pace.stats["holds"] += 1
        if lv.turns_here - self.pace.since[lv.key] >= self.opts.pace_wait:
            self.pace.opened.add(lv.key)
            self.pace.stats["valve_time"] += 1
            return self.pace_hold_end("time")
        if self.bl(nh.NLE_BL_HUNGER) >= WEAK:
            self.pace.stats["valve_food"] += 1
            return self.pace_hold_end("food")
        if self.pace.hold is None:
            self.pace.hold = [list(lv.key)] + self.pace_now()
        return True

    def pace_now(self):
        return [int(self.bl(f)) for f in (nh.NLE_BL_DEPTH, nh.NLE_BL_TIME, nh.NLE_BL_XP, nh.NLE_BL_EXP)]

    def pace_hold_end(self, how):
        """The gate lets us through (how: "xl", "time", "food", "dive"; "end": the game is over): the hold in
        progress goes to the log (summary 'pace'). False."""
        if self.pace.hold is not None:
            self.pace.log.append(self.pace.hold + self.pace_now()[1:] + [how])
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

    def pace_summary(self):
        if not self.opts.pace and not self.opts.pace_dive:
            return {}
        self.pace_hold_end("end")
        return {"pace": dict(self.pace.stats, turns=self.pace.turns, keys=self.pace.keys,
                             dive_from=self.pace.dive_from, log=self.pace.log)}
