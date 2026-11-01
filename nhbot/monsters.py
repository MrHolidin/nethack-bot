"""Monster data derived from NetHack 3.6.6 (permonst, monst.c attacks) and the bot's monster lists."""
import nle.nethack as nh

from nhbot.monattacks import ATTACKS


NEVER_MELEE = {"floating eye", "gas spore", "cockatrice", "chickatrice",
               "blue jelly", "spotted jelly", "ochre jelly", "brown mold", "green mold"}

PASSIVE_MOLDS = {"yellow mold", "green mold", "brown mold", "red mold", "lichen" and "", "violet fungus" and ""}
PASSIVE_MOLDS.discard("")

ALWAYS_AVOID = {"gas spore", "cockatrice", "chickatrice", "brown mold", "green mold"}   # even when desperate

RANGED_TARGETS = {"floating eye", "gas spore", "blue jelly", "spotted jelly",
                  "ochre jelly", "brown mold", "green mold", "cockatrice", "chickatrice"}

# eat.c cannibal test / were.c were_beastie(): the animals that count as our kind once infected
WERE_KIN = {"werejackal": {"jackal", "fox", "coyote", "werejackal"},
            "wererat": {"sewer rat", "giant rat", "rabid rat", "wererat"},
            "werewolf": {"wolf", "warg", "winter wolf", "werewolf"}}

# monflag.h (NetHack 3.6)
M1_ACID, M1_POIS = 0x08000000, 0x10000000

M2_UNDEAD, M2_WERE, M2_SHAPESHIFTER = 0x2, 0x4, 0x4000
M2_STALK = 0x01000000          # follows you up and down stairs
M1_NOHANDS = 0x00002000

RACE_FLAG = {"human": 0x8, "elf": 0x10, "elven": 0x10, "dwarf": 0x20, "dwarven": 0x20,
             "gnome": 0x40, "gnomish": 0x40, "orc": 0x80, "orcish": 0x80}

NEVER_EAT = {"cockatrice", "chickatrice", "Medusa", "green slime", "little dog", "dog", "large dog",
             "kitten", "housecat", "large cat", "Death", "Pestilence", "Famine"}

PM_BY_NAME = {nh.permonst(i).mname: nh.permonst(i) for i in range(nh.NUMMONS)}


# hurt us only when we hit them (a passive attack and no active one): molds, jellies, acid blob, floating eye.
# A shrieker has no attack at all: hitting it is free.
PASSIVE_DMG = {nh.permonst(i).mname for i in range(nh.NUMMONS)
               if ATTACKS[i] and all(a[0] == "NONE" for a in ATTACKS[i])}


THIEVES = ("water nymph", "wood nymph", "mountain nymph", "monkey")

NYMPHS = ("water nymph", "wood nymph", "mountain nymph")

SWARMERS = {"killer bee", "soldier ant", "fire ant", "giant ant"}

# =====================================================================================
# elb2: Elbereth as measured in NLE 3.6.6 wizard mode
#   - while you stand on a correctly spelled Elbereth, monsters that respect it never melee you
#   - it survives waiting; your first melee attack (and usually a throw) erases it
#   - ~1 in 5 finger engravings is misspelled and does nothing -> always read it back
# =====================================================================================
ELB_IGNORE_NAMES = {"minotaur", "shopkeeper", "guard", "watchman", "watch captain", "aligned priest",
                    "high priest", "Oracle"}

B_HUMAN_MLET = next(nh.permonst(i).mlet for i in range(nh.NUMMONS) if nh.permonst(i).mname == "human")

B_ANGEL_MLET = next(nh.permonst(i).mlet for i in range(nh.NUMMONS) if nh.permonst(i).mname == "Angel")

VALK_RANKS = {"stripling", "skirmisher", "fighter", "man-at-arms", "woman-at-arms", "warrior",
              "swashbuckler", "hero", "heroine", "champion", "lord", "lady"}

def permonst_of(g):
    m = nh.glyph_to_mon(int(g))
    return nh.permonst(m) if 0 <= m < nh.NUMMONS else None
