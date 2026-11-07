"""Who is around: hostile / peaceful monsters next to us and in view, threat gates for
housekeeping, monsters we never melee, straight-line targets, and what blindness / hallucination
leave us able to tell."""
import re
from collections import Counter

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import COLS, DELTA2KEY, NEIGH, ROWS
from nhbot.monalign import ALIGN
from nhbot.monattacks import ATTACKS
from nhbot.monsters import ALWAYS_AVOID, NEVER_MELEE, PASSIVE_DMG, PM_BY_NAME, THIEVES, permonst_of
from nhbot.rays import our_protection

# no active attack: only passive ones (molds, jellies, floating eye, acid blob), an explosion when killed
# (gas spore), the Oracle, a long worm's tail. No monster without one can move (mmove 0 for all that can't).
# Not the shrieker: no attack, but next to us it shrieks every move (mon.c m_respond): wakes the level, and
# one shriek in 10 creates a monster (1 in 13 of those a purple worm).
NO_ACTIVE_ATTACK = {nh.permonst(i).mname for i in range(nh.NUMMONS)
                    if all(a[0] in ("NONE", "BOOM") for a in ATTACKS[i])} - {"shrieker"}

# passive_immune: the monsters whose only attack is a passive cold / fire one -- uhitm.c passive(): with the
# resistance it does no damage (shieldeff, "You feel a mild chill" / "You're not affected"), nothing else
# (brown mold, blue jelly: cold; red mold: fire)
PASSIVE_ELEMENT = {"COLD": "cold", "FIRE": "fire"}
PASSIVE_KIND = {nh.permonst(i).mname: PASSIVE_ELEMENT[ATTACKS[i][0][1]] for i in range(nh.NUMMONS)
                if ATTACKS[i] and all(a[0] == "NONE" for a in ATTACKS[i]) and ATTACKS[i][0][1] in PASSIVE_ELEMENT}
# monst.h MR_* bits of mconveys: the resistances eating the corpse may give (eat.c cpostfx: one of them at random)
CONVEYS = ((0x01, "fire"), (0x02, "cold"), (0x04, "sleep"), (0x08, "disint"), (0x10, "shock"), (0x20, "poison"))


M2_HUMAN, M2_ELF, M2_DWARF, M2_GNOME, M2_ORC = 0x8, 0x10, 0x20, 0x40, 0x80
M2_MINION, M2_HOSTILE, M2_PEACEFUL = 0x1000, 0x00100000, 0x00200000
MS_LEADER, MS_NEMESIS, MS_GUARDIAN = 31, 32, 33
# role.c races[]: (lovemask, hatemask)
RACE_MASKS = {"human": (0, M2_GNOME | M2_ORC), "elf": (M2_ELF, M2_ORC), "elven": (M2_ELF, M2_ORC),
              "dwarf": (M2_DWARF | M2_GNOME, M2_ORC), "dwarven": (M2_DWARF | M2_GNOME, M2_ORC),
              "gnome": (M2_DWARF | M2_GNOME, M2_HUMAN), "gnomish": (M2_DWARF | M2_GNOME, M2_HUMAN),
              "orc": (0, M2_HUMAN | M2_ELF | M2_DWARF), "orcish": (0, M2_HUMAN | M2_ELF | M2_DWARF)}
# a monster's melee attack on us (not on another monster: those name their target, without '!')
ATTACKER_RE = re.compile(r"(?:^|[.!?]\s+)(The [^.!?]+?|[A-Z][\w'-]*(?: [\w'-]+)*?) (?:hits|bites|misses|just misses|stings|"
                         r"kicks|butts|claws|scratches|lashes|tickles|stabs|pummels|whips|gores)!|"
                         r"(?:^|[.!?]\s+)(The [^.!?]+?|[A-Z][\w'-]*(?: [\w'-]+)*?) (?:touches|engulfs|squeezes|charms|grabs) you")


