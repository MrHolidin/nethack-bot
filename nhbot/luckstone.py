"""Mines' End luckstone (A/B mines_luckstone, off by default): find it, prove it is no loadstone, keep it.

The variants (mines.des, NetHack 3.6.6; dungeon.def:76 RNDLEVEL "minend" 3, mkmaze.c:967 picks one when the level is
made). The maps are drawn at GEOMETRY center: map (0,0) is level (3,3) (sp_lev.c:4944-4967, x_maze_max 78 and
y_maze_max 20 from decl.c:31), and NLE's columns are level x - 1 (winrl.cc:365) -- our square (y, x) is
(map y + 3, map x + 2). All three put their up staircase where we arrive: map (36,4) for 1 and 2, (42,8) for 3.
  minend-1 "Mimic of the Mines" (mines.des:846-954): seven niche squares shuffled (871-872); one holds a luckstone with
      a ruby and red glass (910-912), one a loadstone with the same two gems (907-909) -- the two piles look the same --,
      four hold a mimic that looks like a luckstone / loadstone / flint / touchstone over gems (891-906), one is empty
      (890). Five niches are closets of two squares behind a locked secret door (878-884), the stone on the square by
      the door; two (map (13,7), (66,1)) have no square beyond the stone for it to fly into: no kick test there.
  minend-2 "Gnome King's Wine Cellar" (960-1103): the luckstone at map (70,5) (1045), at the bottom of a pile of
      gems (1058-1061: created after it, place_object puts each on top) in a 2x2 chamber closed in rock: digging only.
  minend-3 "Catacombs" (1109-1206): the luckstone on one of map (1,15) / (68,6) / (1,13) (1132, 1150), each on a
      level teleporter (1188-1189, one use: teleport.c:1108 deltrap): stepping there sends us off the level.
  Not handled yet: minend-2 and minend-3 (the variant is only counted).

The luckstone: mksobj makes a gem uncursed and never curses it, a loadstone always cursed (mkobj.c:886-895);
create_object curses nothing the level file leaves random (sp_lev.c:1881-1897). A loadstone picked up is cursed
(invent.c:1139-1140) and cannot be dropped (do.c:572-580), weight 500 (objects.c:1115) -- never picked up untested.

The test: a kick (dokick.c:462-725). The pile's top object is kicked (470); it moves range = Str/2 - weight/40 squares
(549), 1 only when the square beyond it is no ZAP_POS or a closed door (573-575); range < 2 is "Thump!" and the
object stays (647-651) -- and 2 times in 3 the kick then hurts us (968-975 -> 1227-1244: "Ouch!  That hurts!",
1d3 HP with Con > 15, wounded legs 1 time in 3: no kicking for 6-10 turns). A loadstone (500) never moves; a
luckstone (10) flies to the closet's far square. A mimic kicked is found (dokick.c:896-900 maybe_kick_monster ->
uhitm.c:165-176 attack_checks: "Wait!  That's a small mimic!", or kicked: "There is a small mimic here."). In
minend-1 the gray stone lies on top of its pile (created last). Kicking wakes the monsters near (dokick.c:902).

Carrying it (attrib.c:350-382, timeout.c:491-505): uncursed or blessed -- Luck +3 (u.moreluck); uncursed stops Luck
from timing out both ways (bad Luck stays too), blessed only good Luck, cursed only bad Luck (and -3). So a
cursed one is dropped as soon as we know it (an altar's flash, nhbot.altar).

Ours is named NAME (C, "a particular object in inventory": do_name.c docallcmd) so every rule knows it by its
text: carry.needed keeps it while not known cursed -- value.keep_plan "needed": never dropped for weight, sold or
thrown; excalibur.junk_to_dip never dips it for a wish (fountain.c:418-420 curses a dipped item 1 time in 30).
"""
from collections import Counter

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import COLS, DELTA2KEY, ROWS

NAME = "luck"
OFF_Y, OFF_X = 3, 2                  # our (y, x) = (map y + OFF_Y, map x + OFF_X): see the module docstring
ORTHO = ((-1, 0), (1, 0), (0, -1), (0, 1))
SEARCH_MAX = 40                      # turns searching for one niche's secret door (detect.c:1732-1735 dosearch0:
                                     # found when !rnl(7), about 1 in 7 a turn at Luck 0)
DOOR_KICKS = 20                      # kicks at one locked niche door (dokick.c:1276: it gives when
                                     # rnl(35) < (Str + Dex + Con) / 3 -- about 1 in 2 for a Valkyrie)
