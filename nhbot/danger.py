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
Our attack comes first in the turn: the monster we attack doesn't act if this hit kills it -- P(hit) by
uhitm.c find_roll_to_hit (Luck taken as 0) and P(kill | alive) from its HP d(level, 8) against our damage
dice (dmgval + enchantment + dbon) over the hits we already landed on it.
Standing on Elbereth (read back) a monster that respects it doesn't melee us -- unless we attack, which
erases it (mon.c setmangry).
P(death) = P(total damage >= HP) combined with the instant deaths. Calibration (summary 'danger'): predicted
mean damage and P(death) against what the next turn did.
"""
import re
from collections import Counter, defaultdict

import numpy as np
import nle.nethack as nh

from nhbot.carry import WEAPON_NAME_OF
from nhbot.items import base_name
from nhbot.monattacks import ATTACKS
from nhbot.monsters import PM_BY_NAME
from nhbot.weapondice import WEAPON_DICE

MELEE = {"CLAW", "BITE", "KICK", "BUTT", "TUCH", "STNG", "HUGS", "WEAP", "TENT"}
NO_DAMAGE = {"RUST", "CORR", "DCAY", "SGLD", "SEDU", "SSEX", "SLIM", "ENCH", "CURS", "STON", "COLD"}
POISON = {"DRST", "DRDX", "DRCO"}
MAX_D = 400
MON_INDEX = {nh.permonst(i).mname: i for i in range(nh.NUMMONS)}
WIELD_RE = re.compile(r"The ([a-zA-Z' -]+?) (?:swings|thrusts|wields) (?:his|her|its|an?|the|\d+)? ?([a-z' -]+?)[.!]")
FLEE_P = 0.5                     # flee: P(death this turn) above this
FLEE_TURNS = 30                  # flee: keep trying to get away this long after writing Elbereth
FLEE_DIST = 3                    # flee: toward a square at least this far (Chebyshev) from every hostile in view
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
        self.danger_pending = None               # (turn, hp, [(pos, pmf, P(instant death), P(we kill it), scared)])
        self.our_hits = {}                       # (level key, square) -> our hits on the monster there
        self.hit_seen = False                    # this tick: a melee hit of ours
        self.attack_turn = -1                    # turn of our last melee attack (combat.attack)
        self.flee_stats = Counter()
        self.flee_mode = None                    # flee: (level key, until turn) after writing Elbereth
        self.danger_mean = defaultdict(lambda: [0, 0.0, 0.0])    # bin -> [n, sum predicted, sum actual]
        self.danger_p = defaultdict(lambda: [0, 0.0, 0])         # bin -> [n, sum predicted, deaths]

    def danger_msg(self, m):
        if re.search(r"\bYou (?:hit|smite|strike|bite|kick|butt|sting|touch)\b", m):
            self.hit_seen = True
        if re.search(r"\bYou (?:kill|destroy)\b", m) and self.last_attack_target is not None:
            self.our_hits.pop((self.cur_key, self.last_attack_target), None)
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

    def monster_round(self, name):
        """(damage pmf, P(instant death)) of this monster's actions in one game turn (mcalcmove)."""
        pm = PM_BY_NAME.get(name)
        if pm is None:
            return np.array([1.0]), 0.0
        one, inst = self.monster_turn_pmf(name)
        k, frac = divmod(pm.mmove, 12)
        pk = np.array([1.0])
        for _ in range(k):
            pk = conv(pk, one)
        pmf = self._mix(pk, conv(pk, one), frac / 12) if frac else pk
        return pmf, 1 - (1 - inst) ** (k + frac / 12)

    # ------------------------------------------------------------ our attack: it may die before it acts
    def our_weapon(self):
        it = next((i for i in self.items() if i.wielded), None)
        if it is None:
            return None, 0
        _, ench, name = base_name(it.text)
        name = WEAPON_NAME_OF.get(name, name)
        return (name if name in WEAPON_DICE else None), (ench or 0)

    def our_hit_prob(self, name):
        """uhitm.c find_roll_to_hit: 1 + Luck(0) + abon + monster AC + XL + weapon to-hit > rnd(20)."""
        pm = PM_BY_NAME[name]
        st, dx, xl = self.bl(nh.NLE_BL_STR125), self.bl(nh.NLE_BL_DEX), self.bl(nh.NLE_BL_XP)
        abon = -2 if st < 6 else -1 if st < 8 else 0 if st < 17 else 1 if st <= 68 else 2 if st < 118 else 3
        abon += (1 if xl < 3 else 0) + (-3 if dx < 4 else -2 if dx < 6 else -1 if dx < 8 else 0 if dx < 14 else dx - 14)
        w, ench = self.our_weapon()
        tmp = 1 + abon + pm.ac + xl + ench + (WEAPON_DICE[w][2] if w else 0)
        return min(max(tmp - 1, 0), 20) / 20

    def our_damage_pmf(self, name):
        """dmgval (small / large dice + enchantment) + dbon, at least 1."""
        pm = PM_BY_NAME[name]
        st = self.bl(nh.NLE_BL_STR125)
        dbon = -1 if st < 6 else 0 if st < 16 else 1 if st < 17 else 2 if st == 18 else 3 if st <= 93 \
            else 4 if st <= 108 else 5 if st < 118 else 6
        w, ench = self.our_weapon()
        d = (WEAPON_DICE[w][1] if pm.msize >= 3 else WEAPON_DICE[w][0]) if w else 2
        base = dice_pmf(1, d)
        out = np.zeros(max(2, d + ench + dbon + 1))
        for v in range(1, d + 1):
            out[max(1, v + ench + dbon)] += base[v]
        return out

    def our_kill_prob(self, name, hits):
        """P(this attack kills it): it took `hits` hits of ours already and lives; its HP d(level, 8)."""
        pm = PM_BY_NAME.get(name)
        if pm is None:
            return 0.0
        lev = adj_level(pm.mlevel, self.bl(nh.NLE_BL_DEPTH), self.bl(nh.NLE_BL_XP))
        hp = dice_pmf(lev, 8) if lev > 0 else dice_pmf(1, 4)
        one = self.our_damage_pmf(name)
        dk = np.array([1.0])
        for _ in range(hits):
            dk = conv(dk, one)
        dk1 = conv(dk, one)
        cdf = lambda a, h: float(a[:h].sum())               # P(D < h)
        alive = sum(hp[h] * cdf(dk, h) for h in range(len(hp)) if hp[h])
        if alive <= 0:
            return 1.0                                      # it should be dead by now: a tougher one
        dies = sum(hp[h] * (cdf(dk, h) - cdf(dk1, h)) for h in range(len(hp)) if hp[h])
        return self.our_hit_prob(name) * dies / alive

    def danger_estimate(self, adjacent, target=None):
        """(mean damage, P(death)) over the next game turn from the adjacent hostiles [(pos, name)]; target: the
        square we attack first (if it dies, it doesn't act)."""
        hp = self.bl(nh.NLE_BL_HP)
        return self.danger_combine([self.danger_parts(pos, name) for pos, name in adjacent], target, hp)

    def danger_parts(self, pos, name):
        pmf, inst = self.monster_round(name)
        pk = self.our_kill_prob(name, self.our_hits.get((self.cur_key, pos), 0)) if name in PM_BY_NAME else 0.0
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
        pend = self.danger_pending
        self.danger_pending = None
        if pend is not None:
            pt, php, parts = pend
            target = self.last_attack_target if self.attack_turn == pt else None
            if target is not None and self.hit_seen:
                key = (self.cur_key, target)
                self.our_hits[key] = self.our_hits.get(key, 0) + 1
            if t == pt + 1 and hp <= php:
                mean, pd = self.danger_combine(parts, target, php)
                self.danger_score((pt, php, mean, pd), php - hp, died=False)
        self.hit_seen = False
        if adjacent:
            self.danger_pending = (t, hp, [self.danger_parts(pos, name) for pos, name in adjacent])

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
            pt, php, parts = self.danger_pending
            target = self.last_attack_target if self.attack_turn == pt else None
            mean, pd = self.danger_combine(parts, target, php)
            self.danger_score((pt, php, mean, pd), php, died=True)
            self.danger_pending = None
        return {"mean": {f"{MEAN_EDGES[k]}-{MEAN_EDGES[k + 1]}": [v[0], round(v[1], 1), v[2]]
                         for k, v in sorted(self.danger_mean.items())},
                "p": {f"{P_EDGES[k]}-{P_EDGES[k + 1]}": [v[0], round(v[1], 3), v[2]]
                      for k, v in sorted(self.danger_p.items())}}

    # ------------------------------------------------------------ flee (flag flee)
    def our_speed(self):
        """12; a Valkyrie is intrinsically Fast from XL 7 (2 moves in 3 get +6: 16 on average); Burdened 3/4."""
        sp = 16 if self.bl(nh.NLE_BL_XP) >= 7 else 12
        return sp * 3 // 4 if self.bl(nh.NLE_BL_CAP) >= 1 else sp

    def flee_step(self, lv, hostiles):
        """flee: P(death this turn) > FLEE_P.
          faster than every hostile in view: step away along squares that touch none of them;
          else, if Elbereth would hold them all (elb_blocked: no ranged / Elbereth-ignoring one) and we can
          write here: write it, then for FLEE_TURNS keep trying to step away the same way, waiting on the
          square (never attacking: that erases it) while no such path exists.
        True if it used the turn."""
        if not self.opts.flee:
            return False
        fm = self.flee_mode
        if fm is not None and (fm[0] != lv.key or self.turn() > fm[1] or not self.visible_hostiles(lv)):
            self.flee_mode = fm = None
        if fm is None:
            if not hostiles:
                return False
            target = min(hostiles, key=lambda t: self.mon_level(t[0]))[0]       # what melee would hit first
            if self.danger_estimate(hostiles, target)[1] <= FLEE_P:
                return False
            if self.faster_than_all(lv):
                if self.flee_walk(lv):
                    self.flee_stats["fled"] += 1
                    return True
                self.flee_stats["no_path"] += 1          # hemmed in: Elbereth as for faster ones
            if self.elb_can_write(lv) and not self.elb_blocked(lv):
                self.cur_act = "flee"
                if self.engrave_elbereth():
                    self.flee_mode = (lv.key, self.turn() + FLEE_TURNS)
                    self.flee_stats["elbereth"] += 1
                    return True
            self.flee_stats["no_escape"] += 1
            return False
        if self.flee_walk(lv):                  # on Elbereth: away once a path clear of them opens
            self.flee_stats["elb_fled"] += 1
            self.flee_mode = None
            return True
        if (self.pos() in lv.elbereth or self.elb_confirm(lv)) and hostiles:
            self.cur_act = "flee"
            self.flee_stats["elb_wait"] += 1
            self.press("s")
            return True
        self.flee_mode = None                   # Elbereth gone or nobody next to us: back to normal
        return False

    def faster_than_all(self, lv):
        sp = self.our_speed()
        return all(PM_BY_NAME[n].mmove < sp for _, n in self.visible_hostiles(lv) if n in PM_BY_NAME)

    def flee_walk(self, lv):
        """One step along squares next to no hostile in view, toward a square FLEE_DIST from all of them."""
        seen = self.visible_hostiles(lv)
        if not seen:
            return False
        k_mem, k_live, passable = self.grids(lv)
        near = np.zeros_like(passable)
        far = np.ones_like(passable)
        for (y, x), _ in seen:
            near[max(0, y - 1):y + 2, max(0, x - 1):x + 2] = True
            far[max(0, y - FLEE_DIST + 1):y + FLEE_DIST, max(0, x - FLEE_DIST + 1):x + FLEE_DIST] = False
        ok = passable & ~near
        ok[self.pos()] = True
        status, _ = self.walk_to(lv, far & ok, max_cost=40, act="flee", grids=(k_mem, k_live, ok))
        return status == "moved"
