"""Glyph classification tables for NLE (NetHack 3.6.6)."""
import numpy as np
import nle.nethack as nh

# terrain kinds
UNKNOWN, FLOOR, WALL, DOOR_OPEN, DOOR_CLOSED, TRAP, DOWNSTAIR, UPSTAIR, \
    LIQUID, DOORWAY, OBJECT, BOULDER, MONSTER, PET, INVIS, GOLD, CORPSE, EFFECT = range(18)

N = nh.MAX_GLYPH
KIND = np.full(N, EFFECT, dtype=np.int8)

CMAP_KIND = {}
for i in range(nh.MAXPCHARS):
    if i == 0:
        k = UNKNOWN
    elif 1 <= i <= 11:
        k = WALL
    elif i == 12:
        k = DOORWAY          # no door / broken door: diagonal ok
    elif i in (13, 14):
        k = DOOR_OPEN
    elif i in (15, 16):
        k = DOOR_CLOSED
    elif i in (17, 18, 37, 38):  # bars, tree, raised drawbridge
        k = WALL
    elif i in (23, 25):
        k = UPSTAIR
    elif i in (24, 26):
        k = DOWNSTAIR
    elif i in (32, 34, 41):      # water, lava
        k = LIQUID
    elif 42 <= i <= 63:
        k = TRAP
    elif i == 64:
        k = FLOOR
    elif i <= 40:
        k = FLOOR
    else:
        k = EFFECT
    CMAP_KIND[i] = k

BOULDER_OBJ = None
GOLD_OBJ = None
CORPSE_OBJ = None
for o in range(nh.NUM_OBJECTS):
    name = nh.OBJ_NAME(nh.objclass(o))
    if name == "boulder":
        BOULDER_OBJ = o
    elif name == "gold piece":
        GOLD_OBJ = o
    elif name == "corpse":
        CORPSE_OBJ = o

for g in range(N):
    if nh.glyph_is_pet(g):
        KIND[g] = PET
    elif nh.glyph_is_invisible(g) or nh.glyph_is_warning(g):
        KIND[g] = INVIS
    elif nh.glyph_is_monster(g):     # normal, detected, ridden
        KIND[g] = MONSTER
    elif nh.glyph_is_statue(g):
        KIND[g] = BOULDER
    elif nh.glyph_is_body(g):
        KIND[g] = CORPSE
    elif nh.glyph_is_object(g):
        o = nh.glyph_to_obj(g)
        KIND[g] = BOULDER if o == BOULDER_OBJ else GOLD if o == GOLD_OBJ else OBJECT
    elif nh.glyph_is_cmap(g):
        KIND[g] = CMAP_KIND[nh.glyph_to_cmap(g)]
    # swallow/explode/zap stay EFFECT

# kinds that hide the terrain under them (don't overwrite memory)
TRANSIENT = np.zeros(N, dtype=bool)
TRANSIENT[(KIND == MONSTER) | (KIND == PET) | (KIND == INVIS) | (KIND == EFFECT)] = True

PASSABLE_KINDS = {FLOOR, DOOR_OPEN, DOOR_CLOSED, TRAP, DOWNSTAIR, UPSTAIR,
                  DOORWAY, OBJECT, GOLD, CORPSE}
PASSABLE = np.zeros(32, dtype=bool)
for k in PASSABLE_KINDS:
    PASSABLE[k] = True

STONE_GLYPH = nh.GLYPH_CMAP_OFF + 0

_mon_name_cache = {}


def monster_name(g):
    if g in _mon_name_cache:
        return _mon_name_cache[g]
    m = nh.glyph_to_mon(g)
    name = nh.permonst(m).mname if 0 <= m < nh.NUMMONS else "?"
    _mon_name_cache[g] = name
    return name


def monster_letter(g):
    m = nh.glyph_to_mon(g)
    return chr(nh.permonst(m).mlet + 0) if 0 <= m < nh.NUMMONS else "?"


def trap_name(g):
    return nh.symdef.from_idx(nh.glyph_to_cmap(g)).explanation

# '[' piles: armor class is visible to a human (symbol), the exact type is not used
ARMOR_GLYPH = np.zeros(N, dtype=bool)
for g in range(N):
    if nh.glyph_is_normal_object(g) and ord(nh.objclass(nh.glyph_to_obj(g)).oc_class) == nh.ARMOR_CLASS:
        ARMOR_GLYPH[g] = True

# '%' food items (not corpses: those are body glyphs)
FOOD_GLYPH = np.zeros(N, dtype=bool)
for g in range(N):
    if nh.glyph_is_normal_object(g) and ord(nh.objclass(nh.glyph_to_obj(g)).oc_class) == nh.FOOD_CLASS:
        FOOD_GLYPH[g] = True
