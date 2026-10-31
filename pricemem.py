"""Price memory: every price a shopkeeper shows is evidence about what an unidentified item is.

Sources (both recorded whenever they appear, whatever the bot is doing):
  * a price tag:   "a bubbly potion (for sale, 133 zorkmids)"     -- shk.c get_cost, total for the stack
  * a sell offer:  "Adjama offers 75 gold pieces for your oak wand.  Sell it?"   -- shk.c set_cost

Arithmetic (NetHack 3.6.6, shk.c):
  getprice  = objects.c base cost; armor/weapons +10 per point of positive enchantment; uncursed water 0
  get_cost  = getprice (5 if 0) * [4/3 for 1 in 4 unidentified objects: o_id % 4] * [4/3 dunce cap / shirt]
              * charisma factor, rounded (t*10/div + 5)/10, per unit
  set_cost  = getprice * units / 2  (/3 with a dunce cap / visible shirt) * [3/4 for unidentified items at
              shopkeepers with m_id % 4 == 0], same rounding
Appearances (o_init.c) are a random permutation inside each shuffled group, so before any evidence every type
of the group is equally likely for a given appearance. Posterior = uniform prior x likelihood of all readings.
Armor enchantment odds come from mkobj.c (armorid.spe_dist). Unknowns that are fixed per object or per
shopkeeper (o_id % 4, m_id % 4) are treated as independent 1-in-4 events per reading.

Identified items ("potion of healing") need nothing: the game already names them.
"""
import re

import nle.nethack as nh

from scrolls import cha_factor

SHUFFLED_CLASSES = (nh.AMULET_CLASS, nh.POTION_CLASS, nh.RING_CLASS, nh.SCROLL_CLASS, nh.SPBOOK_CLASS,
                    nh.WAND_CLASS)
NOUN = {nh.POTION_CLASS: "potion", nh.SCROLL_CLASS: "scroll", nh.RING_CLASS: "ring", nh.WAND_CLASS: "wand",
        nh.AMULET_CLASS: "amulet", nh.SPBOOK_CLASS: "spellbook"}
ALWAYS_CURSED = {"fumble boots", "levitation boots", "helm of opposite alignment", "gauntlets of fumbling"}
ARMOR_GROUPS = (("helmet", "helm of telepathy"), ("leather gloves", "gauntlets of dexterity"),
                ("cloak of protection", "cloak of displacement"), ("speed boots", "levitation boots"))

# ---------------------------------------------------------------- object table
OBJ = []                                  # index -> (name, descr, class, cost)
for _i in range(nh.NUM_OBJECTS):
    _oc = nh.objclass(_i)
    OBJ.append((nh.OBJ_NAME(_oc), nh.OBJ_DESCR(_oc), ord(_oc.oc_class), _oc.oc_cost))
_INDEX = {(c, n): i for i, (n, d, c, k) in enumerate(OBJ) if n}   # names repeat across classes


def _pool(cls):
    idx = [i for i, o in enumerate(OBJ) if o[2] == cls and o[0]]
    if cls == nh.POTION_CLASS:
        return [i for i in idx if OBJ[i][0] != "water"]
    if cls in (nh.AMULET_CLASS, nh.SCROLL_CLASS, nh.SPBOOK_CLASS):
        out = []
        for i in idx:                    # up to the first non-magic / unique type (o_init.c)
            if OBJ[i][0] in ("cheap plastic imitation of the Amulet of Yendor", "Amulet of Yendor",
                             "blank paper", "mail", "Book of the Dead"):
                break
            out.append(i)
        return out
    return idx


POOLS = {cls: [OBJ[i][0] for i in _pool(cls)] for cls in SHUFFLED_CLASSES}
POTION_PROB = {OBJ[i][0]: nh.objclass(i).oc_prob for i in _pool(nh.POTION_CLASS)}
_AR = nh.ARMOR_CLASS
for _a, _b in ARMOR_GROUPS:
    _grp = [OBJ[i][0] for i in range(_INDEX[(_AR, _a)], _INDEX[(_AR, _b)] + 1)]
    for _n in _grp:
        POOLS[("armor", _n)] = _grp
