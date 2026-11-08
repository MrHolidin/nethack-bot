"""Inventory items: one parse of each inventory line, so every module reads the same state.

The state suffixes are exactly what NetHack 3.6.6 writes (objnam.c doname_base):
  wielded      " (weapon in hand)", " (weapon in hands)" (two-handed), " (tethered weapon in hand)" (aklys),
               " (weapon in claw)" etc. when polymorphed; a wielded stack: " (wielded)"
  off-hand     " (wielded in other hand)"            two-weapon combat
  alternate    " (alternate weapon; not wielded)"
  quiver       " (in quiver)", " (in quiver pouch)" (ammo), " (at the ready)" (anything else)
  worn         " (being worn)" armor, amulet, blindfold / towel; " (embedded in your skin)" dragon scales
  ring         " (on left hand)", " (on right hand)"
  lit          " (lit)" lamps, candles, oil
There is no "(in use)" and no "(weapons in hands)" in 3.6.6.
"""
import re
from dataclasses import dataclass
from functools import lru_cache

import nle.nethack as nh

WIELD_RE = re.compile(r"\((?:tethered )?weapon in (\w+)")
CURSED_RE = re.compile(r"\bcursed\b")               # not "uncursed"
WAND_SPENT_RE = re.compile(r"\(\d+:(?:0|-1)\)")     # a wand known to have no charges (-1: cancelled)


@dataclass(frozen=True)
class Item:
    letter: str
    ocls: int
    text: str
    wield: str = None        # "hand": the wielded weapon; "stack": a wielded stack; "other": two-weapon off-hand
    two_hands: bool = False  # wielded in both hands (a two-handed weapon)
    alternate: bool = False
    quivered: bool = False
    worn: bool = False       # armor, amulet, blindfold / towel
    ring_on: bool = False
    lit: bool = False
    cursed: bool = False     # known cursed

    @property
    def key(self):
        """Identity for 'don't try again' memories: the letter with the text minus its state suffixes (a
        letter alone is reused by the next item we pick up; the suffixes change while it stays the same item,
        e.g. a wand's charges once known)."""
        return self.letter, re.sub(r"\s*\(.*?\)", "", self.text).strip()

    @property
    def wielded(self):
        """In our hands as the weapon (uwep)."""
        return self.wield in ("hand", "stack")

    @property
    def held(self):
        """Wielded in either hand."""
        return self.wield is not None

    @property
    def on_body(self):
        """Can't be dropped / thrown / sold without taking it off or unwielding it first."""
        return self.wield is not None or self.worn or self.ring_on


def parse_item(letter, ocls, s):
    m = WIELD_RE.search(s)
    if m:
        wield = "hand"
    elif "(wielded in other " in s:
        wield = "other"
    elif "(wielded)" in s:
        wield = "stack"
    else:
        wield = None
    return Item(letter=letter, ocls=ocls, text=s, wield=wield,
                two_hands=bool(m) and m.group(1).endswith("s"),
                alternate="(alternate weapon" in s,
                quivered="(in quiver" in s or "(at the ready)" in s,
                worn="(being worn)" in s or "(embedded in your skin)" in s,
                ring_on="(on left " in s or "(on right " in s,
                lit="(lit)" in s,
                cursed=bool(CURSED_RE.search(s)))


# ---------------------------------------------------------------- names
# Words NetHack 3.6.6 puts in front of an object's name (objnam.c doname_base / xname / add_erosion_words):
# containers "empty", "broken" / "locked" / "unlocked"; candles "partly used"; food "partly eaten";
# BUC; "greased"; "poisoned"; erosion (very / thoroughly) rusty | burnt, corroded | rotted;
# erodeproof fixed | rustproof | corrodeproof | fireproof; potions "diluted". Then the enchantment.
PREFIX_WORDS = ("empty", "broken", "locked", "unlocked", "partly used", "partly eaten", "uncursed", "cursed",
                "blessed", "greased", "poisoned", "very", "thoroughly", "rusty", "burnt", "corroded", "rotted",
                "fixed", "rustproof", "corrodeproof", "fireproof", "diluted")
PREFIX_RE = re.compile(r"^(?:%s)\s+" % "|".join(sorted(PREFIX_WORDS, key=len, reverse=True)))


EROSION_RE = re.compile(r"\b(?:(very|thoroughly) )?(?:rusty|burnt|corroded|rotted)\b")


def erosion(s):
    """Greatest erosion (objnam.c add_erosion_words: 1 plain, 2 "very", 3 "thoroughly") of the two kinds."""
    return max((3 if m.group(1) == "thoroughly" else 2 if m.group(1) else 1 for m in EROSION_RE.finditer(s)),
               default=0)


