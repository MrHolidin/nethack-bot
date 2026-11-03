"""Fighting a group at a room's entrance (flag door_ambush).

Rooms are read off the remembered map, not off the level's room list: a square is room floor when it is passable
and some square of its 3 x 3 block has all 8 neighbours passable too (a "core" square). That takes in ordinary
rooms and the open parts of the Mines, and leaves out corridors, doorways and other one- or two-wide passages.
An entrance of a room is a passable square outside it next to one of its squares (a door, a doorway, the mouth
of a passage).

Active threats are the hostiles in view that came closer to us lately (their own move: the distance from where we
stand now) or shot at us lately. With more than AMBUSH_THREATS of them and nobody next to us, the room holding
most of them is found, and a square outside it, behind its wall:

    -D-
    @..

that is: not next to any square of the room, within AMBUSH_NEAR steps of one of its entrances (outside the room),
and with no straight line (mthrowu.c m_lined_up: 8 directions; a door with a door in it stops diagonals) from the
room, its entrances or any hostile in view -- at any length, not only under BOLT_LIM: they come closer along it. Whoever comes after us comes out of the
entrance and round the wall one at a time, and nothing can shoot at us before it stands next to us. We go there
if we get there first (our path at our speed against each threat's distance at its speed, along squares next to
none of them), then wait AMBUSH_WAIT turns; whatever comes next to us is fought by the melee step, which comes
first.
"""
import collections

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import COLS, NEIGH, ROWS
from nhbot.monsters import PM_BY_NAME

AMBUSH_THREATS = 2        # act with more active threats than this
AMBUSH_RECENT = 5         # turns: came closer / shot at us this lately
AMBUSH_WAIT = 10          # turns to wait at the spot
AMBUSH_MAX_PATH = 20      # path cost to the spot at most
AMBUSH_NEAR = 12          # the spot is this many steps from an entrance of the room at most
TRACK_FORGET = 10         # turns a monster track is kept unseen



def _shift(a, dy, dx, fill=False):
    """a shifted so that out[y, x] = a[y + dy, x + dx] (fill outside)."""
    out = np.full_like(a, fill)
    ys = slice(max(0, -dy), ROWS - max(0, dy))
    yd = slice(max(0, dy), ROWS - max(0, -dy))
    xs = slice(max(0, -dx), COLS - max(0, dx))
    xd = slice(max(0, dx), COLS - max(0, -dx))
    out[ys, xs] = a[yd, xd]
    return out


def _near(mask):
    """Squares 8-adjacent to some square of mask (not mask itself unless adjacent to another)."""
    out = np.zeros_like(mask)
    for dy, dx in NEIGH:
        out |= _shift(mask, dy, dx)
    return out


def room_labels(passable):
    """Room label per square (0: not room floor), by the core rule of the module docstring."""
    core = passable.copy()
    for dy, dx in NEIGH:
        core &= _shift(passable, dy, dx)
    room = (core | _near(core)) & passable
    labels = np.zeros((ROWS, COLS), dtype=np.int32)
    n = 0
    for y, x in zip(*np.nonzero(room)):
        if labels[y, x]:
            continue
        n += 1
        labels[y, x] = n
        q = collections.deque([(y, x)])
        while q:
            cy, cx = q.popleft()
            for dy, dx in NEIGH:
                ny, nx = cy + dy, cx + dx
                if 0 <= ny < ROWS and 0 <= nx < COLS and room[ny, nx] and not labels[ny, nx]:
                    labels[ny, nx] = n
                    q.append((ny, nx))
    return labels


def _steps_from(start, ok, limit):
    """Squares of ok reachable from the squares of start in at most `limit` 8-way steps (start included)."""
    seen = start.copy()
    front = start.copy()
    for _ in range(limit):
        front = _near(front) & ok & ~seen
        if not front.any():
            break
        seen |= front
    return seen


def _lined_up(y, x, see_through, intact_door, sources):
    """A square of sources on a straight line from (y, x) with nothing solid between."""
    for dy, dx in NEIGH:
        cy, cx = y, x
        while True:
            if dy and dx and intact_door[cy, cx]:
                break                                   # no diagonal into or out of a door
            cy, cx = cy + dy, cx + dx
            if not (0 <= cy < ROWS and 0 <= cx < COLS) or not see_through[cy, cx]:
                break
            if dy and dx and intact_door[cy, cx]:
                break
            if sources[cy, cx]:
                return True
    return False


def ambush_spots(passable, labels, room, intact_door, threats_at):
    """Squares outside room `room` and next to none of its squares, within AMBUSH_NEAR steps of one of its
    entrances, that nothing in the room, at its entrances or at threats_at can shoot along a straight line."""
    inside = labels == room
    near_in = _near(inside)
    entrance = passable & ~inside & near_in
    reach = _steps_from(entrance, passable & ~inside, AMBUSH_NEAR)
    cand = reach & ~inside & ~near_in
    sources = inside | entrance | threats_at
    out = np.zeros_like(passable)
    for y, x in zip(*np.nonzero(cand)):
        if not _lined_up(y, x, passable, intact_door, sources):
            out[y, x] = True
    return out


