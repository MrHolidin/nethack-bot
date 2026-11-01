"""Monster danger estimates and staircase memory.

(The staircase escape tactics that used to live here were removed: off by default, never used.)
"""
import nle.nethack as nh

import glyphs as G

UPSTAIR_GLYPH = nh.GLYPH_CMAP_OFF + 23
DOWNSTAIR_GLYPH = nh.GLYPH_CMAP_OFF + 24


def permonst_of(g):
    m = nh.glyph_to_mon(int(g))
    return nh.permonst(m) if 0 <= m < nh.NUMMONS else None


class TacticsMixin:
    def tactics_init(self):
        self.last_stair_dir = None

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

    def stairs_kind_here(self, lv):
        k = G.KIND[lv.under[self.pos()]]
        return k if k in (G.UPSTAIR, G.DOWNSTAIR) else None

    def note_stair_arrival(self, lv, arrived):
        if arrived and self.last_stair_dir:
            lv.under[self.pos()] = UPSTAIR_GLYPH if self.last_stair_dir == ">" else DOWNSTAIR_GLYPH
        self.last_stair_dir = None
