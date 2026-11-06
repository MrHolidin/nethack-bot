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

import nle.nethack as nh

from nhbot.game import MENU_RE
from nhbot.items import base_name, erosion, parse_item

HELM, CLOAK, SUIT, SHIELD, GLOVES, BOOTS, SHIRT = "helm", "cloak", "suit", "shield", "gloves", "boots", "shirt"
TEST_KEEP_ENCH = 3               # strip_for_test: pieces this enchanted or more come off before an untested scroll

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

HEAVY = {"bronze plate mail", "plate mail", "crystal plate mail", "splint mail", "banded mail"}

# unknown enchantment of a floor item: ~79% uncursed (+0 mostly), ~12% cursed (often -1..-3)
UNKNOWN_ENCH = -0.15


def parse_armor(s):
    """Inventory/floor text -> dict(slot, ac, ench, worn, cursed, name) or None."""
    it = parse_item(None, nh.ARMOR_CLASS, s)
    worn, cursed = it.worn, it.cursed
    _, ench, t = base_name(s)
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
            "text": s, "eroded": erosion(s)}


BLESSED_RE = re.compile(r"\bblessed\b")

# A wish (wand of wishing, a djinni from a lamp or a smoky potion, a water demon from a fountain): armor, the first
# of these we don't carry yet -- what the gift experiment found worth most to the bot (AC above all), one per slot.
# zap.c makewish / readobjnam: a wished +2 stays +2 with probability 4/5 (else +0).
ARMOR_WISHES = ("blessed +2 gray dragon scale mail", "blessed +2 gauntlets of power", "blessed +2 speed boots",
                "blessed +2 shield of reflection", "blessed +2 cloak of protection", "blessed +2 dwarvish iron helm")

# objects.c a_can: magic cancellation (mhitu.c: an attack's extra effect lands if rn2(10) >= 3 * MC, MC the best of
# what we wear); suits and cloaks give 1 unless named here, everything else 0
MC_OF = {"cloak of protection": 3, "plate mail": 2, "crystal plate mail": 2, "dwarvish mithril-coat": 2,
         "elven mithril-coat": 2, "oilskin cloak": 2, "slippery cloak": 2, "robe": 2, "leather jacket": 0,
         "cornuthaum": 1}
# cloak_cover: what any cloak is worth beyond its AC -- it takes destroy armor (do_wear.c some_armor: the cloak
# before the suit) and the torso's erosion (uhitm.c erode_armor) for the suit. Counted only against an empty slot
# (every cloak has it); above UNKNOWN_ENCH + the 0.5 of improves, so an AC 0 cloak of unknown enchantment is worn.
CLOAK_COVER = 0.7
MC_VALUE = 1.75          # mc_value: AC a point of MC is worth
# what a worn piece gives that its AC doesn't show: magic resistance, reflection -- PROP_VALUE AC each (mc_value)
PROPS_OF = {"cloak of magic resistance": {"mr"}, "gray dragon scale mail": {"mr"}, "gray dragon scales": {"mr"},
            "shield of reflection": {"refl"}, "polished silver shield": {"refl"},
            "silver dragon scale mail": {"refl"}, "silver dragon scales": {"refl"}}
PROP_VALUE = 3.0


def armor_mc(a):
    return MC_OF.get(a["name"], 1 if a["slot"] in (SUIT, CLOAK) else 0)


def value(a):
    """AC the piece gives: do_wear.c ARM_BONUS = a_ac + spe - min(greatest erosion, a_ac); an unknown
    enchantment counts UNKNOWN_ENCH. (A/B erosion_value: +257 [-298, +877].)"""
    ac = a["ac"] - min(a.get("eroded", 0), a["ac"])
    return ac + (a["ench"] if a["ench"] is not None else UNKNOWN_ENCH)


def enchant_risk(a):
    """read.c seffects: enchant armor evaporates the piece it lands on with probability (spe-1)/spe when spe
    is above 3 (elven armor: above 5; unidentified elven armor counts as plain -- the stricter limit)."""
    return a["ench"] is not None and a["ench"] > (5 if "elven" in a["name"] else 3)


