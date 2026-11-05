"""Sokoban, offline: the eight level variants of sokoban.des (tools/data/sokoban.des, NetHack 3.6) and a solver
for each -- the plans nhbot/soko_data.py carries for the bot to follow.

    python tools/soko_solve.py            solve all eight, check each plan in the simulator, write soko_data.py
    python tools/soko_solve.py soko4-1    solve one (saved in tools/data/soko_plans)

A level: walls, boulders, traps (pits on the bottom two levels, holes above), the staircase we arrive on and the
goal -- the up staircase, or on the top level the square in front of the zoo's locked door. The rules and the
solver: nhbot/soko_solver.py.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from nhbot.soko_solver import DIRS8, ORTHO, Level, plan_list  # noqa: E402,F401  (soko_import_aa uses Level)
DES = os.path.join(HERE, "data", "sokoban.des")
OUT = os.path.join(os.path.dirname(HERE), "nhbot", "soko_data.py")


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
             'list of pushes (boulder square, (drow, dcol)), in order. The plans of the upper three levels come from',
             'AutoAscend (tools/soko_import_aa.py; MIT License, Copyright (c) 2022 Maciej Sypetkowski, Michal',
             'Sypetkowski), the bottom level\'s from our solver; all checked in tools/soko_solve.py\'s simulator."""',
             "", "LEVELS = {"]
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
