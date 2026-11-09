"""Picking things up: what lies where and is worth a walk (explore goals), what to take from a pile, the
'Pick up what?' menu, merchandise. Every path that picks something up goes through here:

  pile        housekeeping on an uninspected pile under us (armor upgrade, carried classes, weapons, food)
  gold        gold on our square (step_gold_here)
  ammo        our missiles on our square (step_ammo_here)
  retrieve    our thrown missiles along their rays (step_retrieve_missiles)
  loot        the square a thief died on (thieves.loot_consume)
  own         what we put down ourselves (an unsold offer, the digger left outside a shop)
"""
import re
from collections import Counter

import numpy as np
import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.carry import (ALL_GLYPH, CARRY_CLASSES, CARRY_GLYPH, GEM_NAMES, MORE_GLYPH, NO_TOOLS, OBJ_INFO,
                         TOOL_WORDS, WEAPON_GLYPH, WEAPON_NAME_OF)
from nhbot.equipment import GLOVES, parse_armor
from nhbot.game import MENU_RE
from nhbot.items import CURSED_RE, base_name, parse_item, singular_name
from nhbot.tins import MAX_TINS
from nhbot.weapons import THROWABLE
from nhbot.wishing import LAMP_NAMES

# safe permanent food (no eggs: could be cockatrice; no tins: slow; no unknown corpses)
SAFE_FOOD = ("food ration", "cram ration", "lembas wafer", "K-ration", "C-ration", "fortune cookie",
             "apple", "orange", "pear", "melon", "banana", "carrot", "slime mold", "pancake", "cream pie",
             "candy bar", "lump of royal jelly", "kelp frond", "eucalyptus leaf", "sprig of wolfsbane",
             "clove of garlic", "meatball", "meat stick", "huge chunk of meat", "meat ring",
             "lichen corpse", "lizard corpse")
KEEP_FOOD = tuple(f for f in SAFE_FOOD if not f.endswith(" corpse"))   # food we eat from the pack (survival
#                                  eat_from_inventory: no corpse -- a lichen / lizard corpse was kept, never eaten)
MAX_FOOD = 6                       # pieces of KEEP_FOOD kept (value.keep_plan)

# ---------------------------------------------------------------- item kinds by type, not substring
_WEAPONS = {nh.OBJ_NAME(nh.objclass(i)) for i in range(nh.NUM_OBJECTS)
            if ord(nh.objclass(i).oc_class) == nh.WEAPON_CLASS and nh.OBJ_NAME(nh.objclass(i))}
MISSILE_TYPES = {n for n in _WEAPONS if any(w in n for w in THROWABLE)} - {"crysknife"}   # what we throw
AMMO_TYPES = {"arrow", "elven arrow", "orcish arrow", "silver arrow", "ya", "crossbow bolt"}   # needs a launcher
WIELD_TYPES = {"long sword", "katana"}                                                       # weapons.weapon_rank
THROW_STONE_TYPES = {"flint stone", "rock"}
FOOD_NAMES = {nh.OBJ_NAME(nh.objclass(i)) for i in range(nh.NUM_OBJECTS)
              if ord(nh.objclass(i).oc_class) == nh.FOOD_CLASS and nh.OBJ_NAME(nh.objclass(i))}
CLASS_WORDS = {"potion": nh.POTION_CLASS, "scroll": nh.SCROLL_CLASS, "ring": nh.RING_CLASS, "wand": nh.WAND_CLASS,
               "amulet": nh.AMULET_CLASS, "spellbook": nh.SPBOOK_CLASS}
CLASS_RE = re.compile(r"\b(potion|scroll|ring|wand|amulet|spellbook)s?\b")
PETRIFYING_CORPSE_RE = re.compile(r"\b(?:cockatrice|chickatrice) corpses?\b")   # mondata.h:192 touch_petrifies
WANTED_WEAPON_GLYPH = np.zeros(nh.MAX_GLYPH, dtype=bool)   # a remembered weapon worth the walk
for _g in range(nh.MAX_GLYPH):
    if WEAPON_GLYPH[_g]:
        _n = nh.OBJ_NAME(nh.objclass(nh.glyph_to_obj(_g)))
        _wc = OBJ_INFO.get((nh.WEAPON_CLASS, _n))
        WANTED_WEAPON_GLYPH[_g] = _n not in AMMO_TYPES and (_n in MISSILE_TYPES or _n in WIELD_TYPES
                                                          or bool(_wc and _wc[1] >= _wc[0]))


