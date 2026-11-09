"""Staying alive: prayer, eating (inventory food, fresh corpses of our kills), shedding weight,
healing potions, skill enhancement, the vault guard protocol."""
import re
from collections import Counter

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.carry import HEAL_POTIONS
from nhbot.consts import DELTA2KEY, FAINTING, HUNGRY, NOT_HUNGRY, SATIATED, WEAK
from nhbot.goals import GOALS
from nhbot.items import base_name, singular_name
from nhbot.monattacks import ATTACKS
from nhbot.monsters import M1_ACID, M1_POIS, M2_SHAPESHIFTER, M2_UNDEAD, M2_WERE, NEVER_EAT, PM_BY_NAME, RACE_FLAG, WERE_KIN


# apply.c use_unicorn_horn: what an uncursed / blessed horn can fix (deafness left alone: harmless to us), and a
# cursed one's harm -- one of these conditions, or an attribute lost (attrib.c adjattrib: "You feel weak!", ...)
HORN_SICK = nh.BL_MASK_FOODPOIS | nh.BL_MASK_TERMILL
HORN_FIXES = HORN_SICK | nh.BL_MASK_BLIND | nh.BL_MASK_CONF | nh.BL_MASK_STUN | nh.BL_MASK_HALLU
HORN_HARM = HORN_FIXES | nh.BL_MASK_DEAF
ATTR_LOSS_RE = re.compile(r"You feel (?:weak|stupid|foolish|clumsy|fragile|repulsive)!")
# An attribute lost (A/B horn_attrs: +309 [-676, +1261] on 79k, its 217 changed games median +1192; accepted), as
# the game says it -- attrib.c adjattrib ("You feel weak!", "very" for 2+ points:
# exercise, a mind flayer, ...) and poisontell after poisoned() took points ("You feel weaker!", attrib.c:238-245) --
# and its status line field. The horn mends ABASE up to AMAX, 3 points of each at most per apply, a random number of
# troubles in all (apply.c use_unicorn_horn); the hunger "You feel weak." ends in a period (eat.c:3062-3064)
ATTR_LOSS = ((re.compile(r"You feel (?:very )?weak!|You feel weaker!"), nh.NLE_BL_STR125),
             (re.compile(r"You feel (?:very )?stupid!|Your brain is on fire!"), nh.NLE_BL_INT),
             (re.compile(r"You feel (?:very )?foolish!|Your judgement is impaired!"), nh.NLE_BL_WIS),
             (re.compile(r"You feel (?:very )?clumsy!|Your muscles won't obey you!"), nh.NLE_BL_DEX),
             (re.compile(r"You feel (?:very )?fragile!|You feel very sick!"), nh.NLE_BL_CON),
             (re.compile(r"You feel (?:very )?repulsive!|You break out in hives!"), nh.NLE_BL_CHA))
HORN_ATTR_TRIES = 6        # applies in a row that raised a lowered attribute not at all: given up (its maximum fell too,
                           # attrib.c adjattrib below ATTRMIN; sustain ability: apply.c Fixed_abil)
WEAK_HUNGER = 3            # NLE_BL_HUNGER Weak and worse: Strength lowered for now (ATEMP, eat.c), no horn trouble

# eat.c newuhs: the status line by u.uhunger
NUTRITION_BOUNDS = {SATIATED: (1001, 10 ** 6), NOT_HUNGRY: (150, 1000), HUNGRY: (50, 149), WEAK: (1, 49),
                    FAINTING: (-10 ** 6, 0)}
# objects.c oc_nutrition of the food we carry and eat (objects.c:769 FOOD("slime mold", ..., 250, ...))
FOOD_NUTRITION = {"food ration": 800, "cram ration": 600, "lembas wafer": 800, "K-ration": 400, "C-ration": 300,
                  "fortune cookie": 40, "apple": 50, "orange": 80, "pear": 50, "melon": 100, "banana": 80,
                  "carrot": 50, "slime mold": 250, "pancake": 200, "cream pie": 100, "candy bar": 100,
                  "lump of royal jelly": 200, "kelp frond": 30, "eucalyptus leaf": 30, "sprig of wolfsbane": 40,
                  "clove of garlic": 40, "meatball": 5, "meat stick": 5, "huge chunk of meat": 2000,
                  "meat ring": 5, "lichen corpse": 200, "lizard corpse": 40, "tripe ration": 200, "egg": 80}
