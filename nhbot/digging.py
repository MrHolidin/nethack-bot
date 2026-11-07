"""Digging, for vault_rob / vault_find (nhbot.vault) and dig_through (nhbot.digthrough): which digger we have (a wand
of digging, a pick-axe, a dwarvish mattock), the pick-axe / mattock into our hands and the weapon back after
(weapons.swap_in / swap_back, job "dig"), applying it in a direction."""
import nle.nethack as nh


class DiggingMixin:
    def digging_init(self):
        self.dig_refused = set()       # level keys whose floor would not be dug ("too hard to dig in"), or where a
                                       # cursed shield keeps a mattock out of our hands (dig_wield)

    def dig_means(self):
        """How we can dig down: ("wand", item) a wand of digging with charges left, ("pick", item) a pick-axe,
        ("mattock", item) a dwarvish mattock -- none known cursed (a cursed digger applied stays welded), no
        digger while a cursed weapon is welded to our hand. None."""
        items = self.items()
        wand = next((it for it in items if it.ocls == nh.WAND_CLASS and "wand of digging" in it.text
                     and ":0)" not in it.text and "cancelled" not in it.text), None)
        welded = any(it.wielded and it.cursed and "pick-axe" not in it.text and "mattock" not in it.text
                     for it in items)             # a cursed weapon in hand: no digger can be wielded (wield.c)
        pick = None if welded else next((it for it in items if "pick-axe" in it.text and not it.cursed), None)
        mattock = None if welded else next((it for it in items if "dwarvish mattock" in it.text and not it.cursed),
                                           None)
        if pick is not None:
            return "pick", pick
        if wand is not None:
            return "wand", wand
        if mattock is not None:
            return "mattock", mattock
        return None

    def dig_wield(self, lv, means):
        """The pick-axe / mattock into our hands (the weapon back later: dig_unwield; a mattock: the shield off
        first). True if it used the turn."""
        kind, it = means
        if it.wielded:
            return False
        shield = next((a for a in self.armor_inventory() if a["worn"] and a["slot"] == "shield"), None)
        if kind == "mattock" and shield is not None:
            if not self.take_off(shield):             # a two-handed digger: not with a shield on (wield.c)
                self.dig_refused.add(lv.key)          # a cursed shield: no mattock
            return True
        self.swap_in("dig", it)
        return True

    def dig_unwield(self):
        """The weapon back in our hands after digging (weapons.swap_back, job "dig"). True if it used the turn."""
        return self.swap_back("dig")

    def apply_digger(self, it, key):
        """Apply the wielded digger in direction key (">" down). The text the game answered; None: no apply."""
        seq0 = self.msg_seq
        if not self.ask("a", "apply"):
            return None
        self.press(it.letter, expect_prompt=True)
        if "direction" in self.message().lower():
            self.press(key)
        else:
            self.settle()
        return self.text_since(seq0)
