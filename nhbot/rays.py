"""Our own ray coming back at us, and what a hit would do (statistics only: wand_step logs them, decides nothing).

self_hit_prob follows zap.c buzz() (3.6.6) square by square over the map we remember, every random branch weighed:
  * range rn1(7, 7) = 7..13; each square costs 1 (`while (range-- > 0)`), a bounce 1 more (`--range`);
  * a monster on the way (pets too) is hit with zap_hit(its AC): range -= 2, and a silver / chromatic dragon
    reflects the ray straight back; a miss leaves the range alone;
  * our square: zap_hit(our AC) (a miss "whizzes by" and the ray goes on); the first hit is what we count;
  * solid rock (or the map edge) bounces at once, with bchance 10; a wall, tree or raised drawbridge after the
    square is entered, bchance 75 (Mines walls 20); straight rays reverse, a diagonal one reverses with 1/bchance,
    else turns off the open side (both open: 50/50) -- the room / corridor test of buzz() included;
  * a closed door absorbs the ray (zap_over_floor: range -1000); fire over water and cold over water or lava lose
    3 more squares.
Unexplored squares count as solid rock (they mostly are: rock beside a corridor shows blank) -- an overestimate
next to an unlit room.

ray_harm is zhitu() for a wand ray on us: reflection, resistances from the role and what we wear, damage dice,
sleep / blindness, the item classes it can destroy.
"""
import numpy as np
import nle.nethack as nh

from nhbot.consts import COLS, ROWS

# terrain codes for the ray
ROOM, OPEN, WATER, LAVA, WALL, STONE, CLOSED = range(7)

_CMAP = {0: STONE, 12: OPEN, 13: OPEN, 14: OPEN, 15: CLOSED, 16: CLOSED, 17: OPEN, 18: WALL, 21: OPEN, 22: OPEN,
         32: WATER, 34: LAVA, 37: WALL, 38: WALL, 41: WATER}
for _i in range(1, 12):
    _CMAP[_i] = WALL                        # walls and corners (a secret door / corridor looks like one)

REFLECTORS = ("silver dragon", "chromatic dragon")          # muse.c mon_reflects: by species
RANGES = range(7, 14)                                        # rn1(7, 7)


def terrain_code(glyph):
    """Ray terrain of a remembered glyph: an object or monster on it -> room floor."""
    if glyph == nh.GLYPH_CMAP_OFF:
        return STONE
    if nh.glyph_is_cmap(glyph):
        return _CMAP.get(nh.glyph_to_cmap(glyph), ROOM)
    return ROOM


TERRAIN_CODE = np.array([terrain_code(g) for g in range(nh.MAX_GLYPH)], dtype=np.int8)   # glyph -> code


def zap_hit_prob(ac):
    """zap.c zap_hit(ac, 0): chance = rn2(20); 0 -> rnd(10) < ac; else 3 - chance < AC_VALUE(ac), where a negative
    AC counts as -rnd(-ac)."""
    p = 0.0
    for chance in range(20):
        if chance == 0:
            p += sum(1 for r in range(1, 11) if r < ac) / 10
        elif ac >= 0:
            p += 3 - chance < ac
        else:
            p += sum(1 for v in range(1, -ac + 1) if 3 - chance < -v) / -ac
    return p / 20


def _isok(y, x):
    return 0 <= y < ROWS and 1 <= x < COLS                 # isok(): column 0 is never on the map


def _zap_pos(code):
    return code not in (WALL, STONE)


