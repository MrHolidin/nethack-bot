"""diag: death taxonomy, score at stake, self-inflicted deaths, time, survivor predictors.
python main.py [sets,comma-separated]"""
import collections, re, statistics as st, sys
import numpy as np
import load

SETS = tuple(sys.argv[1].split(",")) if len(sys.argv) > 1 else ("base22_80k", "base22_81k", "base_d1", "base_d2")
rs = load.rows(SETS)
N = len(rs)
print("games", N, collections.Counter(r["set"] for r in rs))

SPECIAL = [  # checked on the last 4 messages before the attacker name; order = priority
    (r"faint from lack of food|starv", "starvation"),
    (r"You drown|You sink like|crawl out of the water", "drowning"),
    (r"Keystone Kop|You murderer|under arrest", "angered law"),
    (r"Medusa's gaze", "Medusa gaze"),
    (r"psychic energy", "mind flayer psychic"),
    (r"tainted|deathly sick|You feel feverish", "food poisoning/illness"),
    (r"Thou art arrogant|You feel that \w+ is displeased|Thou hast angered|Thou durst", "bad prayer"),
    (r"sharp iron spikes|rolling boulder|trigger a trap|surge of electricity|land mine|KABOOM|cloud of gas|bear trap",
     "trap"),
    (r"breaks apart and explodes", "own wand exploded"),
]
FAMILY = {
    "soldier ant": "ants/bees", "fire ant": "ants/bees", "killer bee": "ants/bees", "giant ant": "ants/bees",
    "troll": "trolls", "rock troll": "trolls", "Olog-hai": "trolls", "ice troll": "trolls", "water troll": "trolls",
    "Green-elf": "elves", "Grey-elf": "elves", "Woodland-elf": "elves", "elf-lord": "elves", "Elvenking": "elves",
    "hill orc": "orcs", "Uruk-hai": "orcs", "Mordor orc": "orcs", "orc-captain": "orcs",
    "soldier": "soldiers", "sergeant": "soldiers", "lieutenant": "soldiers", "captain": "soldiers",
    "winged gargoyle": "gargoyles", "gargoyle": "gargoyles",
    "water demon": "FOUNTAIN", "water moccasin": "FOUNTAIN",
    "wand": "monster wand", "ray(unknown src)": "monster wand/ray",
    "invisible(hist)": "unseen/blind melee", "unseen": "unseen/blind melee",
}


def cause(r):
    if r.get("crash"):
        return "CRASH"
    if r.get("truncated"):
        return "TRUNCATED"
    tail = " ".join((r.get("last_msgs") or [])[-3:])
    for pat, lab in SPECIAL:
        if re.search(pat, tail):
            return lab
    c = load.cause(r)
    return c.replace("(hist)", "") if c != "invisible(hist)" else c


for r in rs:
    r["cause"] = cause(r)
    r["fam"] = FAMILY.get(r["cause"], r["cause"])
dead = [r for r in rs if r["cause"] not in ("TRUNCATED", "CRASH")]
print(f"dead {len(dead)}  truncated {sum(r['cause']=='TRUNCATED' for r in rs)}  crash {sum(r['cause']=='CRASH' for r in rs)}")
print("mean score %.0f  mean depth %.2f" % (st.mean(r["score"] for r in rs), st.mean(r["max_depth"] for r in rs)))

# ---------------- continuation value -----------------
# For a death at max depth d with XL x: V = mean final score (and depth) of games that reached depth d+1 having been
# at depth d with XL in the same bucket (XL when entering depth d, from level_stats). Fallback: all with depth > d.


def xb(x):
    return 0 if x <= 5 else 1 if x <= 8 else 2 if x <= 10 else 3


def depth_entry_xl(r, d):
    """XL when first entering a main-dungeon/any level of depth d (level_stats key = (dnum, dlvl))."""
    best = None
    for ls in r.get("level_stats") or []:
        if ls["key"][1] == d and (best is None or ls["entered"] < best["entered"]):
            best = ls
    return best["xl"] if best else None


cont = collections.defaultdict(list)
for r in rs:
    md = r["max_depth"]
    for ls in r.get("level_stats") or []:
        d = ls["key"][1]
        if d < md:
            cont[(d, xb(ls["xl"]))].append((r["score"], md, r["seed"], r["set"]))
