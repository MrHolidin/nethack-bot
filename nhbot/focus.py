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

fight_model2 (A/B, options.py) scores the same rule from danger.py's model where it matched the true game state on
real games and fightmodel.py's fixes where it did not (scratchpad zi/fight_calib.py): fm2_parts.
"""
import re
from collections import deque
from functools import lru_cache

import numpy as np
import nle.nethack as nh

from nhbot.danger import adj_level
from nhbot.fightmodel import (BASIC, WEAPON_SKILL, hits_to_kill, hp_prior, remaining_hp, skill_bonus,
                              typical_monster, unseen_level)
from nhbot.messages import KILL_WORD_RE, OUR_HIT_RE
from nhbot.monattacks import ATTACKS
from nhbot.monsters import PM_BY_NAME
from nhbot.weapondice import WEAPON_DICE, str_dbon, to_hit_abon

MELEE = {"CLAW", "BITE", "KICK", "BUTT", "TUCH", "STNG", "HUGS", "TENT", "WEAP"}
NO_DAMAGE_AD = {"SSEX", "SEDU", "SGLD", "SITM", "STCK", "STON"}   # steal/seduce/stick: no HP damage
WEAP_EXTRA = 3.0          # AT_WEAP adds the wielded weapon's dice; we can't always tell what it holds
# fight_model2
SKILL_RE = re.compile(r"You are now (?:more|most) skilled in ([a-z -]+)\.")      # weapon.c:1138 skill_advance
UNSEEN_ATTACK_RE = re.compile(r"\bIt (?:hits|bites|stings|butts|touches you|kicks|misses|just misses)\b")
SEEN_ATTACK_RE = re.compile(r"\bThe [a-zA-Z' -]+? (?:hits|bites|stings|butts|touches you|kicks|misses|just misses)\b")
START_WEAPONS = {"Valkyrie": {"long sword", "dagger"}}   # u_init.c Valkyrie[]; weapon.c skill_init: those at Basic
UNSEEN_WINDOW = 20        # turns of unseen attacks an 'I' is scored from
HIT_MEMORY = 30           # turns our hits on a square are remembered (as focus_hits)


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


class FocusMixin:
    def focus_init(self):
        self.focus_hits = {}        # (level key, pos) -> [mon index, hits, last turn]
        self.focus_picks = 0        # times focus chose a different target than lowest-level
        self.focus_calls = 0
        # fight_model2 bookkeeping (kept with the flag off too: it sends no keys)
        self.fm2_hits = {}          # (level key, pos) -> [mon index, hits, last turn], the 'F' step's message skipped
        self.fm2_skill = {}         # skill name -> advances read ("You are now more skilled in ...")
        self.fm2_unseen = deque()   # (turn, HP lost) of each message with an unseen monster's attack
        self.fm2_hp = None          # our HP at the last message

    def wielded(self):
        for it in self.items():
            if it.ocls == nh.WEAPON_CLASS and it.wielded:
                return it.text
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

    def focus_note(self, m):
        """Count our landed hits on the square we attacked."""
        self.fm2_note(m)
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

    def fm2_note(self, m):
        """fight_model2's reading of a message: our hits on the square we attacked (a kill forgets them), our weapon
        skill's advances, an unseen attacker's attacks and the HP they cost us. The message logged at the step of
        our attack's 'F' is the one shown before, logged again (NLE keeps it on the line while asking the
        direction): skipped -- counted as a hit it was one more, and a kill in it forgot the new target's hits."""
        if self.steps == self.attack_step + 1:
            return
        hp = self.bl(nh.NLE_BL_HP)
        sk = SKILL_RE.search(m)
        if sk:
            self.fm2_skill[sk.group(1)] = self.fm2_skill.get(sk.group(1), 0) + 1
        if UNSEEN_ATTACK_RE.search(m) and not SEEN_ATTACK_RE.search(m):
            self.fm2_unseen.append((self.turn(), max(0, self.fm2_hp - hp) if self.fm2_hp is not None else 0))
        while self.fm2_unseen and self.turn() - self.fm2_unseen[0][0] >= UNSEEN_WINDOW:
            self.fm2_unseen.popleft()
        self.fm2_hp = hp
        pos = self.last_attack_target
        if pos is None or self.cur_key is None:
            return
        key = (self.cur_key, pos)
        if KILL_WORD_RE.search(m):
            self.fm2_hits.pop(key, None)
        elif OUR_HIT_RE.search(m):
            g = int(self.obs["glyphs"][pos])
            if nh.glyph_is_monster(g):
                idx = nh.glyph_to_mon(g)
                rec = self.fm2_hits.get(key)
                if rec is None or rec[0] != idx or self.turn() - rec[2] > HIT_MEMORY:
                    rec = [idx, 0, self.turn()]
                rec[1] += 1
                rec[2] = self.turn()
                self.fm2_hits[key] = rec

    def fm2_weapon_skill(self):
        """(to-hit, damage) of our skill with the weapon in hand: Basic for the weapons we start with (START_WEAPONS;
        another role: Basic for any), Unskilled for the others, one level up per advance message (weapon.c:1130-1140
        skill_advance); bare-handed or a non-weapon: 0."""
        w = self.our_weapon()[0]
        skill = WEAPON_SKILL.get(w)
        if skill is None:
            return 0, 0
        start = START_WEAPONS.get(self.role)
        level = BASIC if start is None or skill in start else BASIC - 1
        return skill_bonus(level + self.fm2_skill.get(skill, 0))

    def fm2_parts(self, pos, name):
        """fight_model2's focus_score parts for the hostile at pos: P(our blow hits) and its damage pmf (danger
        our_hit_prob / our_damage_pmf with our weapon skill), our hits on it (fm2_hits), its HP left (the newmonhp prior
        of its adj_level -- golems their fixed HP -- after those hits: fightmodel.remaining_hp), the game turns we need
        to kill it (fightmodel.hits_to_kill / P(hit), at our_speed), the damage it deals per turn (monster_round
        model2: negative AC, its weapon or none, spells; an instant death as all our HP). An unseen one ('I'): the HP
        unseen attackers took per turn lately (fm2_unseen) over a typical monster of the level's kill time
        (fightmodel.unseen_level / typical_monster). None for a name we know nothing of."""
        unseen = name == "invisible"
        if unseen:
            lev = unseen_level(self.bl(nh.NLE_BL_DEPTH), self.bl(nh.NLE_BL_XP))
            ref = typical_monster(lev)
        elif name in PM_BY_NAME:
            ref = name
            lev = adj_level(PM_BY_NAME[name].mlevel, self.bl(nh.NLE_BL_DEPTH), self.bl(nh.NLE_BL_XP))
        else:
            return None
        hit_sk, dmg_sk = self.fm2_weapon_skill()
        p = self.our_hit_prob(ref, hit_sk)
        dmg = self.our_damage_pmf(ref, dmg_sk)
        hits = 0
        g = int(self.obs["glyphs"][pos])
        rec = self.fm2_hits.get((self.cur_key, pos))
        if rec and nh.glyph_is_monster(g) and rec[0] == nh.glyph_to_mon(g) and self.turn() - rec[2] <= HIT_MEMORY:
            hits = rec[1]           # (a monster that stepped followed by its kind: others of a pack credited, worse)
        left = remaining_hp(hp_prior(None if unseen else name, lev), dmg, hits)
        if left is None:
            left = np.array([0.0, 1.0])                  # tougher than the prior allows: 1 HP left
        ttk = hits_to_kill(left, dmg) / max(p, 0.05) * 12 / self.our_speed()
        if unseen:
            dpt = sum(d for _, d in self.fm2_unseen) / UNSEEN_WINDOW if self.fm2_unseen else 0.0
            inst = 0.0
        else:
            rnd, inst = self.monster_round(name, model2=True, hurt=hits > 0)
            dpt = float((np.arange(len(rnd)) * rnd).sum()) + inst * self.bl(nh.NLE_BL_HP)
        return {"p": p, "dmg": float((np.arange(len(dmg)) * dmg).sum()), "hits": hits,
                "rem": float((np.arange(len(left)) * left).sum()), "ttk": ttk, "dpt": dpt, "inst": inst, "lev": lev,
                "score": dpt / max(ttk, 0.05)}

    def focus_score(self, pos, name=None):
        # (A/B fight_model -- scored with danger's fight model instead: -1411 [-2662, -184], 7148)
        if self.opts.fight_model2:
            parts = self.fm2_parts(pos, name)
            return parts["score"] if parts else 0.0
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

    def focus_target(self, hostiles):
        """The (pos, name) hostile to hit among several: the highest focus_score."""
        self.focus_calls += 1
        if self.opts.fight_model2:       # a tie (both harmless so far): a seen monster before an unseen one
            best = max(hostiles, key=lambda t: (self.focus_score(t[0], t[1]), t[1] != "invisible"))[0]
        else:
            best = max(hostiles, key=lambda t: self.focus_score(t[0]))[0]
        if best != min(hostiles, key=lambda t: self.mon_level(t[0]))[0]:
            self.focus_picks += 1
        return best
