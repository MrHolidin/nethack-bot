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

WIELD_RE = re.compile(r"\((?:tethered )?weapon in (\w+)")
CURSED_RE = re.compile(r"\bcursed\b")               # not "uncursed"


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