contd = collections.defaultdict(list)
for r in rs:
    for d in range(1, r["max_depth"]):
        contd[d].append((r["score"], r["max_depth"]))


def V(d, x):
    # dedupe per game
    lst = {(s, se): (sc, md) for sc, md, s, se in cont.get((d, xb(x)), [])}
    if len(lst) >= 15:
        v = list(lst.values())
    else:
        v = contd.get(d, [])
    if not v:
        return None, None
    return st.mean(a for a, b in v), st.mean(b for a, b in v)


for r in dead:
    vs, vd = V(r["max_depth"], r["xl"])
    r["lost_s"] = max(0.0, vs - r["score"]) if vs else 0.0
    r["lost_d"] = max(0.0, vd - r["max_depth"]) if vd else 0.0

# ---------------- per-killer situation -----------------


def situation(r):
    h = r.get("hist") or []
    if not h:
        return None
    last = h[-1]
    mx = max(x[2] for x in h[-10:])
    # burst: ticks from the last time HP >= 50% to the end
    i = len(h) - 1
    while i > 0 and h[i][1] < 0.5 * h[i][2]:
        i -= 1
    hp_window = h[-10:]
    drop10 = (hp_window[0][1] - last[1]) / max(1, last[2])
    turns_below_half = last[0] - h[i][0]
    low = [x for x in h if x[1] < x[2] / 3]
    could_pray_low = any(x[5] for x in low) if low else None
    adj = max(x[3] for x in h[-5:])
    near_st = any(x[9] <= 1 for x in h[-8:])
    on_st = any(x[10] for x in h[-8:])
    speeds = [a[2] for x in h[-5:] for a in x[11] if a[2]]
    fast = max(speeds) if speeds else None
    msgs = " ".join(r.get("last_msgs") or [])
    elb = bool(re.search(r"Elbereth|engrave|write in the", msgs)) or r.get("elb_engraves", 0) > 0 and False
    prayed = bool(re.search(r"You begin praying", msgs))
    return dict(drop10=drop10, tbh=turns_below_half, cplow=could_pray_low, adj=adj, near_st=near_st, on_st=on_st,
                fast=fast, elb=elb, prayed=prayed, hp_last=last[1] / max(1, last[2]), xl=last[7], ac=last[8],
                maxhp=last[2])


for r in dead:
    r["sit"] = situation(r)

sc_total = sum(r["score"] for r in rs)
print("\n=== TOP KILLERS (cause) ===")
print(f"{'cause':26s} {'n':>4s} {'%':>5s} {'dep':>4s} {'xl':>3s} {'score':>6s} {'lost/g':>7s} {'gain_s':>6s} {'gain_d':>6s} "
      f"{'burst':>5s} {'adj':>4s} {'cpray':>5s} {'prayd':>5s} {'stair':>5s} {'fast':>4s} {'elbE':>4s}")


def table(key):
    g = collections.defaultdict(list)
    for r in dead:
        g[r[key]].append(r)
    out = []
    for k, L in g.items():
        out.append((sum(r["lost_s"] for r in L), k, L))
    out.sort(reverse=True)
    for tot, k, L in out[:30]:
        S = [r["sit"] for r in L if r["sit"]]
        def m(f):
            v = [f(s) for s in S if f(s) is not None]
            return st.mean(v) if v else float("nan")
        print(f"{k[:26]:26s} {len(L):4d} {100*len(L)/N:5.1f} {st.median(r['max_depth'] for r in L):4.0f} "
              f"{st.median(r['xl'] for r in L):3.0f} {st.mean(r['score'] for r in L):6.0f} {tot/len(L):7.0f} "
              f"{tot/N:6.0f} {sum(r['lost_d'] for r in L)/N:6.2f} "
              f"{m(lambda s: s['tbh'] <= 3):5.2f} {m(lambda s: s['adj']):4.1f} {m(lambda s: s['cplow']):5.2f} "
              f"{m(lambda s: s['prayed']):5.2f} {m(lambda s: s['near_st'] or s['on_st']):5.2f} "
              f"{m(lambda s: (s['fast'] or 0) > 12):4.2f} {m(lambda s: s['elb']):4.2f}")
    return out


