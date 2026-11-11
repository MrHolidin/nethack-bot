"""The water dead ends of the Dungeons of Doom: Medusa's level and the Castle.

Both lie at the bottom of the main dungeon (dungeon.def: the Castle is its last level, Dlvl 25-29; Medusa 1-4 levels
above it, Dlvl 21-28; ordinary levels between). On Medusa's level we arrive on an island (medusa.des: the up stairs
of medusa-1/-3/-4) or in a closed building whose only doors are secret and lead to the water (medusa-2); the down
stairs are on her island across the lake. The Castle has no stairs down: its trap doors are behind the raised
drawbridge and undiggable walls (castle.des). Neither has a hidden passage: searching their walls is what the bot
did there for 6-15 000 turns a game, making 0.3 kills per 500 turns (6.4 while descending) until gremlins, eels or
hunger ended it (auto/notes/deep-analysis.md).

medusa_dig: on Medusa's level, with a way to dig (digging.dig_means), a hole through the floor (vault.dig_down) --
medusa.des sets no hardfloor flag and the level is not the dungeon's last, so dungeon.c:1300 Can_dig_down holds. A
hole (and the pit dug before it: dig.c:240 dig -> dighole) fills with water with chance n / (n + 1), n the moat
squares among the 3 x 3 around it (dig.c:504 fillholetyp), and we would fall in (trap.c drown: the inventory wet): we
dig only on a square whose 8 neighbours we know and none is water. The level below Medusa's has its up stairs on her
island (her gaze: instadeath without reflection): never taken (DeepState.no_up), and revisit_up never climbs there.

dead_end_patrol: at such a dead end with no hole to dig -- back up the stairs we came by (never onto Medusa's
island) and walk about the ordinary level above for the rest of the game: the random monsters the game makes (1 in
70 turns, allmain.c) come at us by greedy steps (monmove.c m_move) and stay stuck behind walls -- a hero who stands
still meets few of them. On the patrol level its down stairs are hidden from explore (stairs_mask), which goes on
taking items and frontiers; where it would search walls, we walk to the nearest square not seen for PATROL_STALE
turns. With no way up (the Castle below Medusa's level) the patrol is where we are, off the squares next to water
(sea monsters: castle.des puts giant eels and sharks in the moat).

The steps hang on explore's own calls, overridden here (the mixin comes before MapMixin and ExploreMixin in Bot):
search_mode (the dead end is told where explore has nothing left but walls to search), stairs_mask, revisit_up.
With both options off each override is the method it replaces.
"""
from collections import Counter

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import COLS, CORRIDOR_GLYPHS, FLOOR_GLYPH, ROWS, WEAK

MEDUSA_MIN, MEDUSA_MAX = 21, 28      # dungeon.def: medusa @ (-5, 4) of 25-29 levels
WATER_MIN = 3                        # liquid squares known on a level of that depth: Medusa's or the Castle -- no
                                     # ordinary level is made with pools (mklev.c), medusa-2's building holds 3
DBRIDGE_GLYPHS = tuple(nh.GLYPH_CMAP_OFF + i for i in (35, 36, 37, 38))    # S_vodbridge .. S_hcdbridge: the Castle
BARE_FLOOR = (FLOOR_GLYPH, nh.GLYPH_CMAP_OFF + 20) + tuple(CORRIDOR_GLYPHS)   # S_room, S_darkroom, corridors
DIG_HP = 0.7                         # rest before the hole below this share of max HP (we land among strangers)
DIG_APPLIES = 60                     # applies / zaps at most on one level
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


class DeepState:
    """State of the water dead ends (DeepMixin)."""
    def __init__(self):
        self.kind = {}                 # level key -> "medusa" / "castle", once told (water_dead_end)
        self.dig = None                # medusa_dig: (level key, square) of the hole we are digging
        self.dig_bad = set()           # ... (level key, square) that filled with water or could not be reached
        self.applies = Counter()       # ... level key -> applies / zaps made
        self.no_up = set()             # level keys whose up stairs lead onto Medusa's island: never taken
        self.patrol = None             # dead_end_patrol: the level key we walk about on
        self.near_at = {}              # ... level key -> the turn each square was last within PATROL_R of us (0: never)
        self.mark = {}                 # summary: event -> (turn, score, kills) when it first happened
        self.once = set()              # summary: (event, level key) counted
        self.stats = Counter()


