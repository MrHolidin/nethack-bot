"""Large boxes and chests: walk to the ones we saw (an explore goal, kind "box"), and with no hostile in view open
them and take out what the floor rules would take (pickup.take_reason). A/B open_boxes (with the pause), seeds
72000 over base_k: score +1597 [+394, +2779], max_depth +0.1 [-0.1, +0.4]; seeds 71000 over base_i (before wand
identification): score -434 [-1737, +885].

NetHack 3.6.6 facts (mkobj.c, lock.c, dokick.c, trap.c):
  contents     chest 0..5 random objects (0..7 if locked), large box 0..3 (0..5)
  locked       4 in 5. #force with the wielded weapon: a blade pries (chance a turn = 2 x its large-monster
               damage die: dagger 6%, long sword 24%) and may break (about 0.6% a turn): so the alternate dagger
               is swapped in for it ('x', weapons.swap_in) and back after. No dagger, or it broke: kick the box
               from a square next to it -- the lock gives 1 time in 5, and every kick shatters each glass item
               inside (potions) with probability 2/3; the rest is unharmed.
  trapped      1 in 10, set off by opening or kicking; at Luck 0 harmless 5 times in 13, else fire, a shock,
               paralysis for 5..30 turns, stun and hallucination, rarely poison or an explosion.
  mimics       a mimic can look like a box, but we stand on the box to open it, and nothing stands on a mimic.
Not opened: boxes in shops (the contents are merchandise), ice boxes (corpses).
"""
import re
from collections import Counter

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import DELTA2KEY, NEIGH

BOX_NAMES = ("large box", "chest")
BOX_GLYPH = np.zeros(nh.MAX_GLYPH, dtype=bool)
for _i in range(nh.NUM_OBJECTS):
    if nh.OBJ_NAME(nh.objclass(_i)) in BOX_NAMES:
        BOX_GLYPH[nh.GLYPH_OBJ_OFF + _i] = True
BOX_TRIES = 12                   # actions on one box (loot, force, kick) before giving it up
FAILED_TRIES = 3                 # loot attempts that ended in neither contents nor a lock before giving up
FORCE_TRIES = 2                  # #force attempts (50 turns at most each) before kicking instead
BOX_PAUSE = 300                  # turns a level's boxes are no goal after a hostile showed up on the way
KICK_TRIES = 12                  # kicks (the lock gives 1 in 5)
KICK_FROM = (G.FLOOR, G.TRAP, G.DOWNSTAIR, G.UPSTAIR, G.OBJECT, G.GOLD, G.CORPSE)   # squares we kick from
NO_ACT = nh.BL_MASK_BLIND | nh.BL_MASK_CONF | nh.BL_MASK_STUN | nh.BL_MASK_HALLU | nh.BL_MASK_LEV


