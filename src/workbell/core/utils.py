"""Small helpers shared by core and every client."""

import fcntl
import os
import time
from pathlib import Path
from typing import TextIO

TRAY_LOCK_FILENAME = "tray.lock"  # tray single-instance lock, kept next to the DB; named here so clients agree on it
TIMER_LOCK_FILENAME = "timer.lock"  # timer liveness lock, next to the DB; flock'ed by the timer process for its whole life


def unix_now() -> int:
    """Return the current unix time in whole seconds — the timestamp unit used throughout the data model."""
    return int(time.time())


def format_hms(sec: int) -> str:
    """Format a second count as M:SS, or H:MM:SS from one hour up."""
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def acquire_pid_lock(path: Path, *, blocking: bool = False) -> TextIO | None:
    """Take the exclusive flock on path and record our PID in it; None when another process holds it.

    blocking=True waits for the current holder to exit instead of failing — the timer uses it to
    wait out its predecessor's final poll. The lock lives exactly as long as the returned handle
    stays open: the kernel releases it the moment the holder dies, so unlike a plain PID file it
    can never go stale.
    """
    handle = path.open("a+")  # "a+", not "w": must not truncate the holder's PID before the lock is ours
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


def lock_holder_pid(path: Path) -> int | None:
    """Return the PID of the live process holding the lock, or None when the lock is free.

    Truth comes from the flock probe, not the file content: a leftover file whose writer died
    reads as free, because the kernel dropped the lock with the process.
    """
    try:
        handle = path.open()
    except FileNotFoundError:
        return None
    with handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)  # shared probe: conflicts only with a live holder
        except OSError:
            content = handle.read().strip()
            return int(content) if content.isdigit() else None  # non-digit: holder is mid-write (microsecond window)
        return None  # probe succeeded, so nobody holds the lock; ours is released when the handle closes