HP_MIN = 0.6                         # work on it only from this fraction of max HP
LEGS_WAIT = 10                       # turns without kicking after "no shape for kicking" (dokick.c:1242: wounded
                                     # legs for 5 + rnd(5) turns)

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
VARIANT_MIN_MATCH = 120              # squares of a template our map must agree with before we believe it
VARIANT_MAX_MISS = 0.04              # ... and disagree with at most this fraction of that

# the gray stones look alike (objects.c:1114-1117 ROCK(..., "gray", ...)): one look for all four types
GRAY_LOOK = np.zeros(nh.MAX_GLYPH, dtype=bool)
for _g in range(nh.MAX_GLYPH):
    if nh.glyph_is_normal_object(_g):
        _oc = nh.objclass(nh.glyph_to_obj(_g))
        GRAY_LOOK[_g] = ord(_oc.oc_class) == nh.GEM_CLASS and nh.OBJ_DESCR(_oc) == "gray"
FLOORISH = np.zeros(G.EFFECT + 1, dtype=bool)        # kinds of a square that is no wall or rock
for _k in (G.FLOOR, G.DOORWAY, G.DOOR_OPEN, G.TRAP, G.UPSTAIR, G.DOWNSTAIR, G.OBJECT, G.GOLD, G.CORPSE):
    FLOORISH[_k] = True


def _template(rows):
    """(floor, wall, rock, char) masks of a map on our grid."""
    char = np.full((ROWS, COLS), " ", dtype="<U1")
    for my, row in enumerate(rows):
        for mx, c in enumerate(row):
            if 0 <= my + OFF_Y < ROWS and 0 <= mx + OFF_X < COLS:
                char[my + OFF_Y, mx + OFF_X] = c
    return char == ".", np.isin(char, ("-", "|")), char == " ", char


TEMPLATES = {"minend-1": _template(MINEND_1), "minend-2": _template(MINEND_2)}


def kick_setups(char, places):
    """Per niche square p (map (x, y)): (p, h, b, o) on our grid -- we stand on h and kick toward p; b, beyond p, is
    floor (the stone flies there); o is the floor square outside when h is a secret door (searched from, the door
    opened from: straight, no diagonal into a doorway). A niche with no such h: (p, None, None, None)."""
    out = []
    for mx, my in places:
        p = (my + OFF_Y, mx + OFF_X)
        got = (p, None, None, None)
        for dy, dx in ORTHO:
            h, b, o = (p[0] - dy, p[1] - dx), (p[0] + dy, p[1] + dx), (p[0] - 2 * dy, p[1] - 2 * dx)
            if char[b] != "." or char[h] not in ".S":
                continue
            if char[h] == "S" and char[o] != ".":
                continue
            got = (p, h, b, o if char[h] == "S" else None)
            break
        out.append(got)
    return tuple(out)


SETUPS_1 = kick_setups(TEMPLATES["minend-1"][3], PLACES_1)


class LuckState:
    """State of the Mines' End luckstone hunt (LuckstoneMixin)."""
    def __init__(self):
        self.variant = {}                # level key -> (seen squares when judged, variant or None)
        self.status = {}                 # (level key, niche p) -> untestable / thump / mimic / passed / taken /
                                         # not_picked / empty / hidden / stuck / unreachable / lost
        self.landed = {}                 # (level key, niche p) -> the square its stone flew to (passed)
        self.searched = Counter()        # (level key, niche p) -> turns searched for its door
        self.kicks = Counter()           # (level key, niche p) -> kicks at its door
        self.found = set()               # (level key, niche p) where we saw a gray stone from the kick square
        self.unclear = Counter()         # (level key, niche p) -> kicks at its stone that showed no outcome
        self.legs_until = 0              # no kick before this turn (wounded legs)
        self.done = set()                # level keys finished (the stone taken, or nothing left to try)
        self.stats = Counter()


