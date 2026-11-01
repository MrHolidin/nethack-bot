"""Armor management: decide what to pick up and wear, using only what a human sees.

Identity comes from item text (appearance or identified name), never from the
glyph number (in NLE the glyph leaks the true object type).

Policy (from NetHack wiki guidance, see notes in the chat):
  * wear only armor whose appearance is NOT randomized, i.e. known-mundane;
    randomized helmets/gloves/boots can be opposite-alignment helm, fumbling,
    levitation (mostly cursed) -> skip them unless formally identified as safe.
  * randomized cloaks (tattered cape, opera cloak, ornamental cope, piece of
    cloth) are all useful (protection / invisibility / MR / displacement) -> ok.
  * ~12% of random armor is cursed (often -1); accepted: still nets AC.
  * no shield while wielding a two-handed weapon ("weapon in hands").
"""
import re

import numpy as np
import nle.nethack as nh

HELM, CLOAK, SUIT, SHIELD, GLOVES, BOOTS, SHIRT = "helm", "cloak", "suit", "shield", "gloves", "boots", "shirt"

# name (appearance or identified) -> (slot, base AC)
ARMOR = {}


def _add(slot, ac, *names):
    for n in names:
        ARMOR[n] = (slot, ac)


# helmets (only mundane appearances / safe identified names)
_add(HELM, 1, "elven leather helm", "leather hat", "orcish helm", "iron skull cap", "dented pot",
     "helmet", "helm of brilliance", "helm of telepathy")
_add(HELM, 2, "dwarvish iron helm", "hard hat")
# cloaks
_add(CLOAK, 1, "elven cloak", "faded pall", "oilskin cloak", "slippery cloak", "alchemy smock", "apron",
     "leather cloak", "cloak of invisibility", "cloak of magic resistance", "cloak of displacement",
     "tattered cape", "opera cloak", "ornamental cope", "piece of cloth")
_add(CLOAK, 2, "robe")
_add(CLOAK, 3, "cloak of protection")
# body armor
_add(SUIT, 1, "leather jacket")
_add(SUIT, 2, "leather armor", "orcish ring mail", "crude ring mail")
_add(SUIT, 3, "studded leather armor", "ring mail")
_add(SUIT, 4, "scale mail", "orcish chain mail", "crude chain mail")
_add(SUIT, 5, "chain mail", "elven mithril-coat")
_add(SUIT, 6, "splint mail", "banded mail", "dwarvish mithril-coat", "bronze plate mail")
_add(SUIT, 7, "plate mail", "crystal plate mail")
# shields
_add(SHIELD, 1, "small shield", "Uruk-hai shield", "white-handed shield", "orcish shield", "red-eyed shield")
_add(SHIELD, 2, "elven shield", "blue and green shield", "large shield", "dwarvish roundshield",
     "large round shield", "shield of reflection", "polished silver shield")
# gloves: every appearance is randomized (1 in 4 is fumbling) -> identified names only
_add(GLOVES, 1, "leather gloves", "gauntlets of power", "gauntlets of dexterity")
# boots: mundane appearances + identified safe magic boots
_add(BOOTS, 1, "low boots", "walking shoes", "elven boots", "kicking boots", "speed boots",
     "jumping boots", "water walking boots")
_add(BOOTS, 2, "high boots", "jackboots", "iron shoes", "hard shoes")
# never: fedora, cornuthaum/dunce cap ("conical hat"), helm of opposite alignment, random helmets
# ("plumed/etched/crested/visored helmet"), random gloves/boots, fumble/levitation boots,
# mummy wrapping, orcish/dwarvish cloak (AC 0), shirts (AC 0).

# items we never put on ourselves, but must recognise when worn (they occupy a slot)
UNSAFE = {}
for n in ("fedora", "cornuthaum", "dunce cap", "conical hat"):
    UNSAFE[n] = (HELM, 0)
