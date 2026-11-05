"""Which monsters in view are coming for us (the fight of combat.wand_ev_pairs): tracks of the monsters on screen from tick to tick.

A monster is an active threat when it stands next to us, came into view this turn close enough to hit us next
turn (its moves a turn, mmove / 12 rounded up, reach the square next to us), has ever attacked us (a message names it: "The X hits!",
"The X misses!", "The X zaps a wand!", ... -- the nearest one of that name in view), or its last move, at most
ACTIVE_RECENT turns ago, brought it closer to us (the distance from where we stand now). The others in view are
not in the fight: asleep, busy, wandering, or not after us.

Tracks match the monsters on screen of the last ticks by name: the nearest track of the same name within
2 squares plus one per turn unseen (the tracker reads the screen, no looks).

A track also keeps the ranged attacks we saw that monster make (ranged_profile, for win_prob's walk_fight, which
gives it unlimited use of them):
  wand      "The X zaps a wand of K!", or "zaps a <look> wand!" followed this turn by its effect ("The bolt of fire
            ...", "The sleep ray ...", "The wand hits you!", "Boing!");
  missiles  "The X shoots / throws 2 orcish arrows!": the kind, the volley sizes seen, poisoned or not;
  breath    "The X breathes ...": its breath attack (monattacks).
"""
import re

import numpy as np

from nhbot import glyphs as G
from nhbot.monsters import PM_BY_NAME

ACTIVE_RECENT = 3            # turns: a move toward us this lately counts
TRACK_FORGET = 10            # turns a track is kept unseen
WAND_KINDS = ("striking", "magic missile", "fire", "cold", "sleep", "lightning", "death")
ZAP_RE = re.compile(r"\bThe ([a-zA-Z' -]+?) zaps (?:an? |the )?([a-z' -]*?wand(?: of [a-z ]+)?)!")
RAY_SEEN = (("sleep ray", "sleep"), ("bolt of fire", "fire"), ("bolt of cold", "cold"),
            ("bolt of lightning", "lightning"), ("magic missile", "magic missile"), ("death ray", "death"),
            ("The wand hits you", "striking"), ("The wand misses you", "striking"), ("Boing!", "striking"))
SHOOT_RE = re.compile(r"\bThe ([a-zA-Z' -]+?) (?:shoots|throws) (\d+|an?|the) ([a-z' -]+?)!")
BREATH_RE = re.compile(r"\bThe ([a-zA-Z' -]+?) breathes ")
ATTACK_RE = re.compile(r"\bThe ([a-zA-Z' -]+?) (?:hits|misses|bites|stings|kicks|butts|touches|claws|thrusts|swings|"
                       r"shoots|throws|zaps|breathes|casts|spits|gazes|engulfs|squeezes|lashes|tentacles|"
                       r"just misses|strikes)\b")


def singular(what):
    """'2 orcish arrows' kind -> 'orcish arrow' (knives -> knife)."""
    if what.endswith("ves"):
        return what[:-3] + "fe"
    return what[:-1] if what.endswith("s") else what


def _dist(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


class ThreatMixin:
    def threats_init(self):
        self.mon_tracks = []         # dicts: name, pos, seen, closer (turn), attacked (turn)
        self.tracks_key = None       # the level the tracks are on
        self.zapper = None           # (turn, track) that zapped an unknown wand: its effect names the kind

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
                tracks.append({"name": n, "pos": p, "seen": t, "first": t, "closer": None, "attacked": None,
                               "wands": set(), "missile": None, "breath": False})
        self.mon_tracks = tracks

    def msg_threat(self, m):
        """A message naming a monster attacking us: the nearest track of that name in view attacked; its ranged
        attacks noted (module docstring)."""
        if not self.mon_tracks:
            return
        t = self.turn()
        for name in ATTACK_RE.findall(m):
            tr = self.track_named(name)
            if tr is not None:
                tr["attacked"] = t
        for name, wand in ZAP_RE.findall(m):
            tr = self.track_named(name)
            if tr is not None:
                kind = wand[len("wand of "):] if wand.startswith("wand of ") else None
                if kind in WAND_KINDS:
                    tr["wands"].add(kind)
                self.zapper = (t, tr) if kind is None else None
        if self.zapper is not None and t - self.zapper[0] <= 1:            # its effect: this turn or the next
            kind = next((k for phrase, k in RAY_SEEN if phrase in m), None)
            if kind is not None:
                self.zapper[1]["wands"].add(kind)
                self.zapper = None
        for name, count, what in SHOOT_RE.findall(m):
            tr = self.track_named(name)
            if tr is not None:
                n = int(count) if count.isdigit() else 1
                poisoned = what.startswith("poisoned ")
                kind = singular(what[len("poisoned "):] if poisoned else what)
                old = tr["missile"]
                tr["missile"] = {"kind": kind, "counts": (old["counts"] if old else []) + [n],
                                 "poisoned": poisoned or bool(old and old["poisoned"])}
        for name in BREATH_RE.findall(m):
            tr = self.track_named(name)
            if tr is not None:
                tr["breath"] = True

    def track_named(self, name):
        """The track of that name seen this turn or the last, nearest to us."""
        t, me = self.turn(), self.pos()
        seen = [tr for tr in self.mon_tracks if tr["name"] == name and t - tr["seen"] <= 1]
        return min(seen, key=lambda r: _dist(r["pos"], me)) if seen else None

    def ranged_profile(self, pos):
        """The ranged attacks seen from the monster at pos (None: none): {"wands", "missile", "breath"}."""
        tr = next((r for r in self.mon_tracks if r["pos"] == pos and r["seen"] == self.turn()), None)
        if tr is None or not (tr["wands"] or tr["missile"] or tr["breath"]):
            return None
        return {"wands": sorted(tr["wands"]), "missile": tr["missile"], "breath": tr["breath"]}

    def active_threat(self, pos):
        """The monster at pos is coming for us (module docstring)."""
        t, me = self.turn(), self.pos()
        if _dist(pos, me) <= 1:
            return True
        tr = next((r for r in self.mon_tracks if r["pos"] == pos and r["seen"] == t), None)
        if tr is None:
            return False
        if tr.get("first") == t:                 # just come into view: a threat if it can hit us next turn
            pm = PM_BY_NAME.get(tr["name"])
            return pm is not None and _dist(pos, me) - 1 < -(-pm.mmove // 12)
        return tr["attacked"] is not None or (tr["closer"] is not None and t - tr["closer"] <= ACTIVE_RECENT)
