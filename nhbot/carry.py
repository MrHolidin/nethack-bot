"""Carry valuables, never be Burdened.

Pick up: wands, rings, amulets, scrolls, potions, tools (not chests, boxes, traps), armor we won't wear,
spellbooks, gems/glass and diggers -- whatever fits without Burdened, or is worth more per weight than what
would go to make room (nhbot.value.worth_taking).

Never Burdened (Burdened costs a quarter of our speed). When the status shows any encumbrance, drop one
unit per turn: the lowest value per weight first (nhbot.value: worn / wielded, needed, food and water last).
A square we dropped something on is remembered: no going back to pick it up.

Kept from selling (needed; the selling is in shop.py): identified attack wands (wand_step), healing potions
(heal_step), scrolls known to be good (read_good).

Identity comes from the item text only: an unidentified potion/scroll/ring/wand/amulet/spellbook is named
by its appearance ("bubbly potion", "scroll labeled FOO"); identified ones by "... of X".
"""
import re
from collections import Counter

import numpy as np
import nle.nethack as nh

from nhbot.equipment import parse_armor
from nhbot.vault import FIND_SCROLLS
from nhbot.items import CORPSE_WEIGHT, GEM_LOOKS, base_name, corpse_kind, singular_name, unid_gem_look
from nhbot.pricemem import ARMOR_APPEAR, appearance
from nhbot.rays import ATTACK_WANDS
from nhbot.weapons import THROWABLE

CARRY_CLASSES = (nh.WAND_CLASS, nh.RING_CLASS, nh.AMULET_CLASS, nh.SCROLL_CLASS, nh.POTION_CLASS)
RANDOM_CLASSES = CARRY_CLASSES + (nh.SPBOOK_CLASS,)
CLASS_WEIGHT = {nh.WAND_CLASS: 7, nh.RING_CLASS: 3, nh.AMULET_CLASS: 20, nh.SCROLL_CLASS: 5,
                nh.POTION_CLASS: 20, nh.SPBOOK_CLASS: 50}
HEAL_POTIONS = ("full healing", "extra healing", "healing")

CARRY_GLYPH = np.zeros(nh.MAX_GLYPH, dtype=bool)
MORE_GLYPH = np.zeros(nh.MAX_GLYPH, dtype=bool)
for _g in range(nh.MAX_GLYPH):
    if nh.glyph_is_normal_object(_g):
        _c = ord(nh.objclass(nh.glyph_to_obj(_g)).oc_class)
        CARRY_GLYPH[_g] = _c in CARRY_CLASSES
        MORE_GLYPH[_g] = _c in (nh.TOOL_CLASS, nh.ARMOR_CLASS)
MORE_CLASSES = (nh.TOOL_CLASS, nh.ARMOR_CLASS)
WEAPON_GLYPH = np.zeros(nh.MAX_GLYPH, dtype=bool)
for _g in range(nh.MAX_GLYPH):
    if nh.glyph_is_normal_object(_g):
        WEAPON_GLYPH[_g] = ord(nh.objclass(nh.glyph_to_obj(_g)).oc_class) == nh.WEAPON_CLASS
# weapon appearances are fixed (not shuffled): "samurai sword" is always a katana, "broad pick" a dwarvish mattock
WEAPON_NAME_OF = {}
for _i in range(nh.NUM_OBJECTS):
    _oc = nh.objclass(_i)
    if ord(_oc.oc_class) == nh.WEAPON_CLASS and nh.OBJ_NAME(_oc):
        WEAPON_NAME_OF.setdefault(nh.OBJ_NAME(_oc), nh.OBJ_NAME(_oc))
for _i in range(nh.NUM_OBJECTS):
    _oc = nh.objclass(_i)
    if ord(_oc.oc_class) == nh.WEAPON_CLASS and nh.OBJ_DESCR(_oc):
        WEAPON_NAME_OF.setdefault(nh.OBJ_DESCR(_oc), nh.OBJ_NAME(_oc))
NO_TOOLS = {"chest", "large box", "ice box", "beartrap", "land mine"}
# also spellbooks, gems/glass (not gray stones: a loadstone can't be dropped; not rocks -- the one exception is the
# Mines' End luckstone nhbot.luckstone kick-tests and takes itself), and diggers
DIGGER_WORDS = ("pick-axe", "dwarvish mattock", "broad pick")
NO_GEMS = {"gray stone", "rock", "luckstone", "loadstone", "touchstone", "flint stone"}
GEM_NAMES = set()
ALL_GLYPH = np.zeros(nh.MAX_GLYPH, dtype=bool)
for _i in range(nh.NUM_OBJECTS):
    _oc = nh.objclass(_i)
    if ord(_oc.oc_class) == nh.GEM_CLASS and nh.OBJ_NAME(_oc) and nh.OBJ_NAME(_oc) not in NO_GEMS \
            and nh.OBJ_DESCR(_oc) != "gray":
        GEM_NAMES.add(nh.OBJ_NAME(_oc))
