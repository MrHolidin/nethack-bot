"""Item value: what an item is worth to us, in gold.

est_gold(ocls, text): what a shopkeeper would pay for ONE unit (shk.c set_cost, NetHack 3.6.6):
  offer = getprice / 2 (/ 3 with a visible dunce cap or shirt: sucker); an unidentified type gets 3/4 from one
  shopkeeper in 4 (m_id % 4 == 0), so x 15/16 on average; an unidentified gem or glass gets only
  (otyp % (6 - m_id % 3)) + 3, about 5. getprice: objects.c cost, +10 per positive enchantment of armor (the
  mkobj.c odds when unknown), 0 for uncursed water and a cancelled wand.
  An unidentified appearance is priced over its possible types: prior oc_prob (finding an item of this look
  is likelier when the look belongs to a common type), types already identified this game excluded (they would
  show by name), times the likelihood of every price a shopkeeper showed for this look (pricemem).
est_value(item, same): est_gold, +20% for an unidentified type of which we would have a single unit
  (what we may learn or use), VALUE_MAX + est_gold for what we wear / wield, what we need (carry.needed) and
  safe food up to MAX_FOOD pieces (pickup.food_needed), and water (clear potions).
Dropping divides by the unit weight: the lowest value per weight goes first. Picking up uses the same order
(worth_taking): what fits without Burdened, or what is worth more per weight than what would go to make room.
"""
import re
from collections import Counter

import nle.nethack as nh

from nhbot.carry import RANDOM_CLASSES, describe
from nhbot.items import base_name, parse_item
from nhbot.pricemem import _cls_of, _unit_prices, appearance, candidates, likelihood

VALUE_MAX = 1_000_000.0
UNID_BONUS = 1.2
UNID_GEM_OFFER = 5.0
UNID_SHK = 1 - 0.25 * 0.25       # 3/4 from one shopkeeper in 4
CANCELLED_RE = re.compile(r"\(\d+:-1\)")
UNID_GEM_RE = re.compile(r"^(?:\w+ )?(?:gem|stone)s?$")

BLANK_PAPER_COST = 60


def is_water(ocls, text):
    """A clear potion: water (holy / unholy / plain). Kept and picked up like what we need (owner's decision)."""
    return ocls == nh.POTION_CLASS and re.match(r"^clear potions?$", base_name(text)[2]) is not None


TYPE_PROB = {}                   # (class, name) -> oc_prob
for _i in range(nh.NUM_OBJECTS):
    _oc = nh.objclass(_i)
    if nh.OBJ_NAME(_oc):
        TYPE_PROB.setdefault((ord(_oc.oc_class), nh.OBJ_NAME(_oc)), _oc.oc_prob)


