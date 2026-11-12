"""Map memory per level: what lies under monsters, what we visited, searched, learned to avoid,
where the shops are; terrain and passability grids for path finding."""
import re
from collections import Counter, deque

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import (ALTAR_GLYPH, COLS, CORRIDOR_GLYPHS, DOWNSTAIR_GLYPH, FEATURE_GLYPH, FEATURE_HERE_RE, FLOOR_GLYPH,
                          FOUNTAIN_GLYPH, NEIGH, ROWS, UPSTAIR_GLYPH)



# engrave.c wipeout_text: a worn engraving keeps its length; a letter becomes one of its rubouts, or '?' (no
# rubout), and '?' and small punctuation become ' ' -- repeatedly, so substitutes wear on in turn.
RUBOUTS = {"A": "^", "B": "Pb[", "C": "(", "D": "|)[", "E": "|FL[_", "F": "|-", "G": "C(", "H": "|-", "I": "|",
           "K": "|<", "L": "|_", "M": "|", "N": "|\\", "O": "C(", "P": "F", "Q": "C(", "R": "PF", "T": "|", "U": "J",
           "V": "/\\", "W": "V/\\", "Z": "/", "b": "|", "d": "c|", "e": "c", "g": "c", "h": "n", "j": "i", "k": "|",
           "l": "|", "m": "nr", "n": "r", "o": "c", "q": "c", "w": "v", "y": "v", ":": ".", ";": ",:", ",": ".",
           "=": "-", "+": "-|", "*": "+", "@": "0", "0": "C(", "1": "|", "6": "o", "7": "/", "8": "3o"}


def worn_to(c):
    """Every character c can wear into (itself included)."""
    out, todo = {c, "?", " "}, [c]
    while todo:
        for d in RUBOUTS.get(todo.pop(), ""):
            if d not in out:
                out.add(d)
                todo.append(d)
    return out


def engraving_says(seen, text, min_exact=6):
    """Could the engraving we read (seen) be text worn down? Same length, every character the original or
    something it wears into, and at least min_exact characters still exact (a fully worn engraving says
    nothing)."""
    if len(seen) != len(text):
        return False
    exact = 0
    for a, b in zip(seen, text):
        if a == b:
            exact += b != " "
        elif a not in worn_to(b):
            return False
    return exact >= min_exact


CFI_RE = re.compile(r'You read: "([^"]*)"')

# hack.c trapmove / trap.c: held by a trap ("caught" texts, including the repeats while still held) and let go
TRAP_MSGS = (("bear", ("A bear trap closes on your foot", "You are caught in a bear trap"),
              ("You finally wriggle free",)),
             ("pit", ("You fall into a pit", "You land on a set of sharp iron spikes", "You are still in a pit"),
              ("You crawl to the edge of the pit",)),
             ("web", ("You stumble into a spider web", "You are stuck to the web"),
              ("You disentangle yourself", "You tear through", "cuts through the web")))

BARS_GLYPH = nh.GLYPH_CMAP_OFF + 17   # S_bars (iron bars)
# sounds.c dosounds: a level's shopkeeper, temple, fountains, sinks heard from afar -- on Mines level 3-4 (where
# Minetown lies: dungeon.def minetn @ (3, 2)) only Minetown has any of them (filler levels are caves, no rooms)
# the watch's warnings (dig.c watch_dig, dokick.c, fountain.c, monmove.c watch_on_duty): only Minetown has a watch
WATCH_WARNINGS = ("Hey, stop damaging that", "Hey, stop picking that lock", "Hey, stop using that fountain")
TOWN_SOUNDS = ("cursing shoplifters", "chime of a cash register", "Neiman and Marcus arguing",
               "strident plea for donations", "carcass being offered in sacrifice", "someone praising",
               "someone beseeching", "bubbling water", "water falling on coins", "splashing of a naiad",
               "a soda fountain", "a slow drip", "a gurgling noise", "dishes being washed")


