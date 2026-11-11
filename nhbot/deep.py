"""The water dead ends of the Dungeons of Doom: Medusa's level and the Castle.

Both lie at the bottom of the main dungeon (dungeon.def: the Castle is its last level, Dlvl 25-29; Medusa 1-4 levels
above it, Dlvl 21-28; ordinary levels between). On Medusa's level we arrive on an island (medusa.des: the up stairs
of medusa-1/-3/-4) or in a closed building whose only doors are secret and lead to the water (medusa-2); the down
stairs are on her island across the lake. The Castle has no stairs down: its trap doors are behind the raised
drawbridge and undiggable walls (castle.des). Neither has a hidden passage: searching their walls is what the bot
did there for 6-15 000 turns a game, making 0.3 kills per 500 turns (6.4 while descending) until gremlins, eels or
hunger ended it (auto/notes/deep-analysis.md).

medusa_dig: past Medusa through the floor.
  - On her level, with a way to dig (digging.dig_means), a hole (vault.dig_down) -- medusa.des sets no hardfloor
    flag and the level is not the dungeon's last, so dungeon.c:1300 Can_dig_down holds. A hole (and the pit dug
    before it: dig.c:240 dig -> dighole) fills with water with chance n / (n + 1), n the moat squares among the 3 x 3
    around it (dig.c:504 fillholetyp), and we would fall in (trap.c drown: the inventory wet): we dig only on a
    square whose 8 neighbours we know and none is water (medusa-1's island, medusa-2's building, one islet of
    medusa-4 have such squares; medusa-3 has none).
  - With no such square: back up the stairs, and a hole dug on the ordinary level above -- or a trap door / hole
    our map knows there -- taken again and again: a fall goes one level further with chance 1/4 (trap.c:474
    fall_through; stepping onto the trap, not '>', which goes one level: do.c dodown -> next_level), past Medusa's
    level; else we land on the arrival island and climb back (SHAFT_JUMPS tries).
  The level below Medusa's has its up stairs on her island (her gaze: death without reflection): never taken
  (DeepState.no_up -- stairs_mask, revisit_up).

dead_end_patrol: at such a dead end with no way through -- back up the stairs we came by (never onto Medusa's
island) and walk about the ordinary level above for the rest of the game: the random monsters the game makes (1 in
70 turns, allmain.c) come at us by greedy steps (monmove.c m_move) and stay stuck behind walls -- a hero who stands
still meets few of them. On that level its down stairs are hidden from explore (stairs_mask), which goes on taking
items and frontiers; where it would search walls, we walk to the nearest square not seen for PATROL_STALE turns.
With no way up we may take (the Castle right below Medusa's level) the patrol is where we are, off the squares
next to water (castle.des puts giant eels and sharks in the moat).

The steps hang on methods explore calls, overridden here (the mixin comes first in Bot): search_mode -- the dead end
is told where explore has nothing left but walls to search --, stairs_mask, passable_grid, revisit_up; and
weapons.swap_back (the digger stays in our hands while the only hostiles in view are far). With both options off each override is the
method it replaces.
"""
from collections import Counter

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import COLS, CORRIDOR_GLYPHS, FLOOR_GLYPH, ROWS, WEAK

MEDUSA_MIN, MEDUSA_MAX = 21, 28      # dungeon.def: medusa @ (-5, 4) of 25-29 levels
LAKE_MIN = 100                       # liquid squares known: Medusa's lake (its lit variants show several hundred from
                                     # the arrival island) -- not the pools of an overflowing fountain (fountain.c
                                     # dogushforth, a dozen), not the Castle's moat seen from the maze around it
MOAT_MIN = 3                         # ... with the drawbridge in our map: the Castle
DBRIDGE_GLYPHS = tuple(nh.GLYPH_CMAP_OFF + i for i in (35, 36, 37, 38))    # S_vodbridge .. S_hcdbridge: the Castle
SHAFT_GLYPHS = (nh.GLYPH_CMAP_OFF + 54, nh.GLYPH_CMAP_OFF + 55)            # S_hole, S_trap_door
WAY_OUT_GLYPHS = SHAFT_GLYPHS + (nh.GLYPH_CMAP_OFF + 57,)                  # ... and S_level_teleporter
BARE_FLOOR = (FLOOR_GLYPH, nh.GLYPH_CMAP_OFF + 20) + tuple(CORRIDOR_GLYPHS)   # S_room, S_darkroom, corridors
DIG_HP = 0.7                         # rest before the hole / the jump below this share of max HP (we land among
                                     # strangers)