class EquipMixin:
    """Mixed into Bot. Needs: press, raw_step, settle, inventory, obs, messages, tty_text, ..."""

    def equip_init(self):
        self.no_shield = False
        self.no_suit = False
        self.cursed_slots = set()
        self.test_stripped = set()    # strip_for_test: slots taken off before a test read, until worn again
        self.test_strip_refused = set()   # letters of pieces that would not come off
        self.wear_failed = set()
        self.equip_events = []        # (turn, action, name)
        self.start_ac = None
        self.wishes = []              # (turn, what we asked for, what came)
        self.armor_called = {}        # appearance -> type, for armor we wished for ("fencing gloves" -> power)
        self.food_picked = 0

    # ---------------------------------------------------------- inventory view
    def armor_true_text(self, s):
        """Inventory text with the appearance of a type we know (wished for) replaced by the type's name."""
        for look, name in self.armor_called.items():
            if look in s:
                return s.replace(look, name)
        return s

    def armor_inventory(self):
        out = []
        for letter, ocls, s in self.inventory():
            if ocls != nh.ARMOR_CLASS:
                continue
            s = self.armor_true_text(s)
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
        return any(it.two_hands for it in self.items())

    def wear_gain(self, a, worn):
        """What putting a on instead of what we wear in its slot gains: its AC over that one's; mc_value: plus
        MC_VALUE a point of MC the whole outfit gains (MC is the best of what we wear, the other slots as they
        are) and PROP_VALUE for magic resistance / reflection it gains or loses -- the gain of every swap is the
        gain of sum(AC) + MC_VALUE * MC + PROP_VALUE * properties, so swaps can't go round in a circle."""
        cur = worn.get(a["slot"])
        gain = value(a) - (value(cur) if cur is not None else 0)
        if self.opts.cloak_cover and a["slot"] == CLOAK and cur is None:
            gain += CLOAK_COVER
        if self.opts.mc_value:
            others = [armor_mc(w) for s, w in worn.items() if s != a["slot"]]
            mc_with = max(others + [armor_mc(a)])
            mc_now = max(others + ([armor_mc(cur)] if cur is not None else []) + [0])
            gain += MC_VALUE * (mc_with - mc_now)
            have = set().union(*[PROPS_OF.get(w["name"], set()) for s, w in worn.items() if s != a["slot"]])
            if any(it.worn and it.ocls == nh.AMULET_CLASS and "reflection" in it.text for it in self.items()):
                have.add("refl")                  # an amulet of reflection on: a second source adds nothing
            props_with = have | PROPS_OF.get(a["name"], set())
            props_now = have | (PROPS_OF.get(cur["name"], set()) if cur is not None else set())
            gain += PROP_VALUE * (len(props_with) - len(props_now))
        return gain

    def improves(self, a, worn):
        safe = a.get("safe") or self.opts.cloak_cover and a["slot"] == CLOAK   # mummy wrapping, orcish / dwarvish cloak
        if a["slot"] is None or not safe or not self.slot_allowed(a["slot"]):
            return False
        if (a["name"], a.get("letter")) in self.wear_failed:
            return False
        cur = worn.get(a["slot"])
        gain = self.wear_gain(a, worn)
        if cur is None:
            return gain > 0.5
        if cur.get("cursed") or a["slot"] in self.cursed_slots:
            return False
        if abs(gain) <= 0.5 and BLESSED_RE.search(a.get("text", "")) \
                and not BLESSED_RE.search(cur.get("text", "")):
            return True                       # as good, and blessed: resists erosion and a curse (altar test)
        return gain > 0.5

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
            best = max(cands, key=lambda a: self.wear_gain(a, worn))
            self.wear(best, worn)
            return True
        return False                  # armor we won't wear is carried for selling (the value decides drops)

    def strip_for_enchant(self):
        """Before reading enchant armor (no threat in view): the scroll lands on a random worn piece
        (wear.c some_armor), so the pieces it could evaporate come off first, one per call; equip_step puts them
        back on afterwards. "ready": read now; "acted": a piece came off (the turn is used); "wait": not now --
        nothing safe would be left to enchant, or a risky piece can't come off (cursed, a suit under a cloak)."""
        worn = [a for a in self.armor_inventory() if a["worn"]]
        risky = [a for a in worn if enchant_risk(a)]
        if not risky:
            return "ready" if worn else "wait"
        if len(risky) == len(worn):
            return "wait"
        if any(a["cursed"] or a["slot"] in self.cursed_slots or (a["slot"] == SUIT and any(w["slot"] == CLOAK for w in worn))
               for a in risky):
            return "wait"
        self.cur_act = "enchant_strip"
        self.take_off(risky[0])
        return "acted"

    def strip_for_test(self):
        """Before reading an untested scroll (scrolls.read_scroll_step), take off every worn piece enchanted
        +TEST_KEEP_ENCH or more, one per call -- destroy armor can't take it then (a suit under a cloak is safe
        already: the cloak goes first). equip_step puts them back on once the reading is over. True if it used
        the turn."""
        worn = [a for a in self.armor_inventory() if a["worn"]]
        cloak = any(a["slot"] == CLOAK for a in worn)
        for a in worn:
            if a["ench"] is None or a["ench"] < TEST_KEEP_ENCH or (a["slot"] == SUIT and cloak):
                continue
            if self.take_off_for_test(a):
                return True
        return False

    def take_off_for_test(self, a):
        """strip_for_test: take a off unless it can't come off. True if it used the turn."""
        if a["cursed"] or a["slot"] in self.cursed_slots or a["letter"] in self.test_strip_refused:
            return False
        self.cur_act = "test_strip"
        if self.take_off(a):
            self.test_stripped.add(a["slot"])
            self.scroll_stats["test_strip"] = self.scroll_stats.get("test_strip", 0) + 1
        else:
            self.test_strip_refused.add(a["letter"])     # it would not come off: don't try every tick
        return True

    def answer_wish(self):
        """The "For what do you wish?" line is open: ask for the first armor of ARMOR_WISHES we don't carry."""
        have = " | ".join(self.armor_true_text(it.text) for it in self.items())
        want = next((w for w in ARMOR_WISHES if w.split(" ", 2)[2] not in have), ARMOR_WISHES[0])
        for c in want:
            self.raw_step(ord(c))
        self.raw_step(13)
        got = re.match(r"([a-zA-Z]) - (.+?)\.(?:\s|$)", self.message().strip() + " ")
        if got:
            look = re.sub(r"^(pair|set) of ", "", base_name(got.group(2))[2])
            real = want.split(" ", 2)[2]
            if look != real and look not in ARMOR:
                self.armor_called[look] = real          # the game shows its appearance: we know what it is
        self.wishes.append((self.turn(), want, got.group(2) if got else self.message()[:60]))

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
        seq0 = self.msg_seq
        if not self.ask("W", "what do you want to wear"):
            if "even bother" in self.asked:
                self.polyd = True             # a form we failed to notice; cleared by "You return to ... form"
            return
        self.press(a["letter"])
        msgs = self.text_since(seq0)
        if "two-handed" in msgs:
            self.no_shield = True
        now = [x for x in self.armor_inventory() if x["letter"] == a["letter"]]
        if not (now and now[0]["worn"]):
            self.wear_failed.add((a["name"], a["letter"]))
            self.equip_events.append((self.turn(), "fail", a["name"] + " | " + msgs[-80:]))
            return
        self.equip_events.append((self.turn(), "wear", a["name"]))
        if slot in self.test_stripped:
            self.scroll_stats["test_rewear"] = self.scroll_stats.get("test_rewear", 0) + 1
            self.test_stripped.discard(slot)
        # put the cloak back on (it stays in inventory; next equip_step re-wears it anyway)

    def take_off(self, a):
        """Take off a worn item. False if cursed / failed."""
        seq0 = self.msg_seq
        if self.ask("T", "what do you want to take off"):
            self.press(a["letter"])
        msgs = self.text_since(seq0)
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
        self.goal_close("pile", self.level().key, self.pos())
        if self.ask("d", "drop"):
            self.press(letter)

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
                if "Things that are here" in tty:
                    for item in (l.strip() for l in self.menu_lines(tty, "Things that are here")):
                        if not item or item.startswith("--More--") or item.startswith("(end)"):
                            continue
                        names.append(item.replace("--More--", "").strip())
            if self.obs["misc"][2] or "--More--" in tty.replace("\n", "") or MENU_RE.search(tty):
                self.raw_step(13 if "(end)" not in tty else 27)
                continue
            break
        self.settle()
        self.price_note_text(" | ".join(names))
        return names

