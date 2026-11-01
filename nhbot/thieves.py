"""Nymphs and monkeys steal and teleport: shoot them from range, melee them first, after a theft
hunt them and loot the square they die on."""
import re

from nhbot import glyphs as G
from nhbot.consts import COLS, ROWS, ray_squares
from nhbot.monsters import THIEVES
from nhbot.nav import line_clear


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

    # ================================================================== nymphs
    def msg_thieves(self, m):
        if re.search(r"\b(stole|steals|stolen)\b", m) or "charms you" in m:
            if any(t in m for t in THIEVES) or "She stole" in m or "He stole" in m:
                if self.turn() != self._theft_turn:
                    self._theft_turn = self.turn()
                    self.thefts += 1
                self.stolen_pending = True
        mk = re.search(r"You (?:kill|destroy) (?:the |an? )?(.+?)!", m)
        if mk and any(t in mk.group(1) for t in THIEVES) and self.last_attack_target:
            self.nymph_kills += 1
            if self.stolen_pending:
                self.goal_event("loot", "abandoned", self.loot_sq is not None)    # replaced by a newer one
                self.goal_event("loot", "created")
                self.loot_sq = self.last_attack_target
                self.loot_key = self.cur_key
        if "It stole" in m or "It steals" in m or "She charms you" in m:
            if self.turn() != self._theft_turn:
                self._theft_turn = self.turn()
                self.thefts += 1
            self.stolen_pending = True
        if self.opts.nymph and re.search(r"You turn into an? \w+|shrink out of your|break out of your armor|armor falls around you", m):
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

    def nymph_step(self, lv, hostiles):
        if not self.opts.nymph:
            return False
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
            if self.peaceful_far(lv, pos, key, d):
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
        if have_shot and self.opts.nymph_align:
            step = self.align_step(lv, th)
            if step is not None:
                self.cur_act = "fight"
                self.move(step)
                return True
        # 2c) no way to shoot: stand on Elbereth (nymphs respect it and won't steal in melee)
        if not have_shot and self.opts.nymph_elb and (y, x) not in lv.elbereth:
            close = [t for t in th if max(abs(t[0][0] - y), abs(t[0][1] - x)) <= 4]
            if close and G.KIND[lv.under[y, x]] not in (G.UPSTAIR, G.DOWNSTAIR) and self.nymph_elbs < 30:
                self.nymph_elbs += 1
                self.cur_act = "fight"
                self.engrave_elbereth()
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
        k_mem, k_live = self.kind_grid(lv)
        p = self.passable_grid(lv, k_mem, k_live)
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

    def pickup_all(self):
        self.press(",", expect_prompt=True)
        tty = self.tty_text()
        if "Pick up what?" not in tty:
            self.settle()
            return
        n = 0
        lines = self.menu_lines(tty, "Pick up what?")
        for line in lines:
            mm = re.match(r"^\s*([a-zA-Z]) - (.*)$", line.strip())
            if mm and "corpse" not in mm.group(2) and "boulder" not in mm.group(2):
                self.raw_step(ord(mm.group(1)))
                n += 1
        self.raw_step(13 if n else 27)
        self.settle()

    def loot_step(self, lv):
        if self.loot_sq is None or self.loot_key != lv.key:
            return False
        if self.pos() == self.loot_sq:
            self.pickup_all()
            self.loot_pickups += 1
            self.goal_event("loot", "consumed")
            self.loot_sq = None
            self.stolen_pending = False
            return True
        if self.go_toward(lv, self.loot_sq):
            self.goal_chase("loot")
            return True
        self.goal_event("loot", "abandoned")
        self.loot_sq = None
        return False
