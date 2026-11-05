"""Record one game of the bot as a replay, and build the replay viewer around it.

    python tools/replay.py SEED [--kw JSON] [--char val] [--out game.json.gz] [--html game.html]

--out writes the recording (gzipped JSON) for tools/replay_viewer.html to open; --html writes a copy of the viewer
with the recording built in (one file that opens anywhere). The game is the same one eval.py plays for that seed
and options (the recorder only watches: it sends no keys of its own).

A recording holds every frame the terminal showed -- one per key the bot sent -- as the rows that changed since
the frame before (every KEY_EVERY frames all of them, so the viewer can jump anywhere), the colors likewise, the
status line numbers, the key, and what the bot was doing: the policy step that acted on that tick and its own
activity label (fight, explore, rest, ...). Besides the frames: the message log, events worth jumping to (kills,
level changes, zaps, prayers, low HP, the end) and, with wand_ev on, the wand decisions (P(win) of fighting on and
of each zap considered).
"""
import argparse
import base64
import gzip
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import nle.nethack as nh  # noqa: E402

from nhbot import Bot  # noqa: E402
from nhbot.combat import WAND_PWIN  # noqa: E402

KEY_EVERY = 200                  # frames between full screens
VIEWER = os.path.join(ROOT, "tools", "replay_viewer.html")
DATA_MARK = "/*REPLAY_DATA*/null"
LOW_HP = 0.33                    # an event when HP falls below this share of max


def key_name(code):
    if code == 27:
        return "Esc"
    if code == 13:
        return "Enter"
    if code < 32:
        return "^" + chr(code + 64)
    if code == 32:
        return "Space"
    return chr(code) if code < 127 else str(code)


class RecordingBot(Bot):
    OBS_KEYS = Bot.OBS_KEYS + ("tty_colors",)

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.rec_frames, self.rec_events, self.rec_decisions, self.rec_msgs = [], [], [], []
        self._prev_rows, self._prev_cols = None, None
        self._prev_depth, self._low = None, False

    # ------------------------------------------------------------------ frames
    def raw_step(self, code):
        try:
            super().raw_step(code)
        finally:
            self.record_frame(code)

    def record_frame(self, code):
        rows = [bytes(r).decode("latin1") for r in self.obs["tty_chars"]]
        cols = ["".join("%x" % (c & 15) for c in r) for r in self.obs["tty_colors"]]
        n = len(self.rec_frames)
        full = self._prev_rows is None or n % KEY_EVERY == 0
        bl = self.obs["blstats"]
        stats = [int(bl[nh.NLE_BL_HP]), int(bl[nh.NLE_BL_HPMAX]), int(bl[nh.NLE_BL_DEPTH]), int(bl[nh.NLE_BL_XP]),
                 int(bl[nh.NLE_BL_AC]), int(bl[nh.NLE_BL_GOLD]), int(bl[nh.NLE_BL_HUNGER]),
                 int(bl[nh.NLE_BL_CONDITION])]
        t = int(bl[nh.NLE_BL_TIME])
        if t == 0 and self.rec_frames:          # the game is over: the status is gone, keep the last one (HP 0)
            prev = self.rec_frames[-1]
            t, stats = prev["t"], [0] + prev["s"][1:]
        f = {"t": t, "k": key_name(code), "s": stats,
             "r": [[i, r] for i, r in enumerate(rows) if full or r != self._prev_rows[i]],
             "c": [[i, c] for i, c in enumerate(cols) if full or c != self._prev_cols[i]]}
        if full:
            f["f"] = 1
        self.rec_frames.append(f)
        self._prev_rows, self._prev_cols = rows, cols
        hp, hpmax, depth = f["s"][0], f["s"][1], f["s"][2]
        if self._prev_depth is not None and depth != self._prev_depth:
            self.event("level", f"Dungeon level {self._prev_depth} → {depth}")
        self._prev_depth = depth
        low = hpmax > 0 and hp < LOW_HP * hpmax
        if low and not self._low:
            self.event("lowhp", f"HP {hp}/{hpmax}")
        self._low = low

    def event(self, kind, text):
        i = max(0, len(self.rec_frames) - 1)
        self.rec_events.append({"i": i, "t": self.rec_frames[i]["t"] if self.rec_frames else 0,
                                "type": kind, "text": text})

    # ------------------------------------------------------------------ what the bot did
    def tick(self):
        start = len(self.rec_frames)
        try:
            super().tick()
        finally:
            step, act = self.last_step or "", self.cur_act or ""
            for f in self.rec_frames[start:]:
                f["p"], f["a"] = step, act

    def log_msg(self, m):
        m2 = m.strip()
        if m2 and (not self.rec_msgs or self.rec_msgs[-1][2] != m2 or self.rec_msgs[-1][0] != len(self.rec_frames)):
            i = max(0, len(self.rec_frames) - 1)
            self.rec_msgs.append([i, self.rec_frames[i]["t"] if self.rec_frames else 0, m2])
            if re.search(r"\bYou (kill|destroy)\b", m2):
                self.event("kill", m2)
            elif re.search(r"You begin praying|You finish your prayer|You feel that \w+ is", m2):
                self.event("pray", m2)
            elif re.search(r"\bYou die\b|Do you want your possessions", m2):
                self.event("death", m2)
        return super().log_msg(m)

    def zap(self, letter, key):
        it = next((i.text for i in self.items() if i.letter == letter), "?")
        r = super().zap(letter, key)
        self.event("zap", f"zap {it} ({key_name(ord(key)) if isinstance(key, str) else key})")
        return r

    def wand_ev_pairs(self, hostiles, targets, wands):
        got = []
        orig = self.win_prob

        def wp(*a, **k):
            p = orig(*a, **k)
            got.append(p)
            return p
        self.win_prob = wp
        try:
            out = super().wand_ev_pairs(hostiles, targets, wands)
        finally:
            del self.win_prob
        if targets and got:
            labels, seen = [], set()
            for t in targets:
                for letter, kind in wands:
                    if (t[3], letter) not in seen:
                        seen.add((t[3], letter))
                        labels.append(f"{kind} → {t[4]} ({t[1]} sq)")
            opts = [[lab, round(p, 3)] for lab, p in zip(labels, got[1:])]
            chosen = f"{out[0][2]} → {out[0][0][4]}" if out else None
            self.rec_decisions.append({"i": max(0, len(self.rec_frames) - 1), "t": self.turn(),
                                       "threshold": WAND_PWIN, "fight": round(got[0], 3),
                                       "opts": opts, "chosen": chosen,
                                       "line": [[t[4], t[1], bool(self.active_threat(t[2]))] for t in targets]})
        return out


