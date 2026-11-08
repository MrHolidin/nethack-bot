"""Melee danger estimate: from the monsters next to us, the distribution of the damage we
take in the next game turn, and so the chance it kills us (NetHack 3.6.6 mhitu.c / makemon.c / mon.c).

Per adjacent hostile, per action it gets this turn (mcalcmove: mmove / 12 actions, the remainder a random
extra one), per melee attack i of its type (monattacks.ATTACKS):
  hit      if 10 + AC_VALUE(our AC) + level > rnd(20 + i)   (AC_VALUE: a negative AC counts as -rnd(-AC))
  level    makemon.c adj_lev from the base level, the depth and our XL (a grown-up monster: unknown)
  damage   d(n, d), plus the weapon's small-monster dice for a weapon attack (the weapon we saw it swing or
           thrust; else a d6 guess); cold: none (Valkyries resist); rust / steal / seduce ...: none
  poison   a hit of a poisoning attack poisons 1 in 8: deadly 1 in 30 without poison resistance, else
           rn1(10, 6) more damage 5 in 30
Our attack comes first in the turn: the monster we attack doesn't act if this hit kills it -- P(hit) by
uhitm.c find_roll_to_hit (Luck taken as 0) and P(kill | alive) from its HP d(level, 8) against our damage
dice (dmgval + enchantment + dbon) over the hits we already landed on it.
Standing on Elbereth (read back) a monster that respects it doesn't melee us -- unless we attack, which
erases it (mon.c setmangry).
P(death) = P(total damage >= HP) combined with the instant deaths. Calibration (summary 'danger'): predicted
mean damage and P(death) against what the next turn did -- statistics only.
win_prob (sampled whole fights) decides: the prey explore walks up to (combat.prey_mask), whether and which attack
wand to zap (combat.wand_ev_pairs), a fountain dip that may bring a water demon (excalibur).
fight_model2_all (A/B, options.py): win_prob and the calibration statistics with the model focus scores by
(focus.focus_parts): monster_turn_pmf / monster_round model2, our weapon skill, the newmonhp prior, focus's hit count.
"""
import re
from bisect import bisect_right
from collections import defaultdict
from typing import NamedTuple

import numpy as np
import nle.nethack as nh

from nhbot.carry import WEAPON_NAME_OF
from nhbot.fightmodel import ac_reduce, cast_chance, cast_profile, hp_prior
from nhbot.items import base_name, erosion
from nhbot.messages import KILL_WORD_RE, OUR_HIT_RE
from nhbot.monattacks import ATTACKS
from nhbot.monsters import M1_REGEN, PM_BY_NAME, PM_INDEX, PM_INDICES
from nhbot.weapondice import WEAPON_DICE, str_dbon, to_hit_abon
from nhbot.rays import RAY_RESIST, zap_hit_prob

MELEE = {"CLAW", "BITE", "KICK", "BUTT", "TUCH", "STNG", "HUGS", "WEAP", "TENT"}
# hits that do no HP damage. The d(n, d) of a rust / corrode / disenchant / slime / gold-stealing hit lands (mhitu.c
# hitmu: AD_RUST 1436, AD_CORR 1448, AD_ENCH 1654, AD_SLIM 1636, AD_SGLD 1320 keep dmg)
# (A/B dmg_nodmg: -72 [-415, +265], median 7726 -> 7726, 32 of 1000 changed); a cold hit is zeroed only when we
# resist cold (monster_turn_pmf)
NO_DAMAGE = {"DCAY", "SEDU", "SSEX", "CURS", "STON"}
POISON = {"DRST", "DRDX", "DRCO"}
MAX_D = 400
TAINT_AD = {"BLND": 1.0, "WERE": 0.25, "SEDU": 1.0, "SITM": 1.0, "SSEX": 1.0, "SGLD": 1.0}   # a hit blinds /
# passes lycanthropy (mhitu.c AD_WERE: 1 in 4) / charms and robs us / steals our gold (a leprechaun: steal.c
# somegold, most of what we carry; only when we carry some): a fight won that way counts half (walk_fight)
TAINTED_WIN = 0.5
WAND_ORDER = ("death", "sleep", "fire", "cold", "lightning", "magic missile", "striking")   # muse.c find_offensive
MISSILE_DIE = {"arrow": 6, "elven arrow": 7, "orcish arrow": 5, "silver arrow": 6, "ya": 7, "crossbow bolt": 4,
               "rock": 3, "flint stone": 6, "boulder": 20}        # objects.c, small monsters' die
BREATH_KIND = {"FIRE": "fire", "COLD": "cold", "ELEC": "lightning", "SLEE": "sleep", "MAGM": "magic missile",
               "DISN": "death", "ACID": "fire", "DRST": "fire", "RBRE": "fire"}
WIELD_RE = re.compile(r"The ([a-zA-Z' -]+?) (?:swings|thrusts|wields) (?:his|her|its|an?|the|\d+)? ?([a-z' -]+?)[.!]")
# a seen monster's melee hit or miss (mhitu.c hitmsg default "%s hits!", missmu); a weapon attack with a weapon in hand
# says "swings" / "thrusts" first (mhitu.c:767-772, 100-106 mswings, a seen monster) -- without it, none
MON_MELEE_RE = re.compile(r"\bThe ([a-zA-Z' -]+?) (?:hits|misses|just misses)!")
WIN_SIMS = 200                   # win_prob: sampled fights
EXCALIBUR_BONUS = (5, 10)        # artilist.h Excalibur PHYS(5, 10): + rnd(5) to hit, + d10 damage, against anything
MEAN_EDGES = (0, 1, 3, 6, 10, 15, 25, 1e9)
P_EDGES = (0, 0.001, 0.01, 0.05, 0.2, 0.5, 1.01)


def dice_pmf(n, d):
    p = np.zeros(n * d + 1)
    p[0] = 1.0
    for _ in range(n):
        q = np.zeros(len(p) + d)
        for k in range(1, d + 1):
            q[k:k + len(p)] += p / d
        p = q[:n * d + 1] if len(q) > n * d + 1 else q
    return p


