"""Monster data derived from NetHack 3.6.6 (permonst, monst.c attacks) and the bot's monster lists."""
import nle.nethack as nh

from nhbot.monattacks import ATTACKS


NEVER_MELEE = {"floating eye", "gas spore", "cockatrice", "chickatrice",
               "blue jelly", "spotted jelly", "ochre jelly", "brown mold", "green mold"}

PASSIVE_MOLDS = {"yellow mold", "green mold", "brown mold", "red mold"}

ALWAYS_AVOID = {"gas spore", "cockatrice", "chickatrice", "brown mold", "green mold"}   # even when desperate

RANGED_TARGETS = {"floating eye", "gas spore", "blue jelly", "spotted jelly",
                  "ochre jelly", "brown mold", "green mold", "cockatrice", "chickatrice"}

# eat.c cannibal test / were.c were_beastie(): the animals that count as our kind once infected
WERE_KIN = {"werejackal": {"jackal", "fox", "coyote", "werejackal"},
            "wererat": {"sewer rat", "giant rat", "rabid rat", "wererat"},
            "werewolf": {"wolf", "warg", "winter wolf", "werewolf"}}

# monflag.h (NetHack 3.6)
M1_NOHANDS, M1_MINDLESS, M1_ANIMAL = 0x00002000, 0x00010000, 0x00040000
M1_REGEN = 0x00800000
M1_ACID, M1_POIS = 0x08000000, 0x10000000

M2_UNDEAD, M2_WERE = 0x2, 0x4
M2_HUMAN, M2_ELF, M2_DWARF, M2_GNOME, M2_ORC = 0x8, 0x10, 0x20, 0x40, 0x80
M2_MINION, M2_SHAPESHIFTER = 0x1000, 0x4000
M2_HOSTILE, M2_PEACEFUL = 0x00100000, 0x00200000
M2_STALK = 0x01000000          # follows you up and down stairs
# a liking for objects: M2_GREEDY | M2_JEWELS | M2_COLLECT | M2_MAGIC
M2_LIKES_OBJS = 0x10000000 | 0x20000000 | 0x40000000 | 0x80000000

MS_LEADER, MS_NEMESIS, MS_GUARDIAN = 31, 32, 33     # monflag.h msound: the quest's leader, nemesis, guardians

# monst.h mresists / mconveys bits, by the resistance's name (as our_resists names it)
MR_FIRE, MR_COLD, MR_SLEEP, MR_DISINT, MR_ELEC, MR_POISON = 0x01, 0x02, 0x04, 0x08, 0x10, 0x20
MR_BITS = {"fire": MR_FIRE, "cold": MR_COLD, "sleep": MR_SLEEP, "disint": MR_DISINT, "shock": MR_ELEC,
           "poison": MR_POISON}

# our race (the ^X line's word) -> its M2 flag, and role.c races[]: (lovemask, hatemask)
RACE_FLAG = {"human": M2_HUMAN, "elf": M2_ELF, "elven": M2_ELF, "dwarf": M2_DWARF, "dwarven": M2_DWARF,
             "gnome": M2_GNOME, "gnomish": M2_GNOME, "orc": M2_ORC, "orcish": M2_ORC}
RACE_MASKS = {"human": (0, M2_GNOME | M2_ORC), "elf": (M2_ELF, M2_ORC), "elven": (M2_ELF, M2_ORC),
              "dwarf": (M2_DWARF | M2_GNOME, M2_ORC), "dwarven": (M2_DWARF | M2_GNOME, M2_ORC),
              "gnome": (M2_DWARF | M2_GNOME, M2_HUMAN), "gnomish": (M2_DWARF | M2_GNOME, M2_HUMAN),
              "orc": (0, M2_HUMAN | M2_ELF | M2_DWARF), "orcish": (0, M2_HUMAN | M2_ELF | M2_DWARF)}

NEVER_EAT = {"cockatrice", "chickatrice", "Medusa", "green slime", "little dog", "dog", "large dog",
             "kitten", "housecat", "large cat", "Death", "Pestilence", "Famine"}

# name -> permonst index. The three lycanthropes have two kinds of one name (the animal, then the @): PM_INDEX and
# PM_BY_NAME hold the last of them (the @), PM_INDICES every one in index order.
PM_INDEX = {nh.permonst(i).mname: i for i in range(nh.NUMMONS)}
PM_INDICES = {}
for _i in range(nh.NUMMONS):
    PM_INDICES.setdefault(nh.permonst(_i).mname, []).append(_i)
PM_BY_NAME = {name: nh.permonst(i) for name, i in PM_INDEX.items()}

S_HUMAN, S_ANGEL = PM_BY_NAME["human"].mlet, PM_BY_NAME["Angel"].mlet      # monster classes '@' and 'A'

# Monsters that may carry things -- dropped where they die, under the corpse (mon.c: relobj, then make_corpse):
# a weapon attack (makemon.c m_initweap arms them) or a liking for objects (M2_LIKES_OBJS).
CARRIERS = {nh.permonst(i).mname for i in range(nh.NUMMONS)
            if nh.permonst(i).mflags2 & M2_LIKES_OBJS or any(a[0] == "WEAP" for a in ATTACKS[i])}


# hurt us only when we hit them (a passive attack and no active one): molds, jellies, acid blob, floating eye.
# A shrieker has no attack at all: hitting it is free.
PASSIVE_DMG = {nh.permonst(i).mname for i in range(nh.NUMMONS)
               if ATTACKS[i] and all(a[0] == "NONE" for a in ATTACKS[i])}

# no active attack: only passive ones (molds, jellies, floating eye, acid blob), an explosion when killed
# (gas spore), the Oracle, a long worm's tail. Most of them never move (mmove 0); the floating eye (speed 1), gas
# spore and acid blob (speed 3) do, slowly.
# Not the shrieker: no attack, but next to us it shrieks every move (mon.c m_respond): wakes the level, and
# one shriek in 10 creates a monster (1 in 13 of those a purple worm).
NO_ACTIVE_ATTACK = {nh.permonst(i).mname for i in range(nh.NUMMONS)
                    if all(a[0] in ("NONE", "BOOM") for a in ATTACKS[i])} - {"shrieker"}

# passive_immune: the monsters whose only attack is a passive cold / fire one -- uhitm.c passive(): with the
# resistance it does no damage (shieldeff, "You feel a mild chill" / "You're not affected"), nothing else
# (brown mold, blue jelly: cold; red mold: fire)
PASSIVE_ELEMENT = {"COLD": "cold", "FIRE": "fire"}
PASSIVE_KIND = {nh.permonst(i).mname: PASSIVE_ELEMENT[ATTACKS[i][0][1]] for i in range(nh.NUMMONS)
                if ATTACKS[i] and all(a[0] == "NONE" for a in ATTACKS[i]) and ATTACKS[i][0][1] in PASSIVE_ELEMENT}


THIEVES = ("water nymph", "wood nymph", "mountain nymph", "monkey")

SWARMERS = {"killer bee", "soldier ant", "fire ant", "giant ant"}

# =====================================================================================
# elb2: Elbereth as measured in NLE 3.6.6 wizard mode
#   - while you stand on a correctly spelled Elbereth, monsters that respect it never melee you
#   - it survives waiting; your first melee attack (and usually a throw) erases it
#   - each letter engraved in the dust is garbled 1 in 25 (engrave.c doengrave): ~28% of Elbereths are misspelled
#     and do nothing -> always read it back
# =====================================================================================


def permonst_of(g):
    m = nh.glyph_to_mon(int(g))
    return nh.permonst(m) if 0 <= m < nh.NUMMONS else None
