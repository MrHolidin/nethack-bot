"""Mines' End luckstone (A/B mines_luckstone, off by default): find the gray stones where the level file puts the
luckstone, prove each is no loadstone, keep them; a shopkeeper's offer tells which one is the luckstone.

The variants (mines.des, NetHack 3.6.6; dungeon.def:76 RNDLEVEL "minend" 3, mkmaze.c:967 picks one when the level is
made). The maps are drawn so that map (0,0) is level (3,3) (sp_lev.c:4944-4967, x_maze_max 78 and y_maze_max 20 from
decl.c:31), and NLE's columns are level x - 1 (winrl.cc:365): our square (y, x) is (map y + 3, map x + 2). The up
staircase, where we arrive, is at map (36,4) in 1 and 2, (42,8) in 3 -- with the map, how the variant is told.
  minend-1 "Mimic of the Mines" (mines.des:846-954, all of it undiggable: 888): seven niches shuffled (871-872); one
      holds the luckstone with a ruby and red glass (910-912), one a loadstone with the same two gems (907-909), four
      a mimic that looks like a gray stone over gems (891-906), one nothing (890). Five niches are closets of two
      squares behind a locked secret door (878-884), the stone on the square by the door, on top of its pile (made
      last); two (map (13,7), (66,1)) have walls behind the stone from every side: no kick test there -- their stone is
      taken only once a loadstone was found in another niche (the one loadstone of the level accounted for).
  minend-2 "Gnome King's Wine Cellar" (960-1103): the luckstone at map (70,5) (1045) at the bottom of a pile
      (1058-1061, place_object puts each new object on top) in a 2x2 chamber closed in rock, with seven random gems
      (1047-1060: any of them may be a gray stone, a loadstone too). Dug into with a pick-axe / mattock, the gems taken,
      a dead-end square dug beside each square that holds a gray stone, the pile kicked into it.
  minend-3 "Catacombs" (1109-1206): the luckstone and a flint on two of map (1,15) / (68,6) / (1,13) (1132, 1150),
      each on a level teleporter (1188-1189). Taken without a test: only those two are placed there (a random loadstone
      on one of the two squares: 7 random gems (1153-1167, 1 in 100 a loadstone: objects.c:1115) and 3 random objects
      (1177-1179, 8 in 100 a gem: mkobj.c:33) over ~670 floor squares (79198) -- about 0.02%). The teleporter is used once: it is deleted before it sends us off (teleport.c:1108), with magic
      resistance it does nothing and stays (1097-1103); to the same level 1 time in 5 ("You shudder for a moment"),
      else 1..3 levels up or to a random shallower depth (1494, 1537-1546) -- then we come back down. Its rooms open by
      secret doors (the start room: map (37,8), (47,8)): searched where the map has them.

The luckstone: mksobj makes a gem uncursed and never curses it, a loadstone always cursed (mkobj.c:886-895);
create_object curses nothing the level file leaves random (sp_lev.c:1882-1897). A loadstone picked up is cursed
(invent.c:1139-1140) and cannot be dropped (do.c:572-580), weight 500 (objects.c:1115) -- never picked up untested.

The test: a kick (dokick.c:462-725). The pile's top object is kicked (470); it moves range = Str/2 - weight/40 squares
(549), 1 only when the square beyond it is no ZAP_POS or a closed door (573-575); range < 2 is "Thump!" and the
object stays (647-651) -- and 2 times in 3 the kick then hurts us (968-975 -> 1227-1244: "Ouch!  That hurts!",
1d3 HP with Con > 15, wounded legs 1 time in 3: no kicking for 6-10 turns). A loadstone (500) never moves; a
luckstone, touchstone or flint (10) flies until a wall stops it. A mimic kicked is found (dokick.c:896-900 ->
uhitm.c:165-176: "Wait!  That's a small mimic!", or kicked: "There is a small mimic here."). Every stone that flew
is kept: luckstone, touchstone or flint, all harmless.

Which one is the luckstone: a shopkeeper buying gems offers for an unidentified gray stone half its price (a third
with a dunce cap, a visible shirt, a low-level Tourist) -- no unidentified-gem trick for them (shk.c:2342-2352: only
GEMSTONE / GLASS materials; gray stones are MINERAL), no random factor (shk.c:2324-2370 set_cost, 3390-3429
getprice): luckstone 60 -> 30 / 20, touchstone 45 -> 23 / 15, flint 1 -> 1 (objects.c:1114-1117). The luckstone is
kept (named NAME), the others sold. "offers only" (short of gold, shk.c:3204-3207) tells nothing.

Carrying it (attrib.c:350-382, timeout.c:491-505): uncursed or blessed -- Luck +3 (u.moreluck); uncursed stops Luck
from timing out both ways (bad Luck stays too), blessed only good Luck, cursed only bad Luck (and -3). So a
stone of ours known cursed is dropped (an altar's flash, nhbot.altar).

Our stones are named (C, "a particular object in inventory": do_name.c:1358-1379 docallcmd): TESTED + a number until
a price tells, NAME for the luckstone; carry.needed keeps them while not known cursed -- never dropped for weight,
thrown, dipped for a wish (fountain.c:418-420 curses a dipped item 1 time in 30); sold only to learn the price (shop
sell_step, luck_offer_keep)."""
import re
from collections import Counter, deque

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.carry import describe
from nhbot.consts import COLS, DELTA2KEY, ROWS
from nhbot.equipment import parse_armor
from nhbot.value import stack_key

NAME = "luck"
TESTED = "tested"
NAMED_RE = re.compile(rf" named (?:{NAME}|{TESTED}\d+)\b")
TESTED_RE = re.compile(rf" named ({TESTED}\d+)\b")
OFFER_RE = re.compile(r"offers (\d+) gold pieces? for your (.+?)\.\s+Sell (?:it|them)")
OFF_Y, OFF_X = 3, 2                  # our (y, x) = (map y + OFF_Y, map x + OFF_X): see the module docstring
ORTHO = ((-1, 0), (1, 0), (0, -1), (0, 1))
DIAG = ((-1, -1), (-1, 1), (1, -1), (1, 1))
SEARCH_MAX = 40                      # turns searching for one secret door (detect.c:1732-1735 dosearch0: found when
                                     # !rnl(7), about 1 in 7 a turn at Luck 0)
DOOR_KICKS = 20                      # kicks at one locked door (dokick.c:1276: it gives when rnl(35) < (Str + Dex +
                                     # Con) / 3 -- about 1 in 2 for a Valkyrie)
PILE_KICKS = 30                      # kicks at one pile (each moves its top object; a stack of rocks one by one)
SQUEEZE_WT = 560                     # what we carry at most for the pocket's squeeze (600: hack.c cant_squeeze_thru;
                                     # our weights are estimates)
DIG_TRIES = 12                       # applies of the digger at one square
HP_MIN = 0.6                         # work on it only from this fraction of max HP
LEGS_WAIT = 10                       # turns without kicking after "no shape for kicking" (dokick.c:1242: wounded legs
                                     # for 5 + rnd(5) turns)
