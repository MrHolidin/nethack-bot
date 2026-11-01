"""Melee target choice when several hostiles are adjacent: focus fire.

Rule (deterministic optimum of 'minimise damage taken while killing everyone', Smith's rule):
attack the monster with the largest  (damage it deals us per turn) / (turns we need to kill it).

Everything is computed from what a player can know:
  * monster attacks and damage dice, speed, AC, level, size: monst.c (monattacks.py) / permonst
  * monster to-hit (mhitu.c): hits if 10 + AC_VALUE(our AC) + level > rnd(20 + attack index)
  * our weapon dice: objects.c (weapondice.py), enchantment from the inventory line, Excalibur +d10
  * our to-hit (uhitm.c, simplified): 1 + abon + monster AC + our level + enchantment + weapon bonus > rnd(20)
  * monster HP is unknown: prior d(level, 8) (rnd(4) at level 0), conditioned on the hits we already
    landed on it (we count "You hit the X" at the square we attacked; the damage itself is not shown,
    so each hit counts as our expected damage).
"""
import re
from functools import lru_cache

import nle.nethack as nh

from monattacks import ATTACKS
from weapondice import WEAPON_DICE

MELEE = {"CLAW", "BITE", "KICK", "BUTT", "TUCH", "STNG", "HUGS", "TENT", "WEAP"}
NO_DAMAGE_AD = {"SSEX", "SEDU", "SGLD", "SITM", "STCK", "STON"}   # steal/seduce/stick: no HP damage
WEAP_EXTRA = 3.0          # AT_WEAP adds the wielded weapon's dice; we can't always tell what it holds


def _mean_dice(n, d):
    return n * (d + 1) / 2.0


def mon_hit_p(mlevel, my_ac, idx):
    acv = my_ac if my_ac >= 0 else -(abs(my_ac) + 1) / 2.0
    tmp = 10 + acv + mlevel
    return min(max((tmp - 1) / (20.0 + idx), 0.0), 1.0)


def mon_dpt(mon_idx, my_ac):
    """Expected HP damage per our turn (we move at speed 12)."""
    pm = nh.permonst(mon_idx)
    dmg = 0.0
    for i, (at, ad, n, d) in enumerate(ATTACKS[mon_idx]):
        if at not in MELEE or ad in NO_DAMAGE_AD:
            continue
        e = _mean_dice(n, d) + (WEAP_EXTRA if at == "WEAP" else 0.0)
        dmg += mon_hit_p(pm.mlevel, my_ac, i) * e
    return dmg * max(pm.mmove, 1) / 12.0


@lru_cache(maxsize=None)
def _hp_dist(level):
    if level <= 0:
        return {h: 0.25 for h in range(1, 5)}
    dist = {0: 1.0}
    for _ in range(level):
        nxt = {}
        for s, p in dist.items():
            for k in range(1, 9):
                nxt[s + k] = nxt.get(s + k, 0.0) + p / 8.0
        dist = nxt
    return dist


def expected_remaining_hp(level, dealt):
    """E[HP - dealt | HP > dealt] under the d(level,8) prior (it is still alive)."""
    dist = _hp_dist(min(level, 30))
    alive = {h: p for h, p in dist.items() if h > dealt}
    z = sum(alive.values())
    if z <= 1e-9:
        return 1.0                       # tougher than the prior allows (grown / higher level): ~1 hit left
    return sum((h - dealt) * p for h, p in alive.items()) / z


def str_dbon(s):
    if s < 6: return -1
    if s < 16: return 0
    if s < 18: return 1
    if s == 18: return 2
    if s <= 18 + 75: return 3
    if s <= 18 + 90: return 4
    if s < 18 + 100: return 5
    return 6


def to_hit_abon(s, dex, xl):
    sb = -2 if s < 6 else -1 if s < 8 else 0 if s < 17 else 1 if s <= 18 + 50 else 2 if s < 18 + 100 else 3
    if xl < 3:
        sb += 1
    db = -3 if dex < 4 else -2 if dex < 6 else -1 if dex < 8 else 0 if dex < 14 else dex - 14
    return sb + db


