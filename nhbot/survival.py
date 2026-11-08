"""Staying alive: prayer, eating (inventory food, fresh corpses of our kills), shedding weight,
healing potions, skill enhancement, the vault guard protocol."""
import re
from collections import Counter

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.carry import HEAL_POTIONS
from nhbot.consts import DELTA2KEY, FAINTING, HUNGRY, NOT_HUNGRY, SATIATED, WEAK
from nhbot.game import PAGE_RE
from nhbot.goals import GOALS
from nhbot.items import base_name
from nhbot.monsters import M1_ACID, M1_POIS, M2_SHAPESHIFTER, M2_UNDEAD, M2_WERE, NEVER_EAT, PM_BY_NAME, RACE_FLAG, WERE_KIN
from nhbot.weapondice import SKILL_LEVEL


# apply.c use_unicorn_horn: what an uncursed / blessed horn can fix (deafness left alone: harmless to us), and a
# cursed one's harm -- one of these conditions, or an attribute lost (attrib.c adjattrib: "You feel weak!", ...)
HORN_SICK = nh.BL_MASK_FOODPOIS | nh.BL_MASK_TERMILL
HORN_FIXES = HORN_SICK | nh.BL_MASK_BLIND | nh.BL_MASK_CONF | nh.BL_MASK_STUN | nh.BL_MASK_HALLU
HORN_HARM = HORN_FIXES | nh.BL_MASK_DEAF
# a line of the #enhance menu: "   long sword         [Basic]", "a -   dagger   [Unskilled]" (weapon.c:1262)
SKILL_LINE_RE = re.compile(r"^ *(?:[a-zA-Z] - )?[ *#]*([a-z][a-z' -]*?[a-z]) +\[(" + "|".join(SKILL_LEVEL) + r")\]",
                           re.M)
ATTR_LOSS_RE = re.compile(r"You feel (?:weak|stupid|foolish|clumsy|fragile|repulsive)!")

# eat.c newuhs: the status line by u.uhunger
NUTRITION_BOUNDS = {SATIATED: (1001, 10 ** 6), NOT_HUNGRY: (150, 1000), HUNGRY: (50, 149), WEAK: (1, 49),
                    FAINTING: (-10 ** 6, 0)}
# objects.c oc_nutrition of the food we carry and eat
FOOD_NUTRITION = {"food ration": 800, "cram ration": 600, "lembas wafer": 800, "K-ration": 400, "C-ration": 300,
                  "fortune cookie": 40, "apple": 50, "orange": 80, "pear": 50, "melon": 100, "banana": 80,
                  "carrot": 50, "slime mold": 80, "pancake": 200, "cream pie": 100, "candy bar": 100,
                  "lump of royal jelly": 200, "kelp frond": 30, "eucalyptus leaf": 30, "sprig of wolfsbane": 40,
                  "clove of garlic": 40, "meatball": 5, "meat stick": 5, "huge chunk of meat": 2000,
                  "meat ring": 5, "lichen corpse": 200, "lizard corpse": 40, "tripe ration": 200, "egg": 80}


