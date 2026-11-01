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

import nle.nethack as nh

from nhbot import glyphs as G
from nhbot.carry import (ALL_GLYPH, CARRY_GLYPH, GEM_NAMES, MORE_GLYPH, NO_TOOLS, TOOL_WORDS, WEAPON_GLYPH,
                         WEAPON_NAME_OF, singular)
from nhbot.equipment import parse_armor
from nhbot.items import base_name

# safe permanent food (no eggs: could be cockatrice; no tins: slow; no unknown corpses)
SAFE_FOOD = ("food ration", "cram ration", "lembas wafer", "K-ration", "C-ration", "fortune cookie",
             "apple", "orange", "pear", "melon", "banana", "carrot", "slime mold", "pancake", "cream pie",
             "candy bar", "lump of royal jelly", "kelp frond", "eucalyptus leaf", "sprig of wolfsbane",
             "clove of garlic", "meatball", "meat stick", "huge chunk of meat", "meat ring",
             "lichen corpse", "lizard corpse")
MAX_FOOD = 6
AMMO_WORDS = re.compile(r"\b(darts?|daggers?|knives|knife|shuriken|spears?|javelins?|arrows?|crossbow bolts?)\b")


class PickupMixin:
    # ------------------------------------------------------------------ merchandise
    def merch_risk(self, lv, pos):
        """Could what lies at pos be merchandise? On a shop square; and unless shop_by_square, whenever a
        shopkeeper is in view."""
        return bool(lv.shop[pos]) or (not self.opts.shop_by_square and self.shopkeeper_in_view())

    # ------------------------------------------------------------------ explore goals: piles worth a walk
    def carry_glyph(self, g):
        """Is this remembered glyph an item carry goes for? The SAME test makes it an explore goal and
        makes the step that inspects it (and so removes the goal) run."""
        return bool(CARRY_GLYPH[g] or (self.carry_all_on() and MORE_GLYPH[g])
                    or (WEAPON_GLYPH[g]) or (self.carry_all_on() and ALL_GLYPH[g]))

    def carry_targets(self, lv):
        glyphs = CARRY_GLYPH | MORE_GLYPH if self.carry_all_on() else CARRY_GLYPH
        glyphs = glyphs | WEAPON_GLYPH
        if self.carry_all_on():
            glyphs = glyphs | ALL_GLYPH
        mask = glyphs[lv.under] & ~lv.shop
        for p in self.goal_closed_set("pile", lv.key):
            mask[p] = False
        return mask

    def armor_targets(self, lv, glyphs_mod):
        """Mask of remembered '[' (and '%' food when low on food) piles not yet inspected."""
        mask = glyphs_mod.ARMOR_GLYPH[lv.under].copy()
        if self.food_count() < MAX_FOOD:
            mask = mask | glyphs_mod.FOOD_GLYPH[lv.under]
        for p in self.goal_closed_set("pile", lv.key):
            mask[p] = False
        return mask

    def pile_to_inspect(self, lv, y, x):
        """An armor / food / carried-class pile under us that we have not looked at, outside a shop."""
        return bool((G.ARMOR_GLYPH[lv.under[y, x]] or G.FOOD_GLYPH[lv.under[y, x]]
                     or self.carry_glyph(lv.under[y, x])) and (y, x) not in self.goal_closed_set("pile", lv.key)
                    and not lv.shop[y, x])

    # ------------------------------------------------------------------ what to take
    def carry_wanted(self, n):
        """A floor item (look_here text) to take: one of the carried classes, not merchandise."""
        if "for sale" in n:
            return None
        if re.search(r"\b(potion|scroll|ring|wand|amulet)s?\b", n) and "corpse" not in n:
            return re.sub(r"^(a|an|the|\d+)\s+", "", n).strip()
        if "corpse" not in n:
            core = base_name(n)[2]
            one = " ".join(singular(w) for w in core.split(" "))
            if (core in WEAPON_NAME_OF or one in WEAPON_NAME_OF) and " cursed" not in " " + n:
                return core
        if self.carry_all_on():
            a = parse_armor(n)
            if a is not None:
                return a["name"]
            core = base_name(n)[2]
            one = " ".join(singular(w) for w in core.split(" "))
            no_tools = NO_TOOLS - {"pick-axe"} if self.carry_all_on() else NO_TOOLS
            if (core in TOOL_WORDS or one in TOOL_WORDS) and core not in no_tools and one not in no_tools:
                return core
        if self.carry_all_on() and "corpse" not in n:
            core = base_name(n)[2]
            one = " ".join(singular(w) for w in core.split(" "))
            if "spellbook" in core:
                return core
            if "gray stone" in core:
                return None
            if one.endswith(" gem") or "glass" in one or one in GEM_NAMES or core in GEM_NAMES:
                return core
        return None

    def food_count(self):
        return sum(1 for _, ocls, _ in self.inventory() if ocls == nh.FOOD_CLASS)

    def food_wanted(self, name):
        if self.food_count() >= MAX_FOOD:
            return False
        if "egg" in name or re.search(r"\btins?\b", name):
            return False
        if "partly eaten" in name:
            return False
        return any(f in name for f in SAFE_FOOD)

    # ------------------------------------------------------------------ the paths
    def armor_pickup_here(self, lv):
        self.goal_done("pile", lv, self.pos())
        names = self.look_here()
        # never take merchandise (a lone item is picked up without a menu, so filter here)
        names = [n for n in names if "for sale" not in n]
        worn = self.worn_by_slot()
        want = []
        for n in names:
            a = parse_armor(n)
            if a and self.improves(a, worn):
                want.append(a["name"])
            elif self.carry_wanted(n):
                want.append(self.carry_wanted(n))
                self.carry_stats["picked"] += 1
            elif self.food_wanted(n):
                fm = next((f for f in SAFE_FOOD if f in n), None)
                if fm is None:
                    continue
                want.append(fm)
                self.food_picked += 1
        if not want:
            return False
        self.pickup_matching(want)
        self.equip_events.append((self.turn(), "pickup", ",".join(want)))
        return True

    def pickup_all(self):
        if self.merch_risk(self.level(), self.pos()):
            self.msg_audit["loot_pickup_merch_risk"] += 1
        self.pickup(lambda t: "corpse" not in t and "boulder" not in t, "loot")

    # ------------------------------------------------------------------ the menu
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