for _g in range(nh.MAX_GLYPH):
    if nh.glyph_is_normal_object(_g):
        _oc = nh.objclass(nh.glyph_to_obj(_g))
        _c = ord(_oc.oc_class)
        ALL_GLYPH[_g] = _c == nh.SPBOOK_CLASS or (_c == nh.GEM_CLASS and nh.OBJ_NAME(_oc) in GEM_NAMES)
KEEP_TOOLS = ("unicorn horn",)
TOOL_WORDS = set()                # tool names and looks ("oil lamp", "lamp", "bag", "wax candle")
for _i in range(nh.NUM_OBJECTS):
    _oc = nh.objclass(_i)
    if ord(_oc.oc_class) == nh.TOOL_CLASS:
        for _w in (nh.OBJ_NAME(_oc), nh.OBJ_DESCR(_oc)):
            if _w:
                TOOL_WORDS.add(_w)
TOOL_LOOKS = {nh.OBJ_DESCR(nh.objclass(_i)) for _i in range(nh.NUM_OBJECTS)
              if ord(nh.objclass(_i).oc_class) == nh.TOOL_CLASS and nh.OBJ_DESCR(nh.objclass(_i))}

# identified name -> (weight, cost), from objects.c
OBJ_INFO = {}                     # (class, name): names repeat across classes ("levitation")
for _i in range(nh.NUM_OBJECTS):
    _oc = nh.objclass(_i)
    _n = nh.OBJ_NAME(_oc)
    if _n:
        OBJ_INFO.setdefault((ord(_oc.oc_class), _n), (_oc.oc_weight, _oc.oc_cost))
FIXED_LOOK = {}                   # (class, description of one type only) -> that type ("faded pall" -> elven cloak)
for _i in range(nh.NUM_OBJECTS):
    _oc = nh.objclass(_i)
    _d = nh.OBJ_DESCR(_oc)
    if _d and nh.OBJ_NAME(_oc):
        FIXED_LOOK.setdefault((ord(_oc.oc_class), _d), []).append(nh.OBJ_NAME(_oc))
FIXED_LOOK = {k: v[0] for k, v in FIXED_LOOK.items() if len(v) == 1}
APPEAR_WEIGHT = {}
for _i in range(nh.NUM_OBJECTS):
    _oc = nh.objclass(_i)
    _d = nh.OBJ_DESCR(_oc)
    if _d:
        APPEAR_WEIGHT[_d] = max(APPEAR_WEIGHT.get(_d, 0), _oc.oc_weight)

ID_RE = re.compile(r"\b(potion|scroll|ring|wand|amulet|spellbook)s? of ([a-zA-Z' -]+?)(?: \(|$| called| named)")


def is_clear_potion(ocls, text):
    """Water (holy / unholy / plain): its look is fixed, "clear potion"."""
    return ocls == nh.POTION_CLASS and re.match(r"^clear potions?$", base_name(text)[2]) is not None


