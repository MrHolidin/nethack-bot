"""Picking things up: what lies where and is worth a walk (explore goals), what to take from a pile, the
'Pick up what?' menu, merchandise. Every path that picks something up goes through here:

  pile        housekeeping on an uninspected pile under us (armor upgrade, carried classes, weapons, food)
  gold        gold on our square (step_gold_here)
  ammo        our missiles on our square (step_ammo_here)
  retrieve    our thrown missiles along their rays (step_retrieve_missiles)
  loot        the square a thief died on (thieves.loot_consume)
  own         what we put down ourselves (an unsold offer, the digger left outside a shop)
"""
import re
from collections import Counter

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.carry import (ALL_GLYPH, CARRY_CLASSES, CARRY_GLYPH, GEM_NAMES, MORE_GLYPH, NO_TOOLS, OBJ_INFO,
                         TOOL_WORDS, WEAPON_GLYPH, WEAPON_NAME_OF, singular)
from nhbot.combat import THROWABLE
from nhbot.equipment import parse_armor
from nhbot.items import CURSED_RE, base_name

# safe permanent food (no eggs: could be cockatrice; no tins: slow; no unknown corpses)
SAFE_FOOD = ("food ration", "cram ration", "lembas wafer", "K-ration", "C-ration", "fortune cookie",
             "apple", "orange", "pear", "melon", "banana", "carrot", "slime mold", "pancake", "cream pie",
             "candy bar", "lump of royal jelly", "kelp frond", "eucalyptus leaf", "sprig of wolfsbane",
             "clove of garlic", "meatball", "meat stick", "huge chunk of meat", "meat ring",
             "lichen corpse", "lizard corpse")
MAX_FOOD = 6
AMMO_WORDS = re.compile(r"\b(darts?|daggers?|knives|knife|shuriken|spears?|javelins?|arrows?|crossbow bolts?)\b")

# ---------------------------------------------------------------- pickup_v2: item kinds by type, not substring
_WEAPONS = {nh.OBJ_NAME(nh.objclass(i)) for i in range(nh.NUM_OBJECTS)
            if ord(nh.objclass(i).oc_class) == nh.WEAPON_CLASS and nh.OBJ_NAME(nh.objclass(i))}
MISSILE_TYPES = {n for n in _WEAPONS if any(w in n for w in THROWABLE)} - {"crysknife"}   # what we throw
AMMO_TYPES = {"arrow", "elven arrow", "orcish arrow", "silver arrow", "ya", "crossbow bolt"}   # needs a launcher
WIELD_TYPES = {"long sword", "katana"}                                                       # weapons.weapon_rank
THROW_STONE_TYPES = {"flint stone", "rock"}
FOOD_NAMES = {nh.OBJ_NAME(nh.objclass(i)) for i in range(nh.NUM_OBJECTS)
              if ord(nh.objclass(i).oc_class) == nh.FOOD_CLASS and nh.OBJ_NAME(nh.objclass(i))}
SAFE_FOOD_SET = set(SAFE_FOOD)
CLASS_WORDS = {"potion": nh.POTION_CLASS, "scroll": nh.SCROLL_CLASS, "ring": nh.RING_CLASS, "wand": nh.WAND_CLASS,
               "amulet": nh.AMULET_CLASS, "spellbook": nh.SPBOOK_CLASS}
CLASS_RE = re.compile(r"\b(potion|scroll|ring|wand|amulet|spellbook)s?\b")
STOLE_RE = re.compile(r"\b(?:stole|steals) (.+?)[.!](?:\s|$)")
WANTED_WEAPON_GLYPH = np.zeros(nh.MAX_GLYPH, dtype=bool)   # a remembered weapon worth the walk
for _g in range(nh.MAX_GLYPH):
    if WEAPON_GLYPH[_g]:
        _n = nh.OBJ_NAME(nh.objclass(nh.glyph_to_obj(_g)))
        _wc = OBJ_INFO.get((nh.WEAPON_CLASS, _n))
        WANTED_WEAPON_GLYPH[_g] = _n not in AMMO_TYPES and (_n in MISSILE_TYPES or _n in WIELD_TYPES
                                                          or bool(_wc and _wc[1] >= _wc[0]))