# the slime mold's 250, a prayer's 900 (nutrition_set), the corpses below and the quantum mechanic's speed:
# (A/B food_facts: -362 [-1546, +841], median 7726 -> 7555, 279 of 1000 changed)
# corpses (and tins) whose eating does what we won't have (eat.c cpostfx, also for a tin's meat):
# a mimic -- helpless 20 / 40 / 50 turns mimicking gold (eat.c:1016-1033); hallucination 200 turns -- the violet
# fungus and every kind with a stunning / hallucinating attack (eat.c:1107-1112: the yellow mold)
MIMIC_CORPSES = {"small mimic": 20, "large mimic": 40, "giant mimic": 50}
HALLU_CORPSES = {"violet fungus"} | {nh.permonst(i).mname for i in range(nh.NUMMONS)
                                    if any(a[1] in ("STUN", "HALU") for a in ATTACKS[i])}
# attrib.c *_abil: the roles intrinsically Fast, from this experience level (a quantum mechanic's corpse toggles it:
# eat.c:1052-1060 -- eaten Fast we lose it)
INTRINSIC_FAST_XL = {"Archeologist": 1, "Monk": 1, "Samurai": 1, "Barbarian": 7, "Caveman": 7, "Cavewoman": 7,
                     "Knight": 7, "Valkyrie": 7}
STOMACH_CONTENT_RE = re.compile(r"\bYour [a-z ]+ feels content\.")     # pray.c:368-370 fix_worst_trouble


class SurvivalState:
    """State of eating, praying, the vault guard protocol, hunger and unicorn horns (SurvivalMixin)."""
    def __init__(self):
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
        self.enhances = 0
        self.quaffs = 0
        self.nutrition = 900           # estimated u.uhunger (start 900): see nutrition_tick
        self.horn_bad = set()          # letters of unicorn horns that harmed us (cursed): not applied, sold
        self.horn_nothing = 0          # the conditions a horn said "Nothing happens." to
        self.horn_stats = Counter()
        self.attr_seen = {}            # status line field -> its value at the start of this tick
        self.attr_want = {}            # ... -> the value before the game said we lost points of it (attr_lowered)
        self.attr_tries = Counter()    # ... -> applies in a row that did not raise it
        self.hunger_at = (0, NOT_HUNGRY)     # (turn, status line hunger) at the last tick (nutrition_tick)
        self.qm_fast = None            # Fast as a quantum mechanic's corpse left us (None: never ate one)


