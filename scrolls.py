"""Price identification of scrolls in shops, and reading the ones that can only be good.

A scroll's appearance ("scroll labeled ZELGO MER") is random per game, its base price is fixed per type
(objects.c).  The shop sell price is  base * charisma factor  (shk.c get_cost), times 4/3 for ~1/4 of
unidentified items (an arbitrary surcharge) and for a visible dunce cap / tourist shirt.  From one
price and our Cha the base is pinned down except 'base 80' == 'base 60 + surcharge'.

Read rule: an appearance whose possible base prices are all in {60, 80} is enchant weapon, blank paper,
enchant armor or remove curse -- never harmful.  Everything else stays unread.

Shop visit: general stores and bookstores, no digging tool, nothing is picked up or bought; we walk
over each '?' pile, read prices with ':' (free), then leave.
"""
import re

import numpy as np
import nle.nethack as nh

import glyphs as G

SCROLL_BASES = (20, 50, 60, 80, 100, 200, 300)
GOOD_BASES = {60, 80}
GOOD_NAMES = ("scroll of enchant armor", "scroll of enchant weapon", "scroll of remove curse")
SCROLL_SHOPS = ("general store", "second-hand bookstore")
MAX_CARRY = 12

SCROLL_GLYPH = np.zeros(nh.MAX_GLYPH, dtype=bool)
for _g in range(nh.MAX_GLYPH):
    if nh.glyph_is_normal_object(_g) and ord(nh.objclass(nh.glyph_to_obj(_g)).oc_class) == nh.SCROLL_CLASS:
        SCROLL_GLYPH[_g] = True

APPEAR_RE = re.compile(r"scrolls? labeled ([A-Z0-9 ]+?)(?: \(|$|\.|,)")
PRICE_RE = re.compile(r"scrolls? labeled ([A-Z0-9 ]+?) \(for sale, (\d+) zorkmids")


def cha_factor(cha):
    """(multiplier, divisor) from shk.c get_cost."""
    if cha > 18: return 1, 2
    if cha == 18: return 2, 3
    if cha >= 16: return 3, 4
    if cha <= 5: return 2, 1
    if cha <= 7: return 3, 2
    if cha <= 10: return 4, 3
    return 1, 1


