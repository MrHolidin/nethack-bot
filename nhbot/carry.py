"""Carry valuables, never be Burdened, sell what we don't use (flag carry).

Pick up: wands, rings, amulets, scrolls, potions (light and worth gold; gold on hand is score 1:1).
carry_all: also tools (not chests, boxes, traps) and armor we won't wear (kept for selling instead of dropped at
once), spellbooks, gems/glass and diggers.

Never Burdened (Burdened costs a quarter of our speed). When the status shows any encumbrance, drop one
unit per turn, in this order:
  1. duplicated unidentified items (same appearance in two slots, or a stack), heaviest first
  2. other unidentified items, heaviest first
  3. anything not worn / wielded, lowest price per weight first
  4. worn / wielded
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
KEEP_WEAPONS = ("dagger", "knife", "dart", "shuriken", "javelin", "spear")   # bot.THROWABLE: thrown, kept
NO_TOOLS = {"pick-axe", "chest", "large box", "ice box", "beartrap", "land mine"}
# carry_all: also spellbooks, gems/glass (not gray stones: a loadstone can't be dropped; not rocks), and diggers
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
SOLD_RE = re.compile(r"You sold .*? for (\d+) gold pieces?")


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
    t = re.sub(r"\s*\(.*?\)", "", s).strip()
    t = re.sub(r"\s+(called|named)\s+.*$", "", t)
    m = re.match(r"^(\d+)\s+", t)
    qty = int(m.group(1)) if m else 1
    t = re.sub(r"^(a|an|the|\d+)\s+", "", t)
    t = re.sub(r"\b(uncursed|cursed|blessed|rustproof|fireproof|corrodeproof|rotted|very|thoroughly|rusty|"
               r"rusted|corroded|burnt|burned|partly eaten|greased|poisoned|diluted)\s+", "", t)
    t = re.sub(r"^[+-]\d+\s+", "", t)
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
        self.carry_stats = {"picked": 0, "dropped": [0, 0, 0, 0, 0], "sold": 0, "gold": 0, "kept_back": 0}
        self.selling = False
        self.sell_tried = set()      # (shop level key, item text) the shopkeeper would not take
        self.stash_pending = None    # (level key, door) -- a shopkeeper asked us to leave the digger outside
        self.dig_stash = None        # dict(key, pos, turn): where we left it
        self.stash_stats = {"asked": 0, "stashed": 0, "retrieved": 0, "lost": 0}
        self.selling_item = (None, "")   # (class, text) of the item on offer
        self.last_drop_qty = None        # units in the last drop (pricemem reads it for a sell offer)

    def carry_all_on(self):
        """carry_all: pick up everything worth carrying -- carry_more (tools, armor) plus spellbooks, gems/glass
        and diggers (pick-axe, mattock: kept, never sold).
        KEEP THIS FLAG (owner's decision, 2026-11-01): A/B -525 n.s., off by default, but it is the way to carry
        a digger for future vault / digging logic. Do not remove it in cleanups."""
        return bool(self.opts.carry_all)

    def carry_classes(self):
        return CARRY_CLASSES + (MORE_CLASSES if self.carry_all_on() else ()) + \
            (nh.WEAPON_CLASS,) + \
            ((nh.SPBOOK_CLASS, nh.GEM_CLASS) if self.carry_all_on() else ())

    # ------------------------------------------------------------ pick up
    def carry_glyph(self, g):
        """Is this remembered glyph an item carry goes for? The SAME test makes it an explore goal and
        makes the step that inspects it (and so removes the goal) run."""
        return bool(CARRY_GLYPH[g] or (self.carry_all_on() and MORE_GLYPH[g])
                    or (WEAPON_GLYPH[g]) or (self.carry_all_on() and ALL_GLYPH[g]))

    def carry_targets(self, lv):
        glyphs = CARRY_GLYPH | MORE_GLYPH if self.carry_all_on() else CARRY_GLYPH
        glyphs = glyphs | WEAPON_GLYPH
        if self.carry_all_on():
            glyphs = glyphs | ALL_GLYPH
        mask = glyphs[lv.under] & ~lv.shop
        for p in self.goal_closed_set("pile", lv.key):
            mask[p] = False
        return mask

    def carry_wanted(self, n):
        """A floor item (look_here text) to take: one of the carried classes, not merchandise."""
        if "for sale" in n:
            return None
        if re.search(r"\b(potion|scroll|ring|wand|amulet)s?\b", n) and "corpse" not in n:
            return re.sub(r"^(a|an|the|\d+)\s+", "", n).strip()
        if "corpse" not in n:
            core = re.sub(r"\s*\(.*?\)", "", n)
            core = re.sub(r"\s+(called|named)\s+.*$", "", core)
            core = re.sub(r"^(a|an|the|\d+)\s+", "", core)
            core = re.sub(r"\b(uncursed|cursed|blessed|rustproof|fireproof|corrodeproof|rotted|very|thoroughly|"
                          r"rusty|rusted|corroded|burnt|burned|greased|poisoned)\s+", "", core)
            core = re.sub(r"^[+-]\d+\s+", "", core).strip()
            one = " ".join(singular(w) for w in core.split(" "))
            if (core in WEAPON_NAME_OF or one in WEAPON_NAME_OF) and " cursed" not in " " + n:
                return core
        if self.carry_all_on():
            a = parse_armor(n)
            if a is not None:
                return a["name"]
            core = re.sub(r"\s*\(.*?\)", "", n)
            core = re.sub(r"^(a|an|the|\d+)\s+", "", core)
            core = re.sub(r"\b(uncursed|cursed|blessed|lit|partly used|rusty|greased)\s+", "", core).strip()
            one = " ".join(singular(w) for w in core.split(" "))
            no_tools = NO_TOOLS - {"pick-axe"} if self.carry_all_on() else NO_TOOLS
            if (core in TOOL_WORDS or one in TOOL_WORDS) and core not in no_tools and one not in no_tools:
                return core
        if self.carry_all_on() and "corpse" not in n:
            core = re.sub(r"\s*\(.*?\)", "", n)
            core = re.sub(r"\s+(called|named)\s+.*$", "", core)
            core = re.sub(r"^(a|an|the|\d+)\s+", "", core)
            core = re.sub(r"\b(uncursed|cursed|blessed)\s+", "", core).strip()
            one = " ".join(singular(w) for w in core.split(" "))
            if "spellbook" in core:
                return core
            if "gray stone" in core:
                return None
            if one.endswith(" gem") or "glass" in one or one in GEM_NAMES or core in GEM_NAMES:
                return core
        return None

    # ------------------------------------------------------------ never Burdened
    def drop_units(self, letter, n=None):
        """Drop n of a stack (all if None); remember the square."""
        s = next((s for l, _, s in self.inventory() if l == letter), "")
        m = re.match(r"^(\d+) ", s)
        self.last_drop_qty = n or (int(m.group(1)) if m else 1)
        self.goal_close("pile", self.level().key, self.pos())      # never come back for what we dropped
        self.press("d", expect_prompt=True)
        if "drop" not in self.message().lower():
            self.settle()
            return
        if n:
            for c in str(n):
                self.raw_step(ord(c))
        self.press(letter)

    def carry_drop_step(self):
        """Encumbered: drop one unit following the four tiers. True if it used the turn."""
        if self.bl(nh.NLE_BL_CAP) < 1:
            return False
        inv = [(l, c, s, describe(c, s)) for l, c, s in self.inventory() if c != nh.COIN_CLASS]
        equipped = lambda s: "being worn" in s or "weapon in hand" in s or "(in use)" in s or "(on " in s
        free = [x for x in inv if not equipped(x[2])]
        keys = {}
        for l, c, s, d in free:
            if d["unid"]:
                keys[d["key"]] = keys.get(d["key"], 0) + d["qty"]
        tier1 = [x for x in free if x[3]["unid"] and keys[x[3]["key"]] > 1]
        tier2 = [x for x in free if x[3]["unid"]]
        tier3 = [x for x in free if not x[3]["unid"]]
        for tier, items, key in ((1, tier1, lambda x: -x[3]["wt"]), (2, tier2, lambda x: -x[3]["wt"]),
                                 (3, tier3, lambda x: (x[3]["cost"] or 0) / x[3]["wt"])):
            if items:
                l, c, s, d = min(items, key=key)
                self.drop_units(l, 1 if d["qty"] > 1 else None)
                self.carry_stats["dropped"][tier] += 1
                return True
        worn = [x for x in inv if equipped(x[2])]
        if worn:
            l, c, s, d = min(worn, key=lambda x: (x[3]["cost"] or 0) / x[3]["wt"])
            if c == nh.ARMOR_CLASS and "being worn" in s:
                a = parse_armor(s) or {"slot": None}
                a["letter"] = l
                if not self.take_off(a):
                    return False
            self.drop_units(l)
            self.carry_stats["dropped"][4] += 1
            return True
        return False

    # ------------------------------------------------------------ sell
    def needed(self, c, s):
        if c == nh.WAND_CLASS and re.search(r"wand of (%s)\b" % "|".join(ATTACK_WANDS), s):
            return True
        if c == nh.POTION_CLASS and any(("potion of " + p) in s or ("potions of " + p) in s for p in HEAL_POTIONS):
            return True
        if c == nh.SCROLL_CLASS \
                and self.scroll_is_good(s):
            return True
        if c == nh.TOOL_CLASS and any(k in s for k in KEEP_TOOLS):
            return True
        if self.carry_all_on() and any(w in s for w in DIGGER_WORDS):
            return True                      # a digger: kept (vaults, ways down), never sold
        if c == nh.WEAPON_CLASS:
            d = describe(c, s)["key"][1]
            if d in ("long sword", "katana") or "Excalibur" in s or any(k in d for k in KEEP_WEAPONS):
                return True                  # wield candidates (valk.weapon_rank) and missiles we throw
        return False

    def sellables(self, lv, stype):
        buys = SHOP_BUYS.get(stype, set())
        return [(l, c, s) for l, c, s in self.inventory()
                if c in self.carry_classes() and (buys is ALL or c in buys) and not self.needed(c, s)
                and (lv.key, s) not in self.sell_tried and "being worn" not in s and "(on " not in s
                and "(weapon in " not in s and "(weapons in " not in s and "(wielded" not in s
                and "alternate weapon" not in s
                and "in quiver" not in s]

    def keep_after_offer(self):
        """read_good: the offer just recorded may show the scroll we are selling is a good one: keep it."""
        c, s = self.selling_item
        if c == nh.SCROLL_CLASS and self.scroll_is_good(s):
            self.scroll_stats["kept_good"] = self.scroll_stats.get("kept_good", 0) + 1
            return True                    # the offer just showed it is enchant armor/weapon or remove curse
        return False

    def carry_shop_greeted(self, lv, stype):
        if lv.key in self.shops_done or not self.sellables(lv, stype):
            return
        self.shopping = {"key": lv.key, "until": self.turn() + 150, "kind": "sell", "stype": stype}

    def carry_sell_step(self, lv):
        stype = self.shopping.get("stype")
        items = self.sellables(lv, stype)
        if not items:
            self.shops_done.add(lv.key)
            self.shopping = None
            return False
        y, x = self.pos()
        k = G.KIND[lv.under]
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
        return self.go_toward_mask(lv, targets)

    # ------------------------------------------------------------ carry_all: diggers and shops
    def digger_letters(self):
        return [l for l, c, s in self.inventory() if any(w in s for w in DIGGER_WORDS)
                and "weapon in" not in s and "(wielded" not in s]

    def stash_request(self):
        """shk.c: 'Will you please leave your pick-axe outside?' -- the keeper blocks the way in while one is
        in the open inventory: put it down next to the door, outside the shop. Always on (with carry): a
        mattock also comes in through the weapons pipeline."""
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
            k = G.KIND[lv.under]
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
            k_mem, k_live = self.kind_grid(lv)
            p = self.passable_grid(lv, k_mem, k_live)
            dist, prev, reached = self.dijkstra(lv, k_mem, k_live, p, here, ok)
            step = self.first_step(prev, here, reached) if reached is not None else None
            if step is None:
                self.stash_pending = None
                return False
            self.cur_act = "stash"
            self.move(step)
            return True
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
        if self.go_toward(lv, st["pos"]):
            self.cur_act = "stash"
            return True
        self.dig_stash = None
        self.stash_stats["lost"] += 1
        return False
