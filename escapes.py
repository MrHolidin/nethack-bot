import json, sys, collections
rs = [json.loads(l) for l in open(sys.argv[1])]
inc = []
for r in rs:
    log = r["escape_log"]
    for i, e in enumerate(log):
        if e["hops"] != 0:
            continue
        chain = [e] + [x for x in log[i + 1:i + 3] if x["hops"] > 0 and x["t"] - e["t"] < 100]
        returned = "returned_hp" in e or any("returned_hp" in x for x in chain)
        died_soon = (r["turns"] - e["t"]) < 150 and not r["truncated"]
        inc.append(dict(seed=r["seed"], role=r["role"], t=e["t"], hp=f'{e["hp"]}/{e["max"]}', dir=e["dir"],
                        adj=e["adj"], hop=len(chain) - 1, returned=returned, died_soon=died_soon))
c = collections.Counter((x["returned"], x["died_soon"]) for x in inc)
print("games with escapes", len({x["seed"] for x in inc}), " incidents", len(inc))
print(f"  healed+returned, alive 150t later: {c[(True, False)]}\n  healed+returned, died <150t:      {c[(True, True)]}"
      f"\n  not returned, died <150t:         {c[(False, True)]}\n  not returned, alive:              {c[(False, False)]}")
print("  dir", dict(collections.Counter(x["dir"] for x in inc)), " hopped back", sum(x["hop"] for x in inc))
print("  fled from:", collections.Counter(n for x in inc for n in x["adj"]).most_common(10))
for x in [x for x in inc if x["died_soon"] and not x["returned"]][:8]:
    print("   ", x)
