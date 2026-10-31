"""Wear random-appearance armor once shop prices show it is harmless (flag armor_pid).

Helmets, gloves and boots with a random appearance ("plumed helmet", "padded gloves", "combat boots") are
shuffled per game, so the bot never wears them blind: some are fumbling / levitation / opposite alignment.
With the flag on, the bot walks over every armor pile in armor shops and general stores (nothing is bought
or picked up); the price tags go to the shared price memory (pricemem.py), which turns all readings of an
appearance into probabilities of its types. An appearance is worn when P(harmful type) < WEAR_MAX_P_BAD.

(The NLE glyph of such an item shows its appearance, not its type, so nothing here can be read off glyphs.)
"""
import nle.nethack as nh

import glyphs as G
from equipment import HELM, GLOVES, BOOTS

RANDOM_APPEARANCE = {
    "plumed helmet": HELM, "etched helmet": HELM, "crested helmet": HELM, "visored helmet": HELM,
    "old gloves": GLOVES, "padded gloves": GLOVES, "riding gloves": GLOVES, "fencing gloves": GLOVES,
    "combat boots": BOOTS, "jungle boots": BOOTS, "hiking boots": BOOTS, "mud boots": BOOTS,
    "buckled boots": BOOTS, "riding boots": BOOTS, "snow boots": BOOTS,
}
HARMFUL = {"fumble boots", "levitation boots", "helm of opposite alignment", "gauntlets of fumbling"}
MAGIC_BOOTS = {"speed boots", "water walking boots", "jumping boots"}      # base 50: same AC 1, plus a power
ARMOR_SHOPS = ("used armor dealership", "general store")
WEAR_MAX_P_BAD = 0.01


class ArmorIdMixin:
    def armor_id_init(self):
        self.armor_id_stats = {"shops": 0, "piles": 0}

    def price_safe(self, name):
        """Random-appearance armor shown (by shop prices) to be harmless with high probability.
        armor_pid gathers prices in armor shops; pid_wear uses whatever prices we have (any shop, any sale)."""
        if not (self.role_opts.get("armor_pid", False) or self.role_opts.get("pid_wear", False)) \
                or name not in RANDOM_APPEARANCE:
            return False
        post = self.price_posterior((nh.ARMOR_CLASS, name))
        return post is not None and sum(p for t, p in post.items() if t in HARMFUL) < WEAR_MAX_P_BAD

    def magic_boots(self, name):
        """Random-appearance boots that prices put in the speed / water walking / jumping group."""
        if name not in RANDOM_APPEARANCE or not self.price_safe(name):
            return False
        post = self.price_posterior((nh.ARMOR_CLASS, name)) or {}
        return sum(p for t, p in post.items() if t in MAGIC_BOOTS) >= 1 - WEAR_MAX_P_BAD

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
            self.look_here()                         # pricemem records the price tags
            return True
        return self.go_toward_mask(lv, mask)
