"""Melee danger estimate (logging only for now): from the monsters next to us, the distribution of the damage we
take in the next game turn, and so the chance it kills us (NetHack 3.6.6 mhitu.c / makemon.c / mon.c).

Per adjacent hostile, per action it gets this turn (mcalcmove: mmove / 12 actions, the remainder a random
extra one), per melee attack i of its type (monattacks.ATTACKS):
  hit      if 10 + AC_VALUE(our AC) + level > rnd(20 + i)   (AC_VALUE: a negative AC counts as -rnd(-AC))
  level    makemon.c adj_lev from the base level, the depth and our XL (a grown-up monster: unknown)
  damage   d(n, d), plus the weapon's small-monster dice for a weapon attack (the weapon we saw it swing or
           thrust; else a d6 guess); cold: none (Valkyries resist); rust / steal / seduce ...: none
  poison   a hit of a poisoning attack poisons 1 in 8: deadly 1 in 30 without poison resistance, else
           rn1(10, 6) more damage 5 in 30
P(death) = P(total damage >= HP) combined with the instant deaths. Calibration (summary 'danger'): predicted
mean damage and P(death) against what the next turn did.
"""
import re
from collections import defaultdict

import numpy as np
import nle.nethack as nh

from nhbot.monattacks import ATTACKS
from nhbot.monsters import PM_BY_NAME
from nhbot.weapondice import WEAPON_DICE

MELEE = {"CLAW", "BITE", "KICK", "BUTT", "TUCH", "STNG", "HUGS", "WEAP", "TENT"}
NO_DAMAGE = {"RUST", "CORR", "DCAY", "SGLD", "SEDU", "SSEX", "SLIM", "ENCH", "CURS", "STON", "COLD"}
POISON = {"DRST", "DRDX", "DRCO"}
MAX_D = 400
MON_INDEX = {nh.permonst(i).mname: i for i in range(nh.NUMMONS)}
WIELD_RE = re.compile(r"The ([a-zA-Z' -]+?) (?:swings|thrusts|wields) (?:his|her|its|an?|the|\d+)? ?([a-z' -]+?)[.!]")
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


class DangerMixin:
    def danger_init(self):
        self.mon_weapon = {}                     # monster name -> weapon we saw it use
        self.danger_pending = None               # (turn, hp, mean, p_death)
        self.danger_mean = defaultdict(lambda: [0, 0.0, 0.0])    # bin -> [n, sum predicted, sum actual]
        self.danger_p = defaultdict(lambda: [0, 0.0, 0])         # bin -> [n, sum predicted, deaths]

    def danger_msg(self, m):
        for mon, weapon in WIELD_RE.findall(m):
            w = re.sub(r"s$", "", weapon) if weapon not in WEAPON_DICE else weapon
            if w in WEAPON_DICE:
                self.mon_weapon[mon] = w

    def hit_prob(self, level, i):
        """P(10 + AC_VALUE(ac) + level > rnd(20 + i))."""
        ac = self.bl(nh.NLE_BL_AC)
        n = 20 + i
        acs = [ac] if ac >= 0 else [-k for k in range(1, -ac + 1)]
        p = 0.0
        for a in acs:
            tmp = 10 + a + level
            p += min(max(tmp - 1, 0), n) / n
        return p / len(acs)

    def monster_turn_pmf(self, name):
        """(damage pmf of one action of this monster, P(instant death) per action)."""
        idx = MON_INDEX.get(name)
        if idx is None:
            return np.array([1.0]), 0.0
        pm = nh.permonst(idx)
        level = adj_level(pm.mlevel, self.bl(nh.NLE_BL_DEPTH), self.bl(nh.NLE_BL_XP))
        pmf, alive = np.array([1.0]), 1.0
        for i, (at, ad, n, d) in enumerate(ATTACKS[idx]):
            if at not in MELEE:
                continue
            p = self.hit_prob(level, i)
            dmg = dice_pmf(n, d) if n and d and ad not in NO_DAMAGE else np.array([1.0])
            if at == "WEAP":
                w = self.mon_weapon.get(name)
                dmg = conv(dmg, dice_pmf(1, WEAPON_DICE[w][0]) if w else dice_pmf(1, 6))
            if ad in POISON and not self.poison_res:
                alive *= 1 - p / 240                         # poisoned 1 in 8, deadly 1 in 30
                extra = np.concatenate([np.zeros(6), np.full(10, 0.1)])     # rn1(10, 6): 6..15
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

    def danger_estimate(self, adjacent):
        """(mean damage, P(death)) over the next game turn from the adjacent hostiles [(pos, name)]."""
        total, alive = np.array([1.0]), 1.0
        for _, name in adjacent:
            pm = PM_BY_NAME.get(name)
            if pm is None:
                continue
            one, inst = self.monster_turn_pmf(name)
            k, frac = divmod(pm.mmove, 12)
            pk = np.array([1.0])
            for _ in range(k):
                pk = conv(pk, one)
            pmf = self._mix(pk, conv(pk, one), frac / 12) if frac else pk
            total = conv(total, pmf)
            alive *= (1 - inst) ** (k + frac / 12)
        hp = self.bl(nh.NLE_BL_HP)
        mean = float((np.arange(len(total)) * total).sum())
        p_dmg = float(total[hp:].sum()) if hp < len(total) else 0.0
        return mean, 1 - (1 - p_dmg) * alive

    def danger_tick(self, t, hp, adjacent):
        """Score the last prediction against what happened; make the next one."""
        pend = self.danger_pending
        self.danger_pending = None
        if pend is not None and t == pend[0] + 1 and hp <= pend[1]:
            self.danger_score(pend, pend[1] - hp, died=False)
        if adjacent:
            mean, pd = self.danger_estimate(adjacent)
            self.danger_pending = (t, hp, mean, pd)

    def danger_score(self, pend, actual, died):
        _, hp0, mean, pd = pend
        bm = next(i for i in range(len(MEAN_EDGES) - 1) if mean < MEAN_EDGES[i + 1])
        r = self.danger_mean[bm]
        r[0] += 1; r[1] += mean; r[2] += actual
        bp = next(i for i in range(len(P_EDGES) - 1) if pd < P_EDGES[i + 1])
        r = self.danger_p[bp]
        r[0] += 1; r[1] += pd; r[2] += int(died or actual >= hp0)

    def danger_summary(self):
        if self.done and not self.truncated and self.danger_pending is not None:
            self.danger_score(self.danger_pending, self.danger_pending[1], died=True)
            self.danger_pending = None
        return {"mean": {f"{MEAN_EDGES[k]}-{MEAN_EDGES[k + 1]}": [v[0], round(v[1], 1), v[2]]
                         for k, v in sorted(self.danger_mean.items())},
                "p": {f"{P_EDGES[k]}-{P_EDGES[k + 1]}": [v[0], round(v[1], 3), v[2]]
                      for k, v in sorted(self.danger_p.items())}}