class LuckstoneMixin:
    def luckstone_init(self):
        self.luck = LuckState()

    def luckstone_summary(self):
        """Game summary entries."""
        return {"luckstone": dict(self.luck.stats)}

    # ------------------------------------------------------------------ the stone we keep
    def luck_item(self):
        """Our luckstone (named NAME), or None."""
        return next((it for it in self.items() if it.ocls == nh.GEM_CLASS and luck_named(it.text)), None)

    def luck_keeps(self, it):
        """carry.needed: our luckstone, not known cursed."""
        return self.opts.mines_luckstone and it.ocls == nh.GEM_CLASS and luck_named(it.text) and not it.cursed

    # ------------------------------------------------------------------ which Mines' End
    def minend_variant(self, lv):
        """'minend-1' / 'minend-2' when our map of this deep Mines level (Mines levels 8-9: dungeon.def:70 "(8, 2)")
        agrees with that variant's map on VARIANT_MIN_MATCH squares or more and disagrees on at most
        VARIANT_MAX_MISS of them; None otherwise (minend-3: its maze part is random -- not matched). Judged again
        as more of the map is seen, until it is known."""
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
            match = int((floor & t_floor).sum() + (wall & t_wall).sum())
            miss = int((floor & (t_wall | t_rock)).sum() + (wall & t_floor).sum())
            if match >= VARIANT_MIN_MATCH and miss <= VARIANT_MAX_MISS * match:
                found = name
        self.luck.variant[lv.key] = (seen, found)
        if found is not None:
            self.luck.stats[found] += 1
        return found

    # ------------------------------------------------------------------ the step
    def luckstone_step(self, lv, c):
        """mines_luckstone: our luckstone known cursed -- dropped; on minend-1, nothing in view, HP from HP_MIN: the
        niches one by one, the nearest by path first -- its secret door searched for, unlocked / kicked open, the
        gray stone in it kicked from the door square: "Thump!" a loadstone (left), a mimic found (left to the
        fight), else it flew to the closet's far square -- picked up there (only a lone gray stone) and named. A
        niche we can't reach yet waits for explore; given up once the level is explored or mines_return leaves.
        True if it used the turn."""
        if not self.opts.mines_luckstone or c.vis:
            return False
        it = self.luck_item()
        if it is not None:
            if it.cursed:
                self.luck.stats["dropped_cursed"] += 1
                self.drop_units(it.letter)
                return True
            return False
        if lv.key in self.luck.done or c.hp < c.maxhp * HP_MIN or self.minend_variant(lv) != "minend-1":
            return False
        for s in SETUPS_1:
            if s[1] is None and (lv.key, s[0]) not in self.luck.status:
                self.luck_status(lv, s[0], "untestable")
        passed = [s for s in SETUPS_1 if self.luck.status.get((lv.key, s[0])) == "passed"]
        if passed:
            return self.luck_take(lv, passed[0])
        todo = [s for s in SETUPS_1 if (lv.key, s[0]) not in self.luck.status]
        if not todo:
            self.luck.done.add(lv.key)
            return False
        here = self.pos()
        live = self.obs["glyphs"]
        targets = {}
        for s in todo:
            t = self.luck_target(lv, s)
            if t == here:
                return self.luck_kick(lv, s) if t == s[1] else self.luck_door(lv, s)
            if G.KIND[live[t]] != G.MONSTER:                 # someone in the way: the fight steps, or later
                targets.setdefault(t, s)
        if not targets:
            return False
        mask = np.zeros((ROWS, COLS), dtype=bool)
        for t in targets:
            mask[t] = True
        st = self.walk_to(lv, mask, act="luckstone", also=mask & lv.no_entry)[0]  # (a niche door explore was kept
        if st == "moved":                                                           # out of: nav.move)
            return True
        if self.mines.return_on or lv.explored:
            for s in targets.values():
                self.luck_status(lv, s[0], "unreachable")    # explored, or leaving: given up
        return False

    def luck_status(self, lv, p, st):
        self.luck.status[(lv.key, p)] = st
        self.luck.stats[st] += 1
        if st in ("thump", "mimic", "passed"):
            self.luck.stats["tested"] += 1                   # the kick told what it is

    def luck_target(self, lv, s):
        """Where niche s wants us now: its outside square o while its secret door is unfound or shut, else the kick
        square h."""
        p, h, b, o = s
        if o is not None and self.kinds(lv)[h] in (G.WALL, G.UNKNOWN, G.DOOR_CLOSED):
            return o
        return h

    def luck_door(self, lv, s):
        """On o: search for the secret door h (SEARCH_MAX turns at most), then open it -- a step into it (autoopen),
        the lock tool, or kicks (Mines' End has no watch; nav.move never kicks a door in the Mines for Minetown's)."""
        p, h, b, o = s
        self.cur_act = "luckstone"
        if self.kinds(lv)[h] != G.DOOR_CLOSED:                # the secret door not found yet
            if self.luck.searched[(lv.key, p)] >= SEARCH_MAX:
                self.luck_status(lv, p, "hidden")
                return False
            t0 = self.turn()
            self.search_turns(5)
            self.luck.searched[(lv.key, p)] += max(1, self.turn() - t0)
            return True
        if h not in lv.locked:
            self.move(h)                                     # opens it, or "This door is locked." (mapmem)
            return True
        if self.lock_door_step(lv, h):                       # unlocked with the tool (nhbot.locktools)
            return True
        if self.luck.kicks[(lv.key, p)] >= DOOR_KICKS:
            self.luck_status(lv, p, "stuck")
            return False
        if self.luck_legs_wait():
            return True
        self.luck.kicks[(lv.key, p)] += 1
        self.luck.stats["door_kicks"] += 1
        self.luck_kick_toward(h)
        if self.kinds(lv)[h] != G.DOOR_CLOSED:
            lv.locked.discard(h)                             # it crashed open / shattered (dokick.c:1286-1290)
        return True

    def luck_kick_toward(self, sq):
        """Kick toward the adjacent square sq; the messages it brought. Not a step (nav.not_stepping): no failure is
        put on sq (mapmem blocks a door the legs refused to kick -- here a wait instead, luck_legs_wait)."""
        self.not_stepping()
        y, x = self.pos()
        seq0 = self.msg_seq
        self.kick(DELTA2KEY[(sq[0] - y, sq[1] - x)])
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

    def luck_kick(self, lv, s):
        """On h: a gray stone in view on p -- kicked toward b. What came of it: "Thump!" (a loadstone: never taken),
        a mimic found, or the stone gone from p (flown to b: passed)."""
        p, h, b, _ = s
        live = self.obs["glyphs"]
        g = int(live[p])
        if G.KIND[g] == G.MONSTER:
            return False                                     # a mimic shown, a gnome stepped in: the fight steps
        if not GRAY_LOOK[g]:
            self.luck_status(lv, p, "empty")                 # no gray stone here (and kicking empty space can
            return False                                     # strain a muscle: dokick.c:1254-1262)
        self.cur_act = "luckstone"
        if (lv.key, p) not in self.luck.found:
            self.luck.found.add((lv.key, p))
            self.luck.stats["found"] += 1                    # a gray stone (or a mimic looking like one) in a niche
        if self.luck_legs_wait():
            return True
        said = self.luck_kick_toward(p)
        if "no shape for kicking" in said:
            return True
        self.luck.stats["kicks"] += 1
        g2 = int(self.obs["glyphs"][p])
        if "Thump!" in said:
            self.luck_status(lv, p, "thump")                 # too heavy to move (dokick.c:647-651): a loadstone
        elif "Wait!" in said or "mimic" in said or G.KIND[g2] == G.MONSTER:
            self.luck_status(lv, p, "mimic")
        elif not GRAY_LOOK[g2]:
            self.luck_status(lv, p, "passed")
            self.luck.landed[(lv.key, p)] = b
        else:
            self.luck.stats["kick_unclear"] += 1             # still a gray stone there: tried again (a clumsy
            self.luck.unclear[(lv.key, p)] += 1              # kick, dokick.c:512) -- not for ever
            if self.luck.unclear[(lv.key, p)] >= 5:
                self.luck_status(lv, p, "lost")
        return True

    def luck_take(self, lv, s):
        """The stone that passed lies on b: there, if it is the only gray stone, pick it up and name it."""
        p = s[0]
        b = self.luck.landed[(lv.key, p)]
        if self.pos() != b:
            mask = np.zeros((ROWS, COLS), dtype=bool)
            mask[b] = True
            st = self.walk_to(lv, mask, act="luckstone", also=mask)[0]    # b may be unseen yet (a dark closet)
            if st == "moved":
                return True
            self.luck_status(lv, p, "lost")
            return False
        grays = [n for n in self.look_here() if "gray stone" in n]
        if len(grays) != 1:
            self.luck_status(lv, p, "lost")                  # none, or another gray stone came along: not this
            return False
        self.cur_act = "luckstone"
        before = {it.letter for it in self.items()}
        self.pickup(lambda t: "gray stone" in t, "luckstone")
        new = [it for it in self.items() if it.letter not in before and "gray stone" in it.text]
        self.luck.done.add(lv.key)
        if not new:
            self.luck_status(lv, p, "not_picked")
            return True
        self.luck_status(lv, p, "taken")
        if self.name_item(new[0].letter, NAME):
            self.luck.stats["named"] += 1
        return True

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


def luck_named(text):
    """The text of our luckstone: a gray stone (or, identified, a luckstone) named NAME."""
    return f" named {NAME}" in text and ("gray stone" in text or "luckstone" in text)
