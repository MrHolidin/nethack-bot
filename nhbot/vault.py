"""vault_rob: in a vault (a closed 2x2 room of gold -- most often reached by its teleporter, mklev.c makevtele) with a
way to dig: take the gold and dig down through the floor with it -- the guard comes only after 30 turns inside
(vault.c invault: u.uinvault % VAULT_GUARD_TIME), and asks for every coin we carry, bags too (hidden_gold). If he
comes first, we are "Croesus" (vault.c: "Oh, yes, of course. Sorry to have disturbed you." -- he leaves; lawful:
-1 alignment for the lie) and dig on. Ways to dig: a wand of digging zapped down (a hole at once), a pick-axe, a
dwarvish mattock (two-handed: the shield comes off first) applied down -- the weapon is wielded back after
(weapons.swap_in / swap_back, job "dig").

vault_find: a vault on our map -- its walls drawn by magic mapping, or its four piles of gold shown by gold detection
(a 2x2 of gold in the rock) -- is dug to: a tunnel through the rock from the square nearest to it we can reach, into
the vault, where vault_rob goes on; a wand of digging digs it zap by zap (a straight line each, the tunnel planned
with few turns), walking to the end of each line. On a
level whose vault we heard ("someone counting money", "the footsteps of a guard on patrol": sounds.c) and could dig
to, a scroll of gold detection / magic mapping we know is read; those scrolls and a wand of digging are kept."""

import heapq
from collections import Counter

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import COLS, DELTA2KEY, FLOOR_GLYPH, ROWS, WEAK

VAULT_GRAB_TURNS = 12          # turns inside spent on the gold at most: the dig (~15 turns with a pick) ends by 30
VAULT_SOUNDS = ("counting money", "footsteps of a guard on patrol")
FIND_SCROLLS = ("scroll of gold detection", "scroll of magic mapping")
MAX_TUNNEL = 30                # squares of rock and wall dug at most toward a vault (a pick: ~6 turns each)
TURN_COST = 0.1                # vault_tunnel: what a turn of the tunnel costs more, a pick (straighter at no cost)
TURN_COST_WAND = 6             # ... a wand of digging: a turn is a zap more (zap.c zap_dig: one line, rn1(18, 8) deep)
ORTHO = ((-1, 0), (1, 0), (0, -1), (0, 1))
DIG_TRIES = 4                  # tries at one square before the tunnel is given up
VAULT_RETRY = 100              # turns before a tunnel whose start we could not reach is planned again


