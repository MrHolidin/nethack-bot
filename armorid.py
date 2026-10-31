"""Price identification of random-appearance armor in shops (flag armor_pid).

Helmets, gloves and boots with a random appearance ("plumed helmet", "padded gloves", "combat boots") are
shuffled per game, so the bot never wears them blind: some are fumbling / levitation / opposite alignment.
Base prices (objects.c) separate them:

  boots   8: elven, kicking      30: fumble, levitation      50: speed, water walking, jumping
  helmet 10: plain helmet        50: brilliance, telepathy, opposite alignment
  gloves  8: leather             50: power, dexterity, fumbling

The shop price is not the base alone (shk.c):
  getprice: armor costs base + 10 * enchantment when the enchantment is positive;
  get_cost: times 4/3 for unidentified items with o_id % 4 == 0 (1 in 4), times 4/3 for a dunce cap /
            visible shirt, times the charisma factor; rounded (scrolls.sell_price).
So a price is evidence, not a verdict: 'combat boots' for 50 at Cha 11-15 are speed/water walking/jumping
+0 -- or fumble/levitation +2. mkobj.c says how likely each is: the bad ones are generated cursed with a
negative enchantment 9 times in 10 and positive only 1 in 100, the good ones positive ~9 in 100.
P(bad | all prices read for this appearance) with a uniform prior over the slot's types; the appearance is
worn when that is below WEAR_MAX_P_BAD.

(The NLE glyph of such an item shows its appearance, not its type, so nothing here can be read off glyphs.)
"""
import re

import nle.nethack as nh

import glyphs as G
from equipment import parse_armor, HELM, GLOVES, BOOTS
from scrolls import cha_factor, sell_price

# (type, base cost, harmful)
SLOT_TYPES = {
    BOOTS: [("elven boots", 8, False), ("kicking boots", 8, False), ("fumble boots", 30, True),
            ("levitation boots", 30, True), ("jumping boots", 50, False), ("speed boots", 50, False),
            ("water walking boots", 50, False)],
    HELM: [("helmet", 10, False), ("helm of brilliance", 50, False), ("helm of opposite alignment", 50, True),
           ("helm of telepathy", 50, False)],
    GLOVES: [("leather gloves", 8, False), ("gauntlets of fumbling", 50, True), ("gauntlets of power", 50, False),
             ("gauntlets of dexterity", 50, False)],
}
RANDOM_APPEARANCE = {
    "plumed helmet": HELM, "etched helmet": HELM, "crested helmet": HELM, "visored helmet": HELM,
    "old gloves": GLOVES, "padded gloves": GLOVES, "riding gloves": GLOVES, "fencing gloves": GLOVES,
    "combat boots": BOOTS, "jungle boots": BOOTS, "hiking boots": BOOTS, "mud boots": BOOTS,
    "buckled boots": BOOTS, "riding boots": BOOTS, "snow boots": BOOTS,
}
ARMOR_SHOPS = ("used armor dealership", "general store")
PRICE_RE = re.compile(r"for sale, (\d+) zorkmids?")
WEAR_MAX_P_BAD = 0.01

# mkobj.c ARMOR_CLASS: positive enchantment = rne(3) (hero XL < 15: 1..5, P(k) = (2/3)(1/3)^(k-1), 5 takes the rest)
_RNE3 = {1: 2 / 3, 2: 2 / 9, 3: 2 / 27, 4: 2 / 81, 5: 1 / 81}


def spe_dist(bad):
    """P(enchantment counted in the price = k), k = 0..5 (negative enchantments add nothing)."""
    p_pos = 0.1 * 0.1 if bad else (1 - 0.9 / 11) * 0.1
    d = {0: 1 - p_pos}
    for k, p in _RNE3.items():
        d[k] = p_pos * p
    return d


def likelihood(price, cha, sucker, base, bad):
    m, d = cha_factor(cha)
    if sucker:
        m, d = m * 4, d * 3
    out = 0.0
    for k, pk in spe_dist(bad).items():
        b = base + 10 * k
        if sell_price(b, m, d) == price:
            out += pk * 0.75
        if sell_price(b, m * 4, d * 3) == price:             # the 1-in-4 unidentified surcharge
            out += pk * 0.25
    return out


def p_bad(slot, reads):
    """Posterior probability that the appearance is a harmful type, from (price, cha, sucker) readings.
    None if no reading is consistent with any type."""
    post = []
    for name, base, bad in SLOT_TYPES[slot]:
        lk = 1.0
        for price, cha, sucker in reads:
            lk *= likelihood(price, cha, sucker, base, bad)
        post.append((lk, bad))
    z = sum(l for l, _ in post)
    if z <= 0:
        return None
    return sum(l for l, b in post if b) / z


class ArmorIdMixin:
    def armor_id_init(self):
        self.armor_reads = {}        # appearance -> [(price, cha, sucker)]
        self.armor_id_stats = {"shops": 0, "piles": 0, "readings": 0}

    def price_safe(self, name):
        """Random-appearance armor shown (by shop prices) to be harmless with high probability."""
        if not self.role_opts.get("armor_pid", False) or name not in RANDOM_APPEARANCE:
            return False
        reads = self.armor_reads.get(name)
        if not reads:
            return False
        p = p_bad(RANDOM_APPEARANCE[name], reads)
        return p is not None and p < WEAR_MAX_P_BAD

    def note_armor_prices(self, names):
        for n in names:
            pm = PRICE_RE.search(n)
            a = parse_armor(n)
            if not pm or a is None or a["name"] not in RANDOM_APPEARANCE:
                continue
            self.armor_reads.setdefault(a["name"], []).append(
                (int(pm.group(1)), self.bl(nh.NLE_BL_CHA), self.sucker()))
            self.armor_id_stats["readings"] += 1

    def armor_shop_greeted(self, lv, stype):
        if not self.role_opts.get("armor_pid", False) or stype not in ARMOR_SHOPS or lv.key in self.shops_done:
            return
        if any(("pick-axe" in s or "mattock" in s) for _, _, s in self.inventory()):
            return                                   # the shopkeeper won't let a digger in
        self.shopping = {"key": lv.key, "until": self.turn() + 150, "kind": "armor"}
        self.armor_id_stats["shops"] += 1

    def armor_shop_step(self, lv):
        """Walk over every armor pile in the shop and read its prices; buy and pick up nothing."""
        mask = G.ARMOR_GLYPH[lv.under] & lv.shop
        for p in self.inspected.get(lv.key, ()):
            mask[p] = False
        if not mask.any():
            self.shops_done.add(lv.key)
            self.shopping = None
            return False
        y, x = self.pos()
        if mask[y, x]:
            self.inspected.setdefault(lv.key, set()).add((y, x))
            self.armor_id_stats["piles"] += 1
            self.note_armor_prices(self.look_here())
            return True
        return self.go_toward_mask(lv, mask)

    def armor_id_report(self):
        out = {}
        for app, reads in self.armor_reads.items():
            p = p_bad(RANDOM_APPEARANCE[app], reads)
            out[app] = {"reads": reads, "p_bad": None if p is None else round(p, 4)}
        return out
