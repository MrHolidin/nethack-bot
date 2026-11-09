"""rock_dig (A/B, off by default): gold and gems lying inside solid rock. mklev.c:898-985 mineralize puts them in
STONE squares whose eight neighbours are stone too (gems three times as often in the Mines, mklev.c:937-939), 2 in 3
on the square, 1 in 3 buried. We see one only once a passage runs beside it (a dwarf's tunnel, our own: display.c
_map_location shows a seen square's top object, even on rock) -- standing next to it, as the games show (scratchpad
zi/rockobj.py). The bot took the glyph for floor: the step into it is "It's solid stone." (hack.c:768-772, no game
time), and after a few of those (nav.move: blocked at 6 failures, forgotten by step_progress) it came back for more.
Here: that answer on a square showing something makes it a dig job -- the square dug open with the pick-axe /
mattock from where we stood (dig.c dig: rock becomes a passage), what lies on it then taken as anything is
(step_gold_here, the pile pickup); without a digger, or where we may not dig, the square kept out of for good
(no_entry_mark). Not in Sokoban, not on a Minetown level (dig.c watch_dig) but Orcish Town, not by a shop
(shopdig: digthrough.dig_ok)."""
from nhbot import glyphs as G

ROCK_DIG_TRIES = 4             # applies at one square (an apply digs on by itself till the rock gives way: dig.c dig)
LOOKS_LIKE_THINGS = (G.OBJECT, G.GOLD, G.CORPSE)     # glyph kinds of a square holding something
# the rock gave way (dig.c:404 "You succeed in cutting away some rock."), or it was open already (a dwarf dug it:
# apply.c use_pick_axe2 "You swing your pick-axe through thin air.")
OPENED = ("cutting away some rock", "through thin air")


class RockDigState:
    """State of digging out things seen in rock (RockDigMixin)."""
    def __init__(self):
        self.job = None                # (level key, stand square, rock square, applies so far)
        self.wielded = False           # the digger came into our hands for a job (dig_unwield once none is left)
        self.stats = {}


class RockDigMixin:
    def rock_dig_init(self):
        self.rock_dig = RockDigState()

    def rock_dig_summary(self):
        """Game summary entries."""
        return {"rock_dig": dict(self.rock_dig.stats)}

    def rock_stat(self, k):
        self.rock_dig.stats[k] = self.rock_dig.stats.get(k, 0) + 1

    def rock_note(self, lv, here, target):
        """mapmem.msg_map: "It's solid stone." for our step from here to target -- if target shows something lying
        there (mineralize's gold / gems), a dig job; we can't or may not dig: kept out of for good. True if it was
        such a square."""
        if not self.opts.rock_dig or lv is None:
            return False
        if G.KIND[int(self.obs["glyphs"][target])] not in LOOKS_LIKE_THINGS \
                and G.KIND[int(lv.under[target])] not in LOOKS_LIKE_THINGS:
            return False
        self.rock_stat("seen")
        orcs = self.is_orctown(lv)
        if self.dig_hand_means() is None or self.in_sokoban(lv) or lv.key in self.digging.refused \
                or (not orcs and (self.is_minetown(lv) or self.minetown_rooms(lv))) \
                or not (orcs or self.dig_ok(lv, target)):
            self.no_entry_mark(lv, target)
            self.rock_stat("kept_out")
            return True
        if self.rock_dig.job is None or self.rock_dig.job[:3] != (lv.key, here, target):
            self.rock_dig.job = (lv.key, here, target, 0)
            self.rock_stat("planned")
        return True

    def rock_dig_step(self, lv, hostiles):
        """The job's rock square dug from where we stood (an apply digs on by itself till the rock gives way); once
        it is open, what lies there is taken by the usual steps, and with no job left the weapon goes back into our
        hands (dig_unwield). True if it used the turn."""
        job = self.rock_dig.job
        if job is None:
            if self.rock_dig.wielded and not hostiles and self.dig_through.job is None and not self.digger_held(lv):
                self.rock_dig.wielded = False
                return self.dig_unwield()
            return False
        key, here, sq, tries = job
        if key != lv.key or self.pos() != here or hostiles:
            self.rock_dig.job = None               # moved off, or a fight: the next step into it plans it again
            return False
        means = self.dig_hand_means()
        if means is None or tries >= ROCK_DIG_TRIES:
            self.rock_dig.job = None
            self.no_entry_mark(lv, sq)
            self.rock_stat("gave_up")
            return False
        self.cur_act = "rock_dig"
        self.rock_dig.job = (key, here, sq, tries + 1)
        self.rock_dig.wielded = True
        msgs = self.dig_at(lv, sq, means)
        if msgs is None:
            return True                            # the digger wielded this turn
        self.rock_stat("apply")
        if any(t in msgs for t in OPENED):
            lv.blocked[sq] = False                 # a passage now: the usual steps walk in and take what lies there
            lv.fail[sq] = 0
            self.rock_dig.job = None
            self.rock_stat("opened")
        elif "too hard to" in msgs:
            self.rock_dig.job = (key, here, sq, ROCK_DIG_TRIES)    # it won't give way: given up next tick
        return True
