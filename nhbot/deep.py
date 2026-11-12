"""The water dead ends of the Dungeons of Doom: Medusa's level and the Castle.

Both lie at the bottom of the main dungeon (dungeon.def: the Castle is its last level, Dlvl 25-29; Medusa 1-4 levels
above it, Dlvl 21-28; ordinary levels between). On Medusa's level we arrive on an island (medusa.des: the up stairs
of medusa-1/-3/-4) or in a closed building whose only doors are secret and lead to the water (medusa-2); the down
stairs are on her island across the lake. The Castle has no stairs down: its trap doors are behind the raised
drawbridge and undiggable walls (castle.des). Neither has a hidden passage: searching their walls is what the bot
did there for 6-15 000 turns a game (3.7 kills per 500 turns, 4 points a turn) until gremlins, eels or hunger ended
it (auto/notes/deep-analysis.md).

At such a dead end -- back up the stairs we came by (never onto Medusa's island; from her level as soon as its lake
shows: the depth is reached) and walk about the ordinary level above for the rest of the game (the patrol). The
random monsters the game makes (1 in 70 turns, allmain.c) come at us by greedy steps (monmove.c m_move) and stay
stuck behind walls or across the water: on the level above we made 7.0 kills per 500 turns, 5.7 points a turn, and
lived half as long again. On that level its down stairs are hidden from explore (stairs_mask), which goes on taking
items and frontiers, and the holes, trap doors and level teleporters we know are never walked over
(passable_grid); where explore would search walls, we walk to the nearest square not seen for patrol_stale turns.
With no way up we may take (the Castle right below Medusa's level) the patrol is where we are, off the squares
next to water (castle.des puts giant eels and sharks in the moat). The level below Medusa's has its up stairs on
her island (her gaze: death without reflection): never taken (DeepState.no_up -- stairs_mask, revisit_up).
(A/B dead_end_patrol, accepted 2026-11-11: D1, 1000 games, the 133 seeds with base depth 21+ replayed: score
+4776 [+3784, +5809], depth -0.002; D2: +6015 [+4754, +7357].)

Removed experiments (auto/notes/deep-analysis.md on a/deep): medusa_dig -- a hole past Medusa on a dry square of
her island, or a shaft dug on the level above (13 games, 9 got past: depth +1.1, score +-0; the mazes below have
minotaurs) -- and medusa_dive -- the next hole at once down to the Castle (depth +1.25, score -12 k on 12 games);
next to the patrol neither paid, and the patrol made them unreachable. patrol_rise (the patrol higher up),
patrol_hp (it rests while hurt), patrol_look (far looks only every n-th turn) were never screened and were no-ops
by default. dead_end_dive and the farm_dlvl / farm_keys probe read the evaluation's key budget: no play may
(owner's rule).

The steps hang on methods explore calls, overridden here (the mixin comes first in Bot): explore itself, search_mode
-- the dead end is told where explore has nothing left but walls to search --, stairs_mask, passable_grid and
revisit_up.
"""
from collections import Counter

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import COLS, ROWS

MEDUSA_MIN, MEDUSA_MAX = 21, 28      # dungeon.def: medusa @ (-5, 4) of 25-29 levels
LAKE_MIN = 100                       # liquid squares known: Medusa's lake (its lit variants show several hundred from
                                     # the arrival island) -- not the pools of an overflowing fountain (fountain.c
                                     # dogushforth, a dozen), not the Castle's moat seen from the maze around it
MOAT_MIN = 3                         # ... with the drawbridge in our map: the Castle
DBRIDGE_GLYPHS = tuple(nh.GLYPH_CMAP_OFF + i for i in (35, 36, 37, 38))    # S_vodbridge .. S_hcdbridge: the Castle
WAY_OUT_GLYPHS = tuple(nh.GLYPH_CMAP_OFF + i for i in (54, 55, 57))     # S_hole, S_trap_door, S_level_teleporter
PATROL_R = 2                         # patrol: a square is near us within this many squares
PATROL_WAIT = 10                     # ... nothing stale in reach: search this many turns (the count: 3 keys); cut
                                     # short by something in view, single searches for as many turns


def dilate(mask):
    """mask grown by one square in the 8 directions (the squares next to a square of it, and itself)."""
    out = mask.copy()
    out[1:, :] |= mask[:-1, :]
    out[:-1, :] |= mask[1:, :]
    out[:, 1:] |= out[:, :-1].copy()
    out[:, :-1] |= out[:, 1:].copy()
    return out


