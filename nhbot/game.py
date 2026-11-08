"""Talking to the game: keys, prompts, messages, the status line and the inventory text."""
import re
from collections import Counter, deque

import nle.nethack as nh

from nhbot.consts import DELTA2KEY
from nhbot.events import RESHOW_KEYS, Message
from nhbot.items import parse_item


MENU_RE = re.compile(r"\(end\)|\(\d+ of \d+\)")      # a menu or text window is on screen
MENU_ITEM_RE = re.compile(r"^\s*([a-zA-Z]) - (.*)$")
MENU_ITEM_GOLD_RE = re.compile(r"^\s*([a-zA-Z$]) - (.*)$")   # gold's line too: "$ - 173 gold pieces" (goldbag)
PAGE_RE = re.compile(r"\((\d+) of (\d+)\)")       # a menu page: "(1 of 2)"


class GameOver(Exception):
    pass


class GameMixin:
    def game_init(self):
        self.steps = 0                   # keys sent so far
        self.last_key = None             # the key sent last (log_msg: a message NLE shows again after it)
        self.reward = 0.0
        self.done = False
        self.truncated = False
        self.messages = deque()
        self.msg_seq = 0                 # total messages logged so far (the deque keeps only the last 60)
        self.all_msgs = []               # every message (verbose)
        self._last_logged, self._last_logged_step = None, -1
        self.asked = ""                  # ask: the last question's message
        self.really_attacks = 0          # "Really attack?" questions (answered no)
        self._items, self._items_at = [], -1
        self._items_parsed, self._items_inv = [], None
        self._inv, self._inv_at = (), -1
        self.msg_audit = Counter()       # cases where message reading may go wrong (game.audit, pickup, ...)
        self.here_window = None          # (turn, pos, text) of the last 'Things that are here' window
        self.seen_here = None            # (turn, pos, message) of the last message listing what lies here

    def raw_step(self, code):
        if code not in self.key2act:
            raise ValueError(f"key {code!r} not in action set")
        self.obs, r, term, trunc, info = self.env.step(self.key2act[code])
        self.steps += 1
        self.last_key = code
        self.reward += r
        self.done = term or trunc
        if not self.done:
            self.last_bl = self.obs["blstats"].copy()
        if self.done:
            raise GameOver()
        if self.steps >= self.max_steps or (self.max_turns and self.turn() >= self.max_turns):
            self.truncated = True
            raise GameOver()

    def press(self, key, expect_prompt=False):
        """Send one key, then clear --More-- and unexpected menus/prompts."""
        code = ord(key) if isinstance(key, str) else key
        self.raw_step(code)
        self.settle(expect_prompt)

    def settle(self, expect_prompt=False):
        for _ in range(50):
            tty = self.tty_text()
            msg = self.message()
            flat = tty.replace("\n", "")
            menu = MENU_RE.search(tty)
            id_menu = self.identify_menu_shown(tty, menu)        # jewelry.py
            if "Things that are here" in tty:
                self.here_window = (self.turn(), self.pos(), " | ".join(
                    l.strip() for l in self.menu_lines(tty, "Things that are here")))
            # mapmem: "There is a staircase down here." -- atop the window, or first on the top line, where the
            # message observation holds only the last message of the line ("You see here a large box.")
            self.note_feature_here(tty if "Things that are here" in tty else self.top_line())
            if "--More--" in flat or (self.obs["misc"][2] and not menu):
                self.log_msg(msg if msg else self.top_line().replace("--More--", ""))
                self.raw_step(13)
                continue
            if expect_prompt:
                self.log_msg(msg)
                return
            misc = self.obs["misc"]
            if misc[0]:      # yn question
                self.log_msg(msg)
                self.answer_yn(msg)
                continue
            if misc[1]:      # getlin
                self.log_msg(msg)
                if "for what do you wish" in (msg + self.top_line()).lower():
                    self.answer_wish()                      # a djinni, a water demon, a wand of wishing
                    continue
                if "to genocide" in (msg + self.top_line()).lower():
                    self.answer_genocide(msg + " " + self.top_line())     # scrolls.py
                    continue
                if "who are you" in (msg + self.top_line()).lower():
                    self.answer_guard()                     # vault.py
                    continue
                self.raw_step(27)
                continue
            if id_menu:
                self.answer_identify_menu(tty)                   # jewelry.py
                continue
            if menu:
                self.raw_step(27)
                continue
            self.log_msg(msg)
            return

    def msgs_since(self, seq0):
        """Messages logged since the log counter was seq0 (as many as the log still holds)."""
        n = min(self.msg_seq - seq0, len(self.messages))
        return [t for _, t in list(self.messages)[len(self.messages) - n:]] if n else []

    def text_since(self, seq0):
        """The messages logged since the log counter was seq0, as one string: what one action answered."""
        return " ".join(self.msgs_since(seq0))

    def ask(self, cmd, word):
        """Give a command that asks which item / direction: True if that question came (word in the message).
        Otherwise whatever came instead is cleared and False; the message is in self.asked either way."""
        self.press(cmd, expect_prompt=True)
        self.asked = self.message().lower()
        if word in self.asked and self.obs["misc"][0]:
            return True
        if word in self.asked:
            # not a question: a refusal that happens to contain the word ("You can't throw or shoot without
            # hands.") -- answering it sent the item letter and the direction as commands, every tick
            self.msg_audit["ask_not_question_" + cmd] += 1
        self.settle()
        return False

    def ask_drink(self):
        """'q' up to "What do you want to drink?": True if that question came (ask). On a fountain / sink the game
        asks first "Drink from the fountain?" (potion.c:501, 510) -- answered 'n'; before, ask took that question for
        the item prompt ("drink" in it) and typed the potion's letter there: no potion drunk and the step done again
        every tick (455 quaffs in a game), a letter 'y' drank from the fountain (water moccasins, a water demon).
        (A/B drink_prompt: +0.1 [0, +0.2], median 7567 -> 7567, 2 of 1000 changed)"""
        self.press("q", expect_prompt=True)
        if "drink from the" in self.message().lower() and self.obs["misc"][0]:
            self.msg_audit["drink_from_declined"] += 1
            self.press("n", expect_prompt=True)
        self.asked = self.message().lower()
        if "what do you want to drink" in self.asked and self.obs["misc"][0]:
            return True
        self.settle()
        return False

    def call_type(self, letter, name):
        """#call the type of the inventory item letter: name (C, "the type of an object in inventory"). Its items
        then read "<appearance> called <name>". True if the name was given."""
        self.raw_step(ord("C"))
        if "What do you want to name?" not in self.tty_text():
            self.settle()
            return False
        self.raw_step(ord("o"))
        if not self.obs["misc"][0] or "call" not in self.message().lower():
            self.settle()                     # "You don't have anything to call." (all of its kind known)
            return False
        self.raw_step(ord(letter))
        if not self.obs["misc"][1]:
            self.settle()                     # no name asked: already identified
            return False
        for c in name:
            self.raw_step(ord(c))
        self.raw_step(13)
        self.settle()
        return True

    def answer_yn(self, msg):
        m = msg.lower()
        if "offers" in m and "sell" in m:
            self.price_note_offer(msg + " " + self.top_line())       # every offer is a price reading
        if self.shop.selling and ("sell it" in m or "sell them" in m):
            self.raw_step(ord("n" if self.keep_after_offer() else "y"))
            return
        if "really attack" in m:
            self.really_attacks += 1
            self.mark_peaceful_target()
            self.raw_step(27)
        elif "are you sure you want to pray" in m:
            self.raw_step(ord("y"))
        elif "still climb" in m:
            self.raw_step(ord("n"))
        elif "continue eating" in m:
            self.raw_step(ord("n"))
        elif "stop eating" in m:
            self.raw_step(ord("y"))           # eat.c: "hard time getting all of it down" -- the next bites choke
        elif "eat it" in m or "eat one" in m:
            self.raw_step(ord("n"))
        elif "what do you want to charge" in m:
            self.answer_charge()                                 # scrolls.py
        elif "itemized billing" in m:
            self.raw_step(ord("n"))
        elif "sell it?" in m:
            self.raw_step(ord("y"))
        elif ("trouble lifting" in m or "trouble removing" in m) and self.lift_answer(msg):
            self.raw_step(ord("y"))                              # lift_heavy (pickup.py)
        elif "pay?" in m:
            self.raw_step(ord("y"))
        elif "possessions identified" in m:
            self.raw_step(ord("q"))
        else:
            self.raw_step(27)

    def log_msg(self, m):
        """Log a message and hand it to the domains (on_message) -- the one place that tells a new message from one
        shown again: the same text at the same step is dropped; after a key the game reads before clearing the
        message window (events.RESHOW_KEYS) the same text is a repeat -- logged and handed on, marked."""
        m = m.strip()
        if m and m == self._last_logged and self.steps == self._last_logged_step:
            return
        repeat = m == self._last_logged and self.last_key in RESHOW_KEYS
        self._last_logged, self._last_logged_step = m, self.steps
        if m:
            self.messages.append((self.turn(), m))
            self.msg_seq += 1
            if self.verbose:
                self.all_msgs.append((self.turn(), m))
            if len(self.messages) > 60:
                self.messages.popleft()
            self.on_message(Message(m, repeat))

    def tty_text(self):
        return "\n".join(bytes(r).decode("latin1") for r in self.obs["tty_chars"])

    def top_line(self):
        return bytes(self.obs["tty_chars"][0]).decode("latin1").rstrip()

    def message(self):
        return bytes(self.obs["message"]).decode("latin1").rstrip("\x00 ").strip()

    def bl(self, idx):
        return int(self.last_bl[idx])

    def hp_below(self, frac):
        """HP below this fraction of max HP (the HP thresholds in options)."""
        return self.bl(nh.NLE_BL_HP) < self.bl(nh.NLE_BL_HPMAX) * frac

    def turn(self):
        return self.bl(nh.NLE_BL_TIME)

    def pos(self):
        return self.bl(nh.NLE_BL_Y), self.bl(nh.NLE_BL_X)

    def inventory(self):
        """(letter, class, text) per inventory line, read once per observation (a read-only tuple)."""
        if self._inv_at != self.steps:
            items = []
            for letter, ocls, s in zip(self.obs["inv_letters"].tolist(), self.obs["inv_oclasses"].tolist(),
                                       self.obs["inv_strs"]):
                if letter == 0:
                    break
                items.append((chr(letter), ocls, bytes(s).decode("latin1").rstrip("\x00")))
            self._inv, self._inv_at = tuple(items), self.steps
        return self._inv

    def items(self):
        """The inventory as Items (nhbot.items): a fresh list each observation, parsed again only when the
        inventory changed."""
        if self._items_at != self.steps:
            inv = self.inventory()
            if inv != self._items_inv:
                self._items_parsed, self._items_inv = [parse_item(l, c, s) for l, c, s in inv], inv
            self._items = list(self._items_parsed)
            self._items_at = self.steps
        return self._items

    def find_item(self, ocls, names):
        for n in names:
            for it in self.items():
                if it.ocls == ocls and re.search(r"\b(potions?|scrolls?) of " + re.escape(n) + r"\b", it.text) \
                        and not it.cursed:
                    return it.letter, n
        return None

    @staticmethod
    def menu_lines(tty, header):
        """Lines of a menu: a short menu is drawn over the map from the header's column (tty overlay), so
        each line is cut there; a full-screen menu has the header at column 0 and is unchanged."""
        lines = tty.split("\n")
        hi = next(i for i, l in enumerate(lines) if header in l)
        col = lines[hi].index(header)
        return [l[col:] for l in lines[hi + 1:]]

    def menu_items(self, tty, header):
        """(letter, text) of the selectable lines of a menu."""
        out = []
        for line in self.menu_lines(tty, header):
            m = MENU_ITEM_RE.match(line.strip())
            if m:
                out.append((m.group(1), m.group(2)))
        return out

    def menu_pick(self, header, want):
        """A pick-any item menu headed header is on screen: select every entry want(text) accepts, page by page
        (pages after the first have no header), then confirm -- or ESC with nothing selected. Returns how many
        were selected."""
        n = 0
        items = self.menu_items(self.tty_text(), header)
        for _ in range(20):
            for letter, text in items:
                if want(text):
                    self.raw_step(ord(letter))
                    n += 1
            page = PAGE_RE.search(self.tty_text())
            if not (page and int(page.group(1)) < int(page.group(2))):
                break
            self.raw_step(ord(">"))                  # the next page (no header there)
            items = [(m.group(1), m.group(2)) for l in self.tty_text().split("\n")
                     for m in [MENU_ITEM_RE.match(l.strip())] if m]
        self.raw_step(13 if n else 27)
        return n

    def describe_at(self, pos):
        """Farlook (';' with autodescribe) at any square: the cursor goes there by single steps, by 8 with
        the capital keys; next to us this is ";" and one direction key."""
        y, x = self.pos()
        dy, dx = pos[0] - y, pos[1] - x
        self.raw_step(ord(";"))
        while dy or dx:
            sy, sx = (dy > 0) - (dy < 0), (dx > 0) - (dx < 0)
            n = min(abs(dy), abs(dx)) if sy and sx else max(abs(dy), abs(dx))
            step = 8 if n >= 8 else 1
            key = DELTA2KEY[(sy, sx)]
            self.raw_step(ord(key.upper() if step == 8 else key))
            dy, dx = dy - sy * step, dx - sx * step
        desc = self.top_line()
        self.raw_step(27)
        self.settle()
        return desc

    def on_message(self, msg):
        """Every logged message, parsed once (events.Message), to each domain in this order: the raw-text readers get
        the text, the others read its events."""
        m = msg.text
        lv = self.levels.get(self.cur_key) if self.cur_key else None
        if lv is not None and ("You see here" in m or "Things that are here" in m or "several objects here" in m):
            self.seen_here = (self.turn(), self.pos(), m)
        # the message logged at the step after attack()'s 'F' (the one before, shown again: events.RESHOW_KEYS) is not
        # read by focus and the destroyed-item count
        after_attack_f = self.steps == self.acts.attack_step + 1
        self.msg_survival(m)
        self.msg_enchant(m)
        if not after_attack_f:
            self.focus_note(msg)
        self.msg_combat(msg)
        if not after_attack_f:
            self.danger_items_msg(msg)
        self.danger_weapons_msg(msg)
        self.msg_peace(msg, lv)
        self.msg_map(m, lv)
        self.msg_shop(m, lv)
        self.msg_thieves(msg)
        self.msg_sacrifice(m, lv)
        self.msg_threat(msg)
        self.msg_vault(m)
        self.msg_elbereth(msg, lv)
        if "You die" in m or "You starve" in m:
            self.death_msgs = [mm for _, mm in list(self.messages)[-8:]]
