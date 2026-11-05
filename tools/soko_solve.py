"""Sokoban, offline: the eight level variants of sokoban.des (tools/data/sokoban.des, NetHack 3.6) and a solver
for each -- the plans nhbot/soko_data.py carries for the bot to follow.

    python tools/soko_solve.py            solve all eight, check each plan in the simulator, write soko_data.py
    python tools/soko_solve.py soko4-1    solve one (saved in tools/data/soko_plans)

A level: walls, boulders, traps (pits on the bottom two levels, holes above), the staircase we arrive on and the
goal -- the up staircase, or on the top level the square in front of the zoo's locked door. The rules (hack.c
moverock / test_move under Sokoban): a boulder is pushed only orthogonally, into a square free of walls, doors
and boulders; pushed into a pit or hole it fills it (both go); the hero never steps onto an open trap, moves
diagonally only if the two squares beside the move are not both wall or boulder, and never through a doorway
diagonally. A plan is the list of pushes, each (boulder square, direction): where the hero stands between
pushes is free -- any square the walk reaches.
"""
import heapq
import json
import os
import re
import sys
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
DES = os.path.join(HERE, "data", "sokoban.des")
OUT = os.path.join(os.path.dirname(HERE), "nhbot", "soko_data.py")
ORTHO = ((-1, 0), (1, 0), (0, -1), (0, 1))
DIRS8 = ORTHO + ((-1, -1), (-1, 1), (1, -1), (1, 1))


def plan_list(plan):
    """The plan as a list from its linked form (prev, push)."""
    out = []
    while plan:
        plan, step = plan
        out.append(step)
    return out[::-1]


def parse(path=DES):
    """{name: level} from the des file; squares are (row, col) in the MAP block."""
    text = open(path).read()
    out = {}
    for block in re.split(r"\nMAZE:", text)[1:]:
        name = re.match(r'"([^"]+)"', block).group(1)
        rows = block.split("\nMAP\n", 1)[1].split("\nENDMAP", 1)[0].split("\n")
        width = max(len(r) for r in rows)
        rows = [r.ljust(width) for r in rows]
        xy = lambda m: (int(m[1]), int(m[0]))
        boulders = {xy(m) for m in re.findall(r"OBJECT:\('`',\"boulder\"\),\((\d+),(\d+)\)", block)}
        traps = {xy(m[1:]): m[0] for m in re.findall(r'TRAP:"(hole|pit)",\((\d+),(\d+)\)', block)}
        stairs = {d: xy((a, b)) for a, b, d in re.findall(r"STAIR:\((\d+),(\d+)\),(up|down)", block)}
        br = re.search(r"BRANCH:\((\d+),(\d+),", block)
        arrive = xy(br.groups()) if br else stairs["down"]
        doors = {xy((a, b)): s for s, a, b in re.findall(r"DOOR:(locked|closed|open),\((\d+),(\d+)\)", block)}
        if "up" in stairs:
            goal = stairs["up"]
        else:                                  # the top level: the square east of the zoo's locked door
            (dy, dx), = [d for d, s in doors.items() if s == "locked"]
            goal = (dy, dx + 1)
        out[name] = {"name": name, "map": rows, "boulders": boulders, "traps": traps, "arrive": arrive,
                     "goal": goal, "up": stairs.get("up"), "doors": doors}
    return out


