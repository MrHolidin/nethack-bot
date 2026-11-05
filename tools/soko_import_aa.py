"""Import Sokoban push lists from AutoAscend (https://github.com/skbly7/autoascend, autoascend/soko_solver/maps.py;
MIT License, Copyright (c) 2022 Maciej Sypetkowski, Michal Sypetkowski -- their maps are from NetHackWiki) as plans
for our variants, each checked in our simulator (soko_solve.Level.check) before it is saved.

    python -I tools/soko_import_aa.py PATH/TO/autoascend/soko_solver/maps.py tools tools/data/soko_aa.json

The file is read as data (ast.literal_eval, nothing in it runs). Their maps show the holes but the last as floor
(a boulder rolls on past them, the last hole is bottomless) and their x counts the map's indent past 4 columns:
here a boulder drops into the first open trap -- its later pushes are dropped -- and the plan ends once the goal
is open (they push the spares on into the bottomless hole).
"""
import ast, json, sys
maps_path, tools_dir, out = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, tools_dir)
import soko_solve as S
text = open(maps_path).read()
data = ast.literal_eval(text[text.index("maps = ") + len("maps = "):].strip())
levels = S.parse()
res = {}
for smap, plan in data.items():
    rows = smap.split("\n")
    ind = min(len(r) - len(r.lstrip(" ")) for r in rows if r.strip())
    rows = [r[ind:] for r in rows]
    aw = {(y, x) for y, r in enumerate(rows) for x, c in enumerate(r) if c in "-|"}
    found = None
    for name, lv in levels.items():
        ow = {(y, x) for y, r in enumerate(lv["map"]) for x, c in enumerate(r) if c in "-|"}
        for oy in range(-3, 4):
            for ox in range(-3, 4):
                sh = {(y + oy, x + ox) for y, x in aw}
                if len(sh ^ ow) <= 4:
                    found = (name, oy, ox, len(sh ^ ow))
                    break
            if found:
                break
        if found:
            break
    if not found:
        print("no match", rows[:2]); continue
    name, oy, ox, diff = found
    L = S.Level(levels[name])
    raw = [((y + oy, x - (ind - 4) + ox), (dy, dx)) for (y, x), (dy, dx) in plan]
    # their maps show the holes but the last as floor: a boulder rolls on past them. In the game it drops into
    # the first open one -- so the pushes of a boulder that fell in are dropped, the rest kept
    lv = levels[name]
    bs, ts = set(lv["boulders"]), set(lv["traps"])
    p = []
    for b, d in raw:
        if b not in bs:
            continue
        to = (b[0] + d[0], b[1] + d[1])
        p.append((b, d))
        bs.discard(b)
        if to in ts:
            ts.discard(to)
        else:
            bs.add(to)
        # their last hole is bottomless: they keep pushing spares into it -- stop once the goal is open
        if L.goal in L.walk(L.idx(b), {L.idx(x) for x in bs}, {L.idx(x) for x in ts}):
            break
    try:
        ok = L.check(p)
    except AssertionError as e:
        ok = "assert " + str(e)
    print(name, "offset", (oy, ox), "walldiff", diff, "pushes", len(p), "check", ok)
    if ok is True:
        res[name] = p
json.dump(res, open(out, "w"))