def floor_kind(text):
    """Floor / menu text -> (object class or None, type name): identified name for weapons and food, else the
    bare name."""
    _, _, name = base_name(text)
    one = " ".join(singular(w) for w in name.split(" "))
    if re.search(r"\bgold pieces?\b", name):
        return nh.COIN_CLASS, "gold piece"
    if re.search(r"\bcorpses?$", name):
        return nh.FOOD_CLASS, re.sub(r"s$", "", name)
    if name in FOOD_NAMES or one in FOOD_NAMES:
        return nh.FOOD_CLASS, name if name in FOOD_NAMES else one
    m = CLASS_RE.search(name)
    if m:
        return CLASS_WORDS[m.group(1)], name
    w = WEAPON_NAME_OF.get(name) or WEAPON_NAME_OF.get(one)
    if w:
        return nh.WEAPON_CLASS, w
    a = parse_armor(text)
    if a is not None:
        return nh.ARMOR_CLASS, a["name"]
    if name in TOOL_WORDS or one in TOOL_WORDS:
        return nh.TOOL_CLASS, one if one in TOOL_WORDS else name
    if one in ("boulder", "statue") or one.startswith("statue of"):
        return nh.ROCK_CLASS, one
    if one in ("heavy iron ball", "iron chain"):
        return nh.BALL_CLASS if "ball" in one else nh.CHAIN_CLASS, one
    if one in GEM_NAMES or name in GEM_NAMES or one.endswith(" gem") or "glass" in one or one.endswith(" stone") \
            or one == "rock":
        return nh.GEM_CLASS, one
    return None, name


