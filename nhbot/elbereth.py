"""Elbereth: engrave it, read it back (about 1 in 5 dust engravings is misspelled), stand on it
while hurt and the monsters around respect it.

Measured in NLE 3.6.6 wizard mode: while you stand on a correctly spelled Elbereth, monsters that respect
it never melee you; it survives waiting; your first melee attack (and usually a throw) erases it."""
import collections
import re

import nle.nethack as nh

from nhbot import elb_rules as ELB
from nhbot import glyphs as G
from nhbot.consts import NO_ENGRAVE_CMAP
from nhbot.elb_rules import M1_NOHANDS
from nhbot.monsters import B_ANGEL_MLET, B_HUMAN_MLET, ELB_IGNORE_NAMES, PM_BY_NAME, SWARMERS, VALK_RANKS

_HANDLESS = {}                     # polymorph form name -> handless (permonst lookup is slow for were forms)


class ElberethMixin:
    def elbereth_init(self):
        self.elb_state = None        # dict(pos, key, since, last_read, hp_hist)
        self.elb_engraves = 0
        self.elb_misspelled = 0
        self.elb_turns = 0
        self.elb_exits = collections.Counter()
        self.elb_fail_at = None
        self.elb_block_reasons = collections.Counter()
        self.elb_fail_msgs = []
        self.elb_fail = 0
        self.elb_rewrites = 0
        self.elb_only_c = 0

    def engrave_elbereth(self):
        lv = self.level()
        if not self.ask("E", "write with"):
            return False
        self.press("-", expect_prompt=True)
        for _ in range(5):
            if self.obs["misc"][0]:          # "Do you want to add to the current engraving?"
                self.press("n", expect_prompt=True)
                continue
            if "--more--" in self.tty_text().lower():
                self.raw_step(13)
                continue
            break
        if self.obs["misc"][1]:
            for c in "Elbereth":
                self.raw_step(ord(c))
            self.press(13)
            lv.elbereth.add(self.pos())
            self.elbereths += 1
            return True
        self.settle()
        return False

    def read_engraving(self):
        """Text of the engraving under us, from the answer to THIS ':' only (older 'You read' lines in the
        log belong to earlier reads and must not be used); last match if the answer has several lines."""
        seq0 = self.msg_seq
        self.raw_step(ord(":"))
        self.settle()
        txt = " ".join(self.msgs_since(seq0))
        found = re.findall(r'You read: "([^"]*)"', txt)
        return found[-1] if found else ""

    def poly_form(self):
        """Name of the form we are polymorphed into (the status line shows it instead of the rank), else None."""
        line = bytes(self.obs["tty_chars"][22]).decode("latin1")
        m = re.match(r"\S+ the (.+?)\s{2,}St:", line)
        if not m or m.group(1).lower() in VALK_RANKS:
            return None
        return m.group(1).lower()

    def handless(self):
        """Polymorphed into a form that can't wear or wield (nohands / very small: do_wear.c, wield.c)."""
        form = self.poly_form()
        if form is None:
            return False
        if form not in _HANDLESS:
            pm = PM_BY_NAME.get(form)
            if form.startswith("were"):      # lycanthrope: the status line names it, the body is the animal
                pm = next(nh.permonst(i) for i in range(nh.NUMMONS)
                          if nh.permonst(i).mname == form and nh.permonst(i).mlet != B_HUMAN_MLET)
            _HANDLESS[form] = pm is None or bool(pm.mflags1 & M1_NOHANDS) or pm.msize == 0
        return _HANDLESS[form]

    def can_engrave_here(self, lv):
        """What a player knows before trying: the square, and whether they have hands."""
        g = int(lv.under[self.pos()])
        if nh.glyph_is_cmap(g) and nh.glyph_to_cmap(g) in NO_ENGRAVE_CMAP:
            return False
        return not self.handless()

    def respects(self, pos, name):
        if name == "invisible" or name in ELB_IGNORE_NAMES:
            return False
        pm = PM_BY_NAME.get(name)
        if pm is None:
            return False
        return pm.mlet not in (B_HUMAN_MLET, B_ANGEL_MLET)

    def elb_blocked(self, lv):
        """Some visible monster that Elbereth won't stop (wrong type, or can hurt from range): don't write."""
        glyphs, me = self.obs["glyphs"], self.pos()
        pp = {p for p in self.visible_monsters() if self.peaceful_now(lv, p, look=False)} \
            if self.opts.danger_check else None
        bl = ELB.blockers(glyphs, me, lv.peaceful, lv.key[0], peaceful_pos=pp)
        if bl and not ELB.blockers(glyphs, me, lv.peaceful, lv.key[0], optimistic=True, peaceful_pos=pp):
            self.elb_only_c += 1                  # ticks where only class-C monsters stood in the way
        if bl:
            self.elb_block_reasons[bl[0][1].split(":")[0]] += 1
        return bool(bl)

    def elb_wanted(self, lv, hostiles):
        hp, maxhp = self.bl(nh.NLE_BL_HP), self.bl(nh.NLE_BL_HPMAX)
        if not self.can_engrave_here(lv) or self.elb_fail_at == (lv.key, self.pos(), self.turn()):
            return False
        if self.can_pray():
            return False
        if G.KIND[lv.under[self.pos()]] in (G.UPSTAIR, G.DOWNSTAIR):
            return False
        if int(self.last_bl[nh.NLE_BL_CONDITION]) & (nh.BL_MASK_LEV | nh.BL_MASK_BLIND | nh.BL_MASK_STUN | nh.BL_MASK_CONF):
            return False
        y, x = self.pos()
        near = [(p, n) for p, n in self.visible_hostiles(lv) if max(abs(p[0] - y), abs(p[1] - x)) <= 3]
        threats = hostiles + [t for t in near if t not in hostiles]
        if not threats:
            return False
        swarm = sum(1 for _, n in threats if n in SWARMERS)
        if not (hp < maxhp * self.opts.elb_hp or swarm >= 2):
            return False
        return not self.elb_blocked(lv)

    def elb_step(self, lv, hostiles):
        st = self.elb_state
        y, x = self.pos()
        hp, maxhp = self.bl(nh.NLE_BL_HP), self.bl(nh.NLE_BL_HPMAX)
        if st is not None:
            if st["pos"] != (y, x) or st["key"] != lv.key:
                self.elb_exits["moved"] += 1
                self.elb_state = None
            else:
                bad = [n for p, n in hostiles if not self.respects(p, n)]
                st["hp_hist"].append(hp)
                # a dust engraving wears off on its own (allmain.c: 1/(40+3*Dex) per turn); with a foe
                # adjacent check it every turn (reading is free); a hit through a smudged one means rewrite
                if hostiles and not bad:
                    st["last_read"] = self.turn()
                    if self.read_engraving() != "Elbereth":
                        if self.elb_blocked(lv):
                            self.elb_exits["blocked"] += 1
                            self.elb_state = None
                            return False
                        self.elb_rewrites += 1
                        st["hp_hist"] = [hp]
                        return self.elb_write(lv)
                losing = len(st["hp_hist"]) > 4 and st["hp_hist"][-1] < st["hp_hist"][-5] - 2
                if bad or losing:
                    self.elb_exits["ignored" if bad else "ranged"] += 1
                    self.elb_state = None
                    return False                       # fight / let tactics handle it
                visible = self.visible_hostiles(lv)
                early = not visible and hp >= maxhp * 0.6
                if hp >= maxhp * self.opts.elb_exit or early:
                    self.elb_exits["healed"] += 1
                    self.elb_state = None
                    return False
                if self.turn() - st["since"] > self.opts.elb_max:
                    self.elb_exits["timeout"] += 1
                    self.elb_state = None
                    return False
                if self.turn() - st["last_read"] >= 4:
                    st["last_read"] = self.turn()
                    if self.read_engraving() != "Elbereth":
                        if self.elb_blocked(lv):
                            self.elb_exits["blocked"] += 1
                            self.elb_state = None
                            return False
                        return self.elb_write(lv)
                self.elb_turns += 1
                self.cur_act = "rest"
                self.press("s")
                return True
        if not self.elb_wanted(lv, hostiles):
            return False
        return self.elb_write(lv)

    def elb_write(self, lv):
        """Engrave and verify by reading. Any failure to reach the text prompt (fountain/altar/stairs,
        polymorphed into a handless form, levitating, ...) backs off instead of retrying every tick."""
        for attempt in range(3):
            ok = self.engrave_elbereth()
            self.elb_engraves += 1
            if not ok:
                # precondition missed a case: log it (to find it), and don't retry on this square this turn
                self.elb_fail += 1
                self.elb_fail_msgs.append(" ".join(m for _, m in list(self.messages)[-2:])[:80])
                self.elb_fail_at = (lv.key, self.pos(), self.turn())
                self.elb_state = None
                return False
            if self.read_engraving() == "Elbereth":
                self.elb_state = {"pos": self.pos(), "key": lv.key, "since": self.turn(),
                                  "last_read": self.turn(), "hp_hist": [self.bl(nh.NLE_BL_HP)]}
                self.cur_act = "rest"
                return True
            self.elb_misspelled += 1
        self.elb_state = None
        return True
