"""Valkyrie-branch features, each behind its own flag in role_opts.

nymph:       nymphs (and monkeys) steal and teleport. Shoot them from range, melee them first,
             and after a theft hunt them and loot the square they die on; re-wield the stolen
             main weapon.
armor_mode:  "safe"        - only known-mundane armor (previous behaviour)
             "tested"      - also random-appearance helm/gloves/boots into an EMPTY slot, but only
                             once the item is known not cursed (altar test, or B/U/C shown)
             "aggressive"  - also random-appearance helm/gloves/boots into an empty slot, untested;
                             undo levitation (take off, else pray) and drop fumbling items.
"""
import re

import numpy as np
import nle.nethack as nh

import glyphs as G
from equipment import parse_armor, HELM, GLOVES, BOOTS

ROWS, COLS = 21, 79
THIEVES = ("water nymph", "wood nymph", "mountain nymph", "monkey")
NYMPHS = ("water nymph", "wood nymph", "mountain nymph")
ALTAR_GLYPH = nh.GLYPH_CMAP_OFF + 27

# random appearances that may hide a bad item (never conical hat = dunce cap / cornuthaum)
RISKY = {
    "plumed helmet": HELM, "etched helmet": HELM, "crested helmet": HELM, "visored helmet": HELM,
    "old gloves": GLOVES, "padded gloves": GLOVES, "riding gloves": GLOVES, "fencing gloves": GLOVES,
    "combat boots": BOOTS, "jungle boots": BOOTS, "hiking boots": BOOTS, "mud boots": BOOTS,
    "buckled boots": BOOTS, "riding boots": BOOTS, "snow boots": BOOTS,
}
NEVER = ("helm of opposite alignment", "gauntlets of fumbling", "fumble boots", "levitation boots",
         "dunce cap", "conical hat")