class AmbushMixin:
    def ambush_init(self):
        self.mon_tracks = []          # dicts: name, pos, seen, closer (turn), shot (turn)
        self.ambush = None            # dict: key, pos, deadline, wait_until, shot0
        self.ambush_stats = collections.Counter()

    # ------------------------------------------------------------------ who is coming
    def threat_track(self, lv):
        """Match the hostiles in view to the tracks of the last ticks (same name, nearest, a few squares) and
        note which came closer by their own move and which shot at us (combat.shot_event names it)."""
        t, me = self.turn(), self.pos()
        dist = lambda p: max(abs(p[0] - me[0]), abs(p[1] - me[1]))
        tracks = [tr for tr in self.mon_tracks if t - tr["seen"] <= TRACK_FORGET]
        free = list(tracks)
        for p, n in self.visible_hostiles(lv):
            cand = [tr for tr in free if tr["name"] == n
                    and max(abs(tr["pos"][0] - p[0]), abs(tr["pos"][1] - p[1])) <= 2 + (t - tr["seen"])]
            if cand:
                tr = min(cand, key=lambda r: max(abs(r["pos"][0] - p[0]), abs(r["pos"][1] - p[1])))
                free.remove(tr)
                if dist(p) < dist(tr["pos"]):
                    tr["closer"] = t
                tr["pos"], tr["seen"] = p, t
            else:
                tracks.append({"name": n, "pos": p, "seen": t, "closer": None, "shot": None})
        ev = self.shot_event
        if ev and ev[1] and t - ev[0] <= 1:
            seen = [tr for tr in tracks if tr["name"] == ev[1] and tr["seen"] == t]
            if seen:
                min(seen, key=lambda r: dist(r["pos"]))["shot"] = ev[0]
        self.mon_tracks = tracks

    def active_threats(self):
        t = self.turn()
        return [tr for tr in self.mon_tracks if tr["seen"] == t
                and any(v is not None and t - v <= AMBUSH_RECENT for v in (tr["closer"], tr["shot"]))]

    # ------------------------------------------------------------------ the plan
    def ambush_plan(self, lv, threats):
        """The spot to wait at, or None (ambush_stats says why)."""
        k_mem, k_live, passable = self.grids(lv)
        labels = room_labels(G.PASSABLE[k_mem] & ~lv.blocked)
        rooms = collections.Counter(int(labels[tr["pos"]]) for tr in threats if labels[tr["pos"]])
        if not rooms:
            self.ambush_stats["no_room"] += 1
            return None
        room = rooms.most_common(1)[0][0]
        danger = np.zeros((ROWS, COLS), dtype=bool)
        for p, _ in self.visible_hostiles(lv):
            danger[p] = True
        intact = (k_mem == G.DOOR_OPEN) | (k_mem == G.DOOR_CLOSED) | lv.door_intact | lv.no_diag
        spots = ambush_spots(G.PASSABLE[k_mem] & ~lv.blocked, labels, room, intact, danger) & passable
        if not spots.any():
            self.ambush_stats["no_spot"] += 1
            return None
        danger |= _near(danger)
        spots &= ~danger
        safe = passable & ~danger
        safe[self.pos()] = True
        dist, _, _ = self.dijkstra(lv, k_mem, k_live, safe, self.pos(), max_cost=AMBUSH_MAX_PATH)
        ours = self.our_speed()
        best = None
        for y, x in zip(*np.nonzero(spots)):
            d = int(dist[y, x])
            if d < 0 or d >= AMBUSH_MAX_PATH or (best is not None and d >= best[0]):
                continue
            if all(d * PM_BY_NAME[tr["name"]].mmove < ours * max(abs(tr["pos"][0] - y), abs(tr["pos"][1] - x))
                   for tr in threats if tr["name"] in PM_BY_NAME):
                best = (d, (int(y), int(x)))
        if best is None:
            self.ambush_stats["too_far"] += 1
            return None
        return best

    def ambush_step(self, lv, hostiles):
        """door_ambush: plan when more than AMBUSH_THREATS threats are active and nobody is next to us; then
        walk to the spot and wait there. True if it used the turn."""
        if not self.opts.door_ambush:
            return False
        t = self.turn()
        a = self.ambush
        if a is None:
            if hostiles or self.elb_state is not None:
                return False
            threats = self.active_threats()
            if len(threats) <= AMBUSH_THREATS:
                return False
            self.ambush_stats["triggers"] += 1
            plan = self.ambush_plan(lv, threats)
            if plan is None:
                return False
            d, spot = plan
            self.ambush_stats["planned"] += 1
            a = self.ambush = {"key": lv.key, "pos": spot, "deadline": t + 2 * d + 5, "wait_until": None,
                               "shot0": None}
        if a["key"] != lv.key:
            self.ambush_stats["left_level"] += 1
            self.ambush = None
            return False
        if hostiles:
            return False                                  # the melee step fights; we resume after
        if self.pos() == a["pos"]:
            if a["wait_until"] is None:
                a["wait_until"] = t + AMBUSH_WAIT
                a["shot0"] = self.last_shot_turn
                self.ambush_stats["arrived"] += 1
            if self.last_shot_turn > a["shot0"]:
                self.ambush_stats["shot_at"] += 1         # something reaches us at the spot: not a good one
                self.ambush = None
                return False
            if t >= a["wait_until"]:
                self.ambush_stats["waited"] += 1
                self.ambush = None
                return False
            self.cur_act = "ambush"
            self.press("s")
            return True
        if t > a["deadline"]:
            self.ambush_stats["late"] += 1
            self.ambush = None
            return False
        k_mem, k_live, passable = self.grids(lv)
        danger = np.zeros((ROWS, COLS), dtype=bool)
        for p, _ in self.visible_hostiles(lv):
            danger[p] = True
        safe = passable & ~_near(danger)
        safe[self.pos()] = True
        mask = np.zeros((ROWS, COLS), dtype=bool)
        mask[a["pos"]] = True
        if self.walk_to(lv, mask, max_cost=AMBUSH_MAX_PATH * 2, act="ambush",
                        grids=(k_mem, k_live, safe))[0] != "moved":
            self.ambush_stats["cut_off"] += 1
            self.ambush = None
            return False
        return True