class SurvivalMixin:
    def survival_init(self):
        self.surv = SurvivalState()

    def pray(self):
        self.cur_act = "pray"
        self.surv.last_pray = self.turn()
        self.surv.prayers += 1
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
        if self.surv.god_angry:
            return False
        t = self.turn()
        if self.surv.last_pray is None:
            return t > 100            # u.ublesscnt = 300 - (moves - 1) <= 200: a prayer in major trouble is safe (the
                                      # steps that pray are; step_history, heal_step, Sokoban only ask)
        gap = t - self.surv.last_pray
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
        t0, h0 = self.surv.hunger_at
        t, h = self.turn(), self.bl(nh.NLE_BL_HUNGER)
        self.surv.hunger_turns[h0] += t - t0
        n = self.surv.nutrition - max(0, t - t0)
        if h > h0:                                   # a step down: right at the edge
            n = {NOT_HUNGRY: 1000, HUNGRY: 149, WEAK: 49, FAINTING: 0}.get(h, n)
        lo, hi = NUTRITION_BOUNDS.get(h, (-10 ** 6, 10 ** 6))
        self.surv.nutrition = min(max(n, lo), hi)
        self.surv.hunger_at = (t, h)

    def nutrition_add(self, n):
        self.surv.nutrition += n

    def nutrition_set(self, n):
        """u.uhunger is n now (a prayer's init_uhunger) -- nutrition_tick takes off the turns since the
        last tick, so they are added here."""
        self.surv.nutrition = n + max(0, self.turn() - self.surv.hunger_at[0])

    def intrinsic_fast(self):
        """Intrinsically Fast -- by role and experience level (INTRINSIC_FAST_XL), or as the last quantum
        mechanic we ate left us."""
        if self.surv.qm_fast is not None:
            return self.surv.qm_fast
        xl = INTRINSIC_FAST_XL.get(self.role or "")
        return xl is not None and self.bl(nh.NLE_BL_XP) >= xl

    def eat_prompt(self):
        """'e', declining the food lying here ("There is a jackal corpse here; eat it?", eat.c floorfood): True if
        the inventory prompt "What do you want to eat?" is open."""
        self.press("e", expect_prompt=True)
        for _ in range(3):
            m = self.message().lower()
            if self.obs["misc"][0] and "eat" in m and "here" in m:
                self.press("n", expect_prompt=True)
                continue
            break
        return "what do you want to eat" in self.message().lower()

    def eat_from_inventory(self):
        for letter, ocls, s in self.inventory():
            if ocls != nh.FOOD_CLASS or not self.edible_now(s):
                continue
            if self.eat_prompt():
                self.press(letter)
                # one piece of a stack: "2 food rations" -> food ration, 800 (was 200)
                # (name_parse, accepted without A/B by the user -- see carry.describe)
                self.nutrition_add(FOOD_NUTRITION.get(singular_name(base_name(s)[2]), 200))
            else:
                self.settle()
            return True
        return False

    def corpse_ok(self, name, tin=False):
        """Fresh corpse of our own kill: decide from the species' flags. tin: the meat of a tin -- eat.c
        consume_tin skips eatcorpse(), so no poison or acid damage (the intrinsics still come)."""
        if self.surv.lycanthropy:
            kind = self.surv.lyc_kind
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
        if name in MIMIC_CORPSES or name in HALLU_CORPSES or (name == "quantum mechanic" and self.intrinsic_fast()):
            return False                      # helpless mimicking, hallucinating, our speed lost (tins too)
        hp, hunger = self.bl(nh.NLE_BL_HP), self.bl(nh.NLE_BL_HUNGER)
        if tin:
            return True
        if f1 & M1_POIS and not f1 & M1_ACID and self.surv.poison_res:
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
                self.surv.corpses_eaten += 1
                pm = PM_BY_NAME.get(kind)
                self.nutrition_add(pm.cnutrit if pm is not None else 100)
                self.surv.eaten_by[kind] += 1
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
        kind = GOALS["corpse"]
        self.goal_event("corpse", "expired", self.kills_expire(kind.ttl))
        cands = []
        for kt, name, pos, key in self.combat.kills:
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
        return it.letter in self.surv.horn_bad or it.cursed

    def have_horn(self):
        """A unicorn horn we would apply is on us."""
        return any(it.ocls == nh.TOOL_CLASS and "unicorn horn" in it.text
                                         and not self.horn_is_bad(it) for it in self.items())

    def attr_track(self):
        """Every tick: the attribute fields as the tick starts (a loss said during it is measured against
        them: msg_survival); a lowered one back at its old value no longer wanted."""
        for _, f in ATTR_LOSS:
            v = self.surv.attr_seen[f] = int(self.bl(f))
            if f in self.surv.attr_want and v >= self.surv.attr_want[f]:
                del self.surv.attr_want[f]
                self.surv.attr_tries.pop(f, None)

    def attr_lowered(self):
        """The attribute fields below the value they had before a loss the game told us of (Strength not
        while Weak from hunger)."""
        return [f for f, v in self.surv.attr_want.items() if self.bl(f) < v
                and not (f == nh.NLE_BL_STR125 and self.bl(nh.NLE_BL_HUNGER) >= WEAK_HUNGER)]

    def unihorn_step(self, troubles, attrs=False):
        """Apply a unicorn horn while one of `troubles` (HORN_FIXES bits) is on us, or (attrs) an attribute is
        lowered (attr_lowered); the caller decides when (sickness: always, ahead of a prayer; the rest:
        nothing next to us). A horn that brings a new condition or takes an attribute is cursed: never applied again,
        and no longer kept (sold). True if acted."""
        if self.thief.polyd or self.handless():
            return False
        before = int(self.last_bl[nh.NLE_BL_CONDITION])
        if not before & HORN_FIXES:
            self.surv.horn_nothing = 0
        cond = bool(before & troubles) and before & HORN_FIXES != self.surv.horn_nothing
        low = {f: int(self.bl(f)) for f in self.attr_lowered()} if attrs else {}
        if not cond and not low:
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
        self.surv.horn_stats["applied"] += 1
        if "Nothing happens" in self.text_since(seq0):
            self.surv.horn_nothing = before & HORN_FIXES     # apply.c: no trouble it can fix; until the conditions change
            self.surv.horn_stats["nothing"] += 1
        if before & ~after & HORN_FIXES:
            self.surv.horn_stats["fixed"] += 1
        msgs = self.text_since(seq0)
        if after & ~before & HORN_HARM or ATTR_LOSS_RE.search(msgs):
            self.surv.horn_bad.add(horn.letter)
            self.surv.horn_stats["bad"] += 1
        for f, v in low.items():
            if self.bl(f) > v:
                self.surv.attr_tries[f] = 0
                self.surv.horn_stats["attr_mended"] += 1
                continue
            self.surv.attr_tries[f] += 1
            if self.surv.attr_tries[f] >= HORN_ATTR_TRIES:
                self.surv.attr_want.pop(f, None)
                self.surv.horn_stats["attr_given_up"] += 1
        return True

    def heal_step(self, hostiles):
        if not self.hp_below(self.opts.heal_hp) or self.can_pray():
            return False
        it = self.find_item(nh.POTION_CLASS, HEAL_POTIONS)
        if it:
            self.cur_act = "heal"
            if self.ask_drink():
                self.press(it[0])
                self.surv.quaffs += 1
                return True
        return False

    def enhance_step(self):
        if not self.surv.want_enhance:
            return False
        self.surv.want_enhance = False
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
            self.surv.enhances += 1
        return False                                 # takes no game time

    def vault_step(self, lv, hostiles):
        """Vault guard protocol: drop the gold, then follow the guard out along his corridor."""
        if self.surv.vault_drop:
            bag = self.gold_bag()
            if bag is not None and self.bag.gold > 0:
                self.surv.vault_bag_outs += 1          # he wants the gold in our bag too (vault.c hidden_gold): out first
                #                                   (A/B vault_bag_out +316 [+84, +574]: 9 of 10 guard deaths gone)
                return self.bag_take_out(bag)
            self.surv.vault_drop = False
            self.surv.vault_drops += 1
            if self.ask("d", "drop"):
                self.press("$")
            return True
        if self.turn() > self.surv.vault_follow_until:
            return False
        if any(n != "guard" for _, n in hostiles):
            return False                      # something else is attacking: fight first
        g = self.obs["glyphs"]
        ys, xs = np.nonzero(G.KIND[g] == G.MONSTER)
        guards = [(int(a), int(b)) for a, b in zip(ys, xs) if G.monster_name(int(g[a, b])) == "guard"]
        y, x = self.pos()
        if not guards:
            if self.surv.guard_trail and self.turn() - self.surv.guard_trail[-1][1] > 20:
                self.surv.vault_follow_until = -1
                return False
            last = self.surv.guard_trail[-1][0] if self.surv.guard_trail else None
            d = (last[0] - y, last[1] - x) if last else None
            if d in DELTA2KEY and last != self.surv.guard_stepped:
                self.surv.guard_stepped = last     # he went on into his dark corridor -- onto the square he left
                self.surv.vault_moves += 1
                self.cur_act = "vault"
                self.press(DELTA2KEY[d])
                return True
        else:
            gp = min(guards, key=lambda p: max(abs(p[0] - y), abs(p[1] - x)))
            if not self.surv.guard_trail or self.surv.guard_trail[-1][0] != gp:
                self.surv.guard_trail.append((gp, self.turn()))
        # step onto the newest square the guard has left that is next to us
        gnow = self.surv.guard_trail[-1][0] if self.surv.guard_trail else None
        gd = (lambda p: max(abs(p[0] - gnow[0]), abs(p[1] - gnow[1]))) if gnow else None
        for p, _ in reversed(self.surv.guard_trail[:-1]):
            d = (p[0] - y, p[1] - x)
            if p != gnow and d in DELTA2KEY and gd(p) < gd((y, x)):
                # forward only, never back
                self.surv.vault_moves += 1
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
                self.surv.vault_moves += 1
                self.surv.vault_approach += 1
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
            self.surv.poison_res = True
        # eat.c givit: FIRE_RES "You feel a momentary chill." (hallucinating "You be chillin'."), COLD_RES
        # "You feel full of hot air."
        if "You feel a momentary chill" in m or "You be chillin'" in m:
            self.surv.eaten_res.add("fire")
        if "You feel full of hot air" in m:
            self.surv.eaten_res.add("cold")
        for rx, f in ATTR_LOSS:
            if f in self.surv.attr_seen and rx.search(m):
                self.surv.attr_want[f] = max(self.surv.attr_want.get(f, 0), self.surv.attr_seen[f])
                self.surv.horn_stats["attr_lost"] += 1
        if "more confident in your" in m:
            self.surv.skill_msgs += 1
            self.surv.want_enhance = True
        recent = self.surv.last_pray is not None and self.turn() - self.surv.last_pray <= 5
        if "You feel that" in m and ("displeased" in m or "bummed" in m):
            self.surv.pray_failed += 1
            if recent:
                self.surv.god_angry = True     # pray.c angrygods case 0-1; p_type 0 (too soon) also did u.ugangr++
        if recent and any(p in m for p in ("Thou hast angered me", "Thou must relearn", "You feel guilty",
                                           "Then die, mortal", "Thou durst")):
            self.surv.god_angry = True
        if "drop that gold" in m or "drop that money" in m or "drop that hidden money" in m:
            self.surv.vault_drop = True
        if "follow me" in m:
            self.surv.vault_follow_until = self.turn() + 300
            self.surv.guard_trail = []
            self.surv.guard_stepped = None
        if "the guard disappears" in m:
            self.surv.vault_follow_until = -1              # out of his corridor: the escort is over (vault.c)
        if "You feel feverish" in m:
            self.surv.lycanthropy = True
            mk = re.search(r"\b(were(?:jackal|rat|wolf))\b", m)
            self.surv.lyc_kind = mk.group(1) if mk else None      # None: infected by something we didn't see
        if "You feel purified" in m:
            self.surv.lycanthropy = False
        if "carrying so much" in m:
            self.surv.no_eat_until = self.turn() + 20
        if STOMACH_CONTENT_RE.search(m):
            self.nutrition_set(900)           # pray.c:368-370 -> eat.c:119 init_uhunger: u.uhunger = 900
        elif "surrounded by a golden glow" in m:
            self.nutrition_set(max(900, self.surv.nutrition - max(0, self.turn() - self.surv.hunger_at[0])))
            #                                   pray.c:1110 pat_on_head: init_uhunger if u.uhunger < 900
        if "You seem faster." in m:           # eat.c:1052-1060 a quantum mechanic (the only source of either)
            self.surv.qm_fast = True
        elif "You seem slower." in m:
            self.surv.qm_fast = False