class VaultMixin:
    def vault_init(self):
        self.vault_since = None        # (level key, turn) we were first seen in this vault
        self.vault_seen = None         # (level key, its 4 squares): the vault we were last in -- the guard's way in
                                       # opens its wall (vault.c fake corridor), so it is known by its squares then
        self.dig_refused = set()       # level keys whose floor would not be dug ("too hard to dig in")
        self.vault_stats = Counter()
        self.vault_portal = None       # level key of a vault where we found a magic portal (the Fort Ludios one,
                                       # mkmaze.c): no more gold picked there -- a step onto it takes us to the fort
        self.vault_heard = set()       # vault_find: level keys whose vault we heard
        self.vault_done = set()        # vault_find: level keys whose vault we reached or gave up
        self.vault_plan = None         # vault_find: {key, inner, start, path (squares to dig, in order), wand}
        self.vault_out = None          # vault_exit: (level key, square) where the tunnel into the vault we are in begins
        self.vault_shut = {}           # vault_clear: level key -> the squares (floor, wall) of a vault we are leaving
        self.vault_tries = Counter()   # vault_find: tries at digging each square of the plan
        self.vault_loc_at = {}         # vault_find: level key -> (lv.under bytes hash, located interior or None)
        self.vault_wait = {}           # vault_find: level key -> turn before which no tunnel is planned again

    # ------------------------------------------------------------------ in a vault
    def vault_box(self):
        """The 4 floor squares of the 2x2 room we stand in, closed all round by wall (no door): a vault -- or
        those of the vault we were seen in on this level, while we stand in it. None if not."""
        y, x = self.pos()
        if self.vault_seen is not None and self.vault_seen[0] == self.cur_key and (y, x) in self.vault_seen[1]:
            return self.vault_seen[1]
        inner = self.vault_closed()
        if inner is not None:
            self.vault_seen = (self.cur_key, inner)
        return inner

    @staticmethod
    def vault_walls(inner):
        """The 4 floor squares of a vault and the 12 of its wall around them."""
        (y0, x0) = min(inner)
        return [(y0 + i, x0 + j) for i in range(-1, 3) for j in range(-1, 3)]

    def vault_closed(self):
        g = self.obs["glyphs"]
        y, x = self.pos()
        for y0 in (y - 1, y):
            for x0 in (x - 1, x):
                if y0 < 1 or x0 < 1 or y0 + 2 >= ROWS or x0 + 2 >= COLS:
                    continue
                inner = [(y0 + i, x0 + j) for i in (0, 1) for j in (0, 1)]
                ring = [(y0 + i, x0 + j) for i in range(-1, 3) for j in range(-1, 3)
                        if not (0 <= i <= 1 and 0 <= j <= 1)]
                if all(G.KIND[g[p]] == G.WALL for p in ring) and not any(G.KIND[g[p]] == G.WALL for p in inner):
                    return inner
        return None

    def dig_means(self):
        """How we can dig down: ("wand", item) a wand of digging with charges left, ("pick", item) a pick-axe,
        ("mattock", item) a dwarvish mattock -- none known cursed (a cursed digger applied stays welded), no
        digger while a cursed weapon is welded to our hand. None."""
        items = self.items()
        wand = next((it for it in items if it.ocls == nh.WAND_CLASS and "wand of digging" in it.text
                     and ":0)" not in it.text and "cancelled" not in it.text), None)
        welded = any(it.wielded and it.cursed and "pick-axe" not in it.text and "mattock" not in it.text
                     for it in items)             # a cursed weapon in hand: no digger can be wielded (wield.c)
        pick = None if welded else next((it for it in items if "pick-axe" in it.text and not it.cursed), None)
        mattock = None if welded else next((it for it in items if "dwarvish mattock" in it.text and not it.cursed),
                                           None)
        if pick is not None:
            return "pick", pick
        if wand is not None:
            return "wand", wand
        if mattock is not None:
            return "mattock", mattock
        return None

    def vault_rob_ready(self):
        """In a vault, a way to dig, the floor here not refused. (game.py: the guard is told "Croesus" then.)"""
        return self.cur_key not in self.dig_refused and self.vault_box() is not None \
            and self.dig_means() is not None

    def vault_rob_step(self, lv, hostiles):
        """Out of the vault after a dig -- the weapon back (not while tunnelling toward one); in one with a way to
        dig -- the gold (VAULT_GRAB_TURNS at most), then down -- or out by our tunnel. True if it used the turn.
        A/B vault_rob +316 [+92, +566]; vault_exit -222 [-411, -47] (with the gold-lift fix taken); vault_clear
        +129 [-3, +274]."""
        box = self.vault_box()
        if box is None and self.vault_leaving(lv):
            return self.vault_walk_out(lv)
        if box is None:
            self.vault_since = None
            return self.vault_plan is None and self.dig_job is None and self.swap_back("dig")
        if self.vault_plan is not None and self.vault_plan["key"] == lv.key:
            self.vault_done.add(lv.key)               # vault_find: the tunnel is through
            self.vault_out = (lv.key, self.vault_plan["start"])
            self.vault_plan = None
            self.vault_stats["tunnel_in"] += 1
        if hostiles and any(n != "guard" for _, n in hostiles) or lv.key in self.dig_refused:
            return False
        means = self.dig_means()
        if means is None:
            return False                              # the guard protocol (survival.vault_step): drop, follow
        if self.vault_since is None or self.vault_since[0] != lv.key:
            self.vault_since = (lv.key, self.turn())
            self.vault_stats["entered"] += 1
        here = self.pos()
        gold = [p for p in box if G.KIND[self.obs["glyphs"][p]] == G.GOLD or (p == here and G.KIND[lv.under[p]] == G.GOLD)]
        if gold and self.turn() - self.vault_since[1] < VAULT_GRAB_TURNS and self.vault_portal != lv.key:
            self.cur_act = "vault_rob"
            if here in gold:
                g0 = int(self.bl(nh.NLE_BL_GOLD))
                self.pickup_matching(("gold piece",), own=True)
                lv.under[here] = FLOOR_GLYPH
                self.vault_stats["gold"] += int(self.bl(nh.NLE_BL_GOLD)) - g0
                return True
            p = gold[0]                               # every square of the 2x2 is next to us
            self.press(DELTA2KEY[(p[0] - here[0], p[1] - here[1])])
            return True
        if self.vault_out is not None and self.vault_out[0] == lv.key:
            self.vault_shut[lv.key] = self.vault_walls(box)
            if self.vault_walk_out(lv):
                return True
        return self.dig_down(lv, means)

    def vault_leaving(self, lv):
        """On the wall of the vault we are leaving -- in its dug opening, still in the vault for the game (in_rooms
        counts a door with the room: the guard's count goes on)."""
        return self.vault_out is not None and self.vault_out[0] == lv.key \
            and self.pos() in self.vault_shut.get(lv.key, ())

    def vault_walk_out(self, lv):
        """vault_exit: a step back along our tunnel. True if it used the turn; False if the way is shut (down
        after all)."""
        mask = np.zeros(lv.under.shape, dtype=bool)
        mask[self.vault_out[1]] = True
        if self.walk_to(lv, mask, act="vault_exit")[0] == "moved":
            self.vault_stats["walk_out"] += 1         # vault_exit: out by our own tunnel, not down a hole
            return True
        self.vault_out = None
        return False

    def dig_down(self, lv, means):
        kind, it = means
        self.cur_act = "vault_dig"
        if kind == "wand":
            self.vault_stats["zap"] += 1
            seq0 = self.msg_seq
            self.zap(it.letter, ">")
            self.dig_note(lv, self.text_since(seq0))
            return True
        if self.dig_wield(lv, means):
            return True
        self.vault_stats["apply"] += 1
        return self.dig_apply(lv, it, ">")

    def dig_wield(self, lv, means):
        """The pick-axe / mattock into our hands (the weapon back later: swap_back "dig"; a mattock: the shield off
        first). True if it used the turn."""
        kind, it = means
        if it.wielded:
            return False
        shield = next((a for a in self.armor_inventory() if a["worn"] and a["slot"] == "shield"), None)
        if kind == "mattock" and shield is not None:
            if not self.take_off(shield):             # a two-handed digger: not with a shield on (wield.c)
                self.dig_refused.add(lv.key)          # a cursed shield: no mattock
            return True
        self.swap_in("dig", it)
        return True

    def apply_digger(self, it, key):
        """Apply the wielded digger in direction key (">" down). The text the game answered; None: no apply."""
        seq0 = self.msg_seq
        if not self.ask("a", "apply"):
            return None
        self.press(it.letter, expect_prompt=True)
        if "direction" in self.message().lower():
            self.press(key)
        else:
            self.settle()
        return self.text_since(seq0)

    def dig_apply(self, lv, it, key):
        """Apply the wielded digger in direction key (">" down), noting what the game said. True if it used the
        turn."""
        msgs = self.apply_digger(it, key)
        if msgs is None:
            return False
        if key == ">":
            self.dig_note(lv, msgs)
        elif "too hard to" in msgs:                   # undiggable walls / rock (W_NONDIGGABLE): no tunnel here
            self.vault_done.add(lv.key)
            self.vault_plan = None
            self.vault_stats["tunnel_refused"] += 1
        return True

    def msg_vault(self, m):
        if "You find a magic portal" in m and self.vault_since is not None:
            self.vault_portal = self.cur_key
            self.vault_stats["portal"] += 1
        if any(s in m for s in VAULT_SOUNDS):
            self.vault_heard.add(self.cur_key)

    def dig_note(self, lv, msgs):
        if "too hard to" in msgs or "cannot reach the" in msgs:
            self.dig_refused.add(lv.key)
            self.vault_stats["refused"] += 1
        if "You dig a hole through" in msgs or "fall through" in msgs:
            self.vault_stats["dug_out"] += 1

    # ------------------------------------------------------------------ vault_find: to a vault on our map
    def vault_locate(self, lv):
        """The interior (4 squares) of a vault our map shows: a 2x2 closed all round by wall (magic mapping), or a
        2x2 of gold none of whose 12 neighbours we know as floor or door (gold detection: the vault lies in rock).
        None. Cached per map state."""
        h = hash(lv.under.tobytes())
        got = self.vault_loc_at.get(lv.key)
        if got is not None and got[0] == h:
            return got[1]
        k = G.KIND[lv.under]
        found = None
        for y0 in range(2, ROWS - 3):
            for x0 in range(3, COLS - 2):
                inner = k[y0:y0 + 2, x0:x0 + 2]
                box = k[y0 - 1:y0 + 3, x0 - 1:x0 + 3]
                ring = np.concatenate([box[0], box[3], box[1:3, 0], box[1:3, 3]])
                walled = (ring == G.WALL).all() and not (inner == G.WALL).any()
                gold = (inner == G.GOLD).all() and np.isin(ring, (G.UNKNOWN, G.WALL)).all()
                if walled or gold:
                    found = [(y0 + i, x0 + j) for i in (0, 1) for j in (0, 1)]
                    break
            if found:
                break
        self.vault_loc_at[lv.key] = (h, found)
        return found

    def vault_tunnel(self, lv, inner, wand):
        """The tunnel to dig: (start, path) -- start a square we know as passable, its floor seen, path the squares
        from it to the vault, in order (rock or the wall of an ordinary room, the vault's wall, then a square
        inside), orthogonal steps only (a squeeze between rock on a diagonal fails when we carry much: hack.c
        test_move). The fewest squares to dig, a turn counting TURN_COST more (a wand of digging digs a straight
        line a zap: zap.c zap_dig), then the nearest start. None."""
        k = G.KIND[lv.under]
        # a start: passable, its floor seen (detected gold lies in the rock too: mklev.c mineralize)
        passable = self.grids(lv)[2] & (G.KIND[lv.terrain] != G.UNKNOWN)
        inner_set = set(inner)
        y0, x0 = min(inner)
        ring_ok = {(y0 - 1, x0), (y0 - 1, x0 + 1), (y0 + 2, x0), (y0 + 2, x0 + 1),
                   (y0, x0 - 1), (y0 + 1, x0 - 1), (y0, x0 + 2), (y0 + 1, x0 + 2)}    # not the corners
        ring = {(y0 + i, x0 + j) for i in range(-1, 3) for j in range(-1, 3)} - inner_set
        shopish = np.zeros_like(passable)
        if lv.shop.any():
            ys, xs = np.nonzero(lv.shop)
            for y, x in zip(ys, xs):
                shopish[max(0, y - 2):y + 3, max(0, x - 2):x + 3] = True          # never a shop's wall
        me = self.pos()
        turn = TURN_COST_WAND if wand else TURN_COST

        def diggable(q):                                  # rock, or the wall of a room that is not a shop
            return (k[q] == G.UNKNOWN or k[q] == G.WALL and q not in ring) and not shopish[q]

        dist, prev, heap, ends = {}, {}, [], []
        for p in inner:
            for di, (dy, dx) in enumerate(ORTHO):
                q = (p[0] + dy, p[1] + dx)
                if q in ring_ok:
                    dist[(q, di)] = 1
                    prev[(q, di)] = (p, None)
                    heapq.heappush(heap, (1, q, di))
        while heap:
            c, p, di = heapq.heappop(heap)
            if c > dist.get((p, di), 10 ** 9) or c > MAX_TUNNEL:
                continue
            for dj, (dy, dx) in enumerate(ORTHO):
                q = (p[0] + dy, p[1] + dx)
                if not (0 <= q[0] < ROWS and 0 <= q[1] < COLS) or q in inner_set or q in ring:
                    continue
                if passable[q]:
                    ends.append((c, max(abs(q[0] - me[0]), abs(q[1] - me[1])), q, (p, di)))
                    continue
                if not diggable(q):
                    continue
                c2 = c + 1 + (turn if dj != di else 0)
                if c2 < dist.get((q, dj), 10 ** 9):
                    dist[(q, dj)] = c2
                    prev[(q, dj)] = (p, di)
                    heapq.heappush(heap, (c2, q, dj))
        if not ends:
            return None
        _, _, start, st = min(ends)
        path = []
        while st[1] is not None:
            path.append(st[0])
            st = prev[st]
        path.append(st[0])                                # the square inside
        return start, path

    def vault_find_step(self, lv, hostiles_in_view):
        """Nothing in view: read a detection scroll where we heard a vault; dig to a vault our map shows. True if it
        used the turn. (A/B vault_find -34 [-708, +601], taken with vault_exit.)"""
        if hostiles_in_view or lv.key in self.vault_done or lv.key[0] != 0:
            return False
        means = self.dig_means()
        if means is None or lv.key in self.dig_refused:
            return False
        if self.bl(nh.NLE_BL_HUNGER) >= WEAK or self.bl(nh.NLE_BL_HP) * 10 < self.bl(nh.NLE_BL_HPMAX) * 6:
            return False
        inner = self.vault_locate(lv)
        if inner is None:
            return self.vault_detect(lv)
        if self.turn() < self.vault_wait.get(lv.key, 0):
            return False
        plan = self.vault_plan
        if plan is None or plan["key"] != lv.key or plan["wand"] != (means[0] == "wand"):
            got = self.vault_tunnel(lv, inner, means[0] == "wand")
            if got is None:                           # no start near enough yet: again once more is explored
                self.vault_wait[lv.key] = self.turn() + VAULT_RETRY
                self.vault_stats["no_tunnel"] += 1
                return False
            plan = self.vault_plan = {"key": lv.key, "inner": inner, "start": got[0], "path": got[1],
                                      "wand": means[0] == "wand"}
            self.vault_seen = (lv.key, inner)         # its wall will have our opening: known by its squares
            self.vault_stats["planned"] += 1
        return self.vault_tunnel_step(lv, plan, means)

    def vault_detect(self, lv):
        """A vault heard here and not on our map: read a scroll of gold detection / magic mapping we know."""
        if lv.key not in self.vault_heard or int(self.last_bl[nh.NLE_BL_CONDITION]) & (
                nh.BL_MASK_BLIND | nh.BL_MASK_CONF | nh.BL_MASK_STUN | nh.BL_MASK_HALLU):
            return False
        for name in FIND_SCROLLS:
            it = next((i for i in self.items() if i.ocls == nh.SCROLL_CLASS and name in i.text.replace("scrolls", "scroll")),
                      None)
            if it is not None:
                self.cur_act = "vault_detect"
                self.vault_stats["read_" + name.split()[-1]] += 1
                self.vault_heard.discard(lv.key)      # one scroll per hearing
                return self.read_scroll(lv, it.letter)
        return False

    def vault_tunnel_step(self, lv, plan, means):
        here = self.pos()
        path = plan["path"]
        if here == plan["start"] or here in path:
            i = path.index(here) + 1 if here in path else 0
            if i >= len(path):
                return False                          # inside: vault_rob from here
            nxt = path[i]
            d = (nxt[0] - here[0], nxt[1] - here[1])
            if G.KIND[self.obs["glyphs"][nxt]] not in (G.UNKNOWN, G.WALL):
                self.cur_act = "vault_tunnel"
                self.press(DELTA2KEY[d])              # dug: step in
                return True
            self.vault_tries[(lv.key, nxt)] += 1
            if self.vault_tries[(lv.key, nxt)] > DIG_TRIES:
                self.vault_done.add(lv.key)           # it won't give way: given up
                self.vault_plan = None
                self.vault_stats["stuck"] += 1
                return self.swap_back("dig")
            self.cur_act = "vault_tunnel"
            kind, it = means
            if kind == "wand":
                self.vault_stats["tunnel_zap"] += 1
                seq0 = self.msg_seq
                self.zap(it.letter, DELTA2KEY[d])
                return True
            if self.dig_wield(lv, means):
                return True
            self.vault_stats["tunnel_apply"] += 1
            return self.dig_apply(lv, it, DELTA2KEY[d])
        mask = np.zeros(lv.under.shape, dtype=bool)
        mask[plan["start"]] = True
        st = self.walk_to(lv, mask, act="vault_tunnel")[0]
        if st == "moved":
            return True
        self.vault_plan = None                        # the start can't be reached yet: again once more is explored
        self.vault_wait[lv.key] = self.turn() + VAULT_RETRY
        self.vault_stats["unreachable"] += 1
        return False
