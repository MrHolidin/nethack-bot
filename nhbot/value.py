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
  (what we may learn or use), VALUE_MAX + est_gold for what keep_reason keeps (one rule for value, selling,
  throwing and taking, with quotas: keep_plan).
Dropping divides by the unit weight: the lowest value per weight goes first. Picking up uses the same order
(worth_taking): what fits without Burdened, or what is worth more per weight than what would go to make room.
"""
import re
from collections import Counter

import nle.nethack as nh

from nhbot.carry import RANDOM_CLASSES, WEAPON_NAME_OF, describe
from nhbot.items import base_name, parse_item, singular_name, unid_gem_look
from nhbot.pickup import KEEP_FOOD, MAX_FOOD, MISSILE_TYPES, floor_kind
from nhbot.pricemem import _cls_of, _unit_prices, appearance, candidates, likelihood

VALUE_MAX = 1_000_000.0
UNID_BONUS = 1.2
UNID_GEM_OFFER = 5.0
UNID_SHK = 1 - 0.25 * 0.25       # 3/4 from one shopkeeper in 4
CANCELLED_RE = re.compile(r"\(\d+:-1\)")

BLANK_PAPER_COST = 60

# the quotas of keep_plan (food: pickup.KEEP_FOOD up to MAX_FOOD pieces)
MISSILE_KEEP = 10                # missile pieces kept (combat.throwables: daggers, knives, darts, ... not crysknives)
DIGGERS = ("pick-axe", "dwarvish mattock")

# slots: the 52 inventory letters (invent.c; gold takes none) -- pickup.c:1426-1434 lift_object refuses an item
# that would need a 53rd ("Your knapsack cannot accommodate any more items.")
INV_LETTERS = 52
# what can stack (objects.c oc_merge): the classes whose every type merges, and the weapons that do (missiles,
# daggers, knives, spears); candles are the common mergeable tool
MERGE_CLASSES = (nh.FOOD_CLASS, nh.POTION_CLASS, nh.SCROLL_CLASS, nh.GEM_CLASS)
MERGE_WEAPONS = {"arrow", "elven arrow", "orcish arrow", "silver arrow", "ya", "crossbow bolt", "dart", "shuriken",
                 "boomerang", "spear", "elven spear", "orcish spear", "dwarvish spear", "silver spear", "javelin",
                 "dagger", "elven dagger", "orcish dagger", "silver dagger", "athame", "scalpel", "knife", "stiletto",
                 "worm tooth", "crysknife"}


def stack_key(text):
    """What must agree for two stacks to merge, as far as the text shows (invent.c mergable: the type, BUC and its
    knowledge, enchantment, erosion, name): the text without count, article and state suffixes, singular
    (items.singular_name)."""
    t = re.sub(r"\s*\(.*?\)", "", text).strip()
    t = re.sub(r"^(?:a|an|the|some|\d+)\s+", "", t)
    return singular_name(t)     # (name_parse, accepted without A/B by the user -- see carry.describe)


def is_water(ocls, text):
    """A clear potion: water (holy / unholy / plain). Kept and picked up like what we need (owner's decision)."""
    return ocls == nh.POTION_CLASS and re.match(r"^clear potions?$", base_name(text)[2]) is not None


TYPE_PROB = {}                   # (class, name) -> oc_prob
for _i in range(nh.NUM_OBJECTS):
    _oc = nh.objclass(_i)
    if nh.OBJ_NAME(_oc):
        TYPE_PROB.setdefault((ord(_oc.oc_class), nh.OBJ_NAME(_oc)), _oc.oc_prob)


class ValueState:
    """State of item identification: known types, deductions, the posterior memo (ValueMixin)."""
    def __init__(self):
        self.known_types = set()     # (class, name) seen identified in our inventory this game
        self.known_inv = None        # the inventory note_known_types last read
        self.type_version = 0        # bumped whenever what type_posterior reads changes
        self.deduced = {}            # appearance key -> type worked out though the game did not name it (deduce_type)
        self.post_memo = {}          # text -> (type_version, posterior)
        self.keep_memo = (None, {})  # (game state key, keep_plan)


class ValueMixin:
    def value_init(self):
        self.value = ValueState()

    def value_types_changed(self):
        """Something type_posterior reads changed (a price reading, a wand engrave-tested): its memo is stale."""
        self.value.type_version += 1

    def note_known_types(self):
        inv = self.inventory()
        if inv == self.value.known_inv:
            return                   # the same inventory adds nothing new
        self.value.known_inv = inv
        for it in self.items():
            if appearance(it.text) is None and (it.ocls in RANDOM_CLASSES or it.ocls in (nh.ARMOR_CLASS, nh.TOOL_CLASS)):
                key = describe(it.ocls, it.text)["key"]
                if key in TYPE_PROB and key not in self.value.known_types:
                    self.value.known_types.add(key)
                    self.value.type_version += 1

    def type_posterior(self, text):
        """{type: probability} for an unidentified appearance, None for an identified item (or no look)."""
        key = appearance(text)
        if key is None:
            return None
        self.note_known_types()
        memo = self.value.post_memo.get(text)
        if memo is not None and memo[0] == self.value.type_version:
            return dict(memo[1])
        post = self._type_posterior(key)
        self.value.post_memo[text] = (self.value.type_version, post)
        return dict(post)

    def deduce_type(self, ocls, key, name):
        """We worked out that an appearance is this type (quaff_test: restore ability doesn't name itself, potion.c
        unkn): its posterior is that type alone, and no other appearance is it."""
        if self.value.deduced.get(key) != name:
            self.value.deduced[key] = name
            self.value.known_types.add((ocls, name))
            self.value.type_version += 1

    def _type_posterior(self, key):
        if key in self.value.deduced:
            return {self.value.deduced[key]: 1.0}
        cands = [n for n in candidates(key) if (_cls_of(n, key), n) not in self.value.known_types] or list(candidates(key))
        engraved = self.wandid.engraved.get(key)              # wandid: the engraving test narrowed the types
        if engraved:
            cands = [n for n in cands if n in engraved] or cands
        reads = list(self.prices.reads.get(key, {}).values())
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
        if ocls == nh.GEM_CLASS and unid_gem_look(t):
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
        """More than one type is still possible for it. An unidentified gem: any gem / glass / gray stone look
        (items.unid_gem_look)."""
        # (name_parse, accepted without A/B by the user -- see carry.describe): replaced a pattern of one word
        # before "gem" / "stone" -- "yellowish brown gem" failed it: valued 0, dropped first
        if ocls == nh.GEM_CLASS and unid_gem_look(base_name(text)[2]):
            return True
        post = self.type_posterior(text)
        return post is not None and len(post) > 1

    def est_value(self, it, same=1):
        """Value of keeping one unit of Item it; same: units of its look we would carry. VALUE_MAX + its gold for
        whatever keep_reason keeps."""
        g = self.est_gold(it.ocls, it.text)
        if self.keep_reason(it) is not None:
            return VALUE_MAX + g
        if same == 1 and self.is_unknown(it.ocls, it.text):
            g *= UNID_BONUS
        return g

    # ------------------------------------------------------------ what we keep, one rule
    def keep_reason(self, it, inv=None):
        """Why we keep Item it among inv (default: what we carry; an item not among them -- a floor stack,
        letter "?" -- is judged as if added), or None: it may be sold, dropped, thrown. The reasons of keep_plan;
        est_value, sellables, expendables and take_reason all read this. (A/B keep_rule: -731 [-2505, +1053] on 79k;
        +1451 [-357, +3365], median 8100 -> 8874, 824 of 1000 changed on 80k)"""
        inv = list(self.items()) if inv is None else list(inv)
        if not any(x.letter == it.letter and x.text == it.text for x in inv):
            inv.append(it)
        return self.keep_plan(inv).get(it.letter)

    def keep_plan(self, inv):
        """{letter: reason} of the items of inv we keep (the others are left out):
          worn        on the body (worn, wielded, rings on)
          alternate   the alternate weapon
          water       clear potions (owner's decision)
          digger      one digger (pick-axe before dwarvish mattock; the one in hand first)
          wield       the best wield candidate (weapons.weapon_rank above 0, not known cursed), in hand or not
          excalibur   lawful without Excalibur: the best long sword too (excalibur.long_sword's rule)
          missile     missiles (pickup.MISSILE_TYPES -- no crysknife) up to MISSILE_KEEP pieces: quivered first,
                      then the biggest stacks
          food        food we eat from the pack (KEEP_FOOD: no corpses, no tins) up to MAX_FOOD pieces, the most
                      nutrition per weight first
          needed      what carry.needed keeps (attack wands, healing, good scrolls, a lamp to rub, jewelry, the
                      lock tool, ...) -- for weapons only by the rules above
        Cached for the game state (tick, keys sent, the texts)."""
        key = (self.pol.tick_no, self.steps, tuple((x.letter, x.ocls, x.text) for x in inv))
        if self.value.keep_memo[0] == key:
            return self.value.keep_memo[1]
        from nhbot.survival import FOOD_NUTRITION
        plan = {}
        lawful = int(self.last_bl[nh.NLE_BL_ALIGN]) == 1
        diggers, wield, swords, missiles, food = [], [], [], [], []
        for it in inv:
            if it.ocls == nh.COIN_CLASS:
                continue
            if it.on_body:
                plan[it.letter] = "worn"
            elif it.alternate:
                plan[it.letter] = "alternate"
            elif is_water(it.ocls, it.text):
                plan[it.letter] = "water"
            d = describe(it.ocls, it.text)
            name = d["key"][1]
            if name in DIGGERS:
                diggers.append(it)
            elif it.ocls == nh.WEAPON_CLASS:
                rank = self.weapon_rank(it.text)
                if rank[0] > 0 and not it.cursed:
                    wield.append((rank, it))
                    if lawful and not self.excal.excalibur and name == "long sword" and "Excalibur" not in it.text \
                            and base_name(it.text)[0] == 1:
                        swords.append((rank, it))
                elif name in MISSILE_TYPES and not it.cursed:
                    missiles.append(it)
            elif it.ocls == nh.FOOD_CLASS:
                kind = floor_kind(it.text)[1]
                if kind in KEEP_FOOD:
                    food.append((-FOOD_NUTRITION.get(kind, 200) / d["wt"], it))
            elif it.letter not in plan and self.needed(it):
                plan[it.letter] = "needed"
        if diggers:
            best = min(diggers, key=lambda x: (not x.held, "mattock" in x.text or "broad pick" in x.text))
            plan.setdefault(best.letter, "digger")
        if wield:
            plan.setdefault(max(wield, key=lambda c: c[0])[1].letter, "wield")
        if swords:
            plan.setdefault(max(swords, key=lambda c: c[0])[1].letter, "excalibur")
        n = 0
        for it in sorted(missiles, key=lambda x: (not x.quivered, -base_name(x.text)[0])):
            if n >= MISSILE_KEEP:
                break
            plan.setdefault(it.letter, "missile")
            n += base_name(it.text)[0]
        n = 0
        for _, it in sorted(food, key=lambda c: c[0]):
            if n >= MAX_FOOD:
                break
            plan.setdefault(it.letter, "food")
            n += base_name(it.text)[0]
        self.value.keep_memo = (key, plan)
        return plan

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

    # ------------------------------------------------------------ the 52 letters (slots)
    def letters_free(self):
        """Inventory letters left (gold takes none)."""
        return INV_LETTERS - sum(1 for it in self.items() if it.ocls != nh.COIN_CLASS)

    def merges_in(self, ocls, text):
        """slots: a floor stack that would join a stack we carry (no letter of its own) -- a mergeable kind whose
        text agrees with one of ours (stack_key; hidden differences -- an unknown BUC -- can still keep them apart)."""
        if ocls == nh.WEAPON_CLASS:
            name = base_name(text)[2]
            name = WEAPON_NAME_OF.get(name, WEAPON_NAME_OF.get(singular_name(name), name))
            if name not in MERGE_WEAPONS:
                return False
        elif ocls not in MERGE_CLASSES and not (ocls == nh.TOOL_CLASS and "candle" in text):
            return False
        k = stack_key(text)
        return any(it.ocls == ocls and stack_key(it.text) == k for it in self.items())

    def stack_value(self, it, same=1):
        """est_value of the whole stack (a letter is freed only by all of it)."""
        return self.est_value(it, same) * base_name(it.text)[0]

    def slot_victim(self):
        """slots: the stack whose letter we would give up -- the lowest stack_value among what we may drop: off the
        body, not refused before, not needed (est_value below VALUE_MAX: not what we wear / wield / need, not
        safe food, not water), not a corpse carried to an altar. None: nothing."""
        looks = self.carried_by_look()
        same = lambda it: looks[appearance(it.text)] if appearance(it.text) is not None else 1
        cands = [(self.stack_value(it, same(it)), it) for it in self.items()
                 if it.ocls != nh.COIN_CLASS and not it.on_body and not it.alternate and not it.quivered
                 and it.key not in self.carry.cant_drop and not self.sac_carrying(it)
                 and self.est_value(it, same(it)) < VALUE_MAX]
        return min(cands, key=lambda c: c[0])[1] if cands else None

    def slot_ok(self, ocls, text, reason):
        """slots: may this floor stack (take_reason: reason) have a letter? One that merges needs none; while two or
        more are free, yes; taking the last free one (or none is free), only if it is worth more than the stack
        slot_victim would give up -- which the drop step (carry.carry_drop_step) then drops, so a letter stays free.
        An armor upgrade counts as needed (it will be worn)."""
        if self.merges_in(ocls, text):
            return True
        free = self.letters_free()
        if free >= 2:
            return True
        victim = self.slot_victim()
        if victim is None:
            return free >= 1
        looks = self.carried_by_look()
        k = appearance(text)
        qty = base_name(text)[0]
        it = parse_item("?", ocls, text)
        v = VALUE_MAX if reason == "armor" else self.est_value(it, (looks[k] if k is not None else 0) + qty)
        vs = looks[appearance(victim.text)] if appearance(victim.text) is not None else 1
        return v * qty > self.stack_value(victim, vs)

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
                       if it.ocls != nh.COIN_CLASS and not it.on_body and it.key not in self.carry.cant_drop),
                      key=lambda x: x[0])
        for v, it in drop:
            if v >= vpw:
                return False
            dd = describe(it.ocls, it.text)
            need -= dd["wt"] * dd["qty"]
            if need <= 0:
                return True
        return False