def self_hit_prob(terrain, start, step, monsters, our_ac, kind, mines=False):
    """P(our own ray of `kind` fired from `start` in direction `step` (dy, dx) hits us at least once).
    terrain: ROWS x COLS codes; monsters: {(y, x): (ac, name)} besides us."""
    def code(y, x):
        return terrain[y][x] if _isok(y, x) else STONE

    our_p = zap_hit_prob(our_ac)
    mon_p = {pos: zap_hit_prob(ac) for pos, (ac, _) in monsters.items()}
    total = 0.0
    # state: (y, x, dy, dx, range, weight); the loop body runs while range-- > 0
    stack = [(start[0], start[1], step[0], step[1], r, 1 / len(RANGES)) for r in RANGES]
    while stack:
        y, x, dy, dx, rng, w = stack.pop()
        if rng <= 0 or w < 1e-9:
            continue
        rng -= 1
        ly, lx = y, x
        y, x = y + dy, x + dx
        if code(y, x) != STONE:                            # solid rock / off the map: straight to make_bounce
            if (y, x) in monsters:
                p = mon_p[(y, x)]
                back = any(r in monsters[(y, x)][1] for r in REFLECTORS)
                if p < 1:
                    stack += _bounce_or_go(terrain, ly, lx, y, x, dy, dx, rng, w * (1 - p), kind, mines)
                if p > 0:
                    ndy, ndx = (-dy, -dx) if back else (dy, dx)
                    stack += _bounce_or_go(terrain, ly, lx, y, x, ndy, ndx, rng - 2, w * p, kind, mines)
                continue
            if (y, x) == tuple(start) and rng >= 0:
                total += w * our_p                         # the first hit ends the branch
                w *= 1 - our_p                             # "whizzes by you": on it goes
        stack += _bounce_or_go(terrain, ly, lx, y, x, dy, dx, rng, w, kind, mines)
    return min(total, 1.0)


def ray_walk(terrain, start, step, kind, rng, hit, mines=False):
    """One ray of ours sampled the way buzz() runs it (the rules above, each random branch drawn with `rng`).
    hit(pos) is called at every square the ray enters (our own square included): None when nothing is there,
    else (the ray hit it -- range -= 2, it reflects -- the ray turns straight back)."""
    y, x = start
    dy, dx = step
    r = int(rng.integers(RANGES.start, RANGES.stop))
    while r > 0:
        r -= 1
        ly, lx = y, x
        y, x = y + dy, x + dx
        if (terrain[y][x] if _isok(y, x) else STONE) != STONE:
            got = hit((y, x))
            if got is not None and got[0]:
                r -= 2
                if got[1]:
                    dy, dx = -dy, -dx
        nxt = _bounce_or_go(terrain, ly, lx, y, x, dy, dx, r, 1.0, kind, mines)
        if len(nxt) > 1:
            w = np.array([b[5] for b in nxt])
            nxt = [nxt[int(rng.choice(len(nxt), p=w / w.sum()))]]
        y, x, dy, dx, r = nxt[0][:5]


def beam_walk(terrain, start, step, rng, hit):
    """A wand of striking, bhit(): range rn1(8, 6), one per square and 3 more for each monster on the way (hit or
    missed); it stops at a wall, rock or a closed door and never comes back. hit(pos) as for ray_walk."""
    y, x = start
    dy, dx = step
    r = int(rng.integers(6, 14))
    while r > 0:
        r -= 1
        y, x = y + dy, x + dx
        if not _isok(y, x):
            return
        if hit((y, x)) is not None:
            r -= 3
        if terrain[y][x] in (WALL, STONE, CLOSED):
            return


def _bounce_or_go(terrain, ly, lx, y, x, dy, dx, rng, w, kind, mines):
    c = terrain[y][x] if _isok(y, x) else STONE
    if c != STONE:
        if c == CLOSED:
            return [(y, x, dy, dx, -1000, w)]             # zap_over_floor: the door absorbs it
        if (kind == "fire" and c == WATER) or (kind == "cold" and c in (WATER, LAVA)):
            rng -= 3
        if _zap_pos(c):
            return [(y, x, dy, dx, rng, w)]
    # make_bounce
    rng -= 1
    bchance = 10 if c == STONE else 20 if mines else 75
    if not dy or not dx:
        return [(y, x, -dy, -dx, rng, w)]
    out = [(y, x, -dy, -dx, rng, w / bchance)]
    w *= 1 - 1 / bchance

    def side_ok(cy, cx, ny, nx):
        cc = terrain[cy][cx] if _isok(cy, cx) else STONE
        if not _isok(cy, cx) or not _zap_pos(cc) or cc == CLOSED:
            return False
        return cc == ROOM or (_isok(ny, nx) and _zap_pos(terrain[ny][nx]))
    b1 = side_ok(ly, x, ly, x + dx)                        # levl[sx][lsy]: new column, old row -> dy flips
    b2 = side_ok(y, lx, y + dy, lx)                        # levl[lsx][sy]: old column, new row -> dx flips
    if b1 and b2:
        out += [(y, x, -dy, dx, rng, w / 2), (y, x, dy, -dx, rng, w / 2)]
    elif b1:
        out.append((y, x, -dy, dx, rng, w))
    elif b2:
        out.append((y, x, dy, -dx, rng, w))
    else:
        out.append((y, x, -dy, -dx, rng, w))
    return out


