import json, sys, collections, statistics as st
rs = [json.loads(l) for l in open(sys.argv[1])]
dead = [r for r in rs if not r["truncated"] and r["hist"]]
cat = collections.Counter(); rows = []
for r in dead:
    h = r["hist"]
    # final fight: walk back over ticks with an adjacent hostile (allow 2-tick gaps)
    i, gap = len(h) - 1, 0
    while i > 0:
        if h[i - 1][3] > 0: gap = 0
        else:
            gap += 1
            if gap > 2: break
        i -= 1
    fight = h[i:]
    if not any(x[3] for x in fight):
        cat["no melee at death (ranged/unseen/other)"] += 1; continue
    dp = next((x for x in fight if x[1] < 0.5 * x[2]), fight[0])
    stalk = any(a[1] for x in fight for a in x[11])
    fast = max((a[2] or 12) for x in fight for a in x[11]) if any(x[11] for x in fight) else 12
    on_st_ok = any(x[10] and x[1] >= 0.25 * x[2] for x in fight)
    d = dp[9]
    dl1_only = dp[6] == 1
    if stalk:
        c = "adjacent stalker (follows)"
    elif on_st_ok:
        c = "A: stood on stairs during fight with HP>=25%"
    elif d <= 2:
        c = "B: stairs 1-2 steps away at HP<50%"
    elif d <= 6:
        c = "C: stairs 3-6 steps away"
    elif d < 99:
        c = "D: stairs 7+ away"
    else:
        c = "E: no stairs known"
    cat[c] += 1
    rows.append((c, r["seed"], r["role"], dp[6], f"{dp[1]}/{dp[2]}", d, len(fight), [a[0] for a in dp[11]], fast))
print("deaths", len(dead))
for k, v in sorted(cat.items()): print(f"  {v:3d}  {k}")
print("\nfight length (ticks) median:", st.median(x[6] for x in rows))
for c in ("A", "B"):
    print(f"\n-- examples {c}")
    for x in [x for x in rows if x[0].startswith(c)][:8]: print("  ", x[1:])
