"""Fighting: melee, throwing (at monsters we won't melee, at a blocker in the only way through),
picking thrown missiles back up, hunting a shooter, attack wands."""
import re

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import COLS, DELTA2KEY, NEIGH, ROWS, ray_squares
from nhbot.goals import GOALS
from nhbot.monsters import RANGED_TARGETS
from nhbot.nav import line_clear


THROWABLE = ("dagger", "dart", "knife", "shuriken", "javelin", "spear")


THROW_STONES = ("flint stone", "rock")


# =====================================================================================
# Attack wands (wiki: Wand of sleep and the ray wand pages)
# =====================================================================================
RAY_WANDS = ("sleep", "magic missile", "fire", "cold", "lightning")   # rays bounce off walls


BEAM_WANDS = ("striking",)                                            # no bounce


SAFE_RAY_DIST = 7          # ray range is 7..13: a wall >= 7 away can't bounce it back onto us


# mhitu.c: an attack by a monster we can't see is reported as "It <verb>" and marks its square with an 'I'
IT_ATTACK_RE = re.compile(r"\bIt (?:hits|bites|misses|just misses|touches you|stings|kicks|butts|claws|scratches|"
                          r"thrusts|swings|grabs|hugs|lashes|squeezes|engulfs|tickles|stabs|pummels|whips)\b")


# mhitu.c: a melee attack on us by a monster we see: "The <name> <verb>!" (hallucination: the name is random);
# monster-vs-monster and missiles read differently ("The gnome hits the jackal.", "You are hit by a dart.")
MELEE_ON_US_RE = re.compile(r"\bThe [^.!]+? (?:hits|bites|misses|just misses|stings|kicks|butts|claws|scratches|"
                            r"thrusts|swings|grabs|lashes|tickles|stabs|pummels|whips|touches you|engulfs you|"
                            r"squeezes you|gores|charms you)!")


# Somebody attacked us from a distance (mthrowu.c monshoot / thitu, zap.c buzz, muse.c), seen or not.
RTHREAT_RE = re.compile(r"(?:throws|shoots) |zaps (?:a|an|the) |You are (?:almost )?hit by |You are hit!|misses you\.|"
                        r"whizzes by you|hits you!|crashes on your head|You hear a nearby zap")


# ...but arrow/dart/rock traps print the same 'You are hit by' lines
RTRAP_RE = re.compile(r"trap|shoots out at you|falls on your head|from the ceiling")


