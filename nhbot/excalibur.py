"""Excalibur (wiki "Excalibur"): lawful, XL >= 5, dip an unnamed long sword into a fountain;
1/6 per dip, the fountain disappears on success."""
import re

import nle.nethack as nh

from nhbot.consts import FLOOR_GLYPH, FOUNTAIN_GLYPH
from nhbot.equipment import CLOAK, GLOVES, SHIRT, SUIT
from nhbot.items import base_name
from nhbot.materials import rusts

JUNK_CLASSES = (nh.GEM_CLASS, nh.ROCK_CLASS, nh.WEAPON_CLASS, nh.TOOL_CLASS, nh.ARMOR_CLASS)   # water spoils little
CONTAINERS = ("bag", "sack", "box", "chest", "lamp", "candle")
FOUNTAIN_DIP_DEPTH = 20     # dips for a wish on dungeon levels above this only
# artilist.h: the long-sword artifacts besides Excalibur (a long sword named so is one: oname makes it the artifact)
LONG_SWORD_ARTIFACT_RE = re.compile(r"\bnamed (?:Frost Brand|Fire Brand|Demonbane|Giantslayer|Vorpal Blade|Sunsword)\b")
DEMON_WIN = 0.7      # dip for a wish only while P(we beat a water demon) is above this


class ExcaliburState:
    """State of making Excalibur at a fountain (ExcaliburMixin)."""
    def __init__(self):
        self.excalibur = False
        self.turn = None
        self.dips = 0
        self.dip_events = []
        self.fountain_levels = set()
        self.trips = 0
        self.skip = set()
        self.demon_win = (None, 0.0)     # (state key, P(we beat a water demon))


