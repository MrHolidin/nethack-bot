"""The primitive game actions. Each one sends its keys and does its own bookkeeping (what we attacked, where a
staircase we took leads, what we threw and where to pick it up, what a zap told, where we dropped something), so
the steps above never press these command keys themselves."""
from nhbot.consts import DELTA2KEY
from nhbot.goals import GOALS
from nhbot.items import base_name


class ActionsMixin:
    def actions_init(self):
        self.last_attack_target = None   # the square we last attacked (melee, missile, wand): kills are noted there
        self.took_stairs = False         # the last action was a staircase (mapmem.note_arrival reads it)
        self.last_stair_dir = None       # '<' / '>' of the staircase we took this tick
        self.stair_from = None           # (level key, square) of the staircase we last took
        self.throws = 0
        self.zaps = 0
        self.own_zap_turn = -99          # a bouncing ray of ours is not an enemy shooter

    def attack(self, target):
        """Fight the monster on the square next to us (F + direction)."""
        self.cur_act = "fight"
        y, x = self.pos()
        if (target[0] - y, target[1] - x) not in DELTA2KEY:   # we were moved this tick (e.g. teleported)
            self.press("s")
            return
        key = DELTA2KEY[(target[0] - y, target[1] - x)]
        self.last_attack_target = target
        self.attack_turn = self.turn()           # danger: the monster we hit first may not act
        self.last_move_target = None
        self.press("F")
        self.press(key)

    def attack_engulfer(self):
        """Engulfed: hit in any direction -- the engulfer is all around us (no square to note)."""
        self.last_attack_target = None
        self.press("F")
        self.press("h")

    def take_stairs(self, key):
        """Up ('<') or down ('>') the staircase we stand on. Where it led is noted next tick (mapmem.note_arrival:
        Level.stairs_to, the staircase under us on arrival)."""
        self.last_stair_dir = key
        self.stair_from = (self.cur_key, self.pos())
        self.took_stairs = True
        self.press(key)

    def search_turns(self, n):
        """Rest / search n turns: the count, then 's' ("20s"); the game stops early when something shows up."""
        for c in str(n):
            self.press(c)
        self.press("s")

    def throw(self, letter, key, ray):
        """Throw the item letter in direction key; ray: the squares it may land on (picked up again later)."""
        if not self.ask("t", "throw"):
            return
        self.press(letter, expect_prompt=True)
        if "direction" not in self.message().lower() and self.obs["misc"][0] == 0:
            self.msg_audit["throw_key_without_direction"] += 1
        if "direction" in self.message().lower() or self.obs["misc"][0] == 0:
            self.press(key)
        else:
            self.settle()
        self.throws += 1
        self.elb_scuffed()                       # a throw scuffs the engraving under us
        self.retrieve.append((self.cur_key, ray, self.turn() + GOALS["retrieve"].ttl))
        self.goal_event("retrieve", "created")

    def zap(self, letter, key):
        """Zap the wand letter in direction key; its charges (charges.py) and whom a sleep ray hit (combat.py) noted.
        False if no zap was asked for."""
        self.own_zap_turn = self.turn()           # a bouncing ray of ours is not an enemy shooter
        seq0 = self.msg_seq
        wand = next(it for it in self.items() if it.letter == letter)
        if not self.ask("z", "zap"):
            return False
        self.press(letter, expect_prompt=True)
        m = self.message().lower()
        if "direction" in m:
            self.press(key)
        else:
            self.settle()
        msgs = self.text_since(seq0)
        self.note_wand_use(wand, msgs)                   # charges.py
        self.zaps += 1
        self.note_slept(key, msgs)
        return True

    def engrave(self, stylus, text):
        """E with stylus ('-': fingers, or an inventory letter) and write text, answering what comes between:
        'add to the current engraving?' (no), --More--, and the wish a wand of wishing grants. True if the
        text was written."""
        if not self.ask("E", "write with"):
            return False
        self.press(stylus, expect_prompt=True)
        for _ in range(8):
            if self.obs["misc"][0]:          # "Do you want to add to the current engraving?"
                self.press("n", expect_prompt=True)
                continue
            if "--more--" in self.tty_text().lower():
                self.raw_step(13)
                continue
            if self.obs["misc"][1] and "wish" in self.top_line().lower():
                self.answer_wish()               # zap.c zapnodir: engraving with a wand of wishing zaps it
                continue
            break
        if self.obs["misc"][1]:
            for c in text:
                self.raw_step(ord(c))
            self.press(13)
            return True
        self.settle()
        return False

    def drop_units(self, letter, n=None):
        """Drop n of a stack (all if None); remember the square."""
        item = next((it for it in self.items() if it.letter == letter), None)
        self.last_drop_qty = n or (base_name(item.text)[0] if item else 1)
        self.goal_close("pile", self.level().key, self.pos())      # never come back for what we dropped
        seq0 = self.msg_seq
        if not self.ask("d", "drop"):
            return
        if n:
            for c in str(n):
                self.raw_step(ord(c))
        self.press(letter)
        if any("cannot drop" in t for t in self.msgs_since(seq0)) and item is not None:
            self.cant_drop.add(item.key)      # "For some reason, you cannot drop the stone!"
