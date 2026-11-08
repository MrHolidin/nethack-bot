"""Armor management: decide what to pick up and wear, using only what a human sees.

Identity comes from item text (appearance or identified name), never from the
glyph number (in NLE the glyph leaks the true object type).

Policy (from NetHack wiki guidance):
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

from nhbot.items import base_name, erosion, parse_item
from nhbot.pricemem import ARMOR_APPEAR

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
# the shuffled helmet / gloves / boots appearances (pricemem.ARMOR_APPEAR; the cloaks are in ARMOR): the slot and
# AC of their group's first type
UNSAFE = {look: ARMOR[types[0]] for look, types in ARMOR_APPEAR.items() if look not in ARMOR}
for n in ("fedora", "cornuthaum", "dunce cap", "conical hat"):
    UNSAFE[n] = (HELM, 0)
for n in ("helm of opposite alignment", "helm of caution"):
    UNSAFE[n] = (HELM, 1)
UNSAFE["gauntlets of fumbling"] = (GLOVES, 1)
for n in ("fumble boots", "levitation boots"):
    UNSAFE[n] = (BOOTS, 1)
for n in ("mummy wrapping", "orcish cloak", "coarse mantelet", "dwarvish cloak", "hooded cloak"):
    UNSAFE[n] = (CLOAK, 0)
for n in ("Hawaiian shirt", "T-shirt"):
    UNSAFE[n] = (SHIRT, 0)

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
UNCURSED_RE = re.compile(r"\b(?:uncursed|blessed)\b")

# A wish (wand of wishing, a djinni from a lamp or a smoky potion, a water demon from a fountain): armor, the first
# of these we don't carry yet -- what the gift experiment found worth most to the bot (AC above all), one per slot.
# zap.c makewish / readobjnam: a wished +2 stays +2 with probability 4/5 (else +0).
ARMOR_WISHES = ("blessed +2 gray dragon scale mail", "blessed +2 gauntlets of power", "blessed +2 speed boots",
                "blessed +2 shield of reflection", "blessed +2 cloak of protection", "blessed +2 dwarvish iron helm")

# what any cloak is worth beyond its AC -- it takes destroy armor (do_wear.c some_armor: the cloak before the suit)
# and the torso's erosion (uhitm.c erode_armor) for the suit. Counted only against an empty slot (every cloak has
# it); above UNKNOWN_ENCH + the 0.5 of improves, so an AC 0 cloak of unknown enchantment is worn. With it a mummy
# wrapping / orcish / dwarvish cloak known uncursed or blessed is worn too (cover_cloak_ok). A/B cloak_cover
# "uncursed" +862 [-5, +1787] (any of those cloaks, curse status unknown too: +662 [-678, +1971]).
CLOAK_COVER = 0.7
MC_VALUE = 1.75          # mc_value: AC a point of MC is worth
# what a worn piece gives that its AC doesn't show: magic resistance, reflection -- PROP_VALUE AC each (mc_value)
PROPS_OF = {"cloak of magic resistance": {"mr"}, "gray dragon scale mail": {"mr"}, "gray dragon scales": {"mr"},
            "shield of reflection": {"refl"}, "polished silver shield": {"refl"},
            "silver dragon scale mail": {"refl"}, "silver dragon scales": {"refl"}}
PROP_VALUE = 3.0


# objects.c a_can: magic cancellation (mhitu.c: an attack's extra effect lands if rn2(10) >= 3 * MC) of every armor
# with one (all others 0 -- dragon scales and dragon scale mail too: DRGN_ARMR passes can 0, objects.c:373-375), by
# name and by the appearances fixed to one type; a shuffled appearance by the least of its group (the four random
# cloaks: cloak of protection 3, the others 1; mhitu.c:869 magic_negation: the best a_can of what we wear -- a cloak
# of protection's extrinsic Protection keeps it at 3)
# (A/B dragon_mc: +57 [-15, +133], median 7726 -> 7726, 4 of 1000 changed)
MC_CAN = {"cornuthaum": 1, "plate mail": 2, "crystal plate mail": 2, "bronze plate mail": 1, "splint mail": 1,
          "banded mail": 1, "dwarvish mithril-coat": 2, "elven mithril-coat": 2, "chain mail": 1, "orcish chain mail": 1,
          "scale mail": 1, "studded leather armor": 1, "ring mail": 1, "orcish ring mail": 1, "leather armor": 1,
          "mummy wrapping": 1, "elven cloak": 1, "orcish cloak": 1, "dwarvish cloak": 1, "oilskin cloak": 2, "robe": 2,
          "alchemy smock": 1, "leather cloak": 1, "cloak of protection": 3, "cloak of invisibility": 1,
          "cloak of magic resistance": 1, "cloak of displacement": 1,
          "crude chain mail": 1, "crude ring mail": 1, "faded pall": 1, "coarse mantelet": 1, "hooded cloak": 1,
          "slippery cloak": 2, "apron": 1,
          "tattered cape": 1, "opera cloak": 1, "ornamental cope": 1, "piece of cloth": 1}


def armor_mc(a):
    """MC of a worn piece: objects.c's (MC_CAN)."""
    return MC_CAN.get(a["name"], 0)