@lru_cache(maxsize=1 << 16)
def base_name(s, called=False):
    """Inventory / floor text -> (quantity, enchantment or None, bare name): no state suffixes, article or
    count, prefix words, enchantment; no 'called' / 'named' part unless called. A function of the text
    alone, and the same texts come back every tick: cached (a quarter of the run time went here)."""
    t = re.sub(r"\s*\(.*?\)", "", s).strip()
    if not called:
        t = re.sub(r"\s+(called|named)\s+.*$", "", t)
    m = re.match(r"^(\d+)\s+", t)
    qty = int(m.group(1)) if m else 1
    t = re.sub(r"^(a|an|the|some|\d+)\s+", "", t)
    while True:
        t2 = PREFIX_RE.sub("", t)
        if t2 == t:
            break
        t = t2
    ench = None
    m = re.match(r"^([+-]\d+)\s+", t)
    if m:
        ench = int(m.group(1))
        t = t[m.end():]
    return qty, ench, t.strip()


# ---------------------------------------------------------------- plural names (name_parse)
# objnam.c makeplural (objnam.c:2328) -- what xname does to a name for a stack of more than one -- and its tables
# (objnam.c:2149-2196 one_off / as_is, 2283 singplur_compound, 2622 badman). singular_name inverts it over the
# names the game uses: of the singulars whose makeplural is the text, the object / monster name.
ONE_OFF = (("child", "children"), ("cubus", "cubi"), ("culus", "culi"), ("djinni", "djinn"), ("erinys", "erinyes"),
           ("foot", "feet"), ("fungus", "fungi"), ("goose", "geese"), ("knife", "knives"), ("labrum", "labra"),
           ("louse", "lice"), ("mouse", "mice"), ("mumak", "mumakil"), ("nemesis", "nemeses"), ("ovum", "ova"),
           ("ox", "oxen"), ("passerby", "passersby"), ("rtex", "rtices"), ("serum", "sera"), ("staff", "staves"),
           ("tooth", "teeth"))
AS_IS = ("boots", "shoes", "gloves", "lenses", "scales", "eyes", "gauntlets", "iron bars", "bison", "deer", "elk",
         "fish", "fowl", "tuna", "yaki", "-hai", "krill", "manes", "moose", "ninja", "sheep", "ronin", "roshi",
         "shito", "tengu", "ki-rin", "Nazgul", "gunyoki", "piranha", "samurai", "shuriken")
COMPOUNDS = (" of ", " labeled ", " called ", " named ", " above", " versus ", " from ", " in ", " on ", " a la ",
             " with", " de ", " d'", " du ", "-in-", "-at-")
NO_MEN = ("albu", "antihu", "anti", "ata", "auto", "bildungsro", "cai", "cay", "ceru", "corner", "decu", "des", "dura",
          "fir", "hanu", "het", "infrahu", "inhu", "nonhu", "otto", "out", "prehu", "protohu", "subhu", "superhu",
          "talis", "unhu", "sha", "hu", "un", "le", "re", "so", "to", "at", "a")
VOWELS = "aeiou"


def _badman(base):
    """objnam.c badman, to plural: a *man word without a *men plural (human, shaman)."""
    if len(base) < 4:
        return False
    low = base.lower()
    for p in NO_MEN:
        start = len(low) - (len(p) + 3)
        if start >= 0 and low[start:start + len(p)] == p and (start == 0 or low[start - 1] == " "):
            return True
    return False


def _compound_at(s):
    low = s.lower()
    hits = [i for i in (low.find(c) for c in COMPOUNDS) if i >= 0]
    return min(hits) if hits else -1


def makeplural(name):
    """objnam.c:2328 makeplural (the cases of our object and monster names)."""
    s = name.strip()
    if s.lower().startswith("pair of "):
        return s
    at = _compound_at(s)
    head, excess = (s[:at], s[at:]) if at >= 0 else (s, "")
    head = head.rstrip()
    low = head.lower()
    n = len(head)
    if n == 1 or not head[-1].isalpha():
        return head + "'s" + excess
    if low.endswith("ae") or low.endswith("matzot") or low == "ya" or low.endswith(" ya"):
        return head + excess
    for a in AS_IS:
        if low.endswith(a.lower()):
            return head + excess
    if n > 5 and low.endswith("craft"):
        return head + excess
    if low in ("slice", "mongoose"):
        return head + "s" + excess
    if n > 2 and low.endswith("ox") and not (n > 5 and low.endswith("muskox")):
        return head + "es" + excess
    if n > 2 and low.endswith("man") and _badman(head):
        return head + "s" + excess
    for sing, plur in ONE_OFF:
        if low.endswith(plur):
            return head + excess
        if low.endswith(sing):
            return head[:-len(sing)] + plur + excess
    if n >= 3 and low.endswith("man"):
        return head[:-2] + "en" + excess
    if low[-1] == "f" and not (n >= 3 and low.endswith("erf")) and n >= 2 and (low[-2] in "lr" or low[-2] in VOWELS):
        return head[:-1] + "ves" + excess
    if n >= 3 and low.endswith("ium"):
        return head[:-2] + "a" + excess
    if low.endswith(("alga", "hypha", "larva", "amoeba", "vertebra")):
        return head + "e" + excess
    if n > 3 and low.endswith("us") and not low.endswith(("lotus", "wumpus")):
        return head[:-2] + "i" + excess
    if n >= 3 and low.endswith("sis"):
        return head[:-2] + "es" + excess
    if n >= 6 and low.endswith(("matzoh", "matzah")):
        return head[:-2] + "ot" + excess
    if n >= 5 and low.endswith(("matzo", "matza")):
        return head[:-1] + "ot" + excess
    if n >= 5 and low.endswith(("dex", "dix", "tex")) and not low.endswith("index"):
        return head[:-2] + "ices" + excess
    if low[-1] in "zxs" or (n >= 2 and low[-1] == "h" and low[-2] in "cs"
                            and not (n >= 4 and ((low[-3] == "e" and low[-4] in "mt")
                                                 or (low[-3] == "o" and low[-4] in "lp")))) \
            or (n >= 4 and low.endswith("ato")) or (n >= 5 and low.endswith("dingo")):
        return head + "es" + excess
    if low[-1] == "y" and n >= 2 and low[-2] not in VOWELS:
        return head[:-1] + "ies" + excess
    return head + "s" + excess