REPLANS = 15                         # ... tried again 20 turns apart at most this often
TUNNEL_AFTER = 1000                  # turns on minend-2 after which the tunnel is planned even if exploring goes on
HOME_TURNS = 3000                    # turns at most on the way back down after a teleporter
LEVEL_TURNS = 3000                   # turns spent on Mines' End (Level.turns_here) after which it is given up
# sell offers for one unidentified gray stone (shk.c:2324-2370): half the price, or a third; rounded
PRICES = {"luckstone": 60, "touchstone": 45, "flint": 1}

# mines.des:849-867
MINEND_1 = (
    "------------------------------------------------------------------   ------",
    "|                        |.......|     |.......-...|       |.....|.       |",
    "|    ---------        ----.......-------...........|       ---...-S-      |",
    "|    |.......|        |..........................-S-      --.......|      |",
    "|    |......-------   ---........................|.       |.......--      |",
    "|    |..--........-----..........................|.       -.-..----       |",
    "|    --..--.-----........-.....................---        --..--          |",
    "|     --..--..| -----------..................---.----------..--           |",
    "|      |...--.|    |..S...S..............---................--            |",
    "|     ----..-----  ------------........--- ------------...---             |",
    "|     |.........--            ----------              ---...-- -----      |",
    "|    --.....---..--                           --------  --...---...--     |",
    "| ----..-..-- --..---------------------      --......--  ---........|     |",
    "|--....-----   --..-..................---    |........|    |.......--     |",
    "|.......|       --......................S..  --......--    ---..----      |",
    "|--.--.--        ----.................---     ------..------...--         |",
    "| |....S..          |...............-..|         ..S...........|          |",
    "--------            --------------------           ------------------------",
)
PLACES_1 = ((8, 16), (13, 7), (21, 8), (41, 14), (50, 4), (50, 16), (66, 1))     # mines.des:871, map (x, y)
# mines.des:962-980 (the IF blocks of 983-1005 change a few squares: matched with a tolerance)
MINEND_2 = (
    "---------------------------------------------------------------------------",
    "|...................................................|                     |",
    "|.|---------S--.--|...|--------------------------|..|                     |",
    "|.||---|   |.||-| |...|..........................|..|                     |",
    "|.||...| |-|.|.|---...|.............................|                ..   |",
    "|.||...|-|.....|....|-|..........................|..|.               ..   |",
    "|.||.....|-S|..|....|............................|..|..                   |",
    "|.||--|..|..|..|-|..|----------------------------|..|-.                   |",
    "|.|   |..|..|....|..................................|...                  |",
    "|.|   |..|..|----|..-----------------------------|..|....                 |",
    "|.|---|..|--|.......|----------------------------|..|.....                |",
    "|...........|----.--|......................|     |..|.......              |",
    "|-----------|...|.| |------------------|.|.|-----|..|.....|..             |",
    "|-----------|.{.|.|--------------------|.|..........|.....|....           |",
    "|...............|.S......................|-------------..-----...         |",
    "|.--------------|.|--------------------|.|.........................       |",
    "|.................|                    |.....................|........    |",
    "---------------------------------------------------------------------------",
)
CHAMBER_2 = ((4, 69), (4, 70), (5, 69), (5, 70))      # mines.des:1045-1061, map (y, x)
# mines.des:1022-1029 NON_DIGGABLE, map (x1, y1, x2, y2)
NON_DIG_2 = ((0, 0, 52, 17), (53, 0, 74, 0), (53, 17, 74, 17), (74, 1, 74, 16), (53, 7, 53, 7), (58, 12, 58, 13),
             (53, 14, 61, 14), (61, 15, 61, 16))
# mines.des:1113-1129 -- its '-' and ' ' squares are the maze MAZEWALK carves (1145): only '.' and '|' are fixed
MINEND_3 = (
    " - - - - - - - - - - -- -- - - . - - - - - - - - - -- - - -- - - - - . - - |",
    "------...---------.-----------...-----.-------.-------     ----------------|",
    " - - - - - - - - - - - . - - - . - - - - - - - - - - -- - -- - . - - - - - |",
    "------------.---------...-------------------------.---   ------------------|",
    " - - - - - - - - - - . . - - --- - . - - - - - - - - -- -- - - - - |.....| |",
    "--.---------------.......------------------------------- ----------|.....S-|",
    " - - - - |.. ..| - ....... . - - - - |.........| - - - --- - - - - |.....| |",
    "----.----|.....|------.......--------|.........|--------------.------------|",
    " - - - - |..{..| - - -.... . --- - -.S.........S - - - - - - - - - - - - - |",
    "---------|.....|--.---...------------|.........|---------------------------|",
    " - - - - |.. ..| - - - . - - - - - - |.........| - --- . - - - - - - - - - |",
    "----------------------...-------.---------------------...------------------|",
    "---..| - - - - - - - - . --- - - - - - - - - - - - - - . - - --- - - --- - |",
    "-.S..|----.-------.------- ---------.-----------------...----- -----.-------",
    "---..| - - - - - - - -- - - -- . - - - - - . - - - . - . - - -- -- - - - -- ",
    "-.S..|--------.---.---       -...---------------...{.---------   ---------  ",
    "--|. - - - - - - - -- - - - -- . - - - --- - - - . . - - - - -- - - - - - - ",
)
SPOTS_3 = ((1, 15), (68, 6), (1, 13))                 # mines.des:1132, map (x, y)
UPSTAIR = {"minend-1": (36, 4), "minend-2": (36, 4), "minend-3": (42, 8)}      # mines.des:886, 1020, 1146
MIN_MATCH = {"minend-1": 120, "minend-2": 120, "minend-3": 40}
MAX_MISS = 0.04                      # disagreeing squares, a fraction of the agreeing ones

# the gray stones look alike (objects.c:1114-1117 ROCK(..., "gray", ...)): one look for all four types
GRAY_LOOK = np.zeros(nh.MAX_GLYPH, dtype=bool)
ROCK_LOOK = np.zeros(nh.MAX_GLYPH, dtype=bool)        # a rock (its look is its own: objects.c:1118)
for _g in range(nh.MAX_GLYPH):
    if nh.glyph_is_normal_object(_g):
        _oc = nh.objclass(nh.glyph_to_obj(_g))
        GRAY_LOOK[_g] = ord(_oc.oc_class) == nh.GEM_CLASS and nh.OBJ_DESCR(_oc) == "gray"
        ROCK_LOOK[_g] = nh.OBJ_NAME(_oc) == "rock"
FLOORISH = np.zeros(G.EFFECT + 1, dtype=bool)        # kinds of a square that is no wall or rock
for _k in (G.FLOOR, G.DOORWAY, G.DOOR_OPEN, G.TRAP, G.UPSTAIR, G.DOWNSTAIR, G.OBJECT, G.GOLD, G.CORPSE):
    FLOORISH[_k] = True
OPEN_KIND = FLOORISH.copy()                           # ... by the terrain alone (no object, corpse, gold)
for _k in (G.OBJECT, G.GOLD, G.CORPSE):
    OPEN_KIND[_k] = False