class BoxMixin:
    def box_init(self):
        self.box_stats = Counter()
        self.box_tries = Counter()       # (level key, square) -> actions spent on that box
        self.box_forces = Counter()      # (level key, square) -> #force attempts on that box
        self.box_fails = Counter()       # (level key, square) -> loot attempts that got neither contents nor a lock
        self.box_kick = None             # (level key, box square): kicking it open from next to it
        self.box_paused = {}             # (level key, square) -> turn: not a goal until then (box_pause)
        self.box_chase_turn = -1         # last turn we walked toward a box

    # ------------------------------------------------------------------ goal
    def box_targets(self, lv):
        """Remembered boxes not done yet, outside shops (goals.goal_raw / goal_masks, kind "box")."""
        m = BOX_GLYPH[lv.under] & ~lv.shop
        for p in self.goal_closed_set("box", lv.key):
            m[p] = False
        t = self.turn()
        for (key, p), until in self.box_paused.items():
            if key == lv.key and t < until:
                m[p] = False
        return m

    def box_goal_mask(self, lv, passable):
        """goals.goal_masks, kind "box": the boxes to walk to now. Only with no hostile in view (the gate of
        box_step); and when one shows up while we were on our way to a box, the level's boxes stop being
        goals for BOX_PAUSE turns -- else we walk in, see it, turn away, lose sight of it and walk in again
        (sleeping graveyard undead do not come to fight)."""
        box = self.box_targets(lv)
        if not box.any():
            return box
        if self.view_threats(lv):
            if self.turn() - self.box_chase_turn <= 2:
                until = self.turn() + BOX_PAUSE
                for p in zip(*np.nonzero(box)):
                    self.box_paused[(lv.key, (int(p[0]), int(p[1])))] = until
                self.box_stats["paused"] += 1
            return np.zeros_like(box)
        return box & passable

    def box_done(self, lv, pos, why):
        self.box_stats[why] += 1
        self.box_kick = None
        self.goal_done("box", lv, pos)

    # ------------------------------------------------------------------ step
    def box_step(self, lv):
        """Housekeeping (no hostile in view): open the box under us, or go on kicking one open. True if it
        used the turn."""
        if self.box_kick is not None:
            return self.box_kick_step(lv)
        pos = self.pos()
        if not self.box_targets(lv)[pos]:
            return self.swap_back("box")
        if int(self.last_bl[nh.NLE_BL_CONDITION]) & NO_ACT or self.handless():
            return False
        key = (lv.key, pos)
        self.box_tries[key] += 1
        if self.box_tries[key] > BOX_TRIES:
            self.box_done(lv, pos, "gave_up")
            return self.swap_back("box")
        self.cur_act = "box"
        r = self.box_loot()
        if r == "opened" or r == "empty":
            self.box_done(lv, pos, r)
            return True
        if r == "failed":
            self.box_fails[key] += 1
            if self.box_fails[key] < FAILED_TRIES:
                return True                      # something came between (a trap went off, --More--): again
        if r != "locked":
            self.box_done(lv, pos, "no_box" if r == "none" else "failed")
            return True
        if self.swapped_for is None and self.lock_box_step(key):
            return True                          # lock_tools: unlocked with the tool, nothing broken
        if self.swapped_for == "box" and self.box_forces[key] < FORCE_TRIES:
            return self.box_force(key)
        opener = self.dagger_alternate() if self.swapped_for is None and self.box_forces[key] < FORCE_TRIES else None
        if opener is not None:
            self.swap_in("box", opener)
            return True
        if self.swap_back("box"):
            return True
        self.box_kick = (lv.key, pos)
        self.box_stats["kick_start"] += 1
        return self.box_kick_step(lv)

    def box_loot(self):
        """#loot the box under us. "opened" (took what we want), "empty", "locked", "none" (no box here), or
        "failed"."""
        seq0 = self.msg_seq
        self.press("#", expect_prompt=True)
        for c in "loot":
            self.raw_step(ord(c))
        self.press(13, expect_prompt=True)
        took = None
        for _ in range(12):
            tty, msg = self.tty_text(), self.message()
            if self.obs["misc"][0] and "loot it?" in msg:
                self.press("y", expect_prompt=True)
                continue
            if "Do what with" in tty:
                self.raw_step(ord("o"))
                continue
            if "Take out what type" in tty:
                self.raw_step(ord("a"))                  # all types: the item menu comes next
                self.raw_step(13)
                continue
            if "Take out what?" in tty:
                self._take_state = (self.food_count(), self.bl(nh.NLE_BL_CAP))
                try:
                    took = self.menu_pick("Take out what?", lambda t: self.take_reason(t) is not None)
                finally:
                    self._take_state = None
                continue
            break
        self.settle()
        said = self.text_since(seq0)
        if "trigger a trap" in said or "set it off" in said:
            self.box_stats["trap"] += 1
        if re.search(r"\blocked\b", said):
            return "locked"                      # not "There is an unlocked chest here" (lock_tools opened it)
        if "is empty" in said:
            return "empty"
        if took is not None:
            self.box_stats["taken"] += took
            return "opened"
        if "here to loot" in said:
            return "none"
        return "failed"

    def box_force(self, key):
        """#force the lock with the dagger in hand (an occupation: the game runs it until done or interrupted)."""
        self.box_forces[key] += 1
        seq0 = self.msg_seq
        self.press("#", expect_prompt=True)
        for c in "force":
            self.raw_step(ord(c))
        self.press(13, expect_prompt=True)
        if self.obs["misc"][0] and "force its lock" in self.message():
            self.press("y")
        else:
            self.settle()
        said = self.text_since(seq0)
        if "succeed in forcing" in said:
            self.box_stats["forced"] += 1
        elif "broke" in said:
            self.box_stats["dagger_broke"] += 1
            self.swapped_for = None              # the dagger is gone: nothing to swap back from
        return True

    def box_kick_step(self, lv):
        """Kick the box open from a square next to it (step off it first). True if it used the turn."""
        key, box = self.box_kick
        if key != lv.key:
            self.box_kick = None                 # left the level: the goal stays there
            return False
        if self.box_tries[(key, box)] > BOX_TRIES + KICK_TRIES:
            self.box_done(lv, box, "gave_up")
            return False
        y, x = self.pos()
        live = G.KIND[self.obs["glyphs"]]
        if (y, x) == box:
            k = self.kinds(lv)
            rows, cols = k.shape
            order = sorted(NEIGH, key=lambda d: abs(d[0]) + abs(d[1]))       # straight first: doorways
            for dy, dx in order:
                ny, nx = y + dy, x + dx
                if 0 <= ny < rows and 0 <= nx < cols and k[ny, nx] in KICK_FROM \
                        and live[ny, nx] not in (G.MONSTER, G.PET, G.INVIS, G.BOULDER):
                    self.cur_act = "box"
                    self.move((ny, nx))
                    return True
            self.box_done(lv, box, "no_room_to_kick")
            return False
        if max(abs(box[0] - y), abs(box[1] - x)) != 1:
            self.box_kick = None                 # moved away: the goal walks us back, the lock decides again
            return False
        if live[box] in (G.MONSTER, G.PET, G.INVIS):
            self.cur_act = "box"
            self.press("s")                      # something on the box: don't kick it
            return True
        self.box_tries[(key, box)] += 1
        self.box_stats["kicks"] += 1
        self.cur_act = "box"
        seq0 = self.msg_seq
        self.kick(DELTA2KEY[(box[0] - y, box[1] - x)])
        said = self.text_since(seq0)
        if "trigger a trap" in said or "set it off" in said:
            self.box_stats["trap"] += 1
        if "break open the lock" in said:
            self.box_stats["kicked_open"] += 1
            self.box_kick = None                 # the goal walks us back onto it to loot
        return True