print("(burst = <=3 turns from HP>=50% to death; adj = max adjacent hostiles in last 5 ticks; cpray = could pray "
      "while HP<1/3; prayd = prayed in last msgs; stair = on/next to stairs in last 8 ticks; fast = an adjacent "
      "monster faster than 12; elbE = Elbereth/engrave in last msgs; lost/g = continuation value - score; gain_s "
      "= mean-score gain over ALL games if removed; gain_d = same for depth)")
table("cause")
print("\n=== BY FAMILY ===")
table("fam")
print("total lost (all deaths) per game: score %.0f depth %.2f" % (sum(r["lost_s"] for r in dead) / N,
                                                               sum(r["lost_d"] for r in dead) / N))

# ---------------- phases -----------------
print("\n=== PHASE BUCKETS (depth at death x XL) top killers ===")


def db(d):
    return "D1-4" if d <= 4 else "D5-9" if d <= 9 else "D10-14" if d <= 14 else "D15-20" if d <= 20 else "D21+"


ph = collections.defaultdict(list)
for r in dead:
    ph[(db(r["max_depth"]), ["XL1-5", "XL6-8", "XL9-10", "XL11+"][xb(r["xl"])])].append(r)
for k in sorted(ph, key=lambda k: (["D1-4", "D5-9", "D10-14", "D15-20", "D21+"].index(k[0]), k[1])):
    L = ph[k]
    c = collections.Counter(r["fam"] for r in L).most_common(6)
    print(f"{k[0]:7s} {k[1]:6s} n={len(L):4d} ({100*len(L)/N:4.1f}%) lost/g={sum(r['lost_s'] for r in L)/N:5.0f}  "
          + ", ".join(f"{a} {b}" for a, b in c))

# ---------------- fountain -----------------
print("\n=== FOUNTAIN / EXCALIBUR ===")
fd = [r for r in dead if r["fam"] == "FOUNTAIN"]
print("fountain deaths", len(fd), "of", N, "median xl", st.median(r["xl"] for r in fd), "xl hist",
      sorted(collections.Counter(r["xl"] for r in fd).items()))
print("  dips in those games: median", st.median(r.get("dips", 0) for r in fd), " had excalibur already:",
      sum(1 for r in fd if r.get("excalibur")), " turn median", st.median(r["turns"] for r in fd),
      " depth median", st.median(r["max_depth"] for r in fd))
print("  HP at last hist tick (frac) median", st.median(r["sit"]["hp_last"] for r in fd if r["sit"]),
      " maxhp median", st.median(r["maxhp"] for r in fd))
ev = collections.Counter(e[1] for r in rs for e in r.get("dip_events") or [])
print("  dip events all games:", ev.most_common())
# how the deaths happen: what message?
print("  last-msg kinds:", collections.Counter(
    "quaff" if re.search(r"drink|quaff|sip", " ".join(r["last_msgs"])) else "dip" if re.search(r"dip|Dip", " ".join(r["last_msgs"])) else "-" for r in fd))
ex = [r for r in rs if r.get("excalibur")]
nex = [r for r in rs if not r.get("excalibur")]
print(f"  games with Excalibur {len(ex)} mean score {st.mean(r['score'] for r in ex):.0f} depth "
      f"{st.mean(r['max_depth'] for r in ex):.2f} | without {len(nex)} {st.mean(r['score'] for r in nex):.0f} "
      f"{st.mean(r['max_depth'] for r in nex):.2f}")
dippers = [r for r in rs if r.get("dips")]
print("  games that dipped:", len(dippers), " got Excalibur", sum(1 for r in dippers if r.get("excalibur")),
      " died to fountain", sum(1 for r in dippers if r["fam"] == "FOUNTAIN"))
for lo, hi in ((1, 4), (5, 5), (6, 6), (7, 8), (9, 30)):
    L = [r for r in fd if lo <= r["xl"] <= hi]
    print(f"   fountain death XL {lo}-{hi}: {len(L)}")