def singular(w):
    if w.endswith("ves"):
        return w[:-3] + "f"
    if w.endswith("ies"):
        return w[:-3] + "y"
    if w.endswith(("ches", "shes", "xes", "sses")):
        return w[:-2]
    if w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def describe(ocls, s):
    """Inventory/floor text -> dict(qty, unit weight, unit cost (None if unknown), unidentified, key). Names made
    singular by items.singular_name (makeplural inverted); a corpse weighs its monster's cwt, an unidentified gem /
    glass / gray stone its type's weight (objects.c)."""
    # (name_parse, accepted without A/B by the user; its A/B: -649 [-2301, +1045], median 7726 -> 7638, 716 changed --
    # in every divergence checked on real games the new parse is the game's: gems weigh 1, cloves of garlic / cream
    # pies are food, fencing gloves / hiking boots looks, a stack's piece nutrition). It replaced a word-by-word
    # singular ("knives" was "knif", "cloves of garlic" no food) and a gem weight of 10.
    qty, _, t = base_name(s)
    t = re.sub(r"^(pair|set)s? of ", "", t).strip()
    unid, name = False, None
    if ocls in RANDOM_CLASSES:
        mm = ID_RE.search(s)
        if mm:
            kind, what = mm.group(1), mm.group(2).strip()
            name = ("amulet of " + what) if kind == "amulet" else what
        else:
            unid = True
    elif ocls == nh.ARMOR_CLASS:
        a = parse_armor(s)
        nm = a["name"] if a else t
        unid = nm in ARMOR_APPEAR
        name = nm
    else:
        name = t
        if ocls == nh.WEAPON_CLASS:
            name = WEAPON_NAME_OF.get(t, WEAPON_NAME_OF.get(singular_name(t), t))
        one = singular_name(t)
        if ocls == nh.TOOL_CLASS and one in TOOL_LOOKS and (ocls, one) not in OBJ_INFO:
            unid = True                      # "bag", "lamp", "flute": several types share the look
    if name is not None and (ocls, name) not in OBJ_INFO:
        one = singular_name(name)
        head = one.split(" of ")[0]
        name = head if (ocls, one) not in OBJ_INFO and (ocls, head) in OBJ_INFO else one     # "tins of X meat": tin
    if (ocls, name) in OBJ_INFO:
        wt, cost = OBJ_INFO[(ocls, name)]
    elif ocls == nh.FOOD_CLASS and corpse_kind(t):
        wt, cost = CORPSE_WEIGHT[corpse_kind(t)], None          # mkobj.c weight(): the monster's cwt
    elif ocls == nh.GEM_CLASS and unid_gem_look(t):
        wt, cost = GEM_LOOKS[unid_gem_look(t)], None
    else:
        wt = CLASS_WEIGHT.get(ocls) or APPEAR_WEIGHT.get(singular(t), APPEAR_WEIGHT.get(t, 10))
        cost = None
    app = singular_name(t)
    return {"qty": qty, "wt": max(wt, 1), "cost": cost, "unid": unid, "key": (ocls, app if unid else name)}


class CarryState:
    """State of what we carry: drops, squeezes, carry statistics (CarryMixin)."""
    def __init__(self):
        self.cant_drop = set()     # Item.key of items the game refused to drop (a cursed loadstone): never again
        self.squeeze_pending = None  # (level key, square) a diagonal squeeze refused for our weight (squeeze_step)
        self.squeeze_stats = Counter()
        self.stats = {"picked": 0, "dropped": [0, 0, 0, 0, 0], "sold": 0, "gold": 0, "kept_back": 0}


