"""Valkyrie-branch features, each behind its own flag in role_opts.

nymph:       nymphs (and monkeys) steal and teleport. Shoot them from range, melee them first,
             and after a theft hunt them and loot the square they die on; re-wield the stolen
             main weapon.
"""
import collections
import re

import numpy as np
import nle.nethack as nh

import glyphs as G
import elbereth as ELB

ROWS, COLS = 21, 79
THIEVES = ("water nymph", "wood nymph", "mountain nymph", "monkey")
NYMPHS = ("water nymph", "wood nymph", "mountain nymph")
class ValkMixin:
    def valk_init(self):
        self.thefts = 0
        self.stolen_pending = False
        self.loot_sq = None
        self.loot_key = None
        self.nymph_kills = 0
        self.loot_pickups = 0
        self.main_weapon = None
        self.rewields = 0
        self.nymph_waits = 0
        self.nymph_elbs = 0

    def vopt(self, k, d=None):
        return self.role_opts.get(k, d)

    # ================================================================== nymphs
    def on_valk_message(self, m):
        if re.search(r"\b(stole|steals|stolen)\b", m) or "charms you" in m:
            if any(t in m for t in THIEVES) or "She stole" in m or "He stole" in m:
                if self.turn() != getattr(self, "_theft_turn", None):
                    self._theft_turn = self.turn()
                    self.thefts += 1
                self.stolen_pending = True
        mk = re.search(r"You (?:kill|destroy) (?:the |an? )?(.+?)!", m)
        if mk and any(t in mk.group(1) for t in THIEVES) and self.last_attack_target:
            self.nymph_kills += 1
            if self.stolen_pending:
                self.loot_sq = self.last_attack_target
                self.loot_key = self.cur_key
        if "It stole" in m or "It steals" in m or "She charms you" in m:
            if self.turn() != getattr(self, "_theft_turn", None):
                self._theft_turn = self.turn()
                self.thefts += 1
            self.stolen_pending = True
        if self.vopt("nymph", True) and re.search(r"You turn into an? \w+|shrink out of your|break out of your armor|armor falls around you", m):
            self.were_drop = (self.cur_key, self.pos())      # armor fell here; collect it once human again
        if re.search(r"You turn into an? ", m):
            self.polyd = True                                 # weapons: no wielding in a borrowed body
        if re.search(r"You return to \w+ form|You feel like a new ", m):
            self.polyd = False
        if re.search(r"You return to \w+ form", m) and getattr(self, "were_drop", None):   # dwarves: "dwarven form"
            self.loot_key, self.loot_sq = self.were_drop
            self.were_drop = None

    def nymph_elb_instead(self, lv, hostiles, pos):
        """nymph_pk: a thief is next to us. One action either way: a swing kills it with P(kill in one hit);
        a dust Elbereth stops its theft if spelled right, (24/25)^8 = 0.72 (engrave.c degrades each
        character with 1/25; our own count over 4375 engravings: 0.718). Engrave if that is likelier; on an
        intact Elbereth, wait instead of swinging (attacking from it wipes it). 20-turn cap per stand."""
        y, x = self.pos()
        if any(not self.respects_elbereth(n, p) for p, n in hostiles):
            return False
        on_elb = (y, x) in lv.elbereth and self.read_engraving() == "Elbereth"
        if on_elb:
            if getattr(self, "nymph_pk_waits", 0) >= 20:
                return False
            self.nymph_pk_waits = getattr(self, "nymph_pk_waits", 0) + 1
            self.nymph_pk_wait_total = getattr(self, "nymph_pk_wait_total", 0) + 1
            self.cur_act = "fight"
            self.press("s")
            return True
        self.nymph_pk_waits = 0
        cond = int(self.last_bl[nh.NLE_BL_CONDITION])
        if cond & (nh.BL_MASK_LEV | nh.BL_MASK_BLIND | nh.BL_MASK_STUN | nh.BL_MASK_CONF) or \
                not self.can_engrave_here(lv) or G.KIND[lv.under[y, x]] in (G.UPSTAIR, G.DOWNSTAIR):
            return False
        if self.kill_one_hit_p(pos) >= (24 / 25) ** 8:
            return False
        self.nymph_pk_elbs = getattr(self, "nymph_pk_elbs", 0) + 1
        self.cur_act = "fight"
        self.engrave_elbereth()
        return True

    def thieves_visible(self, lv):
        g = self.obs["glyphs"]
        out = []
        for p, name in self.visible_hostiles(lv):
            if name in THIEVES:
                out.append((p, name))
        return out

    def nymph_step(self, lv, hostiles):
        if not self.vopt("nymph", True):
            return False
        y, x = self.pos()
        # 1) adjacent thief: hit it first (normal melee would pick the lowest level target)
        adj = [(p, n) for p, n in hostiles if n in THIEVES]
        if adj:
            if self.vopt("nymph_pk", False) and self.nymph_elb_instead(lv, hostiles, adj[0][0]):
                return True
            self.attack(adj[0][0])
            return True
        th = self.thieves_visible(lv)
        if not th:
            return False
        # 2) thief in a clear line at range: throw / fire / bolt
        for key, d, pos, (dy, dx), name in self.line_targets(lv, max_d=7):
            if name not in THIEVES or d < 2:
                continue
            if self.peaceful_far(lv, pos, key, d):
                continue
            self.last_attack_target = pos
            self.cur_act = "fight"
            if self.can_cast("force bolt"):
                return self.cast("force bolt", key)
            if self.use_roles and self.ranger_can_fire():
                return self.fire(key)
            tw = self.throwables()
            if tw:
                ray = [(y + i * dy, x + i * dx) for i in range(1, 10)
                       if 0 <= y + i * dy < ROWS and 0 <= x + i * dx < COLS]
                self.throw(tw[0][0], key, ray)
                return True
        have_shot = bool(self.throwables()) or self.can_cast("force bolt") or (self.use_roles and self.ranger_can_fire())
        # 2b) we could shoot but it isn't in line: step to a square that lines us up, at distance >= 2
        if have_shot and self.vopt("nymph_align", True):
            step = self.align_step(lv, th)
            if step is not None:
                self.cur_act = "fight"
                self.move(step)
                return True
        # 2c) no way to shoot: stand on Elbereth (nymphs respect it and won't steal in melee)
        if not have_shot and self.vopt("nymph_elb", True) and (y, x) not in lv.elbereth:
            close = [t for t in th if max(abs(t[0][0] - y), abs(t[0][1] - x)) <= 4]
            if close and G.KIND[lv.under[y, x]] not in (G.UPSTAIR, G.DOWNSTAIR) and self.nymph_elbs < 30:
                self.nymph_elbs += 1
                self.cur_act = "fight"
                self.engrave_elbereth()
                return True
        # 3) no shot: never step next to a thief (that hands it the first move). Hold still and
        #    let it come; nymphs come back to steal more, so waiting is also how we get our items back.
        close = [t for t in th if 2 <= max(abs(t[0][0] - y), abs(t[0][1] - x)) <= self.vopt("nymph_hold", 4)]
        if close and self.nymph_waits < self.vopt("nymph_wait_max", 8):
            self.nymph_waits += 1
            self.cur_act = "fight"
            self.press("s")
            return True
        if not close:
            self.nymph_waits = 0
        return False

    def align_step(self, lv, th):
        """A neighbouring free square from which some thief is in a straight clear line, 2..6 away."""
        y, x = self.pos()
        k_mem, k_live = self.kind_grid(lv)
        p = self.passable_grid(lv, k_mem, k_live)
        g = self.obs["glyphs"]
        best = None
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if not (dy or dx):
                    continue
                ny, nx = y + dy, x + dx
                if not (0 <= ny < ROWS and 0 <= nx < COLS) or not p[ny, nx] or G.KIND[g[ny, nx]] in (G.MONSTER, G.PET):
                    continue
                if dy and dx and (k_mem[y, x] in (G.DOOR_OPEN, G.DOOR_CLOSED) or k_mem[ny, nx] in (G.DOOR_OPEN, G.DOOR_CLOSED)):
                    continue
                for (ty, tx), _ in th:
                    ry, rx = ty - ny, tx - nx
                    d = max(abs(ry), abs(rx))
                    if d < 2 or d > 6 or not (ry == 0 or rx == 0 or abs(ry) == abs(rx)):
                        continue
                    sy, sx = (ry > 0) - (ry < 0), (rx > 0) - (rx < 0)
                    if all(G.PASSABLE[k_mem[ny + i * sy, nx + i * sx]] and G.KIND[g[ny + i * sy, nx + i * sx]] not in (G.MONSTER, G.PET, G.BOULDER)
                           for i in range(1, d)):
                        if best is None or d < best[0]:
                            best = (d, (ny, nx))
        return best[1] if best else None

    def pickup_all(self):
        self.press(",", expect_prompt=True)
        tty = self.tty_text()
        if "Pick up what?" not in tty:
            self.settle()
            return
        n = 0
        lines = self.menu_lines(tty, "Pick up what?") if self.vopt("menu_fix", True) else tty.split("\n")
        for line in lines:
            mm = re.match(r"^\s*([a-zA-Z]) - (.*)$", line.strip())
            if mm and "corpse" not in mm.group(2) and "boulder" not in mm.group(2):
                self.raw_step(ord(mm.group(1)))
                n += 1
        self.raw_step(13 if n else 27)
        self.settle()

    def loot_step(self, lv):
        if self.loot_sq is None or self.loot_key != lv.key:
            return False
        if self.pos() == self.loot_sq:
            self.pickup_all()
            self.loot_pickups += 1
            self.loot_sq = None
            self.stolen_pending = False
            return True
        if self.go_toward(lv, self.loot_sq):
            return True
        self.loot_sq = None
        return False

    def weapon_check(self):
        """Remember the starting weapon; re-wield it if we got it back after a theft."""
        inv = self.inventory()
        wielded = [s for _, _, s in inv if "weapon in hand" in s]
        if self.main_weapon is None:
            if wielded:
                base = re.sub(r"\s*\(.*?\)", "", wielded[0])
                base = re.sub(r"^(a|an|the|\d+)\s+", "", base)
                base = re.sub(r"\b(uncursed|cursed|blessed|rustproof|[+-]\d+)\s+", "", base).strip()
                self.main_weapon = base
            return False
        if self.vopt("weapons", True):
            return self.weapon_upgrade(inv)
        if wielded or not self.vopt("nymph", True):
            return False
        weapons = [(l, s) for l, c, s in inv if c == nh.WEAPON_CLASS and not re.search(r"\b(arrows?|bolts?|ya|darts?)\b", s)]
        pick = next(((l, s) for l, s in weapons if self.main_weapon in s), None) or (weapons[0] if weapons else None)
        if pick and pick[0] not in getattr(self, "_wield_tried", set()):
            self._wield_tried = getattr(self, "_wield_tried", set()) | {pick[0]}
            self.wield(pick[0])
            self.rewields += 1
            return True
        return False

    def weapon_rank(self, s):
        """weapons: Excalibur > the two long-sword-skill blades > anything else. Lawful: katana < long sword
        (a long sword can still become Excalibur); others: long sword < katana. Ties: known enchantment."""
        m = re.search(r"(?:^|\s)([+-]\d+) ", s)
        ench = int(m.group(1)) if m else 0
        lawful = int(self.last_bl[nh.NLE_BL_ALIGN]) == 1
        if "Excalibur" in s:
            return (3, ench)
        if re.search(r"\blong swords?\b", s):
            return (2 if lawful else 1, ench)
        if re.search(r"\bkatanas?\b", s) or (re.search(r"\bsamurai swords?\b", s) and "long samurai" not in s):
            return (1 if lawful else 2, ench)
        return (0, ench)

    def weapon_upgrade(self, inv):
        """Wield the best-ranked weapon we carry if it beats the wielded one (or nothing is wielded).
        Never a known-cursed one; never switch away from a cursed (welded) one; each candidate tried once."""
        if getattr(self, "polyd", False) or self.handless():
            return False                     # animal forms can't hold weapons ("Don't be ridiculous!")
        cur = next((s for _, c, s in inv if WIELDED_RE.search(s)), None)
        if cur is not None and " cursed" in " " + cur:
            return False
        tried = getattr(self, "_wield_tried", set())
        cands = [(self.weapon_rank(s), l, s) for l, c, s in inv
                 if c == nh.WEAPON_CLASS and not WIELDED_RE.search(s) and " cursed" not in " " + s
                 and not re.search(r"\b(arrows?|bolts?|ya|darts?|shuriken|bows?|crossbows?|yumi|sling)\b", s)
                 and (l, s) not in tried]
        if not cands:
            return False
        rank, l, s = max(cands, key=lambda x: x[0])
        if cur is not None and rank <= self.weapon_rank(cur):
            return False
        if cur is not None and rank[0] == 0:
            return False                     # only the long-sword-skill blades replace a wielded weapon
        self.cur_act = "wield"
        t0 = self.turn()
        self.wield(l)
        recent = " ".join([t for tt, t in list(self.messages)[-4:] if tt >= t0] + [self.message()])
        if "Don't be ridiculous" in recent:
            self.polyd = True                # a form we failed to notice; retry after "You return to ... form"
            return True
        self._wield_tried = tried | {(l, s)}
        self.rewields += 1
        return True

