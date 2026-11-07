"""Message patterns that more than one domain reads, or that several modules read in near the same way -- side by
side here, named by what they mean. Each keeps the exact pattern of the module that reads it; how they differ is
noted, so the readings can be merged knowingly later."""
import re

# ---------------------------------------------------------------- a monster attacks us (mhitu.c)
# MELEE_BY_NAME_RE (perception.msg_peace: a peaceful-looking monster attacked us): who it was -- group 1 / 2 the
#   attacker, at the start of a sentence: "The <name>" or a proper name ("Asidonhopo hits!"); contact verbs ending
#   in '!', or touches / engulfs / squeezes / charms / grabs you. Monster-vs-monster lines name their target
#   without '!' and do not match.
MELEE_BY_NAME_RE = re.compile(r"(?:^|[.!?]\s+)(The [^.!?]+?|[A-Z][\w'-]*(?: [\w'-]+)*?) (?:hits|bites|misses|just misses|stings|"
                              r"kicks|butts|claws|scratches|lashes|tickles|stabs|pummels|whips|gores)!|"
                              r"(?:^|[.!?]\s+)(The [^.!?]+?|[A-Z][\w'-]*(?: [\w'-]+)*?) (?:touches|engulfs|squeezes|charms|grabs) you")
# MELEE_ON_US_RE (combat.msg_combat -> hallu_strike: something hit us in melee this turn): only "The <name> <verb>!",
#   anywhere in the line (hallucinating, the name is random); thrusts / swings / grabs too, no proper names.
#   Monster-vs-monster and missiles read differently ("The gnome hits the jackal.", "You are hit by a dart.").
MELEE_ON_US_RE = re.compile(r"\bThe [^.!]+? (?:hits|bites|misses|just misses|stings|kicks|butts|claws|scratches|"
                            r"thrusts|swings|grabs|lashes|tickles|stabs|pummels|whips|touches you|engulfs you|"
                            r"squeezes you|gores|charms you)!")
# UNSEEN_ATTACK_RE (combat.msg_combat -> blind_strike): "It <verb>" -- a monster we can't see attacked us; mhitu.c
#   marks its square with an 'I' the same turn. No '!' needed, hugs too.
UNSEEN_ATTACK_RE = re.compile(r"\bIt (?:hits|bites|misses|just misses|touches you|stings|kicks|butts|claws|scratches|"
                              r"thrusts|swings|grabs|hugs|lashes|squeezes|engulfs|tickles|stabs|pummels|whips)\b")
# ATTACKER_NAME_RE (threats.msg_threat: the track of that name attacked): the name of any monster attacking, melee or
#   ranged (shoots, throws, zaps, breathes, casts, spits, gazes, ...); no '!' needed, so a monster-vs-monster line
#   matches too (the tracker only follows names in view).
ATTACKER_NAME_RE = re.compile(r"\bThe ([a-zA-Z' -]+?) (?:hits|misses|bites|stings|kicks|butts|touches|claws|thrusts|swings|"
                              r"shoots|throws|zaps|breathes|casts|spits|gazes|engulfs|squeezes|lashes|tentacles|"
                              r"just misses|strikes)\b")

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