class ValueMixin:
    def value_init(self):
        self.known_types = set()     # (class, name) seen identified in our inventory this game
        self._known_inv = None       # the inventory note_known_types last read
        self.type_version = 0        # bumped whenever what type_posterior reads changes
        self.deduced = {}            # appearance key -> type worked out though the game did not name it (deduce_type)
        self._post_memo = {}         # text -> (type_version, posterior)

    def note_known_types(self):
        inv = self.inventory()
        if inv == self._known_inv:
            return                   # the same inventory adds nothing new
        self._known_inv = inv
        for it in self.items():
            if appearance(it.text) is None and (it.ocls in RANDOM_CLASSES or it.ocls in (nh.ARMOR_CLASS, nh.TOOL_CLASS)):
                key = describe(it.ocls, it.text)["key"]
                if key in TYPE_PROB and key not in self.known_types:
                    self.known_types.add(key)
                    self.type_version += 1

    def type_posterior(self, text):
        """{type: probability} for an unidentified appearance, None for an identified item (or no look)."""
        key = appearance(text)
        if key is None:
            return None
        self.note_known_types()
        memo = self._post_memo.get(text)
        if memo is not None and memo[0] == self.type_version:
            return dict(memo[1])
        post = self._type_posterior(key)
        self._post_memo[text] = (self.type_version, post)
        return dict(post)

    def deduce_type(self, ocls, key, name):
        """We worked out that an appearance is this type (quaff_test: restore ability doesn't name itself, potion.c
        unkn): its posterior is that type alone, and no other appearance is it."""
        if self.deduced.get(key) != name:
            self.deduced[key] = name
            self.known_types.add((ocls, name))
            self.type_version += 1

    def _type_posterior(self, key):
        if key in self.deduced:
            return {self.deduced[key]: 1.0}
        cands = [n for n in candidates(key) if (_cls_of(n, key), n) not in self.known_types] or list(candidates(key))
        engraved = self.wand_engraved.get(key)              # wandid: the engraving test narrowed the types
        if engraved:
            cands = [n for n in cands if n in engraved] or cands
        reads = list(self.price_reads.get(key, {}).values())
        for prior in (lambda n: TYPE_PROB.get((_cls_of(n, key), n), 0), lambda n: 1.0):
            post = {}
            for n in cands:
                p = prior(n)
                for r in reads:
                    if p == 0:
                        break
                    p *= likelihood(n, _cls_of(n, key), r)
                post[n] = p
            z = sum(post.values())
            if z > 0:
                return {n: p / z for n, p in post.items() if p > 0}
        return {n: 1 / len(cands) for n in cands}           # readings that fit no type: misread, ignore them

    def est_gold(self, ocls, text):
        """Expected shopkeeper offer for one unit."""
        if ocls == nh.COIN_CLASS:
            return 1.0
        div = 3 if self.sucker() else 2
        _, ench, t = base_name(text)
        if ocls == nh.WAND_CLASS and CANCELLED_RE.search(text):
            return 0.0
        if ocls == nh.GEM_CLASS and UNID_GEM_RE.match(t):
            return UNID_GEM_OFFER
        if ocls == nh.POTION_CLASS and re.match(r"^clear potions?$", t):
            return 0.0 if not re.search(r"\b(blessed|cursed)\b", text) or "uncursed" in text else 100 / div
        if ocls == nh.SCROLL_CLASS and re.match(r"^unlabeled scrolls?$", t):
            return BLANK_PAPER_COST / div * UNID_SHK            # the fixed look of blank paper
        post = self.type_posterior(text)
        if post is not None:
            key = appearance(text)
            tot = 0.0
            for n, p in post.items():
                tot += p * sum(pk * gp for gp, pk in _unit_prices(n, _cls_of(n, key)))
            return tot / div * UNID_SHK
        d = describe(ocls, text)
        if d["cost"] is None:
            return 0.0
        gp = d["cost"]
        if ocls in (nh.ARMOR_CLASS, nh.WEAPON_CLASS) and ench is not None and ench > 0:
            gp += 10 * ench
        if ocls == nh.POTION_CLASS and d["key"][1] == "water" and "uncursed" in text:
            gp = 0
        return gp / div * (UNID_SHK if d["unid"] else 1.0)

    def is_unknown(self, ocls, text):
        """More than one type is still possible for it."""
        if ocls == nh.GEM_CLASS and UNID_GEM_RE.match(base_name(text)[2]):
            return True
        post = self.type_posterior(text)
        return post is not None and len(post) > 1

    def est_value(self, it, same=1):
        """Value of keeping one unit of Item it; same: units of its look we would carry."""
        g = self.est_gold(it.ocls, it.text)
        if it.on_body or self.needed(it) or self.food_needed(it) or is_water(it.ocls, it.text):
            return VALUE_MAX + g
        if same == 1 and self.is_unknown(it.ocls, it.text):
            g *= UNID_BONUS
        return g

    def carried_by_look(self):
        """Units carried per appearance key (unidentified looks only)."""
        out = Counter()
        for it in self.items():
            k = appearance(it.text)
            if k is not None:
                out[k] += base_name(it.text)[0]
        return out

    def value_per_weight(self, it, same=1):
        return self.est_value(it, same) / describe(it.ocls, it.text)["wt"]

    # ------------------------------------------------------------ the same comparison for picking up
    def weight_capacity(self):
        """hack.c weight_cap: 25 * (Str + Con) + 50, at most 1000; carrying more is Burdened."""
        return min(25 * (self.bl(nh.NLE_BL_STR25) + self.bl(nh.NLE_BL_CON)) + 50, 1000)

    def inventory_weight(self):
        wt = 0
        for it in self.items():
            if it.ocls == nh.COIN_CLASS:
                wt += (base_name(it.text)[0] + 50) // 100           # invent.c: 100 coins weigh 1
            else:
                d = describe(it.ocls, it.text)
                wt += d["wt"] * d["qty"]
        return wt

    def worth_taking(self, ocls, text):
        """Take a floor stack if it fits without Burdened, or if it is worth more per weight than
        the cheapest things (off the body) we would drop to make room for it -- the order carry_drop_step drops
        in, so we never pick up what the drop step would put straight back down."""
        d = describe(ocls, text)
        wt = d["wt"] * d["qty"]
        free = self.weight_capacity() - self.inventory_weight()
        if wt <= free:
            return True
        looks = self.carried_by_look()
        k = appearance(text)
        vpw = self.value_per_weight(parse_item("?", ocls, text), (looks[k] if k is not None else 0) + d["qty"])
        same = lambda it: looks[appearance(it.text)] if appearance(it.text) is not None else 1
        need = wt - free
        drop = sorted(((self.value_per_weight(it, same(it)), it) for it in self.items()
                       if it.ocls != nh.COIN_CLASS and not it.on_body and it.key not in self.cant_drop),
                      key=lambda x: x[0])
        for v, it in drop:
            if v >= vpw:
                return False
            dd = describe(it.ocls, it.text)
            need -= dd["wt"] * dd["qty"]
            if need <= 0:
                return True
        return False
