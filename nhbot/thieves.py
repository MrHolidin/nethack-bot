"""Nymphs and monkeys steal and teleport: shoot them from range, melee them first, after a theft
hunt them and loot the square they die on.

nymph_wands: a thief in a clear line (next to us too) gets an attack wand first -- sleep first (attack_wands
order) -- a ray only when our own ray would come back and hit us with probability below NYMPH_RAY_RISK
(nhbot.rays); a target a sleep ray hit is not zapped again while asleep (combat.asleep).
"""
import re
from collections import Counter

import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.consts import COLS, ROWS, ray_squares
from nhbot.monsters import THIEVES
from nhbot.items import base_name
from nhbot.nav import line_clear
from nhbot.pickup import STOLE_RE
from nhbot.combat import RAY_WANDS

NYMPH_RAY_RISK = 0.10


class ThievesMixin:
    def thieves_init(self):
        self.thefts = 0
        self.stolen_pending = False
        self.loot_sq = None
        self.loot_key = None
        self.nymph_kills = 0
        self.loot_pickups = 0
        self.nymph_waits = 0
        self.nymph_elbs = 0
        self._theft_turn = None
        self.polyd = False             # polymorphed: no wearing / wielding
        self.were_drop = None          # (level key, pos) where our armor fell when we turned into an animal
        self.nymph_zap_stats = Counter()
        self.gold_flow = Counter()       # gold got / lost by cause (gold_flow_tick), summary 'gold_flow'
        self._gold_prev = None
        self._gold_seq = 0
        self._gold_xl = {}               # XL -> most gold carried at it

    def gold_flow_tick(self):
        """Stats only: a change of the gold we carry since the last tick, by the messages that came with it --
        a leprechaun's touch ("Your purse feels lighter."), a foocubus, a vault guard, a shop, a fountain."""
        g = int(self.bl(nh.NLE_BL_GOLD))
        if self._gold_prev is not None and g != self._gold_prev:
            d = g - self._gold_prev
            m = self.text_since(self._gold_seq)
            if d > 0:
                self.gold_flow["got_sold" if "You sold" in m else "got_other"] += d
            else:
                why = ("leprechaun" if "purse feels lighter" in m else
                       "foocubus" if ("attracted" in m or "seduc" in m or "prettier" in m) else
                       "vault" if self.vault_drops and "drop" in m and "gold" in m else
                       "shop" if ("bought" in m or "zorkmid" in m or "pay" in m.lower()) else
                       "fountain" if "fountain" in m else
                       "drop" if "You drop" in m else "other")
                self.gold_flow["lost_" + why] -= d
        xl = int(self.bl(nh.NLE_BL_XP))
        self._gold_xl[xl] = max(self._gold_xl.get(xl, 0), g)
        self._gold_prev, self._gold_seq = g, self.msg_seq

    # ================================================================== nymphs
    def msg_thieves(self, m):
        for what in STOLE_RE.findall(m):                    # "She stole a +0 orcish helm." / "It steals ...!"
            self.stolen_names.add(base_name(what)[2])
        stole = (re.search(r"\b(stole|steals|stolen)\b", m) or "charms you" in m) and \
            (any(t in m for t in THIEVES) or "She stole" in m or "He stole" in m)
        if stole or "It stole" in m or "It steals" in m or "She charms you" in m:
            if self.turn() != self._theft_turn:
                self._theft_turn = self.turn()
                self.thefts += 1
            self.stolen_pending = True
        if self.killed and any(t in self.killed for t in THIEVES) and self.last_attack_target:
            self.nymph_kills += 1
            if self.stolen_pending:
                self.goal_event("loot", "abandoned", self.loot_sq is not None)    # replaced by a newer one
                self.goal_event("loot", "created")
                self.loot_sq = self.last_attack_target
                self.loot_key = self.cur_key
        if re.search(r"You turn into an? \w+|shrink out of your|break out of your armor|armor falls around you", m):
            self.were_drop = (self.cur_key, self.pos())      # armor fell here; collect it once human again
        if re.search(r"You turn into an? ", m):
            self.polyd = True                                 # weapons: no wielding in a borrowed body
        if re.search(r"You return to \w+ form|You feel like a new ", m):
            self.polyd = False
        if re.search(r"You return to \w+ form", m) and self.were_drop:   # dwarves: "dwarven form"
            self.goal_event("loot", "abandoned", self.loot_sq is not None)
            self.goal_event("loot", "created")
            self.loot_key, self.loot_sq = self.were_drop
            self.were_drop = None

    def nymph_zap(self, lv):
        """nymph_wands: zap a thief in a clear line within 7. True if we zapped."""
        if not self.opts.nymph_wands:
            return False
        wands = self.attack_wands()
        if not wands:
            return False
        for key, d, pos, step, name in self.line_targets(lv, max_d=7):
            if name not in THIEVES or self.peaceful_now(lv, pos, far=True):
                continue
            for letter, kind in wands:
                if kind == "sleep" and self.asleep(lv, pos):
                    continue                     # asleep already: melee / missiles finish it
                if kind in RAY_WANDS:
                    p, _ = self.ray_risk(lv, step, kind, letter)
                    if p >= NYMPH_RAY_RISK:
                        self.nymph_zap_stats["held_risk"] += 1
                        continue
                self.cur_act = "fight"
                self.last_attack_target = pos
                if not self.zap(letter, key):
                    return False
                self.nymph_zap_stats["zaps_" + kind] += 1
                if kind == "sleep" and self.asleep(lv, pos):
                    self.nymph_zap_stats["slept"] += 1
                return True
        return False

    def nymph_step(self, lv, hostiles):
        if self.nymph_zap(lv):
            return True
        y, x = self.pos()
        # 1) adjacent thief: hit it first (normal melee would pick the lowest level target)
        adj = [(p, n) for p, n in hostiles if n in THIEVES]
        if adj:
            self.attack(adj[0][0])
            return True
        th = self.thieves_visible(lv)
        if not th:
            return False
        # 2) thief in a clear line at range: throw / fire / bolt
        for key, d, pos, (dy, dx), name in self.line_targets(lv, max_d=7):
            if name not in THIEVES or d < 2:
                continue
            if self.peaceful_now(lv, pos, far=True):
                continue
            self.last_attack_target = pos
            self.cur_act = "fight"
            tw = self.throwables()
            if tw:
                ray = ray_squares(y, x, dy, dx)
                self.throw(tw[0][0], key, ray)
                return True
        have_shot = bool(self.throwables())
        # 2b) we could shoot but it isn't in line: step to a square that lines us up, at distance >= 2
        if have_shot:
            step = self.align_step(lv, th)
            if step is not None:
                self.cur_act = "fight"
                self.move(step)
                return True
        # 2c) no way to shoot: stand on Elbereth (nymphs respect it and won't steal in melee)
        if not have_shot and (y, x) not in lv.elbereth:
            close = [t for t in th if max(abs(t[0][0] - y), abs(t[0][1] - x)) <= 4]
            if close and self.nymph_elbs < 30 and self.elb_can_write(lv):
                self.nymph_elbs += 1
                self.cur_act = "fight"
                if not self.engrave_elbereth():
                    self.elb_fail += 1
                    self.elb_fail_at = (lv.key, self.pos(), self.turn())
                    self.elb_stats["nymph_fail"] += 1
                elif not self.elb_confirm(lv):
                    self.elb_misspelled += 1
                    self.elb_stats["nymph_misspelled"] += 1
                else:
                    self.elb_stats["nymph_ok"] += 1
                return True
        # 3) no shot: never step next to a thief (that hands it the first move). Hold still and
        #    let it come; nymphs come back to steal more, so waiting is also how we get our items back.
        close = [t for t in th if 2 <= max(abs(t[0][0] - y), abs(t[0][1] - x)) <= self.opts.nymph_hold]
        if close and self.nymph_waits < self.opts.nymph_wait_max:
            self.nymph_waits += 1
            self.cur_act = "fight"
            self.press("s")
            return True
        if not close:
            self.nymph_waits = 0
        return False

    def align_step(self, lv, th):
        """A neighbouring free square from which some thief is in a straight clear line, 2..6 away."""
        y, x = self.pos()
        k_mem, _, p = self.grids(lv)
        g = self.obs["glyphs"]
        best = None
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if not (dy or dx):
                    continue
                ny, nx = y + dy, x + dx
                if not (0 <= ny < ROWS and 0 <= nx < COLS) or not p[ny, nx] or G.KIND[g[ny, nx]] in (G.MONSTER, G.PET):
                    continue
                if dy and dx and (k_mem[y, x] in (G.DOOR_OPEN, G.DOOR_CLOSED) or k_mem[ny, nx] in (G.DOOR_OPEN, G.DOOR_CLOSED)):
                    continue
                for (ty, tx), _ in th:
                    ry, rx = ty - ny, tx - nx
                    d = max(abs(ry), abs(rx))
                    if d < 2 or d > 6 or not (ry == 0 or rx == 0 or abs(ry) == abs(rx)):
                        continue
                    sy, sx = (ry > 0) - (ry < 0), (rx > 0) - (rx < 0)
                    if line_clear(k_mem, g, ny, nx, sy, sx, d):
                        if best is None or d < best[0]:
                            best = (d, (ny, nx))
        return best[1] if best else None

    def loot_step(self, lv):
        if self.loot_sq is None or self.loot_key != lv.key:
            return False
        return self.pursue("loot", lv, [self.loot_sq], self.loot_consume)

    def loot_consume(self, goal):
        self.pickup_all()
        self.loot_pickups += 1
        self.stolen_pending = False
