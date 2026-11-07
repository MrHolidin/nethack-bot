"""Experiments only: the true map of the current level, read from the running game's memory -- for analysis and
data (search_log), never for play. The bot itself sees only what the screen shows.

How. NLE dlopens its own copy of libnethack per instance (env.unwrapped.nethack.dlpath); between steps the game
is suspended, so its globals are consistent. In 3.6.6 the map is `levl`, a macro for `level.locations` (rm.h):
the global `dlevel_t level` begins with `struct rm locations[COLNO][ROWNO]` (COLNO 80, ROWNO 21), column-major.
struct rm on x86_64 is 8 bytes:
    int glyph                       offset 0
    schar typ                       offset 4   (rm.h levl_typ_types: STONE 0, VWALL 1 .. DBWALL 12, TREE 13,
                                                SDOOR 14, SCORR 15, POOL 16, MOAT 17, WATER 18, DRAWBRIDGE_UP 19,
                                                LAVAPOOL 20, IRONBARS 21, DOOR 22, CORR 23, ROOM 24, STAIRS 25,
                                                LADDER 26, FOUNTAIN 27, THRONE 28, SINK 29, GRAVE 30, ALTAR 31,
                                                ICE 32, DRAWBRIDGE_DOWN 33, AIR 34, CLOUD 35)
    uchar seenv                     offset 5
    flags:5 horizontal:1 lit:1 waslit:1 roomno:6 edge:1 candig:1     offset 6-7 (bitfields from the low bit);
                                    for a door, flags is its doormask (D_NODOOR 0, D_BROKEN 1, D_ISOPEN 2,
                                    D_CLOSED 4, D_LOCKED 8, D_TRAPPED 16); roomno: the room (NO_ROOM 0,
                                    SHARED 1, else ROOMOFFSET 3 + index)
The staircases: `stairway dnstair, upstair` (decl.h), each {xchar sx, sy; ...}; sx 0 = none.
Level x 0 is never used: map column x is the glyph column x - 1, map row y the glyph row y.

Only memory is read -- no game function runs, the RNG is untouched: a game reads the same with or without it.
The handle is closed after each read (NLE refuses to load its library again while one is open).
"""
import _ctypes
import ctypes

import numpy as np

COLNO, ROWNO, RM_SIZE = 80, 21, 8
STONE, SDOOR, SCORR, DOOR, CORR, ROOM, STAIRS = 0, 14, 15, 22, 23, 24, 25
WALLS = range(1, 13)
WALKABLE = frozenset((DOOR, CORR, ROOM, STAIRS) + tuple(range(26, 36)))   # ladder .. cloud


class TrueMap:
    """typ, doormask and roomno of every square ([21, 79], glyph coordinates), the down / up staircase squares."""

    def __init__(self, typ, doormask, roomno, down, up):
        self.typ, self.doormask, self.roomno, self.down, self.up = typ, doormask, roomno, down, up

    def hidden(self):
        return (self.typ == SDOOR) | (self.typ == SCORR)


def read_true_map(env):
    """The current level of the game in `env` (the bot's self.env) as a TrueMap."""
    lib = ctypes.CDLL(env.unwrapped.nethack.dlpath)
    try:
        base = ctypes.addressof(ctypes.c_char.in_dll(lib, "level"))
        raw = np.frombuffer(ctypes.string_at(base, COLNO * ROWNO * RM_SIZE), dtype=np.uint8)
        raw = raw.reshape(COLNO, ROWNO, RM_SIZE).transpose(1, 0, 2)[:, 1:, :]       # [y, x - 1, byte]
        stairs = []
        for name in ("dnstair", "upstair"):
            sx, sy = ctypes.string_at(ctypes.addressof(ctypes.c_char.in_dll(lib, name)), 2)
            stairs.append((sy, sx - 1) if sx else None)
    finally:
        _ctypes.dlclose(lib._handle)
    return TrueMap(raw[:, :, 4].astype(np.int8), raw[:, :, 6] & 0x1F, raw[:, :, 7] & 0x3F, *stairs)
