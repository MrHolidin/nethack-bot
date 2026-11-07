"""Fighting: melee, throwing (at monsters we won't melee, at a blocker in the only way through),
picking thrown missiles back up, hunting a shooter, attack wands."""
import re
from collections import Counter

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.items import WAND_SPENT_RE
from nhbot.consts import COLS, DELTA2KEY, DIRS, NEIGH, ROWS, ray_squares
from nhbot.danger import adj_level, dice_pmf
from nhbot.goals import GOALS
from nhbot.monattacks import ATTACKS
from nhbot.monsters import CARRIERS, PM_BY_NAME, RANGED_TARGETS, permonst_of
from nhbot.nav import line_clear
from nhbot.pricemem import appearance
from nhbot.rays import (RAY_DICE, RAY_RESIST, REFLECTORS, TERRAIN_CODE, beam_walk, our_protection, ray_harm, ray_walk,
                        self_hit_prob, zap_hit_prob, ROOM as ROOM_CODE, STONE as STONE_CODE)


THROWABLE = ("dagger", "dart", "knife", "shuriken", "javelin", "spear")


THROW_STONES = ("flint stone", "rock")


# =====================================================================================
# Attack wands (wiki: Wand of sleep and the ray wand pages)
# =====================================================================================
RAY_WANDS = ("sleep", "magic missile", "fire", "cold", "lightning")   # rays bounce off walls


BEAM_WANDS = ("striking",)                                            # no bounce


SLEPT_TURNS = 30           # a sleep ray puts a monster down for d(6, 25) turns (zap.c): taken as asleep this long
SLEEP_HIT_RE = re.compile(r"The sleep ray hits (?:the )?([\w' -]+?)[.!]")
MR_BIT = {"sleep": 0x04, "fire": 0x01, "cold": 0x02, "lightning": 0x10}    # monst.c mresists: MR_SLEEP, ...
_PM_INDEX = {nh.permonst(i).mname: i for i in range(nh.NUMMONS)}
WAND_PWIN = 0.9            # an attack wand only when P(we win the fight) is at most this (wand_ev_pairs)
PREY_PWIN = 0.95           # explore walks up to a hostile in view we beat with P(win) above this (prey_mask)


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


def wand_resisted(kind, name):
    """wand_resist: does a monster of this kind shrug off this attack wand? sleep / fire / cold / lightning:
    its intrinsic resistance (mresists); magic missile and striking: magic resistance -- mondata.c resists_magm:
    a magic-missile or random-breath attack, or a baby gray dragon (what it wears is not seen)."""
    pm = PM_BY_NAME.get(name)
    if pm is None:
        return False
    if kind in MR_BIT:
        return bool(pm.mresists & MR_BIT[kind])
    if kind in ("magic missile", "striking"):
        return name == "baby gray dragon" or any(a[1] in ("MAGM", "RBRE") for a in ATTACKS[_PM_INDEX[name]])
    return False


