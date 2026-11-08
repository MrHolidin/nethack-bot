"""Message patterns that more than one domain reads, or that several modules read in near the same way -- side by
side here, named by what they mean. Each keeps the exact pattern of the module that reads it; how they differ is
noted, so the readings can be merged knowingly later."""
import re

# ---------------------------------------------------------------- attacks on us: one table, one parser
# How the game tells that a monster attacks US, subject first ("The <name>", "It" unseen, "Something", a proper name
# -- a shopkeeper, a priest). A monster-vs-monster line (mhitm.c) names its target after the verb and has no '!'
# right after it: "The jackal bites the little dog.", "The gnome swings her axe at the jackal.", "The kobold throws
# a dart at the newt!" -- those are not attacks on us. (Four regexes read this before and disagreed on exactly that:
# A/B attacked_us.)
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


def attacks_on_us(m):
    """The attacks on us a message line tells, [(who, kind)] -- who "The <name>", "It", "Something" or a
    proper name; kind "melee" / "ranged" (ATTACK_ON_US_VERBS)."""
    out = []
    for mm in ATTACK_ON_US_RE.finditer(m):
        kind = next(k for k, v in mm.groupdict().items() if v is not None and k != "who")
        out.append((mm.group("who"), kind.rstrip("0123456789")))
    return out


def attacker_kind(who):
    """'The jackal' -> 'jackal'; None for It / Something / a proper name."""
    return who[4:] if who.startswith("The ") else None

# ---------------------------------------------------------------- shot at from a distance
# SHOT_AT_RE (combat.msg_combat -> last_shot_turn, hunt_shooter): somebody attacked us from a distance (mthrowu.c
#   monshoot / thitu, zap.c buzz, muse.c), seen or not ...
SHOT_AT_RE = re.compile(r"(?:throws|shoots) |zaps (?:a|an|the) |You are (?:almost )?hit by |You are hit!|misses you\.|"
                        r"whizzes by you|hits you!|crashes on your head|You hear a nearby zap")
# ... but arrow / dart / rock traps print the same 'You are hit by' lines (SHOT_AT_RE then does not count)
TRAP_SHOT_RE = re.compile(r"trap|shoots out at you|falls on your head|from the ceiling")
# SHOOTER_RE (combat.msg_combat): the shooter's name for hunt_shooter, any ranged verb
SHOOTER_RE = re.compile(r"The ([a-z][a-z' -]*?) (?:zaps|shoots|throws|hurls|fires|spits|breathes)")
# threats.msg_threat, per kind of ranged attack (ranged_profile): the zapper and its wand, the volley, the breath
MON_ZAPS_RE = re.compile(r"\bThe ([a-zA-Z' -]+?) zaps (?:an? |the )?([a-z' -]*?wand(?: of [a-z ]+)?)!")
MON_SHOOTS_RE = re.compile(r"\bThe ([a-zA-Z' -]+?) (?:shoots|throws) (\d+|an?|the) ([a-z' -]+?)!")
MON_BREATHES_RE = re.compile(r"\bThe ([a-zA-Z' -]+?) breathes ")

# ---------------------------------------------------------------- our own blows and kills (uhitm.c)
# KILL_RE (combat.msg_combat: the kill count) -- a space after the verb; KILLED_RE: the name of what we killed
KILL_RE = re.compile(r"You (kill|destroy) ")
KILLED_RE = re.compile(r"You (?:kill|destroy) (?:the |an? )?(.+?)!")
# KILL_WORD_RE (danger.danger_msg: our hits on it forgotten) -- word boundaries instead of the space
KILL_WORD_RE = re.compile(r"\bYou (?:kill|destroy)\b")
# OUR_HIT_RE (danger.danger_msg: hit_seen) -- a melee blow of ours that landed
OUR_HIT_RE = re.compile(r"\bYou (?:hit|smite|strike|bite|kick|butt|sting|touch)\b")
# ELB_WIPED_RE (elbereth.msg_elbereth): a blow of ours, landed or not, or a kill -- it scuffs the Elbereth under us
#   (uhitm.c u_wipe_engr) -- or mon.c setmangry erased it
ELB_WIPED_RE = re.compile(r"\bYou (?:hit|miss|smite|kill|destroy)\b|The engraving beneath you fades")