# fountain deaths after excalibur: dipping for what?
post = [r for r in fd if r.get("excalibur")]
print("  fountain deaths after Excalibur:", len(post), " examples:", [(r["seed"], r["excalibur"], r["turns"],
                                                                        r["last_msgs"][-3:]) for r in post[:3]])
pre = [r for r in fd if not r.get("excalibur")]
print("  fountain deaths before Excalibur:", len(pre), " xl median", st.median([r['xl'] for r in pre]) if pre else None,
      " example msgs:", [r["last_msgs"][-4:] for r in pre[:2]])

# ---------------- starvation -----------------
print("\n=== STARVATION ===")
sv = [r for r in dead if r["cause"] == "starvation"]
print("n", len(sv), "prayers used median", st.median(r["prayers"] for r in sv),
      "turns since last prayer median", st.median(r["turns"] - (r.get("last_pray") or 0) for r in sv),
      " never prayed", sum(1 for r in sv if not r["prayers"]), " god_angry", sum(1 for r in sv if r.get("god_angry")),
      " pray_failed>0", sum(1 for r in sv if r.get("pray_failed")))
print("  hunger turns (median of weak+fainting)", st.median(r["hunger_turns"].get("weak", 0) + r["hunger_turns"].get("fainting", 0) for r in sv))
print("  dlvl at death:", sorted(collections.Counter(r["hist"][-1][6] if r["hist"] else 0 for r in sv).items()))
print("  turns on the death level (median)", st.median(
    max((ls["turns"] for ls in r["level_stats"] if ls["key"][1] == (r["hist"][-1][6] if r["hist"] else 0)), default=0) for r in sv))
print("  eaten corpses median", st.median(r.get("corpses", 0) for r in sv), " food_picked median",
      st.median(r.get("food_picked", 0) or 0 for r in sv))
print("  last msgs sample:", [r["last_msgs"][-6:-2] for r in sv[:4]])
print("  sokoban dnum at death:", collections.Counter(r["dnum"] for r in sv))

# ---------------- other self-inflicted -----------------
print("\n=== OTHER SELF-INFLICTED ===")
for lab in ("bad prayer", "food poisoning/illness", "own wand exploded", "trap", "angered law", "drowning",
            "Medusa gaze", "mind flayer psychic", "shopkeeper", "watchman", "watch captain", "aligned priest"):
    L = [r for r in dead if r["cause"] == lab]
    if L:
        print(f"{lab:24s} {len(L):4d}  lost/g {sum(r['lost_s'] for r in L)/N:5.0f}  ex: " +
              " | ".join(f"{r['seed']}:{r['last_msgs'][-2][:70]}" for r in L[:2]))
pk = sum(1 for r in rs if re.search(r"You hear the shrieks|You kill the poor|You murderer|You hear the studio", " ".join(r["last_msgs"])))
print("peaceful_hits total", sum(sum((r.get("peaceful_hits") or {}).values()) for r in rs) if rs and isinstance(rs[0].get("peaceful_hits"), dict) else None)
print("deadly_prayers sum", sum(r.get("deadly_prayers", 0) for r in rs), " pray_failed sum", sum(r.get("pray_failed", 0) for r in rs),
      " god_angry games", sum(1 for r in rs if r.get("god_angry")))

# ---------------- time and keys -----------------
print("\n=== TIME / KEYS ===")
tb = collections.Counter()
for r in rs:
    tb.update(r.get("time_by") or {})
T = sum(tb.values())
print("turns by activity (share):", ", ".join(f"{k} {100*v/T:.1f}%" for k, v in tb.most_common(18)))
print("keys/turn overall %.2f   median keys %d   truncated %d" % (sum(r.get("steps", 0) for r in rs) / max(1, sum(r.get("turns", 0) for r in rs)),
                                                                    st.median(r.get("steps", 0) for r in rs), sum(1 for r in rs if r.get("truncated"))))
