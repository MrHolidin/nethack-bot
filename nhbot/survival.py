"""Staying alive: prayer, eating (inventory food, fresh corpses of our kills), shedding weight,
healing potions, skill enhancement, the vault guard protocol."""
import re

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.carry import HEAL_POTIONS
from nhbot.consts import DELTA2KEY, WEAK
from nhbot.goals import GOALS
from nhbot.monsters import M1_ACID, M1_POIS, M2_SHAPESHIFTER, M2_UNDEAD, M2_WERE, NEVER_EAT, PM_BY_NAME, RACE_FLAG, WERE_KIN


class SurvivalMixin:
    def survival_init(self):
        self.want_enhance = False
        self.enhances = 0
        self.quaffs = 0

    def pray(self):
        self.cur_act = "pray"
        self.last_pray = self.turn()
        self.prayers += 1
        self.press("#", expect_prompt=True)
        for c in "pray":
            self.raw_step(ord(c))
        self.press(13)

    def can_pray(self, hunger_emergency=None, weak=False):
        # Weak/Fainting is major trouble (timeout <= 200 suffices); 500 turns after a prayer is ~88% safe.
        # A/B (1000 games): +273 [-1, +553], deaths while fainted 108 -> 76
        if self.god_angry:
            return False
        t = self.turn()
        if self.last_pray is None:
            return t > 300 or (hunger_emergency and t > 100)
        gap = t - self.last_pray
        if hunger_emergency:          # fainting for 200+ turns: death is close, take the risk
            return gap > 300
        if weak:
            return gap > self.opts.hunger_gap
        return gap > self.opts.pray_gap

    def edible_now(self, s):
        return not re.search(r"\btins?\b", s) and "corpse" not in s and "egg" not in s

    def eat_from_inventory(self):
        for letter, ocls, s in self.inventory():
            if ocls != nh.FOOD_CLASS or not self.edible_now(s):
                continue
            self.press("e", expect_prompt=True)
            for _ in range(3):
                m = self.message().lower()
                if self.obs["misc"][0] and "eat" in m and "here" in m:
                    self.press("n", expect_prompt=True)
                    continue
                break
            if "what do you want to eat" in self.message().lower():
                self.press(letter)
            else:
                self.settle()
            return True
        return False

    def corpse_ok(self, name):
        """Fresh corpse of our own kill: decide from the species' flags."""
        if self.lycanthropy:
            kind = self.lyc_kind
            kin = WERE_KIN.get(kind) if kind else set().union(*WERE_KIN.values())
            if name in kin:
                return False                  # eat.c: our own were-kind is cannibalism (Luck, aggravate)
        pm = PM_BY_NAME.get(name)
        if pm is None or name in NEVER_EAT:
            return False
        if name in ("bat", "giant bat", "vampire bat"):
            return False                      # eat.c: bat corpses stun for 30 (giant bat 60) turns
        f1, f2 = pm.mflags1, pm.mflags2
        if f2 & (M2_UNDEAD | M2_WERE | M2_SHAPESHIFTER):
            return False
        if f2 & RACE_FLAG.get((self.race or "").lower(), 0):
            return False                      # cannibalism
        hp, hunger = self.bl(nh.NLE_BL_HP), self.bl(nh.NLE_BL_HUNGER)
        if f1 & M1_POIS and not f1 & M1_ACID and self.poison_res:
            return True                       # poison resistant: a poisonous corpse is ordinary food
        if f1 & (M1_POIS | M1_ACID):          # up to 15 damage: only when starving and healthy
            return hunger >= WEAK and hp > 20
        return True

    def eat_corpse_here(self):
        self.press("e", expect_prompt=True)
        m = self.message().lower()
        if self.obs["misc"][0] and "corpse here" in m:
            name = re.search(r"there (?:is|are) (?:an? |\d+ )?(.+?) corpses? here", m)
            if name and self.corpse_ok(name.group(1)):
                self.press("y")
                self.corpses_eaten += 1
                return True
            self.press("n", expect_prompt=True)
        if "what do you want to eat" in self.message().lower():
            self.press(27)
        else:
            self.settle()
        return False

    def corpse_goals(self, lv):
        """Fresh corpses of our kills here that we would eat, within max_dist, nearest (straight line) first."""
        t = self.turn()
        kind = GOALS["corpse"]
        n = len(self.kills)
        self.kills = [k for k in self.kills if t - k[0] < kind.ttl]
        self.goal_event("corpse", "expired", n - len(self.kills))
        cands = []
        for kt, name, pos, key in self.kills:
            if key != lv.key or not self.corpse_ok(name):
                continue
            if G.KIND[lv.under[pos]] != G.CORPSE:
                continue
            if self.opts.shop_by_square and self.merch_risk(lv, pos):
                continue
            d = max(abs(pos[0] - self.pos()[0]), abs(pos[1] - self.pos()[1]))
            if d <= kind.max_dist and pos not in [p for _, p in cands]:
                cands.append((d, pos))
        cands.sort(key=lambda c: c[0])           # stable: the first of equally near ones, as before
        return [p for _, p in cands]

    def drop_heavy(self):
        """Strained or worse (e.g. polymorphed into something small): shed non-essentials."""
        order = (nh.GEM_CLASS, nh.ROCK_CLASS, nh.TOOL_CLASS, nh.WEAPON_CLASS, nh.ARMOR_CLASS,
                 nh.SPBOOK_CLASS, nh.POTION_CLASS, nh.WAND_CLASS, nh.SCROLL_CLASS)
        inv = self.inventory()
        for cls in order:
            for letter, ocls, s in inv:
                if ocls == cls and "being worn" not in s and "weapon in hand" not in s \
                        and (letter, s) not in self.undroppable:
                    self.undroppable.add((letter, s))   # try each item once
                    self.drop_letter(letter)
                    return True
        return False

    def heal_step(self, hostiles):
        hp, maxhp = self.bl(nh.NLE_BL_HP), self.bl(nh.NLE_BL_HPMAX)
        if hp * 3 >= maxhp or self.can_pray():
            return False
        it = self.find_item(nh.POTION_CLASS, HEAL_POTIONS)
        if it:
            self.cur_act = "heal"
            if self.ask("q", "drink"):
                self.press(it[0])
                self.quaffs += 1
                return True
        return False

    def enhance_step(self):
        if not self.want_enhance:
            return False
        self.want_enhance = False
        for _ in range(6):
            self.raw_step(229)                       # M-e: #enhance
            tty = self.tty_text()
            if "Pick a skill to advance" not in tty:
                self.raw_step(27); self.settle()
                break
            m = re.search(r"(?<![\w-])([a-zA-Z]) - +[a-z][a-z \-]+?\s+\[", tty)
            if not m:
                self.raw_step(27); self.settle()
                break
            self.raw_step(ord(m.group(1)))
            self.settle()
            self.enhances += 1
        return False                                 # takes no game time

    def vault_step(self, lv, hostiles):
        """Vault guard protocol: drop the gold, then follow the guard out along his corridor."""
        if self.vault_drop:
            self.vault_drop = False
            self.vault_drops += 1
            if self.ask("d", "drop"):
                self.press("$")
            return True
        if self.turn() > self.vault_follow_until:
            return False
        if any(n != "guard" for _, n in hostiles):
            return False                      # something else is attacking: fight first
        g = self.obs["glyphs"]
        ys, xs = np.nonzero(G.KIND[g] == G.MONSTER)
        guards = [(int(a), int(b)) for a, b in zip(ys, xs) if G.monster_name(int(g[a, b])) == "guard"]
        y, x = self.pos()
        if not guards:
            if self.guard_trail and self.turn() - self.guard_trail[-1][1] > 20:
                self.vault_follow_until = -1
                return False
        else:
            gp = min(guards, key=lambda p: max(abs(p[0] - y), abs(p[1] - x)))
            if not self.guard_trail or self.guard_trail[-1][0] != gp:
                self.guard_trail.append((gp, self.turn()))
        # step onto the newest square the guard has left that is next to us
        gnow = self.guard_trail[-1][0] if self.guard_trail else None
        for p, _ in reversed(self.guard_trail[:-1]):
            d = (p[0] - y, p[1] - x)
            if p != gnow and d in DELTA2KEY:
                self.vault_moves += 1
                self.cur_act = "vault"
                self.press(DELTA2KEY[d])
                return True
        self.cur_act = "vault"
        self.press("s")
        return True

    def msg_survival(self, m):
        """Poison resistance, skills, prayer outcome, the vault guard, lycanthropy, eating."""
        # eat.c givit(POISON_RES): "You feel healthy."; eating poison while resistant: "You seem unaffected"
        if "You feel healthy" in m or "You seem unaffected by the poison" in m:
            self.poison_res = True
        if "more confident in your" in m:
            self.skill_msgs += 1
            self.want_enhance = True
        if "You feel that" in m and "displeased" in m:
            self.pray_failed += 1
        if self.last_pray is not None and self.turn() - self.last_pray <= 5 and any(
                p in m for p in ("Thou hast angered me", "Thou must relearn", "You feel guilty",
                                 "Then die, mortal", "Thou durst", "You feel that Mitra is angry")):
            self.god_angry = True
        if "drop that gold" in m or "drop that money" in m:
            self.vault_drop = True
        if "follow me" in m:
            self.vault_follow_until = self.turn() + 300
            self.guard_trail = []
        if "You feel feverish" in m:
            self.lycanthropy = True
            mk = re.search(r"\b(were(?:jackal|rat|wolf))\b", m)
            self.lyc_kind = mk.group(1) if mk else None      # None: infected by something we didn't see
        if "You feel purified" in m:
            self.lycanthropy = False
        if "carrying so much" in m:
            self.no_eat_until = self.turn() + 20