for n in ("plumed helmet", "etched helmet", "crested helmet", "visored helmet", "helm of opposite alignment",
          "helm of caution"):
    UNSAFE[n] = (HELM, 1)
for n in ("old gloves", "padded gloves", "riding gloves", "fencing gloves", "gauntlets of fumbling"):
    UNSAFE[n] = (GLOVES, 1)
for n in ("combat boots", "jungle boots", "hiking boots", "mud boots", "buckled boots", "riding boots",
          "snow boots", "fumble boots", "levitation boots"):
    UNSAFE[n] = (BOOTS, 1)
for n in ("mummy wrapping", "orcish cloak", "coarse mantelet", "dwarvish cloak", "hooded cloak"):
    UNSAFE[n] = (CLOAK, 0)
for n in ("Hawaiian shirt", "T-shirt"):
    UNSAFE[n] = (SHIRT, 0)

# safe permanent food (no eggs: could be cockatrice; no tins: slow; no unknown corpses)
SAFE_FOOD = ("food ration", "cram ration", "lembas wafer", "K-ration", "C-ration", "fortune cookie",
             "apple", "orange", "pear", "melon", "banana", "carrot", "slime mold", "pancake", "cream pie",
             "candy bar", "lump of royal jelly", "kelp frond", "eucalyptus leaf", "sprig of wolfsbane",
             "clove of garlic", "meatball", "meat stick", "huge chunk of meat", "meat ring",
             "lichen corpse", "lizard corpse")
MAX_FOOD = 6

HEAVY = {"bronze plate mail", "plate mail", "crystal plate mail", "splint mail", "banded mail"}

# unknown enchantment of a floor item: ~79% uncursed (+0 mostly), ~12% cursed (often -1..-3)
UNKNOWN_ENCH = -0.15


def parse_armor(s):
    """Inventory/floor text -> dict(slot, ac, ench, worn, cursed, name) or None."""
    t = s.strip()
    worn = "(being worn)" in t
    t = re.sub(r"\s*\(.*?\)", "", t)
    t = re.sub(r"\s+(called|named)\s+.*$", "", t)
    cursed = bool(re.search(r"\bcursed\b", t)) and "uncursed" not in t
    t = re.sub(r"^(a|an|the|\d+)\s+", "", t)
    t = re.sub(r"\b(uncursed|cursed|blessed|rustproof|fireproof|corrodeproof|rotted|very|thoroughly|"
               r"rusty|rusted|corroded|burnt|burned|partly eaten)\s+", "", t)
    m = re.match(r"^([+-]\d+)\s+", t)
    ench = None
    if m:
        ench = int(m.group(1))
        t = t[m.end():]
    t = re.sub(r"^(pair|set) of ", "", t).strip()
    safe = True
    if t in ARMOR:
        slot, ac = ARMOR[t]
    elif t in UNSAFE:
        (slot, ac), safe = UNSAFE[t], False
    elif t.endswith("dragon scale mail"):
        slot, ac = SUIT, 9
    elif t.endswith("dragon scales"):
        slot, ac = SUIT, 3
    else:
        return None
    return {"slot": slot, "ac": ac, "ench": ench, "worn": worn, "cursed": cursed, "name": t, "safe": safe,
            "text": s}


def value(a):
    return a["ac"] + (a["ench"] if a["ench"] is not None else UNKNOWN_ENCH)


