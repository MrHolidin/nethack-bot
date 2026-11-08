"""dig_through: what the Mines' caves shut with -- a diagonal squeeze refused for our weight (hack.c test_move: more
than 600 carried), a boulder that won't move (a monster or another boulder behind it) -- opened with a digger
instead of shedding our things or giving the way up: one of the squeeze's two corners dug (dig.c: a wall or rock
square becomes a passage; a wand of digging zapped that way), a boulder broken by the pick-axe / mattock applied
at it (dig.c dig: "you hit the boulder with all your might" -- fracture_rock). Not in Sokoban (boulders are the
puzzle), not on a Minetown level (the watch minds dug walls: dig.c watch_dig) but Orcish Town (all of them dead),
not next to a shop (shopdig)."""
from nhbot import glyphs as G
from nhbot.nav import DELTA2KEY

DIG_THROUGH_TRIES = 3          # applies / zaps at one square before it is given up


class DigThroughMixin:
    def dig_through_init(self):
        self.dig_job = None            # (level key, stand square, square to dig, kind "squeeze" / "boulder", tries)
        self.dig_given_up = set()      # (level key, square to dig) that would not give way
        self.dig_stats = {}

    def dig_note_stat(self, k):
        self.dig_stats[k] = self.dig_stats.get(k, 0) + 1

    def dig_through_note(self, lv, here, target, kind):
        """A squeeze from here to target refused for our weight, or the boulder on target that won't move:
        a dig job if we can dig it open. True if one was set (the caller then neither sheds nor blocks)."""
        if not self.opts.dig_through or lv is None or self.in_sokoban(lv):
            return False
        orcs = self.is_orctown(lv)                     # Orcish Town: its watch is dead -- dug there too
        if not orcs and (self.is_minetown(lv) or self.minetown_rooms(lv)):
            return False
        means = self.dig_means()
        if means is None or (kind == "boulder" and means[0] == "wand"):
            return False                               # a wand of digging digs no boulder
        if kind == "boulder":
            sq = target
        else:
            corners = [(here[0], target[1]), (target[0], here[1])]
            k = self.kinds(lv)
            corners = [c for c in corners if k[c] in (G.WALL, G.UNKNOWN) and (orcs or self.dig_ok(lv, c))]
            if not corners:
                return False
            sq = corners[0]
        if (lv.key, sq) in self.dig_given_up or not (orcs or self.dig_ok(lv, sq)):
            return False
        self.dig_job = (lv.key, here, sq, kind, 0)
        self.dig_note_stat("planned_" + kind)
        return True

    def dig_ok(self, lv, sq):
        """Not a shop's square nor next to one (shopdig: the shopkeeper minds a dug wall)."""
        y, x = sq
        return not lv.shop[max(0, y - 1):y + 2, max(0, x - 1):x + 2].any()

    def dig_through_step(self, lv, hostiles):
        """dig_through: the job's square dug from where we stood when refused; once it gives way the way on is
        walked by explore as ever. True if it used the turn."""
        job = self.dig_job
        if job is None:
            return False
        key, here, sq, kind, tries = job
        if key != lv.key or self.pos() != here or hostiles:
            self.dig_job = None                        # moved off (or a fight): explore meets it again if need be
            return False
        if self.is_minetown(lv) and not self.is_orctown(lv):
            self.dig_job = None                        # known as Minetown only now (a watch warning): stop
            self.dig_note_stat("town_stop")
            return False
        k = self.kinds(lv)
        open_now = (not (self.grids(lv)[1][sq] == G.BOULDER or k[sq] == G.BOULDER)) if kind == "boulder" \
            else G.PASSABLE[k[sq]]
        if open_now:
            lv.blocked[sq] = False
            lv.fail[sq] = 0
            lv.no_entry[sq] = False
            self.dig_job = None
            self.dig_note_stat("opened_" + kind)
            return False
        means = self.dig_means()
        if means is None or tries >= DIG_THROUGH_TRIES:
            self.dig_given_up.add((key, sq))
            self.dig_job = None
            self.dig_note_stat("gave_up")
            if kind == "boulder":
                self.no_entry_mark(lv, sq)
            return False
        d = DELTA2KEY[(sq[0] - here[0], sq[1] - here[1])]
        self.cur_act = "dig_through"
        kind_m, it = means
        self.dig_job = (key, here, sq, kind, tries + 1)
        if kind_m == "wand":
            self.dig_note_stat("zap")
            self.zap(it.letter, d)
            return True
        if self.dig_wield(lv, means):
            return True
        self.dig_note_stat("apply")
        msgs = self.apply_digger(it, d) or ""
        if "too hard to" in msgs:
            self.dig_job = (key, here, sq, kind, DIG_THROUGH_TRIES)   # it won't give way: given up next tick
        return True