# dokick.c:782-810 dokick: a kick refused for our body or load (no time) -- kicking the door again would loop (300835: a
# form "too small to do any kicking", 105 guard firings)
KICK_REFUSED = ("no shape for kicking", "not enough room to kick", "no legs to kick with", "too small to do any kicking",
                "legs cannot kick effectively", "too heavy to balance yourself for a kick")

class Level:
    def __init__(self, key):
        self.key = key
        self.under = np.full((ROWS, COLS), G.STONE_GLYPH, dtype=np.int32)
        self.seen = np.zeros((ROWS, COLS), dtype=bool)
        self.visited = np.zeros((ROWS, COLS), dtype=np.int32)
        self.near = np.zeros((ROWS, COLS), dtype=bool)
        self.searched = np.zeros((ROWS, COLS), dtype=np.int32)
        self.blocked = np.zeros((ROWS, COLS), dtype=bool)   # learned failures (forgotten by step_progress's stall reset)
        self.fail = np.zeros((ROWS, COLS), dtype=np.int32)
        self.no_entry = np.zeros((ROWS, COLS), dtype=bool)  # squares a standing rule keeps us out of
                                                            # (no_entry_mark) -- never forgotten
        self.locked = set()
        self.avoid_down = set()    # downstairs leading into the Gnomish Mines
        self.shop = np.zeros((ROWS, COLS), dtype=bool)
        self.shop_anchors = []     # [door, square we came from (outside), closed] of each greeting (shop_regrow)
        self.grotto = False        # Grotto Town (is_grotto)
        self.town_heard = False    # Minetown told before seen: heard (minetown_sounds), warned by the watch
                                   # (minetown_watch), its watch / priest / shopkeeper in view (minetown_folk)
        self.watch_warned = set()  # doors a watchman saw us kick ("Hey, stop damaging that door!")
        self.door_seen = np.zeros((ROWS, COLS), dtype=bool)     # a door / doorway was seen here (an item may cover it)
        self.door_intact = np.zeros((ROWS, COLS), dtype=bool)   # ... an open or closed one: no diagonal moves
        self.terrain = np.full((ROWS, COLS), G.STONE_GLYPH, dtype=np.int32)   # last dungeon feature seen here
        self.no_diag = np.zeros((ROWS, COLS), dtype=bool)       # the game refused a diagonal step into / out of it
                                                                # (kept: on the Rogue level a doorway refuses too)
        self.desperate = False
        self.search_turns = 0
        self.turns_here = 0
        self.progress_count = 0
        self.last_progress = 0
        self.progress_here = 0     # turns_here at the last progress (step_progress counts turns here)
        self.last_reset = 0        # turn the learned obstacles were last forgotten
                                   # (step_progress)
        self.entered_turn = None
        self.entered_xl = None     # experience level at the first arrival (stats)
        self.explored = False      # the last explore step here found no frontier: none left, or none we can reach
        self.unexplored = False    # explore.revisit_up: the last explore step here walked toward a frontier we can reach (we
                                   # left by a hole / trap door / teleport, not by the stairs on purpose)
        self.stairs_to = {}        # staircase square -> the level key it led to when we took it (both ends)
        self.altar_align = {}      # sacrifice: altar square -> its alignment, read on stepping there
        self.stationary = {}       # square -> a never-melee monster that never moves, seen there
        self.not_stairs = set()    # squares where the game said there is no staircase
        self.kill_piles = set()    # squares where we killed a monster that may carry things (monsters.CARRIERS)
        self.elbereth = set()     # positions where we engraved
        self.cfi = set()          # squares where a shopkeeper said "Closed for inventory"
        self.search_goal = None   # square chosen for searching, kept until reached
        self.mapped = False       # a magic mapping scroll was read here
        self.kinds_memo = None    # MapMixin.kinds: (under, terrain, kinds) of its last answer

    def set_terrain(self, pos, glyph):
        """What we learned is at pos now (a dried-up fountain, a staircase that isn't): both layers."""
        self.under[pos] = glyph
        self.terrain[pos] = glyph