class CombatMixin:
    def combat_init(self):
        self.zaps = 0
        self.empty_wands = set()
        self.own_zap_turn = -99        # a bouncing ray of ours is not an enemy shooter

    def attack(self, target):
        self.cur_act = "fight"
        y, x = self.pos()
        if (target[0] - y, target[1] - x) not in DELTA2KEY:   # we were moved this tick (e.g. teleported)
            self.press("s")
            return
        key = DELTA2KEY[(target[0] - y, target[1] - x)]
        self.last_attack_target = target
        self.last_move_target = None
        self.press("F")
        self.press(key)

    def throwables(self):
        out = []
        for letter, ocls, s in self.inventory():
            if "weapon in hand" in s or "(wielded)" in s or " cursed" in s:
                continue
            if ocls == nh.WEAPON_CLASS and any(t in s for t in THROWABLE):
                out.append((0, letter, s))
            elif ocls == nh.GEM_CLASS and any(t in s for t in THROW_STONES):
                out.append((1, letter, s))
        out.sort()
        return [(l, s) for _, l, s in out]

    def ranged_target(self, lv):
        """Floating eyes / gas spores in a clear straight line -> (dir_key, dist, pos)."""
        if not self.avoid_cells:
            return None
        y, x = self.pos()
        g = self.obs["glyphs"]
        k_mem = G.KIND[lv.under]
        for (ty, tx) in self.avoid_cells:
            dy, dx = ty - y, tx - x
            d = max(abs(dy), abs(dx))
            if d == 0 or d > 6 or not (dy == 0 or dx == 0 or abs(dy) == abs(dx)):
                continue
            name = G.monster_name(g[ty, tx])
            if name not in RANGED_TARGETS:
                continue
            if name == "gas spore" and d < 3:
                continue
            sy, sx = (dy > 0) - (dy < 0), (dx > 0) - (dx < 0)
            if line_clear(k_mem, g, y, x, sy, sx, d):
                return DELTA2KEY[(sy, sx)], d, (ty, tx), (sy, sx)
        return None

    def throw(self, letter, key, ray):
        if not self.ask("t", "throw"):
            return
        self.press(letter, expect_prompt=True)
        if "direction" not in self.message().lower() and self.obs["misc"][0] == 0:
            self.msg_audit["throw_key_without_direction"] += 1
        if "direction" in self.message().lower() or self.obs["misc"][0] == 0:
            self.press(key)
        else:
            self.settle()
        self.throws += 1
        self.retrieve.append((self.cur_key, ray, self.turn() + GOALS["retrieve"].ttl))
        self.goal_event("retrieve", "created")

    def retrieve_goals(self, lv):
        """Squares on our rays (in throw order) where a weapon or gem lies now; expired rays dropped."""
        t = self.turn()
        n = len(self.retrieve)
        self.retrieve = [r for r in self.retrieve if r[2] > t]
        self.goal_event("retrieve", "expired", n - len(self.retrieve))
        g = self.obs["glyphs"]
        out = []
        for key, ray, _ in self.retrieve:
            if key != lv.key:
                continue
            for p in ray:
                if self.opts.shop_by_square and self.merch_risk(lv, p):
                    continue
                if G.KIND[g[p]] == G.OBJECT and nh.glyph_is_object(int(g[p])) and \
                        ord(nh.objclass(nh.glyph_to_obj(int(g[p]))).oc_class) in (nh.WEAPON_CLASS, nh.GEM_CLASS) \
                        and p not in out:
                    out.append(p)
        return out

    def expendables(self):
        """Inventory items worth less than a way through: missiles first, then gems/rocks, spare weapons,
        unworn armor, ordinary tools."""
        out = [(0, l, s) for l, s in self.throwables()]
        for letter, ocls, s in self.inventory():
            if any(w in s for w in ("weapon in hand", "(wielded", "being worn", "(in use", " cursed", "alternate weapon")):
                continue
            if ocls == nh.GEM_CLASS:
                out.append((1, letter, s))
            elif ocls == nh.WEAPON_CLASS:
                out.append((2, letter, s))
            elif ocls == nh.ARMOR_CLASS:
                out.append((3, letter, s))
            elif ocls == nh.TOOL_CLASS and not any(w in s for w in ("pick-axe", "mattock", "unicorn horn", "key", "lock pick", "bag", "sack")):
                out.append((4, letter, s))
        out.sort()
        seen, res = set(), []
        for _, l, s in out:
            if l not in seen:
                seen.add(l); res.append((l, s))
        return res

    def unblock_step(self, lv, grids, goal):
        """Explore/descend goals are reachable only through squares held by monsters we refuse to melee
        (a floating eye in a doorway, a mold in a corridor): throw whatever is expendable at the blocker;
        stuck long with nothing to throw, hit a floating eye anyway (paralysis beats starving)."""
        if not self.avoid_cells:
            return False
        k_mem, k_live, passable = grids
        p2 = passable.copy()
        for c in self.avoid_cells:
            p2[c] = bool(G.PASSABLE[k_mem[c]]) or k_mem[c] == G.DOORWAY
        start = self.pos()
        blocker = None
        if goal.any():
            dist, prev, reached = self.dijkstra(lv, k_mem, k_live, p2, start, goal)
            if reached is not None:
                path, c = [], reached
                while c != start:
                    path.append(c)
                    c = prev[c]
                blocker = next((c for c in reversed(path) if c in self.avoid_cells), None)
        if blocker is None:
            # no goal left, but we are shut in a pocket: most of the known level lies past the blocker
            d1, _, _ = self.dijkstra(lv, k_mem, k_live, passable, start, None)
            d2, _, _ = self.dijkstra(lv, k_mem, k_live, p2, start, None)
            r1, r2 = d1 < (1 << 29), d2 < (1 << 29)
            if r1.sum() * 2 >= r2.sum():
                return False
            near = [c for c in self.avoid_cells if r2[c] and any(
                0 <= c[0] + a < ROWS and 0 <= c[1] + b < COLS and r1[c[0] + a, c[1] + b] for a, b in NEIGH)]
            if not near:
                return False
            blocker = min(near, key=lambda c: d2[c])
        name = G.monster_name(int(self.obs["glyphs"][blocker]))
        self.unblocks += 1
        y, x = start
        dy, dx = blocker[0] - y, blocker[1] - x
        d = max(abs(dy), abs(dx))
        if d <= 6 and (dy == 0 or dx == 0 or abs(dy) == abs(dx)) and not (name == "gas spore" and d < 3):
            sy, sx = (dy > 0) - (dy < 0), (dx > 0) - (dx < 0)
            clear = line_clear(k_mem, self.obs["glyphs"], y, x, sy, sx, d)
            ex = self.expendables() if clear else []
            if ex:
                ray = ray_squares(y, x, sy, sx)
                self.cur_act = "unblock"
                self.last_attack_target = blocker
                self.unblock_throws += 1
                self.throw(ex[0][0], DELTA2KEY[(sy, sx)], ray)
                return True
            if d == 1 and name == "floating eye" and lv.desperate:
                self.unblock_melee += 1
                self.attack(blocker)
                return True
        # get next to it (any adjacent square is in line)
        if d > 1:
            adj = np.zeros((ROWS, COLS), dtype=bool)
            for ny, nx in ((blocker[0] + a, blocker[1] + b) for a, b in NEIGH):
                if 0 <= ny < ROWS and 0 <= nx < COLS and passable[ny, nx]:
                    adj[ny, nx] = True
            if adj.any() and self.walk_to(lv, adj, act="unblock", grids=(k_mem, k_live, passable))[0] == "moved":
                return True
        return False

    def hunt_step(self, lv):
        """hunt_shooter: something hit us from range and nothing is next to us -> close in on the likeliest
        shooter: a visible hostile of the named kind, else one standing on a line with us within 8 squares
        (monsters only fire when lined up, BOLT_LIM). Pursue it for at most 25 turns, while HP >= 40%."""
        t = self.turn()
        y, x = self.pos()
        hp, maxhp = self.bl(nh.NLE_BL_HP), self.bl(nh.NLE_BL_HPMAX)
        if hp < maxhp * 0.4:
            self.hunt = None
            return False
        ev = self.shot_event
        dist = lambda p: max(abs(p[0] - y), abs(p[1] - x))
        if ev and t - ev[0] <= 2:
            self.shot_event = None
            vis = self.visible_hostiles(lv)
            lined = [(p, n) for p, n in vis if dist(p) <= 8 and (p[0] == y or p[1] == x or abs(p[0] - y) == abs(p[1] - x))]
            cands = lined
            if ev[1]:
                cands = [c for c in lined if c[1] == ev[1]] or [c for c in vis if c[1] == ev[1]] or lined
            if cands:
                p, n = min(cands, key=lambda c: dist(c[0]))
                self.hunt = {"key": lv.key, "pos": p, "name": n, "until": t + 25, "lost": 0}
                self.hunts += 1
        h = self.hunt
        if not h:
            return False
        if h["key"] != lv.key or t > h["until"]:
            self.hunt = None
            return False
        same = [p for p, n in self.visible_hostiles(lv) if n == h["name"]]
        if same:
            h["pos"] = min(same, key=lambda p: max(abs(p[0] - h["pos"][0]), abs(p[1] - h["pos"][1])))
            h["lost"] = 0
        else:
            h["lost"] += 1
            if h["lost"] > 5:
                self.hunt = None
                return False
        if dist(h["pos"]) <= 1:
            return False                       # next to it: the fight step takes over
        k_mem, k_live, passable = self.grids(lv)
        # among the steps that get as close as any, prefer one off the target's lines (it fires only when
        # lined up); distances from the target over the same grid
        ty, tx = h["pos"]
        p2 = passable.copy()
        p2[ty, tx] = True
        dmap, _, _ = self.dijkstra(lv, k_mem, k_live, p2, (ty, tx), None, max_cost=80)
        INF = 1 << 29
        if dmap[y, x] < INF:
            cands = []
            for dy, dx in NEIGH:
                ny, nx = y + dy, x + dx
                if 0 <= ny < ROWS and 0 <= nx < COLS and passable[ny, nx] and dmap[ny, nx] < dmap[y, x] \
                        and G.KIND[self.obs["glyphs"][ny, nx]] not in (G.MONSTER, G.PET) \
                        and not ((k_mem[y, x] in (G.DOOR_OPEN, G.DOOR_CLOSED) or k_mem[ny, nx] in (G.DOOR_OPEN, G.DOOR_CLOSED)) and dy and dx):
                    cands.append((int(dmap[ny, nx]), (ny, nx)))
            if cands:
                best = min(c[0] for c in cands)
                pool = [p for d, p in cands if d == best]
                lined = lambda p: p[0] == ty or p[1] == tx or abs(p[0] - ty) == abs(p[1] - tx)
                off = [p for p in pool if not lined(p)]
                self.cur_act = "hunt"
                self.hunt_steps += 1
                self.hunt_offline_steps += bool(off and any(lined(p) for p in pool))
                self.move((off or pool)[0])
                return True
        adj = np.zeros((ROWS, COLS), dtype=bool)
        for dy, dx in NEIGH:
            ny, nx = h["pos"][0] + dy, h["pos"][1] + dx
            if 0 <= ny < ROWS and 0 <= nx < COLS and passable[ny, nx]:
                adj[ny, nx] = True
        if adj.any() and not adj[y, x]:
            hs = self.hunt_steps
            self.hunt_steps += 1                     # counted before the step, as before
            if self.walk_to(lv, adj, max_cost=60, act="hunt", grids=(k_mem, k_live, passable))[0] == "moved":
                return True
            self.hunt_steps = hs
        self.hunt = None
        return False

    def attack_wands(self):
        out = []
        for letter, ocls, s in self.inventory():
            if ocls != nh.WAND_CLASS or letter in self.empty_wands:
                continue
            m = re.search(r"wand of ([a-z ]+?)(?: \(|$)", s)
            if not m:
                continue
            kind = m.group(1).strip()
            if re.search(r"\(\d+:0\)", s):
                continue
            if kind in RAY_WANDS or kind in BEAM_WANDS:
                out.append((letter, kind))
        prio = {"sleep": 0, "striking": 1, "magic missile": 2, "cold": 3, "fire": 4, "lightning": 5}
        return sorted(out, key=lambda t: prio.get(t[1], 9))

    def zap(self, letter, key):
        self.own_zap_turn = self.turn()           # a bouncing ray of ours is not an enemy shooter
        seq0 = self.msg_seq
        if not self.ask("z", "zap"):
            return False
        self.press(letter, expect_prompt=True)
        m = self.message().lower()
        if "direction" in m:
            self.press(key)
        else:
            self.settle()
        msgs = " ".join(t for _, t in list(self.messages)[-3:])
        if self.audit("zap", msgs, seq0, lambda s: "Nothing happens" in s or "You wrest" in s):
            self.empty_wands.add(letter)
        self.zaps += 1
        return True

    def wand_step(self, lv, hostiles):
        wands = self.attack_wands()
        if not wands:
            return False
        for key, d, pos, (dy, dx), name in self.line_targets(lv, max_d=6):
            if d == 1 and pos not in [p for p, _ in hostiles]:
                continue
            if not self.worth_special(pos, name):
                continue
            if d > 1 and self.peaceful_far(lv, pos, key, d):
                continue
            for letter, kind in wands:
                if kind == "sleep" and ("elf" in name or "zombie" in name or "Elvenking" in name):
                    continue                     # sleep resistant
                if kind in RAY_WANDS and not self.ray_safe(lv, -dy, -dx) and not self.ray_safe(lv, dy, dx):
                    continue
                self.cur_act = "fight"
                self.last_attack_target = pos
                return self.zap(letter, key)
        return False

    def ray_safe(self, lv, dy, dx):
        """A ray going from us in direction (dy, dx) can't bounce back at us: a door within SAFE_RAY_DIST
        absorbs it, otherwise no wall, unknown square or boulder lies within SAFE_RAY_DIST."""
        y, x = self.pos()
        k_mem = G.KIND[lv.under]
        for i in range(1, SAFE_RAY_DIST + 1):
            yy, xx = y + i * dy, x + i * dx
            if not (0 <= yy < ROWS and 0 <= xx < COLS):
                return False
            k = k_mem[yy, xx]
            if k in (G.DOOR_OPEN, G.DOOR_CLOSED, G.DOORWAY):
                return True                      # doors absorb the ray
            if k in (G.WALL, G.UNKNOWN, G.BOULDER):
                return False
        return True

    def msg_combat(self, m):
        """Our hits and kills, being shot at, being attacked by something unseen."""
        self.focus_note(m)
        if re.search(r"You (kill|destroy) ", m):
            self.kill_count += 1
        mk = re.search(r"You (kill|destroy) (?:the |an? )?(.+?)!", m)
        self.killed = mk.group(2) if mk else None      # what this message says we killed (thieves read it too)
        if mk and self.last_attack_target:
            lvk = self.levels.get(self.cur_key)
            old_corpse = lvk is not None and G.KIND[lvk.under[self.last_attack_target]] == G.CORPSE
            if not old_corpse:      # an older corpse already lay there: what we'd eat may be that one
                self.kills.append((self.turn(), mk.group(2), self.last_attack_target, self.cur_key))
                self.goal_event("corpse", "created")
        if RTHREAT_RE.search(m) and not RTRAP_RE.search(m) and self.turn() - self.own_zap_turn > 1:
            self.last_shot_turn = self.turn()
            mm = re.search(r"The ([a-z][a-z' -]*?) (?:zaps|shoots|throws|hurls|fires|spits|breathes)", m)
            self.shot_event = (self.turn(), mm.group(1) if mm else None)
        if IT_ATTACK_RE.search(m):
            self.it_attacked = True           # blind_strike: an unseen monster attacked us this turn
        if MELEE_ON_US_RE.search(m):
            self.melee_on_us = True           # hallu_strike: something attacked us in melee this turn
