"""Fight-or-flee tactics built around staircases ("stair dance").

* threat of a monster = its generation difficulty - our XL (difficulty/speed come from
  the monster's species, which a human also knows from symbol/colour/farlook).
* dangerous monster in view (threat >= danger_k): walk to the nearest staircase if it is
  close and the monster is not faster than us, and fight standing on it.
* losing on a staircase (HP < flee_hp, no prayer): take the stairs. Only monsters adjacent
  at that moment can follow. Rest on the other side to recover_hp, then come back.
"""
import numpy as np
import nle.nethack as nh

import glyphs as G

ROWS, COLS = 21, 79
UPSTAIR_GLYPH = nh.GLYPH_CMAP_OFF + 23
DOWNSTAIR_GLYPH = nh.GLYPH_CMAP_OFF + 24
USUALLY_PEACEFUL = {"shopkeeper", "watchman", "watch captain", "aligned priest", "high priest",
                    "guard", "Oracle", "prisoner"}


def permonst_of(g):
    m = nh.glyph_to_mon(int(g))
    return nh.permonst(m) if 0 <= m < nh.NUMMONS else None


class TacticsMixin:
    def tactics_init(self):
        self.recovering = None        # (level key, key to press to go back, started turn)
        self.flees = 0
        self.stair_runs = 0
        self.last_stair_dir = None
        self.stair_wait = 0

    def threat(self, g):
        pm = permonst_of(g)
        if pm is None:
            return 0
        return pm.difficulty - self.bl(nh.NLE_BL_XP)

    def speed(self, g):
        pm = permonst_of(g)
        return pm.mmove if pm is not None else 12

    def stairs_kind_here(self, lv):
        k = G.KIND[lv.under[self.pos()]]
        return k if k in (G.UPSTAIR, G.DOWNSTAIR) else None

    def note_stair_arrival(self, lv, arrived):
        """Called on level change: we stand on the opposite staircase."""
        if arrived and self.last_stair_dir:
            lv.under[self.pos()] = UPSTAIR_GLYPH if self.last_stair_dir == ">" else DOWNSTAIR_GLYPH
        self.last_stair_dir = None

    def can_use_stairs(self, lv, kind):
        if kind == G.UPSTAIR and self.bl(nh.NLE_BL_DEPTH) == 1:
            return False                       # leaving the dungeon ends the game
        if kind == G.DOWNSTAIR and self.pos() in lv.avoid_down:
            return False
        return True

    def tactical_step(self, lv, hostiles):
        """Returns True if it used the turn."""
        hp, maxhp = self.bl(nh.NLE_BL_HP), self.bl(nh.NLE_BL_HPMAX)
        t = self.turn()
        here = self.stairs_kind_here(lv)

        # 1) recovering on the far side of the stairs
        if self.recovering and not hostiles:
            key, back, t0 = self.recovering
            if lv.key != key and here is not None and (hp >= maxhp * self.recover_hp or t - t0 > 800):
                self.recovering = None
                self.press(back)
                return True
            if lv.key == key or here is None:
                self.recovering = None         # we already moved on / fell somewhere
            else:
                vis = [v for v in self.visible_hostiles(lv) if v[1] not in USUALLY_PEACEFUL]
                if not vis and self.bl(nh.NLE_BL_HUNGER) < 3:
                    self.press("2"); self.press("0"); self.press("s")
                    return True

        # 2) losing a fight while standing on stairs -> leave
        if hostiles and here is not None and self.can_use_stairs(lv, here):
            worst = max(self.threat(self.obs["glyphs"][p]) for p, _ in hostiles)
            losing = hp < maxhp * self.flee_hp or (worst >= self.danger_k + 3 and hp < maxhp * 0.7)
            if losing and not self.can_pray():
                key = "<" if here == G.UPSTAIR else ">"
                back = ">" if key == "<" else "<"
                self.flees += 1
                self.recovering = (lv.key, back, t)
                self.press(key)
                return True

        # 3) danger in view (or losing a fight) -> get onto stairs first
        g = self.obs["glyphs"]
        losing = hp < maxhp * self.flee_hp and not self.can_pray()
        danger = []
        for p, name in self.visible_hostiles(lv):
            if name in USUALLY_PEACEFUL:
                continue
            th = self.threat(g[p])
            if th >= self.danger_k or (losing and max(abs(p[0] - self.pos()[0]), abs(p[1] - self.pos()[1])) <= 2):
                danger.append((p, th, self.speed(g[p])))
        if not danger:
            self.stair_wait = 0
            return False
        if here is not None and self.can_use_stairs(lv, here):
            if not hostiles and self.stair_wait < 8:
                self.stair_wait += 1
                self.press("s")                # let it come to us
                return True
            return False                       # fight on the stairs (normal melee)
        k_mem, k_live = self.kind_grid(lv)
        passable = self.passable_grid(lv, k_mem, k_live)
        stairs = (k_mem == G.UPSTAIR) | (k_mem == G.DOWNSTAIR)
        for p in lv.avoid_down:
            stairs[p] = False
        if self.bl(nh.NLE_BL_DEPTH) == 1:
            stairs &= k_mem != G.UPSTAIR
        if not stairs.any():
            return False
        start = self.pos()
        dist, prev, reached = self.dijkstra(lv, k_mem, k_live, passable, start, stairs, max_cost=40)
        if reached is None:
            return False
        # go only if we reach the stairs before the fastest threat reaches us (12 = our speed)
        y0, x0 = start
        d_stairs = int(dist[reached])
        if d_stairs > 15:
            return False
        if not hostiles:
            for p, _, sp in danger:
                d_mon = max(abs(p[0] - y0), abs(p[1] - x0)) - 1
                if d_mon * 12.0 / max(sp, 1) < d_stairs:
                    return False
        elif d_stairs > 3:
            return False
        step = self.first_step(prev, start, reached)
        if step is None:
            return False
        self.stair_runs += 1
        self.move(step)
        return True
