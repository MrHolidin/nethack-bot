"""Vault gold with a digging tool (flag vault_dig).

mklev.c: a vault is a closed 2 x 2 room of gold, mkgold(rn1(depth * 100, 51)) on each square. With a third of
them comes a niche (makeniche(TELEP_TRAP)): in an ordinary room, "ad aerarium" engraved in the dust next to its
top or bottom wall (worn a little at once), a secret door in that wall right beside it, behind the door a secret
corridor square with a one-shot teleport trap that drops us inside the vault. (Below depth 15 the same words
may mark a level teleporter.)

vault.c: in a vault, every VAULT_GUARD_TIME (30) turns a guard comes and asks our name; anything but Croesus
(alive) means "drop that gold and follow me" -- all of our gold, the vault's and our own. Answering Croesus
sends the guard away (a lawful hero pays 1 alignment point for the lie).

With a digger (pick-axe, a mattock with no shield on, a wand of digging we know) this module:
  * in a vault (the closed room of at most 4 squares we stand in): picks up the gold on its squares, then digs
    down (apply > / zap >) and falls to the level below with it; the guard is answered "Croesus";
  * on a level where we read the hint: walks to it, searches for the door in the wall beside it, steps into
    the door, searches for the corridor square behind, steps onto it.
"""
import collections
import re

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.carry import DIGGER_WORDS
from nhbot.consts import COLS, CORRIDOR_GLYPHS, FLOOR_GLYPH, NEIGH, ROWS

HINT = "ad aerarium"
HINT_MIN_SAME = 4          # letters of the worn engraving still matching HINT
SEEK_SEARCHES = 25         # searches at the hint square, and again at the door, before giving up
SEEK_TURNS = 300           # turns spent on one hint at most
DIG_TRIES = 12             # applications / zaps downward in one vault at most
FLOORISH = (G.FLOOR, G.GOLD, G.OBJECT, G.CORPSE, G.TRAP, G.UNKNOWN)


def is_hint(text):
    return len(text) == len(HINT) and sum(a == b for a, b in zip(text, HINT)) >= HINT_MIN_SAME


