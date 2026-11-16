"""Human games from public NetHack servers (run in CI: the servers are not reachable from the dev box).
Reads the servers' xlogfiles, keeps NetHack 3.6.x games that reached a depth over MIN_DEPTH, finds each game's
ttyrec files in the player's directory (one file per play session; a file's name is its start time, UTC: kept if it
starts within the game's starttime..endtime) and downloads up to N games into OUT, with manifest.json (the xlogfile
fields, the files, their URLs). DISCOVER=1 only prints counts and the first directory listings.
Only games that ended before BEFORE (unix time, default 2025-01-01): a player's ttyrec directory mixes every version
he played, and NAO hosts NetHack 5.0 since -- a 3.6 game's window could hold sessions of another version's game.
env: N (default 5), MIN_DEPTH (30), OUT (replays), DISCOVER, BEFORE."""
import datetime
import json
import os
import re
import sys
import urllib.parse
import urllib.request

SOURCES = {
    "nao": ("https://alt.org/nethack/xlogfile.nh363+", "https://alt.org/nethack/userdata/{l}/{name}/ttyrec/"),
    "hdf-us": ("https://www.hardfought.org/xlogfiles/nethack36/xlogfile",
               "https://www.hardfought.org/userdata/{l}/{name}/nethack/ttyrec/"),
    "hdf-eu": ("https://eu.hardfought.org/xlogfiles/nethack36/xlogfile",
               "https://eu.hardfought.org/userdata/{l}/{name}/nethack/ttyrec/"),
    "hdf-au": ("https://au.hardfought.org/xlogfiles/nethack36/xlogfile",
               "https://au.hardfought.org/userdata/{l}/{name}/nethack/ttyrec/"),
}
N = int(os.environ.get("N", 5))
MIN_DEPTH = int(os.environ.get("MIN_DEPTH", 30))
OUT = os.environ.get("OUT", "replays")
DISCOVER = bool(os.environ.get("DISCOVER"))
BEFORE = int(os.environ.get("BEFORE", 1735689600))
# NAO: href="2026-11-12.06%3A22%3A05.645.ttyrec" (url-quoted, milliseconds; older ones .ttyrec.bz2)
TTY_RE = re.compile(r'href="([^"/?]+?\.ttyrec(?:\.bz2|\.gz|\.xz)?)"')
UA = {"User-Agent": "nethack-bot-research (replay study)"}


def get(url, binary=False):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        data = r.read()
    return data if binary else data.decode("utf-8", "replace")


def xlog(text):
    for line in text.splitlines():
        rec = dict(f.split("=", 1) for f in line.split("\t") if "=" in f)
        if rec:
            yield rec


def stamp(name):
    """A ttyrec file's start time from its (unquoted) name; None if it does not start with one."""
    try:
        return datetime.datetime.strptime(name[:19], "%Y-%m-%d.%H:%M:%S").replace(
            tzinfo=datetime.timezone.utc).timestamp()
    except ValueError:
        return None


def main():
    games = []
    for src, (xurl, _) in SOURCES.items():
        try:
            recs = list(xlog(get(xurl)))
        except Exception as e:                       # noqa: BLE001
            print(f"{src}: xlogfile failed: {e}", flush=True)
            continue
        deep = [r for r in recs if r.get("version", "").startswith("3.6") and int(r.get("maxlvl", 0)) > MIN_DEPTH
                and int(r.get("endtime", 0)) < BEFORE]
        vers = {}
        for r in deep:
            vers[r["version"]] = vers.get(r["version"], 0) + 1
        asc = sum(1 for r in deep if r.get("death") == "ascended")
        print(f"{src}: {len(recs)} games; 3.6.x deeper than {MIN_DEPTH}: {len(deep)} by version {vers}; ascended "
              f"{asc}", flush=True)
        games += [(src, r) for r in deep]
    games.sort(key=lambda g: (g[1]["version"] != "3.6.7", g[1]["version"] != "3.6.6", -int(g[1].get("endtime", 0))))
    os.makedirs(OUT, exist_ok=True)
    manifest, listings, shown = [], {}, 0
    for src, r in games:
        if len(manifest) >= N:
            break
        name = r["name"]
        durl = SOURCES[src][1].format(l=name[0], name=name)
        if durl not in listings:
            try:
                listings[durl] = [urllib.parse.unquote(h) for h in TTY_RE.findall(get(durl))]
            except Exception as e:                   # noqa: BLE001
                print(f"  {src} {name}: listing {durl} failed: {e}", flush=True)
                listings[durl] = []
        files = sorted(f for f in set(listings[durl])
                       if stamp(f) is not None and int(r["starttime"]) - 60 <= stamp(f) <= int(r["endtime"]))
        if DISCOVER:
            print(f"  {src} {name} {r['version']} maxlvl {r['maxlvl']} {r.get('death')} start {r['starttime']} end "
                  f"{r['endtime']}: {len(listings[durl])} files in {durl}; in the game's window: {files[:5]}",
                  flush=True)
            if shown < 2 or (src == "nao" and shown < 4):
                for url in (durl, durl.rsplit("/", 2)[0] + "/"):
                    try:
                        page = get(url)
                        print(f"    RAW {url} ({len(page)} chars): {page[:700]!r}", flush=True)
                    except Exception as e:           # noqa: BLE001
                        print(f"    RAW {url} failed: {e}", flush=True)
            shown += 1
            if shown >= 8:
                break
            continue
        if not files:
            continue
        gdir = os.path.join(OUT, f"{src}_{name}_{r['starttime']}")
        os.makedirs(gdir, exist_ok=True)
        got = []
        for f in files:
            url = durl + urllib.parse.quote(f)
            data = get(url, binary=True)
            with open(os.path.join(gdir, f.replace(":", "_")), "wb") as fh:
                fh.write(data)
            got.append({"file": f, "url": url, "bytes": len(data)})
        manifest.append({"src": src, "dir": os.path.basename(gdir), "xlog": r, "files": got})
        print(f"  got {src} {name} {r['version']} {r['role']}-{r['race']} maxlvl {r['maxlvl']} turns {r['turns']} "
              f"{r.get('death')}: {len(got)} files, {sum(g['bytes'] for g in got) / 1e6:.1f} MB", flush=True)
    if not DISCOVER:
        with open(os.path.join(OUT, "manifest.json"), "w") as fh:
            json.dump(manifest, fh, indent=1)
        print(f"{len(manifest)} games in {OUT}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
