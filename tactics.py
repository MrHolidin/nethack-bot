"""Staircase tactics, v2 (case analysis in chat).

Mechanics (NetHack wiki, "Follower"): when you change level, an adjacent monster follows
only if it is a pet, a peaceful, an angry shopkeeper, or has M2_STALK (Z zombies, imps,
demons, mercenaries, A/T/V/W, ...) and is not fleeing. Jackals, ants, bats, rothes, cats,
dogs, jaguars... do NOT follow. So a staircase is an escape hatch from non-stalkers.

Policy:
  1. ESCAPE: standing on stairs, losing (HP < flee_hp, prayer unavailable), every adjacent
     hostile is a non-stalker -> take the stairs (prefer known levels; DL1 up is forbidden).
  2. FAR SIDE: rest on the arrival staircase until recover_hp. If a hostile shows up while
     still weak, hop back (at most 2 hops per incident). Then return.
  3. HURT, NOTHING AROUND: walk to the nearest staircase (<= 25 steps) and rest there, so a
     fight that starts while we are weak starts on an escape hatch.
  4. THREAT IN VIEW, NOT YET ADJACENT: move toward stairs only if we get there first.
"""
import numpy as np
import nle.nethack as nh

import glyphs as G

ROWS, COLS = 21, 79
UPSTAIR_GLYPH = nh.GLYPH_CMAP_OFF + 23
DOWNSTAIR_GLYPH = nh.GLYPH_CMAP_OFF + 24
M2_STALK = 0x01000000
USUALLY_PEACEFUL = {"shopkeeper", "watchman", "watch captain", "aligned priest", "high priest",
                    "guard", "Oracle", "prisoner"}


def permonst_of(g):
    m = nh.glyph_to_mon(int(g))
    return nh.permonst(m) if 0 <= m < nh.NUMMONS else None


