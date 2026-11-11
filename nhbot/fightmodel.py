"""fight_model2: the parts of the melee model beyond the plain attack dice, as plain functions danger.py (the danger
estimate, win_prob) and focus.py use (NetHack 3.6.6; calibrated against the true game state on real games,
scratchpad zi/fight_calib.py):

  * monster spells (mcastu.c castmu): which spell a caster of level ml picks, the damage it does, how often it can cast;
  * negative AC: every hit's damage less rnd(-AC), at least 1 (mhitu.c:1696-1703);
  * our weapon skill, read from the advance messages (weapon.c skill_advance / weapon_hit_bonus / weapon_dam_bonus);
  * a monster's HP prior (makemon.c newmonhp) and, after the hits we landed, the expected number of our attacks
    still needed to kill it;
  * what fire / cold / shock does to our pack (zap.c destroy_item): the HP our own boiling potions and exploding
    wands take, the items lost -- one implementation for melee hits, spells and rays (pack_destroy).
"""
from functools import lru_cache

import numpy as np
import nle.nethack as nh

from nhbot.monattacks import ATTACKS

# makemon.c:1967-1995 golemhp: golems have fixed HP (newmonhp 990-991)
GOLEM_HP = {"straw golem": 20, "paper golem": 20, "rope golem": 30, "leather golem": 40, "gold golem": 40,
            "wood golem": 50, "flesh golem": 40, "clay golem": 50, "stone golem": 60, "glass golem": 60,
            "iron golem": 80}

# the skill each melee weapon trains (objects.c's sub field; weapon.c P_NAME, as "You are now more skilled in <name>.")
WEAPON_SKILL = {
    'spear': 'spear', 'elven spear': 'spear', 'orcish spear': 'spear', 'dwarvish spear': 'spear',
    'silver spear': 'spear', 'javelin': 'spear', 'trident': 'trident', 'dagger': 'dagger', 'elven dagger': 'dagger',
    'orcish dagger': 'dagger', 'silver dagger': 'dagger', 'athame': 'dagger', 'scalpel': 'knife', 'knife': 'knife',
    'stiletto': 'knife', 'worm tooth': 'knife', 'crysknife': 'knife', 'axe': 'axe', 'battle-axe': 'axe',
    'short sword': 'short sword', 'elven short sword': 'short sword', 'orcish short sword': 'short sword',
    'dwarvish short sword': 'short sword', 'scimitar': 'scimitar', 'silver saber': 'saber',
    'broadsword': 'broadsword', 'elven broadsword': 'broadsword', 'long sword': 'long sword',
    'two-handed sword': 'two-handed sword', 'katana': 'long sword', 'tsurugi': 'two-handed sword',
    'runesword': 'broadsword', 'partisan': 'polearms', 'ranseur': 'polearms', 'spetum': 'polearms',
    'glaive': 'polearms', 'lance': 'lance', 'halberd': 'polearms', 'bardiche': 'polearms', 'voulge': 'polearms',
    'dwarvish mattock': 'pick-axe', 'fauchard': 'polearms', 'guisarme': 'polearms', 'bill-guisarme': 'polearms',
    'lucern hammer': 'polearms', 'bec de corbin': 'polearms', 'mace': 'mace', 'morning star': 'morning star',
    'war hammer': 'hammer', 'club': 'club', 'rubber hose': 'whip', 'quarterstaff': 'quarterstaff', 'aklys': 'club',
    'flail': 'flail', 'bullwhip': 'whip', 'pick-axe': 'pick-axe', 'unicorn horn': 'unicorn horn'}
BASIC = 2                          # skills.h P_BASIC: weapon.c skill_init gives it to the weapons we start with
SKILL_HIT = {0: -4, 1: -4, 2: 0, 3: 2}          # weapon.c:1414-1430 weapon_hit_bonus (Expert and up: +3)
SKILL_DMG = {0: -2, 1: -2, 2: 0, 3: 1}          # weapon.c:1508-1525 weapon_dam_bonus (Expert and up: +2)

# mcastu.c spell numbers (the MGC_* / CLC_* enums)
PSI_BOLT, CURE_SELF, HASTE_SELF, STUN_YOU, DISAPPEAR, WEAKEN_YOU, DESTRY_ARMR, CURSE_ITEMS, AGGRAVATION, \
    SUMMON_MONS, CLONE_WIZ, DEATH_TOUCH = range(12)