_NAMES = set()
for _i in range(nh.NUM_OBJECTS):
    _oc = nh.objclass(_i)
    for _w in (nh.OBJ_NAME(_oc), nh.OBJ_DESCR(_oc)):
        if _w:
            _NAMES.add(_w)
MONSTER_NAMES = {nh.permonst(_i).mname for _i in range(nh.NUMMONS)}
_NAMES |= MONSTER_NAMES | {m + " corpse" for m in MONSTER_NAMES} | {m + " egg" for m in MONSTER_NAMES}
_NOUNS = ("potion", "scroll", "ring", "wand", "amulet", "spellbook", "gem", "stone", "corpse", "egg", "tin", "glass",
          "figurine", "statue", "pair", "set")
_WORDS = {w for n in _NAMES for w in n.split()} | set(_NOUNS)


def _singular_heads(head):
    """Candidate singulars of a plural head (before any compound), by undoing each makeplural rule."""
    low = head.lower()
    out = [head]
    for sing, plur in ONE_OFF:
        if low.endswith(plur):
            out.append(head[:-len(plur)] + sing)
    for suf, reps in (("'s", ("",)), ("men", ("man",)), ("ves", ("f", "ve")), ("ia", ("ium",)), ("ae", ("a",)),
                      ("i", ("us",)), ("ses", ("sis",)), ("ot", ("oh", "ah", "o", "a")), ("ices", ("ex", "ix")),
                      ("ies", ("y",)), ("es", ("",)), ("s", ("",)), ("oxen", ("ox",))):
        if low.endswith(suf):
            out += [head[:-len(suf)] + r for r in reps]
    return out


@lru_cache(maxsize=1 << 14)
def singular_name(name):
    """name_parse: the singular of an object / monster name as xname wrote it for a stack (makeplural inverted):
    "knives" -> knife, "cloves of garlic" -> clove of garlic, "quarterstaves" -> quarterstaff, "jackal corpses" ->
    jackal corpse, "scrolls labeled FOO" -> scroll labeled FOO. Of the candidates whose makeplural is the name: a
    name the game uses, else one whose last word it uses, else the first."""
    s = name.strip()
    if not s:
        return s
    at = _compound_at(s)
    head, excess = (s[:at], s[at:]) if at >= 0 else (s, "")
    best, score = None, -1
    for cand in _singular_heads(head.rstrip()):
        if not cand or makeplural(cand + excess) != s:
            continue
        full = cand + excess
        sc = 3 if full in _NAMES else 2 if cand in _NAMES else 1 if cand.split()[-1] in _WORDS else 0
        if sc > score:
            best, score = full, sc
    return best if best is not None else s


CORPSE_WEIGHT = {nh.permonst(_i).mname: nh.permonst(_i).cwt for _i in range(nh.NUMMONS)}
GEM_LOOKS = {}                    # gem / glass / gray stone description -> the least weight of its types (objects.c)
for _i in range(nh.NUM_OBJECTS):
    _oc = nh.objclass(_i)
    if ord(_oc.oc_class) == nh.GEM_CLASS and nh.OBJ_DESCR(_oc):
        _d = nh.OBJ_DESCR(_oc)
        GEM_LOOKS[_d] = min(GEM_LOOKS.get(_d, 10 ** 6), _oc.oc_weight)
UNID_GEM_NAME_RE = re.compile(r"^(.+) (?:gem|stone)$")


def unid_gem_look(name):
    """name_parse: the description of an unidentified gem / glass / gray stone named "<description> gem" /
    "<description> stone" in the singular (objnam.c xname: "yellowish brown gem", "gray stone"), else None."""
    m = UNID_GEM_NAME_RE.match(singular_name(name))
    return m.group(1) if m and m.group(1) in GEM_LOOKS else None


def corpse_kind(name):
    """name_parse: the monster of a corpse name in the singular ("lichen corpse" -> lichen), else None."""
    one = singular_name(name)
    return one[:-len(" corpse")] if one.endswith(" corpse") and one[:-len(" corpse")] in CORPSE_WEIGHT else None
