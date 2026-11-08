"""The message event layer: each logged message is parsed here once into typed events, and game.on_message hands the
Message to the domains in a fixed order.

Events are the fight facts handlers count or read in more than one place: our blows and kills, the attacks on us,
monsters' weapons, missiles, wands and breath, our items destroyed, thefts, a weapon skill advance. A domain that
tests fixed phrases of its own (the prayer outcome, the vault guard, doors, traps and stairs, shops, polymorph, ...)
reads Message.text.

A repeat (Message.repeat, decided in game.log_msg) is a message NLE shows again although the game did not say it
again. After a key the game reads before it clears the message window -- a command prefix such as 'F' (cmd.c:5857-5864
parse reads the next key, then clear_nhwindow) or a count's first digit (cmd.c:5760-5770 get_count clears it only from
the second digit on) -- the observation still holds the old top line (winrl.cc:348-351 copies toplines while
ttyDisplay->toplin)."""
import re
from typing import NamedTuple, Optional

import nle.nethack as nh

from nhbot.monsters import THIEVES

# the keys after which NLE shows the top line again (module docstring): 'F' (cmd.c:5023-5033 prefix_cmd; the only
# prefix the bot sends) and the digits of a count
RESHOW_KEYS = frozenset([ord("F")] + [ord(c) for c in "0123456789"])


class Message:
    """One logged message: its text, whether NLE showed it again (repeat: module docstring), its events."""
    __slots__ = ("text", "repeat", "events")

    def __init__(self, text, repeat):
        self.text, self.repeat, self.events = text, repeat, parse(text)

    def all(self, kind):
        """The events of this kind, in the order of the text."""
        return [e for e in self.events if type(e) is kind]


# ---------------------------------------------------------------- our own blows and kills (uhitm.c, mon.c)
class OurBlow(NamedTuple):
    """A melee blow of ours, landed or not: "You hit / smite %s" (uhitm.c hmon_hitmon), "You miss %s." (uhitm.c:2340),
    "You strike %s from behind!" (uhitm.c:778), polymorphed "You bite / kick / butt / sting / touch" (uhitm.c hmonas);
    also "You kick at empty space." and the like (dokick.c), read the same."""
    verb: str


class Kill(NamedTuple):
    """We killed a monster: mon.c:2350-2355 xkilled "You kill / destroy %s!". name: from after the article up to the
    first '!' ("it" unseen); None without a '!' after it ("You destroy the bear trap with ..." dig.c:340, also read
    as a kill)."""
    name: Optional[str]


OUR_BLOW_RE = re.compile(r"\bYou (hit|miss|smite|strike|bite|kick|butt|sting|touch|kill|destroy)\b")
KILLED_RE = re.compile(r"You (?:kill|destroy) (?:the |an? )?(.+?)!")
KILL_VERBS = ("kill", "destroy")


# ---------------------------------------------------------------- attacks on us: one table, one parser
class Attacked(NamedTuple):
    """A monster attacks US: who "The <name>", "It" (unseen), "Something" or a proper name (a shopkeeper, a priest);
    how "melee" / "ranged" (ATTACK_ON_US_VERBS)."""
    who: str
    how: str

    @property
    def monster(self):
        """'The jackal' -> 'jackal'; None for It / Something / a proper name."""
        return self.who[4:] if self.who.startswith("The ") else None


