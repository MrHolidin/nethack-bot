"""Reacting to game messages: every logged message goes through on_message."""
import re

import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.carry import LEAVE_RE
from nhbot.consts import COLS, NEIGH, ROWS


# mhitu.c: an attack by a monster we can't see is reported as "It <verb>" and marks its square with an 'I'
IT_ATTACK_RE = re.compile(r"\bIt (?:hits|bites|misses|just misses|touches you|stings|kicks|butts|claws|scratches|"
                          r"thrusts|swings|grabs|hugs|lashes|squeezes|engulfs|tickles|stabs|pummels|whips)\b")


# mhitu.c: a melee attack on us by a monster we see: "The <name> <verb>!" (hallucination: the name is random);
# monster-vs-monster and missiles read differently ("The gnome hits the jackal.", "You are hit by a dart.")
MELEE_ON_US_RE = re.compile(r"\bThe [^.!]+? (?:hits|bites|misses|just misses|stings|kicks|butts|claws|scratches|"
                            r"thrusts|swings|grabs|lashes|tickles|stabs|pummels|whips|touches you|engulfs you|"
                            r"squeezes you|gores|charms you)!")


# Somebody attacked us from a distance (mthrowu.c monshoot / thitu, zap.c buzz, muse.c), seen or not.
RTHREAT_RE = re.compile(r"(?:throws|shoots) |zaps (?:a|an|the) |You are (?:almost )?hit by |You are hit!|misses you\.|"
                        r"whizzes by you|hits you!|crashes on your head|You hear a nearby zap")


# ...but arrow/dart/rock traps print the same 'You are hit by' lines
RTRAP_RE = re.compile(r"trap|shoots out at you|falls on your head|from the ceiling")


class MessagesMixin:
    def on_message(self, m):
        lv = self.levels.get(self.cur_key) if self.cur_key else None
        # eat.c givit(POISON_RES): "You feel healthy."; eating poison while resistant: "You seem unaffected"
        if "You feel healthy" in m or "You seem unaffected by the poison" in m:
            self.poison_res = True
        if self.opts.focus:
            self.focus_note(m)
        if "This door is locked" in m and self.last_move_target and lv:
            lv.locked.add(self.last_move_target)
        if lv and self.last_move_target and any(s in m for s in (
                "You try to move the boulder, but in vain",
                "Perhaps that's why you cannot move past it",
                "There is a boulder in your way",
                "You are carrying too much to get through",
                "You don't have enough room to maneuver")):
            lv.blocked[self.last_move_target] = True
        if "no shape for kicking" in m and lv and self.last_move_target:
            lv.blocked[self.last_move_target] = True
        if "Closed for inventory" in m and lv:
            y, x = self.pos()
            for dy, dx in NEIGH:
                ny, nx = y + dy, x + dx
                if 0 <= ny < ROWS and 0 <= nx < COLS and G.KIND[lv.under[ny, nx]] == G.DOOR_CLOSED:
                    lv.blocked[ny, nx] = True
        if lv is not None and ("You see here" in m or "Things that are here" in m or "several objects here" in m):
            self.seen_here = (self.turn(), self.pos(), m)
        if "more confident in your" in m:
            self.skill_msgs += 1
            self.want_enhance = True
        if re.search(r"You (kill|destroy) ", m):
            self.kill_count += 1
        mk = re.search(r"You (kill|destroy) (?:the |an? )?(.+?)!", m)
        if mk and self.last_attack_target:
            lvk = self.levels.get(self.cur_key)
            old_corpse = lvk is not None and G.KIND[lvk.under[self.last_attack_target]] == G.CORPSE
            if not old_corpse:      # an older corpse already lay there: what we'd eat may be that one
                self.kills.append((self.turn(), mk.group(2), self.last_attack_target, self.cur_key))
        if "You feel that" in m and "displeased" in m:
            self.pray_failed += 1
        if self.last_pray is not None and self.turn() - self.last_pray <= 5 and any(
                p in m for p in ("Thou hast angered me", "Thou must relearn", "You feel guilty",
                                 "Then die, mortal", "Thou durst", "You feel that Mitra is angry",
                                 "is displeased.") if p != "is displeased."):
            self.god_angry = True
        if "for sale" in m:
            self.price_note_text(m)
        if RTHREAT_RE.search(m) and not RTRAP_RE.search(m) and self.turn() - self.own_zap_turn > 1:
            self.last_shot_turn = self.turn()
        if self.opts.hunt_shooter and RTHREAT_RE.search(m) and not RTRAP_RE.search(m) \
                and self.turn() - self.own_zap_turn > 1:
            mm = re.search(r"The ([a-z][a-z' -]*?) (?:zaps|shoots|throws|hurls|fires|spits|breathes)", m)
            self.shot_event = (self.turn(), mm.group(1) if mm else None)
        if ("You can't go up here" in m or "You can't go down here" in m) and lv is not None:
            # we remembered a staircase that isn't here (arriving next to stairs a monster stood on marks the
            # wrong square); the refusal costs no time, so pressing again looped to the step cap
            yy, xx = self.pos()
            if G.KIND[int(lv.under[yy, xx])] in (G.UPSTAIR, G.DOWNSTAIR):
                lv.under[yy, xx] = nh.GLYPH_CMAP_OFF + 19
        if IT_ATTACK_RE.search(m):
            self.it_attacked = True           # blind_strike: an unseen monster attacked us this turn
        if MELEE_ON_US_RE.search(m):
            self.melee_on_us = True           # hallu_strike: something attacked us in melee this turn
        if self.opts.vault_guard:
            if "drop that gold" in m or "drop that money" in m:
                self.vault_drop = True
            if "follow me" in m:
                self.vault_follow_until = self.turn() + 300
                self.guard_trail = []
        if lv is not None and "Closed for inventory" in m:
            lv.cfi = lv.cfi | {self.pos()}
        # the square under us is often not in our map memory yet, so 'on the door' can't be checked;
        # instead: we are inside only if we just fell / were teleported onto this level
        recent = " ".join(mm for _, mm in list(self.messages)[-6:])
        on_door = not any(k in recent for k in ("trap door", "fall through", "hole", "teleport",
                                                 "wrenching", "You materialize"))
        if lv and re.search(r"Welcome to [A-Z][\w' -]*'s ", m) and on_door:
            # shop entrance: mark the shop from the door -- after falling in through a trap door we are
            # inside, and marking from there walls us in
            self.mark_shop(lv, self.pos())
            self.shops_seen += 1
            self.shop_greeted(lv, m)
        if LEAVE_RE.search(m):
            self.stash_request()
        if "Please pay before leaving" in m or "you owe" in m.lower() and "zorkmid" in m:
            self.need_pay = True
        self.on_valk_message(m)
        if "You feel feverish" in m:
            self.lycanthropy = True
            mk = re.search(r"\b(were(?:jackal|rat|wolf))\b", m)
            self.lyc_kind = mk.group(1) if mk else None      # None: infected by something we didn't see
        if "You feel purified" in m:
            self.lycanthropy = False
        if "carrying so much" in m:
            self.no_eat_until = self.turn() + 20
        if "You die" in m or "You starve" in m:
            self.death_msgs = [mm for _, mm in list(self.messages)[-8:]]