class SurvivalMixin:
    def survival_init(self):
        self.eaten_by = Counter()      # corpses eaten, by kind
        self.corpses_eaten = 0
        self.no_eat_until = 0          # no eating from the inventory before this turn ("carrying so much": msg_survival)
        self.last_pray = None
        self.prayers = 0
        self.pray_failed = 0
        self.god_angry = False
        self.lycanthropy = False
        self.lyc_kind = None           # the were that infected us (None: unseen)
        self.poison_res = False
        self.eaten_res = set()         # resistances a corpse gave us (msg_survival): "fire", "cold"
        self.skill_msgs = 0
        # the vault guard protocol (vault_step)
        self.vault_drop = False
        self.vault_follow_until = -1
        self.guard_trail = []
        self.vault_moves = 0
        self.vault_drops = 0
        self.guard_stepped = None      # the guard's last square we stepped onto while he was out of sight
        self.vault_approach = 0        # steps toward a vault guard that waited for us
        self.vault_bag_outs = 0        # vault_bag_out: gold taken out of the bag for the guard
        self.hunger_turns = Counter()  # turns spent per hunger state (status line)
        self.want_enhance = False
        self.skills = None             # ranges: {skill name: level} from the #enhance menu (read_skills)
        self.enhances = 0
        self.quaffs = 0
        self.nutrition = 900           # estimated u.uhunger (start 900): see nutrition_tick
        self.horn_bad = set()          # letters of unicorn horns that harmed us (cursed): not applied, sold
        self.horn_nothing = 0          # the conditions a horn said "Nothing happens." to
        self.horn_stats = Counter()
        self._hunger_at = (0, NOT_HUNGRY)    # (turn, status line hunger) at the last tick (nutrition_tick)

    def pray(self):
        self.cur_act = "pray"
        self.last_pray = self.turn()
        self.prayers += 1
        self.press("#", expect_prompt=True)
        for c in "pray":
            self.raw_step(ord(c))
        self.press(13)

    def critically_low_hp(self, hp, maxhp):
        """pray.c critically_low_hp: major trouble TROUBLE_HIT. The status line shows the HP the game tests (u.mh and
        u.mhmax while polymorphed)."""
        xl = self.bl(nh.NLE_BL_XP)
        rank = 0 if xl <= 2 else (xl + 2) // 4                 # botl.c xlev_to_rank
        div = 5 if rank <= 1 else 6 if rank <= 3 else 7 if rank <= 5 else 8 if rank <= 7 else 9
        return hp <= 5 or hp * div <= min(maxhp, 15 * xl)

    def can_pray(self, hunger_emergency=None, weak=False):
        # Weak/Fainting is major trouble (timeout <= 200 suffices); 500 turns after a prayer is ~88% safe.
        # A/B (1000 games): +273 [-1, +553], deaths while fainted 108 -> 76
        if self.god_angry:
            return False
        t = self.turn()
        if self.last_pray is None:
            return t > 100            # u.ublesscnt = 300 - (moves - 1) <= 200: a prayer in major trouble is safe (the
                                      # steps that pray are; step_history, heal_step, Sokoban only ask)
        gap = t - self.last_pray
        if hunger_emergency:          # fainting for 200+ turns: death is close, take the risk
            return gap > 300
        if weak:
            return gap > self.opts.hunger_gap
        return gap > self.opts.pray_gap

    def edible_now(self, s):
        return not re.search(r"\btins?\b", s) and "corpse" not in s and "egg" not in s

    def nutrition_tick(self):
        """Every tick: the turns since the last one counted to the hunger state they passed in (hunger_turns), and
        u.uhunger estimated: 1 a turn, plus what we ate (nutrition_add); the status line pins it --
        Satiated > 1000, Not Hungry 150..1000, Hungry 50..149, Weak 1..49, Fainting <= 0 (eat.c newuhs), and
        a step down sets it to the edge just crossed."""
        t0, h0 = self._hunger_at
        t, h = self.turn(), self.bl(nh.NLE_BL_HUNGER)
        self.hunger_turns[h0] += t - t0
        n = self.nutrition - max(0, t - t0)
        if h > h0:                                   # a step down: right at the edge
            n = {NOT_HUNGRY: 1000, HUNGRY: 149, WEAK: 49, FAINTING: 0}.get(h, n)
        lo, hi = NUTRITION_BOUNDS.get(h, (-10 ** 6, 10 ** 6))
        self.nutrition = min(max(n, lo), hi)
        self._hunger_at = (t, h)

    def nutrition_add(self, n):
        self.nutrition += n

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
                self.nutrition_add(FOOD_NUTRITION.get(base_name(s)[2], 200))
            else:
                self.settle()
            return True
        return False

    def corpse_ok(self, name, tin=False):
        """Fresh corpse of our own kill: decide from the species' flags. tin: the meat of a tin -- eat.c
        consume_tin skips eatcorpse(), so no poison or acid damage (the intrinsics still come)."""
        if self.lycanthropy:
            kind = self.lyc_kind
            kin = WERE_KIN.get(kind) if kind else set().union(*WERE_KIN.values())
            if name in kin:
                return False                  # eat.c: our own were-kind is cannibalism (Luck, aggravate)
        pm = PM_BY_NAME.get(name)
        if pm is None or name in NEVER_EAT:
            return False
        horn = self.have_horn()               # a horn cures their stun / food poisoning
        if name in ("bat", "giant bat", "vampire bat") and not horn:
            return False                      # eat.c: bat corpses stun for 30 (giant bat 60) turns
        f1, f2 = pm.mflags1, pm.mflags2
        if f2 & (M2_WERE | M2_SHAPESHIFTER) or (f2 & M2_UNDEAD and not horn):
            return False                      # undead: a zombie's / mummy's corpse is made old -- often tainted
        if f2 & RACE_FLAG.get((self.race or "").lower(), 0):
            return False                      # cannibalism
        hp, hunger = self.bl(nh.NLE_BL_HP), self.bl(nh.NLE_BL_HUNGER)
        if tin:
            return True
        if f1 & M1_POIS and not f1 & M1_ACID and self.poison_res:
            return True                       # poison resistant: a poisonous corpse is ordinary food
        if f1 & (M1_POIS | M1_ACID):          # up to 15 damage: only when starving and healthy
            return hunger >= WEAK and hp > 20
        return True

    def eat_corpse_here(self):
        self.press("e", expect_prompt=True)
        m = self.message().lower()
        # "There is a jackal corpse here; eat it?" / "There are 2 jackal corpses here; eat one?" (eat.c floorfood):
        # the second one is answered no (settle)
        if self.obs["misc"][0] and "corpse here" in m:
            name = re.search(r"there (?:is|are) (?:an? |\d+ )?(.+?) corpses? here", m)
            kind = name.group(1) if name else None
            if kind and kind.startswith("partly eaten "):
                kind = kind[len("partly eaten "):]   # a meal we were interrupted in: resumed
            if kind and self.corpse_ok(kind):
                seq0 = self.msg_seq
                self.press("y")
                self.corpses_eaten += 1
                pm = PM_BY_NAME.get(kind)
                self.nutrition_add(pm.cnutrit if pm is not None else 100)
                self.eaten_by[kind] += 1
                if "You stop eating" in self.text_since(seq0):
                    return "keep"                     # interrupted (monmove.c dochugw): the corpse stays a goal
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
            if G.KIND[lv.under[pos]] != G.CORPSE or self.merch_risk(lv, pos):
                continue                          # on a shop's floor it is merchandise ("You bite that, you pay
                #                                   for it!"): where the corpse lies decides, not where we stand
            d = max(abs(pos[0] - self.pos()[0]), abs(pos[1] - self.pos()[1]))
            if d <= kind.max_dist and pos not in [p for _, p in cands]:
                cands.append((d, pos))
        cands.sort(key=lambda c: c[0])           # stable: the first of equally near ones, as before
        return [p for _, p in cands]

    def horn_is_bad(self, it):
        return it.letter in self.horn_bad or it.cursed

    def have_horn(self):
        """A unicorn horn we would apply is on us."""
        return any(it.ocls == nh.TOOL_CLASS and "unicorn horn" in it.text
                                         and not self.horn_is_bad(it) for it in self.items())

    def unihorn_step(self, troubles):
        """Apply a unicorn horn while one of `troubles` (HORN_FIXES bits) is on us; the caller decides
        when (sickness: always, ahead of a prayer; the rest: nothing next to us). A horn that brings a new
        condition or takes an attribute is cursed: never applied again, and no longer kept (sold). True if acted."""
        if self.polyd or self.handless():
            return False
        before = int(self.last_bl[nh.NLE_BL_CONDITION])
        if not before & HORN_FIXES:
            self.horn_nothing = 0
        if not before & troubles or before & HORN_FIXES == self.horn_nothing:
            return False              # nothing to fix, or nothing the horn can fix (goop on the face: u.ucreamed)
        horn = next((it for it in self.items() if it.ocls == nh.TOOL_CLASS and "unicorn horn" in it.text
                     and not self.horn_is_bad(it)), None)
        if horn is None:
            return False
        self.cur_act = "unihorn"
        seq0 = self.msg_seq
        if not self.ask("a", "apply"):
            return False
        self.press(horn.letter)
        after = int(self.bl(nh.NLE_BL_CONDITION))
        self.horn_stats["applied"] += 1
        if "Nothing happens" in self.text_since(seq0):
            self.horn_nothing = before & HORN_FIXES     # apply.c: no trouble it can fix; until the conditions change
            self.horn_stats["nothing"] += 1
        if before & ~after & HORN_FIXES:
            self.horn_stats["fixed"] += 1
        msgs = self.text_since(seq0)
        if after & ~before & HORN_HARM or ATTR_LOSS_RE.search(msgs):
            self.horn_bad.add(horn.letter)
            self.horn_stats["bad"] += 1
        return True

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
        if self.opts.ranges and self.skills is None:
            self.read_skills()                       # ranges: the skill levels our to-hit / damage read
        if not self.want_enhance:
            return False
        self.want_enhance = False
        if self.opts.ranges:
            self.skills = None                       # read again next time, after the advance
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

    def read_skills(self):
        """ranges: the skill levels from the #enhance menu (no game time): every page of its "Current skills:" (or
        "Pick a skill to advance:") list -- weapon.c:1250-1269 enhance_weapon_skill, " <name> [<level>]" -- into
        self.skills {name: skills.h level}. A restricted skill is not listed (and counts as Restricted)."""
        skills = {}
        self.raw_step(229)                           # M-e: #enhance
        for _ in range(6):
            tty = self.tty_text()
            # a short menu is drawn over the map from its header's column (game.menu_lines); pages after the
            # first have no header and fill the screen
            header = next((h for h in ("Current skills:", "Pick a skill to advance:") if h in tty), None)
            lines = self.menu_lines(tty, header) if header else tty.split("\n")
            for m in SKILL_LINE_RE.finditer("\n".join(lines)):
                skills[m.group(1)] = SKILL_LEVEL[m.group(2)]
            page = PAGE_RE.search(tty)
            if not (page and int(page.group(1)) < int(page.group(2))):
                break
            self.raw_step(ord(">"))
        self.raw_step(27)
        self.settle()
        self.skills = skills

    def skill_level(self, name):
        """ranges: the level of skill name (weapon.c P_NAME) -- None while not read; not listed: Restricted."""
        return None if self.skills is None else self.skills.get(name, 0)

    def vault_step(self, lv, hostiles):
        """Vault guard protocol: drop the gold, then follow the guard out along his corridor."""
        if self.vault_drop:
            bag = self.gold_bag()
            if bag is not None and self.bag_gold > 0:
                self.vault_bag_outs += 1          # he wants the gold in our bag too (vault.c hidden_gold): out first
                #                                   (A/B vault_bag_out +316 [+84, +574]: 9 of 10 guard deaths gone)
                return self.bag_take_out(bag)
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
            last = self.guard_trail[-1][0] if self.guard_trail else None
            d = (last[0] - y, last[1] - x) if last else None
            if d in DELTA2KEY and last != self.guard_stepped:
                self.guard_stepped = last     # he went on into his dark corridor -- onto the square he left
                self.vault_moves += 1
                self.cur_act = "vault"
                self.press(DELTA2KEY[d])
                return True
        else:
            gp = min(guards, key=lambda p: max(abs(p[0] - y), abs(p[1] - x)))
            if not self.guard_trail or self.guard_trail[-1][0] != gp:
                self.guard_trail.append((gp, self.turn()))
        # step onto the newest square the guard has left that is next to us
        gnow = self.guard_trail[-1][0] if self.guard_trail else None
        gd = (lambda p: max(abs(p[0] - gnow[0]), abs(p[1] - gnow[1]))) if gnow else None
        for p, _ in reversed(self.guard_trail[:-1]):
            d = (p[0] - y, p[1] - x)
            if p != gnow and d in DELTA2KEY and gd(p) < gd((y, x)):
                # forward only, never back
                self.vault_moves += 1
                self.cur_act = "vault"
                self.press(DELTA2KEY[d])
                return True
        # he waits in the opening of the vault wall for us to come next to him (vault.c gd_move: he leads only a
        # hero next to him; 7 warnings and he attacks) -- a step closer to him, never onto him (the escort:
        # A/B guard_follow +443 [+246, +647])
        if guards and max(abs(gnow[0] - y), abs(gnow[1] - x)) > 1:
            dist = lambda p: max(abs(p[0] - gnow[0]), abs(p[1] - gnow[1]))
            steps = [(y + dy, x + dx) for dy, dx in DELTA2KEY if (dy, dx) != (0, 0)
                     and 0 <= y + dy < g.shape[0] and 0 <= x + dx < g.shape[1]
                     and G.KIND[g[y + dy, x + dx]] in (G.FLOOR, G.DOORWAY, G.GOLD, G.OBJECT, G.CORPSE)
                     and dist((y + dy, x + dx)) < dist((y, x))]
            if steps:
                q = min(steps, key=dist)
                self.vault_moves += 1
                self.vault_approach += 1
                self.cur_act = "vault"
                self.press(DELTA2KEY[(q[0] - y, q[1] - x)])
                return True
        self.cur_act = "vault"
        self.press("s")
        return True

    def msg_survival(self, m):
        """Poison resistance, skills, prayer outcome, the vault guard, lycanthropy, eating."""
        # eat.c givit(POISON_RES): "You feel healthy."; eating poison while resistant: "You seem unaffected"
        if "You feel healthy" in m or "You seem unaffected by the poison" in m:
            self.poison_res = True
        # eat.c givit: FIRE_RES "You feel a momentary chill." (hallucinating "You be chillin'."), COLD_RES
        # "You feel full of hot air."
        if "You feel a momentary chill" in m or "You be chillin'" in m:
            self.eaten_res.add("fire")
        if "You feel full of hot air" in m:
            self.eaten_res.add("cold")
        if "more confident in your" in m:
            self.skill_msgs += 1
            self.want_enhance = True
        recent = self.last_pray is not None and self.turn() - self.last_pray <= 5
        if "You feel that" in m and ("displeased" in m or "bummed" in m):
            self.pray_failed += 1
            if recent:
                self.god_angry = True     # pray.c angrygods case 0-1; p_type 0 (too soon) also did u.ugangr++
        if recent and any(p in m for p in ("Thou hast angered me", "Thou must relearn", "You feel guilty",
                                           "Then die, mortal", "Thou durst")):
            self.god_angry = True
        if "drop that gold" in m or "drop that money" in m or "drop that hidden money" in m:
            self.vault_drop = True
        if "follow me" in m:
            self.vault_follow_until = self.turn() + 300
            self.guard_trail = []
            self.guard_stepped = None
        if "the guard disappears" in m:
            self.vault_follow_until = -1              # out of his corridor: the escort is over (vault.c)
        if "You feel feverish" in m:
            self.lycanthropy = True
            mk = re.search(r"\b(were(?:jackal|rat|wolf))\b", m)
            self.lyc_kind = mk.group(1) if mk else None      # None: infected by something we didn't see
        if "You feel purified" in m:
            self.lycanthropy = False
        if "carrying so much" in m:
            self.no_eat_until = self.turn() + 20
