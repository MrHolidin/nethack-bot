"""Map memory per level: what lies under monsters, what we visited, searched, learned to avoid,
where the shops are; terrain and passability grids for path finding."""
import re
from collections import deque

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import ALTAR_GLYPH, COLS, CORRIDOR_GLYPHS, DOWNSTAIR_GLYPH, FLOOR_GLYPH, FOUNTAIN_GLYPH, NEIGH, ROWS, UPSTAIR_GLYPH



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

SHOP_MAX = 150                   # shk_marks_shop: a shop room is no bigger than this


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
        self.avoid_down = set()
        self.shop = np.zeros((ROWS, COLS), dtype=bool)
        self.grotto = False        # Grotto Town (is_grotto)
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
        self.last_reset = 0   # downstairs leading into the Gnomish Mines
        self.entered_turn = None
        self.entered_xl = None     # experience level at the first arrival (stats)
        self.unexplored = False    # the last explore step here walked toward a frontier we can reach
        self.explored = False      # the last explore step here found no frontier: none left, or none we can reach
        self.stairs_to = {}        # staircase square -> the level key it led to when we took it (both ends)
        self.squeeze_shut = set()  # squeeze_plan: (from, to) diagonal squeezes refused for our weight, both ways
        self.not_stairs = set()    # mines_xl: squares where the game said there is no staircase
        self.kill_piles = set()    # squares where we killed a monster that may carry things (monsters.CARRIERS)
        self.elbereth = set()     # positions where we engraved
        self.cfi = set()          # squares where a shopkeeper said "Closed for inventory"
        self.search_goal = None   # square chosen for searching, kept until reached
        self.mapped = False       # a magic mapping scroll was read here
        self.shop_type = None     # from the shopkeeper's greeting

    def set_terrain(self, pos, glyph):
        """What we learned is at pos now (a dried-up fountain, a staircase that isn't): both layers."""
        self.under[pos] = glyph
        self.terrain[pos] = glyph