class EquipMixin:
    """Mixed into Bot. Needs: press, raw_step, settle, inventory, obs, messages, tty_text, ..."""

    def equip_init(self):
        self.no_shield = False
        self.no_suit = False
        self.cursed_slots = set()
        self.wear_failed = set()
        self.equip_events = []        # (turn, action, name)
        self.inspected = {}           # level key -> set of positions looked at
        self.start_ac = None
        self.food_picked = 0

    # ---------------------------------------------------------- inventory view
    def armor_inventory(self):
        out = []
        for letter, ocls, s in self.inventory():
            if ocls != nh.ARMOR_CLASS:
                continue
            a = parse_armor(s)
            if a is None:
                # unknown/unsafe armor: track worn status only
                a = {"slot": None, "ac": 0, "ench": None, "worn": "(being worn)" in s,
                     "cursed": False, "name": s, "safe": False}
            a["letter"] = letter
            out.append(a)
        return out

    def worn_by_slot(self, inv=None):
        inv = inv if inv is not None else self.armor_inventory()
        worn = {}
        for a in inv:
            if a["worn"] and a["slot"]:
                worn[a["slot"]] = a
        return worn

    def slot_allowed(self, slot):
        if slot == SHIELD and (self.no_shield or self.two_handed()):
            return False
        if slot == SUIT and self.no_suit:
            return False
        return True

    def two_handed(self):
        return any("(weapon in hands)" in s for _, _, s in self.inventory())

    def improves(self, a, worn):
        if a["slot"] is None or not a.get("safe") or not self.slot_allowed(a["slot"]):
            return False
        if (a["name"], a.get("letter")) in self.wear_failed:
            return False
        cur = worn.get(a["slot"])
        if cur is None:
            return value(a) > 0.5
        if cur.get("cursed") or a["slot"] in self.cursed_slots:
            return False
        return value(a) > value(cur) + 0.5

    # ---------------------------------------------------------- main hook
    def equip_step(self, lv):
        """Called when no hostiles are visible. Returns True if it used the turn."""
        if self.polyd or self.handless():
            return False                      # do_wear.c: very small / handless forms can't ("Don't even bother.")
        inv = self.armor_inventory()
        worn = self.worn_by_slot(inv)
        # 1) wear something better we already carry
        cands = [a for a in inv if not a["worn"] and self.improves(a, worn)]
        if cands:
            best = max(cands, key=lambda a: value(a) - (value(worn[a["slot"]]) if a["slot"] in worn else 0))
            self.wear(best, worn)
            return True
        # 2) drop carried armor we will never wear (weight)
        junk = [] if self.carry_all_on() else [a for a in inv if not a["worn"]]
        if junk:
            self.drop_letter(junk[0]["letter"])
            return True
        return False

    # ---------------------------------------------------------- actions
    def wear(self, a, worn):
        slot = a["slot"]
        # body armor goes under the cloak
        if slot == SUIT and CLOAK in worn:
            if not self.take_off(worn[CLOAK]):
                self.no_suit = True
                return
        if slot in worn:
            if not self.take_off(worn[slot]):
                self.cursed_slots.add(slot)
                return
        self.press("W", expect_prompt=True)
        if "what do you want to wear" not in self.message().lower():
            if "even bother" in self.message().lower():
                self.polyd = True             # a form we failed to notice; cleared by "You return to ... form"
            self.settle()
            return
        self.press(a["letter"])
        msgs = " ".join(m for _, m in list(self.messages)[-4:])
        if "two-handed" in msgs:
            self.no_shield = True
        now = [x for x in self.armor_inventory() if x["letter"] == a["letter"]]
        if not (now and now[0]["worn"]):
            self.wear_failed.add((a["name"], a["letter"]))
            self.equip_events.append((self.turn(), "fail", a["name"] + " | " + msgs[-80:]))
            return
        self.equip_events.append((self.turn(), "wear", a["name"]))
        # put the cloak back on (it stays in inventory; next equip_step re-wears it anyway)

    def take_off(self, a):
        """Take off a worn item. False if cursed / failed."""
        n_worn = sum(1 for x in self.armor_inventory() if x["worn"])
        self.press("T", expect_prompt=True)
        if "what do you want to take off" in self.message().lower():
            self.press(a["letter"])
        elif n_worn > 1:
            self.settle()
        else:
            self.settle()
        msgs = " ".join(m for _, m in list(self.messages)[-4:])
        if "cursed" in msgs and "You can't" in msgs:
            self.cursed_slots.add(a["slot"])
            return False
        still = [x for x in self.armor_inventory() if x["letter"] == a["letter"] and x["worn"]]
        if still:
            return False
        self.equip_events.append((self.turn(), "takeoff", a["name"]))
        return True

    def drop_letter(self, letter):
        s = next((s for l, _, s in self.inventory() if l == letter), "")
        m = re.match(r"^(\d+) ", s)
        self.last_drop_qty = int(m.group(1)) if m else 1
        if self.carry_on():                     # carry: never come back for what we dropped
            self.dropped_at.add((self.level().key, self.pos()))
            self.inspected.setdefault(self.level().key, set()).add(self.pos())
        self.press("d", expect_prompt=True)
        if "drop" in self.message().lower():
            self.press(letter)
        else:
            self.settle()

    # ---------------------------------------------------------- floor items
    def look_here(self):
        """Names of items on our square (':' look), without consuming a turn."""
        self.raw_step(ord(":"))
        names = []
        for _ in range(20):
            tty = self.tty_text()
            msg = self.message()
            m = re.search(r"You (?:see|feel) here (.+?)\.", msg) or re.search(r"You (?:see|feel) here (.+?)\.", tty.replace("\n", " "))
            if m:
                names.append(m.group(1))
            if "Things that are here" in tty or "There are several objects here" in tty:
                lines = tty.split("\n")
                start = next((i for i, l in enumerate(lines) if "Things that are here" in l), None)
                if start is not None:
                    col = lines[start].index("Things that are here")
                    for l in lines[start + 1:]:
                        item = l[col:].strip() if len(l) > col else ""
                        if not item or item.startswith("--More--") or item.startswith("(end)"):
                            continue
                        names.append(item.replace("--More--", "").strip())
            if self.obs["misc"][2] or "--More--" in tty.replace("\n", "") or re.search(r"\(end\)|\(\d+ of \d+\)", tty):
                self.raw_step(13 if "(end)" not in tty else 27)
                continue
            break
        self.settle()
        self.price_note_text(" | ".join(names))
        return names

    def food_count(self):
        return sum(1 for _, ocls, _ in self.inventory() if ocls == nh.FOOD_CLASS)

    def food_wanted(self, name):
        if not self.opts.use_food or self.food_count() >= MAX_FOOD:
            return False
        if "egg" in name or re.search(r"\btins?\b", name):
            return False
        if "partly eaten" in name:
            return False
        return any(f in name for f in SAFE_FOOD)

    def armor_pickup_here(self, lv):
        key = lv.key
        insp = self.inspected.setdefault(key, set())
        insp.add(self.pos())
        self.goal_done("pile", lv, self.pos())
        names = self.look_here()
        if self.shop_visits_on():
            # never take merchandise (a lone item is picked up without a menu, so filter here)
            names = [n for n in names if "for sale" not in n]
        worn = self.worn_by_slot()
        want = []
        for n in names:
            a = parse_armor(n) if self.opts.use_armor else None
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
        cap_before = self.bl(nh.NLE_BL_CAP)
        self.pickup_matching(want)
        if self.bl(nh.NLE_BL_CAP) > cap_before and not self.carry_on():   # (carry: its own drop order)
            for a in self.armor_inventory():
                if not a["worn"]:
                    self.drop_letter(a["letter"])
                    break
        self.equip_events.append((self.turn(), "pickup", ",".join(want)))
        return True

    def armor_targets(self, lv, glyphs_mod):
        """Mask of remembered '[' (and '%' food when low on food) piles not yet inspected."""
        mask = glyphs_mod.ARMOR_GLYPH[lv.under] if self.opts.use_armor else np.zeros(lv.under.shape, bool)
        if self.opts.use_food and self.food_count() < MAX_FOOD:
            mask = mask | glyphs_mod.FOOD_GLYPH[lv.under]
        for p in self.inspected.get(lv.key, ()):
            mask[p] = False
        return mask