class DeepState:
    """State of the water dead ends (DeepMixin)."""
    def __init__(self):
        self.kind = {}                 # level key -> "medusa" / "castle", once told (water_dead_end)
        self.no_up = set()             # level keys whose up stairs lead onto Medusa's island: never taken
        self.above = None              # the level key above a dead end we went back up to: its down stairs are
                                       # hidden; the patrol is there
        self.near_at = {}              # the patrol: level key -> the turn each square was last within
                                       # PATROL_R of us (0: never)
        self.wait_short = 0            # ... the turn until which the patrol waits by single searches
        self.mark = {}                 # summary: event -> (turn, score, kills) when it first happened
        self.once = set()              # summary: (event, level key) counted
        self.stats = Counter()


class DeepMixin:
    def deep_init(self):
        self.deep = DeepState()

    def deep_summary(self):
        """Game summary entry: the counters, and (turn, score, kills) at the first of each event."""
        if not self.deep.stats and not self.deep.kind:
            return {"deep": {}}
        return {"deep": dict(self.deep.stats, kinds={str(k[1]): v for k, v in self.deep.kind.items()},
                             **{k: list(v) for k, v in self.deep.mark.items()})}

    def deep_mark(self, event):
        """Count event; the first time, where the game stood."""
        self.deep.stats[event] += 1
        self.deep.mark.setdefault(event + "_at", (self.turn(), int(self.reward), self.combat.kill_count))

    def deep_once(self, event, lv):
        """Count event once a level."""
        if (event, lv.key) not in self.deep.once:
            self.deep.once.add((event, lv.key))
            self.deep.stats[event] += 1

    # ------------------------------------------------------------------ methods of other mixins, overridden
    def explore(self, lv):
        """explore.explore; first, on a deep level of the main dungeon: is this Medusa's level (told as soon as its
        water shows: the stairs up from below are closed at once), are we past it (summary)."""
        st = self.deep
        if lv.key[0] == 0 and lv.key[1] >= MEDUSA_MIN:
            if lv.key not in st.kind:
                self.water_dead_end(lv, self.grids(lv)[0])
            past = any(k == "medusa" and key[1] < lv.key[1] for key, k in st.kind.items())
            if past and "past_medusa_at" not in st.mark:
                self.deep_mark("past_medusa")
            if st.kind.get(lv.key) == "medusa" and self.back_up_step(lv, self.grids(lv)):
                return                                # her level is reached: nothing to explore on the island
        super().explore(lv)

    def search_mode(self, lv, grids):
        """explore has nothing left on this level but walls to search: at a water dead end, the way back up /
        the patrol instead (dead_end_step)."""
        if self.dead_end_step(lv, grids):
            return
        super().search_mode(lv, grids)

    def stairs_mask(self, lv, kind, k_mem=None):
        """mapmem.stairs_mask, less the up stairs that lead onto Medusa's island (no_up) and the down stairs of
        the level above a dead end we went back up to."""
        mask = super().stairs_mask(lv, kind, k_mem)
        if kind == G.UPSTAIR and lv.key in self.deep.no_up:
            mask[:] = False
        elif kind == G.DOWNSTAIR and lv.key == self.deep.above:
            mask[:] = False
        return mask

    def passable_grid(self, lv, k_mem, k_live):
        """mapmem.passable_grid, less the holes, trap doors and level teleporters our map shows on the level we
        patrol: a path over one (the only way to some corner) dropped us onto Medusa's island again and again, or
        past it into the mazes."""
        p = super().passable_grid(lv, k_mem, k_live)
        if lv.key == self.deep.above:
            p[np.isin(lv.terrain, WAY_OUT_GLYPHS)] = False
        return p

    def revisit_up(self, lv, grids):
        """explore.revisit_up -- never to Medusa's level: the stairs up to it end on her island."""
        if lv.key in self.deep.no_up:
            return False
        return super().revisit_up(lv, grids)

    # ------------------------------------------------------------------ which level this is
    def water_dead_end(self, lv, k_mem):
        """"medusa" if this level of the main dungeon, Dlvl 21-28, shows a lake (LAKE_MIN squares of water) or
        medusa-2's arrival building (medusa2_square) -- the up stairs of the level below it are closed from now on;
        "castle" if it shows water and the drawbridge, or water where the floor would not be dug, or water below
        Medusa's range. None: neither, as far as we see."""
        if lv.key[0] != 0 or lv.key[1] < MEDUSA_MIN:
            return None
        st = self.deep
        kind = st.kind.get(lv.key)
        if kind is not None:
            return kind
        water = int((k_mem == G.LIQUID).sum())
        if water < MOAT_MIN:
            return None
        if lv.key[1] > MEDUSA_MAX or lv.key in self.digging.refused or np.isin(lv.terrain, DBRIDGE_GLYPHS).any():
            kind = "castle"
        elif water >= LAKE_MIN or self.medusa2_square(k_mem, np.ones((ROWS, COLS), dtype=bool)) is not None:
            kind = "medusa"
            st.no_up.add((lv.key[0], lv.key[1] + 1))
            lv.unexplored = False
        else:
            return None
        st.kind[lv.key] = kind
        st.stats[kind] += 1
        return kind

    @staticmethod
    def medusa2_square(k_mem, bare):
        """medusa.des medusa-2: the up stairs at (4, 9) in a closed building, columns 2-5 between walls at 1 and 6,
        with pool at (5, 13), (5, 14), (5, 15) -- told by those three below-right of the stairs and the walls left
        and right of the stairs' row. The lake lies behind the west wall (column 0) and from column 8 on: a square
        of the stairs' column, rows 5-11, has no water around it. The one below the stairs, or the one above; None
        if this is not that building."""
        ys, xs = np.nonzero(k_mem == G.UPSTAIR)
        for y, x in zip(ys.tolist(), xs.tolist()):
            if y + 6 < ROWS and x + 2 < COLS and x >= 3 and y >= 1 \
                    and all(k_mem[y + d, x + 1] == G.LIQUID for d in (4, 5, 6)) \
                    and k_mem[y, x - 3] == G.WALL and k_mem[y, x + 2] == G.WALL:
                for q in ((y + 1, x), (y - 1, x)):
                    if bare[q]:
                        return q
        return None

    def dead_end_step(self, lv, grids):
        """Where explore would search walls. On the level above a dead end we came back up to: the patrol. At a
        water dead end: the way back up, or the patrol here. True if it used the turn."""
        if self.deep.above == lv.key:
            return self.patrol_step(lv, grids)
        kind = self.water_dead_end(lv, grids[0])
        if kind is None:
            return False
        self.deep_once("dead_end_" + kind, lv)
        return self.dead_end_leave_step(lv, grids)

    # ------------------------------------------------------------------ the patrol
    def back_up_step(self, lv, grids):
        """A step to the up stairs of a dead end, and up them -- the level above is where the patrol is -- unless
        that level may be Medusa's (the Castle reached by a fall past levels we never saw). True if it used the
        turn."""
        st = self.deep
        above = (lv.key[0], lv.key[1] - 1)
        up = self.stairs_mask(lv, G.UPSTAIR, grids[0])
        if not up.any() or st.kind.get(above) == "medusa" \
                or not (above in self.levels or st.kind.get(lv.key) == "medusa"):
            return False
        if up[self.pos()]:
            st.above = above
            self.deep_mark("back_up")
            self.cur_act = "patrol"
            self.take_stairs("<")
            return True
        return self.walk_to(lv, up, act="patrol", grids=grids)[0] == "moved"

    def dead_end_leave_step(self, lv, grids):
        """At a dead end: back up (back_up_step); with no way up we may take, the patrol is here. True if it used
        the turn."""
        st = self.deep
        if self.back_up_step(lv, grids):
            return True
        st.above = lv.key
        self.deep_once("patrol_here", lv)
        return self.patrol_step(lv, grids)

    def patrol_step(self, lv, grids):
        """A step of the patrol: toward the nearest square in reach that was not within PATROL_R of us for
        patrol_stale turns (never a trap, never next to water); none: search PATROL_WAIT turns. Always True."""
        st = self.deep
        k_mem, k_live, passable = grids
        t = self.turn()
        near_at = st.near_at.get(lv.key)
        if near_at is None:
            near_at = st.near_at[lv.key] = np.zeros((ROWS, COLS), dtype=np.int64)
            self.deep_mark("patrol")
        y, x = self.pos()
        near_at[max(0, y - PATROL_R):y + PATROL_R + 1, max(0, x - PATROL_R):x + PATROL_R + 1] = t
        lv.progress_here = lv.turns_here              # walking about is no stall: no desperation (step_progress)
        stale = passable & ((near_at == 0) | (t - near_at > self.opts.patrol_stale)) & (k_mem != G.TRAP) \
            & ~dilate(k_mem == G.LIQUID)
        self.cur_act = "patrol"
        if stale.any() and self.walk_to(lv, stale, act="patrol", grids=grids)[0] == "moved":
            return True
        st.stats["patrol_waits"] += 1
        if t < st.wait_short:
            self.press("s")                           # the counted search was cut short just now: one key a turn
            return True
        self.search_turns(PATROL_WAIT)
        if self.turn() - t <= 1:                      # something in view stops it every turn (3 keys each)
            st.wait_short = self.turn() + PATROL_WAIT
        return True
