"""Who is around: hostile / peaceful monsters next to us and in view, threat gates for
housekeeping, monsters we never melee, straight-line targets, and what blindness / hallucination
leave us able to tell."""
import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import COLS, DELTA2KEY, NEIGH, ROWS
from nhbot.monattacks import ATTACKS
from nhbot.monsters import ALWAYS_AVOID, NEVER_MELEE, PASSIVE_DMG, PASSIVE_ONLY, PM_BY_NAME, THIEVES, USUALLY_PEACEFUL, permonst_of

# no active attack: only passive ones (molds, jellies, floating eye, acid blob), an explosion when killed
# (gas spore) or none at all (shrieker). No monster without one can move (mmove 0 for all that can't).
NO_ACTIVE_ATTACK = {nh.permonst(i).mname for i in range(nh.NUMMONS)
                    if all(a[0] in ("NONE", "BOOM") for a in ATTACKS[i])}


class PerceptionMixin:
    def perception_init(self):
        self.far_peaceful = {}         # (level, glyph, pos) -> (peaceful, turn)
        self.farlooks = 0              # ';' looks that is_peaceful made

    def is_actively_dangerous(self, lv, pos):
        """Can the monster at pos hurt us of its own accord? False if it has no active attack (NO_ACTIVE_ATTACK)
        or is peaceful: its glyph answered 'Really attack?' on this level, or a farlook says so (cached 5 turns
        per monster and square). An unseen 'I': True."""
        g = int(self.obs["glyphs"][pos])
        k = G.KIND[g]
        if k == G.INVIS:
            return True
        if k != G.MONSTER or G.monster_name(g) in NO_ACTIVE_ATTACK or g in lv.peaceful:
            return False
        return not self.is_peaceful(pos)

    def visible_hostiles(self, lv):
        if self.opts.danger_check:
            return [(p, G.monster_name(int(self.obs["glyphs"][p]))) for p in self.visible_monsters()
                    if self.is_actively_dangerous(lv, p)]
        g = self.obs["glyphs"]
        ys, xs = np.nonzero(G.KIND[g] == G.MONSTER)
        py, px = self.pos()
        res = []
        for yy, xx in zip(ys, xs):
            if (yy, xx) == (py, px):
                continue
            gg = int(g[yy, xx])
            if gg in lv.peaceful:
                continue
            res.append(((int(yy), int(xx)), G.monster_name(gg)))
        return res

    def visible_monsters(self):
        """Squares of the monsters on screen other than us."""
        g = self.obs["glyphs"]
        ys, xs = np.nonzero(G.KIND[g] == G.MONSTER)
        me = self.pos()
        return [(int(a), int(b)) for a, b in zip(ys, xs) if (a, b) != me]

    def adjacent_hostiles(self, lv):
        y, x = self.pos()
        g = self.obs["glyphs"]
        out = []
        self.avoid_cells = []
        for yy in range(max(0, y - 7), min(ROWS, y + 8)):
            for xx in range(max(0, x - 7), min(COLS, x + 8)):
                k = G.KIND[g[yy, xx]]
                if k == G.MONSTER:
                    name = G.monster_name(g[yy, xx])
                    if self.never_melee(name) and not (lv.desperate and name not in self.always_avoid()) \
                            and not self.spore_ok(name):
                        self.avoid_cells.append((yy, xx))
        for dy, dx in NEIGH:
            ny, nx = y + dy, x + dx
            if not (0 <= ny < ROWS and 0 <= nx < COLS):
                continue
            gg = int(g[ny, nx])
            k = G.KIND[gg]
            if k == G.MONSTER and self.opts.danger_check:
                name = G.monster_name(gg)
                if self.never_melee(name) and not (lv.desperate and name not in self.always_avoid()
                                                and self.bl(nh.NLE_BL_HP) * 10 >= self.bl(nh.NLE_BL_HPMAX) * 9) \
                        and not self.spore_ok(name):
                    continue
                if self.is_actively_dangerous(lv, (ny, nx)):
                    out.append(((ny, nx), name))
            elif k == G.MONSTER and gg not in lv.peaceful:
                name = G.monster_name(gg)
                if self.never_melee(name) and not (lv.desperate and name not in self.always_avoid()
                                                and self.bl(nh.NLE_BL_HP) * 10 >= self.bl(nh.NLE_BL_HPMAX) * 9) \
                        and not self.spore_ok(name):
                    continue
                if self.is_peaceful((ny, nx)):
                    continue
                out.append(((ny, nx), name))
            elif k == G.INVIS and (ny, nx):
                out.append(((ny, nx), "invisible"))
        return out

    def view_threats(self, lv):
        """Visible hostiles that should stop housekeeping (pickups, equipment, shopping). The SAME list
        gates those steps and the explore goals they consume."""
        vis = self.visible_hostiles(lv)
        if self.opts.danger_check:
            return vis                       # no active attack / peaceful: all in is_actively_dangerous
        vis = [v for v in vis if v[1] != "shopkeeper"]         # a peaceful shopkeeper is not a threat
        # a monster that cannot move (molds, lichens' kin with speed 0) only matters next to us; otherwise
        # stepping in and out of its line of sight flips this gate and two goals take turns
        y, x = self.pos()
        vis = [(p, n) for p, n in vis if max(abs(p[0] - y), abs(p[1] - x)) <= 1
               or n not in PM_BY_NAME or PM_BY_NAME[n].mmove > 0]
        # no active attack at all (molds, jellies, floating eye, shrieker): harmless unless we hit it, and
        # we never do. Counting it only when adjacent made the gate flip on the square next to it (an item
        # beside a brown mold was a goal from 2 squares away and forbidden on arrival).
        vis = [(p, n) for p, n in vis if n not in PASSIVE_ONLY]
        return vis

    def items_gate(self, lv):
        """May item goals be pursued / piles inspected now? Not in combat: nothing in melee range and not shot
        at in the last 5 turns. Goals and the steps that consume them use this same test."""
        return not self.adjacent_hostiles(lv) and self.turn() - self.last_shot_turn > 5

    def is_peaceful(self, pos):
        g = int(self.obs["glyphs"][pos])
        if G.KIND[g] != G.MONSTER:
            return False
        ck = (self.cur_key, g, pos)
        hit = self.hostile_cache.get(ck)
        if hit is not None and self.turn() - hit[1] <= 5:
            return hit[0]
        desc = self.describe_at(pos)
        self.farlooks += 1
        peaceful = "peaceful" in desc or "tame" in desc
        self.hostile_cache[ck] = (peaceful, self.turn())
        if peaceful:
            self.peaceful_seen += 1
        return peaceful

    def peaceful_far(self, lv, pos, dirkey, d):
        g = int(self.obs["glyphs"][pos])
        ck = (lv.key, g, pos)
        hit = self.far_peaceful.get(ck)
        if hit is not None and self.turn() - hit[1] <= 5:
            return hit[0]
        desc = self.describe_far(dirkey, d)
        res = ("peaceful" in desc) or ("tame" in desc) or not desc
        self.far_peaceful[ck] = (res, self.turn())
        return res

    def mark_peaceful_target(self):
        t = self.last_attack_target
        if t is None:
            return
        g = int(self.obs["glyphs"][t])
        lv = self.levels.get(self.cur_key)
        if lv is not None:
            lv.peaceful.add(g)

    def line_targets(self, lv, max_d=6):
        """Hostile-looking monsters in a clear straight line: [(dirkey, d, pos, step)]."""
        y, x = self.pos()
        g = self.obs["glyphs"]
        k_mem = G.KIND[lv.under]
        out = []
        for (dy, dx), key in DELTA2KEY.items():
            for i in range(1, max_d + 1):
                yy, xx = y + i * dy, x + i * dx
                if not (0 <= yy < ROWS and 0 <= xx < COLS):
                    break
                k = G.KIND[g[yy, xx]]
                if k == G.MONSTER:
                    name = G.monster_name(int(g[yy, xx]))
                    if name not in USUALLY_PEACEFUL and int(g[yy, xx]) not in lv.peaceful:
                        out.append((key, i, (yy, xx), (dy, dx), name))
                    break
                if k in (G.PET, G.BOULDER) or not G.PASSABLE[k_mem[yy, xx]] and k_mem[yy, xx] != G.UNKNOWN:
                    break
        return sorted(out, key=lambda t: t[1])

    def thieves_visible(self, lv):
        out = []
        for p, name in self.visible_hostiles(lv):
            if name in THIEVES:
                out.append((p, name))
        return out

    def shopkeeper_in_view(self):
        g = self.obs["glyphs"]
        ys, xs = np.nonzero(G.KIND[g] == G.MONSTER)
        return any(G.monster_name(int(g[a, c])) == "shopkeeper" for a, c in zip(ys, xs))

    def law_nearby(self):
        g = self.obs["glyphs"]
        ys, xs = np.nonzero(G.KIND[g] == G.MONSTER)
        for yy, xx in zip(ys, xs):
            n = G.monster_name(int(g[yy, xx]))
            if n in ("watchman", "watch captain", "shopkeeper"):
                return True
        return False

    def town_folk_visible(self):
        """Minetown's watch, temple priest or shopkeepers in view (an unlit Minetown may hide its altar)."""
        if int(self.last_bl[nh.NLE_BL_CONDITION]) & nh.BL_MASK_HALLU:
            return False
        g = self.obs["glyphs"]
        ys, xs = np.nonzero(G.KIND[g] == G.MONSTER)
        return any(G.monster_name(int(g[yy, xx])) in ("watchman", "watch captain", "aligned priest", "shopkeeper")
                   for yy, xx in zip(ys, xs))

    def always_avoid(self):
        s = ALWAYS_AVOID
        if not int(self.last_bl[nh.NLE_BL_CONDITION]) & nh.BL_MASK_BLIND:
            s = s | {"floating eye"}          # its passive gaze paralyses for up to ~127 turns
        return s

    def never_melee(self, name):
        """Don't hit what has only a passive attack (it never hurts us otherwise); desperate (stuck) still may."""
        if name in ("cockatrice", "chickatrice") and any("weapon in hand" in s for _, _, s in self.inventory()):
            return False       # hitting it with a wielded weapon is safe; standing by while it touches us is not
        return name in NEVER_MELEE or name in PASSIVE_DMG

    def spore_ok(self, name):
        # gas spore explosion is 4d6 (max 24): meleeing it is safe above that
        return name == "gas spore" and self.bl(nh.NLE_BL_HP) >= 25

    def mon_level(self, pos):
        g = int(self.obs["glyphs"][pos])
        m = nh.glyph_to_mon(g)
        return nh.permonst(m).mlevel if 0 <= m < nh.NUMMONS else 0

    def threat(self, g):
        pm = permonst_of(g)
        return 0 if pm is None else pm.difficulty - self.bl(nh.NLE_BL_XP)

    def est_dmg(self, g, name=None):
        """Rough expected damage per player turn from one adjacent monster.
        to-hit from the wiki formula d20 < 10 + AC + level; per-hit damage ~ 1 + 1.5*level
        (attack tables are not exposed by NLE, so this is a level-based proxy)."""
        pm = permonst_of(g)
        if pm is None or name == "invisible":
            return 3.0
        lvl = pm.mlevel
        ac = self.bl(nh.NLE_BL_AC)
        hit = min(max((10 + ac + lvl - 1) / 20.0, 0.05), 1.0)
        return (1.0 + 1.5 * lvl) * hit * max(pm.mmove, 1) / 12.0

    def worth_special(self, pos, name):
        """Is this target worth a charge / energy / a flash?"""
        g = self.obs["glyphs"][pos]
        hp, maxhp = self.bl(nh.NLE_BL_HP), self.bl(nh.NLE_BL_HPMAX)
        if hp < maxhp * 0.5:
            return True
        return self.est_dmg(g, name) >= 2.0 or self.threat(g) >= 1

    def blind_attackers(self, lv, hostiles):
        """blind_strike: while blind, an adjacent 'I' is only a target if it attacked us. mhitu.c marks the square
        of an unseen attacker with 'I' in the same turn as its "It hits!"; 'I' also appears when we bump into or
        search out a monster that did nothing (61969: a watchman; 61057). So: an attack message this turn and a
        new 'I' next to us -> that one; an attack and a single 'I' next to us -> that one; otherwise unknown,
        don't hit (blind_wait then keeps us still)."""
        cur = {p for p, n in hostiles if n == "invisible"}
        attacked, self.it_attacked = self.it_attacked, False
        prev = self.prev_inv
        known = self.inv_attackers
        if attacked:
            new = cur - prev
            known |= new if new else (cur if len(cur) == 1 else set())
        known &= cur
        self.prev_inv, self.inv_attackers = cur, known
        if not int(self.last_bl[nh.NLE_BL_CONDITION]) & nh.BL_MASK_BLIND or not self.strike_scope_ok(lv):
            return hostiles
        out = [(p, n) for p, n in hostiles if n != "invisible" or p in known]
        if len(out) < len(hostiles):
            self.blind_held += 1
        return out

    def hallu_attackers(self, lv, hostiles):
        """hallu_strike: while hallucinating, looks and names are random, so peacefuls can't be told apart
        (61520 hit a shopkeeper, 61969 two peacefuls). Hit only a square whose monster attacked us: a melee
        attack message this turn with exactly one monster next to us marks that square; it stays a target
        while a monster stands on it. Never one inside a shop (the shopkeeper)."""
        g = self.obs["glyphs"]
        y, x = self.pos()
        adj = [(y + dy, x + dx) for dy, dx in NEIGH if 0 <= y + dy < ROWS and 0 <= x + dx < COLS
               and nh.glyph_is_monster(int(g[y + dy, x + dx]))]
        attacked, self.melee_on_us = self.melee_on_us, False
        known = self.hallu_targets
        if attacked and len(adj) == 1:
            known.add(adj[0])
        known &= set(adj)
        self.hallu_targets = known
        if not int(self.last_bl[nh.NLE_BL_CONDITION]) & nh.BL_MASK_HALLU or not self.strike_scope_ok(lv):
            return hostiles
        out = [(p, n) for p, n in hostiles if p in known and not lv.shop[p]]
        if len(out) < len(hostiles):
            self.hallu_held += 1
        return out

    def hallu_blind_ranged(self):
        """hallu_strike: no throwing / zapping / hunting at range while hallucinating -- the target can't be told
        from a peaceful (61520 threw a dagger into one)."""
        return bool(int(self.last_bl[nh.NLE_BL_CONDITION]) & nh.BL_MASK_HALLU
                    and self.strike_scope_ok(self.levels.get(self.cur_key)))

    def strike_scope_ok(self, lv):
        """blind_strike / hallu_strike only in Minetown -- a Mines level with an altar, a fountain or
        a shop (filler Mines levels have none), where the peaceful watch, priest and shopkeepers are."""
        return self.is_minetown(lv)
