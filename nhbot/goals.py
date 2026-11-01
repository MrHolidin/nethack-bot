"""Goals: squares the bot walks to for something lying there, in one registry.

Each kind of goal is one GoalKind record: how it is walked to (tier), how long it lives, how far we go for
it, what happens when we can't get there, whether it holds us on the level (items_first). Two tiers:

  explore  the goal joins the exploration frontier: explore() walks to the nearest of frontier + goals, and
           another step consumes it when we stand on it. Its walk mask must use the same gate as the
           consuming step (else we walk to a square where nothing happens). gold, pile.
  own      a policy step of its own walks to it and consumes it, at its place in STEPS.
           retrieve (our thrown missiles), corpse (fresh corpse of our kill), loot (stolen items).

Statistics per kind (summary 'goals'):
  created     goals that appeared (mask kinds: squares first seen with an uninspected pile / gold on them)
  consumed    we stood on it and did what it was for (picked up, inspected, ate)
  expired     its time ran out
  abandoned   given up because it could not be reached
  vanished    mask kinds: gone from the map memory without us consuming it (picked up by a monster, the
              square turned out to be part of a shop, ...)
  unfinished  still open at the end of the game
  chase_turns game turns spent on ticks whose action was a step toward this kind (frontier and downstairs
              are counted too, for comparison)
"""
from dataclasses import dataclass

import numpy as np

from nhbot import glyphs as G


@dataclass(frozen=True)
class GoalKind:
    name: str
    tier: str                      # "explore" | "own"
    ttl: int = None                # turns a goal lives, None: until consumed
    max_dist: int = None           # Chebyshev distance at most, None: any
    on_unreachable: str = "skip"   # "skip": not walked to while unreachable; "drop": forgotten; "keep"
    holds_descent: bool = False    # items_first: don't take the stairs down while one is reachable


GOALS = {
    "gold": GoalKind("gold", "explore", holds_descent=True),
    "pile": GoalKind("pile", "explore", holds_descent=True),
    "retrieve": GoalKind("retrieve", "own", ttl=60, on_unreachable="drop"),
    "corpse": GoalKind("corpse", "own", ttl=40, max_dist=8, on_unreachable="keep"),
    "loot": GoalKind("loot", "own", on_unreachable="drop"),
}
EXPLORE_KINDS = tuple(k for k, g in GOALS.items() if g.tier == "explore")
CHASE_ONLY = ("frontier", "downstairs")       # walked to, but not goals with a lifetime
STAT_FIELDS = ("created", "consumed", "expired", "abandoned", "vanished", "unfinished", "chase_turns")


