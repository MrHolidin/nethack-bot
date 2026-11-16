"""Is NLD-NAO (Dungeons and Data, NeurIPS 2022: NAO ttyrecs, NetHack 3.4-3.6.6) still downloadable, and can single games
be read out of its zips without fetching the whole ~200 GB (HTTP range requests: zipfile over a seekable remote file)?
Prints each part's size and, for the first part, the zip's member count and first members. Run in CI."""
import io
import sys
import urllib.error
import urllib.request
import zipfile

BASE = "https://dl.fbaipublicfiles.com/nld/nld-nao/"
UA = {"User-Agent": "nethack-bot-research (replay study)"}


class RemoteFile(io.RawIOBase):
    """Read-only seekable file over HTTP range requests."""
    def __init__(self, url, size):
        self.url, self.size, self.pos = url, size, 0

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
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
        b[:len(data)] = data
        self.pos += len(data)
        return len(data)


def head(url):
    req = urllib.request.Request(url, headers=UA, method="HEAD")
    with urllib.request.urlopen(req, timeout=60) as r:
        return int(r.headers.get("Content-Length", 0)), r.headers.get("Accept-Ranges")


def main():
    names = ["nld-nao_xlogfiles.zip"] + [f"nld-nao-dir-{a}{b}.zip" for a in "ab" for b in "abcdefghijklmnopqrstuvwxyz"]
    first = None
    for n in names:
        try:
            size, ranges = head(BASE + n)
        except urllib.error.HTTPError as e:
            print(f"{n}: HTTP {e.code}", flush=True)
            if n != names[0]:
                break
            continue
        except Exception as e:                       # noqa: BLE001
            print(f"{n}: {e}", flush=True)
            break
        print(f"{n}: {size / 1e9:.2f} GB, Accept-Ranges {ranges}", flush=True)
        if first is None and n != names[0]:
            first = (n, size)
    if first:
        n, size = first
        try:
            z = zipfile.ZipFile(io.BufferedReader(RemoteFile(BASE + n, size), buffer_size=1 << 20))
            infos = z.infolist()
            print(f"{n}: {len(infos)} members; first: {[(i.filename, i.file_size) for i in infos[:15]]}", flush=True)
            print(f"  last: {[(i.filename, i.file_size) for i in infos[-5:]]}", flush=True)
        except Exception as e:                       # noqa: BLE001
            print(f"{n}: zip listing failed: {e!r} (a split archive's part has no central directory of its own)",
                  flush=True)


if __name__ == "__main__":
    sys.exit(main())
