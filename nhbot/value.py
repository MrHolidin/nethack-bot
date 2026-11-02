"""Item value (flag value_model): what an item is worth to us, in gold.

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
  safe food up to MAX_FOOD pieces (pickup.food_needed).
Decisions divide by the unit weight: drop the lowest value per weight first, pick up from 0.5 gold per weight.
"""
import re
from collections import Counter

import nle.nethack as nh

from nhbot.carry import RANDOM_CLASSES, describe
from nhbot.items import base_name, parse_item
from nhbot.pricemem import _cls_of, _unit_prices, appearance, candidates, likelihood

VALUE_MAX = 1_000_000.0
UNID_BONUS = 1.2
PICKUP_MIN = 0.5                 # gold per weight unit worth picking up (was: weapons costing >= their weight)
UNID_GEM_OFFER = 5.0
UNID_SHK = 1 - 0.25 * 0.25       # 3/4 from one shopkeeper in 4
CANCELLED_RE = re.compile(r"\(\d+:-1\)")
UNID_GEM_RE = re.compile(r"^(?:\w+ )?(?:gem|stone)s?$")

TYPE_PROB = {}                   # (class, name) -> oc_prob
for _i in range(nh.NUM_OBJECTS):
    _oc = nh.objclass(_i)
    if nh.OBJ_NAME(_oc):
        TYPE_PROB.setdefault((ord(_oc.oc_class), nh.OBJ_NAME(_oc)), _oc.oc_prob)


class ValueMixin:
    def value_init(self):
        self.known_types = set()     # (class, name) seen identified in our inventory this game
        self._known_at = -1

    def note_known_types(self):
        if self._known_at == self.steps:
            return
        self._known_at = self.steps
        for it in self.items():
            if appearance(it.text) is None and (it.ocls in RANDOM_CLASSES or it.ocls in (nh.ARMOR_CLASS, nh.TOOL_CLASS)):
                key = describe(it.ocls, it.text)["key"]
                if key in TYPE_PROB:
                    self.known_types.add(key)

    def type_posterior(self, text):
        """{type: probability} for an unidentified appearance, None for an identified item (or no look)."""
        key = appearance(text)
        if key is None:
            return None
        self.note_known_types()
        cands = [n for n in candidates(key) if (_cls_of(n, key), n) not in self.known_types] or list(candidates(key))
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
        if it.on_body or self.needed(it) or self.food_needed(it):
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

    def floor_value_per_weight(self, ocls, text):
        """Value per weight of one unit of a floor item if we took it."""
        it = parse_item("?", ocls, text)
        k = appearance(text)
        same = (self.carried_by_look()[k] if k is not None else 0) + base_name(text)[0]
        return self.value_per_weight(it, same)
