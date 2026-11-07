"""Excalibur (wiki "Excalibur"): lawful, XL >= 5, dip an unnamed long sword into a fountain;
1/6 per dip, the fountain disappears on success."""
import re
from collections import Counter

import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import DELTA2KEY, FLOOR_GLYPH, FOUNTAIN_GLYPH, NO_ENGRAVE_CMAP
from nhbot.equipment import CLOAK, GLOVES, SHIRT, SUIT
from nhbot.materials import rusts

JUNK_CLASSES = (nh.GEM_CLASS, nh.ROCK_CLASS, nh.WEAPON_CLASS, nh.TOOL_CLASS, nh.ARMOR_CLASS)   # water spoils little
CONTAINERS = ("bag", "sack", "box", "chest", "lamp", "candle")
FOUNTAIN_DIP_DEPTH = 20     # dips for a wish on dungeon levels above this only
DEMON_WIN = 0.7      # dip for a wish only while P(we beat a water demon) is above this
FOUNTAIN_PWIN = 0.75  # fountain_elb: what a dip brought out we fight below this P(win) only from our Elbereth
FOUNTAIN_CALM = 3     # fountain_elb: turns with nothing within 2 squares before we leave the Elbereth
FOUNTAIN_HIDE_MAX = 300   # fountain_elb: turns at most on it
FOUNTAIN_REHIDE_MAX = 20  # fountain_rehide: hides at most on one level while we leave it


