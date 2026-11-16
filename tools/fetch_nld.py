"""Human games out of NLD-NAO (Dungeons and Data, NeurIPS 2022: NAO's ttyrecs up to 2020, NetHack 3.4.3-3.6.6) without
fetching its ~230 GB: the parts are independent zips served with HTTP range requests, so zipfile reads each part's
central directory and then just the members wanted over a seekable remote file. Games: NetHack 3.6.x reaching a depth
over MIN_DEPTH (nld-nao_xlogfiles.zip), newest version first, then the newest; a game's files are its player's
ttyrecs (nld-nao-unzipped/<player>/<start time UTC>.ttyrec.bz2, one per play session) starting within its
starttime..endtime -- as NLD's own loader (nle.dataset add_altorg_directory) matches them. A player may have played
another version at the same time on NAO: check the turn counter across the files against the xlog turns.
Downloads up to N games into OUT/nld_<player>_<starttime>/ with manifest.json. Run in CI.
env: N (default 5), MIN_DEPTH (30), OUT (replays)."""
import io
import datetime
import json
import os
import sys
import urllib.request
import zipfile

BASE = "https://dl.fbaipublicfiles.com/nld/nld-nao/"
PARTS = [f"nld-nao-dir-{a}{b}.zip" for a in "ab" for b in "abcdefghijklmnopqrstuvwxyz"][:40]   # aa..bn
UA = {"User-Agent": "nethack-bot-research (replay study)"}
N = int(os.environ.get("N", 5))
MIN_DEPTH = int(os.environ.get("MIN_DEPTH", 30))
OUT = os.environ.get("OUT", "replays")


class RemoteFile(io.RawIOBase):
    """Read-only seekable file over HTTP range requests."""
    def __init__(self, url):
        self.url, self.pos = url, 0
        req = urllib.request.Request(url, headers=UA, method="HEAD")
        with urllib.request.urlopen(req, timeout=60) as r:
            self.size = int(r.headers["Content-Length"])

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos

    def readinto(self, b):
        if self.pos >= self.size or not len(b):
            return 0
        end = min(self.pos + len(b), self.size) - 1
        req = urllib.request.Request(self.url, headers={**UA, "Range": f"bytes={self.pos}-{end}"})
        with urllib.request.urlopen(req, timeout=300) as r:
            data = r.read()
        b[:len(data)] = data
        self.pos += len(data)
        return len(data)


def remote_zip(name):
    return zipfile.ZipFile(io.BufferedReader(RemoteFile(BASE + name), buffer_size=1 << 22))


def xlog_games():
    z = remote_zip("nld-nao_xlogfiles.zip")
    games, files = [], [i for i in z.infolist() if not i.is_dir()]
    print(f"xlogfiles: {[(i.filename, i.file_size) for i in files]}", flush=True)
    for i in files:
        for line in z.read(i).decode("utf-8", "replace").splitlines():
            r = dict(f.split("=", 1) for f in line.split("\t") if "=" in f)
            if r.get("version", "").startswith("3.6") and int(r.get("maxlvl", 0) or 0) > MIN_DEPTH:
                games.append(r)
    vers = {}
    for r in games:
        vers[r["version"]] = vers.get(r["version"], 0) + 1
    print(f"3.6.x deeper than {MIN_DEPTH}: {len(games)} by version {vers}; ascended "
          f"{sum(r.get('death') == 'ascended' for r in games)}", flush=True)
    games.sort(key=lambda r: (tuple(-int(x) for x in r["version"].split(".")), -int(r["endtime"])))
    return games


def stamp(fname):
    try:
        return datetime.datetime.strptime(fname[:19], "%Y-%m-%d.%H:%M:%S").replace(
            tzinfo=datetime.timezone.utc).timestamp()
    except ValueError:
        return None


def main():
    games = xlog_games()
    want = {r["name"] for r in games}
    where = {}                                       # player -> [(part, member info)]
    for p in PARTS:
        z = remote_zip(p)
        k = 0
        for i in z.infolist():
            bits = i.filename.split("/")
            if len(bits) == 3 and bits[2] and bits[1] in want:
                where.setdefault(bits[1], []).append((p, i))
                k += 1
        print(f"{p}: {len(z.infolist())} members, {k} of the deep games' players", flush=True)
    os.makedirs(OUT, exist_ok=True)
    manifest, zips = [], {}
    for r in games:
        if len(manifest) >= N:
            break
        lo, hi = int(r["starttime"]) - 60, int(r["endtime"])
        mine = sorted(((p, i) for p, i in where.get(r["name"], []) if (s := stamp(i.filename.split("/")[2]))
                       and lo <= s <= hi), key=lambda x: x[1].filename)
        if not mine:
            continue
        gdir = os.path.join(OUT, f"nld_{r['name']}_{r['starttime']}")
        os.makedirs(gdir, exist_ok=True)
        got = []
        for p, i in mine:
            z = zips.setdefault(p, remote_zip(p))
            fn = i.filename.split("/")[2]
            with open(os.path.join(gdir, fn.replace(":", "_")), "wb") as fh:
                fh.write(z.read(i))
            got.append({"file": fn, "part": p, "bytes": i.file_size})
        manifest.append({"src": "nld-nao", "dir": os.path.basename(gdir), "xlog": r, "files": got})
        print(f"  got {r['name']} {r['version']} {r['role']}-{r['race']} maxlvl {r['maxlvl']} turns {r['turns']} "
              f"{r.get('death')}: {len(got)} files, {sum(g['bytes'] for g in got) / 1e6:.1f} MB", flush=True)
    with open(os.path.join(OUT, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=1)
    print(f"{len(manifest)} games in {OUT}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