class Level:
    """A level for the solver. Squares are ints (row * w + col) inside; plans come out as (row, col)."""

    def __init__(self, lv):
        self.lv = lv
        self.rows = lv["map"]
        self.h, self.w = len(self.rows), len(self.rows[0])
        w = self.w
        self.idx = lambda p: p[0] * w + p[1]
        self.rc = lambda i: (i // w, i % w)
        doors = {self.idx(p) for p in lv["doors"]}
        self.wall = bytearray(self.h * w)      # walls and stone; doors are not walls for the hero
        for r in range(self.h):
            for c in range(w):
                if self.rows[r][c] != "." and r * w + c not in doors:
                    self.wall[r * w + c] = 1
        self.goal = self.idx(lv["goal"])
        # never a boulder on: the goal, our way back down, a door (moverock: a closed door stops it; we open
        # the locked ones by kicking -- a boulder there would close the way)
        self.nopush = {self.goal, self.idx(lv["arrive"])} | doors
        # hero steps: (to, side1, side2) -- a diagonal step needs side1 or side2 free (no squeeze); never
        # diagonally into or out of a doorway
        self.steps = []
        for i in range(self.h * w):
            r, c = self.rc(i)
            out = []
            for dr, dc in DIRS8:
                rr, cc = r + dr, c + dc
                j = rr * w + cc
                if not (0 <= rr < self.h and 0 <= cc < w) or self.wall[j]:
                    continue
                if dr and dc and (i in doors or j in doors):
                    continue
                sides = ((r + dr) * w + c, r * w + c + dc) if dr and dc else (-1, -1)
                out.append((j, sides[0], sides[1]))
            self.steps.append(out)
        self.dirs = tuple(dr * w + dc for dr, dc in ORTHO)
        self._dist = {}

    def blocked(self, i, bs):
        return self.wall[i] or i in bs

    def walk(self, start, bs, ts):
        """Squares the hero reaches from start (Sokoban: no squeeze between boulders / walls)."""
        seen = {start}
        stack = [start]
        wall = self.wall
        while stack:
            i = stack.pop()
            for n, s1, s2 in self.steps[i]:
                if n in seen or n in bs or n in ts:
                    continue
                if s1 >= 0 and (wall[s1] or s1 in bs) and (wall[s2] or s2 in bs):
                    continue
                seen.add(n)
                stack.append(n)
        return seen

    def pushes(self, reach, bs, ts):
        wall = self.wall
        for b in bs:
            for d in self.dirs:
                to = b + d
                if (b - d) in reach and not wall[to] and to not in bs and to not in self.nopush:
                    yield b, d, to

    def push_dist(self, ts):
        """Pushes a lone boulder needs from each square to the nearest trap (other boulders ignored): a reverse
        search from the traps -- a boulder comes into s from s - d when s - d and the hero's square s - 2d are
        floor. Squares no trap is reached from (corners, dead ends) are absent."""
        if ts in self._dist:
            return self._dist[ts]
        dist = {t: 0 for t in ts}
        q = deque(ts)
        while q:
            s = q.popleft()
            for d in self.dirs:
                prev, stand = s - d, s - 2 * d
                if prev in dist or not (0 <= stand < len(self.wall)) or self.wall[prev] or self.wall[stand] \
                        or prev in self.nopush:
                    continue
                dist[prev] = dist[s] + 1
                q.append(prev)
        self._dist[ts] = dist
        return dist

    def feasible(self, bs, ts):
        """Enough boulders can still reach a trap to fill the open ones."""
        dist = self.push_dist(ts)
        return sum(1 for b in bs if b in dist) >= len(ts)

    def fill_one(self, bs, ts, pos, want=4, limit=200_000, weight=2):
        """Best-first over pushes from this state until a trap is filled: up to `want` distinct results
        (boulders left, traps left, hero square, pushes as a linked list). Priority: pushes so far + weight *
        the fewest pushes any boulder needs to some open trap (walls only, push_dist of that trap alone)."""
        tdist = [self.push_dist(frozenset([t])) for t in ts]
        big = 10 ** 6

        def hmin(cbs):
            return min((d[b] for d in tdist for b in cbs if b in d), default=big)

        start = (bs, min(self.walk(pos, bs, ts)))
        seen = {start}
        tick = 0
        heap = [(weight * hmin(bs), 0, tick, bs, pos, ())]
        results = []
        while heap and tick < limit:
            _, g, _, cbs, cpos, plan = heapq.heappop(heap)
            reach = self.walk(cpos, cbs, ts)
            for b, d, to in self.pushes(reach, cbs, ts):
                if to in ts:
                    nbf = cbs - {b}
                    nt = ts - {to}
                    if nt and not self.feasible(nbf, nt):
                        continue
                    if all(r[0] != nbf for r in results):
                        results.append((nbf, nt, b, (plan, (b, d))))
                        if len(results) >= want:
                            return results
                    continue
                nbf = (cbs - {b}) | {to}
                if not self.feasible(nbf, ts):
                    continue
                k = (nbf, min(self.walk(b, nbf, ts)))
                if k in seen:
                    continue
                seen.add(k)
                tick += 1
                hv = hmin(nbf)
                heapq.heappush(heap, (g + 1 + weight * hv, g + 1, tick, nbf, b, (plan, (b, d))))
        return results

    def solve(self, want=4, budget=600):
        """Trap by trap (fill_one), depth first with backtracking over the alternatives each step offers;
        returns the plan -- a list of ((row, col), (drow, dcol)) -- or None. budget: seconds."""
        import time
        lv = self.lv
        t_end = time.time() + budget
        dead = set()

        def rec(bs, ts, pos, plan):
            if time.time() > t_end:
                return None
            reach = self.walk(pos, bs, ts)
            if self.goal in reach:
                return plan
            key = (bs, ts, min(reach))
            if key in dead or not ts:
                return None
            for nb, nt, npos, nplan in self.fill_one(bs, ts, pos, want):
                got = rec(nb, nt, npos, (plan, nplan))
                if got is not None:
                    return got
            dead.add(key)
            return None

        got = rec(frozenset(map(self.idx, lv["boulders"])), frozenset(map(self.idx, lv["traps"])),
                  self.idx(lv["arrive"]), ())
        if got is None:
            return None
        segs = []
        while got:
            got, seg = got
            segs.append(plan_list(seg))
        w = self.w
        return [(self.rc(b), (d // w if abs(d) >= w else 0, d if abs(d) < w else 0))
                for seg in segs[::-1] for b, d in seg]

    def check(self, plan):
        """Play the plan in the simulator: every push legal, the goal reached at the end."""
        bs, ts = set(map(self.idx, self.lv["boulders"])), set(map(self.idx, self.lv["traps"]))
        pos = self.idx(self.lv["arrive"])
        for b, (dr, dc) in plan:
            b, d = self.idx(b), dr * self.w + dc
            reach = self.walk(pos, bs, ts)
            assert b in bs and (b - d) in reach and not self.blocked(b + d, bs), (self.rc(b), (dr, dc))
            bs.discard(b)
            if b + d in ts:
                ts.discard(b + d)
            else:
                bs.add(b + d)
            pos = b
        return self.goal in self.walk(pos, bs, ts)


PLANS = os.path.join(HERE, "data", "soko_plans")


def main():
    """Solve the named levels (all by default) -- a plan already solved and saved (tools/data/soko_plans) is
    reused -- check each in the simulator, and with all eight in hand write nhbot/soko_data.py."""
    levels = parse()
    names = sys.argv[1:] or sorted(levels)
    os.makedirs(PLANS, exist_ok=True)
    for name in names:
        path = os.path.join(PLANS, name + ".json")
        L = Level(levels[name])
        if os.path.exists(path):
            plan = [(tuple(b), tuple(d)) for b, d in json.load(open(path))]
        else:
            plan = L.solve()
        ok = plan is not None and L.check(plan)
        print(f"{name}: {'%d pushes' % len(plan) if plan else 'NO SOLUTION'} check={ok}", flush=True)
        if ok:
            json.dump(plan, open(path, "w"))
    plans = {}
    for name in levels:
        path = os.path.join(PLANS, name + ".json")
        if os.path.exists(path):
            plans[name] = [(tuple(b), tuple(d)) for b, d in json.load(open(path))]
    write(levels, plans)                     # a variant not solved yet has plan None (the bot gives it up)


def write(levels, plans):
    lines = ['"""Sokoban\'s eight level variants (tools/data/sokoban.des) and a plan for each -- written by',
             'tools/soko_solve.py, do not edit. Squares are (row, col) in the level\'s MAP block; a plan is the',
             'list of pushes (boulder square, (drow, dcol)), in order."""', "", "LEVELS = {"]
    for name in sorted(levels):
        lv = levels[name]
        lines.append(f"    {name!r}: {{")
        lines.append(f"        'map': {json.dumps(lv['map'])},")
        for k in ("boulders", "traps", "arrive", "goal", "up", "doors"):
            v = lv[k]
            if isinstance(v, set):
                v = sorted(v)
            if isinstance(v, dict):
                v = dict(sorted(v.items()))
            lines.append(f"        {k!r}: {v!r},")
        plan = plans.get(name)
        lines.append(f"        'plan': {None if plan is None else [(b, d) for b, d in plan]!r},")
        lines.append("    },")
    lines.append("}")
    open(OUT, "w").write("\n".join(lines) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
