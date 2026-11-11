"""diag part 3: fountain lethality by XL/HP before the event; prayer gap at death; search efficiency."""
import collections, re, statistics as st
import load
from main import rs, dead, N

print("\n\n######## PART 3 ########")
by = collections.defaultdict(lambda: [0, 0])
byhp = collections.defaultdict(lambda: [0, 0])
for r in rs:
    for e in r.get("dip_events") or []:
        if e[1] != "demon":
            continue
        s = None
        for x in r["snaps"]:
            if x["t"] <= e[0]:
                s = x
        x = s["xl"] if s else 1
        died = r["fam"] == "FOUNTAIN" and r["turns"] - e[0] < 80
        k = "pre-excal" if not r.get("excalibur") or r["excalibur"] > e[0] else "post-excal"
        by[(k, min(x, 10))][0] += 1
        by[(k, min(x, 10))][1] += died
        mh = s["maxhp"] if s else 16
        byhp[(mh // 15) * 15][0] += 1
        byhp[(mh // 15) * 15][1] += died
print("demon/moccasin events by (phase, XL at the snapshot BEFORE): n, died <80 turns later")
for k in sorted(by):
    n, d = by[k]
    print(f"   {k}: {n:4d} {d:4d}  {100*d/max(1,n):3.0f}%")
print("by max HP (snap before):", sorted((k, v[0], v[1], round(100 * v[1] / v[0])) for k, v in byhp.items()))
# which one: demon vs moccasin per XL
fd = [r for r in dead if r["fam"] == "FOUNTAIN"]
print("fountain deaths demon/moccasin by final XL:", sorted(collections.Counter((r["cause"][6:], r["xl"]) for r in fd).items()))
print("fountain deaths: was Elbereth/upstairs used? elbE", sum(1 for r in fd if re.search("Elbereth|engrave", " ".join(r["last_msgs"]))),
      " on/near stairs", sum(1 for r in fd if r["sit"] and (r["sit"]["near_st"] or r["sit"]["on_st"])),
      " ticks of fight median", st.median(len([x for x in r["hist"] if x[3]]) for r in fd))

# prayer gap at death, timeout class
gaps = []
for r in dead:
    h = r.get("hist") or []
    if h and not h[-1][5] and not r.get("god_angry") and r.get("last_pray"):
        gaps.append(r["turns"] - r["last_pray"])
gaps.sort()
print("\nprayer-timeout deaths: turns since last prayer: n", len(gaps), " pctiles",
      [gaps[int(len(gaps) * p)] for p in (0.1, 0.25, 0.5, 0.75, 0.9)],
      " share in 200..500:", round(sum(1 for g in gaps if 200 <= g <= 500) / len(gaps), 2),
      " share <200:", round(sum(1 for g in gaps if g < 200) / len(gaps), 2))
nev = [r for r in dead if r.get("hist") and not r["hist"][-1][5] and not r.get("god_angry") and not r.get("last_pray")]
print("   never prayed but can_pray False at end (t<=100?):", len(nev))
# how fast did these die: hp at last tick of hist vs prayer threshold
# search efficiency
sk = []
for r in rs:
    tb = r.get("time_by") or {}
    sk.append((tb.get("search", 0), r["steps"], r["turns"]))
print("\nsearch: total search turns", sum(a for a, _, _ in sk), " share", round(sum(a for a, _, _ in sk) / sum(c for _, _, c in sk), 3))
tr = [r for r in rs if r.get("truncated")]
print("truncated games:", len(tr), " keys/turn", [round(r["steps"] / r["turns"], 1) for r in tr][:15],
      " search share", [round(r["time_by"].get("search", 0) / r["turns"], 2) for r in tr][:15])
print("  truncated dlvl at end:", collections.Counter(r["hist"][-1][6] if r["hist"] else 0 for r in tr))
# games with keys/turn > 4: which activity dominates
hi = [r for r in rs if r["steps"] / max(1, r["turns"]) > 4]
print("games with keys/turn > 4:", len(hi), " their top activity:",
      collections.Counter(max(r["time_by"], key=r["time_by"].get) for r in hi if r["time_by"]).most_common(5),
      " mean score", round(st.mean(r["score"] for r in hi)) if hi else None)
# loops
lp = [r for r in rs if r.get("loops")]
print("loops>0 games", len(lp), " loops sum", sum(r["loops"] for r in lp), " mean score", round(st.mean(r["score"] for r in lp)),
      " vs all", round(st.mean(r["score"] for r in rs)), " max loops", max(r["loops"] for r in lp))
# medusa: deep games stuck where
deep = [r for r in rs if r["max_depth"] >= 21]
stk = collections.Counter()
for r in deep:
    ls = max(r["level_stats"], key=lambda l: l["turns"])
    stk[(ls["key"][1], ls["down_known"])] += 1
print("deep games: the level with most turns (depth, down_known):", stk.most_common(10))
# repeated identical last messages: what
rep = collections.Counter()
for r in rs:
    m = r.get("last_msgs") or []
    if len(m) >= 6 and len(set(m[-6:])) == 1:
        rep[m[-1][:60]] += 1
print("identical last-6 messages:", rep.most_common(8))