SHUT = (G.WALL, G.UNKNOWN, G.DOOR_CLOSED)            # a secret door not found (a wall to us), or a closed door
FLOOR_LIT = nh.GLYPH_CMAP_OFF + 19                    # S_room: a floor square we see lit (S_darkroom: remembered dark)


def sq(mx, my):
    """Our square of map (x, y)."""
    return my + OFF_Y, mx + OFF_X


def _template(rows, floor, wall, rock):
    """(floor, wall, rock, char) on our grid; floor / wall / rock: the map characters of each."""
    char = np.full((ROWS, COLS), " ", dtype="<U1")
    for my, row in enumerate(rows):
        for mx, c in enumerate(row):
            y, x = sq(mx, my)
            if 0 <= y < ROWS and 0 <= x < COLS:
                char[y, x] = c
    inside = np.zeros((ROWS, COLS), dtype=bool)
    inside[OFF_Y:OFF_Y + len(rows), OFF_X:OFF_X + len(rows[0])] = True
    return (np.isin(char, list(floor)) & inside, np.isin(char, list(wall)) & inside,
            np.isin(char, list(rock or "\0")) & inside, char)


TEMPLATES = {"minend-1": _template(MINEND_1, ".", "-|", " "), "minend-2": _template(MINEND_2, ".", "-|", " "),
             "minend-3": _template(MINEND_3, ".{", "|", "")}


def niche_setups(char, places):
    """Per niche square p (map (x, y)): (p, h, b, o) on our grid -- we stand on h, next to p, and kick toward p; b,
    beyond p, is the floor the stone flies to (None: walls behind p from every side -- no kick test); o, outside,
    when h is a secret door (searched from and opened from, straight: no diagonal into a doorway)."""
    out = []
    for mx, my in places:
        p = sq(mx, my)
        best = None
        for dy, dx in ORTHO:
            h, b, o = (p[0] - dy, p[1] - dx), (p[0] + dy, p[1] + dx), (p[0] - 2 * dy, p[1] - 2 * dx)
            if char[h] not in ".S" or (char[h] == "S" and char[o] != "."):
                continue
            cand = (p, h, b if char[b] == "." else None, o if char[h] == "S" else None)
            if best is None or (best[2] is None and cand[2] is not None):
                best = cand
        out.append(best)
    return tuple(out)


SETUPS_1 = niche_setups(TEMPLATES["minend-1"][3], PLACES_1)
# the niche at map (13,7) lies in a pocket entered only diagonally from map (11,6) to (12,7), between the walls at
# (12,6) and (11,7) (mines.des:855-857): a squeeze
POCKET_1, SQUEEZE_1, SQUEEZE_IN = sq(13, 7), sq(11, 6), sq(12, 7)
POCKET_SIDE = {SQUEEZE_IN, POCKET_1} | {s[1] for s in SETUPS_1 if s[0] == POCKET_1}
assert TEMPLATES["minend-1"][3][sq(12, 6)] in "-|" and TEMPLATES["minend-1"][3][sq(11, 7)] in "-|"
CHAMBER = tuple(sq(mx, my) for my, mx in CHAMBER_2)
STONE_2 = sq(70, 5)                  # the luckstone's square (mines.des:1045)
DIG_OK_2 = TEMPLATES["minend-2"][2].copy()        # rock we may dig: not NON_DIGGABLE
for _x1, _y1, _x2, _y2 in NON_DIG_2:
    (_ya, _xa), (_yb, _xb) = sq(_x1, _y1), sq(_x2, _y2)
    DIG_OK_2[_ya:_yb + 1, _xa:_xb + 1] = False
SPOTS = tuple(sq(mx, my) for mx, my in SPOTS_3)
# mines.des:983-989: half the time map (52,5) is a locked secret door and the walls at (55,14), (56,14), (61,15) close
# the eastern cave (where the chamber lies) from the south: that door, found from map (51,5), is then its only way in
DOOR_2, DOOR_2_OUT = sq(52, 5), sq(51, 5)


class LuckState:
    """State of the Mines' End luckstone hunt (LuckstoneMixin)."""
    def __init__(self):
        self.variant = {}                # level key -> (seen squares when judged, variant or None)
        self.status = {}                 # (level key, site square) -> outcome of that niche / chamber square / spot
        self.searched = Counter()        # (level key, door) -> turns searched for it
        self.kicks = Counter()           # (level key, door) -> kicks at it; (level key, "pile", q) -> at a pile
        self.dug = Counter()             # (level key, square) -> applies of the digger at it
        self.no_dig = set()              # (level key, square) that would not be dug
        self.lane = {}                   # (level key, q) -> (h, b): where the pile on q is kicked from and to
        self.looked = set()              # (level key, q) chamber squares stood on, their gems taken
        self.tunnel = None               # (level key, [squares from a reachable start to the chamber])
        self.stash = None                # (level key, square, {stack_key}) our things left before the squeeze
        self.squeeze_refused = False     # the last squeeze step was refused for our weight
        self.lifting = False             # picking up our stones now (luck_lift)
        self.collect_at = {}             # (level key, site) -> the square along the kick's line we look at now
        self.plan_wait = 0               # no tunnel planned before this turn
        self.replans = 0                 # tunnel plans that found no start (the eastern cave being explored)
        self.legs_until = 0              # no kick before this turn (wounded legs)
        self.done = set()                # level keys finished
        self.home = None                 # the Mines' End level key while a teleporter sent us away from it
        self.home_since = 0              # ... since this turn
        self.last = None                 # [turn, what, level key] of our last action (summary: what we did last)
        self.seq = 0                     # the last TESTED number given
        self.price_luck = set()          # TESTED names a shopkeeper's offer showed to be the luckstone
        self.report = {}                 # game summary: variant, digger on arrival, outcome, counts
        self.stats = Counter()


