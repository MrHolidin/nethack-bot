"""The fight's tactical options as explicit choices (experiments; the learned chooser behind `tactic_model`).

The policy's order of steps (policy.STEPS) *is* the tactical policy: pray when critically low and a prayer is due,
Elbereth below half HP, a wand when win_prob says so, else melee. This module names the alternatives so that one of
them can be forced at a tick -- by tools/rollout (counterfactual rollouts from a forked game: what happens if we do
X here and play on as scripted) and by the chooser trained on those rollouts:

  default   the scripted steps
  melee     attack the focus target now (no prayer, potion, Elbereth, wand first)
  pray      pray now, whatever can_pray says
  elbereth  engrave Elbereth now (elb_write) -- the scripted elb_step stands on it afterwards
  quaff     drink the best known healing potion now
  zap       zap the first usable attack wand at the nearest target in line
  up, down  walk to the nearest known staircase of that kind and take it (a macro: at most STAIR_TICKS ticks)
  retreat   one step to a free square next to no hostile in view

`tactic_step` is the policy step "tactic" (before "pray"); it does nothing -- and costs nothing -- unless a hook is
installed (tools/rollout), an option is being forced, or `tactic_model` is set. The features (`tactic_features`)
are what the bot sees on the screen and remembers; nothing is read from the game's memory.
"""
import json
import os

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.carry import HEAL_POTIONS
from nhbot.combat import wand_resisted
from nhbot.consts import DELTA2KEY
from nhbot.danger import adj_level
from nhbot.monsters import PM_BY_NAME

OPTIONS = ("default", "melee", "pray", "elbereth", "quaff", "zap", "up", "down", "retreat")
MACROS = ("up", "down")
MELEE_SKIPS = ("pray", "heal", "elbereth", "wands")      # the scripted alternatives to hitting the monster next to us
STAIR_TICKS = 10           # ticks at most a forced walk to a staircase lasts
STAIR_COST = 15            # ... and the path cost at most at which a staircase is an option
WIN_SIMS = 100             # sampled fights of the win_prob feature (its own generator: never danger.win_rng)
NEIGH = [d for d in DELTA2KEY]


class TacticState:
    """State of the tactic step (TacticMixin)."""
    def __init__(self):
        self.hook = None             # experiments: hook(bot, tick) called at every tick (tools/rollout forks in it)
        self.forced = None           # (option, ticks left) of a forced macro option in progress
        self.model = None            # tactic_model: the loaded chooser (tactic_load)
        self.rng = np.random.default_rng(777)      # win_prob draws of the features
        self.stats = {}              # option -> times the chooser took it