kpt = [(r["steps"] / max(1, r["turns"]), r) for r in rs if r.get("turns")]
kpt.sort(key=lambda x: -x[0])
print("keys/turn pctiles", [round(np.percentile([a for a, _ in kpt], p), 2) for p in (10, 50, 90, 99)])
# regress keys/turn on activity shares
acts = [k for k, _ in tb.most_common(14)]
X = np.array([[(r.get("time_by") or {}).get(a, 0) for a in acts] for _, r in kpt])
y = np.array([r["steps"] for _, r in kpt])
coef, *_ = np.linalg.lstsq(X, y, rcond=None)
print("keys per turn of activity (least squares on games):", ", ".join(f"{a} {c:.1f}" for a, c in zip(acts, coef)))
lp = [r for r in rs if r.get("loops")]
print("games with loops>0:", len(lp), " loop_by:", sum((collections.Counter(r.get("loop_by") or {}) for r in lp), collections.Counter()).most_common(8))
tr = [r for r in rs if r.get("truncated")]
if tr:
    print("truncated: depth median", st.median(r["max_depth"] for r in tr), " turns median", st.median(r["turns"] for r in tr),
          " score mean", round(st.mean(r["score"] for r in tr)), " top activities",
          sum((collections.Counter(r["time_by"]) for r in tr), collections.Counter()).most_common(5))
# stuck levels
stuck = []
for r in rs:
    for ls in r.get("level_stats") or []:
        if ls["turns"] >= 3000:
            stuck.append((r, ls))
print("level visits >= 3000 turns:", len(stuck), " by depth:", sorted(collections.Counter(ls["key"][1] for _, ls in stuck).items()))
print("  of which down stairs known:", sum(ls["down_known"] for _, ls in stuck), " search share median",
      st.median(ls["search"] / ls["turns"] for _, ls in stuck) if stuck else None, " desperate", sum(ls["desperate"] for _, ls in stuck))
sh = [(r, ls) for r, ls in stuck if ls["key"][1] < 20]
print("  stuck (>=3000 turns) above depth 20:", len(sh), " down_known", sum(ls["down_known"] for _, ls in sh),
      " dnum", collections.Counter(ls["key"][0] for _, ls in sh))
for r, ls in sh[:8]:
    print("    ", r["seed"], ls, "final depth", r["max_depth"])
# turns by depth
tdepth = collections.Counter()
for r in rs:
    for ls in r.get("level_stats") or []:
        tdepth[db(ls["key"][1])] += ls["turns"]
print("turns by depth bucket:", {k: round(v / N) for k, v in tdepth.items()})
srch = collections.Counter()
for r in rs:
    for ls in r.get("level_stats") or []:
        srch[db(ls["key"][1])] += ls["search"]
print("search turns by depth bucket (per game):", {k: round(v / N) for k, v in srch.items()})

# ---------------- survivors -----------------
print("\n=== PREDICTORS (alive at checkpoint; success = max_depth>=15) ===")


def snap_at(r, t):
    for s in r.get("snaps") or []:
        if s["t"] >= t:
            return s
    return None


def check(name, pick):
    rows = []
    for r in rs:
        s = pick(r)
        if s is None:
            continue
        rows.append((s, r))
    if not rows:
        return
    ok = [x for x in rows if x[1]["max_depth"] >= 15]
    no = [x for x in rows if x[1]["max_depth"] < 15]
    print(f"-- {name}: alive {len(rows)}, later D15+ {len(ok)} ({100*len(ok)/len(rows):.0f}%)")
    for f in ("xl", "ac", "maxhp", "dlvl", "max_depth", "prayers", "pet", "gold", "kills", "excal"):
        a = [float(s.get(f, 0) or 0) for s, _ in ok]
        b = [float(s.get(f, 0) or 0) for s, _ in no]
        allv = np.array([float(s.get(f, 0) or 0) for s, _ in rows])
        yy = np.array([r["max_depth"] >= 15 for _, r in rows], float)
        cor = np.corrcoef(allv, yy)[0, 1] if allv.std() > 0 else 0
        print(f"   {f:9s} D15+ {st.mean(a):7.2f}  others {st.mean(b):7.2f}  corr {cor:+.2f}")
    return rows


def with_excal(r, s):
    if s is None:
        return None
    s = dict(s)
    s["excal"] = 1 if r.get("excalibur") and r["excalibur"] <= s["t"] else 0
    return s


check("turn 3000", lambda r: with_excal(r, snap_at(r, 3000)) if r["turns"] > 3000 else None)
check("turn 6000", lambda r: with_excal(r, snap_at(r, 6000)) if r["turns"] > 6000 else None)