def halved(pmf, w, rounding_up):
    """The damage pmf when, with probability w, it is halved (resist: (d + 1) / 2; a ray: d / 2)."""
    out = np.zeros(len(pmf))
    for v, q in enumerate(pmf):
        out[v] += (1 - w) * q
        out[(v + 1) // 2 if rounding_up else v // 2] += w * q
    return out


def wand_effect(kind, name, depth, xl):
    """wand_ev: what our attack wand does to a monster of this kind it reaches -- (P(an effect), damage pmf; None for
    sleep: it falls asleep). zap.c: striking (bhitm) hits when rnd(20) < 10 + AC, 2d12; a ray's hit is rolled on
    the way (zap_hit, rays.ray_walk) and then does magic missile 2d6, fire / cold / lightning 6d6 (fire +7 on a
    cold resistant one, cold +6d3 on a fire resistant one); resist() -- rn2(100 + 12 - level) < its magic
    resistance (mr) -- halves the damage and stops a sleep. AC and level are those of its kind (armor and growth
    unseen); an unknown kind: nothing."""
    pm = PM_BY_NAME.get(name)
    if pm is None or wand_resisted(kind, name):
        return 0.0, None
    n = 100 + 12 - max(1, min(50, adj_level(pm.mlevel, depth, xl)))
    p_res = min(pm.mr, n) / n
    if kind == "striking":
        return max(0, min(20, 9 + pm.ac)) / 20, halved(dice_pmf(2, 12), p_res, True)
    if kind == "sleep":
        return 1 - p_res, None
    dmg = dice_pmf(RAY_DICE[kind][0], 6)
    if kind == "fire" and pm.mresists & MR_BIT["cold"]:
        dmg = np.concatenate([np.zeros(7), dmg])
    if kind == "cold" and pm.mresists & MR_BIT["fire"]:
        dmg = np.convolve(dmg, dice_pmf(6, 3))
    return 1.0, halved(dmg, p_res, False)


class CombatMixin:
    def combat_init(self):
        self.kill_by = Counter()       # our kills, by kind
        self.kill_log = []             # every kill of ours: (turn, name, square, level key) -- self.kills: corpses
        self.zaps = 0
        self.ray_risk_stats = Counter()  # statistics only: our own ray back at us (nhbot.rays), per zap / skip
        self.ray_risk_log = []
        self.slept = {}                  # (level key, pos) -> (turn, name): a sleep ray of ours hit it (note_slept)
        self.zap_stats = Counter()       # sleep marks; zaps held: asleep target, resisting target, on Elbereth
        self.wand_pwin_log = []          # zaps: (turn, target, distance, wand, P(win) fighting on, gain, None, HP)
        self.own_zap_turn = -99        # a bouncing ray of ours is not an enemy shooter
        self.prey_cache = {}             # prey_win by state

    def attack(self, target):
        self.cur_act = "fight"
        y, x = self.pos()
        if (target[0] - y, target[1] - x) not in DELTA2KEY:   # we were moved this tick (e.g. teleported)
            self.press("s")
            return
        key = DELTA2KEY[(target[0] - y, target[1] - x)]
        self.last_attack_target = target
        self.attack_turn = self.turn()           # danger: the monster we hit first may not act
        self.last_move_target = None
        self.press("F")
        self.press(key)

    def throwables(self):
        if self.handless():
            return []                        # "You can't throw or shoot without hands."
        out = []
        for it in self.items():
            if it.held or it.cursed:
                continue
            # the alternate weapon too: a Valkyrie's is her starting dagger, a missile
            if it.ocls == nh.WEAPON_CLASS and any(t in it.text for t in THROWABLE):
                out.append((0, it.letter, it.text))
            elif it.ocls == nh.GEM_CLASS and any(t in it.text for t in THROW_STONES):
                out.append((1, it.letter, it.text))
        out.sort()
        return [(l, s) for _, l, s in out]

    def ranged_target(self, lv):
        """Floating eyes / gas spores in a clear straight line -> (dir_key, dist, pos)."""
        if not self.avoid_cells:
            return None
        y, x = self.pos()
        g = self.obs["glyphs"]
        k_mem = self.kinds(lv)
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
                if G.KIND[g[p]] == G.OBJECT and nh.glyph_is_object(int(g[p])) and \
                        ord(nh.objclass(nh.glyph_to_obj(int(g[p]))).oc_class) in (nh.WEAPON_CLASS, nh.GEM_CLASS) \
                        and p not in out:
                    out.append(p)
        return out

    def expendables(self):
        """Inventory items worth less than a way through: missiles first, then gems/rocks, spare weapons,
        unworn armor, ordinary tools."""
        if self.handless():
            return []
        out = [(0, l, s) for l, s in self.throwables()]          # missiles, the alternate weapon included
        for it in self.items():
            if it.on_body or it.alternate or it.cursed:
                continue
            letter, ocls, s = it.letter, it.ocls, it.text
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
        for it in self.items():
            letter, ocls = it.letter, it.ocls
            if ocls != nh.WAND_CLASS or self.wand_spent(it):
                continue
            kind = self.wand_kind(it)            # by name, or narrowed by an engraving test (wandid)
            if kind in RAY_WANDS or kind in BEAM_WANDS:
                out.append((letter, kind))
        prio = {"sleep": 0, "striking": 1, "magic missile": 2, "cold": 3, "fire": 4, "lightning": 5}
        return sorted(out, key=lambda t: prio.get(t[1], 9))

    def zap(self, letter, key):
        self.own_zap_turn = self.turn()           # a bouncing ray of ours is not an enemy shooter
        seq0 = self.msg_seq
        wand = next(it for it in self.items() if it.letter == letter)
        if not self.ask("z", "zap"):
            return False
        self.press(letter, expect_prompt=True)
        m = self.message().lower()
        if "direction" in m:
            self.press(key)
        else:
            self.settle()
        msgs = self.text_since(seq0)
        self.note_wand_use(wand, msgs)                   # charges.py
        self.zaps += 1
        self.note_slept(key, msgs)
        return True

    def note_slept(self, key, msgs):
        """Our zap in direction key put these to sleep ("The sleep ray hits the X"): remember the monsters of
        those names on the ray's straight path (asleep)."""
        names = set(SLEEP_HIT_RE.findall(msgs))
        if not names or key not in DIRS:
            return
        lv = self.level()
        y, x = self.pos()
        g = self.obs["glyphs"]
        for sq in ray_squares(y, x, *DIRS[key], n=13):
            if G.KIND[g[sq]] == G.MONSTER and G.monster_name(int(g[sq])) in names:
                self.slept[(lv.key, sq)] = (self.turn(), G.monster_name(int(g[sq])))
                self.zap_stats["slept"] += 1

    def asleep(self, lv, pos):
        """A sleep ray of ours hit the monster at pos less than SLEPT_TURNS ago and it is still there."""
        v = self.slept.get((lv.key, pos)) if pos is not None else None
        if v is None or self.turn() - v[0] >= SLEPT_TURNS:
            return False
        g = int(self.obs["glyphs"][pos])
        return G.KIND[g] == G.MONSTER and G.monster_name(g) == v[1]

    def wand_step(self, lv, hostiles):
        """An attack wand when wand_ev_pairs finds a zap that beats fighting on. Never from Elbereth (attacking
        erases it: engrave.c u_wipe_engr), never sleep at one our sleep ray put down (asleep), never at a monster
        that resists the wand (wand_resisted). Targets asleep come last. None in Sokoban's stealth (soko_stealth)."""
        if self.soko_stealth(lv):
            return False
        wands = self.attack_wands()
        if not wands:
            return False
        if self.pos() in lv.elbereth or self.elb_state is not None:
            self.zap_stats["held_elbereth"] += 1
            return False
        targets = sorted(self.wand_targets(lv, hostiles), key=lambda t: self.asleep(lv, t[2]))
        for (key, d, pos, (dy, dx), name, pwin, gain), letter, kind in self.wand_ev_pairs(hostiles, targets, wands):
            if kind == "sleep" and self.asleep(lv, pos):
                self.zap_stats["held_asleep"] += 1
                continue
            if wand_resisted(kind, name):
                self.zap_stats["held_resist"] += 1
                continue
            if kind in RAY_WANDS:          # statistics only: the ray coming back is in the P(win) of the zap
                self.ray_risk_note(lv, (dy, dx), d, kind, letter, True)
            self.cur_act = "fight"
            self.last_attack_target = pos
            if len(self.wand_pwin_log) < 30:
                self.wand_pwin_log.append((self.turn(), name, d, kind, round(pwin, 2), round(gain, 2), None,
                                           f"{self.bl(nh.NLE_BL_HP)}/{self.bl(nh.NLE_BL_HPMAX)}"))
            return self.zap(letter, key)
        return False

    def prey_mask(self, lv, passable):
        """Prey: the squares next to a hostile in view that we would melee (not never_melee) and beat with
        P(win) > PREY_PWIN -- danger.win_prob of the fight next to it at our HP now -- for explore to walk to;
        once it is next to us the melee step hits it. (A/B hunt_easy 0.95: +1838 [+251, +3343], median
        4645 -> 5089.)"""
        mask = np.zeros_like(passable)
        g = self.obs["glyphs"]
        passive = [(p, n) for p in self.visible_monsters()
                   if self.passive_prey(n := G.monster_name(int(g[p]))) and not self.peaceful_now(lv, p, far=True)]
        for (y, x), name in self.visible_hostiles(lv) + passive:
            if name not in PM_BY_NAME or self.never_melee(name) or self.prey_win(name, (y, x)) <= PREY_PWIN:
                continue
            if self.peaceful_now(lv, (y, x), far=True):
                continue                  # visible_hostiles looks only next to us: a far peaceful one is no prey
                                          # (A/B prey_far_peace: lawful chase turns 447631 -> 87813)
            for dy, dx in NEIGH:
                q = (y + dy, x + dx)
                if 0 <= q[0] < ROWS and 0 <= q[1] < COLS and passable[q]:
                    mask[q] = True
        return mask

    def prey_win(self, name, pos):
        """P(we win a fight with this monster next to us), cached while what it depends on stays the
        same (its name, our HP, max HP, AC, XL, the dungeon level, the weapon in hand); the RNG state restored."""
        weapon = next((it.text for it in self.items() if it.wielded), None)
        key = (name, self.bl(nh.NLE_BL_HP), self.bl(nh.NLE_BL_HPMAX), self.bl(nh.NLE_BL_AC), self.bl(nh.NLE_BL_XP),
               self.bl(nh.NLE_BL_DEPTH), weapon)
        if key not in self.prey_cache:
            state = self.win_rng.bit_generator.state
            self.prey_cache[key] = self.win_prob([(pos, name)])
            self.win_rng.bit_generator.state = state
        return self.prey_cache[key]

    def wand_targets(self, lv, hostiles):
        """Hostiles in a line within 6 we may zap, nearest first (a generator: the peaceful check looks only as
        far as needed)."""
        for key, d, pos, step, name in self.line_targets(lv, max_d=6):
            if d == 1 and pos not in [p for p, _ in hostiles]:
                continue
            if d > 1 and self.peaceful_now(lv, pos, far=True):
                continue
            yield key, d, pos, step, name, None, None

    def wand_ev_pairs(self, hostiles, targets, wands):
        """(target, wand letter, kind) worth a zap, best first. One fight for every choice: the adjacent
        hostiles and every target in line that is coming for us (threats.active_threat), the far ones walking up
        (win_prob approach), each with the ranged attacks we saw it make (threats.ranged_profile). Fighting on (win_prob) against each zap -- a direction and a wand -- as
        our next action, played out in full (zap_opening: every monster on the way, the ray coming back at us), all
        from the same draws (the RNG state restored). A zap only when that fight is at most WAND_PWIN, and only one
        that beats fighting on."""
        fight = list(hostiles) + [(t[2], t[4]) for t in targets
                                  if (t[2], t[4]) not in hostiles and self.active_threat(t[2])]
        if not targets:
            return []
        me = self.pos()
        approach = {p: max(0, max(abs(p[0] - me[0]), abs(p[1] - me[1])) - 1) for p, _ in fight if p is not None}
        ranged = {p: r for p, _ in fight if p is not None and (r := self.ranged_profile(p)) is not None}
        state = self.win_rng.bit_generator.state
        p_fight = self.win_prob(fight, approach=approach, ranged=ranged)
        if p_fight > WAND_PWIN:
            return []
        lv = self.level()
        out, seen = [], {}
        for t in targets:
            for letter, kind in wands:
                if (t[3], letter) not in seen:
                    self.win_rng.bit_generator.state = state
                    seen[(t[3], letter)] = self.win_prob(fight, opening=self.zap_opening(lv, t[3], kind, letter, fight),
                                                         approach=approach, ranged=ranged)
                p = seen[(t[3], letter)]
                if p > p_fight:
                    out.append((p, (t[0], t[1], t[2], t[3], t[4], p_fight, p - p_fight), letter, kind))
        if not out:
            self.zap_stats["held_ev"] += 1
        out.sort(key=lambda e: -e[0])
        return [(tt, letter, kind) for _, tt, letter, kind in out]

    def zap_opening(self, lv, step, kind, letter, fight):
        """win_prob's opening for zapping this wand in direction step: the beam (striking) or ray walked square by
        square over the map we remember (rays.beam_walk / ray_walk); each monster in view on the way is hit by its
        AC (striking: in wand_effect) -- range lost, a reflecting dragon turning the ray back -- and a monster of the
        fight takes the effect (wand_effect); our own square: zap_hit by our AC, then reflection, resistance or
        the ray's damage (6d6, magic missile 2d6) / d(6, 25) turns asleep (zap.c zhitu). Monsters out of view,
        destroyed items and blindness are not counted. A hit on a peaceful monster (a priest, a shopkeeper, the
        watch -- they and their god turn on us) or on our pet counts as the fight lost. fight: the (pos, name) of
        win_prob's fight."""
        y0, x0 = self.pos()
        fight_pos = {pos for pos, _ in fight}
        g = self.obs["glyphs"]
        depth, xl = self.bl(nh.NLE_BL_DEPTH), self.bl(nh.NLE_BL_XP)
        mons = {}
        for (my, mx) in zip(*np.nonzero((G.KIND[g] == G.MONSTER) | (G.KIND[g] == G.PET))):
            pm = permonst_of(g[my, mx])
            pos = (int(my), int(mx))
            if pm is not None and pos != (y0, x0):
                name = G.monster_name(int(g[my, mx]))
                p_eff, dmg = wand_effect(kind, name, depth, xl)
                friend = G.KIND[g[my, mx]] == G.PET or self.peaceful_now(lv, pos, look=False)
                mons[pos] = (zap_hit_prob(pm.ac), any(r in name for r in REFLECTORS), p_eff, dmg, friend)
        terrain = TERRAIN_CODE[self.terrain_glyphs(lv)].copy()
        for (my, mx) in mons:                    # a monster seen in line: the squares up to it are open, not rock
            dy, dx = my - y0, mx - x0
            if dy == 0 or dx == 0 or abs(dy) == abs(dx):
                n = max(abs(dy), abs(dx))
                for i in range(1, n + 1):
                    sq = (y0 + i * np.sign(dy), x0 + i * np.sign(dx))
                    if terrain[sq] == STONE_CODE:
                        terrain[sq] = ROOM_CODE
        mines = bool(lv.key and lv.key[0] == 2)
        it = next((i for i in self.items() if i.letter == letter), None)
        maybe_death = it is not None and "wand of" not in it.text and \
            self.wand_engraved.get(appearance(it.text)) == {"sleep", "death"}
        prot = our_protection(self.role, self.race, [i.text for i in self.items() if i.on_body])
        our_p = zap_hit_prob(self.bl(nh.NLE_BL_AC))
        reflect = "reflection" in prot
        resisted = RAY_RESIST.get("death" if maybe_death else kind) in prot
        our_dmg = dice_pmf(RAY_DICE[kind][0], 6) if kind in RAY_DICE and not resisted else None

        p_charged = (self.wand_p_charged(it) if it is not None else 0.0) * self.our_state()["aim"]   # astray: wasted
        pack = self.pack_profile()

        def opening(rng, alive_at, apply):
            got = {"dmg": 0, "sleep": 0, "blind": False}
            if rng.random() >= p_charged:
                return 0, 0, False                        # "Nothing happens" (or the zap went astray)

            def hit(pos):
                if pos == (y0, x0):
                    if kind == "striking" or rng.random() >= our_p:
                        return (False, False)
                    if reflect:
                        return (True, True)
                    got["blind"] |= kind == "lightning"       # zap.c flashburn, resisted or not
                    got["dmg"] += self.pack_blast(kind, pack, prot, rng)
                    if maybe_death and not resisted:
                        got["dmg"] += 10 ** 4                 # judged as death (ray_risk does the same)
                    elif kind == "sleep" and not resisted:
                        got["sleep"] += int(rng.integers(1, 26, size=6).sum())
                    elif our_dmg is not None:
                        got["dmg"] += int(rng.choice(len(our_dmg), p=our_dmg))
                    return (True, False)
                m = mons.get(pos)
                if m is None or (pos in fight_pos and not alive_at(pos)):
                    return None
                p_hit, refl, p_eff, dmg, friend = m
                if kind == "striking":
                    p_hit, refl = 1.0, False                  # bhitm: its own roll, in p_eff
                if rng.random() >= p_hit:
                    return (False, False)
                if friend:
                    got["dmg"] += 10 ** 6                     # a peaceful / our pet hit: counted as the fight lost
                if refl:
                    return (True, True)
                if pos in fight_pos and rng.random() < p_eff:
                    apply(pos, None if dmg is None else int(rng.choice(len(dmg), p=dmg)))
                return (True, False)

            if kind == "striking":
                beam_walk(terrain, (y0, x0), step, rng, hit)
            else:
                ray_walk(terrain, (y0, x0), step, kind, rng, hit, mines)
            return got["dmg"], got["sleep"], got["blind"]

        return opening

    def ray_risk(self, lv, step, kind, letter):
        """(P(our ray of `kind` fired along `step` comes back and hits us), what that hit would do) -- nhbot.rays.
        A wand the engraving test left as sleep-or-death is judged as death."""
        y, x = self.pos()
        g = self.obs["glyphs"]
        terrain = TERRAIN_CODE[self.terrain_glyphs(lv)]
        mons = {}
        for (my, mx) in zip(*np.nonzero((G.KIND[g] == G.MONSTER) | (G.KIND[g] == G.PET))):
            pm = permonst_of(g[my, mx])
            if pm is not None and (my, mx) != (y, x):
                mons[(int(my), int(mx))] = (pm.ac, G.monster_name(int(g[my, mx])))
        p = self_hit_prob(terrain, (y, x), step, mons, self.bl(nh.NLE_BL_AC), kind,
                          mines=bool(lv.key and lv.key[0] == 2))
        it = next((i for i in self.items() if i.letter == letter), None)
        maybe_death = it is not None and "wand of" not in it.text and \
            self.wand_engraved.get(appearance(it.text)) == {"sleep", "death"}
        worn = [i.text for i in self.items() if i.on_body]
        harm = ray_harm("death" if maybe_death else kind, our_protection(self.role, self.race, worn),
                        self.bl(nh.NLE_BL_HP))
        return p, harm

    def ray_risk_note(self, lv, step, d, kind, letter, safe):
        """Statistics only: the risk of a ray we fire (safe) or hold back."""
        p, harm = self.ray_risk(lv, step, kind, letter)
        ev = "zap" if safe else "held"
        bucket = "0" if p == 0 else "<5%" if p < 0.05 else "<20%" if p < 0.2 else "<50%" if p < 0.5 else ">=50%"
        self.ray_risk_stats[f"{ev} p{bucket}"] += 1
        self.ray_risk_stats[f"{ev} {harm['verdict']}"] += 1
        if len(self.ray_risk_log) < 40:
            self.ray_risk_log.append((self.turn(), ev, kind, d, round(p, 3), harm["verdict"]))

    def msg_combat(self, m):
        """Our hits and kills, being shot at, being attacked by something unseen."""
        self.focus_note(m)
        if re.search(r"You (kill|destroy) ", m):
            self.kill_count += 1
            mk0 = re.search(r"You (?:kill|destroy) (?:the |an? )?(.+?)!", m)
            if mk0:
                self.kill_by[mk0.group(1)] += 1
        mk = re.search(r"You (kill|destroy) (?:the |an? )?(.+?)!", m)
        self.killed = mk.group(2) if mk else None      # what this message says we killed (thieves read it too)
        if mk and self.last_attack_target:
            self.kill_log.append((self.turn(), mk.group(2), self.last_attack_target, self.cur_key))
            lvk = self.levels.get(self.cur_key)
            if lvk is not None:
                lvk.stationary.pop(self.last_attack_target, None)   # killed it (a missile at a mold)
            if lvk is not None and mk.group(2) in CARRIERS:
                lvk.kill_piles.add(self.last_attack_target)    # what it carried lies under its corpse (pickup.py)
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