OPEN_WOUNDS, CLC_CURE_SELF, CONFUSE_YOU, PARALYZE, BLIND_YOU, INSECTS, CLC_CURSE_ITEMS, LIGHTNING, FIRE_PILLAR, \
    GEYSER = range(10)


def skill_bonus(level):
    """(to-hit, damage) of a weapon skill level (skills.h: 0 restricted .. 4 expert)."""
    return SKILL_HIT.get(level, 3), SKILL_DMG.get(level, 2)


def dice(n, d):
    """The pmf of the sum of n d-sided dice: a fresh array (the cached table is shared)."""
    return _dice(n, d).copy()


@lru_cache(maxsize=None)
def _dice(n, d):
    p = np.zeros(n * d + 1)
    p[0] = 1.0
    for _ in range(n):
        q = np.zeros(len(p) + d)
        for k in range(1, d + 1):
            q[k:k + len(p)] += p / d
        p = q[:n * d + 1]
    return p


def ac_reduce(pmf, ac):
    """mhitu.c:1696-1703 hitmu: with a negative AC a hit that does damage does rnd(-AC) less, at least 1."""
    if ac >= 0:
        return pmf
    out = np.zeros(len(pmf))
    out[0] = pmf[0]
    k = -ac
    for v in range(1, len(pmf)):
        if pmf[v]:
            for r in range(1, k + 1):
                out[max(1, v - r)] += pmf[v] / k
    return out


@lru_cache(maxsize=None)
def _spell_values(ml, cap):
    """mcastu.c:210-214, 87-88 / 142-143: spellnum = rn2(ml), and while above cap (24 mage, 15 cleric) and
    rn2(cap + 1): rn2(spellnum) again -- the distribution of the value the spell table is looked up with."""
    top = max(ml, 1)
    dist = np.zeros(top)
    dist[:ml] = 1.0 / ml
    for v in range(top - 1, cap, -1):           # from the top down: a value above cap rerolls with chance cap/(cap+1)
        if dist[v]:
            move = dist[v] * cap / (cap + 1)
            dist[v] -= move
            dist[:v] += move / v
    return dist


def mage_spell(v, antimagic):
    """mcastu.c:82-132 choose_magic_spell."""
    if v in (24, 23):
        return PSI_BOLT if antimagic else DEATH_TOUCH
    table = {22: DEATH_TOUCH, 21: DEATH_TOUCH, 20: DEATH_TOUCH, 19: CLONE_WIZ, 18: CLONE_WIZ, 17: SUMMON_MONS,
             16: SUMMON_MONS, 15: SUMMON_MONS, 14: AGGRAVATION, 13: AGGRAVATION, 12: CURSE_ITEMS, 11: CURSE_ITEMS,
             10: CURSE_ITEMS, 9: DESTRY_ARMR, 8: DESTRY_ARMR, 7: WEAKEN_YOU, 6: WEAKEN_YOU, 5: DISAPPEAR,
             4: DISAPPEAR, 3: STUN_YOU, 2: HASTE_SELF, 1: CURE_SELF}
    return table.get(v, PSI_BOLT)


def cleric_spells(v):
    """mcastu.c:137-177 choose_clerical_spell, as [(P, spell)] (14, 15: OPEN_WOUNDS 2 in 3, else GEYSER)."""
    if v in (15, 14):
        return [(2 / 3, OPEN_WOUNDS), (1 / 3, GEYSER)]
    table = {13: GEYSER, 12: FIRE_PILLAR, 11: LIGHTNING, 10: CLC_CURSE_ITEMS, 9: CLC_CURSE_ITEMS, 8: INSECTS,
             7: BLIND_YOU, 6: BLIND_YOU, 5: PARALYZE, 4: PARALYZE, 3: CONFUSE_YOU, 2: CONFUSE_YOU, 1: CLC_CURE_SELF}
    return [(1.0, table.get(v, OPEN_WOUNDS))]


