"""Goals: squares the bot walks to for something lying there, in one registry.

Each kind of goal is one GoalKind record: how it is walked to (tier), how long it lives, how far we go for
it, whether it holds us on the level (items_first). Two tiers:

  explore  the goal joins the exploration frontier: explore() walks to the nearest of frontier + goals, and
           another step consumes it when we stand on it. Its walk mask must use the same gate as the
           consuming step (else we walk to a square where nothing happens). gold, pile, altar, box.
           Also walked to, with no lifetime: prey (the squares next to a hostile we beat, combat.prey_mask).
  own      a policy step of its own walks to it and consumes it, at its place in STEPS.
           retrieve (our thrown missiles), corpse (fresh corpse of our kill), loot (stolen items).

Statistics per kind (summary 'goals'):
  created     goals that appeared (mask kinds: squares first seen with an uninspected pile / gold on them)
  consumed    we stood on it and did what it was for (picked up, inspected, ate)
  expired     its time ran out
  abandoned   loot: replaced by a newer theft before we got there
  vanished    mask kinds: gone from the map memory without us consuming it (picked up by a monster, the
              square turned out to be part of a shop, ...)
  unfinished  still open at the end of the game
  chase_turns game turns spent on ticks whose action was a step toward this kind (frontier and downstairs
              are counted too, for comparison)
  unreach_cell / unreach_path   own tier: ticks on which no goal of the kind could be reached because the
              goal square itself is impassable (a never-melee monster, a shop, blocked) / the way is cut
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
    holds_descent: bool = False    # items_first: don't take the stairs down while one is reachable


GOALS = {
    "gold": GoalKind("gold", "explore", holds_descent=True),
    "pile": GoalKind("pile", "explore", holds_descent=True),
    "altar": GoalKind("altar", "explore", holds_descent=True),    # items of unknown curse status (nhbot.altar)
    "box": GoalKind("box", "explore", holds_descent=True),        # boxes and chests to open (nhbot.boxes)
    "retrieve": GoalKind("retrieve", "own", ttl=60),
    "corpse": GoalKind("corpse", "own", ttl=40, max_dist=8),
    "loot": GoalKind("loot", "own"),
}
EXPLORE_KINDS = tuple(k for k, g in GOALS.items() if g.tier == "explore")
CHASE_ONLY = ("frontier", "downstairs", "prey")   # walked to, but not goals with a lifetime (prey: combat.prey_mask)
STAT_FIELDS = ("created", "consumed", "expired", "abandoned", "vanished", "unfinished", "chase_turns",
               "unreach_cell", "unreach_path", "kept")


class GoalState:
    """State of the goal ledger: open / closed goal squares and their statistics (GoalsMixin)."""
    def __init__(self):
        self.stats = {k: dict.fromkeys(STAT_FIELDS, 0) for k in tuple(GOALS) + CHASE_ONLY}
        self.open = {}                 # (kind, level key) -> set of open goal squares (mask kinds)
        self.closed = {}               # (kind, level key) -> squares done: consumed, or dropped there by us
        self.chasing = None            # kind walked toward by this tick's action


class GoalsMixin:
    def goals_init(self):
        self.goals = GoalState()

    # ------------------------------------------------------------------ events
    def goal_event(self, kind, event, n=1):
        if n:
            self.goals.stats[kind][event] += n

    def goal_chase(self, kind):
        self.goals.chasing = kind
        if kind == "box":
            self.box.chase_turn = self.turn()

    # ------------------------------------------------------------------ explore tier
    def goal_raw(self, kind, lv):
        """Goal squares of a mask kind as the map memory shows them, before any gate (for statistics)."""
        if kind == "altar":
            return self.altar_mask(lv)
        if kind == "box":
            return self.box_targets(lv)
        if kind != "gold":
            return self.pile_mask(lv)         # (A/B pile_one: -494 [-980, +4], median 7726 -> 7726, 67 of 1000 changed)
        m = G.KIND[lv.under] == G.GOLD
        for p in self.goal_closed_set(kind, lv.key):
            m[p] = False
        return m & ~lv.shop

    def goal_observe(self, lv):
        """Count goals of the mask kinds appearing on / vanishing from this level's map memory."""
        for kind in EXPLORE_KINDS:
            cur = {(int(a), int(b)) for a, b in zip(*np.nonzero(self.goal_raw(kind, lv)))}
            key = (kind, lv.key)
            prev = self.goals.open.get(key, set())
            self.goal_event(kind, "created", len(cur - prev))
            self.goal_event(kind, "vanished", len(prev - cur))
            self.goals.open[key] = cur

    def goal_closed_set(self, kind, key):
        """Squares of this kind already done on level key: never a goal again (gold: a pile shows '$' on top
        again after we leave, so it is tried once; piles: inspected once; anything we dropped ourselves)."""
        return self.goals.closed.setdefault((kind, key), set())

    def goal_close(self, kind, key, pos):
        """Mark done without counting a consumption (we dropped something here ourselves)."""
        self.goal_closed_set(kind, key).add(pos)

    def goal_done(self, kind, lv, pos):
        """A mask-kind goal at pos consumed (also when we got there before it was ever observed)."""
        key = (kind, lv.key)
        op = self.goals.open.setdefault(key, set())
        if pos in op:
            op.discard(pos)
        else:
            self.goal_event(kind, "created")
        self.goal_close(kind, lv.key, pos)
        self.goal_event(kind, "consumed")

    # ------------------------------------------------------------------ own tier
    def pursue(self, kind, lv, goals, consume):
        """One tick toward an own-tier goal, goals = its candidate squares. Like the explore tier: on any of
        them, consume it (a consume returning "keep" leaves the goal: a meal interrupted); else step toward the
        nearest reachable one by path; none reachable: nothing happens, they stay goals (until consumed or
        expired). True if the tick acted."""
        here = self.pos()
        if here in goals:
            if consume(here) == "keep":
                self.goal_event(kind, "kept")
            else:
                self.goal_event(kind, "consumed", self.goal_forget(kind, lv, here))
            return True
        mask = np.zeros(lv.under.shape, dtype=bool)
        for p in goals:
            mask[p] = True
        if self.walk_to(lv, mask, chase=kind)[0] == "moved":
            return True
        self.goal_unreachable(kind, goals, self.grids(lv)[2])
        return False

    def goal_unreachable(self, kind, goals, passable):
        """Count a tick with no reachable goal of this kind, by cause."""
        cell = not any(passable[p] for p in goals)
        self.goal_event(kind, "unreach_cell" if cell else "unreach_path")

    def goal_forget(self, kind, lv, goal):
        """Remove an own-tier goal at goal from its list; returns how many entries went."""
        if kind == "retrieve":
            n = len(self.combat.retrieve)
            self.combat.retrieve = [r for r in self.combat.retrieve if goal not in r[1]]
            return n - len(self.combat.retrieve)
        if kind == "corpse":
            n = len(self.combat.kills)
            self.combat.kills = [k for k in self.combat.kills if k[2] != goal or k[3] != lv.key]
            return n - len(self.combat.kills)
        if kind == "loot":
            self.thief.loot_sq = None
            return 1
        raise ValueError(kind)

    def goal_masks(self, lv, passable, gold):
        """Walk masks of the explore-tier kinds, {kind: mask}. All of them only under items_gate (not in combat),
        the gate of the steps that consume them; gold not in a shop when we visit shops (gold_here), piles never
        on a shop square (housekeeping inspects them)."""
        ok = self.items_gate(lv)
        # gold where step_gold_here would take it -- not where merch_risk holds (a shopkeeper in view and no shop
        # marked too), else explore walks to gold that step never picks up (A/B merch_one: -252 [-482, -47], median
        # 7777 unchanged, 15 games of 1000 changed)
        out = {"gold": gold & ~self.merch_mask(lv) & ok}
        pile = np.zeros_like(gold)
        if ok:
            im = passable & ~lv.shop
            pile |= self.pile_mask(lv) & im
        out["pile"] = pile
        out["altar"] = self.altar_mask(lv) & passable if ok else np.zeros_like(gold)
        # boxes: opened by housekeeping, so only with no hostile in view (its gate; boxes.box_goal_mask)
        out["box"] = self.box_goal_mask(lv, passable)
        out["prey"] = self.prey_mask(lv, passable) if ok else np.zeros_like(gold)   # the melee step hits it
        return out

    def goal_summary(self):
        st = {k: dict(v) for k, v in self.goals.stats.items()}
        for (kind, _), squares in self.goals.open.items():
            st[kind]["unfinished"] += len(squares)
        t = self.turn()
        for r in self.combat.retrieve:
            st["retrieve"]["expired" if r[2] <= t else "unfinished"] += 1
        for k in self.combat.kills:
            st["corpse"]["expired" if t - k[0] >= GOALS["corpse"].ttl else "unfinished"] += 1
        if self.thief.loot_sq is not None:
            st["loot"]["unfinished"] += 1
        return st