def floor_kind(text):
    """Floor / menu text -> (object class or None, type name): identified name for weapons and food, else the
    bare name -- in the singular (items.singular_name)."""
    # (name_parse, accepted without A/B by the user -- see carry.describe): the singular by makeplural inverted,
    # not word by word ("knives" was "knif", no weapon; "cloves of garlic" no food)
    _, _, name = base_name(text)
    one = singular_name(name)
    if re.search(r"\bgold pieces?\b", name):
        return nh.COIN_CLASS, "gold piece"
    if re.search(r"\bcorpses?$", name):
        return nh.FOOD_CLASS, one
    if name in FOOD_NAMES or one in FOOD_NAMES:
        return nh.FOOD_CLASS, name if name in FOOD_NAMES else one
    a = parse_armor(text)                   # before the class words: "ring mail" is armor, not a ring
    if a is not None:
        return nh.ARMOR_CLASS, a["name"]
    m = CLASS_RE.search(name)
    if m:
        return CLASS_WORDS[m.group(1)], name
    w = WEAPON_NAME_OF.get(name) or WEAPON_NAME_OF.get(one)
    if w:
        return nh.WEAPON_CLASS, w
    if name in TOOL_WORDS or one in TOOL_WORDS:
        return nh.TOOL_CLASS, one if one in TOOL_WORDS else name
    if one in ("boulder", "statue") or one.startswith("statue of"):
        return nh.ROCK_CLASS, one
    if one in ("heavy iron ball", "iron chain"):
        return nh.BALL_CLASS if "ball" in one else nh.CHAIN_CLASS, one
    if one in GEM_NAMES or name in GEM_NAMES or one.endswith(" gem") or "glass" in one or one.endswith(" stone") \
            or one == "rock":
        return nh.GEM_CLASS, one
    return None, name


LIFT_UNDO_TURNS = 30     # lift_heavy: turns after a pick-up into Burdened its drops are watched (lift_undo)


class PickupState:
    """State of picking things up (PickupMixin)."""
    def __init__(self):
        self.stats = Counter()         # why things were taken / refused
        self.lift_want = None          # lift_heavy: the want of the pick-up under way (pickup, lift_answer)
        self.lift_last = None          # lift_heavy: (type, turn) of the last pick-up let through into Burdened
        self.never_take = set()        # bare names dropped to make room (sokoban.soko_make_room): never taken again
        self.food_picked = 0           # food stacks taken from piles (armor_pickup_here)


