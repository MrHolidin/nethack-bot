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
from collections import Counter

import numpy as np

from nhbot import glyphs as G
from nhbot.events import Attacked, MonBreath, MonVolley, MonZap, RaySeen
from nhbot.monsters import PM_BY_NAME

ACTIVE_RECENT = 3            # turns: a move toward us this lately counts
TRACK_FORGET = 10            # turns a track is kept unseen
HOLD_TURNS = 10              # hold_position: turns at most waiting on the spot for the threats in view
WAND_KINDS = ("striking", "magic missile", "fire", "cold", "sleep", "lightning", "death")


def singular(what):
    """'2 orcish arrows' kind -> 'orcish arrow' (knives -> knife)."""
    if what.endswith("ves"):
        return what[:-3] + "fe"
    return what[:-1] if what.endswith("s") else what


def _dist(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


class ThreatState:
    """State of tracking the monsters in view (ThreatMixin)."""
    def __init__(self):
        self.mon_tracks = []         # dicts: name, pos, seen, closer (turn), attacked (turn)
        self.tracks_key = None       # the level the tracks are on
        self.zapper = None           # (turn, track) that zapped an unknown wand: its effect names the kind
        self.hold_since = None       # hold_position: the turn we began waiting for the threats in view
        self.hold_stats = Counter()


class ThreatMixin:
    def threats_init(self):
        self.threats = ThreatState()

    def threat_track(self):
        """Match the monsters on screen (not pets) to the tracks; note who came closer by its own move."""
        t, me = self.turn(), self.pos()
        g = self.obs["glyphs"]
        if self.threats.tracks_key != self.cur_key:
            self.threats.mon_tracks, self.threats.tracks_key = [], self.cur_key
        tracks = [tr for tr in self.threats.mon_tracks if t - tr["seen"] <= TRACK_FORGET]
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
        self.threats.mon_tracks = tracks

    def msg_threat(self, msg):
        """A message naming a monster attacking us: the nearest track of that name in view attacked; its ranged
        attacks noted (module docstring)."""
        if not self.threats.mon_tracks:
            return
        t = self.turn()
        # only attacks on us (events.Attacked), melee or ranged -- not "The jackal bites the little dog."
        names = [e.monster for e in msg.all(Attacked) if e.monster is not None]
        for name in names:
            tr = self.track_named(name)
            if tr is not None:
                tr["attacked"] = t
        for zap in msg.all(MonZap):
            tr = self.track_named(zap.name)
            if tr is not None:
                kind = zap.wand[len("wand of "):] if zap.wand.startswith("wand of ") else None
                if kind in WAND_KINDS:
                    tr["wands"].add(kind)
                self.threats.zapper = (t, tr) if kind is None else None
        if self.threats.zapper is not None and t - self.threats.zapper[0] <= 1:            # its effect: this turn or the next
            for ray in msg.all(RaySeen):
                self.threats.zapper[1]["wands"].add(ray.kind)
                self.threats.zapper = None
        for vol in msg.all(MonVolley):
            tr = self.track_named(vol.name)
            if tr is not None:
                n = int(vol.count) if vol.count.isdigit() else 1
                poisoned = vol.missile.startswith("poisoned ")
                kind = singular(vol.missile[len("poisoned "):] if poisoned else vol.missile)
                old = tr["missile"]
                tr["missile"] = {"kind": kind, "counts": (old["counts"] if old else []) + [n],
                                 "poisoned": poisoned or bool(old and old["poisoned"])}
        for br in msg.all(MonBreath):
            tr = self.track_named(br.name)
            if tr is not None:
                tr["breath"] = True

    def track_named(self, name):
        """The track of that name seen this turn or the last, nearest to us."""
        t, me = self.turn(), self.pos()
        seen = [tr for tr in self.threats.mon_tracks if tr["name"] == name and t - tr["seen"] <= 1]
        return min(seen, key=lambda r: _dist(r["pos"], me)) if seen else None

    def ranged_profile(self, pos):
        """The ranged attacks seen from the monster at pos (None: none): {"wands", "missile", "breath"}."""
        tr = next((r for r in self.threats.mon_tracks if r["pos"] == pos and r["seen"] == self.turn()), None)
        if tr is None or not (tr["wands"] or tr["missile"] or tr["breath"]):
            return None
        return {"wands": sorted(tr["wands"]), "missile": tr["missile"], "breath": tr["breath"]}

    def hold_step(self, lv):
        """A/B hold_position: monsters in view coming for us (active_threat), none of them seen to shoot, zap or
        breathe (ranged_profile) -- wait for them on the spot ("s"), HOLD_TURNS turns at most till none is in view
        any more; one next to us we can hit is the melee step's (before this one). True if it waited."""
        th = [p for p, _ in self.visible_hostiles(lv) if self.active_threat(p)]
        st = self.threats
        if not th:
            st.hold_since = None
            return False
        if any(self.ranged_profile(p) for p in th):
            st.hold_stats["shot"] += 1
            return False
        t = self.turn()
        if st.hold_since is None:
            st.hold_since = t
            st.hold_stats["holds"] += 1
        if t - st.hold_since >= HOLD_TURNS:
            return False
        st.hold_stats["waits"] += 1
        self.cur_act = "hold"
        self.press("s")
        return True

    def active_threat(self, pos):
        """The monster at pos is coming for us (module docstring)."""
        t, me = self.turn(), self.pos()
        if _dist(pos, me) <= 1:
            return True
        tr = next((r for r in self.threats.mon_tracks if r["pos"] == pos and r["seen"] == t), None)
        if tr is None:
            return False
        if tr.get("first") == t:                 # just come into view: a threat if it can hit us next turn
            pm = PM_BY_NAME.get(tr["name"])
            return pm is not None and _dist(pos, me) - 1 < -(-pm.mmove // 12)
        return tr["attacked"] is not None or (tr["closer"] is not None and t - tr["closer"] <= ACTIVE_RECENT)
