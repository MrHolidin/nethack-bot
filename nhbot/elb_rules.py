"""Will Elbereth protect me from the monsters I can see?

Rules from NetHack 3.6.6 itself:
  * monmove.c onscary(): a written Elbereth is ignored by @ (humans and elves), minotaurs, shopkeepers,
    guards, priests in their temple, the Riders, Angels and lawful minions, blind and peaceful monsters,
    and by everybody in Gehennom and the endgame.
  * Elbereth only stops melee.  Anything that can hurt from a distance makes standing on it pointless:
    monst.c attack types BREA / SPIT / GAZE / MAGC, weapon users (AT_WEAP: they throw and fire what they
    carry), and monsters that can zap wands or throw potions (muse.c find_offensive: not an animal,
    not mindless, has hands).

blockers() lists every visible hostile for which one of these holds; if the list is non-empty the bot
does not engrave at all.
"""
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.monattacks import ATTACK_TYPES

M1_NOHANDS, M1_MINDLESS, M1_ANIMAL = 0x00002000, 0x00010000, 0x00040000
M2_MINION = 0x00001000

_MLET = {nh.permonst(i).mname: nh.permonst(i).mlet for i in range(nh.NUMMONS)}
S_HUMAN, S_ANGEL = _MLET["human"], _MLET["Angel"]

IGNORES_BY_NAME = {
    "minotaur": "minotaur",
    "shopkeeper": "shopkeeper", "guard": "vault guard", "aligned priest": "priest", "high priest": "priest",
    "Death": "Rider", "Pestilence": "Rider", "Famine": "Rider",
}
RANGED = {"BREA": "breath", "SPIT": "spit", "GAZE": "gaze", "MAGC": "spells"}

GEHENNOM_DNUM, ENDGAME_DNUM = 1, 7


def reason(mon_idx):
    """None if Elbereth fully protects against this monster type, else why not."""
    pm = nh.permonst(mon_idx)
    name = pm.mname
    if pm.mlet == S_HUMAN:
        return "@ ignores Elbereth"
    if name in IGNORES_BY_NAME:
        return IGNORES_BY_NAME[name] + " ignores Elbereth"
    if pm.mlet == S_ANGEL or pm.mflags2 & M2_MINION:
        return "angelic/minion may ignore Elbereth"
    atk = ATTACK_TYPES[mon_idx]
    for a in atk:
        if a in RANGED:
            return "ranged attack: " + RANGED[a]
    if "WEAP" in atk:
        return "weapon user: may throw or fire"
    if not pm.mflags1 & (M1_NOHANDS | M1_MINDLESS | M1_ANIMAL):
        return "has hands and a mind: may zap wands"
    return None


_REASON = [reason(i) for i in range(nh.NUMMONS)]

# Class C: blocked only because they MIGHT carry missiles or a wand (makemon.c m_initweap gives a launcher
# or throwables to a minority of them: gnome 4/14, gnome lord 4/12, hill orc 1/4, ...). A scared monster
# does not melee (monmove.c dochug: no mattacku while 'scared'); after stepping away it can shoot only if
# it really has something to throw (thrwmu / find_offensive).
MAYBE_ARMED = frozenset(i for i, r in enumerate(_REASON)
                        if r and r.startswith(("weapon user", "has hands and a mind")))


def blockers(glyphs, me, peaceful, dnum, optimistic=False, skip_names=()):
    """[(name, reason)] for every visible non-peaceful monster that makes Elbereth useless, plus unseen
    attackers ('I' markers) within 2 squares.  Empty list = Elbereth is worth writing.
    optimistic: class-C monsters (MAYBE_ARMED) don't block."""
    if dnum in (GEHENNOM_DNUM, ENDGAME_DNUM):
        return [("-", "Elbereth has no power here")]
    out = []
    py, px = me
    rows, cols = glyphs.shape
    for y in range(rows):
        for x in range(cols):
            g = int(glyphs[y, x])
            k = G.KIND[g]
            if (y, x) == (py, px):
                continue
            if k == G.INVIS and max(abs(y - py), abs(x - px)) <= 2:
                out.append(("unseen", "can't tell what it is"))
            elif k == G.MONSTER and g not in peaceful:
                idx = nh.glyph_to_mon(g)
                r = _REASON[idx]
                if r and optimistic and idx in MAYBE_ARMED:
                    continue
                if r and G.monster_name(g) not in skip_names:
                    out.append((G.monster_name(g), r))
    return out


def summary():
    """How the 381 monster types split (for inspection)."""
    import collections
    c = collections.Counter((r or "protected").split(":")[0] for r in _REASON)
    return c


if __name__ == "__main__":
    for k, v in summary().most_common():
        print(f"{v:4d}  {k}")
    for n in ("killer bee", "soldier ant", "jackal", "gnome lord", "dwarf", "hill orc", "Uruk-hai", "bugbear",
              "kobold lord", "black unicorn", "dwarf zombie", "wood nymph", "giant beetle", "rothe",
              "homunculus", "imp", "floating eye", "werewolf", "wererat", "gnome mummy", "cave spider"):
        idx = [i for i in range(nh.NUMMONS) if nh.permonst(i).mname == n]
        print(f"{n:15s}", [(chr(nh.permonst(i).mlet + 64) if False else "", _REASON[i] or "protected") for i in idx])
