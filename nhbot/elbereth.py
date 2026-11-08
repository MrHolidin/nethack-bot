"""Elbereth: engrave it, read it back (engrave.c doengrave garbles each letter in the dust 1 in 25: about 28% of
Elbereths come out misspelled), stand on it while hurt and the monsters around respect it.

Measured in NLE 3.6.6 wizard mode: while you stand on a correctly spelled Elbereth, monsters that respect
it never melee you; it survives waiting; your first melee attack (and usually a throw) erases it."""
import collections
import re

import nle.nethack as nh

from nhbot import elb_rules as ELB
from nhbot import glyphs as G
from nhbot.consts import ENGRAVE_REFUSED_CMAP, NO_ENGRAVE_CMAP
from nhbot.messages import ELB_WIPED_RE
from nhbot.monsters import (ELB_IGNORE_NAMES, M1_NOHANDS, PM_BY_NAME, PM_INDICES, S_ANGEL, S_HUMAN, SWARMERS,
                            VALK_RANKS)

_HANDLESS = {}                     # polymorph form name -> handless (permonst lookup is slow for were forms)


class ElberethMixin:
    def elbereth_init(self):
        self.elbereths = 0
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
        self.elb_stats = collections.Counter()   # reads, confirmed rests, nymph engravings

    def engrave_elbereth(self):
        if int(self.last_bl[nh.NLE_BL_CONDITION]) & nh.BL_MASK_HALLU:
            return False                         # hallucinating: each letter garbled 1 in 2 (engrave.c)
        if not self.engrave("-", "Elbereth"):
            return False
        self.elbereths += 1                      # lv.elbereth only once read back (elb_confirm)
        return True

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
                pm = next(nh.permonst(i) for i in PM_INDICES.get(form, ()) if nh.permonst(i).mlet != S_HUMAN)
            _HANDLESS[form] = pm is None or bool(pm.mflags1 & M1_NOHANDS) or pm.msize == 0
        return _HANDLESS[form]

    def can_engrave_here(self, lv):
        """What a player knows before trying: the square, and whether they have hands. The terrain under an item
        counts: an item lying on an altar hides it, and Elbereth "written" on an altar angers its god
        (engrave.c altar_wrath) and writes nothing."""
        g = int(self.terrain_glyphs(lv)[self.pos()])
        if nh.glyph_is_cmap(g) and nh.glyph_to_cmap(g) in (ENGRAVE_REFUSED_CMAP if self.opts.engrave_more
                                                           else NO_ENGRAVE_CMAP):
            return False
        return not self.handless()

    def respects(self, pos, name):
        """Does a monster of this name respect a written Elbereth? elb_respect: by elb_rules.onscary_ignores (the rule
        elb_blocked uses too) for every kind of that name (a were's @ form doesn't)."""
        if self.opts.elb_respect:
            idxs = PM_INDICES.get(name) if name != "invisible" else None
            return bool(idxs) and all(ELB.onscary_ignores(nh.permonst(i)) is None for i in idxs)
        if name == "invisible" or name in ELB_IGNORE_NAMES:
            return False
        pm = PM_BY_NAME.get(name)
        if pm is None:
            return False
        return pm.mlet not in (S_HUMAN, S_ANGEL)

    def elb_blocked(self, lv):
        """Some visible monster that Elbereth won't stop (wrong type, or can hurt from range): don't write."""
        glyphs, me = self.obs["glyphs"], self.pos()
        pp = {p for p in self.visible_monsters() if self.peaceful_now(lv, p, look=False)}
        onscary = self.opts.elb_respect
        bl = ELB.blockers(glyphs, me, pp, lv.key[0], onscary=onscary)
        if bl and not ELB.blockers(glyphs, me, pp, lv.key[0], optimistic=True, onscary=onscary):
            self.elb_only_c += 1                  # ticks where only class-C monsters stood in the way
        if bl:
            self.elb_block_reasons[bl[0][1].split(":")[0]] += 1
        return bool(bl)

    def elb_can_write(self, lv):
        """Engraving is possible here and now: square, hands, not the square that just failed, not stairs,
        not levitating / blind / stunned / confused."""
        if not self.can_engrave_here(lv) or self.elb_fail_at == (lv.key, self.pos(), self.turn()):
            return False
        if self.kinds(lv)[self.pos()] in (G.UPSTAIR, G.DOWNSTAIR) and not self.opts.engrave_more:
            return False
        cond = int(self.last_bl[nh.NLE_BL_CONDITION])
        if cond & nh.BL_MASK_HALLU:
            return False                         # hallucinating: Elbereth won't come out right (engrave_elbereth)
        return not cond & (nh.BL_MASK_LEV | nh.BL_MASK_BLIND | nh.BL_MASK_STUN | nh.BL_MASK_CONF)

    def msg_elbereth(self, m, lv):
        """The Elbereth under us gone or scuffed -- mon.c setmangry deletes it when we attack one that respects it
        ("The engraving beneath you fades"), a melee blow wipes letters (uhitm.c u_wipe_engr(3)): off lv.elbereth till
        read back (elb_confirm). Before, lv.elbereth kept it for good and the wand gate, the nymph rule and the danger
        model trusted it (A/B elb_stale +609 [-317, +1545], 215 of 1000 games changed -- accepted)."""
        if lv is not None and ELB_WIPED_RE.search(m):
            self.elb_scuffed(lv)

    def elb_scuffed(self, lv=None):
        """Our square off lv.elbereth (a throw scuffs it too: dothrow.c u_wipe_engr(2))."""
        (lv or self.level()).elbereth.discard(self.pos())

    def elb_confirm(self, lv):
        """Read the engraving under us; lv.elbereth follows what it says. True if Elbereth."""
        ok = self.read_engraving() == "Elbereth"
        self.elb_stats["read_ok" if ok else "read_not"] += 1
        if ok:
            lv.elbereth.add(self.pos())
        else:
            lv.elbereth.discard(self.pos())
        return ok

    def elb_wanted(self, lv, hostiles):
        """Write Elbereth now: a hostile next to us or within 3 squares, and either two swarmers among them or
        we are hurt -- below elb_hp of max HP -- and we can write here and nothing in view ignores it (elb_blocked).
        A prayer in reserve doesn't hold it back (A/B elb_with_prayer: the prayer stays for when Elbereth can't help)."""
        if not self.elb_can_write(lv):
            return False
        y, x = self.pos()
        near = [(p, n) for p, n in self.visible_hostiles(lv) if max(abs(p[0] - y), abs(p[1] - x)) <= 3]
        threats = hostiles + [t for t in near if t not in hostiles]
        if not threats:
            return False
        if sum(1 for _, n in threats if n in SWARMERS) < 2 \
                and self.bl(nh.NLE_BL_HP) >= self.bl(nh.NLE_BL_HPMAX) * self.opts.elb_hp:
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
                    if not self.elb_confirm(lv):
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
                    if not self.elb_confirm(lv):
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

    def elb_write(self, lv, rest=True, stat=None):
        """Engrave and verify by reading. Any failure to reach the text prompt (fountain/altar/stairs,
        polymorphed into a handless form, levitating, ...) backs off instead of retrying every tick.
        rest: then rest on it (elb_state, elb_step); False: only write it (nymph_elb: thieves.nymph_step holds
        still on it by itself). stat: elb_stats counts <stat>_ok / _misspelled / _fail."""
        for attempt in range(3):
            ok = self.engrave_elbereth()
            self.elb_engraves += 1
            if not ok:
                # precondition missed a case: log it (to find it), and don't retry on this square this turn
                self.elb_fail += 1
                self.elb_fail_msgs.append(" ".join(m for _, m in list(self.messages)[-2:])[:80])
                self.elb_fail_at = (lv.key, self.pos(), self.turn())
                self.elb_state = None
                if stat:
                    self.elb_stats[stat + "_fail"] += 1
                return False
            if self.elb_confirm(lv):
                if rest:
                    self.elb_state = {"pos": self.pos(), "key": lv.key, "since": self.turn(),
                                      "last_read": self.turn(), "hp_hist": [self.bl(nh.NLE_BL_HP)]}
                    self.cur_act = "rest"
                if stat:
                    self.elb_stats[stat + "_ok"] += 1
                return True
            self.elb_misspelled += 1
            if stat:
                self.elb_stats[stat + "_misspelled"] += 1
        self.elb_state = None
        return True

    def elb_holds(self, lv, foes):
        """nymph_elb: we stand on an Elbereth -- in lv.elbereth and read back right now (no game time) -- and every
        one of foes [(pos, name)] respects it: none of them melees us (monmove.c:341-346 distfleeck scares it,
        dochug then makes no attack), and any blow of ours would erase it (mon.c:2895-2912 setmangry)."""
        if self.pos() not in lv.elbereth or not all(self.respects(p, n) for p, n in foes):
            return False
        return self.elb_confirm(lv)
