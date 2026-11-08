"""Melee target choice when several hostiles are adjacent: focus fire.

Rule (deterministic optimum of 'minimise damage taken while killing everyone', Smith's rule):
attack the monster with the largest  (damage it deals us per turn) / (turns we need to kill it).

Scored by focus_parts from danger.py's model where it matched the true game state on real games and fightmodel.py's
fixes where it did not (scratchpad zi/fight_calib.py): spells, negative AC, unarmed weapon users, our weapon skill,
HP left and kill time after the hits we counted, an unseen attacker by the HP it took.
"""
import re
from collections import deque

import numpy as np
import nle.nethack as nh

from nhbot.danger import adj_level
from nhbot.fightmodel import (BASIC, WEAPON_SKILL, hits_to_kill, hp_prior, remaining_hp, skill_bonus,
                              typical_monster, unseen_level)
from nhbot.messages import KILL_WORD_RE, OUR_HIT_RE
from nhbot.monsters import PM_BY_NAME

SKILL_RE = re.compile(r"You are now (?:more|most) skilled in ([a-z -]+)\.")      # weapon.c:1138 skill_advance
UNSEEN_ATTACK_RE = re.compile(r"\bIt (?:hits|bites|stings|butts|touches you|kicks|misses|just misses)\b")
SEEN_ATTACK_RE = re.compile(r"\bThe [a-zA-Z' -]+? (?:hits|bites|stings|butts|touches you|kicks|misses|just misses)\b")
START_WEAPONS = {"Valkyrie": {"long sword", "dagger"}}   # u_init.c Valkyrie[]; weapon.c skill_init: those at Basic
UNSEEN_WINDOW = 20        # turns of unseen attacks an 'I' is scored from
HIT_MEMORY = 30           # turns our hits on a square are remembered


class FocusState:
    """State of focusing on one target (FocusMixin)."""
    def __init__(self):
        self.hits = {}              # (level key, pos) -> [mon index, hits, last turn], the 'F' step's message skipped
        self.skill = {}             # skill name -> advances read ("You are now more skilled in ...")
        self.unseen = deque()       # (turn, HP lost) of each message with an unseen monster's attack
        self.hp = None              # our HP at the last message
        self.picks = 0              # times focus chose a different target than lowest-level
        self.calls = 0