def known_uncursed(s):
    return bool(re.search(r"\b(uncursed|blessed)\b", s))


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
        self.altar_tests = 0
        self.risky_worn = []
        self.lev_fixes = 0
        self.fumble_drops = 0
        self.tested_bad = set()
        self.inspected_daggers = {}
        self.daggers_picked = 0
        self.nymph_waits = 0
        self.nymph_elbs = 0
        self.nymph_hide = None
        self.nymph_escapes = 0

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
        if self.vopt("nymph", False) and re.search(r"You turn into an? \w+|shrink out of your|break out of your armor|armor falls around you", m):
            self.were_drop = (self.cur_key, self.pos())      # armor fell here; collect it once human again
        if "return to human form" in m and getattr(self, "were_drop", None):
            self.loot_key, self.loot_sq = self.were_drop
            self.were_drop = None
        if "You float" in m or "float into the air" in m or "start to float" in m:
            self.just_levitated = True
        if self.vopt("armor_mode", "safe") == "aggressive" and re.search(r"You (trip|flounder|slip)", m):
            self.fumbling_seen = True

    def dagger_count(self):
        n = 0
        for _, c, s in self.inventory():
            if c == nh.WEAPON_CLASS and re.search(r"\bdaggers?\b", s) and "weapon in hand" not in s:
                m = re.match(r"^(\d+) ", s)
                n += int(m.group(1)) if m else 1
        return n

    def dagger_targets(self, lv):
        """Remembered dagger piles to collect (Valkyries can throw daggers)."""
        if not self.vopt("daggers", False) or self.dagger_count() >= 8:
            return None
        mask = G.DAGGER_GLYPH[lv.under].copy()
        for p in self.inspected_daggers.get(lv.key, ()):
            mask[p] = False
        mask &= ~lv.shop
        return mask if mask.any() else None

    def dagger_step(self, lv):
        mask = self.dagger_targets(lv)
        if mask is None:
            return False
        y, x = self.pos()
        if mask[y, x]:
            self.inspected_daggers.setdefault(lv.key, set()).add((y, x))
            self.pickup_matching(("dagger",))
            self.daggers_picked += 1
            return True
        k_mem, k_live = self.kind_grid(lv)
        p = self.passable_grid(lv, k_mem, k_live)
        dist, prev, reached = self.dijkstra(lv, k_mem, k_live, p, (y, x), mask, max_cost=40)
        if reached is None:
            return False
        step = self.first_step(prev, (y, x), reached)
        if step is None:
            return False
        self.move(step)
        return True

    def thieves_visible(self, lv):
        g = self.obs["glyphs"]
        out = []
        for p, name in self.visible_hostiles(lv):
            if name in THIEVES:
                out.append((p, name))
        return out

    def nymph_step(self, lv, hostiles):
        if not self.vopt("nymph", False):
            return False
        y, x = self.pos()
        # 1) adjacent thief: hit it first (normal melee would pick the lowest level target)
        adj = [(p, n) for p, n in hostiles if n in THIEVES]
        if adj:
            self.attack(adj[0][0])
            return True
        # 0) hiding on another level after slipping away from a nymph
        hide = self.nymph_hide
        if hide is not None:
            here = self.stairs_kind_here(lv)
            if lv.key == hide["from"] or here is None:
                self.nymph_hide = None
            elif not hostiles:
                if self.turn() < hide["until"]:
                    self.cur_act = "rest"
                    self.press("2"); self.press("0"); self.press("s")
                    return True
                self.nymph_hide = None
                self.press(hide["back"])
                return True
        th = self.thieves_visible(lv)
        if not th:
            return False
        if self.vopt("nymph_avoid", False) and not self.stolen_pending and self.nymph_escape(lv, th):
            return True
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

    def nymph_escape(self, lv, th):
        """Nothing to gain from a nymph: leave by the stairs if we get there first."""
        y, x = self.pos()
        nyms = [t for t in th if t[1] in NYMPHS]
        if not nyms:
            return False
        d_n = min(max(abs(p[0] - y), abs(p[1] - x)) for p, _ in nyms)
        if d_n < 3:
            return False
        here = self.stairs_kind_here(lv)
        if here is not None and self.can_use_stairs(lv, here):
            key = ">" if here == G.DOWNSTAIR else "<"
            self.nymph_escapes += 1
            if key == "<":
                self.nymph_hide = {"from": lv.key, "back": ">", "until": self.turn() + 50}
            else:
                self.descents += 1
                self.took_stairs = True
            self.press(key)
            return True
        k_mem, k_live = self.kind_grid(lv)
        passable = self.passable_grid(lv, k_mem, k_live)
        stairs = self.stairs_mask(lv, k_mem)
        if not stairs.any():
            return False
        dist, prev, reached = self.dijkstra(lv, k_mem, k_live, passable, (y, x), stairs, max_cost=30)
        if reached is None or dist[reached] >= d_n - 1:
            return False
        step = self.first_step(prev, (y, x), reached)
        if step is None:
            return False
        self.cur_act = "stairs"
        self.move(step)
        return True

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
        for line in tty.split("\n"):
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
        if wielded or not self.vopt("nymph", False):
            return False
        weapons = [(l, s) for l, c, s in inv if c == nh.WEAPON_CLASS and not re.search(r"\b(arrows?|bolts?|ya|darts?)\b", s)]
        pick = next(((l, s) for l, s in weapons if self.main_weapon in s), None) or (weapons[0] if weapons else None)
        if pick and pick[0] not in getattr(self, "_wield_tried", set()):
            self._wield_tried = getattr(self, "_wield_tried", set()) | {pick[0]}
            self.wield(pick[0])
            self.rewields += 1
            return True
        return False

    # ================================================================== risky armor
    def risky_allowed(self, a, s_text, worn):
        """Called for armor the base module calls unsafe. a = parse_armor(...)."""
        mode = self.vopt("armor_mode", "safe")
        if mode == "safe" or a is None:
            return False
        if a["name"] in NEVER or a["name"] not in RISKY:
            return False
        slot = RISKY[a["name"]]
        if slot in worn or not self.slot_allowed(slot):
            return False
        if mode == "aggressive":
            return not a["cursed"]
        # tested: B/U/C must be known and not cursed
        return known_uncursed(s_text) and not a["cursed"]

    def risky_candidate(self, a, worn):
        """Worth picking up (tested mode: to test later; aggressive: to wear)."""
        mode = self.vopt("armor_mode", "safe")
        if mode == "safe" or a is None or a["name"] not in RISKY or a["name"] in NEVER or a["cursed"]:
            return False
        slot = RISKY[a["name"]]
        if slot in worn or not self.slot_allowed(slot):
            return False
        held = [x for x in self.armor_inventory() if not x["worn"] and x["name"] in RISKY and RISKY[x["name"]] == slot]
        return not held

    def altar_step(self, lv):
        """tested mode: drop untested risky armor on a known altar to learn B/U/C."""
        if self.vopt("armor_mode", "safe") != "tested":
            return False
        untested = [(l, s) for l, c, s in self.inventory() if c == nh.ARMOR_CLASS and "being worn" not in s
                    and (parse_armor(s) or {}).get("name") in RISKY and not re.search(r"\b(uncursed|blessed|cursed)\b", s)]
        if not untested:
            return False
        amask = lv.under == ALTAR_GLYPH
        if not amask.any():
            return False
        y, x = self.pos()
        if amask[y, x]:
            for l, s in untested:
                self.drop_letter(l)
            self.altar_tests += 1
            self.pickup_all()
            return True
        return self.go_toward_mask(lv, amask) if hasattr(self, "go_toward_mask") else False

    def risky_aftercare(self):
        """aggressive mode: undo levitation and fumbling caused by a risky item."""
        if self.vopt("armor_mode", "safe") == "safe":
            return False
        cond = int(self.last_bl[nh.NLE_BL_CONDITION])
        lev = bool(cond & nh.BL_MASK_LEV)
        inv = self.armor_inventory()
        worn_risky = [a for a in inv if a["worn"] and a["name"] in RISKY]
        if lev:
            boots = [a for a in worn_risky if RISKY[a["name"]] == BOOTS]
            for a in boots:
                if a["name"] not in self.tested_bad and self.take_off(a):
                    self.tested_bad.add(a["name"])
                    self.lev_fixes += 1
                    self.drop_letter(a["letter"])
                    return True
            if self.can_pray():
                self.lev_fixes += 1
                self.pray()
                return True
        if getattr(self, "fumbling_seen", False):
            self.fumbling_seen = False
            for a in worn_risky:
                if RISKY[a["name"]] in (GLOVES, BOOTS) and a["name"] not in self.tested_bad:
                    if self.take_off(a):
                        self.tested_bad.add(a["name"])
                        self.fumble_drops += 1
                        self.drop_letter(a["letter"])
                        return True
        return False