class LuckstoneMixin:
    def luckstone_init(self):
        self.luck = LuckState()

    def luckstone_summary(self):
        """Game summary entries."""
        stones = [it.text for it in self.items() if it.ocls == nh.GEM_CLASS and NAMED_RE.search(it.text)]
        sites = {f"{p[0]},{p[1]}": v for (k, p), v in self.luck.status.items()
                 if isinstance(p, tuple) and isinstance(p[0], int) and isinstance(v, str)}
        end = [int(self.bl(nh.NLE_BL_DNUM)), int(self.bl(nh.NLE_BL_DLEVEL))] if self.last_bl is not None else None
        return {"luckstone": dict(self.luck.stats), "luckstone_report": dict(
            self.luck.report, carried=stones, sites=sites, end_key=end, last_act=self.luck.last,
            home=list(self.luck.home) if self.luck.home else None)}

    # ------------------------------------------------------------------ our stones
    def luck_items(self):
        """The gray stones we keep (named NAME / TESTED<n>)."""
        return [it for it in self.items() if it.ocls == nh.GEM_CLASS and NAMED_RE.search(it.text)]

    def luck_keeps(self, it):
        """carry.needed: a stone of ours, not known cursed."""
        return self.opts.mines_luckstone and it.ocls == nh.GEM_CLASS and bool(NAMED_RE.search(it.text)) \
            and not it.cursed

    def luck_price_check(self, it):
        """shop.sellables: a kept stone whose type a sell offer would tell (TESTED<n>) -- offered, and sold only if
        the offer shows it is no luckstone (luck_offer_keep)."""
        return self.opts.mines_luckstone and it.ocls == nh.GEM_CLASS and bool(TESTED_RE.search(it.text)) \
            and not it.cursed

    def luck_offer_keep(self, ocls, text, msg):
        """shop.keep_after_offer: the offer for a TESTED stone (msg) -- the luckstone's price: keep it (named NAME
        next tick); a touchstone's or flint's: sell it. No reading (short of gold, a stack we can't split): keep."""
        m = TESTED_RE.search(text) if ocls == nh.GEM_CLASS else None
        if not self.opts.mines_luckstone or m is None:
            return False
        got = OFFER_RE.search(msg)
        if "offers only" in msg or got is None:
            self.luck.stats["price_unread"] += 1
            return True
        qty = int(re.match(r"^(\d+) ", text).group(1)) if re.match(r"^\d+ ", text) else 1
        offer = int(got.group(1))
        kind = next((k for k, p in PRICES.items() if offer in (offer_for(p * qty, 2), offer_for(p * qty, 3))), None)
        self.luck.stats["price_" + (kind or "unclear")] += 1
        if kind == "luckstone":
            self.luck.price_luck.add(m.group(1))
            self.luck.report["price_id"] = self.luck.report.get("price_id", 0) + 1
            return True
        if kind is None:
            return True
        self.luck.report["sold"] = self.luck.report.get("sold", 0) + 1
        return False

    def luck_lift(self, m):
        """pickup.lift_answer: "You have a little trouble lifting a gray stone." while we pick up our stones
        (luck.lifting) -- yes: Burdened, the drop step sheds what is worth least per weight, never these."""
        return self.opts.mines_luckstone and self.luck.lifting and "a little trouble lifting" in m \
            and "gray stone" in m

    def luck_pickup_grays(self):
        """Pick up the gray stones here (luck_lift says yes to a lift into Burdened) and name them; how many came."""
        before = {it.letter for it in self.items()}
        self.luck_did("collect")
        self.luck.lifting = True
        try:
            self.pickup(lambda t: "gray stone" in t, "luckstone")
        finally:
            self.luck.lifting = False
        return self.luck_name_new(before)

    def luck_name_new(self, before):
        """Name each gray stone that came into the pack since before (letters): TESTED<n>. How many came."""
        got = 0
        for it in self.items():
            if it.letter not in before and it.ocls == nh.GEM_CLASS and "gray stone" in it.text \
                    and " named " not in it.text:
                got += 1
                if "taken_after" not in self.luck.report:   # turns on the level when the first stone was kept
                    self.luck.report["taken_after"] = int(self.level().turns_here)
                self.luck.seq += 1
                if self.name_item(it.letter, f"{TESTED}{self.luck.seq}"):
                    self.luck.stats["kept"] += 1
                    self.luck.report["kept"] = self.luck.report.get("kept", 0) + 1
        return got

    def luck_housekeeping(self):
        """Every tick with the flag on: a stone of ours known cursed dropped; the one a price showed to be the
        luckstone named NAME. True if it used the turn."""
        for it in self.luck_items():
            if it.cursed:
                self.luck.stats["dropped_cursed"] += 1
                self.drop_units(it.letter)
                return True
            m = TESTED_RE.search(it.text)
            if m and m.group(1) in self.luck.price_luck:
                self.luck.price_luck.discard(m.group(1))
                if self.name_item(it.letter, NAME):
                    self.luck.stats["named_luck"] += 1
        return False

    # ------------------------------------------------------------------ which Mines' End
    def minend_variant(self, lv):
        """The variant of this deep Mines level (Mines levels 8-9: dungeon.def:70 "(8, 2)", dungeon.c:796-798): its up
        staircase where the variant has it, and our map agreeing with the variant's on MIN_MATCH squares or more,
        disagreeing on at most MAX_MISS of them. None until then. Judged again as more of the map is seen."""
        if lv.key[0] != 2 or lv.key[1] < 8:
            return None
        seen = int(lv.seen.sum())
        got = self.luck.variant.get(lv.key)
        if got is not None and (got[1] is not None or got[0] == seen):
            return got[1]
        k = self.kinds(lv)
        floor, wall = FLOORISH[k], k == G.WALL
        found = None
        for name, (t_floor, t_wall, t_rock, _) in TEMPLATES.items():
            if k[sq(*UPSTAIR[name])] != G.UPSTAIR:
                continue
            match = int((floor & t_floor).sum() + (wall & t_wall).sum())
            miss = int((floor & (t_wall | t_rock)).sum() + (wall & t_floor).sum())
            if match >= MIN_MATCH[name] and miss <= MAX_MISS * match:
                found = name
        self.luck.variant[lv.key] = (seen, found)
        if found is not None:
            self.luck.stats[found] += 1
            self.luck.report.update(variant=found, digger=self.dig_hand_means() is not None, outcome="working")
        return found

    def luck_holds(self, lv):
        """explore: Mines' End with work left for us, or a teleporter sent us up from it (luck.home) -- no
        mines_return yet ("bottom", "no way")."""
        if not self.opts.mines_luckstone:
            return False
        if self.luck.home is not None:
            return True
        if lv.key in self.luck.done:
            return False
        v = self.minend_variant(lv)
        return v is not None and not (v == "minend-2" and (self.dig_hand_means() is None
                                                           or lv.key in self.digging.refused))

    def luck_digging(self, lv):
        """vault.vault_rob_step: the digger stays in our hands -- minend-2's work goes on here (luck_finish puts it
        away)."""
        return self.opts.mines_luckstone and lv.key not in self.luck.done \
            and self.luck.variant.get(lv.key, (0, None))[1] == "minend-2"

    # ------------------------------------------------------------------ the step
    def luckstone_step(self, lv, c):
        """mines_luckstone, nothing in view: our stones' housekeeping (luck_housekeeping); sent off Mines' End by a
        teleporter: back down; on Mines' End from HP_MIN of max HP: the variant's work (luck_minend1 / 2 / 3). True if
        it used the turn."""
        if not self.opts.mines_luckstone or c.vis:
            return False
        if self.luck_housekeeping():
            return True
        if self.luck.home is not None and lv.key != self.luck.home:
            return self.luck_go_home(lv)
        if lv.key in self.luck.done or c.hp < c.maxhp * HP_MIN:
            return False
        v = self.minend_variant(lv)
        if v is None:
            return False
        self.luck.home = None
        if lv.turns_here > LEVEL_TURNS:
            return self.luck_finish(lv, "timeout")
        if v == "minend-1":
            return self.luck_minend1(lv)
        if v == "minend-2":
            return self.luck_minend2(lv)
        return self.luck_minend3(lv)

    def luck_finish(self, lv, outcome):
        """Done on this level: the outcome for the summary, the digger back out of our hands."""
        self.luck.done.add(lv.key)
        if self.luck.report.get("outcome") in (None, "working"):
            self.luck.report["outcome"] = outcome
        self.luck.stats["outcome_" + outcome] += 1
        return self.dig_unwield()

    def luck_did(self, what):
        """Note our last action (summary last_act)."""
        self.luck.last = [self.turn(), what, list(self.cur_key) if self.cur_key else None]

    def luck_status(self, lv, p, st):
        self.luck.status[(lv.key, p)] = st
        self.luck.stats[st] += 1
        if st in ("thump", "mimic", "kicked"):
            self.luck.stats["tested"] += 1                   # the kick told what it is

    def luck_go_home(self, lv):
        """A teleporter sent us up from Mines' End: down again -- a Mines level above it: its down staircase we know;
        elsewhere the usual way (mines.mines_trip_step, explore). True if it used the turn."""
        home = self.luck.home
        if self.turn() - self.luck.home_since > HOME_TURNS:
            self.luck.home = None                            # given up: the Mines may be left now
            self.luck.stats["home_given_up"] += 1
            self.luck.report["outcome"] = "home_given_up"
            return False
        if lv.key[0] != 2 or lv.key[1] >= home[1]:
            return False
        down = self.stairs_mask(lv, G.DOWNSTAIR)
        if not down.any():
            return False
        self.luck.stats["home_steps"] += 1
        self.luck_did("home")
        return self.stairs_step(lv, self.grids(lv), down, ">")

    # ------------------------------------------------------------------ walking and doors
    def luck_walk(self, lv, targets):
        """One step toward the nearest of targets (squares) by path -- they may be unseen yet (a dark closet). The
        status of walk_to."""
        mask = np.zeros((ROWS, COLS), dtype=bool)
        for t in targets:
            mask[t] = True
        st = self.walk_to(lv, mask, act="luckstone", also=mask)[0]
        if st == "moved":
            self.luck_did("walk")
        return st

    def luck_door(self, lv, door, out):
        """On out, straight beside door (a secret door of the map): search for it (SEARCH_MAX turns at most), then
        open it -- a step into it (autoopen), the lock tool, or kicks (Mines' End has no watch; nav.move never kicks
        a door in the Mines, for Minetown's). True if it used the turn; False: given up."""
        self.cur_act = "luckstone"
        if self.kinds(lv)[door] != G.DOOR_CLOSED:            # the secret door not found yet
            if self.luck.searched[(lv.key, door)] >= SEARCH_MAX:
                return False
            t0 = self.turn()
            self.luck_did("search")
            self.search_turns(5)
            self.luck.searched[(lv.key, door)] += max(1, self.turn() - t0)
            return True
        if door not in lv.locked:
            self.move(door)                                  # opens it, or "This door is locked." (mapmem)
            return True
        if self.lock_door_step(lv, door):                    # unlocked with the tool (nhbot.locktools)
            return True
        if self.luck.kicks[(lv.key, door)] >= DOOR_KICKS:
            return False
        if self.luck_legs_wait():
            return True
        self.luck.kicks[(lv.key, door)] += 1
        self.luck.stats["door_kicks"] += 1
        self.luck_kick_toward(door)
        if self.kinds(lv)[door] != G.DOOR_CLOSED:
            lv.locked.discard(door)                          # it crashed open / shattered (dokick.c:1286-1290)
        return True

    def luck_doors_step(self, lv, char):
        """Our targets are out of reach: the map's secret doors (char "S") not open yet whose straight outside
        square we can reach -- the nearest searched for and opened (luck_door). True if it used the turn."""
        here = self.pos()
        k = self.kinds(lv)
        outs = {}
        for d in zip(*np.nonzero(char == "S")):
            d = (int(d[0]), int(d[1]))
            if k[d] not in SHUT or self.luck.status.get((lv.key, d)) == "door_given_up":
                continue
            for dy, dx in ORTHO:
                o = (d[0] + dy, d[1] + dx)
                if 0 <= o[0] < ROWS and 0 <= o[1] < COLS and FLOORISH[k[o]]:
                    outs.setdefault(o, d)
        if not outs:
            return False
        if here in outs:
            if self.luck_door(lv, outs[here], here):
                return True
            self.luck_status(lv, outs[here], "door_given_up")
            return False
        return self.luck_walk(lv, outs) == "moved"

    # ------------------------------------------------------------------ kicking
    def luck_kick_toward(self, target):
        """Kick toward the adjacent square target; the messages it brought. Not a step (nav.not_stepping): no failure
        is put on the square (mapmem blocks a door the legs refused to kick -- here a wait instead)."""
        self.not_stepping()
        self.luck_did("kick")
        y, x = self.pos()
        seq0 = self.msg_seq
        self.kick(DELTA2KEY[(target[0] - y, target[1] - x)])
        said = self.text_since(seq0)
        if "no shape for kicking" in said:
            self.luck.legs_until = self.turn() + LEGS_WAIT
            self.luck.stats["legs_wait"] += 1
        return said

    def luck_legs_wait(self):
        """Wounded legs (luck_kick_toward): search here till they may have healed. True if it used the turn."""
        if self.turn() >= self.luck.legs_until:
            return False
        self.search_turns(min(5, self.luck.legs_until - self.turn()))
        return True

    def luck_kick_pile(self, lv, q, n):
        """On a square next to q: kick the pile on q, one object a kick (its top: dokick.c:470), on along its lane --
        n kicks at most, fewer once the game says "You kick at empty space" (q bare: dokick.c:1252-1258; a dark square
        shows us nothing of what is left). "acted" (the turn used), "wait" (a monster on q before any kick: nothing
        done), else the outcome: "thump" (a loadstone, or something as heavy, on top -- dokick.c:647-651 -- whatever
        flew before it is on the lane), "mimic", "kicked", "empty" (nothing was there)."""
        kicked = self.luck.kicks[(lv.key, "pile", q)]
        if G.KIND[self.obs["glyphs"][q]] == G.MONSTER:
            return "mimic" if kicked else "wait"
        if kicked >= min(n, PILE_KICKS):
            return "kicked" if kicked else "empty"
        self.cur_act = "luckstone"
        if self.luck_legs_wait():
            return "acted"
        said = self.luck_kick_toward(q)
        if "no shape for kicking" in said:
            return "acted"
        self.luck.stats["kicks"] += 1
        if "Thump!" in said:
            return "thump"
        if "Wait!" in said or "mimic" in said or G.KIND[self.obs["glyphs"][q]] == G.MONSTER:
            return "mimic"
        if "empty space" in said or "strain a muscle" in said:
            return "kicked" if kicked else "empty"
        self.luck.kicks[(lv.key, "pile", q)] += 1
        return "acted"

    def luck_unseen_or_gray(self, p):
        """The square shows a gray stone, a monster, or nothing we can read (dark: the objects on an unlit square are
        not shown, even next to us) -- not a visible bare floor or other object."""
        g = int(self.obs["glyphs"][p])
        return bool(GRAY_LOOK[g]) or G.KIND[g] in (G.MONSTER, G.UNKNOWN) or (
            G.KIND[g] == G.FLOOR and g != FLOOR_LIT)

    def luck_collect(self, lv, b, site, line=None):
        """Walk to b; there pick up every gray stone (all of them flew from a kick, or lie where only the luckstone and
        a flint are placed) and name them; a free inventory letter made first for each (value.slot_victim dropped).
        line: the kick's direction -- nothing on b, and the square beyond open (a tunnel a dwarf dug on, unseen in the
        dark when the lane was chosen): the stones flew on till a wall stopped them (dokick.c:686 bhit), followed.
        Sets site's status to "taken" / "empty" when done. True if it used the turn."""
        key = (lv.key, site)
        at = self.luck.collect_at.get(key, b)
        if self.pos() != at:
            if self.luck_walk(lv, [at]) == "moved":
                return True
            self.luck_status(lv, site, "lost")
            return False
        grays = [n for n in self.look_here() if "gray stone" in n]
        if not grays:
            nxt = (at[0] + line[0], at[1] + line[1]) if line else None
            if nxt is not None and 0 <= nxt[0] < ROWS and 0 <= nxt[1] < COLS and self.luck_open(lv, nxt) \
                    and abs(nxt[0] - b[0]) + abs(nxt[1] - b[1]) <= 10:
                self.luck.collect_at[key] = nxt
                self.luck.stats["followed"] += 1
                return self.luck_walk(lv, [nxt]) == "moved"
            self.luck_status(lv, site, "empty")
            return False
        if self.letters_free() < len(grays):
            victim = self.slot_victim()
            if victim is not None:
                self.cur_act = "luckstone"
                self.luck.stats["slot_dropped"] += 1
                self.drop_units(victim.letter)
                return True
        self.cur_act = "luckstone"
        got = self.luck_pickup_grays()
        self.luck_status(lv, site, "taken" if got else "not_picked")
        return True

    # ------------------------------------------------------------------ minend-1
    def luck_minend1(self, lv):
        """The niches nearest first: each one's secret door found and opened, its pile kicked from the door square
        (luck_kick_pile) when a gray stone shows, the gray stones that flew picked up. A niche with walls behind its
        stone: probed by a kick (a mimic shows) and its stone taken only once another niche gave "Thump!" (the
        level's loadstone) -- the one in the pocket behind a diagonal squeeze with our pack left outside
        (luck_squeeze). True if it used the turn."""
        thumped = any(self.luck.status.get((lv.key, s[0])) == "thump" for s in SETUPS_1)
        for s in SETUPS_1:
            st = self.luck.status.get((lv.key, s[0]))
            if st == "kicked":
                return self.luck_collect(lv, s[2], s[0])
            if st == "blind_object" and thumped:
                if s[0] == POCKET_1 and self.pos() not in POCKET_SIDE:
                    return self.luck_squeeze(lv)
                return self.luck_collect(lv, s[0], s[0])
        if self.luck.stash is not None and self.luck.stash[0] == lv.key \
                and (lv.key, POCKET_1) in self.luck.status:
            return self.luck_unstash(lv)
        todo = [s for s in SETUPS_1 if (lv.key, s[0]) not in self.luck.status
                and (s[2] is not None or thumped or self.luck_testable_done(lv))]
        if not todo:
            return self.luck_end1(lv)
        here = self.pos()
        live = self.obs["glyphs"]
        targets = {}
        for s in todo:
            p, h, b, o = s
            t = o if o is not None and self.kinds(lv)[h] in SHUT else h
            if t == here:
                return self.luck_niche_here(lv, s)
            if p == POCKET_1 and here not in POCKET_SIDE:
                if here == SQUEEZE_1:
                    return self.luck_squeeze(lv)
                t = SQUEEZE_1                                # the pocket: through the squeeze
            if G.KIND[live[t]] != G.MONSTER:
                targets.setdefault(t, s)
        if targets and self.luck_walk(lv, targets) == "moved":
            return True
        if self.luck_doors_step(lv, TEMPLATES["minend-1"][3]):
            return True
        if self.mines.return_on or lv.explored:
            for s in targets.values():
                self.luck_status(lv, s[0], "unreachable")
        return False

    def luck_testable_done(self, lv):
        return all((lv.key, s[0]) in self.luck.status for s in SETUPS_1 if s[2] is not None)

    def luck_niche_here(self, lv, s):
        """We stand where niche s wants us: outside its door (luck_door), or on h (the kick)."""
        p, h, b, o = s
        if self.pos() == o:
            if self.luck_door(lv, h, o):
                return True
            self.luck_status(lv, p, "door_given_up")
            return False
        if not self.luck.kicks[(lv.key, "pile", p)] and not self.luck_unseen_or_gray(p):
            self.luck_status(lv, p, "empty")                 # (once kicked, the gems under the stone show)
            return False
        if b is None:                                        # walls behind the stone: a mimic or an object?
            if self.luck_legs_wait():
                return True
            said = self.luck_kick_toward(p)
            if "no shape for kicking" in said:
                return True
            self.luck_status(lv, p, "mimic" if "Wait!" in said or "mimic" in said
                             else "empty" if "empty space" in said or "strain a muscle" in said else "blind_object")
            return True
        out = self.luck_kick_pile(lv, p, 1)                  # the gray stone lies on top (mines.des:907-912)
        if out in ("acted", "wait"):
            return out == "acted"
        self.luck_status(lv, p, out)
        return False

    def luck_squeeze(self, lv):
        """On SQUEEZE_1, the pocket's niche behind a diagonal squeeze (hack.c test_move -> cant_squeeze_thru: more than
        600 carried, worn things too, is "You are carrying too much to get through"): our things dropped here, the
        heaviest first (gold too: invent.c 100 coins weigh 1), till we carry at most SQUEEZE_WT (luck.stash: picked
        up again after, luck_unstash), then the diagonal step -- refused with nothing left to drop but what we wear:
        the pocket given up ("too_heavy"). True if it used the turn."""
        here = self.pos()
        if here != SQUEEZE_1:
            return self.luck_walk(lv, [SQUEEZE_1]) == "moved"
        self.cur_act = "luckstone"
        cands = [it for it in self.items() if not it.on_body and not NAMED_RE.search(it.text)
                 and it.key not in self.carry.cant_drop]
        refused, self.luck.squeeze_refused = self.luck.squeeze_refused, False
        if cands and (self.inventory_weight() > SQUEEZE_WT or refused):
            it = max(cands, key=item_weight)
            if self.luck.stash is None:
                self.luck.stash = (lv.key, here, set())
                self.luck.stats["stash"] += 1
            self.luck.stash[2].add(stack_key(it.text))
            self.luck_did("stash")
            self.drop_units(it.letter)
            return True
        worn = [it for it in self.items() if it.ocls == nh.ARMOR_CLASS and it.worn and not it.cursed]
        if worn and (self.inventory_weight() > SQUEEZE_WT or refused):
            it = max(worn, key=item_weight)                  # off, then dropped like the rest next tick
            a = parse_armor(it.text) or {"slot": None}
            a["letter"] = it.letter
            self.luck_did("strip")
            if self.take_off(a):
                self.luck.stats["squeeze_unworn"] += 1
                self.luck.squeeze_refused = refused
                return True
        if refused:
            self.luck_status(lv, POCKET_1, "too_heavy")
            return False
        self.luck.stats["squeeze_steps"] += 1
        seq0 = self.msg_seq
        self.press(DELTA2KEY[(SQUEEZE_IN[0] - here[0], SQUEEZE_IN[1] - here[1])])
        # refused: no game time -- drop more, or give up, next tick
        self.luck.squeeze_refused = "carrying too much" in self.text_since(seq0)
        return True

    def luck_unstash(self, lv):
        """Back on the stash square: our things picked up again. True if it used the turn."""
        key, square, keys = self.luck.stash
        if self.pos() != square:
            if self.luck_walk(lv, [square]) == "moved":
                return True
        else:
            self.cur_act = "luckstone"
            self.pickup(lambda t: stack_key(t) in keys, "luckstone")
            self.luck.stats["unstash"] += 1
        self.luck.stash = None
        return True

    def luck_end1(self, lv):
        took = any(v == "taken" for (k, _), v in self.luck.status.items() if k == lv.key)
        blind = any(self.luck.status.get((lv.key, s[0])) == "blind_object" for s in SETUPS_1)
        return self.luck_finish(lv, "taken" if took else "both_untestable" if blind else "not_found")

    # ------------------------------------------------------------------ minend-2
    def luck_minend2(self, lv):
        """With a pick-axe / mattock: tunnel into the chamber (luck_tunnel_step), take the gems of each chamber
        square, and for each square holding gray stones dig a dead end beside it, kick its pile into the dead end
        from the chamber square opposite and pick up the gray stones there. True if it used the turn."""
        means = self.dig_hand_means()
        if means is None or lv.key in self.digging.refused:
            self.luck.report["outcome"] = "no_digger"
            return False
        todo = [q for q in sorted(CHAMBER, key=lambda q: q != STONE_2) if self.luck.status.get((lv.key, q))
                not in ("taken", "empty", "thump", "mimic", "no_lane", "lost", "not_picked")]
        if not todo:
            took = any(v == "taken" for (k, _), v in self.luck.status.items() if k == lv.key)
            return self.luck_finish(lv, "taken" if took else "not_found")
        if self.pos() not in CHAMBER and not self.luck_reachable(lv, [q for q in CHAMBER if self.luck_open(lv, q)]):
            return self.luck_tunnel_step(lv, means)
        return self.luck_chamber_square(lv, todo[0], means)

    def luck_open(self, lv, p):
        """A square we know as open ground -- by the terrain seen there (Level.terrain): an object glyph alone is no
        proof (the Mines' rock holds gems: mkmap.c mineralize; "It's solid stone.")."""
        return bool(OPEN_KIND[G.KIND[lv.terrain[p]]] or OPEN_KIND[G.KIND[self.obs["glyphs"][p]]])

    def luck_reachable(self, lv, squares):
        """Any of squares reachable by path from here."""
        if not squares:
            return False
        mask = np.zeros((ROWS, COLS), dtype=bool)
        for p in squares:
            mask[p] = True
        k_mem, k_live, passable = self.grids(lv)
        return self.dijkstra(lv, k_mem, k_live, passable, self.pos(), mask, want_dist=False)[2] is not None

    def luck_chamber_square(self, lv, q, means):
        """One chamber square: stand on it, take its gems (take_reason), note whether gray stones lie there; dig the
        dead end b of its lane from q, kick the pile from h into b, collect at b. True if it used the turn."""
        key = (lv.key, q)
        if key not in self.luck.looked:
            if self.pos() != q:
                if self.luck_walk(lv, [q]) == "moved":
                    return True
                self.luck_status(lv, q, "lost")
                return False
            names = self.look_here()
            self.luck.looked.add(key)
            if not any("gray stone" in n for n in names):
                self.luck_status(lv, q, "empty")
                return False
            if any(self.take_reason(n) is not None for n in names if "gray stone" not in n):
                self.cur_act = "luckstone"
                self.pickup(lambda t: "gray stone" not in t and self.take_reason(t) is not None, "luckstone")
                return True
            return False
        lane = self.luck.lane.get(key) or self.luck_lane(lv, q)
        if lane is None:
            self.luck_status(lv, q, "no_lane")
            return False
        self.luck.lane[key] = lane
        h, b = lane
        st = self.luck.status.get(key)
        if st in ("kicked", "thump_after"):
            return self.luck_collect(lv, b, q, (b[0] - q[0], b[1] - q[1]))
        if not self.luck_open(lv, b):                        # dig the dead end from q
            if self.pos() != q:
                return self.luck_walk(lv, [q]) == "moved"
            return self.luck_dig(lv, b, means, q)
        if self.pos() != h:
            return self.luck_walk(lv, [h]) == "moved"
        out = self.luck_kick_pile(lv, q, PILE_KICKS)
        if out in ("acted", "wait"):
            return out == "acted"
        if out == "thump" and self.luck.kicks[(lv.key, "pile", q)]:
            out = "thump_after"                              # a heavy one under: what flew before it is on b
        self.luck_status(lv, q, out)
        return False

    def luck_lane(self, lv, q):
        """(h, b) for the pile on q: h a chamber square beside q, b beyond q on the other side (straight first; a
        diagonal kick flies as well, dokick.c:686 bhit). Best a b of rock we dig ourselves (DIG_OK_2, not refused:
        "This wall is too hard to dig into"), the square beyond it rock as far as the map tells; then a b open
        already with the square beyond known shut; last a b open with open ground beyond (a dwarf's tunnel: the
        stones fly on, luck_collect follows the line)."""
        cands = []
        for rank_dir, (dy, dx) in enumerate(ORTHO + DIAG):
            h, b, bb = (q[0] - dy, q[1] - dx), (q[0] + dy, q[1] + dx), (q[0] + 2 * dy, q[1] + 2 * dx)
            if h not in CHAMBER or b in CHAMBER or (lv.key, b) in self.luck.no_dig:
                continue
            open_b, open_bb = self.luck_open(lv, b), self.luck_open(lv, bb) or TEMPLATES["minend-2"][0][bb]
            if not open_b and not DIG_OK_2[b]:
                continue
            rank = (0 if not open_b and not open_bb else 1 if not open_bb else 2, rank_dir)
            cands.append((rank, (h, b)))
        return min(cands)[1] if cands else None

    def luck_dig(self, lv, target, means, here):
        """Apply the digger from here toward the adjacent target (dig_at); a square that would not give way after
        DIG_TRIES applies is noted (no_dig). True if it used the turn."""
        key = (lv.key, target)
        if self.luck.dug[key] >= DIG_TRIES or key in self.luck.no_dig:
            self.luck.no_dig.add(key)
            self.luck.lane.pop((lv.key, here), None)
            self.luck.tunnel = None
            return False
        self.cur_act = "luckstone"
        self.luck_did("dig")
        said = self.dig_at(lv, target, means)
        if said is None:
            return True                                      # the digger wielded this turn
        self.luck.dug[key] += 1
        self.luck.stats["dig_applies"] += 1
        if "too hard to" in said:
            self.luck.no_dig.add(key)
            self.luck.tunnel = None
        return True

    def luck_tunnel_step(self, lv, means):
        """Dig our way to the chamber: the fewest squares of diggable rock (DIG_OK_2, straight steps: a squeeze between
        rock fails when we carry much, hack.c test_move) from a square we can reach to a square next to the chamber;
        walked to its start, each square dug and stepped into. True if it used the turn."""
        plan = self.luck.tunnel
        if plan is None or plan[0] != lv.key:
            if not (lv.explored or self.mines.return_on or lv.turns_here > TUNNEL_AFTER) \
                    or self.turn() < self.luck.plan_wait:
                return False                                 # explored first: the start nearest the chamber known
            path = self.luck_tunnel_plan(lv)
            if path is None:
                if self.luck_east_door(lv):
                    return True
                if self.kinds(lv)[DOOR_2] not in SHUT and self.luck.replans < REPLANS:
                    self.luck.replans += 1                   # the eastern cave just opened: explored first
                    self.luck.plan_wait = self.turn() + 20
                    return False
                return self.luck_finish(lv, "no_tunnel")
            plan = self.luck.tunnel = (lv.key, path)
            self.luck.stats["tunnels"] += 1
        path = plan[1]
        here = self.pos()
        if here not in path:
            st = self.luck_walk(lv, [path[0]])
            if st != "moved":
                self.luck.tunnel = None
            return st == "moved"
        i = path.index(here)
        if i + 1 >= len(path):
            return False
        nxt = path[i + 1]
        if self.luck_open(lv, nxt):
            self.cur_act = "luckstone"
            self.move(nxt)
            return True
        return self.luck_dig(lv, nxt, means, here)

    def luck_east_door(self, lv):
        """No start for the tunnel within reach: the eastern cave shut (DOOR_2) -- its secret door searched for from
        DOOR_2_OUT and opened (luck_door). True if it used the turn."""
        if self.kinds(lv)[DOOR_2] not in SHUT or self.luck.status.get((lv.key, DOOR_2)) == "door_given_up":
            return False
        if self.pos() != DOOR_2_OUT:
            return self.luck_walk(lv, [DOOR_2_OUT]) == "moved"
        if self.luck_door(lv, DOOR_2, DOOR_2_OUT):
            return True
        self.luck_status(lv, DOOR_2, "door_given_up")
        return False

    def luck_tunnel_plan(self, lv):
        """[start, ..., a chamber square]: breadth first from the chamber over diggable rock (or open squares) to the
        nearest square we can reach; None."""
        k_mem, k_live, passable = self.grids(lv)
        dist, _, _ = self.dijkstra(lv, k_mem, k_live, passable, self.pos(), None)
        reach = dist < (1 << 30)
        prev = {q: None for q in CHAMBER}
        todo = deque(CHAMBER)
        while todo:
            p = todo.popleft()
            if p not in CHAMBER and reach[p]:
                path = [p]
                while prev[path[-1]] is not None:
                    path.append(prev[path[-1]])
                return path
            for dy, dx in ORTHO:
                n = (p[0] + dy, p[1] + dx)
                if n in prev or not (0 <= n[0] < ROWS and 0 <= n[1] < COLS) or (lv.key, n) in self.luck.no_dig:
                    continue
                if DIG_OK_2[n] or reach[n] or FLOORISH[k_mem[n]]:
                    prev[n] = p
                    todo.append(n)
        return None

    # ------------------------------------------------------------------ minend-3
    def luck_minend3(self, lv):
        """The three spots: walked onto (their closets' and rooms' secret doors found by luck_doors_step); a
        teleporter there sends us off (luck.home: back down), or does nothing (magic resistance), or keeps us here
        (the same level); on a spot, its gray stones taken untested. True if it used the turn."""
        here = self.pos()
        k = self.kinds(lv)
        todo = []
        for p in SPOTS:
            if (lv.key, p) in self.luck.status:
                continue
            if here == p:
                grays = any("gray stone" in n for n in self.look_here())
                got = 0
                if grays:
                    self.cur_act = "luckstone"
                    got = self.luck_pickup_grays()
                self.luck_status(lv, p, "taken" if got else "not_picked" if grays else "empty")
                return grays
            if lv.seen[p] and FLOORISH[k[p]] and not G.IS_COVERED[G.KIND[lv.under[p]]]:
                self.luck_status(lv, p, "empty")             # seen bare (the third spot holds nothing)
                continue
            todo.append(p)
        if not todo:
            took = any(v == "taken" for (kk, _), v in self.luck.status.items() if kk == lv.key)
            return self.luck_finish(lv, "taken" if took else "not_found")
        seq0 = self.msg_seq
        st = self.luck_walk(lv, todo)
        if st == "moved":
            said = self.text_since(seq0)
            if "level teleport trap" in said:
                self.luck.stats["teleporter"] += 1
                self.luck.report["teleports"] = self.luck.report.get("teleports", 0) + 1
                if "wrenching sensation" in said:
                    self.luck.stats["teleporter_resisted"] += 1
                elif (self.bl(nh.NLE_BL_DNUM), self.bl(nh.NLE_BL_DLEVEL)) != lv.key:
                    self.luck.home = lv.key                  # sent off: back down (luck_go_home)
                    self.luck_did("teleported")
                    self.luck.home_since = self.turn()
            return True
        if self.luck_doors_step(lv, TEMPLATES["minend-3"][3]):
            return True
        if self.mines.return_on or (lv.explored and not self.luck_door_left(lv, TEMPLATES["minend-3"][3])):
            for p in todo:
                self.luck_status(lv, p, "unreachable")
        return False

    def luck_door_left(self, lv, char):
        """A secret door of the map not given up yet (luck_doors_step may still open a way)."""
        k = self.kinds(lv)
        return any(k[d] in SHUT and self.luck.status.get((lv.key, (int(d[0]), int(d[1])))) != "door_given_up"
                   for d in zip(*np.nonzero(char == "S")))

    # ------------------------------------------------------------------ naming
    def name_item(self, letter, name):
        """#name one inventory item (C, "a particular object in inventory": do_name.c docallcmd); no game time.
        True if the name was given."""
        self.raw_step(ord("C"))
        if "What do you want to name?" not in self.tty_text():
            self.settle()
            return False
        self.raw_step(ord("i"))
        if not self.obs["misc"][0] or "name" not in self.message().lower():
            self.settle()
            return False
        self.raw_step(ord(letter))
        if not self.obs["misc"][1]:
            self.settle()
            return False
        for ch in name:
            self.raw_step(ord(ch))
        self.raw_step(13)
        self.settle()
        return True


def item_weight(it):
    """What a stack of ours weighs, as far as its text tells (carry.describe; invent.c: 100 coins weigh 1)."""
    if it.ocls == nh.COIN_CLASS:
        return (int(re.match(r"\d+", it.text).group()) + 50) // 100 if re.match(r"\d+", it.text) else 1
    d = describe(it.ocls, it.text)
    return d["wt"] * d["qty"]


def offer_for(price, divisor):
    """A shopkeeper's sell offer for an unidentified gray stone of this price (shk.c:2354-2366 set_cost)."""
    return max(1, (price * 10 // divisor + 5) // 10)
