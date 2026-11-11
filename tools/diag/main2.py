"""diag part 2: prayer state at death, god anger, fountain timing, shallow stuck levels, deep killers."""
import collections, re, statistics as st, sys
import load
from main import rs, dead, N, cause  # noqa: reuses the classification (prints part 1 again; redirect)

print("\n\n######## PART 2 ########")


def crit(hp, maxhp, xl):
    rank = 0 if xl <= 2 else (xl + 2) // 4
    div = 5 if rank <= 1 else 6 if rank <= 3 else 7 if rank <= 5 else 8 if rank <= 7 else 9
    return hp <= 5 or hp * div <= min(maxhp, 15 * xl)


cls = collections.Counter()
bycause = collections.defaultdict(collections.Counter)
for r in dead:
    h = r.get("hist") or []
    if not h:
        continue
    last = h[-1]
    msgs = " ".join(r["last_msgs"])
    if r.get("god_angry"):
        k = "god angry"
    elif re.search(r"You begin praying", msgs):
        k = "prayed in last msgs (still died)"
    elif not last[5]:
        k = "prayer timeout (can_pray False at end)"
    elif crit(last[1], last[2], last[7]):
        k = "critical+can_pray at last tick but no prayer?"
    else:
        k = "can_pray, killed from above prayer threshold (burst)"
    cls[k] += 1
    bycause[r["fam"]][k] += 1
print("prayer state at death:", cls.most_common())
for f in ("FOUNTAIN", "ants/bees", "elves", "trolls", "unseen/blind melee", "orcs", "soldiers", "gargoyles", "leocrotta",
          "mumak"):
    print(f"   {f:20s}", dict(bycause[f]))
pf = [r for r in dead if re.search(r"You feel that \w+ is displeased|Thou hast angered|You feel guilty|smited|is displeased",
                                    " ".join(r["last_msgs"]))]
print("deaths with a failed/early prayer in last msgs:", len(pf))
ga = [r for r in rs if r.get("god_angry")]
nga = [r for r in rs if not r.get("god_angry")]
print(f"god_angry games {len(ga)} mean score {st.mean(r['score'] for r in ga):.0f} depth {st.mean(r['max_depth'] for r in ga):.1f}"
      f" causes {collections.Counter(r['fam'] for r in ga).most_common(6)}")
print("   prayers in angry games median", st.median(r["prayers"] for r in ga), " deadly_prayers>0:",
      sum(1 for r in ga if r.get("deadly_prayers")), " pray_failed>0:", sum(1 for r in ga if r.get("pray_failed")))
# prayer count distribution vs outcome
pc = collections.defaultdict(list)
for r in rs:
    pc[min(r["prayers"], 8)].append(r)
print("   prayers -> n, god_angry share, mean turns:", [(k, len(v), round(sum(1 for r in v if r.get("god_angry")) / len(v), 2),
                                                        round(st.mean(r["turns"] for r in v))) for k, v in sorted(pc.items())])

print("\n--- fountain timing")
ex = [r for r in rs if r.get("excalibur")]
fx = collections.Counter()
for r in ex:
    s = next((s for s in r["snaps"] if s["t"] >= r["excalibur"]), None)
    fx[s["xl"] if s else -1] += 1
print("XL at the snapshot after Excalibur:", sorted(fx.items()))
fd = [r for r in dead if r["fam"] == "FOUNTAIN"]
print("fountain deaths: depth at death", sorted(collections.Counter(r["hist"][-1][6] for r in fd if r["hist"]).items()))
print("  maxhp at death median", st.median(r["maxhp"] for r in fd), " AC median", st.median(r["ac"] for r in fd))
print("  demon events per game (dip_events 'demon') in fountain-death games:",
      st.mean(sum(1 for e in r.get("dip_events") or [] if e[1] == "demon") for r in fd))
tot_demon = sum(sum(1 for e in r.get("dip_events") or [] if e[1] == "demon") for r in rs)
print("  'demon' events (demon or moccasins) total", tot_demon, " -> deaths", len(fd), f" ({100*len(fd)/max(1,tot_demon):.0f}% lethal)")
# survival rate of demon event by XL
by = collections.defaultdict(lambda: [0, 0])
for r in rs:
    for e in r.get("dip_events") or []:
        if e[1] == "demon":
            s = next((s for s in r["snaps"] if s["t"] >= e[0]), None)
            x = s["xl"] if s else r["xl"]
            died = r["fam"] == "FOUNTAIN" and r["turns"] - e[0] < 60
            by[min(x, 10)][0] += 1
            by[min(x, 10)][1] += died
