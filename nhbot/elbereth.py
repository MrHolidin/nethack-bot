"""Elbereth: engrave it, read it back (engrave.c doengrave garbles each letter in the dust 1 in 25: about 28% of
Elbereths come out misspelled), stand on it while hurt and the monsters around respect it.

Measured in NLE 3.6.6 wizard mode: while you stand on a correctly spelled Elbereth, monsters that respect
it never melee you; it survives waiting; your first melee attack (and usually a throw) erases it."""
import collections
import re

import nle.nethack as nh

from nhbot import elb_rules as ELB
from nhbot.consts import NO_ENGRAVE_CMAP
from nhbot.events import Kill, OurBlow
from nhbot.monsters import PM_INDICES, SWARMERS

ELB_WIPE_VERBS = ("hit", "miss", "smite")     # msg_elbereth: our blows read as scuffing it (with a kill)


class ElberethState:
    """State of Elbereth engraving and resting on it (ElberethMixin)."""
    def __init__(self):
        self.elbereths = 0
        self.state = None            # dict(pos, key, since, last_read, hp_hist)
        self.engraves = 0
        self.misspelled = 0
        self.turns = 0
        self.exits = collections.Counter()
        self.fail_at = None
        self.block_reasons = collections.Counter()
        self.fail_msgs = []
        self.fail = 0
        self.rewrites = 0
        self.only_c = 0
        self.stats = collections.Counter()       # reads, confirmed rests, nymph engravings