def cast_profile(ad, ml, n, d, us):
    """(damage pmf of one cast at us, P(it kills us outright)) of a monster of level ml casting an AT_MAGC attack of
    damage type ad and dice (n, d) next to us, given the cast is made and not fumbled. us: {"resists": set,
    "blind": bool, "hurt": bool -- we hit it, so CURE_SELF is not useless, "wizard": bool}.
      castmu 288-291: dmg = d(ml / 2 + n, d), d(ml / 2 + 1, 6) when the attack has no dice;
      AD_FIRE / AD_COLD 298-314: nothing if we resist; AD_MAGM 315-323: d(ml / 2 + 1, 6), nothing with magic
      resistance; AD_SPEL / AD_CLRC: the spell picked (_spell_values, mage_spell / cleric_spells), the useless ones
      drawn again (spell_would_be_useless 767-834: CLONE_WIZ but for the Wizard, CURE_SELF at full HP, BLIND_YOU
      while we are blind): PSI_BOLT 496-514 and OPEN_WOUNDS 710-723 dmg (halved with magic resistance);
      DEATH_TOUCH 378-396 kills unless magic resistance when rn2(ml) > 12; GEYSER 535-543 d(8, 6); FIRE_PILLAR
      544-559 d(8, 6) unless we resist fire; LIGHTNING 560-578 d(8, 6) unless reflection / shock resistance. The rest
      (stun, weaken, destroy armor, curse, summon, aggravate, paralyse, blind, confuse, haste, invisible) do no HP
      damage here. us["blast"] (an AD_CLRC caster's): {FIRE_PILLAR / LIGHTNING: the damage pmf of what that
      spell's destroy_item calls do to our pack (pack_destroy)} -- added to the spell's, resisted or not (but for a
      reflected lightning bolt, 563-569)."""
    res = us["resists"]
    magic = "magic" in res
    base = dice(ml // 2 + n, d) if d else dice(ml // 2 + 1, 6)
    if ad == "FIRE":
        return (np.array([1.0]) if "fire" in res else base), 0.0
    if ad == "COLD":
        return (np.array([1.0]) if "cold" in res else base), 0.0
    if ad == "MAGM":
        return (np.array([1.0]) if magic else dice(ml // 2 + 1, 6)), 0.0
    if ad not in ("SPEL", "CLRC"):
        return base, 0.0
    halved = np.zeros(len(base) // 2 + 2)
    for v, p in enumerate(base):
        halved[(v + 1) // 2] += p
    big = dice(8, 6)
    none = np.array([1.0])
    picks, z = spell_picks(ad, ml, us)
    if z <= 0:
        return none, 0.0
    blast = us.get("blast")
    pmf, death = np.zeros(max(len(base), len(big))), 0.0
    for p, s in picks:
        p /= z
        if ad == "SPEL" and s == PSI_BOLT or ad == "CLRC" and s == OPEN_WOUNDS:
            q = halved if magic else base
        elif ad == "SPEL" and s == DEATH_TOUCH:
            if not magic:
                death += p * max(0, ml - 13) / ml          # rn2(ml) > 12
            q = none
        elif ad == "CLRC" and (s == GEYSER or s == FIRE_PILLAR and "fire" not in res
                               or s == LIGHTNING and not res & {"shock", "reflection"}):
            q = big
        else:
            q = none
        if blast is not None and ad == "CLRC" and s in blast and (s != LIGHTNING or "reflection" not in res):
            q = np.convolve(q, blast[s])                    # 555-557, 574-575: our pack burns / is zapped
            if len(q) > len(pmf):
                pmf = np.concatenate([pmf, np.zeros(len(q) - len(pmf))])
        pmf[:len(q)] += p * q
    return pmf, death


def spell_picks(ad, ml, us):
    """([(weight, spell)], their sum) -- the spells an AD_SPEL / AD_CLRC caster of level ml picks (_spell_values,
    mage_spell / cleric_spells), without the useless ones (mcastu.c:767-834 spell_would_be_useless: CLONE_WIZ but
    for the Wizard, CURE_SELF while it is not hurt, BLIND_YOU while we are blind); us as cast_profile's."""
    magic = "magic" in us["resists"]
    if ad == "SPEL":
        picks = [(p, mage_spell(v, magic)) for v, p in enumerate(_spell_values(ml, 24)) if p]
    else:
        picks = [(p * q, s) for v, p in enumerate(_spell_values(ml, 15)) if p for q, s in cleric_spells(v)]
    useless = {CLONE_WIZ} if ad == "SPEL" and not us.get("wizard") else set()
    if not us.get("hurt"):
        useless |= {CURE_SELF} if ad == "SPEL" else {CLC_CURE_SELF}
    if ad == "CLRC" and us.get("blind"):
        useless.add(BLIND_YOU)
    picks = [(p, s) for p, s in picks if s not in useless]
    return picks, sum(p for p, _ in picks)


def cast_chance(ad, ml, mmove):
    """P(a move of a caster next to us is a cast that is not fumbled):
    castmu 233-242 -- AD_SPEL / AD_CLRC set mspec_used = max(2, 10 - ml), and while it is above 0 the monster cannot
    cast; mon_regen (monmove.c:193, once a turn from mon.c:698 mcalcdistress) counts it down: one cast in
    max(2, 10 - ml) - 1 turns plus the wait for its next move (12 / mmove turns on average) -- per move 12 / mmove of
    that; castmu 206, 233: never at level 0; castmu 257: fumbled when rn2(ml * 10) < 20."""
    if ml <= 0:
        return 0.0
    ok = max(0.0, 1 - 20 / (10 * ml))
    if ad not in ("SPEL", "CLRC"):
        return ok
    mmove = max(mmove, 1)
    period = max(2, 10 - ml) - 1 + max(1.0, 12 / mmove)
    return ok * min(1.0, 12 / mmove / period)


def hp_prior(name, lev):
    """makemon.c:983-1015 newmonhp: golems their fixed HP (golemhp), level 0 rnd(4), else d(level, 8)."""
    if name in GOLEM_HP:
        out = np.zeros(GOLEM_HP[name] + 1)
        out[-1] = 1.0
        return out
    return dice(lev, 8) if lev > 0 else dice(1, 4)


def remaining_hp(prior, dmg, hits):
    """P(HP left = r | alive), r = 0.. (0 impossible), after `hits` hits of damage pmf dmg on a monster of HP prior;
    None when the prior allows no monster that lives through them (a tougher one than the prior)."""
    dk = np.array([1.0])
    for _ in range(hits):
        dk = np.convolve(dk, dmg)
    left = np.zeros(len(prior))
    for h, ph in enumerate(prior):
        if ph:
            n = min(h, len(dk))
            left[h - np.arange(n)] += ph * dk[:n]        # HP h, damage k < h: h - k left
    left[0] = 0.0
    z = left.sum()
    return left / z if z > 1e-12 else None


def hits_to_kill(left, dmg):
    """E[hits we still need] = sum over k >= 0 of P(k more hits leave it alive), over the posterior left."""
    total, sk = 0.0, np.array([1.0])                     # sk: the damage pmf of k hits
    r = np.arange(1, len(left))
    alive, k = 1.0, 0
    while alive > 1e-4 and k < 200:
        cdf = np.cumsum(sk)
        alive = float(left[1:] @ cdf[np.minimum(r - 1, len(cdf) - 1)])     # P(S_k < r) = cdf[r - 1]
        total += alive
        sk = np.convolve(sk, dmg)
        k += 1
    return total


@lru_cache(maxsize=None)
def typical_monster(lev):
    """A stand-in for an unseen monster of level lev: of the small / medium kinds of that level that attack
    (monst.c), the one with the median AC."""
    kinds = sorted((nh.permonst(i).ac, nh.permonst(i).mname) for i in range(nh.NUMMONS)
                   if nh.permonst(i).mlevel == lev and nh.permonst(i).msize < 3
                   and any(a[0] != "NONE" for a in ATTACKS[i]))
    return kinds[len(kinds) // 2][1] if kinds else "jackal"


def unseen_level(depth, xl):
    """makemon.c:1546-1550 rndmonst: a random monster's level lies between depth / 6 and (depth + XL) / 2 -- an
    unseen one taken at the middle."""
    return (depth // 6 + (depth + xl) // 2) // 2


# ------------------------------------------------------------------ our pack under fire, cold and shock
RESIST_OF = {"FIRE": "fire", "COLD": "cold", "ELEC": "shock"}
PACK_CLASSES = (nh.POTION_CLASS, nh.SCROLL_CLASS, nh.SPBOOK_CLASS, nh.WAND_CLASS, nh.RING_CLASS)
# mhitu.c:1066-1071, 1084-1085, 1097-1100 hitmu (an uncancelled hit): destroy_item(class) when m_lev > rn2(n)
MELEE_DESTROY = {"FIRE": ((20, nh.SCROLL_CLASS), (20, nh.POTION_CLASS), (25, nh.SPBOOK_CLASS)),
                 "COLD": ((20, nh.POTION_CLASS),),
                 "ELEC": ((20, nh.WAND_CLASS), (20, nh.RING_CLASS))}
# zap.c:3790-3797, 3808-3809, 3865-3868 zhitu: a ray at us (fire: after burnarmor's body hit, the caller's gate)
RAY_DESTROY = {"fire": ((1 / 3, nh.POTION_CLASS, "FIRE"), (1 / 3, nh.SCROLL_CLASS, "FIRE"),
                        (1 / 5, nh.SPBOOK_CLASS, "FIRE")),
               "cold": ((1 / 3, nh.POTION_CLASS, "COLD"),),
               "lightning": ((1 / 3, nh.WAND_CLASS, "ELEC"), (1 / 3, nh.RING_CLASS, "ELEC"))}
# mcastu.c:555-557 fire pillar, 574-575 lightning: every time
SPELL_DESTROY = {FIRE_PILLAR: ((1.0, nh.SCROLL_CLASS, "FIRE"), (1.0, nh.POTION_CLASS, "FIRE"),
                               (1.0, nh.SPBOOK_CLASS, "FIRE")),
                 LIGHTNING: ((1.0, nh.WAND_CLASS, "ELEC"), (1.0, nh.RING_CLASS, "ELEC"))}


def uncancelled(mc):
    """mhitu.c:967-968: P(rn2(10) >= 3 * MC) -- an elemental hit's effect lands (a monster not cancelled)."""
    return max(0, 10 - 3 * mc) / 10


def melee_destroy_events(ad, level):
    """The destroy_item calls of an uncancelled hit of damage type ad by a monster of level `level`, as
    ((P, class, ad), ...) (MELEE_DESTROY: P(m_lev > rn2(n)) = min(m_lev, n) / n)."""
    return tuple((min(max(level, 0), n) / n, cls, ad) for n, cls in MELEE_DESTROY.get(ad, ()))


def destroy_damage(cls, name, ad, resists):
    """zap.c:4811-4900 destroy_one_item: the HP damage pmf of one stack of this class and name going (None: never
    destroyed). Cold: potions but oil, rnd(4). Fire: potions rnd(6) (cold or fire resistance never helps: xresist
    leaves potions out), scrolls / spellbooks 1 (none with fire resistance); not a scroll of fire, a spellbook of
    fireball, the Book of the Dead. Shock: wands but lightning rnd(10) (none with shock resistance), rings but shock
    resistance 0."""
    if ad == "COLD":
        return dice(1, 4) if cls == nh.POTION_CLASS and name != "potion of oil" else None
    if ad == "FIRE":
        if cls == nh.POTION_CLASS:
            return dice(1, 6)
        if cls == nh.SCROLL_CLASS and name != "scroll of fire" or \
                cls == nh.SPBOOK_CLASS and name not in ("spellbook of fireball", "Book of the Dead"):
            return np.array([1.0]) if "fire" in resists else np.array([0.0, 1.0])
        return None
    if ad == "ELEC":
        if cls == nh.WAND_CLASS and name != "wand of lightning":
            return np.array([1.0]) if "shock" in resists else dice(1, 10)
        if cls == nh.RING_CLASS and name != "ring of shock resistance":
            return np.array([1.0])
    return None


@lru_cache(maxsize=1 << 14)
def pack_destroy(stacks, events, resists):
    """What these destroy_item calls do to our pack: (HP damage pmf, ((class, expected units lost, expected stacks
    hit), ...)). stacks: ((class, quantity, bare name), ...) of our pack (danger.pack_stacks); events: ((P,
    class, ad), ...), each call made with its P, independently; resists: frozenset (perception.our_resists).
    zap.c:4958-5037 destroy_item -> 4900-4915 destroy_one_item: each unit of an eligible stack goes 1 in 3, and a
    stack that loses any does its damage once (destroy_damage). Cached by its arguments: the arrays it returns
    are shared, never to be written."""
    pmf = np.array([1.0])
    loss = {}
    for p, cls, ad in events:
        if p <= 0:
            continue
        one = np.array([1.0])
        units = stacks_hit = 0.0
        for c, qty, name in stacks:
            if c != cls:
                continue
            dmg = destroy_damage(c, name, ad, resists)
            if dmg is None:
                continue
            q = 1 - (2 / 3) ** qty                         # rn2(3) == 0 for some unit of it
            hit = np.zeros(max(len(dmg), 1))
            hit[0] = 1 - q
            hit[:len(dmg)] += q * dmg
            one = np.convolve(one, hit)
            units += qty / 3
            stacks_hit += q
        if units:
            mixed = np.zeros(len(one))
            mixed[0] = 1 - p
            mixed += p * one
            pmf = np.convolve(pmf, mixed)
            u, h = loss.get(cls, (0.0, 0.0))
            loss[cls] = (u + p * units, h + p * stacks_hit)
    return pmf, tuple((c, u, h) for c, (u, h) in sorted(loss.items()))
