"""Experiments only (option gift): put items into the inventory at the start of the game, identified, to measure
what having them is worth to the bot as it plays now.

The running game's own functions are called through the loaded libnethack copy (NLE dlopens one per
instance; the game is suspended between steps, so its state is consistent): readobjnam -- the wish parser,
non-wizard rules -- then fully_identify_obj and addinv. One call per unit (a wish caps stack sizes). A wish may
lower the enchantment asked for and leaves the curse status to chance: the enchantment is written into the
object (struct obj: otyp at offset 30, spe at 48, x86_64) and it is blessed if asked, else uncursed. The game is
not in wizard mode: level generation and prompts stay those of a normal game. The calls use the game's RNG, so a
gifted game departs from the same seed without the gift.
"""
import _ctypes
import ctypes
import re


SPE_OFFSET = 48                  # struct obj: nobj, v, cobj (8 each), o_id (4), ox, oy (1 each), otyp (2), owt (4),
                                 # quan (8), spe


class GiftMixin:
    def gift_init(self):
        self.gift_stats = {}             # name -> {"given", "held_end", "on_body_end", "first_on_body"}

    def gift_apply(self):
        gifts = self.opts.gift
        if not gifts:
            return
        self.gift_items([gifts] if isinstance(gifts, str) else gifts)

    def gift_items(self, names):
        """Put the named items (wish syntax) into the inventory, identified; one step without time after."""
        lib = ctypes.CDLL(self.env.unwrapped.nethack.dlpath)
        lib.readobjnam.restype = ctypes.c_void_p
        lib.readobjnam.argtypes = [ctypes.c_char_p, ctypes.c_void_p]
        lib.fully_identify_obj.argtypes = [ctypes.c_void_p]
        lib.addinv.restype = ctypes.c_void_p
        lib.addinv.argtypes = [ctypes.c_void_p]
        for f in ("bless", "uncurse"):
            getattr(lib, f).argtypes = [ctypes.c_void_p]
        for name in names:
            buf = ctypes.create_string_buffer(name.encode(), 256)    # readobjnam edits its buffer
            obj = lib.readobjnam(buf, None)
            st = self.gift_stats.setdefault(name, {"given": 0, "held_end": False, "on_body_end": False,
                                                   "first_on_body": None})
            if obj:
                m = re.search(r"(?:^|\s)([+-]\d+)\s", name)
                if m:
                    ctypes.c_byte.from_address(obj + SPE_OFFSET).value = int(m.group(1))
                if "blessed" in name:
                    lib.bless(obj)
                elif "cursed" not in name.replace("uncursed", ""):
                    lib.uncurse(obj)
                lib.fully_identify_obj(obj)
                lib.addinv(obj)
                st["given"] += 1
        _ctypes.dlclose(lib._handle)             # NLE refuses to load its library again while a handle is open
        self.raw_step(27)                         # a step without time: the observation shows the inventory
        self.settle()

    def gift_match(self, name, text):
        words = [w for w in name.split() if not w.lstrip("+-").isdigit() and w not in ("blessed", "uncursed")]
        return all(w.rstrip("s") in text for w in words[-2:])

    def gift_check(self):
        for name, st in self.gift_stats.items():
            held = [it for it in self.items() if self.gift_match(name, it.text)]
            st["held_end"] = bool(held)
            st["on_body_end"] = any(it.on_body for it in held)
            if st["on_body_end"] and st["first_on_body"] is None:
                st["first_on_body"] = self.turn()