# How the game tells that a monster attacks US, subject first. A monster-vs-monster line (mhitm.c) names its target
# after the verb and has no '!' right after it: "The jackal bites the little dog.", "The gnome swings her axe at the
# jackal.", "The kobold throws a dart at the newt!" -- those are not attacks on us. (Four regexes read this before and
# disagreed on exactly that: A/B attacked_us.)
ATTACK_ON_US_VERBS = (
    # melee -- mhitu.c:46-75 hitmsg, :92 missmu, :40-43 a seduction, :100-108 mswings (no "at <target>", which
    # mhitm.c:1566-1576 mswingsm adds), :980 a hug, :1818 an engulf, steal.c:413
    ("melee", r"(?:hits|misses|just misses|bites|stings|butts)!|kicks[!.]|touches you!|grabs you!|engulfs you!|"
              r"charms you\.|(?:smiles at|talks to) you\b|pretends to be friendly\.|"
              r"(?:thrusts|swings) (?:one of )?(?:his|her|its) (?:(?! at )[^.!?])+\."),
    # melee, the subject possessive (hitmsg AT_TENT)
    ("melee", r"tentacles suck you!"),
    # ranged -- mthrowu.c:277-279 monshoot ("at <target>" only at a monster), :782 / :827 venom and breath (the same
    # line at a monster: counted, as before), mcastu.c:249 / :263 / :858, muse.c:186
    ("ranged", r"(?:shoots|throws) (?:(?! at )[^!?])+!|zaps (?!(?:him|her|it)self)(?:you with )?(?:an? |the )?[^!?]*!|breathes [^!?]+!|"
               r"spits venom!|casts (?:a spell|at )"),
)
ATTACK_ON_US_RE = re.compile(
    r"(?:^|(?<=[.!?])\s+)(?P<who>The [^.!?]+?|It|Something|(?!You\b|Your\b)[A-Z][\w'-]*(?: [A-Z][\w'-]*)*?)(?:'s?)? "
    r"(?:" + "|".join(f"(?P<{kind}{i}>{pat})" for i, (kind, pat) in enumerate(ATTACK_ON_US_VERBS)) + ")")


# ---------------------------------------------------------------- monsters' melee lines and weapons
class MonMelee(NamedTuple):
    """A melee line of a monster, at us or at another monster: who "It" (unseen) or "The <name>"; bang: a '!' right
    after the verb -- "The X hits!" / "misses!" is at us (mhitu.c hitmsg default, missmu), at a monster the target
    follows the verb (mhitm.c)."""
    who: str
    verb: str
    bang: bool


class MonWeapon(NamedTuple):
    """A seen monster swings / thrusts / wields a weapon (mhitu.c:100-106 mswings, a seen monster's weapon attack
    says it first; mhitm.c:1566-1576 mswingsm; weapon.c mon_wield_item): its name and the weapon's words."""
    name: str
    weapon: str


MON_MELEE_RE = re.compile(r"\b(It|The [a-zA-Z' -]+?) (hits|bites|stings|butts|touches you|kicks|misses|just misses)\b(!?)")
MON_WEAPON_RE = re.compile(r"The ([a-zA-Z' -]+?) (?:swings|thrusts|wields) (?:his|her|its|an?|the|\d+)? ?([a-z' -]+?)[.!]")


# ---------------------------------------------------------------- shot at, monsters' missiles, wands and breath
class ShotAt(NamedTuple):
    """Somebody attacked us from a distance (mthrowu.c monshoot / thitu, zap.c buzz, muse.c), seen or not -- not an
    arrow / dart / rock trap, which prints the same 'You are hit by' lines; shooter: the name of a seen one with any
    ranged verb, else None."""
    shooter: Optional[str]


class MonZap(NamedTuple):
    """"The X zaps a wand of K!" / "zaps a <look> wand!": the zapper and the wand's words."""
    name: str
    wand: str


class MonVolley(NamedTuple):
    """"The X shoots / throws 2 orcish arrows!": the shooter, the count word (a number, a / an / the), the missile."""
    name: str
    count: str
    missile: str


class MonBreath(NamedTuple):
    """"The X breathes ...": the breather."""
    name: str


class RaySeen(NamedTuple):
    """A ray / wand effect named in the message (RAY_SEEN: the first phrase found): its wand kind."""
    kind: str


SHOT_AT_RE = re.compile(r"(?:throws|shoots) |zaps (?:a|an|the) |You are (?:almost )?hit by |You are hit!|misses you\.|"
                        r"whizzes by you|hits you!|crashes on your head|You hear a nearby zap")
TRAP_SHOT_RE = re.compile(r"trap|shoots out at you|falls on your head|from the ceiling")
SHOOTER_RE = re.compile(r"The ([a-z][a-z' -]*?) (?:zaps|shoots|throws|hurls|fires|spits|breathes)")
MON_ZAPS_RE = re.compile(r"\bThe ([a-zA-Z' -]+?) zaps (?:an? |the )?([a-z' -]*?wand(?: of [a-z ]+)?)!")
MON_SHOOTS_RE = re.compile(r"\bThe ([a-zA-Z' -]+?) (?:shoots|throws) (\d+|an?|the) ([a-z' -]+?)!")
MON_BREATHES_RE = re.compile(r"\bThe ([a-zA-Z' -]+?) breathes ")
RAY_SEEN = (("sleep ray", "sleep"), ("bolt of fire", "fire"), ("bolt of cold", "cold"),
            ("bolt of lightning", "lightning"), ("magic missile", "magic missile"), ("death ray", "death"),
            ("The wand hits you", "striking"), ("The wand misses you", "striking"), ("Boing!", "striking"))