def conv(a, b):
    c = np.convolve(a, b)
    if len(c) > MAX_D:
        c = np.concatenate([c[:MAX_D - 1], [c[MAX_D - 1:].sum()]])
    return c


def adj_level(base, depth, xl):
    """makemon.c adj_lev."""
    tmp = base
    if base > 49:
        return 50
    t2 = depth - base
    tmp = tmp - 1 if t2 < 0 else tmp + t2 // 5
    t2 = xl - base
    if t2 > 0:
        tmp += t2 // 4
    cap = min(3 * base // 2, 49)
    return min(tmp, cap) if tmp > 0 else 0



def pmf_cdf(p):
    """The table Generator.choice(len(p), p=p) searches: the cumulative sum over its last value (numpy
    _generator.pyx choice)."""
    c = np.asarray(p, dtype=np.float64).cumsum()
    c /= c[-1]
    return c.tolist()


def cdf_draw(rng, cdf):
    """int(rng.choice(len(p), p=p)) for cdf = pmf_cdf(p): the same one uniform draw, the same index -- without
    choice's checks and cumulative sum on every call (a twentieth of the time)."""
    return bisect_right(cdf, rng.random())


def cdf_draws(rng, cdf, n):
    """int(rng.choice(len(p), size=n, p=p).sum()) for cdf = pmf_cdf(p): the same n uniform draws."""
    return sum(bisect_right(cdf, u) for u in rng.random(n))

class FightMon(NamedTuple):
    """One monster of a fight win_prob samples."""
    lev: int            # its level (adj_level), at least 0
    hit: float          # P(our blow hits it) (our_hit_prob)
    dmg: object         # our damage pmf on it (our_damage_pmf)
    rnd: object         # its round's damage pmf (monster_round) -- the simple model
    inst: float         # P(its round kills us at once) -- the simple model
    hits: int           # our hits on it so far (their damage is off its HP)
    pos: object         # its square, None for one not there yet
    turn: tuple         # (damage pmf, P(instant death)) of one of its moves (monster_turn_pmf)
    speed: int          # its mmove
    name: str
    taint: tuple        # (P(a hit taints us), explodes) (monster_taint)
    turn_helpless: tuple  # turn while we sleep / are frozen: +4 to hit us
    regen: bool         # M1_REGEN
    plys: tuple         # (P(a move freezes us), passive paralysis dice or None) (monster_paralysis)
    never: bool         # a kind we never melee (perception.never_melee)
    effects: tuple      # monster_effects of its hits
    hp: object          # its HP pmf (fightmodel.hp_prior) under fight_model2_all; None: d(lev, 8) drawn as is


def opening_hooks(index, alive, hps):
    """win_prob's opening (a zap) sees the fight through these: alive_at(pos) -- a monster of the fight still at pos
    --, apply(pos, damage or None for asleep) -- the zap's effect on it."""
    def alive_at(pos):
        return pos in index and index[pos] in alive

    def apply(pos, dmg):
        jj = index[pos]
        if dmg is None:
            alive.remove(jj)                 # asleep: out of the fight
        else:
            hps[jj] -= dmg
            if hps[jj] <= 0:
                alive.remove(jj)
    return alive_at, apply


class DangerState:
    """State of the danger model: monster weapons, our hits, win_prob draws, calibration (DangerMixin)."""
    def __init__(self):
        self.mon_weapon = {}                     # monster name -> weapon we saw it use
        self.mon_unarmed = set()                 # monster names we saw hit / miss with no weapon swung
        self.pending = None                      # (turn, hp, [(pos, pmf, P(instant death), P(we kill it), scared)])
        self.our_hits = {}                       # (level key, square) -> our hits on the monster there
        self.win_rng = np.random.default_rng(12345)   # win_prob's own draws (never the game's RNG)
        self.opening_rng = np.random.default_rng(54321)   # win_prob's draws for the opening zap (wand_ev)
        self.hit_seen = False                    # this tick: a melee hit of ours
        self.attack_turn = -1                    # turn of our last melee attack (combat.attack)
        self.mean = defaultdict(lambda: [0, 0.0, 0.0])           # bin -> [n, sum predicted, sum actual]
        self.p = defaultdict(lambda: [0, 0.0, 0])                # bin -> [n, sum predicted, deaths]


class DangerMixin:
    def danger_init(self):
        self.danger = DangerState()

    def danger_msg(self, m):
        if OUR_HIT_RE.search(m):
            self.danger.hit_seen = True
        if KILL_WORD_RE.search(m) and self.acts.last_attack_target is not None:
            self.danger.our_hits.pop((self.cur_key, self.acts.last_attack_target), None)
        for mon, weapon in WIELD_RE.findall(m):
            w = re.sub(r"s$", "", weapon) if weapon not in WEAPON_DICE else weapon
            if w in WEAPON_DICE:
                self.danger.mon_weapon[mon] = w
        for mon in MON_MELEE_RE.findall(m):
            if mon not in self.danger.mon_weapon:
                self.danger.mon_unarmed.add(mon)

    def hit_prob(self, level, i, bonus=0):
        """P(10 + AC_VALUE(ac) + level (+ bonus: 4 while we are helpless, mhitu.c multi < 0) > rnd(20 + i))."""
        ac = self.bl(nh.NLE_BL_AC)
        n = 20 + i
        acs = [ac] if ac >= 0 else [-k for k in range(1, -ac + 1)]
        p = 0.0
        for a in acs:
            tmp = 10 + a + level + bonus
            p += min(max(tmp - 1, 0), n) / n
        return p / len(acs)

    def monster_turn_pmf(self, name, bonus=0, model2=False, hurt=False):
        """(damage pmf of one action of this monster, P(instant death) per action); bonus: to its to-hit.
        model2 (focus.focus_parts; win_prob and danger_tick under fight_model2_all): each hit's damage less rnd(-AC)
        at a negative AC (fightmodel.ac_reduce), a weapon attack of a kind we saw hit / miss without swinging one: its
        own dice only (mon_unarmed), its spells (AT_MAGC: fightmodel.cast_chance / cast_profile; hurt: we hit it -- it
        may cure itself), and a leprechaun does not attack us while we carry no gold."""
        idx = PM_INDEX.get(name)
        if idx is None:
            return np.array([1.0]), 0.0
        if model2 and name == "leprechaun" and not self.bl(nh.NLE_BL_GOLD):
            # monmove.c:574-576 dochug: we carry no gold and it carries some (makemon.c:764-765 m_initinv: d(depth,
            # 30) at its making) -- it moves off instead of attacking (on calibration games 0.10 of the modelled damage)
            return np.array([1.0]), 0.0
        pm = nh.permonst(idx)
        level = adj_level(pm.mlevel, self.bl(nh.NLE_BL_DEPTH), self.bl(nh.NLE_BL_XP))
        pmf, alive = np.array([1.0]), 1.0
        ac = self.bl(nh.NLE_BL_AC)
        for i, (at, ad, n, d) in enumerate(ATTACKS[idx]):
            if model2 and at == "MAGC":
                q = cast_chance(ad, level, pm.mmove)
                if q:
                    us = {"resists": self.our_resists(), "hurt": hurt, "wizard": name == "Wizard of Yendor",
                          "blind": bool(int(self.last_bl[nh.NLE_BL_CONDITION]) & nh.BL_MASK_BLIND)}
                    cast, death = cast_profile(ad, level, n, d, us)
                    pmf = conv(pmf, self._mix(np.array([1.0]), cast, q))
                    alive *= 1 - q * death
                continue
            if at not in MELEE:
                continue
            p = self.hit_prob(level, i, bonus)
            # a cold hit is zeroed only when we resist cold (mhitu.c AD_COLD 1076)
            # (A/B dmg_cold: 0, median 7726 -> 7726, 0 of 1000 changed)
            zero = ad in NO_DAMAGE or (ad == "COLD" and "cold" in self.our_resists())
            dmg = dice_pmf(n, d) if n and d and not zero else np.array([1.0])
            if at == "WEAP":
                w = self.danger.mon_weapon.get(name)
                if w or not (model2 and name in self.danger.mon_unarmed):
                    dmg = conv(dmg, dice_pmf(1, WEAPON_DICE[w][0]) if w else dice_pmf(1, 6))
            if model2:
                dmg = ac_reduce(dmg, ac)                     # before the poison's own losehp (attrib.c poisoned)
            # (A/B dmg_ac -- negative AC takes rnd(-AC) off each hit: -1141 [-2242, -60], 7523)
            if ad in POISON and not self.surv.poison_res:
                alive *= 1 - p / 240                         # poisoned 1 in 8, deadly 1 in 30
                extra = np.concatenate([np.zeros(6), np.full(10, 0.1)])     # rn1(10, 6): 6..15
                # attrib.c:311-320 poisoned: i = rn2(30), 0 deadly, 1..5 an attribute, 6..29 the extra HP damage
                # (A/B dmg_poison -- the extra damage 24 in 240, not 5: -819 [-1613, -63], 7406)
                dmg = self._mix(dmg, conv(dmg, extra), 5 / 240)
            hit = self._mix(np.array([1.0]), dmg, p)
            pmf = conv(pmf, hit)
        return pmf, 1 - alive

    @staticmethod
    def _mix(a, b, w):
        n = max(len(a), len(b))
        out = np.zeros(n)
        out[:len(a)] += (1 - w) * a
        out[:len(b)] += w * b
        return out

    def monster_round(self, name, model2=False, hurt=False):
        """(damage pmf, P(instant death)) of this monster's actions in one game turn (mcalcmove); model2, hurt:
        monster_turn_pmf's."""
        pm = PM_BY_NAME.get(name)
        if pm is None:
            return np.array([1.0]), 0.0
        one, inst = self.monster_turn_pmf(name, model2=model2, hurt=hurt)
        k, frac = divmod(pm.mmove, 12)
        pk = np.array([1.0])
        for _ in range(k):
            pk = conv(pk, one)
        pmf = self._mix(pk, conv(pk, one), frac / 12) if frac else pk
        return pmf, 1 - (1 - inst) ** (k + frac / 12)

    # ------------------------------------------------------------ our attack: it may die before it acts
    def our_weapon(self):
        """(weapon type or None, enchantment, (to-hit die, damage die) of an artifact's attack bonus) of the weapon
        in hand."""
        it = next((i for i in self.items() if i.wielded), None)
        if it is None:
            return None, 0, (0, 0)
        _, ench, name = base_name(it.text)
        if "Excalibur" in it.text:
            return "long sword", (ench or 0), EXCALIBUR_BONUS
        name = WEAPON_NAME_OF.get(name, name)
        return (name if name in WEAPON_DICE else None), (ench or 0), (0, 0)

    def our_hit_prob(self, name, skill=0):
        """uhitm.c find_roll_to_hit: 1 + Luck(0) + abon + monster AC + XL + weapon to-hit - encumbrance > rnd(20);
        skill: our weapon skill's to-hit (uhitm.c:318 weapon_hit_bonus; focus.weapon_skill reads it)."""
        pm = PM_BY_NAME[name]
        st, dx, xl = self.bl(nh.NLE_BL_STR125), self.bl(nh.NLE_BL_DEX), self.bl(nh.NLE_BL_XP)
        abon = to_hit_abon(st, dx, xl)
        w, ench, (hit_die, _) = self.our_weapon()
        tmp = 1 + abon + pm.ac + xl + ench + (WEAPON_DICE[w][2] if w else 0) + skill
        # (A/B skill_bonus -- our to-hit and damage counted our weapon skill: -577 [-1832, +703], median 7134)
        # (A/B helpless_bonus -- to-hit +4 on monsters we slept, +2 on fleeing ones: -1049 [-1988, -67], median 7561)
        cap = self.bl(nh.NLE_BL_CAP)
        if cap:
            tmp -= cap * 2 - 1                    # encumbrance: near_capacity()
        if not hit_die:
            return min(max(tmp - 1, 0), 20) / 20
        return sum(min(max(tmp + k - 1, 0), 20) for k in range(1, hit_die + 1)) / (20 * hit_die)   # + rnd(die)

    def our_damage_pmf(self, name, skill=0):
        """weapon.c dmgval -- the small / large die + enchantment (not below 0), then less the erosion (rusty,
        corroded, ...: 1..3, not below 1) -- plus dbon, at least 1 (uhitm.c hmon); plus an artifact's damage die.
        skill: our weapon skill's damage (weapon_dam_bonus), only on a dmgval above 1 (uhitm.c:769 valid_weapon_attack,
        1111; focus.weapon_skill)."""
        pm = PM_BY_NAME[name]
        dbon = str_dbon(self.bl(nh.NLE_BL_STR125))       # weapon.c dbon
        w, ench, (_, dmg_die) = self.our_weapon()
        wielded = next((i for i in self.items() if i.wielded), None)
        eros = erosion(wielded.text) if w and wielded is not None else 0
        d = (WEAPON_DICE[w][1] if pm.msize >= 3 else WEAPON_DICE[w][0]) if w else 2
        base = dice_pmf(1, d)
        out = np.zeros(max(2, d + max(ench, 0) + dbon + max(skill, 0) + 1))
        for v in range(1, d + 1):
            dv = max(0, v + ench)
            if dv > 0:
                dv = max(1, dv - eros)
            out[max(1, dv + dbon + (skill if dv > 1 else 0))] += base[v]
        return conv(out, dice_pmf(1, dmg_die)) if dmg_die else out

    def our_kill_prob(self, name, hits, model2=False):
        """P(this attack kills it): it took `hits` hits of ours already and lives; its HP d(level, 8). model2
        (fight_model2_all): the newmonhp prior (fightmodel.hp_prior: golems their fixed HP) and our weapon skill."""
        pm = PM_BY_NAME.get(name)
        if pm is None:
            return 0.0
        lev = adj_level(pm.mlevel, self.bl(nh.NLE_BL_DEPTH), self.bl(nh.NLE_BL_XP))
        hp = hp_prior(name if model2 else None, lev)
        hit_sk, dmg_sk = self.weapon_skill() if model2 else (0, 0)
        one = self.our_damage_pmf(name, dmg_sk)
        dk = np.array([1.0])
        for _ in range(hits):
            dk = conv(dk, one)
        dk1 = conv(dk, one)
        cdf = lambda a, h: float(a[:h].sum())               # P(D < h)
        alive = sum(hp[h] * cdf(dk, h) for h in range(len(hp)) if hp[h])
        if alive <= 0:
            return 1.0                                      # it should be dead by now: a tougher one
        dies = sum(hp[h] * (cdf(dk, h) - cdf(dk1, h)) for h in range(len(hp)) if hp[h])
        return self.our_hit_prob(name, hit_sk) * dies / alive

    def fight_hits(self, pos):
        """Our hits on the monster at pos as the fight model counts them: focus.focus_hits_on (the message logged
        again at our 'F' skipped) under fight_model2_all, else our_hits (danger_tick: a hit seen in the turn we
        attacked)."""
        if self.opts.fight_model2_all:
            return self.focus_hits_on(pos)
        return self.danger.our_hits.get((self.cur_key, pos), 0)

    def danger_parts(self, pos, name):
        m2 = self.opts.fight_model2_all
        hits = self.fight_hits(pos)
        pmf, inst = self.monster_round(name, model2=m2, hurt=m2 and hits > 0)
        pk = self.our_kill_prob(name, hits, model2=m2) if name in PM_BY_NAME else 0.0
        lv = self.levels.get(self.cur_key)
        scared = lv is not None and self.pos() in lv.elbereth and self.respects(pos, name)
        return pos, pmf, inst, pk, scared

    def danger_combine(self, parts, target, hp):
        total, alive = np.array([1.0]), 1.0
        for pos, pmf, inst, pk, scared in parts:
            if scared and target is None:
                continue                                    # on Elbereth it won't melee us (attacking erases it)
            if pos == target:
                pmf = self._mix(pmf, np.array([1.0]), pk)
                inst *= 1 - pk
            total = conv(total, pmf)
            alive *= 1 - inst
        mean = float((np.arange(len(total)) * total).sum())
        p_dmg = float(total[hp:].sum()) if hp < len(total) else 0.0
        return mean, 1 - (1 - p_dmg) * alive

    def danger_tick(self, t, hp, adjacent):
        """Score the last prediction (with the attack we made since) against what happened; make the next."""
        pend = self.danger.pending
        self.danger.pending = None
        if pend is not None:
            pt, php, parts = pend
            target = self.acts.last_attack_target if self.danger.attack_turn == pt else None
            if target is not None and self.danger.hit_seen:
                key = (self.cur_key, target)
                self.danger.our_hits[key] = self.danger.our_hits.get(key, 0) + 1
            if t == pt + 1 and hp <= php:
                mean, pd = self.danger_combine(parts, target, php)
                self.danger_score((pt, php, mean, pd), php - hp, died=False)
        self.danger.hit_seen = False
        if adjacent:
            self.danger.pending = (t, hp, [self.danger_parts(pos, name) for pos, name in adjacent])

    def danger_score(self, pend, actual, died):
        _, hp0, mean, pd = pend
        bm = next(i for i in range(len(MEAN_EDGES) - 1) if mean < MEAN_EDGES[i + 1])
        r = self.danger.mean[bm]
        r[0] += 1; r[1] += mean; r[2] += actual
        bp = next(i for i in range(len(P_EDGES) - 1) if pd < P_EDGES[i + 1])
        r = self.danger.p[bp]
        r[0] += 1; r[1] += pd; r[2] += int(died or actual >= hp0)

    def danger_summary(self):
        if self.done and not self.truncated and self.danger.pending is not None:
            pt, php, parts = self.danger.pending
            target = self.acts.last_attack_target if self.danger.attack_turn == pt else None
            mean, pd = self.danger_combine(parts, target, php)
            self.danger_score((pt, php, mean, pd), php, died=True)
            self.danger.pending = None
        return {"mean": {f"{MEAN_EDGES[k]}-{MEAN_EDGES[k + 1]}": [v[0], round(v[1], 1), v[2]]
                         for k, v in sorted(self.danger.mean.items())},
                "p": {f"{P_EDGES[k]}-{P_EDGES[k + 1]}": [v[0], round(v[1], 3), v[2]]
                      for k, v in sorted(self.danger.p.items())}}

    # ------------------------------------------------------------ the fight to the end
    def win_prob(self, adjacent, sims=WIN_SIMS, max_turns=40, opening=None, approach=None, ranged=None):
        """P(we kill every adjacent hostile before they kill us), sampled (an RNG of our own, not the game's):
        each turn our actions (our_speed / 12) hit the lowest-level one alive (our_hit_prob, our_damage_pmf),
        then each one alive takes its round (monster_round: damage and the instant deaths). A monster's HP:
        d(level, 8), minus what our hits on it so far (fight_hits) took, drawn again while that would leave it dead.
        Under fight_model2_all the model focus uses: monster rounds and moves with model2 (hurt: we hit it), our
        to-hit and damage with our weapon skill (focus.weapon_skill), the HP from fightmodel.hp_prior. Others
        joining the fight are not counted; a fight still on after max_turns counts as won. adjacent: (pos, name);
        pos None for a monster that isn't there yet (the water demon a dip may bring).
        opening (wand_ev): our first action is a zap instead of a melee hit -- a function (rng, alive_at, apply) ->
        (damage to us, turns we sleep) that plays the zap out (combat.zap_opening): alive_at(pos) tells whether a
        monster of this fight is still at pos, apply(pos, damage or None for asleep) does the zap's effect on it.
        Its draws come from a generator of their own and the melee draws of that action are still made, so a fight
        with and one without the opening see the same monster HP and the same later rolls.
        approach (wand_ev): {pos: squares it still has to walk} -- such a monster spends its moves (mcalcmove:
        mmove / 12 a turn, the remainder by chance) walking up before it attacks, one attack per move after; we
        only hit monsters next to us (none there: we wait).
        ranged (with approach): {pos: threats.ranged_profile} -- the ranged attacks we saw that monster make, used
        without limit (ranged_plan / ranged_hit): a wand on every move, near or far (muse.c: it zaps instead of
        hitting); missiles and breath on a move it is not next to us, after its step (monmove.c dochug: a monster
        with a ranged attack may move and attack in one move)."""
        if self.cur_key is not None and self.cur_key in self.levels:
            adjacent = [t for t in adjacent if not self.asleep(self.levels[self.cur_key], t[0])]
        if not adjacent:
            return 1.0
        rng = self.danger.win_rng
        hp0 = self.bl(nh.NLE_BL_HP)
        m2 = self.opts.fight_model2_all
        hit_sk, dmg_sk = self.weapon_skill() if m2 else (0, 0)
        mons = []
        for pos, name in sorted(adjacent, key=lambda t: PM_BY_NAME[t[1]].mlevel if t[1] in PM_BY_NAME else 0):
            pm = PM_BY_NAME.get(name)
            if pm is None:
                continue
            lev = adj_level(pm.mlevel, self.bl(nh.NLE_BL_DEPTH), self.bl(nh.NLE_BL_XP))
            hits = self.fight_hits(pos)
            hurt = m2 and hits > 0
            rnd_pmf, inst = self.monster_round(name, model2=m2, hurt=hurt)
            mons.append(FightMon(max(lev, 0), self.our_hit_prob(name, hit_sk), self.our_damage_pmf(name, dmg_sk),
                                 rnd_pmf, inst, hits, pos, self.monster_turn_pmf(name, model2=m2, hurt=hurt), pm.mmove,
                                 name, self.monster_taint(name), self.monster_turn_pmf(name, 4, model2=m2, hurt=hurt),
                                 bool(pm.mflags1 & M1_REGEN), self.monster_paralysis(name), self.never_melee(name),
                                 self.monster_effects(name), hp_prior(name, lev) if m2 else None))
        if not mons:
            return 1.0
        # (A/B walk_fight_all -- every fight by the full walk_fight model: -2810 [-4263, -1271], 6891)
        index = {m.pos: j for j, m in enumerate(mons) if m.pos is not None}
        # the pmfs drawn from, as choice's tables, by object (they all live in mons for the whole call)
        cdfs = {id(q): pmf_cdf(q) for m in mons for q in (m.dmg, m.rnd, m.turn[0], m.turn_helpless[0], m.hp)
                if q is not None}
        state = self.our_state() if approach is not None else None
        plans = [self.ranged_plan(ranged.get(m.pos), m.name) if ranged else None for m in mons]
        zrng = self.danger.opening_rng
        sp = self.our_speed()
        k, frac = divmod(sp, 12)
        wins = 0
        for _ in range(sims):
            hps = []
            hcap = []
            for lev, dmg, hits, prior in ((m.lev, m.dmg, m.hits, m.hp) for m in mons):
                for _try in range(20):
                    if prior is not None:
                        h = full = cdf_draw(rng, cdfs[id(prior)])
                    elif lev > 0:
                        h = full = int(rng.integers(1, 9, size=lev).sum())
                    else:
                        h = full = int(rng.integers(1, 5))
                    if hits:
                        h -= cdf_draws(rng, cdfs[id(dmg)], hits)
                    if h > 0:
                        break
                hps.append(max(h, 1))
                hcap.append(max(full, h, 1))             # regeneration stops at its full HP
            hp, alive, asleep = hp0, list(range(len(mons))), 0
            if approach is not None:
                end, tainted = self.walk_fight(mons, hps, hp, approach, opening, rng, zrng, index, max_turns, cdfs,
                                               plans, hcap, state)
                if end > 0:
                    wins += TAINTED_WIN if tainted else 1
                continue
            for _turn in range(max_turns):
                acts = k + (1 if frac and rng.random() < frac / 12 else 0)
                for _a in range(acts):
                    if not alive:
                        break
                    j = alive[0]
                    hit = rng.random() < mons[j].hit
                    d = cdf_draw(rng, cdfs[id(mons[j].dmg)]) if hit else 0
                    if opening is not None and _turn == 0 and _a == 0:
                        lost, asleep, _ = opening(zrng, *opening_hooks(index, alive, hps))
                        hp -= lost
                        continue
                    if asleep > 0:
                        continue                         # our own ray put us to sleep
                    if hit:
                        hps[j] -= d
                        if hps[j] <= 0:
                            alive.pop(0)
                if not alive:
                    break
                asleep -= 1
                if hp <= 0:
                    break
                for j in alive:
                    if rng.random() < mons[j].inst:
                        hp = 0
                        break
                    hp -= cdf_draw(rng, cdfs[id(mons[j].rnd)])
                if hp <= 0:
                    break
            if hp > 0:
                wins += 1
        return wins / sims

    def walk_fight(self, mons, hps, hp, approach, opening, rng, zrng, index, max_turns, cdfs, plans=None, hcap=None,
                   state=None):
        """One sampled fight of win_prob with approach (see there): (our HP at its end -- <= 0: lost, tainted: it
        blinded us, gave us lycanthropy, charmed and robbed us or took our gold -- TAINT_AD, a yellow light's or
        a black light's (hallucination) explosion, a lightning bolt's flash -- so a win counts TAINTED_WIN).
        monster_effects of its hits: asleep, stunned / confused (our blows go astray), slowed (our speed
        without intrinsic Fast), stoned, our brain eaten (Int). Monsters that regenerate (M1_REGEN) get 1 HP a
        turn back (mon.c mon_regen); a paralysing hit (or a gelatinous cube we hit) freezes us
        (monster_paralysis), and while we sleep or are frozen they hit us +4 (mhitu.c); confused or stunned
        (state) our blow goes astray as domove's confdir sends it; we never hit the kinds we never melee
        (perception.never_melee: a floating eye, a cockatrice when we hold no weapon)."""
        state = state or self.our_state()
        left = [approach.get(m.pos, 0) for m in mons]
        plans = plans or [None] * len(mons)
        cool = [0] * len(mons)                   # breath: turns until it can breathe again
        alive, asleep, tainted = list(range(len(mons))), 0, False
        us = {"stun": 0, "conf": 0, "slow": False, "int": state.get("int", 18)}
        for _turn in range(max_turns):
            k, frac = divmod(state["speed_slow"] if us["slow"] else state.get("speed", self.our_speed()), 12)
            acts = k + (1 if frac and rng.random() < frac / 12 else 0)
            aim = 1 / 8 if us["stun"] > 0 else 0.8 + 0.2 / 8 if us["conf"] > 0 else state["aim"]
            for _a in range(acts):
                if not alive:
                    break
                ready = [j for j in alive if left[j] == 0 and not mons[j].never]      # never_melee: a floating eye
                j = ready[0] if ready else None
                hit = j is not None and rng.random() < mons[j].hit * aim
                d = cdf_draw(rng, cdfs[id(mons[j].dmg)]) if hit else 0
                if opening is not None and _turn == 0 and _a == 0:
                    lost, asleep, blind = opening(zrng, *opening_hooks(index, alive, hps))
                    hp -= lost
                    tainted |= blind
                    continue
                if asleep > 0 or j is None:
                    continue
                if hit:
                    hps[j] -= d
                    if hps[j] <= 0:
                        alive.remove(j)
                        continue
                    p_passive = 2 / 3
                else:
                    # uhitm.c:628 hitum calls passive on a miss too (2 in 3 while it lives, uhitm.c:2873) -- if
                    # the blow went at it: a stunned / confused one may have gone astray
                    # (A/B dmg_cube: -233 [-848, +383], median 7726 -> 7726, 86 of 1000 changed)
                    p, a = mons[j].hit, aim
                    p_passive = 2 / 3 * a * (1 - p) / (1 - p * a) if p * a < 1 else 0.0
                if mons[j].plys[1] and not state["free_action"] and rng.random() < p_passive:
                    n, die = mons[j].plys[1]              # uhitm.c passive: a gelatinous cube freezes us
                    asleep = max(asleep, min(127, int(rng.integers(1, die + 1, size=n).sum())))
            if not alive or hp <= 0:
                break
            asleep -= 1
            us["stun"] -= 1
            us["conf"] -= 1
            for j in list(alive):
                if mons[j].regen and hcap is not None and hps[j] < hcap[j]:
                    hps[j] += 1                          # mon_regen
                (one, inst), speed, (p_taint, explodes) = mons[j].turn, mons[j].speed, mons[j].taint
                if asleep > 0:
                    one, inst = mons[j].turn_helpless     # we are helpless: +4 to hit us
                mk, mf = divmod(speed, 12)
                moves = mk + (1 if mf and rng.random() < mf / 12 else 0)
                plan = plans[j]
                if plan is not None:
                    cool[j] -= 1
                for _m in range(moves):
                    if left[j] > 0:
                        left[j] -= 1                     # its step; then a ranged attack, a melee one only next to us
                        if plan is None:
                            continue
                    if plan is not None:
                        dmg, sleep, blind = self.ranged_hit(plan, left[j] + 1, cool, j, rng, asleep > 0)
                        if dmg is not None:
                            hp -= dmg
                            asleep, tainted = max(asleep, sleep), tainted or blind
                            if hp <= 0:
                                return hp, tainted
                            continue
                        if left[j] > 0:
                            continue
                    if explodes:
                        tainted = True                   # mhitu.c explmu: it blows up, blinding us
                        alive.remove(j)
                        break
                    if rng.random() < inst:
                        return 0, tainted
                    hp -= cdf_draw(rng, cdfs[id(one)])
                    if p_taint and rng.random() < p_taint:
                        tainted = True
                    p_plys = mons[j].plys[0]
                    if p_plys and asleep <= 0 and not state["free_action"] and rng.random() < p_plys:
                        asleep = int(rng.integers(1, 11))    # mhitu.c AD_PLYS: nomul(-rnd(10))
                    for p, kind, n, die in mons[j].effects:
                        if rng.random() >= p:
                            continue
                        if kind == "ston":
                            return 0, tainted            # stoned (no lizard / acid counted)
                        if kind == "drin":
                            if us["int"] <= 3:
                                return 0, tainted        # eat.c eat_brains: "Your last thought fades away."
                            us["int"] -= int(rng.integers(1, 3))
                        elif kind == "sleep":
                            if asleep <= 0 and not state.get("sleep_res"):
                                asleep = int(rng.integers(1, 11))
                        elif kind == "slow":
                            us["slow"] = True
                        else:                            # stun / conf: the attack's dice more turns of it
                            us[kind] = max(us[kind], 0) + int(rng.integers(1, die + 1, size=max(n, 1)).sum())
                    if hp <= 0:
                        return hp, tainted
        return hp, tainted

    def monster_effects(self, name):
        """What one move of its melee may do to us besides damage, as [(P per move, kind, dice n, die)] (mhitu.c):
        AD_SLEE 1 in 5 of the hits, asleep rnd(10) (not if we resist sleep); AD_STUN 1 in 4, stunned for the
        attack's dice; AD_CONF 1 in 4, confused the same; AD_SLOW 1 in 4, we lose intrinsic speed; AD_STON
        (a cockatrice's touch) 1 in 3 hissing, then 1 in 10: stoned; AD_DRIN (a mind flayer's tentacle) unless
        our helmet blocks it (7 in 8): Int -rnd(2), at Int 3 our last thought fades."""
        idx = PM_INDEX.get(name)
        if idx is None:
            return []
        level = adj_level(nh.permonst(idx).mlevel, self.bl(nh.NLE_BL_DEPTH), self.bl(nh.NLE_BL_XP))
        helmet = None
        out = []
        for i, (at, ad, n, d) in enumerate(ATTACKS[idx]):
            if at not in MELEE:
                continue
            hit = self.hit_prob(level, i)
            if ad == "SLEE":
                out.append((hit / 5, "sleep", n, d))
            elif ad == "STUN":
                out.append((hit / 4, "stun", n, d))
            elif ad == "CONF":
                out.append((hit / 4, "conf", n, d))
            elif ad == "SLOW" and self.bl(nh.NLE_BL_XP) >= 7:
                out.append((hit / 4, "slow", n, d))     # only intrinsic Fast is lost (our_speed's Valkyrie)
            elif ad == "STON":
                out.append((hit / 30, "ston", n, d))
            elif ad == "DRIN":
                if helmet is None:
                    helmet = any(a["worn"] and a["slot"] == "helm" for a in self.armor_inventory())
                out.append((hit / 8 if helmet else hit, "drin", n, d))
        return out

    def monster_paralysis(self, name):
        """(P(one move of its melee freezes us): mhitu.c AD_PLYS, 1 in 3 of the hits, for rnd(10) turns; the
        dice of its passive paralysis when we hit it and it lives, and when we miss it too -- uhitm.c passive, 2 in
        3: d(damn, damd) turns, d(level + 1, die) when damn is 0 -- or None).
        (A/B dmg_cube: -233 [-848, +383], median 7726 -> 7726, 86 of 1000 changed)"""
        keep, passive = 1.0, None
        idx = PM_INDEX.get(name)
        if idx is None:
            return 0.0, None
        level = adj_level(nh.permonst(idx).mlevel, self.bl(nh.NLE_BL_DEPTH), self.bl(nh.NLE_BL_XP))
        for i, (at, ad, n, d) in enumerate(ATTACKS[idx]):
            if ad != "PLYS":
                continue
            if at == "NONE":
                # uhitm.c:2755-2758 passive: d(damn, damd) -- d(m_lev + 1, damd) only when damn is 0 (a floating eye);
                # a gelatinous cube's is d(1, 4)
                passive = (n, d) if n else (level + 1, d)
            elif at in MELEE:
                keep *= 1 - self.hit_prob(level, i) / 3
        return 1 - keep, passive

    def our_state(self):
        """What our condition does to a fight we simulate: aim -- P(our blow goes where we meant): stunned, a
        random direction always, confused 1 in 5 (hack.c:1442 domove confdir; 1 in 8 random ones is right anyway)."""
        cond = int(self.last_bl[nh.NLE_BL_CONDITION])
        if cond & nh.BL_MASK_STUN:
            aim = 1 / 8
        elif cond & nh.BL_MASK_CONF:
            aim = 0.8 + 0.2 / 8
        else:
            aim = 1.0
        its = self.items()
        free = any(i.ring_on and "free action" in i.text for i in its)
        prot = self.our_resists()
        sp = self.our_speed()
        slow = 12 * 3 // 4 if self.bl(nh.NLE_BL_CAP) >= 1 else 12
        return {"aim": aim, "free_action": free, "int": self.bl(nh.NLE_BL_INT), "speed": sp,
                "speed_slow": min(sp, slow), "sleep_res": "sleep" in prot}

    def pack_profile(self):
        """What a ray hitting us can blow up in our pack (zap.c zhitu -> destroy_item): the potion stacks'
        sizes, and the wands that are not of lightning."""
        its = self.items()
        return {"potions": [base_name(i.text)[0] for i in its if i.ocls == nh.POTION_CLASS],
                "wands": sum(1 for i in its if i.ocls == nh.WAND_CLASS and "wand of lightning" not in i.text)}

    @staticmethod
    def pack_blast(kind, pack, prot, rng):
        """Damage from our own items a ray of `kind` destroyed (zap.c zhitu / destroy_one_item: fire 1 in 3,
        each potion stack goes when one of its potions does (2 in 3 each spared), rnd(6); cold the same, rnd(4);
        lightning 1 in 3, each wand stack, rnd(10) unless we resist shock). Resisting the ray itself does not
        save the potions."""
        dmg = 0
        if kind in ("fire", "cold") and pack["potions"] and rng.random() < 1 / 3:
            for q in pack["potions"]:
                if rng.random() >= (2 / 3) ** q:
                    dmg += int(rng.integers(1, 7 if kind == "fire" else 5))
        elif kind == "lightning" and pack["wands"] and rng.random() < 1 / 3 and "shock" not in prot:
            for _w in range(pack["wands"]):
                if rng.random() < 1 / 3:
                    dmg += int(rng.integers(1, 11))
        return dmg

    def monster_taint(self, name):
        """(P(one move of its melee blinds us, gives us lycanthropy, charms and robs us or takes our gold) -- TAINT_AD over the
        attacks of every kind of that name: a were's animal form bites -- , it explodes blinding: a yellow light)."""
        keep, explodes = 1.0, False
        for idx in PM_INDICES.get(name, ()):
            level = adj_level(nh.permonst(idx).mlevel, self.bl(nh.NLE_BL_DEPTH), self.bl(nh.NLE_BL_XP))
            for i, (at, ad, _, _) in enumerate(ATTACKS[idx]):
                if at == "EXPL" and ad in ("BLND", "HALU"):
                    explodes = True                  # a yellow light blinds, a black light makes us hallucinate
                elif ad == "SGLD" and not self.bl(nh.NLE_BL_GOLD):
                    continue                     # nothing to steal
                elif at in MELEE and ad in TAINT_AD:
                    keep *= 1 - self.hit_prob(level, i) * TAINT_AD[ad]
        return 1 - keep, explodes

    def ranged_plan(self, profile, name):
        """What a monster's seen ranged attacks do to us, for ranged_hit (None: none seen)."""
        if profile is None:
            return None
        ac = self.bl(nh.NLE_BL_AC)
        prot = self.our_resists()
        plan = {"wand": next((k for k in WAND_ORDER if k in profile["wands"]), None), "missile": None,
                "breath": None, "ray_p": zap_hit_prob(ac), "ac": ac, "prot": prot, "pack": self.pack_profile()}
        mis = profile["missile"]
        if mis:
            plan["missile"] = (MISSILE_DIE.get(mis["kind"], WEAPON_DICE.get(mis["kind"], (6,))[0]), mis["counts"],
                               mis["poisoned"] and not self.surv.poison_res)
        if profile["breath"]:
            idx = PM_INDEX.get(name)
            br = next((a for a in ATTACKS[idx] if a[0] == "BREA"), None) if idx is not None else None
            if br is not None:
                plan["breath"] = (BREATH_KIND.get(br[1], "fire"), br[2])
        return plan

    @staticmethod
    def ranged_hit(plan, dist, cool, j, rng, we_sleep=False):
        """One move's ranged attack of a monster `dist` squares away by its plan: (damage to us or None when it
        has no ranged attack to make, turns we fall asleep, a lightning flash blinded us). zap.c buzz/zhitu (a ray: zap_hit by our AC,
        reflection, resistance, 6d6 / magic missile 2d6 / sleep d(6, 25) / death), bhitm striking (rnd(20) < 10 +
        AC, 2d12, magic resistance), mthrowu.c m_throw / thitu (a missile hits when rnd(20) < AC + 8 + 3 - distance;
        a poisoned one: 1 in 30 deadly, else mostly rnd(6) more), mhitu.c breamu (2 in 3, then 10..29 turns
        before the next). A wand of sleep is not zapped at us asleep (muse.c find_offensive: multi >= 0): it
        fights on instead."""
        ac, prot = plan["ac"], plan["prot"]

        def ray(kind, nd):
            if rng.random() >= plan["ray_p"] or "reflection" in prot:
                return 0, 0, False
            blind = kind == "lightning"                  # zap.c flashburn, resisted or not
            blast = DangerMixin.pack_blast(kind, plan["pack"], prot, rng)
            if kind == "death":
                return (0, 0, False) if "magic" in prot else (10 ** 6, 0, False)
            if RAY_RESIST.get(kind) in prot:
                return blast, 0, blind
            if kind == "sleep":
                return 0, int(rng.integers(1, 26, size=6).sum()), False
            return int(rng.integers(1, 7, size=nd).sum()) + blast, 0, blind

        wand = None if plan["wand"] == "sleep" and we_sleep else plan["wand"]
        if wand == "striking":
            if "magic" in prot or rng.integers(1, 21) >= 10 + ac:
                return 0, 0, False
            return int(rng.integers(1, 13, size=2).sum()), 0, False
        if wand:
            return ray(wand, 2 if wand == "magic missile" else 6)
        if dist < 2:
            return None, 0, False
        if plan["missile"]:
            die, counts, poisoned = plan["missile"]
            dmg = 0
            for _s in range(counts[int(rng.integers(len(counts)))]):
                if rng.integers(1, 21) < ac + 11 - dist:
                    dmg += int(rng.integers(1, die + 1))
                    if poisoned:
                        r = rng.integers(30)
                        if r == 0:
                            return 10 ** 6, 0, False
                        if r > 5:
                            dmg += int(rng.integers(1, 7))
            return dmg, 0, False
        if plan["breath"] and cool[j] <= 0 and rng.random() < 2 / 3:
            cool[j] = 10 + int(rng.integers(20))
            return ray(*plan["breath"])
        return 0, 0, False

    # ------------------------------------------------------------ our speed
    def our_speed(self):
        """12; a Valkyrie is intrinsically Fast from XL 7 (allmain.c: a full extra move 1 turn in 3 -- 16 on
        average); Burdened 3/4."""
        sp = 16 if self.bl(nh.NLE_BL_XP) >= 7 else 12
        return sp * 3 // 4 if self.bl(nh.NLE_BL_CAP) >= 1 else sp
