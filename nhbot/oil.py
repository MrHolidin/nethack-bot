"""Potions of oil told apart and used on rust (A/B oil: 81k -1181 [-2307, -45], 82k +1328 [+224, +2406] -- the games
only lighting one, 2 turns, swing with chance; the games mending: +441 / +452, median +1739 / +3014; accepted).
Test: with nothing hostile in view (a housekeeping job), every unidentified potion of ours of a look not yet tried is
applied -- only oil can be (apply.c doapply: any other potion is "Sorry, I don't know how to use that.", no time
taken); oil lights ("You light ... potion", the type made known: apply.c light_cocktail) and is snuffed at once by a
second apply (a stack lights one potion split off: the lit one is the one snuffed). Oil known already -- a Valkyrie
starting with an oil lamp knows it (u_init.c ini_inv) -- the game won't offer any other potion ("That is a silly
thing to use or apply.", apply.c setapplyclasses): the test is over (81190 looped on it 99338 times).
Rust: the weapon in our hands rusty or corroded, a potion of oil not known cursed -- #dip the weapon into it, one
level of rust and one of corrosion off a dip (potion.c dodip; not burnt, not ammo; a cursed potion spills instead:
slippery fingers, d(2,10) turns); again while some is left. With no Excalibur (rustproof, never needs it) one stack
of oil not known cursed is kept (carry.needed: never dropped for weight or sold)."""

from collections import Counter

import nle.nethack as nh

from nhbot.pricemem import appearance

LIT = "(lit)"
AMMO_WORDS = ("arrow", "crossbow bolt")  # objclass is_ammo: oil does not mend them (potion.c dodip)
ERODED_WORDS = ("rusty", "corroded")
NOT_TESTED = ("clear",)                  # water's fixed look: never oil


class OilState:
    """State of the oil test and rust repair (OilMixin)."""
    def __init__(self):
        self.tried = set()                # potion looks applied that would not light
        self.known = False                # oil known by name: no potion of another look can be oil
        self.stats = Counter()


class OilMixin:
    def oil_init(self):
        self.oil = OilState()

    def oil_summary(self):
        """Game summary entries."""
        return {"oil": dict(self.oil.stats)}

    def oil_test_step(self):
        """Housekeeping: apply the untried unidentified potions (module notes). True if it used game time."""
        if self.oil.known:
            return False
        for it in self.items():
            if it.ocls != nh.POTION_CLASS or it.unpaid:
                continue
            look = appearance(it.text)
            if look is None or look[1] in NOT_TESTED or look[1] in self.oil.tried:
                continue
            self.cur_act = "oil_test"
            seq0 = self.msg_seq
            if not self.ask("a", "apply"):
                return False
            self.press(it.letter)
            said = self.text_since(seq0)
            if "You light" in said:
                self.oil.stats["oil_found"] += 1
                self.oil_snuff()
                return True
            self.settle()
            if "silly thing" in said:
                self.oil.known = True             # oil known: no other potion is offered
                self.oil.stats["oil_known"] += 1
                return False
            self.oil.tried.add(look[1])           # "don't know how to use that" -- or anything else: not again
            self.oil.stats["not_oil" if "know how to use" in said else "unclear"] += 1
        return False

    def oil_snuff(self):
        lit = next((it for it in self.items() if it.ocls == nh.POTION_CLASS and LIT in it.text), None)
        if lit is None or not self.ask("a", "apply"):
            return
        self.press(lit.letter)
        self.oil.stats["snuffed"] += 1

    def oil_needed(self, it):
        """carry.needed: it is the one stack of oil we keep (module notes)."""
        if it.ocls != nh.POTION_CLASS or " of oil" not in it.text:
            return False
        items = self.items()
        if any("Excalibur" in x.text for x in items):
            return False
        keep = next((x for x in items if x.ocls == nh.POTION_CLASS and " of oil" in x.text and LIT not in x.text
                     and not x.cursed and not x.unpaid), None)
        return keep is not None and keep.letter == it.letter

    def oil_fix_step(self):
        """Housekeeping: the rusty / corroded weapon in our hands dipped into a potion of oil (module notes). True
        if it used the turn."""
        weapon = next((it for it in self.items() if it.wielded), None)
        if weapon is None or not any(w in weapon.text for w in ERODED_WORDS) \
                or not (weapon.ocls == nh.WEAPON_CLASS or weapon.ocls == nh.TOOL_CLASS and "pick-axe" in weapon.text) \
                or any(w in weapon.text for w in AMMO_WORDS):
            return False
        oil = next((it for it in self.items() if it.ocls == nh.POTION_CLASS and "potion of oil" in it.text
                    and LIT not in it.text and not it.cursed and not it.unpaid), None)
        if oil is None:
            return False
        self.cur_act = "oil_fix"
        seq0 = self.msg_seq
        self.raw_step(228)                        # M-d: #dip
        if "dip" not in self.message().lower():
            self.settle()
            return True
        self.raw_step(ord(weapon.letter))
        if self.obs["misc"][0] and "into the" in self.message():
            self.raw_step(ord("n"))               # not into the fountain / pool here
        if "dip" in self.message().lower() and "into" in self.message().lower():
            self.raw_step(ord(oil.letter))
        self.settle()
        said = self.text_since(seq0)
        self.oil.stats["fixed" if "less" in said else "dip_other"] += 1
        return True