# =====================================================================================
# kill_loot: a dead monster's inventory lies UNDER its corpse, so the '[' never shows.
#            Look at the square of every humanoid we kill and take armor/food.
# =====================================================================================
M1_HUMANOID = 0x20000
WIELDED_RE = re.compile(r"\((?:weapons? in \w+|wielded)")
PM_BY_NAME_V = {nh.permonst(i).mname: nh.permonst(i) for i in range(nh.NUMMONS)}


class ValkMixin2:
    def valk2_init(self):
        self.kill_loot = []           # (level key, pos, turn)
        self.kill_loot_checks = 0

    # ------------------------------------------------------------------ kill loot
    def note_kill(self, name, pos):
        if not self.vopt("kill_loot", False) or pos is None:
            return
        pm = PM_BY_NAME_V.get(name)
        if pm is not None and pm.mflags1 & M1_HUMANOID:
            self.kill_loot.append((self.cur_key, pos, self.turn()))

    def kill_loot_step(self, lv):
        if not self.kill_loot:
            return False
        t = self.turn()
        self.kill_loot = [k for k in self.kill_loot if t - k[2] < 300]
        y, x = self.pos()
        cand = [k for k in self.kill_loot if k[0] == lv.key]
        if not cand:
            return False
        goal = min(cand, key=lambda k: max(abs(k[1][0] - y), abs(k[1][1] - x)))
        if goal[1] == (y, x):
            self.kill_loot.remove(goal)
            self.kill_loot_checks += 1
            self.inspected.get(lv.key, set()).discard((y, x))
            self.armor_pickup_here(lv)
            return True
        if max(abs(goal[1][0] - y), abs(goal[1][1] - x)) > 15 or not self.go_toward(lv, goal[1]):
            self.kill_loot.remove(goal)
            return False
        return True