# the helmets, shields, gloves and boots that burn (mkobj.c:1705 is_flammable: material up to WOOD, not LIQUID --
# objects.c:339-528 leather, cloth, wood), by name and fixed appearance; a shuffled appearance by the share of its
# group that burns (o_init.c: the four gloves 3 of 4 leather, the seven magic boots 6 of 7)
FLAMMABLE = {"elven leather helm": 1.0, "leather hat": 1.0, "fedora": 1.0, "cornuthaum": 1.0, "dunce cap": 1.0,
             "conical hat": 1.0, "small shield": 1.0, "elven shield": 1.0, "blue and green shield": 1.0,
             "leather gloves": 1.0, "gauntlets of fumbling": 1.0, "gauntlets of dexterity": 1.0,
             "old gloves": 0.75, "padded gloves": 0.75, "riding gloves": 0.75, "fencing gloves": 0.75,
             "low boots": 1.0, "walking shoes": 1.0, "high boots": 1.0, "jackboots": 1.0, "speed boots": 1.0,
             "water walking boots": 1.0, "jumping boots": 1.0, "elven boots": 1.0, "fumble boots": 1.0,
             "levitation boots": 1.0, "combat boots": 6 / 7, "jungle boots": 6 / 7, "hiking boots": 6 / 7,
             "mud boots": 6 / 7, "buckled boots": 6 / 7, "riding boots": 6 / 7, "snow boots": 6 / 7}


def value(a):
    """AC the piece gives: do_wear.c ARM_BONUS = a_ac + spe - min(greatest erosion, a_ac); an unknown
    enchantment counts UNKNOWN_ENCH. (A/B erosion_value: +257 [-298, +877].)"""
    ac = a["ac"] - min(a.get("eroded", 0), a["ac"])
    return ac + (a["ench"] if a["ench"] is not None else UNKNOWN_ENCH)


def enchant_risk(a):
    """read.c seffects: enchant armor evaporates the piece it lands on with probability (spe-1)/spe when spe
    is above 3 (elven armor: above 5; unidentified elven armor counts as plain -- the stricter limit)."""
    return a["ench"] is not None and a["ench"] > (5 if "elven" in a["name"] else 3)


class EquipState:
    """State of armor: worn pieces, failures, wishes (EquipMixin)."""
    def __init__(self):
        self.no_shield = False
        self.no_suit = False
        self.cursed_slots = set()
        self.test_stripped = set()    # strip_for_test: slots taken off before a test read, until worn again
        self.test_strip_refused = set()   # letters of pieces that would not come off
        self.wear_failed = set()
        self.events = []              # (turn, action, name)
        self.wishes = []              # (turn, what we asked for, what came)
        self.armor_called = {}        # appearance -> type, for armor we wished for ("fencing gloves" -> power)