DIG_APPLIES = 40                     # applies / zaps at most on one level
DIG_NEAR = 3                         # a hostile within this many squares: the weapon back in our hands
SHAFT_JUMPS = 12                     # falls from the level above Medusa's at most (0.75 ** 12: 3 % never get past)
PATROL_STALE = 400                   # patrol: a square not near us for this many turns is walked to again
PATROL_R = 2                         # ... near: within this many squares
PATROL_WAIT = 10                     # ... nothing stale in reach: search this many turns (the count: cheap keys)


def dilate(mask):
    """mask grown by one square in the 8 directions (the squares next to a square of it, and itself)."""
    out = mask.copy()
    out[1:, :] |= mask[:-1, :]
    out[:-1, :] |= mask[1:, :]
    out[:, 1:] |= out[:, :-1].copy()
    out[:, :-1] |= out[:, 1:].copy()
    return out


def one_square(sq):
    mask = np.zeros((ROWS, COLS), dtype=bool)
    mask[sq] = True
    return mask


class DeepState:
    """State of the water dead ends (DeepMixin)."""
    def __init__(self):
        self.kind = {}                 # level key -> "medusa" / "castle", once told (water_dead_end)
        self.dig = None                # medusa_dig: (level key, square) of the hole we are digging
        self.dig_bad = set()           # ... (level key, square) that filled with water or could not be reached
        self.applies = Counter()       # ... level key -> applies / zaps made
        self.shaft = {}                # ... level key -> the square of the hole we dug there
        self.jumps = Counter()         # ... level key -> steps onto its hole / trap door
        self.no_up = set()             # level keys whose up stairs lead onto Medusa's island: never taken
        self.above = None              # the level key above a dead end we went back up to: its down stairs are
                                       # hidden; the shaft (medusa_dig), the patrol (dead_end_patrol) are there
        self.rise_to = None            # dead_end_patrol, patrol_rise: the level key we climb to for the patrol
        self.diving = False            # dead_end_dive: the keys are nearly spent -- no patrol any more, down
        self.near_at = {}              # dead_end_patrol: level key -> the turn each square was last within
                                       # PATROL_R of us (0: never)
        self.mark = {}                 # summary: event -> (turn, score, kills) when it first happened
        self.once = set()              # summary: (event, level key) counted
        self.stats = Counter()


