"""Load result rows for the diag analysis: base22_80k/81k (older base) + base_d1/base_d2 (jsonl or .parts), and a
better death cause than eval.death_cause (all last_msgs, hist fallback)."""
import glob, json, os, re

RES = "/workspace/nh/results"
AG = "/workspace/agents/diag"


def rows(sets=("base22_80k", "base22_81k", "base_d1", "base_d2")):
    out = []
    for s in sets:
        p = f"{RES}/{s}.jsonl" if os.path.exists(f"{RES}/{s}.jsonl") else f"{AG}/{s}.jsonl"
        if os.path.exists(p):
            rs = [json.loads(l) for l in open(p)]
        else:
            rs = [json.load(open(f)) for f in sorted(glob.glob(f"{RES}/{s}.parts/*.json"))]
        for r in rs:
            r["set"] = s
        out += rs
    return out


ATTACK = (r"(?:hits|bites|stings|kicks|butts|touches|claws|thrusts|swings|shoots|zaps|breathes|explodes|casts|"
          r"strikes|grabs|crushes|engulfs|squeezes|spits|throws|fires|gazes|whips|swallows|digests|lashes|slashes|"
          r"stabs|tickles|hugs|drowns|blinds|pecks|nibbles|misses|summons|curses|kisses|reaches)")
RAYS = ("bolt of lightning", "bolt of fire", "bolt of cold", "death ray", "sleep ray", "magic missile")
PATS = [(r"faint from lack of food|starv", "starvation"),
        (r"You drown|You sink like|You try to crawl out of the water", "drowning"),
        (r"Keystone Kop|You murderer|under arrest", "angered law"),
        (r"water moccasin", "water moccasin"),
        (r"water demon", "water demon"),
        (r"Your limbs are stiffening|You are slowing down|turn to stone|You are a statue", "stoning"),
        (r"You feel deathly sick|You are dying from", "illness"),
        (r"The poison was deadly|Rotten food", "poison"),
        ]


def cause(r):
    if r.get("crash"):
        return "CRASH"
    if r.get("truncated"):
        return "TRUNCATED"
    msgs = r.get("last_msgs") or []
    txt = " ".join(msgs)
    tail = " ".join(msgs[-4:])
    for pat, lab in PATS[:3]:
        if re.search(pat, tail):
            return lab
    named = [x for x in re.findall(r"(?:The|the) ([a-zA-Z \-']+?) " + ATTACK, tail) if x not in RAYS]
    for pat, lab in PATS[3:]:
        if re.search(pat, tail):
            return lab
    if named:
        return clean(named[-1])
    if re.search(r"bolt of|blast of|death ray|magic missile", tail):
        return "ray(unknown src)"
    named = [x for x in re.findall(r"(?:The|the) ([a-zA-Z \-']+?) " + ATTACK, txt) if x not in RAYS]
    if named:
        return clean(named[-1])
    h = r.get("hist") or []
    for x in reversed(h[-5:]):
        if x[11]:
            return clean(x[11][0][0]) + "(hist)"
    if re.search(r"\bIt \w+|You hit it|You miss it", txt):
        return "unseen"
    return "?"


def clean(n):
    n = n.strip()
    for p in ("poor ", "tame ", "peaceful ", "invisible "):
        if n.startswith(p):
            n = n[len(p):]
    return n