class EquipMixin:
    """Mixed into Bot. Needs: press, raw_step, settle, inventory, obs, messages, tty_text, ..."""

    def equip_init(self):
        self.equip = EquipState()

    # ---------------------------------------------------------- inventory view
    def armor_true_text(self, s):
        """Inventory text with the appearance of a type we know (wished for) replaced by the type's name."""
        for look, name in self.equip.armor_called.items():
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

    def our_mc(self):
        """mhitu.c:869-912 magic_negation for us: the best a_can of the armor we wear (armor_mc); a ring of
        protection on (extrinsic Protection) adds 1, up to 3; else the protection a temple priest gave us (intrinsic,
        u.ublessed > 0) makes it at least 1."""
        mc = max((armor_mc(a) for a in self.armor_inventory() if a["worn"]), default=0)
        if any(i.ring_on and "ring of protection" in i.text for i in self.items()):
            return min(mc + 1, 3)
        return max(mc, 1) if self.altar.prot_bought > 0 else mc

    def burn_body_prob(self):
        """P(trap.c:56-129 burnarmor reports a body hit -- what lets a fire ray at us go on to our pack, zap.c:3790):
        each round it picks one of five spots; the body (the cloak / suit / shirt) ends it TRUE, a worn helmet,
        shield, gloves or boots that burns (FLAMMABLE; not thoroughly burnt or known fireproof: trap.c:204, 230
        erode_obj gives ER_NOTHING and it picks again; blessed: spared 1 in 4, trap.c:210 rnl(4)) ends it FALSE --
        1 / (1 + the burnable pieces)."""
        k = 0.0
        for a in self.armor_inventory():
            if not a["worn"] or a["slot"] not in (HELM, SHIELD, GLOVES, BOOTS):
                continue
            t = a.get("text", "")
            if "thoroughly burnt" in t or "fireproof" in t:
                continue
            k += FLAMMABLE.get(a["name"], 0.0) * (0.75 if BLESSED_RE.search(t) else 1.0)
        return 1 / (1 + k)

    def worn_by_slot(self, inv=None):
        inv = inv if inv is not None else self.armor_inventory()
        worn = {}
        for a in inv:
            if a["worn"] and a["slot"]:
                worn[a["slot"]] = a
        return worn

    def slot_allowed(self, slot):
        if slot == SHIELD and (self.equip.no_shield or self.two_handed()):
            return False
        if slot == SUIT and self.equip.no_suit:
            return False
        return True

    def two_handed(self):
        return any(it.two_hands for it in self.items())

    def wear_gain(self, a, worn):
        """What putting a on instead of what we wear in its slot gains: its AC over that one's; plus
        MC_VALUE a point of MC the whole outfit gains (MC is the best of what we wear, the other slots as they
        are) and PROP_VALUE for magic resistance / reflection it gains or loses -- the gain of every swap is the
        gain of sum(AC) + MC_VALUE * MC + PROP_VALUE * properties, so swaps can't go round in a circle."""
        cur = worn.get(a["slot"])
        gain = value(a) - (value(cur) if cur is not None else 0)
        if a["slot"] == CLOAK and cur is None:
            gain += CLOAK_COVER
        # magic cancellation and magic resistance / reflection count (A/B mc_v1 +289 [-191, +792])
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

    def cover_cloak_ok(self, a):
        """A mummy wrapping / orcish / dwarvish cloak may be worn when known uncursed or blessed -- objnam.c
        always names "uncursed" on armor whose curse status we know (CLOAK_COVER)."""
        return a["slot"] == CLOAK and bool(UNCURSED_RE.search(a.get("text", "")))

    def improves(self, a, worn):
        safe = a.get("safe") or self.cover_cloak_ok(a)
        if a["slot"] is None or not safe or not self.slot_allowed(a["slot"]):
            return False
        if (a["name"], a.get("letter")) in self.equip.wear_failed:
            return False
        cur = worn.get(a["slot"])
        gain = self.wear_gain(a, worn)
        if cur is None:
            return gain > 0.5
        if cur.get("cursed") or a["slot"] in self.equip.cursed_slots:
            return False
        if abs(gain) <= 0.5 and BLESSED_RE.search(a.get("text", "")) \
                and not BLESSED_RE.search(cur.get("text", "")):
            return True                       # as good, and blessed: resists erosion and a curse (altar test)
        return gain > 0.5

    # ---------------------------------------------------------- main hook
    def equip_step(self, lv):
        """Called when no hostiles are visible. Returns True if it used the turn."""
        if self.thief.polyd or self.handless():
            return False                      # do_wear.c: very small / handless forms can't ("Don't even bother.")
        inv = self.armor_inventory()
        worn = self.worn_by_slot(inv)
        # wear something better we already carry
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
        if any(a["cursed"] or a["slot"] in self.equip.cursed_slots or (a["slot"] == SUIT and any(w["slot"] == CLOAK for w in worn))
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
        if a["cursed"] or a["slot"] in self.equip.cursed_slots or a["letter"] in self.equip.test_strip_refused:
            return False
        self.cur_act = "test_strip"
        if self.take_off(a):
            self.equip.test_stripped.add(a["slot"])
            self.scroll_stat("test_strip")
        else:
            self.equip.test_strip_refused.add(a["letter"])     # it would not come off: don't try every tick
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
                self.equip.armor_called[look] = real          # the game shows its appearance: we know what it is
        self.equip.wishes.append((self.turn(), want, got.group(2) if got else self.message()[:60]))

    # ---------------------------------------------------------- actions
    def wear(self, a, worn):
        slot = a["slot"]
        # body armor goes under the cloak
        if slot == SUIT and CLOAK in worn:
            if not self.take_off(worn[CLOAK]):
                self.equip.no_suit = True
                return
        if slot in worn:
            if not self.take_off(worn[slot]):
                self.equip.cursed_slots.add(slot)
                return
        seq0 = self.msg_seq
        if not self.ask("W", "what do you want to wear"):
            if "even bother" in self.asked:
                self.poly_unnoticed()
            return
        self.press(a["letter"])
        msgs = self.text_since(seq0)
        if "two-handed" in msgs:
            self.equip.no_shield = True
        now = [x for x in self.armor_inventory() if x["letter"] == a["letter"]]
        if not (now and now[0]["worn"]):
            self.equip.wear_failed.add((a["name"], a["letter"]))
            self.equip.events.append((self.turn(), "fail", a["name"] + " | " + msgs[-80:]))
            return
        self.equip.events.append((self.turn(), "wear", a["name"]))
        if slot in self.equip.test_stripped:
            self.scroll_stat("test_rewear")
            self.equip.test_stripped.discard(slot)
        # put the cloak back on (it stays in inventory; next equip_step re-wears it anyway)

    def equip_event(self, kind, what):
        """Log an event (a pickup) beside the wear / fail / takeoff ones of the equipment summary."""
        self.equip.events.append((self.turn(), kind, what))

    def take_off(self, a):
        """Take off a worn item. False if cursed / failed."""
        seq0 = self.msg_seq
        if self.ask("T", "what do you want to take off"):
            self.press(a["letter"])
        msgs = self.text_since(seq0)
        if "cursed" in msgs and "You can't" in msgs:
            self.equip.cursed_slots.add(a["slot"])
            return False
        still = [x for x in self.armor_inventory() if x["letter"] == a["letter"] and x["worn"]]
        if still:
            return False
        self.equip.events.append((self.turn(), "takeoff", a["name"]))
        return True