class DeepMixin:
    def deep_init(self):
        self.deep = DeepState()
        # game.digger_held: the pick-axe stays in our hands while we dig the hole (vault_rob_step puts it away)
        self.digger_holders.append(lambda lv: self.deep.dig is not None and self.deep.dig[0] == lv.key)

    def deep_on(self):
        return self.opts.medusa_dig or self.opts.dead_end_patrol

    def deep_summary(self):
        """Game summary entry: the counters, and turn / score / kills at the first hole and at the patrol's start."""
        if not self.deep.stats and not self.deep.kind:
            return {"deep": {}}
        return {"deep": dict(self.deep.stats, kinds={f"{k[1]}": v for k, v in self.deep.kind.items()},
                             **{k: list(v) for k, v in self.deep.mark.items()})}

    def deep_mark(self, event):
        self.deep.stats[event] += 1
        self.deep.mark.setdefault(event + "_at", (self.turn(), int(self.reward), self.combat.kill_count))

    def deep_once(self, event, lv):
        """Count event once a level."""
        if (event, lv.key) not in self.deep.once:
            self.deep.once.add((event, lv.key))
            self.deep.stats[event] += 1

    # ------------------------------------------------------------------ explore's calls, overridden
    def search_mode(self, lv, grids):
        """explore has nothing left on this level but walls to search: at a water dead end, the hole / the way
        back up / the patrol instead (dead_end_step)."""
        if self.deep_on() and self.dead_end_step(lv, grids):
            return
        super().search_mode(lv, grids)

    def stairs_mask(self, lv, kind, k_mem=None):
        """mapmem.stairs_mask, less the up stairs that lead onto Medusa's island (no_up) and the down stairs of
        the level we patrol."""
        mask = super().stairs_mask(lv, kind, k_mem)
        if kind == G.UPSTAIR and lv.key in self.deep.no_up:
            mask[:] = False
        elif kind == G.DOWNSTAIR and lv.key == self.deep.patrol:
            mask[:] = False
        return mask

    def revisit_up(self, lv, grids):
        """explore.revisit_up -- never to Medusa's level: the stairs up to it end on her island."""
        if lv.key in self.deep.no_up or self.deep.kind.get((lv.key[0], lv.key[1] - 1)) == "medusa":
            return False
        return super().revisit_up(lv, grids)

    # ------------------------------------------------------------------ which level this is
    def water_dead_end(self, lv, k_mem):
        """"medusa" / "castle" if this level of the main dungeon, Dlvl 21+, shows water (WATER_MIN squares): the
        Castle below Medusa's range, where the drawbridge is in our map, or where the floor would not be dug;
        Medusa's level else. None: neither, as far as we see."""
        if lv.key[0] != 0 or lv.key[1] < MEDUSA_MIN:
            return None
        kind = self.deep.kind.get(lv.key)
        if kind == "castle":
            return kind
        if kind is None and int((k_mem == G.LIQUID).sum()) < WATER_MIN:
            return None
        if lv.key[1] > MEDUSA_MAX or lv.key in self.digging.refused or np.isin(lv.terrain, DBRIDGE_GLYPHS).any():
            kind = "castle"
        else:
            kind = "medusa"
        if self.deep.kind.get(lv.key) != kind:
            self.deep.kind[lv.key] = kind
            self.deep.stats[kind] += 1
        return kind

    def dead_end_step(self, lv, grids):
        """Where explore would search walls: on the patrol level, the patrol; at a water dead end, the hole
        (medusa_dig), else the way back up and the patrol (dead_end_patrol). True if it used the turn."""
        if self.opts.dead_end_patrol and self.deep.patrol == lv.key:
            return self.patrol_step(lv, grids)
        kind = self.water_dead_end(lv, grids[0])
        if kind is None:
            return False
        if self.opts.medusa_dig and kind == "medusa" and self.medusa_dig_step(lv, grids):
            return True
        if self.opts.dead_end_patrol:
            return self.dead_end_leave_step(lv, grids)
        return False

    # ------------------------------------------------------------------ medusa_dig
    def medusa_dig_step(self, lv, grids):
        """One step of the hole on Medusa's level: rest first if hurt, walk to the dry square, dig (the pick-axe
        wielded by vault.dig_down; the pit, then the hole: two occupations). True if it used the turn; False: no
        way to dig here (no digger, the floor refused, no dry square in reach, too many tries)."""
        st = self.deep
        if st.dig is not None and st.dig[0] != lv.key:
            st.dig = None
        means = self.dig_means()
        if means is None or lv.key in self.digging.refused or st.applies[lv.key] >= DIG_APPLIES:
            st.dig = None
            return False
        if self.hp_below(DIG_HP) and not self.visible_hostiles(lv) and self.bl(nh.NLE_BL_HUNGER) < WEAK:
            self.cur_act = "rest"
            self.search_turns(20)
            return True
        if st.dig is None:
            sq = self.medusa_dig_square(lv, grids)
            if sq is None:
                self.deep_once("no_dry_square", lv)
                return False
            st.dig = (lv.key, sq)
        sq = st.dig[1]
        if self.pos() != sq:
            mask = np.zeros((ROWS, COLS), dtype=bool)
            mask[sq] = True
            if self.walk_to(lv, mask, act="medusa_dig", grids=grids)[0] == "moved":
                return True
            st.dig_bad.add(st.dig)
            st.dig = None
            return False
        # never back up to this level from below: its down stairs are on Medusa's island
        lv.unexplored = False
        st.no_up.add((lv.key[0], lv.key[1] + 1))
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
        return acted

    def medusa_dig_square(self, lv, grids):
        """The square for the hole: bare floor in reach, its 8 neighbours all known and none of them water (dig.c
        fillholetyp), the nearest; in medusa-2's dark arrival building, whose walls hide what lies behind them, the
        square beside the up stairs (medusa2_square). None if there is none."""
        k_mem, k_live, passable = grids
        bare = np.isin(lv.under, BARE_FLOOR) & passable
        for q in self.deep.dig_bad:
            if q[0] == lv.key:
                bare[q[1]] = False
        sq = self.medusa2_square(k_mem, bare)
        if sq is not None:
            return sq
        dry = bare & ~dilate(k_mem == G.LIQUID) & ~dilate(k_mem == G.UNKNOWN)
        dry[0, :] = dry[-1, :] = dry[:, 0] = dry[:, -1] = False
        if not dry.any():
            return None
        here = self.pos()
        if dry[here]:
            return here
        _, _, reached = self.dijkstra(lv, k_mem, k_live, passable, here, dry, want_dist=False)
        return reached

    @staticmethod
    def medusa2_square(k_mem, bare):
        """medusa.des medusa-2: the up stairs at (4, 9) in a closed building, columns 2-5, with pool at (5, 13),
        (5, 14), (5, 15) -- told by those three below-right of the stairs. The lake lies behind the west wall (column
        0) and from column 8 on: a square of the stairs' column, rows 5-11, has no water around it. The one below
        the stairs, or the one above; None if this is not that building."""
        ys, xs = np.nonzero(k_mem == G.UPSTAIR)
        for y, x in zip(ys.tolist(), xs.tolist()):
            if y + 6 < ROWS and x + 1 < COLS and all(k_mem[y + d, x + 1] == G.LIQUID for d in (4, 5, 6)):
                for q in ((y + 1, x), (y - 1, x)):
                    if bare[q]:
                        return q
        return None

    # ------------------------------------------------------------------ dead_end_patrol
    def dead_end_leave_step(self, lv, grids):
        """At a dead end with no hole to dig: to the up stairs and up them, the level above becoming the patrol
        level -- if we know that level and it is not Medusa's (we may have fallen past her); else the patrol is
        here. True if it used the turn."""
        st = self.deep
        above = (lv.key[0], lv.key[1] - 1)
        up = self.stairs_mask(lv, G.UPSTAIR, grids[0])
        if up.any() and above in self.levels and st.kind.get(above) != "medusa":
            if up[self.pos()]:
                st.patrol = above
                self.deep_mark("patrol_up")
                self.cur_act = "patrol"
                self.take_stairs("<")
                return True
            if self.walk_to(lv, up, act="patrol", grids=grids)[0] == "moved":
                return True
        st.patrol = lv.key
        self.deep_mark("patrol_here")
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
        stale = passable & ((near_at == 0) | (t - near_at > PATROL_STALE)) & (k_mem != G.TRAP) \
            & ~dilate(k_mem == G.LIQUID)
        self.cur_act = "patrol"
        if stale.any() and self.walk_to(lv, stale, act="patrol", grids=grids)[0] == "moved":
            return True
        st.stats["patrol_waits"] += 1
        self.search_turns(PATROL_WAIT)
        return True
