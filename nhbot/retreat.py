"""retreat: leave a melee fight we are losing instead of trading blows to the end (option `retreat`, off by default).

Why: in the baseline about half of all deaths come with the prayer on timeout, a median of 40 turns after it: the
prayer gave the HP back, the bot fought on against the same monsters and lost (auto/notes/diag.md on a/diag).

When (retreat_losing): a hostile next to us, the prayer not available (it is the better rescue: step_pray acts
first), HP below retreat_hp of max HP and danger.win_prob of the fight next to us below retreat_win. For
retreat_pp_window turns after a prayer the thresholds are retreat_pp_hp / retreat_pp_win instead (post-prayer
disengage: the fight that brought us down is usually still there). An unseen attacker counts as a monster of the
level the danger model takes for an unseen one: win_prob leaves out names it does not know.

The ways out, in order:
  stairs   a known staircase (up or down) by a path that keeps off the squares next to the monsters chasing us.
           A monster moves *or* attacks in one move (monmove.c dochug: m_move returning 1 -- moved -- returns before
           mattacku unless it has a ranged attack), so a chaser no faster than us gets no blow while we walk; a faster
           one does: then only a staircase within retreat_near steps. Only M2_STALK monsters next to us follow us to
           the other level (dog.c keepdogs -> levl_follower), so the stairs shake off every non-stalker and every
           stalker we got one square ahead of. Not taken: up from level 1 (leaving the dungeon ends the game), into
           the Mines while they are closed (mines_tick would bounce us straight back), Sokoban's up staircase; and,
           within retreat_cool turns of a flight a stalker followed, not again (a stair dance with it changes nothing).
  elbereth written when every monster in view that blocks it (elb_rules.blockers) blocks it only because it MIGHT
           carry a missile or a wand (class C: trolls, dwarves, orcs, ...) -- step_elbereth's own rule refuses those;
           losing, a scared troll (monmove.c onscary) that may poke us with a polearm beats a troll in melee. elb_step
           then rests on it and leaves it when the HP still falls (its "ranged" exit).
  scroll   a scroll of teleportation known by name: read (read.c: a random square of this level).
  dig      a wand of digging known by name: zapped down (zap.c zap_dig: a hole, we fall to the next level) -- not in a
           shop (the shopkeeper grabs the pack), not in Sokoban, not where the floor was refused.

After a flight by the stairs (retreat_rest): on the staircase we arrived on, nothing in view, not Hungry: rest until
retreat_rest of max HP (at most RETREAT_REST_MAX turns a flight) -- the staircase is at hand if something comes.

Counted in the summary "retreat": triggers, the exits taken, flights a stalker followed, deaths within 50 turns of a
retreat action (died_after).
"""
from collections import Counter

import numpy as np
import nle.nethack as nh

from nhbot import elb_rules as ELB
from nhbot import glyphs as G
from nhbot.consts import COLS, HUNGRY, NEIGH, ROWS
from nhbot.monsters import M2_STALK, PM_BY_NAME

CHASE_DIST = 7               # visible hostiles this close that are coming for us (threats.active_threat) chase us
RETREAT_STATE_TURNS = 40     # a walk to the stairs goes on at most this long without a new trigger
RETREAT_REST_MAX = 400       # turns at most resting on the arrival staircase after one flight
SOKOBAN_DNUM, MINES_DNUM = 4, 2


class RetreatState:
    """State of retreating (RetreatMixin)."""
    def __init__(self):
        self.stats = Counter()
        self.walk = None             # dict(key, since): walking to a staircase to leave by
        self.flight = None           # dict(key, turn, followed, rested): the last flight by the stairs
        self.last_act = None         # turn of the last retreat action (died_after)
        self.wp_cache = (None, None)
        self.why = ("-", "-")         # why the stairs / Elbereth were not taken this tick (retreat_why)
        self.why_stats = Counter()