# =====================================================================================
# elb2: Elbereth as measured in NLE 3.6.6 wizard mode
#   - while you stand on a correctly spelled Elbereth, monsters that respect it never melee you
#   - it survives waiting; your first melee attack (and usually a throw) erases it
#   - ~1 in 5 finger engravings is misspelled and does nothing -> always read it back
# =====================================================================================
ELB_IGNORE_NAMES = {"minotaur", "shopkeeper", "guard", "watchman", "watch captain", "aligned priest",
                    "high priest", "Oracle"}
SWARMERS = {"killer bee", "soldier ant", "fire ant", "giant ant"}

# Somebody attacked us from a distance (mthrowu.c monshoot / thitu, zap.c buzz, muse.c), seen or not.
RTHREAT_RE = re.compile(r"(?:throws|shoots) |zaps (?:a|an|the) |You are (?:almost )?hit by |You are hit!|misses you\.|"
                        r"whizzes by you|hits you!|crashes on your head|You hear a nearby zap")
# ...but arrow/dart/rock traps print the same 'You are hit by' lines
RTRAP_RE = re.compile(r"trap|shoots out at you|falls on your head|from the ceiling")
RTHREAT_TTL = 100


B_HUMAN_MLET = next(nh.permonst(i).mlet for i in range(nh.NUMMONS) if nh.permonst(i).mname == "human")
B_ANGEL_MLET = next(nh.permonst(i).mlet for i in range(nh.NUMMONS) if nh.permonst(i).mname == "Angel")

