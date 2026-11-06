"""vault_rob: in a vault (a closed 2x2 room of gold -- most often reached by its teleporter, mklev.c makevtele) with a
way to dig: take the gold and dig down through the floor with it -- the guard comes only after 30 turns inside
(vault.c invault: u.uinvault % VAULT_GUARD_TIME), and asks for every coin we carry, bags too (hidden_gold). If he
comes first, we are "Croesus" (vault.c: "Oh, yes, of course. Sorry to have disturbed you." -- he leaves; lawful:
-1 alignment for the lie) and dig on. Ways to dig: a wand of digging zapped down (a hole at once), a pick-axe, a
dwarvish mattock (two-handed: the shield comes off first) applied down -- the weapon is wielded back after
(weapons.swap_in / swap_back, job "dig")."""

from collections import Counter

import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import COLS, DELTA2KEY, FLOOR_GLYPH, ROWS

VAULT_GRAB_TURNS = 12          # turns inside spent on the gold at most: the dig (~15 turns with a pick) ends by 30


class VaultMixin:
    def vault_init(self):
        self.vault_since = None        # (level key, turn) we were first seen in this vault
        self.vault_seen = None         # (level key, its 4 squares): the vault we were last in -- the guard's way in
                                       # opens its wall (vault.c fake corridor), so it is known by its squares then
        self.dig_refused = set()       # level keys whose floor would not be dug ("too hard to dig in")
        self.vault_stats = Counter()

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
        ("mattock", item) a dwarvish mattock -- none known cursed (a cursed digger applied stays welded). None."""
        items = self.items()
        wand = next((it for it in items if it.ocls == nh.WAND_CLASS and "wand of digging" in it.text
                     and ":0)" not in it.text and "cancelled" not in it.text), None)
        pick = next((it for it in items if "pick-axe" in it.text and not it.cursed), None)
        mattock = next((it for it in items if "dwarvish mattock" in it.text and not it.cursed), None)
        if pick is not None:
            return "pick", pick
        if wand is not None:
            return "wand", wand
        if mattock is not None:
            return "mattock", mattock
        return None

    def vault_rob_ready(self):
        """vault_rob: in a vault, a way to dig, the floor here not refused. (game.py: the guard is told
        "Croesus" then.)"""
        return self.opts.vault_rob and self.cur_key not in self.dig_refused and self.vault_box() is not None \
            and self.dig_means() is not None

    def vault_rob_step(self, lv, hostiles):
        """vault_rob: out of the vault after a dig -- the weapon back; in one with a way to dig -- the gold
        (VAULT_GRAB_TURNS at most), then down. True if it used the turn."""
        if not self.opts.vault_rob:
            return False
        box = self.vault_box()
        if box is None:
            self.vault_since = None
            return self.swap_back("dig")
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
        if gold and self.turn() - self.vault_since[1] < VAULT_GRAB_TURNS:
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
        return self.dig_down(lv, means)

    def dig_down(self, lv, means):
        kind, it = means
        self.cur_act = "vault_dig"
        if kind == "wand":
            self.vault_stats["zap"] += 1
            seq0 = self.msg_seq
            self.zap(it.letter, ">")
            self.dig_note(lv, self.text_since(seq0))
            return True
        if not it.wielded:
            shield = next((a for a in self.armor_inventory() if a["worn"] and a["slot"] == "shield"), None)
            if kind == "mattock" and shield is not None:
                if not self.take_off(shield):         # a two-handed digger: not with a shield on (wield.c)
                    self.dig_refused.add(lv.key)      # a cursed shield: no mattock
                return True
            self.swap_in("dig", it)
            return True
        self.vault_stats["apply"] += 1
        seq0 = self.msg_seq
        if not self.ask("a", "apply"):
            return False
        self.press(it.letter, expect_prompt=True)
        if "direction" in self.message().lower():
            self.press(">")
        else:
            self.settle()
        self.dig_note(lv, self.text_since(seq0))
        return True

    def dig_note(self, lv, msgs):
        if "too hard to" in msgs or "cannot reach the" in msgs:
            self.dig_refused.add(lv.key)
            self.vault_stats["refused"] += 1
        if "You dig a hole through" in msgs or "fall through" in msgs:
            self.vault_stats["dug_out"] += 1