class RetreatMixin:
    def retreat_init(self):
        self.retreat = RetreatState()

    # ------------------------------------------------------------------ when
    def retreat_after_prayer(self):
        lp = self.surv.last_pray
        return lp is not None and self.opts.retreat_pp_window > 0 and self.turn() - lp <= self.opts.retreat_pp_window

    def retreat_win(self, hostiles):
        """win_prob of the fight next to us, once a tick, the model's RNG state restored (as combat.prey_win)."""
        key = (self.pol.tick_no, tuple(hostiles))
        if self.retreat.wp_cache[0] != key:
            state = self.danger.win_rng.bit_generator.state
            p = self.win_prob(list(hostiles))
            self.danger.win_rng.bit_generator.state = state
            self.retreat.wp_cache = (key, p)
        return self.retreat.wp_cache[1]

    def retreat_losing(self, hostiles):
        """The fight next to us is being lost (module docstring): True / False."""
        if not hostiles or self.can_pray():
            return False
        pp = self.retreat_after_prayer()
        hp_thr = self.opts.retreat_pp_hp if pp else self.opts.retreat_hp
        if not self.hp_below(hp_thr):
            return False
        known = [t for t in hostiles if t[1] in PM_BY_NAME]
        if not known:
            return False
        win_thr = self.opts.retreat_pp_win if pp else self.opts.retreat_win
        return self.retreat_win(known) < win_thr

    def chasers(self, lv, hostiles):
        """[(pos, name)]: the hostiles next to us and those in view within CHASE_DIST coming for us."""
        y, x = self.pos()
        out = list(hostiles)
        for p, n in self.visible_hostiles(lv):
            if (p, n) not in out and max(abs(p[0] - y), abs(p[1] - x)) <= CHASE_DIST and self.active_threat(p):
                out.append((p, n))
        return out

    # ------------------------------------------------------------------ the step
    def step_retreat(self, c):
        """policy step "retreat" (after wands, before melee). True if it acted."""
        if not self.opts.retreat:
            return False
        lv = c.lv
        if self.retreat_rest_step(c):
            return True
        walking = self.retreat.walk is not None and self.retreat.walk["key"] == lv.key \
            and c.t - self.retreat.walk["since"] <= RETREAT_STATE_TURNS
        losing = self.retreat_losing(c.hostiles)
        if losing:
            self.retreat.stats["losing_ticks"] += 1
        if not losing and not walking:
            self.retreat.walk = None
            return False
        ch = self.chasers(lv, c.hostiles)
        self.retreat.why = ("-", "off" if not self.opts.retreat_elb else "-")
        if walking and not losing:
            hp_thr = self.opts.retreat_pp_hp if self.retreat_after_prayer() else self.opts.retreat_hp
            if not ch or not self.hp_below(hp_thr):
                self.retreat.walk = None
                return False
        if self.retreat_stairs(c, ch):
            return True
        self.retreat.walk = None
        if not losing:
            return False
        if self.opts.retreat_elb and self.retreat_elbereth(lv, c.hostiles):
            return True
        if self.retreat_scroll(lv):
            return True
        if self.retreat_dig(lv):
            return True
        self.retreat.stats["no_exit"] += 1
        self.retreat.why_stats["stairs:" + self.retreat.why[0]] += 1
        self.retreat.why_stats["elb:" + self.retreat.why[1]] += 1
        for _, n in c.hostiles:
            self.retreat.why_stats["mon:" + n] += 1
        return False

    def retreat_why(self, why, stairs=True):
        """Note why an exit was not taken (summary "retreat_why", counted on the ticks no exit was found). False."""
        w = self.retreat.why
        self.retreat.why = (why, w[1]) if stairs else (w[0], why)
        return False

    def retreat_acted(self, what):
        self.retreat.stats[what] += 1
        self.retreat.last_act = self.turn()

    # ------------------------------------------------------------------ the stairs
    def retreat_stairs_mask(self, lv):
        """The staircases we may leave by (module docstring)."""
        k_mem = self.kinds(lv)
        up = self.stairs_mask(lv, G.UPSTAIR, k_mem)
        down = self.stairs_mask(lv, G.DOWNSTAIR, k_mem)
        if lv.key == (0, 1):
            up[:] = False                                   # up from Dlvl 1: out of the dungeon, the game over
        for p, k in lv.stairs_to.items():
            if k[0] == SOKOBAN_DNUM:
                up[p] = False
                for dy, dx in NEIGH:                         # the noted square may be beside it (linked_stairs)
                    q = (p[0] + dy, p[1] + dx)
                    if 0 <= q[0] < ROWS and 0 <= q[1] < COLS:
                        up[q] = False
        if lv.key[0] == 0 and self.mines_blocked():
            for p in self.mines_stairs(lv) | set(lv.avoid_down):
                down[p] = False
        if self.in_sokoban(lv):
            up[:] = down[:] = False
        return up | down

    def retreat_stairs(self, c, ch):
        """To a staircase and off this level (module docstring). True if it acted."""
        lv = c.lv
        y, x = c.y, c.x
        ours = self.our_speed()
        fl = self.retreat.flight
        if fl is not None and fl["followed"] and fl["key"] == lv.key and c.t - fl["turn"] <= self.opts.retreat_cool:
            return self.retreat_why("cool")                 # a stalker came along last time: no stair dance
        pms = [PM_BY_NAME.get(n) for _, n in ch]
        stalkers = [t for t, pm in zip(ch, pms) if pm is not None and pm.mflags2 & M2_STALK or t[1] == "invisible"]
        slower = [t for t, pm in zip(ch, pms) if pm is not None and pm.mmove < ours]
        if ch and len(stalkers) == len(ch) and not slower:
            return self.retreat_why("all_stalk")            # every one of them follows us and keeps up: no gain
        mask = self.retreat_stairs_mask(lv)
        if not mask.any():
            return self.retreat_why("no_stairs")
        if mask[y, x]:
            followers = [t for t in c.hostiles if t in stalkers]
            if ch and len(followers) == len(ch):
                return self.retreat_why("followers")        # all that chase us stand next to us and follow
            self.retreat.flight = {"key": None, "from": lv.key, "turn": c.t, "followed": False,
                                   "rested": 0, "n_follow": len(followers)}
            self.retreat.walk = None
            kind = self.stairs_kind_here(lv)
            self.retreat_acted("stairs_up" if kind == G.UPSTAIR else "stairs_down")
            self.cur_act = "retreat"
            self.take_stairs("<" if kind == G.UPSTAIR else ">")
            return True
        fast = any(pm is not None and pm.mmove > ours for pm in pms)
        k_mem, k_live, passable = self.grids(lv)
        near = np.zeros((ROWS, COLS), dtype=bool)          # squares next to a chaser: a step there costs a blow
        for (py, px), _ in ch:
            near[max(0, py - 1):py + 2, max(0, px - 1):px + 2] = True
        ok = passable & ~near & (k_live != G.MONSTER) & (k_live != G.INVIS)
        ok |= mask & passable                               # the staircase itself, next to one or not
        limit = self.opts.retreat_near if fast else self.opts.retreat_far
        _, prev, reached = self.dijkstra(lv, k_mem, k_live, ok, (y, x), mask, max_cost=limit, want_dist=False)
        step = self.first_step(prev, (y, x), reached) if reached is not None else None
        if step is None:
            return self.retreat_why("far_fast" if fast else "no_path")
        if self.retreat.walk is None or self.retreat.walk["key"] != lv.key:
            self.retreat.walk = {"key": lv.key, "since": c.t}
            self.retreat.stats["walks"] += 1
        self.retreat_acted("walk_steps")
        self.cur_act = "retreat"
        self.move(step)
        return True

    def retreat_arrival(self, lv, hostiles):
        """The first tick on the level a flight brought us to: did a stalker come along?"""
        fl = self.retreat.flight
        if fl is None or fl["key"] is not None:
            return
        if lv.key == fl["from"]:
            fl["key"] = "failed"                            # still here: no staircase after all (not_stairs)
            return
        fl["key"] = lv.key
        fl["followed"] = bool(hostiles)
        if hostiles:
            self.retreat.stats["followed"] += 1

    def retreat_rest_step(self, c):
        """After a flight by the stairs: rest on the arrival staircase (module docstring). True if it acted."""
        self.retreat_arrival(c.lv, c.hostiles)
        fl = self.retreat.flight
        if fl is None or fl["key"] != c.lv.key or self.opts.retreat_rest <= 0:
            return False
        if fl["rested"] >= RETREAT_REST_MAX or not self.hp_below(self.opts.retreat_rest) or c.hostiles:
            return False
        if c.hunger >= HUNGRY or self.stairs_kind_here(c.lv) is None:
            self.retreat.stats["rest_no_" + ("hungry" if c.hunger >= HUNGRY else "stairs")] += 1
            return False
        if c.vis and self.turn() - self.combat.last_shot_turn <= 5:
            return False                                    # shot at: the fight steps answer it
        t0 = self.turn()
        self.cur_act = "rest"
        if c.vis:
            # something in view, not next to us: wait a turn on the staircase rather than let explore take it back
            # down to what we fled from (300116: down again at half HP into five hill orcs, three times)
            self.retreat.stats["rest_waits"] += 1
            self.press("s")
        else:
            self.search_turns(20)
        dt = max(1, self.turn() - t0)
        fl["rested"] += dt
        self.retreat.stats["rest_turns"] += dt
        return True

    # ------------------------------------------------------------------ Elbereth, scroll, wand
    def retreat_elbereth(self, lv, hostiles):
        """Elbereth against monsters that respect it, though a class-C one in view (may carry a missile or a wand)
        keeps step_elbereth from writing (module docstring). True if it acted."""
        if self.elb.state is not None or not self.elb_can_write(lv):
            return self.retreat_why("elb_cant", stairs=False)
        if any(not self.respects(p, n) for p, n in hostiles):
            return self.retreat_why("elb_ignored", stairs=False)
        glyphs, me = self.obs["glyphs"], self.pos()
        pp = {p for p in self.visible_monsters() if self.peaceful_now(lv, p, look=False)}
        if ELB.blockers(glyphs, me, pp, lv.key[0], optimistic=True):
            return self.retreat_why("elb_blocked", stairs=False)
        self.retreat_acted("elbereth")
        return self.elb_write(lv)

    def retreat_scroll(self, lv):
        it = self.find_item(nh.SCROLL_CLASS, ("teleportation",))
        if it is None or int(self.last_bl[nh.NLE_BL_CONDITION]) & nh.BL_MASK_BLIND:
            return False
        if self.in_sokoban(lv):
            return False
        if not self.ask("r", "read"):
            return False
        self.retreat_acted("scroll")
        self.cur_act = "retreat"
        self.press(it[0])
        return True

    def retreat_dig(self, lv):
        wand = next((it for it in self.items() if it.ocls == nh.WAND_CLASS and "wand of digging" in it.text
                     and ":0)" not in it.text and "cancelled" not in it.text), None)
        if wand is None or lv.key in self.digging.refused or lv.shop[self.pos()] or self.in_sokoban(lv):
            return False
        if self.stairs_kind_here(lv) is not None:
            return False                                    # zap.c zap_dig: the stairs are too hard to dig in
        seq0 = self.msg_seq
        if not self.zap(wand.letter, ">"):
            return False
        self.retreat_acted("dig")
        self.cur_act = "retreat"
        if "too hard to dig" in self.text_since(seq0):
            self.dig_refused_here(lv)
        return True

    # ------------------------------------------------------------------ summary
    def retreat_summary(self):
        if not self.opts.retreat:
            return {}
        out = dict(self.retreat.stats)
        if self.done and not self.truncated and self.retreat.last_act is not None:
            out["died_after"] = int(self.turn() - self.retreat.last_act <= 50)
        return {"retreat": out, "retreat_why": dict(self.retreat.why_stats)}