print("  demon/moccasin events by XL (snap after): n, died within 60 turns:", sorted((k, v[0], v[1]) for k, v in by.items()))
dips_per = [sum(1 for e in r.get("dip_events") or [] if e[0] <= r["excalibur"]) for r in ex]
print("  dips until Excalibur: mean", round(st.mean(dips_per), 1), " (theory 6)")
post = [sum(1 for e in r.get("dip_events") or [] if e[0] > r["excalibur"]) for r in ex]
print("  fountain events AFTER Excalibur per Excalibur game: mean", round(st.mean(post), 1), " total", sum(post),
      " kinds", collections.Counter(e[1] for r in ex for e in r.get("dip_events") or [] if e[0] > r["excalibur"]).most_common())
print("  time_by fountain_wish total turns", sum((r.get("time_by") or {}).get("fountain_wish", 0) for r in rs),
      " wishes from fountains", sum(1 for r in rs for e in r.get("dip_events") or [] if e[1] == "wish"))
# fountain deaths: were they dipping for excalibur or quaffing for wish?
k = collections.Counter()
for r in fd:
    if r.get("excalibur"):
        k["after Excalibur"] += 1
    else:
        k["before Excalibur"] += 1
print("  ", k)

print("\n--- stuck shallow levels (>= 3000 turns, depth <= 6)")
sh = []
for r in rs:
    for ls in r.get("level_stats") or []:
        if ls["turns"] >= 3000 and ls["key"][1] <= 6:
            sh.append((r, ls))
c = collections.Counter()
for r, ls in sh:
    died_here = r["hist"] and r["hist"][-1][6] == ls["key"][1] and r["dnum"] == ls["key"][0]
    c[(("mines" if ls["key"][0] == 2 else "soko" if ls["key"][0] == 3 else "main"),
       "down_known" if ls["down_known"] else "no_down", "died_here" if died_here else "left")] += 1
for k, v in sorted(c.items(), key=lambda kv: -kv[1]):
    print("  ", k, v)
print("  games with such a level:", len({r['seed'] for r, _ in sh}), " their mean score",
      round(st.mean(r["score"] for r in {r['seed']: r for r, _ in sh}.values())), " turns spent there per game (all games)",
      round(sum(ls["turns"] for _, ls in sh) / N))
dh = [(r, ls) for r, ls in sh if r["hist"] and r["hist"][-1][6] == ls["key"][1] and r["dnum"] == ls["key"][0]]
print("  died on such a level: causes", collections.Counter(r["fam"] for r, _ in dh).most_common(8))
print("  examples main/no_down:", [(r["seed"], ls["key"], ls["turns"], ls["search"], ls["seen"]) for r, ls in sh
                                   if ls["key"][0] == 0 and not ls["down_known"]][:8])
print("  examples main/down_known/stayed:", [(r["seed"], ls["key"], ls["turns"], ls["search"], ls["seen"], r["max_depth"]) for r, ls in sh
                                   if ls["key"][0] == 0 and ls["down_known"]][:8])

print("\n--- deep games (max_depth >= 21): what ends them")
dp = [r for r in rs if r["max_depth"] >= 21]
print("n", len(dp), "share of score", round(sum(r["score"] for r in dp) / sum(r["score"] for r in rs), 2),
      " causes", collections.Counter(r["fam"] for r in dp).most_common(14))
print("  dlvl at death", sorted(collections.Counter(r["hist"][-1][6] for r in dp if r["hist"]).items()))
print("  turns median", st.median(r["turns"] for r in dp), " search share", round(sum(r["time_by"].get("search", 0) for r in dp) / sum(r["turns"] for r in dp), 2))
md = collections.Counter(r["max_depth"] for r in dp)
print("  max_depth", sorted(md.items()))
print("\n--- descent: XL at first entry of each depth (median)")
for d in (3, 5, 7, 10, 12, 15, 20):
    xs = [min(ls["xl"] for ls in r["level_stats"] if ls["key"][1] == d) for r in rs if any(ls["key"][1] == d for ls in r["level_stats"])]
    ts = [min(ls["entered"] for ls in r["level_stats"] if ls["key"][1] == d) for r in rs if any(ls["key"][1] == d for ls in r["level_stats"])]
    print(f"   D{d}: reached {len(xs)}  XL median {st.median(xs)}  turn median {st.median(ts)}")
print("\n--- unseen/blind melee: blind?")
ub = [r for r in dead if r["fam"] == "unseen/blind melee"]
kk = collections.Counter()
for r in ub:
    m = " ".join(r["last_msgs"])
    kk["blind msg" if re.search(r"blind|can't see|You can see again", m) else "Wait! There's something" if "something there" in m
       else "engulfed/crushed" if re.search(r"crushed|engulf|swallow", m) else "other"] += 1
print(kk, " adj>=3 share", round(sum(1 for r in ub if r["sit"] and r["sit"]["adj"] >= 3) / len(ub), 2),
      " blind_waits median", st.median(r.get("blind_waits", 0) for r in ub))
print(" sample:", [r["last_msgs"][-7:-3] for r in ub[:5]])