class TacticMixin:
    def tactic_init(self):
        self.tac = TacticState()
        if self.opts.tactic_model:
            self.tactic_load(self.opts.tactic_model)
        if self.opts.rollout:
            from tools.rollout.collect import Collector       # experiments only: forks the process
            cfg = dict(self.opts.rollout)
            out = cfg.pop("out")
            os.makedirs(out, exist_ok=True)
            Collector(self, os.path.join(out, f"{self.seed}.jsonl"), **cfg)

    # ------------------------------------------------------------------ the step
    def tactic_step(self, c):
        tac = self.tac
        if tac.forced is not None:
            # a macro in progress goes on -- unless our HP is critically low: the emergencies (prayer, a potion)
            # come first again (the pilot's 'up' walked 10+ turns with a fox biting from behind and died unprayed)
            name, left = tac.forced
            tac.forced = (name, left - 1) if left > 1 else None
            if not self.critically_low_hp(c.hp, c.maxhp) and self.tactic_do(name, c):
                return True
            tac.forced = None
        if tac.hook is not None:
            tac.hook(self, c)
        if tac.model is not None:
            return self.tactic_choose(c)
        return False

    def tactic_hostiles(self, c):
        """The hostiles next to us as the perceive step finds them (it runs later in the tick: same answer)."""
        hostiles = self.adjacent_hostiles(c.lv)
        hostiles = self.blind_attackers(c.lv, hostiles)
        return self.hallu_attackers(c.lv, hostiles)

    # ------------------------------------------------------------------ the options
    def tactic_do(self, name, c):
        """Do option `name` this tick: True if it acted (the tick is over). 'default' never acts here."""
        if name == "default":
            return False
        return getattr(self, "tactic_do_" + name)(c)

    def tactic_start(self, name, c):
        """Begin option `name`: tactic_do, and a macro option (up, down) goes on over the next ticks (tac.forced) until
        its staircase is taken, it fails or STAIR_TICKS ticks are over. True if it acted."""
        self.tac.forced = (name, STAIR_TICKS) if name in MACROS else None
        if self.tactic_do(name, c):
            return True
        self.tac.forced = None
        return False

    def tactic_do_melee(self, c):
        """Fight on: the scripted steps of this tick without the alternatives to a blow (MELEE_SKIPS) -- whatever
        else comes before the melee step (a stunned wait, the vault guard, a thief, the weapon back in hand) still
        does."""
        return self.run_steps(c, after="tactic", skip=MELEE_SKIPS)

    def tactic_do_pray(self, c):
        self.pray()
        return True

    def tactic_do_elbereth(self, c):
        if not self.elb_can_write(c.lv):
            return False
        return bool(self.elb_write(c.lv))

    def tactic_do_quaff(self, c):
        it = self.find_item(nh.POTION_CLASS, HEAL_POTIONS)
        if not it:
            return False
        self.cur_act = "heal"
        if not self.ask_drink():
            return False
        self.press(it[0])
        self.surv.quaffs += 1
        return True

    def tactic_zap_choice(self, c):
        """(direction key, target square, wand letter) of the forced zap, or None: the nearest target in line (one
        next to us must be one of the hostiles), the first attack wand it does not resist."""
        wands = self.attack_wands()
        if not wands or self.soko_wands_shut(c.lv):
            return None
        hostiles = self.adjacent_hostiles(c.lv)
        for key, _, pos, _, name, _, _ in self.wand_targets(c.lv, hostiles):
            for letter, kind in wands:
                if not wand_resisted(kind, name) and not (kind == "sleep" and self.asleep(c.lv, pos)):
                    return key, pos, letter
        return None

    def tactic_do_zap(self, c):
        ch = self.tactic_zap_choice(c)
        if ch is None:
            return False
        key, pos, letter = ch
        self.cur_act = "fight"
        self.aim_at(pos)
        return bool(self.zap(letter, key))

    def tactic_stairs(self, c, kind):
        """(path cost, True if we stand on it) to the nearest remembered staircase of this kind, or None."""
        mask = self.kinds(c.lv) == kind
        if not mask.any():
            return None
        here = (c.y, c.x)
        if mask[here]:
            return 0, True
        k_mem, k_live, passable = self.grids(c.lv)
        dist, _, reached = self.dijkstra(c.lv, k_mem, k_live, passable, here, mask, max_cost=STAIR_COST)
        return (int(dist[reached]), False) if reached is not None else None

    def tactic_do_stairs(self, c, kind, key):
        st = self.tactic_stairs(c, kind)
        if st is None:
            return False
        if st[1]:
            self.take_stairs(key)
            self.tac.forced = None                   # the macro ends with the staircase taken
            return True
        return self.walk_to(c.lv, self.kinds(c.lv) == kind, max_cost=STAIR_COST, act="flee")[0] == "moved"

    def tactic_do_up(self, c):
        return self.bl(nh.NLE_BL_DEPTH) > 1 and self.tactic_do_stairs(c, G.UPSTAIR, "<")

    def tactic_do_down(self, c):
        return self.tactic_do_stairs(c, G.DOWNSTAIR, ">")

    def tactic_retreat_square(self, c):
        """The free square next to us farthest from every hostile in view (at least 2 from each), or None."""
        vis = [p for p, _ in self.visible_hostiles(c.lv)] + [p for p, _ in self.adjacent_hostiles(c.lv)]
        if not vis:
            return None
        k_mem, k_live, passable = self.grids(c.lv)
        best, best_d = None, 1
        door_here = k_mem[c.y, c.x] in (G.DOOR_OPEN, G.DOORWAY) or c.lv.no_diag[c.y, c.x]
        for dy, dx in NEIGH:
            p = (c.y + dy, c.x + dx)
            if not (0 <= p[0] < passable.shape[0] and 0 <= p[1] < passable.shape[1]) or not passable[p]:
                continue
            if k_live[p] in (G.MONSTER, G.PET, G.INVIS, G.BOULDER) or k_mem[p] in (G.TRAP, G.LIQUID, G.DOOR_CLOSED):
                continue
            if dy and dx and (door_here or k_mem[p] in (G.DOOR_OPEN, G.DOORWAY) or c.lv.no_diag[p]):
                continue
            d = min(max(abs(p[0] - q[0]), abs(p[1] - q[1])) for q in vis)
            if d > best_d:
                best, best_d = p, d
        return best

    def tactic_do_retreat(self, c):
        sq = self.tactic_retreat_square(c)
        if sq is None:
            return False
        self.cur_act = "flee"
        self.move(sq)
        return True

    def tactic_legal(self, c, hostiles):
        """The options that can be tried here, 'default' first."""
        out = ["default"]
        if hostiles:
            out.append("melee")
        last = self.surv.last_pray
        if self.critically_low_hp(c.hp, c.maxhp) and not self.can_pray() and not self.surv.god_angry \
                and (last is None or c.t - last > 50):
            out.append("pray")                       # pray.c: only critically low HP is trouble a prayer fixes; with
                                                     # can_pray the default prays already
        if self.elb_can_write(c.lv) and (c.y, c.x) not in c.lv.elbereth:
            out.append("elbereth")
        if self.find_item(nh.POTION_CLASS, HEAL_POTIONS):
            out.append("quaff")
        if self.tactic_zap_choice(c) is not None:
            out.append("zap")
        if self.bl(nh.NLE_BL_DEPTH) > 1 and self.tactic_stairs(c, G.UPSTAIR) is not None:
            out.append("up")
        if self.tactic_stairs(c, G.DOWNSTAIR) is not None:
            out.append("down")
        if self.tactic_retreat_square(c) is not None:
            out.append("retreat")
        return out

    # ------------------------------------------------------------------ the features
    def tactic_features(self, c, hostiles):
        """What the chooser sees: a flat dict of numbers, all from the screen and the bot's own memory (HP, AC, XL,
        depth, the prayer clock as we count it, the hostiles next to us through danger.py's model, the others in
        view, the staircases, Elbereth, the options' resources)."""
        hp, maxhp, t = c.hp, c.maxhp, c.t
        lv = c.lv
        depth, xl = self.bl(nh.NLE_BL_DEPTH), self.bl(nh.NLE_BL_XP)
        cond = int(self.last_bl[nh.NLE_BL_CONDITION])
        last = self.surv.last_pray
        f = {"hp": hp, "maxhp": maxhp, "hp_frac": hp / max(maxhp, 1), "ac": self.bl(nh.NLE_BL_AC), "xl": xl,
             "depth": depth, "dnum": self.bl(nh.NLE_BL_DNUM), "turn": t,
             "pray_gap": t - last if last is not None else t + 200,      # never prayed: prayer timeout 300 at turn 1
             "prayers": self.surv.prayers, "can_pray": int(self.can_pray()),
             "crit_low": int(self.critically_low_hp(hp, maxhp)), "god_angry": int(self.surv.god_angry),
             "hunger": c.hunger, "stun": int(bool(cond & nh.BL_MASK_STUN)), "conf": int(bool(cond & nh.BL_MASK_CONF)),
             "blind": int(bool(cond & nh.BL_MASK_BLIND)), "hallu": int(bool(cond & nh.BL_MASK_HALLU)),
             "lev": int(bool(cond & nh.BL_MASK_LEV)), "cap": self.bl(nh.NLE_BL_CAP), "speed": self.our_speed()}
        past = [h[1] for h in self.pol.hist if c.t - 5 <= h[0] < c.t]
        f["hp_drop5"] = max(0, max(past, default=hp) - hp)          # HP lost over the last 5 turns
        # the hostiles next to us
        parts = [self.danger_parts(pos, name) for pos, name in hostiles]
        mean1, pd1 = self.danger_combine(parts, None, hp) if parts else (0.0, 0.0)
        known = [(pos, name) for pos, name in hostiles if name in PM_BY_NAME]
        levs = [adj_level(PM_BY_NAME[n].mlevel, depth, xl) for _, n in known]
        f.update(n_adj=len(hostiles), n_adj_unknown=len(hostiles) - len(known), dmg1=mean1, pdeath1=pd1,
                 adj_lev_max=max(levs, default=0), adj_lev_sum=sum(levs),
                 adj_move_max=max((PM_BY_NAME[n].mmove for _, n in known), default=0),
                 adj_respect=sum(1 for p, n in hostiles if self.respects(p, n)),
                 adj_asleep=sum(1 for p, _ in hostiles if self.asleep(lv, p)))
        tgt = None
        if hostiles:
            tgt = hostiles[0] if len(hostiles) == 1 else max(
                hostiles, key=lambda h: (self.focus_score(h[0], h[1]), h[1] != "invisible"))
        fp = self.focus_parts(*tgt) if tgt else None
        fp = fp or {"p": 0.0, "dmg": 0.0, "hits": 0, "rem": 0.0, "ttk": 0.0, "dpt": 0.0, "inst": 0.0, "lev": 0}
        f.update(tgt_p=fp["p"], tgt_dmg=fp["dmg"], tgt_hits=fp["hits"], tgt_rem=fp["rem"], tgt_ttk=min(fp["ttk"], 99.0),
                 tgt_dpt=fp["dpt"], tgt_inst=fp["inst"], tgt_lev=fp["lev"])
        saved, self.danger.win_rng = self.danger.win_rng, self.tac.rng
        try:
            f["win_prob"] = self.win_prob(known, sims=WIN_SIMS) if known else 1.0
        finally:
            self.danger.win_rng = saved
        # the others in view
        vis = self.visible_hostiles(lv)
        adj_pos = {p for p, _ in hostiles}
        far = [max(abs(p[0] - c.y), abs(p[1] - c.x)) for p, _ in vis if p not in adj_pos]
        far_lev = [adj_level(PM_BY_NAME[n].mlevel, depth, xl) for p, n in vis if p not in adj_pos and n in PM_BY_NAME]
        g = self.obs["glyphs"]
        f.update(n_vis=len(vis), n_far=len(far), far_near=min(far, default=99), far_within3=sum(1 for d in far if d <= 3),
                 far_lev_max=max(far_lev, default=0), far_lev_sum=sum(far_lev),
                 pets=int((G.KIND[g] == G.PET).sum()))
        # the ground: staircases, Elbereth, room to move
        up, down = self.tactic_stairs(c, G.UPSTAIR), self.tactic_stairs(c, G.DOWNSTAIR)
        k_mem, k_live, passable = self.grids(lv)
        free = sum(1 for dy, dx in NEIGH
                   if 0 <= c.y + dy < passable.shape[0] and 0 <= c.x + dx < passable.shape[1]
                   and passable[c.y + dy, c.x + dx] and k_live[c.y + dy, c.x + dx] not in (G.MONSTER, G.INVIS))
        f.update(up_cost=up[0] if up else 99, down_cost=down[0] if down else 99,
                 on_elb=int((c.y, c.x) in lv.elbereth), elb_state=int(self.elb.state is not None),
                 elb_can=int(self.elb_can_write(lv)), elb_blocked=int(bool(vis) and self.elb_blocked(lv)),
                 free_sq=free, retreat=int(self.tactic_retreat_square(c) is not None))
        # the resources
        heal = [it for it in self.items() if it.ocls == nh.POTION_CLASS and not it.cursed
                and any(f" of {n}" in it.text for n in HEAL_POTIONS)]
        f.update(n_heal=len(heal), n_wands=len(self.attack_wands()), zap_ok=int(self.tactic_zap_choice(c) is not None),
                 excalibur=int(any(it.wielded and "Excalibur" in it.text for it in self.items())))
        return f

    # ------------------------------------------------------------------ the learned chooser
    def tactic_load(self, path):
        """tactic_model: the chooser's weights (a json written by tools/rollout/train.py; plain numpy at play time)."""
        from nhbot.tacticmodel import TacticModel
        if not os.path.isabs(path):
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
        with open(path) as fh:
            self.tac.model = TacticModel(json.load(fh))

    def tactic_choose(self, c):
        """tactic_model: at a decision point of the model (TacticModel.wants), the option it values highest among the
        legal ones -- taken when it beats the scripted default by the model's margin; True if it acted."""
        hostiles = self.tactic_hostiles(c)
        if not hostiles and (c.hp >= c.maxhp / 2 or not c.vis):
            return False
        model = self.tac.model
        feat = self.tactic_features(c, hostiles)
        if not model.wants(feat):
            return False
        pick = model.choose(feat, self.tactic_legal(c, hostiles))
        self.tac.stats[pick] = self.tac.stats.get(pick, 0) + 1
        return pick != "default" and self.tactic_start(pick, c)
