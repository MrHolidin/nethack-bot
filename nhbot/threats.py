"""Which monsters in view are coming for us (wand_ev's fight): tracks of the monsters on screen from tick to tick.

A monster is an active threat when it stands next to us, has ever attacked us (a message names it: "The X hits!",
"The X misses!", "The X zaps a wand!", ... -- the nearest one of that name in view), or its last move, at most
ACTIVE_RECENT turns ago, brought it closer to us (the distance from where we stand now). The others in view are
not in the fight: asleep, busy, wandering, or not after us.

Tracks match the monsters on screen of the last ticks by name: the nearest track of the same name within
2 squares plus one per turn unseen. Only kept while wand_ev is on (the tracker reads the screen, no looks).
"""
import re

import numpy as np

from nhbot import glyphs as G

ACTIVE_RECENT = 3            # turns: a move toward us this lately counts
TRACK_FORGET = 10            # turns a track is kept unseen
ATTACK_RE = re.compile(r"\bThe ([a-zA-Z' -]+?) (?:hits|misses|bites|stings|kicks|butts|touches|claws|thrusts|swings|"
                       r"shoots|throws|zaps|breathes|casts|spits|gazes|engulfs|squeezes|lashes|tentacles|"
                       r"just misses|strikes)\b")


def _dist(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


class ThreatMixin:
    def threats_init(self):
        self.mon_tracks = []         # dicts: name, pos, seen, closer (turn), attacked (turn)
        self.tracks_key = None       # the level the tracks are on

    def threat_track(self):
        """Match the monsters on screen (not pets) to the tracks; note who came closer by its own move."""
        t, me = self.turn(), self.pos()
        g = self.obs["glyphs"]
        if self.tracks_key != self.cur_key:
            self.mon_tracks, self.tracks_key = [], self.cur_key
        tracks = [tr for tr in self.mon_tracks if t - tr["seen"] <= TRACK_FORGET]
        free = list(tracks)
        for y, x in zip(*np.nonzero(G.KIND[g] == G.MONSTER)):
            p = (int(y), int(x))
            if p == me:
                continue
            n = G.monster_name(int(g[p]))
            cand = [tr for tr in free if tr["name"] == n and _dist(tr["pos"], p) <= 2 + (t - tr["seen"])]
            if cand:
                tr = min(cand, key=lambda r: _dist(r["pos"], p))
                free.remove(tr)
                if tr["pos"] != p:
                    tr["closer"] = t if _dist(p, me) < _dist(tr["pos"], me) else None
                tr["pos"], tr["seen"] = p, t
            else:
                tracks.append({"name": n, "pos": p, "seen": t, "closer": None, "attacked": None})
        self.mon_tracks = tracks

    def msg_threat(self, m):
        """A message naming a monster attacking us: the nearest track of that name in view attacked."""
        if not self.mon_tracks:
            return
        t, me = self.turn(), self.pos()
        for name in ATTACK_RE.findall(m):
            seen = [tr for tr in self.mon_tracks if tr["name"] == name and t - tr["seen"] <= 1]
            if seen:
                min(seen, key=lambda r: _dist(r["pos"], me))["attacked"] = t

    def active_threat(self, pos):
        """The monster at pos is coming for us (module docstring)."""
        t, me = self.turn(), self.pos()
        if _dist(pos, me) <= 1:
            return True
        tr = next((r for r in self.mon_tracks if r["pos"] == pos and r["seen"] == t), None)
        return tr is not None and (tr["attacked"] is not None
                                   or (tr["closer"] is not None and t - tr["closer"] <= ACTIVE_RECENT))
