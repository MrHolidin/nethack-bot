"""Digging, for vault_rob / vault_find (nhbot.vault) and dig_through (nhbot.digthrough): which digger we have (a wand
of digging, a pick-axe, a dwarvish mattock), the pick-axe / mattock into our hands and the weapon back after
(weapons.swap_in / swap_back, job "dig"), applying it in a direction."""
import nle.nethack as nh

from nhbot.consts import DELTA2KEY


class DiggingState:
    """State of digging down (DiggingMixin)."""
    def __init__(self):
        self.refused = set()           # level keys whose floor would not be dug ("too hard to dig in"), or where a
                                       # cursed shield keeps a mattock out of our hands (dig_wield)
        self.shield_off = -10          # turn a shield came off for the mattock (dig_wield, dig_needs_hands)


class DiggingMixin:
    def digging_init(self):
        self.digging = DiggingState()

    def dig_refused_here(self, lv):
        """The floor of lv would not be dug ("too hard to dig in", "cannot reach the floor"): never tried again."""
        self.digging.refused.add(lv.key)

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

    def dig_hand_means(self):
        """dig_means' pick-axe or mattock (not a wand of digging: its ray digs on past the square we want, zap.c
        zap_dig), or None."""
        means = self.dig_means()
        if means is not None and means[0] != "wand":
            return means
        items = self.items()
        welded = any(it.wielded and it.cursed and "pick-axe" not in it.text and "mattock" not in it.text
                     for it in items)
        mattock = None if welded else next((it for it in items if "dwarvish mattock" in it.text and not it.cursed),
                                           None)
        return ("mattock", mattock) if mattock is not None else None

    def dig_at(self, lv, target, means):
        """One apply of the pick-axe / mattock (wielded first: dig_wield) toward the adjacent square target -- dig.c
        dig: a rock or wall square becomes a passage over several turns, an occupation that goes on by itself. The
        text the game answered; None: no apply this turn (wielding took it, or no apply)."""
        if self.dig_wield(lv, means):
            return None
        y, x = self.pos()
        return self.apply_digger(means[1], DELTA2KEY[(target[0] - y, target[1] - x)])

    def dig_wield(self, lv, means):
        """The pick-axe / mattock into our hands (the weapon back later: dig_unwield; a mattock: the shield off
        first). True if it used the turn."""
        kind, it = means
        if it.wielded:
            return False
        shield = next((a for a in self.armor_inventory() if a["worn"] and a["slot"] == "shield"), None)
        if kind == "mattock" and shield is not None:
            if not self.take_off(shield):             # a two-handed digger: not with a shield on (wield.c)
                self.digging.refused.add(lv.key)          # a cursed shield: no mattock
            self.digging.shield_off = self.turn()
            return True
        self.swap_in("dig", it)
        return True

    def dig_needs_hands(self):
        """equipment.slot_allowed: a shield just came off for the mattock, not worn again before it is wielded (then
        two_handed keeps it off) -- A/B mattock_shield (digging with a mattock went round taking the shield off and
        putting it back on: 79611)."""
        return self.opts.mattock_shield and self.turn() - self.digging.shield_off <= 2

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