class MapMixin:
    def level(self):
        key = (self.bl(nh.NLE_BL_DNUM), self.bl(nh.NLE_BL_DLEVEL))
        lv = self.levels.get(key)
        if lv is None:
            lv = self.levels[key] = Level(key)
            lv.entered_turn = self.turn()
            lv.entered_xl = self.bl(nh.NLE_BL_XP)
        return lv

    def update_memory(self):
        lv = self.level()
        g = self.obs["glyphs"]
        known = ~G.TRANSIENT[g]
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
        if self.opts.shk_marks_shop:
            self.shop_from_keeper(lv)
        self.max_depth = max(self.max_depth, self.bl(nh.NLE_BL_DEPTH))
        pc = int(lv.seen.sum()) + int((lv.visited > 0).sum())
        if pc > lv.progress_count:
            lv.progress_count = pc
            lv.last_progress = self.turn()
        return lv

    def kinds(self, lv):
        """Kind of every remembered square: a trap / staircase / door / water under an item is that feature (the
        terrain layer); the item still shows on the squares nothing special lies under. Item goals (gold, piles,
        corpses) read the top glyph, lv.under, instead."""
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

    def kind_grid(self, lv):
        """Terrain kind map from memory, with live monsters/objects overlaid."""
        g = self.obs["glyphs"]
        k_live = G.KIND[g]
        return self.kinds(lv), k_live

    def passable_grid(self, lv, k_mem, k_live):
        p = G.PASSABLE[k_mem].copy()
        p |= (k_mem == G.BOULDER) | (k_live == G.BOULDER)   # try pushing; failures mark blocked
        p[lv.blocked] = False
        if int(self.last_bl[nh.NLE_BL_CONDITION]) & nh.BL_MASK_HALLU and self.strike_scope_ok(lv):
            p[k_live == G.MONSTER] = False    # a step into an unrecognisable monster is an attack: route around
        if not lv.shop[self.pos()] and not self.shop_active(lv):
            p[lv.shop] = False
        # stationary dangerous monsters block
        for (y, x) in self.avoid_cells:
            p[y, x] = False
        return p

    def shop_floor(self, lv):
        """Squares that can be shop floor: room floor (or what lies on it), not corridor, not a door."""
        g = lv.under
        k = G.KIND[g]
        ok = np.isin(k, [G.FLOOR, G.OBJECT, G.GOLD, G.CORPSE, G.TRAP, G.BOULDER]) & ~np.isin(g, list(CORRIDOR_GLYPHS))
        return ok & ~lv.door_seen                   # a door under an item is not shop floor

    def shop_from_keeper(self, lv):
        """shk_marks_shop: we stand in an unmarked room with a shopkeeper in view -- a shop we got into without
        the greeting at its door (a mimic in the doorway, a fall, a teleport): mark the room, as mark_shop does
        from the door. Only from inside (marked squares are closed to us from outside, and from the door the
        greeting does it), only a closed room of at most SHOP_MAX squares with the shopkeeper in it."""
        me = self.pos()
        if lv.shop[me] or lv.door_seen[me]:
            return
        g = self.obs["glyphs"]
        ys, xs = np.nonzero(G.KIND[g] == G.MONSTER)
        keepers = [(int(a), int(b)) for a, b in zip(ys, xs) if G.monster_name(int(g[a, b])) == "shopkeeper"]
        if not keepers:
            return
        ok = self.shop_floor(lv)
        ok[me] = True
        for p in keepers:
            ok[p] = True
        room = self._flood(ok, [me], cap=SHOP_MAX + 1)
        if len(room) > SHOP_MAX or not any(p in room for p in keepers):
            return
        k = self.kinds(lv)
        for cy, cx in room:                         # closed: nothing unexplored right next to it
            if (k[max(0, cy - 1):cy + 2, max(0, cx - 1):cx + 2] == G.UNKNOWN).any():
                return
        for c in room:
            lv.shop[c] = True
        self.shops_from_keeper += 1

    def mark_shop(self, lv, door):
        inside_ok = self.shop_floor(lv)
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

    def is_grotto(self, lv):
        """Grotto Town (mines.des minetn-5, a fixed 76x21 map centred: map (x, y) is screen (y, x + 2)): its up
        staircase at map (1, 1) or one of its fountains at map (50, 9), (10, 15), (66, 18)."""
        if lv.key[0] != 2:
            return False
        if not lv.grotto:
            lv.grotto = int(lv.under[1, 3]) == UPSTAIR_GLYPH or any(
                int(self.terrain_glyphs(lv)[p]) == FOUNTAIN_GLYPH for p in ((9, 52), (15, 12), (18, 68)))
        return lv.grotto

    def is_minetown(self, lv):
        """A Mines level with an altar, a fountain or a shop: Minetown (every variant has a temple altar;
        filler Mines levels and Mines' End have none of the three)."""
        if lv is None or lv.key[0] != 2:
            return False
        return bool(lv.shop.any() or np.isin(self.terrain_glyphs(lv), (ALTAR_GLYPH, FOUNTAIN_GLYPH)).any())

    def stairs_kind_here(self, lv):
        k = self.kinds(lv)[self.pos()]
        return k if k in (G.UPSTAIR, G.DOWNSTAIR) else None

    def note_stair_arrival(self, lv, arrived):
        if arrived and self.last_stair_dir:
            lv.set_terrain(self.pos(), UPSTAIR_GLYPH if self.last_stair_dir == ">" else DOWNSTAIR_GLYPH)
        self.last_stair_dir = None

    def msg_map(self, m, lv):
        """What a message tells about the map: locked doors, squares we can't enter, stairs that aren't."""
        if "under arrest" in m:
            self.mines_kick_stats["arrest"] += 1
        if "stop damaging that door" in m and lv and self.last_move_target:
            lv.watch_warned.add(self.last_move_target)      # the next kick it sees means arrest
            lv.blocked[self.last_move_target] = True
            self.mines_kick_stats["warned"] += 1
        if "diagonally into an intact doorway" in m and lv and self.last_move_target:
            lv.door_seen[self.last_move_target] = lv.no_diag[self.last_move_target] = True
        if "diagonally out of an intact doorway" in m and lv:
            lv.door_seen[self.pos()] = lv.no_diag[self.pos()] = True
        for kind, caught, freed in TRAP_MSGS:
            if any(c in m for c in caught) and self.cur_key:
                if self.trapped is None:
                    self.trap_stats[kind] += 1
                    self.trap_stats["_tries"] = 0
                self.trapped = (kind, self.cur_key, self.pos())
            elif any(f in m for f in freed):
                self.trapped = None
        if "This door is locked" in m and self.last_move_target and lv:
            lv.locked.add(self.last_move_target)
        if lv and self.last_move_target and "You are carrying too much to get through" in m:
            # a diagonal squeeze needs inventory weight <= 600 (hack.c test_move): the weight step sheds a unit
            self.squeeze_stats["refused"] += 1
            if self.opts.squeeze_plan and self.squeeze_target != (lv.key, self.pos(), self.last_move_target):
                a, b = self.pos(), self.last_move_target      # explore round it first (explore.squeeze_open_step)
                lv.squeeze_shut |= {(a, b), (b, a)}
                self.squeeze_stats["shut"] += 1
            else:
                self.squeeze_pending = (lv.key, self.last_move_target)
        elif lv and self.last_move_target and any(s in m for s in (
                "You try to move the boulder, but in vain",
                "Perhaps that's why you cannot move past it",
                "There is a boulder in your way",
                "You don't have enough room to maneuver")):
            lv.blocked[self.last_move_target] = True
        if ("no shape for kicking" in m or "not enough room to kick" in m) and lv and self.last_move_target:
            # can't kick from here (a form without legs; in a pit): kicking the door again would loop
            lv.blocked[self.last_move_target] = True
        if lv and ("Closed for inventory" in m or any(engraving_says(t, "Closed for inventory")
                                                         for t in CFI_RE.findall(m))):
            # the closed shop's door: kicking it open angers the shopkeeper ("How dare you break my door?");
            # the engraving in the dust wears as we walk on it
            y, x = self.pos()
            for dy, dx in NEIGH:
                ny, nx = y + dy, x + dx
                if 0 <= ny < ROWS and 0 <= nx < COLS and self.kinds(lv)[ny, nx] == G.DOOR_CLOSED:
                    lv.blocked[ny, nx] = True
            lv.cfi = lv.cfi | {self.pos()}
        if ("You can't go up here" in m or "You can't go down here" in m) and lv is not None:
            # we remembered a staircase that isn't here (arriving next to stairs a monster stood on marks the
            # wrong square); the refusal costs no time, so pressing again looped to the step cap
            yy, xx = self.pos()
            if G.KIND[int(lv.under[yy, xx])] in (G.UPSTAIR, G.DOWNSTAIR):
                lv.set_terrain((yy, xx), FLOOR_GLYPH)
