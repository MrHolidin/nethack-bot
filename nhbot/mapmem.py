"""Map memory per level: what lies under monsters, what we visited, searched, learned to avoid,
where the shops are; terrain and passability grids for path finding."""
from collections import deque

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import ALTAR_GLYPH, COLS, CORRIDOR_GLYPHS, DOWNSTAIR_GLYPH, FLOOR_GLYPH, FOUNTAIN_GLYPH, NEIGH, ROWS, UPSTAIR_GLYPH


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
        self.gold_tried = set()
        self.avoid_down = set()
        self.shop = np.zeros((ROWS, COLS), dtype=bool)
        self.desperate = False
        self.search_turns = 0
        self.turns_here = 0
        self.progress_count = 0
        self.last_progress = 0
        self.last_reset = 0   # downstairs leading into the Gnomish Mines
        self.peaceful = set()     # monster glyphs that turned out peaceful here
        self.entered_turn = None
        self.elbereth = set()     # positions where we engraved
        self.cfi = set()          # squares where a shopkeeper said "Closed for inventory"
        self.search_goal = None   # square chosen for searching, kept until reached
        self.mapped = False       # a magic mapping scroll was read here
        self.shop_type = None     # from the shopkeeper's greeting


class MapMixin:
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
        if self._cur_pos != (y, x):
            self.prev_pos, self._cur_pos = self._cur_pos, (y, x)
        lv.visited[y, x] += 1
        lv.near[max(0, y - 1):y + 2, max(0, x - 1):x + 2] = True
        if not lv.shop[y, x] and lv.shop[max(0, y - 1):y + 2, max(0, x - 1):x + 2].any() \
                and G.KIND[lv.under[y, x]] not in (G.DOOR_OPEN, G.DOOR_CLOSED, G.DOORWAY) \
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
        return lv

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
        if self.opts.hallu_strike and \
                int(self.last_bl[nh.NLE_BL_CONDITION]) & nh.BL_MASK_HALLU and self.strike_scope_ok(lv):
            p[k_live == G.MONSTER] = False    # a step into an unrecognisable monster is an attack: route around
        if not lv.shop[self.pos()] and not self.shop_active(lv):
            p[lv.shop] = False
        # stationary dangerous monsters block
        for (y, x) in self.avoid_cells:
            p[y, x] = False
        return p

    def mark_shop(self, lv, door):
        g = lv.under.copy()
        g[self.pos()] = g[self.pos()]
        corridor = set(CORRIDOR_GLYPHS)
        k = G.KIND[g]
        inside_ok = np.isin(k, [G.FLOOR, G.OBJECT, G.GOLD, G.CORPSE, G.TRAP, G.BOULDER]) & \
            ~np.isin(g, list(corridor))
        seen = set()
        q = deque()
        y, x = door
        came = self._cur_pos          # map memory is not updated yet for the door square
        if came == door:
            came = self.prev_pos
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
        for c in seen:
            lv.shop[c] = True

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

    def is_minetown(self, lv):
        """A Mines level with an altar, a fountain or a shop: Minetown (every variant has a temple altar;
        filler Mines levels and Mines' End have none of the three)."""
        if lv is None or lv.key[0] != 2:
            return False
        return bool(lv.shop.any() or np.isin(lv.under, (ALTAR_GLYPH, FOUNTAIN_GLYPH)).any())

    def stairs_kind_here(self, lv):
        k = G.KIND[lv.under[self.pos()]]
        return k if k in (G.UPSTAIR, G.DOWNSTAIR) else None

    def note_stair_arrival(self, lv, arrived):
        if arrived and self.last_stair_dir:
            lv.under[self.pos()] = UPSTAIR_GLYPH if self.last_stair_dir == ">" else DOWNSTAIR_GLYPH
        self.last_stair_dir = None

    def msg_map(self, m, lv):
        """What a message tells about the map: locked doors, squares we can't enter, stairs that aren't."""
        if "This door is locked" in m and self.last_move_target and lv:
            lv.locked.add(self.last_move_target)
        if lv and self.last_move_target and any(s in m for s in (
                "You try to move the boulder, but in vain",
                "Perhaps that's why you cannot move past it",
                "There is a boulder in your way",
                "You are carrying too much to get through",
                "You don't have enough room to maneuver")):
            lv.blocked[self.last_move_target] = True
        if "no shape for kicking" in m and lv and self.last_move_target:
            lv.blocked[self.last_move_target] = True
        if "Closed for inventory" in m and lv:
            y, x = self.pos()
            for dy, dx in NEIGH:
                ny, nx = y + dy, x + dx
                if 0 <= ny < ROWS and 0 <= nx < COLS and G.KIND[lv.under[ny, nx]] == G.DOOR_CLOSED:
                    lv.blocked[ny, nx] = True
        if lv is not None and "Closed for inventory" in m:
            lv.cfi = lv.cfi | {self.pos()}
        if ("You can't go up here" in m or "You can't go down here" in m) and lv is not None:
            # we remembered a staircase that isn't here (arriving next to stairs a monster stood on marks the
            # wrong square); the refusal costs no time, so pressing again looped to the step cap
            yy, xx = self.pos()
            if G.KIND[int(lv.under[yy, xx])] in (G.UPSTAIR, G.DOWNSTAIR):
                lv.under[yy, xx] = FLOOR_GLYPH