class GoalsMixin:
    def goals_init(self):
        self.goal_stats = {k: dict.fromkeys(STAT_FIELDS, 0) for k in tuple(GOALS) + CHASE_ONLY}
        self.goal_open = {}            # (kind, level key) -> set of open goal squares (mask kinds)
        self.goal_closed = {}          # (kind, level key) -> squares done: consumed, or dropped there by us
        self.chasing = None            # kind walked toward by this tick's action

    # ------------------------------------------------------------------ events
    def goal_event(self, kind, event, n=1):
        if n:
            self.goal_stats[kind][event] += n

    def goal_chase(self, kind):
        self.chasing = kind

    # ------------------------------------------------------------------ explore tier
    def goal_raw(self, kind, lv):
        """Goal squares of a mask kind as the map memory shows them, before any gate (for statistics)."""
        if kind == "gold":
            m = G.KIND[lv.under] == G.GOLD
        else:
            m = G.ARMOR_GLYPH[lv.under] | G.FOOD_GLYPH[lv.under]
            ct = self.carry_targets(lv)
            if ct is not None:
                m |= ct
        for p in self.goal_closed_set(kind, lv.key):
            m[p] = False
        return m & ~lv.shop

    def goal_observe(self, lv):
        """Count goals of the mask kinds appearing on / vanishing from this level's map memory."""
        for kind in EXPLORE_KINDS:
            cur = {(int(a), int(b)) for a, b in zip(*np.nonzero(self.goal_raw(kind, lv)))}
            key = (kind, lv.key)
            prev = self.goal_open.get(key, set())
            self.goal_event(kind, "created", len(cur - prev))
            self.goal_event(kind, "vanished", len(prev - cur))
            self.goal_open[key] = cur

    def goal_closed_set(self, kind, key):
        """Squares of this kind already done on level key: never a goal again (gold: a pile shows '$' on top
        again after we leave, so it is tried once; piles: inspected once; anything we dropped ourselves)."""
        return self.goal_closed.setdefault((kind, key), set())

    def goal_close(self, kind, key, pos):
        """Mark done without counting a consumption (we dropped something here ourselves)."""
        self.goal_closed_set(kind, key).add(pos)

    def goal_done(self, kind, lv, pos):
        """A mask-kind goal at pos consumed (also when we got there before it was ever observed)."""
        key = (kind, lv.key)
        op = self.goal_open.setdefault(key, set())
        if pos in op:
            op.discard(pos)
        else:
            self.goal_event(kind, "created")
        self.goal_close(kind, lv.key, pos)
        self.goal_event(kind, "consumed")

    # ------------------------------------------------------------------ own tier
    def pursue(self, kind, lv, goal, consume):
        """One tick toward an own-tier goal: on it, consume(goal) and close it; else step toward it; if that
        fails, apply the kind's on_unreachable ('drop': forget it). True if the tick acted."""
        if goal == self.pos():
            consume(goal)
            self.goal_event(kind, "consumed", self.goal_forget(kind, lv, goal))
            return True
        if self.go_toward(lv, goal):
            self.goal_chase(kind)
            return True
        if GOALS[kind].on_unreachable == "drop":
            self.goal_event(kind, "abandoned", self.goal_forget(kind, lv, goal))
        return False

    def goal_forget(self, kind, lv, goal):
        """Remove an own-tier goal at goal from its list; returns how many entries went."""
        if kind == "retrieve":
            n = len(self.retrieve)
            self.retrieve = [r for r in self.retrieve if goal not in r[1]]
            return n - len(self.retrieve)
        if kind == "corpse":
            n = len(self.kills)
            self.kills = [k for k in self.kills if k[2] != goal or k[3] != lv.key]
            return n - len(self.kills)
        if kind == "loot":
            self.loot_sq = None
            return 1
        raise ValueError(kind)

    def merch_risk(self, lv, pos):
        """Could what lies at pos be merchandise (when we visit shops)? On a shop square; and unless
        shop_by_square, whenever a shopkeeper is in view."""
        if not self.shop_visits_on():
            return False
        return bool(lv.shop[pos]) or (not self.opts.shop_by_square and self.shopkeeper_in_view())

    def goal_masks(self, lv, passable, gold):
        """Walk masks of the explore-tier kinds, {kind: mask}. All of them only under items_gate (not in combat),
        the gate of the steps that consume them; gold not in a shop when we visit shops (gold_here), piles never
        on a shop square (housekeeping inspects them)."""
        ok = self.items_gate(lv)
        out = {"gold": (gold & ~lv.shop if self.shop_visits_on() else gold.copy()) & ok}
        pile = np.zeros_like(gold)
        if ok and (self.opts.use_armor or self.opts.use_food):
            im = passable & ~lv.shop
            pile |= self.armor_targets(lv, G) & im
            ct = self.carry_targets(lv)
            if ct is not None:
                pile |= ct & im
        out["pile"] = pile
        return out

    def goal_summary(self):
        st = {k: dict(v) for k, v in self.goal_stats.items()}
        for (kind, _), squares in self.goal_open.items():
            st[kind]["unfinished"] += len(squares)
        t = self.turn()
        for r in self.retrieve:
            st["retrieve"]["expired" if r[2] <= t else "unfinished"] += 1
        for k in self.kills:
            st["corpse"]["expired" if t - k[0] >= GOALS["corpse"].ttl else "unfinished"] += 1
        if self.loot_sq is not None:
            st["loot"]["unfinished"] += 1
        return st
