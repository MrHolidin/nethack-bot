"""Talking to the game: keys, prompts, messages, the status line and the inventory text."""
import re

import nle.nethack as nh

from nhbot.consts import DELTA2KEY


MENU_RE = re.compile(r"\(end\)|\(\d+ of \d+\)")      # a menu or text window is on screen
MENU_ITEM_RE = re.compile(r"^\s*([a-zA-Z]) - (.*)$")


class GameOver(Exception):
    pass


class GameMixin:
    def raw_step(self, code):
        if code not in self.key2act:
            raise ValueError(f"key {code!r} not in action set")
        self.obs, r, term, trunc, info = self.env.step(self.key2act[code])
        self.steps += 1
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
        if key in ("<", ">"):
            self.last_stair_dir = key
        self.raw_step(code)
        self.settle(expect_prompt)

    def settle(self, expect_prompt=False):
        for _ in range(50):
            tty = self.tty_text()
            msg = self.message()
            flat = tty.replace("\n", "")
            menu = MENU_RE.search(tty)
            if "Things that are here" in tty:
                self.here_window = (self.turn(), self.pos(), " | ".join(
                    l.strip() for l in self.menu_lines(tty, "Things that are here")))
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
                if "who are you" in (msg + self.top_line()).lower():
                    for c in "Agent":                       # our real name (lawful: lying costs alignment)
                        self.raw_step(ord(c))
                    self.raw_step(13)
                    continue
                self.raw_step(27)
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

    def audit(self, site, used, seq0, pred, alt_pred=None):
        """pred(used): a decision read from a window of recent messages. Counts the cases where reading only
        the messages since seq0 (with alt_pred, if given) would decide otherwise."""
        a = pred(used)
        if a != (alt_pred or pred)(" ".join(self.msgs_since(seq0))):
            self.msg_audit["window_" + site] += 1
        return a

    def ask(self, cmd, word):
        """Give a command that asks which item / direction: True if that question came (word in the message).
        Otherwise whatever came instead is cleared and False; the message is in self.asked either way."""
        self.press(cmd, expect_prompt=True)
        self.asked = self.message().lower()
        if word in self.asked and not self.obs["misc"][0]:
            # not a question: a refusal that happens to contain the word ("You can't throw or shoot
            # without hands."); without hands_check the item letter and the direction went in as commands
            self.msg_audit["ask_not_question_" + cmd] += 1
            if self.opts.hands_check:
                self.settle()
                return False
        if word in self.asked:
            return True
        self.settle()
        return False

    def answer_yn(self, msg):
        m = msg.lower()
        if "offers" in m and "sell" in m:
            self.price_note_offer(msg + " " + self.top_line())       # every offer is a price reading
        if self.selling and ("sell it" in m or "sell them" in m):
            self.raw_step(ord("n" if self.keep_after_offer() else "y"))
            return
        if "really attack" in m:
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
        elif "itemized billing" in m:
            self.raw_step(ord("n"))
        elif "sell it?" in m:
            self.raw_step(ord("y"))
        elif m.rstrip().endswith("pay? [yn] (n)") or "pay?" in m:
            self.raw_step(ord("y"))
        elif "possessions identified" in m:
            self.raw_step(ord("q"))
        else:
            self.raw_step(27)

    def log_msg(self, m):
        m = m.strip()
        if m and m == self._last_logged and self.steps == self._last_logged_step:
            return
        self._last_logged, self._last_logged_step = m, self.steps
        if m:
            self.messages.append((self.turn(), m))
            self.msg_seq += 1
            if self.verbose:
                self.all_msgs.append((self.turn(), m))
            if len(self.messages) > 60:
                self.messages.popleft()
            self.on_message(m)

    def tty_text(self):
        return "\n".join(bytes(r).decode("latin1") for r in self.obs["tty_chars"])

    def top_line(self):
        return bytes(self.obs["tty_chars"][0]).decode("latin1").rstrip()

    def message(self):
        return bytes(self.obs["message"]).decode("latin1").rstrip("\x00 ").strip()

    def bl(self, idx):
        return int(self.last_bl[idx])

    def turn(self):
        return int(self.last_bl[nh.NLE_BL_TIME]) if self.last_bl is not None else 0

    def pos(self):
        return self.bl(nh.NLE_BL_Y), self.bl(nh.NLE_BL_X)

    def inventory(self):
        items = []
        for letter, ocls, s in zip(self.obs["inv_letters"], self.obs["inv_oclasses"],
                                   self.obs["inv_strs"]):
            if letter == 0:
                break
            items.append((chr(letter), int(ocls), bytes(s).decode("latin1").rstrip("\x00")))
        return items

    def find_item(self, ocls, names):
        for n in names:
            for letter, c, s in self.inventory():
                if c == ocls and re.search(r"\b(potions?|scrolls?) of " + re.escape(n) + r"\b", s) \
                        and "cursed" not in s.replace("uncursed", ""):
                    return letter, n
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

    def pickup(self, want, site):
        """',' and select what want(text) accepts in the 'Pick up what?' menu (a lone item is picked up
        without a menu)."""
        seq0 = self.msg_seq
        self.press(",", expect_prompt=True)
        tty = self.tty_text()
        if "Pick up what?" not in tty:
            self.settle()
            for t in self.msgs_since(seq0):
                mm = re.match(r"^[a-zA-Z] - (.+?)\.?$", t)
                if mm and not want(mm.group(1)):
                    self.msg_audit["lone_unwanted_" + site] += 1     # picked up what the filter rejects
            return
        if re.search(r"\(1 of \d+\)", tty):
            self.msg_audit["pickup_multipage_" + site] += 1
        n = 0
        for letter, text in self.menu_items(tty, "Pick up what?"):
            if want(text):
                self.raw_step(ord(letter))
                n += 1
        self.raw_step(13 if n else 27)
        self.settle()

    def pickup_matching(self, words, no_sale=False, own=False):
        if not own and self.merch_risk(self.level(), self.pos()):
            return                            # in a shop: anything here may be merchandise
        self.pickup(lambda t: any(w in t for w in words) and not (no_sale and "for sale" in t), "matching")

    def describe_adjacent(self, pos):
        y, x = self.pos()
        key = DELTA2KEY[(pos[0] - y, pos[1] - x)]
        self.raw_step(ord(";"))
        self.raw_step(ord(key))
        desc = self.top_line()
        self.raw_step(27)
        self.settle()
        return desc

    def describe_far(self, dirkey, d):
        self.raw_step(ord(";"))
        for _ in range(d):
            self.raw_step(ord(dirkey))
        desc = self.top_line()
        self.raw_step(27)
        self.settle()
        return desc

    def on_message(self, m):
        """Every logged message. Each domain reads what concerns it."""
        lv = self.levels.get(self.cur_key) if self.cur_key else None
        if lv is not None and ("You see here" in m or "Things that are here" in m or "several objects here" in m):
            self.seen_here = (self.turn(), self.pos(), m)
        self.msg_survival(m)
        self.msg_combat(m)
        self.msg_map(m, lv)
        self.msg_shop(m, lv)
        self.msg_thieves(m)
        if "You die" in m or "You starve" in m:
            self.death_msgs = [mm for _, mm in list(self.messages)[-8:]]
