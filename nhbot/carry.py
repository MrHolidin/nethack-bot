"""Carry valuables, never be Burdened, sell what we don't use.

Pick up: wands, rings, amulets, scrolls, potions, tools (not chests, boxes, traps), armor we won't wear,
spellbooks, gems/glass and diggers -- whatever fits without Burdened, or is worth more per weight than what
would go to make room (nhbot.value.worth_taking).

Never Burdened (Burdened costs a quarter of our speed). When the status shows any encumbrance, drop one
unit per turn: the lowest value per weight first (nhbot.value: worn / wielded, needed, food and water last).
A square we dropped something on is remembered: no going back to pick it up.

Sell: in a shop that buys the class (general store: everything), drop each item we have no use for deep
inside the shop and accept the offer; take back what the shopkeeper won't buy. Kept: identified attack
wands (wand_step), healing potions (heal_step), scrolls known to be good (read_good).

Identity comes from the item text only: an unidentified potion/scroll/ring/wand/amulet/spellbook is named
by its appearance ("bubbly potion", "scroll labeled FOO"); identified ones by "... of X".
"""
import re

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.equipment import parse_armor
from nhbot.vault import FIND_SCROLLS
from nhbot.items import base_name
from nhbot.pricemem import appearance

CARRY_CLASSES = (nh.WAND_CLASS, nh.RING_CLASS, nh.AMULET_CLASS, nh.SCROLL_CLASS, nh.POTION_CLASS)
RANDOM_CLASSES = CARRY_CLASSES + (nh.SPBOOK_CLASS,)
CLASS_WEIGHT = {nh.WAND_CLASS: 7, nh.RING_CLASS: 3, nh.AMULET_CLASS: 20, nh.SCROLL_CLASS: 5,
                nh.POTION_CLASS: 20, nh.SPBOOK_CLASS: 50}
RANDOM_ARMOR = {"plumed helmet", "etched helmet", "crested helmet", "visored helmet", "old gloves",
                "padded gloves", "riding gloves", "fencing gloves", "combat boots", "jungle boots",
                "hiking boots", "mud boots", "buckled boots", "riding boots", "snow boots", "tattered cape",
                "opera cloak", "ornamental cope", "piece of cloth"}
ATTACK_WANDS = ("sleep", "magic missile", "fire", "cold", "lightning", "striking")
HEAL_POTIONS = ("full healing", "extra healing", "healing")

ALL = None
SHOP_BUYS = {
    "general store": ALL,
    "used armor dealership": {nh.ARMOR_CLASS, nh.WEAPON_CLASS},
    "second-hand bookstore": {nh.SCROLL_CLASS, nh.SPBOOK_CLASS},
    "liquor emporium": {nh.POTION_CLASS},
    "antique weapons outlet": {nh.WEAPON_CLASS, nh.ARMOR_CLASS},
    "delicatessen": {nh.FOOD_CLASS},
    "jewelers": {nh.RING_CLASS, nh.GEM_CLASS, nh.AMULET_CLASS},
    "quality apparel and accessories": {nh.WAND_CLASS, nh.ARMOR_CLASS},
    "hardware store": {nh.TOOL_CLASS},
    "rare books": {nh.SPBOOK_CLASS, nh.SCROLL_CLASS},
    "lighting store": {nh.TOOL_CLASS},
}

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
KEEP_WEAPONS = ("dagger", "knife", "dart", "shuriken", "javelin", "spear")   # combat.THROWABLE: thrown, kept
NO_TOOLS = {"chest", "large box", "ice box", "beartrap", "land mine"}
# also spellbooks, gems/glass (not gray stones: a loadstone can't be dropped; not rocks), and diggers
DIGGER_WORDS = ("pick-axe", "dwarvish mattock", "broad pick")
LEAVE_RE = re.compile(r"[Ll]eave (?:your|the) .*outside")
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
APPEAR_WEIGHT = {}
for _i in range(nh.NUM_OBJECTS):
    _oc = nh.objclass(_i)
    _d = nh.OBJ_DESCR(_oc)
    if _d:
        APPEAR_WEIGHT[_d] = max(APPEAR_WEIGHT.get(_d, 0), _oc.oc_weight)