def record(seed, kw, character="val"):
    b = RecordingBot(seed=seed, character=character, verbose=True, **kw)
    s = b.run()
    b.event("end", f"Game over at turn {s['turns']}: score {int(s['score'])}, deepest level {s['max_depth']}")
    return {"v": 1, "seed": seed, "kw": kw, "character": character, "rows": 24, "cols": 80,
            "summary": {"turns": s["turns"], "score": int(s["score"]), "max_depth": s["max_depth"], "xl": s["xl"],
                        "last": [m for _, _, m in b.rec_msgs[-6:]]},
            "frames": b.rec_frames, "events": b.rec_events, "decisions": b.rec_decisions, "msgs": b.rec_msgs}


def build_html(rec_gz=None, standalone=True):
    """The viewer with this recording built in (None: the empty viewer, which opens recordings itself).
    replay_viewer.html is a page body; standalone wraps it in a full HTML document to open as a local file."""
    html = open(VIEWER, encoding="utf-8").read()
    if rec_gz is not None:
        html = html.replace(DATA_MARK, json.dumps(base64.b64encode(rec_gz).decode("ascii")), 1)
    if standalone:
        html = ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width, initial-scale=1"></head>\n<body>\n'
                + html + "\n</body></html>\n")
    return html


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("seed", type=int)
    ap.add_argument("--kw", default="{}", help="Bot options as JSON, e.g. '{\"wand_ev\": true}'")
    ap.add_argument("--char", default="val")
    ap.add_argument("--out", help="recording, .json.gz")
    ap.add_argument("--html", help="viewer with the recording built in")
    a = ap.parse_args()
    rec = record(a.seed, json.loads(a.kw), a.char)
    gz = gzip.compress(json.dumps(rec, separators=(",", ":")).encode("utf-8"))
    if a.out:
        open(a.out, "wb").write(gz)
    if a.html:
        open(a.html, "w", encoding="utf-8").write(build_html(gz))
    print(f"seed {a.seed}: {rec['summary']['turns']} turns, {len(rec['frames'])} frames, {len(gz) // 1024} KB",
          file=sys.stderr)


if __name__ == "__main__":
    main()