# =====================================================================================
# kill_loot: a dead monster's inventory lies UNDER its corpse, so the '[' never shows.
#            Look at the square of every humanoid we kill and take armor/daggers/food.
# choke:     with 2+ hostiles in view, fight from a square few of them can reach at once
#            (corridor, doorway); go there if we arrive before they do.
# =====================================================================================
M1_HUMANOID = 0x20000
CORRIDOR_GLYPHS = (nh.GLYPH_CMAP_OFF + 21, nh.GLYPH_CMAP_OFF + 22)
PM_BY_NAME_V = {nh.permonst(i).mname: nh.permonst(i) for i in range(nh.NUMMONS)}


class ValkMixin2:
    def valk2_init(self):
        self.kill_loot = []           # (level key, pos, turn)
        self.kill_loot_checks = 0
        self.choke_moves = 0
        self.choke_waits = 0

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
            if self.armor_pickup_here(lv):
                return True
            if self.vopt("daggers", False) and self.dagger_count() < 8:
                self.pickup_matching(("dagger",))
            return True
        if max(abs(goal[1][0] - y), abs(goal[1][1] - x)) > 15 or not self.go_toward(lv, goal[1]):
            self.kill_loot.remove(goal)
            return False
        return True

    # ------------------------------------------------------------------ chokepoints
    def attack_slots(self, lv, k_mem, p, c):
        """How many squares around c a monster could attack from."""
        cy, cx = c
        door_here = k_mem[cy, cx] in (G.DOOR_OPEN, G.DOOR_CLOSED)
        n = 0
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if not (dy or dx):
                    continue
                ny, nx = cy + dy, cx + dx
                if not (0 <= ny < ROWS and 0 <= nx < COLS) or not p[ny, nx]:
                    continue
                if dy and dx and (door_here or k_mem[ny, nx] in (G.DOOR_OPEN, G.DOOR_CLOSED)):
                    continue
                n += 1
        return n

    def choke_step(self, lv, hostiles):
        if not self.vopt("choke", False):
            return False
        y, x = self.pos()
        foes = [(p, n) for p, n in self.visible_hostiles(lv)
                if max(abs(p[0] - y), abs(p[1] - x)) <= 7 and n not in ("floating eye", "gas spore")]
        if len(foes) < 2:
            self.choke_waits = 0
            return False
        k_mem, k_live = self.kind_grid(lv)
        p = self.passable_grid(lv, k_mem, k_live)
        p_free = p.copy()
        here = self.attack_slots(lv, k_mem, p_free, (y, x))
        if here <= 2:
            # already in a good spot: hold it and let them come one at a time
            if not hostiles and self.choke_waits < 6:
                self.choke_waits += 1
                self.cur_act = "fight"
                self.press("s")
                return True
            return False
        if len(hostiles) >= 2 or len(hostiles) == 0 or self.vopt("choke_engaged", True):
            dist, prev, _ = self.dijkstra(lv, k_mem, k_live, p, (y, x), None, max_cost=10)
            best = None
            ys, xs = np.nonzero(dist <= 8)
            for cy, cx in zip(ys, xs):
                c = (int(cy), int(cx))
                if c == (y, x) or not p[c]:
                    continue
                slots = self.attack_slots(lv, k_mem, p_free, c)
                if slots > 2:
                    continue
                d_me = int(dist[c])
                d_foe = min(max(abs(fp[0] - c[0]), abs(fp[1] - c[1])) for fp, _ in foes)
                if d_me >= d_foe:
                    continue                       # they get there first
                score = (slots, d_me)
                if best is None or score < best[0]:
                    best = (score, c)
            if best is not None:
                step = self.first_step(prev, (y, x), best[1])
                if step is not None and G.KIND[self.obs["glyphs"][step]] not in (G.MONSTER, G.PET):
                    self.choke_moves += 1
                    self.cur_act = "fight"
                    self.move(step)
                    return True
        return False