class ElberethMixin:
    def elbereth_init(self):
        self.elb = ElberethState()

    def engrave_elbereth(self):
        if int(self.last_bl[nh.NLE_BL_CONDITION]) & nh.BL_MASK_HALLU:
            return False                         # hallucinating: each letter garbled 1 in 2 (engrave.c)
        if not self.engrave("-", "Elbereth"):
            return False
        self.elb.elbereths += 1                      # lv.elbereth only once read back (elb_confirm)
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

    def can_engrave_here(self, lv):
        """What a player knows before trying: the square, and whether they have hands. The terrain under an item
        counts: an item lying on an altar hides it, and Elbereth "written" on an altar angers its god
        (engrave.c altar_wrath) and writes nothing."""
        g = int(self.terrain_glyphs(lv)[self.pos()])
        if nh.glyph_is_cmap(g) and nh.glyph_to_cmap(g) in NO_ENGRAVE_CMAP:
            return False
        return not self.handless()

    def respects(self, pos, name):
        """Does a monster of this name respect a written Elbereth? By elb_rules.onscary_ignores (the rule
        elb_blocked uses too) for every kind of that name (a were's @ form doesn't).
        (A/B elb_respect: 0, median 7726 -> 7726, 0 of 1000 changed -- no Valkyrie game reaches it)"""
        idxs = PM_INDICES.get(name) if name != "invisible" else None
        return bool(idxs) and all(ELB.onscary_ignores(nh.permonst(i)) is None for i in idxs)

    def elb_blocked(self, lv):
        """Some visible monster that Elbereth won't stop (wrong type, or can hurt from range): don't write."""
        glyphs, me = self.obs["glyphs"], self.pos()
        pp = {p for p in self.visible_monsters() if self.peaceful_now(lv, p, look=False)}
        bl = ELB.blockers(glyphs, me, pp, lv.key[0])
        if bl and not ELB.blockers(glyphs, me, pp, lv.key[0], optimistic=True):
            self.elb.only_c += 1                  # ticks where only class-C monsters stood in the way
        if bl:
            self.elb.block_reasons[bl[0][1].split(":")[0]] += 1
        return bool(bl)

    def elb_can_write(self, lv):
        """Engraving is possible here and now: square, hands, not the square that just failed,
        not levitating / blind / stunned / confused."""
        if not self.can_engrave_here(lv) or self.elb.fail_at == (lv.key, self.pos(), self.turn()):
            return False
        cond = int(self.last_bl[nh.NLE_BL_CONDITION])
        if cond & nh.BL_MASK_HALLU:
            return False                         # hallucinating: Elbereth won't come out right (engrave_elbereth)
        return not cond & (nh.BL_MASK_LEV | nh.BL_MASK_BLIND | nh.BL_MASK_STUN | nh.BL_MASK_CONF)

    def msg_elbereth(self, msg, lv):
        """The Elbereth under us gone or scuffed -- mon.c setmangry deletes it when we attack one that respects it
        ("The engraving beneath you fades"), a melee blow of ours, landed or not, or a kill wipes letters (uhitm.c
        u_wipe_engr(3); read: hit / miss / smite / a kill): off lv.elbereth till read back (elb_confirm). Before,
        lv.elbereth kept it for good and the wand gate, the nymph rule and the danger model trusted it (A/B elb_stale
        +609 [-317, +1545], 215 of 1000 games changed -- accepted)."""
        if lv is None:
            return
        if msg.all(Kill) or any(e.verb in ELB_WIPE_VERBS for e in msg.all(OurBlow)) \
                or "The engraving beneath you fades" in msg.text:
            self.elb_scuffed(lv)

    def elb_scuffed(self, lv=None):
        """Our square off lv.elbereth (a throw scuffs it too: dothrow.c u_wipe_engr(2))."""
        (lv or self.level()).elbereth.discard(self.pos())

    def elb_confirm(self, lv):
        """Read the engraving under us; lv.elbereth follows what it says. True if Elbereth."""
        ok = self.read_engraving() == "Elbereth"
        self.elb.stats["read_ok" if ok else "read_not"] += 1
        if ok:
            lv.elbereth.add(self.pos())
        else:
            lv.elbereth.discard(self.pos())
        return ok

    def elb_rest(self):
        """Counted: a rest on an Elbereth confirmed just now (policy.step_rest_on_elbereth)."""
        self.elb.stats["rest_confirmed"] += 1

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
        if (sum(1 for _, n in threats if n in SWARMERS) >= 2
                or self.bl(nh.NLE_BL_HP) < self.bl(nh.NLE_BL_HPMAX) * self.opts.elb_hp) and not self.elb_blocked(lv):
            return True
        return self.opts.elb_sim and self.elb_sim_wanted(lv, hostiles)

    def elb_sim_wanted(self, lv, hostiles):
        """A/B elb_sim: write Elbereth when the fight with it (win_prob held: the ones next to us that respect it
        held off while we kill the rest, then fought) is likelier won than fighting on -- also with ones next to us
        that ignore it. Not with anything that ignores it standing off (win_prob doesn't play it out) or nothing
        next to us that respects it. Both fights from the same draws; the generators put back after (no other
        decision moves)."""
        if not hostiles:
            return False
        held = {p for p, n in hostiles if self.respects(p, n)}
        if not held:
            return False
        adj = {p for p, _ in hostiles}
        pp = {p for p in self.visible_monsters() if self.peaceful_now(lv, p, look=False)}
        if any(p not in adj for p, _, _ in ELB.blocker_squares(self.obs["glyphs"], self.pos(), pp, lv.key[0])):
            return False
        gens = (self.danger.win_rng.bit_generator, self.danger.opening_rng.bit_generator)
        saved = [g.state for g in gens]
        p_fight = self.win_prob(hostiles)
        for g, s in zip(gens, saved):
            g.state = s
        p_elb = self.win_prob(hostiles, held=held)
        for g, s in zip(gens, saved):
            g.state = s
        self.elb.stats["sim"] += 1
        if p_elb <= p_fight:
            return False
        self.elb.stats["sim_write"] += 1
        return True

    def elb_step(self, lv, hostiles):
        st = self.elb.state
        y, x = self.pos()
        hp, maxhp = self.bl(nh.NLE_BL_HP), self.bl(nh.NLE_BL_HPMAX)
        if st is not None:
            if st["pos"] != (y, x) or st["key"] != lv.key:
                self.elb.exits["moved"] += 1
                self.elb.state = None
            else:
                bad = [n for p, n in hostiles if not self.respects(p, n)]
                st["hp_hist"].append(hp)
                # a dust engraving wears off on its own (allmain.c: 1/(40+3*Dex) per turn); with a foe
                # adjacent check it every turn (reading is free); a hit through a smudged one means rewrite
                if hostiles and not bad:
                    st["last_read"] = self.turn()
                    if not self.elb_confirm(lv):
                        if self.elb_blocked(lv):
                            self.elb.exits["blocked"] += 1
                            self.elb.state = None
                            return False
                        self.elb.rewrites += 1
                        st["hp_hist"] = [hp]
                        return self.elb_write(lv)
                losing = len(st["hp_hist"]) > 4 and st["hp_hist"][-1] < st["hp_hist"][-5] - 2
                if bad or losing:
                    self.elb.exits["ignored" if bad else "ranged"] += 1
                    self.elb.state = None
                    return False                       # fight / let tactics handle it
                visible = self.visible_hostiles(lv)
                early = not visible and hp >= maxhp * self.opts.elb_early
                if hp >= maxhp * self.opts.elb_exit or early:
                    self.elb.exits["healed"] += 1
                    self.elb.state = None
                    return False
                if self.turn() - st["since"] > self.opts.elb_max:
                    self.elb.exits["timeout"] += 1
                    self.elb.state = None
                    return False
                if self.turn() - st["last_read"] >= 4:
                    st["last_read"] = self.turn()
                    if not self.elb_confirm(lv):
                        if self.elb_blocked(lv):
                            self.elb.exits["blocked"] += 1
                            self.elb.state = None
                            return False
                        return self.elb_write(lv)
                self.elb.turns += 1
                self.cur_act = "rest"
                self.press("s")
                return True
        if not self.elb_wanted(lv, hostiles):
            return False
        return self.elb_write(lv)

    def elb_nymph_note(self, lv, how):
        """thieves: what came of an Elbereth written against a nymph: "fail" (not engraved: not again on this
        square this turn), "misspelled" or "ok"."""
        if how == "fail":
            self.elb.fail += 1
            self.elb.fail_at = (lv.key, self.pos(), self.turn())
        elif how == "misspelled":
            self.elb.misspelled += 1
        self.elb.stats["nymph_" + how] += 1

    def elb_write(self, lv):
        """Engrave and verify by reading. Any failure to reach the text prompt (fountain/altar/stairs,
        polymorphed into a handless form, levitating, ...) backs off instead of retrying every tick."""
        for attempt in range(3):
            ok = self.engrave_elbereth()
            self.elb.engraves += 1
            if not ok:
                # precondition missed a case: log it (to find it), and don't retry on this square this turn
                self.elb.fail += 1
                self.elb.fail_msgs.append(" ".join(m for _, m in list(self.messages)[-2:])[:80])
                self.elb.fail_at = (lv.key, self.pos(), self.turn())
                self.elb.state = None
                return False
            if self.elb_confirm(lv):
                self.elb.state = {"pos": self.pos(), "key": lv.key, "since": self.turn(),
                                  "last_read": self.turn(), "hp_hist": [self.bl(nh.NLE_BL_HP)]}
                self.cur_act = "rest"
                return True
            self.elb.misspelled += 1
        self.elb.state = None
        return True