class DeepMixin:
    def deep_init(self):
        self.deep = DeepState()
        # game.digger_held: the pick-axe stays in our hands while we dig the hole (vault_rob_step puts it away)
        self.digger_holders.append(self.deep_digging)

    def deep_on(self):
        return self.opts.medusa_dig or self.opts.dead_end_patrol

    def deep_digging(self, lv):
        return self.deep.dig is not None and self.deep.dig[0] == lv.key

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
        if self.opts.farm_dlvl and lv.key == (0, self.opts.farm_dlvl):
            # farm_dlvl (a probe): this level is held, by the patrol, until farm_keys keys are spent
            if self.steps < self.opts.farm_keys:
                if st.above != lv.key:
                    st.above = lv.key
                    self.deep_mark("farm")
            elif st.above == lv.key:
                st.above = None
                self.deep_mark("farm_end")
        elif st.above is not None and not st.diving and self.max_steps - self.steps < self.opts.dead_end_dive:
            # dead_end_dive: the patrol is over -- down again (the stairs show), through the floor where we can
            st.diving, st.above, st.rise_to = True, None, None
            self.deep_mark("final_dive")
        if st.rise_to is not None and self.rise_step(lv):
            return
        if self.deep_on() and lv.key[0] == 0 and lv.key[1] >= MEDUSA_MIN:
            if lv.key not in st.kind:
                self.water_dead_end(lv, self.grids(lv)[0])
            past = any(k == "medusa" and key[1] < lv.key[1] for key, k in st.kind.items())
            if past and "past_medusa_at" not in st.mark:
                self.deep_mark("past_medusa")
            if past and (self.opts.medusa_dive or st.diving) and self.dive_step(lv):
                return
            if st.kind.get(lv.key) == "medusa" and self.opts.dead_end_patrol and not st.diving \
                    and self.back_up_step(lv, self.grids(lv)):
                return                                # her level is reached: nothing to explore on the island
        super().explore(lv)

    def dig_now(self):
        """medusa_dig acts now: at once without dead_end_patrol; with it, when the patrol is over (dead_end_dive)."""
        return self.opts.medusa_dig and (self.deep.diving or not self.opts.dead_end_patrol)

    def rise_step(self, lv):
        """patrol_rise: on the way up from the level above the dead end to the patrol level (DeepState.rise_to) by
        the stairs we know (explore.level_travel_step). True if it used the turn; with no way up known the patrol
        is where we are, for now."""
        st = self.deep
        if lv.key[0] != 0:
            st.rise_to = None                         # off the main dungeon (a trap sent us): no patrol to climb to
            return False
        st.above = lv.key                             # its down stairs hidden: while we pass, and where we stay
        if lv.key[1] <= st.rise_to[1]:
            st.rise_to = None
            return False
        # no way up in our map (we fell through this level): the patrol is here until its up stairs show
        return self.level_travel_step(lv, self.grids(lv), st.rise_to, "patrol", "patrol_rise")

    def search_mode(self, lv, grids):
        """explore has nothing left on this level but walls to search: at a water dead end, the hole / the way
        back up / the shaft / the patrol instead (dead_end_step)."""
        if (self.deep_on() or self.deep.above == lv.key) and self.dead_end_step(lv, grids):
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
        past it into the mazes. Not while the shaft is what we want (dig_now)."""
        p = super().passable_grid(lv, k_mem, k_live)
        if lv.key == self.deep.above and not self.dig_now():
            p[np.isin(lv.terrain, WAY_OUT_GLYPHS)] = False
        return p

    def revisit_up(self, lv, grids):
        """explore.revisit_up -- never to Medusa's level: the stairs up to it end on her island."""
        if lv.key in self.deep.no_up:
            return False
        return super().revisit_up(lv, grids)

    def swap_back(self, job=None):
        """weapons.swap_back -- not for a hostile merely in view (step_weapon) while we dig the hole: on Medusa's lit
        level something across the water is in view all the time, and the digger went in and out of our hands. A
        hostile within DIG_NEAR squares: the weapon back as ever."""
        if job is None and self.weapons.swapped_for == "dig" and self.deep.dig is not None \
                and self.deep.dig[0] == self.cur_key:
            y, x = self.pos()
            if not any(max(abs(p[0] - y), abs(p[1] - x)) <= DIG_NEAR
                       for p, _ in self.visible_hostiles(self.levels[self.cur_key])):
                return False
        return super().swap_back(job)

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

    def dead_end_step(self, lv, grids):
        """Where explore would search walls. On the level above a dead end we came back up to: the shaft
        (medusa_dig), the patrol (dead_end_patrol). At a water dead end: the hole (medusa_dig), else the way back up
        -- for the shaft or the patrol. True if it used the turn."""
        st = self.deep
        if st.above == lv.key:
            if self.dig_now() and self.shaft_step(lv, grids):
                return True
            if (self.opts.dead_end_patrol and not st.diving) or self.opts.farm_dlvl:
                return self.patrol_step(lv, grids)
            st.above = None                           # no shaft to take: as before (down again, the walls searched)
            return False
        kind = self.water_dead_end(lv, grids[0])
        if kind is None:
            return False
        self.deep_once("dead_end_" + kind, lv)
        if self.dig_now() and kind == "medusa" and self.medusa_dig_step(lv, grids):
            return True
        if (self.opts.dead_end_patrol and not st.diving) \
                or (self.dig_now() and kind == "medusa" and self.shaft_hope(lv)):
            return self.dead_end_leave_step(lv, grids)
        return False

    # ------------------------------------------------------------------ medusa_dig: the hole on her level
    def medusa_dig_step(self, lv, grids):
        """One step of the hole on Medusa's level (hole_step) on a dry square in reach. True if it used the turn;
        False: no way to dig here (no digger, the floor refused, no dry square, too many tries)."""
        st = self.deep
        if st.dig is not None and st.dig[0] != lv.key:
            st.dig = None
        means = self.dig_means()
        if means is None or lv.key in self.digging.refused or st.applies[lv.key] >= DIG_APPLIES:
            st.dig = None
            return False
        if st.dig is None:
            sq = self.medusa_dig_square(lv, grids)
            if sq is None:
                self.deep_once("no_dry_square", lv)
                return False
            st.dig = (lv.key, sq)
        return self.hole_step(lv, grids, means)

    def hole_step(self, lv, grids, means):
        """One step of the hole at DeepState.dig: rest first if hurt, walk to the square, dig (the pick-axe wielded
        by vault.dig_down; the pit, then the hole: two occupations, more when something comes into view). True if it
        used the turn."""
        st = self.deep
        sq = st.dig[1]
        if self.hp_below(DIG_HP) and not self.visible_hostiles(lv) and self.bl(nh.NLE_BL_HUNGER) < WEAK:
            self.cur_act = "rest"
            self.search_turns(20)
            return True
        if self.pos() != sq:
            if self.walk_to(lv, one_square(sq), act="medusa_dig", grids=grids)[0] == "moved":
                return True
            st.dig_bad.add(st.dig)
            st.dig = None
            return False
        kind, it = means
        if kind == "wand" or it.wielded:
            st.applies[lv.key] += 1
            self.deep_mark("dig")
        seq0 = self.msg_seq
        acted = self.dig_down(lv, means)
        self.cur_act = "medusa_dig"
        msgs = self.text_since(seq0)
        if "fills with" in msgs:                      # water we did not know of next to the square
            st.stats["dig_filled"] += 1
            st.dig_bad.add(st.dig)
            st.dig = None
        if "You dig a hole through" in msgs or "fall through" in msgs:
            self.deep_mark("dug_out")
            st.shaft[lv.key] = sq
            st.dig = None
        return acted

    def medusa_dig_square(self, lv, grids):
        """The square for the hole: bare floor in reach, its 8 neighbours all known and none of them water (dig.c
        fillholetyp), the nearest; in medusa-2's dark arrival building, whose walls hide what lies behind them, the
        square beside the up stairs (medusa2_square). None if there is none."""
        k_mem, k_live, passable = grids
        bare = self.bare_floor(lv, passable)
        sq = self.medusa2_square(k_mem, bare)
        if sq is not None:
            return sq
        dry = bare & ~dilate(k_mem == G.LIQUID) & ~dilate(k_mem == G.UNKNOWN)
        return self.nearest(lv, grids, dry)

    def bare_floor(self, lv, passable):
        """Squares we may dig a hole on: plain floor or corridor with nothing on it (not stairs, a fountain, an
        altar, a trap, a door: dig.c dig_check, dighole), not at the map's edge, not tried in vain."""
        bare = np.isin(lv.under, BARE_FLOOR) & passable
        bare[0, :] = bare[-1, :] = bare[:, 0] = bare[:, -1] = False
        for key, sq in self.deep.dig_bad:
            if key == lv.key:
                bare[sq] = False
        return bare

    def nearest(self, lv, grids, mask):
        """The square of mask nearest by path (our own if it is one); None."""
        if not mask.any():
            return None
        here = self.pos()
        if mask[here]:
            return here
        k_mem, k_live, passable = grids
        return self.dijkstra(lv, k_mem, k_live, passable, here, mask, want_dist=False)[2]

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

    def dive_step(self, lv):
        """medusa_dive: below Medusa's level (mazes four times in five -- mklev.c:1008 makelevel -- with their
        minotaurs, mkmaze.c) the next hole at once, where we stand or on the nearest bare floor, until the floor
        refuses: the Castle. True if it used the turn."""
        st = self.deep
        if st.dig is not None and st.dig[0] != lv.key:
            st.dig = None
        means = self.dig_means()
        if means is None or lv.key in self.digging.refused or st.applies[lv.key] >= DIG_APPLIES \
                or st.kind.get(lv.key) == "castle":
            st.dig = None
            return False
        grids = self.grids(lv)
        if st.dig is None:
            sq = self.nearest(lv, grids, self.bare_floor(lv, grids[2]) & ~dilate(grids[0] == G.LIQUID))
            if sq is None:
                return False
            st.dig = (lv.key, sq)
            self.deep_once("dive", lv)
        return self.hole_step(lv, grids, means)

    # ------------------------------------------------------------------ medusa_dig: the shaft from the level above
    def shaft_hope(self, lv):
        """On Medusa's level with no dry square: a fall from the level above may carry us past -- a digger for a
        hole there, or a hole / trap door our map of that level shows; not after SHAFT_JUMPS falls."""
        above = (lv.key[0], lv.key[1] - 1)
        if self.deep.jumps[above] >= SHAFT_JUMPS or above in self.digging.refused and above not in self.deep.shaft:
            return False
        prev = self.levels.get(above)
        return above in self.deep.shaft or self.dig_means() is not None \
            or (prev is not None and bool(np.isin(prev.terrain, SHAFT_GLYPHS).any()))

    def shaft_step(self, lv, grids):
        """On the level above Medusa's: onto the hole we dug here or a hole / trap door of our map (off it first if
        we stand on it: we escaped it, trap.c dotrap 1 in 5) -- or, with a digger, a hole dug where we stand or on
        the nearest bare floor. The fall goes past Medusa's level 1 time in 4. True if it used the turn; False:
        nothing to fall through, or SHAFT_JUMPS falls made."""
        st = self.deep
        if st.kind.get((lv.key[0], lv.key[1] + 1)) != "medusa" or st.jumps[lv.key] >= SHAFT_JUMPS:
            return False
        if st.dig is not None and st.dig[0] != lv.key:
            st.dig = None
        k_mem, k_live, passable = grids
        here = self.pos()
        shafts = np.isin(lv.terrain, SHAFT_GLYPHS) & passable
        if lv.key in st.shaft:
            shafts[st.shaft[lv.key]] = True
        if shafts.any() and st.dig is None:
            if self.hp_below(DIG_HP) and not self.visible_hostiles(lv) and self.bl(nh.NLE_BL_HUNGER) < WEAK:
                self.cur_act = "rest"
                self.search_turns(20)
                return True
            if shafts[here]:
                off = dilate(one_square(here)) & passable & ~shafts
                return self.walk_to(lv, off, act="shaft", grids=grids)[0] == "moved"
            status, reached = self.walk_to(lv, shafts, act="shaft", grids=grids)
            if status == "moved":
                if max(abs(reached[0] - here[0]), abs(reached[1] - here[1])) == 1:
                    st.jumps[lv.key] += 1
                    self.deep_mark("shaft_jump")
                return True
        means = self.dig_means()
        if means is None or lv.key in self.digging.refused or st.applies[lv.key] >= DIG_APPLIES:
            st.dig = None
            return False
        if st.dig is None:
            sq = self.nearest(lv, grids, self.bare_floor(lv, passable) & ~dilate(k_mem == G.LIQUID))
            if sq is None:
                return False
            st.dig = (lv.key, sq)
            st.jumps[lv.key] += 1                     # the hole we dig is the first fall
        return self.hole_step(lv, grids, means)

    # ------------------------------------------------------------------ dead_end_patrol
    def back_up_step(self, lv, grids):
        """A step to the up stairs of a dead end, and up them -- the level above is where the shaft or the patrol
        is -- unless that level may be Medusa's (the Castle reached by a fall past levels we never saw). True if it
        used the turn."""
        st = self.deep
        above = (lv.key[0], lv.key[1] - 1)
        up = self.stairs_mask(lv, G.UPSTAIR, grids[0])
        if not up.any() or st.kind.get(above) == "medusa" \
                or not (above in self.levels or st.kind.get(lv.key) == "medusa"):
            return False
        if up[self.pos()]:
            st.above = above
            if self.opts.patrol_rise and not st.diving and self.opts.dead_end_patrol:
                st.rise_to = (above[0], max(1, above[1] - self.opts.patrol_rise))
            self.deep_mark("back_up")
            self.cur_act = "patrol"
            self.take_stairs("<")
            return True
        return self.walk_to(lv, up, act="patrol", grids=grids)[0] == "moved"

    def dead_end_leave_step(self, lv, grids):
        """At a dead end with no hole to dig here: back up (back_up_step); with no way up we may take and
        dead_end_patrol, the patrol is here. True if it used the turn."""
        st = self.deep
        if self.back_up_step(lv, grids):
            return True
        if not self.opts.dead_end_patrol or st.diving:
            return False
        st.above = lv.key
        self.deep_once("patrol_here", lv)
        return self.patrol_step(lv, grids)

    def patrol_step(self, lv, grids):
        """A step of the patrol: toward the nearest square in reach that was not within PATROL_R of us for
        PATROL_STALE turns (never a trap, never next to water); none: search PATROL_WAIT turns. Always True."""
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
        if self.opts.patrol_hp and self.hp_below(self.opts.patrol_hp) and not self.visible_hostiles(lv) \
                and self.bl(nh.NLE_BL_HUNGER) < WEAK:
            self.cur_act = "rest"                     # patrol_hp: not on to the next stranger while hurt
            self.search_turns(20)
            return True
        stale = passable & ((near_at == 0) | (t - near_at > PATROL_STALE)) & (k_mem != G.TRAP) \
            & ~dilate(k_mem == G.LIQUID)
        self.cur_act = "patrol"
        if stale.any() and self.walk_to(lv, stale, act="patrol", grids=grids)[0] == "moved":
            return True
        st.stats["patrol_waits"] += 1
        self.search_turns(PATROL_WAIT)
        return True