ID_RE = re.compile(r"\b(potion|scroll|ring|wand|amulet|spellbook)s? of ([a-zA-Z' -]+?)(?: \(|$| called| named)")


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
    """Inventory/floor text -> dict(qty, unit weight, unit cost (None if unknown), unidentified, key)."""
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
        unid = nm in RANDOM_ARMOR
        name = nm
    else:
        name = t
        if ocls == nh.WEAPON_CLASS:
            name = WEAPON_NAME_OF.get(t, WEAPON_NAME_OF.get(" ".join(singular(w) for w in t.split(" ")), t))
        if ocls == nh.TOOL_CLASS and singular(t) in TOOL_LOOKS and (ocls, singular(t)) not in OBJ_INFO:
            unid = True                      # "bag", "lamp", "flute": several types share the look
    if name is not None and (ocls, name) not in OBJ_INFO:
        words = name.split(" ")
        for i in range(len(words)):
            cand = " ".join(words[:i] + [singular(words[i])] + words[i + 1:])
            if (ocls, cand) in OBJ_INFO:
                name = cand
                break
    if (ocls, name) in OBJ_INFO:
        wt, cost = OBJ_INFO[(ocls, name)]
    else:
        wt = CLASS_WEIGHT.get(ocls) or APPEAR_WEIGHT.get(singular(t), APPEAR_WEIGHT.get(t, 10))
        cost = None
    app = " ".join(singular(w) if w.islower() else w for w in t.split(" "))
    return {"qty": qty, "wt": max(wt, 1), "cost": cost, "unid": unid, "key": (ocls, app if unid else name)}