class PerceptionMixin:
    def perception_init(self):
        self.farlooks = 0              # ';' looks that peaceful_now made
        self.peace_cls = {}            # permonst index -> 1 always peaceful / -1 never / 0 either (peace_class)
        self.peace_seen = {}           # (level, glyph, pos) -> (turn, peaceful): a look or 'Really attack?'
        self.hostile_marks = {}        # level key -> [(glyph, pos)]: 'peaceful' monsters that attacked us
        self.peaceful_hits = Counter() # species: attacks on us by a monster we took for peaceful
        self.peace_turned = 0          # looks that found a kind created peaceful hostile
        self.empty_looks = 0           # looks whose description came back empty
        self.peaceful_wait_by = Counter()   # species: waits for a peaceful monster in our way (nav.move)

    # ------------------------------------------------------------------ peacefulness
    def peace_class(self, idx):
        """makemon.c peace_minded() for us: 1 = always created peaceful (M2_PEACEFUL, quest leader / guardians,
        our race's friends), -1 = never (M2_HOSTILE, nemesis, our race's enemies, alignment of the other sign,
        A_NONE), 0 = either (co-aligned, a die roll; minions: by our alignment record)."""
        c = self.peace_cls.get(idx)
        if c is None:
            pm = nh.permonst(idx)
            f2 = pm.mflags2
            love, hate = RACE_MASKS.get((self.race or "human").lower(), (0, 0))
            mal, ual = ALIGN[idx], int(self.last_bl[nh.NLE_BL_ALIGN])
            sgn = lambda v: (v > 0) - (v < 0)
            if f2 & M2_PEACEFUL or pm.msound in (MS_LEADER, MS_GUARDIAN):
                c = 1
            elif f2 & M2_HOSTILE or pm.msound == MS_NEMESIS:
                c = -1
            elif f2 & love:
                c = 1
            elif f2 & hate or sgn(mal) != sgn(ual):
                c = -1
            else:
                c = 0
            self.peace_cls[idx] = c
        return c

    def track_hostile_marks(self, lv):
        """Follow marked monsters: still on their square, or the nearest monster of the same glyph within 2
        squares; lost (out of view) -> forgotten."""
        marks = self.hostile_marks.get(lv.key)
        if not marks:
            return set()
        g = self.obs["glyphs"]
        out = []
        taken = set()
        for gl, p in marks:
            if int(g[p]) == gl and p not in taken:
                out.append((gl, p)); taken.add(p)
        for gl, p in marks:
            if int(g[p]) == gl:
                continue
            near = [q for q in self.visible_monsters() if int(g[q]) == gl and q not in taken
                    and max(abs(q[0] - p[0]), abs(q[1] - p[1])) <= 2]
            if near:
                q = min(near, key=lambda q: max(abs(q[0] - p[0]), abs(q[1] - p[1])))
                out.append((gl, q)); taken.add(q)
        self.hostile_marks[lv.key] = out
        return taken

    def peaceful_now(self, lv, pos, look=True, slack=0, far=False):
        """Is the monster at pos peaceful? Attacked us after being taken for peaceful, or a look found it
        hostile: no. Looked at (or it answered 'Really attack?') this turn: that answer. A kind never created
        peaceful: no. Otherwise next to us (and look) a look (';') decides; farther away its kind does: created
        peaceful -> yes, either way -> no. far: also look from a distance (before a ranged attack: a missile or
        a ray angers a peaceful without asking)."""
        g = int(self.obs["glyphs"][pos])
        if G.KIND[g] != G.MONSTER:
            return False
        if pos in self.track_hostile_marks(lv):
            return False
        ck = (lv.key, g, pos)
        s = self.peace_seen.get(ck)
        if s is not None and s[0] >= self.turn() - slack:
            return s[1]
        cls = self.peace_class(nh.glyph_to_mon(g))
        if cls < 0:
            return False
        y, x = self.pos()
        if look and (far or max(abs(pos[0] - y), abs(pos[1] - x)) == 1):
            # next to us: look, also at kinds created peaceful -- they turn hostile (a throne room, onlookers
            # when we hit a peaceful, an angry shopkeeper) and need not attack in melee to be dangerous
            desc = self.describe_at(pos)
            self.farlooks += 1
            peaceful = "peaceful" in desc or "tame" in desc
            if not desc.strip():
                self.empty_looks += 1
            if len(self.peace_seen) > 400:
                t = self.turn()
                self.peace_seen = {k: v for k, v in self.peace_seen.items() if v[0] >= t - 2}
            self.peace_seen[ck] = (self.turn(), peaceful)
            if cls > 0 and not peaceful:
                self.peace_turned += 1
                marks = self.hostile_marks.setdefault(lv.key, [])
                if (g, pos) not in marks:
                    marks.append((g, pos))           # stays hostile while we can follow it
            return peaceful
        return cls > 0

    def msg_peace(self, m, lv):
        """A monster we take for peaceful attacked us: count it (by kind), and every one of that kind next to
        us is hostile from now on."""
        if lv is None or int(self.last_bl[nh.NLE_BL_CONDITION]) & nh.BL_MASK_HALLU:
            return
        g = self.obs["glyphs"]
        y, x = self.pos()
        adj = [(y + dy, x + dx) for dy, dx in NEIGH if 0 <= y + dy < ROWS and 0 <= x + dx < COLS
               and G.KIND[g[y + dy, x + dx]] == G.MONSTER]
        for mm in ATTACKER_RE.finditer(m):
            who = mm.group(1) or mm.group(2)
            if who in ("You", "It") or who.startswith("You "):
                continue
            if who.startswith("The "):
                kind = who[4:]
                match = lambda n: n == kind or (kind.startswith("priest of") and n in ("aligned priest", "high priest"))
            else:                                    # a proper name: shopkeeper, temple priest, ...
                match = lambda n: n in PM_BY_NAME and PM_BY_NAME[n].mflags2 & M2_PEACEFUL
            same = [p for p in adj if match(G.monster_name(int(g[p])))]
            if same and any(self.peaceful_now(lv, p, look=False, slack=1) for p in same):
                self.peaceful_hits[G.monster_name(int(g[same[0]]))] += 1
                marks = self.hostile_marks.setdefault(lv.key, [])
                for p in same:
                    if (int(g[p]), p) not in marks:
                        marks.append((int(g[p]), p))

    def is_actively_dangerous(self, lv, pos):
        """Can the monster at pos hurt us of its own accord? False if it has no active attack (NO_ACTIVE_ATTACK)
        or is peaceful: its glyph answered 'Really attack?' on this level, or a farlook says so (cached 5 turns
        per monster and square). An unseen 'I': True."""
        g = int(self.obs["glyphs"][pos])
        k = G.KIND[g]
        if k == G.INVIS:
            return True
        if k != G.MONSTER or G.monster_name(g) in NO_ACTIVE_ATTACK:
            return False
        return not self.peaceful_now(lv, pos)

    def visible_hostiles(self, lv):
        """Monsters on screen that can hurt us of their own accord (is_actively_dangerous)."""
        return [(p, G.monster_name(int(self.obs["glyphs"][p]))) for p in self.visible_monsters()
                if self.is_actively_dangerous(lv, p)]

    def visible_monsters(self):
        """Squares of the monsters on screen other than us."""
        g = self.obs["glyphs"]
        ys, xs = np.nonzero(G.KIND[g] == G.MONSTER)
        me = self.pos()
        return [(int(a), int(b)) for a, b in zip(ys, xs) if (a, b) != me]

    def stationary_avoid(self, lv):
        """The never-melee monsters that never move (molds, lichens' kin: mmove 0) stay where we saw
        them while out of sight (Level.stationary) -- their squares avoided like the ones in view, so a pile under a
        mold in a dark corridor is no goal we walk up to, see the mold and turn from, over and over. Forgotten
        when we stand next to the square and it is not there. (A/B remember_molds: score -230 [-1150, +738],
        max depth +0.2 [+0.1, +0.4]; 20 first divergences traced: all a remembered mold / jelly avoided.)"""
        g = self.obs["glyphs"]
        y, x = self.pos()
        blind = int(self.last_bl[nh.NLE_BL_CONDITION]) & nh.BL_MASK_BLIND
        for pos, name in list(lv.stationary.items()):
            here = G.KIND[g[pos]] == G.MONSTER and G.monster_name(int(g[pos])) == name
            if not here and not blind and max(abs(pos[0] - y), abs(pos[1] - x)) <= 1:
                del lv.stationary[pos]
                continue
            if not here and pos not in self.avoid_cells and self.never_melee(name) \
                    and not (lv.desperate and name not in self.always_avoid()):
                self.avoid_cells.append(pos)

    def adjacent_hostiles(self, lv):
        y, x = self.pos()
        g = self.obs["glyphs"]
        out = []
        self.avoid_cells = []
        for yy in range(max(0, y - 7), min(ROWS, y + 8)):
            for xx in range(max(0, x - 7), min(COLS, x + 8)):
                k = G.KIND[g[yy, xx]]
                if k == G.MONSTER:
                    name = G.monster_name(g[yy, xx])
                    if self.never_melee(name) and not (lv.desperate and name not in self.always_avoid()) \
                            and not self.spore_ok(name):
                        self.avoid_cells.append((yy, xx))
                    if self.never_melee(name) and name in PM_BY_NAME \
                            and PM_BY_NAME[name].mmove == 0:
                        lv.stationary[(yy, xx)] = name
        self.stationary_avoid(lv)
        for dy, dx in NEIGH:
            ny, nx = y + dy, x + dx
            if not (0 <= ny < ROWS and 0 <= nx < COLS):
                continue
            gg = int(g[ny, nx])
            k = G.KIND[gg]
            if k == G.MONSTER:
                name = G.monster_name(gg)
                if self.never_melee(name) and not (lv.desperate and name not in self.always_avoid()
                                                and self.bl(nh.NLE_BL_HP) * 10 >= self.bl(nh.NLE_BL_HPMAX) * 9) \
                        and not self.spore_ok(name):
                    continue
                if self.is_actively_dangerous(lv, (ny, nx)) or self.passive_prey(name):
                    out.append(((ny, nx), name))
            elif k == G.INVIS and (ny, nx):
                out.append(((ny, nx), "invisible"))
        return out

    def view_threats(self, lv):
        """Visible hostiles that should stop housekeeping (pickups, equipment, shopping) and resting: the
        visible hostiles (no active attack / peaceful: all in is_actively_dangerous; no monster without an
        active attack can move, so a far immobile one never counts)."""
        return self.visible_hostiles(lv)

    def items_gate(self, lv):
        """May item goals be pursued / piles inspected now? Not in combat: nothing in melee range and not shot
        at in the last 5 turns. Goals and the steps that consume them use this same test."""
        return not self.adjacent_hostiles(lv) and self.turn() - self.last_shot_turn > 5

    def mark_peaceful_target(self):
        t = self.last_attack_target
        if t is None:
            return
        g = int(self.obs["glyphs"][t])
        lv = self.levels.get(self.cur_key)
        if lv is not None:
            self.peace_seen[(lv.key, g, t)] = (self.turn(), True)      # this monster, this turn

    def line_targets(self, lv, max_d=6):
        """Hostile-looking monsters in a clear straight line: [(dirkey, d, pos, step)]."""
        y, x = self.pos()
        g = self.obs["glyphs"]
        k_mem = self.kinds(lv)
        out = []
        for (dy, dx), key in DELTA2KEY.items():
            for i in range(1, max_d + 1):
                yy, xx = y + i * dy, x + i * dx
                if not (0 <= yy < ROWS and 0 <= xx < COLS):
                    break
                k = G.KIND[g[yy, xx]]
                if k == G.MONSTER:
                    name = G.monster_name(int(g[yy, xx]))
                    if not self.peaceful_now(lv, (yy, xx), look=False):
                        out.append((key, i, (yy, xx), (dy, dx), name))
                    break
                if k in (G.PET, G.BOULDER) or not G.PASSABLE[k_mem[yy, xx]] and k_mem[yy, xx] != G.UNKNOWN:
                    break
        return sorted(out, key=lambda t: t[1])

    def thieves_visible(self, lv):
        out = []
        for p, name in self.visible_hostiles(lv):
            if name in THIEVES:
                out.append((p, name))
        return out

    def shopkeeper_in_view(self):
        g = self.obs["glyphs"]
        ys, xs = np.nonzero(G.KIND[g] == G.MONSTER)
        return any(G.monster_name(int(g[a, c])) == "shopkeeper" for a, c in zip(ys, xs))

    def law_nearby(self):
        g = self.obs["glyphs"]
        ys, xs = np.nonzero(G.KIND[g] == G.MONSTER)
        for yy, xx in zip(ys, xs):
            n = G.monster_name(int(g[yy, xx]))
            if n in ("watchman", "watch captain", "shopkeeper"):
                return True
        return False

    def peaceful_next(self, lv, hostiles):
        """A monster next to us that is not one of the hostiles (peaceful: the watch, a shopkeeper, a gnome)."""
        g = self.obs["glyphs"]
        y, x = self.pos()
        hot = {p for p, _ in hostiles}
        return any(G.KIND[g[y + dy, x + dx]] == G.MONSTER and (y + dy, x + dx) not in hot
                   for dy, dx in NEIGH if 0 <= y + dy < ROWS and 0 <= x + dx < COLS)

    def town_folk_visible(self):
        """Minetown's watch, temple priest or shopkeepers in view (an unlit Minetown may hide its altar)."""
        if int(self.last_bl[nh.NLE_BL_CONDITION]) & nh.BL_MASK_HALLU:
            return False
        g = self.obs["glyphs"]
        ys, xs = np.nonzero(G.KIND[g] == G.MONSTER)
        return any(G.monster_name(int(g[yy, xx])) in ("watchman", "watch captain", "aligned priest", "shopkeeper")
                   for yy, xx in zip(ys, xs))

    def always_avoid(self):
        s = ALWAYS_AVOID
        if not int(self.last_bl[nh.NLE_BL_CONDITION]) & nh.BL_MASK_BLIND:
            s = s | {"floating eye"}          # its passive gaze paralyses for up to ~127 turns
        return s

    def our_resists(self):
        """The resistances we know we have: role / race and what we wear (rays.our_protection), what corpses gave."""
        out = our_protection(self.role, self.race, [i.text for i in self.items() if i.on_body]) | self.eaten_res
        return out | {"poison"} if self.poison_res else out

    def passive_immune(self, name):
        """Its only attack is a passive cold / fire one and we resist it -- hitting it is harmless: no longer avoided,
        hunted while it gives a resistance we lack (A/B passive_immune +296 [-978, +1553], max depth +0.2)."""
        return name in PASSIVE_KIND and PASSIVE_KIND[name] in self.our_resists()

    def passive_prey(self, name):
        """passive_immune: hitting it is harmless and its corpse may give a resistance we lack -- hunted
        (combat.prey_mask) and hit next to us (adjacent_hostiles), though it never attacks."""
        if not self.passive_immune(name):
            return False
        conveys = {r for bit, r in CONVEYS if PM_BY_NAME[name].mconveys & bit}
        return bool(conveys - self.our_resists())

    def never_melee(self, name):
        """Don't hit what has only a passive attack (it never hurts us otherwise); desperate (stuck) still may."""
        if name in ("cockatrice", "chickatrice") and any(it.wielded for it in self.items()):
            return False       # hitting it with a wielded weapon is safe; standing by while it touches us is not
        if self.passive_immune(name):
            return False
        return name in NEVER_MELEE or name in PASSIVE_DMG

    def spore_ok(self, name):
        # gas spore explosion is 4d6 (max 24): meleeing it is safe above that
        return name == "gas spore" and self.bl(nh.NLE_BL_HP) >= 25

    def mon_level(self, pos):
        g = int(self.obs["glyphs"][pos])
        m = nh.glyph_to_mon(g)
        return nh.permonst(m).mlevel if 0 <= m < nh.NUMMONS else 0

    def threat(self, g):
        pm = permonst_of(g)
        return 0 if pm is None else pm.difficulty - self.bl(nh.NLE_BL_XP)

    def est_dmg(self, g, name=None):
        """Rough expected damage per player turn from one adjacent monster.
        to-hit from the wiki formula d20 < 10 + AC + level; per-hit damage ~ 1 + 1.5*level
        (attack tables are not exposed by NLE, so this is a level-based proxy)."""
        pm = permonst_of(g)
        if pm is None or name == "invisible":
            return 3.0
        lvl = pm.mlevel
        ac = self.bl(nh.NLE_BL_AC)
        hit = min(max((10 + ac + lvl - 1) / 20.0, 0.05), 1.0)
        return (1.0 + 1.5 * lvl) * hit * max(pm.mmove, 1) / 12.0

    def blind_attackers(self, lv, hostiles):
        """blind_strike: while blind, an adjacent 'I' is only a target if it attacked us. mhitu.c marks the square
        of an unseen attacker with 'I' in the same turn as its "It hits!"; 'I' also appears when we bump into or
        search out a monster that did nothing (61969: a watchman; 61057). So: an attack message this turn and a
        new 'I' next to us -> that one; an attack and a single 'I' next to us -> that one; otherwise unknown,
        don't hit (blind_wait then keeps us still)."""
        cur = {p for p, n in hostiles if n == "invisible"}
        attacked, self.it_attacked = self.it_attacked, False
        prev = self.prev_inv
        known = self.inv_attackers
        if attacked:
            new = cur - prev
            known |= new if new else (cur if len(cur) == 1 else set())
        known &= cur
        self.prev_inv, self.inv_attackers = cur, known
        if not int(self.last_bl[nh.NLE_BL_CONDITION]) & nh.BL_MASK_BLIND or not self.strike_scope_ok(lv):
            return hostiles
        out = [(p, n) for p, n in hostiles if n != "invisible" or p in known]
        if len(out) < len(hostiles):
            self.blind_held += 1
        return out

    def hallu_attackers(self, lv, hostiles):
        """hallu_strike: while hallucinating, looks and names are random, so peacefuls can't be told apart
        (61520 hit a shopkeeper, 61969 two peacefuls). Hit only a square whose monster attacked us: a melee
        attack message this turn with exactly one monster next to us marks that square; it stays a target
        while a monster stands on it. Never one inside a shop (the shopkeeper)."""
        g = self.obs["glyphs"]
        y, x = self.pos()
        adj = [(y + dy, x + dx) for dy, dx in NEIGH if 0 <= y + dy < ROWS and 0 <= x + dx < COLS
               and nh.glyph_is_monster(int(g[y + dy, x + dx]))]
        attacked, self.melee_on_us = self.melee_on_us, False
        known = self.hallu_targets
        if attacked and len(adj) == 1:
            known.add(adj[0])
        known &= set(adj)
        self.hallu_targets = known
        if not int(self.last_bl[nh.NLE_BL_CONDITION]) & nh.BL_MASK_HALLU or not self.strike_scope_ok(lv):
            return hostiles
        out = [(p, n) for p, n in hostiles if p in known and not lv.shop[p]]
        if len(out) < len(hostiles):
            self.hallu_held += 1
        return out

    def hallu_blind_ranged(self):
        """hallu_strike: no throwing / zapping / hunting at range while hallucinating -- the target can't be told
        from a peaceful (61520 threw a dagger into one)."""
        return bool(int(self.last_bl[nh.NLE_BL_CONDITION]) & nh.BL_MASK_HALLU
                    and self.strike_scope_ok(self.levels.get(self.cur_key)))

    def peaceful_seen(self, lv):
        """A peaceful monster here, as far as we know: one a look found peaceful (peace_seen), a shop, Minetown."""
        return bool(lv.shop.any()) or self.is_minetown(lv) \
            or any(k == lv.key and v[1] for (k, _, _), v in self.peace_seen.items())

    def strike_scope_ok(self, lv):
        """blind_strike / hallu_strike only in Minetown -- a Mines level with an altar, a fountain or
        a shop (filler Mines levels have none), where the peaceful watch, priest and shopkeepers are."""
        return self.is_minetown(lv)