class PickupMixin:
    def pickup_init(self):
        self.stolen_names = set()      # bare names of what thieves took from us (loot takes these back)
        self.pickup_stats = Counter()  # pickup_v2: why things were taken / refused
        self._take_state = None        # (food count, encumbrance) frozen while one pickup is judged

    # ------------------------------------------------------------------ merchandise
    def merch_risk(self, lv, pos):
        """Could what lies at pos be merchandise? On a shop square; and unless shop_by_square, whenever a
        shopkeeper is in view. pickup_v2: a shopkeeper in view counts only while no shop on this level is
        marked (the marked squares are the better answer)."""
        if self.opts.pickup_v2:
            return bool(lv.shop[pos]) or (self.shopkeeper_in_view() and not lv.shop.any())
        return bool(lv.shop[pos]) or (not self.opts.shop_by_square and self.shopkeeper_in_view())

    # ------------------------------------------------------------------ pickup_v2: one rule what to take
    def take_reason(self, text, worn=None):
        """Why we'd take this floor item: "armor" (an upgrade), "missile", "weapon" (a wield candidate), "food",
        "carry" (worth carrying to sell / use); None: leave it. Never merchandise, known-cursed armor / weapons,
        ammunition without a launcher, rocks / boulders / iron balls; "carry" not while Burdened (the drop step
        would put it down again)."""
        if "for sale" in text:
            return None
        food_n, cap = self._take_state or (self.food_count(), self.bl(nh.NLE_BL_CAP))
        ocls, typ = floor_kind(text)
        cursed = bool(CURSED_RE.search(text))
        reason = None
        if ocls == nh.FOOD_CLASS:
            if typ in SAFE_FOOD_SET and "partly eaten" not in text and food_n < MAX_FOOD:
                reason = "food"
        elif ocls in CARRY_CLASSES:
            reason = "carry"
        elif ocls == nh.ARMOR_CLASS:
            a = parse_armor(text)
            if a is not None and not a["cursed"] and self.improves(a, worn if worn is not None else self.worn_by_slot()):
                reason = "armor"
            elif self.carry_all_on() and not cursed:
                reason = "carry"
        elif ocls == nh.WEAPON_CLASS and not cursed and typ not in AMMO_TYPES:
            if typ in MISSILE_TYPES:
                reason = "missile"
            elif typ in WIELD_TYPES:
                reason = "weapon"
            else:
                wc = OBJ_INFO.get((nh.WEAPON_CLASS, typ))
                if wc and wc[1] >= wc[0]:
                    reason = "carry"                     # worth >= 1 zorkmid per weight unit
        elif ocls == nh.TOOL_CLASS and self.carry_all_on():
            no_tools = NO_TOOLS - {"pick-axe"}
            if typ not in no_tools:
                reason = "carry"
        elif ocls in (nh.SPBOOK_CLASS, nh.GEM_CLASS) and self.carry_all_on():
            if ocls == nh.SPBOOK_CLASS or not (typ == "gray stone" or typ in THROW_STONE_TYPES):
                reason = "carry"
        if reason == "carry" and cap >= 1:
            return None
        return reason

    # ------------------------------------------------------------------ explore goals: piles worth a walk
    def weapon_glyphs(self):
        return WANTED_WEAPON_GLYPH if self.opts.pickup_v2 else WEAPON_GLYPH

    def carry_glyph(self, g):
        """Is this remembered glyph an item carry goes for? The SAME test makes it an explore goal and
        makes the step that inspects it (and so removes the goal) run."""
        return bool(CARRY_GLYPH[g] or (self.carry_all_on() and MORE_GLYPH[g])
                    or (self.weapon_glyphs()[g]) or (self.carry_all_on() and ALL_GLYPH[g]))

    def carry_targets(self, lv):
        glyphs = CARRY_GLYPH | MORE_GLYPH if self.carry_all_on() else CARRY_GLYPH
        glyphs = glyphs | self.weapon_glyphs()
        if self.carry_all_on():
            glyphs = glyphs | ALL_GLYPH
        mask = glyphs[lv.under] & ~lv.shop
        for p in self.goal_closed_set("pile", lv.key):
            mask[p] = False
        return mask

    def armor_targets(self, lv, glyphs_mod):
        """Mask of remembered '[' (and '%' food when low on food) piles not yet inspected."""
        mask = glyphs_mod.ARMOR_GLYPH[lv.under].copy()
        if self.food_count() < MAX_FOOD:
            mask = mask | glyphs_mod.FOOD_GLYPH[lv.under]
        for p in self.goal_closed_set("pile", lv.key):
            mask[p] = False
        return mask

    def pile_to_inspect(self, lv, y, x):
        """An armor / food / carried-class pile under us that we have not looked at, outside a shop."""
        return bool((G.ARMOR_GLYPH[lv.under[y, x]] or G.FOOD_GLYPH[lv.under[y, x]]
                     or self.carry_glyph(lv.under[y, x])) and (y, x) not in self.goal_closed_set("pile", lv.key)
                    and not lv.shop[y, x])

    # ------------------------------------------------------------------ what to take
    def carry_wanted(self, n):
        """A floor item (look_here text) to take: one of the carried classes, not merchandise."""
        if "for sale" in n:
            return None
        if re.search(r"\b(potion|scroll|ring|wand|amulet)s?\b", n) and "corpse" not in n:
            return re.sub(r"^(a|an|the|\d+)\s+", "", n).strip()
        if "corpse" not in n:
            core = base_name(n)[2]
            one = " ".join(singular(w) for w in core.split(" "))
            if (core in WEAPON_NAME_OF or one in WEAPON_NAME_OF) and " cursed" not in " " + n:
                return core
        if self.carry_all_on():
            a = parse_armor(n)
            if a is not None:
                return a["name"]
            core = base_name(n)[2]
            one = " ".join(singular(w) for w in core.split(" "))
            no_tools = NO_TOOLS - {"pick-axe"} if self.carry_all_on() else NO_TOOLS
            if (core in TOOL_WORDS or one in TOOL_WORDS) and core not in no_tools and one not in no_tools:
                return core
        if self.carry_all_on() and "corpse" not in n:
            core = base_name(n)[2]
            one = " ".join(singular(w) for w in core.split(" "))
            if "spellbook" in core:
                return core
            if "gray stone" in core:
                return None
            if one.endswith(" gem") or "glass" in one or one in GEM_NAMES or core in GEM_NAMES:
                return core
        return None

    def food_count(self):
        return sum(1 for _, ocls, _ in self.inventory() if ocls == nh.FOOD_CLASS)

    def food_wanted(self, name):
        if self.food_count() >= MAX_FOOD:
            return False
        if "egg" in name or re.search(r"\btins?\b", name):
            return False
        if "partly eaten" in name:
            return False
        return any(f in name for f in SAFE_FOOD)

    # ------------------------------------------------------------------ the paths
    def armor_pickup_here(self, lv):
        self.goal_done("pile", lv, self.pos())
        names = self.look_here()
        # never take merchandise (a lone item is picked up without a menu, so filter here)
        names = [n for n in names if "for sale" not in n]
        worn = self.worn_by_slot()
        if self.opts.pickup_v2:
            reasons = [self.take_reason(n, worn) for n in names]
            if not any(reasons):
                return False
            for r in reasons:
                if r:
                    self.pickup_stats[r] += 1
                    self.carry_stats["picked"] += r in ("carry", "missile", "weapon")
                    self.food_picked += r == "food"
            self.take_here(lambda t: self.take_reason(t, worn) is not None, "pile")
            self.equip_events.append((self.turn(), "pickup", ",".join(n for n, r in zip(names, reasons) if r)))
            return True
        want = []
        for n in names:
            a = parse_armor(n)
            if a and self.improves(a, worn):
                want.append(a["name"])
            elif self.carry_wanted(n):
                want.append(self.carry_wanted(n))
                self.carry_stats["picked"] += 1
            elif self.food_wanted(n):
                fm = next((f for f in SAFE_FOOD if f in n), None)
                if fm is None:
                    continue
                want.append(fm)
                self.food_picked += 1
        if not want:
            return False
        self.pickup_matching(want)
        self.equip_events.append((self.turn(), "pickup", ",".join(want)))
        return True

    def pickup_all(self):
        if self.merch_risk(self.level(), self.pos()):
            self.msg_audit["loot_pickup_merch_risk"] += 1
        if self.opts.pickup_v2:
            # what the thief took from us, and whatever else is worth taking; never merchandise (a thief that
            # dies in a shop leaves its haul for sale)
            def want(t):
                if "for sale" in t:
                    return False
                if base_name(t)[2] in self.stolen_names:
                    self.pickup_stats["loot_stolen"] += 1
                    return True
                return self.take_reason(t) is not None
            self.take_here(want, "loot")
            return
        self.pickup(lambda t: "corpse" not in t and "boulder" not in t, "loot")

    def take_ammo(self):
        """pickup_v2 ammo / retrieve: our missiles (and the stones we throw) here."""
        def want(t):
            if "for sale" in t or CURSED_RE.search(t):
                return False
            ocls, typ = floor_kind(t)
            return (ocls == nh.WEAPON_CLASS and typ in MISSILE_TYPES) or (ocls == nh.GEM_CLASS and typ in THROW_STONE_TYPES)
        if not self.merch_risk(self.level(), self.pos()):
            self.take_here(want, "ammo")

    def take_here(self, want, site):
        """pickup_v2: pick up what want(text) accepts; a lone item comes without a menu whatever it is: put it
        straight back down if want rejects it."""
        seq0 = self.msg_seq
        self._take_state = (self.food_count(), self.bl(nh.NLE_BL_CAP))    # judged as before the pickup
        try:
            self.pickup(want, site)
            lone = next((mm for mm in (re.match(r"^([a-zA-Z]) - (.+?)\.?$", t) for t in self.msgs_since(seq0))
                         if mm), None)
            bad = lone is not None and not want(lone.group(2))
        finally:
            self._take_state = None
        if bad:
            self.pickup_stats["lone_dropped"] += 1
            self.drop_units(lone.group(1))

    # ------------------------------------------------------------------ the menu
    def pickup(self, want, site):
        """',' and select what want(text) accepts in the 'Pick up what?' menu (a lone item is picked up
        without a menu)."""
        seq0 = self.msg_seq
        self.press(",", expect_prompt=True)
        tty = self.tty_text()
        if "Pick up what?" not in tty:
            self.settle()
            for t in self.msgs_since(seq0):
                mm = re.match(r"^[a-zA-Z] - (.+?)\.?$", t)
                if mm and not want(mm.group(1)):
                    self.msg_audit["lone_unwanted_" + site] += 1     # picked up what the filter rejects
            return
        if re.search(r"\(1 of \d+\)", tty):
            self.msg_audit["pickup_multipage_" + site] += 1
        n = 0
        for letter, text in self.menu_items(tty, "Pick up what?"):
            if want(text):
                self.raw_step(ord(letter))
                n += 1
        self.raw_step(13 if n else 27)
        self.settle()

    def pickup_matching(self, words, no_sale=False, own=False):
        if not own and self.merch_risk(self.level(), self.pos()):
            return                            # in a shop: anything here may be merchandise
        self.pickup(lambda t: any(w in t for w in words) and not (no_sale and "for sale" in t), "matching")