class CarryMixin:
    def carry_init(self):
        self.carry = CarryState()

    def carry_classes(self):
        return CARRY_CLASSES + MORE_CLASSES + (nh.WEAPON_CLASS, nh.SPBOOK_CLASS, nh.GEM_CLASS)

    def carry_stat(self, k, n=1):
        """Count n for k in the summary 'carry' (what was picked up, lifted, sold or kept back)."""
        self.carry.stats[k] = self.carry.stats.get(k, 0) + n

    def drop_refused(self, it):
        """The game would not let it drop (a cursed loadstone): never tried again."""
        self.carry.cant_drop.add(it.key)

    # ------------------------------------------------------------ never Burdened
    def squeeze_msg(self, m, lv):
        """msg_map: a diagonal squeeze refused for our weight -- it needs inventory weight <= 600 (hack.c test_move):
        squeeze_step sheds a unit next tick, unless dig_through digs a corner instead. True if m said so."""
        if not (lv and self.nav.last_move_target and "You are carrying too much to get through" in m):
            return False
        self.carry.squeeze_stats["refused"] += 1
        if not self.dig_through_note(lv, self.pos(), self.nav.last_move_target, "squeeze"):
            self.carry.squeeze_pending = (lv.key, self.nav.last_move_target)
        return True

    def squeeze_step(self, lv):
        """The squeeze refused last tick on this level: drop one unit (nothing on the body); nothing left to shed --
        the squeeze stays shut (Level.blocked). True if it used the turn."""
        if self.carry.squeeze_pending is None:
            return False
        key, target = self.carry.squeeze_pending
        self.carry.squeeze_pending = None
        if key != lv.key:
            return False
        if self.carry_drop_step(force=True, keep_body=True):
            self.carry.squeeze_stats["dropped"] += 1
            return True
        self.carry.squeeze_stats["nothing_to_drop"] += 1
        self.no_entry_mark(lv, target)
        return False

    def carry_drop_step(self, force=False, keep_body=False):
        """Encumbered (or force): drop one unit of the item of lowest value per weight (nhbot.value: what we
        wear / wield / need comes last, being worth VALUE_MAX); keep_body: nothing on the body. Not encumbered, but
        all 52 letters taken and nothing in view: the whole stack value.slot_victim names, so the next item worth a
        letter finds one (value.slot_ok; A/B slots: -745 [-1636, +144], median 7777 -> 7787). True if it used the
        turn."""
        if self.bl(nh.NLE_BL_CAP) < 1 and not force:
            if self.letters_free() <= 0 and not self.visible_hostiles(self.level()):
                victim = self.slot_victim()
                if victim is not None:
                    self.drop_units(victim.letter)
                    self.carry.stats["slot_dropped"] = self.carry.stats.get("slot_dropped", 0) + 1
                    return True
            return False
        inv = [it for it in self.items() if it.ocls != nh.COIN_CLASS and it.key not in self.carry.cant_drop
               and not (keep_body and it.on_body) and not self.sac_carrying(it)]
        if not inv:
            return False
        looks = self.carried_by_look()
        same = lambda it: looks[appearance(it.text)] if appearance(it.text) is not None else 1
        it = min(inv, key=lambda it: self.value_per_weight(it, same(it)))
        it = self.lift_undo(it, inv, same)
        if self.gold_bag_unload(it):
            return True                      # gold_bag: the gold out of the bag first, loose gold is kept
        if it.on_body:
            if it.ocls == nh.ARMOR_CLASS and it.worn:
                a = parse_armor(it.text) or {"slot": None}
                a["letter"] = it.letter
                if not self.take_off(a):
                    return False
            self.drop_units(it.letter)
            self.carry.stats["dropped"][4] += 1
            return True
        d = describe(it.ocls, it.text)
        self.drop_units(it.letter, 1 if d["qty"] > 1 else None)
        self.carry.stats["dropped"][2 if self.is_unknown(it.ocls, it.text) else 3] += 1
        return True

    # ------------------------------------------------------------ what we keep
    def needed(self, it):
        c, s = it.ocls, it.text
        if c == nh.WAND_CLASS and self.wand_kind(it) in ATTACK_WANDS:
            return not self.wand_spent(it)   # an empty one is only weight
        if c == nh.POTION_CLASS and any(("potion of " + p) in s or ("potions of " + p) in s for p in HEAL_POTIONS):
            return True
        if c == nh.SCROLL_CLASS \
                and self.scroll_is_good(s):
            return True
        if c == nh.TOOL_CLASS and any(k in s for k in KEEP_TOOLS) and not self.horn_is_bad(it):
            return True                      # a horn that harmed us is cursed: sold
        if c == nh.POTION_CLASS and self.potion_100(s):
            return True                      # maybe healing / extra healing -- kept for quaff_test
        if c == nh.POTION_CLASS and self.oil_needed(it):
            return True                      # one stack of oil against rust while we have no Excalibur (nhbot.oil)
        bag = self.gold_bag() if c == nh.TOOL_CLASS else None
        if bag is not None and bag.letter == it.letter:
            return True                      # gold_bag: the bag our gold goes in (nhbot.goldbag)
        if c == nh.SCROLL_CLASS and any(n in s.replace("scrolls", "scroll") for n in FIND_SCROLLS) \
                or c == nh.WAND_CLASS and "wand of digging" in s:
            return True                      # to find a vault and dig to it (nhbot.vault)
        if c == nh.TOOL_CLASS:
            lt = self.lock_tool()
            if lt is not None and lt.letter == it.letter:
                return True                  # the unlocking tool we keep (nhbot.locktools)
        if any(w in s for w in DIGGER_WORDS):
            return True                      # a digger: kept (vaults, ways down), never sold
        if self.luck_keeps(it):
            return True                      # our kick-tested Mines' End luckstone, not known cursed
                                             # -- the one gray stone kept (NO_GEMS), never dipped (nhbot.luckstone)
        if self.wish_needed(it):
            return True                      # a lamp to rub, a wand of wishing (nhbot.wishing)
        if self.jewelry_needed(it):
            return True                      # jewelry: identify scrolls, amulets and rings to identify
        if c == nh.WEAPON_CLASS:
            d = describe(c, s)["key"][1]
            if d in ("long sword", "katana") or "Excalibur" in s or any(k in d for k in THROWABLE):
                return True                  # wield candidates (weapons.weapon_rank) and missiles we throw
        return False