class FocusMixin:
    def focus_init(self):
        self.focus_hits = {}        # (level key, pos) -> [mon index, hits, last turn]
        self.focus_picks = 0        # times focus chose a different target than lowest-level
        self.focus_calls = 0

    def wielded(self):
        for _, ocls, s in self.inventory():
            if ocls == nh.WEAPON_CLASS and ("weapon in hand" in s or "(wielded)" in s):
                return s
        return None

    def my_attack(self, mon_idx):
        """(P(hit), expected damage per hit) against this monster type."""
        pm = nh.permonst(mon_idx)
        s = self.wielded()
        large = pm.msize >= 3
        ench, hitbon, dmg = 0, 0, 1.5            # bare hands d2
        if s:
            m = re.search(r"([+-]\d+) ", s)
            ench = int(m.group(1)) if m else 0
            name = next((w for w in sorted(WEAPON_DICE, key=len, reverse=True) if w in s), None)
            if name is None and "Excalibur" in s:
                name = "long sword"              # the inventory line names the artifact, not its base type
            if name:
                sd, ld, hitbon = WEAPON_DICE[name]
                dmg = ((ld if large else sd) + 1) / 2.0
            if "Excalibur" in s:
                dmg += 5.5
        st = self.bl(nh.NLE_BL_STR125)
        dex, xl = self.bl(nh.NLE_BL_DEX), self.bl(nh.NLE_BL_XP)
        dmg = max(dmg + ench + str_dbon(st), 1.0)
        tmp = 1 + to_hit_abon(st, dex, xl) + pm.ac + xl + ench + hitbon
        return min(max((tmp - 1) / 20.0, 0.05), 1.0), dmg

    def kill_one_hit_p(self, pos):
        """P(our next melee swing kills the monster at pos): P(hit) * P(damage >= its remaining HP), with the
        weapon dice + enchantment + Str bonus (+d10 Excalibur) and HP ~ d(level,8) conditioned on our landed hits."""
        g = int(self.obs["glyphs"][pos])
        if not nh.glyph_is_monster(g):
            return 0.0
        idx = nh.glyph_to_mon(g)
        pm = nh.permonst(idx)
        p_hit, mean_dmg = self.my_attack(idx)
        s = self.wielded()
        dice, ench = [2], 0                                # bare hands d2
        if s:
            m = re.search(r"([+-]\d+) ", s)
            ench = int(m.group(1)) if m else 0
            name = next((w for w in sorted(WEAPON_DICE, key=len, reverse=True) if w in s), None)
            if name is None and "Excalibur" in s:
                name = "long sword"
            if name:
                sd, ld, _ = WEAPON_DICE[name]
                dice = [ld if pm.msize >= 3 else sd]
            if "Excalibur" in s:
                dice.append(10)
        bonus = ench + str_dbon(self.bl(nh.NLE_BL_STR125))
        dmg = {0: 1.0}
        for d in dice:
            nxt = {}
            for v, p in dmg.items():
                for k in range(1, d + 1):
                    nxt[v + k] = nxt.get(v + k, 0.0) + p / d
            dmg = nxt
        dmg = {max(v + bonus, 1): p for v, p in dmg.items()}
        rec = self.focus_hits.get((self.cur_key, pos))
        dealt = (rec[1] if rec and rec[0] == idx and self.turn() - rec[2] <= 30 else 0) * mean_dmg
        hp = {h - dealt: p for h, p in _hp_dist(min(pm.mlevel, 30)).items() if h > dealt}
        z = sum(hp.values())
        if z <= 1e-9:
            return p_hit * 0.5
        kill = sum(ph * sum(pd for v, pd in dmg.items() if v >= h) for h, ph in hp.items()) / z
        return p_hit * kill

    def focus_note(self, m):
        """Count our landed hits on the square we attacked."""
        if not self.last_attack_target or self.cur_key is None:
            return
        n = len(re.findall(r"You (?:hit|smite) ", m))
        if not n:
            return
        pos = self.last_attack_target
        g = int(self.obs["glyphs"][pos])
        if not nh.glyph_is_monster(g):
            return
        key = (self.cur_key, pos)
        idx = nh.glyph_to_mon(g)
        rec = self.focus_hits.get(key)
        if rec is None or rec[0] != idx or self.turn() - rec[2] > 30:
            rec = [idx, 0, self.turn()]
        rec[1] += n
        rec[2] = self.turn()
        self.focus_hits[key] = rec

    def focus_score(self, pos):
        g = int(self.obs["glyphs"][pos])
        if not nh.glyph_is_monster(g):
            return 0.0
        idx = nh.glyph_to_mon(g)
        pm = nh.permonst(idx)
        p, dmg = self.my_attack(idx)
        rec = self.focus_hits.get((self.cur_key, pos))
        hits = rec[1] if rec and rec[0] == idx and self.turn() - rec[2] <= 30 else 0
        rem = expected_remaining_hp(pm.mlevel, hits * dmg)
        ttk = rem / max(p * dmg, 0.05)
        return mon_dpt(idx, self.bl(nh.NLE_BL_AC)) / max(ttk, 0.5)

    def focus_target(self, hostiles, fallback):
        self.focus_calls += 1
        best = max(hostiles, key=lambda t: self.focus_score(t[0]))[0]
        if best != fallback:
            self.focus_picks += 1
        return best