class MapMixin:
    def map_init(self):
        self.levels = {}                 # level key (dungeon number, level) -> Level
        self.map_stats = Counter()       # what messages taught the map (summary 'map_stats')
        self.shop_flood_memo = {}        # shop_regrow: (level, door, came) -> (floor mask, flood)
        self.cur_key = None              # the key of the level this tick is on
        self.prev_key = None             # ... of the level at the last tick (note_arrival)
        self.arrived_by_stairs = False   # this tick: a staircase brought us onto this level (note_arrival)
        self._cur_pos = self.prev_pos = None    # our square, and the one before it we last stood on
        self.max_depth = 1

    def level(self):
        key = (self.bl(nh.NLE_BL_DNUM), self.bl(nh.NLE_BL_DLEVEL))
        lv = self.levels.get(key)
        if lv is None:
            lv = self.levels[key] = Level(key)
            lv.entered_turn = self.turn()
            lv.entered_xl = self.bl(nh.NLE_BL_XP)
        return lv

    def engulfed(self):
        """Swallowed: the engulfer is drawn on the 8 squares AROUND us (display.c swallowed()), the rest of the map
        is blank."""
        gg = self.obs["glyphs"]
        y, x = self.pos()
        ring = gg[max(0, y - 1):y + 2, max(0, x - 1):x + 2]
        return int(((ring >= nh.GLYPH_SWALLOW_OFF) & (ring < nh.GLYPH_WARNING_OFF)).sum()) >= 5

    def update_memory(self):
        """First thing every tick: what the screen shows now into this level's memory; a shop greeted in the dark grows
        as its floor shows (shop_regrow); the arrival on another level noted (note_arrival). The level.
        Not while engulfed -- the blank map (display.c swallowed: everything but the engulfer cleared) wrote solid
        rock over every square remembered, the terrain layer too: a staircase under an item, a fountain, what
        note_feature_here / a stair arrival had taught was gone for good (79276: the way down, under a large box).
        (A/B engulf_memory: -312 [-696, +73], median 7567 -> 7674, 57 of 1000 changed)"""
        lv = self.level()
        g = self.obs["glyphs"]
        known = ~G.TRANSIENT[g]
        if self.engulfed():
            known = np.zeros_like(known)
        lv.under[known] = g[known]
        feat = known & G.TERRAIN[g]
        lv.terrain[feat] = g[feat]
        k = G.KIND[g]
        lv.door_seen |= known & ((k == G.DOOR_OPEN) | (k == G.DOOR_CLOSED) | (k == G.DOORWAY))
        lv.door_intact[known & ((k == G.DOOR_OPEN) | (k == G.DOOR_CLOSED))] = True
        lv.door_intact[known & (k == G.DOORWAY)] = False        # no door / a broken one
        lv.seen |= known & (g != G.STONE_GLYPH)
        y, x = self.pos()
        if self._cur_pos != (y, x):
            self.prev_pos, self._cur_pos = self._cur_pos, (y, x)
        lv.visited[y, x] += 1
        lv.near[max(0, y - 1):y + 2, max(0, x - 1):x + 2] = True
        if not lv.shop[y, x] and lv.shop[max(0, y - 1):y + 2, max(0, x - 1):x + 2].any() \
                and self.kinds(lv)[y, x] not in (G.DOOR_OPEN, G.DOOR_CLOSED, G.DOORWAY) \
                and not lv.door_seen[y, x] \
                and int(lv.under[y, x]) not in CORRIDOR_GLYPHS:
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
            lv.progress_here = lv.turns_here
        if lv.shop_anchors:
            self.shop_regrow(lv)
        self.arrived_by_stairs = self.note_arrival(lv)
        return lv

    def kinds(self, lv):
        """Kind of every remembered square: a trap / staircase / door / water under an item is that feature (the
        terrain layer); the item still shows on the squares nothing special lies under. Item goals (gold, piles,
        corpses) read the top glyph, lv.under, instead.
        Asked many times a tick of a map that seldom changes: the last answer is kept with the two layers it was
        read from (Level.kinds_memo) and given again, as a copy, while both are unchanged."""
        memo = lv.kinds_memo
        if memo is not None and np.array_equal(memo[0], lv.under) and np.array_equal(memo[1], lv.terrain):
            return memo[2].copy()
        k = self._kinds(lv)
        lv.kinds_memo = (lv.under.copy(), lv.terrain.copy(), k.copy())
        return k

    @staticmethod
    def _kinds(lv):
        k = G.KIND[lv.under]
        tk = G.KIND[lv.terrain]
        hidden = G.IS_COVERED[k] & G.IS_TERRAIN[tk]
        if hidden.any():
            # nothing lies on a closed door: an item there means it was opened or broken since we saw it
            tk = np.where(tk == G.DOOR_CLOSED, G.DOOR_OPEN, tk)
            k = np.where(hidden, tk, k)
        return k

    def terrain_glyphs(self, lv):
        """Remembered glyphs with the terrain layer where we know it: fountains, altars under items."""
        return np.where(lv.terrain != G.STONE_GLYPH, lv.terrain, lv.under)

    def passable_grid(self, lv, k_mem, k_live):
        p = G.PASSABLE[k_mem].copy()
        p |= (k_mem == G.BOULDER) | (k_live == G.BOULDER)   # try pushing; failures mark blocked
        p[lv.blocked] = False
        p[lv.no_entry] = False
        if int(self.last_bl[nh.NLE_BL_CONDITION]) & nh.BL_MASK_HALLU and self.strike_scope_ok(lv):
            p[k_live == G.MONSTER] = False    # a step into an unrecognisable monster is an attack: route around
        if not lv.shop[self.pos()] and not self.shop_active(lv):
            p[lv.shop] = False
        shut = self.vault.shut.get(lv.key)
        if shut and self.pos() not in shut:
            p[tuple(zip(*shut))] = False      # a vault we left -- no walk back in (the guard's count)
        if self.opts.sokoban and self.in_sokoban(lv) and not (self.soko_failed or self.soko_done):
            # Sokoban: no other walk may push a boulder out of the plan or step into a pit / hole
            p[(k_mem == G.BOULDER) | (k_live == G.BOULDER) | (k_mem == G.TRAP)] = False
        # stationary dangerous monsters block
        for (y, x) in self.perc.avoid_cells:
            p[y, x] = False
        self.deep_passable(lv, p)            # no holes / trap doors on the patrol level (nhbot.deep)
        return p

    def shop_floor(self, lv):
        """Squares that can be shop floor: room floor (or what lies on it), not corridor, not a door."""
        g = lv.under
        k = G.KIND[g]
        ok = np.isin(k, [G.FLOOR, G.OBJECT, G.GOLD, G.CORPSE, G.TRAP, G.BOULDER]) & ~np.isin(g, list(CORRIDOR_GLYPHS))
        return ok & ~lv.door_seen                   # a door under an item is not shop floor

    def mark_shop(self, lv, door):
        came = self._cur_pos          # map memory is not updated yet for the door square
        if came == door:
            came = self.prev_pos
        for c in self.shop_flood(lv, door, came):
            lv.shop[c] = True
        lv.shop_anchors.append([door, came, False])

    def shop_flood(self, lv, door, came, inside_ok=None):
        """The shop's squares behind its door as far as the map knows them: room floor from the door, not the side
        we came from. inside_ok: shop_floor(lv), when the caller has it."""
        if inside_ok is None:
            inside_ok = self.shop_floor(lv)
        seen = set()
        q = deque()
        y, x = door
        if came is not None and max(abs(came[0] - y), abs(came[1] - x)) == 1:
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
        return seen

    def shop_regrow(self, lv):
        """Every tick: a shop greeted while dark (its floor not yet in our map: the flood from the door
        found little or nothing) grows as its squares become known -- the flood from its door again, squares
        added, none taken away -- until nothing unknown is next to it (79607: Izchak's dark shop never marked, a
        corpse on its floor eaten and not paid for). Lit shops too: the squares the shopkeeper or a pet stood on
        at the greeting join later. A/B shop_regrow +1658 [+174, +3111], max_depth +0.4 (628 of 1000 games went
        another way: the mechanism of the gain not found)."""
        k = None
        for a in lv.shop_anchors:
            if a[2]:
                continue
            # the flood depends only on the floor mask and the anchor: while the map shows the same floor, last
            # tick's answer (a shop never finished re-flooded its outside every tick: 1.7 ms a tick)
            ok = self.shop_floor(lv)
            key = (lv.key, a[0], a[1])
            memo = self.shop_flood_memo.get(key)
            if memo is not None and np.array_equal(memo[0], ok):
                room = memo[1]
            else:
                room = self.shop_flood(lv, a[0], a[1], ok)
                self.shop_flood_memo[key] = (ok, room)
            for c in room:
                lv.shop[c] = True
            k = self.kinds(lv) if k is None else k
            a[2] = bool(room) and not any((k[max(0, cy - 1):cy + 2, max(0, cx - 1):cx + 2] == G.UNKNOWN).any()
                                          for cy, cx in room)

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

    def is_grotto(self, lv):
        """Grotto Town (mines.des minetn-5, a fixed 76x21 map centred: map (x, y) is screen (y, x + 2)): its up
        staircase at map (1, 1) or one of its fountains at map (50, 9), (10, 15), (66, 18)."""
        if lv.key[0] != 2:
            return False
        if not lv.grotto:
            lv.grotto = int(lv.under[1, 3]) == UPSTAIR_GLYPH or any(
                int(self.terrain_glyphs(lv)[p]) == FOUNTAIN_GLYPH for p in ((9, 52), (15, 12), (18, 68)))
        return lv.grotto

    def is_orctown(self, lv):
        """Orcish Town (mines.des minetn-1, Frontier Town overrun by orcs): the only Mines level with iron bars (its
        walls' 'F', shown '#'). Its watch, priest and shopkeepers lie dead -- nobody minds a dug wall there."""
        return lv is not None and lv.key[0] == 2 and bool((self.terrain_glyphs(lv) == BARS_GLYPH).any())

    def is_minetown(self, lv):
        """A Mines level with an altar, a fountain or a shop: Minetown (every variant has a temple altar;
        filler Mines levels have none of the three -- but Mines' End has fountains: minend-2 one, minend-3 two,
        mines.des: so Minetown only where the dungeon puts it, Mines level 3 or 4 --
        dungeon.def:74 "minetn" @ (3, 2), dungeon.c:377-379 level_range; A/B minend_not_town +29 [-366, +412], 38 games
        changed, accepted)."""
        if lv is None or lv.key[0] != 2:
            return False
        if not 3 <= lv.key[1] <= 4:
            return False
        if lv.town_heard:
            return True
        return bool(lv.shop.any() or np.isin(self.terrain_glyphs(lv), (ALTAR_GLYPH, FOUNTAIN_GLYPH)).any())

    def no_entry_mark(self, lv, sq):
        """A square a standing rule keeps us out of -- a door the watch warned us off, a closed-for-inventory shop's
        door, a door in the Mines (never kicked), a lock we were warned off, a squeeze we can't shed enough for, a
        boulder dig_through gave up on: Level.no_entry, kept for good (step_progress's stall reset forgets only the
        learned failures, Level.blocked / fail). (A/B blocked_split: -149 [-498, +190], median 7726 -> 7567, 61 of
        1000 changed)"""
        lv.no_entry[sq] = True

    def door_forced_open(self, lv, door):
        """A locked door we kicked open (it crashed open or shattered: dokick.c:1286-1290): no longer locked, and no
        longer kept out of for its lock (no_entry_mark: nav.move never kicks a door in the Mines)."""
        lv.locked.discard(door)
        lv.no_entry[door] = False

    def stairs_mask(self, lv, kind, k_mem=None):
        """The squares of the remembered staircases of kind (G.UPSTAIR / G.DOWNSTAIR) we may walk to and take:
        k_mem (default: kinds) == kind, less the squares where the game said there is none (Level.not_stairs,
        msg_map). Every step that walks to stairs and presses '<' / '>' takes its targets from here.
        (A/B stairs_refused -- one record, every walk to stairs: +94 [-141, +329], median 7777 -> 7794.)"""
        mask = (self.kinds(lv) if k_mem is None else k_mem) == kind
        for p in lv.not_stairs:
            mask[p] = False
        self.deep_stairs(lv, kind, mask)     # never onto Medusa's island, never down from the patrol (nhbot.deep)
        return mask

    def stairs_kind_here(self, lv):
        k = self.kinds(lv)[self.pos()]
        return k if k in (G.UPSTAIR, G.DOWNSTAIR) else None

    def note_arrival(self, lv):
        """On another level than at the last tick: where the staircase we took leads, both ways (Level.stairs_to), and
        its other end under us (note_stair_arrival). The stairs bookkeeping of the last action (actions.take_stairs)
        is used up here. True if a staircase brought us onto this level."""
        arrived_by_stairs = False
        if lv.key != self.prev_key:
            arrived_by_stairs = self.acts.took_stairs
            if self.acts.last_stair_dir and self.acts.stair_from and self.acts.stair_from[0] == self.prev_key \
                    and self.prev_key in self.levels:
                self.levels[self.prev_key].stairs_to[self.acts.stair_from[1]] = lv.key
                lv.stairs_to[self.pos()] = self.prev_key
            self.note_stair_arrival(lv)
            self.prev_key = lv.key
        self.stairs_noted()
        return arrived_by_stairs

    def note_stair_arrival(self, lv):
        """On a new level by a staircase we took: the other end of it is under us."""
        if self.acts.last_stair_dir:
            lv.set_terrain(self.pos(), UPSTAIR_GLYPH if self.acts.last_stair_dir == ">" else DOWNSTAIR_GLYPH)

    def note_feature_here(self, text):
        """"There is a staircase down here." (invent.c look_here, said when something lies on the square we step on --
        first on the top line, or atop the "Things that are here" window; game.settle reads both) into the terrain
        layer under us: an item on a staircase hid it -- kinds read the item, and the level stayed "no way down" for
        thousands of turns searching (79337, 79099, 79276: the true down staircase under an item we had stood on).
        (A/B feature_here: -731 [-1485, +23], median 7567 -> 7772, 168 of 1000 changed)"""
        lv = self.levels.get((self.bl(nh.NLE_BL_DNUM), self.bl(nh.NLE_BL_DLEVEL)))
        if lv is None:
            return
        for mm in FEATURE_HERE_RE.finditer(text):
            g = FEATURE_GLYPH[mm.group(1)]
            pos = self.pos()
            if lv.terrain[pos] != g:
                lv.terrain[pos] = g
                self.map_stats["feature_noted"] += 1

    def msg_map(self, m, lv):
        """What a message tells about the map: locked doors, squares we can't enter, stairs that aren't."""
        if lv is not None and lv.key[0] == 2 and lv.key[1] in (3, 4) \
                and "You hear" in m and any(t in m for t in TOWN_SOUNDS):
            lv.town_heard = True                              # Minetown, before we see it (accepted without A/B)
        if lv is not None and lv.key[0] == 2 and any(w in m for w in WATCH_WARNINGS):
            lv.town_heard = True                              # the watch warned us -- Minetown (A/B minetown_watch:
                                                              # never fired without dig_through, accepted)
        if "under arrest" in m:
            self.mines_kick_stat("arrest")
        if "stop damaging that door" in m and lv and self.nav.last_move_target:
            lv.watch_warned.add(self.nav.last_move_target)      # the next kick it sees means arrest
            self.no_entry_mark(lv, self.nav.last_move_target)
            self.mines_kick_stat("warned")
        if "diagonally into an intact doorway" in m and lv and self.nav.last_move_target:
            lv.door_seen[self.nav.last_move_target] = lv.no_diag[self.nav.last_move_target] = True
        if "diagonally out of an intact doorway" in m and lv:
            lv.door_seen[self.pos()] = lv.no_diag[self.pos()] = True
        for kind, caught, freed in TRAP_MSGS:
            if any(c in m for c in caught) and self.cur_key:
                self.trap_caught(kind)
            elif any(f in m for f in freed):
                self.trap_freed()
        if "This door is locked" in m and self.nav.last_move_target and lv:
            lv.locked.add(self.nav.last_move_target)
        if self.squeeze_msg(m, lv):                           # carry.py: a diagonal squeeze refused for our weight
            pass
        elif lv and self.nav.last_move_target and "You try to move the boulder, but in vain" in m:
            # hack.c:332 moverock (the only boulder message a step gets that stays true; a monster behind it,
            # "Perhaps that's why you cannot move it." (hack.c:172), moves on: left to the step-failure count)
            if not self.dig_through_note(lv, self.pos(), self.nav.last_move_target, "boulder"):
                lv.blocked[self.nav.last_move_target] = True
        if lv and self.nav.last_move_target and "It's solid stone" in m:
            self.rock_note(lv, self.pos(), self.nav.last_move_target)    # rockdig.py: gold / gems seen in rock
        if any(t in m for t in KICK_REFUSED) and lv and self.nav.last_move_target:
            # can't kick from here (wounded legs: dokick.c; in a pit): kicking the door again would loop
            lv.blocked[self.nav.last_move_target] = True
        if lv and ("Closed for inventory" in m or any(engraving_says(t, "Closed for inventory")
                                                         for t in CFI_RE.findall(m))):
            # the closed shop's door: kicking it open angers the shopkeeper ("How dare you break my door?");
            # the engraving in the dust wears as we walk on it
            y, x = self.pos()
            for dy, dx in NEIGH:
                ny, nx = y + dy, x + dx
                if 0 <= ny < ROWS and 0 <= nx < COLS and self.kinds(lv)[ny, nx] == G.DOOR_CLOSED:
                    self.no_entry_mark(lv, (ny, nx))
            lv.cfi = lv.cfi | {self.pos()}
        if ("You can't go up here" in m or "You can't go down here" in m) and lv is not None:
            # we remembered a staircase that isn't here (arriving next to stairs a monster stood on marks the
            # wrong square); the refusal costs no time, so pressing again looped to the step cap
            yy, xx = self.pos()
            # the one place a refusal is recorded -- whichever step pressed the key; every stairs target
            # (stairs_mask, linked_stairs) leaves the square out from now on, also when the staircase is remembered
            # in the terrain layer under an item
            lv.not_stairs.add((yy, xx))
            if G.KIND[int(lv.under[yy, xx])] in (G.UPSTAIR, G.DOWNSTAIR):
                lv.set_terrain((yy, xx), FLOOR_GLYPH)
            elif self.opts.stair_refuse and G.KIND[int(lv.terrain[yy, xx])] in (G.UPSTAIR, G.DOWNSTAIR):
                # stair_refuse: an item lies there and the staircase is in the terrain layer under it (kinds reads
                # that through the item) -- 79654 pressed '>' 14047 times in 120 turns, 25 steps a turn
                lv.terrain[yy, xx] = FLOOR_GLYPH
