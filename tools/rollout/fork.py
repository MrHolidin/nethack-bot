"""Fork a live NLE 1.3.0 game so that parent and child can both play on.

os.fork() copies the whole process: the bot, NLE's game coroutine and the game's globals (libnethack.so is loaded
from a private memfd copy, so its data pages are ours). What a fork does NOT copy:

  the game directory   NetHack keeps every level we are not on in a file `<uid><name>.<n>` (lock.c / files.c:
                       fqname(lock, LEVELPREFIX)), plus perm / record / logfile / xlogfile / save/. NLE points all
                       of fqn_prefix[] at `settings.hackdir` (nle.c mainloop), a char[4096] inside the library's
                       global `settings`: the per-instance temporary directory of nle.nethack.Nethack (_vardir).
                       A child that changes level would rewrite the parent's level files, and one that dies deletes
                       them (end.c done -> clearlocks). privatize() copies the directory and writes the copy's
                       path into `settings.hackdir` in place: every fqname() of the child resolves there.
  file descriptions    open files share their offset with the parent. The only one the game holds open is nhdat
                       (dlb.c: one FILE for the whole archive; a special level, a rumor, a quest text is an fseek
                       + fread on it, and dlb skips the fseek when it believes the offset is already right).
                       privatize() reopens every regular file of the process that lives in the game directory or
                       is nhdat, at the same offset, onto the same descriptor number (dup2).
  randomness           the child inherits the RNG state: left alone it replays the parent's future (that is the
                       determinism check). reseed() gives it a fresh future through NLE's own API,
                       Nethack.set_current_seeds -> nle_set_seed (nlernd.c:167): set_random(core, rn2),
                       set_random(disp, rn2_on_display_rng), has_strong_rngseed = False (no reseeding from the
                       clock), and the level generator's seed (lgen), which decides the layout of the levels made
                       from now on.
  the clock            libfaketime's FAKETIME is in the environment: inherited.

A child must leave with os._exit() (never return into the parent's stack frames, never run the parent's cleanup:
nle's TemporaryDirectory finalizer would delete the parent's game directory).
"""
import ctypes
import os
import shutil
import tempfile

HACKDIR_SIZE = 4096                       # nletypes.h nle_settings: char hackdir[4096] is its first member


def nethack_of(bot):
    return bot.env.unwrapped.nethack


def hackdir_buffer(bot):
    """The game's `settings.hackdir` as a ctypes buffer. dlopen of the path NLE loaded the library from returns the
    same handle (same link-map name), so this is the live game's variable, not a second copy."""
    nethack = nethack_of(bot)
    lib = ctypes.CDLL(nethack.dlpath)
    buf = (ctypes.c_char * HACKDIR_SIZE).in_dll(lib, "settings")
    if buf.value != (nethack._vardir + "/").encode():
        raise RuntimeError(f"settings.hackdir is {buf.value!r}, expected {nethack._vardir + '/'!r}")
    return buf


def privatize(bot, root=None):
    """In a forked child, before its first key: its own copy of the game directory and its own file descriptions.
    Returns the new directory (remove it before os._exit)."""
    nethack = nethack_of(bot)
    old = nethack._vardir
    buf = hackdir_buffer(bot)
    new = tempfile.mkdtemp(prefix="nlefork", dir=root)
    shutil.copytree(old, new, symlinks=True, dirs_exist_ok=True)
    buf.value = (new + "/").encode()
    nhdat = os.path.realpath(os.path.join(old, "nhdat"))
    for name in os.listdir("/proc/self/fd"):
        fd = int(name)
        try:
            path = os.readlink(f"/proc/self/fd/{fd}")
        except OSError:
            continue
        if path == nhdat:
            target = path
        elif path.startswith(old + "/"):
            target = new + path[len(old):]
        else:
            continue
        with open(f"/proc/self/fdinfo/{fd}") as fh:
            info = dict(line.split(":", 1) for line in fh.read().splitlines() if ":" in line)
        flags = int(info["flags"].strip(), 8) & ~(os.O_CREAT | os.O_EXCL | os.O_TRUNC)
        nfd = os.open(target, flags)
        os.lseek(nfd, int(info["pos"].strip()), os.SEEK_SET)
        os.dup2(nfd, fd)
        os.close(nfd)
    nethack._vardir = new
    return new


def reseed(bot, core, lgen=None):
    """A fresh future for this process's game: the core and display RNGs from `core`, the level generator from `lgen`
    (default: core)."""
    nethack_of(bot).set_current_seeds(core=core, disp=core, reseed=False, lgen=core if lgen is None else lgen)


def fork_child(bot, child_main, root=None, timeout=600):
    """Fork; in the child: privatize, then child_main(bot) -> bytes, sent to the parent; the child never returns.
    In the parent: wait for the child, return its bytes (b"" if it died without writing; a child that runs past
    `timeout` seconds is killed)."""
    import select
    import signal
    rfd, wfd = os.pipe()
    pid = os.fork()
    if pid == 0:
        code, new = 0, None
        try:
            os.close(rfd)
            new = privatize(bot, root)
            out = child_main(bot)
        except BaseException:                      # noqa: B902 -- the child must never unwind into the parent's frames
            import traceback
            out = ("CRASH " + traceback.format_exc()[-2000:]).encode()
            code = 1
        try:
            while out:
                out = out[os.write(wfd, out):]
            os.close(wfd)
            if new is not None:
                shutil.rmtree(new, ignore_errors=True)
        finally:
            os._exit(code)
    os.close(wfd)
    chunks = []
    try:
        while True:
            ready, _, _ = select.select([rfd], [], [], timeout)
            if not ready:
                os.kill(pid, signal.SIGKILL)
                break
            chunk = os.read(rfd, 1 << 16)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(rfd)
        os.waitpid(pid, 0)
    return b"".join(chunks)