class TacticsMixin:
    def tactics_init(self):
        self.recovering = None        # dict(back=key, hops=n, t0=turn)
        self.escape_cooldown = -1
        self.fight_hp = []
        self.escape_log = []
        self.flees = 0
        self.stair_runs = 0
        self.stair_rests = 0
        self.last_stair_dir = None
        self.stair_wait = 0

    # ---------------------------------------------------------- helpers
    def threat(self, g):
        pm = permonst_of(g)
        return 0 if pm is None else pm.difficulty - self.bl(nh.NLE_BL_XP)

    def speed(self, g):
        pm = permonst_of(g)
        return pm.mmove if pm is not None else 12

    def is_stalker(self, g):
        pm = permonst_of(g)
        return bool(pm.mflags2 & M2_STALK) if pm is not None else False

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

    def turns_to_die(self, lv, hostiles):
        g = self.obs["glyphs"]
        dmg = sum(self.est_dmg(g[p], n) for p, n in hostiles)
        # observed HP loss rate over the last few turns of this fight
        t, hp = self.turn(), self.bl(nh.NLE_BL_HP)
        old = [(tt, hh) for tt, hh in self.fight_hp if 1 <= t - tt <= 3]
        if old:
            tt, hh = old[0]
            dmg = max(dmg, (hh - hp) / (t - tt))
        return hp / max(dmg, 0.1)

    def stairs_kind_here(self, lv):
        k = G.KIND[lv.under[self.pos()]]
        return k if k in (G.UPSTAIR, G.DOWNSTAIR) else None

    def note_stair_arrival(self, lv, arrived):
        if arrived and self.last_stair_dir:
            lv.under[self.pos()] = UPSTAIR_GLYPH if self.last_stair_dir == ">" else DOWNSTAIR_GLYPH
        self.last_stair_dir = None

    def can_use_stairs(self, lv, kind):
        if kind == G.UPSTAIR and self.bl(nh.NLE_BL_DEPTH) == 1:
            return False
        if kind == G.DOWNSTAIR and self.pos() in lv.avoid_down:
            return False
        return True

    def stairs_mask(self, lv, k_mem):
        m = (k_mem == G.UPSTAIR) | (k_mem == G.DOWNSTAIR)
        for p in lv.avoid_down:
            m[p] = False
        if self.bl(nh.NLE_BL_DEPTH) == 1:
            m &= k_mem != G.UPSTAIR
        return m

    def path_to_stairs(self, lv, max_cost):
        k_mem, k_live = self.kind_grid(lv)
        passable = self.passable_grid(lv, k_mem, k_live)
        stairs = self.stairs_mask(lv, k_mem)
        if not stairs.any():
            return None, None
        start = self.pos()
        dist, prev, reached = self.dijkstra(lv, k_mem, k_live, passable, start, stairs, max_cost=max_cost)
        if reached is None:
            return None, None
        return int(dist[reached]), self.first_step(prev, start, reached)

    def take_stairs(self, lv, kind, hops):
        hp, maxhp = self.bl(nh.NLE_BL_HP), self.bl(nh.NLE_BL_HPMAX)
        names = [n for _, n in self.adjacent_hostiles(lv)]
        self.escape_log.append({"t": self.turn(), "hp": hp, "max": maxhp, "hops": hops,
                                "dir": "up" if kind == G.UPSTAIR else "down", "adj": names})
        key = "<" if kind == G.UPSTAIR else ">"
        back = ">" if key == "<" else "<"
        self.flees += 1
        self.recovering = {"back": back, "hops": hops, "t0": self.turn(), "from": lv.key}
        self.press(key)

    def rest_here(self):
        self.stair_rests += 1
        self.press("2"); self.press("0"); self.press("s")

    # ---------------------------------------------------------- main
    def tactical_step(self, lv, hostiles):
        hp, maxhp = self.bl(nh.NLE_BL_HP), self.bl(nh.NLE_BL_HPMAX)
        if hostiles:
            self.fight_hp.append((self.turn(), hp))
            self.fight_hp = self.fight_hp[-6:]
        else:
            self.fight_hp = []
        here = self.stairs_kind_here(lv)
        g = self.obs["glyphs"]
        weak = hp < maxhp * self.flee_hp and not self.can_pray()
        stalkers = [p for p, n in hostiles if n != "invisible" and self.is_stalker(g[p])]

        # 2) far side of an escape
        rec = self.recovering
        if rec is not None:
            if lv.key == rec["from"] or here is None:
                self.recovering = None            # moved on, fell through, or teleported
            elif hostiles:
                if rec["hops"] == 0 and not stalkers and not self.can_pray() and \
                        self.turns_to_die(lv, hostiles) < self.flee_turns and self.can_use_stairs(lv, here):
                    self.take_stairs(lv, here, 1)
                    return True
                self.recovering = None            # fight it here
                self.escape_cooldown = self.turn() + 30
            elif hp >= maxhp * self.recover_hp or self.turn() - rec["t0"] > 1000 \
                    or self.bl(nh.NLE_BL_HUNGER) >= 3:
                back = rec["back"]
                self.recovering = None
                if self.escape_log:
                    self.escape_log[-1]["returned_hp"] = hp
                self.press(back)
                return True
            else:
                self.rest_here()
                return True

        # 1) escape from a losing fight
        if hostiles and here is not None and not stalkers and not self.can_pray() \
                and self.turn() >= self.escape_cooldown and self.can_use_stairs(lv, here) \
                and self.turns_to_die(lv, hostiles) < self.flee_turns:
            self.take_stairs(lv, here, 0)
            return True

        # stand still on stairs while hurt: let it come, keep the hatch under us
        visible = [(p, n) for p, n in self.visible_hostiles(lv) if n not in USUALLY_PEACEFUL]
        if here is not None and hp < maxhp * self.recover_hp and not self.can_pray() and not hostiles:
            if not visible:
                self.rest_here()
                return True
            if self.stair_wait < 10:
                self.stair_wait += 1
                self.press("s")
                return True
        if here is None:
            self.stair_wait = 0

        # 3) hurt and nothing around: go rest on the nearest stairs
        if not hostiles and not visible and hp < maxhp * self.flee_hp and not self.can_pray() and here is None:
            d, step = self.path_to_stairs(lv, max_cost=25)
            if step is not None:
                self.stair_runs += 1
                self.move(step)
                return True

        # 4) threat approaching: reach stairs first if we can
        if here is None and visible:
            danger = [(p, self.speed(g[p])) for p, n in visible
                      if self.threat(g[p]) >= self.danger_k or (weak and n != "invisible")]
            if danger:
                d, step = self.path_to_stairs(lv, max_cost=20)
                if step is not None:
                    y0, x0 = self.pos()
                    if hostiles:
                        ok = d <= 1
                    else:
                        ok = all((max(abs(p[0] - y0), abs(p[1] - x0)) - 1) * 12.0 / max(sp, 1) >= d
                                 for p, sp in danger)
                    if ok:
                        self.stair_runs += 1
                        self.move(step)
                        return True
        return False