# ------------------------------------------------------------------------------- what a hit does to us
RAY_DICE = {"magic missile": (2, 6), "fire": (6, 6), "cold": (6, 6), "lightning": (6, 6)}
RAY_RESIST = {"magic missile": "magic", "fire": "fire", "cold": "cold", "lightning": "shock", "sleep": "sleep",
              "death": "magic"}
RAY_ITEMS = {"fire": ("scroll", "potion", "spellbook"), "cold": ("potion",), "lightning": ("wand", "ring")}
WORN_GIVES = (("amulet of reflection", "reflection"), ("silver dragon scale mail", "reflection"),
              ("shield of reflection", "reflection"), ("cloak of magic resistance", "magic"),
              ("gray dragon scale mail", "magic"), ("ring of fire resistance", "fire"),
              ("red dragon scale mail", "fire"), ("ring of cold resistance", "cold"),
              ("white dragon scale mail", "cold"), ("ring of shock resistance", "shock"),
              ("blue dragon scale mail", "shock"))
ROLE_GIVES = {"Valkyrie": ("cold",)}
RACE_GIVES = {"elf": ("sleep",)}


def our_protection(role, race, worn_texts):
    """What we know protects us: the role / race intrinsics at the start, and what we wear (not intrinsics eaten
    since -- unknown, so counted as absent)."""
    out = set(ROLE_GIVES.get(role, ())) | set(RACE_GIVES.get(race, ()))
    for t in worn_texts:
        for name, what in WORN_GIVES:
            if name in t:
                out.add(what)
    return out


def ray_harm(kind, protection, hp):
    """zap.c zhitu for a wand ray of `kind` hitting us. Returns {verdict, mean_dmg, max_dmg, asleep, blind, items}:
    verdict 'reflected' / 'resisted' (no damage, items may still go) / 'harmful' / 'dangerous' (can kill us or put
    us to sleep). A kind the engraving test left as sleep-or-death takes the worse of the two (the caller asks
    for 'death')."""
    out = {"kind": kind, "mean_dmg": 0.0, "max_dmg": 0, "asleep": 0.0, "blind": 0.0,
           "items": RAY_ITEMS.get(kind, ())}
    if "reflection" in protection:
        out.update(verdict="reflected", items=())
        return out
    resisted = RAY_RESIST.get(kind) in protection
    if kind == "death":
        out["verdict"] = "resisted" if resisted else "dangerous"
        out["max_dmg"] = 0 if resisted else 10 ** 4
        return out
    if kind == "sleep":
        if not resisted:
            out["asleep"] = 6 * 13.0                       # fall_asleep(-d(6, 25))
        out["verdict"] = "resisted" if resisted else "dangerous"
        return out
    n, s = RAY_DICE.get(kind, (0, 0))
    if not resisted:
        out["mean_dmg"], out["max_dmg"] = n * (s + 1) / 2, n * s
    if kind == "lightning":
        out["blind"] = 6 * 25.5                            # flashburn: make_blinded(d(6, 50)) unless resists_blnd
    out["verdict"] = "resisted" if resisted and not out["blind"] else \
        "dangerous" if out["max_dmg"] >= hp else "harmful"
    return out