class CarryMixin:
    def carry_init(self):
        self.cant_drop = set()     # Item.key of items the game refused to drop (a cursed loadstone): never again
        self.carry_stats = {"picked": 0, "dropped": [0, 0, 0, 0, 0], "sold": 0, "gold": 0, "kept_back": 0}
        self.selling = False
        self.sell_tried = set()      # (shop level key, item text) the shopkeeper would not take
        self.stash_pending = None    # (level key, door) -- a shopkeeper asked us to leave the digger outside
        self.dig_stash = None        # dict(key, pos, turn): where we left it
        self.stash_stats = {"asked": 0, "stashed": 0, "retrieved": 0, "lost": 0}
        self.selling_item = (None, "")   # (class, text) of the item on offer
        self.last_drop_qty = None        # units in the last drop (pricemem reads it for a sell offer)

    def carry_classes(self):
        return CARRY_CLASSES + MORE_CLASSES + (nh.WEAPON_CLASS, nh.SPBOOK_CLASS, nh.GEM_CLASS)

    # ------------------------------------------------------------ pick up
    # ------------------------------------------------------------ never Burdened
    def drop_units(self, letter, n=None):
        """Drop n of a stack (all if None); remember the square."""
        item = next((it for it in self.items() if it.letter == letter), None)
        s = item.text if item else ""
        m = re.match(r"^(\d+) ", s)
        self.last_drop_qty = n or (int(m.group(1)) if m else 1)
        self.goal_close("pile", self.level().key, self.pos())      # never come back for what we dropped
        seq0 = self.msg_seq
        if not self.ask("d", "drop"):
            return
        if n:
            for c in str(n):
                self.raw_step(ord(c))
        self.press(letter)
        if any("cannot drop" in t for t in self.msgs_since(seq0)) and item is not None:
            self.cant_drop.add(item.key)      # "For some reason, you cannot drop the stone!"

    def carry_drop_step(self, force=False, max_tier=4):
        """Encumbered (or force): drop one unit of the item of lowest value per weight (nhbot.value: what we
        wear / wield / need comes last, being worth VALUE_MAX); max_tier < 4: nothing on the body. True if it
        used the turn."""
        if self.bl(nh.NLE_BL_CAP) < 1 and not force:
            return False
        inv = [it for it in self.items() if it.ocls != nh.COIN_CLASS and it.key not in self.cant_drop
               and (max_tier >= 4 or not it.on_body) and not self.sac_carrying(it)]
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
            self.carry_stats["dropped"][4] += 1
            return True
        d = describe(it.ocls, it.text)
        self.drop_units(it.letter, 1 if d["qty"] > 1 else None)
        self.carry_stats["dropped"][2 if self.is_unknown(it.ocls, it.text) else 3] += 1
        return True

    # ------------------------------------------------------------ sell
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
        if self.wish_needed(it):
            return True                      # a lamp to rub, a wand of wishing (nhbot.wishing)
        if self.jewelry_needed(it):
            return True                      # jewelry: identify scrolls, amulets and rings to identify
        if c == nh.WEAPON_CLASS:
            d = describe(c, s)["key"][1]
            if d in ("long sword", "katana") or "Excalibur" in s or any(k in d for k in KEEP_WEAPONS):
                return True                  # wield candidates (weapons.weapon_rank) and missiles we throw
        return False

    def sellables(self, lv, stype):
        buys = SHOP_BUYS.get(stype, set())
        return [(it.letter, it.ocls, it.text) for it in self.items()
                if it.ocls in self.carry_classes() and (buys is ALL or it.ocls in buys)
                and not self.needed(it) and (lv.key, it.text) not in self.sell_tried
                and not it.on_body and not it.alternate and not it.quivered and "unpaid" not in it.text]

    def keep_after_offer(self):
        """read_good: the offer just recorded may show the scroll we are selling is a good one: keep it;
        keep_100: likewise a potion of the 100 group."""
        c, s = self.selling_item
        if c == nh.SCROLL_CLASS and self.scroll_is_good(s):
            self.scroll_stats["kept_good"] = self.scroll_stats.get("kept_good", 0) + 1
            return True                    # the offer just showed it is enchant armor/weapon or remove curse
        if c == nh.POTION_CLASS and self.potion_100(s):
            self.carry_stats["kept_100"] = self.carry_stats.get("kept_100", 0) + 1
            return True                    # the offer just showed it is of the 100 group
        return False

    def carry_shop_greeted(self, lv, stype):
        if lv.key in self.shops_done or not (self.sellables(lv, stype) or self.buy_wanted(stype)):
            return
        self.shopping = {"key": lv.key, "until": self.turn() + 150, "kind": "sell", "stype": stype}

    def carry_sell_step(self, lv):
        stype = self.shopping.get("stype")
        items = self.sellables(lv, stype)
        if not items:
            return False                             # shop_step: buying, or the end of the visit
        y, x = self.pos()
        k = self.kinds(lv)
        door = np.isin(k, [G.DOOR_OPEN, G.DOOR_CLOSED, G.DOORWAY])
        near = door.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                near |= np.roll(np.roll(door, dy, 0), dx, 1)
        if lv.shop[y, x] and not near[y, x]:
            l, c, s = items[0]
            gold0 = self.bl(nh.NLE_BL_GOLD)
            self.selling_item = (c, s)
            self.selling = True
            self.drop_units(l)
            self.selling = False
            got = self.bl(nh.NLE_BL_GOLD) - gold0
            if got > 0:
                self.carry_stats["sold"] += 1
                self.carry_stats["gold"] += got
            else:                                    # not bought: it is still ours, take it back
                self.sell_tried.add((lv.key, s))
                self.carry_stats["kept_back"] += 1
                self.pickup_matching((re.sub(r"^(a|an|the|\d+)\s+", "", re.sub(r"\s*\(.*?\)", "", s)).strip(),),
                                     own=True)
            return True
        targets = lv.shop & ~near
        targets[y, x] = False
        if not targets.any():
            self.shops_done.add(lv.key)
            self.shopping = None
            return False
        if self.walk_to(lv, targets)[0] == "moved":
            return True
        self.shops_done.add(lv.key)          # can't get further in: the visit is over
        self.shopping = None
        return False

    # ------------------------------------------------------------ diggers and shops
    def digger_letters(self):
        return [it.letter for it in self.items() if any(w in it.text for w in DIGGER_WORDS) and not it.held]

    def stash_request(self):
        """shk.c: 'Will you please leave your pick-axe outside?' -- the keeper blocks the way in while one is
        in the open inventory: put it down next to the door, outside the shop (a dwarvish mattock too:
        DIGGER_WORDS)."""
        if self.cur_key is None:
            return
        self.stash_stats["asked"] += 1
        sh = self.shopping                          # the keeper greets and blocks in the same breath
        if sh is None or sh["key"] != self.cur_key:
            self.stash_stats["skipped"] = self.stash_stats.get("skipped", 0) + 1
            return                                   # the greeting found nothing to do in there
        self.stash_pending = (self.cur_key, self.pos())

    def stash_step(self, lv):
        sp = self.stash_pending
        if sp is not None:
            if sp[0] != lv.key or not self.digger_letters():
                self.stash_pending = None
                return False
            door = sp[1]
            k = self.kinds(lv)
            ok = ~lv.shop & ~np.isin(k, [G.DOOR_OPEN, G.DOOR_CLOSED, G.DOORWAY]) & np.isin(k, [G.FLOOR, G.GOLD,
                                                                                            G.OBJECT, G.CORPSE])
            near = np.zeros_like(ok)
            near[max(0, door[0] - 1):door[0] + 2, max(0, door[1] - 1):door[1] + 2] = True
            ok &= near
            here = self.pos()
            if ok[here]:
                self.cur_act = "stash"
                self.drop_units(self.digger_letters()[0])
                if not self.digger_letters():
                    self.stash_stats["stashed"] += 1
                    self.dig_stash = {"key": lv.key, "pos": here, "turn": self.turn()}
                    self.stash_pending = None
                return True
            if self.walk_to(lv, ok, act="stash")[0] == "moved":
                return True
            self.stash_pending = None
            return False
        st = self.dig_stash
        if st is None:
            return False
        if st["key"] != lv.key:
            self.dig_stash = None
            self.stash_stats["lost"] += 1            # left the level without it
            return False
        if self.shop_active(lv) or lv.shop[self.pos()]:
            return False                             # the visit (on since the greeting) is not over
        if self.pos() == st["pos"]:
            self.cur_act = "stash"
            self.pickup_matching(DIGGER_WORDS, own=True)
            self.dig_stash = None
            self.stash_stats["retrieved"] += 1
            return True
        m = np.zeros(lv.under.shape, dtype=bool)
        m[st["pos"]] = True
        if self.walk_to(lv, m)[0] == "moved":
            self.cur_act = "stash"
            return True
        self.dig_stash = None
        self.stash_stats["lost"] += 1
        return False