class PickupMixin:
    def pickup_init(self):
        self.pick = PickupState()

    # ------------------------------------------------------------------ merchandise
    def merch_risk(self, lv, pos):
        """Could what lies at pos be merchandise? On a shop square; a shopkeeper in view counts only while no
        shop on this level is marked (the marked squares are the better answer)."""
        return bool(lv.shop[pos]) or (self.shopkeeper_in_view() and not lv.shop.any())

    def merch_mask(self, lv):
        """merch_risk of every square at once (merch_one: the walk mask of an item goal, so it agrees with the
        step that takes the item there)."""
        if self.shopkeeper_in_view() and not lv.shop.any():
            return np.ones_like(lv.shop, dtype=bool)
        return lv.shop.astype(bool)

    # ------------------------------------------------------------------ one rule what to take
    def take_reason(self, text, worn=None):
        """Why we'd take this floor item: "armor" (an upgrade), "missile", "weapon" (a wield candidate), "food",
        "carry" (worth carrying to sell / use); None: leave it. Never merchandise, known-cursed armor / weapons,
        ammunition without a launcher, rocks / boulders / iron balls. Only with a letter for it (value.slot_ok)."""
        reason = self.take_reason_kind(text, worn)
        if reason is not None and not self.slot_ok(floor_kind(text)[0], text, reason):
            return None
        return reason

    def take_reason_kind(self, text, worn=None):
        """take_reason before the letter count. Food, missiles, wield candidates and diggers only within what
        value.keep_plan keeps of our pack with this stack added (food by pieces, no corpses; MISSILE_KEEP missile
        pieces; one wield candidate and one Excalibur long sword; one digger -- "digger", a dwarvish mattock, worth
        less than its weight, was never taken); tins up to MAX_TINS."""
        if "for sale" in text or base_name(text)[2] in self.pick.never_take:
            return None
        ocls, typ = floor_kind(text)
        cursed = bool(CURSED_RE.search(text))
        kept = self.keep_reason(parse_item("?", ocls, text)) if ocls is not None else None
        reason = None
        if kept == "digger" and not cursed:
            reason = "digger"
        elif ocls == nh.FOOD_CLASS:
            if typ == "tin":
                if self.tins_carried() < MAX_TINS:
                    reason = "tin"
            elif kept == "food" and "partly eaten" not in text:
                reason = "food"
        elif ocls in CARRY_CLASSES:
            reason = "carry"
        elif ocls == nh.ARMOR_CLASS:
            a = parse_armor(text)
            if a is not None and not a["cursed"] and self.improves(a, worn if worn is not None else self.worn_by_slot()):
                reason = "armor"
            elif not cursed:
                reason = "carry"
        elif ocls == nh.WEAPON_CLASS and not cursed and typ not in AMMO_TYPES:
            if typ in MISSILE_TYPES:
                reason = "missile" if kept == "missile" else None
            elif typ in WIELD_TYPES:
                reason = "weapon" if kept in ("wield", "excalibur") else None
            else:
                wc = OBJ_INFO.get((nh.WEAPON_CLASS, typ))
                if wc and wc[1] >= wc[0]:
                    reason = "carry"                     # worth >= 1 zorkmid per weight unit
        elif ocls == nh.TOOL_CLASS:
            if typ in LAMP_NAMES and not cursed:
                return "lamp"                            # maybe a magic lamp: rubbed (nhbot.wishing)
            if not cursed and self.lock_tool_wanted(text):
                return "carry"                           # lock_tools: a better unlocking tool, whatever it weighs
            if typ not in NO_TOOLS:
                reason = "carry"
        elif ocls in (nh.SPBOOK_CLASS, nh.GEM_CLASS):
            if ocls == nh.SPBOOK_CLASS or not (typ == "gray stone" or typ in THROW_STONE_TYPES):
                reason = "carry"
        if reason in ("carry", "digger") and not self.worth_taking(ocls, text):
            return None
        return reason

    # ------------------------------------------------------------------ explore goals: piles worth a walk
    def pile_mask(self, lv):
        """The piles worth a look -- the one mask explore walks to, housekeeping inspects (pile_to_inspect)
        and the goal statistics count (goals.goal_raw): '[' piles, '%' food while we carry less than MAX_FOOD
        pieces, what carry goes for, the corpses on what our kills carried; not in a shop, not looked at yet.
        (A/B pile_one: -494 [-980, +4], median 7726 -> 7726, 67 of 1000 changed)"""
        mask = G.ARMOR_GLYPH[lv.under] | (CARRY_GLYPH | MORE_GLYPH | WANTED_WEAPON_GLYPH | ALL_GLYPH)[lv.under]
        if self.food_count() < MAX_FOOD:
            mask |= G.FOOD_GLYPH[lv.under]
        for p in self.corpse_piles(lv):
            mask[p] = True
        for p in self.goal_closed_set("pile", lv.key):
            mask[p] = False
        return mask & ~lv.shop

    def corpse_piles(self, lv):
        """Squares of our kills (Level.kill_piles) where a corpse lies on top -- what the monster carried is
        under it, unseen. (A/B kill_site, with resuming an interrupted meal: +800 [-528, +2171], median
        4146 -> 4645.)"""
        return [p for p in lv.kill_piles if G.KIND[lv.under[p]] == G.CORPSE]

    def pile_to_inspect(self, lv, y, x):
        """An armor / food / carried-class pile under us (or a corpse on what a kill carried) that we have not
        looked at, outside a shop: pile_mask -- food only while we carry less than MAX_FOOD, as explore walks to it."""
        return bool(self.pile_mask(lv)[y, x])

    # ------------------------------------------------------------------ what to take
    def food_count(self):
        """Pieces of the food we eat from the pack (KEEP_FOOD) we carry."""
        return sum(base_name(it.text)[0] for it in self.items()
                   if it.ocls == nh.FOOD_CLASS and floor_kind(it.text)[1] in KEEP_FOOD)

    # ------------------------------------------------------------------ the paths
    def armor_pickup_here(self, lv):
        self.goal_done("pile", lv, self.pos())
        names = self.look_here()
        # never take merchandise (a lone item is picked up without a menu, so filter here)
        names = [n for n in names if "for sale" not in n]
        worn = self.worn_by_slot()
        reasons = [self.take_reason(n, worn) for n in names]
        if not any(reasons):
            return False
        for r in reasons:
            if r:
                self.pick.stats[r] += 1
                self.carry_stat("picked", r in ("carry", "missile", "weapon"))
                self.pick.food_picked += r == "food"
        self.take_here(lambda t: self.take_reason(t, worn) is not None, "pile")
        self.equip_event("pickup", ",".join(n for n, r in zip(names, reasons) if r))
        return True

    def pickup_all(self):
        if self.merch_risk(self.level(), self.pos()):
            self.msg_audit["loot_pickup_merch_risk"] += 1
        # what the thief took from us, and whatever else is worth taking; never merchandise (a thief that dies in
        # a shop leaves its haul for sale)
        def want(t):
            if "for sale" in t:
                return False
            if base_name(t)[2] in self.thief.stolen_names:
                self.pick.stats["loot_stolen"] += 1
                return True
            return self.take_reason(t) is not None
        self.take_here(want, "loot")

    def ammo_want(self, t):
        """A missile of ours to pick up: a missile weapon or a stone we throw, not for sale, not cursed."""
        if "for sale" in t or CURSED_RE.search(t):
            return False
        ocls, typ = floor_kind(t)
        return (ocls == nh.WEAPON_CLASS and typ in MISSILE_TYPES) or (ocls == nh.GEM_CLASS and typ in THROW_STONE_TYPES)

    def take_ammo(self):
        """Ammo / retrieve: our missiles (and the stones we throw) here."""
        if not self.merch_risk(self.level(), self.pos()):
            self.take_here(self.ammo_want, "ammo")

    def never_take_again(self, name):
        """Items of bare name are dropped to make room (sokoban.soko_make_room): never taken again."""
        self.pick.never_take.add(name)

    def take_here(self, want, site):
        """Pick up what want(text) accepts; a lone item comes without a menu whatever it is: put it
        straight back down if want rejects it."""
        seq0 = self.msg_seq
        how = self.pickup(want, site)
        lone = None
        if how == "lone":                # one item, no menu: "f - an orcish dagger." (a menu pickup of several
            for t in self.msgs_since(seq0):     # items reports them all in one line: not this case)
                lone = re.match(r"^([a-zA-Z]) - ([^.]+)", t)
                if lone:
                    break
        if lone is not None and not want(lone.group(2)):
            self.pick.stats["lone_dropped"] += 1
            self.drop_units(lone.group(1))

    # ------------------------------------------------------------------ the square
    def look_here(self):
        """Names of items on our square (':' look), without consuming a turn."""
        self.raw_step(ord(":"))
        names = []
        for _ in range(20):
            tty = self.tty_text()
            msg = self.message()
            m = re.search(r"You (?:see|feel) here (.+?)\.", msg) or re.search(r"You (?:see|feel) here (.+?)\.", tty.replace("\n", " "))
            if m:
                names.append(m.group(1))
            if "Things that are here" in tty or "There are several objects here" in tty:
                if "Things that are here" in tty:
                    for item in (l.strip() for l in self.menu_lines(tty, "Things that are here")):
                        if not item or item.startswith("--More--") or item.startswith("(end)"):
                            continue
                        names.append(item.replace("--More--", "").strip())
            if self.obs["misc"][2] or "--More--" in tty.replace("\n", "") or MENU_RE.search(tty):
                self.raw_step(13 if "(end)" not in tty else 27)
                continue
            break
        self.settle()
        self.price_note_text(" | ".join(names))
        return names

    # ------------------------------------------------------------------ the menu
    def pickup(self, want, site):
        """',' and select what want(text) accepts in the 'Pick up what?' menu (a lone item is picked up
        without a menu). Returns "menu", or "lone" when there was no menu; "none" when it pressed nothing (a lone
        item want rejects). The square is read first (':' costs no game time): pickup.c:869 query_objlist
        AUTOSELECT_SINGLE takes one object here without a menu, whatever it is -- a cockatrice corpse killed us so.
        A/B safe_pickup (1000 games, 79000..): +386 [-312, +1103], median 7777 -> 7850."""
        want = self.touch_safe(want)
        here = self.look_here()
        if len(here) == 1 and not want(here[0]):
            self.pick.stats["lone_refused"] += 1
            return "none"
        seq0 = self.msg_seq
        self.pick.lift_want = want                  # lift_heavy: a lone item lifted into Burdened, if want takes it
        self.press(",", expect_prompt=True)
        tty = self.tty_text()
        if "Pick up what?" not in tty:
            self.settle()
            self.pick.lift_want = None
            for t in self.msgs_since(seq0):
                mm = re.match(r"^[a-zA-Z] - (.+?)\.?$", t)
                if mm and not want(mm.group(1)):
                    self.msg_audit["lone_unwanted_" + site] += 1     # picked up what the filter rejects
            return "lone"
        if re.search(r"\(1 of \d+\)", tty):
            self.msg_audit["pickup_multipage_" + site] += 1
        self.pick.lift_want = lambda t: True        # what the menu selected is what want took
        self.menu_pick("Pick up what?", want)
        self.settle()
        self.pick.lift_want = None
        return "menu"

    def touch_safe(self, want):
        """want, but never a cockatrice / chickatrice corpse while we wear no gloves: pickup.c:1513
        pickup_object -> fatal_corpse_mistake (pickup.c:258): touching it bare-handed stones us."""
        if GLOVES in self.worn_by_slot():
            return want
        return lambda t: not PETRIFYING_CORPSE_RE.search(t) and want(t)

    def lift_undo(self, it, inv, same):
        """lift_heavy: it, the next thing the drop step would shed, while we are Burdened after letting a pick-up
        through -- worth as much per weight as what we lifted, or more (our weight estimate missed: more has to
        go than worth_taking reckoned): the lifted thing goes instead. it otherwise."""
        if self.pick.lift_last is None or self.turn() - self.pick.lift_last[1] > LIFT_UNDO_TURNS:
            self.pick.lift_last = None
            return it
        lifted = next((x for x in inv if floor_kind(x.text)[1] == self.pick.lift_last[0]), None)
        if lifted is None or lifted.letter == it.letter:
            return it
        if self.value_per_weight(it, same(it)) >= self.value_per_weight(lifted, same(lifted)):
            self.pick.lift_last = None
            self.carry_stat("lift_heavy_undone")
            return lifted
        return it

    def lift_answer(self, m):
        """lift_heavy: "You have a little trouble lifting X.  Continue?" (pickup.c lift_object: we'd be Burdened)
        -- yes if the pick-up asked for X and worth_taking judges it worth more than what the drop step will shed
        for it; much trouble (Stressed) or more: no."""
        if self.luck_lift(m):
            return True                       # mines_luckstone: a tested gray stone, whatever the drop step sheds for it
        if re.search(r"a little trouble (lifting|removing) \d+ gold pieces?\.", m):
            return True                       # coins: 100 weigh 1, worth more than anything we carry (a vault's
            #                                   gold left lying had vault_rob / vault_exit walk back for it; out of
            #                                   the bag -- pickup.c out_container -- for the vault guard / a priest)
        mm = re.search(r"a little trouble lifting (.+?)\.\s+Continue\?", m)
        want = self.pick.lift_want
        if not (mm and want is not None):           # (A/B lift_heavy +248)
            return False
        name = mm.group(1)
        tags = self.prices.for_sale.get((self.cur_key, self.pos()), {})     # the price tag want may look for
        texts = [name] + ["%s (for sale, %d zorkmids)" % (t, pr) for t, pr in tags.items() if t in name or name in t]
        ocls = floor_kind(name)[0]
        # worth_taking: worth more per weight than what the drop step sheds for it -- not only "carry" picks pass
        # it (armor to wear, food, weapons don't), and one that fails would be the first thing dropped again
        ok = any(want(t) for t in texts) and ocls is not None and self.worth_taking(ocls, name)
        if ok:
            self.pick.lift_last = (floor_kind(name)[1], self.turn())
        self.carry_stat("lift_heavy_" + ("yes" if ok else "no"))
        return ok

    def pickup_matching(self, words, no_sale=False, own=False):
        if not own and self.merch_risk(self.level(), self.pos()):
            return                            # in a shop: anything here may be merchandise
        self.pickup(lambda t: any(w in t for w in words) and not (no_sale and "for sale" in t), "matching")