class FocusMixin:
    def focus_init(self):
        self.focus = FocusState()

    def focus_note(self, m):
        """Our reading of a message: our hits on the square we attacked (a kill forgets them), our weapon skill's
        advances, an unseen attacker's attacks and the HP they cost us. The message logged at the step of our
        attack's 'F' is the one shown before, logged again (NLE keeps it on the line while asking the direction):
        skipped -- counted as a hit it was one more, and a kill in it forgot the new target's hits."""
        if self.steps == self.acts.attack_step + 1:
            return
        hp = self.bl(nh.NLE_BL_HP)
        sk = SKILL_RE.search(m)
        if sk:
            self.focus.skill[sk.group(1)] = self.focus.skill.get(sk.group(1), 0) + 1
        if UNSEEN_ATTACK_RE.search(m) and not SEEN_ATTACK_RE.search(m):
            self.focus.unseen.append((self.turn(), max(0, self.focus.hp - hp) if self.focus.hp is not None else 0))
        while self.focus.unseen and self.turn() - self.focus.unseen[0][0] >= UNSEEN_WINDOW:
            self.focus.unseen.popleft()
        self.focus.hp = hp
        pos = self.acts.last_attack_target
        if pos is None or self.cur_key is None:
            return
        key = (self.cur_key, pos)
        if KILL_WORD_RE.search(m):
            self.focus.hits.pop(key, None)
        elif OUR_HIT_RE.search(m):
            g = int(self.obs["glyphs"][pos])
            if nh.glyph_is_monster(g):
                idx = nh.glyph_to_mon(g)
                rec = self.focus.hits.get(key)
                if rec is None or rec[0] != idx or self.turn() - rec[2] > HIT_MEMORY:
                    rec = [idx, 0, self.turn()]
                rec[1] += 1
                rec[2] = self.turn()
                self.focus.hits[key] = rec

    def focus_hits_on(self, pos):
        """Our hits on the monster at pos (focus.hits): the same kind still there, hit within HIT_MEMORY turns (a
        monster that stepped off followed by its kind: others of a pack credited, worse); 0 for no square (a monster
        not there yet)."""
        if pos is None:
            return 0
        g = int(self.obs["glyphs"][pos])
        rec = self.focus.hits.get((self.cur_key, pos))
        if rec and nh.glyph_is_monster(g) and rec[0] == nh.glyph_to_mon(g) and self.turn() - rec[2] <= HIT_MEMORY:
            return rec[1]
        return 0

    def weapon_skill(self):
        """(to-hit, damage) of our skill with the weapon in hand: Basic for the weapons we start with (START_WEAPONS;
        another role: Basic for any), Unskilled for the others, one level up per advance message (weapon.c:1130-1140
        skill_advance); bare-handed or a non-weapon: 0."""
        w = self.our_weapon()[0]
        skill = WEAPON_SKILL.get(w)
        if skill is None:
            return 0, 0
        start = START_WEAPONS.get(self.role)
        level = BASIC if start is None or skill in start else BASIC - 1
        return skill_bonus(level + self.focus.skill.get(skill, 0))

    def focus_parts(self, pos, name):
        """focus_score's parts for the hostile at pos: P(our blow hits) and its damage pmf (danger our_hit_prob /
        our_damage_pmf with our weapon skill), our hits on it (focus.hits), its HP left (the newmonhp prior of its
        adj_level -- golems their fixed HP -- after those hits: fightmodel.remaining_hp), the game turns we need to
        kill it (fightmodel.hits_to_kill / P(hit), at our_speed), the damage it deals per turn (monster_round model2:
        negative AC, its weapon or none, spells; an instant death as all our HP). An unseen one ('I'): the HP unseen
        attackers took per turn lately (focus.unseen) over a typical monster of the level's kill time
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
        hit_sk, dmg_sk = self.weapon_skill()
        p = self.our_hit_prob(ref, hit_sk)
        dmg = self.our_damage_pmf(ref, dmg_sk)
        hits = self.focus_hits_on(pos)
        left = remaining_hp(hp_prior(None if unseen else name, lev), dmg, hits)
        if left is None:
            left = np.array([0.0, 1.0])                  # tougher than the prior allows: 1 HP left
        ttk = hits_to_kill(left, dmg) / max(p, 0.05) * 12 / self.our_speed()
        if unseen:
            dpt = sum(d for _, d in self.focus.unseen) / UNSEEN_WINDOW if self.focus.unseen else 0.0
            inst = 0.0
        else:
            rnd, inst = self.monster_round(name, model2=True, hurt=hits > 0)
            dpt = float((np.arange(len(rnd)) * rnd).sum()) + inst * self.bl(nh.NLE_BL_HP)
        return {"p": p, "dmg": float((np.arange(len(dmg)) * dmg).sum()), "hits": hits,
                "rem": float((np.arange(len(left)) * left).sum()), "ttk": ttk, "dpt": dpt, "inst": inst, "lev": lev,
                "score": dpt / max(ttk, 0.05)}

    def focus_score(self, pos, name):
        # (A/B fight_model -- scored with danger's fight model instead: -1411 [-2662, -184], 7148)
        # (A/B fight_model2: -294 [-1767, +1215], median 8134 -> 8276, 629 of 1000 changed)
        parts = self.focus_parts(pos, name)
        return parts["score"] if parts else 0.0

    def focus_target(self, hostiles):
        """The (pos, name) hostile to hit among several: the highest focus_score; a tie (both harmless so far): a seen
        monster before an unseen one."""
        self.focus.calls += 1
        best = max(hostiles, key=lambda t: (self.focus_score(t[0], t[1]), t[1] != "invisible"))[0]
        if best != min(hostiles, key=lambda t: self.mon_level(t[0]))[0]:
            self.focus.picks += 1
        return best