# random appearances of the shuffled armor groups
ARMOR_APPEAR = {OBJ[_INDEX[(_AR, n)]][1]: POOLS[("armor", n)] for g in ARMOR_GROUPS
                for n in POOLS[("armor", g[0])] if OBJ[_INDEX[(_AR, n)]][1]}
# fixed descriptions shared by several types (conical hat, bag, lamp, flute, horn, ...): not shuffled
SHARED = {}
for _n, _d, _c, _k in OBJ:
    if _n and _d and _c not in SHUFFLED_CLASSES and _c != nh.GEM_CLASS and _d not in ARMOR_APPEAR:
        SHARED.setdefault(_d, []).append(_n)
SHARED = {d: ns for d, ns in SHARED.items() if len(ns) > 1}

_RNE3 = {1: 2 / 3, 2: 2 / 9, 3: 2 / 27, 4: 2 / 81, 5: 1 / 81}


def spe_dist(name):
    """P(positive enchantment = k) for random armor of this type (mkobj.c); negative counts as 0."""
    p_pos = 0.1 * 0.1 if name in ALWAYS_CURSED else (1 - 0.9 / 11) * 0.1
    d = {0: 1 - p_pos}
    for k, p in _RNE3.items():
        d[k] = p_pos * p
    return d


def _round(t, mult, div):
    t *= mult
    if div > 1:
        t = (t * 10 // div + 5) // 10
    return max(t, 1)


def _unit_prices(name, cls):
    """[(getprice, probability)] for one object of this type."""
    base = OBJ[_INDEX[(cls, name)]][3]
    if cls == nh.ARMOR_CLASS:
        return [(base + 10 * k, p) for k, p in spe_dist(name).items()]
    return [(base, 1.0)]


def likelihood(name, cls, r):
    kind, price, qty, cha, sucker = r
    out = 0.0
    for gp, pk in _unit_prices(name, cls):
        if kind == "buy":
            m, d = cha_factor(cha)
            if sucker:
                m, d = m * 4, d * 3
            unit = gp or 5
            for um, ud, pu in ((1, 1, 0.75), (4, 3, 0.25)):          # o_id % 4 surcharge
                if _round(unit, m * um, d * ud) * qty == price:
                    out += pk * pu
        else:
            d0 = 3 if sucker else 2
            tot = gp * qty
            if tot < 1:
                continue
            for um, ud, pu in ((1, 1, 0.75), (3, 4, 0.25)):          # m_id % 4 shopkeepers
                if _round(tot, um, d0 * ud) == price:
                    out += pk * pu
    return out


# ---------------------------------------------------------------- text -> appearance
_STRIP = re.compile(r"\b(uncursed|cursed|blessed|rustproof|fireproof|corrodeproof|rotted|very|thoroughly|rusty|"
                    r"rusted|corroded|burnt|burned|greased|diluted|lit|partly used)\s+")


def appearance(text):
    """(class, appearance key) of an UNIDENTIFIED item named by its looks, else None."""
    t = re.sub(r"\s*\(.*?\)", "", text).strip()
    t = re.sub(r"\s+(called|named)\s+.*$", "", t)
    t = re.sub(r"^(a|an|the|\d+)\s+", "", t)
    t = _STRIP.sub("", t)
    t = re.sub(r"^[+-]\d+\s+", "", t)
    t = re.sub(r"^(pair|set)s? of ", "", t).strip()
    if re.search(r"\b(potion|scroll|ring|wand|amulet|spellbook)s? of ", t):
        return None
    m = re.match(r"^scrolls? labeled (.+)$", t)
    if m:
        return nh.SCROLL_CLASS, m.group(1)
    for cls, noun in NOUN.items():
        m = re.match(r"^(.+?) %ss?$" % noun, t)
        if m:
            if cls == nh.POTION_CLASS and m.group(1) == "clear":
                return None                                          # water: fixed look
            return cls, m.group(1)
    if t in ARMOR_APPEAR:
        return nh.ARMOR_CLASS, t
    if t in SHARED:
        return "shared", t
    return None


def candidates(key):
    cls, app = key
    if cls == nh.ARMOR_CLASS:
        return ARMOR_APPEAR[app]
    if cls == "shared":
        return SHARED[app]
    return POOLS[cls]


def _cls_of(name, key):
    if key[0] == "shared":
        return next(c for (c, n) in _INDEX if n == name)
    return key[0]


TAG_RE = re.compile(r"(?:You see here |There (?:is|are) [^.;]*?here;? )?((?:an?|the|\d+) .+?) \(for sale, (\d+) zorkmids?\)")
OFFER_RE = re.compile(r"offers (\d+) gold pieces? for your (.+?)\.\s+Sell (?:it|them)")


class PriceMemoryMixin:
    def price_init(self):
        self.price_reads = {}        # appearance key -> {reading id: reading}
        self.price_stats = {"buy": 0, "sell": 0}

    def _sucker(self):
        return self.sucker()

    def _record(self, text, kind, price, rid, qty=None):
        key = appearance(text)
        if key is None:
            return
        m = re.match(r"^(\d+) ", text.strip())
        if m:
            qty = int(m.group(1))
        elif qty is None:
            qty = 1
        r = (kind, price, qty, self.bl(nh.NLE_BL_CHA), self._sucker())
        bucket = self.price_reads.setdefault(key, {})
        if rid not in bucket:
            bucket[rid] = r
            self.price_stats[kind] += 1

    def price_note_text(self, text):
        """Any text with price tags (look_here lines, 'You see here ...' messages)."""
        if "for sale" not in text:
            return
        lk = self.cur_key
        for seg in re.split(r"\s*\|\s*|(?<=\.)\s+|:\s+", text):
            m = TAG_RE.search(seg)
            if m:
                item, price = m.group(1).strip(), int(m.group(2))
                self._record(item, "buy", price, ("buy", lk, self.pos(), item, price))

    def price_note_offer(self, msg):
        if "offers only" in msg:
            return                                   # shopkeeper short of cash: no information
        m = OFFER_RE.search(msg)
        if not m:
            return
        offer, item = int(m.group(1)), m.group(2).strip()
        shk = msg.split(" offers ")[0].split(".")[-1].strip()
        # "for your scrolls labeled X": the offer is for the whole stack, whose size the message omits
        qty = getattr(self, "last_drop_qty", None) if re.search(r"\b(potions|scrolls|rings|wands|amulets|spellbooks|pairs)\b", item) else 1
        self._record(item, "sell", offer, ("sell", shk, item, offer, qty), qty)

    def price_posterior(self, key):
        """{type: probability} for an appearance, or None without (consistent) evidence."""
        reads = list(self.price_reads.get(key, {}).values())
        if not reads:
            return None
        post = {}
        for n in candidates(key):
            l = 1.0
            for r in reads:
                l *= likelihood(n, _cls_of(n, key), r)
                if l == 0.0:
                    break
            post[n] = l
        z = sum(post.values())
        if z <= 0:
            return None
        return {n: p / z for n, p in post.items() if p > 0}

    def price_of_text(self, text):
        key = appearance(text)
        return None if key is None else self.price_posterior(key)

    def price_report(self):
        out = {}
        for key in self.price_reads:
            post = self.price_posterior(key)
            top = sorted((post or {}).items(), key=lambda x: -x[1])[:4]
            out[f"{key[0]}:{key[1]}"] = {"n": len(self.price_reads[key]), "top": [(n, round(p, 3)) for n, p in top]}
        return out