# ---------------------------------------------------------------- our items destroyed, thefts, skill
class ItemDestroyed(NamedTuple):
    """One of our stacks lost one or more units (zap.c:4797-4805 destroy_strings, 4920-4922 destroy_one_item
    "%s %s %s!"): its words and its object class (a glob of green slime boiling: food)."""
    name: str
    cls: int


class Stolen(NamedTuple):
    """"She stole a +0 orcish helm." / "It steals ...!": what was taken (any thief, a polymorph)."""
    what: str


class Theft(NamedTuple):
    """A thief robbed or charmed us (a nymph or monkey named, "She / He stole", "It stole / steals", "She charms
    you"): at most one per message."""


class SkillAdvanced(NamedTuple):
    """"You are now more / most skilled in <skill>." (weapon.c:1138 skill_advance)."""
    skill: str


DESTROY_RE = re.compile(r"\b(?:Your|One of your|Some of your|Both of your|All of your) (.+?) (freezes? and shatters?|"
                        r"boils? and explodes?|ignites? and explodes?|catch(?:es)? fire and burns?|"
                        r"turns to dust and vanishes|breaks apart and explodes)!")
DESTROY_VERB_CLASS = {"free": nh.POTION_CLASS, "boil": nh.POTION_CLASS, "igni": nh.POTION_CLASS,
                      "turn": nh.RING_CLASS, "brea": nh.WAND_CLASS}       # "catch": a scroll or a spellbook
STOLE_RE = re.compile(r"\b(?:stole|steals) (.+?)[.!](?:\s|$)")
STOLE_WORD_RE = re.compile(r"\b(stole|steals|stolen)\b")
SKILL_RE = re.compile(r"You are now (?:more|most) skilled in ([a-z -]+)\.")


def parse(m):
    """The events of one message text."""
    ev = []
    for mm in OUR_BLOW_RE.finditer(m):
        verb = mm.group(1)
        if verb in KILL_VERBS:
            mk = KILLED_RE.match(m, mm.start())
            ev.append(Kill(mk.group(1) if mk else None))
        else:
            ev.append(OurBlow(verb))
    for mm in ATTACK_ON_US_RE.finditer(m):
        kind = next(k for k, v in mm.groupdict().items() if v is not None and k != "who")
        ev.append(Attacked(mm.group("who"), kind.rstrip("0123456789")))
    ev.extend(MonMelee(who, verb, bool(bang)) for who, verb, bang in MON_MELEE_RE.findall(m))
    ev.extend(MonWeapon(name, weapon) for name, weapon in MON_WEAPON_RE.findall(m))
    if SHOT_AT_RE.search(m) and not TRAP_SHOT_RE.search(m):
        mm = SHOOTER_RE.search(m)
        ev.append(ShotAt(mm.group(1) if mm else None))
    ev.extend(MonZap(name, wand) for name, wand in MON_ZAPS_RE.findall(m))
    ray = next((k for phrase, k in RAY_SEEN if phrase in m), None)
    if ray is not None:
        ev.append(RaySeen(ray))
    ev.extend(MonVolley(name, count, what) for name, count, what in MON_SHOOTS_RE.findall(m))
    ev.extend(MonBreath(name) for name in MON_BREATHES_RE.findall(m))
    for name, verb in DESTROY_RE.findall(m):
        cls = nh.FOOD_CLASS if "glob" in name else \
            DESTROY_VERB_CLASS.get(verb[:4], nh.SPBOOK_CLASS if "spellbook" in name else nh.SCROLL_CLASS)
        ev.append(ItemDestroyed(name, cls))
    ev.extend(Stolen(what) for what in STOLE_RE.findall(m))
    robbed = (STOLE_WORD_RE.search(m) or "charms you" in m) and \
        (any(t in m for t in THIEVES) or "She stole" in m or "He stole" in m)
    if robbed or "It stole" in m or "It steals" in m or "She charms you" in m:
        ev.append(Theft())
    ev.extend(SkillAdvanced(skill) for skill in SKILL_RE.findall(m))
    return ev