class ExcaliburMixin:
    def excal_init(self):
        self.excal = ExcaliburState()

    def excal_summary(self):
        """Game summary entries."""
        return {"excalibur": self.excal.turn, "dips": self.excal.dips, "excal_trips": self.excal.trips,
                "dip_events": self.excal.dip_events, "fountain_levels": len(self.excal.fountain_levels)}

    def long_sword(self):
        """(letter, text) of a long sword of ours to dip for Excalibur, or None. fountain.c:371-373 dipfountain
        asks only for one long sword (quantity 1) that is no artifact -- a cursed one or one we named is fine (it
        comes out blessed: bless(obj)). (A/B excal_sword: +341 [+81, +613], median 7726 -> 7726, 35 of 1000
        changed)"""
        for it in self.items():
            if it.ocls != nh.WEAPON_CLASS or not re.search(r"\blong sword\b", it.text) or "Excalibur" in it.text:
                continue
            if base_name(it.text)[0] == 1 and not LONG_SWORD_ARTIFACT_RE.search(it.text):
                return it.letter, it.text
        return None

    def excal_eligible(self):
        if self.excal.excalibur:
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
            self.excal.fountain_levels.add(lv.key)
        if not self.excal_eligible():
            return False
        # the fountains we may use (fountains: no shop's, none in the Mines -- Minetown's watch --, none on a level
        # given up -- else a level given up was walked at again every tick)
        fmask = self.fountains(lv)
        if not fmask.any():
            return self.excal_go_up(lv)
        y, x = self.pos()
        if fmask[y, x]:
            return self.dip(lv)
        if self.walk_to(lv, fmask, max_cost=self.opts.excal_cost, act="excal", also=fmask)[0] == "moved":
            return True
        self.excal.skip.add(lv.key)                # can't reach it: don't keep coming back
        return False

    def excal_fountain_level(self):
        """The main-dungeon level, nearest in depth, with a fountain we could make Excalibur at (not a
        shop's, not on a level we gave up reaching it on), while Excalibur can be made at all (lawful, XL
        excal_xl, an unnamed long sword; not the HP: we rest for that). None: no such level."""
        if self.excal.excalibur or int(self.last_bl[nh.NLE_BL_ALIGN]) != 1 or self.bl(nh.NLE_BL_XP) < self.opts.excal_xl \
                or self.long_sword() is None:
            return None
        dl = self.bl(nh.NLE_BL_DEPTH)
        keys = [k for k, l in self.levels.items() if k[0] == 0 and self.fountains(l).any()]
        return min(keys, key=lambda k: abs(k[1] - dl)) if keys else None

    def excal_go_up(self, lv):
        """No fountain here, but one is remembered a few levels up: walk back up to it, toward the nearest such
        level by level_travel_step (no staircase known to lead elsewhere -- Sokoban's --, only the one known to lead
        up there while one is), each staircase taken a trip. (A/B excal_travel: -202 [-522, +128], median 7726 ->
        7567, 42 of 1000 changed)"""
        target = self.excal_up_target(lv)
        if target is None:
            return False
        if not self.level_travel_step(lv, self.grids(lv), target, "excal", "excal_travel", known_only=True,
                                      max_cost=self.opts.excal_cost_up):
            return False
        self.excal.trips += self.took_stairs
        return True

    def excal_up_target(self, lv):
        """The nearest main-dungeon level at most excal_up above this one with a fountain we may use
        (fountains), while trips are left; None."""
        if lv.key[0] != 0 or self.excal.trips >= self.opts.excal_trips:
            return None
        dl = lv.key[1]
        keys = [k for k, l in self.levels.items()
                if k[0] == 0 and dl - self.opts.excal_up <= k[1] < dl and self.fountains(l).any()]
        return max(keys, key=lambda k: k[1]) if keys else None

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
            self.excal.excalibur = True
            self.excal.turn = self.turn()
            lv.set_terrain((y, x), FLOOR_GLYPH)
            self.excal.dip_events.append((self.turn(), "excalibur"))
        elif self.fountain_gone(recent):
            lv.set_terrain((y, x), FLOOR_GLYPH)
            self.excal.dip_events.append((self.turn(), "dried"))
        return True

    @staticmethod
    def fountain_gone(recent):
        return "dries up" in recent or "fountain disappears" in recent or "anything to dip" in recent

    def dip_into_fountain(self, lv, letter):
        """#dip an inventory item into the fountain we stand on. The messages since, or None if no dip
        happened (no fountain here any more: forgotten)."""
        seq0 = self.msg_seq
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
        self.excal.dips += 1
        recent = self.text_since(seq0)
        if "water demon" in recent:              # fountain.c dipfountain case 21, either reason to dip
            self.excal.dip_events.append((self.turn(), "wish" if "grants you a wish" in recent else "demon"))
        if "glows for a moment" in recent:       # cases 17..20: the dipped item was cursed and is not now
            self.excal.dip_events.append((self.turn(), "uncursed"))
        return recent

    def demon_win_prob(self):
        """P(we win a fight with a water demon next to us, from full HP) -- danger.win_prob, cached while what it
        depends on stays the same (level, XL, max HP, AC, the weapon in hand)."""
        weapon = next((it.text for it in self.items() if it.wielded), None)
        key = (self.bl(nh.NLE_BL_DEPTH), self.bl(nh.NLE_BL_XP), self.bl(nh.NLE_BL_HPMAX), self.bl(nh.NLE_BL_AC),
               weapon)
        if self.excal.demon_win[0] != key:
            self.excal.demon_win = (key, self.win_prob([(None, "water demon")]))
        return self.excal.demon_win[1]

    def fountains(self, lv):
        """Fountains of this level we may use: not a shop's, not in the Mines (Minetown's watch), not on a
        level we gave up reaching them on."""
        fmask = self.terrain_glyphs(lv) == FOUNTAIN_GLYPH
        if lv.key[0] == 2 or lv.key in self.excal.skip:
            return fmask & False
        return fmask & ~lv.shop if lv.shop.any() else fmask

    def dip_at_fountain(self, lv, fmask, letter, act):
        """On a fountain of fmask: dip `letter`; else walk toward the nearest. True if it used the turn."""
        self.cur_act = act
        y, x = self.pos()
        if fmask[y, x]:
            recent = self.dip_into_fountain(lv, letter)
            if recent is None:
                return False
            if self.fountain_gone(recent):
                lv.set_terrain((y, x), FLOOR_GLYPH)
                self.excal.dip_events.append((self.turn(), "dried"))
            return True
        if self.walk_to(lv, fmask, max_cost=self.opts.excal_cost, act=act, also=fmask)[0] == "moved":
            return True
        self.excal.skip.add(lv.key)
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
        if lawful and not self.excal.excalibur:
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
                 and not it.quivered and not it.unpaid and not self.needed(it)
                 and not any(w in it.text for w in CONTAINERS) and not re.search(r"\blong sword\b", it.text)]
        return min(cands, key=lambda it: (rusts(it.text), JUNK_CLASSES.index(it.ocls)), default=None)