class ExcaliburMixin:
    def excal_init(self):
        self.excalibur = False
        self.excal_turn = None
        self.dips = 0
        self.dip_events = []
        self.fountain_levels = set()
        self.excal_trips = 0
        self.excal_skip = set()
        self.demon_win = (None, 0.0)     # (state key, P(we beat a water demon))
        self.fountain_shut = set()       # fountain_elb: (level key, square) of fountains left after a hide
        self.fhide = None                # fountain_elb: {key, fountain, sq, phase, hiding, calm, since, dip_turn}
        self.fhide_stats = Counter()
        self.fountain_leave = None       # fountain_elb: level key to leave by the stairs down after a hide
        self.fountain_rehides = Counter()  # fountain_rehide: level key -> hides on the way off it

    def long_sword(self):
        for it in self.items():
            if it.ocls == nh.WEAPON_CLASS and re.search(r"\blong sword\b", it.text) and "named" not in it.text \
                    and "Excalibur" not in it.text and not it.cursed:
                return it.letter, it.text
        return None

    def excal_eligible(self):
        if self.excalibur:
            return False
        if int(self.last_bl[nh.NLE_BL_ALIGN]) != 1:
            return False
        if self.bl(nh.NLE_BL_XP) < self.opts.excal_xl:
            return False
        hp, maxhp = self.bl(nh.NLE_BL_HP), self.bl(nh.NLE_BL_HPMAX)
        if hp < maxhp * self.opts.excal_hp:
            return False
        return self.long_sword() is not None

    def excal_step(self, lv):
        fmask = self.terrain_glyphs(lv) == FOUNTAIN_GLYPH
        if fmask.any():
            self.fountain_levels.add(lv.key)
        if not self.excal_eligible():
            return False
        if not fmask.any():
            return self.excal_go_up(lv)
        if lv.shop.any() and fmask[lv.shop].any():
            fmask &= ~lv.shop
        if lv.key[0] == 2:
            fmask[:] = False          # Minetown: a fountain drying up angers the watch
        for k, p in self.fountain_shut:
            if k == lv.key:
                fmask[p] = False
        if not fmask.any():
            return self.excal_go_up(lv)
        y, x = self.pos()
        if fmask[y, x]:
            if self.fountain_elb_prepare(lv):
                return True
            return self.dip(lv)
        if self.walk_to(lv, fmask, max_cost=self.opts.excal_cost, act="excal", also=fmask)[0] == "moved":
            return True
        self.excal_skip.add(lv.key)                # can't reach it: don't keep coming back
        return False

    def excal_fountain_level(self):
        """The main-dungeon level, nearest in depth, with a fountain we could make Excalibur at (not a
        shop's, not on a level we gave up reaching it on), while Excalibur can be made at all (lawful, XL
        excal_xl, an unnamed long sword; not the HP: we rest for that). None: no such level."""
        if self.excalibur or int(self.last_bl[nh.NLE_BL_ALIGN]) != 1 or self.bl(nh.NLE_BL_XP) < self.opts.excal_xl \
                or self.long_sword() is None:
            return None
        dl = self.bl(nh.NLE_BL_DEPTH)
        keys = [k for k, l in self.levels.items() if k[0] == 0 and self.fountains(l).any()]
        return min(keys, key=lambda k: abs(k[1] - dl)) if keys else None

    def excal_go_up(self, lv):
        """No fountain here, but one is remembered a few levels up: walk back up to it."""
        if lv.key[0] != 0 or self.excal_trips >= self.opts.excal_trips:
            return False
        dl = lv.key[1]
        targets = [k for k, l in self.levels.items()
                   if k[0] == 0 and dl - self.opts.excal_up <= k[1] < dl and k not in self.excal_skip
                   and (self.terrain_glyphs(l) == FOUNTAIN_GLYPH).any()
                   and not (l.shop.any() and (self.terrain_glyphs(l) == FOUNTAIN_GLYPH)[l.shop].all())]
        if not targets:
            return False
        k_mem = self.grids(lv)[0]
        up = k_mem == G.UPSTAIR
        if not up.any():
            return False
        y, x = self.pos()
        if up[y, x]:
            self.cur_act = "excal"
            self.excal_trips += 1
            self.press("<")
            return True
        return self.walk_to(lv, up, max_cost=self.opts.excal_cost_up, act="excal")[0] == "moved"

    def dip(self, lv):
        it = self.long_sword()
        if not it:
            return False
        self.cur_act = "excal"
        recent = self.dip_into_fountain(lv, it[0])
        if recent is None:
            return False
        y, x = self.pos()
        if "Excalibur" in recent or "hand reaches up" in recent or \
                any("Excalibur" in s for _, _, s in self.inventory()):
            self.excalibur = True
            self.excal_turn = self.turn()
            lv.set_terrain((y, x), FLOOR_GLYPH)
            self.dip_events.append((self.turn(), "excalibur"))
        elif self.fountain_gone(recent):
            lv.set_terrain((y, x), FLOOR_GLYPH)
            self.dip_events.append((self.turn(), "dried"))
        return True

    @staticmethod
    def fountain_gone(recent):
        return "dries up" in recent or "fountain disappears" in recent or "anything to dip" in recent

    def dip_into_fountain(self, lv, letter):
        """#dip an inventory item into the fountain we stand on. The messages since, or None if no dip
        happened (no fountain here any more: forgotten)."""
        seq0 = self.msg_seq
        if self.fhide is not None:
            self.fhide["dip_turn"] = self.turn()
        self.raw_step(228)                       # M-d: #dip
        if "dip" not in self.message().lower():
            self.settle(); return None
        self.raw_step(ord(letter))
        m = self.message().lower()
        if "fountain" in m and self.obs["misc"][0]:
            self.press("y")
        else:
            self.settle()
            if "nothing to dip" in m or "anything to dip" in m or "into" in m:
                lv.set_terrain(self.pos(), FLOOR_GLYPH)       # no fountain here any more
            return None
        self.dips += 1
        recent = self.text_since(seq0)
        if "water demon" in recent:              # fountain.c dipfountain case 21, either reason to dip
            self.dip_events.append((self.turn(), "wish" if "grants you a wish" in recent else "demon"))
        if "glows for a moment" in recent:       # cases 17..20: the dipped item was cursed and is not now
            self.dip_events.append((self.turn(), "uncursed"))
        return recent

    def demon_win_prob(self):
        """P(we win a fight with a water demon next to us, from full HP) -- danger.win_prob, cached while what it
        depends on stays the same (level, XL, max HP, AC, the weapon in hand)."""
        weapon = next((it.text for it in self.items() if it.wielded), None)
        key = (self.bl(nh.NLE_BL_DEPTH), self.bl(nh.NLE_BL_XP), self.bl(nh.NLE_BL_HPMAX), self.bl(nh.NLE_BL_AC),
               weapon)
        if self.demon_win[0] != key:
            self.demon_win = (key, self.win_prob([(None, "water demon")]))
        return self.demon_win[1]

    def fountains(self, lv):
        """Fountains of this level we may use: not a shop's, not in the Mines (Minetown's watch), not on a
        level we gave up reaching them on."""
        fmask = self.terrain_glyphs(lv) == FOUNTAIN_GLYPH
        if lv.key[0] == 2 or lv.key in self.excal_skip:
            return fmask & False
        for k, p in self.fountain_shut:
            if k == lv.key:
                fmask[p] = False
        return fmask & ~lv.shop if lv.shop.any() else fmask

    def dip_at_fountain(self, lv, fmask, letter, act):
        """On a fountain of fmask: dip `letter`; else walk toward the nearest. True if it used the turn."""
        self.cur_act = act
        y, x = self.pos()
        if fmask[y, x]:
            if self.fountain_elb_prepare(lv):
                return True
            recent = self.dip_into_fountain(lv, letter)
            if recent is None:
                return False
            if self.fountain_gone(recent):
                lv.set_terrain((y, x), FLOOR_GLYPH)
                self.dip_events.append((self.turn(), "dried"))
            return True
        if self.walk_to(lv, fmask, max_cost=self.opts.excal_cost, act=act, also=fmask)[0] == "moved":
            return True
        self.excal_skip.add(lv.key)
        return False

    # ------------------------------------------------------------------ why we dip
    def fountain_plan_step(self, lv):
        """Every reason to dip, first that applies (no threat in view -- the caller checks):
          1. Excalibur can be made now (excal_step: lawful, XL, HP, an unnamed long sword);
          2. a known-cursed thing we wear, or would wear were it not cursed (uncurse_target): 4/30 uncursed;
          3. a wish: dungeon level below FOUNTAIN_DIP_DEPTH, full HP, P(we beat a water demon) > DEMON_WIN --
             the lawful dip Excalibur, the others a thing we don't need (junk_to_dip).
        A lawful hero without Excalibur yet keeps the fountains for it: no 2 or 3. True if it used the turn.
        (A/B fountain_plan: +290 [-61, +650], the non-lawful +593 [+195, +994]; dipping junk instead of
        Excalibur for the lawful too, wish_junk: -573 [-1385, +262].)"""
        if self.excal_step(lv):
            return True
        lawful = int(self.last_bl[nh.NLE_BL_ALIGN]) == 1
        if lawful and not self.excalibur:
            return False
        fmask = self.fountains(lv)
        if not fmask.any():
            return False
        hp, maxhp = self.bl(nh.NLE_BL_HP), self.bl(nh.NLE_BL_HPMAX)
        if hp < maxhp * self.opts.excal_hp:
            return False
        it = self.uncurse_target(lawful)
        if it is not None:
            return self.dip_at_fountain(lv, fmask, it.letter, "fountain_uncurse")
        if self.bl(nh.NLE_BL_DEPTH) >= FOUNTAIN_DIP_DEPTH or hp < maxhp:
            return False
        if lawful:
            it = next((i for i in self.items() if "Excalibur" in i.text and i.wielded), None)
        else:
            it = self.junk_to_dip()
        if it is None or self.demon_win_prob() <= DEMON_WIN:
            return False                          # the demon a dip may bring could kill us (danger.win_prob)
        return self.dip_at_fountain(lv, fmask, it.letter, "fountain_wish")

    def uncurse_target(self, lawful):
        """A known-cursed thing to dip: worn or wielded and within the water's reach (do_wear.c
        inaccessible_equipment: no suit under a cloak, no shirt under a suit or cloak, no ring under gloves; the
        wielded weapon only when we have a better one to wield -- a dip for a wish may curse Excalibur), or
        armor / a weapon we would put on or wield were it not cursed (equipment.improves, weapon_rank). Not a
        long sword unless lawful (a dip at XL 5+ curses it, may take a point off it and dries the fountain); nothing
        water would rust (materials.rusts: each dip rusts it more, and a rusted piece makes half the dips do
        nothing else -- fountain.c dipfountain).
        We know of a curse on what we wear mostly from taking it off for a better piece: just when lifting it
        pays."""
        worn = self.worn_by_slot()
        covered = set()
        if CLOAK in worn:
            covered |= {SUIT, SHIRT}
        if SUIT in worn:
            covered.add(SHIRT)
        covered = {worn[s]["letter"] for s in covered if s in worn}
        wanted = {a["letter"] for a in self.armor_inventory() if a["cursed"] and not a["worn"]
                  and self.improves(a, worn)}
        cur = next((it for it in self.items() if it.wielded), None)
        cur_rank = self.weapon_rank(cur.text) if cur is not None else (-1, 0)
        better_weapon = any(it.ocls == nh.WEAPON_CLASS and not it.cursed and self.weapon_rank(it.text) > cur_rank
                            for it in self.items())
        for it in self.items():
            if not it.cursed or rusts(it.text) or (not lawful and re.search(r"\blong sword\b", it.text)):
                continue
            if it.wielded and not better_weapon:
                continue                          # welded, but nothing better to wield (Excalibur): no matter
            if it.on_body:
                if it.letter in covered or (it.ring_on and GLOVES in worn):
                    continue
                return it
            if it.letter in wanted or (it.ocls == nh.WEAPON_CLASS and self.weapon_rank(it.text) > cur_rank):
                return it
        return None

    def junk_to_dip(self):
        """Something we don't need that water spoils little: not on us, not kept (carry.needed), no food,
        container or light, no long sword; what water won't rust first (a rusting one makes half the dips do
        nothing else), then gems and stones."""
        cands = [it for it in self.items() if it.ocls in JUNK_CLASSES and not it.on_body and not it.alternate
                 and not it.quivered and "unpaid" not in it.text and not self.needed(it)
                 and not any(w in it.text for w in CONTAINERS) and not re.search(r"\blong sword\b", it.text)]
        return min(cands, key=lambda it: (rusts(it.text), JUNK_CLASSES.index(it.ocls)), default=None)

    # ------------------------------------------------------------------ fountain_elb
    def fountain_elb_prepare(self, lv):
        """fountain_elb, on the fountain about to dip: Elbereth first on a floor square next to it (written and
        read back), then back onto the fountain. True if it used the turn; False: dip now."""
        if not self.opts.fountain_elb:
            return False
        here = self.pos()
        st = self.fhide
        if st is None or st["key"] != lv.key or st["fountain"] != here:
            sq = self.fountain_elb_square(lv, here)
            st = self.fhide = {"key": lv.key, "fountain": here, "sq": sq, "phase": "go" if sq else "none",
                               "hiding": False, "calm": 0, "since": 0, "dip_turn": -99}
            self.fhide_stats["planned" if sq else "no_square"] += 1
        if st["phase"] in ("ready", "none"):
            return False
        sq = st["sq"]
        if st["phase"] == "go":                          # standing on the fountain: a step onto the square
            if self.square_taken(sq):                    # someone on it (the Oracle's centaurs: "Really attack?")
                st["sq"] = sq = self.fountain_elb_square(lv, here)
                if sq is None:
                    st["phase"] = "none"
                    self.fhide_stats["no_square"] += 1
                    return False
            st["phase"] = "write"
            self.cur_act = "fountain_elb"
            self.press(DELTA2KEY[(sq[0] - here[0], sq[1] - here[1])])
            return True
        return False

    def square_taken(self, q):
        return G.KIND[self.obs["glyphs"][q]] in (G.MONSTER, G.PET, G.INVIS)

    def fountain_elb_square(self, lv, fountain):
        """A square next to the fountain to write Elbereth on: floor (no doorway: diagonal steps; no trap, stairs,
        altar, another fountain), one we stand on as written already first."""
        k = self.kinds(lv)
        ter = self.terrain_glyphs(lv)
        best = None
        for dy, dx in DELTA2KEY:
            q = (fountain[0] + dy, fountain[1] + dx)
            if not (0 <= q[0] < k.shape[0] and 0 <= q[1] < k.shape[1]) or k[q] != G.FLOOR \
                    or int(ter[q]) == FOUNTAIN_GLYPH or (nh.glyph_is_cmap(int(ter[q]))
                                                         and nh.glyph_to_cmap(int(ter[q])) in NO_ENGRAVE_CMAP):
                continue
            if self.square_taken(q):
                continue                                 # a monster on it: never a step into it
            if q in lv.elbereth:
                return q
            best = best or q
        return best

    def fountain_hide_step(self, lv, hostiles):
        """fountain_elb, every tick: writing the Elbereth by the fountain and stepping back; after a dip, what came
        out beats us with P(win) below FOUNTAIN_PWIN -- onto the Elbereth, waiting there until nothing is within 2
        squares for FOUNTAIN_CALM turns, then this fountain is left (another one, or on and down). True if it used
        the turn."""
        st = self.fhide
        if self.opts.fountain_elb and self.fountain_leave is not None and st is None:
            return self.fountain_leave_step(lv, hostiles)
        if not self.opts.fountain_elb or st is None or st["key"] != lv.key or not st["sq"]:
            return False
        here, sq, ftn = self.pos(), st["sq"], st["fountain"]
        dist = lambda p, q: max(abs(p[0] - q[0]), abs(p[1] - q[1]))
        if st["phase"] == "write":
            if here != sq:
                st["phase"] = "go"
                return False
            if hostiles:
                return False                             # a fight came first: the step comes back to it
            self.cur_act = "fountain_elb"
            if sq in lv.elbereth and self.elb_confirm(lv):
                st["phase"] = "back"
            elif not self.elb_can_write(lv) or not self.engrave_elbereth():
                st["phase"], st["sq"] = "none", None     # it can't be written here: dip without
                self.fhide_stats["write_failed"] += 1
                return True
            elif self.elb_confirm(lv):
                st["phase"] = "back"
                self.fhide_stats["written"] += 1
            return True
        if st["phase"] == "back":
            if here == ftn:
                st["phase"] = "ready"
                return False
            if dist(here, ftn) == 1 and self.square_taken(ftn):
                return False                             # someone on the fountain: as ever until it moves
            if dist(here, ftn) == 1:
                self.cur_act = "fountain_elb"
                self.press(DELTA2KEY[(ftn[0] - here[0], ftn[1] - here[1])])
                return True
            st["phase"] = "go"
            return False
        if st["phase"] != "ready":
            return False
        y, x = here
        vis = [(p, n) for p, n in self.visible_hostiles(lv) if dist(p, here) <= 6]
        if not st["hiding"]:
            if not vis or here not in (ftn, sq) or self.turn() - st["dip_turn"] > 3:
                return False
            if any(not self.respects(p, n) for p, n in vis):
                return False
            approach = {p: max(0, dist(p, here) - 1) for p, _ in vis}
            if self.win_prob(vis, approach=approach) >= FOUNTAIN_PWIN:
                return False
            st["hiding"], st["since"], st["calm"] = True, self.turn(), 0
            self.fhide_stats["hid"] += 1
        taken = self.square_taken
        if here != sq:
            if dist(here, sq) == 1 and taken(sq):        # something came out onto it (makemon: next to us)
                k = self.kinds(lv)
                ter = self.terrain_glyphs(lv)
                free = [(here[0] + dy, here[1] + dx) for dy, dx in DELTA2KEY]
                free = [q for q in free if 0 <= q[0] < k.shape[0] and 0 <= q[1] < k.shape[1] and k[q] == G.FLOOR
                        and not taken(q) and int(ter[q]) != FOUNTAIN_GLYPH]
                if not free:
                    self.fhide = None                    # boxed in: fight as ever
                    return False
                sq = st["sq"] = min(free, key=lambda q: sum(1 for p, _ in vis if dist(p, q) <= 1))
                st["fresh"] = True                       # a new one: written once we stand there
                self.fhide_stats["moved_square"] += 1
            if dist(here, sq) == 1:
                self.cur_act = "fountain_hide"
                self.press(DELTA2KEY[(sq[0] - here[0], sq[1] - here[1])])
                return True
            self.fhide = None                            # pushed away from it: fight / flee as ever
            return False
        if any(not self.respects(p, n) for p, n in vis):
            self.fhide_stats["hide_broken"] += 1
            self.fhide = None                            # it won't hold them: the Elbereth step / fight
            return False
        if (st.get("fresh") or hostiles) and not self.elb_confirm(lv):
            st["fresh"] = False
            st["rewrites"] = st.get("rewrites", 0) + 1
            if st["rewrites"] > 3 or not self.elb_can_write(lv):
                self.fhide_stats["hide_broken"] += 1
                self.fhide = None
                return False
            self.fhide_stats["rewritten"] += 1
            self.cur_act = "fountain_hide"
            self.engrave_elbereth()                      # written (again) under us -- smudged by what stood on it
            return True
        st["fresh"] = False
        st["calm"] = 0 if any(dist(p, here) <= 2 for p, _ in vis) else st["calm"] + 1
        if st["calm"] < FOUNTAIN_CALM and self.turn() - st["since"] < FOUNTAIN_HIDE_MAX:
            self.cur_act = "fountain_hide"
            self.press("s")
            return True
        if ftn is not None:
            self.fountain_shut.add((lv.key, ftn))        # this fountain is left
        self.fhide_stats["left"] += 1
        self.fhide = None
        self.excal_skip.add(lv.key)                      # what came out still roams here: no more dips on this
        self.fountain_leave = lv.key                     # level, and off it by the stairs down
        return False

    def fountain_rehide_step(self, lv, hostiles):
        """fountain_rehide, on the way off the level after a hide: caught (something next to us) by what beats us
        with P(win) below FOUNTAIN_PWIN -- Elbereth written where we stand and a hide there as by the fountain
        (fountain_hide_step: until nothing is within 2 squares for FOUNTAIN_CALM turns), then on our way again.
        Not where it can't be written (stairs, ...), not against what ignores it. True if it used the turn."""
        if not self.opts.fountain_rehide or self.fountain_rehides[lv.key] >= FOUNTAIN_REHIDE_MAX \
                or not self.elb_can_write(lv):
            return False
        here = self.pos()
        dist = lambda p: max(abs(p[0] - here[0]), abs(p[1] - here[1]))
        vis = [(p, n) for p, n in self.visible_hostiles(lv) if dist(p) <= 6]
        if not vis or any(not self.respects(p, n) for p, n in vis):
            return False
        if self.win_prob(vis, approach={p: max(0, dist(p) - 1) for p, _ in vis}) >= FOUNTAIN_PWIN:
            return False
        self.fountain_rehides[lv.key] += 1
        self.fhide_stats["rehid"] += 1
        self.fhide = {"key": lv.key, "fountain": None, "sq": here, "phase": "ready", "hiding": True, "calm": 0,
                      "since": self.turn(), "dip_turn": -99, "fresh": True}
        return self.fountain_hide_step(lv, hostiles)

    def fountain_leave_step(self, lv, hostiles):
        """fountain_elb, after a hide (what came out still roams this level): off it where we were headed anyway --
        up to a fountain remembered above while we still dip for Excalibur (excal_go_up), else down the stairs
        we know; neither: as ever. Nothing next to us (a fight comes first). True if it used the turn."""
        if self.fountain_leave != lv.key:
            self.fountain_leave = None
            return False
        if hostiles and self.fountain_rehide_step(lv, hostiles):
            return True
        if hostiles:
            return False
        if self.excal_eligible() and self.excal_go_up(lv):
            self.fhide_stats["leave_up"] += 1
            return True
        down = self.kinds(lv) == G.DOWNSTAIR
        if down.any() and self.go_down(lv, self.grids(lv), down):
            self.fhide_stats["leave_down"] += 1
            return True
        return False