def at_depth(r, d):
    ents = [ls for ls in r.get("level_stats") or [] if ls["key"][1] == d]
    if not ents:
        return None
    e = min(ents, key=lambda ls: ls["entered"])
    s = snap_at(r, e["entered"]) or {}
    s = dict(s)
    s["xl"] = e["xl"]
    s["t_arrive"] = e["entered"]
    s["t"] = e["entered"]
    return with_excal(r, s)


rows5 = check("arrival Dlvl 5", lambda r: at_depth(r, 5))
rows10 = check("arrival Dlvl 10", lambda r: at_depth(r, 10))
# XL at arrival -> P(D15+) and mean score
for name, rows in (("Dlvl5", rows5), ("Dlvl10", rows10)):
    print(f"   {name}: XL at arrival -> n, P(D15+), mean final score, mean max depth")
    g = collections.defaultdict(list)
    for s, r in rows:
        g[min(s["xl"], 14)].append(r)
    for x in sorted(g):
        L = g[x]
        print(f"     XL {x:2d}: {len(L):4d}  {100*sum(r['max_depth']>=15 for r in L)/len(L):3.0f}%  "
              f"{st.mean(r['score'] for r in L):6.0f}  {st.mean(r['max_depth'] for r in L):5.1f}")
    g = collections.defaultdict(list)
    for s, r in rows:
        if s.get("ac") is not None:
            g[max(-6, min(int(s["ac"]), 8)) // 2 * 2].append(r)
    print(f"   {name}: AC (snap before) -> n, P(D15+), mean score")
    for x in sorted(g):
        L = g[x]
        print(f"     AC {x:3d}: {len(L):4d}  {100*sum(r['max_depth']>=15 for r in L)/len(L):3.0f}%  {st.mean(r['score'] for r in L):6.0f}")
    g = collections.defaultdict(list)
    for s, r in rows:
        g[s.get("excal", 0)].append(r)
    for x in sorted(g):
        L = g[x]
        print(f"     Excalibur={x}: {len(L):4d}  {100*sum(r['max_depth']>=15 for r in L)/len(L):3.0f}%  {st.mean(r['score'] for r in L):6.0f}")
    g = collections.defaultdict(list)
    for s, r in rows:
        tt = s["t_arrive"]
        g[0 if tt < 2000 else 1 if tt < 4000 else 2 if tt < 7000 else 3].append(r)
    print(f"   {name}: arrival turn -> n, P(D15+), mean score")
    for x in sorted(g):
        L = g[x]
        print(f"     {['<2k','2-4k','4-7k','7k+'][x]:5s}: {len(L):4d}  {100*sum(r['max_depth']>=15 for r in L)/len(L):3.0f}%  {st.mean(r['score'] for r in L):6.0f}")

# ---------------- odd -----------------
print("\n=== ODD ===")
cr = [r for r in rs if r.get("crash")]
print("crashes", len(cr), [c["crash"][-160:] for c in cr[:3]])
rep = 0
for r in rs:
    m = r.get("last_msgs") or []
    if len(m) >= 6 and len(set(m[-6:])) == 1:
        rep += 1
print("games whose last 6 messages are identical:", rep)
print("max_depth < depth in hist (impossible):", sum(1 for r in rs if r.get("hist") and max(x[6] for x in r["hist"]) > r["max_depth"]))
print("score 0 non-crash:", sum(1 for r in rs if r["score"] == 0 and not r.get("crash")))
print("resets sum", sum(r.get("resets", 0) or 0 for r in rs), " desperate games", sum(1 for r in rs if r.get("desperate")))
msgc = collections.Counter()
for r in rs:
    for m in set(r.get("last_msgs") or []):
        if "mysterious force prevents" in m:
            msgc["mysterious force (tengu/unicorn teleport spam)"] += 1
        if "You stop searching" in m:
            msgc["You stop searching"] += 1
        if "fiery gaze" in m:
            msgc["pyrolisk gaze"] += 1
        if "can't" in m or "cannot" in m:
            msgc["can't/cannot"] += 1
print(msgc)