class VaultMixin:
    def vault_init(self):
        self.vault_hints = {}          # level key -> engraving square
        self.vault_seek = None         # dict(key, pos, since, searches, door)
        self.vault_dig_tries = 0
        self.vault_picked = set()      # (key, square): gold picked up there
        self.vault_entered = set()     # level keys of the vaults we stood in with a digger
        self.vault_stats = collections.Counter()

    # ------------------------------------------------------------------ what we have
    def digger(self):
        """("zap" | "apply", letter) of what we would dig down with, or None."""
        items = self.items()
        cur = next((it for it in items if it.wielded), None)
        for it in items:
            if it.ocls == nh.WAND_CLASS and "wand of digging" in it.text and not self.wand_spent(it):
                return "zap", it.letter
        if cur is not None and cur.cursed and not any(w in cur.text for w in DIGGER_WORDS):
            return None                                   # a welded weapon: no tool can be wielded
        shield = "shield" in self.worn_by_slot()
        for it in items:
            if any(w in it.text for w in DIGGER_WORDS) and not it.cursed \
                    and not (shield and ("mattock" in it.text or "broad pick" in it.text)):
                return "apply", it.letter
        return None

    def croesus_ok(self):
        """Answer the guard "Croesus": we are digging out of a vault and Croesus is alive."""
        return bool(self.opts.vault_dig) and self.digger() is not None and "Croesus" not in self.kill_by

    # ------------------------------------------------------------------ where we are
    def vault_room(self, lv):
        """The squares of the closed room of at most 4 squares we stand in (a vault), or None."""
        start = self.pos()
        for r in self.known_vaults.get(lv.key, ()):
            if start in r:
                return r                                  # dig_through dug its way in: no longer closed
        k = self.kinds(lv)
        room, todo = {start}, [start]
        while todo:
            y, x = todo.pop()
            for dy, dx in NEIGH:
                p = (y + dy, x + dx)
                if not (0 <= p[0] < ROWS and 0 <= p[1] < COLS) or p in room:
                    continue
                if k[p] == G.WALL:
                    continue
                if k[p] in FLOORISH and k[p] != G.UNKNOWN and int(lv.under[p]) not in CORRIDOR_GLYPHS:
                    room.add(p)
                    todo.append(p)
                    if len(room) > 4:
                        return None
                else:
                    return None                           # a door, a corridor, the unknown: not closed
        return room

    # ------------------------------------------------------------------ messages
    def msg_vault(self, m):
        mm = re.search(r'You read: "(.*?)"', m)
        if mm and is_hint(mm.group(1)) and self.cur_key is not None:
            if self.cur_key not in self.vault_hints:
                self.vault_stats["hints"] += 1
            self.vault_hints.setdefault(self.cur_key, self.pos())
        if "Sorry to have disturbed you" in m:
            self.vault_stats["croesus"] += 1
        if "You dig a hole through" in m or "You dig a pit" in m:
            self.vault_stats["hole" if "hole" in m else "pit"] += 1

    # ------------------------------------------------------------------ in the vault
    def vault_escape_step(self, lv, hostiles):
        """vault_dig, in a vault with a digger: gold first, then down. True if it used the turn."""
        if not self.opts.vault_dig or hostiles:
            return False
        room = self.vault_room(lv)
        d = self.digger() if room is not None else None
        if d is None:
            return False
        if lv.key not in self.vault_entered:
            self.vault_entered.add(lv.key)
            self.vault_dig_tries = 0
            self.vault_stats["in_vault"] += 1
        here = self.pos()
        if (lv.key, here) not in self.vault_picked:
            self.vault_picked.add((lv.key, here))
            seq0 = self.msg_seq
            self.cur_act = "vault_dig"
            self.pickup_matching(("gold piece",))
            if self.msg_seq != seq0:
                lv.under[here] = FLOOR_GLYPH
                self.vault_stats["gold_squares"] += 1
                return True
        left = [p for p in room if (lv.key, p) not in self.vault_picked]
        if left:
            mask = np.zeros((ROWS, COLS), dtype=bool)
            for p in left:
                mask[p] = True
            if self.walk_to(lv, mask, act="vault_dig")[0] == "moved":
                return True
        if self.vault_dig_tries >= DIG_TRIES:
            return False
        self.vault_dig_tries += 1
        self.vault_stats["digs"] += 1
        self.cur_act = "vault_dig"
        return self.dig_down(d)

    def dig_down(self, d):
        kind, letter = d
        if kind == "zap":
            return self.zap(letter, ">")
        if not self.ask("a", "apply"):
            return False
        self.press(letter, expect_prompt=True)
        if "direction" in self.message().lower():
            self.press(">")
        else:
            self.settle()
        return True

    def vault_digging(self):
        """Keep the digger in hand: we are in a vault with one (weapon_check waits)."""
        if not self.opts.vault_dig:
            return False
        lv = self.levels.get(self.cur_key)
        return lv is not None and self.vault_room(lv) is not None and self.digger() is not None

    # ------------------------------------------------------------------ the way in
    def vault_seek_step(self, lv, hostiles):
        """vault_dig, a hint read on this level and a digger: into the niche. True if it used the turn."""
        if not self.opts.vault_dig or hostiles or self.visible_hostiles(lv) or self.digger() is None:
            return False
        hint = self.vault_hints.get(lv.key)
        if hint is None or lv.key[1] > 15 and lv.key[0] == 0:
            return False
        s = self.vault_seek
        if s is None or s["key"] != lv.key:
            s = self.vault_seek = {"key": lv.key, "pos": hint, "since": self.turn(), "searches": 0, "door": None,
                                   "done": False}
            self.vault_stats["seek"] += 1
        if s["done"]:
            return False
        if self.turn() - s["since"] > SEEK_TURNS or s["searches"] > 2 * SEEK_SEARCHES:
            s["done"] = True
            self.vault_stats["seek_gave_up"] += 1
            return False
        k = self.kinds(lv)
        y, x = hint
        doors = (G.DOOR_OPEN, G.DOOR_CLOSED, G.DOORWAY)
        if s["door"] is None:
            for dy in (-1, 1):
                if 0 <= y + dy < ROWS and k[y + dy, x] in doors:
                    s["door"] = (y + dy, x, dy)
        here = self.pos()
        self.cur_act = "vault_seek"
        if s["door"] is None:
            if here != hint:
                mask = np.zeros((ROWS, COLS), dtype=bool)
                mask[hint] = True
                return self.walk_to(lv, mask, act="vault_seek")[0] == "moved"
            s["searches"] += 1
            self.press("s")
            return True
        dy_, dx_, dy = s["door"]
        door, niche = (dy_, dx_), (dy_ + dy, dx_)
        if not (0 <= niche[0] < ROWS):
            s["done"] = True
            return False
        if k[niche] in (G.FLOOR, G.TRAP) or int(lv.under[niche]) in CORRIDOR_GLYPHS:
            mask = np.zeros((ROWS, COLS), dtype=bool)
            mask[niche] = True
            if here == niche:
                s["done"] = True                      # the trap is gone (used before): nothing more here
                self.vault_stats["niche_empty"] += 1
                return False
            if self.walk_to(lv, mask, act="vault_seek")[0] == "moved":
                if self.pos() == niche or self.cur_key != lv.key:
                    self.vault_stats["niche_entered"] += 1
                return True
            return False                              # not reachable now: explore on, try again later
        if here != door:
            mask = np.zeros((ROWS, COLS), dtype=bool)
            mask[door] = True
            return self.walk_to(lv, mask, act="vault_seek")[0] == "moved"
        s["searches"] += 1
        self.press("s")
        return True