NO_ENGRAVE_CMAP = {23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 34, 39, 40, 41}   # stairs/ladders, altar, grave,
#                    throne, sink, fountain, water, lava, air, cloud: the game refuses to engrave there
VALK_RANKS = {"stripling", "skirmisher", "fighter", "man-at-arms", "woman-at-arms", "warrior",
              "swashbuckler", "hero", "heroine", "champion", "lord", "lady"}


class ElberethMixin:
    def poly_form(self):
        """Name of the form we are polymorphed into (the status line shows it instead of the rank), else None."""
        line = bytes(self.obs["tty_chars"][22]).decode("latin1")
        m = re.match(r"\S+ the (.+?)\s{2,}St:", line)
        if not m or m.group(1).lower() in VALK_RANKS:
            return None
        return m.group(1).lower()

    def handless(self):
        """Polymorphed into a form that can't wear or wield (nohands / very small: do_wear.c, wield.c)."""
        form = self.poly_form()
        if form is None:
            return False
        pm = PM_BY_NAME_V.get(form)
        if form.startswith("were"):
            pm = next(nh.permonst(i) for i in range(nh.NUMMONS)
                      if nh.permonst(i).mname == form and nh.permonst(i).mlet != B_HUMAN_MLET)
        return pm is None or bool(pm.mflags1 & 0x2000) or pm.msize == 0

    def can_engrave_here(self, lv):
        """What a player knows before trying: the square, and whether they have hands."""
        g = int(lv.under[self.pos()])
        if nh.glyph_is_cmap(g) and nh.glyph_to_cmap(g) in NO_ENGRAVE_CMAP:
            return False
        form = self.poly_form()
        if form is not None:
            pm = PM_BY_NAME_V.get(form)
            if form.startswith("were"):          # lycanthrope: the status line names it, the body is the animal
                pm = next(nh.permonst(i) for i in range(nh.NUMMONS)
                          if nh.permonst(i).mname == form and nh.permonst(i).mlet != B_HUMAN_MLET)
            if pm is None or pm.mflags1 & 0x2000 or pm.msize == 0:     # M1_NOHANDS / very small
                return False
        return True
    def elb2_init(self):
        self.elb_state = None        # dict(pos, key, since, last_read, hp_hist)
        self.elb_engraves = 0
        self.elb_misspelled = 0
        self.elb_turns = 0
        self.elb_exits = collections.Counter()
        self.elb_fail_at = None
        self.elb_block_reasons = collections.Counter()
        self.elb_fail_msgs = []
        self.elb_fail = 0
        self.elb_rewrites = 0
        self.elb_only_c = 0
        self.rthreat = None          # (level key, turn of the last evidence of a ranged attacker)
        self.rthreat_events = collections.Counter()
        self.rthreat_msgs = []

    def read_engraving(self):
        """Text of the engraving under us, from the answer to THIS ':' only (older 'You read' lines in the
        log belong to earlier reads and must not be used); last match if the answer has several lines."""
        seq0 = self.msg_seq
        self.raw_step(ord(":"))
        self.settle()
        n_new = min(self.msg_seq - seq0, len(self.messages))
        txt = " ".join(m for _, m in list(self.messages)[len(self.messages) - n_new:]) if n_new else ""
        found = re.findall(r'You read: "([^"]*)"', txt)
        return found[-1] if found else ""

    def respects(self, pos, name):
        if name == "invisible" or name in ELB_IGNORE_NAMES:
            return False
        pm = PM_BY_NAME_V.get(name)
        if pm is None:
            return False
        return pm.mlet not in (B_HUMAN_MLET, B_ANGEL_MLET)

    # ------------------------------------------------------------ ranged threat (rthreat)
    def rthreat_note(self, m):
        """Called for every message: a missile, ray or wand aimed at us (or a zap heard nearby)."""
        if not self.vopt("rthreat", False) or not RTHREAT_RE.search(m):
            return
        t = self.turn()
        if getattr(self, "own_zap_turn", None) == t:          # our own ray bouncing back
            return
        recent = " ".join(mm for tt, mm in list(self.messages)[-4:] if tt == t)
        if RTRAP_RE.search(recent):
            return
        self.rthreat_set("msg", m)

    def rthreat_set(self, why, m=""):
        if not hasattr(self, "rthreat_events"):
            return
        self.rthreat = (self.cur_key, self.turn())
        self.rthreat_events[why] += 1
        if len(self.rthreat_msgs) < 30:
            self.rthreat_msgs.append(f"T{self.turn()} {why}: {m[:120]}")

    def rthreat_active(self):
        """A ranged attacker (possibly unseen) is around: Elbereth does not help, don't write or rest on it.
        Clears after RTHREAT_TTL turns without new evidence, and on another level."""
        r = getattr(self, "rthreat", None)
        return bool(self.vopt("rthreat", False) and r and r[0] == self.cur_key
                    and self.turn() - r[1] <= RTHREAT_TTL)

    def elb_blocked(self, lv):
        """Some visible monster that Elbereth won't stop (wrong type, or can hurt from range): don't write.
        rthreat: monsters that merely might carry missiles/wands (class C) count as respecting it; a ranged
        attack seen or felt switches Elbereth off for a while instead (rthreat_active)."""
        glyphs, me = self.obs["glyphs"], self.pos()
        skip = ("Oracle", "shopkeeper", "aligned priest") if self.vopt("elb_peace", False) else ()
        full = ELB.blockers(glyphs, me, lv.peaceful, lv.key[0], skip_names=skip)
        if full and not ELB.blockers(glyphs, me, lv.peaceful, lv.key[0], optimistic=True, skip_names=skip):
            self.elb_only_c += 1                  # ticks where only class-C monsters stood in the way
        bl = full
        if full and self.vopt("rthreat", False):
            bl = ELB.blockers(glyphs, me, lv.peaceful, lv.key[0], optimistic=True, skip_names=skip)
        if bl:
            self.elb_block_reasons[bl[0][1].split(":")[0]] += 1
        return bool(bl)

    def elb_wanted(self, lv, hostiles):
        hp, maxhp = self.bl(nh.NLE_BL_HP), self.bl(nh.NLE_BL_HPMAX)
        if not self.can_engrave_here(lv) or self.elb_fail_at == (lv.key, self.pos(), self.turn()):
            return False
        dip_on = self.vopt("dip_elb", False) and self.turn() < getattr(self, "dip_threat_until", -1)
        if (self.can_pray() and not dip_on) or self.rthreat_active():
            return False
        if G.KIND[lv.under[self.pos()]] in (G.UPSTAIR, G.DOWNSTAIR):
            return False
        if int(self.last_bl[nh.NLE_BL_CONDITION]) & (nh.BL_MASK_LEV | nh.BL_MASK_BLIND | nh.BL_MASK_STUN | nh.BL_MASK_CONF):
            return False
        y, x = self.pos()
        near = [(p, n) for p, n in self.visible_hostiles(lv) if max(abs(p[0] - y), abs(p[1] - x)) <= 3]
        threats = hostiles + [t for t in near if t not in hostiles]
        if not threats:
            return False
        swarm = sum(1 for _, n in threats if n in SWARMERS)
        dip = self.vopt("dip_elb", False) and self.turn() < getattr(self, "dip_threat_until", -1) \
            and any(n in ("water demon", "water moccasin") for _, n in threats)
        if not (hp < maxhp * self.vopt("elb_hp", 0.5) or swarm >= 2 or dip):
            return False
        return not self.elb_blocked(lv)

    def elb_step(self, lv, hostiles):
        if not self.vopt("elb2", True):
            return False
        st = self.elb_state
        y, x = self.pos()
        hp, maxhp = self.bl(nh.NLE_BL_HP), self.bl(nh.NLE_BL_HPMAX)
        if st is not None:
            if st["pos"] != (y, x) or st["key"] != lv.key:
                self.elb_exits["moved"] += 1
                self.elb_state = None
            else:
                bad = [n for p, n in hostiles if not self.respects(p, n)]
                hurt = hp < st["hp_hist"][-1]
                st["hp_hist"].append(hp)
                # rthreat: hurt while the engraving is intact and nothing that ignores it is adjacent -> hit
                # from range. (A broken engraving explains a melee hit: rewrite below.)
                if hurt and not bad and self.vopt("rthreat", False) and not self.rthreat_active() \
                        and self.read_engraving() == "Elbereth":
                    st["last_read"] = self.turn()
                    self.rthreat_set("hurt on Elbereth", f"{st['hp_hist'][-2]}->{hp}")
                if self.rthreat_active():
                    self.elb_exits["rthreat"] += 1
                    self.elb_state = None
                    return False
                # a dust engraving wears off on its own (allmain.c: 1/(40+3*Dex) per turn); with a foe
                # adjacent check it every turn (reading is free); a hit through a smudged one means rewrite
                if hostiles and not bad:
                    st["last_read"] = self.turn()
                    if self.read_engraving() != "Elbereth":
                        if self.elb_blocked(lv):
                            self.elb_exits["blocked"] += 1
                            self.elb_state = None
                            return False
                        self.elb_rewrites += 1
                        st["hp_hist"] = [hp]
                        return self.elb_write(lv)
                losing = len(st["hp_hist"]) > 4 and st["hp_hist"][-1] < st["hp_hist"][-5] - 2
                if bad or losing:
                    self.elb_exits["ignored" if bad else "ranged"] += 1
                    self.elb_state = None
                    return False                       # fight / let tactics handle it
                visible = self.visible_hostiles(lv)
                early = not visible and hp >= maxhp * 0.6
                if hp >= maxhp * self.vopt("elb_exit", 0.85) or early:
                    self.elb_exits["healed"] += 1
                    self.elb_state = None
                    return False
                if self.turn() - st["since"] > self.vopt("elb_max", 400):
                    self.elb_exits["timeout"] += 1
                    self.elb_state = None
                    return False
                if self.turn() - st["last_read"] >= 4:
                    st["last_read"] = self.turn()
                    if self.read_engraving() != "Elbereth":
                        if self.elb_blocked(lv):
                            self.elb_exits["blocked"] += 1
                            self.elb_state = None
                            return False
                        return self.elb_write(lv)
                self.elb_turns += 1
                self.cur_act = "rest"
                self.press("s")
                return True
        if self.vopt("dip_elb", False) and self.turn() < getattr(self, "dip_threat_until", -1) \
                and not self.can_engrave_here(lv) and self.dip_step_off(lv):
            return True
        if not self.elb_wanted(lv, hostiles):
            return False
        return self.elb_write(lv)

    def dip_step_off(self, lv):
        """A dip let out a water demon / moccasins and we stand on the fountain, where nothing can be
        engraved: step to a free neighbouring square that can hold an Elbereth."""
        import glyphs as G2
        y, x = self.pos()
        g = self.obs["glyphs"]
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            ny, nx = y + dy, x + dx
            if not (0 <= ny < g.shape[0] and 0 <= nx < g.shape[1]):
                continue
            k = G2.KIND[int(g[ny, nx])]
            if k in (G2.FLOOR, G2.CORPSE, G2.OBJECT) and G2.KIND[int(lv.under[ny, nx])] in (G2.FLOOR, G2.CORPSE, G2.OBJECT):
                self.cur_act = "dipflee"
                self.move((ny, nx))
                return True
        return False

    def elb_write(self, lv):
        """Engrave and verify by reading. Any failure to reach the text prompt (fountain/altar/stairs,
        polymorphed into a handless form, levitating, ...) backs off instead of retrying every tick."""
        here = (lv.key, self.pos())
        for attempt in range(3):
            ok = self.engrave_elbereth()
            self.elb_engraves += 1
            if not ok:
                # precondition missed a case: log it (to find it), and don't retry on this square this turn
                self.elb_fail += 1
                self.elb_fail_msgs.append(" ".join(m for _, m in list(self.messages)[-2:])[:80])
                self.elb_fail_at = (lv.key, self.pos(), self.turn())
                self.elb_state = None
                return False
            if self.read_engraving() == "Elbereth":
                self.elb_state = {"pos": self.pos(), "key": lv.key, "since": self.turn(),
                                  "last_read": self.turn(), "hp_hist": [self.bl(nh.NLE_BL_HP)]}
                self.cur_act = "rest"
                return True
            self.elb_misspelled += 1
        self.elb_state = None
        return True