def sell_price(base, mult, div):
    t = base * mult
    if div > 1:
        t = (t * 10 // div + 5) // 10
    return max(t, 1)


def possible_bases(price, cha, sucker=False):
    m, d = cha_factor(cha)
    if sucker:
        m, d = m * 4, d * 3
    out = set()
    for b in SCROLL_BASES:
        if sell_price(b, m, d) == price or sell_price(b, m * 4, d * 3) == price:
            out.add(b)
    return out


def possible_bases_offer(offer, qty, low_divisor):
    """Bases consistent with a shopkeeper's buy offer (shk.c set_cost): total = qty*base / 2 (or /3 for a
    dunce/tourist), times 3/4 for unidentified items at shopkeepers with m_id % 4 == 0 (fixed per shk)."""
    out = set()
    div0 = 3 if low_divisor else 2
    for b in SCROLL_BASES:
        for m, d in ((1, div0), (3, div0 * 4)):
            t = qty * b * m
            t = max((t * 10 // d + 5) // 10, 1)
            if t == offer:
                out.add(b)
    return out


OFFER_RE = re.compile(r"offers (only )?(\d+) gold pieces? for your .*?scrolls? labeled ([A-Z0-9 ]+?)\.\s+Sell")


class ScrollMixin:
    def scroll_init(self):
        self.scroll_bases = {}        # appearance -> set of possible base prices
        self.sell_probe = None        # dict(app, qty) while a drop-to-hear-the-offer is in flight
        self.probed = set()           # (shop level key, appearance)
        self.scroll_stats = {"probes": 0, "probe_info": 0, "shops_entered": 0, "priced": 0, "picked": 0, "read": 0, "read_names": [],
                             "good_appearances": 0, "seen_floor": 0}

    # ------------------------------------------------------------ knowledge
    def sucker(self):
        """Visible dunce cap or a shirt with nothing over it: shopkeepers add 1/3."""
        worn = [s for _, _, s in self.inventory() if "being worn" in s]
        if any("dunce cap" in s for s in worn):
            return True
        shirt = any("shirt" in s for s in worn)
        over = any(re.search(r"mail|armor|jacket|cloak|robe|apron|tunic|coat", s) for s in worn if "shirt" not in s)
        return shirt and not over

    def note_scroll_prices(self, text):
        for m in PRICE_RE.finditer(text):
            app, price = m.group(1).strip(), int(m.group(2))
            cand = possible_bases(price, self.bl(nh.NLE_BL_CHA), self.sucker())
            if not cand:
                continue
            old = self.scroll_bases.get(app)
            new = cand if old is None else (old & cand or old)
            if old is None:
                self.scroll_stats["priced"] += 1
            if new <= GOOD_BASES and not (old is not None and old <= GOOD_BASES):
                self.scroll_stats["good_appearances"] += 1
            self.scroll_bases[app] = new

    def scroll_is_good(self, s):
        if any(n in s for n in GOOD_NAMES):
            return True
        m = APPEAR_RE.search(s)
        return bool(m) and self.scroll_bases.get(m.group(1).strip(), set()) <= GOOD_BASES \
            and m.group(1).strip() in self.scroll_bases

    # ------------------------------------------------------------ shop visit
    def scroll_shop_greeted(self, lv, stype):
        if not self.role_opts.get("scroll_id") or stype not in SCROLL_SHOPS or lv.key in self.shops_done:
            return
        if any(("pick-axe" in s or "mattock" in s) for _, _, s in self.inventory()):
            return
        self.shopping = {"key": lv.key, "until": self.turn() + 150, "kind": "scroll"}
        self.scroll_stats["shops_entered"] += 1

    def scroll_shop_targets(self, lv):
        mask = SCROLL_GLYPH[lv.under] & lv.shop
        for p in self.inspected.get(lv.key, ()):
            mask[p] = False
        return mask

    def on_sell_offer(self, msg):
        """Called from answer_yn on 'Sell it?' while probing: learn from the offer, always decline."""
        m = OFFER_RE.search(msg)
        p = self.sell_probe
        if not m or not p or m.group(1):          # 'offers only N': shopkeeper short of cash, no info
            return
        cand = possible_bases_offer(int(m.group(2)), p["qty"], self.sucker())
        if cand:
            old = self.scroll_bases.get(p["app"])
            new = cand if old is None else (old & cand or old)
            if new <= GOOD_BASES and not (old is not None and old <= GOOD_BASES):
                self.scroll_stats["good_appearances"] += 1
            self.scroll_bases[p["app"]] = new
            self.scroll_stats["probe_info"] += 1

    def unknown_scrolls(self, lv):
        out = []
        for letter, c, s in self.inventory():
            if c != nh.SCROLL_CLASS:
                continue
            m = APPEAR_RE.search(s)
            if not m:
                continue
            app = m.group(1).strip()
            if app in self.scroll_bases and len(self.scroll_bases[app]) == 1 or (lv.key, app) in self.probed:
                continue
            q = re.match(r"(\d+) ", s)
            out.append((letter, app, int(q.group(1)) if q else 1))
        return out

    def probe_scroll(self, lv, letter, app, qty):
        """Drop it on the shop floor, hear the offer, decline, take it back."""
        self.probed.add((lv.key, app))
        self.scroll_stats["probes"] += 1
        self.sell_probe = {"app": app, "qty": qty}
        self.press("d", expect_prompt=True)
        if "drop" not in self.message().lower():
            self.settle()
        else:
            self.press(letter)
        self.sell_probe = None
        self.pickup_matching(("labeled " + app,), no_sale=True, own=True)

    def scroll_shop_step(self, lv):
        y, x = self.pos()
        unknown = self.unknown_scrolls(lv)
        # the square just inside the door is the shopkeeper's post and is not for sale: offers come only
        # for items dropped deeper inside
        near_door = any(G.KIND[lv.under[y + dy, x + dx]] in (G.DOOR_OPEN, G.DOOR_CLOSED, G.DOORWAY)
                        for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                        if 0 <= y + dy < lv.under.shape[0] and 0 <= x + dx < lv.under.shape[1])
        inside = bool(lv.shop[y, x]) and not near_door
        if unknown and inside:
            self.probe_scroll(lv, *unknown[0])
            return True
        targets = self.scroll_shop_targets(lv)
        if unknown and not targets.any():
            k = G.KIND[lv.under]
            door = np.isin(k, [G.DOOR_OPEN, G.DOOR_CLOSED, G.DOORWAY])
            near = door.copy()
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    near |= np.roll(np.roll(door, dy, 0), dx, 1)
            targets = lv.shop & ~near
            targets[y, x] = False
        if not targets.any():
            self.shops_done.add(lv.key)
            self.shopping = None
            return False
        if targets[y, x]:
            self.inspected.setdefault(lv.key, set()).add((y, x))
            self.note_scroll_prices(" ".join(self.look_here()))
            return True
        return self.go_toward_mask(lv, targets)

    # ------------------------------------------------------------ floor pickup and reading
    def scroll_count(self):
        return sum(1 for _, c, _ in self.inventory() if c == nh.SCROLL_CLASS)

    def scroll_targets(self, lv):
        mask = SCROLL_GLYPH[lv.under] & ~lv.shop
        for p in self.inspected.get(lv.key, ()):
            mask[p] = False
        if self.scroll_count() >= MAX_CARRY:
            mask[:] = False
        return mask

    def scroll_pickup_here(self, lv):
        y, x = self.pos()
        if not SCROLL_GLYPH[lv.under[y, x]] or lv.shop[y, x] or (y, x) in self.inspected.get(lv.key, ()):
            return False
        self.inspected.setdefault(lv.key, set()).add((y, x))
        names = [n for n in self.look_here() if "scroll" in n and "for sale" not in n]
        if not names:
            return False
        self.scroll_stats["seen_floor"] += 1
        if self.shopkeeper_in_view():
            return False
        self.pickup_matching(("scroll",), no_sale=True, own=True)   # own: menu parsed by column
        self.scroll_stats["picked"] += 1
        return True

    def read_good_scroll(self):
        cond = int(self.last_bl[nh.NLE_BL_CONDITION])
        if cond & (nh.BL_MASK_BLIND | nh.BL_MASK_CONF | nh.BL_MASK_STUN | nh.BL_MASK_HALLU):
            return False              # confused remove curse / enchant armor do other things
        inv = self.inventory()
        worn_ench = [int(m.group(1)) for _, c, s in inv if c == nh.ARMOR_CLASS and "being worn" in s
                     for m in [re.search(r"([+-]\d+) ", s)] if m]
        for letter, c, s in inv:
            if c != nh.SCROLL_CLASS or not self.scroll_is_good(s):
                continue
            maybe_armor = "enchant armor" in s or "labeled" in s
            if maybe_armor and worn_ench and max(worn_ench) >= 4 and "remove curse" not in s:
                continue              # enchant armor on a +4 piece may evaporate it
            if "enchant weapon" in s and not any("weapon in hand" in t for _, _, t in inv):
                continue
            self.press("r", expect_prompt=True)
            if "read" not in self.message().lower():
                self.settle()
                return False
            self.press(letter)
            self.scroll_stats["read"] += 1
            self.scroll_stats["read_names"].append(s[:60])
            return True
        return False

    def scroll_step(self, lv):
        """No hostiles in view: read a known-good scroll, or pick up a scroll we stand on."""
        if self.read_good_scroll():
            return True
        return self.scroll_pickup_here(lv)
